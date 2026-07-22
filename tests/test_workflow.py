from typing import Any

import pytest
from langgraph.checkpoint.memory import MemorySaver

from deja.models import Alert, NoiseStatus, Precedent, TriageDecision
from deja.workflow import IncidentService, build_graph


class FakeRepository:
    def __init__(self) -> None:
        self.steps: list[str] = []
        self.completed: dict[str, Any] | None = None
        self.failed: tuple[str, str] | None = None
        self.diagnosis: dict[str, Any] | None = None

    def setup_schema(self) -> None:
        pass

    def check_connection(self) -> None:
        pass

    def completed_incident_ids(self, incident_ids: list[str]) -> set[str]:
        return set(incident_ids)

    def begin_run(self, **_kwargs) -> None:
        self.steps.append("ingest")

    def record_step(self, _run_id: str, step: str) -> None:
        self.steps.append(step)

    def record_diagnosis(self, **kwargs) -> None:
        self.diagnosis = kwargs

    def record_noise_observation(self, **kwargs) -> NoiseStatus:
        return NoiseStatus(
            fingerprint=kwargs["fingerprint"],
            occurrence_count=1,
            stable_count=0,
            notification_suppressed=False,
            evidence_run_ids=[kwargs["run_id"]],
        )

    def select_runbook(self, _alert: Alert):
        return None

    def record_runbook_selection(self, _run_id: str, _runbook_id: str) -> None:
        pass

    def complete_run(self, **kwargs) -> None:
        self.completed = kwargs

    def fail_run(self, run_id: str, error_type: str) -> None:
        self.failed = (run_id, error_type)

    def get_run(self, run_id: str) -> str:
        return run_id


class FakeTriager:
    def triage(self, _alert: Alert, precedents: list[Precedent]) -> TriageDecision:
        return TriageDecision(
            diagnosis="Connection pool saturation after deploy",
            confidence=0.9,
            severity="critical",
            recommended_action="Roll back the latest deploy",
            rationale="The timing and pool wait metric are correlated",
            escalate=True,
            postmortem_summary="The deploy exhausted the database connection pool.",
            cited_incident_ids=[precedents[0].incident_id] if precedents else [],
        )


class FailingTriager:
    def triage(self, _alert: Alert, _precedents: list[Precedent]) -> TriageDecision:
        raise RuntimeError("provider failed")


class FakeMemory:
    def __init__(self, precedents: list[Precedent] | None = None) -> None:
        self.precedents = precedents or []
        self.remembered: dict[str, Any] | None = None

    def setup(self) -> None:
        pass

    def recall(self, _alert: Alert, *, limit: int = 3) -> list[Precedent]:
        return self.precedents[:limit]

    def remember(self, **kwargs) -> None:
        self.remembered = kwargs


class SaverContext:
    def __init__(self) -> None:
        self.saver = MemorySaver()

    def __enter__(self):
        self.saver.setup = lambda: None
        return self.saver

    def __exit__(self, *_args) -> None:
        return None


def test_graph_runs_the_p2_path_without_external_action() -> None:
    repository = FakeRepository()
    memory = FakeMemory()
    app = build_graph(repository, FakeTriager(), MemorySaver(), memory)
    alert = Alert(
        service="payments-api",
        alert_type="http-500-spike",
        severity="critical",
        message="500 rate rose after deploy",
    )
    initial = {
        "run_id": "RUN-TEST",
        "incident_id": "INC-TEST",
        "fingerprint": alert.fingerprint(),
        "alert": alert.model_dump(),
        "precedents": [],
        "selected_runbook": None,
        "started_at_epoch_ns": 0,
        "steps": [],
    }

    result = app.invoke(initial, {"configurable": {"thread_id": "RUN-TEST"}})

    assert result["steps"] == ["ingest", "recall", "triage", "act", "writeback"]
    assert result["action_outcome"] == "recommendation_recorded_no_external_action"
    assert result["status"] == "completed"
    assert result["noise"]["notification_suppressed"] is False
    assert repository.completed is not None
    assert memory.remembered is not None


