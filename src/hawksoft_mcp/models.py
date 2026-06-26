"""Pydantic models for HawkSoft MCP tool inputs.

These exist mainly to give agents clear, typed schemas via the MCP ``inputSchema``.
HawkSoft's own responses are loose JSON, so we don't model the full Client schema
here — see https://partner.hawksoft.app/v3/model.html for the source of truth.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

TaskRole = Literal["SpecifiedUser", "Producer", "CSR", "Agent1", "Agent2", "Agent3"]
IncludeSection = Literal["details", "people", "contacts", "claims", "policies", "invoices"]


class ChangedClientsInput(BaseModel):
    agency_id: int = Field(..., description="HawkSoft agency ID. Get it from list_agencies.")
    as_of: str | None = Field(
        None,
        description=(
            "ISO 8601 timestamp. Omit to list all clients ever. Use this to do "
            "incremental syncs — fetch only clients modified since the last poll."
        ),
    )
    office_id: int | None = Field(None, description="Restrict to a specific office.")
    include_deleted: bool = Field(
        False,
        description="If true, include soft-deleted clients in the result.",
    )


class GetClientInput(BaseModel):
    agency_id: int = Field(..., description="HawkSoft agency ID.")
    client_id: int = Field(..., description="HawkSoft client number.")
    include: list[IncludeSection] | None = Field(
        None,
        description=(
            "Sections to include in the response: details, people, contacts, "
            "claims, policies, invoices. Omit to use HawkSoft defaults."
        ),
    )


class BulkClientsInput(BaseModel):
    agency_id: int = Field(..., description="HawkSoft agency ID.")
    client_numbers: list[int] = Field(
        ..., description="List of client numbers to fetch.", min_length=1, max_length=200
    )


class SearchByPolicyInput(BaseModel):
    agency_id: int = Field(..., description="HawkSoft agency ID.")
    policy_number: str = Field(
        ..., description="Exact policy number match (no partial / fuzzy)."
    )
    include: list[IncludeSection] | None = Field(None, description="Sections to include.")


class TaskInput(BaseModel):
    title: str = Field(..., description="Short task title.")
    description: str = Field(..., description="Long description / context.")
    due_date: str = Field(..., description="ISO 8601 due date.")
    assigned_to_role: TaskRole = Field(
        ...,
        description='Role to assign the task to. Use "SpecifiedUser" with assigned_to_email.',
    )
    assigned_to_email: str | None = Field(
        None,
        description="Required when assigned_to_role is 'SpecifiedUser'.",
    )
    category: str | None = Field(None, description="Optional task category label.")


class LogNoteInput(BaseModel):
    agency_id: int
    client_id: int
    channel: str | int = Field(
        ...,
        description=(
            'Interaction channel. Either a friendly name like "Phone To Insured", '
            '"Email From Carrier" or the LogAction integer. Use list_channels to see all.'
        ),
    )
    description: str = Field(
        ..., description="Short summary of the interaction (1 sentence)."
    )
    body: str = Field(..., description="Detailed log body / notes.")
    ref_id: str | None = Field(
        None,
        description="Unique UUID for idempotency. Auto-generated if omitted.",
    )
    ts: str | None = Field(
        None,
        description="ISO 8601 timestamp of the interaction. Defaults to now (UTC).",
    )
    policy_id: str | None = Field(None, description="Optional policy GUID to link to.")
    policy_index: int | None = Field(
        None, description="Optional 1-based line index on the policy."
    )
    action: int | None = Field(None, description="Optional action code on the policy.")
    task: TaskInput | None = Field(
        None, description="Optional follow-up task to create alongside the log note."
    )


class AttachmentInput(BaseModel):
    agency_id: int
    client_id: int
    channel: str | int = Field(..., description="See list_channels.")
    desc: str = Field(..., description="One-line description of the attachment.")
    log_note: str = Field(..., description="Log note to create with the attachment.")
    file_name: str = Field(..., description="File name including extension.")
    file_b64: str = Field(
        ..., description="Base64-encoded file contents (no data: URL prefix)."
    )
    policy_id: str | None = Field(None, description="Optional policy GUID to link to.")
    task: TaskInput | None = Field(
        None, description="Optional follow-up task."
    )


class ReceiptInvoiceInput(BaseModel):
    invoice_id: str = Field(..., description="HawkSoft invoice GUID.")
    amount: float = Field(..., description="Amount to apply to this invoice.")


class ReceiptInput(BaseModel):
    channel: str | int = Field(..., description="Source channel of the payment.")
    log_note: str = Field(..., description="Log note text tied to this payment.")
    total: float = Field(..., description="Total amount received.", gt=0)
    invoices: list[ReceiptInvoiceInput] = Field(
        ..., description="Invoices this payment should be applied to.", min_length=1
    )
    ref_id: str | None = Field(None, description="Unique UUID for idempotency.")
    ts: str | None = Field(None, description="ISO 8601 timestamp. Defaults to now.")
    policy_id: str | None = Field(None, description="Optional policy GUID.")
    office_id: int | None = Field(None, description="Optional office ID.")
    pay_method: str | None = Field(
        None,
        description="Payment method label. Defaults to 'Other' if omitted.",
    )
    task: TaskInput | None = Field(None, description="Optional follow-up task.")


class ReceiptsInput(BaseModel):
    agency_id: int
    client_id: int
    receipts: list[ReceiptInput] = Field(
        ..., description="One or more receipts to record.", min_length=1
    )
