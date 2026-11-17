import unittest
from datetime import datetime, timezone

from content_engine.publishing_connections import connection_dashboard, publishing_connection_statuses


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


if __name__ == "__main__":
    unittest.main()
