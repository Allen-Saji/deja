from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Severity = Literal["info", "warning", "critical"]
WorkflowNode = Literal["ingest", "recall", "triage", "act", "writeback"]
IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


class Alert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service: str = Field(min_length=1, max_length=100)
    alert_type: str = Field(min_length=1, max_length=100)
    severity: Severity
    message: str = Field(min_length=1, max_length=4_000)
    labels: dict[str, str] = Field(default_factory=dict)

    @field_validator("service", "alert_type")
    @classmethod
    def normalize_identifier(cls, value: str) -> str:
        normalized = value.strip().lower().replace(" ", "-")
        if not normalized:
            raise ValueError("identifier cannot be blank")
        if not IDENTIFIER_PATTERN.fullmatch(normalized):
            raise ValueError("identifier contains unsupported characters")
        return normalized

    @field_validator("labels")
    @classmethod
    def bound_labels(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > 32:
            raise ValueError("labels cannot contain more than 32 entries")
        return {str(key)[:100]: str(label_value)[:500] for key, label_value in value.items()}

    def fingerprint(self) -> str:
        identity = {
            "alert_type": self.alert_type,
            "labels": self.labels,
            "service": self.service,
        }
        encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


class TriageDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    diagnosis: str = Field(min_length=1, max_length=2_000)
    confidence: float = Field(ge=0, le=1)
    severity: Severity
    recommended_action: str = Field(min_length=1, max_length=2_000)
    rationale: str = Field(min_length=1, max_length=3_000)
    escalate: bool
    postmortem_summary: str = Field(min_length=1, max_length=4_000)
    cited_incident_ids: list[str] = Field(default_factory=list, max_length=3)

    @field_validator("cited_incident_ids")
    @classmethod
    def validate_citations(cls, value: list[str]) -> list[str]:
        normalized = [incident_id.strip().upper() for incident_id in value]
        if any(not incident_id.startswith("INC-") for incident_id in normalized):
            raise ValueError("citations must be incident IDs")
        if len(set(normalized)) != len(normalized):
            raise ValueError("citations must be unique")
        return normalized


class Precedent(BaseModel):
    incident_id: str
    run_id: str
    fingerprint: str
    service: str
    alert_type: str
    severity: Severity
    summary: str
    action_outcome: str
    distance: float = Field(ge=0)


class NoiseStatus(BaseModel):
    fingerprint: str
    occurrence_count: int = Field(ge=1)
    stable_count: int = Field(ge=0)
    notification_suppressed: bool
    evidence_run_ids: list[str] = Field(default_factory=list)


class RunbookCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    service: str = Field(min_length=1, max_length=100)
    alert_type: str = Field(min_length=1, max_length=100)
    recommended_action: str = Field(min_length=1, max_length=2_000)

    @field_validator("name", "recommended_action")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("runbook text cannot be blank")
        return normalized

    @field_validator("service", "alert_type")
    @classmethod
    def normalize_matcher(cls, value: str) -> str:
        normalized = value.strip().lower().replace(" ", "-")
        if not normalized:
            raise ValueError("runbook matcher cannot be blank")
        if normalized != "*" and not IDENTIFIER_PATTERN.fullmatch(normalized):
            raise ValueError("runbook matcher contains unsupported characters")
        return normalized


class RunbookScore(BaseModel):
    runbook_id: str
    name: str
    service: str
    alert_type: str
    recommended_action: str
    success_count: int = Field(ge=0)
    failure_count: int = Field(ge=0)
    sample_count: int = Field(ge=0)
    efficacy_score: float = Field(ge=0, le=1)


class RunbookOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    succeeded: bool


class ChaosSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["timeout_once"]
    before_node: WorkflowNode


class RunExecutionEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    event_type: Literal["deja.run.execute"] = "deja.run.execute"
    run_id: str = Field(pattern=r"^RUN-[A-F0-9]{12}$")
    incident_id: str = Field(pattern=r"^INC-[A-F0-9]{12}$")
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    alert: Alert
    started_at_epoch_ns: int = Field(gt=0)
    chaos: ChaosSpec | None = None

    @model_validator(mode="after")
    def validate_fingerprint(self) -> RunExecutionEvent:
        if self.fingerprint != self.alert.fingerprint():
            raise ValueError("event fingerprint does not match alert")
        return self


class RunAccepted(BaseModel):
    run_id: str
    incident_id: str
    status: Literal["queued"]
    status_url: str


class RunResult(BaseModel):
    run_id: str
    incident_id: str
    fingerprint: str
    status: Literal["completed"]
    triage: TriageDecision
    action_outcome: str
    postmortem: str
    diagnosis_ms: int = Field(ge=0)
    steps: list[str]
    precedents: list[Precedent] = Field(default_factory=list)
    noise: NoiseStatus | None = None
    selected_runbook: RunbookScore | None = None


class RunRecord(BaseModel):
    run_id: str
    incident_id: str
    fingerprint: str
    service: str
    alert_type: str
    severity: Severity
    status: str
    current_step: str
    attempt_count: int = Field(ge=0)
    last_resume_from: str | None = None
    triage: dict[str, Any] | None = None
    action_outcome: str | None = None
    postmortem: str | None = None
    diagnosis_ms: int | None = Field(default=None, ge=0)
    precedent_ids: list[str] = Field(default_factory=list)
    notification_suppressed: bool = False
    selected_runbook_id: str | None = None
    started_at: str
    completed_at: str | None = None


class RunAttemptRecord(BaseModel):
    attempt_number: int = Field(ge=1)
    resumed_from: str
    status: str
    started_at: str
    finished_at: str | None = None
    error_type: str | None = None
