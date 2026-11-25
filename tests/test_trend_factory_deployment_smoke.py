import io
import json
import unittest
from unittest.mock import patch

from scripts.check_trend_factory_deployment import (
    check_deployment, validate_base_url, validate_health,
)


class FakeResponse:
    def __init__(self, payload, content_type="application/json", status=200):
        self.body = io.BytesIO(payload)
        self.headers = {"Content-Type": content_type}
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, amount):
        return self.body.read(amount)


class TrendFactoryDeploymentSmokeTests(unittest.TestCase):
    def setUp(self):
        self.healthy = {
            "status": "ok",
            "ready": True,
            "storage_persistent": True,
            "storage_mode": "persistent_disk",
            "web_auth_configured": True,
            "perplexity_configured": True,
            "publishing_enabled": False,
            "revision": "9540dde0ed20",
        }

    def test_only_https_origin_is_accepted(self):
        self.assertEqual(validate_base_url("https://example.test/"), "https://example.test")
        for bad in ("http://example.test", "https://user:pass@example.test",
                    "https://example.test/health", "https://example.test/?secret=1",
                    "https://example.test/#token", "example.test"):
            with self.subTest(url=bad), self.assertRaises(ValueError):
                validate_base_url(bad)

    def test_healthy_payload_passes_revision_check(self):
        self.assertEqual(validate_health(self.healthy, expected_revision="9540dde0ed20839e"), [])

    def test_wrong_revision_fails_closed(self):
        self.assertIn("Deployed revision differs from expected commit.",
                      validate_health(self.healthy, expected_revision="abcdef012345"))

    def test_missing_or_disabled_safety_controls_fail(self):
        for key, value in (
            ("ready", False), ("storage_persistent", False),
            ("storage_mode", "ephemeral_fallback"),
            ("web_auth_configured", False), ("perplexity_configured", False),
            ("publishing_enabled", True),
        ):
            with self.subTest(key=key):
                payload = {**self.healthy, key: value}
                self.assertTrue(validate_health(payload), key)

    def test_malformed_payload_fails(self):
        self.assertTrue(validate_health([]))
        self.assertTrue(validate_health(None))

    def test_valid_http_response_passes(self):
        response = FakeResponse(json.dumps(self.healthy).encode())
        with patch("scripts.check_trend_factory_deployment.urlopen", return_value=response) as mocked:
            self.assertEqual(check_deployment("https://example.test", expected_revision="9540dde0ed20"), [])
        self.assertEqual(mocked.call_args.args[0].full_url, "https://example.test/health")

    def test_non_json_response_fails(self):
        with patch("scripts.check_trend_factory_deployment.urlopen",
                   return_value=FakeResponse(b"<html></html>", content_type="text/html")):
            self.assertTrue(check_deployment("https://example.test"))

    def test_invalid_json_response_fails(self):
        with patch("scripts.check_trend_factory_deployment.urlopen",
                   return_value=FakeResponse(b"not json")):
            self.assertTrue(check_deployment("https://example.test"))

    def test_oversized_response_fails(self):
        with patch("scripts.check_trend_factory_deployment.urlopen",
                   return_value=FakeResponse(b" " * 16385)):
            self.assertIn("Health response exceeds 16 KiB.",
                          check_deployment("https://example.test"))

    def test_network_failure_returns_safe_error(self):
        from urllib.error import URLError
        with patch("scripts.check_trend_factory_deployment.urlopen", side_effect=URLError("secret")):
            result = check_deployment("https://example.test")
        self.assertEqual(result, ["Health request failed: URLError."])


if __name__ == "__main__":
    unittest.main()
