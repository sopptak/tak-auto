"""6-28 Full End-to-End Operating Readiness - synthetic 통합 테스트
(docs/6-28-full-e2e-operating-readiness.md).

6-19~6-27에서 각각 검증한 단계를 하나의 synthetic 파이프라인으로 실제
연결해서 검증한다: SCOUT는 제외하고(순수 rule-based 수집, 이미
6-24/6-19에서 감사됨) KNOWLEDGE(승인) -> MEDIA(9개 생성) -> HUMAN REVIEW ->
PROMOTION -> PRODUCTION ARCHIVE -> PUBLISH READINESS -> Threads/YouTube/Blog
-> PUBLISH HISTORY까지 실제 함수를 그대로 호출한다.

이 파일이 새로 만드는 로직은 없다 - 전부 기존(6-06~6-27) 함수를 그대로
호출해서 "서로 연결되어 실제로 동작하는가"만 검증한다. 실제 외부 API/OAuth/
Naver 접근은 어디에도 없다(mock/synthetic만).

모든 데이터는 tempfile에만 쓴다 - 이 저장소의 실제 data/는 어디에서도
참조하지 않는다(단, tak_brain_knowledge.json의 실제 스키마와 호환되는
fixture를 쓰기 위해 KNOWLEDGE 필드 구조만 참고했다).
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from content_engine.media_archive import (
    ArchiveConflictError,
    MediaArchiveRecord,
    check_promotion_conflict,
    find_protected_overwrite_targets,
    load_archive,
    new_generation_id,
    save_archive,
    upsert_archive,
    upsert_generation_archive,
)
from content_engine.pipeline import run_media_batch
from content_engine.publish_audit import (
    ALREADY_PUBLISHED,
    BLOCKED,
    READY,
    SUPERSEDED,
    PublishAuditInputs,
    audit_archive,
    summarize,
)
from content_engine.publish_eligibility import check_content_supersede, find_production_record
from content_engine.publish_history import PublishHistory, PublishRecord, compute_content_id
from content_engine.rewrite import MockRewriteProvider
from content_engine.shorts_adapter import save_approved_shorts_script, shorts_script_output_path
from content_engine.threads_review import ThreadsPendingDraft, load_pending, mark_approved, upsert_pending
from content_engine.youtube_publisher import YouTubeClient, YouTubeUploadResult
from content_engine.youtube_upload_history import YouTubeUploadHistory
from scripts.mark_blog_published import check_blog_publish_confirmation_eligibility, main as mark_blog_published_main
from scripts.promote_media_generation import PromotionConflictError, plan_promotion
from scripts.publish_approved_threads import main as publish_approved_threads_main
from scripts.supersede_media_record import plan_supersede, execute_supersede
from scripts.upload_youtube_short import check_shorts_upload_eligibility, main as upload_youtube_short_main
from tak_brain import load_knowledge_records, select_approved
from content_engine.blog_publish_pack import build_blog_publish_pack_from_archive


# --- 4장: Synthetic E2E Architecture ------------------------------------------

TEST_KNOWLEDGE = {
    "id": "knowledge-TEST-001",
    "source_raw_id": "https://example.test/e2e-source",
    "source_url": "https://example.test/e2e-source",
    "title": "6-28 E2E 테스트용 KNOWLEDGE",
    "domain": "자기계발",
    "knowledge_type": "경험",
    "experience": "E2E 테스트를 위한 경험 서술입니다. 충분한 길이를 갖도록 여러 문장을 포함합니다.",
    "problem": "E2E 테스트를 위한 문제 상황 서술입니다.",
    "action": "E2E 테스트를 위한 행동 서술입니다.",
    "decision": "E2E 테스트를 위한 판단 서술입니다.",
    "result": "E2E 테스트를 위한 결과 서술입니다.",
    "lesson": "E2E 테스트를 위한 교훈 서술입니다.",
    "reusable_principle": "E2E 테스트를 위한 재사용 가능한 원칙 서술입니다.",
    "evidence": ["E2E 테스트 근거 문장 1", "E2E 테스트 근거 문장 2"],
    "derived_insight": "E2E 테스트를 위한 도출된 통찰입니다.",
    "inference_method": "rule_based_template",
    "confidence": None,
    "created_at": "2026-01-01T00:00:00+00:00",
    "knowledge_review_status": "approved",
    "category": "자기계발",
    "key_points": [],
    "case": "E2E 테스트 사례",
    "judgment_rule": "E2E 테스트 판단 규칙",
    "opinion": None,
    "factual_information": None,
    "current_validity": "확인 필요",
    "verification_required": True,
    "privacy_risk": False,
    "internal_information_risk": False,
    "reviewed_at": "2026-01-01T00:10:00+00:00",
    "review_note": "6-28 E2E 테스트 픽스처",
}


class E2EFixtureMixin:
    """모든 E2E 테스트가 공유하는 tempfile 환경 + KNOWLEDGE -> 9개 draft 생성."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.tmp_path = Path(self.tmp_dir.name)

        self.knowledge_path = self.tmp_path / "knowledge.json"
        self.knowledge_path.write_text(json.dumps([TEST_KNOWLEDGE], ensure_ascii=False), encoding="utf-8")

        self.generation_pool_path = self.tmp_path / "generation_pool.json"
        self.production_archive_path = self.tmp_path / "tak_media_archive.json"
        self.threads_pending_path = self.tmp_path / "tak_threads_pending.json"
        self.threads_history_path = self.tmp_path / "threads_publish_log.json"
        self.youtube_history_path = self.tmp_path / "youtube_publish_log.json"
        self.blog_history_path = self.tmp_path / "blog_publish_log.json"
        self.shorts_scripts_dir = self.tmp_path / "shorts_scripts"

        records = load_knowledge_records(self.knowledge_path)
        approved = list(select_approved(records))
        self.report = run_media_batch(approved, provider=MockRewriteProvider())

        # 5장: Blog 1 + Shorts 3 + Threads 5 = 9개 확인(현재 정책 재검증, 변경 없음).
        self.assertEqual(self.report.total_draft_count, 9)
        self.blog_items = [i for i in self.report.items if i.platform == "blog"]
        self.shorts_items = [i for i in self.report.items if i.platform == "shorts"]
        self.threads_items = [i for i in self.report.items if i.platform == "threads"]
        self.assertEqual(len(self.blog_items), 1)
        self.assertEqual(len(self.shorts_items), 3)
        self.assertEqual(len(self.threads_items), 5)

        self.generation_id = new_generation_id("knowledge-TEST-001")
        gen_records = [
            MediaArchiveRecord.from_item(item, generation_id=self.generation_id)
            for item in self.report.items
        ]
        upsert_generation_archive(self.generation_pool_path, gen_records)


