from types import SimpleNamespace

import pytest

from deja.models import Alert
from deja.triage import GroqTriager, TriageError


class FakeCompletions:
    def create(self, **kwargs):
        assert kwargs["response_format"] == {"type": "json_object"}
        content = """{
          "diagnosis": "The database connection pool is likely exhausted after the deploy.",
          "confidence": 0.82,
          "severity": "critical",
          "recommended_action": "Roll back the latest deploy and inspect pool saturation.",
          "rationale": "The error spike and pool wait time rose together after deployment.",
          "escalate": true,
          "postmortem_summary": "A deploy correlated with connection pool saturation and HTTP 500s."
        }"""
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )


class FakeClient:
    def __init__(self) -> None:
        self.chat = SimpleNamespace(completions=FakeCompletions())


class InvalidCompletions:
    def __init__(self) -> None:
        self.calls = 0

    def create(self, **_kwargs):
        self.calls += 1
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"confidence": 2}'))]
        )


def test_triager_validates_json_response() -> None:
    alert = Alert(
        service="payments-api",
        alert_type="http-500-spike",
        severity="critical",
        message="500s and pool wait time rose after deploy",
    )
    triager = GroqTriager(api_key="unused", model="test", client=FakeClient())

    decision = triager.triage(alert, [])

    assert decision.confidence == 0.82
    assert decision.escalate is True


def test_triager_retries_invalid_structured_output_then_fails() -> None:
    completions = InvalidCompletions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    triager = GroqTriager(api_key="unused", model="test", client=client)
    alert = Alert(
        service="payments-api",
        alert_type="http-500-spike",
        severity="critical",
        message="500s rose after deploy",
    )

    with pytest.raises(TriageError, match="invalid triage data"):
        triager.triage(alert, [])

    assert completions.calls == 2
