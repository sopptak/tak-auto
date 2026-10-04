"""content_engine/threads_review.py 검증 (5-11 설계 문서 Phase 1).

PublishHistory/PublishRecord는 이 테스트에서 전혀 참조하지 않는다 - 완전히 별도
구조라는 설계 결정 자체를 검증 대상으로 삼는다.
"""

from __future__ import annotations

from pathlib import Path
import json
import tempfile
import unittest

from content_engine.threads_review import (
    ThreadsPendingDraft,
    ThreadsPendingError,
    has_unresolved_draft,
    load_pending,
    mark_approved,
    mark_failed,
    mark_published,
    save_pending,
    upsert_pending,
)


def _draft(**overrides) -> ThreadsPendingDraft:
    fields = {
        "content_id": "content-abc123",
        "knowledge_id": "knowledge-1",
        "source_url": "https://example.test/source",
        "evidence_unit_ids": ("lesson:1",),
        "article_type": "experience",
        "knowledge_type": "경험",
        "original_title": "원본 제목",
        "original_body": "원본 본문",
        "ai_rewritten_title": "AI 재작성 제목",
        "ai_rewritten_body": "AI가 재작성한 본문입니다.",
        "status": "pending",
        "created_at": "2026-09-16T00:00:00+00:00",
    }
    fields.update(overrides)
    return ThreadsPendingDraft(**fields)


class ThreadsPendingDraftValidationTests(unittest.TestCase):
    """필수 필드 검증 + 잘못된 status 거부."""

    def test_missing_content_id_raises(self):
        with self.assertRaises(ThreadsPendingError):
            _draft(content_id="")

    def test_missing_knowledge_id_raises(self):
        with self.assertRaises(ThreadsPendingError):
            _draft(knowledge_id="")

    def test_missing_created_at_raises(self):
        with self.assertRaises(ThreadsPendingError):
            _draft(created_at="")

    def test_invalid_status_raises(self):
        with self.assertRaises(ThreadsPendingError):
            _draft(status="in_review")

    def test_from_dict_rejects_invalid_status(self):
        with self.assertRaises(ThreadsPendingError):
            ThreadsPendingDraft.from_dict({**_draft().to_dict(), "status": "not_a_real_status"})

    def test_from_dict_rejects_non_dict(self):
        with self.assertRaises(ThreadsPendingError):
            ThreadsPendingDraft.from_dict("not a dict")  # type: ignore[arg-type]

    def test_from_dict_rejects_non_list_evidence_unit_ids(self):
        with self.assertRaises(ThreadsPendingError):
            ThreadsPendingDraft.from_dict({**_draft().to_dict(), "evidence_unit_ids": "lesson:1"})

    def test_valid_statuses_all_construct_successfully(self):
        for status in ("pending", "approved", "published", "failed"):
            draft = _draft(status=status)
            self.assertEqual(draft.status, status)


