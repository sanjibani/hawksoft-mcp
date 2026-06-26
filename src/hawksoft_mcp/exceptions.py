"""HawkSoft exceptions — typed hierarchy with structured context.

Pattern: stripe-python / boto3 — every error carries structured fields
(http_status, error_code, request_id) so callers can branch on cause, not
just message text. The base class is never raised directly.
"""
from __future__ import annotations

from typing import Any


class HawkSoftError(Exception):
    """Base exception for all HawkSoft client errors.

    Subclasses set a default ``http_status`` and may add their own structured
    fields. Never raise this directly — raise the most specific subclass.
    """

    http_status: int | None = None

    def __init__(
        self,
        message: str,
        *,
        http_status: int | None = None,
        error_code: str | None = None,
        request_id: str | None = None,
        body: Any = None,
    ) -> None:
        super().__init__(message)
        self.http_status = http_status if http_status is not None else self.http_status
        self.error_code = error_code
        self.request_id = request_id
        self.body = body

    def __repr__(self) -> str:
        parts = [f"http_status={self.http_status!r}"]
        if self.error_code:
            parts.append(f"error_code={self.error_code!r}")
        if self.request_id:
            parts.append(f"request_id={self.request_id!r}")
        return f"{type(self).__name__}({', '.join(parts)})"


class HawkSoftAuthError(HawkSoftError):
    """401 (bad credentials) or 403 (agency hasn't subscribed to vendor app)."""

    http_status = 401


class HawkSoftNotFoundError(HawkSoftError):
    """404 — client/agency/resource doesn't exist or you don't have access."""

    http_status = 404


class HawkSoftRateLimitError(HawkSoftError):
    """429 — rate limit hit. Includes ``retry_after`` if the server sent one."""

    http_status = 429

    def __init__(
        self,
        message: str,
        *,
        retry_after: float | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, **kwargs)
        self.retry_after = retry_after


class HawkSoftAPIError(HawkSoftError):
    """5xx or other non-2xx response that wasn't caught by a more specific
    exception. Caller may retry after a backoff."""

    http_status = 500


class HawkSoftConnectionError(HawkSoftError):
    """Network-level failure (DNS, TCP, TLS). Distinct from HTTP errors so
    callers can retry transient connectivity issues."""

    http_status = None
