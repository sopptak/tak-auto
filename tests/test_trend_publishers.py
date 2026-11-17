import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from content_engine.publishing_queue import PermanentPublishError, PublishUncertainError
from content_engine.threads_publisher import ThreadsAPIError
from content_engine.trend_publishers import publish


class TrendPublisherTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.data_dir = Path(self.temp_dir.name)
        self.client = Mock()
        self.client.publish_text.return_value = SimpleNamespace(id="threads-post-1")

    def test_threads_adapter_posts_only_text_and_records_history(self):
        with patch.dict("os.environ", {"TAK_AUTO_DATA_DIR": str(self.data_dir)}, clear=True), \
                patch("content_engine.trend_publishers.ThreadsClient.from_environment", return_value=self.client):
            remote_id = publish("threads", {
                "title": "제목", "body": "승인된 Threads 문안", "_content_id": "trend-thread-1",
            }, "queue-key")

        self.assertEqual(remote_id, "threads-post-1")
        self.client.publish_text.assert_called_once_with("승인된 Threads 문안")
        history = (self.data_dir / "threads_publish_log.json").read_text(encoding="utf-8")
        self.assertIn("trend-thread-1", history)
        self.assertIn("threads-post-1", history)

    def test_existing_threads_history_skips_remote_publish(self):
        with patch.dict("os.environ", {"TAK_AUTO_DATA_DIR": str(self.data_dir)}, clear=True), \
                patch("content_engine.trend_publishers.ThreadsClient.from_environment", return_value=self.client):
            publish("threads", {"body": "첫 게시", "_content_id": "same-content"}, "first-key")
            remote_id = publish("threads", {"body": "재시도", "_content_id": "same-content"}, "retry-key")

        self.assertEqual(remote_id, "threads-post-1")
        self.client.publish_text.assert_called_once_with("첫 게시")

    def test_unsupported_platform_fails_closed_without_calling_threads(self):
        with patch("content_engine.trend_publishers.ThreadsClient.from_environment") as factory:
            with self.assertRaisesRegex(PermanentPublishError, "아직 준비되지 않았습니다"):
                publish("youtube_shorts", {"body": "본문"}, "queue-key")
        factory.assert_not_called()

    def test_invalid_threads_text_fails_before_api_call(self):
        with patch("content_engine.trend_publishers.ThreadsClient.from_environment") as factory:
            with self.assertRaisesRegex(PermanentPublishError, "500자 이하"):
                publish("threads", {"body": "x" * 501}, "queue-key")
        factory.assert_not_called()

    def test_ambiguous_threads_api_error_requires_manual_review(self):
        self.client.publish_text.side_effect = ThreadsAPIError("network response lost")
        with patch.dict("os.environ", {"TAK_AUTO_DATA_DIR": str(self.data_dir)}, clear=True), \
                patch("content_engine.trend_publishers.ThreadsClient.from_environment", return_value=self.client):
            with self.assertRaises(PublishUncertainError):
                publish("threads", {"body": "승인된 문안", "_content_id": "uncertain-content"}, "queue-key")
        self.client.publish_text.assert_called_once_with("승인된 문안")
        self.assertFalse((self.data_dir / "threads_publish_log.json").exists())

    def test_uses_encrypted_oauth_token_only_when_publish_scope_is_granted(self):
        with patch.dict("os.environ", {
            "TAK_AUTO_DATA_DIR": str(self.data_dir),
            "TAK_AUTO_OAUTH_ENCRYPTION_KEY": "test-fernet-key",
        }, clear=True), \
                patch("content_engine.trend_publishers.OAuthTokenVault") as vault_type, \
                patch("content_engine.trend_publishers.ThreadsClient") as client_type:
            vault_type.return_value.get.return_value = {
                "access_token": "encrypted-vault-token",
                "granted_scopes": "threads_basic,threads_content_publish",
                "expires_at": "2099-01-01T00:00:00+00:00",
            }
            client_type.return_value.publish_text.return_value = SimpleNamespace(id="oauth-post-1")
            remote_id = publish("threads", {"body": "승인 대기열 문안", "_content_id": "oauth-thread"}, "queue-key")

        self.assertEqual(remote_id, "oauth-post-1")
        client_type.assert_called_once_with(access_token="encrypted-vault-token")
        client_type.return_value.publish_text.assert_called_once_with("승인 대기열 문안")

    def test_oauth_vault_token_without_publish_scope_fails_closed(self):
        with patch.dict("os.environ", {
            "TAK_AUTO_DATA_DIR": str(self.data_dir),
            "TAK_AUTO_OAUTH_ENCRYPTION_KEY": "test-fernet-key",
        }, clear=True), \
                patch("content_engine.trend_publishers.OAuthTokenVault") as vault_type, \
                patch("content_engine.trend_publishers.ThreadsClient") as client_type:
            vault_type.return_value.get.return_value = {
                "access_token": "profile-only-token", "granted_scopes": "threads_basic",
            }
            with self.assertRaisesRegex(PermanentPublishError, "게시 권한이 없습니다"):
                publish("threads", {"body": "게시하지 말아야 할 문안", "_content_id": "no-scope"}, "queue-key")
        client_type.assert_not_called()

    def test_expired_oauth_vault_token_fails_closed(self):
        with patch.dict("os.environ", {
            "TAK_AUTO_DATA_DIR": str(self.data_dir),
            "TAK_AUTO_OAUTH_ENCRYPTION_KEY": "test-fernet-key",
        }, clear=True), \
                patch("content_engine.trend_publishers.OAuthTokenVault") as vault_type, \
                patch("content_engine.trend_publishers.ThreadsClient") as client_type:
            vault_type.return_value.get.return_value = {
                "access_token": "expired-token",
                "granted_scopes": "threads_content_publish",
                "expires_at": "2000-01-01T00:00:00+00:00",
            }
            with self.assertRaisesRegex(PermanentPublishError, "토큰이 만료되었습니다"):
                publish("threads", {"body": "만료 토큰 문안", "_content_id": "expired"}, "queue-key")
        client_type.assert_not_called()


if __name__ == "__main__":
    unittest.main()
