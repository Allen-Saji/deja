from __future__ import annotations

import uuid
from collections.abc import Callable
from contextlib import suppress
from time import time_ns
from typing import Any, TypedDict

from langchain_cockroachdb import CockroachDBSaver
from langgraph.graph import END, START, StateGraph

from deja.memory import EpisodicMemory
from deja.models import (
    Alert,
    ChaosSpec,
    Precedent,
    RunAccepted,
    RunbookCreate,
    RunbookScore,
    RunExecutionEvent,
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


class RunLeaseLost(RuntimeError):
    """Raised when a stale invocation no longer owns the run lease."""


def build_graph(
    repository: IncidentRepository,
    triager: Triager,
    checkpointer: Any,
    memory: EpisodicMemory,
    *,
    execution_token: str | None = None,
    lease_seconds: int = 90,
    failure_hook: Callable[[str, str], None] | None = None,
) -> Any:
    def before_node(state: IncidentState, node_name: str) -> None:
        if execution_token is not None and not repository.renew_run_claim(
            run_id=state["run_id"],
            execution_token=execution_token,
            step=node_name,
            lease_seconds=lease_seconds,
        ):
            raise RunLeaseLost(f"run lease lost before {node_name}")
        if failure_hook is not None:
            failure_hook(state["run_id"], node_name)

    def effect(
        state: IncidentState,
        node_name: str,
        compute: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        existing = repository.get_node_effect(state["run_id"], node_name)
        result = (
            existing
            if existing is not None
            else repository.record_node_effect(
                state["run_id"],
                node_name,
                compute(),
            )
        )
        return {**result, "steps": [*state.get("steps", []), node_name]}

    def ingest(state: IncidentState) -> dict[str, Any]:
        before_node(state, "ingest")

        def compute() -> dict[str, Any]:
            alert = Alert.model_validate(state["alert"])
            repository.begin_run(
                alert=alert,
                run_id=state["run_id"],
                incident_id=state["incident_id"],
                fingerprint=state["fingerprint"],
            )
            return {}

        return effect(state, "ingest", compute)

    def recall(state: IncidentState) -> dict[str, Any]:
        before_node(state, "recall")

        def compute() -> dict[str, Any]:
            precedents = memory.recall(Alert.model_validate(state["alert"]))
            completed_ids = repository.completed_incident_ids(
                [precedent.incident_id for precedent in precedents]
            )
            precedents = [
                precedent for precedent in precedents if precedent.incident_id in completed_ids
            ]
            return {"precedents": [precedent.model_dump() for precedent in precedents]}

        return effect(state, "recall", compute)

    def triage(state: IncidentState) -> dict[str, Any]:
        before_node(state, "triage")

        def compute() -> dict[str, Any]:
            precedents = [
                Precedent.model_validate(precedent) for precedent in state.get("precedents", [])
            ]
            decision = triager.triage(Alert.model_validate(state["alert"]), precedents)
            diagnosis_ms = max(
                0,
                (time_ns() - state["started_at_epoch_ns"]) // 1_000_000,
            )
            repository.record_diagnosis(
                run_id=state["run_id"],
                diagnosis_ms=diagnosis_ms,
                precedent_ids=decision.cited_incident_ids,
            )
            return {
                "triage": decision.model_dump(),
                "diagnosis_ms": diagnosis_ms,
            }

        return effect(state, "triage", compute)

    def act(state: IncidentState) -> dict[str, Any]:
        before_node(state, "act")

        def compute() -> dict[str, Any]:
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
                repository.record_runbook_selection(
                    state["run_id"],
                    selected_runbook.runbook_id,
                )
            if noise.notification_suppressed:
                outcome = "duplicate_notification_suppressed_no_external_action"
            elif selected_runbook:
                outcome = "runbook_recommended_no_external_action"
            else:
                outcome = "recommendation_recorded_no_external_action"
            return {
                "action_outcome": outcome,
                "noise": noise.model_dump(),
                "selected_runbook": (selected_runbook.model_dump() if selected_runbook else None),
            }

        return effect(state, "act", compute)

    def writeback(state: IncidentState) -> dict[str, Any]:
        before_node(state, "writeback")

        def compute() -> dict[str, Any]:
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
            }

        return effect(state, "writeback", compute)

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
        execution_lease_seconds: int = 90,
    ) -> None:
        self._database_url = database_url
        self._repository = repository
        self._triager = triager
        self._memory = memory
        self._execution_lease_seconds = execution_lease_seconds

    def setup(self) -> None:
        self._repository.setup_schema()
        self._memory.setup()

    def readiness(self) -> None:
        self.setup()
        self._repository.check_connection()

    def prepare_alert(
        self,
        alert: Alert,
        *,
        chaos: ChaosSpec | None = None,
    ) -> tuple[RunAccepted, RunExecutionEvent]:
        self.setup()
        run_id = f"RUN-{uuid.uuid4().hex[:12].upper()}"
        incident_id = f"INC-{uuid.uuid4().hex[:12].upper()}"
        event = RunExecutionEvent(
            run_id=run_id,
            incident_id=incident_id,
            fingerprint=alert.fingerprint(),
            alert=alert,
            started_at_epoch_ns=time_ns(),
            chaos=chaos,
        )
        self._repository.reserve_run(
            alert=alert,
            run_id=run_id,
            incident_id=incident_id,
            fingerprint=event.fingerprint,
        )
        return (
            RunAccepted(
                run_id=run_id,
                incident_id=incident_id,
                status="queued",
                status_url=f"/runs/{run_id}",
            ),
            event,
        )

    def execute_run(
        self,
        event: RunExecutionEvent,
        *,
        execution_token: str,
        failure_hook: Callable[[str, str], None] | None = None,
    ) -> RunResult | None:
        self.setup()
        self._repository.reserve_run(
            alert=event.alert,
            run_id=event.run_id,
            incident_id=event.incident_id,
            fingerprint=event.fingerprint,
        )
        initial: IncidentState = {
            "run_id": event.run_id,
            "incident_id": event.incident_id,
            "fingerprint": event.fingerprint,
            "alert": event.alert.model_dump(),
            "precedents": [],
            "selected_runbook": None,
            "started_at_epoch_ns": event.started_at_epoch_ns,
            "steps": [],
        }
        config = {"configurable": {"thread_id": event.run_id}}
        try:
            with CockroachDBSaver.from_conn_string(self._database_url) as saver:
                saver.setup()
                app = build_graph(
                    self._repository,
                    self._triager,
                    saver,
                    self._memory,
                    execution_token=execution_token,
                    lease_seconds=self._execution_lease_seconds,
                    failure_hook=failure_hook,
                )
                snapshot = app.get_state(config)
                if snapshot.values and not snapshot.next:
                    return RunResult.model_validate(snapshot.values)
                resumed_from = snapshot.next[0] if snapshot.next else "ingest"
                if not self._repository.claim_run(
                    run_id=event.run_id,
                    execution_token=execution_token,
                    resumed_from=resumed_from,
                    lease_seconds=self._execution_lease_seconds,
                ):
                    return None
                snapshot = app.get_state(config)
                graph_input = None if snapshot.values else initial
                result = app.invoke(graph_input, config)
        except Exception as error:
            with suppress(Exception):
                self._repository.fail_run(
                    event.run_id,
                    type(error).__name__,
                    execution_token,
                )
            raise
        self._repository.finish_run_attempt(execution_token)
        return RunResult.model_validate(result)

    def process_alert(self, alert: Alert) -> RunResult:
        _accepted, event = self.prepare_alert(alert)
        result = self.execute_run(
            event,
            execution_token=f"LOCAL-{uuid.uuid4().hex.upper()}",
        )
        if result is None:
            raise RuntimeError("local run was already executing")
        return result

    def fail_dispatch(self, run_id: str, error_type: str) -> None:
        self._repository.fail_run(run_id, error_type)

    def claim_chaos_injection(self, run_id: str, before_node: str) -> bool:
        return self._repository.claim_chaos_injection(run_id, before_node)

    def get_run(self, run_id: str):
        return self._repository.get_run(run_id)

    def get_run_attempts(self, run_id: str):
        return self._repository.get_run_attempts(run_id)

    def create_runbook(self, definition: RunbookCreate) -> RunbookScore:
        runbook_id = f"RB-{uuid.uuid4().hex[:12].upper()}"
        self.setup()
        return self._repository.upsert_runbook(runbook_id, definition)

    def record_runbook_outcome(self, run_id: str, succeeded: bool) -> RunbookScore | None:
        self.setup()
        return self._repository.record_runbook_outcome(run_id, succeeded)
