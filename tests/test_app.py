import asyncio

import pytest
from fastapi import HTTPException

from deja.app import (
    create_runbook,
    get_run,
    handler,
    opaque_error_handler,
    ready,
    record_runbook_outcome,
    submit_alert,
)
from deja.models import (
    Alert,
    RunbookCreate,
    RunbookOutcome,
    RunbookScore,
    RunExecutionEvent,
    RunRecord,
)


class FailingService:
    def prepare_alert(self, _alert):
        raise RuntimeError("provider detail must not escape")


class ReadinessService:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    def readiness(self) -> None:
        if self.error:
            raise self.error


class LookupService:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error

    def get_run(self, _run_id):
        if self.error:
            raise self.error
        return self.result


class RunbookService:
    def __init__(self, score: RunbookScore | None) -> None:
        self.score = score

    def create_runbook(self, _definition):
        return self.score

    def record_runbook_outcome(self, _run_id, _succeeded):
        return self.score


class FakeDispatcher:
    def __init__(self) -> None:
        self.events = []

    def dispatch(self, event) -> None:
        self.events.append(event)


def test_processing_error_is_converted_to_opaque_http_error() -> None:
    alert = Alert(
        service="payments-api",
        alert_type="http-500-spike",
        severity="critical",
        message="500 rate rose after deploy",
    )

    with pytest.raises(HTTPException) as raised:
        submit_alert(alert, FailingService(), FakeDispatcher())

    assert raised.value.status_code == 500
    assert raised.value.detail == "incident processing failed"
    assert "provider detail" not in str(raised.value.detail)


def test_ready_reports_success_and_hides_provider_errors() -> None:
    assert ready(ReadinessService()) == {"status": "ready"}

    with pytest.raises(HTTPException) as raised:
        ready(ReadinessService(RuntimeError("database hostname must not escape")))

    assert raised.value.status_code == 503
    assert raised.value.detail == "service is not ready"


def test_get_run_returns_record_and_reports_missing_run() -> None:
    record = RunRecord(
        run_id="RUN-TEST",
        incident_id="INC-TEST",
        fingerprint="a" * 64,
        service="payments-api",
        alert_type="http-500-spike",
        severity="critical",
        status="completed",
        current_step="writeback",
        attempt_count=1,
        started_at="2026-07-21T00:00:00Z",
    )

    assert get_run("RUN-TEST", LookupService(record)) == record

    with pytest.raises(HTTPException) as raised:
        get_run("RUN-MISSING", LookupService())
    assert raised.value.status_code == 404


def test_get_run_and_global_handler_hide_provider_errors() -> None:
    with pytest.raises(HTTPException) as raised:
        get_run("RUN-TEST", LookupService(error=RuntimeError("private detail")))
    assert raised.value.status_code == 500
    assert raised.value.detail == "run lookup failed"

    response = asyncio.run(opaque_error_handler(None, RuntimeError("private detail")))
    assert response.status_code == 500
    assert response.body == b'{"detail":"incident processing failed"}'


def test_runbook_creation_and_outcome_feedback_return_ranked_score() -> None:
    score = RunbookScore(
        runbook_id="RB-TEST",
        name="Rollback deploy",
        service="payments-api",
        alert_type="http-500-spike",
        recommended_action="Roll back the latest deploy.",
        success_count=2,
        failure_count=1,
        sample_count=3,
        efficacy_score=0.6,
    )
    service = RunbookService(score)
    definition = RunbookCreate(
        name=score.name,
        service=score.service,
        alert_type=score.alert_type,
        recommended_action=score.recommended_action,
    )

    assert create_runbook(definition, service) == score
    assert record_runbook_outcome("RUN-TEST", RunbookOutcome(succeeded=True), service) == score

    with pytest.raises(HTTPException) as raised:
        record_runbook_outcome(
            "RUN-MISSING",
            RunbookOutcome(succeeded=True),
            RunbookService(None),
        )
    assert raised.value.status_code == 404


def test_lambda_retries_receive_distinct_attempt_tokens(monkeypatch) -> None:
    alert = Alert(
        service="payments-api",
        alert_type="http-500-spike",
        severity="critical",
        message="500 rate rose after deploy",
    )
    event = RunExecutionEvent(
        run_id="RUN-A1B2C3D4E5F6",
        incident_id="INC-A1B2C3D4E5F6",
        fingerprint=alert.fingerprint(),
        alert=alert,
        started_at_epoch_ns=1,
    )

    class HandlerService:
        def __init__(self) -> None:
            self.tokens = []

        def claim_chaos_injection(self, _run_id, _node):
            return False

        def execute_run(self, _event, *, execution_token, failure_hook):
            self.tokens.append(execution_token)
            return None

    service = HandlerService()
    context = type(
        "Context",
        (),
        {
            "aws_request_id": "same-aws-request-id",
            "get_remaining_time_in_millis": lambda _self: 90_000,
        },
    )()
    monkeypatch.setattr("deja.app.get_service", lambda: service)
    monkeypatch.setattr(
        "deja.app.Settings.from_env",
        lambda: type("Settings", (), {"chaos_enabled": False})(),
    )

    handler(event.model_dump(mode="json"), context)
    handler(event.model_dump(mode="json"), context)

    assert len(set(service.tokens)) == 2
    assert all(token.startswith("same-aws-request-id-") for token in service.tokens)


def test_http_event_recreates_loop_cleared_by_internal_execution(monkeypatch) -> None:
    asyncio.run(asyncio.sleep(0))
    with pytest.raises(RuntimeError, match="no current event loop"):
        asyncio.get_event_loop()

    observed_loops = []
    monkeypatch.setattr(
        "deja.app.mangum_handler",
        lambda _event, _context: (
            observed_loops.append(asyncio.get_event_loop()) or {"statusCode": 200}
        ),
    )

    try:
        response = handler({"requestContext": {}}, object())
        assert response == {"statusCode": 200}
        assert len(observed_loops) == 1
        assert not observed_loops[0].is_closed()
    finally:
        loop = asyncio.get_event_loop()
        loop.close()
        asyncio.set_event_loop(asyncio.new_event_loop())
