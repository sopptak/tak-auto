import json
from pathlib import Path
import tempfile
import unittest

from content_engine.youtube_upload_history import (
    YouTubeUploadHistory,
    YouTubeUploadHistoryError,
    YouTubeUploadRecord,
)


class YouTubeUploadHistoryTests(unittest.TestCase):
    def setUp(self):
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        self.history_path = Path(tmp_dir.name) / "youtube_publish_log.json"

    def test_load_returns_empty_list_when_file_missing(self):
        history = YouTubeUploadHistory(self.history_path)
        self.assertEqual(history.load(), [])

    def test_append_creates_file_and_persists_record(self):
        history = YouTubeUploadHistory(self.history_path)
        history.append(
            YouTubeUploadRecord(
                video_id="vid_001",
                uploaded_at="2026-09-17T00:00:00+00:00",
                title="테스트 제목",
                privacy_status="private",
                video_path="data/shorts/short_001.mp4",
                tags=("인생", "명언"),
            )
        )

        records = history.load()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["video_id"], "vid_001")
        self.assertEqual(records[0]["privacy_status"], "private")
        self.assertEqual(records[0]["tags"], ["인생", "명언"])
        self.assertEqual(records[0]["url"], "https://youtu.be/vid_001")

    def test_append_accumulates_multiple_records(self):
        history = YouTubeUploadHistory(self.history_path)
        for i in range(3):
            history.append(
                YouTubeUploadRecord(
                    video_id=f"vid_{i}",
                    uploaded_at="2026-09-17T00:00:00+00:00",
                    title=f"제목 {i}",
                    privacy_status="private",
                )
            )
        records = history.load()
        self.assertEqual(len(records), 3)
        self.assertEqual([r["video_id"] for r in records], ["vid_0", "vid_1", "vid_2"])

    def test_load_rejects_non_list_json(self):
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        self.history_path.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
        history = YouTubeUploadHistory(self.history_path)
        with self.assertRaises(YouTubeUploadHistoryError):
            history.load()

    def test_load_rejects_invalid_json(self):
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        self.history_path.write_text("not json", encoding="utf-8")
        history = YouTubeUploadHistory(self.history_path)
        with self.assertRaises(YouTubeUploadHistoryError):
            history.load()


if __name__ == "__main__":
    unittest.main()
