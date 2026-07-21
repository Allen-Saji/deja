from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from typing import Any


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
        method="POST",
        url=url,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    SigV4Auth(credentials.get_frozen_credentials(), "lambda", region).add_auth(request)
    return {str(key): str(value) for key, value in request.headers.items()}


def main() -> None:
    args = parse_args()
    payload = {
        "service": args.service,
        "alert_type": args.alert_type,
        "severity": args.severity,
        "message": args.message,
        "labels": {"environment": "production", "region": "ap-south-1"},
    }
    url = f"{args.url.rstrip('/')}/alerts"
    body = json.dumps(payload).encode()
    headers: dict[str, Any] = {"Content-Type": "application/json"}
    if args.aws_profile:
        headers = signed_headers(
            url=url,
            body=body,
            profile=args.aws_profile,
            region=args.aws_region,
        )
    request = urllib.request.Request(
        url,
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        body = error.read().decode(errors="replace")
        raise SystemExit(f"Deja returned HTTP {error.code}: {body}") from None
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
