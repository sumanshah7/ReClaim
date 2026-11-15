"""Pydantic schemas shared by ingest, triage, agent, API and UI."""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, Field


class Platform(str, Enum):
    DOORDASH = "doordash"
    UBEREATS = "ubereats"
    GRUBHUB = "grubhub"


class ClaimReason(str, Enum):
    MISSING_ITEM = "missing_item"
    WRONG_ITEM = "wrong_item"
    OTHER = "other"


class Deduction(BaseModel):
    id: str
    platform: Platform
    order_id: str
    order_ts: datetime
    pickup_ts: datetime | None = None
    amount_cents: int = Field(gt=0, description="Positive amount deducted from the restaurant")
    reason: ClaimReason
    claimed_item: str | None = None
    customer_key: str  # hashed, never the raw name (rule 10)
    payout_date: date
    source_row: int


class Ticket(BaseModel):
    order_id: str
    items: list[str]
    placed_ts: datetime | None = None
    ready_ts: datetime | None = None
    image_path: str | None = None
    extraction_confidence: float = Field(ge=0, le=1, default=1.0)


class EvidenceKind(str, Enum):
    TICKET_LISTS_ITEM = "ticket_lists_item"
    TICKET_OMITS_ITEM = "ticket_omits_item"
    PICKUP_HANDOFF = "pickup_handoff"
    REPEAT_CLAIMANT = "repeat_claimant"
    MISSING_ARTIFACT = "missing_artifact"


class Evidence(BaseModel):
    id: str
    kind: EvidenceKind
    summary: str
    source_ref: str = Field(min_length=1, description="file path, timestamp or row id (rule 2)")
    supports: int = Field(ge=-1, le=1)
    strength: float = Field(ge=0, le=1, default=0.5)


class ConfidenceReason(BaseModel):
    text: str
    delta: int  # basis points applied to p_win


class CaseStatus(str, Enum):
    TRIAGED = "triaged"
    INVESTIGATING = "investigating"
    DRAFTED = "drafted"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    SENT = "sent"
    SKIPPED = "skipped"


class Case(BaseModel):
    id: str
    deduction: Deduction
    evidence: list[Evidence] = []
    p_win_bp: int = Field(ge=0, le=10000)
    confidence: int = Field(ge=0, le=100)
    reasons: list[ConfidenceReason] = Field(min_length=1)
    recoverable_cents: int
    expected_cents: int
    deadline: date
    days_left: int
    status: CaseStatus = CaseStatus.TRIAGED
    weak: bool = False
    recommend_skip: bool = False
    skip_reason: str | None = None


class Dispute(BaseModel):
    case_id: str
    body: str
    cited_evidence_ids: list[str]
    lint_passed: bool = False


class OutcomeResult(str, Enum):
    WON = "won"
    LOST = "lost"
    PENDING = "pending"


class Outcome(BaseModel):
    case_id: str
    result: OutcomeResult
    recovered_cents: int = 0
    reason_pattern: str  # e.g. "doordash:missing_item"
    signature: str = ""  # evidence pattern, e.g. "ticket_lists_item+1|pickup_handoff+1"
    claimed_item: str | None = None
    lesson: str | None = None  # one-line takeaway, also appended to the agent's AGENTS.md memory


class AgentEventType(str, Enum):
    PLAN = "plan"
    TODO_UPDATE = "todo_update"
    TOOL_CALL = "tool_call"
    SUBAGENT = "subagent"
    REPLAN = "replan"
    INTERRUPT = "interrupt"
    DONE = "done"
    ERROR = "error"


class AgentEvent(BaseModel):
    ts: datetime
    type: AgentEventType
    payload: dict
