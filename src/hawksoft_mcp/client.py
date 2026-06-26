"""HawkSoft Insurance Agency Management — async HTTP client.

Implements the HawkSoft Partner API v3.0. Authentication is HTTP Basic with
vendor credentials issued through the HawkSoft License Management Portal.

Docs: https://partner.hawksoft.app/v3/api.html
"""
from __future__ import annotations

import base64
import os
from typing import Any

import httpx


DEFAULT_BASE_URL = "https://integration.hawksoft.app"
DEFAULT_API_VERSION = "3.0"
DEFAULT_TIMEOUT = 30.0


class HawkSoftError(RuntimeError):
    """Base exception for HawkSoft client errors."""

    def __init__(self, message: str, status_code: int | None = None, body: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class HawkSoftAuthError(HawkSoftError):
    """Raised when credentials are missing, invalid, or unauthorized."""


class HawkSoftAPIError(HawkSoftError):
    """Raised on non-2xx API responses other than auth failures."""


class HawkSoftClient:
    """Async client for the HawkSoft Partner API v3.0.

    Args:
        username: HawkSoft vendor username (the value passed to `-u` in cURL).
        password: HawkSoft vendor password.
        base_url: Override the API base URL (mostly for testing).
        timeout: Request timeout in seconds.

    Either pass credentials explicitly OR set ``HAWKSOFT_USERNAME`` and
    ``HAWKSOFT_PASSWORD`` in the environment. The MCP server reads these from
    its own env on startup; tests can construct the client directly.
    """

    def __init__(
        self,
        username: str | None = None,
        password: str | None = None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        username = username or os.environ.get("HAWKSOFT_USERNAME")
        password = password or os.environ.get("HAWKSOFT_PASSWORD")
        if not username or not password:
            raise HawkSoftAuthError(
                "HawkSoft credentials missing. Set HAWKSOFT_USERNAME and HAWKSOFT_PASSWORD "
                "environment variables, or pass them to the client constructor."
            )
        self._basic_auth = base64.b64encode(f"{username}:{password}".encode()).decode()
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Basic {self._basic_auth}",
            "Accept": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        url = f"{self._base_url}{path}"
        # Versioning is required for v3.0
        params = dict(params or {})
        params.setdefault("version", DEFAULT_API_VERSION)

        async with httpx.AsyncClient(timeout=self._timeout) as http:
            response = await http.request(
                method,
                url,
                params=params,
                json=json,
                headers=self._headers(),
            )

        if response.status_code == 401:
            raise HawkSoftAuthError("HawkSoft rejected the credentials (HTTP 401).", 401)
        if response.status_code == 403:
            raise HawkSoftAuthError(
                "HawkSoft denied access to this resource (HTTP 403). "
                "The agency may not have subscribed to your vendor app.",
                403,
            )
        # Raise on other non-2xx
        if not 200 <= response.status_code < 300:
            body: Any
            try:
                body = response.json()
            except ValueError:
                body = response.text
            raise HawkSoftAPIError(
                f"HawkSoft returned HTTP {response.status_code}",
                status_code=response.status_code,
                body=body,
            )

        # Empty body case — HawkSoft returns plain text for 200/202/etc.
        text = response.text
        if not text:
            return None
        try:
            return response.json()
        except ValueError:
            return text

    # ----- Read endpoints ----------------------------------------------------

    async def list_agencies(self) -> list[int]:
        """List agency IDs that have subscribed to this vendor.

        GET /vendor/agencies
        """
        return await self._request("GET", "/vendor/agencies")

    async def list_offices(self, agency_id: int) -> list[dict[str, Any]]:
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
    ) -> list[int]:
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
    ) -> dict[str, Any]:
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
    ) -> list[dict[str, Any]]:
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
    ) -> list[dict[str, Any]]:
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
    ) -> str:
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
    ) -> str:
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
    ) -> list[dict[str, Any]]:
        """Record one or more payments received by a client.

        POST /vendor/agency/{agencyId}/client/{clientId}/receipts
        """
        return await self._request(
            "POST",
            f"/vendor/agency/{agency_id}/client/{client_id}/receipts",
            json=receipts,
        )