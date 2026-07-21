from __future__ import annotations

import uuid
from contextlib import suppress
from typing import Any, TypedDict

from langchain_cockroachdb import CockroachDBSaver
from langgraph.graph import END, START, StateGraph

from deja.models import Alert, RunResult, TriageDecision
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
    status: str
    steps: list[str]


def build_graph(
    repository: IncidentRepository,
    triager: Triager,
    checkpointer: Any,
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
        return {
            "precedents": [],
            "steps": [*state["steps"], "recall"],
        }

    def triage(state: IncidentState) -> dict[str, Any]:
        repository.record_step(state["run_id"], "triage")
        decision = triager.triage(
            Alert.model_validate(state["alert"]),
            state.get("precedents", []),
        )
        return {
            "triage": decision.model_dump(),
            "steps": [*state["steps"], "triage"],
        }

    def act(state: IncidentState) -> dict[str, Any]:
        repository.record_step(state["run_id"], "act")
        outcome = "recommendation_recorded_no_external_action"
        return {
            "action_outcome": outcome,
            "steps": [*state["steps"], "act"],
        }

    def writeback(state: IncidentState) -> dict[str, Any]:
        repository.record_step(state["run_id"], "writeback")
        decision = TriageDecision.model_validate(state["triage"])
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
    ) -> None:
        self._database_url = database_url
        self._repository = repository
        self._triager = triager

    def setup(self) -> None:
        self._repository.setup_schema()

    def readiness(self) -> None:
        self._repository.check_connection()

    def process_alert(self, alert: Alert) -> RunResult:
        run_id = f"RUN-{uuid.uuid4().hex[:12].upper()}"
        incident_id = f"INC-{uuid.uuid4().hex[:12].upper()}"
        initial: IncidentState = {
            "run_id": run_id,
            "incident_id": incident_id,
            "fingerprint": alert.fingerprint(),
            "alert": alert.model_dump(),
            "precedents": [],
            "steps": [],
        }
        self.setup()
        try:
            with CockroachDBSaver.from_conn_string(self._database_url) as saver:
                saver.setup()
                app = build_graph(self._repository, self._triager, saver)
                result = app.invoke(initial, {"configurable": {"thread_id": run_id}})
        except Exception as error:
            with suppress(Exception):
                self._repository.fail_run(run_id, type(error).__name__)
            raise
        return RunResult.model_validate(result)

    def get_run(self, run_id: str):
        return self._repository.get_run(run_id)
