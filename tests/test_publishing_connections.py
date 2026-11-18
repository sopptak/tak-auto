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

    def test_facebook_connection_reports_missing_publish_permissions(self):
        rows = {
            row["key"]: row for row in publishing_connection_statuses(
                {}, now=self.now,
                oauth_connections={"facebook": {
                    "account_id": "123", "account_name": "TAK AUTO 페이지", "tasks": "CREATE_CONTENT",
                    "granted_scopes": "pages_show_list",
                }},
            )
        }
        self.assertEqual(rows["facebook"]["state"], "verified")
        self.assertIn("게시 권한이 부족", rows["facebook"]["publish_note"])

    def test_facebook_connection_requires_create_content_page_task(self):
        rows = {
            row["key"]: row for row in publishing_connection_statuses(
                {}, now=self.now,
                oauth_connections={"facebook": {
                    "account_id": "123", "account_name": "TAK AUTO 페이지",
                    "tasks": "MODERATE",
                    "granted_scopes": "pages_show_list,pages_read_engagement,pages_manage_posts",
                }},
            )
        }
        self.assertIn("CREATE_CONTENT 또는 MANAGE 작업 권한이 없습니다", rows["facebook"]["publish_note"])

    def test_facebook_connection_reports_ready_when_all_page_scopes_are_granted(self):
        rows = {
            row["key"]: row for row in publishing_connection_statuses(
                {}, now=self.now,
                oauth_connections={"facebook": {
                    "account_id": "123", "account_name": "TAK AUTO 페이지", "tasks": "CREATE_CONTENT",
                    "granted_scopes": "pages_show_list,pages_read_engagement,pages_manage_posts",
                }},
            )
        }
        self.assertIn("게시 권한과 CREATE_CONTENT 또는 MANAGE 작업 권한이 확인", rows["facebook"]["publish_note"])

    def test_youtube_oauth_refresh_token_remains_ready_after_access_token_expiry(self):
        rows = {
            row["key"]: row for row in publishing_connection_statuses(
                {}, now=self.now, oauth_connections={"youtube_shorts": {
                    "account_id": "channel-123", "account_name": "TAK AUTO",
                    "expires_at": "2026-11-16T00:00:00Z",
                    "granted_scopes": "https://www.googleapis.com/auth/youtube.readonly https://www.googleapis.com/auth/youtube.upload",
                    "refresh_token_configured": "true",
                }},
            )
        }
        self.assertEqual(rows["youtube_shorts"]["state"], "verified")
        self.assertEqual(rows["youtube_shorts"]["expires_in"], "액세스 토큰 자동 갱신")
        self.assertIn("youtube.upload", rows["youtube_shorts"]["publish_note"])
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

    def test_oauth_vault_threads_connection_is_used_for_read_only_profile_check(self):
        environ = {
            "TAK_AUTO_OAUTH_ENCRYPTION_KEY": "vault-key",
            "TAK_AUTO_DATA_DIR": "/tmp/tak-auto-test",
        }
        connection = {"access_token": "oauth-thread-token", "granted_scopes": "threads_basic"}
        with patch("content_engine.publishing_connections.OAuthTokenVault") as vault_type:
            with patch("content_engine.publishing_connections.ThreadsClient") as client_type:
                vault_type.return_value.get.return_value = connection
                client_type.return_value.api_base = "https://graph.threads.net"
                client_type.return_value.get_profile.return_value = SimpleNamespace(
                    id="oauth-thread-id", username="oauth_creator",
                )
                result = verify_publishing_connection("threads", environ)
                client_type.assert_called_once_with(access_token="oauth-thread-token")
        vault_type.return_value.get.assert_called_once_with("threads")
        self.assertEqual(result, {"account_id": "oauth-thread-id", "account_name": "oauth_creator"})

    def test_oauth_vault_youtube_connection_uses_refresh_token_and_web_app_credentials(self):
        environ = {
            "TAK_AUTO_OAUTH_ENCRYPTION_KEY": "vault-key",
            "TAK_AUTO_DATA_DIR": "/tmp/tak-auto-test",
            "YOUTUBE_OAUTH_CLIENT_ID": "web-client-id",
            "YOUTUBE_OAUTH_CLIENT_SECRET": "web-client-secret",
        }
        connection = {
            "refresh_token": "oauth-refresh-token",
            "granted_scopes": "https://www.googleapis.com/auth/youtube.readonly",
        }
        with patch("content_engine.publishing_connections.OAuthTokenVault") as vault_type:
            with patch("content_engine.publishing_connections.YouTubeClient") as client_type:
                vault_type.return_value.get.return_value = connection
                client_type.return_value.get_channel_profile.return_value = SimpleNamespace(
                    channel_id="oauth-channel-id", title="OAuth channel",
                )
                result = verify_publishing_connection("youtube_shorts", environ)
                client_type.assert_called_once_with(
                    client_id="web-client-id", client_secret="web-client-secret",
                    refresh_token="oauth-refresh-token",
                )
        self.assertEqual(result, {"account_id": "oauth-channel-id", "account_name": "OAuth channel"})

    def test_oauth_vault_verification_rejects_missing_profile_scope(self):
        environ = {"TAK_AUTO_OAUTH_ENCRYPTION_KEY": "vault-key"}
        with patch("content_engine.publishing_connections.OAuthTokenVault") as vault_type:
            with patch("content_engine.publishing_connections.ThreadsClient") as client_type:
                vault_type.return_value.get.return_value = {
                    "access_token": "token", "granted_scopes": "threads_content_publish",
                }
                with self.assertRaisesRegex(ValueError, "threads_basic"):
                    verify_publishing_connection("threads", environ)
                client_type.assert_not_called()

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
        self.assertIn("서비스 아이콘을 누르면 해당 SNS 로그인 페이지가 새 탭으로 열립니다", html)
        self.assertIn("Threads 게시 권한은 승인된 대기열에서만 사용합니다", html)
        self.assertIn("게시 기능은 기본 비활성화입니다", html)
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
        self.assertIn("계정은 연결됐지만 Threads 게시 권한이 없습니다", html)
        self.assertIn('action="/connections/disconnect"', html)
        self.assertNotIn("never-render-this-token", html)
        self.assertIn("action=\"/connections/verify\"", html)
        self.assertIn("게시 기능은 기본 비활성화입니다", html)

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

    def test_each_social_icon_opens_its_official_login_page_in_a_safe_new_tab(self):
        expected_urls = (
            "https://accounts.google.com/ServiceLogin?service=youtube",
            "https://www.tiktok.com/login",
            "https://www.instagram.com/accounts/login/",
            "https://www.facebook.com/login/",
            "https://www.threads.net/login",
            "https://nid.naver.com/nidlogin.login",
        )
        html = connection_dashboard({})
        for url in expected_urls:
            self.assertIn(url.replace("&", "&amp;"), html)
        self.assertEqual(html.count('class="connection-icon connection-login-icon"'), 6)
        self.assertIn('target="_blank" rel="noopener noreferrer"', html)
        self.assertIn("로그인하는 것만으로 TAK AUTO 연결 상태가 바뀌지는 않습니다", html)


if __name__ == "__main__":
    unittest.main()
