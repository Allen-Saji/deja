from contextlib import contextmanager

import psycopg

from deja.models import NoiseStatus, TriageDecision
from deja.repository import SCHEMA_STATEMENTS, IncidentRepository, next_noise_state


def test_noise_suppression_requires_three_stable_eligible_observations() -> None:
    first = next_noise_state(
        occurrence_count=0,
        stable_count=0,
        last_signature=None,
        signature="same",
        eligible=True,
    )
    second = next_noise_state(
        occurrence_count=first[0],
        stable_count=first[1],
        last_signature="same",
        signature="same",
        eligible=True,
    )
    third = next_noise_state(
        occurrence_count=second[0],
        stable_count=second[1],
        last_signature="same",
        signature="same",
        eligible=True,
    )

    assert first == (1, 1, False)
    assert second == (2, 2, False)
    assert third == (3, 3, True)


def test_schema_setup_runs_once_per_repository_instance(monkeypatch) -> None:
    repository = IncidentRepository("postgresql://unused")
    statements: list[str] = []

    class Connection:
        def execute(self, statement: str) -> None:
            statements.append(statement)

    @contextmanager
    def connection():
        yield Connection()

    monkeypatch.setattr(repository, "_connection", connection)

    repository.setup_schema()
    repository.setup_schema()

    assert statements == list(SCHEMA_STATEMENTS)


def test_critical_or_escalated_observation_resets_suppression_streak() -> None:
    assert next_noise_state(
        occurrence_count=4,
        stable_count=4,
        last_signature="same",
        signature="same",
        eligible=False,
    ) == (5, 0, False)


def test_noise_observation_retries_serialization_failures(monkeypatch) -> None:
    repository = IncidentRepository("postgresql://unused")
    attempts = 0

    def observe_once(**kwargs):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise psycopg.errors.SerializationFailure("retry")
        return NoiseStatus(
            fingerprint=kwargs["fingerprint"],
            occurrence_count=1,
            stable_count=1,
            notification_suppressed=False,
        )

    monkeypatch.setattr(repository, "_record_noise_observation_once", observe_once)
    monkeypatch.setattr("deja.repository.sleep", lambda _seconds: None)
    triage = TriageDecision(
        diagnosis="Known warning",
        confidence=0.9,
        severity="warning",
        recommended_action="Observe.",
        rationale="Stable evidence.",
        escalate=False,
        postmortem_summary="Known warning.",
    )

    result = repository.record_noise_observation(
        run_id="RUN-TEST",
        fingerprint="a" * 64,
        severity="warning",
        triage=triage,
    )

    assert attempts == 3
    assert result.notification_suppressed is False
