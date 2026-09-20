"""content_engine.performance.migration 검증(6-01).

이 모듈은 파일을 읽지 않는다 - 이미 로드된 dict 목록을 입력으로 받는다.
실제 production 로그 파일에 대해 이 함수를 실행하는 것은 이번 작업 범위 밖이다
(모듈 docstring 참고) - 여기서는 순수 변환 로직만 검증한다.
"""

from __future__ import annotations

import unittest

from content_engine.performance.migration import (
    migrate_threads_or_blog_baseline_records,
    migrate_youtube_baseline_records,
)


class MigrateThreadsOrBlogBaselineRecordsTests(unittest.TestCase):
    def test_migrates_valid_publish_records(self):
        publish_records = [
            {
                "content_id": "content-1",
                "published_at": "2026-09-13T13:44:03+00:00",
                "threads_post_id": "18114019807999154",
                "knowledge_id": "knowledge-1",
                "platform": "threads",
                "source_url": "https://example.test/a",
            }
        ]
        results = migrate_threads_or_blog_baseline_records(publish_records, platform="threads")

        self.assertEqual(len(results), 1)
        record = results[0]
        self.assertEqual(record.content_id, "content-1")
        self.assertEqual(record.knowledge_id, "knowledge-1")
        self.assertEqual(record.platform, "threads")
        self.assertEqual(record.source, "migration_baseline")
        self.assertEqual(record.metrics, {})
        self.assertEqual(record.external_id, "18114019807999154")
        # baseline은 실제 성과가 아니므로 수집시각을 발행시각과 동일하게 둔다(정보가 없다고
        # 조용히 "지금"을 지어내지 않는다).
        self.assertEqual(record.metric_collected_at, record.published_at)

    def test_skips_records_missing_knowledge_id(self):
        publish_records = [
            {"content_id": "content-1", "published_at": "2026-09-13T00:00:00+00:00", "knowledge_id": ""}
        ]
        results = migrate_threads_or_blog_baseline_records(publish_records, platform="threads")
        self.assertEqual(results, [])

    def test_skips_records_missing_content_id(self):
        publish_records = [{"content_id": "", "knowledge_id": "knowledge-1", "published_at": "x"}]
        results = migrate_threads_or_blog_baseline_records(publish_records, platform="blog")
        self.assertEqual(results, [])

    def test_rejects_unsupported_platform(self):
        with self.assertRaises(ValueError):
            migrate_threads_or_blog_baseline_records([], platform="youtube")

    def test_blog_platform_works_the_same_way(self):
        publish_records = [
            {
                "content_id": "content-blog-1",
                "published_at": "2026-09-13T00:00:00+00:00",
                "threads_post_id": "manual",
                "knowledge_id": "knowledge-1",
                "platform": "blog",
            }
        ]
        results = migrate_threads_or_blog_baseline_records(publish_records, platform="blog")
        self.assertEqual(results[0].platform, "blog")


class MigrateYouTubeBaselineRecordsTests(unittest.TestCase):
    """youtube_publish_log.json에는 content_id/knowledge_id가 아예 없다(6-01 조사 결과) -
    호출부가 명시적 매핑을 줘야만 변환되고, 매핑 없는 항목은 조용히 건너뛴다."""

    def test_migrates_only_mapped_video_ids(self):
        upload_records = [
            {"video_id": "vid1", "uploaded_at": "2026-09-17T00:00:00+00:00", "title": "영상1"},
            {"video_id": "vid2", "uploaded_at": "2026-09-18T00:00:00+00:00", "title": "영상2(매핑 없음)"},
        ]
        mapping = {"vid1": ("content-yt-1", "knowledge-yt-1")}

        results = migrate_youtube_baseline_records(upload_records, mapping)

        self.assertEqual(len(results), 1)
        record = results[0]
        self.assertEqual(record.content_id, "content-yt-1")
        self.assertEqual(record.knowledge_id, "knowledge-yt-1")
        self.assertEqual(record.platform, "youtube")
        self.assertEqual(record.external_id, "vid1")
        self.assertEqual(record.title, "영상1")
        self.assertEqual(record.source, "migration_baseline")

    def test_empty_mapping_migrates_nothing(self):
        upload_records = [{"video_id": "vid1", "uploaded_at": "2026-09-17T00:00:00+00:00"}]
        self.assertEqual(migrate_youtube_baseline_records(upload_records, {}), [])


if __name__ == "__main__":
    unittest.main()
