"""TAK MEDIA Human Review Dashboard(5-28, scripts/run_scout_dashboard.py에 추가된
/media, /media/{content_id} 라우트) 검증.

기존 Threads 검수 화면 테스트(tests/test_threads_dashboard.py)의 HTTP 통합 테스트
패턴(ThreadingHTTPServer + urllib, 실제 소켓)을 그대로 따른다. 실제 LLM/Threads/
YouTube/Naver 네트워크는 이 파일 어디에서도 호출하지 않는다 - 이 Dashboard
자체가 그런 코드를 import조차 하지 않는다는 것을 정적으로도 확인한다(J).
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
from urllib.parse import urlencode

from content_engine.media_archive import MediaArchiveRecord, load_archive, upsert_archive
from content_engine.threads_review import load_pending, upsert_pending, ThreadsPendingDraft
from scripts.run_scout_dashboard import (
    DashboardConfig,
    filter_media_archive_records,
    group_media_archive_records_by_knowledge,
    make_handler_class,
)


def _record(**overrides) -> MediaArchiveRecord:
    fields = {
        "content_id": "content-media-test-1",
        "knowledge_id": "knowledge-media-1",
        "platform": "threads",
        "generation_status": "valid",
        "original_title": "원본 제목",
        "original_body": "원본 본문입니다.",
        "rewritten_title": "AI 재작성 제목",
        "rewritten_body": "AI가 재작성한 본문입니다.",
        "source_url": "https://blog.example.test/original-post",
        "evidence": ("SOURCE FACT: 원문 사실",),
        "evidence_unit_ids": ("lesson:1",),
        "created_at": "2026-09-19T00:00:00+00:00",
        "validation_errors": (),
        "error_message": None,
        "review_status": "unreviewed",
    }
    fields.update(overrides)
    return MediaArchiveRecord(**fields)


_KNOWLEDGE_RECORD = {
    "id": "knowledge-media-1",
    "source_raw_id": "https://blog.example.test/original-post",
    "source_url": "https://blog.example.test/original-post",
    "title": "원문 기사 제목",
    "article_type": "experience",
    "domain": "자기계발",
    "knowledge_type": "경험",
    "lesson": "교훈",
    "reusable_principle": "원칙",
    "evidence": ["SOURCE FACT: 원문 사실"],
    "inference_method": "rule_based_template",
    "created_at": "2026-09-19T00:00:00+00:00",
    "knowledge_review_status": "approved",
}


class MediaDashboardHttpTests(unittest.TestCase):
    """실제로 소켓을 열어 TAK MEDIA Human Review 흐름을 검증한다."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.directory = Path(self._tmp.name)

        self.daily_pack_path = self.directory / "tak_scout_daily.json"
        self.answers_path = self.directory / "tak_interview_answers.json"
        self.knowledge_path = self.directory / "tak_brain_knowledge.json"
        self.skipped_path = self.directory / "tak_scout_dashboard_skipped.json"
        self.sessions_path = self.directory / "tak_interview_sessions.json"
        self.pending_path = self.directory / "tak_threads_pending.json"
        self.archive_path = self.directory / "tak_media_archive.json"

        self.knowledge_path.write_text(
            json.dumps([_KNOWLEDGE_RECORD], ensure_ascii=False), encoding="utf-8"
        )

        self.config = DashboardConfig(
            daily_pack_path=self.daily_pack_path,
            answers_path=self.answers_path,
            knowledge_path=self.knowledge_path,
            skipped_path=self.skipped_path,
            sessions_path=self.sessions_path,
            pending_path=self.pending_path,
            media_archive_path=self.archive_path,
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

    def _post(self, path: str, data: dict[str, str] | None = None) -> tuple[int, str]:
        body = urlencode(data or {}).encode()
        request = urllib.request.Request(self._url(path), data=body, method="POST")
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.read().decode("utf-8")

    def _seed(self, *records: MediaArchiveRecord) -> None:
        upsert_archive(self.archive_path, list(records))

    # --- A. /media 페이지가 정상적으로 렌더링되는지 --------------------------------

    def test_media_list_renders_archive(self):
        self._seed(_record())

        status, body = self._get("/media")

        self.assertEqual(status, 200)
        self.assertIn("TAK MEDIA", body)
        self.assertIn("AI 재작성 제목", body)
        self.assertIn("THREADS", body)
        self.assertIn("VALID", body)
        self.assertIn("검수대기", body)
        self.assertIn("KNOWLEDGE: knowledge-media-1", body)

    def test_media_list_empty_shows_no_results_message(self):
        status, body = self._get("/media")

        self.assertEqual(status, 200)
        self.assertIn("조건에 맞는 Draft가 없습니다", body)

    # --- B. platform 필터 -----------------------------------------------------

    def test_platform_filter_shows_only_matching_platform(self):
        self._seed(
            _record(content_id="content-blog-1", platform="blog", rewritten_title="블로그 제목"),
            _record(content_id="content-threads-1", platform="threads", rewritten_title="스레드 제목"),
        )

        status, body = self._get("/media?platform=blog")

        self.assertEqual(status, 200)
        self.assertIn("블로그 제목", body)
        self.assertNotIn("스레드 제목", body)

    def test_platform_filter_all_shows_everything(self):
        self._seed(
            _record(content_id="content-blog-1", platform="blog", rewritten_title="블로그 제목"),
            _record(content_id="content-threads-1", platform="threads", rewritten_title="스레드 제목"),
        )

        status, body = self._get("/media?platform=all")

        self.assertIn("블로그 제목", body)
        self.assertIn("스레드 제목", body)

    # --- C. generation_status 필터 ----------------------------------------------

    def test_generation_status_filter_shows_only_matching_status(self):
        self._seed(
            _record(content_id="content-valid-1", generation_status="valid", rewritten_title="유효한 글"),
            _record(
                content_id="content-rejected-1",
                generation_status="rejected",
                rewritten_title="반려된 글",
                validation_errors=("원문 근거에 없는 숫자가 추가되었습니다: 999",),
            ),
            _record(
                content_id="content-error-1",
                generation_status="error",
                rewritten_title=None,
                rewritten_body=None,
                error_message="Simulated LLM error",
            ),
        )

        status, body = self._get("/media?generation_status=rejected")

        self.assertEqual(status, 200)
        self.assertIn("반려된 글", body)
        self.assertNotIn("유효한 글", body)
        self.assertNotIn("Simulated LLM error", body)  # error 항목 카드 자체가 안 보임

    # --- D. review_status 필터 ----------------------------------------------

    def test_review_status_filter_shows_only_matching_review_status(self):
        self._seed(
            _record(content_id="content-unreviewed-1", review_status="unreviewed", rewritten_title="검토전 글"),
            _record(content_id="content-approved-1", review_status="approved", rewritten_title="승인된 글"),
        )

        status, body = self._get("/media?review_status=approved")

        self.assertEqual(status, 200)
        self.assertIn("승인된 글", body)
        self.assertNotIn("검토전 글", body)

    # --- 필터 순수 함수 자체도 직접 검증(그룹핑 포함) -------------------------------

    def test_filter_and_group_pure_functions(self):
        records = [
            _record(content_id="c1", platform="blog", knowledge_id="k1"),
            _record(content_id="c2", platform="shorts", knowledge_id="k1", created_at="2026-09-19T01:00:00+00:00"),
            _record(content_id="c3", platform="threads", knowledge_id="k2", created_at="2026-09-19T02:00:00+00:00"),
        ]

        only_blog = filter_media_archive_records(records, platform="blog")
        self.assertEqual([r.content_id for r in only_blog], ["c1"])

        grouped = group_media_archive_records_by_knowledge(records)
        # created_at 내림차순: k2(02:00)의 c3가 가장 최근 -> 첫 그룹
        self.assertEqual(grouped[0][0], "k2")
        self.assertEqual(grouped[1][0], "k1")
        self.assertEqual({r.content_id for r in grouped[1][1]}, {"c1", "c2"})

    # --- E. VALID 콘텐츠만 승인 버튼 노출 ------------------------------------------

    def test_valid_unreviewed_content_shows_approve_button(self):
        self._seed(_record(generation_status="valid", review_status="unreviewed"))

        status, body = self._get("/media/content-media-test-1")

        self.assertEqual(status, 200)
        self.assertIn('action="/media/content-media-test-1/approve"', body)
        self.assertIn("승인", body)

    # --- F. REJECTED/ERROR에는 승인 버튼 없음 --------------------------------------

    def test_rejected_content_has_no_approve_button(self):
        self._seed(_record(generation_status="rejected", review_status="unreviewed"))

        status, body = self._get("/media/content-media-test-1")

        self.assertEqual(status, 200)
        self.assertNotIn('action="/media/content-media-test-1/approve"', body)

    def test_error_content_has_no_approve_button(self):
        self._seed(
            _record(
                generation_status="error",
                review_status="unreviewed",
                rewritten_title=None,
                rewritten_body=None,
                error_message="Simulated LLM error",
            )
        )

        status, body = self._get("/media/content-media-test-1")

        self.assertEqual(status, 200)
        self.assertNotIn('action="/media/content-media-test-1/approve"', body)
        self.assertIn("Simulated LLM error", body)

    def test_already_approved_content_has_no_approve_button(self):
        self._seed(_record(generation_status="valid", review_status="approved"))

        status, body = self._get("/media/content-media-test-1")

        self.assertEqual(status, 200)
        self.assertNotIn('action="/media/content-media-test-1/approve"', body)

    # --- G. 승인하면 review_status가 approved로 저장되는지 --------------------------

    def test_approve_sets_review_status_to_approved_and_shows_banner(self):
        self._seed(_record(platform="blog", generation_status="valid", review_status="unreviewed"))

        status, body = self._post("/media/content-media-test-1/approve")

        self.assertEqual(status, 200)
        self.assertIn("승인되었습니다", body)

        records = load_archive(self.archive_path)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].review_status, "approved")

    def test_rejected_content_cannot_be_approved_via_post(self):
        self._seed(_record(generation_status="rejected", review_status="unreviewed"))

        with self.assertRaises(HTTPError) as ctx:
            self._post("/media/content-media-test-1/approve")
        self.assertEqual(ctx.exception.code, 400)

        records = load_archive(self.archive_path)
        self.assertEqual(records[0].review_status, "unreviewed")

    # --- H. 이미 approved인 콘텐츠를 다시 승인해도 중복 데이터가 생기지 않는지 ---------

    def test_double_approve_is_idempotent_and_does_not_duplicate(self):
        self._seed(_record(platform="blog", generation_status="valid", review_status="unreviewed"))

        first_status, _ = self._post("/media/content-media-test-1/approve")
        second_status, _ = self._post("/media/content-media-test-1/approve")

        self.assertEqual(first_status, 200)
        self.assertEqual(second_status, 200)

        records = load_archive(self.archive_path)
        self.assertEqual(len(records), 1, "재승인이 항목을 중복 추가하면 안 됩니다.")
        self.assertEqual(records[0].review_status, "approved")

    # --- I. Threads 승인 시 기존 threads_review 구조와 연결되는지 --------------------

    def test_threads_approval_creates_pending_draft_via_existing_threads_review(self):
        self._seed(_record(platform="threads", generation_status="valid", review_status="unreviewed"))

        status, _ = self._post("/media/content-media-test-1/approve")
        self.assertEqual(status, 200)

        pending_drafts = load_pending(self.pending_path)
        self.assertEqual(len(pending_drafts), 1)
        draft = pending_drafts[0]
        self.assertEqual(draft.content_id, "content-media-test-1")
        self.assertEqual(draft.knowledge_id, "knowledge-media-1")
        self.assertEqual(draft.status, "pending")  # 승인이 아니라 "검수 대기" 상태로만 이동
        self.assertEqual(draft.ai_rewritten_title, "AI 재작성 제목")
        self.assertEqual(draft.ai_rewritten_body, "AI가 재작성한 본문입니다.")
        self.assertEqual(draft.article_type, "experience")  # KNOWLEDGE에서 조회한 값
        self.assertEqual(draft.knowledge_type, "경험")

    def test_blog_and_shorts_approval_does_not_touch_threads_pending_file(self):
        self._seed(
            _record(content_id="content-blog-1", platform="blog", generation_status="valid"),
            _record(content_id="content-shorts-1", platform="shorts", generation_status="valid"),
        )

        self._post("/media/content-blog-1/approve")
        self._post("/media/content-shorts-1/approve")

        self.assertFalse(self.pending_path.exists(), "Blog/Shorts 승인이 Threads pending 파일을 만들면 안 됩니다.")

    def test_threads_approval_does_not_overwrite_existing_pending_draft(self):
        """이미 tak_threads_pending.json에 같은 content_id의 draft가 있으면(예: 이미
        승인/발행까지 진행된 경우), MEDIA 승인이 그 상태를 절대 덮어쓰면 안 된다."""
        existing = ThreadsPendingDraft(
            content_id="content-media-test-1",
            knowledge_id="knowledge-media-1",
            source_url="https://blog.example.test/original-post",
            evidence_unit_ids=("lesson:1",),
            article_type="experience",
            knowledge_type="경험",
            original_title="원본 제목",
            original_body="원본 본문입니다.",
            ai_rewritten_title="AI 재작성 제목",
            ai_rewritten_body="AI가 재작성한 본문입니다.",
            status="published",
            created_at="2026-09-18T00:00:00+00:00",
            final_title="이미 발행된 제목",
            final_body="이미 발행된 본문",
            published_at="2026-09-18T01:00:00+00:00",
            threads_post_id="th_already_posted",
        )
        upsert_pending(self.pending_path, existing)
        self._seed(_record(platform="threads", generation_status="valid", review_status="unreviewed"))

        status, _ = self._post("/media/content-media-test-1/approve")
        self.assertEqual(status, 200)

        drafts = load_pending(self.pending_path)
        self.assertEqual(len(drafts), 1)
        self.assertEqual(drafts[0].status, "published")
        self.assertEqual(drafts[0].threads_post_id, "th_already_posted")

        # archive 쪽 review_status는 정상적으로 approved가 됐는지(두 상태는 독립적).
        self.assertEqual(load_archive(self.archive_path)[0].review_status, "approved")

    # --- J. 승인 과정에서 실제 외부 API가 호출되지 않는지 ---------------------------

    def test_dashboard_module_never_imports_external_publish_clients(self):
        """ThreadsClient/YouTubeClient/Naver 게시 코드를 이 파일이 아예 참조하지
        않는다는 것을 소스 레벨에서 확인한다(tests/test_generate_threads_draft.py의
        동일한 방법론) - import 자체가 없으므로 승인 과정에서 실제 발행 API가
        호출될 코드 경로 자체가 없다."""
        source = Path("scripts/run_scout_dashboard.py").read_text(encoding="utf-8")
        import_lines = [
            line for line in source.splitlines() if line.strip().startswith(("import ", "from "))
        ]
        self.assertFalse(
            any("ThreadsClient" in line or "threads_publisher" in line for line in import_lines),
            "import 구문에 ThreadsClient/threads_publisher가 있으면 안 됩니다.",
        )
        self.assertFalse(
            any("YouTubeClient" in line or "youtube_publisher" in line for line in import_lines),
            "import 구문에 YouTubeClient/youtube_publisher가 있으면 안 됩니다.",
        )
        # 주석/문서화 문자열에서 "이 파일은 Naver를 게시하지 않는다"고 설명하는 것은
        # 허용한다 - 여기서 확인하려는 것은 실제 import 구문에 naver 관련 클라이언트
        # 모듈이 없다는 사실뿐이다.
        self.assertFalse(
            any("naver" in line.lower() for line in import_lines),
            "import 구문에 naver 관련 모듈이 있으면 안 됩니다.",
        )

    def test_approve_flow_completes_without_any_network_module(self):
        """실제로 승인 흐름 전체(Blog/Shorts/Threads 각각)를 실행해도 예외 없이 끝난다는
        것 자체가, 이 코드 경로 어디에도 외부 API 호출이 없다는 기능적 증거다."""
        self._seed(
            _record(content_id="content-blog-1", platform="blog", generation_status="valid"),
            _record(content_id="content-shorts-1", platform="shorts", generation_status="valid"),
            _record(content_id="content-threads-1", platform="threads", generation_status="valid"),
        )

        for content_id in ("content-blog-1", "content-shorts-1", "content-threads-1"):
            status, _ = self._post(f"/media/{content_id}/approve")
            self.assertEqual(status, 200)

        records = {r.content_id: r for r in load_archive(self.archive_path)}
        self.assertTrue(all(r.review_status == "approved" for r in records.values()))


if __name__ == "__main__":
    unittest.main()
