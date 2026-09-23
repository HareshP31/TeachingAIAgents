from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal, TypedDict
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_REVIEW = "awaiting_review"
    COMPLETED = "completed"
    FAILED = "failed"


class RiskFlag(StrEnum):
    VENDOR_LOCK_IN = "vendor_lock_in"
    HIDDEN_CONSUMPTION_COSTS = "hidden_consumption_costs"
    SOLE_SOURCE_JUSTIFICATION = "sole_source_justification"
    BUDGET_THRESHOLD_EXCEEDED = "budget_threshold_exceeded"


class CitationIssue(BaseModel):
    citation: str
    reason: str


class AuditResult(BaseModel):
    is_valid: bool
    risk_flags: list[RiskFlag] = Field(default_factory=list)
    citation_issues: list[CitationIssue] = Field(default_factory=list)


class ResearchFinding(BaseModel):
    title: str
    url: HttpUrl | str
    excerpt: str
    retrieved_at: datetime
    source_mode: Literal["nanobot", "ddgs_fallback", "fake"] = "nanobot"
    fetched_at: datetime | None = None
    content_sha256: str | None = None
    http_status: int | None = None
    snippet_only: bool = False


class ResearchRequest(BaseModel):
    run_id: UUID
    query: str
    prior_findings: list[ResearchFinding] = Field(default_factory=list)
    audit_feedback: AuditResult | None = None
    allowed_domains: list[str] = Field(default_factory=list)


class ResearchResponse(BaseModel):
    findings: list[ResearchFinding]
    summary: str
    live: bool = True


class ReviewDecision(BaseModel):
    approved: bool
    reviewer_id: str
    note: str | None = None


class RiskBreakdown(BaseModel):
    flags: int = 0
    citations: int = 0
    materiality: int = 0
    live_research: int = 0
    total: int = 0
    forced: bool = False


class ConversationState(TypedDict, total=False):
    run_id: str
    thread_id: str
    channel_id: str
    requester_id: str
    question: str
    route: Literal["research", "analyst"]
    route_reason: str
    research_findings: list[dict[str, Any]]
    retrieved_chunks: list[dict[str, Any]]
    draft: str
    audit: dict[str, Any]
    risk_breakdown: dict[str, Any]
    needs_review: bool
    revision_count: int
    review: dict[str, Any] | None
    final_answer: str
    error: str | None
