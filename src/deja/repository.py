from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from deja.models import Alert, RunRecord, TriageDecision

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
)


class IncidentRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    @contextmanager
    def _connection(self) -> Iterator[psycopg.Connection[Any]]:
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            yield connection

    def setup_schema(self) -> None:
        with self._connection() as connection:
            for statement in SCHEMA_STATEMENTS:
                connection.execute(statement)

    def check_connection(self) -> None:
        with self._connection() as connection:
            connection.execute("SELECT 1").fetchone()

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
                    status = excluded.status,
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
                ON CONFLICT (run_id) DO UPDATE SET
                    status = excluded.status,
                    current_step = excluded.current_step,
                    error_type = NULL
                """,
                (run_id, incident_id),
            )

    def record_step(self, run_id: str, step: str) -> None:
        with self._connection() as connection:
            connection.execute(
                "UPDATE deja_runs SET current_step = %s WHERE run_id = %s",
                (step, run_id),
            )

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

    def fail_run(self, run_id: str, error_type: str) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE deja_runs
                SET status = 'failed', error_type = %s
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
                    i.triage,
                    i.action_outcome,
                    p.summary AS postmortem,
                    r.started_at::STRING AS started_at,
                    r.completed_at::STRING AS completed_at
                FROM deja_runs AS r
                JOIN deja_incidents AS i ON i.incident_id = r.incident_id
                LEFT JOIN deja_postmortems AS p ON p.run_id = r.run_id
                WHERE r.run_id = %s
                """,
                (run_id,),
            ).fetchone()
        return RunRecord.model_validate(row) if row else None
