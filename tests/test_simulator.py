import io
import json
import sys
from types import SimpleNamespace

from botocore.credentials import Credentials

from deja import simulator


def test_base_url_rejects_non_http_schemes() -> None:
    assert simulator.validated_base_url(" https://example.com/ ") == "https://example.com"

    for invalid_url in (
        "file:///etc/passwd",
        "https://example.com?target=other",
        "https://example.com#fragment",
    ):
        try:
            simulator.validated_base_url(invalid_url)
        except ValueError as error:
            assert str(error) == "Deja base URL must use http or https"
        else:
            raise AssertionError(f"{invalid_url} should have been rejected")


def test_signed_headers_add_lambda_authorization(monkeypatch) -> None:
    session = SimpleNamespace(get_credentials=lambda: Credentials("test-access", "test-secret"))
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


def test_submit_alert_polls_queued_run_until_completion(monkeypatch) -> None:
    responses = iter(
        [
            io.BytesIO(
                json.dumps(
                    {
                        "run_id": "RUN-TEST",
                        "status": "queued",
                        "status_url": "/runs/RUN-TEST",
                    }
                ).encode()
            ),
            io.BytesIO(
                json.dumps(
                    {
                        "run_id": "RUN-TEST",
                        "status": "running",
                    }
                ).encode()
            ),
            io.BytesIO(
                json.dumps(
                    {
                        "run_id": "RUN-TEST",
                        "status": "completed",
                    }
                ).encode()
            ),
        ]
    )
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda _request, timeout: next(responses),
    )
    monkeypatch.setattr("deja.simulator.time.sleep", lambda _seconds: None)

    result = simulator.submit_alert(
        "http://localhost:8000",
        {"service": "payments-api"},
    )

    assert result["status"] == "completed"
