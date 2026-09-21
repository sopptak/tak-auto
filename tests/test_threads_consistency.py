"""content_engine.threads_consistency / scripts/audit_threads_publish_consistency.py
검증(6-15).

이 모듈은 Threads pending draft와 실제 게시 이력을 전수 대조해 6개 상태
(CONSISTENT/PUBLISHED_BUT_PENDING_STALE/PENDING_WITHOUT_PUBLISH_LOG/FAILED/
ORPHAN/DUPLICATE)로 분류한다. 읽기 전용이므로 이 테스트도 파일을 쓰지 않는다
(save_consistency_report()만 예외적으로 임시 디렉터리에 쓴다).
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from content_engine.threads_consistency import (
    CONSISTENT,
    DUPLICATE,
    FAILED,
    ORPHAN,
    PENDING_WITHOUT_PUBLISH_LOG,
    PUBLISHED_BUT_PENDING_STALE,
    audit_threads_consistency,
    render_consistency_markdown,
    save_consistency_report,
    summarize,
)
from content_engine.threads_review import ThreadsPendingDraft


def _draft(content_id: str, status: str, **overrides) -> ThreadsPendingDraft:
    fields = dict(
        content_id=content_id,
        knowledge_id="knowledge-x",
        source_url="https://example.com",
        evidence_unit_ids=("lesson:1",),
        article_type=None,
        knowledge_type="의견",
        original_title="원문",
        original_body="본문",
        ai_rewritten_title="제목",
        ai_rewritten_body="본문",
        status=status,
        created_at="2026-09-01T00:00:00+00:00",
    )
    fields.update(overrides)
    return ThreadsPendingDraft(**fields)


def _log(content_id: str, post_id: str = "post-1", **overrides) -> dict:
    record = {
        "content_id": content_id,
        "published_at": "2026-09-02T00:00:00+00:00",
        "threads_post_id": post_id,
        "knowledge_id": "knowledge-x",
        "platform": "threads",
        "source_url": "https://example.com",
    }
    record.update(overrides)
    return record


class ThreadsConsistencyClassificationTests(unittest.TestCase):
    def test_published_matching_is_consistent(self):
        draft = _draft("content-1", "published", threads_post_id="post-1", published_at="2026-09-02T00:00:00+00:00")
        results = audit_threads_consistency([draft], [_log("content-1", "post-1")])
        self.assertEqual(results[0].status, CONSISTENT)
        self.assertFalse(results[0].safe_to_sync)

    def test_approved_with_real_log_post_id_is_stale_and_safe_to_sync(self):
        """6-15에서 실제로 발견한 content-43786cf3ee0d89c5와 동일한 패턴:
        approved인데 게시 이력에는 이미 실제 post_id가 있다."""
        draft = _draft("content-2", "approved")
        results = audit_threads_consistency([draft], [_log("content-2", "post-2")])
        self.assertEqual(results[0].status, PUBLISHED_BUT_PENDING_STALE)
        self.assertTrue(results[0].safe_to_sync)
        self.assertEqual(results[0].log_post_id, "post-2")

    def test_pending_status_with_real_log_post_id_is_stale_but_not_auto_syncable(self):
        """status=='pending'(승인 전)은 publish_approved_threads.py가 처리할 수 있는
        상태 전이 목록에 없으므로, 실제 게시 이력이 있어도 자동 복구 대상이 아니다 -
        사람이 확인해야 한다(6-15 지시 9장: 조건이 명확하지 않으면 NEEDS_REVIEW)."""
        draft = _draft("content-3", "pending")
        results = audit_threads_consistency([draft], [_log("content-3", "post-3")])
        self.assertEqual(results[0].status, PUBLISHED_BUT_PENDING_STALE)
        self.assertFalse(results[0].safe_to_sync)

    def test_pending_without_log_is_normal(self):
        draft = _draft("content-4", "pending")
        results = audit_threads_consistency([draft], [])
        self.assertEqual(results[0].status, PENDING_WITHOUT_PUBLISH_LOG)

    def test_approved_without_log_is_normal(self):
        draft = _draft("content-5", "approved")
        results = audit_threads_consistency([draft], [])
        self.assertEqual(results[0].status, PENDING_WITHOUT_PUBLISH_LOG)

    def test_failed_without_log_is_failed(self):
        draft = _draft("content-6", "failed", failure_reason="네트워크 오류")
        results = audit_threads_consistency([draft], [])
        self.assertEqual(results[0].status, FAILED)

    def test_log_only_entry_is_orphan(self):
        """pending 게이트 도입 이전 레거시 자동 발행 경로(scripts/publish_threads.py)로
        게시된 콘텐츠는 pending 파일에 없는 것이 정상이지만, 사람이 한 번은 확인할 수
        있도록 ORPHAN으로 표시한다."""
        results = audit_threads_consistency([], [_log("content-7", "post-7")])
        self.assertEqual(results[0].status, ORPHAN)
        self.assertFalse(results[0].safe_to_sync)

    def test_published_pending_without_log_is_orphan(self):
        draft = _draft("content-8", "published", threads_post_id="post-8", published_at="x")
        results = audit_threads_consistency([draft], [])
        self.assertEqual(results[0].status, ORPHAN)

    def test_mismatched_post_id_is_orphan(self):
        draft = _draft("content-9", "published", threads_post_id="post-WRONG", published_at="x")
        results = audit_threads_consistency([draft], [_log("content-9", "post-RIGHT")])
        self.assertEqual(results[0].status, ORPHAN)

    def test_duplicate_pending_entries_is_duplicate(self):
        drafts = [_draft("content-10", "pending"), _draft("content-10", "approved")]
        results = audit_threads_consistency(drafts, [])
        self.assertEqual(results[0].status, DUPLICATE)

    def test_duplicate_log_entries_is_duplicate(self):
        draft = _draft("content-11", "approved")
        results = audit_threads_consistency([draft], [_log("content-11", "post-a"), _log("content-11", "post-b")])
        self.assertEqual(results[0].status, DUPLICATE)

    def test_summarize_always_includes_all_six_statuses(self):
        summary = summarize(())
        self.assertEqual(
            set(summary),
            {CONSISTENT, PUBLISHED_BUT_PENDING_STALE, PENDING_WITHOUT_PUBLISH_LOG, FAILED, ORPHAN, DUPLICATE},
        )
        self.assertTrue(all(count == 0 for count in summary.values()))


class ThreadsConsistencyReportTests(unittest.TestCase):
    def test_render_markdown_lists_safe_to_sync_section(self):
        draft = _draft("content-2", "approved")
        results = audit_threads_consistency([draft], [_log("content-2", "post-2")])
        markdown = render_consistency_markdown(results, generated_at="2026-09-21T00:00:00+00:00")
        self.assertIn("content-2", markdown)
        self.assertIn("자동 복구 가능", markdown)
        self.assertIn("PUBLISHED_BUT_PENDING_STALE", markdown)

    def test_save_consistency_report_writes_file_only(self):
        draft = _draft("content-1", "published", threads_post_id="post-1", published_at="x")
        results = audit_threads_consistency([draft], [_log("content-1", "post-1")])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.md"
            save_consistency_report(results, path, generated_at="2026-09-21T00:00:00+00:00")
            self.assertTrue(path.exists())
            self.assertIn("CONSISTENT", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
