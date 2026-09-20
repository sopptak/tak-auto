"""content_engine.performance.threads 검증(6-01).

E. Threads mock metric 저장, H. 외부 API 호출은 mock에서만 실행(이 파일 전체가
mock transport만 쓴다 - 실제 urlopen을 import조차 하지 않는다).
"""

from __future__ import annotations

import unittest

from content_engine.performance.threads import collect_threads_performance, normalize_threads_insights
from content_engine.threads_publisher import ThreadsClient


class NormalizeThreadsInsightsTests(unittest.TestCase):
    def test_normalizes_typical_response(self):
        raw = {
            "data": [
                {"name": "views", "period": "lifetime", "values": [{"value": 120}]},
                {"name": "likes", "period": "lifetime", "values": [{"value": 8}]},
                {"name": "replies", "period": "lifetime", "values": [{"value": 2}]},
            ]
        }
        self.assertEqual(normalize_threads_insights(raw), {"views": 120, "likes": 8, "replies": 2})

    def test_ignores_malformed_entries(self):
        raw = {
            "data": [
                {"name": "views", "values": [{"value": 10}]},
                {"name": "likes", "values": []},  # 빈 values
                {"name": "replies"},  # values 없음
                {"values": [{"value": 3}]},  # name 없음
                {"name": "shares", "values": [{"value": "not-an-int"}]},  # 정수 아님
            ]
        }
        self.assertEqual(normalize_threads_insights(raw), {"views": 10})

    def test_non_dict_response_returns_empty(self):
        self.assertEqual(normalize_threads_insights(None), {})
        self.assertEqual(normalize_threads_insights("oops"), {})
        self.assertEqual(normalize_threads_insights({"data": "not-a-list"}), {})


class CollectThreadsPerformanceTests(unittest.TestCase):
    def test_collect_builds_performance_record_from_mock_client(self):
        def transport(method, url, headers, payload, timeout):
            self.assertEqual(method, "GET")
            self.assertIn("media-123/insights", url)
            return {
                "data": [
                    {"name": "views", "values": [{"value": 500}]},
                    {"name": "likes", "values": [{"value": 30}]},
                ]
            }

        client = ThreadsClient(access_token="mock-token", transport=transport)
        record = collect_threads_performance(
            client,
            media_id="media-123",
            content_id="content-1",
            knowledge_id="knowledge-1",
            published_at="2026-09-14T00:00:00+00:00",
            metric_collected_at="2026-09-16T00:00:00+00:00",
            title="테스트 게시물",
        )

        self.assertEqual(record.platform, "threads")
        self.assertEqual(record.source, "threads_api")
        self.assertEqual(record.metrics, {"views": 500, "likes": 30})
        self.assertEqual(record.external_id, "media-123")
        self.assertEqual(record.content_id, "content-1")
        self.assertEqual(record.knowledge_id, "knowledge-1")
        self.assertIsNotNone(record.raw)


if __name__ == "__main__":
    unittest.main()
