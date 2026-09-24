"""TAK AUTO 6-39 First Operating Day and Data Readiness
(docs/6-39-first-operating-day-and-data-readiness.md).

이 작업은 새 기능을 만드는 것이 목적이 아니다 - 6-21~6-23(Recovery
Architecture)/6-38(Operator Control Center)이 이미 계산한 상태를 실제
운영 시작 절차에 연결하는 것이 목적이다. 이 파일이 검증하는 신규 코드는
정확히 두 곳뿐이다:

    1. ``content_engine.operator_summary.build_recovery_status()`` -
       Production Archive가 STATE A(정상 부재)/STATE B(사라짐 - 복구
       필요)/STATE C(존재하지만 검증 필요)인지 구분하는 새 집계 함수.
       판정에 쓰는 신호(git 이력 존재 여부, archive 무결성 이슈 개수)는
       전부 6-22 ``recovery_staging.validate_production_archive()``와
       ``git log --all``이 이미 계산/제공하는 값을 그대로 재사용한다 -
       이 함수 자신은 새 검증 로직을 만들지 않는다.
    2. ``scripts.operator_control_center._ever_tracked_in_git()`` - git
       이력 조회(호출부 helper, 판정 로직 없음).

나머지 시나리오(superseded 제외, dry-run이 production을 바꾸지 않음,
Recovery Apply가 read-only 보고 단계를 거침 등)는 6-21/6-22/6-23/6-38이
이미 26~68개 테스트로 철저히 검증했다 - 이 파일은 그 테스트를 다시
베끼지 않고, 6-39가 새로 연결한 지점(Operator Control Center의 RECOVERY
행)에서 "그 기존 보장이 여전히 보인다"만 얇게 재확인한다(각 테스트
docstring에 어느 기존 테스트를 참조하는지 명시).

실제 외부 API는 호출하지 않는다. 실제 운영 데이터는 어디에서도
생성/수정하지 않는다 - 전부 tempfile이다. 이 저장소의 실제 git
history/README.md를 읽는 두 테스트(``GitHistoryClassificationTests``)만
예외이며, 둘 다 읽기 전용(``git log``)이고 아무것도 쓰지 않는다.
"""

from __future__ import annotations

import argparse
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from content_engine.data_state import CORRUPTED, NOT_PRESENT, VALID
from content_engine.media_archive import MediaArchiveRecord
from content_engine.recovery_decision import CONFLICT as RECOVERY_CONFLICT, REVIEW_REQUIRED as RECOVERY_REVIEW_REQUIRED
from content_engine.recovery_staging import validate_production_archive

from content_engine.operator_summary import (
    RECOVERY_NOT_REQUIRED,
    RECOVERY_REQUIRED,
    RECOVERY_UNVERIFIED,
    SYSTEM_NEEDS_REVIEW,
    OperatorInputs,
    build_operator_summary,
    build_recovery_status,
)
import scripts.operator_control_center as operator_cli
from scripts.run_scout_dashboard import render_operator_center_html

ROOT = Path(__file__).resolve().parents[1]


def _base_inputs(**overrides) -> OperatorInputs:
    defaults = dict(
        generated_at="2026-10-01T08:00:00+00:00", git_head="abc123", git_origin_main="abc123",
        git_working_tree_clean=True, test_status="PASS",
    )
    defaults.update(overrides)
    return OperatorInputs(**defaults)


def _record(**overrides) -> MediaArchiveRecord:
    defaults = dict(
        content_id="c1", knowledge_id="k1", platform="shorts", generation_status="valid",
        original_title="원본", original_body="원본 본문", rewritten_title=None, rewritten_body=None,
        source_url="https://example.test/1", evidence=(), evidence_unit_ids=(),
        created_at="2026-01-01T00:00:00Z", review_status="unreviewed",
    )
    defaults.update(overrides)
    return MediaArchiveRecord(**defaults)


def _write_archive(path: Path, records: list[MediaArchiveRecord]) -> None:
    path.write_text(json.dumps([r.to_dict() for r in records], ensure_ascii=False, indent=2), encoding="utf-8")


# --- 1. fresh clone / no operational data (STATE A) --------------------------


class Scenario1FreshCloneTests(unittest.TestCase):
    """1. fresh clone/no operational data - production_archive가 NOT_PRESENT고
    git에 커밋된 적도 없으면(STATE A) RECOVERY는 NOT_REQUIRED여야 하고,
    이를 시스템 오류(BLOCKED/NEEDS_REVIEW)로 격상시키면 안 된다."""

    def test_state_a_is_not_required_not_an_error(self) -> None:
        item = build_recovery_status(_base_inputs(production_archive_ever_tracked=False))
        self.assertEqual(item.status, RECOVERY_NOT_REQUIRED)
        self.assertIn("STATE A", item.why)

    def test_state_a_does_not_escalate_system_status(self) -> None:
        summary = build_operator_summary(_base_inputs(
            production_archive_ever_tracked=False, youtube_renderer_available=True, youtube_credentials_present=True,
        ))
        self.assertNotEqual(summary.system_status, SYSTEM_NEEDS_REVIEW)


