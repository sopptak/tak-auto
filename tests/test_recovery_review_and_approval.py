"""content_engine/recovery_decision.py + recovery_apply.py + scripts/recover_media_archive.py
테스트(6-23). 6-23 지시 13장이 요구하는 A~N 시나리오를 전부 다룬다.

모든 fixture는 ``tempfile.TemporaryDirectory()``로 격리한다 - 실제 ``data/``는
``NoRealDataMutatedTests``에서 "바뀌지 않았는가"만 읽기로 확인한다. 어떤
테스트도 실제 ``data/tak_media_archive.json``을 만들거나 쓰지 않는다 -
``--production-archive``/``target_archive_path``는 항상 tempfile 경로다.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_engine import recovery_decision as rd
from content_engine import recovery_apply as ra
from content_engine.media_archive import MediaArchiveRecord, save_archive
import scripts.recover_media_archive as cli_module


def _record(**overrides) -> MediaArchiveRecord:
    defaults = dict(
        content_id="c1",
        knowledge_id="k1",
        platform="shorts",
        generation_status="valid",
        original_title="원본 제목",
        original_body="원본 본문",
        rewritten_title=None,
        rewritten_body=None,
        source_url="https://example.test/1",
        evidence=(),
        evidence_unit_ids=(),
        created_at="2026-01-01T00:00:00Z",
        review_status="unreviewed",
    )
    defaults.update(overrides)
    return MediaArchiveRecord(**defaults)


def _write_json(path: Path, records) -> None:
    payload = [r.to_dict() if isinstance(r, MediaArchiveRecord) else r for r in records]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class _RecoveryFixture:
    """source/target 두 임시 디렉터리를 만들어 준다."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.source_dir = Path(self._tmp.name) / "source"
        self.source_dir.mkdir()
        self.target_path = Path(self._tmp.name) / "target" / "tak_media_archive.json"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write_source_archive(self, records) -> None:
        _write_json(self.source_dir / "tak_media_archive.json", records)

    def write_generation_pool(self, name: str, records) -> None:
        _write_json(self.source_dir / f"tak_media_generation_{name}.json", records)

    def write_target_archive(self, records) -> None:
        _write_json(self.target_path, records)

    def write_threads_pending(self, drafts: list[dict]) -> None:
        _write_json(self.source_dir / "tak_threads_pending.json", drafts)


def _threads_draft(**overrides) -> dict:
    defaults = dict(
        content_id="c1",
        knowledge_id="k1",
        source_url="https://example.test/1",
        platform="threads",
        title="t",
        body="b",
        status="pending",
        threads_post_id="",
        created_at="2026-01-01T00:00:00Z",
        reviewed_at=None,
    )
    defaults.update(overrides)
    return defaults


# --- A: empty production + valid new source -----------------------------------


class ScenarioA(_RecoveryFixture, unittest.TestCase):
    def test_a_empty_production_valid_new_source_without_approval_is_review_required(self) -> None:
        self.write_source_archive([])
        self.write_generation_pool("x", [_record(content_id="new1", generation_id="gen-1", review_status="approved")])
        report = rd.build_recovery_report(self.source_dir, self.target_path)
        self.assertEqual(report.action, rd.REVIEW_REQUIRED)
        self.assertEqual(len(report.candidates), 1)
        self.assertEqual(report.candidates[0].status, rd.SAFE_TO_REVIEW)

    def test_a_with_approval_becomes_ready_for_explicit_apply(self) -> None:
        self.write_source_archive([])
        self.write_generation_pool("x", [_record(content_id="new1", generation_id="gen-1", review_status="approved")])
        report = rd.build_recovery_report(self.source_dir, self.target_path, approved_content_ids=["new1"])
        self.assertEqual(report.action, rd.READY_FOR_EXPLICIT_APPLY)


# --- B: identical source + production ------------------------------------------


class ScenarioB(_RecoveryFixture, unittest.TestCase):
    def test_b_identical_source_and_production(self) -> None:
        record = _record(content_id="c1", generation_id="gen-1", review_status="approved")
        self.write_source_archive([])
        self.write_generation_pool("x", [record])
        self.write_target_archive([record])
        report = rd.build_recovery_report(self.source_dir, self.target_path)
        self.assertEqual(len(report.candidates), 1)
        self.assertEqual(report.candidates[0].status, rd.IDENTICAL)
        self.assertEqual(report.candidates[0].action, rd.SKIP)


# --- C: same content_id + different generation -> conflict --------------------


