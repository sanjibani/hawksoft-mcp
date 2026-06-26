"""Smoke tests for HawkSoft MCP — no live API calls required.

Run with: ``pytest`` from the project root, or ``python -m pytest tests/``.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from hawksoft_mcp.client import HawkSoftAPIError, HawkSoftAuthError, HawkSoftClient
from hawksoft_mcp.log_actions import list_channels, resolve_channel
from hawksoft_mcp.server import _format_error, _json, _utc_now_iso, _ensure_ref_id, _ensure_ts


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
    with pytest.raises(ValueError):
        resolve_channel("not a real channel")


def test_resolve_channel_int_out_of_range() -> None:
    with pytest.raises(ValueError):
        resolve_channel(999)


def test_list_channels_count() -> None:
    channels = list_channels()
    assert len(channels) == 56
    assert all({"value", "label", "category"} <= c.keys() for c in channels)


# --- Client construction ----------------------------------------------------


def test_client_missing_credentials_raises() -> None:
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(HawkSoftAuthError):
            HawkSoftClient()


def test_client_uses_env_when_no_args(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HAWKSOFT_USERNAME", "u")
    monkeypatch.setenv("HAWKSOFT_PASSWORD", "p")
    client = HawkSoftClient()
    assert client._basic_auth  # populated from env


# --- Async request mock -----------------------------------------------------


@pytest.mark.asyncio
async def test_list_agencies_calls_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HAWKSOFT_USERNAME", "u")
    monkeypatch.setenv("HAWKSOFT_PASSWORD", "p")

    fake_response = AsyncMock()
    fake_response.status_code = 200
    fake_response.text = "[1, 2, 3]"
    fake_response.json = lambda: [1, 2, 3]

    fake_http = AsyncMock()
    fake_http.__aenter__ = AsyncMock(return_value=fake_http)
    fake_http.__aexit__ = AsyncMock(return_value=None)
    fake_http.request = AsyncMock(return_value=fake_response)

    with patch("hawksoft_mcp.client.httpx.AsyncClient", return_value=fake_http):
        client = HawkSoftClient()
        result = await client.list_agencies()
        assert result == [1, 2, 3]
        # Verify URL + version param
        args, kwargs = fake_http.request.call_args
        assert args[0] == "GET"
        assert args[1].endswith("/vendor/agencies")
        assert kwargs["params"]["version"] == "3.0"
        assert kwargs["headers"]["Authorization"].startswith("Basic ")


@pytest.mark.asyncio
async def test_401_raises_auth_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HAWKSOFT_USERNAME", "u")
    monkeypatch.setenv("HAWKSOFT_PASSWORD", "p")
    fake_response = AsyncMock()
    fake_response.status_code = 401
    fake_response.text = ""
    fake_http = AsyncMock()
    fake_http.__aenter__ = AsyncMock(return_value=fake_http)
    fake_http.__aexit__ = AsyncMock(return_value=None)
    fake_http.request = AsyncMock(return_value=fake_response)
    with patch("hawksoft_mcp.client.httpx.AsyncClient", return_value=fake_http):
        client = HawkSoftClient()
        with pytest.raises(HawkSoftAuthError):
            await client.list_agencies()


@pytest.mark.asyncio
async def test_500_raises_api_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HAWKSOFT_USERNAME", "u")
    monkeypatch.setenv("HAWKSOFT_PASSWORD", "p")
    fake_response = AsyncMock()
    fake_response.status_code = 500
    fake_response.text = "kaboom"
    fake_response.json = lambda: (_ for _ in ()).throw(ValueError("not json"))
    fake_http = AsyncMock()
    fake_http.__aenter__ = AsyncMock(return_value=fake_http)
    fake_http.__aexit__ = AsyncMock(return_value=None)
    fake_http.request = AsyncMock(return_value=fake_response)
    with patch("hawksoft_mcp.client.httpx.AsyncClient", return_value=fake_http):
        client = HawkSoftClient()
        with pytest.raises(HawkSoftAPIError):
            await client.list_agencies()


# --- Helpers ----------------------------------------------------------------


def test_utc_now_iso_format() -> None:
    ts = _utc_now_iso()
    # ISO 8601 with milliseconds, Z suffix
    assert ts.endswith("Z")
    assert "T" in ts


def test_ensure_ref_id_generates_when_missing() -> None:
    rid = _ensure_ref_id(None)
    # UUID4 string format check
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
    msg = _format_error(HawkSoftAuthError("nope", 401))
    assert "Authentication failed" in msg


def test_format_error_generic() -> None:
    msg = _format_error(ValueError("nope"))
    assert "Unexpected error" in msg


def test_json_serializes() -> None:
    out = _json({"a": 1, "b": [1, 2]})
    parsed = json.loads(out)
    assert parsed == {"a": 1, "b": [1, 2]}