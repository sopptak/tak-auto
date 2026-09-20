"""content_engine.performance.youtube 검증(6-01).

F. YouTube mock metric 저장, H. 외부 API 호출은 mock에서만 실행.
"""

from __future__ import annotations

import unittest

from content_engine.performance.youtube import collect_youtube_performance, normalize_youtube_statistics
from content_engine.youtube_publisher import YouTubeClient


class NormalizeYouTubeStatisticsTests(unittest.TestCase):
    def test_normalizes_typical_item(self):
        item = {"id": "vid1", "statistics": {"viewCount": "1200", "likeCount": "45", "commentCount": "3"}}
        self.assertEqual(normalize_youtube_statistics(item), {"views": 1200, "likes": 45, "comments": 3})

    def test_missing_statistics_returns_empty(self):
        self.assertEqual(normalize_youtube_statistics({"id": "vid1"}), {})
        self.assertEqual(normalize_youtube_statistics(None), {})

    def test_non_numeric_value_is_skipped(self):
        item = {"statistics": {"viewCount": "not-a-number", "likeCount": "5"}}
        self.assertEqual(normalize_youtube_statistics(item), {"likes": 5})


class CollectYouTubePerformanceTests(unittest.TestCase):
    def test_collect_builds_performance_record_from_mock_client(self):
        def token_transport(client_id, client_secret, refresh_token, timeout):
            return {"access_token": "fresh-token"}

        def stats_transport(access_token, video_ids, timeout):
            self.assertEqual(access_token, "fresh-token")
            self.assertEqual(video_ids, ["vid1"])
            return {"items": [{"id": "vid1", "statistics": {"viewCount": "999", "likeCount": "20"}}]}

        client = YouTubeClient(
            client_id="cid",
            client_secret="secret",
            refresh_token="rtoken",
            token_transport=token_transport,
            stats_transport=stats_transport,
        )
        record = collect_youtube_performance(
            client,
            video_id="vid1",
            content_id="content-yt-1",
            knowledge_id="knowledge-yt-1",
            published_at="2026-09-14T00:00:00+00:00",
            metric_collected_at="2026-09-16T00:00:00+00:00",
            title="테스트 Shorts",
        )

        self.assertEqual(record.platform, "youtube")
        self.assertEqual(record.source, "youtube_api")
        self.assertEqual(record.metrics, {"views": 999, "likes": 20})
        self.assertEqual(record.external_id, "vid1")

    def test_collect_handles_empty_items_gracefully(self):
        client = YouTubeClient(
            client_id="cid",
            client_secret="secret",
            refresh_token="rtoken",
            token_transport=lambda *a: {"access_token": "t"},
            stats_transport=lambda *a: {"items": []},
        )
        record = collect_youtube_performance(
            client,
            video_id="vid-missing",
            content_id="content-yt-2",
            knowledge_id="knowledge-yt-2",
            published_at="2026-09-14T00:00:00+00:00",
            metric_collected_at="2026-09-16T00:00:00+00:00",
        )
        self.assertEqual(record.metrics, {})


if __name__ == "__main__":
    unittest.main()
