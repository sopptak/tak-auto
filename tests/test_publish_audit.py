"""content_engine.publish_audit 검증(6-14).

이 모듈은 순수 판정 로직이다 - 실제 파일 I/O는 이 테스트가 직접 만든 임시
저장소(PublishHistory/YouTubeUploadHistory 등, 전부 tempfile)로만 수행하고,
실제 외부 API(Threads/YouTube/Naver)는 이 파일 어디에서도 호출하지 않는다.
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from content_engine.media_archive import MediaArchiveRecord
from content_engine.publish_audit import (
    ALREADY_PUBLISHED,
    BLOCKED,
    ERROR,
    NEEDS_HUMAN_REVIEW,
    READY,
    PublishAuditInputs,
    audit_archive,
    audit_record,
    render_readiness_markdown,
    save_readiness_report,
    summarize,
)
from content_engine.publish_history import PublishHistory, PublishRecord
from content_engine.threads_review import ThreadsPendingDraft
from content_engine.youtube_upload_history import YouTubeUploadHistory, YouTubeUploadRecord
from tak_brain import KnowledgeRecord


def _knowledge(**overrides) -> KnowledgeRecord:
    fields = dict(
        id="knowledge-audit-1",
        source_url="https://example.test/article",
        title="원문 제목",
        article_type="experience",
        domain="자기계발",
        category="자기계발",
        knowledge_type="경험",
    )
    fields.update(overrides)
    return KnowledgeRecord(**fields)


def _record(**overrides) -> MediaArchiveRecord:
    fields = dict(
        content_id="content-audit-1",
        knowledge_id="knowledge-audit-1",
        platform="blog",
        generation_status="valid",
        original_title="원본 제목",
        original_body="원본 본문",
        rewritten_title="AI 재작성 제목",
        rewritten_body="AI가 재작성한 본문입니다.",
        source_url="https://example.test/article",
        evidence=(),
        evidence_unit_ids=("lesson:1",),
        created_at="2026-09-21T00:00:00+00:00",
        review_status="approved",
    )
    fields.update(overrides)
    return MediaArchiveRecord(**fields)


class AuditRecordBasicStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.inputs = PublishAuditInputs(knowledge_by_id={"knowledge-audit-1": _knowledge()})

    def _audit(self, record: MediaArchiveRecord, **overrides):
        inputs = overrides.pop("inputs", self.inputs)
        return audit_record(record, duplicate_content_ids=frozenset(), inputs=inputs)

    def test_approved_blog_becomes_ready(self):
        result = self._audit(_record(review_status="approved"))
        self.assertEqual(result.status, READY)

    def test_unreviewed_is_blocked(self):
        result = self._audit(_record(review_status="unreviewed"))
        self.assertEqual(result.status, BLOCKED)
        self.assertTrue(any("review_status" in reason for reason in result.reasons))

    def test_dismissed_is_blocked(self):
        result = self._audit(_record(review_status="dismissed"))
        self.assertEqual(result.status, BLOCKED)

    def test_rejected_generation_status_is_blocked_even_if_approved(self):
        result = self._audit(_record(review_status="approved", generation_status="rejected"))
        self.assertEqual(result.status, BLOCKED)
        self.assertTrue(any("generation_status" in reason for reason in result.reasons))

    def test_missing_source_url_is_blocked(self):
        result = self._audit(_record(review_status="approved", source_url=""))
        self.assertEqual(result.status, BLOCKED)
        self.assertTrue(any("source_url" in reason for reason in result.reasons))

    def test_missing_title_is_blocked(self):
        result = self._audit(
            _record(review_status="approved", rewritten_title=None, original_title="")
        )
        self.assertEqual(result.status, BLOCKED)
        self.assertTrue(any("제목" in reason for reason in result.reasons))

    def test_missing_body_is_blocked(self):
        result = self._audit(
            _record(review_status="approved", rewritten_body=None, original_body="")
        )
        self.assertEqual(result.status, BLOCKED)
        self.assertTrue(any("본문" in reason for reason in result.reasons))

    def test_finance_sensitive_approved_content_needs_human_review_not_ready(self):
        inputs = PublishAuditInputs(
            knowledge_by_id={
                "knowledge-audit-1": _knowledge(article_type="finance", category="금융", domain="금융")
            }
        )
        result = self._audit(_record(review_status="approved"), inputs=inputs)
        self.assertEqual(result.status, NEEDS_HUMAN_REVIEW)

    def test_unknown_knowledge_defaults_to_needs_human_review(self):
        """is_review_required()는 knowledge를 찾지 못하면 안전한 쪽(True)을
        기본값으로 삼는다(기존 5-10 설계) - 이 모듈도 그 판정을 그대로 재사용하므로
        동일하게 안전한 쪽으로 기운다."""
        empty_inputs = PublishAuditInputs(knowledge_by_id={})
        result = self._audit(_record(review_status="approved"), inputs=empty_inputs)
        self.assertEqual(result.status, NEEDS_HUMAN_REVIEW)


class AuditRecordDuplicateContentIdTests(unittest.TestCase):
    def test_duplicate_content_id_is_error(self):
        inputs = PublishAuditInputs(knowledge_by_id={"knowledge-audit-1": _knowledge()})
        result = audit_record(
            _record(review_status="approved"),
            duplicate_content_ids=frozenset({"content-audit-1"}),
            inputs=inputs,
        )
        self.assertEqual(result.status, ERROR)


class AuditRecordBlogAlreadyPublishedTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        self.blog_history_path = Path(tmp_dir.name) / "blog_publish_log.json"

    def test_blog_already_published_takes_priority_over_ready(self):
        history = PublishHistory(self.blog_history_path)
        history.append(
            PublishRecord(
                content_id="content-audit-1",
                published_at="2026-09-20T00:00:00+00:00",
                threads_post_id="manual",
                knowledge_id="knowledge-audit-1",
                platform="blog",
                source_url="https://example.test/article",
            )
        )
        inputs = PublishAuditInputs(
            knowledge_by_id={"knowledge-audit-1": _knowledge()},
            blog_history=history,
        )
        result = audit_record(
            _record(review_status="approved"), duplicate_content_ids=frozenset(), inputs=inputs
        )
        self.assertEqual(result.status, ALREADY_PUBLISHED)


class AuditRecordThreadsTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        self.threads_history_path = Path(tmp_dir.name) / "threads_publish_log.json"

    def _threads_record(self, **overrides) -> MediaArchiveRecord:
        return _record(platform="threads", review_status="approved", **overrides)

    def test_threads_already_published_via_history(self):
        history = PublishHistory(self.threads_history_path)
        history.append(
            PublishRecord(
                content_id="content-audit-1",
                published_at="2026-09-20T00:00:00+00:00",
                threads_post_id="th_123",
                knowledge_id="knowledge-audit-1",
                platform="threads",
                source_url="https://example.test/article",
            )
        )
        inputs = PublishAuditInputs(
            knowledge_by_id={"knowledge-audit-1": _knowledge()},
            threads_history=history,
        )
        result = audit_record(
            self._threads_record(), duplicate_content_ids=frozenset(), inputs=inputs
        )
        self.assertEqual(result.status, ALREADY_PUBLISHED)

    def test_threads_already_published_via_pending_draft_status(self):
        """PublishHistory에 아직 반영 안 됐어도 pending draft 자체가 published면
        이미 게시된 것으로 판정한다(둘 중 하나만 published여도 충분)."""
        draft = ThreadsPendingDraft(
            content_id="content-audit-1",
            knowledge_id="knowledge-audit-1",
            source_url="https://example.test/article",
            evidence_unit_ids=(),
            article_type="experience",
            knowledge_type="경험",
            original_title="원본",
            original_body="원본 본문",
            ai_rewritten_title="AI 제목",
            ai_rewritten_body="AI 본문",
            status="published",
            created_at="2026-09-20T00:00:00+00:00",
            final_title="최종 제목",
            final_body="최종 본문",
            published_at="2026-09-20T01:00:00+00:00",
            threads_post_id="th_456",
        )
        inputs = PublishAuditInputs(
            knowledge_by_id={"knowledge-audit-1": _knowledge()},
            threads_pending=(draft,),
        )
        result = audit_record(
            self._threads_record(), duplicate_content_ids=frozenset(), inputs=inputs
        )
        self.assertEqual(result.status, ALREADY_PUBLISHED)
        self.assertEqual(result.external_id, "th_456")

    def test_threads_pending_not_yet_published_is_ready(self):
        draft = ThreadsPendingDraft(
            content_id="content-audit-1",
            knowledge_id="knowledge-audit-1",
            source_url="https://example.test/article",
            evidence_unit_ids=(),
            article_type="experience",
            knowledge_type="경험",
            original_title="원본",
            original_body="원본 본문",
            ai_rewritten_title="AI 제목",
            ai_rewritten_body="AI 본문",
            status="approved",
            created_at="2026-09-20T00:00:00+00:00",
            final_title="최종 제목",
            final_body="최종 본문",
        )
        inputs = PublishAuditInputs(
            knowledge_by_id={"knowledge-audit-1": _knowledge()},
            threads_pending=(draft,),
        )
        result = audit_record(
            self._threads_record(), duplicate_content_ids=frozenset(), inputs=inputs
        )
        self.assertEqual(result.status, READY)
        self.assertEqual(result.threads_pending_status, "approved")


class AuditRecordShortsTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        self.tmp_path = Path(tmp_dir.name)
        self.scripts_path = self.tmp_path / "shorts_scripts"
        self.youtube_history_path = self.tmp_path / "youtube_publish_log.json"

    def _shorts_record(self, **overrides) -> MediaArchiveRecord:
        return _record(platform="shorts", review_status="approved", **overrides)

    def test_missing_shorts_script_is_blocked(self):
        inputs = PublishAuditInputs(
            knowledge_by_id={"knowledge-audit-1": _knowledge()},
            shorts_scripts_path=self.scripts_path,
        )
        result = audit_record(
            self._shorts_record(), duplicate_content_ids=frozenset(), inputs=inputs
        )
        self.assertEqual(result.status, BLOCKED)
        self.assertTrue(any("ShortsScript" in reason for reason in result.reasons))
        self.assertFalse(result.shorts_script_exists)

    def test_existing_shorts_script_is_ready(self):
        self.scripts_path.mkdir(parents=True, exist_ok=True)
        (self.scripts_path / "content-audit-1.json").write_text("{}", encoding="utf-8")
        inputs = PublishAuditInputs(
            knowledge_by_id={"knowledge-audit-1": _knowledge()},
            shorts_scripts_path=self.scripts_path,
        )
        result = audit_record(
            self._shorts_record(), duplicate_content_ids=frozenset(), inputs=inputs
        )
        self.assertEqual(result.status, READY)
        self.assertTrue(result.shorts_script_exists)

    def test_youtube_already_uploaded_is_already_published(self):
        self.scripts_path.mkdir(parents=True, exist_ok=True)
        (self.scripts_path / "content-audit-1.json").write_text("{}", encoding="utf-8")
        youtube_history = YouTubeUploadHistory(self.youtube_history_path)
        youtube_history.append(
            YouTubeUploadRecord(
                video_id="yt_video_1",
                uploaded_at="2026-09-20T00:00:00+00:00",
                title="업로드된 Shorts",
                privacy_status="private",
                content_id="content-audit-1",
                knowledge_id="knowledge-audit-1",
            )
        )
        inputs = PublishAuditInputs(
            knowledge_by_id={"knowledge-audit-1": _knowledge()},
            shorts_scripts_path=self.scripts_path,
            youtube_history=youtube_history,
        )
        result = audit_record(
            self._shorts_record(), duplicate_content_ids=frozenset(), inputs=inputs
        )
        self.assertEqual(result.status, ALREADY_PUBLISHED)


class AuditArchiveBatchTests(unittest.TestCase):
    def test_audit_archive_detects_duplicate_content_ids_across_the_whole_list(self):
        records = [
            _record(content_id="content-dup", review_status="approved"),
            _record(content_id="content-dup", review_status="approved"),
            _record(content_id="content-unique", review_status="approved"),
        ]
        inputs = PublishAuditInputs(knowledge_by_id={"knowledge-audit-1": _knowledge()})
        results = audit_archive(records, inputs=inputs)

        statuses = {result.content_id: result.status for result in results}
        # 두 중복 레코드 모두 ERROR로 판정된다(어느 쪽이 "진짜"인지 이 모듈은 알 수 없다).
        self.assertEqual([r.status for r in results if r.content_id == "content-dup"], [ERROR, ERROR])
        self.assertEqual(statuses["content-unique"], READY)

    def test_audit_archive_preserves_input_order(self):
        records = [
            _record(content_id="content-a", review_status="approved"),
            _record(content_id="content-b", review_status="unreviewed"),
        ]
        inputs = PublishAuditInputs(knowledge_by_id={"knowledge-audit-1": _knowledge()})
        results = audit_archive(records, inputs=inputs)
        self.assertEqual([r.content_id for r in results], ["content-a", "content-b"])

    def test_summarize_counts_every_status_key_even_when_zero(self):
        records = [_record(content_id="content-a", review_status="approved")]
        inputs = PublishAuditInputs(knowledge_by_id={"knowledge-audit-1": _knowledge()})
        results = audit_archive(records, inputs=inputs)
        summary = summarize(results)

        self.assertEqual(summary[READY], 1)
        self.assertEqual(summary[BLOCKED], 0)
        self.assertEqual(summary[ALREADY_PUBLISHED], 0)
        self.assertEqual(summary[NEEDS_HUMAN_REVIEW], 0)
        self.assertEqual(summary[ERROR], 0)


class RenderReadinessMarkdownTests(unittest.TestCase):
    def setUp(self) -> None:
        self.inputs = PublishAuditInputs(knowledge_by_id={"knowledge-audit-1": _knowledge()})

    def test_markdown_includes_summary_counts_and_sections(self):
        records = [
            _record(content_id="content-blog-1", platform="blog", review_status="approved"),
            _record(content_id="content-threads-1", platform="threads", review_status="unreviewed"),
        ]
        results = audit_archive(records, inputs=self.inputs)
        markdown = render_readiness_markdown(results, generated_at="2026-09-21T00:00:00+00:00")

        self.assertIn("# Publish Readiness", markdown)
        self.assertIn("## Summary", markdown)
        self.assertIn("게시 가능(READY): 1", markdown)
        self.assertIn("게시 차단(BLOCKED): 1", markdown)
        self.assertIn("## Blog", markdown)
        self.assertIn("## Threads", markdown)
        self.assertIn("## Shorts / YouTube", markdown)
        self.assertIn("## Blocked", markdown)
        self.assertIn("content-blog-1", markdown)
        self.assertIn("content-threads-1", markdown)

    def test_no_content_never_shows_arbitrary_approval(self):
        results = audit_archive([], inputs=self.inputs)
        markdown = render_readiness_markdown(results, generated_at="2026-09-21T00:00:00+00:00")
        self.assertIn("전체 Production 콘텐츠: 0", markdown)

    def test_save_readiness_report_writes_file(self):
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        report_path = Path(tmp_dir.name) / "publish_readiness_latest.md"

        records = [_record(content_id="content-blog-1", review_status="approved")]
        results = audit_archive(records, inputs=self.inputs)
        save_readiness_report(results, report_path, generated_at="2026-09-21T00:00:00+00:00")

        self.assertTrue(report_path.exists())
        self.assertIn("content-blog-1", report_path.read_text(encoding="utf-8"))

    def test_save_readiness_report_is_idempotent_overwrite(self):
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        report_path = Path(tmp_dir.name) / "publish_readiness_latest.md"

        save_readiness_report([], report_path, generated_at="2026-09-21T00:00:00+00:00")
        first = report_path.read_text(encoding="utf-8")
        save_readiness_report([], report_path, generated_at="2026-09-21T00:00:00+00:00")
        second = report_path.read_text(encoding="utf-8")

        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
