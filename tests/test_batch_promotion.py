"""6-09 회귀 테스트: Batch Promotion(여러 generation record를 한 번에 승격) +
Dashboard 검수 현황 요약.

docs/6-09_batch_promotion_and_production_readiness.md 참고. 실제 LLM은 호출하지
않는다. 실제 production archive(``data/tak_media_archive.json``)는 이 테스트
파일 어디에서도 열리지 않는다 - 전부 ``tempfile.TemporaryDirectory()`` 안의
임시 파일만 사용한다.

이 파일이 다루는 범위(6-08의 tests/test_generation_review_and_promotion.py의
PromotionSafetyTests와 중복되지 않는 것만):
    - ``plan_batch_promotion()``/CLI batch 모드(``--content-id`` 생략,
      ``--generation-id``만) 의 partial approval 정책(9장 A~N)
    - batch 모드가 --production-archive 없이는 실행되지 않는 안전장치
    - 기존 단건(``--content-id``) CLI 동작이 이번 변경으로 깨지지 않았는지 regression
    - Dashboard의 generation별 검수 현황 요약(총/valid/approved/unreviewed/dismissed,
      platform별 승인 현황)

6-10에서 추가한 범위(docs/6-10_generation_edit_and_final_review.md 15/17장):
    - 혼합(mixed) idempotency: 여러 record가 서로 다른 시점에 approved가 되는
      상황에서 batch execute를 반복 실행해도 이미 승격된 record는 다시 쓰지 않고,
      새로 approved된 record만 추가로 승격되는지(실제 파일 I/O로 검증)
    - edited_title/edited_body가 있는 record가 batch promotion을 거쳐 production
      archive에 들어갈 때, 최종 final_title/final_body가 edited 값을 쓰는지
"""

from __future__ import annotations

import contextlib
from dataclasses import replace
import io
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from content_engine.media_archive import MediaArchiveRecord, load_archive, save_archive
from scripts.promote_media_generation import (
    BatchPromotionItem,
    PromotionError,
    main as promote_main,
    plan_batch_promotion,
)
from scripts.run_scout_dashboard import summarize_generation_reviews, summarize_platform_approval


def _record(**overrides) -> MediaArchiveRecord:
    fields = {
        "content_id": "content-6-09-test-1",
        "knowledge_id": "knowledge-6-09-test",
        "platform": "blog",
        "generation_status": "valid",
        "original_title": "원본 제목",
        "original_body": "원본 본문",
        "rewritten_title": "재작성 제목",
        "rewritten_body": "재작성 본문",
        "source_url": "https://example.test/6-09",
        "evidence": ("SOURCE FACT: 예시",),
        "evidence_unit_ids": ("lesson:1",),
        "created_at": "2026-09-20T00:00:00+00:00",
        "review_status": "unreviewed",
        "generation_id": "gen-6-09-a",
    }
    fields.update(overrides)
    return MediaArchiveRecord(**fields)


def _run_cli(argv: list[str]) -> tuple[int, str]:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        exit_code = promote_main(argv)
    return exit_code, buffer.getvalue()


