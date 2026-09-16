"""scripts/publish_approved_threads.py 검증 (5-11 설계 문서 Phase 2, 9-2장).

실제 Threads API는 절대 호출하지 않는다. ``content_engine.threads_publisher.ThreadsClient``의
``from_environment``를 patch해서 Fake 클라이언트(또는 호출 시 예외를 던지는 Mock)로
대체한다 - 기존 ``tests/test_threads_dashboard.py``(8, 9번 테스트)와 동일한 방법론이다.
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from content_engine.publish_history import PublishHistory, PublishRecord
from content_engine.threads_publisher import ThreadsAPIError, ThreadsClient, ThreadsPublishResult
from content_engine.threads_review import (
    ThreadsPendingDraft,
    load_pending,
    mark_approved,
    mark_failed,
    mark_published,
    save_pending,
    upsert_pending,
)
from scripts.publish_approved_threads import main


def _draft(**overrides) -> ThreadsPendingDraft:
    fields = {
        "content_id": "content-publish-test-1",
        "knowledge_id": "knowledge-publish-1",
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


def _approved_draft(**overrides) -> ThreadsPendingDraft:
    """pending -> approved까지 진행된 draft. final_title/body는 기본적으로
    ai_rewritten_*과 동일하게(그대로 승인) 설정한다."""
    draft = _draft(**{k: v for k, v in overrides.items() if k not in ("final_title", "final_body")})
    final_title = overrides.get("final_title", draft.ai_rewritten_title)
    final_body = overrides.get("final_body", draft.ai_rewritten_body)
    return mark_approved(draft, final_title=final_title, final_body=final_body, approved_at="2026-09-16T00:30:00+00:00")


class FakeThreadsClient:
    """실제 네트워크를 전혀 만들지 않는 가짜 클라이언트. publish_text 호출 여부/인자를 기록한다."""

    def __init__(
        self,
        result: ThreadsPublishResult | None = None,
        error: Exception | None = None,
        outcomes: list[ThreadsPublishResult | Exception] | None = None,
    ):
        """``outcomes``가 주어지면 ``publish_text`` 호출마다 순서대로 하나씩 소비한다
        (여러 draft를 순회하며 각기 다른 결과를 내야 하는 시나리오용). 주어지지 않으면
        기존처럼 매 호출마다 동일한 ``result``/``error``를 반환/발생시킨다."""
        self.result = result or ThreadsPublishResult(id="th_fake_1")
        self.error = error
        self.outcomes = list(outcomes) if outcomes is not None else None
        self.publish_text_calls: list[str] = []

    def publish_text(self, text: str, reply_control: str | None = None, topic_tag: str | None = None):
        self.publish_text_calls.append(text)
        if self.outcomes is not None:
            outcome = self.outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        if self.error is not None:
            raise self.error
        return self.result


class PublishApprovedThreadsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.tmp_path = Path(self.tmp_dir.name)
        self.pending_path = self.tmp_path / "tak_threads_pending.json"
        self.history_path = self.tmp_path / "threads_publish_log.json"

    def _seed(self, *drafts: ThreadsPendingDraft) -> None:
        save_pending(list(drafts), self.pending_path)

    def _run(self, extra_args: list[str] | None = None) -> int:
        args = ["--input", str(self.pending_path), "--history", str(self.history_path)]
        if extra_args:
            args.extend(extra_args)
        return main(args)

    def _assert_from_environment_not_called(self, extra_args: list[str] | None) -> None:
        with mock.patch.object(
            ThreadsClient, "from_environment", side_effect=AssertionError("Threads API가 호출되면 안 됩니다")
        ) as mocked:
            exit_code = self._run(extra_args)
        mocked.assert_not_called()
        return exit_code

    # --- 1. approved 1건이 dry-run에서 조회되는지 --------------------------------

    def test_dry_run_lists_approved_draft(self) -> None:
        self._seed(_approved_draft())

        exit_code = self._assert_from_environment_not_called(["--dry-run"])

        self.assertEqual(exit_code, 0)

    # --- 2. dry-run에서 API 호출 횟수 == 0 ----------------------------------------

    def test_dry_run_calls_api_zero_times(self) -> None:
        self._seed(_approved_draft())
        self._assert_from_environment_not_called(["--dry-run"])

    # --- 16. 기본 실행(플래그 없음)에서도 API를 호출하지 않는지 -------------------

    def test_default_run_without_flags_calls_api_zero_times(self) -> None:
        self._seed(_approved_draft())
        exit_code = self._assert_from_environment_not_called(None)
        self.assertEqual(exit_code, 0)

    # --- 3. dry-run에서 pending/history가 변경되지 않는지 -------------------------

    def test_dry_run_does_not_modify_pending_or_history(self) -> None:
        draft = _approved_draft()
        self._seed(draft)

        self._assert_from_environment_not_called(["--dry-run"])

        reloaded = load_pending(self.pending_path)[0]
        self.assertEqual(reloaded, draft)
        self.assertFalse(self.history_path.exists())

    def test_default_run_does_not_modify_pending_or_history(self) -> None:
        draft = _approved_draft()
        self._seed(draft)

        self._assert_from_environment_not_called(None)

        reloaded = load_pending(self.pending_path)[0]
        self.assertEqual(reloaded, draft)
        self.assertFalse(self.history_path.exists())

    # --- 4. execute에서 final_title/final_body가 API로 전달되는지 -----------------

    def test_execute_publishes_final_body_not_ai_rewritten(self) -> None:
        draft = _approved_draft(
            ai_rewritten_title="AI 원본 제목",
            ai_rewritten_body="AI 원본 본문",
            final_title="티몽이 고친 제목",
            final_body="티몽이 고친 본문",
        )
        self._seed(draft)
        fake_client = FakeThreadsClient()

        with mock.patch.object(ThreadsClient, "from_environment", return_value=fake_client):
            exit_code = self._run(["--execute"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(fake_client.publish_text_calls, ["티몽이 고친 본문"])

    # --- 5, 6. 성공하면 published 상태 + threads_post_id 저장 ----------------------

    def test_execute_success_marks_published_with_post_id(self) -> None:
        self._seed(_approved_draft())
        fake_client = FakeThreadsClient(result=ThreadsPublishResult(id="th_success_1"))

        with mock.patch.object(ThreadsClient, "from_environment", return_value=fake_client):
            exit_code = self._run(["--execute"])

        self.assertEqual(exit_code, 0)
        updated = load_pending(self.pending_path)[0]
        self.assertEqual(updated.status, "published")
        self.assertEqual(updated.threads_post_id, "th_success_1")
        self.assertIsNotNone(updated.published_at)

    # --- 7. 성공하면 PublishHistory에 기록되는지 ----------------------------------

    def test_execute_success_appends_publish_history(self) -> None:
        draft = _approved_draft()
        self._seed(draft)
        fake_client = FakeThreadsClient(result=ThreadsPublishResult(id="th_success_2"))

        with mock.patch.object(ThreadsClient, "from_environment", return_value=fake_client):
            self._run(["--execute"])

        history = PublishHistory(self.history_path)
        self.assertTrue(history.is_published(draft.content_id))
        records = history.load()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["threads_post_id"], "th_success_2")
        self.assertEqual(records[0]["knowledge_id"], draft.knowledge_id)

    # --- 8. API 실패 시 failed 상태가 되는지 --------------------------------------

    def test_execute_failure_marks_failed_with_reason(self) -> None:
        self._seed(_approved_draft())
        fake_client = FakeThreadsClient(error=ThreadsAPIError("Threads HTTP 500: message=server error"))

        with mock.patch.object(ThreadsClient, "from_environment", return_value=fake_client):
            exit_code = self._run(["--execute"])

        self.assertEqual(exit_code, 1)
        updated = load_pending(self.pending_path)[0]
        self.assertEqual(updated.status, "failed")
        self.assertIn("500", updated.failure_reason)
        self.assertIsNotNone(updated.failed_at)

    # --- 9. API 실패 시 PublishHistory에 기록되지 않는지 --------------------------

    def test_execute_failure_does_not_touch_publish_history(self) -> None:
        self._seed(_approved_draft())
        fake_client = FakeThreadsClient(error=ThreadsAPIError("Threads HTTP 500: message=server error"))

        with mock.patch.object(ThreadsClient, "from_environment", return_value=fake_client):
            self._run(["--execute"])

        self.assertFalse(self.history_path.exists())

    # --- 10. pending은 발행하지 않는지 --------------------------------------------

    def test_pending_status_is_not_published(self) -> None:
        self._seed(_draft(status="pending"))

        exit_code = self._assert_from_environment_not_called(["--execute"])

        self.assertEqual(exit_code, 0)
        reloaded = load_pending(self.pending_path)[0]
        self.assertEqual(reloaded.status, "pending")

    # --- 11. published는 발행하지 않는지 ------------------------------------------

    def test_published_status_is_not_republished(self) -> None:
        published = mark_published(_approved_draft(), threads_post_id="th_already", published_at="2026-09-15T00:00:00+00:00")
        self._seed(published)

        exit_code = self._assert_from_environment_not_called(["--execute"])

        self.assertEqual(exit_code, 0)
        reloaded = load_pending(self.pending_path)[0]
        self.assertEqual(reloaded.threads_post_id, "th_already")

    def test_failed_status_is_not_auto_republished(self) -> None:
        """failed는 자동 재발행 대상이 아니다 - 다시 approved로 승인되어야만 대상이 된다."""
        failed = mark_failed(_approved_draft(), failure_reason="이전 실패", failed_at="2026-09-15T00:00:00+00:00")
        self._seed(failed)

        exit_code = self._assert_from_environment_not_called(["--execute"])

        self.assertEqual(exit_code, 0)
        reloaded = load_pending(self.pending_path)[0]
        self.assertEqual(reloaded.status, "failed")

    # --- 12. history에 이미 content_id가 있으면 API를 호출하지 않는지 -------------

    def test_content_id_already_in_history_skips_api_call(self) -> None:
        draft = _approved_draft()
        self._seed(draft)
        PublishHistory(self.history_path).append(
            PublishRecord(
                content_id=draft.content_id,
                published_at="2026-09-14T00:00:00+00:00",
                threads_post_id="th_preexisting",
                knowledge_id=draft.knowledge_id,
                platform="threads",
                source_url=draft.source_url,
            )
        )

        exit_code = self._assert_from_environment_not_called(["--execute"])

        self.assertEqual(exit_code, 0)
        # 이미 history에 있던 draft는 API 호출 없이 published로 동기화된다.
        updated = load_pending(self.pending_path)[0]
        self.assertEqual(updated.status, "published")
        self.assertEqual(updated.threads_post_id, "th_preexisting")
        # history에는 여전히 레코드 1건만 있어야 한다(중복 추가 없음).
        self.assertEqual(len(PublishHistory(self.history_path).load()), 1)

    def test_content_id_already_in_history_is_untouched_in_dry_run(self) -> None:
        draft = _approved_draft()
        self._seed(draft)
        PublishHistory(self.history_path).append(
            PublishRecord(
                content_id=draft.content_id,
                published_at="2026-09-14T00:00:00+00:00",
                threads_post_id="th_preexisting",
                knowledge_id=draft.knowledge_id,
                platform="threads",
                source_url=draft.source_url,
            )
        )

        self._assert_from_environment_not_called(["--dry-run"])

        reloaded = load_pending(self.pending_path)[0]
        self.assertEqual(reloaded.status, "approved")  # dry-run이므로 동기화도 하지 않음

    # --- 13. --id가 지정되면 해당 content_id만 처리하는지 -------------------------

    def test_id_flag_limits_to_single_content_id(self) -> None:
        draft_a = _approved_draft(content_id="content-a")
        draft_b = _approved_draft(content_id="content-b")
        self._seed(draft_a, draft_b)
        fake_client = FakeThreadsClient(result=ThreadsPublishResult(id="th_a"))

        with mock.patch.object(ThreadsClient, "from_environment", return_value=fake_client):
            exit_code = self._run(["--execute", "--id", "content-a"])

        self.assertEqual(exit_code, 0)
        by_id = {d.content_id: d for d in load_pending(self.pending_path)}
        self.assertEqual(by_id["content-a"].status, "published")
        self.assertEqual(by_id["content-b"].status, "approved")  # 건드리지 않음
        self.assertEqual(len(fake_client.publish_text_calls), 1)

    def test_id_flag_with_unknown_content_id_errors(self) -> None:
        self._seed(_approved_draft())

        exit_code = self._assert_from_environment_not_called(["--execute", "--id", "does-not-exist"])

        self.assertEqual(exit_code, 1)

    # --- 14. final_title/body가 없는 approved 항목을 안전하게 거부하는지 ---------

    def test_approved_without_final_fields_is_rejected_safely(self) -> None:
        # mark_approved()는 항상 final_*을 채우므로, 손상된 데이터를 흉내내기 위해
        # save_pending으로 직접 status만 approved인 draft를 만든다.
        broken = _draft(status="approved", final_title=None, final_body=None, approved_at="2026-09-16T00:30:00+00:00")
        self._seed(broken)

        exit_code = self._assert_from_environment_not_called(["--execute"])

        self.assertEqual(exit_code, 1)
        reloaded = load_pending(self.pending_path)[0]
        self.assertEqual(reloaded.status, "approved")  # 상태는 바뀌지 않음(단순 오류 보고)

    def test_approved_with_blank_final_body_is_rejected_safely(self) -> None:
        broken = _draft(status="approved", final_title="제목", final_body="   ", approved_at="2026-09-16T00:30:00+00:00")
        self._seed(broken)

        exit_code = self._assert_from_environment_not_called(["--execute"])

        self.assertEqual(exit_code, 1)

    # --- 15. --dry-run + --execute 동시 지정 시 거부하는지 ------------------------

    def test_dry_run_and_execute_together_is_rejected(self) -> None:
        self._seed(_approved_draft())

        exit_code = self._assert_from_environment_not_called(["--dry-run", "--execute"])

        self.assertEqual(exit_code, 1)

    # --- 그 외: 승인된 초안이 아예 없을 때 -----------------------------------------

    def test_no_approved_drafts_exits_zero(self) -> None:
        self._seed(_draft(status="pending"))

        exit_code = self._assert_from_environment_not_called(["--execute"])

        self.assertEqual(exit_code, 0)

    def test_no_pending_file_exits_zero(self) -> None:
        exit_code = self._assert_from_environment_not_called(["--execute"])
        self.assertEqual(exit_code, 0)

    # --- (Phase 4 설계 문서 10장 갭 보강) approved 여러 건 부분 실패 ----------------

    def test_multiple_approved_partial_failure_reports_correctly(self) -> None:
        """approved 2건을 --id 없이 처리: 첫 번째는 API 실패, 두 번째는 성공.

        - 첫 번째는 failed, 두 번째는 published가 되어야 한다.
        - 성공한 두 번째만 PublishHistory에 기록되고, 실패한 첫 번째는 기록되지
          않아야 한다.
        - 전체 실행 결과(exit code)는 부분 실패를 정확히 반영해 0이 아니어야 한다.
        """
        draft_first = _approved_draft(content_id="content-first", final_body="첫 번째 본문")
        draft_second = _approved_draft(content_id="content-second", final_body="두 번째 본문")
        self._seed(draft_first, draft_second)

        fake_client = FakeThreadsClient(
            outcomes=[
                ThreadsAPIError("Threads HTTP 500: message=first item failed"),
                ThreadsPublishResult(id="th_second_success"),
            ]
        )

        with mock.patch.object(ThreadsClient, "from_environment", return_value=fake_client):
            exit_code = self._run(["--execute"])

        # 전체 결과는 부분 실패를 정확히 보고해야 한다(하나라도 실패하면 0이 아님).
        self.assertEqual(exit_code, 1)

        by_id = {d.content_id: d for d in load_pending(self.pending_path)}
        self.assertEqual(by_id["content-first"].status, "failed")
        self.assertIn("500", by_id["content-first"].failure_reason)
        self.assertEqual(by_id["content-second"].status, "published")
        self.assertEqual(by_id["content-second"].threads_post_id, "th_second_success")

        # PublishHistory에는 성공한 두 번째 건만 기록되고, 실패한 첫 번째는 없어야 한다.
        history = PublishHistory(self.history_path)
        self.assertFalse(history.is_published("content-first"))
        self.assertTrue(history.is_published("content-second"))
        records = history.load()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["content_id"], "content-second")

        # 두 draft 모두 실제로 API 호출을 받았어야 한다(하나가 실패해도 나머지는 계속 처리).
        self.assertEqual(fake_client.publish_text_calls, ["첫 번째 본문", "두 번째 본문"])

    # --- (Phase 4 설계 문서 10장 갭 보강) 실패 → 재승인 → 재실행 → 성공 -----------

    def test_failed_then_reapproved_then_reexecuted_succeeds(self) -> None:
        """실패한 draft를 사람이 다시 approved로 되돌린 뒤 재실행하면 정상 발행되는지
        end-to-end로 검증한다(자동 재시도가 아니라, 재승인이라는 명시적 사람의 조치를
        거쳐야만 다시 대상이 된다는 계약도 함께 확인)."""
        draft = _approved_draft(content_id="content-retry", final_body="재시도 대상 본문")
        self._seed(draft)

        # 1차 시도: 실패 -> failed 상태 + failure_reason 저장, PublishHistory 불변.
        failing_client = FakeThreadsClient(error=ThreadsAPIError("Threads HTTP 500: message=temporary outage"))
        with mock.patch.object(ThreadsClient, "from_environment", return_value=failing_client):
            first_exit_code = self._run(["--execute"])

        self.assertEqual(first_exit_code, 1)
        failed_draft = load_pending(self.pending_path)[0]
        self.assertEqual(failed_draft.status, "failed")
        self.assertIn("500", failed_draft.failure_reason)
        self.assertIsNotNone(failed_draft.failed_at)
        self.assertFalse(PublishHistory(self.history_path).is_published("content-retry"))
        self.assertEqual(PublishHistory(self.history_path).load(), [])

        # 재승인되기 전까지는 자동으로 다시 대상이 되지 않는다(failed는 approved 필터에서 제외).
        with mock.patch.object(
            ThreadsClient, "from_environment", side_effect=AssertionError("재승인 전에는 API가 호출되면 안 됩니다")
        ):
            still_failed_exit_code = self._run(["--execute"])
        self.assertEqual(still_failed_exit_code, 0)  # 발행 대상 없음(정상 종료)
        self.assertEqual(load_pending(self.pending_path)[0].status, "failed")  # 상태 불변

        # 사람이 재승인: failed -> approved (재시도 텍스트를 그대로 다시 확정한다고 가정).
        reapproved = mark_approved(
            failed_draft,
            final_title=failed_draft.final_title,
            final_body=failed_draft.final_body,
            approved_at="2026-09-17T00:00:00+00:00",
        )
        upsert_pending(self.pending_path, reapproved)
        self.assertEqual(load_pending(self.pending_path)[0].status, "approved")

        # 2차 시도: 재실행하면 API가 호출되고 성공 -> published + PublishHistory 기록.
        succeeding_client = FakeThreadsClient(result=ThreadsPublishResult(id="th_retry_success"))
        with mock.patch.object(ThreadsClient, "from_environment", return_value=succeeding_client):
            second_exit_code = self._run(["--execute"])

        self.assertEqual(second_exit_code, 0)
        self.assertEqual(succeeding_client.publish_text_calls, ["재시도 대상 본문"])
        final_draft = load_pending(self.pending_path)[0]
        self.assertEqual(final_draft.status, "published")
        self.assertEqual(final_draft.threads_post_id, "th_retry_success")

        history = PublishHistory(self.history_path)
        self.assertTrue(history.is_published("content-retry"))
        records = history.load()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["threads_post_id"], "th_retry_success")


if __name__ == "__main__":
    unittest.main()
