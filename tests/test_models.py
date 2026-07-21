import pytest
from pydantic import ValidationError

from deja.models import Alert


def test_fingerprint_is_stable_across_label_order() -> None:
    first = Alert(
        service="payments-api",
        alert_type="http-500-spike",
        severity="critical",
        message="first observation",
        labels={"region": "ap-south-1", "environment": "production"},
    )
    second = Alert(
        service="payments-api",
        alert_type="http-500-spike",
        severity="warning",
        message="later observation",
        labels={"environment": "production", "region": "ap-south-1"},
    )

    assert first.fingerprint() == second.fingerprint()


def test_fingerprint_changes_with_incident_identity() -> None:
    base = Alert(
        service="payments-api",
        alert_type="http-500-spike",
        severity="critical",
        message="observation",
    )
    changed = base.model_copy(update={"service": "checkout-api"})

    assert base.fingerprint() != changed.fingerprint()


@pytest.mark.parametrize("field", ["service", "alert_type"])
def test_identifiers_reject_whitespace_only_values(field: str) -> None:
    payload = {
        "service": "payments-api",
        "alert_type": "http-500-spike",
        "severity": "critical",
        "message": "observation",
    }
    payload[field] = "   "

    with pytest.raises(ValidationError):
        Alert.model_validate(payload)
