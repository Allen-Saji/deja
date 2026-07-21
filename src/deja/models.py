from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Severity = Literal["info", "warning", "critical"]


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


class RunResult(BaseModel):
    run_id: str
    incident_id: str
    fingerprint: str
    status: Literal["completed"]
    triage: TriageDecision
    action_outcome: str
    postmortem: str
    steps: list[str]
    precedents: list[dict[str, Any]] = Field(default_factory=list)


class RunRecord(BaseModel):
    run_id: str
    incident_id: str
    fingerprint: str
    service: str
    alert_type: str
    severity: Severity
    status: str
    triage: dict[str, Any] | None = None
    action_outcome: str | None = None
    postmortem: str | None = None
    started_at: str
    completed_at: str | None = None