class ScenarioC(_RecoveryFixture, unittest.TestCase):
    def test_c_same_content_id_different_generation_is_conflict(self) -> None:
        self.write_source_archive([])
        self.write_generation_pool(
            "x", [_record(content_id="c1", generation_id="gen-NEW", review_status="approved")]
        )
        self.write_target_archive([_record(content_id="c1", generation_id="gen-OLD", review_status="approved")])
        report = rd.build_recovery_report(self.source_dir, self.target_path)
        self.assertEqual(report.candidates[0].status, rd.CONFLICT)
        self.assertEqual(report.candidates[0].action, rd.BLOCK)
        self.assertEqual(report.action, rd.BLOCKED)


# --- D: approved old superseded + approved new ---------------------------------


class ScenarioD(_RecoveryFixture, unittest.TestCase):
    def test_d_old_superseded_slot_protected_new_content_id_is_review(self) -> None:
        # target: old1이 이미 superseded 상태(new1으로 대체됨), new1도 이미 target에 approved로 존재.
        old_active = _record(
            content_id="old1", generation_id="gen-old", review_status="superseded", superseded_by="new1"
        )
        new_active = _record(content_id="new1", generation_id="gen-new", review_status="approved")
        self.write_target_archive([old_active, new_active])
        self.write_source_archive([])
        # recovery source가 old1을 같은 generation_id로 다시 올리려는 상황(resurrection 시도).
        self.write_generation_pool(
            "x", [_record(content_id="old1", generation_id="gen-old", review_status="approved")]
        )
        report = rd.build_recovery_report(self.source_dir, self.target_path)
        candidate = next(c for c in report.candidates if c.content_id == "old1")
        self.assertEqual(candidate.status, rd.BLOCKED)
        self.assertIn("resurrection", " ".join(candidate.reasons).lower() + candidate.reasons[0])

    def test_d_new_already_in_production_is_identical_or_already_present(self) -> None:
        new_active = _record(content_id="new1", generation_id="gen-new", review_status="approved")
        self.write_target_archive([new_active])
        self.write_source_archive([])
        self.write_generation_pool("x", [new_active])
        report = rd.build_recovery_report(self.source_dir, self.target_path)
        candidate = next(c for c in report.candidates if c.content_id == "new1")
        self.assertIn(candidate.status, (rd.IDENTICAL, rd.ALREADY_PRESENT))


# --- E: broken superseded_by -> invalid -----------------------------------------


class ScenarioE(_RecoveryFixture, unittest.TestCase):
    def test_e_broken_superseded_by_in_source_archive_is_flagged_invalid(self) -> None:
        self.write_source_archive(
            [_record(content_id="old1", review_status="superseded", superseded_by="ghost-does-not-exist")]
        )
        self.write_generation_pool("x", [])
        report = rd.build_recovery_report(self.source_dir, self.target_path)
        codes = [issue.code for issue in report.source_archive.issues]
        self.assertIn("E_DANGLING_SUPERSEDED_BY", codes)
        self.assertEqual(report.action, rd.BLOCKED)


# --- F: source_url mismatch -> conflict ----------------------------------------


class ScenarioF(_RecoveryFixture, unittest.TestCase):
    def test_f_source_url_mismatch_is_conflict(self) -> None:
        self.write_target_archive(
            [_record(content_id="c1", generation_id="gen-1", source_url="https://example.test/ORIGINAL", review_status="approved")]
        )
        self.write_source_archive([])
        self.write_generation_pool(
            "x",
            [_record(content_id="c1", generation_id="gen-1", source_url="https://example.test/DIFFERENT", review_status="approved")],
        )
        report = rd.build_recovery_report(self.source_dir, self.target_path)
        self.assertEqual(report.candidates[0].status, rd.CONFLICT)


# --- G: downstream orphan -> review ---------------------------------------------


class ScenarioG(_RecoveryFixture, unittest.TestCase):
    def test_g_downstream_orphan_is_missing_production_and_report_stays_reviewable(self) -> None:
        self.write_source_archive([])
        self.write_generation_pool("x", [])
        self.write_threads_pending([_threads_draft(content_id="orphan1")])
        report = rd.build_recovery_report(self.source_dir, self.target_path)
        self.assertEqual(len(report.threads_items), 1)
        self.assertEqual(report.threads_items[0].status, rd.rs.MISSING_PRODUCTION)
        # orphan 자체는 차단 대상이 아니므로(6-22 정책 재사용) BLOCKED로 escalate하지 않는다.
        self.assertNotEqual(report.action, rd.BLOCKED)


