"""TAK AUTO 6-31 Operational Rehearsal Engine
(docs/6-31-operational-rehearsal-and-october-1-first-run.md).

목표: 10월 1일 Codespaces 사용량이 복구되었을 때 실제로 처음부터 끝까지
돌릴 수 있는지를 synthetic fixture로 리허설한다. 새 pipeline 로직을 만들지
않는다 - 이 파일은 6-28(``tests/test_full_e2e_operating_readiness.py``)이
이미 구축한 ``E2EFixtureMixin``(synthetic KNOWLEDGE 1건 -> Blog1/Shorts3/
Threads5 = 9개 MEDIA draft 생성)과 그 파일의 헬퍼(``_minimal_record``,
``_write_temp_knowledge_file``)를 그대로 재사용해서, 6-28이 다루지 않은
빈틈(Promotion CASE B/C/D/E/G, Full Chain 단일 walkthrough, Failure
Injection 12종, Recovery Rehearsal 4상태)만 새로 채운다.

실제 외부 API(Threads/YouTube/Naver/Google OAuth/RSS 네트워크)는 어디에서도
호출하지 않는다. 모든 fixture는 tempfile에만 쓴다 - 이 저장소의 실제
data/ 디렉터리는 어디에서도 참조하지 않는다.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from content_engine import ThreadsClient
from content_engine.data_state import CORRUPTED, EMPTY, NOT_PRESENT, VALID, json_file_status
from content_engine.media_archive import (
    MediaArchiveError,
    MediaArchiveRecord,
    load_archive,
    new_generation_id,
    save_archive,
    upsert_archive,
    upsert_generation_archive,
)
from content_engine.publish_audit import (
    ALREADY_PUBLISHED,
    BLOCKED,
    ERROR,
    NEEDS_HUMAN_REVIEW,
    READY,
    SUPERSEDED,
    PublishAuditInputs,
    audit_archive,
)
from content_engine.publish_eligibility import check_content_supersede
from content_engine.publish_history import PublishHistory, PublishRecord, compute_content_id
from content_engine.rewrite import MockRewriteProvider
from content_engine.threads_review import ThreadsPendingDraft, upsert_pending
from content_engine.youtube_upload_history import YouTubeUploadHistory
from scripts.promote_media_generation import PromotionConflictError, PromotionError, plan_promotion
from scripts.publish_approved_threads import main as publish_approved_threads_main
from scripts.upload_youtube_short import check_shorts_upload_eligibility, main as upload_youtube_short_main
from tak_brain import load_knowledge_records, select_approved

from tests.test_full_e2e_operating_readiness import (
    TEST_KNOWLEDGE,
    E2EFixtureMixin,
    _minimal_record,
    _write_temp_knowledge_file,
)


# --- Section 10: Promotion CASE A~H (A/F/H는 6-28에 이미 있음 - B/C/D/E/G만 신규) ---


class PromotionCaseBToGTests(E2EFixtureMixin, unittest.TestCase):
    def _set_review_status(self, content_id: str, status: str) -> None:
        pool_records = load_archive(self.generation_pool_path)
        updated = [replace(r, review_status=status) if r.content_id == content_id else r for r in pool_records]
        save_archive(updated, self.generation_pool_path)

    def test_case_b_unreviewed_promotion_blocked(self) -> None:
        content_id = compute_content_id(self.threads_items[0].to_dict())
        # 기본 fixture는 review_status="unreviewed"로 생성된다(promote 전).
        with self.assertRaises(PromotionError) as ctx:
            plan_promotion(self.generation_pool_path, self.production_archive_path, content_id, self.generation_id)
        self.assertIn("unreviewed", str(ctx.exception))

    def test_case_c_dismissed_promotion_blocked(self) -> None:
        content_id = compute_content_id(self.threads_items[0].to_dict())
        self._set_review_status(content_id, "dismissed")
        with self.assertRaises(PromotionError) as ctx:
            plan_promotion(self.generation_pool_path, self.production_archive_path, content_id, self.generation_id)
        self.assertIn("dismissed", str(ctx.exception))

    def test_case_d_invalid_generation_status_promotion_blocked(self) -> None:
        pool_records = load_archive(self.generation_pool_path)
        content_id = compute_content_id(self.threads_items[0].to_dict())
        updated = [
            replace(r, review_status="approved", generation_status="rejected") if r.content_id == content_id else r
            for r in pool_records
        ]
        save_archive(updated, self.generation_pool_path)
        with self.assertRaises(PromotionError) as ctx:
            plan_promotion(self.generation_pool_path, self.production_archive_path, content_id, self.generation_id)
        self.assertIn("rejected", str(ctx.exception))

    def test_case_e_approved_superseded_excluded_from_publish_candidates(self) -> None:
        content_id = compute_content_id(self.threads_items[0].to_dict())
        self._set_review_status(content_id, "approved")
        candidate, _ = plan_promotion(self.generation_pool_path, self.production_archive_path, content_id, self.generation_id)
        upsert_archive(self.production_archive_path, [candidate])

        superseded = replace(candidate, review_status="superseded", superseded_by="content-successor")
        upsert_archive(self.production_archive_path, [superseded])

        records = load_archive(self.production_archive_path)
        knowledge_by_id = {r.id: r for r in load_knowledge_records(_write_temp_knowledge_file())}
        results = audit_archive(records, inputs=PublishAuditInputs(knowledge_by_id=knowledge_by_id))
        self.assertEqual(results[0].status, SUPERSEDED)

    def test_case_g_new_content_id_promotes_normally(self) -> None:
        content_id = compute_content_id(self.blog_items[0].to_dict())
        self._set_review_status(content_id, "approved")
        candidate, current_active = plan_promotion(
            self.generation_pool_path, self.production_archive_path, content_id, self.generation_id
        )
        self.assertIsNone(current_active, "신규 content_id는 기존 active record가 없어야 한다.")
        upsert_archive(self.production_archive_path, [candidate])
        self.assertEqual(len(load_archive(self.production_archive_path)), 1)


# --- Section 11: Publish Readiness 7개 상태 커버리지 -----------------------------


class PublishReadinessStateCoverageTests(unittest.TestCase):
    """READY/NEEDS_HUMAN_REVIEW/BLOCKED/ALREADY_PUBLISHED/SUPERSEDED/ERROR
    6개는 content_engine.publish_audit.audit_archive()의 상태 값이다.
    ORPHAN은 이 모듈의 상태 값이 아니다 - Production Archive에 이미 존재하는
    레코드를 감사하는 audit_archive()의 대상 자체가 아니기 때문이다. ORPHAN은
    channel별 eligibility 검사(예: scripts/upload_youtube_short.py의
    check_shorts_upload_eligibility(), --content-id가 Production Archive에
    전혀 없을 때)에서만 쓰이는 별도 레벨의 개념이다 - 이 테스트가 두 개념을
    구분해서 각각 검증한다."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.tmp_path = Path(self.tmp_dir.name)
        knowledge_records = load_knowledge_records(_write_temp_knowledge_file())
        self.knowledge_by_id = {r.id: r for r in knowledge_records}

    def test_ready_and_needs_human_review_and_blocked(self) -> None:
        ready = _minimal_record(content_id="c-ready", review_status="approved")
        blocked = _minimal_record(content_id="c-blocked", review_status="unreviewed")
        results = audit_archive([ready, blocked], inputs=PublishAuditInputs(knowledge_by_id=self.knowledge_by_id))
        by_id = {r.content_id: r.status for r in results}
        self.assertEqual(by_id["c-ready"], READY)
        self.assertEqual(by_id["c-blocked"], BLOCKED)

    def test_needs_human_review_when_knowledge_missing(self) -> None:
        # is_review_required()는 매칭되는 KNOWLEDGE를 못 찾으면 안전한 쪽(True)을
        # 기본값으로 둔다(content_engine/blog_publish_pack.py 기존 설계).
        record = _minimal_record(content_id="c-unknown-knowledge", knowledge_id="knowledge-NOT-FOUND", review_status="approved")
        results = audit_archive([record], inputs=PublishAuditInputs(knowledge_by_id={}))
        self.assertEqual(results[0].status, NEEDS_HUMAN_REVIEW)

    def test_already_published_and_superseded(self) -> None:
        superseded = replace(
            _minimal_record(content_id="c-superseded", review_status="superseded", superseded_by="c-new"),
        )
        already_published = _minimal_record(content_id="c-already", review_status="superseded", superseded_by="c-new2")
        history = PublishHistory(self.tmp_path / "threads.json")
        history.append(PublishRecord(content_id="c-already", published_at="2026-01-01T00:00:00Z", threads_post_id="p1"))

        results = audit_archive(
            [superseded, already_published],
            inputs=PublishAuditInputs(knowledge_by_id=self.knowledge_by_id, threads_history=history),
        )
        by_id = {r.content_id: r.status for r in results}
        self.assertEqual(by_id["c-superseded"], SUPERSEDED)
        self.assertEqual(by_id["c-already"], ALREADY_PUBLISHED, "이미 게시된 이력이 있으면 SUPERSEDED보다 우선해야 한다(6-17).")

    def test_error_on_duplicate_content_id(self) -> None:
        dup_1 = _minimal_record(content_id="c-dup", generation_id="gen-A", review_status="approved")
        dup_2 = _minimal_record(content_id="c-dup", generation_id="gen-B", review_status="approved")
        results = audit_archive([dup_1, dup_2], inputs=PublishAuditInputs(knowledge_by_id=self.knowledge_by_id))
        self.assertTrue(all(r.status == ERROR for r in results), "같은 content_id가 두 번 있으면 구조적 이상(ERROR)으로 판정해야 한다.")

    def test_orphan_is_a_channel_level_concept_not_an_audit_archive_state(self) -> None:
        # Production Archive에 해당 content_id 레코드가 아예 없는 상태 -
        # audit_archive()가 아니라 채널별 eligibility 함수가 ORPHAN을 판정한다.
        reason = check_shorts_upload_eligibility("c-missing", [], self.tmp_path / "shorts_scripts")
        self.assertIsNotNone(reason)
        self.assertIn("ORPHAN", reason)


