from __future__ import annotations

from types import SimpleNamespace

import pytest

from deja.execution import LambdaDispatcher, TimeoutOnceInjector, is_run_execution_event
from deja.models import Alert, ChaosSpec, RunExecutionEvent


def execution_event(*, chaos: ChaosSpec | None = None) -> RunExecutionEvent:
    alert = Alert(
        service="payments-api",
        alert_type="http-500-spike",
        severity="critical",
        message="500 rate rose after deploy",
    )
    return RunExecutionEvent(
        run_id="RUN-A1B2C3D4E5F6",
        incident_id="INC-A1B2C3D4E5F6",
        fingerprint=alert.fingerprint(),
        alert=alert,
        started_at_epoch_ns=1,
        chaos=chaos,
    )


def test_lambda_dispatcher_queues_compact_internal_event(monkeypatch) -> None:
    calls = []
    client = SimpleNamespace(invoke=lambda **kwargs: calls.append(kwargs) or {"StatusCode": 202})
    monkeypatch.setattr(LambdaDispatcher, "_client", staticmethod(lambda: client))

    LambdaDispatcher(function_name="deja-api").dispatch(execution_event())

    assert calls[0]["FunctionName"] == "deja-api"
    assert calls[0]["InvocationType"] == "Event"
    assert b'"event_type":"deja.run.execute"' in calls[0]["Payload"]


def test_lambda_dispatcher_rejects_unqueued_invocation(monkeypatch) -> None:
    client = SimpleNamespace(invoke=lambda **_kwargs: {"StatusCode": 200})
    monkeypatch.setattr(LambdaDispatcher, "_client", staticmethod(lambda: client))

    with pytest.raises(RuntimeError, match="did not accept"):
        LambdaDispatcher(function_name="deja-api").dispatch(execution_event())


def test_timeout_injection_is_disabled_by_default_and_first_write_wins(
    monkeypatch,
) -> None:
    event = execution_event(chaos=ChaosSpec(mode="timeout_once", before_node="triage"))
    context = SimpleNamespace(get_remaining_time_in_millis=lambda: 10)
    disabled = TimeoutOnceInjector(
        event=event,
        claim_once=lambda _run_id, _node: True,
        lambda_context=context,
        enabled=False,
    )
    with pytest.raises(RuntimeError, match="disabled"):
        disabled(event.run_id, "triage")

    sleeps = []
    claims = iter([True, False])
    monkeypatch.setattr("deja.execution.sleep", lambda seconds: sleeps.append(seconds))
    enabled = TimeoutOnceInjector(
        event=event,
        claim_once=lambda _run_id, _node: next(claims),
        lambda_context=context,
        enabled=True,
    )
    enabled(event.run_id, "triage")
    enabled(event.run_id, "triage")

    assert sleeps == [1.01]


def test_execution_event_detection_requires_internal_event_type() -> None:
    assert is_run_execution_event(execution_event().model_dump())
    assert not is_run_execution_event({"requestContext": {}})
    assert not is_run_execution_event("deja.run.execute")
