from __future__ import annotations

import uuid
from contextlib import suppress
from time import time_ns
from typing import Any, TypedDict

from langchain_cockroachdb import CockroachDBSaver
from langgraph.graph import END, START, StateGraph

from deja.memory import EpisodicMemory
from deja.models import (
    Alert,
    Precedent,
    RunbookCreate,
    RunbookScore,
    RunResult,
    TriageDecision,
)
from deja.repository import IncidentRepository
from deja.triage import Triager


class IncidentState(TypedDict, total=False):
    run_id: str
    incident_id: str
    fingerprint: str
    alert: dict[str, Any]
    precedents: list[dict[str, Any]]
    triage: dict[str, Any]
    action_outcome: str
    postmortem: str
    diagnosis_ms: int
    noise: dict[str, Any]
    selected_runbook: dict[str, Any] | None
    started_at_epoch_ns: int
    status: str
    steps: list[str]


def build_graph(
    repository: IncidentRepository,
    triager: Triager,
    checkpointer: Any,
    memory: EpisodicMemory,
) -> Any:
    def ingest(state: IncidentState) -> dict[str, Any]:
        alert = Alert.model_validate(state["alert"])
        repository.begin_run(
            alert=alert,
            run_id=state["run_id"],
            incident_id=state["incident_id"],
            fingerprint=state["fingerprint"],
        )
        return {"steps": [*state.get("steps", []), "ingest"]}

    def recall(state: IncidentState) -> dict[str, Any]:
        repository.record_step(state["run_id"], "recall")
        precedents = memory.recall(Alert.model_validate(state["alert"]))
        completed_ids = repository.completed_incident_ids(
            [precedent.incident_id for precedent in precedents]
        )
        precedents = [
            precedent for precedent in precedents if precedent.incident_id in completed_ids
        ]
        return {
            "precedents": [precedent.model_dump() for precedent in precedents],
            "steps": [*state["steps"], "recall"],
        }

    def triage(state: IncidentState) -> dict[str, Any]:
        repository.record_step(state["run_id"], "triage")
        precedents = [
            Precedent.model_validate(precedent) for precedent in state.get("precedents", [])
        ]
        decision = triager.triage(Alert.model_validate(state["alert"]), precedents)
        diagnosis_ms = max(0, (time_ns() - state["started_at_epoch_ns"]) // 1_000_000)
        repository.record_diagnosis(
            run_id=state["run_id"],
            diagnosis_ms=diagnosis_ms,
            precedent_ids=decision.cited_incident_ids,
        )
        return {
            "triage": decision.model_dump(),
            "diagnosis_ms": diagnosis_ms,
            "steps": [*state["steps"], "triage"],
        }

    def act(state: IncidentState) -> dict[str, Any]:
        repository.record_step(state["run_id"], "act")
        alert = Alert.model_validate(state["alert"])
        decision = TriageDecision.model_validate(state["triage"])
        noise = repository.record_noise_observation(
            run_id=state["run_id"],
            fingerprint=state["fingerprint"],
            severity=alert.severity,
            triage=decision,
        )
        selected_runbook = repository.select_runbook(alert)
        if selected_runbook:
            repository.record_runbook_selection(state["run_id"], selected_runbook.runbook_id)
        if noise.notification_suppressed:
            outcome = "duplicate_notification_suppressed_no_external_action"
        elif selected_runbook:
            outcome = "runbook_recommended_no_external_action"
        else:
            outcome = "recommendation_recorded_no_external_action"
        return {
            "action_outcome": outcome,
            "noise": noise.model_dump(),
            "selected_runbook": selected_runbook.model_dump() if selected_runbook else None,
            "steps": [*state["steps"], "act"],
        }

    def writeback(state: IncidentState) -> dict[str, Any]:
        repository.record_step(state["run_id"], "writeback")
        alert = Alert.model_validate(state["alert"])
        decision = TriageDecision.model_validate(state["triage"])
        if not decision.cited_incident_ids:
            memory.remember(
                alert=alert,
                incident_id=state["incident_id"],
                run_id=state["run_id"],
                triage=decision,
                action_outcome=state["action_outcome"],
            )
        repository.complete_run(
            run_id=state["run_id"],
            incident_id=state["incident_id"],
            triage=decision,
            action_outcome=state["action_outcome"],
            postmortem=decision.postmortem_summary,
        )
        return {
            "postmortem": decision.postmortem_summary,
            "status": "completed",
            "steps": [*state["steps"], "writeback"],
        }

    graph = StateGraph(IncidentState)
    graph.add_node("ingest", ingest)
    graph.add_node("recall", recall)
    graph.add_node("triage", triage)
    graph.add_node("act", act)
    graph.add_node("writeback", writeback)
    graph.add_edge(START, "ingest")
    graph.add_edge("ingest", "recall")
    graph.add_edge("recall", "triage")
    graph.add_edge("triage", "act")
    graph.add_edge("act", "writeback")
    graph.add_edge("writeback", END)
    return graph.compile(checkpointer=checkpointer)


class IncidentService:
    def __init__(
        self,
        *,
        database_url: str,
        repository: IncidentRepository,
        triager: Triager,
        memory: EpisodicMemory,
    ) -> None:
        self._database_url = database_url
        self._repository = repository
        self._triager = triager
        self._memory = memory

    def setup(self) -> None:
        self._repository.setup_schema()
        self._memory.setup()

    def readiness(self) -> None:
        self.setup()
        self._repository.check_connection()

    def process_alert(self, alert: Alert) -> RunResult:
        self.setup()
        run_id = f"RUN-{uuid.uuid4().hex[:12].upper()}"
        incident_id = f"INC-{uuid.uuid4().hex[:12].upper()}"
        initial: IncidentState = {
            "run_id": run_id,
            "incident_id": incident_id,
            "fingerprint": alert.fingerprint(),
            "alert": alert.model_dump(),
            "precedents": [],
            "selected_runbook": None,
            "started_at_epoch_ns": time_ns(),
            "steps": [],
        }
        try:
            with CockroachDBSaver.from_conn_string(self._database_url) as saver:
                saver.setup()
                app = build_graph(self._repository, self._triager, saver, self._memory)
                result = app.invoke(initial, {"configurable": {"thread_id": run_id}})
        except Exception as error:
            with suppress(Exception):
                self._repository.fail_run(run_id, type(error).__name__)
            raise
        return RunResult.model_validate(result)

    def get_run(self, run_id: str):
        return self._repository.get_run(run_id)

    def create_runbook(self, definition: RunbookCreate) -> RunbookScore:
        runbook_id = f"RB-{uuid.uuid4().hex[:12].upper()}"
        self.setup()
        return self._repository.upsert_runbook(runbook_id, definition)

    def record_runbook_outcome(self, run_id: str, succeeded: bool) -> RunbookScore | None:
        self.setup()
        return self._repository.record_runbook_outcome(run_id, succeeded)
