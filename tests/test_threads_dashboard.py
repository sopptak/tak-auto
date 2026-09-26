"""Threads 검수 화면(5-11 Phase 2, scripts/run_scout_dashboard.py에 추가된
/threads, /threads/{content_id} 라우트) 검증.

기존 TAK SCOUT Dashboard(tests/test_scout_dashboard.py)의 HTTP 통합 테스트
패턴(ThreadingHTTPServer + urllib, 실제 소켓)을 그대로 따른다. 실제 LLM/Threads
네트워크는 이 파일 어디에서도 호출하지 않는다 - LLM/Threads 호출이 있으면
예외를 던지도록 patch해 두고, 승인 흐름이 예외 없이 끝나는 것으로 "호출되지
않았음"을 직접 검증한다(8, 9번 테스트).
"""

from __future__ import annotations

from http.server import ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.request
from unittest import mock
from urllib.error import HTTPError
from urllib.parse import urlencode

from content_engine.llm_provider import OpenAICompatibleRewriteProvider
from content_engine.threads_publisher import ThreadsClient
from content_engine.threads_review import (
    ThreadsPendingDraft,
    load_pending,
    mark_failed,
    mark_published,
    upsert_pending,
)
from scripts.run_scout_dashboard import DashboardConfig, make_handler_class


def _draft(**overrides) -> ThreadsPendingDraft:
    fields = {
        "content_id": "content-dash-test-1",
        "knowledge_id": "knowledge-dash-1",
        "source_url": "https://blog.example.test/original-post",
        "evidence_unit_ids": ("lesson:1",),
        "article_type": None,
        "knowledge_type": "경험",
        "original_title": "원본 규칙기반 제목",
        "original_body": "원본 규칙기반 본문",
        "ai_rewritten_title": "AI가 다시 쓴 제목",
        "ai_rewritten_body": "AI가 다시 쓴 본문입니다.",
        "status": "pending",
        "created_at": "2026-09-16T00:00:00+00:00",
    }
    fields.update(overrides)
    return ThreadsPendingDraft(**fields)