# --- 5장: KNOWLEDGE -> MEDIA 연결관계 -----------------------------------------


class KnowledgeToMediaLinkageTests(E2EFixtureMixin, unittest.TestCase):
    def test_all_nine_items_share_knowledge_id_and_source_url(self) -> None:
        """13장 Cross-Channel Consistency: 같은 KNOWLEDGE에서 나온 9개 항목은
        knowledge_id/source_url이 전부 동일해야 한다."""
        for item in self.report.items:
            self.assertEqual(item.knowledge_id, "knowledge-TEST-001")
            self.assertEqual(item.source_url, TEST_KNOWLEDGE["source_url"])

    def test_all_nine_items_share_generation_id_in_pool(self) -> None:
        pool_records = load_archive(self.generation_pool_path)
        self.assertEqual(len(pool_records), 9)
        generation_ids = {r.generation_id for r in pool_records}
        self.assertEqual(generation_ids, {self.generation_id})

    def test_content_ids_are_unique_across_nine_items(self) -> None:
        content_ids = {compute_content_id(item.to_dict()) for item in self.report.items}
        self.assertEqual(len(content_ids), 9)

    def test_category_domain_article_type_do_not_collide(self) -> None:
        """6장: category(KNOWLEDGE의 원본 카테고리)/domain(자유서술 영역)/
        article_type(규칙 기반 분류 결과, KnowledgeRecord에만 있고 raw dict
        키에는 없음)이 서로 다른 개념·다른 필드임을 재확인한다(6-15 finance
        template contamination 회귀는 tests/test_article_types.py,
        tests/test_critical_content_replacement_audit.py가 전담 - 이 테스트는
        이번 E2E fixture 레벨에서 필드가 실제로 섞이지 않는지만 확인)."""
        records = load_knowledge_records(self.knowledge_path)
        record = next(r for r in records if r.id == "knowledge-TEST-001")
        self.assertEqual(record.category, "자기계발")
        self.assertEqual(record.domain, "자기계발")
        # article_type은 별도 분류 단계(tak_brain.article_types)의 산출물이며
        # KnowledgeRecord 원본 dict에는 없는 필드다 - category/domain과 값이
        # 같다고 해서 같은 필드가 되는 것은 아니다(구조적으로 분리됨).
        self.assertNotIn("article_type", TEST_KNOWLEDGE)