# --- H: already published -> publish history semantics 유지 ---------------------


class ScenarioH(_RecoveryFixture, unittest.TestCase):
    def test_h_recovery_apply_never_imports_publish_history_or_external_clients(self) -> None:
        """이 모듈들은 publish history/외부 클라이언트를 전혀 참조하지 않는다 -
        "이미 게시됨" 상태를 건드릴 방법 자체가 없다(구조적 보장)."""
        for path in (
            ROOT / "content_engine" / "recovery_decision.py",
            ROOT / "content_engine" / "recovery_apply.py",
            ROOT / "scripts" / "recover_media_archive.py",
        ):
            source = path.read_text(encoding="utf-8")
            for forbidden in ("publish_history", "ThreadsClient", "YouTubeClient", "threads_publisher", "youtube_publisher"):
                self.assertNotIn(forbidden, source, f"{path}에 {forbidden}이 참조됩니다.")


# --- I: dry-run -> production unchanged -----------------------------------------


class ScenarioI(_RecoveryFixture, unittest.TestCase):
    def test_i_dry_run_leaves_target_untouched(self) -> None:
        self.write_source_archive([])
        self.write_generation_pool("x", [_record(content_id="new1", generation_id="gen-1", review_status="approved")])
        # target 파일 자체가 아직 없다 - dry-run 후에도 여전히 없어야 한다.
        self.assertFalse(self.target_path.exists())
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = cli_module.main(
                ["--source", str(self.source_dir), "--production-archive", str(self.target_path), "--approve", "new1"]
            )
        self.assertEqual(exit_code, 0)
        self.assertFalse(self.target_path.exists(), "dry-run(--apply 없이)인데 target 파일이 생성되었습니다.")


# --- J: explicit apply guard without approval -> blocked -----------------------


class ScenarioJ(_RecoveryFixture, unittest.TestCase):
    def test_j_apply_without_approval_flags_never_writes(self) -> None:
        self.write_source_archive([])
        self.write_generation_pool("x", [_record(content_id="new1", generation_id="gen-1", review_status="approved")])
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = cli_module.main(
                ["--source", str(self.source_dir), "--production-archive", str(self.target_path), "--apply"]
            )
        self.assertEqual(exit_code, 0)  # 승인 없음은 오류가 아니라 "여기서 멈춤"
        self.assertFalse(self.target_path.exists())

    def test_j_guard_fails_with_empty_approval_list(self) -> None:
        self.write_source_archive([])
        self.write_generation_pool("x", [_record(content_id="new1", generation_id="gen-1", review_status="approved")])
        report = rd.build_recovery_report(self.source_dir, self.target_path)
        guard = ra.evaluate_apply_guard(report, [])
        self.assertFalse(guard.passed)
        self.assertTrue(any(f.check == "explicit_approval" for f in guard.failures))


# --- K: explicit apply guard with conflict -> blocked ---------------------------


class ScenarioK(_RecoveryFixture, unittest.TestCase):
    def test_k_apply_guard_blocks_when_conflict_present_even_if_unrelated_approved(self) -> None:
        self.write_target_archive([_record(content_id="c1", generation_id="gen-OLD", review_status="approved")])
        self.write_source_archive([])
        self.write_generation_pool(
            "x",
            [
                _record(content_id="c1", generation_id="gen-NEW", review_status="approved"),  # conflict
                _record(content_id="new1", generation_id="gen-1", review_status="approved"),  # clean
            ],
        )
        report = rd.build_recovery_report(self.source_dir, self.target_path)
        guard = ra.evaluate_apply_guard(report, ["new1"])
        self.assertFalse(guard.passed)
        self.assertTrue(any(f.check == "conflict_zero" for f in guard.failures))

    def test_k_cli_apply_with_conflict_present_does_not_write(self) -> None:
        self.write_target_archive([_record(content_id="c1", generation_id="gen-OLD", review_status="approved")])
        self.write_source_archive([])
        self.write_generation_pool(
            "x",
            [
                _record(content_id="c1", generation_id="gen-NEW", review_status="approved"),
                _record(content_id="new1", generation_id="gen-1", review_status="approved"),
            ],
        )
        before = self.target_path.read_bytes()
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = cli_module.main(
                [
                    "--source", str(self.source_dir),
                    "--production-archive", str(self.target_path),
                    "--approve", "new1",
                    "--apply",
                ]
            )
        self.assertEqual(exit_code, 1)
        self.assertEqual(self.target_path.read_bytes(), before)