class ThreadsDashboardHttpTests(unittest.TestCase):
    """실제로 소켓을 열어 Threads 검수 흐름을 검증한다."""

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

        self.config = DashboardConfig(
            daily_pack_path=self.daily_pack_path,
            answers_path=self.answers_path,
            knowledge_path=self.knowledge_path,
            skipped_path=self.skipped_path,
            sessions_path=self.sessions_path,
            pending_path=self.pending_path,
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

    def _seed(self, draft: ThreadsPendingDraft) -> None:
        upsert_pending(self.pending_path, draft)

    # --- 1. pending 목록 표시 ------------------------------------------------

    def test_list_shows_no_drafts_message_when_empty(self):
        status, body = self._get("/threads")
        self.assertEqual(status, 200)
        self.assertIn("검수할 초안이 없습니다", body)

    def test_list_redirects_directly_when_exactly_one_unresolved_draft(self):
        self._seed(_draft())

        status, body = self._get("/threads")

        self.assertEqual(status, 200)  # urlopen이 redirect를 따라가서 최종 200
        self.assertIn("AI가 다시 쓴 제목", body)  # 상세 화면이 바로 보임

    def test_list_shows_cards_when_multiple_unresolved_drafts(self):
        self._seed(_draft(content_id="content-a", ai_rewritten_title="제목A"))
        self._seed(_draft(content_id="content-b", ai_rewritten_title="제목B"))

        status, body = self._get("/threads")

        self.assertEqual(status, 200)
        self.assertIn("검수 대기 중인 초안 2건", body)
        self.assertIn("제목A", body)
        self.assertIn("제목B", body)

    # --- 2. pending 상세 표시 --------------------------------------------------

    def test_detail_shows_required_fields(self):
        self._seed(_draft())

        status, body = self._get("/threads/content-dash-test-1")

        self.assertEqual(status, 200)
        self.assertIn("검수 대기", body)  # 1. 상태
        self.assertIn("AI가 다시 쓴 제목", body)  # 2. AI 생성 제목
        self.assertIn("AI가 다시 쓴 본문입니다.", body)  # 3. AI 생성 본문
        self.assertIn("원본 규칙기반 제목", body)  # 4. 원본 KNOWLEDGE 제목
        self.assertIn("https://blog.example.test/original-post", body)  # 5. source_url
        self.assertIn("knowledge-dash-1", body)  # 6. KNOWLEDGE ID
        self.assertIn("AI 초안 그대로 승인", body)  # 7
        self.assertIn('name="title"', body)  # 8. 제목 수정 입력창
        self.assertIn('name="body"', body)  # 9. 본문 수정 입력창
        self.assertIn("수정하여 승인", body)  # 10

    def test_detail_source_url_is_a_link(self):
        self._seed(_draft())
        status, body = self._get("/threads/content-dash-test-1")
        self.assertIn('<a href="https://blog.example.test/original-post"', body)

    def test_detail_shows_finance_warning_when_article_type_is_finance(self):
        self._seed(_draft(article_type="finance"))
        status, body = self._get("/threads/content-dash-test-1")
        self.assertIn("금융 관련 콘텐츠", body)

    def test_detail_no_finance_warning_for_non_finance(self):
        self._seed(_draft(article_type=None))
        status, body = self._get("/threads/content-dash-test-1")
        self.assertNotIn("금융 관련 콘텐츠", body)

    # --- 3. AI 초안 그대로 승인 -------------------------------------------------

    def test_approve_ai_original_sets_final_fields_from_ai_rewritten(self):
        self._seed(_draft())

        status, _ = self._post(
            "/threads/content-dash-test-1/approve",
            {"mode": "ai_original", "title": "무시될 값", "body": "무시될 본문"},
        )

        self.assertEqual(status, 200)
        draft = load_pending(self.pending_path)[0]
        self.assertEqual(draft.status, "approved")
        self.assertEqual(draft.final_title, "AI가 다시 쓴 제목")
        self.assertEqual(draft.final_body, "AI가 다시 쓴 본문입니다.")
        self.assertFalse(draft.edited_by_user)
        self.assertIsNotNone(draft.approved_at)

    # --- 4~6. 사용자 수정 승인 ---------------------------------------------------

    def test_approve_edited_title_only(self):
        self._seed(_draft())

        self._post(
            "/threads/content-dash-test-1/approve",
            {"mode": "edited", "title": "티몽이 고친 제목", "body": "AI가 다시 쓴 본문입니다."},
        )

        draft = load_pending(self.pending_path)[0]
        self.assertEqual(draft.status, "approved")
        self.assertEqual(draft.final_title, "티몽이 고친 제목")
        self.assertEqual(draft.final_body, "AI가 다시 쓴 본문입니다.")
        self.assertTrue(draft.edited_by_user)

    def test_approve_edited_body_only(self):
        self._seed(_draft())

        self._post(
            "/threads/content-dash-test-1/approve",
            {"mode": "edited", "title": "AI가 다시 쓴 제목", "body": "티몽이 고친 본문입니다."},
        )

        draft = load_pending(self.pending_path)[0]
        self.assertEqual(draft.final_title, "AI가 다시 쓴 제목")
        self.assertEqual(draft.final_body, "티몽이 고친 본문입니다.")
        self.assertTrue(draft.edited_by_user)

    def test_approve_edited_title_and_body(self):
        self._seed(_draft())

        self._post(
            "/threads/content-dash-test-1/approve",
            {"mode": "edited", "title": "새 제목", "body": "새 본문"},
        )

        draft = load_pending(self.pending_path)[0]
        self.assertEqual(draft.final_title, "새 제목")
        self.assertEqual(draft.final_body, "새 본문")
        self.assertTrue(draft.edited_by_user)

    # --- 7. 사용자 수정 내용이 정확히(byte-level) 저장되는지 -----------------------

    def test_edited_content_is_preserved_exactly_including_special_characters(self):
        self._seed(_draft())
        exact_body = "특수문자!! @#$%\n두 번째 줄\t탭도 포함 — 정확히 그대로.\"인용\""
        exact_title = "  앞뒤 공백도 그대로 저장되는 제목  "

        self._post(
            "/threads/content-dash-test-1/approve",
            {"mode": "edited", "title": exact_title, "body": exact_body},
        )

        draft = load_pending(self.pending_path)[0]
        self.assertEqual(draft.final_title, exact_title)  # trim되지 않음
        self.assertEqual(draft.final_body, exact_body)

    # --- 8. 승인 시 LLM 호출이 없는지 --------------------------------------------

    def test_approve_never_calls_llm_provider(self):
        self._seed(_draft())

        with mock.patch.object(
            OpenAICompatibleRewriteProvider,
            "from_environment",
            side_effect=AssertionError("LLM이 호출되면 안 됩니다"),
        ):
            status, _ = self._post(
                "/threads/content-dash-test-1/approve",
                {"mode": "edited", "title": "새 제목", "body": "새 본문"},
            )

        self.assertEqual(status, 200)  # patch가 예외를 던지지 않았다 = 호출된 적 없음
        draft = load_pending(self.pending_path)[0]
        self.assertEqual(draft.status, "approved")

    # --- 9. 승인 시 Threads API 호출이 없는지 ------------------------------------

    def test_approve_never_calls_threads_client(self):
        self._seed(_draft())

        with mock.patch.object(
            ThreadsClient, "from_environment", side_effect=AssertionError("Threads API가 호출되면 안 됩니다")
        ):
            status, _ = self._post(
                "/threads/content-dash-test-1/approve",
                {"mode": "ai_original"},
            )

        self.assertEqual(status, 200)
        draft = load_pending(self.pending_path)[0]
        self.assertEqual(draft.status, "approved")
        self.assertIsNone(draft.threads_post_id)

    # --- 10. 승인 시 PublishHistory 변경이 없는지 --------------------------------

    def test_approve_never_creates_publish_history_file(self):
        self._seed(_draft())
        history_path = self.directory / "threads_publish_log.json"  # Dashboard가 알지도 못하는 경로

        self._post("/threads/content-dash-test-1/approve", {"mode": "ai_original"})

        self.assertFalse(history_path.exists())

    # --- 11. 이미 approved인 항목 재승인 방지 ------------------------------------

    def test_double_approve_is_idempotent_and_safe(self):
        self._seed(_draft())
        self._post("/threads/content-dash-test-1/approve", {"mode": "ai_original"})
        first_approved_at = load_pending(self.pending_path)[0].approved_at

        status, body = self._post(
            "/threads/content-dash-test-1/approve",
            {"mode": "edited", "title": "다시 승인 시도", "body": "재승인 본문"},
        )

        self.assertEqual(status, 200)  # 크래시하지 않고 안전하게 처리됨
        draft = load_pending(self.pending_path)[0]
        self.assertEqual(draft.status, "approved")
        self.assertEqual(draft.approved_at, first_approved_at)  # 값이 바뀌지 않음
        self.assertEqual(draft.final_title, "AI가 다시 쓴 제목")  # 두 번째 제출 값이 반영 안 됨

    def test_revisiting_approved_draft_shows_readonly_view(self):
        self._seed(_draft())
        self._post("/threads/content-dash-test-1/approve", {"mode": "ai_original"})

        status, body = self._get("/threads/content-dash-test-1")

        self.assertEqual(status, 200)
        self.assertIn("이미 처리됨", body)
        self.assertNotIn('name="title"', body)  # 편집 폼이 더 이상 보이지 않음

    # --- 12~13. published/failed 항목이 검수 목록에서 제외되는지 ------------------

    def test_published_draft_excluded_from_list(self):
        published = mark_published(
            _draft(status="approved", final_title="t", final_body="b", approved_at="now"),
            threads_post_id="th_1",
            published_at="now",
        )
        self._seed(published)

        status, body = self._get("/threads")

        self.assertIn("검수할 초안이 없습니다", body)

    def test_failed_draft_excluded_from_list(self):
        failed = mark_failed(
            _draft(status="approved", final_title="t", final_body="b", approved_at="now"),
            failure_reason="Threads HTTP 500",
            failed_at="now",
        )
        self._seed(failed)

        status, body = self._get("/threads")

        self.assertIn("검수할 초안이 없습니다", body)

    def test_published_draft_detail_shows_readonly_info_not_edit_form(self):
        published = mark_published(
            _draft(status="approved", final_title="최종 제목", final_body="최종 본문", approved_at="now"),
            threads_post_id="th_999",
            published_at="now",
        )
        self._seed(published)

        status, body = self._get("/threads/content-dash-test-1")

        self.assertEqual(status, 200)
        self.assertIn("th_999", body)
        self.assertNotIn('name="title"', body)

    # --- 14. 잘못된 content_id 처리 ----------------------------------------------

    def test_unknown_content_id_get_returns_404(self):
        with self.assertRaises(HTTPError) as ctx:
            urllib.request.urlopen(self._url("/threads/does-not-exist"), timeout=5)
        self.assertEqual(ctx.exception.code, 404)
        ctx.exception.close()

    def test_unknown_content_id_post_returns_404(self):
        request = urllib.request.Request(
            self._url("/threads/does-not-exist/approve"),
            data=urlencode({"mode": "ai_original"}).encode(),
            method="POST",
        )
        with self.assertRaises(HTTPError) as ctx:
            urllib.request.urlopen(request, timeout=5)
        self.assertEqual(ctx.exception.code, 404)
        ctx.exception.close()

    # --- 15~16. 빈 제목/본문 거부 --------------------------------------------------

    def test_empty_title_is_rejected(self):
        self._seed(_draft())
        request = urllib.request.Request(
            self._url("/threads/content-dash-test-1/approve"),
            data=urlencode({"mode": "edited", "title": "   ", "body": "본문은 있음"}).encode(),
            method="POST",
        )
        with self.assertRaises(HTTPError) as ctx:
            urllib.request.urlopen(request, timeout=5)
        self.assertEqual(ctx.exception.code, 400)
        error_body = ctx.exception.read().decode("utf-8")
        ctx.exception.close()
        self.assertIn("제목을 입력해주세요", error_body)

        draft = load_pending(self.pending_path)[0]
        self.assertEqual(draft.status, "pending")  # 승인되지 않음
        self.assertIsNone(draft.final_title)

    def test_empty_body_is_rejected(self):
        self._seed(_draft())
        request = urllib.request.Request(
            self._url("/threads/content-dash-test-1/approve"),
            data=urlencode({"mode": "edited", "title": "제목은 있음", "body": ""}).encode(),
            method="POST",
        )
        with self.assertRaises(HTTPError) as ctx:
            urllib.request.urlopen(request, timeout=5)
        self.assertEqual(ctx.exception.code, 400)
        ctx.exception.close()

        draft = load_pending(self.pending_path)[0]
        self.assertEqual(draft.status, "pending")
        self.assertIsNone(draft.final_body)

    # --- 500자 초과 거부 (기존 Threads 정책 재사용, [검증] 항목) --------------------

    def test_body_exceeding_500_chars_is_rejected(self):
        self._seed(_draft())
        too_long = "가" * 501
        request = urllib.request.Request(
            self._url("/threads/content-dash-test-1/approve"),
            data=urlencode({"mode": "edited", "title": "제목", "body": too_long}).encode(),
            method="POST",
        )
        with self.assertRaises(HTTPError) as ctx:
            urllib.request.urlopen(request, timeout=5)
        self.assertEqual(ctx.exception.code, 400)
        error_body = ctx.exception.read().decode("utf-8")
        ctx.exception.close()
        self.assertIn("500", error_body)

        draft = load_pending(self.pending_path)[0]
        self.assertEqual(draft.status, "pending")

    def test_body_at_exactly_500_chars_is_accepted(self):
        self._seed(_draft())
        exactly_500 = "가" * 500

        status, _ = self._post(
            "/threads/content-dash-test-1/approve",
            {"mode": "edited", "title": "제목", "body": exactly_500},
        )

        self.assertEqual(status, 200)
        draft = load_pending(self.pending_path)[0]
        self.assertEqual(draft.status, "approved")

    # --- 17. atomic save 유지 -----------------------------------------------------

    def test_pending_file_stays_single_valid_json_after_multiple_requests(self):
        self._seed(_draft())
        self._post(
            "/threads/content-dash-test-1/approve",
            {"mode": "edited", "title": "t1", "body": "b1"},
        )
        # 이미 approved인 상태에서 한 번 더 시도(idempotent 경로) - 에러가 나도 파일은 안전해야 한다.
        self._post(
            "/threads/content-dash-test-1/approve",
            {"mode": "edited", "title": "t2", "body": "b2"},
        )

        files_in_dir = [p for p in self.pending_path.parent.iterdir() if p.name.startswith("tak_threads_pending")]
        self.assertEqual(files_in_dir, [self.pending_path])  # 임시 파일이 남지 않음

        # 파일이 항상 완전한 JSON이었는지(로드 성공 자체가 증거).
        drafts = load_pending(self.pending_path)
        self.assertEqual(len(drafts), 1)
        self.assertEqual(drafts[0].status, "approved")


if __name__ == "__main__":
    unittest.main()