# --- 6장: HUMAN REVIEW ---------------------------------------------------------


class HumanReviewSimulationTests(E2EFixtureMixin, unittest.TestCase):
    def test_five_review_states_are_simulated_correctly(self) -> None:
        """7장 지시사항: unreviewed/approved/dismissed/edited+approved/superseded
        5가지 상태를 시뮬레이션한다."""
        pool_records = load_archive(self.generation_pool_path)
        blog_record = next(r for r in pool_records if r.platform == "blog")
        threads_records = [r for r in pool_records if r.platform == "threads"]
        shorts_records = [r for r in pool_records if r.platform == "shorts"]

        # 1. unreviewed(기본값)
        self.assertEqual(blog_record.review_status, "unreviewed")

        # 2. approved
        approved_threads = replace(threads_records[0], review_status="approved")
        self.assertEqual(approved_threads.review_status, "approved")

        # 3. dismissed
        dismissed_threads = replace(threads_records[1], review_status="dismissed")
        self.assertEqual(dismissed_threads.review_status, "dismissed")

        # 4. edited then approved - edited_title/body가 final_title/body에 반영되는지 확인.
        edited = replace(
            shorts_records[0],
            review_status="approved",
            edited_title="사람이 수정한 최종 제목",
            edited_body="사람이 수정한 최종 본문입니다.",
        )
        self.assertEqual(edited.final_title, "사람이 수정한 최종 제목")
        self.assertEqual(edited.final_body, "사람이 수정한 최종 본문입니다.")

        # 5. superseded(승인된 것만 가능 - 6-17 상태 전이 규칙)
        approved_blog = replace(blog_record, review_status="approved")
        superseded_blog = replace(approved_blog, review_status="superseded", superseded_by="content-placeholder")
        self.assertEqual(superseded_blog.review_status, "superseded")

    def test_unreviewed_and_dismissed_are_not_promotable(self) -> None:
        """미승인 콘텐츠는 Production Archive로 promotion되지 않는다.

        plan_promotion() 자체가 이미 review_status를 검사해 PromotionError를
        던진다(6-06 설계) - candidate가 unreviewed면 여기서 즉시 막힌다."""
        pool_records = load_archive(self.generation_pool_path)
        unreviewed = pool_records[0]  # 기본값 그대로
        self.assertEqual(unreviewed.review_status, "unreviewed")

        from scripts.promote_media_generation import PromotionError

        with self.assertRaises(PromotionError):
            plan_promotion(
                self.generation_pool_path,
                self.production_archive_path,
                unreviewed.content_id,
                self.generation_id,
            )

        # CLI를 통해 실제로 승격 시도해도 동일하게 막혀야 한다.
        from scripts.promote_media_generation import main as promote_main

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = promote_main(
                [
                    "--archive", str(self.generation_pool_path),
                    "--content-id", unreviewed.content_id,
                    "--generation-id", self.generation_id,
                    "--execute",
                ]
            )
        self.assertEqual(exit_code, 1)
        self.assertFalse(self.production_archive_path.exists(), "미승인 콘텐츠가 production archive에 생성되면 안 됩니다.")


# --- 7장/8장: PROMOTION --------------------------------------------------------