class BatchPromotionPlanningTests(unittest.TestCase):
    """``plan_batch_promotion()`` 자체의 분류 로직 - 파일을 쓰지 않는다."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.directory = Path(self._tmp.name)
        self.pool_path = self.directory / "pool.json"
        self.production_path = self.directory / "prod.json"

    def test_case_a_all_unreviewed_yields_zero_promoted(self):
        save_archive(
            [_record(content_id=f"c{i}", review_status="unreviewed") for i in range(3)], self.pool_path
        )

        items = plan_batch_promotion(self.pool_path, self.production_path, "gen-6-09-a")

        self.assertEqual(len(items), 3)
        self.assertTrue(all(item.action == "skip" for item in items))
        self.assertFalse(self.production_path.exists())

    def test_case_b_partial_approval_only_approved_are_promoted(self):
        save_archive(
            [
                _record(content_id="c-approved", review_status="approved"),
                _record(content_id="c-unreviewed", review_status="unreviewed"),
            ],
            self.pool_path,
        )

        items = plan_batch_promotion(self.pool_path, self.production_path, "gen-6-09-a")
        by_id = {item.record.content_id: item for item in items}

        self.assertEqual(by_id["c-approved"].action, "promote")
        self.assertEqual(by_id["c-unreviewed"].action, "skip")

    def test_case_c_approved_and_dismissed_only_approved_promoted(self):
        save_archive(
            [
                _record(content_id="c-approved", review_status="approved"),
                _record(content_id="c-dismissed", review_status="dismissed"),
            ],
            self.pool_path,
        )

        items = plan_batch_promotion(self.pool_path, self.production_path, "gen-6-09-a")
        by_id = {item.record.content_id: item for item in items}

        self.assertEqual(by_id["c-approved"].action, "promote")
        self.assertEqual(by_id["c-dismissed"].action, "skip")
        self.assertIn("dismissed", by_id["c-dismissed"].reason)

    def test_case_d_approved_and_rejected_only_approved_promoted(self):
        save_archive(
            [
                _record(content_id="c-approved", review_status="approved"),
                _record(content_id="c-rejected", review_status="approved", generation_status="rejected"),
            ],
            self.pool_path,
        )

        items = plan_batch_promotion(self.pool_path, self.production_path, "gen-6-09-a")
        by_id = {item.record.content_id: item for item in items}

        self.assertEqual(by_id["c-approved"].action, "promote")
        self.assertEqual(by_id["c-rejected"].action, "skip")
        self.assertIn("rejected", by_id["c-rejected"].reason)

    def test_case_e_all_approved_all_promoted(self):
        save_archive(
            [_record(content_id=f"c{i}", review_status="approved") for i in range(4)], self.pool_path
        )

        items = plan_batch_promotion(self.pool_path, self.production_path, "gen-6-09-a")

        self.assertTrue(all(item.action == "promote" for item in items))

    def test_case_k_different_generation_records_are_not_mixed_in(self):
        save_archive(
            [
                _record(content_id="c-a", review_status="approved", generation_id="gen-6-09-a"),
                _record(content_id="c-b", review_status="approved", generation_id="gen-6-09-other"),
            ],
            self.pool_path,
        )

        items = plan_batch_promotion(self.pool_path, self.production_path, "gen-6-09-a")

        self.assertEqual([item.record.content_id for item in items], ["c-a"])

    def test_case_l_legacy_records_without_generation_id_are_not_matched(self):
        save_archive(
            [
                _record(content_id="c-a", review_status="approved", generation_id="gen-6-09-a"),
                _record(content_id="c-legacy", review_status="approved", generation_id=None),
            ],
            self.pool_path,
        )

        items = plan_batch_promotion(self.pool_path, self.production_path, "gen-6-09-a")

        self.assertEqual([item.record.content_id for item in items], ["c-a"])

        # generation_id가 None인 legacy record 자체도 별도로 조회 가능해야 한다
        # (None 자체가 하나의 유효한 조회 키다) - 다만 "gen-6-09-a"와는 절대 섞이지 않는다.
        legacy_items = plan_batch_promotion(self.pool_path, self.production_path, None)  # type: ignore[arg-type]
        self.assertEqual([item.record.content_id for item in legacy_items], ["c-legacy"])

    def test_case_m_nonexistent_generation_raises_clear_error(self):
        save_archive([_record(content_id="c-a", review_status="approved")], self.pool_path)

        with self.assertRaises(PromotionError):
            plan_batch_promotion(self.pool_path, self.production_path, "gen-does-not-exist")


class BatchPromotionCliTests(unittest.TestCase):
    """CLI(``main()``) batch 모드 - dry-run/execute/idempotency/안전장치."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.directory = Path(self._tmp.name)
        self.pool_path = self.directory / "pool.json"
        self.production_path = self.directory / "prod.json"

    def _seed(self, records: list[MediaArchiveRecord]) -> None:
        save_archive(records, self.pool_path)

    def test_batch_dry_run_does_not_touch_production_archive(self):
        self._seed(
            [
                _record(content_id="c-approved", review_status="approved"),
                _record(content_id="c-unreviewed", review_status="unreviewed"),
            ]
        )

        exit_code, stdout = _run_cli(
            [
                "--archive", str(self.pool_path),
                "--production-archive", str(self.production_path),
                "--generation-id", "gen-6-09-a",
            ]
        )

        self.assertEqual(exit_code, 0)
        self.assertFalse(self.production_path.exists())
        self.assertIn("DRY-RUN", stdout)
        self.assertIn("promotion 예정:  1건", stdout)
        self.assertIn("skip:            1건", stdout)

    def test_batch_execute_writes_only_approved_records(self):
        self._seed(
            [
                _record(content_id="c-approved", review_status="approved"),
                _record(content_id="c-unreviewed", review_status="unreviewed"),
                _record(content_id="c-dismissed", review_status="dismissed"),
            ]
        )

        exit_code, stdout = _run_cli(
            [
                "--archive", str(self.pool_path),
                "--production-archive", str(self.production_path),
                "--generation-id", "gen-6-09-a",
                "--execute",
            ]
        )

        self.assertEqual(exit_code, 0)
        promoted = load_archive(self.production_path)
        self.assertEqual({r.content_id for r in promoted}, {"c-approved"})
        self.assertIn("승격 완료: 1건", stdout)

    def test_batch_execute_twice_is_idempotent(self):
        self._seed([_record(content_id="c-approved", review_status="approved")])

        self._run_execute_once()
        first = load_archive(self.production_path)

        exit_code, stdout = _run_cli(
            [
                "--archive", str(self.pool_path),
                "--production-archive", str(self.production_path),
                "--generation-id", "gen-6-09-a",
                "--execute",
            ]
        )
        second = load_archive(self.production_path)

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 1)
        self.assertIn("ALREADY PROMOTED", stdout)
        self.assertIn("promotion 대상이 없습니다", stdout)

    def _run_execute_once(self) -> None:
        _run_cli(
            [
                "--archive", str(self.pool_path),
                "--production-archive", str(self.production_path),
                "--generation-id", "gen-6-09-a",
                "--execute",
            ]
        )

    def test_batch_without_explicit_production_archive_refuses_to_run(self):
        """6-09 8장 안전 원칙: batch 모드는 --production-archive 없이는 (dry-run조차)
        실행되지 않는다 - "기본값으로 실제 production archive에 쓴다"는 사고를
        구조적으로 막는다."""
        self._seed([_record(content_id="c-approved", review_status="approved")])

        exit_code, _ = _run_cli(["--archive", str(self.pool_path), "--generation-id", "gen-6-09-a"])

        self.assertEqual(exit_code, 1)

    def test_batch_zero_promotable_records_is_not_an_error(self):
        """9장 N: promotion 대상이 0건이어도(전부 unreviewed 등) 오류가 아니다 -
        dry-run/execute 모두 exit 0으로 끝나고, execute는 아무것도 쓰지 않는다."""
        self._seed([_record(content_id="c-unreviewed", review_status="unreviewed")])

        dry_exit, dry_stdout = _run_cli(
            [
                "--archive", str(self.pool_path),
                "--production-archive", str(self.production_path),
                "--generation-id", "gen-6-09-a",
            ]
        )
        execute_exit, execute_stdout = _run_cli(
            [
                "--archive", str(self.pool_path),
                "--production-archive", str(self.production_path),
                "--generation-id", "gen-6-09-a",
                "--execute",
            ]
        )

        self.assertEqual(dry_exit, 0)
        self.assertEqual(execute_exit, 0)
        self.assertFalse(self.production_path.exists())
        self.assertIn("promotion 대상이 없습니다", execute_stdout)

    def test_batch_nonexistent_generation_returns_clear_error(self):
        self._seed([_record(content_id="c-a", review_status="approved")])

        exit_code, _ = _run_cli(
            [
                "--archive", str(self.pool_path),
                "--production-archive", str(self.production_path),
                "--generation-id", "gen-does-not-exist",
            ]
        )

        self.assertEqual(exit_code, 1)


