from __future__ import annotations

import unittest
from unittest.mock import patch

from content_engine.facebook_publisher import FacebookClient
from content_engine.tiktok_publisher import TikTokClient
from scripts.collect_performance import _facebook_insights_client, _tiktok_video_client


class PerformanceOAuthPermissionTests(unittest.TestCase):
    def test_facebook_insights_requires_read_scope_and_analyze_task(self):
        environ = {"TAK_AUTO_OAUTH_ENCRYPTION_KEY": "fake-key", "TAK_AUTO_DATA_DIR": "/tmp/tak"}
        connected = {
            "access_token": "page-token", "account_id": "123",
            "granted_scopes": "read_insights,pages_read_engagement",
            "tasks": ["ANALYZE"], "expires_at": "2099-01-01T00:00:00+00:00",
        }
        with patch("scripts.collect_performance.OAuthTokenVault") as vault:
            vault.return_value.get.return_value = connected
            client = _facebook_insights_client(environ)
        self.assertIsInstance(client, FacebookClient)
        self.assertEqual(client.access_token, "page-token")
        vault.return_value.get.assert_called_once_with("facebook")

        for changed in (
            {**connected, "granted_scopes": "pages_read_engagement"},
            {**connected, "tasks": ["CREATE_CONTENT"]},
        ):
            with self.subTest(changed=changed), patch("scripts.collect_performance.OAuthTokenVault") as vault:
                vault.return_value.get.return_value = changed
                with self.assertRaises(ValueError):
                    _facebook_insights_client(environ)

    def test_tiktok_video_query_requires_video_list_scope(self):
        environ = {"TAK_AUTO_OAUTH_ENCRYPTION_KEY": "fake-key", "TAK_AUTO_DATA_DIR": "/tmp/tak"}
        connected = {
            "access_token": "tt-token", "account_id": "open-id", "granted_scopes": "video.list",
            "expires_at": "2099-01-01T00:00:00+00:00",
        }
        with patch("scripts.collect_performance.OAuthTokenVault") as vault:
            vault.return_value.get.return_value = connected
            client = _tiktok_video_client(environ)
        self.assertIsInstance(client, TikTokClient)
        self.assertEqual(client.open_id, "open-id")
        vault.return_value.get.assert_called_once_with("tiktok")

        with patch("scripts.collect_performance.OAuthTokenVault") as vault:
            vault.return_value.get.return_value = {**connected, "granted_scopes": "user.info.basic"}
            with self.assertRaisesRegex(ValueError, "video.list"):
                _tiktok_video_client(environ)

    def test_facebook_and_tiktok_reject_expired_or_malformed_oauth_expiry(self):
        environ = {"TAK_AUTO_OAUTH_ENCRYPTION_KEY": "fake-key", "TAK_AUTO_DATA_DIR": "/tmp/tak"}
        expired_facebook = {
            "access_token": "page-token", "account_id": "123",
            "granted_scopes": "read_insights,pages_read_engagement", "tasks": ["ANALYZE"],
            "expires_at": "2000-01-01T00:00:00+00:00",
        }
        expired_tiktok = {
            "access_token": "tt-token", "account_id": "open-id",
            "granted_scopes": "video.list", "expires_at": "2000-01-01T00:00:00+00:00",
        }
        for platform, helper, connection in (
            ("facebook", _facebook_insights_client, expired_facebook),
            ("tiktok", _tiktok_video_client, expired_tiktok),
        ):
            for expiry in (connection["expires_at"], "not-a-date"):
                candidate = {**connection, "expires_at": expiry}
                with self.subTest(platform=platform, expiry=expiry), patch(
                    "scripts.collect_performance.OAuthTokenVault"
                ) as vault:
                    vault.return_value.get.return_value = candidate
                    with self.assertRaisesRegex(ValueError, "만료|형식"):
                        helper(environ)

    def test_legacy_environment_credentials_remain_supported(self):
        with self.subTest(platform="facebook"), patch(
            "scripts.collect_performance.OAuthTokenVault"
        ) as vault:
            client = _facebook_insights_client({
                "FACEBOOK_ACCESS_TOKEN": "legacy-page-token", "FACEBOOK_PAGE_ID": "123",
            })
        self.assertIsInstance(client, FacebookClient)
        self.assertEqual(client.access_token, "legacy-page-token")
        vault.assert_not_called()

        with self.subTest(platform="tiktok"), patch(
            "scripts.collect_performance.OAuthTokenVault"
        ) as vault:
            client = _tiktok_video_client({
                "TIKTOK_ACCESS_TOKEN": "legacy-tiktok-token", "TIKTOK_OPEN_ID": "open-id",
            })
        self.assertIsInstance(client, TikTokClient)
        self.assertEqual(client.access_token, "legacy-tiktok-token")
        vault.assert_not_called()


if __name__ == "__main__":
    unittest.main()
