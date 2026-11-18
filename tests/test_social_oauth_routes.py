import base64
from http.client import HTTPConnection
from urllib.parse import urlencode
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from cryptography.fernet import Fernet

from content_engine.social_oauth import OAuthTokenVault
from scripts import run_trend_content_mvp as app


class SocialOAuthRouteTests(unittest.TestCase):
    def test_health_payload_reports_only_a_valid_short_render_revision(self):
        payload = app._health_payload({
            "TAK_SCOUT_PERPLEXITY_API_KEY": "private-key",
            "TAK_WEB_USERNAME": "operator",
            "TAK_WEB_PASSWORD": "private-password",
            "TAK_AUTO_PUBLISHING_ENABLED": "false",
            "RENDER_GIT_COMMIT": "abcdef0123456789abcdef0123456789abcdef01",
        })
        self.assertEqual(payload["revision"], "abcdef012345")
        self.assertTrue(payload["ready"])
        self.assertFalse(payload["publishing_enabled"])
        self.assertNotIn("private-key", json.dumps(payload))
        self.assertNotIn("private-password", json.dumps(payload))
        self.assertIsNone(app._health_payload({"RENDER_GIT_COMMIT": "untrusted"})["revision"])

    def test_oauth_cookie_transport_security_comes_from_registered_callback(self):
        with patch.dict(os.environ, {"TAK_AUTO_PUBLIC_URL": "https://tak-auto.example"}, clear=False):
            self.assertTrue(app._oauth_cookie_is_secure("tiktok"))
        with patch.dict(os.environ, {"TAK_AUTO_PUBLIC_URL": "http://localhost:8765"}, clear=False):
            self.assertFalse(app._oauth_cookie_is_secure("tiktok"))

    def test_editorial_revision_http_flow_keeps_original_until_apply_and_can_revert(self):
        from contextlib import ExitStack
        from types import SimpleNamespace
        from unittest.mock import Mock

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            preview_path = root / "previews.json"
            trend_path = root / "trends.json"
            queue_path = root / "queue.json"
            insights_path = root / "insights.json"
            original = "원문 본문입니다. " * 40
            recommendation = {
                "area": "블로그 본문",
                "original": "본문 분량 부족",
                "proposal": "핵심 설명과 적용 사례를 보완하세요.",
                "reason": "품질 점검 미통과",
            }
            preview_path.write_text(json.dumps([{
                "keyword": "테스트 키워드",
                "knowledge_id": "knowledge-route-test",
                "blog": {"title": "테스트", "body": original, "meta_description": "설명"},
                "shorts": [],
                "threads": [],
                "facebook": {},
                "source_urls": ["https://example.test/source"],
                "editorial_recommendations": [recommendation],
            }], ensure_ascii=False), encoding="utf-8")
            trend_path.write_text("{}", encoding="utf-8")
            environment = {
                "TAK_WEB_USERNAME": "operator",
                "TAK_WEB_PASSWORD": "private-test-password",
                "TAK_AUTO_PUBLIC_URL": "",
                "TAK_AUTO_MEDIA_SIGNING_KEY": "test-signing-key-that-is-at-least-32-chars",
                "TAK_AUTO_PUBLISHING_ENABLED": "false",
            }
            auth = "Basic " + base64.b64encode(b"operator:private-test-password").decode("ascii")
            provider = Mock()
            provider.search.return_value = SimpleNamespace(
                answer=json.dumps({
                    "revised_text": "검토한 수정 본문입니다. " * 40,
                    "changes": ["문장 흐름 보완"],
                    "unresolved_claims": [],
                }, ensure_ascii=False),
                citations=["https://example.test/revision"],
                model="test-model",
            )
            server = app.ThreadingHTTPServer(("127.0.0.1", 0), app.create_handler())
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()

            def post(path, fields):
                body = urlencode(fields)
                connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
                connection.request("POST", path, body=body, headers={
                    "Authorization": auth,
                    "Origin": "http://127.0.0.1:" + str(server.server_address[1]),
                    "Host": "127.0.0.1:" + str(server.server_address[1]),
                    "X-Forwarded-Proto": "http",
                    "Content-Type": "application/x-www-form-urlencoded",
                })
                response = connection.getresponse()
                status = response.status
                response.read()
                connection.close()
                return status

            try:
                with ExitStack() as stack:
                    stack.enter_context(patch.dict(os.environ, environment, clear=False))
                    stack.enter_context(patch.object(app, "PREVIEW_PATH", preview_path))
                    stack.enter_context(patch.object(app, "TREND_PATH", trend_path))
                    stack.enter_context(patch.object(app, "QUEUE_PATH", queue_path))
                    stack.enter_context(patch.object(app, "INSIGHTS_PATH", insights_path))
                    stack.enter_context(patch.object(app, "_read_connection_checks", return_value={}))
                    stack.enter_context(patch.object(app, "_read_oauth_connections", return_value=({}, "")))
                    stack.enter_context(patch.object(app, "_list_media_assets", return_value=[]))
                    stack.enter_context(patch.object(app.PerplexityResearchProvider, "from_environment", return_value=provider))
                    key = app._editorial_recommendation_key(recommendation, "knowledge-route-test")
                    self.assertEqual(post("/editorial/revise", {
                        "preview_index": "0",
                        "recommendation_index": "0",
                        "recommendation_key": key,
                    }), 200)
                    stored = json.loads(preview_path.read_text(encoding="utf-8"))
                    self.assertEqual(stored[0]["blog"]["body"], original)
                    revision = stored[0]["editorial_revisions"][0]
                    self.assertEqual(revision["status"], "pending_review")
                    self.assertEqual(revision["citations"], ["https://example.test/revision"])
                    self.assertEqual(post("/editorial/apply", {
                        "preview_index": "0",
                        "revision_id": revision["revision_id"],
                    }), 200)
                    stored = json.loads(preview_path.read_text(encoding="utf-8"))
                    self.assertNotEqual(stored[0]["blog"]["body"], original)
                    self.assertEqual(stored[0]["editorial_history"][0]["before"], original)
                    self.assertEqual(post("/editorial/revert", {
                        "preview_index": "0",
                        "revision_id": revision["revision_id"],
                    }), 200)
                    stored = json.loads(preview_path.read_text(encoding="utf-8"))
                    self.assertEqual(stored[0]["blog"]["body"], original)
                    self.assertTrue(stored[0]["editorial_history"][0]["reverted_at"])
            finally:
                server.shutdown()
                server.server_close()
                worker.join(timeout=3)

    def test_web_start_callback_state_cookie_and_encrypted_account_save(self):
        with tempfile.TemporaryDirectory() as directory:
            token_path = Path(directory) / "oauth.enc"
            key = Fernet.generate_key().decode("ascii")
            environment = {
                "TAK_WEB_USERNAME": "operator",
                "TAK_WEB_PASSWORD": "private-test-password",
                "TAK_AUTO_PUBLIC_URL": "https://tak-auto-trend-factory.onrender.com",
                "TAK_AUTO_OAUTH_ENCRYPTION_KEY": key,
                "TIKTOK_CLIENT_KEY": "test-client-key",
                "TIKTOK_CLIENT_SECRET": "test-client-secret",
            }
            auth = "Basic " + base64.b64encode(b"operator:private-test-password").decode("ascii")
            server = app.ThreadingHTTPServer(("127.0.0.1", 0), app.create_handler())
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                with patch.dict(os.environ, environment, clear=False), patch.object(app, "OAUTH_TOKENS_PATH", token_path), \
                     patch.object(app.SocialOAuthClient, "authorization_url", return_value="https://www.tiktok.com/authorize?test=1"), \
                     patch.object(app.SocialOAuthClient, "complete", return_value={
                         "tokens": {"access_token": "test-access-token", "refresh_token": "test-refresh-token", "expires_in": 3600},
                         "profile": {"account_id": "tiktok-id", "account_name": "takcreator"},
                         "scopes": "user.info.basic",
                     }) as complete:
                    connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
                    connection.request("GET", "/connections/oauth/tiktok", headers={
                        "Authorization": auth, "X-Forwarded-Proto": "http",
                    })
                    start = connection.getresponse()
                    self.assertEqual(start.status, 303)
                    self.assertEqual(start.getheader("Location"), "https://www.tiktok.com/authorize?test=1")
                    set_cookie = start.getheader("Set-Cookie")
                    self.assertIn("HttpOnly", set_cookie)
                    self.assertIn("SameSite=Lax", set_cookie)
                    self.assertIn("Secure", set_cookie)
                    cookie = set_cookie.split(";", 1)[0]
                    state = cookie.split("=", 1)[1]
                    start.read()

                    # Provider callback without the matching state cookie is rejected.
                    connection.request("GET", f"/connections/oauth/callback/tiktok?code=demo&state={state}", headers={"Cookie": "tak_oauth_tiktok=wrong"})
                    invalid = connection.getresponse()
                    self.assertEqual(invalid.status, 400)
                    invalid.read()
                    complete.assert_not_called()

                    # A same-browser provider callback is allowed even if the IdP does not forward Basic Auth.
                    connection.request("GET", f"/connections/oauth/callback/tiktok?code=demo&state={state}", headers={
                        "Cookie": cookie, "X-Forwarded-Proto": "http",
                    })
                    callback = connection.getresponse()
                    self.assertEqual(callback.status, 303)
                    self.assertEqual(callback.getheader("Location"), "/?connected=tiktok")
                    self.assertIn("Max-Age=0", callback.getheader("Set-Cookie"))
                    self.assertIn("Secure", callback.getheader("Set-Cookie"))
                    callback.read()
                    complete.assert_called_once()
                    connection.close()

                vault = OAuthTokenVault(token_path, key)
                self.assertEqual(vault.public_connections()["tiktok"]["account_name"], "takcreator")
                self.assertEqual(vault.get("tiktok")["refresh_token"], "test-refresh-token")
                self.assertNotIn("test-access-token", token_path.read_text(encoding="ascii"))
            finally:
                server.shutdown()
                server.server_close()
                worker.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
