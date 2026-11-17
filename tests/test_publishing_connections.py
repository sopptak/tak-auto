import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from content_engine.publishing_connections import (
    connection_dashboard, publishing_connection_statuses, verify_publishing_connection,
)


class PublishingConnectionTests(unittest.TestCase):
    now = datetime(2026, 11, 17, 0, 0, tzinfo=timezone.utc)

    def test_missing_accounts_and_manual_naver_mode_are_explicit(self):
        statuses = {row["key"]: row for row in publishing_connection_statuses({}, now=self.now)}
        self.assertEqual(statuses["threads"]["state"], "missing")
        self.assertIn("THREADS_ACCESS_TOKEN", statuses["threads"]["missing"])
        self.assertEqual(statuses["youtube_shorts"]["state"], "missing")
        self.assertEqual(statuses["instagram_reels"]["state"], "missing")
        self.assertEqual(statuses["tiktok"]["state"], "missing")
        self.assertEqual(statuses["facebook"]["state"], "missing")
        self.assertEqual(statuses["blog"]["state"], "manual")

    def test_configured_credentials_show_account_and_expiry_without_secret(self):
        token = "private-token-value"
        statuses = publishing_connection_statuses({
            "THREADS_ACCESS_TOKEN": token,
            "THREADS_USERNAME": "tak_creator",
            "THREADS_ACCESS_TOKEN_EXPIRES_AT": "2026-11-20T00:00:00Z",
            "YOUTUBE_CLIENT_ID": "id",
            "YOUTUBE_CLIENT_SECRET": "secret",
            "YOUTUBE_REFRESH_TOKEN": "refresh",
            "YOUTUBE_CHANNEL_NAME": "TAK AUTO",
        }, now=self.now)
        rows = {row["key"]: row for row in statuses}
        self.assertEqual(rows["threads"]["state"], "configured")
        self.assertEqual(rows["threads"]["account_name"], "tak_creator")
        self.assertEqual(rows["threads"]["expires_in"], "3일 후 만료")
        self.assertEqual(rows["youtube_shorts"]["state"], "configured")
        self.assertEqual(rows["youtube_shorts"]["expires_in"], "")
        html = connection_dashboard({"THREADS_ACCESS_TOKEN": token}, now=self.now)
        self.assertIn("tok", html.lower())
        self.assertNotIn(token, html)

    def test_expired_and_invalid_expiration_are_not_reported_as_connected(self):
        statuses = {row["key"]: row for row in publishing_connection_statuses({
            "THREADS_ACCESS_TOKEN": "x",
            "THREADS_ACCESS_TOKEN_EXPIRES_AT": "2026-11-16T00:00:00Z",
            "INSTAGRAM_ACCESS_TOKEN": "x",
            "INSTAGRAM_USER_ID": "123",
            "INSTAGRAM_ACCESS_TOKEN_EXPIRES_AT": "not-a-date",
        }, now=self.now)}
        self.assertEqual(statuses["threads"]["state"], "expired")
        self.assertEqual(statuses["threads"]["label"], "토큰 만료")
        self.assertEqual(statuses["instagram_reels"]["state"], "attention")
        self.assertEqual(statuses["instagram_reels"]["expires_in"], "만료일 형식 오류")

    def test_recent_api_verification_sets_real_account_name_and_stale_results_need_refresh(self):
        env = {"THREADS_ACCESS_TOKEN": "secret", "THREADS_USERNAME": "old_name"}
        cache = {"threads": {
            "status": "verified", "account_id": "123", "account_name": "verified_name",
            "checked_at": "2026-11-17T00:00:00Z",
        }}
        current = datetime(2026, 11, 17, 0, 30, tzinfo=timezone.utc)
        recent = {row["key"]: row for row in publishing_connection_statuses(env, now=current, verification_cache=cache)}
        self.assertEqual(recent["threads"]["state"], "verified")
        self.assertEqual(recent["threads"]["account_name"], "verified_name")
        self.assertIn("마지막 확인: 2026-11-17 09:00", recent["threads"]["checked_at_label"])

        cache["threads"]["checked_at"] = "2026-11-15T00:00:00Z"
        stale = {row["key"]: row for row in publishing_connection_statuses(env, now=current, verification_cache=cache)}
        self.assertEqual(stale["threads"]["state"], "attention")
        self.assertEqual(stale["threads"]["label"], "재확인 필요")

    def test_dashboard_only_offers_live_api_check_for_supported_configured_accounts(self):
        html = connection_dashboard({
            "THREADS_ACCESS_TOKEN": "secret",
            "YOUTUBE_CLIENT_ID": "id", "YOUTUBE_CLIENT_SECRET": "secret", "YOUTUBE_REFRESH_TOKEN": "refresh",
        })
        self.assertIn('action="/connections/verify"', html)
        self.assertIn("계정 연결 확인", html)
        self.assertIn("API 계정 확인 기능 준비 중", html)

    def test_verify_dispatch_uses_read_only_profile_clients(self):
        with patch("content_engine.publishing_connections.ThreadsClient.from_environment") as threads_factory:
            threads_factory.return_value.api_base = "https://graph.threads.net"
            threads_factory.return_value.get_profile.return_value = SimpleNamespace(id="thread-id", username="tak_auto")
            self.assertEqual(
                verify_publishing_connection("threads", {"THREADS_ACCESS_TOKEN": "secret"}),
                {"account_id": "thread-id", "account_name": "tak_auto"},
            )
        with patch("content_engine.publishing_connections.YouTubeClient.from_environment") as youtube_factory:
            youtube_factory.return_value.get_channel_profile.return_value = SimpleNamespace(
                channel_id="channel-id", title="TAK AUTO",
            )
            self.assertEqual(
                verify_publishing_connection("youtube_shorts", {"YOUTUBE_REFRESH_TOKEN": "secret"}),
                {"account_id": "channel-id", "account_name": "TAK AUTO"},
            )
        with self.assertRaisesRegex(ValueError, "아직 지원하지 않습니다"):
            verify_publishing_connection("tiktok", {})

    def test_threads_verification_rejects_non_official_api_host_before_sending_token(self):
        with patch("content_engine.publishing_connections.ThreadsClient.from_environment") as factory:
            factory.return_value.api_base = "https://example.invalid"
            with self.assertRaisesRegex(ValueError, "공식 HTTPS API 주소"):
                verify_publishing_connection("threads", {"THREADS_ACCESS_TOKEN": "secret"})
        factory.return_value.get_profile.assert_not_called()

    def test_dashboard_shows_connection_cards_expiration_and_publish_switch(self):
        html = connection_dashboard({
            "TAK_AUTO_PUBLISHING_ENABLED": "false",
            "TIKTOK_ACCESS_TOKEN": "fake",
            "TIKTOK_OPEN_ID": "id",
            "TIKTOK_USERNAME": "creator",
            "TIKTOK_ACCESS_TOKEN_EXPIRES_AT": "2026-11-18T00:00:00Z",
        }, now=self.now)
        self.assertIn("게시 계정 연결 현황", html)
        self.assertIn("TikTok", html)
        self.assertIn("Facebook 페이지", html)
        self.assertIn("creator", html)
        self.assertIn("1일 후 만료", html)
        self.assertIn("비활성화 (기본값)", html)
        self.assertIn("게시 어댑터:", html)
        self.assertIn("미설정", html)
        self.assertIn("자동 게시를 지원하지 않습니다", html)
        self.assertNotIn('TIKTOK_ACCESS_TOKEN</p>', html)

    def test_dashboard_offers_web_login_for_each_social_account_and_never_renders_tokens(self):
        setup = {key: {"ready": True, "missing": [], "redirect_uri": f"https://example.test/connections/oauth/callback/{key}"}
                 for key in ("youtube_shorts", "tiktok", "instagram_reels", "facebook", "threads", "blog")}
        linked = {"threads": {
            "account_id": "thread-id", "account_name": "tak_auto", "connected_at": "2026-11-17T00:00:00+00:00",
            "expires_at": "", "granted_scopes": "threads_basic", "access_token": "never-render-this-token",
        }}
        html = connection_dashboard({"TAK_AUTO_PUBLISHING_ENABLED": "false"}, oauth_connections=linked, oauth_setup=setup)
        for platform in setup:
            self.assertIn(f'href="/connections/oauth/{platform}"', html)
        self.assertIn("계정 연결됨", html)
        self.assertIn("tak_auto", html)
        self.assertIn('action="/connections/disconnect"', html)
        self.assertNotIn("never-render-this-token", html)
        self.assertIn("게시 기능을 켜지 않습니다", html)

    def test_dashboard_shows_provider_callback_and_setup_without_secrets(self):
        html = connection_dashboard({}, oauth_setup={"youtube_shorts": {
            "ready": False,
            "missing": ["YOUTUBE_OAUTH_CLIENT_SECRET", "TAK_AUTO_OAUTH_ENCRYPTION_KEY"],
            "redirect_uri": "https://example.test/connections/oauth/callback/youtube_shorts",
        }})
        self.assertIn("YOUTUBE_OAUTH_CLIENT_SECRET", html)
        self.assertIn("TAK_AUTO_OAUTH_ENCRYPTION_KEY", html)
        self.assertIn("https://example.test/connections/oauth/callback/youtube_shorts", html)
        self.assertIn("계정 연결 설정 필요", html)
        self.assertNotIn("client_secret=", html)


if __name__ == "__main__":
    unittest.main()
