"""Exercise the noise ledger and runbook ranking against CockroachDB."""

from __future__ import annotations

import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

from deja.models import Alert, RunbookCreate, TriageDecision
from deja.repository import IncidentRepository


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def identifier(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12].upper()}"


def complete_acceptance_run(
    repository: IncidentRepository,
    *,
    alert: Alert,
    triage: TriageDecision,
    run_id: str,
    incident_id: str,
) -> None:
    repository.begin_run(
        alert=alert,
        run_id=run_id,
        incident_id=incident_id,
        fingerprint=alert.fingerprint(),
    )
    repository.record_diagnosis(run_id=run_id, diagnosis_ms=1, precedent_ids=[])
    repository.complete_run(
        run_id=run_id,
        incident_id=incident_id,
        triage=triage,
        action_outcome="acceptance_recorded_no_external_action",
        postmortem=triage.postmortem_summary,
    )


def main() -> None:
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise SystemExit("DATABASE_URL is required")

    repository = IncidentRepository(database_url)
    repository.setup_schema()
    session = uuid.uuid4().hex[:8]
    warning = Alert(
        service=f"deja-acceptance-{session}",
        alert_type="duplicate-warning",
        severity="warning",
        message="Identical non-critical acceptance alert.",
    )
    stable_triage = TriageDecision(
        diagnosis="Known synthetic warning",
        confidence=0.95,
        severity="warning",
        recommended_action="Observe without external remediation.",
        rationale="The acceptance alert is stable and non-critical.",
        escalate=False,
        postmortem_summary="Synthetic noise-ledger acceptance event.",
    )

    suppression_results = []
    noise_run_ids = []
    for _index in range(3):
        run_id = identifier("RUN-NOISE")
        noise_run_ids.append(run_id)
        incident_id = identifier("INC-NOISE")
        repository.begin_run(
            alert=warning,
            run_id=run_id,
            incident_id=incident_id,
            fingerprint=warning.fingerprint(),
        )
        status = repository.record_noise_observation(
            run_id=run_id,
            fingerprint=warning.fingerprint(),
            severity=warning.severity,
            triage=stable_triage,
        )
        repository.record_diagnosis(run_id=run_id, diagnosis_ms=1, precedent_ids=[])
        repository.complete_run(
            run_id=run_id,
            incident_id=incident_id,
            triage=stable_triage,
            action_outcome=(
                "duplicate_notification_suppressed_no_external_action"
                if status.notification_suppressed
                else "recommendation_recorded_no_external_action"
            ),
            postmortem=stable_triage.postmortem_summary,
        )
        suppression_results.append(status.notification_suppressed)

    require(
        suppression_results == [False, False, True],
        "duplicate notification suppression did not activate on the third stable observation",
    )
    replayed_first = repository.record_noise_observation(
        run_id=noise_run_ids[0],
        fingerprint=warning.fingerprint(),
        severity=warning.severity,
        triage=stable_triage,
    )
    require(
        replayed_first.notification_suppressed is False,
        "replaying the first observation changed its persisted suppression decision",
    )

    concurrent_warning = warning.model_copy(
        update={"service": f"deja-concurrency-{session}"}
    )
    concurrent_runs = []
    for _index in range(5):
        run_id = identifier("RUN-CONCURRENT")
        incident_id = identifier("INC-CONCURRENT")
        repository.begin_run(
            alert=concurrent_warning,
            run_id=run_id,
            incident_id=incident_id,
            fingerprint=concurrent_warning.fingerprint(),
        )
        concurrent_runs.append((run_id, incident_id))

    def observe_concurrently(item: tuple[str, str]) -> bool:
        run_id, incident_id = item
        status = repository.record_noise_observation(
            run_id=run_id,
            fingerprint=concurrent_warning.fingerprint(),
            severity=concurrent_warning.severity,
            triage=stable_triage,
        )
        repository.record_diagnosis(run_id=run_id, diagnosis_ms=1, precedent_ids=[])
        repository.complete_run(
            run_id=run_id,
            incident_id=incident_id,
            triage=stable_triage,
            action_outcome="concurrency_acceptance_no_external_action",
            postmortem=stable_triage.postmortem_summary,
        )
        return status.notification_suppressed

    with ThreadPoolExecutor(max_workers=5) as executor:
        concurrent_suppression = list(executor.map(observe_concurrently, concurrent_runs))
    require(
        concurrent_suppression.count(True) == 3,
        "concurrent observations produced an unexpected suppression count",
    )

    low_id = identifier("RB-LOW")
    high_id = identifier("RB-HIGH")
    low = repository.upsert_runbook(
        low_id,
        RunbookCreate(
            name="Low-efficacy acceptance runbook",
            service=warning.service,
            alert_type=warning.alert_type,
            recommended_action="Use the low-efficacy acceptance path.",
        ),
    )
    high = repository.upsert_runbook(
        high_id,
        RunbookCreate(
            name="High-efficacy acceptance runbook",
            service=warning.service,
            alert_type=warning.alert_type,
            recommended_action="Use the high-efficacy acceptance path.",
        ),
    )

    for runbook_id, succeeded in ((low.runbook_id, False), (high.runbook_id, True)):
        run_id = identifier("RUN-RUNBOOK")
        incident_id = identifier("INC-RUNBOOK")
        complete_acceptance_run(
            repository,
            alert=warning,
            triage=stable_triage,
            run_id=run_id,
            incident_id=incident_id,
        )
        repository.record_runbook_selection(run_id, runbook_id)
        score = repository.record_runbook_outcome(run_id, succeeded)
        require(score is not None, "runbook outcome did not return a score")
        if runbook_id == low.runbook_id:
            unchanged = repository.record_runbook_outcome(run_id, True)
            require(unchanged is not None, "idempotent runbook outcome lookup failed")
            require(unchanged.success_count == 0, "runbook outcome was overwritten")
            require(unchanged.failure_count == 1, "recorded runbook failure was lost")

    selected = repository.select_runbook(warning)
    require(selected is not None, "no runbook was selected")
    require(selected.runbook_id == high.runbook_id, "lower-efficacy runbook was selected")
    low_score = repository.get_runbook_score(low.runbook_id)
    require(low_score is not None, "lower-efficacy runbook score was not found")
    require(
        selected.efficacy_score > low_score.efficacy_score,
        "runbook efficacy ordering was not preserved",
    )

    print(
        json.dumps(
            {
                "noise_suppression": suppression_results,
                "replayed_first_suppressed": replayed_first.notification_suppressed,
                "concurrent_suppression_count": concurrent_suppression.count(True),
                "selected_runbook_id": selected.runbook_id,
                "selected_efficacy_score": selected.efficacy_score,
                "status": "passed",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