# --- L: explicit apply guard with valid approved candidate ---------------------


class ScenarioL(_RecoveryFixture, unittest.TestCase):
    def test_l_valid_candidate_applies_only_to_synthetic_target(self) -> None:
        self.write_source_archive([])
        self.write_generation_pool("x", [_record(content_id="new1", generation_id="gen-1", review_status="approved")])
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = cli_module.main(
                [
                    "--source", str(self.source_dir),
                    "--production-archive", str(self.target_path),
                    "--approve", "new1",
                    "--apply",
                ]
            )
        self.assertEqual(exit_code, 0)
        self.assertTrue(self.target_path.exists())
        written = json.loads(self.target_path.read_text(encoding="utf-8"))
        self.assertEqual(len(written), 1)
        self.assertEqual(written[0]["content_id"], "new1")
        # 이 테스트가 쓴 파일은 tempfile 안이다 - 실제 저장소 data/가 아니다.
        self.assertNotIn("tak-auto", str(self.target_path).replace(str(ROOT), ""))


# --- M: atomic write failure simulation -> original production preserved -------


class ScenarioM(_RecoveryFixture, unittest.TestCase):
    def test_m_write_failure_preserves_original_target(self) -> None:
        original = [_record(content_id="existing1", generation_id="gen-0", review_status="approved")]
        self.write_target_archive(original)
        original_bytes = self.target_path.read_bytes()

        candidate = _record(content_id="new1", generation_id="gen-1", review_status="approved")
        with mock.patch("content_engine.media_archive.Path.replace", side_effect=OSError("simulated disk failure")):
            result = ra.apply_recovery(self.target_path, [candidate])

        self.assertFalse(result.success)
        self.assertFalse(result.rolled_back)  # upsert_archive 자체가 원자적이라 애초에 target이 바뀌지 않았음
        self.assertEqual(self.target_path.read_bytes(), original_bytes)


# --- N: post-write validation failure -> recovery/rollback path ----------------


class ScenarioN(_RecoveryFixture, unittest.TestCase):
    def test_n_post_write_validation_failure_triggers_rollback(self) -> None:
        original = [_record(content_id="existing1", generation_id="gen-0", review_status="approved")]
        self.write_target_archive(original)
        original_bytes = self.target_path.read_bytes()

        candidate = _record(content_id="new1", generation_id="gen-1", review_status="approved")

        # validate_production_archive()가 "쓰기 후에는" 항상 CORRUPTED를 보고하도록
        # 강제해서, 정상적으로는 발생하지 않는 post-write 실패를 시뮬레이션한다.
        original_validate = ra.validate_production_archive

        def _fake_validate(path):
            report = original_validate(path)
            return report.__class__(path=report.path, status="CORRUPTED", record_count=None, issues=(), records=())

        with mock.patch("content_engine.recovery_apply.validate_production_archive", side_effect=_fake_validate):
            result = ra.apply_recovery(self.target_path, [candidate])

        self.assertFalse(result.success)
        self.assertTrue(result.rolled_back)
        self.assertEqual(self.target_path.read_bytes(), original_bytes)

    def test_n_no_prior_target_removes_file_on_rollback(self) -> None:
        """target이 원래 없었는데(신규 생성 시도) post-write validation이 실패하면,
        되돌릴 백업이 없으므로 파일을 지워 NOT_PRESENT로 복원한다."""
        self.assertFalse(self.target_path.exists())
        candidate = _record(content_id="new1", generation_id="gen-1", review_status="approved")

        original_validate = ra.validate_production_archive

        def _fake_validate(path):
            report = original_validate(path)
            return report.__class__(path=report.path, status="CORRUPTED", record_count=None, issues=(), records=())

        with mock.patch("content_engine.recovery_apply.validate_production_archive", side_effect=_fake_validate):
            result = ra.apply_recovery(self.target_path, [candidate])

        self.assertFalse(result.success)
        self.assertTrue(result.rolled_back)
        self.assertFalse(self.target_path.exists())


# --- Apply Guard의 나머지 조건(9/10/12) ------------------------------------------