# --- Section 16: Full Chain 단일 Walkthrough -------------------------------------


class FullChainSingleWalkthroughTest(unittest.TestCase):
    """KNOWLEDGE -> MEDIA -> REVIEW -> PROMOTION -> PRODUCTION -> PUBLISH
    READINESS -> THREADS -> YOUTUBE(mock renderer) -> BLOG -> PUBLISH HISTORY
    를 하나의 synthetic content_id(Threads 경로)로 처음부터 끝까지 연결한다.
    테스트가 끝난 뒤 실제 data/ 디렉터리에는 어떤 파일도 남기지 않는다(전부
    tempfile)."""

    def test_single_knowledge_reaches_threads_publish_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            # 1) KNOWLEDGE
            knowledge_path = tmp_path / "knowledge.json"
            knowledge_path.write_text(json.dumps([TEST_KNOWLEDGE], ensure_ascii=False), encoding="utf-8")
            records = load_knowledge_records(knowledge_path)
            approved = list(select_approved(records))
            self.assertEqual(len(approved), 1)

            # 2) MEDIA (Blog1/Shorts3/Threads5 = 9)
            report = run_media_batch_safe(approved)
            self.assertEqual(report.total_draft_count, 9)
            threads_item = next(i for i in report.items if i.platform == "threads" and i.status == "valid")
            content_id = compute_content_id(threads_item.to_dict())

            generation_pool_path = tmp_path / "generation_pool.json"
            generation_id = new_generation_id("knowledge-TEST-001")
            gen_records = [MediaArchiveRecord.from_item(i, generation_id=generation_id) for i in report.items]
            upsert_generation_archive(generation_pool_path, gen_records)

            # 3) HUMAN REVIEW: unreviewed -> approved
            pool_records = load_archive(generation_pool_path)
            updated = [replace(r, review_status="approved") if r.content_id == content_id else r for r in pool_records]
            save_archive(updated, generation_pool_path)

            # 4) PROMOTION
            production_archive_path = tmp_path / "tak_media_archive.json"
            candidate, current_active = plan_promotion(generation_pool_path, production_archive_path, content_id, generation_id)
            self.assertIsNone(current_active)
            upsert_archive(production_archive_path, [candidate])

            # 5) PRODUCTION ARCHIVE
            production_records = load_archive(production_archive_path)
            self.assertEqual(len(production_records), 1)
            self.assertEqual(production_records[0].review_status, "approved")

            # 6) PUBLISH READINESS
            knowledge_by_id = {r.id: r for r in approved}
            audit_results = audit_archive(production_records, inputs=PublishAuditInputs(knowledge_by_id=knowledge_by_id))
            self.assertEqual(audit_results[0].status, READY)

            # 7) THREADS: pending draft 생성 -> 승인 -> 발행(mock, 실제 API 없음)
            threads_pending_path = tmp_path / "tak_threads_pending.json"
            draft = ThreadsPendingDraft(
                content_id=content_id,
                knowledge_id="knowledge-TEST-001",
                source_url=str(threads_item.to_dict().get("source_url") or ""),
                evidence_unit_ids=(),
                article_type=None,
                knowledge_type=None,
                original_title=str(threads_item.to_dict().get("original_title") or ""),
                original_body=str(threads_item.to_dict().get("original_body") or ""),
                ai_rewritten_title=str(threads_item.to_dict().get("rewritten_title") or ""),
                ai_rewritten_body=str(threads_item.to_dict().get("rewritten_body") or ""),
                status="approved",
                created_at="2026-01-01T00:00:00Z",
                final_title=str(threads_item.to_dict().get("rewritten_title") or ""),
                final_body=str(threads_item.to_dict().get("rewritten_body") or ""),
            )
            upsert_pending(threads_pending_path, draft)

            threads_history_path = tmp_path / "threads_publish_log.json"
            fake_client = mock.Mock()
            fake_client.publish_text.return_value = mock.Mock(id="threads_post_fake_1")
            with mock.patch.object(ThreadsClient, "from_environment", return_value=fake_client):
                exit_code = publish_approved_threads_main(
                    [
                        "--input",
                        str(threads_pending_path),
                        "--history",
                        str(threads_history_path),
                        "--production-archive",
                        str(production_archive_path),
                        "--id",
                        content_id,
                        "--execute",
                    ]
                )

            # 8) PUBLISH HISTORY
            self.assertEqual(exit_code, 0)
            final_history = PublishHistory(threads_history_path)
            self.assertTrue(any(r.get("content_id") == content_id for r in final_history.load()))

            # 완료 후 실제 data/ 아래에는 아무 것도 남지 않았어야 한다(tempfile만 사용).
        self.assertFalse(Path(tmp).exists(), "TemporaryDirectory가 정상적으로 정리되어야 한다.")