class PromotionE2ETests(E2EFixtureMixin, unittest.TestCase):
    def _approve(self, content_id: str) -> None:
        pool_records = load_archive(self.generation_pool_path)
        updated = [
            replace(r, review_status="approved") if r.content_id == content_id else r for r in pool_records
        ]
        save_archive(updated, self.generation_pool_path)

    def test_approved_valid_record_promotes_successfully(self) -> None:
        threads_content_id = self.threads_items[0].to_dict()
        content_id = compute_content_id(threads_content_id)
        self._approve(content_id)

        candidate, current_active = plan_promotion(
            self.generation_pool_path, self.production_archive_path, content_id, self.generation_id
        )
        self.assertIsNone(current_active)
        upsert_archive(self.production_archive_path, [candidate])

        promoted = load_archive(self.production_archive_path)
        self.assertEqual(len(promoted), 1)
        self.assertEqual(promoted[0].review_status, "approved")

    def test_promotion_is_idempotent_for_same_generation(self) -> None:
        content_id = compute_content_id(self.threads_items[0].to_dict())
        self._approve(content_id)
        candidate, _ = plan_promotion(self.generation_pool_path, self.production_archive_path, content_id, self.generation_id)
        upsert_archive(self.production_archive_path, [candidate])

        # 같은 generation_id로 다시 승격 시도 - 충돌 없이 idempotent해야 한다.
        candidate2, current_active2 = plan_promotion(
            self.generation_pool_path, self.production_archive_path, content_id, self.generation_id
        )
        self.assertIsNotNone(current_active2)
        self.assertEqual(current_active2.generation_id, self.generation_id)
        check_promotion_conflict(current_active2, candidate2)  # 예외 없어야 함

    def test_same_content_id_different_generation_is_conflict(self) -> None:
        """8장 핵심: 동일 content_id + 다른 generation_id가 기존 production을
        덮어쓰지 않는다."""
        content_id = compute_content_id(self.threads_items[0].to_dict())
        self._approve(content_id)
        candidate, _ = plan_promotion(self.generation_pool_path, self.production_archive_path, content_id, self.generation_id)
        upsert_archive(self.production_archive_path, [candidate])
        original_bytes = self.production_archive_path.read_bytes()

        # 새 generation(다른 generation_id)으로 같은 content_id를 다시 만든다.
        other_generation_id = new_generation_id("knowledge-TEST-001")
        other_gen_records = [
            MediaArchiveRecord.from_item(item, generation_id=other_generation_id) for item in self.report.items
        ]
        upsert_generation_archive(self.generation_pool_path, other_gen_records)
        self._approve_in_generation(content_id, other_generation_id)

        # plan_promotion() 자체가 내부적으로 check_promotion_conflict()를 호출해
        # PromotionConflictError(ArchiveConflictError의 문자열을 감싼 하위 예외)를
        # 던진다(6-18 설계) - 이 시점에 production archive는 전혀 건드려지지 않는다.
        with self.assertRaises(PromotionConflictError):
            plan_promotion(self.generation_pool_path, self.production_archive_path, content_id, other_generation_id)

        self.assertEqual(self.production_archive_path.read_bytes(), original_bytes, "충돌 시 production archive가 바뀌면 안 됩니다.")

    def _approve_in_generation(self, content_id: str, generation_id: str) -> None:
        pool_records = load_archive(self.generation_pool_path)
        updated = [
            replace(r, review_status="approved")
            if r.content_id == content_id and r.generation_id == generation_id
            else r
            for r in pool_records
        ]
        save_archive(updated, self.generation_pool_path)

    def test_batch_promotion_partial_approval(self) -> None:
        """batch promotion: 일부만 승인된 generation에서 승인된 것만 승격된다."""
        from scripts.promote_media_generation import plan_batch_promotion

        # threads 5개 중 2개만 승인
        approve_ids = [compute_content_id(item.to_dict()) for item in self.threads_items[:2]]
        for cid in approve_ids:
            self._approve(cid)

        items = plan_batch_promotion(self.generation_pool_path, self.production_archive_path, self.generation_id)
        promote_items = [i for i in items if i.action == "promote"]
        self.assertEqual(len(promote_items), 2)
        self.assertEqual({i.record.content_id for i in promote_items}, set(approve_ids))


# --- 9장: SUPERSEDED E2E(가장 중요한 테스트) -----------------------------------


