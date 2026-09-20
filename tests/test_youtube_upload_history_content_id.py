"""YouTubeUploadRecord.content_id/knowledge_id 필드 검증(6-02).

별도 파일로 분리한 이유: tests/test_youtube_upload_history.py는 이번 작업
시작 시점에 이미 이전 세션에서 만들어진 채 커밋되지 않은 상태였다(6-01
보고서에서도 동일하게 확인된 패턴) - 그 파일에 이어 쓰면 이번 커밋에 무관한
이전 세션의 미커밋 내용까지 함께 섞여 들어간다("기존 미커밋 변경과 절대
섞지 않는다"는 지시 위반). 이 파일은 이번 세션에서 새로 만든 것이므로
git add 시 이 파일 하나만 정확히 추가된다.
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from content_engine.youtube_upload_history import YouTubeUploadHistory, YouTubeUploadRecord


class YouTubeUploadRecordContentIdTests(unittest.TestCase):
    def setUp(self):
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        self.history_path = Path(tmp_dir.name) / "youtube_publish_log.json"

    def test_content_id_and_knowledge_id_default_to_empty_string(self):
        # 기존 호출부(테스트 포함)가 이 두 인자를 전혀 넘기지 않아도 그대로 동작해야 한다.
        record = YouTubeUploadRecord(
            video_id="vid_001",
            uploaded_at="2026-09-17T00:00:00+00:00",
            title="제목",
            privacy_status="private",
        )
        self.assertEqual(record.content_id, "")
        self.assertEqual(record.knowledge_id, "")
        self.assertEqual(record.to_dict()["content_id"], "")
        self.assertEqual(record.to_dict()["knowledge_id"], "")

    def test_content_id_and_knowledge_id_are_persisted(self):
        history = YouTubeUploadHistory(self.history_path)
        history.append(
            YouTubeUploadRecord(
                video_id="vid_001",
                uploaded_at="2026-09-17T00:00:00+00:00",
                title="제목",
                privacy_status="private",
                content_id="content-abc123",
                knowledge_id="knowledge-xyz",
            )
        )

        records = history.load()
        self.assertEqual(records[0]["content_id"], "content-abc123")
        self.assertEqual(records[0]["knowledge_id"], "knowledge-xyz")

    def test_legacy_records_without_content_id_still_load_as_raw_dicts(self):
        # YouTubeUploadHistory.load()는 원래부터 원본 dict를 그대로 반환한다(파싱하지
        # 않는다) - content_id/knowledge_id 키가 아예 없는 과거 파일도 에러 없이
        # 읽혀야 한다(구조를 억지로 맞추지 않는다).
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        legacy_json = (
            '[{"video_id": "legacy_vid", "uploaded_at": "2026-09-01T00:00:00+00:00", '
            '"title": "레거시 업로드", "privacy_status": "private", "video_path": "", '
            '"tags": [], "url": "https://youtu.be/legacy_vid"}]'
        )
        self.history_path.write_text(legacy_json, encoding="utf-8")

        history = YouTubeUploadHistory(self.history_path)
        records = history.load()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["video_id"], "legacy_vid")
        self.assertNotIn("content_id", records[0])  # 있는 그대로 - 추측해서 채우지 않는다.

    def test_appending_new_record_does_not_touch_legacy_records_in_same_file(self):
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        legacy_json = (
            '[{"video_id": "legacy_vid", "uploaded_at": "2026-09-01T00:00:00+00:00", '
            '"title": "레거시 업로드", "privacy_status": "private", "video_path": "", '
            '"tags": [], "url": "https://youtu.be/legacy_vid"}]'
        )
        self.history_path.write_text(legacy_json, encoding="utf-8")

        history = YouTubeUploadHistory(self.history_path)
        history.append(
            YouTubeUploadRecord(
                video_id="new_vid",
                uploaded_at="2026-09-17T00:00:00+00:00",
                title="새 업로드",
                privacy_status="private",
                content_id="content-new",
                knowledge_id="knowledge-new",
            )
        )

        records = history.load()
        self.assertEqual(len(records), 2)
        self.assertNotIn("content_id", records[0])  # legacy 기록은 그대로
        self.assertEqual(records[1]["content_id"], "content-new")


if __name__ == "__main__":
    unittest.main()
