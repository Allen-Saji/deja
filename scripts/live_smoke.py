"""Run one real P1 workflow against configured Groq and CockroachDB services."""

import json

from deja.app import get_service
from deja.models import Alert


def main() -> None:
    alert = Alert(
        service="payments-api",
        alert_type="http-500-spike",
        severity="critical",
        message=(
            "HTTP 500 rate reached 18 percent after deploy 2026.07.21.3; "
            "database connection pool wait time rose from 4 ms to 920 ms"
        ),
        labels={"environment": "production", "region": "ap-south-1"},
    )
    result = get_service().process_alert(alert)
    print(
        json.dumps(
            {
                "run_id": result.run_id,
                "incident_id": result.incident_id,
                "status": result.status,
                "steps": result.steps,
                "diagnosis": result.triage.diagnosis,
                "action_outcome": result.action_outcome,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