class ThreadsPendingStorageTests(unittest.TestCase):
    """save/load round trip + 원자적 저장."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.path = Path(self.tmp_dir.name) / "tak_threads_pending.json"

    def test_missing_file_loads_as_empty(self):
        self.assertEqual(load_pending(self.path), [])

    def test_empty_file_loads_as_empty(self):
        self.path.write_text("", encoding="utf-8")
        self.assertEqual(load_pending(self.path), [])

    def test_whitespace_only_file_loads_as_empty(self):
        self.path.write_text("   \n", encoding="utf-8")
        self.assertEqual(load_pending(self.path), [])

    def test_corrupted_json_raises(self):
        self.path.write_text("{not valid json", encoding="utf-8")
        with self.assertRaises(ThreadsPendingError):
            load_pending(self.path)

    def test_non_list_json_raises(self):
        self.path.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
        with self.assertRaises(ThreadsPendingError):
            load_pending(self.path)

    def test_save_and_load_round_trip(self):
        draft = _draft()
        save_pending([draft], self.path)

        loaded = load_pending(self.path)

        self.assertEqual(loaded, [draft])

    def test_round_trip_preserves_all_fields_including_none(self):
        draft = _draft(status="failed", final_title=None, final_body=None, failure_reason="Threads HTTP 500")
        save_pending([draft], self.path)

        loaded = load_pending(self.path)[0]

        self.assertEqual(loaded.final_title, None)
        self.assertEqual(loaded.failure_reason, "Threads HTTP 500")

    def test_save_creates_parent_directory(self):
        nested_path = Path(self.tmp_dir.name) / "nested" / "tak_threads_pending.json"
        save_pending([_draft()], nested_path)
        self.assertTrue(nested_path.exists())

    def test_atomic_save_leaves_no_stray_temp_files(self):
        """tempfile + Path.replace() 방식이므로, 저장 후 디렉터리에는 최종 파일 하나만 남아야 한다."""
        save_pending([_draft()], self.path)
        save_pending([_draft(content_id="content-def456")], self.path)

        files_in_dir = list(self.path.parent.iterdir())

        self.assertEqual(files_in_dir, [self.path])

    def test_atomic_save_file_is_never_partially_written(self):
        """저장된 파일은 항상 완전한 JSON이어야 한다(중간에 잘린 파일이 남지 않음)."""
        save_pending([_draft(), _draft(content_id="content-def456")], self.path)

        # 파일을 다시 읽어 유효한 JSON인지, 두 건 모두 온전한지 확인한다.
        raw = self.path.read_text(encoding="utf-8")
        data = json.loads(raw)
        self.assertEqual(len(data), 2)

    def test_upsert_overwrites_same_content_id(self):
        upsert_pending(self.path, _draft(status="pending"))
        upsert_pending(self.path, _draft(status="approved", final_title="t", final_body="b", approved_at="now"))

        loaded = load_pending(self.path)

        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].status, "approved")

    def test_upsert_adds_new_content_id(self):
        upsert_pending(self.path, _draft(content_id="content-1"))
        upsert_pending(self.path, _draft(content_id="content-2"))

        loaded = load_pending(self.path)

        self.assertEqual({draft.content_id for draft in loaded}, {"content-1", "content-2"})


class HasUnresolvedDraftTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.path = Path(self.tmp_dir.name) / "tak_threads_pending.json"

    def test_no_file_means_no_unresolved_draft(self):
        self.assertFalse(has_unresolved_draft(self.path))

    def test_pending_is_unresolved(self):
        save_pending([_draft(status="pending")], self.path)
        self.assertTrue(has_unresolved_draft(self.path))

    def test_approved_is_unresolved(self):
        save_pending([_draft(status="approved")], self.path)
        self.assertTrue(has_unresolved_draft(self.path))

    def test_published_is_not_unresolved(self):
        save_pending([_draft(status="published")], self.path)
        self.assertFalse(has_unresolved_draft(self.path))

    def test_failed_is_not_unresolved(self):
        save_pending([_draft(status="failed")], self.path)
        self.assertFalse(has_unresolved_draft(self.path))

    def test_mixed_published_and_pending_is_unresolved(self):
        save_pending([_draft(content_id="c1", status="published"), _draft(content_id="c2", status="pending")], self.path)
        self.assertTrue(has_unresolved_draft(self.path))


class StateTransitionTests(unittest.TestCase):
    """pending -> approved -> published/failed, failed -> approved, 잘못된 전이 거부."""

    def test_pending_to_approved(self):
        draft = _draft(status="pending")

        approved = mark_approved(draft, final_title="최종 제목", final_body="최종 본문", approved_at="2026-09-16T01:00:00+00:00")

        self.assertEqual(approved.status, "approved")
        self.assertEqual(approved.final_title, "최종 제목")
        self.assertEqual(approved.final_body, "최종 본문")
        self.assertEqual(approved.approved_at, "2026-09-16T01:00:00+00:00")

    def test_approve_without_edit_sets_edited_by_user_false(self):
        draft = _draft(status="pending")

        approved = mark_approved(
            draft,
            final_title=draft.ai_rewritten_title,
            final_body=draft.ai_rewritten_body,
            approved_at="now",
        )

        self.assertFalse(approved.edited_by_user)

    def test_approve_with_edit_sets_edited_by_user_true(self):
        draft = _draft(status="pending")

        approved = mark_approved(draft, final_title="티몽이 고친 제목", final_body=draft.ai_rewritten_body, approved_at="now")

        self.assertTrue(approved.edited_by_user)

    def test_approved_to_published(self):
        draft = _draft(status="approved", final_title="t", final_body="b", approved_at="now")

        published = mark_published(draft, threads_post_id="th_123", published_at="2026-09-16T02:00:00+00:00")

        self.assertEqual(published.status, "published")
        self.assertEqual(published.threads_post_id, "th_123")
        self.assertEqual(published.published_at, "2026-09-16T02:00:00+00:00")

    def test_approved_to_failed(self):
        draft = _draft(status="approved", final_title="t", final_body="b", approved_at="now")

        failed = mark_failed(draft, failure_reason="Threads HTTP 500", failed_at="2026-09-16T02:00:00+00:00")

        self.assertEqual(failed.status, "failed")
        self.assertEqual(failed.failure_reason, "Threads HTTP 500")
        self.assertEqual(failed.failed_at, "2026-09-16T02:00:00+00:00")

    def test_failed_to_approved_retry(self):
        draft = _draft(status="failed", final_title="t", final_body="b", failure_reason="Threads HTTP 500")

        retried = mark_approved(draft, final_title="재승인된 제목", final_body="재승인된 본문", approved_at="2026-09-17T00:00:00+00:00")

        self.assertEqual(retried.status, "approved")
        self.assertEqual(retried.final_title, "재승인된 제목")

    # --- 잘못된 상태 전이 거부 -----------------------------------------------

    def test_pending_to_published_directly_rejected(self):
        draft = _draft(status="pending")
        with self.assertRaises(ThreadsPendingError):
            mark_published(draft, threads_post_id="th_1", published_at="now")

    def test_pending_to_failed_directly_rejected(self):
        draft = _draft(status="pending")
        with self.assertRaises(ThreadsPendingError):
            mark_failed(draft, failure_reason="오류", failed_at="now")

    def test_published_is_terminal_cannot_transition_again(self):
        draft = _draft(status="published", threads_post_id="th_1", published_at="now")
        with self.assertRaises(ThreadsPendingError):
            mark_approved(draft, final_title="t", final_body="b", approved_at="now")

    def test_failed_cannot_go_directly_to_published(self):
        draft = _draft(status="failed", failure_reason="오류")
        with self.assertRaises(ThreadsPendingError):
            mark_published(draft, threads_post_id="th_1", published_at="now")

    def test_approved_cannot_approve_again(self):
        draft = _draft(status="approved", final_title="t", final_body="b", approved_at="now")
        with self.assertRaises(ThreadsPendingError):
            mark_approved(draft, final_title="t2", final_body="b2", approved_at="later")


if __name__ == "__main__":
    unittest.main()
