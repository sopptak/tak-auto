"""GET /publish-readiness 화면 검증(6-14).

content_engine.publish_audit.audit_archive()를 실제 HTTP 요청으로 확인한다.
이 화면은 완전히 읽기 전용이다(승인/보류/게시 폼이 전혀 없다) - 그 사실도
함께 검증한다.
"""

from __future__ import annotations

from http.server import ThreadingHTTPServer
from pathlib import Path
import json
import tempfile
import threading
import unittest
import urllib.request

from content_engine.media_archive import MediaArchiveRecord, upsert_archive
from scripts.run_scout_dashboard import DashboardConfig, make_handler_class


_KNOWLEDGE_RECORD = {
    "id": "knowledge-readiness-1",
    "source_raw_id": "https://blog.example.test/original-post",
    "source_url": "https://blog.example.test/original-post",
    "title": "원문 기사 제목",
    "article_type": "experience",
    "domain": "자기계발",
    "category": "자기계발",
    "knowledge_type": "경험",
    "knowledge_review_status": "approved",
}


def _record(**overrides) -> MediaArchiveRecord:
    fields = {
        "content_id": "content-readiness-1",
        "knowledge_id": "knowledge-readiness-1",
        "platform": "blog",
        "generation_status": "valid",
        "original_title": "원본 제목",
        "original_body": "원본 본문입니다.",
        "rewritten_title": "AI 재작성 제목",
        "rewritten_body": "AI가 재작성한 본문입니다.",
        "source_url": "https://blog.example.test/original-post",
        "evidence": (),
        "evidence_unit_ids": ("lesson:1",),
        "created_at": "2026-09-19T00:00:00+00:00",
        "review_status": "unreviewed",
    }
    fields.update(overrides)
    return MediaArchiveRecord(**fields)


class PublishReadinessDashboardTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.directory = Path(self._tmp.name)

        self.knowledge_path = self.directory / "tak_brain_knowledge.json"
        self.knowledge_path.write_text(
            json.dumps([_KNOWLEDGE_RECORD], ensure_ascii=False), encoding="utf-8"
        )
        self.archive_path = self.directory / "tak_media_archive.json"

        self.config = DashboardConfig(
            daily_pack_path=self.directory / "tak_scout_daily.json",
            answers_path=self.directory / "tak_interview_answers.json",
            knowledge_path=self.knowledge_path,
            skipped_path=self.directory / "tak_scout_dashboard_skipped.json",
            sessions_path=self.directory / "tak_interview_sessions.json",
            pending_path=self.directory / "tak_threads_pending.json",
            media_archive_path=self.archive_path,
            shorts_scripts_path=self.directory / "shorts_scripts",
            blog_history_path=self.directory / "blog_publish_log.json",
            youtube_history_path=self.directory / "youtube_publish_log.json",
            threads_history_path=self.directory / "threads_publish_log.json",
        )
        handler_class = make_handler_class(self.config)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler_class)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._shutdown)

    def _shutdown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _get(self, path: str) -> tuple[int, str]:
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=5) as response:
            return response.status, response.read().decode("utf-8")

    def _seed(self, *records: MediaArchiveRecord) -> None:
        upsert_archive(self.archive_path, list(records))

    def test_empty_archive_shows_empty_state(self):
        status, body = self._get("/publish-readiness")
        self.assertEqual(status, 200)
        self.assertIn("콘텐츠가 없습니다", body)

    def test_approved_content_shows_ready(self):
        self._seed(_record(review_status="approved"))
        status, body = self._get("/publish-readiness")
        self.assertEqual(status, 200)
        self.assertIn("게시 가능(READY) 1", body)
        self.assertIn("content-readiness-1", body)

    def test_unreviewed_content_never_shows_as_ready(self):
        self._seed(_record(review_status="unreviewed"))
        status, body = self._get("/publish-readiness")
        self.assertEqual(status, 200)
        self.assertIn("게시 가능(READY) 0", body)
        self.assertIn("차단 1", body)

    def test_page_has_no_approve_or_publish_forms(self):
        """이 화면은 완전히 읽기 전용이다 - 승인/보류/게시 폼이 전혀 없어야 한다."""
        self._seed(_record(review_status="unreviewed"))
        _status, body = self._get("/publish-readiness")
        self.assertNotIn("<form", body)

    def test_detail_link_points_to_existing_media_detail_route(self):
        self._seed(_record(review_status="approved"))
        _status, body = self._get("/publish-readiness")
        self.assertIn('href="/media/content-readiness-1"', body)

    def test_existing_media_route_still_works(self):
        """이번 변경이 기존 /media 라우트를 깨지 않았는지 회귀 확인."""
        status, body = self._get("/media")
        self.assertEqual(status, 200)
        self.assertIn("TAK MEDIA", body)


if __name__ == "__main__":
    unittest.main()
