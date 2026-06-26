"""HawkSoft MCP server.

Exposes HawkSoft Insurance Agency Management (Partner API v3.0) as MCP tools so
Claude / Cursor / any MCP client can read client & policy data and write log
notes, attachments, and receipts.

Quick start:
    pip install -e .
    export HAWKSOFT_USERNAME=...
    export HAWKSOFT_PASSWORD=...
    hawksoft-mcp
"""
from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from typing import Any

from mcp.server.fastmcp import FastMCP

from .client import HawkSoftAPIError, HawkSoftAuthError, HawkSoftClient, HawkSoftError
from .log_actions import list_channels, resolve_channel
from .models import (
    AttachmentInput,
    BulkClientsInput,
    ChangedClientsInput,
    GetClientInput,
    LogNoteInput,
    ReceiptsInput,
    SearchByPolicyInput,
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _ensure_ref_id(value: str | None) -> str:
    return value or str(uuid.uuid4())


def _ensure_ts(value: str | None) -> str:
    return value or _utc_now_iso()


def _format_error(e: Exception) -> str:
    if isinstance(e, HawkSoftAuthError):
        return (
            "Authentication failed against HawkSoft. Verify HAWKSOFT_USERNAME "
            f"and HAWKSOFT_PASSWORD. Details: {e}"
        )
    if isinstance(e, HawkSoftAPIError):
        return f"HawkSoft API error (HTTP {e.status_code}): {e}"
    if isinstance(e, HawkSoftError):
        return f"HawkSoft error: {e}"
    return f"Unexpected error: {e!r}"


def _json(data: Any) -> str:
    """Stable, agent-friendly JSON."""
    return json.dumps(data, indent=2, default=str, ensure_ascii=False)


# ----- MCP server setup ------------------------------------------------------

mcp = FastMCP(
    "hawksoft",
    instructions=(
        "Tools for interacting with the HawkSoft Insurance Agency Management "
        "system via its Partner API v3.0. Use these to query clients, policies, "
        "claims, and invoices for any agency that has subscribed to your vendor "
        "app, and to write log notes, attachments, and receipts back to HawkSoft. "
        "All write operations require a refId for idempotency; one is generated "
        "automatically if you don't supply one."
    ),
)


def _client() -> HawkSoftClient:
    return HawkSoftClient()


# ----- Read tools ------------------------------------------------------------


@mcp.tool()
async def list_agencies() -> str:
    """List agency IDs that have subscribed to your HawkSoft vendor app.

    Returns an array of integer agency IDs. Each represents an independent
    insurance agency that has opted in to data sharing with your app via the
    HawkSoft License Management Portal.
    """
    try:
        result = await _client().list_agencies()
        return _json({"agency_ids": result, "count": len(result)})
    except HawkSoftError as e:
        return _format_error(e)


@mcp.tool()
async def list_offices(agency_id: int) -> str:
    """List offices configured under an agency.

    Args:
        agency_id: HawkSoft agency ID (from list_agencies).
    """
    try:
        result = await _client().list_offices(agency_id)
        return _json({"agency_id": agency_id, "offices": result, "count": len(result)})
    except HawkSoftError as e:
        return _format_error(e)


@mcp.tool()
async def list_changed_clients(
    agency_id: int,
    as_of: str | None = None,
    office_id: int | None = None,
    include_deleted: bool = False,
) -> str:
    """List client IDs that changed since a given timestamp.

    The workhorse for syncing. Pass an ``as_of`` ISO 8601 timestamp to get only
    clients modified after that point; omit it to get all clients. Then use
    ``get_client`` or ``get_clients_bulk`` on each ID.

    Args:
        agency_id: HawkSoft agency ID.
        as_of: ISO 8601 timestamp (e.g. ``2026-06-01T00:00:00Z``). Omit for full list.
        office_id: Restrict to a specific office.
        include_deleted: Include soft-deleted clients.
    """
    # Pydantic validation
    ChangedClientsInput(
        agency_id=agency_id,
        as_of=as_of,
        office_id=office_id,
        include_deleted=include_deleted,
    )
    try:
        result = await _client().get_changed_clients(
            agency_id,
            as_of=as_of,
            office_id=office_id,
            deleted=include_deleted or None,
        )
        return _json({
            "agency_id": agency_id,
            "as_of": as_of,
            "client_ids": result,
            "count": len(result),
        })
    except HawkSoftError as e:
        return _format_error(e)


@mcp.tool()
async def get_client(
    agency_id: int,
    client_id: int,
    include: list[str] | None = None,
) -> str:
    """Fetch full details for a single client.

    Returns the full client object — details, people, contacts, claims, policies
    by default. Use ``include`` to narrow the response and save bandwidth.

    Args:
        agency_id: HawkSoft agency ID.
        client_id: HawkSoft client number.
        include: Sections to include: details, people, contacts, claims, policies, invoices.
    """
    GetClientInput(agency_id=agency_id, client_id=client_id, include=include)
    try:
        result = await _client().get_client(agency_id, client_id, include=include)
        return _json(result)
    except HawkSoftError as e:
        return _format_error(e)


@mcp.tool()
async def get_clients_bulk(agency_id: int, client_numbers: list[int]) -> str:
    """Fetch multiple clients in one call (up to 200 per request).

    Args:
        agency_id: HawkSoft agency ID.
        client_numbers: List of client numbers (1–200 per call).
    """
    BulkClientsInput(agency_id=agency_id, client_numbers=client_numbers)
    try:
        result = await _client().get_clients_bulk(agency_id, client_numbers)
        return _json({"agency_id": agency_id, "clients": result, "count": len(result)})
    except HawkSoftError as e:
        return _format_error(e)


@mcp.tool()
async def search_client_by_policy(
    agency_id: int,
    policy_number: str,
    include: list[str] | None = None,
) -> str:
    """Find a client by exact policy number match.

    Useful when an agent has a policy number from a carrier but not the
    HawkSoft client number. Returns all clients (usually 1) holding that
    policy. Exact match only — no partial or fuzzy search.

    Args:
        agency_id: HawkSoft agency ID.
        policy_number: Exact policy number.
        include: Sections to include.
    """
    SearchByPolicyInput(
        agency_id=agency_id, policy_number=policy_number, include=include
    )
    try:
        result = await _client().search_client_by_policy(
            agency_id, policy_number, include=include
        )
        return _json({
            "agency_id": agency_id,
            "policy_number": policy_number,
            "clients": result,
            "count": len(result),
        })
    except HawkSoftError as e:
        return _format_error(e)


# ----- Write tools -----------------------------------------------------------


@mcp.tool()
async def create_log_note(
    agency_id: int,
    client_id: int,
    channel: str,
    description: str,
    body: str,
    ref_id: str | None = None,
    ts: str | None = None,
    policy_id: str | None = None,
    policy_index: int | None = None,
    action: int | None = None,
    task_title: str | None = None,
    task_description: str | None = None,
    task_due_date: str | None = None,
    task_assigned_to_role: str | None = None,
    task_assigned_to_email: str | None = None,
    task_category: str | None = None,
) -> str:
    """Append a log note (and optional follow-up task) to a client's record.

    The single most useful write tool — call this whenever the agent does
    anything that should be visible in HawkSoft: a phone call, an email, a
    conversation summary, a carrier touch.

    Args:
        agency_id: HawkSoft agency ID.
        client_id: HawkSoft client number.
        channel: Friendly channel name (e.g. ``"Phone From Insured"``) or LogAction int.
        description: One-sentence summary shown in the activity feed.
        body: Full note text. May be multi-line.
        ref_id: Unique UUID for idempotency. Auto-generated if omitted.
        ts: ISO 8601 timestamp. Defaults to now (UTC).
        policy_id: Optional policy GUID to link the note to.
        policy_index: Optional 1-based index on the policy.
        action: Optional action code.
        task_title: Set to create a follow-up task.
        task_description: Task description.
        task_due_date: ISO 8601 due date.
        task_assigned_to_role: One of SpecifiedUser, Producer, CSR, Agent1, Agent2, Agent3.
        task_assigned_to_email: Required when assigned_to_role is SpecifiedUser.
        task_category: Optional category label.
    """
    try:
        channel_int = resolve_channel(channel)
    except ValueError as e:
        return _format_error(e)
    task = None
    if task_title and task_due_date and task_assigned_to_role:
        task = {
            "title": task_title,
            "description": task_description or "",
            "dueDate": task_due_date,
            "assignedToRole": task_assigned_to_role,
        }
        if task_assigned_to_email:
            task["assignedToEmail"] = task_assigned_to_email
        if task_category:
            task["category"] = task_category
    try:
        result = await _client().create_log_note(
            agency_id,
            client_id,
            ref_id=_ensure_ref_id(ref_id),
            ts=_ensure_ts(ts),
            channel=channel_int,
            description=description,
            body=body,
            policy_id=policy_id,
            policy_index=policy_index,
            action=action,
            task=task,
        )
        return _json({"status": "ok", "response": result})
    except HawkSoftError as e:
        return _format_error(e)


@mcp.tool()
async def create_attachment(
    agency_id: int,
    client_id: int,
    channel: str,
    desc: str,
    log_note: str,
    file_name: str,
    file_b64: str,
    policy_id: str | None = None,
    ref_id: str | None = None,
    ts: str | None = None,
    task_title: str | None = None,
    task_description: str | None = None,
    task_due_date: str | None = None,
    task_assigned_to_role: str | None = None,
    task_assigned_to_email: str | None = None,
    task_category: str | None = None,
) -> str:
    """Attach a base64-encoded file (PDF, image, doc) to a client record.

    Args:
        agency_id: HawkSoft agency ID.
        client_id: HawkSoft client number.
        channel: Channel name or LogAction int (use list_channels for the catalog).
        desc: One-line description of the file.
        log_note: Log note text tied to this attachment.
        file_name: File name including extension, e.g. ``"declaration_page.pdf"``.
        file_b64: Base64-encoded file contents — NO ``data:`` URL prefix.
        policy_id: Optional policy GUID to link to.
        ref_id: Idempotency UUID (auto-generated if omitted).
        ts: ISO 8601 timestamp (defaults to now).
        task_title, task_description, task_due_date, task_assigned_to_role,
        task_assigned_to_email, task_category: Optional follow-up task.
    """
    try:
        channel_int = resolve_channel(channel)
    except ValueError as e:
        return _format_error(e)
    try:
        result = await _client().create_attachment(
            agency_id,
            client_id,
            ref_id=_ensure_ref_id(ref_id),
            ts=_ensure_ts(ts),
            channel=channel_int,
            desc=desc,
            log_note=log_note,
            file_name=file_name,
            file_ext=file_name.rsplit(".", 1)[-1] if "." in file_name else "",
            file_b64=file_b64,
            policy_id=policy_id,
            task_title=task_title,
            task_description=task_description,
            task_due_date=task_due_date,
            task_assigned_to_role=task_assigned_to_role,
            task_assigned_to_email=task_assigned_to_email,
            task_category=task_category,
        )
        return _json({"status": "ok", "response": result})
    except HawkSoftError as e:
        return _format_error(e)


@mcp.tool()
async def create_receipts(
    agency_id: int,
    client_id: int,
    receipts: list[dict[str, Any]],
) -> str:
    """Record one or more payments received by a client.

    Each receipt applies to one or more invoices. A log note is automatically
    created and linked. Optionally create a follow-up task.

    Args:
        agency_id: HawkSoft agency ID.
        client_id: HawkSoft client number.
        receipts: List of receipts. Each item must include:
            - ``channel``: channel name or int
            - ``logNote``: text of the log note
            - ``total``: total amount received
            - ``invoices``: list of ``{"invoiceId": "<guid>", "amount": <float>}``
        Optional per receipt: refId, ts, policyId, officeId, payMethod, task.
    """
    ReceiptsInput(agency_id=agency_id, client_id=client_id, receipts=receipts)
    # Resolve channel names in each receipt before sending
    resolved = []
    for receipt in receipts:
        r = dict(receipt)
        try:
            r["channel"] = resolve_channel(r["channel"])
        except ValueError as e:
            return _format_error(e)
        r.setdefault("refId", _ensure_ref_id(r.get("refId")))
        r.setdefault("ts", _ensure_ts(r.get("ts")))
        resolved.append(r)
    try:
        result = await _client().create_receipts(agency_id, client_id, resolved)
        return _json({"status": "ok", "results": result})
    except HawkSoftError as e:
        return _format_error(e)


# ----- Resources / utilities -------------------------------------------------


@mcp.resource("hawksoft://channels")
def channels_resource() -> str:
    """All HawkSoft LogAction channel codes — useful reference for the agent.

    Each entry has the integer value, the friendly label, and the channel
    category (Phone / Mail / Email / etc).
    """
    return _json(list_channels())


@mcp.tool()
async def list_channels_tool() -> str:
    """Return all 56 HawkSoft channel codes with friendly names and categories.

    Use this to discover the right ``channel`` value to pass into create_log_note,
    create_attachment, or create_receipts.
    """
    return _json(list_channels())


def main() -> None:
    """Run the MCP server over stdio."""
    try:
        mcp.run()
    except HawkSoftAuthError as e:
        print(f"[hawksoft-mcp] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()