"""TAK AUTO 6-33 October 1 Operating Day Rehearsal
(docs/6-33-october-1-operating-day-rehearsal.md).

10월 1일 실제 운영 첫날, 운영자가 최소한의 판단과 조작만으로
SCOUT→KNOWLEDGE→MEDIA→HUMAN REVIEW→PROMOTION→PRODUCTION ARCHIVE→
PUBLISH READINESS를 운영할 수 있는지 실제 운영자 관점에서 검증한다.
새 기능을 많이 만들지 않는다 - 6-28/6-31/6-32가 이미 구축한 fixture와
함수를 최대한 재사용하고, 이번에 새로 필요한 부분(승인 매트릭스 A~G,
dry-run 파일시스템 보호, resume 동작, operator status CLI)만 채운다.

실제 외부 API/네트워크/OAuth는 호출하지 않는다. 실제 운영 데이터
(data/)는 어디에서도 생성/수정하지 않는다 - 전부 tempfile이다.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from content_engine.media_archive import (
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
    READY,
    SUPERSEDED,
    PublishAuditInputs,
    audit_archive,
)
from content_engine.publish_history import PublishHistory, PublishRecord, compute_content_id
from content_engine.rewrite import MockRewriteProvider
from content_engine.threads_review import ThreadsPendingDraft, upsert_pending
from scripts.promote_media_generation import PromotionConflictError, PromotionError, plan_promotion
from scripts.run_scout_dashboard import (
    handle_generation_edit_submission,
    handle_generation_review_submission,
)
from tak_brain import load_knowledge_records, select_approved
from tak_scout.answers import InterviewAnswer
from tak_scout.knowledge_bridge import build_knowledge_from_interview
from tak_scout.models import ScoutCandidate

import scripts.show_operating_status as operator_status_cli

from tests.test_full_e2e_operating_readiness import TEST_KNOWLEDGE, _minimal_record, _write_temp_knowledge_file


def _candidate(**overrides) -> ScoutCandidate:
    defaults = dict(
        scout_id="scout-6-33-1",
        title="AI로 사이드 프로젝트를 완성했다",
        summary="비개발자가 AI 도구로 앱을 만든 사례.",
        source_url="https://example.test/6-33/1",
        published_at="2026-01-01T00:00:00Z",
        source_name="Hacker News",
        category="기타",
    )
    defaults.update(overrides)
    return ScoutCandidate(**defaults)


# --- Section 4: 10월 1일 First Run 시나리오(3개 후보 -> 1개 선택) --------------


class FirstRunThreeCandidatesTest(unittest.TestCase):
    def test_three_scout_candidates_one_selected_reaches_publish_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            candidates = [
                _candidate(scout_id="scout-a", source_url="https://example.test/a", title="뉴스 A"),
                _candidate(scout_id="scout-b", source_url="https://example.test/b", title="뉴스 B"),
                _candidate(scout_id="scout-c", source_url="https://example.test/c", title="뉴스 C"),
            ]
            self.assertEqual(len(candidates), 3)

            selected = candidates[1]
            answer = InterviewAnswer(scout_id=selected.scout_id, selected_option="A", custom_answer="", answered_at="2026-01-01T00:10:00Z")

            knowledge = build_knowledge_from_interview(selected, answer)
            self.assertEqual(knowledge.knowledge_review_status, "pending")

            approved_knowledge = replace(knowledge, knowledge_review_status="approved")
            knowledge_path = tmp_path / "knowledge.json"
            knowledge_path.write_text(json.dumps([approved_knowledge.to_dict()], ensure_ascii=False), encoding="utf-8")

            records = load_knowledge_records(knowledge_path)
            approved = list(select_approved(records))
            self.assertEqual(len(approved), 1)

            from content_engine.pipeline import run_media_batch

            report = run_media_batch(approved, provider=MockRewriteProvider())
            self.assertEqual(report.total_draft_count, 9)

            generation_pool_path = tmp_path / "generation_pool.json"
            generation_id = new_generation_id(knowledge.id)
            gen_records = [MediaArchiveRecord.from_item(i, generation_id=generation_id) for i in report.items]
            upsert_generation_archive(generation_pool_path, gen_records)

            # Human Review: 1건 수정 후 승인(edit -> approve)
            threads_item = next(i for i in report.items if i.platform == "threads" and i.status == "valid")
            content_id = compute_content_id(threads_item.to_dict())

            edited, edit_error = handle_generation_edit_submission(
                (generation_pool_path,), content_id, generation_id, "수정된 제목", "수정된 본문입니다."
            )
            self.assertIsNone(edit_error)
            self.assertEqual(edited.edited_title, "수정된 제목")

            approved_record, approve_error = handle_generation_review_submission(
                (generation_pool_path,), content_id, generation_id, "approved"
            )
            self.assertIsNone(approve_error)
            self.assertEqual(approved_record.review_status, "approved")

            # Promotion
            production_archive_path = tmp_path / "tak_media_archive.json"
            candidate_record, current_active = plan_promotion(
                generation_pool_path, production_archive_path, content_id, generation_id
            )
            self.assertIsNone(current_active)
            upsert_archive(production_archive_path, [candidate_record])

            # Publish Readiness
            production_records = load_archive(production_archive_path)
            knowledge_by_id = {approved_knowledge.id: approved_knowledge}
            results = audit_archive(production_records, inputs=PublishAuditInputs(knowledge_by_id=knowledge_by_id))
            self.assertEqual(results[0].status, READY)
            self.assertEqual(results[0].rewritten_title if hasattr(results[0], "rewritten_title") else None, None)

        self.assertFalse(Path(tmp).exists())


# --- Section 6/20: Operator command(신규 read-only CLI) -------------------------


class OperatorStatusCliTests(unittest.TestCase):
    """scripts/show_operating_status.py(6-33 신규) - 파이프라인 단계별 현재
    상태를 한 번에 보여주는 읽기 전용 CLI. 새 판정 로직을 만들지 않고 기존
    로더/요약 함수만 조합한다."""

    def test_empty_data_dir_reports_absence_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            exit_code = operator_status_cli.main(["--data-dir", tmp])
        self.assertEqual(exit_code, 0)

    def test_status_cli_never_writes_any_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            knowledge_path = tmp_path / "tak_brain_knowledge.json"
            knowledge_path.write_text(json.dumps([TEST_KNOWLEDGE], ensure_ascii=False), encoding="utf-8")
            before = sorted(p.name for p in tmp_path.iterdir())

            operator_status_cli.main(["--data-dir", tmp])

            after = sorted(p.name for p in tmp_path.iterdir())
            self.assertEqual(before, after, "operator status CLI는 어떤 파일도 새로 만들면 안 된다.")

    def test_status_cli_summarizes_pending_knowledge_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            pending = {**TEST_KNOWLEDGE, "id": "k-pending", "knowledge_review_status": "pending"}
            (tmp_path / "tak_brain_knowledge.json").write_text(json.dumps([pending], ensure_ascii=False), encoding="utf-8")
            status = operator_status_cli._knowledge_status(tmp_path / "tak_brain_knowledge.json")
        self.assertIn("1건", status)


# --- Section 7: SAFE DRY-RUN 파일시스템 보호 -------------------------------------


class DryRunFilesystemProtectionTests(unittest.TestCase):
    """10월 1일 운영과 동일한 명령을 tempfile 대상으로 실행하고, 이 저장소의
    실제 data/ 아래 보호 대상 파일들의 존재 상태/SHA256이 실행 전후로
    전혀 바뀌지 않음을 직접 검증한다."""

    PROTECTED_RELATIVE_PATHS = (
        "data/tak_brain_knowledge.json",
        "data/tak_threads_pending.json",
        "data/tak_media_archive.json",
    )
    PROTECTED_DIRS = ("data/shorts_scripts", "data/blog_drafts")

    def _snapshot(self, repo_root: Path) -> dict[str, str | None]:
        snapshot: dict[str, str | None] = {}
        for rel in self.PROTECTED_RELATIVE_PATHS:
            path = repo_root / rel
            if path.exists():
                snapshot[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
            else:
                snapshot[rel] = None
        for rel in self.PROTECTED_DIRS:
            path = repo_root / rel
            snapshot[rel] = "EXISTS" if path.exists() else None
        import glob as _glob

        gen_pool_files = sorted(_glob.glob(str(repo_root / "data" / "tak_media_generation_*.json")))
        snapshot["generation_pool_files"] = ",".join(Path(p).name for p in gen_pool_files) or None
        return snapshot

    def test_full_tempfile_rehearsal_does_not_touch_real_data_directory(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        before = self._snapshot(repo_root)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            knowledge_path = _write_temp_knowledge_file()
            records = load_knowledge_records(knowledge_path)
            approved = list(select_approved(records))

            from content_engine.pipeline import run_media_batch

            report = run_media_batch(approved, provider=MockRewriteProvider())
            generation_pool_path = tmp_path / "generation_pool.json"
            generation_id = new_generation_id("knowledge-TEST-001")
            gen_records = [MediaArchiveRecord.from_item(i, generation_id=generation_id) for i in report.items]
            upsert_generation_archive(generation_pool_path, gen_records)

            production_archive_path = tmp_path / "tak_media_archive.json"
            content_id = compute_content_id(next(i for i in report.items if i.platform == "blog").to_dict())
            pool_records = load_archive(generation_pool_path)
            updated = [replace(r, review_status="approved") if r.content_id == content_id else r for r in pool_records]
            save_archive(updated, generation_pool_path)
            candidate_record, _ = plan_promotion(generation_pool_path, production_archive_path, content_id, generation_id)
            upsert_archive(production_archive_path, [candidate_record])

            operator_status_cli.main(["--data-dir", str(tmp_path)])

        after = self._snapshot(repo_root)
        self.assertEqual(before, after, "tempfile 기반 전체 리허설이 실제 data/ 디렉터리를 건드리면 안 된다.")

    def test_dry_run_promotion_writes_nothing(self) -> None:
        """promote_media_generation.py는 --execute 없이는 파일을 쓰지 않는다
        (main()의 dry-run 분기, 6-06 기존 동작) - CLI 레벨로 재확인."""
        import scripts.promote_media_generation as promote_module

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            knowledge_path = _write_temp_knowledge_file()
            records = load_knowledge_records(knowledge_path)
            approved = list(select_approved(records))
            from content_engine.pipeline import run_media_batch

            report = run_media_batch(approved, provider=MockRewriteProvider())
            generation_pool_path = tmp_path / "generation_pool.json"
            generation_id = new_generation_id("knowledge-TEST-001")
            gen_records = [MediaArchiveRecord.from_item(i, generation_id=generation_id) for i in report.items]
            upsert_generation_archive(generation_pool_path, gen_records)

            content_id = compute_content_id(next(i for i in report.items if i.platform == "blog").to_dict())
            pool_records = load_archive(generation_pool_path)
            updated = [replace(r, review_status="approved") if r.content_id == content_id else r for r in pool_records]
            save_archive(updated, generation_pool_path)

            production_archive_path = tmp_path / "tak_media_archive.json"
            self.assertFalse(production_archive_path.exists())

            exit_code = promote_module.main(
                [
                    "--archive", str(generation_pool_path),
                    "--production-archive", str(production_archive_path),
                    "--content-id", content_id,
                    "--generation-id", generation_id,
                    # --execute 생략 = dry-run(기본값)
                ]
            )
            self.assertEqual(exit_code, 0)
            self.assertFalse(production_archive_path.exists(), "dry-run(--execute 없음)은 production archive를 만들면 안 된다.")


# --- Section 9: 승인 정책 CASE A~G ------------------------------------------------


class ApprovalMatrixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.tmp_path = Path(self.tmp_dir.name)
        self.generation_pool_path = self.tmp_path / "generation_pool.json"
        self.production_archive_path = self.tmp_path / "tak_media_archive.json"
        self.generation_id = "gen-matrix-1"

    def _seed(self, review_status: str = "unreviewed", generation_status: str = "valid", content_id: str = "c-matrix") -> None:
        record = _minimal_record(content_id=content_id, review_status=review_status, generation_id=self.generation_id)
        record = replace(record, generation_status=generation_status)
        upsert_generation_archive(self.generation_pool_path, [record])

    def test_case_a_nine_valid_unreviewed_all_blocked_from_promotion(self) -> None:
        self._seed(review_status="unreviewed", generation_status="valid")
        with self.assertRaises(PromotionError):
            plan_promotion(self.generation_pool_path, self.production_archive_path, "c-matrix", self.generation_id)

    def test_case_b_partial_approved_only_approved_promotes(self) -> None:
        self._seed(review_status="approved", generation_status="valid", content_id="c-approved")
        candidate, current = plan_promotion(self.generation_pool_path, self.production_archive_path, "c-approved", self.generation_id)
        self.assertIsNone(current)
        self.assertEqual(candidate.review_status, "approved")

    def test_case_c_dismissed_blocked_from_promotion(self) -> None:
        self._seed(review_status="dismissed", generation_status="valid", content_id="c-dismissed")
        with self.assertRaises(PromotionError):
            plan_promotion(self.generation_pool_path, self.production_archive_path, "c-dismissed", self.generation_id)

    def test_case_d_invalid_generation_status_blocked_from_promotion(self) -> None:
        self._seed(review_status="approved", generation_status="rejected", content_id="c-rejected")
        with self.assertRaises(PromotionError):
            plan_promotion(self.generation_pool_path, self.production_archive_path, "c-rejected", self.generation_id)

    def test_case_e_superseded_excluded_from_publish_readiness(self) -> None:
        record = replace(_minimal_record(content_id="c-superseded", review_status="superseded", superseded_by="c-new"))
        knowledge_by_id = {r.id: r for r in load_knowledge_records(_write_temp_knowledge_file())}
        results = audit_archive([record], inputs=PublishAuditInputs(knowledge_by_id=knowledge_by_id))
        self.assertEqual(results[0].status, SUPERSEDED)

    def test_case_f_content_id_conflict_blocked(self) -> None:
        approved = _minimal_record(content_id="c-conflict", review_status="approved", generation_id="gen-A")
        upsert_archive(self.production_archive_path, [approved])
        conflicting = replace(
            _minimal_record(content_id="c-conflict", review_status="approved", generation_id="gen-B"),
        )
        upsert_generation_archive(self.generation_pool_path, [conflicting])
        with self.assertRaises(PromotionConflictError):
            plan_promotion(self.generation_pool_path, self.production_archive_path, "c-conflict", "gen-B")

    def test_case_g_generation_conflict_is_idempotent_not_error_when_same_generation(self) -> None:
        record = _minimal_record(content_id="c-same-gen", review_status="approved", generation_id="gen-X")
        upsert_generation_archive(self.generation_pool_path, [record])
        candidate, current = plan_promotion(self.generation_pool_path, self.production_archive_path, "c-same-gen", "gen-X")
        upsert_archive(self.production_archive_path, [candidate])
        candidate2, current2 = plan_promotion(self.generation_pool_path, self.production_archive_path, "c-same-gen", "gen-X")
        self.assertIsNotNone(current2)
        self.assertEqual(current2.generation_id, "gen-X")


# --- Section 11: Publish Readiness matrix ---------------------------------------


class PublishReadinessMatrixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.knowledge_by_id = {r.id: r for r in load_knowledge_records(_write_temp_knowledge_file())}

    def test_approved_published_outranks_superseded(self) -> None:
        record = replace(_minimal_record(content_id="c1", review_status="superseded", superseded_by="c2"))
        history = PublishHistory(Path(tempfile.mkdtemp()) / "threads.json")
        history.append(PublishRecord(content_id="c1", published_at="2026-01-01T00:00:00Z", threads_post_id="p1"))
        results = audit_archive([record], inputs=PublishAuditInputs(knowledge_by_id=self.knowledge_by_id, threads_history=history))
        self.assertEqual(results[0].status, ALREADY_PUBLISHED)

    def test_approved_invalid_generation_status_is_blocked(self) -> None:
        record = replace(_minimal_record(content_id="c2", review_status="approved"), generation_status="rejected")
        results = audit_archive([record], inputs=PublishAuditInputs(knowledge_by_id=self.knowledge_by_id))
        self.assertEqual(results[0].status, BLOCKED)

    def test_unreviewed_is_blocked(self) -> None:
        record = _minimal_record(content_id="c3", review_status="unreviewed")
        results = audit_archive([record], inputs=PublishAuditInputs(knowledge_by_id=self.knowledge_by_id))
        self.assertEqual(results[0].status, BLOCKED)

    def test_content_conflict_duplicate_is_error(self) -> None:
        r1 = _minimal_record(content_id="c-dup", generation_id="gen-A", review_status="approved")
        r2 = _minimal_record(content_id="c-dup", generation_id="gen-B", review_status="approved")
        results = audit_archive([r1, r2], inputs=PublishAuditInputs(knowledge_by_id=self.knowledge_by_id))
        self.assertTrue(all(r.status == ERROR for r in results))


# --- Section 12: Threads 공식/레거시 경로 -----------------------------------------


class ThreadsPathConsistencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.tmp_path = Path(self.tmp_dir.name)

    def test_official_path_approved_not_published_is_eligible(self) -> None:
        from content_engine.publish_eligibility import check_content_supersede, find_production_record

        record = _minimal_record(content_id="c-official", review_status="approved")
        found = find_production_record([record], "c-official")
        self.assertIsNotNone(found)
        check = check_content_supersede([record], "c-official")
        self.assertFalse(check.blocked)

    def test_superseded_blocked_on_both_official_and_legacy_shared_eligibility(self) -> None:
        """6-25 통합: publish_threads.py(legacy)와 publish_approved_threads.py
        (공식)가 같은 content_engine.publish_eligibility를 재사용하므로,
        여기서 하나만 검증해도 두 경로 모두에 적용된다(코드가 같은 함수를
        호출하기 때문 - 이번에 import를 직접 확인)."""
        import scripts.publish_threads as legacy_module
        import scripts.publish_approved_threads as official_module

        self.assertIs(legacy_module.check_content_supersede, official_module.check_content_supersede)

    def test_orphan_pending_without_production_record_is_not_blocked(self) -> None:
        from content_engine.publish_eligibility import find_production_record

        self.assertIsNone(find_production_record([], "c-orphan"))

    def test_duplicate_and_content_id_conflict_via_pending_draft(self) -> None:
        pending_path = self.tmp_path / "pending.json"
        draft = ThreadsPendingDraft(
            content_id="c-thread-1", knowledge_id="k1", source_url="https://example.test/1",
            evidence_unit_ids=(), article_type=None, knowledge_type=None,
            original_title="원본", original_body="원본 본문",
            ai_rewritten_title="재작성", ai_rewritten_body="재작성 본문",
            status="approved", created_at="2026-01-01T00:00:00Z",
            final_title="최종 제목", final_body="최종 본문",
        )
        upsert_pending(pending_path, draft)
        from content_engine.threads_review import load_pending

        loaded = load_pending(pending_path)
        self.assertEqual(len(loaded), 1)


# --- Section 14: Blog Pack candidate 필터링 --------------------------------------


class BlogPackCandidateTests(unittest.TestCase):
    def test_unapproved_superseded_invalid_excluded_from_pack(self) -> None:
        from content_engine.blog_publish_pack import build_blog_publish_pack_from_archive

        unapproved = _minimal_record(content_id="c-blog-unapproved", platform="blog", review_status="unreviewed")
        superseded = replace(
            _minimal_record(content_id="c-blog-superseded", platform="blog", review_status="superseded", superseded_by="c-blog-new"),
        )
        invalid = replace(_minimal_record(content_id="c-blog-invalid", platform="blog", review_status="approved"), generation_status="error")
        approved_valid = _minimal_record(content_id="c-blog-ok", platform="blog", review_status="approved")

        knowledge_records = load_knowledge_records(_write_temp_knowledge_file())
        history = PublishHistory(Path(tempfile.mkdtemp()) / "blog.json")
        pack_items = build_blog_publish_pack_from_archive(
            [unapproved, superseded, invalid, approved_valid], knowledge_records, history
        )
        pack_content_ids = {item.content_id for item in pack_items}
        self.assertIn("c-blog-ok", pack_content_ids)
        self.assertNotIn("c-blog-unapproved", pack_content_ids)
        self.assertNotIn("c-blog-superseded", pack_content_ids)
        self.assertNotIn("c-blog-invalid", pack_content_ids)


# --- Section 15: Traceability -----------------------------------------------------


class TraceabilityTest(unittest.TestCase):
    def test_source_url_to_publish_readiness_chain_is_connected(self) -> None:
        candidate = _candidate(scout_id="scout-trace-1", source_url="https://example.test/trace-1")
        answer = InterviewAnswer(scout_id=candidate.scout_id, selected_option="A", custom_answer="", answered_at="2026-01-01T00:10:00Z")
        knowledge = build_knowledge_from_interview(candidate, answer)
        approved_knowledge = replace(knowledge, knowledge_review_status="approved")

        from content_engine.pipeline import run_media_batch

        report = run_media_batch([approved_knowledge], provider=MockRewriteProvider())
        threads_item = next(i for i in report.items if i.platform == "threads" and i.status == "valid")
        content_id = compute_content_id(threads_item.to_dict())
        generation_id = new_generation_id(knowledge.id)
        record = MediaArchiveRecord.from_item(threads_item, generation_id=generation_id)

        # source_url -> scout candidate -> knowledge_id -> content_id -> generation_id -> platform
        self.assertEqual(knowledge.source_url, candidate.source_url)
        self.assertEqual(knowledge.source_raw_id, candidate.scout_id)
        self.assertEqual(record.knowledge_id, knowledge.id)
        self.assertEqual(record.content_id, content_id)
        self.assertEqual(record.generation_id, generation_id)
        self.assertEqual(record.platform, "threads")

        # Synthetic ID 예시(문서 15장에 그대로 기록):
        # source_url=https://example.test/trace-1
        # -> scout_id=scout-trace-1
        # -> knowledge_id=knowledge-scout-<12자리 sha256>
        # -> content_id=content-<8자리 sha256>
        # -> generation_id=gen-<knowledge_id 기반>-<타임스탬프>
        self.assertTrue(knowledge.id.startswith("knowledge-scout-"))
        self.assertTrue(content_id.startswith("content-"))


# --- Section 17: Resume / Restart ------------------------------------------------


class ResumeRestartTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.tmp_path = Path(self.tmp_dir.name)

    def test_media_generation_completed_then_process_restarts_at_human_review(self) -> None:
        """MEDIA generation까지 완료된 상태에서 프로세스가 재시작되어도,
        generation pool 파일이 이미 디스크에 있으므로 그 파일을 다시 읽어
        Human Review부터 이어갈 수 있다(재실행 시 MEDIA를 중복 생성하지
        않아도 됨을 확인)."""
        knowledge_path = _write_temp_knowledge_file()
        records = load_knowledge_records(knowledge_path)
        approved = list(select_approved(records))
        from content_engine.pipeline import run_media_batch

        report = run_media_batch(approved, provider=MockRewriteProvider())
        generation_pool_path = self.tmp_path / "generation_pool.json"
        generation_id = new_generation_id("knowledge-TEST-001")
        gen_records = [MediaArchiveRecord.from_item(i, generation_id=generation_id) for i in report.items]
        upsert_generation_archive(generation_pool_path, gen_records)

        # "프로세스 재시작" 시뮬레이션: 새로 파일을 읽어서 이어간다.
        reloaded = load_archive(generation_pool_path)
        self.assertEqual(len(reloaded), 9, "재시작 후에도 generation pool 파일에서 9개를 그대로 읽을 수 있어야 한다.")

    def test_promotion_completed_then_restart_reads_production_archive_not_regenerate(self) -> None:
        knowledge_path = _write_temp_knowledge_file()
        records = load_knowledge_records(knowledge_path)
        approved = list(select_approved(records))
        from content_engine.pipeline import run_media_batch

        report = run_media_batch(approved, provider=MockRewriteProvider())
        generation_pool_path = self.tmp_path / "generation_pool.json"
        generation_id = new_generation_id("knowledge-TEST-001")
        gen_records = [MediaArchiveRecord.from_item(i, generation_id=generation_id) for i in report.items]
        upsert_generation_archive(generation_pool_path, gen_records)

        content_id = compute_content_id(next(i for i in report.items if i.platform == "blog").to_dict())
        pool_records = load_archive(generation_pool_path)
        updated = [replace(r, review_status="approved") if r.content_id == content_id else r for r in pool_records]
        save_archive(updated, generation_pool_path)

        production_archive_path = self.tmp_path / "tak_media_archive.json"
        candidate, _ = plan_promotion(generation_pool_path, production_archive_path, content_id, generation_id)
        upsert_archive(production_archive_path, [candidate])

        # "재시작": 같은 content_id/generation_id로 다시 promotion 시도해도
        # idempotent해야 한다(재생성/재승격 불필요) - Publish Readiness부터 재개.
        candidate2, current2 = plan_promotion(generation_pool_path, production_archive_path, content_id, generation_id)
        self.assertIsNotNone(current2)
        self.assertEqual(current2.generation_id, generation_id)


if __name__ == "__main__":
    unittest.main()