def run_media_batch_safe(approved):
    from content_engine.pipeline import run_media_batch

    return run_media_batch(approved, provider=MockRewriteProvider())


# --- Section 17: Failure Injection (12종) ----------------------------------------


class FailureInjectionTests(E2EFixtureMixin, unittest.TestCase):
    def test_01_missing_knowledge_produces_zero_drafts_gracefully(self) -> None:
        from content_engine.pipeline import run_media_batch

        report = run_media_batch([], provider=MockRewriteProvider())
        self.assertEqual(report.total_draft_count, 0, "KNOWLEDGE가 없으면 조용히 0건으로 끝나야 한다(크래시 없음).")

    def test_02_invalid_knowledge_filtered_out_by_select_approved(self) -> None:
        pending_knowledge = {**TEST_KNOWLEDGE, "id": "knowledge-PENDING", "knowledge_review_status": "pending"}
        path = Path(tempfile.mkdtemp()) / "knowledge.json"
        path.write_text(json.dumps([pending_knowledge], ensure_ascii=False), encoding="utf-8")
        records = load_knowledge_records(path)
        approved = list(select_approved(records))
        self.assertEqual(len(approved), 0, "승인되지 않은 KNOWLEDGE는 MEDIA 대상에서 제외되어야 한다.")

    def test_03_media_generation_failure_blocks_promotion(self) -> None:
        content_id = compute_content_id(self.threads_items[0].to_dict())
        pool_records = load_archive(self.generation_pool_path)
        updated = [
            replace(r, review_status="approved", generation_status="error") if r.content_id == content_id else r
            for r in pool_records
        ]
        save_archive(updated, self.generation_pool_path)
        with self.assertRaises(PromotionError):
            plan_promotion(self.generation_pool_path, self.production_archive_path, content_id, self.generation_id)

    def test_04_human_review_missing_blocks_promotion(self) -> None:
        content_id = compute_content_id(self.threads_items[0].to_dict())
        with self.assertRaises(PromotionError):
            plan_promotion(self.generation_pool_path, self.production_archive_path, content_id, self.generation_id)

    def test_05_promotion_conflict_does_not_touch_production_archive(self) -> None:
        content_id = compute_content_id(self.threads_items[0].to_dict())
        pool_records = load_archive(self.generation_pool_path)
        save_archive(
            [replace(r, review_status="approved") if r.content_id == content_id else r for r in pool_records],
            self.generation_pool_path,
        )
        candidate, _ = plan_promotion(self.generation_pool_path, self.production_archive_path, content_id, self.generation_id)
        upsert_archive(self.production_archive_path, [candidate])
        before = self.production_archive_path.read_bytes()

        other_generation_id = new_generation_id("knowledge-TEST-001")
        other_records = [MediaArchiveRecord.from_item(i, generation_id=other_generation_id) for i in self.report.items]
        upsert_generation_archive(self.generation_pool_path, other_records)
        pool_records2 = load_archive(self.generation_pool_path)
        save_archive(
            [
                replace(r, review_status="approved") if r.content_id == content_id and r.generation_id == other_generation_id else r
                for r in pool_records2
            ],
            self.generation_pool_path,
        )
        with self.assertRaises(PromotionConflictError):
            plan_promotion(self.generation_pool_path, self.production_archive_path, content_id, other_generation_id)
        self.assertEqual(self.production_archive_path.read_bytes(), before)

    def test_06_superseded_production_is_blocked_downstream(self) -> None:
        old = _minimal_record(content_id="c-old", review_status="superseded", superseded_by="c-new")
        new = _minimal_record(content_id="c-new", review_status="approved")
        check = check_content_supersede([old, new], "c-old")
        self.assertTrue(check.blocked)

    def test_07_duplicate_content_id_is_structural_error(self) -> None:
        knowledge_by_id = {r.id: r for r in load_knowledge_records(_write_temp_knowledge_file())}
        dup = [
            _minimal_record(content_id="c-dup2", generation_id="gen-A"),
            _minimal_record(content_id="c-dup2", generation_id="gen-B"),
        ]
        results = audit_archive(dup, inputs=PublishAuditInputs(knowledge_by_id=knowledge_by_id))
        self.assertTrue(all(r.status == ERROR for r in results))

    def test_08_missing_shorts_script_blocks_youtube_upload(self) -> None:
        record = _minimal_record(content_id="c-no-script", platform="shorts", review_status="approved")
        reason = check_shorts_upload_eligibility("c-no-script", [record], Path(tempfile.mkdtemp()))
        self.assertIsNotNone(reason)
        self.assertIn("ShortsScript", reason)

    def test_09_missing_mock_mp4_blocks_youtube_cli(self) -> None:
        tmp_path = Path(tempfile.mkdtemp())
        missing_video = tmp_path / "does_not_exist.mp4"
        exit_code = upload_youtube_short_main(
            [
                "--video",
                str(missing_video),
                "--title",
                "제목",
                "--history",
                str(tmp_path / "youtube_publish_log.json"),
            ]
        )
        self.assertEqual(exit_code, 1)

    def test_10_already_published_is_idempotent_not_a_crash(self) -> None:
        tmp_path = Path(tempfile.mkdtemp())
        history = YouTubeUploadHistory(tmp_path / "youtube_publish_log.json")
        from content_engine.youtube_upload_history import YouTubeUploadRecord

        history.append(
            YouTubeUploadRecord(
                video_id="yt_prior",
                uploaded_at="2026-01-01T00:00:00Z",
                title="이미 올라간 영상",
                privacy_status="private",
                video_path="x.mp4",
                tags=(),
                content_id="c-already-yt",
                knowledge_id="k1",
            )
        )
        self.assertTrue(history.is_published("c-already-yt"))

    def test_11_missing_production_archive_returns_empty_not_crash(self) -> None:
        tmp_path = Path(tempfile.mkdtemp())
        missing_path = tmp_path / "does_not_exist.json"
        records = load_archive(missing_path)
        self.assertEqual(records, [], "Production Archive 파일이 없으면 빈 목록을 반환해야 한다(크래시 없음).")

    def test_12_corrupted_synthetic_json_raises_loudly(self) -> None:
        tmp_path = Path(tempfile.mkdtemp())
        corrupted_path = tmp_path / "corrupted.json"
        corrupted_path.write_text("{not valid json", encoding="utf-8")
        with self.assertRaises(MediaArchiveError):
            load_archive(corrupted_path)


