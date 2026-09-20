"""GET /performance(6-01, TAK MEDIA Dashboard에 추가된 읽기 전용 성과 화면) 검증.

tests/test_media_dashboard.py와 동일한 HTTP 통합 테스트 패턴(ThreadingHTTPServer +
urllib, 실제 소켓)을 그대로 따른다. 이 화면에는 POST 라우트가 없다 - 어떤 파일도
쓰지 않는 순수 읽기 전용이라는 것을 직접 확인한다(J: performance 데이터가 기존
archive를 변경하지 않음의 Dashboard 쪽 증거).
"""

from __future__ import annotations

from http.server import ThreadingHTTPServer
from pathlib import Path
import json
import tempfile
import threading
import unittest
import urllib.request
from urllib.error import HTTPError

from content_engine.media_archive import MediaArchiveRecord, load_archive, upsert_archive
from content_engine.performance.models import PerformanceRecord
from content_engine.performance.store import append_snapshot
from scripts.run_scout_dashboard import DashboardConfig, make_handler_class


_KNOWLEDGE_RECORD = {
    "id": "knowledge-perf-1",
    "source_raw_id": "https://blog.example.test/original-post",
    "source_url": "https://blog.example.test/original-post",
    "title": "원문 기사 제목",
    "article_type": "experience",
    "domain": "자기계발",
    "knowledge_review_status": "approved",
}


def _archive_record(**overrides) -> MediaArchiveRecord:
    fields = {
        "content_id": "content-perf-1",
        "knowledge_id": "knowledge-perf-1",
        "platform": "blog",
        "generation_status": "valid",
        "original_title": "원본 제목",
        "original_body": "원본 본문",
        "rewritten_title": "AI 재작성 제목",
        "rewritten_body": "AI가 재작성한 본문",
        "source_url": "https://blog.example.test/original-post",
        "evidence": (),
        "evidence_unit_ids": ("lesson:1",),
        "created_at": "2026-09-14T00:00:00+00:00",
        "review_status": "approved",
    }
    fields.update(overrides)
    return MediaArchiveRecord(**fields)


def _perf_record(**overrides) -> PerformanceRecord:
    fields = {
        "content_id": "content-perf-1",
        "knowledge_id": "knowledge-perf-1",
        "platform": "blog",
        "published_at": "2026-09-14T00:00:00+00:00",
        "metric_collected_at": "2026-09-17T00:00:00+00:00",
        "metrics": {"views": 850, "likes": 12},
        "source": "manual",
    }
    fields.update(overrides)
    return PerformanceRecord(**fields)


class PerformanceDashboardHttpTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.directory = Path(self._tmp.name)

        self.knowledge_path = self.directory / "tak_brain_knowledge.json"
        self.knowledge_path.write_text(json.dumps([_KNOWLEDGE_RECORD], ensure_ascii=False), encoding="utf-8")

        self.archive_path = self.directory / "tak_media_archive.json"
        self.performance_path = self.directory / "tak_performance.json"

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
            performance_path=self.performance_path,
        )
        self._start_server()

    def _start_server(self) -> None:
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

    def _url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def _get(self, path: str) -> tuple[int, str]:
        with urllib.request.urlopen(self._url(path), timeout=5) as response:
            return response.status, response.read().decode("utf-8")

    def test_empty_performance_store_shows_empty_state(self):
        status, body = self._get("/performance")
        self.assertEqual(status, 200)
        self.assertIn("아직 수집된 성과 데이터가 없습니다", body)

    def test_performance_list_shows_latest_and_previous_snapshot(self):
        upsert_archive(self.archive_path, [_archive_record()])
        append_snapshot(self.performance_path, _perf_record(metric_collected_at="2026-09-15T00:00:00+00:00", metrics={"views": 100}))
        append_snapshot(self.performance_path, _perf_record(metric_collected_at="2026-09-17T00:00:00+00:00", metrics={"views": 850}))

        status, body = self._get("/performance")
        self.assertEqual(status, 200)
        # 6-02: 최근 값과 이전 값을 모두 보여준다(추이 확인용) - 6-01의 "최신만 표시"에서
        # "최신 + 이전 + 변화량 + 추이"로 확장되었다.
        self.assertIn("최근 metrics: views 850", body)
        self.assertIn("이전 metrics: views 100", body)
        self.assertIn("views 추이: 100 → 850", body)
        self.assertIn("최초 대비 변화량: views +750", body)
        self.assertIn("content-perf-1", body)
        self.assertIn("AI 재작성 제목", body)  # archive의 final_title이 채워졌는지

    def test_performance_list_single_snapshot_shows_no_delta_or_previous(self):
        upsert_archive(self.archive_path, [_archive_record()])
        append_snapshot(self.performance_path, _perf_record(metric_collected_at="2026-09-15T00:00:00+00:00", metrics={"views": 100}))

        status, body = self._get("/performance")
        self.assertEqual(status, 200)
        self.assertIn("최근 metrics: views 100", body)
        self.assertNotIn("이전 metrics", body)
        self.assertIn("최초 대비 변화량: (비교할 이전 값 없음)", body)

    def test_performance_list_warns_when_baseline_is_migration(self):
        upsert_archive(self.archive_path, [_archive_record()])
        append_snapshot(
            self.performance_path,
            _perf_record(metric_collected_at="2026-09-10T00:00:00+00:00", metrics={}, source="migration_baseline"),
        )
        append_snapshot(self.performance_path, _perf_record(metric_collected_at="2026-09-17T00:00:00+00:00", metrics={"views": 850}))

        status, body = self._get("/performance")
        self.assertEqual(status, 200)
        self.assertIn("migration_baseline", body)
        self.assertIn("실제 성과 비교의 기준점으로", body)

    def test_nav_link_present_on_home_page(self):
        # SCOUT Dashboard 메인 화면(load_daily_pack)은 {"candidates": [...]} 구조를 요구한다.
        self.config.daily_pack_path.write_text(json.dumps({"candidates": []}), encoding="utf-8")
        status, body = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn('href="/performance"', body)

    def test_performance_route_is_read_only_no_post_handler(self):
        request = urllib.request.Request(self._url("/performance"), data=b"", method="POST")
        with self.assertRaises(HTTPError) as ctx:
            urllib.request.urlopen(request, timeout=5)
        self.assertEqual(ctx.exception.code, 404)

    def test_performance_view_does_not_modify_archive_or_store(self):
        upsert_archive(self.archive_path, [_archive_record()])
        append_snapshot(self.performance_path, _perf_record())

        archive_before = self.archive_path.read_text(encoding="utf-8")
        store_before = self.performance_path.read_text(encoding="utf-8")

        self._get("/performance")
        self._get("/performance")

        self.assertEqual(self.archive_path.read_text(encoding="utf-8"), archive_before)
        self.assertEqual(self.performance_path.read_text(encoding="utf-8"), store_before)


if __name__ == "__main__":
    unittest.main()