class SingleModeRegressionTests(unittest.TestCase):
    """6-06 단건(``--content-id``) CLI 동작이 이번 batch 확장으로 깨지지 않았는지."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.directory = Path(self._tmp.name)
        self.pool_path = self.directory / "pool.json"
        self.production_path = self.directory / "prod.json"
        save_archive([_record(content_id="c-single", review_status="approved")], self.pool_path)

    def test_single_mode_still_requires_explicit_production_archive_flag_to_write_there(self):
        exit_code, stdout = _run_cli(
            [
                "--archive", str(self.pool_path),
                "--production-archive", str(self.production_path),
                "--content-id", "c-single",
                "--generation-id", "gen-6-09-a",
                "--execute",
            ]
        )

        self.assertEqual(exit_code, 0)
        promoted = load_archive(self.production_path)
        self.assertEqual([r.content_id for r in promoted], ["c-single"])
        self.assertIn("승격 완료", stdout)

    def test_single_mode_without_explicit_production_archive_falls_back_to_default_path(self):
        """6-06 기존 동작(하위 호환): --content-id를 쓰면 --production-archive를
        생략해도 여전히 기본 경로(``DEFAULT_PRODUCTION_ARCHIVE_PATH``)로 동작한다
        - 이번 6-09 변경(batch 모드는 명시 필수)이 단건 모드의 기존 기본값 동작을
        바꾸지 않았는지 확인한다. 실제 production archive를 건드리지 않도록 그
        상수 자체를 임시 경로로 patch해서 검증한다(dry-run이므로 어차피 쓰지는
        않지만, "어떤 경로를 읽으려 했는지"까지 확인한다)."""
        fake_default = self.directory / "fake_default_production.json"
        with mock.patch(
            "scripts.promote_media_generation.DEFAULT_PRODUCTION_ARCHIVE_PATH", fake_default
        ):
            exit_code, stdout = _run_cli(
                [
                    "--archive", str(self.pool_path),
                    "--content-id", "c-single",
                    "--generation-id", "gen-6-09-a",
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("DRY-RUN", stdout)
        self.assertFalse(fake_default.exists())


class DashboardReviewSummaryTests(unittest.TestCase):
    """/media/generations의 검수 현황 요약(6-09 14장/15장) - production archive를
    전혀 읽지 않는 순수 집계 함수만 테스트한다(HTTP 레벨 렌더링은 6-08의
    GenerationPoolDashboardRouteTests가 이미 커버)."""

    def test_summarize_generation_reviews_matches_real_9_record_shape(self):
        records = (
            [_record(content_id="blog-1", platform="blog")]
            + [_record(content_id=f"shorts-{i}", platform="shorts") for i in range(3)]
            + [_record(content_id=f"threads-{i}", platform="threads") for i in range(5)]
        )

        summary = summarize_generation_reviews(records)

        self.assertEqual(
            summary,
            {"total": 9, "valid": 9, "rejected": 0, "error": 0, "approved": 0, "unreviewed": 9, "dismissed": 0},
        )

    def test_summarize_platform_approval_counts_approved_per_platform(self):
        records = [
            _record(content_id="blog-1", platform="blog", review_status="approved"),
            _record(content_id="shorts-1", platform="shorts", review_status="approved"),
            _record(content_id="shorts-2", platform="shorts", review_status="unreviewed"),
            _record(content_id="shorts-3", platform="shorts", review_status="unreviewed"),
        ]

        result = summarize_platform_approval(records)

        self.assertEqual(result, [("blog", 1, 1), ("shorts", 1, 3)])

    def test_summary_never_touches_production_archive(self):
        """이 요약 함수들은 production archive 경로를 인자로 받지 않는다 -
        시그니처 자체가 production archive를 참조할 수 없다는 것이 안전장치다."""
        import inspect

        for func in (summarize_generation_reviews, summarize_platform_approval):
            params = inspect.signature(func).parameters
            self.assertNotIn("production", " ".join(params).lower())
            self.assertEqual(list(params), ["records"])


# --- 6-10 15장: Batch Promotion 혼합(mixed) idempotency ---------------------


class MixedIdempotencyBatchPromotionTests(unittest.TestCase):
    """여러 record가 서로 다른 시점에 approved가 되는 실제 운영 시나리오를 실제
    파일 I/O(임시 파일)로 검증한다 - 6-09에서 남겨둔 테스트 공백(6-09 15장)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.directory = Path(self._tmp.name)
        self.pool_path = self.directory / "pool.json"
        self.production_path = self.directory / "prod.json"

    def _execute(self) -> tuple[int, str]:
        return _run_cli(
            [
                "--archive", str(self.pool_path),
                "--production-archive", str(self.production_path),
                "--generation-id", "gen-mixed",
                "--execute",
            ]
        )

    def test_scenario_1_two_approved_one_unreviewed_repeat_execute_is_idempotent(self):
        """A=approved, B=approved, C=unreviewed. 첫 execute는 A+B를 승격한다.
        두 번째 execute는 아무 상태 변화 없이 다시 실행해도 A/B는
        already_promoted로만 보고되고 production에는 A/B만 (각 1건씩) 남는다 -
        C는 계속 skip이고 production에는 절대 들어가지 않는다."""
        save_archive(
            [
                _record(content_id="a", generation_id="gen-mixed", review_status="approved"),
                _record(content_id="b", generation_id="gen-mixed", review_status="approved"),
                _record(content_id="c", generation_id="gen-mixed", review_status="unreviewed"),
            ],
            self.pool_path,
        )

        first_exit, first_stdout = self._execute()
        self.assertEqual(first_exit, 0)
        self.assertIn("승격 완료: 2건", first_stdout)
        first_ids = {r.content_id for r in load_archive(self.production_path)}
        self.assertEqual(first_ids, {"a", "b"})

        second_exit, second_stdout = self._execute()
        self.assertEqual(second_exit, 0)
        self.assertIn("ALREADY PROMOTED", second_stdout)
        self.assertIn("promotion 대상이 없습니다", second_stdout)

        final_records = load_archive(self.production_path)
        self.assertEqual({r.content_id for r in final_records}, {"a", "b"})
        self.assertEqual(len(final_records), 2, "중복 승격으로 레코드가 늘어나면 안 된다.")

        # 계획 단계에서도 정확한 action으로 분류되는지 재확인한다(9장 표기와 동일).
        items = plan_batch_promotion(self.pool_path, self.production_path, "gen-mixed")
        by_id = {item.record.content_id: item.action for item in items}
        self.assertEqual(by_id, {"a": "already_promoted", "b": "already_promoted", "c": "skip"})

    def test_scenario_2_approval_happens_between_two_executes(self):
        """1차 실행 시점에는 A만 approved(B/C는 unreviewed)라 A만 승격된다. 1차
        실행과 2차 실행 사이에 사람이 B를 승인한다(Dashboard가 하는 것과 동일하게
        generation pool 파일만 직접 갱신). 2차 실행에서는 A=already_promoted,
        B=promote, C=skip으로 정확히 나뉘고, production에는 A/B만 남는다(C는
        끝까지 0건)."""
        save_archive(
            [
                _record(content_id="a", generation_id="gen-mixed", review_status="approved"),
                _record(content_id="b", generation_id="gen-mixed", review_status="unreviewed"),
                _record(content_id="c", generation_id="gen-mixed", review_status="unreviewed"),
            ],
            self.pool_path,
        )

        first_exit, first_stdout = self._execute()
        self.assertEqual(first_exit, 0)
        self.assertIn("승격 완료: 1건", first_stdout)
        self.assertEqual({r.content_id for r in load_archive(self.production_path)}, {"a"})

        # 사람이 이제 B를 승인한다(Dashboard 승인 액션과 동일한 파일 갱신).
        pool_records = load_archive(self.pool_path)
        updated_pool = [
            replace(record, review_status="approved") if record.content_id == "b" else record
            for record in pool_records
        ]
        save_archive(updated_pool, self.pool_path)

        items_before_second_execute = plan_batch_promotion(self.pool_path, self.production_path, "gen-mixed")
        by_id_before = {item.record.content_id: item.action for item in items_before_second_execute}
        self.assertEqual(by_id_before, {"a": "already_promoted", "b": "promote", "c": "skip"})

        second_exit, second_stdout = self._execute()
        self.assertEqual(second_exit, 0)
        self.assertIn("승격 완료: 1건", second_stdout)

        final_records = load_archive(self.production_path)
        self.assertEqual({r.content_id for r in final_records}, {"a", "b"})
        # a는 여전히 정확히 1건뿐이어야 한다(재승격으로 중복되지 않음).
        self.assertEqual(len([r for r in final_records if r.content_id == "a"]), 1)
        self.assertEqual(len([r for r in final_records if r.content_id == "c"]), 0)


