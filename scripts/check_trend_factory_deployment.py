#!/usr/bin/env python3
"""Read-only deployment smoke check for TAK AUTO trend factory.

Example:
  python scripts/check_trend_factory_deployment.py https://example.onrender.com \
      --expect-revision 9540dde0ed20

This command never logs in, creates content, or publishes posts.
"""
from __future__ import annotations

import argparse
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def validate_base_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("A valid HTTPS service URL is required.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Service URL must not contain credentials, query, or fragment.")
    if parsed.path not in ("", "/"):
        raise ValueError("Service URL must be the origin, without a path.")
    return value.rstrip("/")


def validate_health(payload: object, *, expected_revision: str = "") -> list[str]:
    if not isinstance(payload, dict):
        return ["Health response is not a JSON object."]
    failures = []
    if payload.get("status") != "ok":
        failures.append("Health status is not ok.")
    if payload.get("ready") is not True:
        failures.append("Service is not ready.")
    if payload.get("storage_persistent") is not True or payload.get("storage_mode") != "persistent_disk":
        failures.append("Persistent storage is not confirmed.")
    if payload.get("web_auth_configured") is not True:
        failures.append("Web authentication is not configured.")
    if payload.get("perplexity_configured") is not True:
        failures.append("Research API key is not configured.")
    if payload.get("publishing_enabled") is not False:
        failures.append("Public publishing must remain disabled.")
    if expected_revision:
        revision = payload.get("revision")
        if not isinstance(revision, str) or revision.lower() != expected_revision[:12].lower():
            failures.append("Deployed revision differs from expected commit.")
    return failures


def check_deployment(url: str, *, expected_revision: str = "", timeout: float = 10) -> list[str]:
    base = validate_base_url(url)
    request = Request(base + "/health", headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                return [f"Health endpoint returned HTTP {response.status}."]
            if "application/json" not in response.headers.get("Content-Type", "").lower():
                return ["Health endpoint did not return JSON."]
            raw = response.read(16385)
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        return [f"Health request failed: {type(error).__name__}."]
    if len(raw) > 16384:
        return ["Health response exceeds 16 KiB."]
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return ["Health response is not valid JSON."]
    return validate_health(payload, expected_revision=expected_revision)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="HTTPS service origin, without credentials or path")
    parser.add_argument("--expect-revision", default="", help="Expected Git commit SHA (at least 12 hex digits)")
    parser.add_argument("--timeout", type=float, default=10)
    args = parser.parse_args(argv)
    if args.expect_revision and (
        len(args.expect_revision) < 12
        or len(args.expect_revision) > 40
        or any(char not in "0123456789abcdefABCDEF" for char in args.expect_revision)
    ):
        parser.error("--expect-revision must be 12 to 40 hexadecimal characters")
    if not 0 < args.timeout <= 60:
        parser.error("--timeout must be between 0 and 60 seconds")
    try:
        failures = check_deployment(args.url, expected_revision=args.expect_revision, timeout=args.timeout)
    except ValueError as error:
        parser.error(str(error))
    if failures:
        for failure in failures:
            print("FAIL:", failure)
        return 1
    print("PASS: health, readiness, persistent storage, auth, research and publishing gate.")
    print("NOTE: this does not verify persistence across restart, OAuth, content creation or uploads.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
