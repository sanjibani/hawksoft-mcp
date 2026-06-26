"""Smoke tests for HawkSoft MCP — no live API calls required.

Built with ``respx`` (industry-standard httpx mocking) + ``pytest-asyncio``.
The pattern: each async test sets up respx routes that intercept the actual
``httpx.AsyncClient``, then calls client methods and asserts on the request
shape (URL, headers, params) and the parsed response.
"""
from __future__ import annotations

import base64
import json
import os
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import respx
from hypothesis import given, settings
from hypothesis import strategies as st

from hawksoft_mcp import (
    HawkSoftAPIError,
    HawkSoftAuthError,
    HawkSoftClient,
    HawkSoftConnectionError,
    HawkSoftNotFoundError,
    HawkSoftRateLimitError,
)
from hawksoft_mcp.log_actions import list_channels, resolve_channel
from hawksoft_mcp.server import (
    _ensure_ref_id,
    _ensure_ts,
    _format_error,
    _json,
    _utc_now_iso,
)

# --- Log actions ------------------------------------------------------------


def test_resolve_channel_int_passthrough() -> None:
    assert resolve_channel(5) == 5
    assert resolve_channel(56) == 56


def test_resolve_channel_name_case_insensitive() -> None:
    assert resolve_channel("Phone To Insured") == 1
    assert resolve_channel("PHONE TO INSURED") == 1
    assert resolve_channel("phone to insured") == 1
    assert resolve_channel("Email From Carrier") == 38


def test_resolve_channel_invalid_raises() -> None:
    with pytest.raises(ValueError, match="Unknown channel name"):
        resolve_channel("not a real channel")


def test_resolve_channel_int_out_of_range() -> None:
    with pytest.raises(ValueError, match="Valid range"):
        resolve_channel(999)


def test_list_channels_count() -> None:
    channels = list_channels()
    assert len(channels) == 56
    assert all({"value", "label", "category"} <= c.keys() for c in channels)


# --- Fixtures ---------------------------------------------------------------


def _env(monkeypatch: pytest.MonkeyPatch, user: str = "u", password: str = "p") -> None:
    monkeypatch.setenv("HAWKSOFT_USERNAME", user)
    monkeypatch.setenv("HAWKSOFT_PASSWORD", password)


@pytest.fixture
async def client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[HawkSoftClient]:
    _env(monkeypatch)
    c = HawkSoftClient()
    try:
        yield c
    finally:
        await c.aclose()


# --- Client construction ---------------------------------------------------


def test_client_missing_credentials_raises() -> None:
    os.environ.pop("HAWKSOFT_USERNAME", None)
    os.environ.pop("HAWKSOFT_PASSWORD", None)
    with pytest.raises(HawkSoftAuthError):
        HawkSoftClient()


def test_client_uses_env_when_no_args(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(monkeypatch)
    client = HawkSoftClient()
    expected = base64.b64encode(b"u:p").decode()
    assert client._basic_auth == expected


@pytest.mark.asyncio
async def test_client_aclose_closes_underlying_httpx_client(
    client: HawkSoftClient,
) -> None:
    assert not client._client.is_closed
    await client.aclose()
    assert client._client.is_closed


# --- Request shape ---------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_list_agencies_calls_endpoint_with_version(
    client: HawkSoftClient,
) -> None:
    route = respx.get("https://integration.hawksoft.app/vendor/agencies").mock(
        return_value=httpx.Response(200, json=[1, 2, 3])
    )
    result = await client.list_agencies()
    assert result == [1, 2, 3]
    # Version param auto-added
    assert route.calls[0].request.url.params["version"] == "3.0"
    # Basic auth header present
    auth = route.calls[0].request.headers["Authorization"]
    assert auth.startswith("Basic ")


# --- HTTP status code mapping ---------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_401_raises_auth_error(client: HawkSoftClient) -> None:
    respx.get("https://integration.hawksoft.app/vendor/agencies").mock(
        return_value=httpx.Response(401, text="")
    )
    with pytest.raises(HawkSoftAuthError) as exc_info:
        await client.list_agencies()
    assert exc_info.value.http_status == 401


@pytest.mark.asyncio
@respx.mock
async def test_403_raises_auth_error(client: HawkSoftClient) -> None:
    respx.get("https://integration.hawksoft.app/vendor/agencies").mock(
        return_value=httpx.Response(403, text="")
    )
    with pytest.raises(HawkSoftAuthError) as exc_info:
        await client.list_agencies()
    assert exc_info.value.http_status == 403
    assert "subscribed" in str(exc_info.value).lower()


@pytest.mark.asyncio
@respx.mock
async def test_404_raises_not_found(client: HawkSoftClient) -> None:
    respx.get("https://integration.hawksoft.app/vendor/agency/1/client/999").mock(
        return_value=httpx.Response(404, json={"message": "no such client"})
    )
    with pytest.raises(HawkSoftNotFoundError):
        await client.get_client(1, 999)


@pytest.mark.asyncio
@respx.mock
async def test_429_includes_retry_after(client: HawkSoftClient) -> None:
    respx.get("https://integration.hawksoft.app/vendor/agencies").mock(
        return_value=httpx.Response(429, headers={"retry-after": "2.5"}, text="slow")
    )
    with pytest.raises(HawkSoftRateLimitError) as exc_info:
        await client.list_agencies()
    assert exc_info.value.retry_after == 2.5


