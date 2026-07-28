"""Prove novel-then-recalled behavior through the deployed HTTP API."""

from __future__ import annotations

import argparse
import json
import uuid

from deja.simulator import submit_alert


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="Deja base URL")
    parser.add_argument("--aws-profile", default="deja")
    parser.add_argument("--aws-region", default="ap-south-1")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    session = uuid.uuid4().hex[:10]
    payload = {
        "service": f"deja-replay-{session}",
        "alert_type": "connection-pool-saturation",
        "severity": "critical",
        "message": (
            "HTTP 500 rate reached 18 percent after deploy; database connection pool "
            "wait time rose from 4 ms to 920 ms"
        ),
        "labels": {"environment": "acceptance", "region": args.aws_region},
    }
    request_options = {
        "aws_profile": args.aws_profile,
        "aws_region": args.aws_region,
    }
    novel = submit_alert(args.url, payload, **request_options)
    replay = submit_alert(args.url, payload, **request_options)

    require(novel["status"] == "completed", "novel incident did not complete")
    require(novel["precedent_ids"] == [], "novel incident unexpectedly recalled a precedent")
    require(replay["status"] == "completed", "replayed incident did not complete")
    require(
        novel["incident_id"] in replay["precedent_ids"],
        "replayed incident did not retrieve the novel incident",
    )
    require(
        novel["incident_id"] in replay["triage"]["cited_incident_ids"],
        "replayed diagnosis did not cite the retrieved incident",
    )

    print(
        json.dumps(
            {
                "novel_run_id": novel["run_id"],
                "novel_incident_id": novel["incident_id"],
                "novel_diagnosis_ms": novel["diagnosis_ms"],
                "replay_run_id": replay["run_id"],
                "replay_diagnosis_ms": replay["diagnosis_ms"],
                "replay_citations": replay["triage"]["cited_incident_ids"],
                "status": "passed",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
