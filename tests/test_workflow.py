from typing import Any

import pytest
from langgraph.checkpoint.memory import MemorySaver

from deja.models import Alert, TriageDecision
from deja.workflow import IncidentService, build_graph


class FakeRepository:
    def __init__(self) -> None:
        self.steps: list[str] = []
        self.completed: dict[str, Any] | None = None
        self.failed: tuple[str, str] | None = None

    def setup_schema(self) -> None:
        pass

    def check_connection(self) -> None:
        pass

    def begin_run(self, **_kwargs) -> None:
        self.steps.append("ingest")

    def record_step(self, _run_id: str, step: str) -> None:
        self.steps.append(step)

    def complete_run(self, **kwargs) -> None:
        self.completed = kwargs

    def fail_run(self, run_id: str, error_type: str) -> None:
        self.failed = (run_id, error_type)

    def get_run(self, run_id: str) -> str:
        return run_id


class FakeTriager:
    def triage(self, _alert: Alert, _precedents: list[dict[str, Any]]) -> TriageDecision:
        return TriageDecision(
            diagnosis="Connection pool saturation after deploy",
            confidence=0.9,
            severity="critical",
            recommended_action="Roll back the latest deploy",
            rationale="The timing and pool wait metric are correlated",
            escalate=True,
            postmortem_summary="The deploy exhausted the database connection pool.",
        )


class FailingTriager:
    def triage(self, _alert: Alert, _precedents: list[dict[str, Any]]) -> TriageDecision:
        raise RuntimeError("provider failed")


class SaverContext:
    def __init__(self) -> None:
        self.saver = MemorySaver()

    def __enter__(self):
        self.saver.setup = lambda: None
        return self.saver

    def __exit__(self, *_args) -> None:
        return None


def test_graph_runs_the_p1_path_without_external_action() -> None:
    repository = FakeRepository()
    app = build_graph(repository, FakeTriager(), MemorySaver())
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
        "steps": [],
    }

    result = app.invoke(initial, {"configurable": {"thread_id": "RUN-TEST"}})

    assert result["steps"] == ["ingest", "recall", "triage", "act", "writeback"]
    assert result["action_outcome"] == "recommendation_recorded_no_external_action"
    assert result["status"] == "completed"
    assert repository.completed is not None


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
    )
    result = service.process_alert(alert)
    assert result.status == "completed"
    assert service.get_run("RUN-LOOKUP") == "RUN-LOOKUP"

    failing_repository = FakeRepository()
    failing_service = IncidentService(
        database_url="postgresql://unused",
        repository=failing_repository,
        triager=FailingTriager(),
    )
    with pytest.raises(RuntimeError, match="provider failed"):
        failing_service.process_alert(alert)

    assert failing_repository.failed is not None
    assert failing_repository.failed[1] == "RuntimeError"
