import base64
from http.client import HTTPConnection
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
