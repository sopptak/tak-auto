"""content_engine/recovery_staging.py + scripts/audit_recovery_source.py 테스트(6-22).

6-22 지시 13장이 요구하는 18개 최소 시나리오를 전부 다룬다. 모든 fixture는
``tempfile.TemporaryDirectory()``로 격리한다 - 실제 ``data/``는 마지막
``NoRealDataMutatedTests``에서 "바뀌지 않았는가"를 확인하는 용도로만, 그것도
읽기만 참조한다.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import replace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_engine import recovery_staging as rs
from content_engine.data_state import CORRUPTED, EMPTY, NOT_PRESENT, VALID
from content_engine.media_archive import MediaArchiveRecord
import scripts.audit_recovery_source as cli_module


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


def _write_archive(path: Path, records: list[dict] | list[MediaArchiveRecord]) -> None:
    payload = [r.to_dict() if isinstance(r, MediaArchiveRecord) else r for r in records]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


# --- 1~4: source missing / valid / empty / corrupted -------------------------


class SourceFileStatusTests(unittest.TestCase):
    def test_1_source_missing(self) -> None:
        """1. source missing"""
        with tempfile.TemporaryDirectory() as tmp:
            report = rs.validate_production_archive(Path(tmp) / "tak_media_archive.json")
            self.assertEqual(report.status, NOT_PRESENT)
            self.assertEqual(report.issues, ())

    def test_2_source_valid(self) -> None:
        """2. source valid"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tak_media_archive.json"
            _write_archive(path, [_record(content_id="c1", review_status="approved")])
            report = rs.validate_production_archive(path)
            self.assertEqual(report.status, VALID)
            self.assertEqual(report.record_count, 1)
            self.assertEqual(report.issues, ())

    def test_3_source_empty(self) -> None:
        """3. source empty"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tak_media_archive.json"
            path.write_text("[]", encoding="utf-8")
            report = rs.validate_production_archive(path)
            self.assertEqual(report.status, VALID)
            self.assertEqual(report.record_count, 0)

    def test_3b_zero_byte_file_is_empty_not_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tak_media_archive.json"
            path.write_text("", encoding="utf-8")
            report = rs.validate_production_archive(path)
            self.assertEqual(report.status, EMPTY)

    def test_4_source_corrupted(self) -> None:
        """4. source corrupted"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tak_media_archive.json"
            path.write_text("{not valid json", encoding="utf-8")
            report = rs.validate_production_archive(path)
            self.assertEqual(report.status, CORRUPTED)


# --- 5: duplicate content_id --------------------------------------------------


