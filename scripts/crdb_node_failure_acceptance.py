"""Prove a Deja run completes while one node in a three-node CockroachDB cluster is down."""

from __future__ import annotations

import json
import shutil
import subprocess  # nosec B404
import time
from pathlib import Path

import psycopg

from deja.models import Alert, Precedent, TriageDecision
from deja.repository import IncidentRepository
from deja.workflow import IncidentService

# The executable is resolved explicitly and subprocess never invokes a shell.
ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = ROOT / "deploy" / "chaos-compose.yml"
DATABASE_URL = "postgresql://root@localhost:26258/defaultdb?sslmode=disable"


def compose(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    docker = shutil.which("docker")
    if docker is None:
        raise RuntimeError("docker is required for the node-failure acceptance")
    # Every argument is selected by this acceptance script.
    return subprocess.run(  # nosec B603
        [docker, "compose", "-f", str(COMPOSE_FILE), *arguments],
        check=check,
        cwd=ROOT,
        text=True,
        capture_output=True,
    )


def initialize_cluster() -> None:
    compose("up", "-d")
    result = compose(
        "exec",
        "-T",
        "crdb-1",
        "./cockroach",
        "init",
        "--insecure",
        "--host=crdb-1:26357",
        check=False,
    )
    combined = f"{result.stdout}\n{result.stderr}".lower()
    if result.returncode and "already been initialized" not in combined:
        raise RuntimeError("CockroachDB cluster initialization failed")


def wait_for_sql(timeout_seconds: int = 90) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with psycopg.connect(DATABASE_URL) as connection:
                connection.execute("SELECT 1").fetchone()
            return
        except psycopg.OperationalError:
            time.sleep(2)
    raise TimeoutError("CockroachDB SQL endpoint did not become ready")


def wait_for_three_replicas(timeout_seconds: int = 90) -> None:
    deadline = time.monotonic() + timeout_seconds
    query = """
        SELECT min(array_length(replicas, 1)) AS replica_count
        FROM [SHOW RANGES FROM TABLE deja_runs]
    """
    while time.monotonic() < deadline:
        with psycopg.connect(DATABASE_URL) as connection:
            row = connection.execute(query).fetchone()
        if row and row[0] is not None and row[0] >= 3:
            return
        time.sleep(2)
    raise TimeoutError("Deja ranges did not reach three replicas")


class StaticTriager:
    def triage(self, _alert: Alert, _precedents: list[Precedent]) -> TriageDecision:
        return TriageDecision(
            diagnosis="Connection pool saturation after deploy",
            confidence=0.95,
            severity="critical",
            recommended_action="Roll back the latest deploy",
            rationale="Pool wait time rose immediately after the deploy",
            escalate=True,
            postmortem_summary="The deploy exhausted the database connection pool.",
        )


class StaticMemory:
    def setup(self) -> None:
        pass

    def recall(self, _alert: Alert, *, limit: int = 3) -> list[Precedent]:
        return []

    def remember(self, **_kwargs) -> None:
        pass


def main() -> None:
    initialize_cluster()
    wait_for_sql()
    repository = IncidentRepository(DATABASE_URL)
    service = IncidentService(
        database_url=DATABASE_URL,
        repository=repository,
        triager=StaticTriager(),
        memory=StaticMemory(),
    )
    alert = Alert(
        service="chaos-payments-api",
        alert_type="connection-pool-saturation",
        severity="critical",
        message="Pool wait time rose from 4 ms to 920 ms after deploy",
        labels={"environment": "node-failure-acceptance"},
    )
    _accepted, event = service.prepare_alert(alert)
    wait_for_three_replicas()
    node_was_killed = False

    def kill_second_node(_run_id: str, before_node: str) -> None:
        nonlocal node_was_killed
        if before_node != "triage" or node_was_killed:
            return
        compose("kill", "crdb-2")
        node_was_killed = True

    try:
        result = service.execute_run(
            event,
            execution_token=event.run_id,
            failure_hook=kill_second_node,
        )
        if result is None:
            raise RuntimeError("chaos run did not acquire its execution lease")
        record = repository.get_run(event.run_id)
        if not node_was_killed or record is None or record.status != "completed":
            raise RuntimeError("run did not complete during the node failure")
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute("SELECT 1").fetchone()
        print(
            json.dumps(
                {
                    "run_id": event.run_id,
                    "status": record.status,
                    "steps": result.steps,
                    "failed_node": "crdb-2",
                    "surviving_sql_check": "passed",
                },
                indent=2,
            )
        )
    finally:
        if node_was_killed:
            compose("start", "crdb-2")


if __name__ == "__main__":
    main()