@pytest.mark.asyncio
@respx.mock
async def test_500_captures_request_id(client: HawkSoftClient) -> None:
    respx.get("https://integration.hawksoft.app/vendor/agencies").mock(
        return_value=httpx.Response(500, headers={"x-request-id": "req-abc"}, text="boom")
    )
    with pytest.raises(HawkSoftAPIError) as exc_info:
        await client.list_agencies()
    assert exc_info.value.request_id == "req-abc"


@pytest.mark.asyncio
@respx.mock
async def test_connection_error_wrapped(client: HawkSoftClient) -> None:
    respx.get("https://integration.hawksoft.app/vendor/agencies").mock(
        side_effect=httpx.ConnectError("DNS failure")
    )
    with pytest.raises(HawkSoftConnectionError):
        await client.list_agencies()


# --- Retry with exponential backoff ---------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_429_is_retried_then_raises(client: HawkSoftClient) -> None:
    route = respx.get("https://integration.hawksoft.app/vendor/agencies").mock(
        return_value=httpx.Response(429, text="slow")
    )
    client._max_retries = 2
    with pytest.raises(HawkSoftRateLimitError):
        await client.list_agencies()
    assert route.call_count == 3  # initial + 2 retries


@pytest.mark.asyncio
@respx.mock
async def test_5xx_eventually_succeeds_after_retry(client: HawkSoftClient) -> None:
    route = respx.get("https://integration.hawksoft.app/vendor/agencies").mock(
        side_effect=[
            httpx.Response(502, text="bad gateway"),
            httpx.Response(503, text="unavailable"),
            httpx.Response(200, json=[42]),
        ]
    )
    client._max_retries = 3
    result = await client.list_agencies()
    assert result == [42]
    assert route.call_count == 3


# --- POST / write endpoints ------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_create_receipts_uses_post(client: HawkSoftClient) -> None:
    route = respx.post(
        "https://integration.hawksoft.app/vendor/agency/1/client/2/receipts"
    ).mock(return_value=httpx.Response(200, json=[{"receiptId": 99}]))
    result = await client.create_receipts(
        1, 2, [{"amount": 100.0, "date": "2026-01-01"}]
    )
    assert result == [{"receiptId": 99}]
    assert route.calls[0].request.method == "POST"
    body = json.loads(route.calls[0].request.content)
    assert body == [{"amount": 100.0, "date": "2026-01-01"}]


# --- Helpers ----------------------------------------------------------------


def test_utc_now_iso_format() -> None:
    ts = _utc_now_iso()
    assert ts.endswith("Z")
    assert "T" in ts


def test_ensure_ref_id_generates_when_missing() -> None:
    rid = _ensure_ref_id(None)
    assert len(rid) == 36
    assert rid.count("-") == 4


def test_ensure_ref_id_passes_through() -> None:
    assert _ensure_ref_id("abc") == "abc"


def test_ensure_ts_generates_when_missing() -> None:
    ts = _ensure_ts(None)
    assert ts.endswith("Z")


def test_ensure_ts_passes_through() -> None:
    assert _ensure_ts("2026-01-01T00:00:00Z") == "2026-01-01T00:00:00Z"


def test_format_error_auth() -> None:
    msg = _format_error(HawkSoftAuthError("nope"))
    assert "Authentication failed" in msg
    assert "HAWKSOFT_USERNAME" in msg


def test_format_error_404_says_not_found() -> None:
    msg = _format_error(HawkSoftNotFoundError("missing"))
    assert "not found" in msg.lower()


def test_format_error_429_includes_retry_after() -> None:
    msg = _format_error(HawkSoftRateLimitError("slow", retry_after=5.0))
    assert "Retry in 5.0s" in msg or "Retry in 5s" in msg


def test_format_error_connection_says_network() -> None:
    msg = _format_error(HawkSoftConnectionError("dns"))
    assert "network" in msg.lower()


def test_format_error_500_includes_request_id() -> None:
    err = HawkSoftAPIError("boom", request_id="req-xyz")
    msg = _format_error(err)
    assert "req-xyz" in msg


def test_format_error_generic() -> None:
    msg = _format_error(ValueError("nope"))
    assert "Unexpected" in msg


def test_json_serializes() -> None:
    out = _json({"a": 1, "b": [1, 2]})
    parsed = json.loads(out)
    assert parsed == {"a": 1, "b": [1, 2]}


def test_error_repr_includes_structured_fields() -> None:
    err = HawkSoftAPIError("boom", http_status=500, error_code="oops", request_id="req-1")
    r = repr(err)
    assert "http_status=500" in r
    assert "error_code='oops'" in r
    assert "request_id='req-1'" in r


# --- Property-based test ---------------------------------------------------


@given(st.dictionaries(st.text(min_size=1), st.integers() | st.text() | st.booleans(), max_size=10))
@settings(max_examples=50, deadline=None)
def test_json_serialization_round_trip(d: dict[str, Any]) -> None:
    try:
        json.loads(_json(d))
    except (TypeError, ValueError):
        pytest.skip("non-JSON value")
    assert json.loads(_json(d)) == d
