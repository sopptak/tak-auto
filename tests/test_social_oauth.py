import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from urllib.parse import parse_qs, urlsplit

from cryptography.fernet import Fernet

from content_engine.social_oauth import (
    OAuthFlowRegistry, OAuthTokenVault, PROVIDERS, SocialOAuthClient, SocialOAuthError,
    callback_uri, setup_status,
)


class SocialOAuthTests(unittest.TestCase):
    def setUp(self):
        self.key = Fernet.generate_key().decode("ascii")
        self.environ = {
            "TAK_AUTO_PUBLIC_URL": "https://tak-auto-trend-factory.onrender.com",
            "TAK_AUTO_OAUTH_ENCRYPTION_KEY": self.key,
            "META_GRAPH_API_VERSION": "v27.0",
            "YOUTUBE_OAUTH_CLIENT_ID": "google-client",
            "YOUTUBE_OAUTH_CLIENT_SECRET": "google-secret",
            "TIKTOK_CLIENT_KEY": "tiktok-key",
            "TIKTOK_CLIENT_SECRET": "tiktok-secret",
            "INSTAGRAM_APP_ID": "instagram-id",
            "INSTAGRAM_APP_SECRET": "instagram-secret",
            "FACEBOOK_APP_ID": "facebook-id",
            "FACEBOOK_APP_SECRET": "facebook-secret",
            "THREADS_APP_ID": "threads-id",
            "THREADS_APP_SECRET": "threads-secret",
            "NAVER_LOGIN_CLIENT_ID": "naver-id",
            "NAVER_LOGIN_CLIENT_SECRET": "naver-secret",
        }

    def test_all_dashboard_social_accounts_have_configurable_web_oauth(self):
        self.assertEqual(set(PROVIDERS), {"youtube_shorts", "tiktok", "instagram_reels", "facebook", "threads", "blog"})
        for platform in PROVIDERS:
            with self.subTest(platform=platform):
                status = setup_status(platform, self.environ)
                self.assertTrue(status["ready"], status)
                self.assertEqual(status["redirect_uri"], callback_uri(platform, self.environ))

    def test_oauth_setup_requires_client_credentials_https_callback_and_encryption_key(self):
        status = setup_status("tiktok", {})
        self.assertFalse(status["ready"])
        self.assertIn("TAK_AUTO_PUBLIC_URL (HTTPS 주소)", status["missing"])
        self.assertIn("TAK_AUTO_OAUTH_ENCRYPTION_KEY", status["missing"])
        self.assertIn("TIKTOK_CLIENT_KEY", status["missing"])
        bad = dict(self.environ, TAK_AUTO_PUBLIC_URL="https://example.test/path")
        self.assertFalse(setup_status("blog", bad)["ready"])

    def test_callback_url_validation_rejects_malformed_authorities(self):
        for value in (
            "https://example.test:bad", "https://example.test:", "https://example.test:0",
            "https://user:password@example.test", "https://example.test?query=1",
            "https://example.test#fragment", "https://bad host.test", "https://[::1",
        ):
            with self.subTest(value=value), self.assertRaises(SocialOAuthError):
                callback_uri("tiktok", dict(self.environ, TAK_AUTO_PUBLIC_URL=value))

    def test_authorization_url_has_state_and_provider_scopes(self):
        cases = {
            "youtube_shorts": ("accounts.google.com", "youtube.readonly"),
            "tiktok": ("www.tiktok.com", "user.info.basic"),
            "instagram_reels": ("www.instagram.com", "instagram_business_basic"),
            "facebook": ("www.facebook.com", "pages_show_list"),
            "threads": ("threads.net", "threads_basic"),
            "blog": ("nid.naver.com", "response_type"),
        }
        publishing_scopes = {
            "youtube_shorts": "youtube.upload",
            "tiktok": "video.publish",
            "instagram_reels": "instagram_business_content_publishing",
            "facebook": "pages_manage_posts",
            "threads": "threads_content_publish",
        }
        client = SocialOAuthClient(self.environ)
        for platform, (host, expected) in cases.items():
            with self.subTest(platform=platform):
                redirect = callback_uri(platform, self.environ)
                url = client.authorization_url(platform, redirect, "state-test", "verifier-test")
                parsed = urlsplit(url)
                params = parse_qs(parsed.query)
                self.assertEqual(parsed.hostname, host)
                self.assertEqual(params["state"], ["state-test"])
                self.assertEqual(params["redirect_uri"], [redirect])
                self.assertIn(expected, params.get("scope", ["response_type"])[0])
                if platform in publishing_scopes:
                    if platform in {"threads", "instagram_reels", "tiktok"}:
                        self.assertIn(publishing_scopes[platform], params["scope"][0])
                    else:
                        self.assertNotIn(publishing_scopes[platform], params["scope"][0])

    def test_oauth_state_is_cookie_bound_single_use_and_provider_bound(self):
        registry = OAuthFlowRegistry(now=lambda: datetime(2026, 11, 17, tzinfo=timezone.utc))
        state, entry = registry.create("youtube_shorts", "https://example.test/callback", verifier="pkce")
        self.assertEqual(entry["verifier"], "pkce")
        with self.assertRaisesRegex(SocialOAuthError, "로그인 요청"):
            registry.consume("youtube_shorts", state, "another-state")
        self.assertEqual(registry.consume("youtube_shorts", state, state)["platform"], "youtube_shorts")
        with self.assertRaisesRegex(SocialOAuthError, "만료되었거나 이미 사용"):
            registry.consume("youtube_shorts", state, state)

    def test_vault_encrypts_tokens_returns_only_public_profile_and_disconnects(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tokens.enc"
            vault = OAuthTokenVault(path, self.key)
            vault.save("threads", {
                "access_token": "a-private-access-token", "refresh_token": "a-private-refresh-token",
                "expires_in": 3600,
            }, {"account_id": "thread-123", "account_name": "tak_auto"}, scopes="threads_basic")
            ciphertext = path.read_text(encoding="ascii")
            self.assertNotIn("a-private-access-token", ciphertext)
            self.assertNotIn("a-private-refresh-token", ciphertext)
            public = vault.public_connections()["threads"]
            self.assertEqual(public["account_name"], "tak_auto")
            self.assertNotIn("access_token", public)
            self.assertEqual(vault.get("threads")["refresh_token"], "a-private-refresh-token")
            self.assertTrue(vault.disconnect("threads"))
            self.assertEqual(vault.public_connections(), {})

    def test_vault_rejects_wrong_key_without_exposing_ciphertext(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tokens.enc"
            vault = OAuthTokenVault(path, self.key)
            vault.save("blog", {"access_token": "secret"}, {"account_id": "naver", "account_name": "TAK"})
            wrong = OAuthTokenVault(path, Fernet.generate_key().decode("ascii"))
            with self.assertRaisesRegex(SocialOAuthError, "인증 저장소를 열 수 없습니다") as raised:
                wrong.public_connections()
            self.assertNotIn("secret", str(raised.exception))

    def test_youtube_callback_exchanges_code_with_pkce_and_verifies_channel(self):
        calls = []

        def fake_request(method, url, *, fields=None, headers=None):
            calls.append((method, url, fields, headers))
            if url == "https://oauth2.googleapis.com/token":
                return {"access_token": "access", "refresh_token": "refresh", "expires_in": 3600, "scope": "youtube.readonly"}
            return {"items": [{"id": "channel-123", "snippet": {"title": "TAK AUTO"}}]}

        client = SocialOAuthClient(self.environ, request_json=fake_request)
        result = client.complete("youtube_shorts", "code", callback_uri("youtube_shorts", self.environ), "verifier", state="state")
        self.assertEqual(result["profile"], {"account_id": "channel-123", "account_name": "TAK AUTO"})
        self.assertEqual(calls[0][2]["code_verifier"], "verifier")
        self.assertEqual(calls[1][3]["Authorization"], "Bearer access")
        self.assertEqual(result["tokens"]["refresh_token"], "refresh")

    def test_tiktok_callback_uses_basic_profile_fields_and_stores_refresh_token(self):
        responses = iter([
            {"data": {"access_token": "tt-access", "refresh_token": "tt-refresh", "expires_in": 86400,
                       "scope": "user.info.basic,video.publish"}},
            {"data": {"user": {"open_id": "tt-open-id", "display_name": "TAK AUTO"}}},
        ])
        calls = []
        def fake_request(method, url, *, fields=None, headers=None):
            calls.append((method, url, fields, headers))
            return next(responses)
        client = SocialOAuthClient(self.environ, request_json=fake_request)
        result = client.complete("tiktok", "code", callback_uri("tiktok", self.environ), state="state")
        self.assertEqual(result["profile"], {"account_id": "tt-open-id", "account_name": "TAK AUTO"})
        self.assertIn("fields=open_id,display_name", calls[1][1])
        self.assertEqual(result["tokens"]["refresh_token"], "tt-refresh")

    def test_instagram_callback_exchanges_long_lived_token_and_reads_professional_profile(self):
        responses = iter([
            {"access_token": "ig-short", "expires_in": 3600},
            {"access_token": "ig-long", "expires_in": 5184000},
            {"user_id": "ig-user-123", "username": "takcreator"},
        ])
        calls = []
        def fake_request(method, url, *, fields=None, headers=None):
            calls.append((method, url, fields, headers))
            return next(responses)
        client = SocialOAuthClient(self.environ, request_json=fake_request)
        result = client.complete("instagram_reels", "code", callback_uri("instagram_reels", self.environ), state="state")
        self.assertEqual(result["profile"], {"account_id": "ig-user-123", "account_name": "takcreator"})
        self.assertEqual(result["tokens"]["access_token"], "ig-long")
        self.assertEqual(calls[1][2]["grant_type"], "ig_exchange_token")

    def test_threads_callback_exchanges_long_lived_token_and_reads_profile(self):
        responses = iter([
            {"access_token": "threads-short", "expires_in": 3600},
            {"access_token": "threads-long", "expires_in": 5184000},
            {"id": "threads-id", "username": "tak_auto"},
        ])
        calls = []
        def fake_request(method, url, *, fields=None, headers=None):
            calls.append((method, url, fields, headers))
            return next(responses)
        client = SocialOAuthClient(self.environ, request_json=fake_request)
        result = client.complete("threads", "code", callback_uri("threads", self.environ), state="state")
        self.assertEqual(result["profile"], {"account_id": "threads-id", "account_name": "tak_auto"})
        self.assertEqual(result["tokens"]["access_token"], "threads-long")
        self.assertEqual(calls[1][2]["grant_type"], "th_exchange_token")

    def test_naver_callback_sends_the_original_state_and_reads_profile(self):
        calls = []

        def fake_request(method, url, *, fields=None, headers=None):
            calls.append((url, fields, headers))
            if "oauth2.0/token" in url:
                return {"access_token": "naver-access", "refresh_token": "naver-refresh", "expires_in": 3600}
            return {"resultcode": "00", "response": {"id": "naver-user", "nickname": "takcreator"}}

        client = SocialOAuthClient(self.environ, request_json=fake_request)
        result = client.complete("blog", "code", callback_uri("blog", self.environ), state="original-state")
        self.assertEqual(calls[0][1]["state"], "original-state")
        self.assertEqual(result["profile"]["account_name"], "takcreator")

    def test_facebook_returns_page_choices_without_storing_them_implicitly(self):
        responses = iter([
            {"access_token": "short-user-token", "expires_in": 3600},
            {"access_token": "long-user-token", "expires_in": 5184000},
            {"data": [
                {"permission": "pages_show_list", "status": "granted"},
                {"permission": "pages_read_engagement", "status": "granted"},
                {"permission": "pages_manage_posts", "status": "granted"},
                {"permission": "business_management", "status": "declined"},
            ]},
            {"data": [{"id": "page-1", "name": "TAK AUTO", "access_token": "page-token", "tasks": ["CREATE_CONTENT", "MODERATE"]}]},
        ])
        client = SocialOAuthClient(self.environ, request_json=lambda *args, **kwargs: next(responses))
        result = client.complete("facebook", "code", callback_uri("facebook", self.environ), state="state")
        self.assertEqual(result["choices"][0]["account_id"], "page-1")
        self.assertEqual(result["choices"][0]["access_token"], "page-token")
        self.assertIn("CREATE_CONTENT", result["choices"][0]["tasks"])
        self.assertEqual(result["tokens"], {})
        self.assertEqual(result["scopes"], "pages_show_list,pages_read_engagement,pages_manage_posts")


if __name__ == "__main__":
    unittest.main()
