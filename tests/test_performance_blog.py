"""content_engine.performance.blog 검증(6-01).

G. Blog manual metric import 저장. 이 채널은 공식 조회 API가 없어(모듈 docstring
참고) 네트워크 코드가 전혀 없다 - 순수 함수 검증만 한다.
"""

from __future__ import annotations

import unittest

from content_engine.performance.blog import build_manual_blog_performance_record


class BuildManualBlogPerformanceRecordTests(unittest.TestCase):
    def test_builds_record_with_manual_source(self):
        record = build_manual_blog_performance_record(
            content_id="content-blog-1",
            knowledge_id="knowledge-blog-1",
            published_at="2026-09-10T00:00:00+00:00",
            metric_collected_at="2026-09-17T00:00:00+00:00",
            metrics={"views": 850, "likes": 12},
            title="블로그 제목",
            blog_url="https://blog.naver.com/tmong2/1234",
        )

        self.assertEqual(record.platform, "blog")
        self.assertEqual(record.source, "manual")
        self.assertEqual(record.metrics, {"views": 850, "likes": 12})
        self.assertEqual(record.external_id, "https://blog.naver.com/tmong2/1234")
        self.assertIsNone(record.raw)


if __name__ == "__main__":
    unittest.main()
