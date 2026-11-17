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
        with patch.dict("os.environ", {"TAK_AUTO_DATA_DIR": str(self.data_dir)}), \
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
        with patch.dict("os.environ", {"TAK_AUTO_DATA_DIR": str(self.data_dir)}), \
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
        with patch.dict("os.environ", {"TAK_AUTO_DATA_DIR": str(self.data_dir)}), \
                patch("content_engine.trend_publishers.ThreadsClient.from_environment", return_value=self.client):
            with self.assertRaises(PublishUncertainError):
                publish("threads", {"body": "승인된 문안", "_content_id": "uncertain-content"}, "queue-key")
        self.client.publish_text.assert_called_once_with("승인된 문안")
        self.assertFalse((self.data_dir / "threads_publish_log.json").exists())


if __name__ == "__main__":
    unittest.main()
