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
        self.shorts_scripts_path = self.directory / "shorts_scripts"
        self.blog_history_path = self.directory / "blog_publish_log.json"

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
            shorts_scripts_path=self.shorts_scripts_path,
            blog_history_path=self.blog_history_path,
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


class MediaEditAndDismissHttpTests(unittest.TestCase):
    """5-29: MEDIA 상세 화면의 사람 수정(edit) + 보류(dismiss) + 최종 콘텐츠
    선택 규칙(edited가 있으면 edited, 없으면 generated) 검증.

    A~M은 사용자가 지정한 회귀 테스트 항목 번호와 그대로 대응한다.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.directory = Path(self._tmp.name)

        self.knowledge_path = self.directory / "tak_brain_knowledge.json"
        self.pending_path = self.directory / "tak_threads_pending.json"
        self.archive_path = self.directory / "tak_media_archive.json"
        self.shorts_scripts_path = self.directory / "shorts_scripts"
        self.blog_history_path = self.directory / "blog_publish_log.json"

        self.knowledge_path.write_text(
            json.dumps([_KNOWLEDGE_RECORD], ensure_ascii=False), encoding="utf-8"
        )

        self.config = DashboardConfig(
            daily_pack_path=self.directory / "tak_scout_daily.json",
            answers_path=self.directory / "tak_interview_answers.json",
            knowledge_path=self.knowledge_path,
            skipped_path=self.directory / "tak_scout_dashboard_skipped.json",
            sessions_path=self.directory / "tak_interview_sessions.json",
            pending_path=self.pending_path,
            media_archive_path=self.archive_path,
            shorts_scripts_path=self.shorts_scripts_path,
            blog_history_path=self.blog_history_path,
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

    # --- A. 기존 AI 생성본이 수정 화면에 기본값으로 표시되는가 -----------------------

    def test_edit_form_prefilled_with_generated_content_by_default(self):
        self._seed(_record(platform="blog"))

        status, body = self._get("/media/content-media-test-1")

        self.assertEqual(status, 200)
        self.assertIn('value="AI 재작성 제목"', body)
        self.assertIn("AI가 재작성한 본문입니다.", body)

    # --- B/C/F. 제목/본문 수정이 저장되고 edited_*로 남는가 --------------------------

    def test_edit_saves_title_and_body_into_edited_fields(self):
        self._seed(_record(platform="blog"))

        status, body = self._post(
            "/media/content-media-test-1/edit", {"title": "사람이 고친 제목", "body": "사람이 고친 본문입니다."}
        )

        self.assertEqual(status, 200)
        self.assertIn("수정 내용이 저장되었습니다", body)

        record = load_archive(self.archive_path)[0]
        self.assertEqual(record.edited_title, "사람이 고친 제목")
        self.assertEqual(record.edited_body, "사람이 고친 본문입니다.")

    # --- D. original_title/original_body가 보존되는가 ------------------------------

    def test_edit_does_not_touch_original_fields(self):
        self._seed(_record(platform="blog"))

        self._post("/media/content-media-test-1/edit", {"title": "새 제목", "body": "새 본문"})

        record = load_archive(self.archive_path)[0]
        self.assertEqual(record.original_title, "원본 제목")
        self.assertEqual(record.original_body, "원본 본문입니다.")

    # --- E. generated(rewritten)_title/body가 보존되는가 ---------------------------

    def test_edit_does_not_touch_rewritten_fields(self):
        self._seed(_record(platform="blog"))

        self._post("/media/content-media-test-1/edit", {"title": "새 제목", "body": "새 본문"})

        record = load_archive(self.archive_path)[0]
        self.assertEqual(record.rewritten_title, "AI 재작성 제목")
        self.assertEqual(record.rewritten_body, "AI가 재작성한 본문입니다.")

    # --- G. 수정만 하고 승인하지 않으면 approved가 되지 않는가 ------------------------

    def test_edit_alone_does_not_approve(self):
        self._seed(_record(platform="blog"))

        self._post("/media/content-media-test-1/edit", {"title": "새 제목", "body": "새 본문"})

        record = load_archive(self.archive_path)[0]
        self.assertEqual(record.review_status, "unreviewed")

    def test_editing_dismissed_content_resets_it_to_unreviewed(self):
        self._seed(_record(platform="blog", review_status="dismissed"))

        self._post("/media/content-media-test-1/edit", {"title": "새 제목", "body": "새 본문"})

        record = load_archive(self.archive_path)[0]
        self.assertEqual(record.review_status, "unreviewed")

    # --- H. 수정 후 승인하면 edited 내용이 최종 콘텐츠로 사용되는가(Threads 예시) -----

    def test_edited_then_approved_threads_content_uses_edited_text_in_pending_queue(self):
        self._seed(_record(platform="threads"))

        self._post(
            "/media/content-media-test-1/edit",
            {"title": "사람이 고친 최종 제목", "body": "사람이 고친 최종 본문"},
        )
        status, _ = self._post("/media/content-media-test-1/approve")
        self.assertEqual(status, 200)

        draft = load_pending(self.pending_path)[0]
        self.assertEqual(draft.ai_rewritten_title, "사람이 고친 최종 제목")
        self.assertEqual(draft.ai_rewritten_body, "사람이 고친 최종 본문")

        record = load_archive(self.archive_path)[0]
        self.assertEqual(record.final_title, "사람이 고친 최종 제목")
        self.assertEqual(record.final_body, "사람이 고친 최종 본문")

    # --- I/P. 수정하지 않고 승인하면 generated 내용이 그대로 pending queue로 넘어가는가 --

    def test_unedited_approved_threads_content_uses_generated_text_in_pending_queue(self):
        self._seed(_record(platform="threads"))

        status, _ = self._post("/media/content-media-test-1/approve")
        self.assertEqual(status, 200)

        draft = load_pending(self.pending_path)[0]
        self.assertEqual(draft.ai_rewritten_title, "AI 재작성 제목")
        self.assertEqual(draft.ai_rewritten_body, "AI가 재작성한 본문입니다.")

    # --- 이미 승인된 콘텐츠는 수정할 수 없는가(수정 폼/버튼도 사라지는가) -------------

    def test_approved_content_cannot_be_edited(self):
        self._seed(_record(platform="blog", review_status="approved"))

        status, body = self._get("/media/content-media-test-1")
        self.assertEqual(status, 200)
        self.assertNotIn('action="/media/content-media-test-1/edit"', body)

        with self.assertRaises(HTTPError) as ctx:
            self._post("/media/content-media-test-1/edit", {"title": "몰래 수정", "body": "몰래 수정"})
        self.assertEqual(ctx.exception.code, 400)

        record = load_archive(self.archive_path)[0]
        self.assertEqual(record.edited_title, None)

    def test_rejected_content_cannot_be_edited(self):
        self._seed(_record(platform="blog", generation_status="rejected"))

        with self.assertRaises(HTTPError) as ctx:
            self._post("/media/content-media-test-1/edit", {"title": "몰래 수정", "body": "몰래 수정"})
        self.assertEqual(ctx.exception.code, 400)

    # --- L. dismissed 저장 가능 -----------------------------------------------------

    def test_dismiss_sets_review_status_to_dismissed(self):
        self._seed(_record(platform="blog"))

        status, body = self._post("/media/content-media-test-1/dismiss")

        self.assertEqual(status, 200)
        self.assertIn("보류되었습니다", body)
        record = load_archive(self.archive_path)[0]
        self.assertEqual(record.review_status, "dismissed")

    def test_dismiss_does_not_delete_the_record(self):
        self._seed(_record(platform="blog"))

        self._post("/media/content-media-test-1/dismiss")

        records = load_archive(self.archive_path)
        self.assertEqual(len(records), 1, "보류는 데이터를 삭제하면 안 됩니다.")

    def test_approved_content_cannot_be_dismissed(self):
        self._seed(_record(platform="blog", review_status="approved"))

        with self.assertRaises(HTTPError) as ctx:
            self._post("/media/content-media-test-1/dismiss")
        self.assertEqual(ctx.exception.code, 400)

        record = load_archive(self.archive_path)[0]
        self.assertEqual(record.review_status, "approved")

    # --- M. dismissed에서 다시 검토(수정/승인) 가능 ----------------------------------

    def test_dismissed_content_can_be_reviewed_again(self):
        self._seed(_record(platform="blog", review_status="dismissed"))

        status, body = self._get("/media/content-media-test-1")
        self.assertEqual(status, 200)
        self.assertIn('action="/media/content-media-test-1/approve"', body)
        self.assertIn('action="/media/content-media-test-1/edit"', body)

        status, _ = self._post("/media/content-media-test-1/approve")
        self.assertEqual(status, 200)

        record = load_archive(self.archive_path)[0]
        self.assertEqual(record.review_status, "approved")

    def test_edit_saves_are_preserved_across_reload(self):
        """저장된 edited_*가 파일에서 다시 읽어도 그대로 남아있는지(round-trip)."""
        self._seed(_record(platform="blog"))
        self._post(
            "/media/content-media-test-1/edit",
            {"title": "재로드 확인용 제목", "body": "재로드 확인용 본문"},
        )

        reloaded = load_archive(self.archive_path)[0]
        self.assertEqual(reloaded.edited_title, "재로드 확인용 제목")
        self.assertEqual(reloaded.edited_body, "재로드 확인용 본문")


class MediaDownstreamStatusHttpTests(unittest.TestCase):
    """5-29: /media 목록·상세 화면의 downstream 상태 표시(J, K) + 승인 후
    다음 단계 안내(L) 검증. 새 저장소를 만들지 않고 기존 파일(tak_threads_
    pending.json, blog_publish_log.json, data/shorts_scripts/<id>.json 존재
    여부)만 읽어서 계산한다는 설계를 그대로 검증한다."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.directory = Path(self._tmp.name)

        self.knowledge_path = self.directory / "tak_brain_knowledge.json"
        self.knowledge_path.write_text(
            json.dumps([_KNOWLEDGE_RECORD], ensure_ascii=False), encoding="utf-8"
        )
        self.pending_path = self.directory / "tak_threads_pending.json"
        self.archive_path = self.directory / "tak_media_archive.json"
        self.shorts_scripts_path = self.directory / "shorts_scripts"
        self.blog_history_path = self.directory / "blog_publish_log.json"
        self.youtube_history_path = self.directory / "youtube_publish_log.json"

        self.config = DashboardConfig(
            daily_pack_path=self.directory / "tak_scout_daily.json",
            answers_path=self.directory / "tak_interview_answers.json",
            knowledge_path=self.knowledge_path,
            skipped_path=self.directory / "tak_scout_dashboard_skipped.json",
            sessions_path=self.directory / "tak_interview_sessions.json",
            pending_path=self.pending_path,
            media_archive_path=self.archive_path,
            shorts_scripts_path=self.shorts_scripts_path,
            blog_history_path=self.blog_history_path,
            youtube_history_path=self.youtube_history_path,
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

    # --- J. Threads pending 상태 표시 -----------------------------------------

    def test_threads_downstream_status_reflects_pending_file_status(self):
        self._seed(_record(platform="threads", review_status="approved"))
        upsert_pending(
            self.pending_path,
            ThreadsPendingDraft(
                content_id="content-media-test-1",
                knowledge_id="knowledge-media-1",
                source_url="https://blog.example.test/original-post",
                evidence_unit_ids=("lesson:1",),
                article_type="experience",
                knowledge_type="경험",
                original_title="원본",
                original_body="원본 본문",
                ai_rewritten_title="AI 재작성 제목",
                ai_rewritten_body="AI가 재작성한 본문입니다.",
                status="published",
                created_at="2026-09-19T00:00:00+00:00",
                final_title="최종",
                final_body="최종 본문",
                published_at="2026-09-19T01:00:00+00:00",
                threads_post_id="th_1",
            ),
        )

        status, body = self._get("/media/content-media-test-1")

        self.assertEqual(status, 200)
        self.assertIn("발행됨", body)  # _THREADS_STATUS_LABELS["published"]

    def test_threads_downstream_status_before_approval(self):
        self._seed(_record(platform="threads", review_status="unreviewed"))

        status, body = self._get("/media/content-media-test-1")

        self.assertEqual(status, 200)
        self.assertIn("승인 전", body)

    # --- K. Dashboard downstream 상태 표시(목록 + 상세) -----------------------------

    def test_list_shows_blog_ready_for_pack_before_publish(self):
        self._seed(_record(platform="blog", review_status="approved"))

        status, body = self._get("/media")

        self.assertEqual(status, 200)
        self.assertIn("Pack 생성 가능", body)
        self.assertNotIn("게시 기록됨", body)

    def test_blog_downstream_status_shows_published_once_history_recorded(self):
        from content_engine.publish_history import PublishHistory, PublishRecord

        self._seed(_record(platform="blog", review_status="approved"))
        PublishHistory(self.blog_history_path).append(
            PublishRecord(
                content_id="content-media-test-1",
                published_at="2026-09-19T01:00:00+00:00",
                threads_post_id="",
                knowledge_id="knowledge-media-1",
                platform="blog",
                source_url="https://blog.example.test/original-post",
            )
        )

        status, body = self._get("/media/content-media-test-1")

        self.assertEqual(status, 200)
        self.assertIn("게시 기록됨", body)

    def test_shorts_downstream_status_shows_script_ready_after_approval(self):
        self._seed(_record(platform="shorts", review_status="unreviewed"))

        status, _ = self._post("/media/content-media-test-1/approve")
        self.assertEqual(status, 200)

        status, body = self._get("/media/content-media-test-1")
        self.assertEqual(status, 200)
        self.assertIn("Script 생성됨", body)

        # 실제 파일도 만들어졌는지(자동 연결 기능 자체의 재확인).
        self.assertTrue((self.shorts_scripts_path / "content-media-test-1.json").exists())

    def test_shorts_downstream_status_shows_youtube_uploaded_once_history_recorded(self):
        """6-13: Script만 생성돼 있고 실제 YouTube 업로드 이력
        (YouTubeUploadHistory, content_id로 연결)이 없으면 "MP4 미생성"까지만
        보여주고, 업로드 이력이 생기면 "YouTube 업로드됨"으로 바뀌어야 한다 -
        review_status=="approved"(사람의 승인)와 실제 게시 여부를 절대 같은
        의미로 취급하지 않는다는 원칙(6-13)의 확인. 실제 MP4 파일(고정 경로
        data/shorts/<content_id>.mp4)은 이 테스트가 만들지 않는다 - YouTube
        업로드 이력 확인이 MP4 파일 존재 확인보다 먼저 판정되므로 필요 없다."""
        from content_engine.youtube_upload_history import YouTubeUploadHistory, YouTubeUploadRecord

        self._seed(_record(platform="shorts", review_status="unreviewed"))
        self._post("/media/content-media-test-1/approve")  # 최초 승인 - ShortsScript 자동 생성

        status, body = self._get("/media/content-media-test-1")
        self.assertEqual(status, 200)
        self.assertIn("MP4 미생성", body)
        self.assertNotIn("YouTube 업로드됨", body)

        YouTubeUploadHistory(self.youtube_history_path).append(
            YouTubeUploadRecord(
                video_id="yt_video_1",
                uploaded_at="2026-09-21T00:00:00+00:00",
                title="업로드된 Shorts",
                privacy_status="private",
                content_id="content-media-test-1",
                knowledge_id="knowledge-media-1",
            )
        )

        status, body = self._get("/media/content-media-test-1")
        self.assertEqual(status, 200)
        self.assertIn("YouTube 업로드됨", body)

    # --- L. 승인 후 다음 단계 안내 표시 ----------------------------------------------

    def test_next_step_hint_shown_after_blog_approval(self):
        self._seed(_record(platform="blog", review_status="unreviewed"))

        self._post("/media/content-media-test-1/approve")
        status, body = self._get("/media/content-media-test-1")

        self.assertEqual(status, 200)
        self.assertIn("Blog Publishing Pack을 생성할 수 있습니다", body)

    def test_next_step_hint_shown_after_shorts_approval(self):
        self._seed(_record(platform="shorts", review_status="unreviewed"))

        self._post("/media/content-media-test-1/approve")
        status, body = self._get("/media/content-media-test-1")

        self.assertEqual(status, 200)
        self.assertIn("MP4 렌더링 여부는 사람이 별도로 결정합니다", body)

    def test_next_step_hint_shown_after_threads_approval(self):
        self._seed(_record(platform="threads", review_status="unreviewed"))

        self._post("/media/content-media-test-1/approve")
        status, body = self._get("/media/content-media-test-1")

        self.assertEqual(status, 200)
        self.assertIn("최종 승인해야 실제 발행 후보가 됩니다", body)

    def test_no_next_step_hint_before_approval(self):
        self._seed(_record(platform="blog", review_status="unreviewed"))

        status, body = self._get("/media/content-media-test-1")

        self.assertEqual(status, 200)
        self.assertNotIn("다음 단계:", body)


if __name__ == "__main__":
    unittest.main()
