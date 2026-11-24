import unittest
from unittest.mock import patch

from content_engine.publishing_queue import QueueStoreError
from scripts import run_trend_content_mvp
from scripts.run_trend_content_mvp import _health_payload


class TrendContentHealthTests(unittest.TestCase):
    def test_readiness_requires_persistent_storage(self):
        environ = {
            "TAK_SCOUT_PERPLEXITY_API_KEY": "configured",
            "TAK_WEB_USERNAME": "operator",
            "TAK_WEB_PASSWORD": "configured",
            "TAK_AUTO_PUBLISHING_ENABLED": "false",
        }
        with patch("scripts.run_trend_content_mvp.USING_EPHEMERAL_STORAGE", True):
            payload = _health_payload(environ)
        self.assertEqual(payload["status"], "ok")
        self.assertFalse(payload["storage_persistent"])
        self.assertEqual(payload["storage_mode"], "ephemeral_fallback")
        self.assertFalse(payload["ready"])

    def test_whitespace_only_secrets_do_not_report_service_ready(self):
        environ = {
            "TAK_SCOUT_PERPLEXITY_API_KEY": "   ",
            "TAK_WEB_USERNAME": " operator ",
            "TAK_WEB_PASSWORD": " \t ",
            "TAK_AUTO_PUBLISHING_ENABLED": "false",
        }
        with patch("scripts.run_trend_content_mvp.USING_EPHEMERAL_STORAGE", False):
            payload = _health_payload(environ)
        self.assertFalse(payload["perplexity_configured"])
        self.assertFalse(payload["web_auth_configured"])
        self.assertFalse(payload["ready"])

    def test_external_bind_rejects_whitespace_only_password(self):
        with patch.dict("os.environ", {
            "TAK_WEB_USERNAME": "operator",
            "TAK_WEB_PASSWORD": " \t ",
        }, clear=False):
            with self.assertRaises(SystemExit) as error:
                run_trend_content_mvp.main(["--host", "0.0.0.0", "--port", "8765"])
        self.assertEqual(error.exception.code, 2)

    def test_readiness_requires_publisher_adapter_when_publishing_is_enabled(self):
        environ = {
            "TAK_SCOUT_PERPLEXITY_API_KEY": "configured",
            "TAK_WEB_USERNAME": "operator",
            "TAK_WEB_PASSWORD": "configured",
            "TAK_AUTO_PUBLISHING_ENABLED": "true",
        }
        with patch("scripts.run_trend_content_mvp.USING_EPHEMERAL_STORAGE", False):
            without_adapter = _health_payload(environ)
            with_adapter = _health_payload({**environ, "TAK_AUTO_PUBLISHER": "content_engine.trend_publishers:publish"})
        self.assertTrue(without_adapter["storage_persistent"])
        self.assertFalse(without_adapter["publisher_adapter_configured"])
        self.assertFalse(without_adapter["ready"])
        self.assertTrue(with_adapter["publisher_adapter_configured"])
        self.assertTrue(with_adapter["ready"])

    def test_disabled_publishing_does_not_require_publisher_adapter(self):
        environ = {
            "TAK_SCOUT_PERPLEXITY_API_KEY": "configured",
            "TAK_WEB_USERNAME": "operator",
            "TAK_WEB_PASSWORD": "configured",
            "TAK_AUTO_PUBLISHING_ENABLED": "false",
        }
        with patch("scripts.run_trend_content_mvp.USING_EPHEMERAL_STORAGE", False):
            payload = _health_payload(environ)
        self.assertTrue(payload["storage_persistent"])
        self.assertFalse(payload["publisher_adapter_configured"])
        self.assertTrue(payload["ready"])


    def test_health_revision_is_exposed_only_for_valid_commit_hash(self):
        environ = {
            "TAK_SCOUT_PERPLEXITY_API_KEY": "configured",
            "TAK_WEB_USERNAME": "operator",
            "TAK_WEB_PASSWORD": "configured",
            "TAK_AUTO_PUBLISHING_ENABLED": "false",
        }
        with patch("scripts.run_trend_content_mvp.USING_EPHEMERAL_STORAGE", False):
            valid = _health_payload({**environ, "RENDER_GIT_COMMIT": "A" * 40})
            invalid = _health_payload({**environ, "RENDER_GIT_COMMIT": "not-a-commit"})
        self.assertEqual(valid["revision"], "a" * 12)
        self.assertIsNone(invalid["revision"])

    def test_health_never_exposes_authentication_or_provider_secrets(self):
        secrets = {
            "TAK_SCOUT_PERPLEXITY_API_KEY": "perplexity-secret-value",
            "TAK_WEB_USERNAME": "operator-secret-value",
            "TAK_WEB_PASSWORD": "password-secret-value",
            "TAK_AUTO_OAUTH_ENCRYPTION_KEY": "encryption-secret-value",
            "TAK_AUTO_MEDIA_SIGNING_KEY": "signing-secret-value",
            "TAK_AUTO_PUBLISHING_ENABLED": "false",
        }
        with patch("scripts.run_trend_content_mvp.USING_EPHEMERAL_STORAGE", False):
            payload = _health_payload(secrets)
        import json
        serialized = json.dumps(payload, ensure_ascii=False)
        for value in secrets.values():
            if value != "false":
                self.assertNotIn(value, serialized)
        self.assertTrue(payload["ready"])

    def test_only_explicit_true_enables_publishing_readiness_requirement(self):
        base = {
            "TAK_SCOUT_PERPLEXITY_API_KEY": "configured",
            "TAK_WEB_USERNAME": "operator",
            "TAK_WEB_PASSWORD": "configured",
        }
        with patch("scripts.run_trend_content_mvp.USING_EPHEMERAL_STORAGE", False):
            for setting in ("false", "0", "yes", "TRUE-ish", ""):
                with self.subTest(setting=setting):
                    payload = _health_payload({**base, "TAK_AUTO_PUBLISHING_ENABLED": setting})
                    self.assertFalse(payload["publishing_enabled"])
                    self.assertTrue(payload["ready"])
            enabled = _health_payload({**base, "TAK_AUTO_PUBLISHING_ENABLED": " TRUE "})
        self.assertTrue(enabled["publishing_enabled"])
        self.assertFalse(enabled["ready"])

    def test_postgres_readiness_reports_queue_outage_without_exposing_credentials(self):
        env = {
            "TAK_AUTO_QUEUE_BACKEND": "postgres",
            "TAK_AUTO_QUEUE_DSN": "test-private-database-string",
            "TAK_WEB_USERNAME": "operator",
            "TAK_WEB_PASSWORD": "configured",
            "TAK_SCOUT_PERPLEXITY_API_KEY": "configured",
        }
        with patch.object(run_trend_content_mvp, "USING_EPHEMERAL_STORAGE", False), \
                patch.object(run_trend_content_mvp, "open_publishing_queue") as open_queue:
            queue = open_queue.return_value
            queue.storage_ready.side_effect = QueueStoreError("database unavailable")
            unavailable = _health_payload(env)
            queue.storage_ready.side_effect = None
            queue.storage_ready.return_value = True
            available = _health_payload(env)

        self.assertFalse(unavailable["ready"])
        self.assertFalse(unavailable["queue_ready"])
        self.assertEqual(available["queue_backend"], "postgres")
        self.assertTrue(available["queue_ready"])
        self.assertTrue(available["ready"])
        self.assertNotIn(env["TAK_AUTO_QUEUE_DSN"], str(available))

if __name__ == "__main__":
    unittest.main()
