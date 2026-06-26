"""Unit tests for the audit module (JSONL audit logger)."""
from __future__ import annotations

import io
import json
import os
from contextlib import redirect_stderr

import pytest

from hawksoft_mcp.audit import _sanitize_args, audit_tool_call


def test_sanitize_args_redacts_password() -> None:
    sanitized = _sanitize_args({"username": "alice", "password": "hunter2"})
    assert sanitized["username"] == "alice"
    assert sanitized["password"] == "***REDACTED***"


def test_sanitize_args_redacts_nested_secrets() -> None:
    sanitized = _sanitize_args(
        {"client": {"api_key": "abc123", "name": "acme"}, "token": "xyz"}
    )
    assert sanitized["client"]["api_key"] == "***REDACTED***"
    assert sanitized["client"]["name"] == "acme"
    assert sanitized["token"] == "***REDACTED***"


def test_sanitize_args_truncates_long_strings() -> None:
    long = "x" * 1000
    sanitized = _sanitize_args({"body": long})
    assert len(sanitized["body"]) == 256  # 253 + "..."


def test_audit_tool_call_writes_jsonl_to_stderr() -> None:
    """Default sink is stderr; one JSON object per line."""
    buf = io.StringIO()
    with redirect_stderr(buf), audit_tool_call("test_tool", {"query": "foo"}) as _:
        _.set_result("hello")
    line = buf.getvalue().strip()
    assert line.endswith("}")
    record = json.loads(line)
    assert record["tool"] == "test_tool"
    assert record["args"] == {"query": "foo"}
    assert record["result_size"] == 5  # len("hello")
    assert record["is_error"] is False
    assert record["error_type"] is None
    assert isinstance(record["duration_ms"], int)
    assert isinstance(record["request_id"], str)
    assert "ts" in record


def test_audit_tool_call_records_error() -> None:
    """Tool errors are captured with is_error=True and exception class name."""
    buf = io.StringIO()
    with (
        redirect_stderr(buf),
        pytest.raises(RuntimeError),
        audit_tool_call("failing_tool", {"x": 1}) as _,
    ):
        raise RuntimeError("boom")
    record = json.loads(buf.getvalue().strip())
    assert record["tool"] == "failing_tool"
    assert record["is_error"] is True
    assert record["error_type"] == "RuntimeError"


def test_audit_tool_call_writes_to_file_when_env_set(tmp_path) -> None:
    """HAWKSOFT_MCP_AUDIT_LOG overrides default sink to a file path."""
    log_file = tmp_path / "audit.jsonl"
    os.environ["HAWKSOFT_MCP_AUDIT_LOG"] = str(log_file)
    try:
        with audit_tool_call("file_tool", {"k": "v"}) as _:
            _.set_result("ok")
    finally:
        os.environ.pop("HAWKSOFT_MCP_AUDIT_LOG", None)
    line = log_file.read_text().strip()
    record = json.loads(line)
    assert record["tool"] == "file_tool"
    assert record["result_size"] == 2


def test_audit_tool_call_never_breaks_tool_on_sink_failure() -> None:
    """If writing to the sink fails, the tool still returns its result."""
    # Point the env var to a path under a non-existent directory
    os.environ["HAWKSOFT_MCP_AUDIT_LOG"] = "/nonexistent/dir/audit.jsonl"
    try:
        with audit_tool_call("x", {}) as _:
            _.set_result("ok")
            result = "tool returned this"
        assert result == "tool returned this"
    finally:
        os.environ.pop("HAWKSOFT_MCP_AUDIT_LOG", None)
