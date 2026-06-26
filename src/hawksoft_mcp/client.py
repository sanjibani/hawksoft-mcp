"""HawkSoft Insurance Agency Management — async HTTP client.

Implements the HawkSoft Partner API v3.0. Authentication is HTTP Basic with
vendor credentials issued through the HawkSoft License Management Portal.

Built on industry-leading patterns (encode/httpx, stripe-python):
- **Shared ``httpx.AsyncClient``** with connection pooling + transport retries.
- **Typed exception hierarchy** with structured fields. See ``exceptions.py``.
- **Application-level retry** with exponential backoff + full jitter on
  transient failures, honoring ``Retry-After``.

Docs: https://partner.hawksoft.app/v3/api.html
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import os
import random
import time
from typing import Any

import httpx
import structlog

from . import __version__
from .exceptions import (
    HawkSoftAPIError,
    HawkSoftAuthError,
    HawkSoftConnectionError,
    HawkSoftError,
    HawkSoftNotFoundError,
    HawkSoftRateLimitError,
)

log = structlog.get_logger(__name__)


# --- Configuration constants -----------------------------------------------

DEFAULT_BASE_URL = "https://integration.hawksoft.app"
DEFAULT_API_VERSION = "3.0"
DEFAULT_TIMEOUT = 30.0

# Connection pool sizing — httpx best practice
DEFAULT_MAX_CONNECTIONS = 100
DEFAULT_MAX_KEEPALIVE_CONNECTIONS = 20
DEFAULT_KEEPALIVE_EXPIRY = 30.0

# Application-level retry (orthogonal to transport-level retries)
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_RETRY_DELAY = 0.5
DEFAULT_MAX_RETRY_DELAY = 30.0

RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


# --- Internal helpers ------------------------------------------------------


def _retry_delay(attempt: int, retry_after: float | None = None) -> float:
    """Exponential backoff with full jitter, clamped to [0.5, 30] seconds."""
    if retry_after is not None:
        return min(float(retry_after), DEFAULT_MAX_RETRY_DELAY)
    delay = min(DEFAULT_BASE_RETRY_DELAY * (2 ** attempt), DEFAULT_MAX_RETRY_DELAY)
    return float(delay * random.uniform(0.5, 1.0))  # full jitter


class HawkSoftClient:
    """Async client for the HawkSoft Partner API v3.0.

    Authentication: HTTP Basic with vendor credentials issued by the HawkSoft
    License Management Portal.

    Either pass credentials explicitly OR set ``HAWKSOFT_USERNAME`` and
    ``HAWKSOFT_PASSWORD`` in the environment.

    Use as an async context manager to ensure the underlying httpx client's
    connection pool is cleanly closed:

        async with HawkSoftClient() as client:
            await client.list_agencies()
    """

    def __init__(
        self,
        username: str | None = None,
        password: str | None = None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        username = username or os.environ.get("HAWKSOFT_USERNAME")
        password = password or os.environ.get("HAWKSOFT_PASSWORD")
        if not (username and password):
            raise HawkSoftAuthError(
                "HawkSoft credentials missing. Set HAWKSOFT_USERNAME and "
                "HAWKSOFT_PASSWORD environment variables, or pass them to the "
                "client constructor."
            )
        assert username is not None
        assert password is not None
        self._basic_auth = base64.b64encode(f"{username}:{password}".encode()).decode()
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_retries = max_retries

        # Build shared httpx.AsyncClient with pooling + transport retries.
        transport = httpx.AsyncHTTPTransport(retries=3)
        limits = httpx.Limits(
            max_connections=DEFAULT_MAX_CONNECTIONS,
            max_keepalive_connections=DEFAULT_MAX_KEEPALIVE_CONNECTIONS,
            keepalive_expiry=DEFAULT_KEEPALIVE_EXPIRY,
        )
        timeout_obj = httpx.Timeout(
            timeout,
            connect=10.0,
            read=timeout,
            write=10.0,
            pool=5.0,
        )
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout_obj,
            limits=limits,
            transport=transport,
            headers={
                "Authorization": f"Basic {self._basic_auth}",
                "Accept": "application/json",
                "User-Agent": f"hawksoft-mcp/{__version__}",
            },
            follow_redirects=False,
        )

    # --- Context manager ------------------------------------------------------

    async def __aenter__(self) -> HawkSoftClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Flush keepalive connections and release the httpx client."""
        await self._client.aclose()

    # --- Request execution ----------------------------------------------------

    def _raise_for_status(self, response: httpx.Response) -> None:
        """Map a non-2xx response to the most specific typed exception."""
        request_id = (
            response.headers.get("x-request-id")
            or response.headers.get("x-amzn-requestid")
            or response.headers.get("request-id")
        )
        try:
            data = response.json()
        except ValueError:
            data = response.text

        if response.status_code == 401:
            raise HawkSoftAuthError(
                "HawkSoft rejected the credentials (HTTP 401).",
                http_status=401,
                request_id=request_id,
                body=data,
            )
        if response.status_code == 403:
            raise HawkSoftAuthError(
                "HawkSoft denied access to this resource (HTTP 403). "
                "The agency may not have subscribed to your vendor app.",
                http_status=403,
                request_id=request_id,
                body=data,
            )
        if response.status_code == 404:
            raise HawkSoftNotFoundError(
                f"HawkSoft resource not found: {response.url}",
                http_status=404,
                request_id=request_id,
                body=data,
            )
        if response.status_code == 429:
            retry_after: float | None = None
            with contextlib.suppress(ValueError):
                ra_header = response.headers.get("retry-after")
                if ra_header:
                    retry_after = float(ra_header)
            raise HawkSoftRateLimitError(
                "HawkSoft rate limit hit (HTTP 429). Slow down.",
                retry_after=retry_after,
                request_id=request_id,
                body=data,
            )
        if 500 <= response.status_code < 600:
            raise HawkSoftAPIError(
                f"HawkSoft server error (HTTP {response.status_code})",
                http_status=response.status_code,
                request_id=request_id,
                body=data,
            )
        raise HawkSoftAPIError(
            f"HawkSoft returned HTTP {response.status_code}",
            http_status=response.status_code,
            request_id=request_id,
            body=data,
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        """Issue an authenticated request with retry on transient errors."""
        # Versioning is required for v3.0
        full_params: dict[str, Any] = dict(params or {})
        full_params.setdefault("version", DEFAULT_API_VERSION)

        last_exc: HawkSoftError | None = None
        for attempt in range(self._max_retries + 1):
            log.info("request.start", method=method, path=path, attempt=attempt)
            t0 = time.monotonic()
            try:
                response = await self._client.request(
                    method, path, params=full_params, json=json
                )
            except httpx.HTTPError as exc:
                duration_ms = (time.monotonic() - t0) * 1000
                log.warning(
                    "request.connection_error",
                    method=method,
                    path=path,
                    error=str(exc),
                    duration_ms=round(duration_ms, 1),
                )
                if attempt < self._max_retries:
                    await asyncio.sleep(_retry_delay(attempt))
                    continue
                raise HawkSoftConnectionError(
                    f"Network failure calling HawkSoft {method} {path}: {exc}",
                ) from exc

            duration_ms = (time.monotonic() - t0) * 1000
            log.info(
                "request.end",
                method=method,
                path=path,
                status=response.status_code,
                duration_ms=round(duration_ms, 1),
            )

            if response.status_code in RETRYABLE_STATUS_CODES and attempt < self._max_retries:
                retry_after: float | None = None
                with contextlib.suppress(ValueError):
                    ra_header = response.headers.get("retry-after")
                    if ra_header:
                        retry_after = float(ra_header)
                delay = _retry_delay(attempt, retry_after)
                log.warning(
                    "request.retry",
                    method=method,
                    path=path,
                    status=response.status_code,
                    attempt=attempt,
                    delay=round(delay, 2),
                )
                await asyncio.sleep(delay)
                continue

            if 200 <= response.status_code < 300:
                # Empty body case — HawkSoft returns plain text for 200/202/etc.
                text = response.text
                if not text:
                    return None
                try:
                    return response.json()
                except ValueError:
                    return text

            try:
                self._raise_for_status(response)
            except HawkSoftRateLimitError as exc:
                last_exc = exc
                if attempt < self._max_retries:
                    delay = _retry_delay(attempt, exc.retry_after)
                    log.warning("request.retry_after_429", delay=round(delay, 2))
                    await asyncio.sleep(delay)
                    continue
                raise
            except (HawkSoftAPIError, HawkSoftAuthError, HawkSoftNotFoundError):
                raise
            except HawkSoftError as exc:
                last_exc = exc
                if attempt < self._max_retries:
                    await asyncio.sleep(_retry_delay(attempt))
                    continue
                raise

        assert last_exc is not None
        raise last_exc

    # ----- Read endpoints ----------------------------------------------------

    async def list_agencies(self) -> Any:
        """List agency IDs that have subscribed to this vendor.

        GET /vendor/agencies
        """
        return await self._request("GET", "/vendor/agencies")

    async def list_offices(self, agency_id: int) -> Any:
        """List offices defined for an agency.

        GET /vendor/agency/{agencyId}/offices
        """
        return await self._request("GET", f"/vendor/agency/{agency_id}/offices")

    async def get_changed_clients(
        self,
        agency_id: int,
        *,
        as_of: str | None = None,
        office_id: int | None = None,
        deleted: bool | None = None,
    ) -> Any:
        """List client IDs that have changed since ``as_of``.

        GET /vendor/agency/{agencyId}/clients?asOf=...&officeId=...&deleted=...

        Args:
            as_of: ISO 8601 timestamp. Omit to get all clients.
            office_id: Restrict to a specific office.
            deleted: True to include deleted clients, False to exclude.
        """
        params: dict[str, Any] = {}
        if as_of is not None:
            params["asOf"] = as_of
        if office_id is not None:
            params["officeId"] = office_id
        if deleted is not None:
            params["deleted"] = str(deleted).lower()
        return await self._request(
            "GET", f"/vendor/agency/{agency_id}/clients", params=params
        )

    async def get_client(
        self,
        agency_id: int,
        client_id: int,
        *,
        include: list[str] | None = None,
    ) -> Any:
        """Fetch a single client.

        GET /vendor/agency/{agencyId}/client/{clientId}

        Args:
            include: Optional list of sections to include (e.g.
                ["details", "policies", "people", "claims"]). See HawkSoft docs
                for the full set.
        """
        params: dict[str, Any] = {}
        if include:
            params["include"] = ",".join(include)
        return await self._request(
            "GET", f"/vendor/agency/{agency_id}/client/{client_id}", params=params
        )

    async def get_clients_bulk(
        self,
        agency_id: int,
        client_numbers: list[int],
    ) -> Any:
        """Fetch multiple clients by client number.

        POST /vendor/agency/{agencyId}/clients with ``{"clientNumbers": [...]}``.
        """
        return await self._request(
            "POST",
            f"/vendor/agency/{agency_id}/clients",
            json={"clientNumbers": client_numbers},
        )

    async def search_client_by_policy(
        self,
        agency_id: int,
        policy_number: str,
        *,
        include: list[str] | None = None,
    ) -> Any:
        """Search clients by exact policy number match.

        GET /vendor/agency/{agencyId}/clients/search?policyNumber=...
        """
        params: dict[str, Any] = {"policyNumber": policy_number}
        if include:
            params["include"] = ",".join(include)
        return await self._request(
            "GET", f"/vendor/agency/{agency_id}/clients/search", params=params
        )

    # ----- Write endpoints ---------------------------------------------------

    async def create_log_note(
        self,
        agency_id: int,
        client_id: int,
        *,
        ref_id: str,
        ts: str,
        channel: int,
        description: str,
        body: str,
        policy_id: str | None = None,
        policy_index: int | None = None,
        action: int | None = None,
        task: dict[str, Any] | None = None,
    ) -> Any:
        """Append a log note (and optional follow-up task) to a client's record.

        POST /vendor/agency/{agencyId}/client/{clientId}/log
        """
        payload: dict[str, Any] = {
            "refId": ref_id,
            "ts": ts,
            "channel": channel,
            "description": description,
            "body": body,
        }
        if policy_id is not None:
            payload["policyId"] = policy_id
        if policy_index is not None:
            payload["policyIndex"] = policy_index
        if action is not None:
            payload["action"] = action
        if task is not None:
            payload["task"] = task
        return await self._request(
            "POST", f"/vendor/agency/{agency_id}/client/{client_id}/log", json=payload
        )

    async def create_attachment(
        self,
        agency_id: int,
        client_id: int,
        *,
        ref_id: str,
        ts: str,
        channel: int,
        desc: str,
        log_note: str,
        file_name: str,
        file_ext: str,
        file_b64: str,
        policy_id: str | None = None,
        task_title: str | None = None,
        task_description: str | None = None,
        task_due_date: str | None = None,
        task_assigned_to_role: str | None = None,
        task_assigned_to_email: str | None = None,
        task_category: str | None = None,
    ) -> Any:
        """Attach a base64-encoded file to a client record.

        POST /vendor/agency/{agencyId}/client/{clientId}/attachment
        """
        payload: dict[str, Any] = {
            "refId": ref_id,
            "ts": ts,
            "channel": channel,
            "desc": desc,
            "logNote": log_note,
            "fileName": file_name,
            "fileExt": file_ext,
            "data": file_b64,
        }
        if policy_id is not None:
            payload["policyId"] = policy_id
        if task_title is not None:
            payload["taskTitle"] = task_title
        if task_description is not None:
            payload["taskDescription"] = task_description
        if task_due_date is not None:
            payload["taskDueDate"] = task_due_date
        if task_assigned_to_role is not None:
            payload["taskAssignedToRole"] = task_assigned_to_role
        if task_assigned_to_email is not None:
            payload["taskAssignedToEmail"] = task_assigned_to_email
        if task_category is not None:
            payload["taskCategory"] = task_category
        return await self._request(
            "POST",
            f"/vendor/agency/{agency_id}/client/{client_id}/attachment",
            json=payload,
        )

    async def create_receipts(
        self,
        agency_id: int,
        client_id: int,
        receipts: list[dict[str, Any]],
    ) -> Any:
        """Record one or more payments received by a client.

        POST /vendor/agency/{agencyId}/client/{clientId}/receipts
        """
        return await self._request(
            "POST",
            f"/vendor/agency/{agency_id}/client/{client_id}/receipts",
            json=receipts,
        )