# --- 6-10 17장: edited content가 batch promotion을 거쳐도 유지되는지 --------


class EditedContentPromotionTests(unittest.TestCase):
    """사람이 수정한(edited_title/edited_body) generation record가 batch
    promotion을 거쳐 production archive에 들어갈 때, final_title/final_body가
    rewritten이 아니라 edited 값을 쓰는지 확인한다(우선순위:
    edited -> rewritten -> original, content_engine/media_archive.py 참고)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.directory = Path(self._tmp.name)
        self.pool_path = self.directory / "pool.json"
        self.production_path = self.directory / "prod.json"

    def test_edited_title_and_body_win_over_rewritten_after_batch_promotion(self):
        save_archive(
            [
                _record(
                    content_id="c-edited",
                    generation_id="gen-mixed",
                    review_status="approved",
                    rewritten_title="원래 제목",
                    rewritten_body="원래 본문",
                    edited_title="사람이 수정한 제목",
                    edited_body="사람이 수정한 본문",
                )
            ],
            self.pool_path,
        )

        exit_code, stdout = _run_cli(
            [
                "--archive", str(self.pool_path),
                "--production-archive", str(self.production_path),
                "--generation-id", "gen-mixed",
                "--execute",
            ]
        )

        self.assertEqual(exit_code, 0)
        self.assertIn("승격 완료: 1건", stdout)

        promoted = load_archive(self.production_path)[0]
        # rewritten_*은 그대로 보존된다 - final_*만 edited 값을 고른다.
        self.assertEqual(promoted.rewritten_title, "원래 제목")
        self.assertEqual(promoted.rewritten_body, "원래 본문")
        self.assertEqual(promoted.final_title, "사람이 수정한 제목")
        self.assertEqual(promoted.final_body, "사람이 수정한 본문")


if __name__ == "__main__":
    unittest.main()