def test_graph_carries_recalled_precedent_into_validated_triage() -> None:
    prior = Precedent(
        incident_id="INC-PREVIOUS",
        run_id="RUN-PREVIOUS",
        fingerprint="a" * 64,
        service="payments-api",
        alert_type="http-500-spike",
        severity="critical",
        summary="Connection pool exhaustion after deploy.",
        action_outcome="recommendation_recorded_no_external_action",
        distance=0.1,
    )
    repository = FakeRepository()
    memory = FakeMemory([prior])
    app = build_graph(repository, FakeTriager(), MemorySaver(), memory)
    alert = Alert(
        service="payments-api",
        alert_type="http-500-spike",
        severity="critical",
        message="500 rate rose after another deploy",
    )

    result = app.invoke(
        {
            "run_id": "RUN-REPEAT",
            "incident_id": "INC-REPEAT",
            "fingerprint": alert.fingerprint(),
            "alert": alert.model_dump(),
            "precedents": [],
            "selected_runbook": None,
            "started_at_epoch_ns": 0,
            "steps": [],
        },
        {"configurable": {"thread_id": "RUN-REPEAT"}},
    )

    assert result["triage"]["cited_incident_ids"] == ["INC-PREVIOUS"]
    assert result["precedents"][0]["incident_id"] == "INC-PREVIOUS"
    assert repository.diagnosis is not None
    assert repository.diagnosis["precedent_ids"] == ["INC-PREVIOUS"]
    assert memory.remembered is None


def test_graph_excludes_precedents_without_completed_relational_incidents() -> None:
    prior = Precedent(
        incident_id="INC-INCOMPLETE",
        run_id="RUN-INCOMPLETE",
        fingerprint="a" * 64,
        service="payments-api",
        alert_type="http-500-spike",
        severity="critical",
        summary="Uncommitted postmortem.",
        action_outcome="unknown",
        distance=0.1,
    )
    repository = FakeRepository()
    repository.completed_incident_ids = lambda _incident_ids: set()
    app = build_graph(repository, FakeTriager(), MemorySaver(), FakeMemory([prior]))
    alert = Alert(
        service="payments-api",
        alert_type="http-500-spike",
        severity="critical",
        message="500 rate rose after deploy",
    )

    result = app.invoke(
        {
            "run_id": "RUN-CURRENT",
            "incident_id": "INC-CURRENT",
            "fingerprint": alert.fingerprint(),
            "alert": alert.model_dump(),
            "precedents": [],
            "selected_runbook": None,
            "started_at_epoch_ns": 0,
            "steps": [],
        },
        {"configurable": {"thread_id": "RUN-CURRENT"}},
    )

    assert result["precedents"] == []
    assert result["triage"]["cited_incident_ids"] == []


def test_service_runs_graph_and_records_failures(monkeypatch) -> None:
    monkeypatch.setattr(
        "deja.workflow.CockroachDBSaver.from_conn_string",
        lambda _url: SaverContext(),
    )
    alert = Alert(
        service="payments-api",
        alert_type="http-500-spike",
        severity="critical",
        message="500 rate rose after deploy",
    )

    successful_repository = FakeRepository()
    service = IncidentService(
        database_url="postgresql://unused",
        repository=successful_repository,
        triager=FakeTriager(),
        memory=FakeMemory(),
    )
    result = service.process_alert(alert)
    assert result.status == "completed"
    assert service.get_run("RUN-LOOKUP") == "RUN-LOOKUP"

    failing_repository = FakeRepository()
    failing_service = IncidentService(
        database_url="postgresql://unused",
        repository=failing_repository,
        triager=FailingTriager(),
        memory=FakeMemory(),
    )
    with pytest.raises(RuntimeError, match="provider failed"):
        failing_service.process_alert(alert)

    assert failing_repository.failed is not None
    assert failing_repository.failed[1] == "RuntimeError"