# --- 2. operational data missing(일반) -----------------------------------------


class Scenario2OperationalDataMissingTests(unittest.TestCase):
    """2. operational data missing - production archive뿐 아니라 knowledge/
    threads_pending/performance/insight 등이 전부 NOT_PRESENT여도 크래시하지
    않고 각자의 NOT_PRESENT를 그대로 보여준다(6-38 데이터가 이미 검증한
    부분이지만, 6-39가 추가한 recovery 필드가 함께 있어도 깨지지 않음을
    재확인)."""

    def test_all_not_present_summary_includes_recovery_field(self) -> None:
        summary = build_operator_summary(_base_inputs())
        self.assertIsNotNone(summary.recovery)
        self.assertEqual(summary.recovery.label, "RECOVERY")


# --- 3. staging data present ---------------------------------------------------


class Scenario3StagingDataPresentTests(unittest.TestCase):
    """3. staging data present - Production Archive가 VALID고 6-22
    ``validate_production_archive()``가 이슈를 하나도 못 찾으면(정상 staging)
    RECOVERY는 NOT_REQUIRED다."""

    def test_valid_archive_without_issues_is_not_required(self) -> None:
        item = build_recovery_status(_base_inputs(production_archive_status=VALID, production_archive_issue_count=0))
        self.assertEqual(item.status, RECOVERY_NOT_REQUIRED)


# --- 4. recovery required(STATE B) ---------------------------------------------


class Scenario4RecoveryRequiredTests(unittest.TestCase):
    """4. recovery required - git 이력에는 Production Archive가 커밋된 적이
    있는데 지금 이 PC 디스크에는 없으면(STATE B) RECOVERY_REQUIRED여야
    하고, 이는 사람이 확인해야 하는 실제 문제이므로 system_status를
    NEEDS_REVIEW로 끌어올려야 한다."""

    def test_state_b_is_recovery_required(self) -> None:
        item = build_recovery_status(_base_inputs(production_archive_ever_tracked=True))
        self.assertEqual(item.status, RECOVERY_REQUIRED)
        self.assertIn("STATE B", item.why)
        self.assertTrue(item.action)

    def test_state_b_escalates_system_status(self) -> None:
        summary = build_operator_summary(_base_inputs(
            production_archive_ever_tracked=True, youtube_renderer_available=True, youtube_credentials_present=True,
        ))
        self.assertEqual(summary.system_status, SYSTEM_NEEDS_REVIEW)


# --- 5. production data protected ----------------------------------------------


class Scenario5ProductionDataProtectedTests(unittest.TestCase):
    """5. production data protected - ``build_recovery_status()``는 순수
    함수라 어떤 파일도 쓰지 않는다(recovery_apply/media_archive의 쓰기
    함수를 import하지 않음 - 정적 검증). 실제 atomic write/overwrite 방지
    자체는 6-23 ``ApplyGuardTests``/``AtomicApplyTests``가 이미 26개
    테스트로 검증했다(이 파일은 다시 만들지 않는다)."""

    def test_operator_summary_does_not_import_write_functions(self) -> None:
        import content_engine.operator_summary as module
        source = Path(module.__file__).read_text(encoding="utf-8")
        for forbidden in ("upsert_archive", "save_archive", "apply_recovery(", "set_review_status"):
            self.assertNotIn(forbidden, source)


# --- 6. dry-run does not mutate production --------------------------------------


class Scenario6DryRunDoesNotMutateTests(unittest.TestCase):
    """6. dry-run does not mutate production - operator_control_center.py를
    tempfile 대상으로 실행해도(신규 ``_ever_tracked_in_git``/
    ``validate_production_archive`` 호출 포함) 대상 파일이 생성되거나
    바뀌지 않는다. 실제 apply 경로(``--apply``)의 원자적 쓰기/롤백
    자체는 6-23이 이미 검증했다(중복 없음)."""

    def test_load_operator_inputs_does_not_write_target_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            args = argparse.Namespace(
                data_dir=tmp_path,
                scout_daily=tmp_path / "tak_scout_daily.json",
                knowledge=tmp_path / "tak_brain_knowledge.json",
                production_archive=tmp_path / "tak_media_archive.json",
                threads_pending=tmp_path / "tak_threads_pending.json",
                performance=tmp_path / "tak_performance.json",
                insights=tmp_path / "tak_performance_insights.json",
                shorts_scripts=tmp_path / "shorts_scripts",
                blog_drafts=tmp_path / "blog_drafts",
            )
            before = sorted(p.name for p in tmp_path.iterdir())
            inputs = operator_cli._load_operator_inputs(args, "UNKNOWN")
            after = sorted(p.name for p in tmp_path.iterdir())
            self.assertEqual(before, after)
            self.assertEqual(inputs.production_archive_status, NOT_PRESENT)
            # tempfile 경로는 저장소(ROOT) 밖이므로 git 이력을 확인할 수
            # 없다 - 이것이 바로 11번(unknown/unverified) 시나리오다.
            self.assertIsNone(inputs.production_archive_ever_tracked)