class DuplicateContentIdTests(unittest.TestCase):
    def test_5_duplicate_content_id(self) -> None:
        """5. duplicate content_id"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tak_media_archive.json"
            _write_archive(
                path,
                [
                    _record(content_id="dup", review_status="approved"),
                    _record(content_id="dup", review_status="approved"),
                ],
            )
            report = rs.validate_production_archive(path)
            codes = [issue.code for issue in report.issues]
            self.assertIn("A_DUPLICATE_CONTENT_ID", codes)


# --- 6: generation conflict ---------------------------------------------------


class GenerationConflictTests(unittest.TestCase):
    def test_6_generation_conflict(self) -> None:
        """6. generation conflict - production에 다른 generation_id로 이미
        존재하는 content_id를 generation pool이 다시 올리려는 경우(6-18
        check_promotion_conflict()를 그대로 재사용해서 판정)."""
        with tempfile.TemporaryDirectory() as tmp:
            archive_records = [_record(content_id="c1", generation_id="gen-old", review_status="approved")]
            pool_path = Path(tmp) / "tak_media_generation_x.json"
            _write_archive(
                pool_path,
                [_record(content_id="c1", generation_id="gen-new", review_status="approved")],
            )
            items, issues = rs.validate_generation_pool_file(pool_path, archive_records)
            self.assertEqual(issues, [])
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].comparison, "CONTENT_ID_CONFLICT")

    def test_generation_only_new_content_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pool_path = Path(tmp) / "tak_media_generation_x.json"
            _write_archive(pool_path, [_record(content_id="new1", generation_id="gen-1")])
            items, issues = rs.validate_generation_pool_file(pool_path, [])
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].comparison, "GENERATION_ONLY")

    def test_generation_already_promoted_is_production_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive_records = [_record(content_id="c1", generation_id="gen-1", review_status="approved")]
            pool_path = Path(tmp) / "tak_media_generation_x.json"
            _write_archive(pool_path, [_record(content_id="c1", generation_id="gen-1", review_status="approved")])
            items, issues = rs.validate_generation_pool_file(pool_path, archive_records)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].comparison, "PRODUCTION_MATCH")


# --- 7~8: superseded relationship valid / invalid -----------------------------


class SupersededRelationshipTests(unittest.TestCase):
    def test_7_superseded_relationship_valid(self) -> None:
        """7. superseded relationship valid - superseded_by가 실제로 존재하고
        knowledge_id/platform/source_url이 전부 일치한다."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tak_media_archive.json"
            old = _record(
                content_id="old1",
                knowledge_id="k1",
                platform="threads",
                source_url="https://example.test/x",
                review_status="superseded",
                superseded_by="new1",
            )
            new = _record(
                content_id="new1",
                knowledge_id="k1",
                platform="threads",
                source_url="https://example.test/x",
                review_status="approved",
            )
            _write_archive(path, [old, new])
            report = rs.validate_production_archive(path)
            codes = [issue.code for issue in report.issues]
            self.assertNotIn("E_DANGLING_SUPERSEDED_BY", codes)
            self.assertNotIn("J_SUPERSEDE_PAIR_MISMATCH", codes)

    def test_8_superseded_relationship_invalid_dangling(self) -> None:
        """8a. superseded relationship invalid - superseded_by 대상이 archive에 없음(E)."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tak_media_archive.json"
            _write_archive(
                path,
                [_record(content_id="old1", review_status="superseded", superseded_by="ghost")],
            )
            report = rs.validate_production_archive(path)
            codes = [issue.code for issue in report.issues]
            self.assertIn("E_DANGLING_SUPERSEDED_BY", codes)

    def test_8_superseded_relationship_invalid_field_mismatch(self) -> None:
        """8b. superseded relationship invalid - 대상은 존재하지만 platform/
        source_url/knowledge_id가 다름(J)."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tak_media_archive.json"
            old = _record(
                content_id="old1",
                platform="threads",
                source_url="https://example.test/x",
                review_status="superseded",
                superseded_by="new1",
            )
            new = _record(
                content_id="new1",
                platform="blog",  # platform 불일치
                source_url="https://example.test/y",  # source_url도 불일치
                review_status="approved",
            )
            _write_archive(path, [old, new])
            report = rs.validate_production_archive(path)
            codes = [issue.code for issue in report.issues]
            self.assertIn("J_SUPERSEDE_PAIR_MISMATCH", codes)


# --- 9: source_url mismatch ---------------------------------------------------


class SourceUrlMismatchTests(unittest.TestCase):
    def test_9_source_url_mismatch(self) -> None:
        """9. source_url mismatch - threads pending draft의 source_url이
        production archive 레코드와 다르면 MISMATCH로 표시(자동 병합하지 않음)."""
        with tempfile.TemporaryDirectory() as tmp:
            threads_path = Path(tmp) / "tak_threads_pending.json"
            threads_path.write_text(
                json.dumps(
                    [
                        {
                            "content_id": "c1",
                            "knowledge_id": "k1",
                            "source_url": "https://example.test/DIFFERENT",
                            "platform": "threads",
                            "title": "t",
                            "body": "b",
                            "status": "pending",
                            "threads_post_id": "",
                            "created_at": "2026-01-01T00:00:00Z",
                            "reviewed_at": None,
                        }
                    ]
                ),
                encoding="utf-8",
            )
            archive_records = [
                _record(content_id="c1", platform="threads", source_url="https://example.test/original", review_status="approved")
            ]
            items = rs.reconcile_threads_pending(threads_path, archive_records)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].field_consistency, rs.MISMATCH)
            self.assertEqual(items[0].status, rs.APPROVED)


# --- 10~12: downstream orphan / superseded / approved -------------------------


