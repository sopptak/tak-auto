import base64
import io
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from content_engine.publishing_queue import QueueStoreError
from scripts import run_trend_content_mvp
from scripts.run_trend_content_mvp import _health_payload


class TrendContentHealthTests(unittest.TestCase):
    def test_generic_html_response_does_not_receive_script_nonce(self):
        captured_headers = []
        response_body = io.BytesIO()
        handler = run_trend_content_mvp.create_handler()
        response = SimpleNamespace(
            send_response=lambda status: None,
            send_header=lambda name, value: captured_headers.append((name, value)),
            end_headers=lambda: None,
            wfile=response_body,
        )
        body = "<script>untrusted()</script><script>also-untrusted()</script>"
        handler._respond(response, body)
        self.assertEqual(response_body.getvalue().decode("utf-8"), body)
        policy = next(value for name, value in captured_headers if name == "Content-Security-Policy")
        self.assertIn("script-src 'none'", policy)

    def test_dashboard_nonce_is_renderer_owned_and_matches_policy(self):
        not_ready = {name: False for name in ("threads", "facebook", "youtube_shorts", "instagram_reels", "tiktok")}
        with (
            patch.object(run_trend_content_mvp, "_read_connection_checks", return_value={}),
            patch.object(run_trend_content_mvp, "_read_oauth_connections", return_value=({}, "")),
            patch.object(run_trend_content_mvp, "_oauth_setup_statuses", return_value={}),
            patch.object(run_trend_content_mvp, "_list_media_assets", return_value=[]),
            patch.object(run_trend_content_mvp, "_publishing_platform_readiness", return_value=not_ready),
            patch.object(run_trend_content_mvp, "load_insights", return_value=[]),
            patch.object(run_trend_content_mvp, "connection_dashboard", return_value=""),
        ):
            body = run_trend_content_mvp._page({}, [], queue_snapshot={})
        self.assertIsInstance(body, run_trend_content_mvp._CSPNonceHTML)
        self.assertEqual(body.count("<script"), 1)
        self.assertIn(f'<script nonce="{body.nonce}">', body)

        captured_headers = []
        response_body = io.BytesIO()
        handler = run_trend_content_mvp.create_handler()
        response = SimpleNamespace(
            send_response=lambda status: None,
            send_header=lambda name, value: captured_headers.append((name, value)),
            end_headers=lambda: None,
            wfile=response_body,
        )
        handler._respond(response, body)
        self.assertEqual(response_body.getvalue().decode("utf-8"), str(body))
        policy = next(value for name, value in captured_headers if name == "Content-Security-Policy")
        self.assertIn(f"script-src 'nonce-{body.nonce}'", policy)

    def test_basic_auth_supports_utf8_and_rejects_blank_credentials(self):
        for user, password, configured_user, configured_password, expected in (
            ("운영자", "비밀번호🔒", "운영자", "비밀번호🔒", True),
            ("운영자", "비밀번호🔒", "operator", "secret", False),
            ("운영자", "틀린암호", "운영자", "비밀번호🔒", False),
            ("operator", "secret", "operator", " \t ", False),
        ):
            header = "Basic " + base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
            self.assertEqual(run_trend_content_mvp._basic_auth_valid(header, configured_user, configured_password), expected)

    def test_local_bind_rejects_partial_auth_configuration(self):
        for username, password in (("operator", ""), ("operator", " \t "), ("", "secret")):
            with self.subTest(username=username, password=password):
                with patch.dict("os.environ", {
                    "TAK_WEB_USERNAME": username,
                    "TAK_WEB_PASSWORD": password,
                }, clear=False), patch.object(run_trend_content_mvp, "ThreadingHTTPServer") as server:
                    with self.assertRaises(SystemExit) as error:
                        run_trend_content_mvp.main(["--host", "127.0.0.1", "--port", "8765"])
                    server.assert_not_called()
                self.assertEqual(error.exception.code, 2)

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
