"""scripts/audit_data_state.py의 상태 판정 로직 테스트(6-21).

이 스크립트는 읽기 전용이어야 하므로, 핵심 검증 포인트는 두 가지다.
    1. NOT_PRESENT/EMPTY/VALID/CORRUPTED 네 가지 상태를 실제로 구분하는가
       (특히 "파일이 없음"과 "파일은 있지만 비어 있음"을 혼동하지 않는가).
    2. 실행해도 실제 저장소(data/ 등)에 어떤 파일도 새로 생성/수정하지 않는가.

파일 시스템 상태 판정 함수는 순수 함수이므로 전부 tempfile로 격리해서
테스트한다 - 실제 data/ 디렉터리는 오직 "실행 후 변화가 없는지" 확인하는
회귀 테스트 1건에서만, 그것도 읽기만 하는 용도로 참조한다.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.audit_data_state as audit_module


class JsonFileStatusTests(unittest.TestCase):
    def test_missing_file_is_not_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "does_not_exist.json"
            status, count = audit_module._json_file_status(path)
            self.assertEqual(status, audit_module.NOT_PRESENT)
            self.assertIsNone(count)

    def test_zero_byte_file_is_empty_not_not_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.json"
            path.write_text("", encoding="utf-8")
            status, count = audit_module._json_file_status(path)
            self.assertEqual(status, audit_module.EMPTY)
            self.assertIsNone(count)

    def test_whitespace_only_file_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "whitespace.json"
            path.write_text("   \n\t  ", encoding="utf-8")
            status, _ = audit_module._json_file_status(path)
            self.assertEqual(status, audit_module.EMPTY)

    def test_valid_json_list_reports_record_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "valid.json"
            path.write_text(json.dumps([{"a": 1}, {"a": 2}, {"a": 3}]), encoding="utf-8")
            status, count = audit_module._json_file_status(path)
            self.assertEqual(status, audit_module.VALID)
            self.assertEqual(count, 3)

    def test_valid_json_empty_list_is_valid_with_zero_records(self) -> None:
        """빈 JSON 배열(``[]``)은 EMPTY가 아니라 VALID/0건이다 - "파일이 없음"과
        "파일은 있고 유효한 JSON이지만 레코드가 0건"은 서로 다른 상태다."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty_list.json"
            path.write_text("[]", encoding="utf-8")
            status, count = audit_module._json_file_status(path)
            self.assertEqual(status, audit_module.VALID)
            self.assertEqual(count, 0)

    def test_malformed_json_is_corrupted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken.json"
            path.write_text("{not valid json", encoding="utf-8")
            status, count = audit_module._json_file_status(path)
            self.assertEqual(status, audit_module.CORRUPTED)
            self.assertIsNone(count)


class DirStatusTests(unittest.TestCase):
    def test_missing_dir_is_not_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nope"
            status, count = audit_module._dir_status(path, "*")
            self.assertEqual(status, audit_module.NOT_PRESENT)
            self.assertIsNone(count)

    def test_existing_empty_dir_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty_dir"
            path.mkdir()
            status, count = audit_module._dir_status(path, "*")
            self.assertEqual(status, audit_module.EMPTY)
            self.assertEqual(count, 0)

    def test_dir_with_matching_files_is_valid_with_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "populated"
            path.mkdir()
            (path / "a.json").write_text("{}", encoding="utf-8")
            (path / "b.json").write_text("{}", encoding="utf-8")
            (path / "c.txt").write_text("ignored by glob", encoding="utf-8")
            status, count = audit_module._dir_status(path, "*.json")
            self.assertEqual(status, audit_module.VALID)
            self.assertEqual(count, 2)


class MainDoesNotMutateRepositoryTests(unittest.TestCase):
    """스크립트를 실제로 실행해도 저장소에 어떤 파일도 새로 생기지 않는지 확인한다."""

    def test_json_mode_produces_parseable_output_and_no_new_files(self) -> None:
        data_dir = ROOT / "data"
        before = set(p for p in data_dir.rglob("*") if p.is_file())

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = audit_module.main(["--json"])

        after = set(p for p in data_dir.rglob("*") if p.is_file())

        self.assertEqual(exit_code, 0)
        self.assertEqual(before, after, "audit_data_state.py가 data/ 아래 파일을 생성/삭제했습니다.")

        rows = json.loads(buffer.getvalue())
        self.assertIsInstance(rows, list)
        self.assertTrue(rows)
        for row in rows:
            self.assertIn("status", row)
            self.assertIn(
                row["status"],
                {audit_module.NOT_PRESENT, audit_module.EMPTY, audit_module.VALID, audit_module.CORRUPTED},
            )

    def test_production_archive_row_reports_not_present_when_absent(self) -> None:
        """이 테스트 환경(노트북2, 새 clone)에는 Production Archive가 없어야
        정상이다. 있다면(다른 이유로 이미 생성돼 있다면) 상태만 확인하고
        내용은 건드리지 않는다."""
        archive_path = ROOT / "data" / "tak_media_archive.json"
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            audit_module.main(["--json"])
        rows = json.loads(buffer.getvalue())
        archive_row = next(r for r in rows if r["path"] == "data/tak_media_archive.json")
        if archive_path.exists():
            self.assertNotEqual(archive_row["status"], audit_module.NOT_PRESENT)
        else:
            self.assertEqual(archive_row["status"], audit_module.NOT_PRESENT)


if __name__ == "__main__":
    unittest.main()
