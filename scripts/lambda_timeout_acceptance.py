"""Invoke one timeout-injected Lambda run and prove its retry resumes from triage."""

from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from time import time_ns

import boto3

from deja.config import configure_root_certificate
from deja.models import Alert, ChaosSpec, RunExecutionEvent
from deja.repository import IncidentRepository


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--function-name", default="deja-api")
    parser.add_argument("--aws-profile", default="deja")
    parser.add_argument("--aws-region", default="ap-south-1")
    parser.add_argument("--timeout", type=int, default=300)
    return parser.parse_args()


def database_url() -> str:
    value = os.environ.get("DATABASE_URL", "").strip()
    if not value:
        raise SystemExit("DATABASE_URL is required")
    return configure_root_certificate(
        value,
        os.environ.get("DATABASE_CA_CERT", "").strip(),
    )


def main() -> None:
    args = parse_args()
    repository = IncidentRepository(database_url())
    repository.setup_schema()
    session = boto3.Session(
        profile_name=args.aws_profile,
        region_name=args.aws_region,
    )
    client = session.client("lambda")
    configuration = client.get_function_configuration(FunctionName=args.function_name)
    chaos_enabled = (
        configuration.get("Environment", {})
        .get("Variables", {})
        .get("DEJA_CHAOS_ENABLED", "")
        .lower()
        == "true"
    )
    if not chaos_enabled:
        raise SystemExit("Lambda DEJA_CHAOS_ENABLED must be true for this acceptance run")

    alert = Alert(
        service=f"deja-timeout-{uuid.uuid4().hex[:10]}",
        alert_type="connection-pool-saturation",
        severity="critical",
        message="Pool wait time rose from 4 ms to 920 ms after deploy",
        labels={"environment": "timeout-acceptance", "region": args.aws_region},
    )
    event = RunExecutionEvent(
        run_id=f"RUN-{uuid.uuid4().hex[:12].upper()}",
        incident_id=f"INC-{uuid.uuid4().hex[:12].upper()}",
        fingerprint=alert.fingerprint(),
        alert=alert,
        started_at_epoch_ns=time_ns(),
        chaos=ChaosSpec(mode="timeout_once", before_node="triage"),
    )
    response = client.invoke(
        FunctionName=args.function_name,
        InvocationType="Event",
        Payload=json.dumps(event.model_dump(mode="json"), separators=(",", ":")).encode(),
    )
    if response.get("StatusCode") != 202:
        raise RuntimeError("Lambda did not queue the timeout event")

    deadline = time.monotonic() + args.timeout
    record = None
    while time.monotonic() < deadline:
        record = repository.get_run(event.run_id)
        if record is not None and record.status == "completed":
            break
        time.sleep(5)
    if record is None or record.status != "completed":
        raise TimeoutError("timeout-injected run did not complete")

    attempts = repository.get_run_attempts(event.run_id)
    if len(attempts) < 2:
        raise RuntimeError("Lambda did not record a retry attempt")
    if attempts[-1].resumed_from != "triage":
        raise RuntimeError("Lambda retry did not resume from triage")
    if attempts[-1].status != "completed":
        raise RuntimeError("resumed Lambda attempt did not complete")

    print(
        json.dumps(
            {
                "run_id": event.run_id,
                "status": record.status,
                "attempt_count": record.attempt_count,
                "attempts": [attempt.model_dump() for attempt in attempts],
                "resumed_from": attempts[-1].resumed_from,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
