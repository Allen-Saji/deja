import io
import json
import sys
from types import SimpleNamespace

from botocore.credentials import Credentials

from deja import simulator


def test_signed_headers_add_lambda_authorization(monkeypatch) -> None:
    session = SimpleNamespace(
        get_credentials=lambda: Credentials("test-access", "test-secret")
    )
    monkeypatch.setattr("boto3.Session", lambda **_kwargs: session)

    headers = simulator.signed_headers(
        url="https://example.lambda-url.ap-south-1.on.aws/alerts",
        body=b"{}",
        profile="deja",
        region="ap-south-1",
    )

    assert headers["Authorization"].startswith("AWS4-HMAC-SHA256")
    assert "X-Amz-Date" in headers


def test_main_sends_unsigned_alert_and_prints_result(monkeypatch, capsys) -> None:
    response = io.BytesIO(json.dumps({"status": "completed"}).encode())
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda _request, timeout: response,
    )
    monkeypatch.setattr(sys, "argv", ["deja-simulate", "http://localhost:8000"])

    simulator.main()

    assert json.loads(capsys.readouterr().out) == {"status": "completed"}
