from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class SessionStatus(StrEnum):
    ANALYZING = "ANALYZING"
    AWAITING_SUPPLEMENT_CHOICE = "AWAITING_SUPPLEMENT_CHOICE"
    AWAITING_USER_INPUT = "AWAITING_USER_INPUT"
    SUPPLEMENT_SKIPPED = "SUPPLEMENT_SKIPPED"
    AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"
    RETRIEVING_RULES = "RETRIEVING_RULES"
    SCORING = "SCORING"
    REPORTING = "REPORTING"
    COMPLETE = "COMPLETE"
    LLM_UNAVAILABLE = "LLM_UNAVAILABLE"


class EvidenceRef(BaseModel):
    chunk_id: str
    parent_id: str
    heading_path: list[str]
    text: str
    rule_domains: list[str] = Field(default_factory=list)
    decision_authority: list[str] = Field(default_factory=list)
    source_file: str
    knowledge_base_hash: str
    retrieval_score: float = 0.0


class RoundAssessment(BaseModel):
    round: int = Field(ge=1)
    winner: Literal["red", "blue", "even", "insufficient"]
    dominance: Literal["close", "clear", "overwhelming"] = "close"
    knockdowns: dict[str, Any] = Field(
        default_factory=lambda: {"red": None, "blue": None, "source": "unknown"}
    )
    deductions: dict[str, Any] = Field(
        default_factory=lambda: {"red": None, "blue": None, "source": "unknown"}
    )
    reason: str
    evidence_refs: list[str] = Field(default_factory=list)
    data_sources: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "low"


class ScoreRow(BaseModel):
    round: int
    red_base: int | None
    blue_base: int | None
    red_deduction: int | None
    blue_deduction: int | None
    red_adjusted: int | None
    blue_adjusted: int | None


class SupplementRecord(BaseModel):
    revision: int
    scope: str = "bout"
    round: int | None = None
    fighter: Literal["red", "blue"] | None = None
    metric: str
    value: Any = None
    value_range: list[float] | None = None
    source_type: Literal[
        "user_asserted_fact",
        "user_estimate",
        "verified_official_ruling",
        "agent_assumption",
        "dataset_annotation",
    ]
    confidence: Literal["high", "medium", "low"] = "medium"
    raw_user_text: str
    confirmed: bool = False


class ProgressEvent(BaseModel):
    sequence: int = Field(ge=1)
    phase: str
    status: Literal["running", "completed", "failed", "skipped"]
    tool: str
    title: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class AgentSession(BaseModel):
    session_id: str
    analysis_id: str | None = None
    status: SessionStatus
    csv_path: str
    csv_hash: str | None = None
    question: str | None = None
    batch_analysis: dict[str, Any] | None = None
    missing_context: dict[str, Any] | None = None
    supplement_mode: Literal["pending", "add", "skip"] = "pending"
    supplements: list[SupplementRecord] = Field(default_factory=list)
    pending_supplements: list[SupplementRecord] = Field(default_factory=list)
    assumptions: list[SupplementRecord] = Field(default_factory=list)
    supplement_rounds: int = 0
    rule_evidence: list[EvidenceRef] = Field(default_factory=list)
    round_assessments: list[RoundAssessment] = Field(default_factory=list)
    report: dict[str, Any] | None = None
    last_error: dict[str, str] | None = None
    progress_events: list[ProgressEvent] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class MessageRequest(BaseModel):
    message: str = Field(min_length=1)


class ConfirmRequest(BaseModel):
    action: Literal[
        "add_supplement",
        "skip_supplement",
        "confirm_supplements",
        "confirm_assumptions",
        "reject_assumptions",
    ]


class LLMRoundResponse(BaseModel):
    assessments: list[RoundAssessment]

    @model_validator(mode="after")
    def unique_rounds(self) -> "LLMRoundResponse":
        rounds = [x.round for x in self.assessments]
        if len(rounds) != len(set(rounds)):
            raise ValueError("duplicate round assessments")
        return self