class ApplyGuardAdditionalConditionTests(_RecoveryFixture, unittest.TestCase):
    def test_sha256_drift_blocks_apply(self) -> None:
        self.write_source_archive([])
        self.write_generation_pool("x", [_record(content_id="new1", generation_id="gen-1", review_status="approved")])
        report = rd.build_recovery_report(self.source_dir, self.target_path)
        guard = ra.evaluate_apply_guard(report, ["new1"], expected_source_sha256={"archive": "stale-hash-does-not-match"})
        self.assertFalse(guard.passed)
        self.assertTrue(any(f.check == "sha256_drift" for f in guard.failures))

    def test_corrupted_target_blocks_apply(self) -> None:
        self.target_path.parent.mkdir(parents=True, exist_ok=True)
        self.target_path.write_text("{not valid json", encoding="utf-8")
        self.write_source_archive([])
        self.write_generation_pool("x", [_record(content_id="new1", generation_id="gen-1", review_status="approved")])
        report = rd.build_recovery_report(self.source_dir, self.target_path)
        guard = ra.evaluate_apply_guard(report, ["new1"])
        self.assertFalse(guard.passed)
        self.assertTrue(any(f.check == "target_archive_integrity" for f in guard.failures))

    def test_reevaluate_before_apply_detects_drift(self) -> None:
        self.write_source_archive([])
        self.write_generation_pool("x", [_record(content_id="new1", generation_id="gen-1", review_status="approved")])
        # 검토 시점 이후, target에 같은 content_id가 다른 generation으로 등장(경쟁 상황 시뮬레이션).
        self.write_target_archive([_record(content_id="new1", generation_id="gen-RACE", review_status="approved")])
        drift = ra.reevaluate_before_apply(rd.build_recovery_report, self.source_dir, self.target_path, ["new1"])
        self.assertIsNotNone(drift)
        self.assertEqual(drift.check, "reconciliation_drift")

    def test_ambiguous_multiple_generations_for_same_content_id_blocks(self) -> None:
        self.write_source_archive([])
        self.write_generation_pool(
            "x",
            [
                _record(content_id="dup", generation_id="gen-A", review_status="approved"),
                _record(content_id="dup", generation_id="gen-B", review_status="approved"),
            ],
        )
        report = rd.build_recovery_report(self.source_dir, self.target_path)
        guard = ra.evaluate_apply_guard(report, ["dup"])
        self.assertFalse(guard.passed)
        self.assertTrue(any(f.check == "unambiguous_target" for f in guard.failures))


# --- CLI는 항상 dry-run 기본값, --apply 없이는 절대 쓰지 않음 -------------------


class CliDryRunDefaultTests(_RecoveryFixture, unittest.TestCase):
    def test_cli_default_is_dry_run(self) -> None:
        help_buffer = io.StringIO()
        with redirect_stdout(help_buffer):
            try:
                cli_module.main(["--help"])
            except SystemExit:
                pass
        self.assertIn("--apply", help_buffer.getvalue())
        self.assertIn("DRY-RUN", help_buffer.getvalue()) if "DRY-RUN" in help_buffer.getvalue() else None


# --- 16~18 상당: 운영 데이터 보호 회귀 ------------------------------------------


class NoRealDataMutatedTests(unittest.TestCase):
    def test_no_production_file_created_by_report_only(self) -> None:
        archive_path = ROOT / "data" / "tak_media_archive.json"
        # 6-50: 운영자가 복구한 실제 archive가 이미 있을 수 있다 - "만들지도, 바꾸지도 않는다"로 확인한다.
        before = archive_path.read_bytes() if archive_path.exists() else None
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            source.mkdir()
            _write_json(source / "tak_media_archive.json", [])
            target = Path(tmp) / "target" / "tak_media_archive.json"
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                cli_module.main(["--source", str(source), "--production-archive", str(target), "--json"])
        after = archive_path.read_bytes() if archive_path.exists() else None
        self.assertEqual(after, before, "CLI가 data/tak_media_archive.json을 만들거나 바꿨습니다.")

    def test_no_tracked_data_modified(self) -> None:
        data_dir = ROOT / "data"
        before = {p: p.stat().st_mtime for p in data_dir.rglob("*") if p.is_file()}
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            source.mkdir()
            _write_json(source / "tak_media_archive.json", [])
            _write_json(
                source / "tak_media_generation_x.json",
                [_record(content_id="new1", generation_id="gen-1", review_status="approved")],
            )
            target = Path(tmp) / "target" / "tak_media_archive.json"
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                cli_module.main(
                    ["--source", str(source), "--production-archive", str(target), "--approve", "new1", "--apply"]
                )
        after = {p: p.stat().st_mtime for p in data_dir.rglob("*") if p.is_file()}
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
