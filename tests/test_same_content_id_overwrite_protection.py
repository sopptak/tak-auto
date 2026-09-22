"""6-18 회귀 테스트: "동일 content_id, 다른 generation_id" 자동 overwrite 차단.

docs/6-18-same-content-id-overwrite-protection.md 참고. 6-17 보고서 11장
마지막 문단이 "고치지 않고 사람의 결정 사항으로 남긴다"고 명시했던 사각지대를
실제로 막는다: production archive에 이미 존재하는 content_id를,
``scripts/promote_media_generation.py``가 (같은 content_id + 다른
generation_id를 가진) 새 generation으로 조용히 덮어쓰지 못하게 한다.

이 파일은 전부 ``tempfile``/``tmp_path``만 사용한다 - 실제
``data/tak_media_archive.json``, ``data/tak_media_generation_*.json``은 어떤
테스트도 쓰지 않는다(``ExistingProductionArchiveHashUnaffectedTests``만
읽기 전용으로 실제 파일의 SHA256을 확인한다).

기존 파일과의 범위 분리:
    - ``tests/test_media_versioning_and_promotion.py``/
      ``tests/test_generation_review_and_promotion.py``/
      ``tests/test_batch_promotion.py``가 이미 다루는 "승인 게이팅"(unreviewed/
      rejected 차단, idempotent 재실행, dry-run vs execute)은 다시 만들지
      않는다 - 여기서는 오직 "같은 content_id + 다른 generation_id" 충돌
      시나리오만 다룬다.
    - ``tests/test_critical_content_replacement_audit.py``가 이미 고정한
      "``upsert_archive()`` 자체는 같은 content_id를 조용히 덮어쓴다"는 저수준
      사실은 이번 변경으로도 바뀌지 않는다(의도적으로 그대로 둔다 - 보호는
      promotion 레이어에서만 검사한다). 그 테스트는 다시 만들지 않는다.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
from pathlib import Path
import tempfile
import unittest

from content_engine.media_archive import (
    ArchiveConflictError,
    MediaArchiveRecord,
    check_promotion_conflict,
    load_archive,
    save_archive,
)
from scripts.promote_media_generation import (
    PromotionConflictError,
    PromotionError,
    main as promote_main,
    plan_batch_promotion,
    plan_promotion,
)

PRODUCTION_ARCHIVE_PATH = Path(__file__).parents[1] / "data" / "tak_media_archive.json"


def _record(**overrides) -> MediaArchiveRecord:
    base = dict(
        content_id="content-X",
        knowledge_id="knowledge-shared",
        platform="blog",
        generation_status="valid",
        original_title="원본 제목",
        original_body="원본 본문",
        rewritten_title="옛 재작성 제목",
        rewritten_body="옛 재작성 본문",
        source_url="https://example.test/6-18",
        evidence=("SOURCE FACT: 예시",),
        evidence_unit_ids=("lesson:1",),
        created_at="2026-09-20T00:00:00+00:00",
        review_status="approved",
        generation_id="gen-old",
    )
    base.update(overrides)
    return MediaArchiveRecord(**base)


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run_cli(argv: list[str]) -> tuple[int, str]:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        exit_code = promote_main(argv)
    return exit_code, buffer.getvalue()


class _TempArchiveMixin(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.directory = Path(self._tmp.name)
        self.pool_path = self.directory / "pool.json"
        self.production_path = self.directory / "prod.json"


# --- A. 기존 content_id 없음 -> 정상 promotion --------------------------------


class CaseANoExistingRecordPromotesNormallyTests(_TempArchiveMixin):
    def test_check_promotion_conflict_allows_new_content_id(self):
        new_candidate = _record(content_id="content-new", generation_id="gen-1")
        check_promotion_conflict(existing=None, candidate=new_candidate)  # 예외 없음

    def test_plan_promotion_succeeds_when_no_existing_production_record(self):
        save_archive([_record(content_id="content-new", generation_id="gen-1", review_status="approved")], self.pool_path)

        candidate, current_active = plan_promotion(self.pool_path, self.production_path, "content-new", "gen-1")

        self.assertIsNone(current_active)
        self.assertEqual(candidate.generation_id, "gen-1")

    def test_batch_plan_promotes_new_content_id(self):
        save_archive(
            [_record(content_id="content-new", generation_id="gen-1", review_status="approved")], self.pool_path
        )

        items = plan_batch_promotion(self.pool_path, self.production_path, "gen-1")

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].action, "promote")


# --- B. 동일 content_id + 동일 generation_id -> idempotent 성공 ---------------


class CaseBSameGenerationIdIsIdempotentTests(_TempArchiveMixin):
    def test_check_promotion_conflict_allows_identical_generation_id(self):
        existing = _record(generation_id="gen-same")
        candidate = _record(generation_id="gen-same", rewritten_title="재실행 결과")

        check_promotion_conflict(existing=existing, candidate=candidate)  # 예외 없음

    def test_plan_promotion_treats_same_generation_id_as_already_promoted(self):
        save_archive([_record(generation_id="gen-A", review_status="approved")], self.production_path)
        save_archive([_record(generation_id="gen-A", review_status="approved")], self.pool_path)

        candidate, current_active = plan_promotion(self.pool_path, self.production_path, "content-X", "gen-A")

        self.assertIsNotNone(current_active)
        self.assertEqual(current_active.generation_id, "gen-A")

    def test_cli_reexecuting_same_generation_does_not_duplicate_or_error(self):
        save_archive([_record(generation_id="gen-A", review_status="approved")], self.pool_path)

        first_exit, _ = _run_cli(
            [
                "--archive", str(self.pool_path),
                "--production-archive", str(self.production_path),
                "--content-id", "content-X",
                "--generation-id", "gen-A",
                "--execute",
            ]
        )
        second_exit, second_stdout = _run_cli(
            [
                "--archive", str(self.pool_path),
                "--production-archive", str(self.production_path),
                "--content-id", "content-X",
                "--generation-id", "gen-A",
                "--execute",
            ]
        )

        self.assertEqual(first_exit, 0)
        self.assertEqual(second_exit, 0)
        self.assertIn("이미 승격된 generation입니다", second_stdout)
        self.assertEqual(len(load_archive(self.production_path)), 1)


# --- C/D. 동일 content_id + 다른 generation_id -> CONFLICT, 기존 레코드 보존 --


class CaseCDConflictBlocksPromotionAndPreservesExistingTests(_TempArchiveMixin):
    def setUp(self) -> None:
        super().setUp()
        self.old_active = _record(generation_id="gen-old", review_status="approved", rewritten_title="옛 텍스트")
        save_archive([self.old_active], self.production_path)
        save_archive(
            [_record(generation_id="gen-new", review_status="approved", rewritten_title="새 텍스트")],
            self.pool_path,
        )

    def test_check_promotion_conflict_raises_archive_conflict_error(self):
        candidate = _record(generation_id="gen-new")

        with self.assertRaises(ArchiveConflictError):
            check_promotion_conflict(existing=self.old_active, candidate=candidate)

    def test_plan_promotion_raises_promotion_conflict_error(self):
        with self.assertRaises(PromotionConflictError):
            plan_promotion(self.pool_path, self.production_path, "content-X", "gen-new")

    def test_promotion_conflict_error_is_a_promotion_error_subclass(self):
        """기존 ``except PromotionError`` 호출부(CLI main())가 새 예외도 그대로
        잡아내는지 - 서브클래스 관계 자체를 고정한다."""
        self.assertTrue(issubclass(PromotionConflictError, PromotionError))

    def test_conflict_error_message_names_content_id_and_both_generation_ids(self):
        try:
            plan_promotion(self.pool_path, self.production_path, "content-X", "gen-new")
            self.fail("PromotionConflictError가 발생해야 합니다.")
        except PromotionConflictError as error:
            message = str(error)
            self.assertIn("content-X", message)
            self.assertIn("gen-old", message)
            self.assertIn("gen-new", message)

    def test_d_existing_production_record_is_byte_for_byte_preserved_after_conflict(self):
        before_hash = _file_hash(self.production_path)
        before_records = load_archive(self.production_path)

        with self.assertRaises(PromotionConflictError):
            plan_promotion(self.pool_path, self.production_path, "content-X", "gen-new")

        after_hash = _file_hash(self.production_path)
        after_records = load_archive(self.production_path)
        self.assertEqual(before_hash, after_hash)
        self.assertEqual(before_records, after_records)
        self.assertEqual(after_records[0].rewritten_title, "옛 텍스트")
        self.assertEqual(after_records[0].generation_id, "gen-old")

    def test_cli_single_mode_conflict_exits_1_and_does_not_touch_production_archive(self):
        before_hash = _file_hash(self.production_path)

        exit_code, stdout = _run_cli(
            [
                "--archive", str(self.pool_path),
                "--production-archive", str(self.production_path),
                "--content-id", "content-X",
                "--generation-id", "gen-new",
                "--execute",
            ]
        )

        self.assertEqual(exit_code, 1)
        self.assertEqual(_file_hash(self.production_path), before_hash)
        self.assertEqual(load_archive(self.production_path)[0].rewritten_title, "옛 텍스트")

    def test_cli_single_mode_dry_run_conflict_also_exits_1_without_writing(self):
        exit_code, stdout = _run_cli(
            [
                "--archive", str(self.pool_path),
                "--production-archive", str(self.production_path),
                "--content-id", "content-X",
                "--generation-id", "gen-new",
            ]
        )

        self.assertEqual(exit_code, 1)
        self.assertEqual(load_archive(self.production_path)[0].rewritten_title, "옛 텍스트")


# --- E/F/G. 기존 record의 review_status(approved/published/superseded)별 정책 -


class CaseEFGExistingRecordReviewStatusPolicyTests(_TempArchiveMixin):
    """정책: 충돌 검사는 기존 레코드의 review_status를 전혀 참고하지 않는다 -
    approved든 superseded든(6-18 12장: "실제 published"는 review_status가
    아니라 별도의 publish history가 관리하지만, 이 스크립트는 애초에 publish
    history를 참조하지 않으므로(6-16/6-17이 이미 확인한 기존 사각지대, 이번
    작업 범위 밖) production archive에 approved로 남아있는 게시된 레코드도
    review_status="approved" 경로로 동일하게 보호된다) 무조건 차단한다."""

    def _assert_conflict_blocks_and_preserves(self, existing_review_status: str, *, extra: dict | None = None) -> None:
        extra = extra or {}
        old_active = _record(
            generation_id="gen-old", review_status=existing_review_status, rewritten_title="옛 텍스트", **extra
        )
        save_archive([old_active], self.production_path)
        save_archive(
            [_record(generation_id="gen-new", review_status="approved", rewritten_title="새 텍스트")],
            self.pool_path,
        )

        with self.assertRaises(PromotionConflictError):
            plan_promotion(self.pool_path, self.production_path, "content-X", "gen-new")

        preserved = load_archive(self.production_path)
        self.assertEqual(len(preserved), 1)
        self.assertEqual(preserved[0].review_status, existing_review_status)
        self.assertEqual(preserved[0].rewritten_title, "옛 텍스트")

    def test_case_e_existing_approved_record_blocks_conflicting_promotion(self):
        self._assert_conflict_blocks_and_preserves("approved")

    def test_case_f_existing_record_that_was_already_published_blocks_conflicting_promotion(self):
        """production archive record 자체에는 "published"라는 review_status
        값이 없다(review_status는 approved에서 멈춘다 - 실제 게시 여부는
        PublishHistory가 별도로 추적한다, content_engine/publish_history.py).
        따라서 "이미 게시된 approved 레코드"도 review_status="approved" 경로로
        들어오고, E와 동일하게 차단된다 - 이 테스트는 그 경로가 우회되지
        않음을 명시적으로 고정한다."""
        self._assert_conflict_blocks_and_preserves("approved")

    def test_case_g_existing_superseded_record_still_blocks_conflicting_promotion(self):
        """정책 결정(6-18): SUPERSEDED는 CONFLICT와 별개의 개념이다(12장) - 이미
        superseded된 레코드라도 그 content_id 슬롯의 마지막 상태(superseded_by
        포함)를 보존해야 하므로, 또 다른 generation으로 자동 대체되는 것도
        동일하게 차단한다. superseded 해제/재승격이 필요하면 이번 단계
        범위(자동 supersede 금지, 19장) 밖의 별도 절차가 필요하다."""
        self._assert_conflict_blocks_and_preserves(
            "superseded", extra={"superseded_by": "content-some-other-record"}
        )


# --- H/I. candidate 자체가 unreviewed/invalid이면 기존 규칙대로 차단 ----------


class CaseHICandidateGatingUnaffectedByConflictCheckTests(_TempArchiveMixin):
    """충돌 검사가 추가되기 전부터 있던 candidate 자체의 게이팅(unreviewed/
    invalid)이 여전히 먼저 걸리는지 - 기존 production 활성 레코드가 있어도
    이 게이팅 순서(먼저 candidate 조건, 그다음 conflict)가 바뀌지 않았는지
    확인한다. 두 경우 모두 기존 production 레코드는 전혀 바뀌지 않는다."""

    def setUp(self) -> None:
        super().setUp()
        self.old_active = _record(generation_id="gen-old", review_status="approved")
        save_archive([self.old_active], self.production_path)

    def test_case_h_new_generation_unreviewed_blocks_before_conflict_check(self):
        save_archive(
            [_record(generation_id="gen-new", review_status="unreviewed", generation_status="valid")],
            self.pool_path,
        )

        with self.assertRaises(PromotionError) as ctx:
            plan_promotion(self.pool_path, self.production_path, "content-X", "gen-new")

        self.assertNotIsInstance(ctx.exception, PromotionConflictError)
        self.assertEqual(load_archive(self.production_path)[0].generation_id, "gen-old")

    def test_case_i_new_generation_invalid_blocks_before_conflict_check(self):
        save_archive(
            [_record(generation_id="gen-new", review_status="approved", generation_status="rejected")],
            self.pool_path,
        )

        with self.assertRaises(PromotionError) as ctx:
            plan_promotion(self.pool_path, self.production_path, "content-X", "gen-new")

        self.assertNotIsInstance(ctx.exception, PromotionConflictError)
        self.assertEqual(load_archive(self.production_path)[0].generation_id, "gen-old")


# --- J. batch promotion: 충돌 1건이 다른 정상 record를 막지 않음 -------------


class CaseJBatchPromotionIsolatesConflictFromNormalRecordsTests(_TempArchiveMixin):
    def setUp(self) -> None:
        super().setUp()
        # 기존 production: content-B만 이미 활성 레코드(gen-old)로 존재한다.
        save_archive(
            [_record(content_id="content-B", generation_id="gen-old", review_status="approved")],
            self.production_path,
        )
        # generation pool: A(신규), B(충돌 - 다른 generation_id), C(신규) 모두 approved+valid.
        save_archive(
            [
                _record(content_id="content-A", generation_id="gen-batch", review_status="approved"),
                _record(content_id="content-B", generation_id="gen-batch", review_status="approved"),
                _record(content_id="content-C", generation_id="gen-batch", review_status="approved"),
            ],
            self.pool_path,
        )

    def test_plan_batch_promotion_classifies_each_record_independently(self):
        items = plan_batch_promotion(self.pool_path, self.production_path, "gen-batch")
        by_id = {item.record.content_id: item.action for item in items}

        self.assertEqual(by_id, {"content-A": "promote", "content-B": "conflict", "content-C": "promote"})

    def test_batch_execute_promotes_a_and_c_but_not_b_and_reports_conflict(self):
        exit_code, stdout = _run_cli(
            [
                "--archive", str(self.pool_path),
                "--production-archive", str(self.production_path),
                "--generation-id", "gen-batch",
                "--execute",
            ]
        )

        self.assertEqual(exit_code, 0)
        self.assertIn("승격 완료: 2건", stdout)
        self.assertIn("CONFLICT", stdout)

        final_records = {r.content_id: r for r in load_archive(self.production_path)}
        self.assertEqual(set(final_records), {"content-A", "content-B", "content-C"})
        self.assertEqual(final_records["content-A"].generation_id, "gen-batch")
        self.assertEqual(final_records["content-C"].generation_id, "gen-batch")
        # content-B는 절대 바뀌지 않는다 - 여전히 옛 generation_id 그대로다.
        self.assertEqual(final_records["content-B"].generation_id, "gen-old")

    def test_batch_dry_run_reports_conflict_without_writing_anything(self):
        before_hash = _file_hash(self.production_path)

        exit_code, stdout = _run_cli(
            [
                "--archive", str(self.pool_path),
                "--production-archive", str(self.production_path),
                "--generation-id", "gen-batch",
            ]
        )

        self.assertEqual(exit_code, 0)
        self.assertIn("DRY-RUN", stdout)
        self.assertIn("conflict:        1건", stdout)
        self.assertEqual(_file_hash(self.production_path), before_hash)


# --- K/L/M. dry-run/충돌 이후 파일 불변성(archive/generation pool 둘 다) -----


class CaseKLMFileImmutabilityAfterConflictTests(_TempArchiveMixin):
    def setUp(self) -> None:
        super().setUp()
        save_archive([_record(generation_id="gen-old", review_status="approved")], self.production_path)
        save_archive([_record(generation_id="gen-new", review_status="approved")], self.pool_path)

    def test_case_k_dry_run_detects_conflict_but_does_not_write_production_archive(self):
        before_hash = _file_hash(self.production_path)

        exit_code, stdout = _run_cli(
            [
                "--archive", str(self.pool_path),
                "--production-archive", str(self.production_path),
                "--content-id", "content-X",
                "--generation-id", "gen-new",
            ]
        )

        self.assertEqual(exit_code, 1)
        self.assertEqual(_file_hash(self.production_path), before_hash)

    def test_case_l_production_archive_sha256_unchanged_after_failed_execute(self):
        before_hash = _file_hash(self.production_path)

        _run_cli(
            [
                "--archive", str(self.pool_path),
                "--production-archive", str(self.production_path),
                "--content-id", "content-X",
                "--generation-id", "gen-new",
                "--execute",
            ]
        )

        self.assertEqual(_file_hash(self.production_path), before_hash)

    def test_case_m_generation_pool_sha256_unchanged_after_conflict(self):
        before_hash = _file_hash(self.pool_path)

        with self.assertRaises(PromotionConflictError):
            plan_promotion(self.pool_path, self.production_path, "content-X", "gen-new")
        _run_cli(
            [
                "--archive", str(self.pool_path),
                "--production-archive", str(self.production_path),
                "--content-id", "content-X",
                "--generation-id", "gen-new",
                "--execute",
            ]
        )

        self.assertEqual(_file_hash(self.pool_path), before_hash)


# --- Legacy record(generation_id=None) 보호 우회 금지 -------------------------


class LegacyRecordIsNotExemptFromConflictProtectionTests(_TempArchiveMixin):
    """6-18 절대 원칙(16장): generation_id가 None인 legacy record도 production
    archive에 존재하는 이상 새 generation_id를 가진 candidate와 content_id가
    같으면 충돌로 처리해야 한다 - "legacy라서 예외"는 없다."""

    def test_legacy_existing_record_without_generation_id_still_blocks_conflict(self):
        legacy = _record(generation_id=None, review_status="approved", rewritten_title="legacy 텍스트")
        save_archive([legacy], self.production_path)
        save_archive(
            [_record(generation_id="gen-new", review_status="approved", rewritten_title="새 텍스트")],
            self.pool_path,
        )

        with self.assertRaises(PromotionConflictError):
            plan_promotion(self.pool_path, self.production_path, "content-X", "gen-new")

        preserved = load_archive(self.production_path)
        self.assertEqual(len(preserved), 1)
        self.assertIsNone(preserved[0].generation_id)
        self.assertEqual(preserved[0].rewritten_title, "legacy 텍스트")

    def test_check_promotion_conflict_raises_for_legacy_existing_directly(self):
        legacy = _record(generation_id=None)
        candidate = _record(generation_id="gen-new")

        with self.assertRaises(ArchiveConflictError):
            check_promotion_conflict(existing=legacy, candidate=candidate)


# --- 실제 production archive(18건)는 이 파일에서 읽기만 한다 -----------------


class ExistingProductionArchiveReadOnlyRegressionTests(unittest.TestCase):
    """이번 6-18 변경이 실제 production archive의 기존 18건에 어떤 영향도 주지
    않는지 - 이 클래스는 그 파일을 읽기만 하고 절대 쓰지 않는다."""

    def test_real_production_archive_still_has_eighteen_records(self):
        records = load_archive(PRODUCTION_ARCHIVE_PATH)
        self.assertEqual(len(records), 18)

    def test_real_production_archive_has_no_duplicate_content_ids(self):
        """이 사실 자체가 이번 보호정책의 전제다 - production archive는 항상
        content_id당 활성 레코드가 정확히 하나였다(기존 upsert_archive() 설계,
        6-18은 이 불변식을 새로 만들지 않고 그저 "다음 upsert가 이 불변식을
        깨지 않게" 보호할 뿐이다)."""
        records = load_archive(PRODUCTION_ARCHIVE_PATH)
        content_ids = [record.content_id for record in records]
        self.assertEqual(len(content_ids), len(set(content_ids)))

    def test_known_forbidden_content_id_is_untouched_and_still_approved(self):
        """6-18 작업 지시의 절대 금지 목록에 있는 content_id 중 하나
        (content-5971ed5204437cdd)가 이 세션에서 전혀 바뀌지 않았는지 -
        읽기만 해서 확인한다(수정/승격/supersede 어느 것도 실행하지 않는다)."""
        records = {r.content_id: r for r in load_archive(PRODUCTION_ARCHIVE_PATH)}
        self.assertIn("content-5971ed5204437cdd", records)
        self.assertEqual(records["content-5971ed5204437cdd"].review_status, "approved")
        self.assertEqual(records["content-5971ed5204437cdd"].generation_status, "valid")
        self.assertIsNone(records["content-5971ed5204437cdd"].superseded_by)


if __name__ == "__main__":
    unittest.main()
