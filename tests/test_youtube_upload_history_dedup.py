"""YouTubeUploadHistory.published_content_ids()/is_published() 검증(6-13).

content_engine.publish_history.PublishHistory와 동일한 이름/관례(published_content_ids,
is_published)로 YouTubeUploadHistory에도 중복 게시 판정 메서드를 추가했다(6-13
Publish Pack/중복 게시 방지 작업). 이 파일은 그 두 메서드만 검증한다 - 기존
tests/test_youtube_upload_history.py, tests/test_youtube_upload_history_content_id.py는
전혀 수정하지 않는다(새 파일로 분리, 동일 파일들의 관례).
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from content_engine.youtube_upload_history import YouTubeUploadHistory, YouTubeUploadRecord


class YouTubeUploadHistoryDedupTests(unittest.TestCase):
    def setUp(self):
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        self.history_path = Path(tmp_dir.name) / "youtube_publish_log.json"

    def test_published_content_ids_empty_when_file_missing(self):
        history = YouTubeUploadHistory(self.history_path)
        self.assertEqual(history.published_content_ids(), set())

    def test_published_content_ids_collects_only_non_empty_content_ids(self):
        history = YouTubeUploadHistory(self.history_path)
        history.append(
            YouTubeUploadRecord(
                video_id="vid_with_id",
                uploaded_at="2026-09-21T00:00:00+00:00",
                title="제목",
                privacy_status="private",
                content_id="content-abc123",
            )
        )
        history.append(
            YouTubeUploadRecord(
                video_id="vid_without_id",
                uploaded_at="2026-09-21T00:00:00+00:00",
                title="제목2",
                privacy_status="private",
            )
        )
        self.assertEqual(history.published_content_ids(), {"content-abc123"})

    def test_is_published_true_for_known_content_id(self):
        history = YouTubeUploadHistory(self.history_path)
        history.append(
            YouTubeUploadRecord(
                video_id="vid_001",
                uploaded_at="2026-09-21T00:00:00+00:00",
                title="제목",
                privacy_status="private",
                content_id="content-abc123",
            )
        )
        self.assertTrue(history.is_published("content-abc123"))

    def test_is_published_false_for_unknown_content_id(self):
        history = YouTubeUploadHistory(self.history_path)
        self.assertFalse(history.is_published("content-does-not-exist"))

    def test_is_published_false_for_empty_or_none_content_id(self):
        history = YouTubeUploadHistory(self.history_path)
        self.assertFalse(history.is_published(""))
        self.assertFalse(history.is_published(None))  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
