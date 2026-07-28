from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send a simulated alert to Deja")
    parser.add_argument("url", help="Deja base URL, for example http://localhost:8000")
    parser.add_argument(
        "--aws-profile",
        help="Sign a Lambda Function URL request with this local AWS profile",
    )
    parser.add_argument("--aws-region", default="ap-south-1")
    parser.add_argument("--service", default="payments-api")
    parser.add_argument("--alert-type", default="http-500-spike")
    parser.add_argument("--severity", choices=("info", "warning", "critical"), default="critical")
    parser.add_argument(
        "--message",
        default="HTTP 500 rate exceeded 18% after deploy; database pool wait time is rising",
    )
    return parser.parse_args()


def signed_headers(
    *,
    method: str = "POST",
    url: str,
    body: bytes,
    profile: str,
    region: str,
) -> dict[str, str]:
    import boto3
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest

    session = boto3.Session(profile_name=profile, region_name=region)
    credentials = session.get_credentials()
    if credentials is None:
        raise SystemExit(f"AWS profile {profile!r} has no usable credentials")
    request = AWSRequest(
        method=method,
        url=url,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    SigV4Auth(credentials.get_frozen_credentials(), "lambda", region).add_auth(request)
    return {str(key): str(value) for key, value in request.headers.items()}


def validated_base_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlparse(normalized)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Deja base URL must use http or https")
    return normalized


def submit_alert(
    base_url: str,
    payload: dict[str, Any],
    *,
    aws_profile: str | None = None,
    aws_region: str = "ap-south-1",
    wait_timeout: int = 240,
) -> dict[str, Any]:
    base_url = validated_base_url(base_url)
    url = f"{base_url}/alerts"
    body = json.dumps(payload).encode()
    headers: dict[str, Any] = {"Content-Type": "application/json"}
    if aws_profile:
        headers = signed_headers(
            url=url,
            body=body,
            profile=aws_profile,
            region=aws_region,
        )
    request = urllib.request.Request(
        url,
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:  # nosec B310
            result = json.load(response)
    except urllib.error.HTTPError as error:
        error_body = error.read().decode(errors="replace")
        raise SystemExit(f"Deja returned HTTP {error.code}: {error_body}") from None
    if result.get("status") != "queued" or not result.get("status_url"):
        return result

    status_url = f"{base_url}{result['status_url']}"
    deadline = time.monotonic() + wait_timeout
    while time.monotonic() < deadline:
        headers = {}
        if aws_profile:
            headers = signed_headers(
                method="GET",
                url=status_url,
                body=b"",
                profile=aws_profile,
                region=aws_region,
            )
        status_request = urllib.request.Request(
            status_url,
            headers=headers,
            method="GET",
        )
        try:
            with urllib.request.urlopen(status_request, timeout=30) as response:  # nosec B310
                current = json.load(response)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                time.sleep(2)
                continue
            error_body = error.read().decode(errors="replace")
            raise SystemExit(f"Deja returned HTTP {error.code}: {error_body}") from None
        if current.get("status") == "completed":
            return current
        if current.get("status") == "failed":
            raise SystemExit(f"Deja run {current.get('run_id')} failed")
        time.sleep(2)
    raise SystemExit(f"Deja run {result.get('run_id')} did not complete before timeout")


def main() -> None:
    args = parse_args()
    payload = {
        "service": args.service,
        "alert_type": args.alert_type,
        "severity": args.severity,
        "message": args.message,
        "labels": {"environment": "production", "region": "ap-south-1"},
    }
    result = submit_alert(
        args.url,
        payload,
        aws_profile=args.aws_profile,
        aws_region=args.aws_region,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