# --- Section 18: Recovery Rehearsal (NOT_PRESENT/EMPTY/VALID/CORRUPTED) ----------


class RecoveryRehearsalTests(unittest.TestCase):
    """6-22 Recovery Staging이 이미 정의한 4가지 상태 분류
    (``content_engine.data_state.json_file_status``)를 재사용해, Production
    Archive tempfile이 각 상태일 때 시스템이 안전하게 동작하는지 확인한다.
    실제 data/tak_media_archive.json은 절대 건드리지 않는다."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.tmp_path = Path(self.tmp_dir.name)

    def test_not_present_is_classified_and_loads_empty(self) -> None:
        path = self.tmp_path / "archive.json"
        status, count = json_file_status(path)
        self.assertEqual(status, NOT_PRESENT)
        self.assertEqual(load_archive(path), [])

    def test_empty_file_is_classified_and_loads_empty(self) -> None:
        path = self.tmp_path / "archive.json"
        path.write_text("", encoding="utf-8")
        status, count = json_file_status(path)
        self.assertEqual(status, EMPTY)
        self.assertEqual(load_archive(path), [])

    def test_valid_file_is_classified_and_loads_records(self) -> None:
        path = self.tmp_path / "archive.json"
        save_archive([_minimal_record(content_id="c-valid")], path)
        status, count = json_file_status(path)
        self.assertEqual(status, VALID)
        self.assertEqual(count, 1)
        self.assertEqual(len(load_archive(path)), 1)

    def test_corrupted_file_is_classified_and_raises_on_load(self) -> None:
        path = self.tmp_path / "archive.json"
        path.write_text("{not valid json at all", encoding="utf-8")
        status, count = json_file_status(path)
        self.assertEqual(status, CORRUPTED)
        with self.assertRaises(MediaArchiveError):
            load_archive(path)

    def test_valid_json_but_wrong_shape_is_a_separate_layer_from_corrupted(self) -> None:
        """6-21의 json_file_status()는 파일이 파싱 가능한 JSON이면 VALID로
        본다(list든 dict든 구분하지 않는다) - "list여야 한다"는 검증은 더
        상위 레이어인 content_engine.media_archive.load_archive()의 책임이다.
        같은 파일이 두 레이어에서 서로 다르게 판정될 수 있다는 것을 명시적으로
        확인한다(6-31에서 새로 발견 - 정책을 바꾸지 않고 기록만 한다)."""
        path = self.tmp_path / "archive.json"
        path.write_text('{"not": "a list"}', encoding="utf-8")
        status, _count = json_file_status(path)
        self.assertEqual(status, VALID, "파싱 가능한 JSON이므로 6-21 레이어에서는 VALID다.")
        with self.assertRaises(MediaArchiveError, msg="하지만 6-06 레이어(load_archive)는 list가 아니라서 거부해야 한다."):
            load_archive(path)


if __name__ == "__main__":
    unittest.main()