class DownstreamReconciliationTests(unittest.TestCase):
    def test_10_downstream_orphan_is_missing_production(self) -> None:
        """10. downstream orphan - production archive에 해당 content_id가 없음.
        기존 orphan 정책(content_engine.publish_eligibility)과 마찬가지로 차단
        대상이 아니라 MISSING_PRODUCTION으로만 표시한다."""
        with tempfile.TemporaryDirectory() as tmp:
            shorts_dir = Path(tmp) / "shorts_scripts"
            shorts_dir.mkdir()
            (shorts_dir / "orphan1.json").write_text(
                json.dumps({"content_id": "orphan1", "knowledge_id": "k1"}), encoding="utf-8"
            )
            items = rs.reconcile_shorts_scripts(shorts_dir, [])
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].status, rs.MISSING_PRODUCTION)

    def test_11_downstream_superseded(self) -> None:
        """11. downstream superseded"""
        with tempfile.TemporaryDirectory() as tmp:
            shorts_dir = Path(tmp) / "shorts_scripts"
            shorts_dir.mkdir()
            (shorts_dir / "c1.json").write_text(json.dumps({"content_id": "c1"}), encoding="utf-8")
            archive_records = [
                _record(content_id="c1", platform="shorts", review_status="superseded", superseded_by="c2")
            ]
            items = rs.reconcile_shorts_scripts(shorts_dir, archive_records)
            self.assertEqual(items[0].status, rs.SUPERSEDED)

    def test_12_downstream_approved(self) -> None:
        """12. approved downstream"""
        with tempfile.TemporaryDirectory() as tmp:
            shorts_dir = Path(tmp) / "shorts_scripts"
            shorts_dir.mkdir()
            (shorts_dir / "c1.json").write_text(json.dumps({"content_id": "c1"}), encoding="utf-8")
            archive_records = [_record(content_id="c1", platform="shorts", review_status="approved")]
            items = rs.reconcile_shorts_scripts(shorts_dir, archive_records)
            self.assertEqual(items[0].status, rs.APPROVED)
            self.assertEqual(items[0].field_consistency, rs.MATCH)


# --- 13: new content -----------------------------------------------------------


class NewContentTests(unittest.TestCase):
    def test_13_new_content_is_generation_only(self) -> None:
        """13. new content - generation pool에만 있고 production에는 전혀
        없는 완전히 새로운 콘텐츠."""
        with tempfile.TemporaryDirectory() as tmp:
            pool_path = Path(tmp) / "tak_media_generation_x.json"
            _write_archive(pool_path, [_record(content_id="brand-new", generation_id="gen-1")])
            items, issues = rs.validate_generation_pool_file(pool_path, [])
            self.assertEqual(issues, [])
            self.assertEqual(items[0].comparison, "GENERATION_ONLY")


# --- 14~15: overwrite block / idempotency (재사용 - 6-18 자체 회귀는 이미
# tests/test_same_content_id_overwrite_protection.py가 검증한다. 여기서는
# Recovery Staging이 "같은 정책을 그대로 재사용해 판정하는지"만 확인한다) --


class OverwriteBlockAndIdempotencyTests(unittest.TestCase):
    def test_14_same_content_id_different_generation_blocks(self) -> None:
        """14. same content_id overwrite block"""
        archive_records = [_record(content_id="c1", generation_id="gen-A", review_status="approved")]
        with tempfile.TemporaryDirectory() as tmp:
            pool_path = Path(tmp) / "tak_media_generation_x.json"
            _write_archive(pool_path, [_record(content_id="c1", generation_id="gen-B", review_status="approved")])
            items, _ = rs.validate_generation_pool_file(pool_path, archive_records)
            self.assertEqual(items[0].comparison, "CONTENT_ID_CONFLICT")

    def test_15_identical_content_id_and_generation_is_idempotent(self) -> None:
        """15. identical content_id + same generation idempotency"""
        archive_records = [_record(content_id="c1", generation_id="gen-A", review_status="approved")]
        with tempfile.TemporaryDirectory() as tmp:
            pool_path = Path(tmp) / "tak_media_generation_x.json"
            _write_archive(pool_path, [_record(content_id="c1", generation_id="gen-A", review_status="approved")])
            items, _ = rs.validate_generation_pool_file(pool_path, archive_records)
            self.assertEqual(items[0].comparison, "PRODUCTION_MATCH")


# --- G/I: approved 필수 필드 누락 / generation pool 내부 중복 -----------------


class AdditionalArchiveIssueTests(unittest.TestCase):
    def test_approved_missing_source_url_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tak_media_archive.json"
            _write_archive(path, [_record(content_id="c1", review_status="approved", source_url="")])
            report = rs.validate_production_archive(path)
            codes = [issue.code for issue in report.issues]
            self.assertIn("G_APPROVED_MISSING_REQUIRED_FIELD", codes)

    def test_generation_pool_internal_duplicate_pair_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pool_path = Path(tmp) / "tak_media_generation_x.json"
            raw = [
                _record(content_id="c1", generation_id="gen-1").to_dict(),
                _record(content_id="c1", generation_id="gen-1").to_dict(),
            ]
            pool_path.write_text(json.dumps(raw), encoding="utf-8")
            items, issues = rs.validate_generation_pool_file(pool_path, [])
            codes = [issue.code for issue in issues]
            self.assertIn("I_DUPLICATE_CONTENT_GENERATION_PAIR", codes)


