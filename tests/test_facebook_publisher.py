import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from content_engine.facebook_publisher import (
    FacebookAPIError,
    FacebookClient,
    FacebookConfigurationError,
)
from content_engine.publishing_queue import PermanentPublishError, PublishUncertainError
from content_engine.trend_publishers import publish


class FacebookClientTests(unittest.TestCase):
    def test_publish_text_posts_to_page_feed_with_message(self):
        calls = []

        def transport(method, url, *, access_token, fields=None, timeout_seconds=30.0):
            calls.append((method, url, access_token, fields, timeout_seconds))
            return {"id": "123_456"}

        client = FacebookClient(
            access_token="page-token",
            page_id="123",
            transport=transport,
            timeout_seconds=7,
        )
        result = client.publish_text("  승인된 게시물  ")

        self.assertEqual(result.post_id, "123_456")
        self.assertEqual(calls, [(
            "POST",
            "https://graph.facebook.com/v27.0/123/feed",
            "page-token",
            {"message": "승인된 게시물"},
            7,
        )])

    def test_rejects_invalid_page_id_and_empty_message(self):
        with self.assertRaises(FacebookConfigurationError):
            FacebookClient(access_token="token", page_id="not-a-number")
        client = FacebookClient(access_token="token", page_id="123")
        with self.assertRaises(ValueError):
            client.publish_text("  ")

    def test_missing_remote_post_id_is_not_success(self):
        client = FacebookClient(
            access_token="token",
            page_id="123",
            transport=lambda *args, **kwargs: {},
        )
        with self.assertRaises(FacebookAPIError):
            client.publish_text("게시 본문")


class FacebookTrendPublisherTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.data_dir = Path(self.temp_dir.name)

    def _connection(self):
        return {
            "access_token": "page-token",
            "account_id": "123456789",
            "granted_scopes": "pages_show_list pages_read_engagement pages_manage_posts",
            "tasks": ["CREATE_CONTENT"],
            "expires_at": "2099-01-01T00:00:00+00:00",
        }

    def test_approved_facebook_post_uses_page_connection_and_records_history(self):
        client = type("Client", (), {
            "publish_text": lambda self, message: SimpleNamespace(post_id="123_456")
        })()
        with patch.dict("os.environ", {
            "TAK_AUTO_DATA_DIR": str(self.data_dir),
            "TAK_AUTO_OAUTH_ENCRYPTION_KEY": "test-fernet-key",
            "META_GRAPH_API_VERSION": "v27.0",
        }, clear=True), \
             patch("content_engine.trend_publishers.OAuthTokenVault") as vault_type, \
             patch("content_engine.trend_publishers.FacebookClient", return_value=client) as client_type:
            vault_type.return_value.get.return_value = self._connection()
            remote_id = publish("facebook", {
                "body": "승인된 Facebook 페이지 게시물",
                "_content_id": "facebook-content-1",
                "_knowledge_id": "knowledge-1",
                "_source_url": "https://example.test/source",
                "title": "테스트 제목",
            }, "queue-key")

        self.assertEqual(remote_id, "123_456")
        vault_type.return_value.get.assert_called_once_with("facebook")
        client_type.assert_called_once_with(
            access_token="page-token", page_id="123456789", api_version="v27.0",
        )
        history = (self.data_dir / "threads_publish_log.json").read_text(encoding="utf-8")
        self.assertIn('"platform": "facebook"', history)
        self.assertIn('"remote_id": "123_456"', history)
        self.assertIn("facebook-content-1", history)

    def test_facebook_requires_publish_scope_and_page_task(self):
        with patch.dict("os.environ", {
            "TAK_AUTO_DATA_DIR": str(self.data_dir),
            "TAK_AUTO_OAUTH_ENCRYPTION_KEY": "test-fernet-key",
        }, clear=True), \
             patch("content_engine.trend_publishers.OAuthTokenVault") as vault_type, \
             patch("content_engine.trend_publishers.FacebookClient") as client_type:
            connection = self._connection()
            connection["granted_scopes"] = "pages_show_list pages_read_engagement"
            vault_type.return_value.get.return_value = connection
            with self.assertRaisesRegex(PermanentPublishError, "게시 권한이 부족"):
                publish("facebook", {"body": "게시"}, "key")
            connection["granted_scopes"] = "pages_show_list pages_read_engagement pages_manage_posts"
            connection["tasks"] = ["ANALYZE"]
            with self.assertRaisesRegex(PermanentPublishError, "게시 작업 권한"):
                publish("facebook", {"body": "게시"}, "key")
        client_type.assert_not_called()

    def test_duplicate_content_does_not_publish_twice(self):
        with patch.dict("os.environ", {
            "TAK_AUTO_DATA_DIR": str(self.data_dir),
            "TAK_AUTO_OAUTH_ENCRYPTION_KEY": "test-fernet-key",
        }, clear=True), \
             patch("content_engine.trend_publishers.OAuthTokenVault") as vault_type, \
             patch("content_engine.trend_publishers.FacebookClient") as client_type:
            vault_type.return_value.get.return_value = self._connection()
            client = type("Client", (), {
                "publish_text": lambda self, message: SimpleNamespace(post_id="123_456")
            })()
            client_type.return_value = client
            payload = {"body": "첫 게시", "_content_id": "same-facebook-content"}
            first = publish("facebook", payload, "first-key")
            second = publish("facebook", {"body": "재시도", "_content_id": "same-facebook-content"}, "retry-key")

        self.assertEqual(first, "123_456")
        self.assertEqual(second, "123_456")
        client_type.assert_called_once()


if __name__ == "__main__":
    unittest.main()