# --- 7. operator remains read-only ----------------------------------------------


class Scenario7OperatorReadOnlyTests(unittest.TestCase):
    """7. operator remains read-only - RECOVERY 행이 추가된 뒤에도
    ``/operator`` HTML에는 여전히 form 태그가 없다(6-38
    ``test_no_form_tags_in_operator_html``과 동일한 불변식을 6-39가
    바꾸지 않았음을 재확인)."""

    def test_operator_html_still_has_no_form_tags(self) -> None:
        summary = build_operator_summary(_base_inputs(production_archive_ever_tracked=True))
        html = render_operator_center_html(summary)
        self.assertNotIn("<form", html)
        self.assertIn("RECOVERY", html)
        self.assertIn(RECOVERY_REQUIRED, html)


# --- 8. superseded data excluded -------------------------------------------------


class Scenario8SupersededExcludedTests(unittest.TestCase):
    """8. superseded data excluded - RECOVERY 판정은 superseded 여부를
    전혀 보지 않는다(archive 유무/무결성만 본다) - superseded 레코드가
    있어도 RECOVERY 판정에 영향이 없어야 한다(그 판정은 이미 6-19/6-37이
    다른 축에서 담당한다). 6-38 ``test_scenario_h_superseded_content_exists``가
    이미 pipeline/publish 쪽 제외 로직을 검증했다 - 여기서는 recovery
    필드가 그 판정을 흔들지 않는지만 확인한다."""

    def test_superseded_records_do_not_affect_recovery_status(self) -> None:
        active = _record(content_id="c1", review_status="approved")
        superseded = _record(content_id="c0", review_status="superseded", superseded_by="c1")
        summary = build_operator_summary(_base_inputs(
            production_archive_status=VALID, production_records=(superseded, active), production_archive_issue_count=0,
        ))
        self.assertEqual(summary.recovery.status, RECOVERY_NOT_REQUIRED)


# --- 9. content_id conflict detected ---------------------------------------------


class Scenario9ContentIdConflictTests(unittest.TestCase):
    """9. content_id conflict detected - 6-22
    ``validate_production_archive()``가 실제로 계산한 duplicate content_id
    이슈 개수를 RECOVERY가 CONFLICT로 정확히 반영하는지 end-to-end로
    확인한다(새 검증 로직이 아니라 기존 함수의 실제 반환값을 그대로
    통합)."""

    def test_duplicate_content_id_becomes_recovery_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tak_media_archive.json"
            _write_archive(path, [
                _record(content_id="dup", review_status="approved"),
                _record(content_id="dup", review_status="approved"),
            ])
            report = validate_production_archive(path)
            self.assertTrue(report.issues)  # 6-22가 이미 A_DUPLICATE_CONTENT_ID로 분류

            item = build_recovery_status(_base_inputs(
                production_archive_status=VALID, production_archive_issue_count=len(report.issues),
            ))
            self.assertEqual(item.status, RECOVERY_CONFLICT)
            self.assertEqual(item.count, len(report.issues))


# --- 10. first operating day readiness -------------------------------------------


class Scenario10FirstOperatingDayReadinessTests(unittest.TestCase):
    """10. first operating day readiness - 완전 fresh clone(모든 데이터
    NOT_PRESENT, git 정상, YouTube renderer 없음)에서 Operator Control
    Center가 던지는 결론이 "지금 시작해도 되는가"에 대한 정직한 답인지
    확인한다: 가짜 READY가 아니라 human action이 명시되고, RECOVERY는
    NOT_REQUIRED(정상 시작 가능)여야 한다."""

    def test_fresh_clone_readiness_is_honest(self) -> None:
        summary = build_operator_summary(_base_inputs(production_archive_ever_tracked=False))
        self.assertEqual(summary.recovery.status, RECOVERY_NOT_REQUIRED)
        # YouTube renderer가 없으므로(기본값 False) BLOCKED 항목이 있어야
        # 하고, 이는 가짜 READY가 아니라는 뜻이다.
        self.assertTrue(summary.blocked_items)