# --- 16~18: 운영 데이터 보호 회귀 ----------------------------------------------


class NoRealDataMutatedTests(unittest.TestCase):
    def test_16_no_production_file_created(self) -> None:
        """16. no production file created - CLI를 실행해도 data/tak_media_archive.json이
        생기지 않는다."""
        archive_path = ROOT / "data" / "tak_media_archive.json"
        with tempfile.TemporaryDirectory() as tmp:
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                cli_module.main(["--source", tmp, "--json"])
        self.assertFalse(archive_path.exists(), "audit_recovery_source.py가 data/tak_media_archive.json을 생성했습니다.")

    def test_17_no_tracked_data_modified(self) -> None:
        """17. no tracked data modified - 전체 data/ 디렉터리 파일 목록이 실행 전후로 동일하다."""
        data_dir = ROOT / "data"
        before = {p: p.stat().st_mtime for p in data_dir.rglob("*") if p.is_file()}
        with tempfile.TemporaryDirectory() as tmp:
            _write_archive(Path(tmp) / "tak_media_archive.json", [_record(content_id="c1", review_status="approved")])
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                cli_module.main(["--source", tmp, "--verbose"])
        after = {p: p.stat().st_mtime for p in data_dir.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_18_no_external_api_called(self) -> None:
        """18. no external API called - recovery_staging/audit_recovery_source
        모듈은 threads/youtube/naver 클라이언트를 전혀 import하지 않는다(정적
        검사 - 모듈 소스에 관련 클래스/모듈명이 없는지 확인)."""
        recovery_source = Path(ROOT / "content_engine" / "recovery_staging.py").read_text(encoding="utf-8")
        cli_source = Path(ROOT / "scripts" / "audit_recovery_source.py").read_text(encoding="utf-8")
        forbidden = ["ThreadsClient", "YouTubeClient", "threads_publisher", "youtube_publisher", "requests.post", "requests.get"]
        for needle in forbidden:
            self.assertNotIn(needle, recovery_source)
            self.assertNotIn(needle, cli_source)


# --- report/action 집계 ---------------------------------------------------


class ReportBuildingTests(unittest.TestCase):
    def test_no_source_archive_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = rs.build_reconciliation_report(tmp)
            self.assertEqual(report.action, "NO_SOURCE_ARCHIVE")
            self.assertEqual(report.conflicts, 0)

    def test_corrupted_archive_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "tak_media_archive.json").write_text("{not json", encoding="utf-8")
            report = rs.build_reconciliation_report(tmp)
            self.assertEqual(report.action, "BLOCKED")

    def test_clean_archive_with_no_downstream_is_ok(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _write_archive(Path(tmp) / "tak_media_archive.json", [_record(content_id="c1", review_status="approved")])
            report = rs.build_reconciliation_report(tmp)
            self.assertEqual(report.conflicts, 0)
            self.assertEqual(report.warnings, 0)
            self.assertEqual(report.action, "OK")

    def test_render_report_text_contains_expected_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _write_archive(Path(tmp) / "tak_media_archive.json", [_record(content_id="c1", review_status="approved")])
            report = rs.build_reconciliation_report(tmp)
            text = rs.render_report_text(report)
            for label in ("RECOVERY RECONCILIATION", "Source:", "Archive:", "Conflicts:", "Warnings:", "Action:"):
                self.assertIn(label, text)


class CliDoesNotHaveApplyOptionTests(unittest.TestCase):
    def test_cli_has_no_apply_flag(self) -> None:
        """6-22 지시 12장: --apply 같은 실제 반영 옵션은 이번 범위에서 구현하지 않는다.
        (help 문구 자체가 "--apply 없음"이라고 설명하므로 텍스트 검색 대신
        --help 출력에서 "옵션 나열 줄"만 골라 실제 등록된 옵션 문자열을
        확인한다 - 설명 문단(예: "--apply 없음")은 제외한다.)"""
        help_buffer = io.StringIO()
        with redirect_stdout(help_buffer):
            try:
                cli_module.main(["--help"])
            except SystemExit:
                pass
        option_lines = [
            line for line in help_buffer.getvalue().splitlines() if line.strip().startswith("--")
        ]
        for line in option_lines:
            self.assertFalse(line.strip().startswith("--apply"))


if __name__ == "__main__":
    unittest.main()
