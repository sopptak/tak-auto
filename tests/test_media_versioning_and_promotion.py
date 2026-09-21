"""6-06 회귀 테스트: MEDIA generation/version 관리 + 안전한 promotion.

docs/6-06_media_versioning_and_safe_promotion.md 참고. 실제 LLM API는 호출하지
않는다 - MockRewriteProvider만 사용한다(6-06 절대 원칙 13: 실제 LLM 호출 금지).

이 파일이 다루는 범위:
    - generation_id 생성과 legacy(예전 5-27 레코드, generation_id 없음) 호환성
    - 같은 content_id에 서로 다른 generation_id를 가진 레코드가 동시에 보존되는지
      (content_engine/media_archive.py의 archive_generation_report/
      upsert_generation_archive)
    - promotion CLI(scripts/promote_media_generation.py)의 승인 게이팅
      (unreviewed/rejected는 승격 불가, approved+valid만 승격 가능),
      dry-run이 파일을 바꾸지 않는지, 실행 후에도 generation 이력이 남는지
    - 기존 production archive(9건)가 이번 기능으로 전혀 바뀌지 않는지

기존 content_id/archive_report/upsert_archive 자체의 동작(단독 키 upsert, 5-27
설계)은 tests/test_media_archive.py가 이미 충분히 검증하므로 여기서 다시 다루지
않는다.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import json
import tempfile
import unittest

from content_engine.media_archive import (
    MediaArchiveRecord,
    archive_generation_report,
    archive_report,
    find_generation_record,
    list_generations_for_content_id,
    load_archive,
    new_generation_id,
    upsert_archive,
    upsert_generation_archive,
)
from content_engine.pipeline import run_media_batch
from content_engine.rewrite import MockRewriteProvider
from scripts.promote_media_generation import PromotionError, plan_promotion
from tak_brain import load_knowledge_records

KNOWLEDGE_PATH = Path(__file__).parents[1] / "data" / "tak_brain_knowledge.json"
PRODUCTION_ARCHIVE_PATH = Path(__file__).parents[1] / "data" / "tak_media_archive.json"
TARGET_KNOWLEDGE_ID = "knowledge-scout-b28b782b2a33"


def _load_target():
    records = load_knowledge_records(KNOWLEDGE_PATH)
    return next(r for r in records if r.id == TARGET_KNOWLEDGE_ID)


def _sample_record(**overrides) -> MediaArchiveRecord:
    base = dict(
        content_id="content-sample0001",
        knowledge_id="knowledge-sample",
        platform="blog",
        generation_status="valid",
        original_title="원본 제목",
        original_body="원본 본문",
        rewritten_title="재작성 제목",
        rewritten_body="재작성 본문",
        source_url="https://example.test/article",
        evidence=("SOURCE FACT: 예시",),
        evidence_unit_ids=("lesson:1",),
        created_at="2026-09-20T00:00:00+00:00",
    )
    base.update(overrides)
    return MediaArchiveRecord(**base)


class GenerationIdTests(unittest.TestCase):
    def test_new_generation_id_has_expected_shape_and_is_unique(self):
        first = new_generation_id("knowledge-x")
        second = new_generation_id("knowledge-x")
        self.assertTrue(first.startswith("gen-"))
        self.assertNotEqual(first, second)

    def test_legacy_record_without_generation_id_field_parses_without_keyerror(self):
        """5-27 시절 레코드(딕셔너리에 generation_id 키 자체가 없음)를 그대로
        from_dict()에 넣어도 KeyError 없이 generation_id=None으로 읽혀야 한다
        (6-06 절대 원칙 6: 기존 JSON을 읽는 코드에서 KeyError가 발생하면 안 됨)."""
        legacy_dict = _sample_record().to_dict()
        del legacy_dict["generation_id"]

        record = MediaArchiveRecord.from_dict(legacy_dict)

        self.assertIsNone(record.generation_id)

    def test_real_production_archive_records_are_legacy_generations(self):
        """실제 production archive(data/tak_media_archive.json)의 legacy 9건
        (knowledge-scout-b28b782b2a33, 5-27 시절 레코드)은 generation_id 없이
        저장돼 있다 - 이 테스트는 그 파일을 읽기만 하고 전혀 쓰지 않는다.

        6-12(docs/6-12_media_generation_promotion_execution.md)에서 실제로
        두 번째 KNOWLEDGE(knowledge-scout-6d1d0e2fa762)의 generation 9건이
        production archive에 승격되어, 이 파일의 총 레코드 수는 이제 9가 아니라
        18이다(9 legacy + 9 신규, 신규 9건은 generation_id가 있다) - 그래서
        "9건 전체"가 아니라 "generation_id가 없는 legacy 부분집합만 9건"인지로
        범위를 좁혀 확인한다. 이 범위 좁히기 자체가 이 테스트의 안전장치(legacy
        레코드는 generation_id 없이 보존된다)를 약화시키지 않는다 - 오히려
        production archive가 앞으로 계속 자라나도(추가 promotion) 이 테스트가
        불필요하게 깨지지 않도록 만든다."""
        records = load_archive(PRODUCTION_ARCHIVE_PATH)
        legacy_records = [record for record in records if record.generation_id is None]
        self.assertEqual(len(legacy_records), 9)
        for record in legacy_records:
            self.assertIsNone(record.generation_id)


class GenerationPoolPreservesHistoryTests(unittest.TestCase):
    """동일 content_id + 서로 다른 generation_id가 archive에 동시에 존재할 수 있는지
    (6-06 8장·14장 핵심 안전장치)."""

    def setUp(self) -> None:
        tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        tmp.close()
        self.pool_path = Path(tmp.name)
        self.addCleanup(self.pool_path.unlink, missing_ok=True)

    def test_same_content_id_different_generation_id_both_survive(self):
        old = _sample_record(generation_id="gen-A")
        new = _sample_record(generation_id="gen-B", rewritten_title="다른 재작성 제목")

        upsert_generation_archive(self.pool_path, [old])
        upsert_generation_archive(self.pool_path, [new])

        stored = load_archive(self.pool_path)
        self.assertEqual(len(stored), 2)
        generation_ids = {record.generation_id for record in stored}
        self.assertEqual(generation_ids, {"gen-A", "gen-B"})
        content_ids = {record.content_id for record in stored}
        self.assertEqual(content_ids, {"content-sample0001"})

    def test_same_content_id_same_generation_id_upserts_in_place(self):
        first = _sample_record(generation_id="gen-A", rewritten_title="첫 버전")
        second = _sample_record(generation_id="gen-A", rewritten_title="같은 generation 재저장")

        upsert_generation_archive(self.pool_path, [first])
        upsert_generation_archive(self.pool_path, [second])

        stored = load_archive(self.pool_path)
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0].rewritten_title, "같은 generation 재저장")

    def test_list_generations_for_content_id_returns_full_history(self):
        upsert_generation_archive(self.pool_path, [_sample_record(generation_id="gen-A", created_at="2026-09-19T00:00:00+00:00")])
        upsert_generation_archive(self.pool_path, [_sample_record(generation_id="gen-B", created_at="2026-09-20T00:00:00+00:00")])

        history = list_generations_for_content_id(self.pool_path, "content-sample0001")

        self.assertEqual([record.generation_id for record in history], ["gen-A", "gen-B"])

    def test_find_generation_record_matches_exact_pair(self):
        upsert_generation_archive(self.pool_path, [_sample_record(generation_id="gen-A")])
        upsert_generation_archive(self.pool_path, [_sample_record(generation_id="gen-B")])

        found = find_generation_record(self.pool_path, "content-sample0001", "gen-B")
        missing = find_generation_record(self.pool_path, "content-sample0001", "gen-does-not-exist")

        self.assertIsNotNone(found)
        self.assertEqual(found.generation_id, "gen-B")
        self.assertIsNone(missing)


class ArchiveGenerationReportRealPipelineTests(unittest.TestCase):
    """실제 run_media_batch() 결과(MockRewriteProvider, LLM 호출 없음)를
    archive_generation_report()로 저장했을 때의 동작 - 6-05에서 재현된 문제
    (9건 중 7건이 같은 content_id로 재계산됨)를 이 새 저장 방식이 데이터 손실
    없이 처리하는지 확인한다."""

    def setUp(self) -> None:
        self.knowledge = _load_target()
        tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        tmp.close()
        self.pool_path = Path(tmp.name)
        self.addCleanup(self.pool_path.unlink, missing_ok=True)

    def test_items_from_one_report_share_a_generation_id(self):
        report = run_media_batch([self.knowledge], provider=MockRewriteProvider())
        archived = archive_generation_report(report, self.pool_path)

        self.assertEqual(len(archived), 9)
        generation_ids = {record.generation_id for record in archived}
        self.assertEqual(len(generation_ids), 1, "한 번의 배치 실행은 하나의 generation_id를 공유해야 합니다.")
        self.assertIsNotNone(next(iter(generation_ids)))

    def test_regenerating_under_different_profile_keeps_both_generations_even_when_content_id_collides(self):
        finance_knowledge = replace(self.knowledge, article_type="finance")

        old_report = run_media_batch([finance_knowledge], provider=MockRewriteProvider())
        archive_generation_report(old_report, self.pool_path, generation_id="gen-old")

        new_report = run_media_batch([self.knowledge], provider=MockRewriteProvider())
        archive_generation_report(new_report, self.pool_path, generation_id="gen-new")

        all_records = load_archive(self.pool_path)
        # 6-05에서 확인된 대로 9건 중 7건은 content_id가 동일하게 재계산된다.
        # 그럼에도 이 저장 방식에서는 generation_id가 달라 18건(9+9) 모두 남아야 한다.
        self.assertEqual(len(all_records), 18)

        by_content_id: dict[str, list[MediaArchiveRecord]] = {}
        for record in all_records:
            by_content_id.setdefault(record.content_id, []).append(record)
        colliding_slots = [records for records in by_content_id.values() if len(records) == 2]
        self.assertGreaterEqual(
            len(colliding_slots), 5, "threads 5건처럼 content_id가 겹치는 슬롯이 여전히 둘 다 보존돼야 합니다."
        )
        for records in colliding_slots:
            self.assertEqual({r.generation_id for r in records}, {"gen-old", "gen-new"})


class PromotionGatingTests(unittest.TestCase):
    """scripts/promote_media_generation.py의 plan_promotion() 승인 게이팅."""

    def setUp(self) -> None:
        tmp_pool = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        tmp_pool.close()
        self.pool_path = Path(tmp_pool.name)
        self.addCleanup(self.pool_path.unlink, missing_ok=True)

        tmp_prod = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        tmp_prod.close()
        self.production_path = Path(tmp_prod.name)
        self.addCleanup(self.production_path.unlink, missing_ok=True)

    def test_unreviewed_generation_cannot_be_promoted(self):
        record = _sample_record(generation_id="gen-A", generation_status="valid", review_status="unreviewed")
        upsert_generation_archive(self.pool_path, [record])

        with self.assertRaises(PromotionError):
            plan_promotion(self.pool_path, self.production_path, record.content_id, "gen-A")

    def test_rejected_generation_cannot_be_promoted_even_if_approved(self):
        record = _sample_record(generation_id="gen-A", generation_status="rejected", review_status="approved")
        upsert_generation_archive(self.pool_path, [record])

        with self.assertRaises(PromotionError):
            plan_promotion(self.pool_path, self.production_path, record.content_id, "gen-A")

    def test_dismissed_generation_cannot_be_promoted(self):
        record = _sample_record(generation_id="gen-A", generation_status="valid", review_status="dismissed")
        upsert_generation_archive(self.pool_path, [record])

        with self.assertRaises(PromotionError):
            plan_promotion(self.pool_path, self.production_path, record.content_id, "gen-A")

    def test_missing_generation_raises_promotion_error(self):
        with self.assertRaises(PromotionError):
            plan_promotion(self.pool_path, self.production_path, "content-does-not-exist", "gen-nope")

    def test_approved_valid_generation_can_be_promoted(self):
        record = _sample_record(generation_id="gen-A", generation_status="valid", review_status="approved")
        upsert_generation_archive(self.pool_path, [record])

        candidate, current_active = plan_promotion(
            self.pool_path, self.production_path, record.content_id, "gen-A"
        )

        self.assertEqual(candidate.generation_id, "gen-A")
        self.assertIsNone(current_active)


class PromotionDryRunAndExecuteTests(unittest.TestCase):
    """dry-run은 파일을 바꾸지 않고, --execute만 실제로 반영해야 한다
    (6-06 11장). CLI 프로세스 대신 main()을 직접 호출해 빠르고 결정적으로 검증."""

    def setUp(self) -> None:
        tmp_pool = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        tmp_pool.close()
        self.pool_path = Path(tmp_pool.name)
        self.addCleanup(self.pool_path.unlink, missing_ok=True)

        tmp_prod = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        tmp_prod.close()
        self.production_path = Path(tmp_prod.name)
        self.addCleanup(self.production_path.unlink, missing_ok=True)

        self.record = _sample_record(generation_id="gen-A", generation_status="valid", review_status="approved")
        upsert_generation_archive(self.pool_path, [self.record])

    def _run_cli(self, *, execute: bool) -> int:
        from scripts.promote_media_generation import main as promote_main

        argv = [
            "--archive", str(self.pool_path),
            "--production-archive", str(self.production_path),
            "--content-id", self.record.content_id,
            "--generation-id", "gen-A",
        ]
        if execute:
            argv.append("--execute")
        return promote_main(argv)

    def test_dry_run_does_not_write_production_archive(self):
        exit_code = self._run_cli(execute=False)

        self.assertEqual(exit_code, 0)
        self.assertFalse(self.production_path.exists() and self.production_path.read_text().strip())

    def test_execute_writes_exactly_the_approved_generation(self):
        exit_code = self._run_cli(execute=True)

        self.assertEqual(exit_code, 0)
        promoted = load_archive(self.production_path)
        self.assertEqual(len(promoted), 1)
        self.assertEqual(promoted[0].generation_id, "gen-A")
        self.assertEqual(promoted[0].review_status, "approved")

    def test_promoting_twice_is_idempotent_no_duplicate(self):
        self._run_cli(execute=True)
        exit_code = self._run_cli(execute=True)

        self.assertEqual(exit_code, 0)
        promoted = load_archive(self.production_path)
        self.assertEqual(len(promoted), 1)

    def test_generation_history_still_queryable_after_promotion(self):
        self._run_cli(execute=True)

        history = list_generations_for_content_id(self.pool_path, self.record.content_id)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].generation_id, "gen-A")

    def test_rejected_generation_cli_promotion_fails_without_writing(self):
        rejected = _sample_record(
            content_id="content-rejected0001", generation_id="gen-R", generation_status="rejected", review_status="approved"
        )
        upsert_generation_archive(self.pool_path, [rejected])

        from scripts.promote_media_generation import main as promote_main

        exit_code = promote_main(
            [
                "--archive", str(self.pool_path),
                "--production-archive", str(self.production_path),
                "--content-id", "content-rejected0001",
                "--generation-id", "gen-R",
                "--execute",
            ]
        )

        self.assertEqual(exit_code, 1)
        self.assertFalse(self.production_path.exists() and self.production_path.read_text().strip())


class ExistingProductionArchiveUntouchedTests(unittest.TestCase):
    """이번 6-06 작업이 실제 production archive(data/tak_media_archive.json)의
    기존 9건을 절대 건드리지 않는지 확인한다(6-06 절대 원칙 7·8, 15장)."""

    def test_production_archive_still_has_exactly_nine_unreviewed_legacy_records(self):
        """6-12 이후 production archive 총 레코드 수는 18(9 legacy + 9 신규
        promoted)이므로, legacy 부분집합(generation_id is None)만 9건인지로
        범위를 좁힌다 - 이유는 test_real_production_archive_records_are_legacy_generations
        와 동일(6-12 참고)."""
        records = load_archive(PRODUCTION_ARCHIVE_PATH)
        legacy_records = [record for record in records if record.generation_id is None]
        self.assertEqual(len(legacy_records), 9)
        for record in legacy_records:
            self.assertIn(record.review_status, ("unreviewed", "approved", "dismissed"))
            self.assertIsNone(record.generation_id)

    def test_new_generation_added_to_a_temp_copy_does_not_drop_existing_nine(self):
        """실제 파일 대신 임시 복사본에 6-06 upsert_archive()(기존 함수, 변경 없음)로
        새 레코드를 추가해도 기존 레코드가 사라지지 않는지 - production archive
        자체는 전혀 열어서 쓰지 않는다(읽기만 한다).

        6-12 이전에는 원본이 9건이라 "10건이 되는지"로 고정 검증했지만, 이제
        원본 자체가 18건(6-12 promotion 결과 포함)이므로 절대값 대신
        "원본 개수 + 1"로 비교한다 - 검증하는 내용(새 레코드 추가로 기존 레코드가
        하나도 사라지지 않는다)은 동일하다."""
        original = load_archive(PRODUCTION_ARCHIVE_PATH)
        tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        tmp.close()
        tmp_path = Path(tmp.name)
        try:
            tmp_path.write_text(json.dumps([record.to_dict() for record in original], ensure_ascii=False), encoding="utf-8")
            new_record = _sample_record(content_id="content-brand-new-slot", generation_id="gen-new")
            upsert_archive(tmp_path, [new_record])

            reloaded = load_archive(tmp_path)
            self.assertEqual(len(reloaded), len(original) + 1)
            original_content_ids = {record.content_id for record in original}
            reloaded_content_ids = {record.content_id for record in reloaded}
            self.assertTrue(original_content_ids.issubset(reloaded_content_ids))
        finally:
            tmp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