def _minimal_record(**overrides) -> MediaArchiveRecord:
    defaults = dict(
        content_id="content-OLD",
        knowledge_id="knowledge-TEST-001",
        platform="threads",
        generation_status="valid",
        original_title="원본 제목",
        original_body="원본 본문입니다.",
        rewritten_title="재작성 제목",
        rewritten_body="재작성 본문입니다.",
        source_url="https://example.test/e2e-source",
        evidence=(),
        evidence_unit_ids=(),
        created_at="2026-01-01T00:00:00Z",
        review_status="approved",
        generation_id="gen-A",
    )
    defaults.update(overrides)
    return MediaArchiveRecord(**defaults)


class SupersededFullE2ETests(unittest.TestCase):
    """9장: OLD(content-OLD, gen-A, approved) -> production 반영 ->
    NEW(content-NEW, gen-B, approved) -> production 반영 -> OLD를
    supersede -> 세 채널 모두에서 OLD=BLOCK, NEW=READY 확인."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.tmp_path = Path(self.tmp_dir.name)
        self.archive_path = self.tmp_path / "tak_media_archive.json"
        self.shorts_scripts_dir = self.tmp_path / "shorts_scripts"
        self.threads_pending_path = self.tmp_path / "tak_threads_pending.json"
        self.threads_history_path = self.tmp_path / "threads_publish_log.json"
        self.youtube_history_path = self.tmp_path / "youtube_publish_log.json"
        self.blog_history_path = self.tmp_path / "blog_publish_log.json"
        self.video_path = self.tmp_path / "video.mp4"
        self.video_path.write_bytes(b"fake-mp4-bytes")

        old_threads = _minimal_record(content_id="content-OLD", platform="threads", generation_id="gen-A")
        new_threads = _minimal_record(
            content_id="content-NEW",
            platform="threads",
            generation_id="gen-B",
            original_title="정정된 제목",
            rewritten_body="정정된 본문입니다.",
        )
        old_shorts = _minimal_record(content_id="content-OLD-shorts", platform="shorts", generation_id="gen-A")
        new_shorts = _minimal_record(
            content_id="content-NEW-shorts", platform="shorts", generation_id="gen-B", original_title="정정된 Shorts 제목"
        )
        old_blog = _minimal_record(content_id="content-OLD-blog", platform="blog", generation_id="gen-A")
        new_blog = _minimal_record(
            content_id="content-NEW-blog", platform="blog", generation_id="gen-B", original_title="정정된 Blog 제목"
        )
        upsert_archive(
            self.archive_path,
            [old_threads, new_threads, old_shorts, new_shorts, old_blog, new_blog],
        )

        # Threads: OLD/NEW 둘 다 승인된 pending draft로 만든다.
        for record in (old_threads, new_threads):
            draft = ThreadsPendingDraft(
                content_id=record.content_id,
                knowledge_id=record.knowledge_id,
                source_url=record.source_url,
                evidence_unit_ids=(),
                article_type=None,
                knowledge_type=None,
                original_title=record.original_title,
                original_body=record.original_body,
                ai_rewritten_title=record.rewritten_title or "",
                ai_rewritten_body=record.rewritten_body or "",
                status="pending",
                created_at="2026-01-01T00:00:00Z",
            )
            upsert_pending(self.threads_pending_path, draft)
            approved = mark_approved(draft, final_title=record.final_title, final_body=record.final_body, approved_at="2026-01-01T00:05:00Z")
            upsert_pending(self.threads_pending_path, approved)

        # Shorts: OLD/NEW 둘 다 ShortsScript를 만든다.
        save_approved_shorts_script(old_shorts, self.shorts_scripts_dir)
        save_approved_shorts_script(new_shorts, self.shorts_scripts_dir)

        # supersede: OLD -> NEW(플랫폼별로 각각)
        for old_id, new_id in (
            ("content-OLD", "content-NEW"),
            ("content-OLD-shorts", "content-NEW-shorts"),
            ("content-OLD-blog", "content-NEW-blog"),
        ):
            plan = plan_supersede(self.archive_path, old_id, new_id)
            execute_supersede(self.archive_path, plan)

    def test_old_threads_is_blocked_new_threads_is_ready(self) -> None:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code_old = publish_approved_threads_main(
                [
                    "--input", str(self.threads_pending_path),
                    "--history", str(self.threads_history_path),
                    "--production-archive", str(self.archive_path),
                    "--id", "content-OLD",
                ]
            )
        self.assertEqual(exit_code_old, 1)
        self.assertFalse(PublishHistory(self.threads_history_path).is_published("content-OLD"))

        fake_client = mock.Mock()
        fake_client.publish_text.return_value = mock.Mock(id="th_new_e2e")
        from content_engine.threads_publisher import ThreadsClient

        with mock.patch.object(ThreadsClient, "from_environment", return_value=fake_client):
            exit_code_new = publish_approved_threads_main(
                [
                    "--input", str(self.threads_pending_path),
                    "--history", str(self.threads_history_path),
                    "--production-archive", str(self.archive_path),
                    "--id", "content-NEW",
                    "--execute",
                ]
            )
        self.assertEqual(exit_code_new, 0)
        self.assertTrue(PublishHistory(self.threads_history_path).is_published("content-NEW"))

    def test_old_youtube_is_blocked_new_youtube_is_ready(self) -> None:
        records = load_archive(self.archive_path)
        old_reason = check_shorts_upload_eligibility("content-OLD-shorts", records, self.shorts_scripts_dir)
        self.assertIsNotNone(old_reason)

        new_reason = check_shorts_upload_eligibility("content-NEW-shorts", records, self.shorts_scripts_dir)
        self.assertIsNone(new_reason)

        fake_client = mock.Mock()
        fake_client.upload_short.return_value = YouTubeUploadResult(video_id="yt_new_e2e")
        with mock.patch.object(YouTubeClient, "from_environment", return_value=fake_client):
            exit_code = upload_youtube_short_main(
                [
                    "--video", str(self.video_path),
                    "--title", "정정된 Shorts 제목",
                    "--content-id", "content-NEW-shorts",
                    "--knowledge-id", "knowledge-TEST-001",
                    "--history", str(self.youtube_history_path),
                    "--production-archive", str(self.archive_path),
                    "--shorts-scripts-dir", str(self.shorts_scripts_dir),
                ]
            )
        self.assertEqual(exit_code, 0)
        self.assertTrue(YouTubeUploadHistory(self.youtube_history_path).is_published("content-NEW-shorts"))

    def test_old_blog_is_blocked_new_blog_is_ready(self) -> None:
        records = load_archive(self.archive_path)
        old_blog_record = next(r for r in records if r.content_id == "content-OLD-blog")
        new_blog_record = next(r for r in records if r.content_id == "content-NEW-blog")

        self.assertEqual(old_blog_record.review_status, "superseded")
        self.assertEqual(new_blog_record.review_status, "approved")

        history = PublishHistory(self.blog_history_path)
        pack = build_blog_publish_pack_from_archive(records, [], history)
        pack_ids = {item.content_id for item in pack}
        self.assertNotIn("content-OLD-blog", pack_ids, "superseded 항목이 Blog Pack 후보가 되면 안 됩니다.")
        self.assertIn("content-NEW-blog", pack_ids)

        exit_code_old = mark_blog_published_main(
            [
                "--content-id", "content-OLD-blog",
                "--history", str(self.blog_history_path),
                "--production-archive", str(self.archive_path),
            ]
        )
        self.assertEqual(exit_code_old, 1)

        exit_code_new = mark_blog_published_main(
            [
                "--content-id", "content-NEW-blog",
                "--history", str(self.blog_history_path),
                "--production-archive", str(self.archive_path),
            ]
        )
        self.assertEqual(exit_code_new, 0)
        self.assertTrue(PublishHistory(self.blog_history_path).is_published("content-NEW-blog"))


def _write_temp_knowledge_file() -> Path:
    path = Path(tempfile.mkdtemp()) / "knowledge.json"
    record = {**TEST_KNOWLEDGE, "id": "knowledge-TEST-001"}
    path.write_text(json.dumps([record], ensure_ascii=False), encoding="utf-8")
    return path


# --- 13장: Cross-Channel Consistency / 16장: Publish Readiness priority -------


class CrossChannelConsistencyTests(unittest.TestCase):
    """Production Archive 상태와 Threads/YouTube/Blog readiness가 서로
    모순되지 않는지 확인한다 - 예: "Production SUPERSEDED인데 Blog만 READY"
    같은 상태는 나오면 안 된다."""

    def test_audit_archive_priority_is_consistent_across_platforms(self) -> None:
        """content_engine.publish_audit.audit_archive()의 기존 우선순위
        (ERROR > ALREADY_PUBLISHED > SUPERSEDED > BLOCKED > NEEDS_HUMAN_REVIEW
        > READY, 6-14/6-17/6-19)를 세 플랫폼 각각에 대해 재확인한다 - 이번에
        순서/의미를 바꾸지 않았다."""
        superseded_by = _minimal_record(content_id="content-successor", platform="threads", generation_id="gen-B")
        records = [
            _minimal_record(content_id="content-ready-threads", platform="threads", generation_id="gen-A"),
            _minimal_record(content_id="content-ready-shorts", platform="shorts", generation_id="gen-A"),
            _minimal_record(content_id="content-ready-blog", platform="blog", generation_id="gen-A"),
            replace(
                _minimal_record(content_id="content-superseded-threads", platform="threads", generation_id="gen-A"),
                review_status="superseded",
                superseded_by="content-successor",
            ),
        ]
        # is_review_required()는 KNOWLEDGE를 찾을 수 없으면 안전한 쪽(True)을
        # 기본값으로 둔다(content_engine/blog_publish_pack.py 설계, 이번에
        # 바꾸지 않음) - READY를 보려면 금융이 아닌 실제 KNOWLEDGE를 함께 넘겨야 한다.
        knowledge_records = load_knowledge_records(_write_temp_knowledge_file())
        knowledge_by_id = {r.id: r for r in knowledge_records}

        results = audit_archive(records, inputs=PublishAuditInputs(knowledge_by_id=knowledge_by_id))
        by_id = {r.content_id: r.status for r in results}

        self.assertEqual(by_id["content-ready-threads"], READY)
        self.assertEqual(by_id["content-ready-shorts"], READY)
        self.assertEqual(by_id["content-ready-blog"], READY)
        self.assertEqual(by_id["content-superseded-threads"], SUPERSEDED)

    def test_already_published_outranks_superseded_on_every_platform(self) -> None:
        """ALREADY_PUBLISHED가 SUPERSEDED보다 항상 우선한다는 6-17 정책이
        Threads/Blog 각각에서 동일하게 지켜지는지 확인한다(YouTube는
        check_shorts_upload_eligibility가 아닌 audit_archive 경로에서는
        youtube_history를 별도로 넘기지 않으므로 이 테스트는 Threads/Blog만
        다룬다 - Shorts의 동일 우선순위는 tests/test_superseded_downstream_safeguards.py
        의 YouTubeUploadSupersedeBlockTests.test_already_published_takes_priority_over_superseded
        가 이미 전담한다)."""
        threads_record = replace(
            _minimal_record(content_id="content-dual-threads", platform="threads"),
            review_status="superseded",
            superseded_by="content-other",
        )
        blog_record = replace(
            _minimal_record(content_id="content-dual-blog", platform="blog"),
            review_status="superseded",
            superseded_by="content-other",
        )
        threads_history = PublishHistory(Path(tempfile.mkdtemp()) / "threads.json")
        threads_history.append(PublishRecord(content_id="content-dual-threads", published_at="2026-01-01T00:00:00Z", threads_post_id="th_1"))
        blog_history = PublishHistory(Path(tempfile.mkdtemp()) / "blog.json")
        blog_history.append(PublishRecord(content_id="content-dual-blog", published_at="2026-01-01T00:00:00Z", threads_post_id=""))

        results = audit_archive(
            [threads_record, blog_record],
            inputs=PublishAuditInputs(threads_history=threads_history, blog_history=blog_history),
        )
        by_id = {r.content_id: r.status for r in results}
        self.assertEqual(by_id["content-dual-threads"], ALREADY_PUBLISHED)
        self.assertEqual(by_id["content-dual-blog"], ALREADY_PUBLISHED)


# --- 15장: Race Condition 통합 테스트 -------------------------------------------


class IntegratedRaceConditionTests(unittest.TestCase):
    """CASE A/B: 스냅샷을 읽은 뒤 supersede가 발생하면, 그 스냅샷을 쓰는
    실행은 감지하지 못하지만 다음 실행(새 스냅샷)은 정확히 차단한다 - 6-25/
    6-26/6-27이 각 채널별로 이미 확인한 것과 동일한 구조적 경계를, 하나의
    archive를 여러 채널이 동시에 참조하는 통합 시나리오로 재확인한다. 새
    lock/DB를 도입하지 않는다(24장 원칙)."""

    def test_case_a_readiness_snapshot_then_supersede_then_publish_blocks_on_fresh_read(self) -> None:
        tmp_path = Path(tempfile.mkdtemp())
        archive_path = tmp_path / "tak_media_archive.json"
        record = _minimal_record(content_id="content-race", platform="threads", generation_id="gen-A")
        save_archive([record], archive_path)

        # Process A: 처음 읽었을 때는 approved라 차단되지 않는다.
        snapshot = load_archive(archive_path)
        self.assertFalse(check_content_supersede(snapshot, "content-race").blocked)

        # Process B(다른 프로세스): 그 사이 supersede를 기록한다.
        successor = _minimal_record(content_id="content-race-new", platform="threads", generation_id="gen-B")
        save_archive([replace(record, review_status="superseded", superseded_by="content-race-new"), successor], archive_path)

        # Process A가 이미 읽은 stale 스냅샷을 계속 쓰면 여전히 통과된 것으로 보인다(알려진 경계).
        self.assertFalse(check_content_supersede(snapshot, "content-race").blocked)

        # 하지만 실제 CLI(publish_approved_threads.py)는 매 실행마다 새로 읽으므로
        # "다음" 실행은 정확히 차단한다.
        fresh = load_archive(archive_path)
        self.assertTrue(check_content_supersede(fresh, "content-race").blocked)

    def test_case_d_threads_pending_created_then_production_deleted_is_orphan_not_blocked(self) -> None:
        """CASE D: Threads pending draft가 만들어진 뒤 Production Archive 자체가
        사라지면(파일 삭제) - 기존 ORPHAN 정책(6-19)대로 차단하지 않는다(PATH A는
        별도 승인 트랙이 있으므로 안전, 6-25 5장에서 이미 정리한 정책)."""
        tmp_path = Path(tempfile.mkdtemp())
        archive_path = tmp_path / "tak_media_archive.json"  # 아예 생성하지 않음(NOT_PRESENT)
        records = load_archive(archive_path)
        self.assertEqual(records, [])
        check = check_content_supersede(records, "content-orphan")
        self.assertFalse(check.blocked, "ORPHAN은 차단 대상이 아니어야 합니다(6-19 정책 유지).")

    def test_case_e_blog_pack_generation_conflict_is_blocked_not_silently_merged(self) -> None:
        """CASE E: Blog Pack 생성 시점에 이미 다른 generation이 같은 content_id를
        차지하고 있으면(6-18 check_promotion_conflict) - 자동 병합하지 않고
        명시적으로 CONFLICT(예외)를 낸다."""
        tmp_path = Path(tempfile.mkdtemp())
        generation_pool_path = tmp_path / "pool.json"
        production_archive_path = tmp_path / "archive.json"

        existing = _minimal_record(content_id="content-blog-race", platform="blog", generation_id="gen-A")
        save_archive([existing], production_archive_path)

        competing = replace(
            _minimal_record(content_id="content-blog-race", platform="blog", generation_id="gen-B"),
        )
        save_archive([competing], generation_pool_path)

        with self.assertRaises(PromotionConflictError):
            plan_promotion(generation_pool_path, production_archive_path, "content-blog-race", "gen-B")

        # 충돌 시 기존 production은 전혀 바뀌지 않아야 한다.
        unchanged = load_archive(production_archive_path)
        self.assertEqual(unchanged[0].generation_id, "gen-A")


if __name__ == "__main__":
    unittest.main()