# --- 11. unknown/unverified environment state -------------------------------------


class Scenario11UnverifiedTests(unittest.TestCase):
    """11. unknown/unverified environment state - git 이력을 확인할 수
    없으면(예: 저장소 밖 경로, 또는 git 명령 실패) "문제 있음"으로
    임의로 단정하지 않고 UNVERIFIED로 정직하게 표시하며, 이는 system
    상태를 끌어올리지 않는다("모른다"와 "문제 있다"를 구분)."""

    def test_unverified_does_not_escalate(self) -> None:
        item = build_recovery_status(_base_inputs())  # ever_tracked 기본값 None
        self.assertEqual(item.status, RECOVERY_UNVERIFIED)
        summary = build_operator_summary(_base_inputs(youtube_renderer_available=True, youtube_credentials_present=True))
        self.assertNotEqual(summary.system_status, SYSTEM_NEEDS_REVIEW)


class GitHistoryClassificationTests(unittest.TestCase):
    """``_ever_tracked_in_git()``이 실제 이 저장소의 잘 알려진(그리고 6-21이
    이미 문서로 확정한) 두 사실을 정확히 구분하는지 확인한다 - 읽기
    전용(``git log``)이며 어떤 파일도 쓰지 않는다."""

    def test_readme_is_tracked(self) -> None:
        self.assertTrue(operator_cli._ever_tracked_in_git(ROOT / "README.md"))

    def test_production_archive_was_never_committed(self) -> None:
        # docs/6-21 3장이 이미 확인한 사실: tak_media_archive.json은 main
        # 어떤 커밋에도 존재한 적이 없다(화이트리스트에는 있으나 미커밋).
        self.assertFalse(operator_cli._ever_tracked_in_git(ROOT / "data" / "tak_media_archive.json"))

    def test_path_outside_repo_is_unverified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(operator_cli._ever_tracked_in_git(Path(tmp) / "tak_media_archive.json"))


# --- 12. data classification ------------------------------------------------------


class Scenario12DataClassificationTests(unittest.TestCase):
    """12. data classification - RECOVERY 판정이 4가지 값(정상/검토
    필요/충돌/복구 필요)만 반환하고, 그 값들이 기존 6-23
    ``recovery_decision`` 어휘(REVIEW_REQUIRED/CONFLICT)와 이번에 새로
    만든 값(NOT_REQUIRED/RECOVERY_REQUIRED/UNVERIFIED) 중 하나임을
    확인한다 - 단일 숫자 점수가 아니라 상태 기반이어야 한다."""

    ALLOWED = {RECOVERY_NOT_REQUIRED, RECOVERY_REQUIRED, RECOVERY_UNVERIFIED, RECOVERY_CONFLICT, RECOVERY_REVIEW_REQUIRED}

    def test_all_four_classification_paths_use_known_vocabulary(self) -> None:
        cases = [
            _base_inputs(production_archive_ever_tracked=False),
            _base_inputs(production_archive_ever_tracked=True),
            _base_inputs(production_archive_status=CORRUPTED),
            _base_inputs(production_archive_status=VALID, production_archive_issue_count=1),
            _base_inputs(),  # UNVERIFIED
        ]
        for inputs in cases:
            item = build_recovery_status(inputs)
            self.assertIn(item.status, self.ALLOWED)
            self.assertIsInstance(item.status, str)
            # 점수(float/int) 필드가 아니라 상태 문자열이어야 한다.
            self.assertNotIsInstance(item.status, (int, float))

    def test_recovery_field_is_json_serializable(self) -> None:
        summary = build_operator_summary(_base_inputs(production_archive_ever_tracked=True))
        payload = summary.to_dict()
        self.assertIn("recovery", payload)
        json.dumps(payload, ensure_ascii=False)  # 예외 없이 직렬화되어야 함


# --- CLI: --json 출력에도 recovery가 포함되는지 -----------------------------------


class CliJsonOutputTests(unittest.TestCase):
    def test_cli_json_output_includes_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            argv = ["--data-dir", str(tmp_path), "--json"]
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = operator_cli.main(argv)
            self.assertEqual(exit_code, 0)
            payload = json.loads(buffer.getvalue())
            self.assertIn("recovery", payload)
            self.assertIn(payload["recovery"]["status"], Scenario12DataClassificationTests.ALLOWED)
            # tempfile 대상 실행이므로 recovery는 확인 불가 상태여야 한다
            # (저장소 밖 경로 - GitHistoryClassificationTests의 3번째 케이스).
            self.assertEqual(payload["recovery"]["status"], RECOVERY_UNVERIFIED)


if __name__ == "__main__":
    unittest.main()
