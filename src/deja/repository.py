from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from threading import Lock
from time import sleep
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from deja.models import (
    Alert,
    NoiseStatus,
    RunAttemptRecord,
    RunbookCreate,
    RunbookScore,
    RunRecord,
    TriageDecision,
)

SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS deja_incidents (
        incident_id STRING PRIMARY KEY,
        fingerprint STRING NOT NULL,
        service STRING NOT NULL,
        alert_type STRING NOT NULL,
        severity STRING NOT NULL,
        message STRING NOT NULL,
        labels JSONB NOT NULL DEFAULT '{}'::JSONB,
        status STRING NOT NULL,
        triage JSONB,
        action_outcome STRING,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS deja_incidents_fingerprint_idx
    ON deja_incidents (fingerprint, created_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS deja_runs (
        run_id STRING PRIMARY KEY,
        incident_id STRING NOT NULL REFERENCES deja_incidents (incident_id),
        status STRING NOT NULL,
        current_step STRING NOT NULL,
        started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        completed_at TIMESTAMPTZ,
        error_type STRING
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS deja_postmortems (
        incident_id STRING PRIMARY KEY REFERENCES deja_incidents (incident_id),
        run_id STRING NOT NULL UNIQUE REFERENCES deja_runs (run_id),
        summary STRING NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    ALTER TABLE deja_runs
    ADD COLUMN IF NOT EXISTS diagnosis_ms INT8
    """,
    """
    ALTER TABLE deja_runs
    ADD COLUMN IF NOT EXISTS precedent_ids JSONB NOT NULL DEFAULT '[]'::JSONB
    """,
    """
    ALTER TABLE deja_runs
    ADD COLUMN IF NOT EXISTS attempt_count INT8 NOT NULL DEFAULT 0
    """,
    """
    ALTER TABLE deja_runs
    ADD COLUMN IF NOT EXISTS execution_token STRING
    """,
    """
    ALTER TABLE deja_runs
    ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMPTZ
    """,
    """
    ALTER TABLE deja_runs
    ADD COLUMN IF NOT EXISTS last_resume_from STRING
    """,
    """
    CREATE TABLE IF NOT EXISTS deja_run_attempts (
        execution_token STRING PRIMARY KEY,
        run_id STRING NOT NULL REFERENCES deja_runs (run_id),
        attempt_number INT8 NOT NULL,
        resumed_from STRING NOT NULL,
        status STRING NOT NULL,
        started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        finished_at TIMESTAMPTZ,
        error_type STRING,
        UNIQUE (run_id, attempt_number)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS deja_run_attempts_run_idx
    ON deja_run_attempts (run_id, attempt_number DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS deja_node_effects (
        run_id STRING NOT NULL REFERENCES deja_runs (run_id),
        node_name STRING NOT NULL,
        result JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (run_id, node_name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS deja_chaos_injections (
        run_id STRING NOT NULL REFERENCES deja_runs (run_id),
        before_node STRING NOT NULL,
        injected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (run_id, before_node)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS deja_alert_noise (
        fingerprint STRING PRIMARY KEY,
        occurrence_count INT8 NOT NULL,
        stable_count INT8 NOT NULL,
        last_triage_signature STRING,
        notification_suppressed BOOL NOT NULL DEFAULT false,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS deja_alert_noise_observations (
        run_id STRING PRIMARY KEY REFERENCES deja_runs (run_id),
        fingerprint STRING NOT NULL,
        triage_signature STRING NOT NULL,
        suppression_eligible BOOL NOT NULL,
        notification_suppressed BOOL NOT NULL,
        observed_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS deja_noise_observations_fingerprint_idx
    ON deja_alert_noise_observations (fingerprint, observed_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS deja_runbooks (
        runbook_id STRING PRIMARY KEY,
        name STRING NOT NULL,
        service STRING NOT NULL,
        alert_type STRING NOT NULL,
        recommended_action STRING NOT NULL,
        enabled BOOL NOT NULL DEFAULT true,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS deja_runbooks_match_idx
    ON deja_runbooks (service, alert_type, enabled)
    """,
    """
    CREATE TABLE IF NOT EXISTS deja_runbook_executions (
        run_id STRING PRIMARY KEY REFERENCES deja_runs (run_id),
        runbook_id STRING NOT NULL REFERENCES deja_runbooks (runbook_id),
        succeeded BOOL,
        selected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        outcome_recorded_at TIMESTAMPTZ
    )
    """,
)


def triage_signature(triage: TriageDecision) -> str:
    evidence = {
        "diagnosis": triage.diagnosis.strip().lower(),
        "recommended_action": triage.recommended_action.strip().lower(),
    }
    encoded = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def next_noise_state(
    *,
    occurrence_count: int,
    stable_count: int,
    last_signature: str | None,
    signature: str,
    eligible: bool,
) -> tuple[int, int, bool]:
    next_occurrence_count = occurrence_count + 1
    if not eligible:
        next_stable_count = 0
    elif last_signature == signature:
        next_stable_count = stable_count + 1
    else:
        next_stable_count = 1
    return (
        next_occurrence_count,
        next_stable_count,
        eligible and next_stable_count >= 3,
    )


class IncidentRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        self._schema_ready = False
        self._schema_lock = Lock()

    @contextmanager
    def _connection(self) -> Iterator[psycopg.Connection[Any]]:
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            yield connection

    def setup_schema(self) -> None:
        if self._schema_ready:
            return
        with self._schema_lock:
            if self._schema_ready:
                return
            with self._connection() as connection:
                for statement in SCHEMA_STATEMENTS:
                    connection.execute(statement)
            self._schema_ready = True

    def check_connection(self) -> None:
        with self._connection() as connection:
            connection.execute("SELECT 1").fetchone()

    def completed_incident_ids(self, incident_ids: list[str]) -> set[str]:
        if not incident_ids:
            return set()
        placeholders = sql.SQL(", ").join(sql.Placeholder() for _incident_id in incident_ids)
        query = sql.SQL(
            """
            SELECT incident_id
            FROM deja_incidents
            WHERE status = 'completed' AND incident_id IN ({placeholders})
            """
        ).format(placeholders=placeholders)
        with self._connection() as connection:
            rows = connection.execute(
                query,
                tuple(incident_ids),
            ).fetchall()
        return {row["incident_id"] for row in rows}

    def reserve_run(
        self,
        *,
        alert: Alert,
        run_id: str,
        incident_id: str,
        fingerprint: str,
    ) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO deja_incidents (
                    incident_id, fingerprint, service, alert_type, severity,
                    message, labels, status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'queued')
                ON CONFLICT (incident_id) DO NOTHING
                """,
                (
                    incident_id,
                    fingerprint,
                    alert.service,
                    alert.alert_type,
                    alert.severity,
                    alert.message,
                    Jsonb(alert.labels),
                ),
            )
            connection.execute(
                """
                INSERT INTO deja_runs (run_id, incident_id, status, current_step)
                VALUES (%s, %s, 'queued', 'queued')
                ON CONFLICT (run_id) DO NOTHING
                """,
                (run_id, incident_id),
            )

    def begin_run(
        self,
        *,
        alert: Alert,
        run_id: str,
        incident_id: str,
        fingerprint: str,
    ) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO deja_incidents (
                    incident_id, fingerprint, service, alert_type, severity,
                    message, labels, status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'triaging')
                ON CONFLICT (incident_id) DO UPDATE SET
                    status = CASE
                        WHEN deja_incidents.status = 'completed'
                            THEN deja_incidents.status
                        ELSE excluded.status
                    END,
                    updated_at = now()
                """,
                (
                    incident_id,
                    fingerprint,
                    alert.service,
                    alert.alert_type,
                    alert.severity,
                    alert.message,
                    Jsonb(alert.labels),
                ),
            )
            connection.execute(
                """
                INSERT INTO deja_runs (run_id, incident_id, status, current_step)
                VALUES (%s, %s, 'running', 'ingest')
                ON CONFLICT (run_id) DO NOTHING
                """,
                (run_id, incident_id),
            )

    def claim_run(
        self,
        *,
        run_id: str,
        execution_token: str,
        resumed_from: str,
        lease_seconds: int,
    ) -> bool:
        lease_expires_at = datetime.now(UTC) + timedelta(seconds=lease_seconds)
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE deja_run_attempts
                SET status = 'lease_expired', finished_at = now()
                WHERE run_id = %s AND status = 'running'
                  AND execution_token != %s
                  AND EXISTS (
                      SELECT 1
                      FROM deja_runs
                      WHERE run_id = %s
                        AND (
                            execution_token IS NULL
                            OR lease_expires_at IS NULL
                            OR lease_expires_at <= now()
                        )
                  )
                """,
                (run_id, execution_token, run_id),
            )
            claimed = connection.execute(
                """
                UPDATE deja_runs
                SET status = 'running',
                    attempt_count = attempt_count + 1,
                    execution_token = %s,
                    lease_expires_at = %s,
                    last_resume_from = %s,
                    error_type = NULL
                WHERE run_id = %s
                  AND (
                      execution_token IS NULL
                      OR lease_expires_at IS NULL
                      OR lease_expires_at <= now()
                  )
                RETURNING attempt_count
                """,
                (
                    execution_token,
                    lease_expires_at,
                    resumed_from,
                    run_id,
                ),
            ).fetchone()
            if claimed is None:
                return False
            connection.execute(
                """
                INSERT INTO deja_run_attempts (
                    execution_token, run_id, attempt_number, resumed_from, status
                ) VALUES (%s, %s, %s, %s, 'running')
                ON CONFLICT (execution_token) DO NOTHING
                """,
                (
                    execution_token,
                    run_id,
                    claimed["attempt_count"],
                    resumed_from,
                ),
            )
        return True

    def renew_run_claim(
        self,
        *,
        run_id: str,
        execution_token: str,
        step: str,
        lease_seconds: int,
    ) -> bool:
        lease_expires_at = datetime.now(UTC) + timedelta(seconds=lease_seconds)
        with self._connection() as connection:
            row = connection.execute(
                """
                UPDATE deja_runs
                SET current_step = %s, lease_expires_at = %s
                WHERE run_id = %s AND execution_token = %s
                RETURNING run_id
                """,
                (step, lease_expires_at, run_id, execution_token),
            ).fetchone()
        return row is not None

    def finish_run_attempt(self, execution_token: str) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE deja_run_attempts
                SET status = 'completed', finished_at = now()
                WHERE execution_token = %s AND status = 'running'
                """,
                (execution_token,),
            )
            connection.execute(
                """
                UPDATE deja_runs
                SET execution_token = NULL, lease_expires_at = NULL
                WHERE execution_token = %s
                """,
                (execution_token,),
            )

    def get_node_effect(self, run_id: str, node_name: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT result
                FROM deja_node_effects
                WHERE run_id = %s AND node_name = %s
                """,
                (run_id, node_name),
            ).fetchone()
        return row["result"] if row else None

    def record_node_effect(
        self,
        run_id: str,
        node_name: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO deja_node_effects (run_id, node_name, result)
                VALUES (%s, %s, %s)
                ON CONFLICT (run_id, node_name) DO NOTHING
                """,
                (run_id, node_name, Jsonb(result)),
            )
            row = connection.execute(
                """
                SELECT result
                FROM deja_node_effects
                WHERE run_id = %s AND node_name = %s
                """,
                (run_id, node_name),
            ).fetchone()
        if row is None:
            raise RuntimeError("node effect did not persist")
        return row["result"]

    def claim_chaos_injection(self, run_id: str, before_node: str) -> bool:
        with self._connection() as connection:
            row = connection.execute(
                """
                INSERT INTO deja_chaos_injections (run_id, before_node)
                VALUES (%s, %s)
                ON CONFLICT (run_id, before_node) DO NOTHING
                RETURNING run_id
                """,
                (run_id, before_node),
            ).fetchone()
        return row is not None

    def record_diagnosis(
        self,
        *,
        run_id: str,
        diagnosis_ms: int,
        precedent_ids: list[str],
    ) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE deja_runs
                SET diagnosis_ms = %s, precedent_ids = %s
                WHERE run_id = %s
                """,
                (max(0, diagnosis_ms), Jsonb(precedent_ids), run_id),
            )

    def record_noise_observation(
        self,
        *,
        run_id: str,
        fingerprint: str,
        severity: str,
        triage: TriageDecision,
    ) -> NoiseStatus:
        for attempt in range(3):
            try:
                return self._record_noise_observation_once(
                    run_id=run_id,
                    fingerprint=fingerprint,
                    severity=severity,
                    triage=triage,
                )
            except psycopg.errors.SerializationFailure:
                if attempt == 2:
                    raise
                sleep(0.05 * (2**attempt))
        raise RuntimeError("noise observation retry loop exhausted")

    def _record_noise_observation_once(
        self,
        *,
        run_id: str,
        fingerprint: str,
        severity: str,
        triage: TriageDecision,
    ) -> NoiseStatus:
        signature = triage_signature(triage)
        eligible = severity != "critical" and not triage.escalate
        with self._connection() as connection:
            inserted = connection.execute(
                """
                INSERT INTO deja_alert_noise_observations (
                    run_id, fingerprint, triage_signature,
                    suppression_eligible, notification_suppressed
                ) VALUES (%s, %s, %s, %s, false)
                ON CONFLICT (run_id) DO NOTHING
                RETURNING run_id
                """,
                (run_id, fingerprint, signature, eligible),
            ).fetchone()

            if inserted:
                row = connection.execute(
                    """
                    INSERT INTO deja_alert_noise (
                        fingerprint, occurrence_count, stable_count,
                        last_triage_signature, notification_suppressed
                    ) VALUES (%s, 1, %s, %s, false)
                    ON CONFLICT (fingerprint) DO UPDATE SET
                        occurrence_count = deja_alert_noise.occurrence_count + 1,
                        stable_count = CASE
                            WHEN %s = false THEN 0
                            WHEN deja_alert_noise.last_triage_signature = %s
                                THEN deja_alert_noise.stable_count + 1
                            ELSE 1
                        END,
                        last_triage_signature = excluded.last_triage_signature,
                        notification_suppressed = CASE
                            WHEN %s = false THEN false
                            WHEN deja_alert_noise.last_triage_signature = %s
                                THEN deja_alert_noise.stable_count + 1 >= 3
                            ELSE false
                        END,
                        updated_at = now()
                    RETURNING occurrence_count, stable_count, notification_suppressed
                    """,
                    (
                        fingerprint,
                        1 if eligible else 0,
                        signature,
                        eligible,
                        signature,
                        eligible,
                        signature,
                    ),
                ).fetchone()
                connection.execute(
                    """
                    UPDATE deja_alert_noise_observations
                    SET notification_suppressed = %s
                    WHERE run_id = %s
                    """,
                    (row["notification_suppressed"], run_id),
                )
            else:
                row = connection.execute(
                    """
                    SELECT ledger.occurrence_count, ledger.stable_count,
                           observation.notification_suppressed
                    FROM deja_alert_noise AS ledger
                    JOIN deja_alert_noise_observations AS observation
                      ON observation.fingerprint = ledger.fingerprint
                    WHERE ledger.fingerprint = %s AND observation.run_id = %s
                    """,
                    (fingerprint, run_id),
                ).fetchone()
            evidence = connection.execute(
                """
                SELECT run_id
                FROM deja_alert_noise_observations
                WHERE fingerprint = %s
                ORDER BY observed_at DESC
                LIMIT 20
                """,
                (fingerprint,),
            ).fetchall()

        return NoiseStatus(
            fingerprint=fingerprint,
            occurrence_count=row["occurrence_count"],
            stable_count=row["stable_count"],
            notification_suppressed=row["notification_suppressed"],
            evidence_run_ids=[item["run_id"] for item in evidence],
        )

    def upsert_runbook(self, runbook_id: str, definition: RunbookCreate) -> RunbookScore:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO deja_runbooks (
                    runbook_id, name, service, alert_type, recommended_action
                ) VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (runbook_id) DO UPDATE SET
                    name = excluded.name,
                    service = excluded.service,
                    alert_type = excluded.alert_type,
                    recommended_action = excluded.recommended_action,
                    enabled = true,
                    updated_at = now()
                """,
                (
                    runbook_id,
                    definition.name,
                    definition.service,
                    definition.alert_type,
                    definition.recommended_action,
                ),
            )
        score = self.get_runbook_score(runbook_id)
        if score is None:
            raise RuntimeError("runbook write did not persist")
        return score

    def select_runbook(self, alert: Alert) -> RunbookScore | None:
        with self._connection() as connection:
            row = connection.execute(
                self._runbook_score_query(
                    """
                    WHERE rb.enabled = true
                      AND rb.service IN (%s, '*')
                      AND rb.alert_type IN (%s, '*')
                    """,
                    """
                    ORDER BY efficacy_score DESC, sample_count DESC,
                             specificity DESC, rb.runbook_id
                    LIMIT 1
                    """,
                ),
                (alert.service, alert.alert_type),
            ).fetchone()
        return RunbookScore.model_validate(row) if row else None

    def get_runbook_score(self, runbook_id: str) -> RunbookScore | None:
        with self._connection() as connection:
            row = connection.execute(
                self._runbook_score_query("WHERE rb.runbook_id = %s", ""),
                (runbook_id,),
            ).fetchone()
        return RunbookScore.model_validate(row) if row else None

    @staticmethod
    def _runbook_score_query(where_clause: str, order_clause: str) -> sql.Composed:
        # Both fragments are private static query clauses selected by the two callers above.
        return sql.SQL(
            """
            SELECT
                rb.runbook_id,
                rb.name,
                rb.service,
                rb.alert_type,
                rb.recommended_action,
                count(*) FILTER (WHERE execution.succeeded = true)::INT8 AS success_count,
                count(*) FILTER (WHERE execution.succeeded = false)::INT8 AS failure_count,
                count(execution.succeeded)::INT8 AS sample_count,
                (
                    (count(*) FILTER (WHERE execution.succeeded = true)) + 1.0
                ) / (count(execution.succeeded) + 2.0) AS efficacy_score,
                (CASE WHEN rb.service = '*' THEN 0 ELSE 1 END
                 + CASE WHEN rb.alert_type = '*' THEN 0 ELSE 1 END) AS specificity
            FROM deja_runbooks AS rb
            LEFT JOIN deja_runbook_executions AS execution
              ON execution.runbook_id = rb.runbook_id
            {where}
            GROUP BY rb.runbook_id, rb.name, rb.service, rb.alert_type,
                     rb.recommended_action
            {order}
            """
        ).format(
            where=sql.SQL(where_clause),
            order=sql.SQL(order_clause),
        )

    def record_runbook_selection(self, run_id: str, runbook_id: str) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO deja_runbook_executions (run_id, runbook_id)
                VALUES (%s, %s)
                ON CONFLICT (run_id) DO NOTHING
                """,
                (run_id, runbook_id),
            )

    def record_runbook_outcome(self, run_id: str, succeeded: bool) -> RunbookScore | None:
        with self._connection() as connection:
            execution = connection.execute(
                """
                SELECT runbook_id, succeeded
                FROM deja_runbook_executions
                WHERE run_id = %s
                FOR UPDATE
                """,
                (run_id,),
            ).fetchone()
            if execution is None:
                return None
            if execution["succeeded"] is None:
                connection.execute(
                    """
                    UPDATE deja_runbook_executions
                    SET succeeded = %s, outcome_recorded_at = now()
                    WHERE run_id = %s AND succeeded IS NULL
                    """,
                    (succeeded, run_id),
                )
        return self.get_runbook_score(execution["runbook_id"])

    def complete_run(
        self,
        *,
        run_id: str,
        incident_id: str,
        triage: TriageDecision,
        action_outcome: str,
        postmortem: str,
    ) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE deja_incidents
                SET status = 'completed', triage = %s, action_outcome = %s, updated_at = now()
                WHERE incident_id = %s
                """,
                (Jsonb(triage.model_dump()), action_outcome, incident_id),
            )
            connection.execute(
                """
                INSERT INTO deja_postmortems (incident_id, run_id, summary)
                VALUES (%s, %s, %s)
                ON CONFLICT (incident_id) DO UPDATE SET
                    run_id = excluded.run_id,
                    summary = excluded.summary,
                    created_at = now()
                """,
                (incident_id, run_id, postmortem),
            )
            connection.execute(
                """
                UPDATE deja_runs
                SET status = 'completed', current_step = 'writeback', completed_at = now()
                WHERE run_id = %s
                """,
                (run_id,),
            )

    def fail_run(
        self,
        run_id: str,
        error_type: str,
        execution_token: str | None = None,
    ) -> None:
        with self._connection() as connection:
            if execution_token is not None:
                connection.execute(
                    """
                    UPDATE deja_run_attempts
                    SET status = 'failed', error_type = %s, finished_at = now()
                    WHERE execution_token = %s AND status = 'running'
                    """,
                    (error_type[:100], execution_token),
                )
            if execution_token is not None:
                connection.execute(
                    """
                    UPDATE deja_runs
                    SET status = 'failed', error_type = %s,
                        execution_token = NULL, lease_expires_at = NULL
                    WHERE run_id = %s AND execution_token = %s
                    """,
                    (error_type[:100], run_id, execution_token),
                )
            else:
                connection.execute(
                    """
                    UPDATE deja_runs
                    SET status = 'failed', error_type = %s,
                        execution_token = NULL, lease_expires_at = NULL
                    WHERE run_id = %s
                    """,
                    (error_type[:100], run_id),
                )

    def get_run(self, run_id: str) -> RunRecord | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT
                    r.run_id,
                    i.incident_id,
                    i.fingerprint,
                    i.service,
                    i.alert_type,
                    i.severity,
                    r.status,
                    r.current_step,
                    r.attempt_count,
                    r.last_resume_from,
                    i.triage,
                    i.action_outcome,
                    p.summary AS postmortem,
                    r.diagnosis_ms,
                    r.precedent_ids,
                    coalesce(noise.notification_suppressed, false)
                        AS notification_suppressed,
                    execution.runbook_id AS selected_runbook_id,
                    r.started_at::STRING AS started_at,
                    r.completed_at::STRING AS completed_at
                FROM deja_runs AS r
                JOIN deja_incidents AS i ON i.incident_id = r.incident_id
                LEFT JOIN deja_postmortems AS p ON p.run_id = r.run_id
                LEFT JOIN deja_alert_noise_observations AS noise ON noise.run_id = r.run_id
                LEFT JOIN deja_runbook_executions AS execution ON execution.run_id = r.run_id
                WHERE r.run_id = %s
                """,
                (run_id,),
            ).fetchone()
        return RunRecord.model_validate(row) if row else None

    def get_run_attempts(self, run_id: str) -> list[RunAttemptRecord]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT
                    attempt_number,
                    resumed_from,
                    status,
                    started_at::STRING AS started_at,
                    finished_at::STRING AS finished_at,
                    error_type
                FROM deja_run_attempts
                WHERE run_id = %s
                ORDER BY attempt_number
                """,
                (run_id,),
            ).fetchall()
        return [RunAttemptRecord.model_validate(row) for row in rows]
