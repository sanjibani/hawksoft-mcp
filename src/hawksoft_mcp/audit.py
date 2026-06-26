"""JSONL audit logger for MCP tool calls.

Writes one structured record per tool call to a configurable sink (stderr by
default for stdio transport, or a file path via env var). Each record has:

    ts                  ISO-8601 UTC timestamp with millisecond precision
    tool                tool name (matches @mcp.tool name)
    args                sanitized input args (password/secret fields redacted)
    result_size         byte length of result string
    is_error            True if the tool raised (wire isError=True)
    error_type          exception class name if is_error
    duration_ms         wall-clock duration of the tool call
    request_id          unique ID for the call (UUID4)

Wire format: one JSON object per line. Suitable for ingestion by any log
aggregator (Loki, Elasticsearch, Datadog) or for replay via `jq`.

Usage:

    from .audit import audit_tool_call

    @mcp.tool()
    async def my_tool(query: str) -> str:
        with audit_tool_call("my_tool", {"query": query}) as audit:
            ... do work ...
            audit.set_result(result_str)
            return result_str

The audit sink defaults to stderr. Override via env var:

    HAWKSOFT_MCP_AUDIT_LOG=/var/log/hawksoft-mcp/audit.jsonl

This module is intentionally dependency-free (stdlib only) so it works in
every MCP without adding to pyproject.toml dependencies.
"""
from __future__ import annotations

import contextlib
import json
import os
import sys
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Fields whose values are stripped before logging the `args` record.
# Add more as needed (PII, PHI, secrets).
_REDACT_KEYS: frozenset[str] = frozenset(
    {
        "password",
        "api_key",
        "apikey",
        "secret",
        "token",
        "access_token",
        "refresh_token",
        "authorization",
        "x-api-key",
        "client_secret",
    }
)
_REDACTED = "***REDACTED***"
_MAX_STRING = 256


def _sanitize_args(args: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of args with sensitive fields redacted."""
    out: dict[str, Any] = {}
    for k, v in args.items():
        if k.lower() in _REDACT_KEYS:
            out[k] = _REDACTED
        elif isinstance(v, dict):
            out[k] = _sanitize_args(v)
        elif isinstance(v, str) and len(v) > _MAX_STRING:
            # Truncate long string values to keep audit line compact.
            out[k] = v[: _MAX_STRING - 3] + "..."
        else:
            out[k] = v
    return out


def _resolve_sink() -> Any:
    """Return the writable sink. Env var override wins; else stderr.

    Failure to open the configured file (e.g. missing directory) returns
    stderr as a safe fallback so audit logging never breaks the tool call.
    """
    path = os.environ.get("HAWKSOFT_MCP_AUDIT_LOG")
    if path:
        try:
            # Open in append mode; line-buffered for tail -f compatibility.
            return Path(path).open("a", buffering=1, encoding="utf-8")
        except OSError:
            return sys.stderr
    return sys.stderr


class _AuditRecord:
    """Mutable record built up over the lifetime of a tool call."""

    __slots__ = (
        "_error_type",
        "_is_error",
        "_result_size",
        "_start",
        "args",
        "request_id",
        "tool",
    )

    def __init__(self, tool: str, args: dict[str, Any]) -> None:
        self.tool = tool
        self.args = _sanitize_args(args)
        self.request_id = str(uuid.uuid4())
        self._start = time.monotonic()
        self._result_size: int | None = None
        self._is_error = False
        self._error_type: str | None = None

    def set_result(self, result: str) -> None:
        self._result_size = len(result.encode("utf-8"))

    def set_error(self, exc: BaseException) -> None:
        self._is_error = True
        self._error_type = type(exc).__name__

    def to_jsonl(self) -> str:
        duration_ms = int((time.monotonic() - self._start) * 1000)
        record = {
            "ts": _utc_now_iso(),
            "tool": self.tool,
            "request_id": self.request_id,
            "args": self.args,
            "result_size": self._result_size,
            "is_error": self._is_error,
            "error_type": self._error_type,
            "duration_ms": duration_ms,
        }
        return json.dumps(record, ensure_ascii=False, separators=(",", ":"))


def _utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


@contextmanager
def audit_tool_call(tool: str, args: dict[str, Any]) -> Iterator[_AuditRecord]:
    """Context manager that emits one JSONL audit record per tool call.

    Writes to stderr by default; set HAWKSOFT_MCP_AUDIT_LOG to a file path
    to redirect.
    """
    record = _AuditRecord(tool, args)
    sink = _resolve_sink()
    try:
        yield record
    except BaseException as exc:
        record.set_error(exc)
        with contextlib.suppress(Exception):
            # Audit logging must never break the tool itself.
            print(record.to_jsonl(), file=sink, flush=True)
        raise
    else:
        with contextlib.suppress(Exception):
            print(record.to_jsonl(), file=sink, flush=True)


__all__ = ["audit_tool_call"]

