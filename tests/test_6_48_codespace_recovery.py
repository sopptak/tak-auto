"""6-48 Codespace Export 운영 데이터 복구 준비 검증.

- export 스키마(superseded_by 필드 없음)를 현재 코드가 그대로 읽는다(COMPATIBLE)
- approved Shorts 판정: valid+approved+not superseded+shorts만
- 복구는 기존 recover_media_archive.py(Report -> Approval -> Apply)로만:
  승인 없으면 아무것도 안 씀, 승인한 content_id만 원본과 같은 내용으로 추가,
  재실행 시 IDENTICAL(중복 추가 없음), 다른 generation이면 CONFLICT(적용 안 함)
- 네트워크 없음(소켓 차단)
- (로컬에 export commit이 있으면) 실제 export 데이터로 위 조건 재확인
"""

from __future__ import annotations

import contextlib
import io
import json
import socket
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from content_engine.media_archive import load_archive
from content_engine.shorts_script import ShortsScript
import scripts.recover_media_archive as recover_cli

ROOT = Path(__file__).resolve().parents[1]
EXPORT_COMMIT = "0547065b4f9b65ada8af6a3c33cc636d97b43345"  # codespace-silver-robot-xrr69q9r4r7j3pwq9
EXPECTED_APPROVED_SHORTS = {
    "content-91869ed8be17f3f3", "content-3ae2d78568210164", "content-e3b8d986ea6db98e",
    "content-e787c9201b94a948", "content-ec0c38b9a20c424c",
}


def _legacy(content_id: str, **overrides) -> dict:
    """6-17 이전 export 형태(superseded_by 키 없음)."""
    record = {
        "content_id": content_id, "knowledge_id": "k1", "platform": "shorts", "generation_status": "valid",
        "original_title": "t", "original_body": "b", "rewritten_title": "rt", "rewritten_body": "rb",
        "source_url": "https://example.test", "evidence": [], "evidence_unit_ids": [], "created_at": "2026-09-20T00:00:00Z",
        "validation_errors": [], "error_message": None, "review_status": "approved", "edited_title": None,
        "edited_body": None, "generation_id": "gen-1",
    }
    record.update(overrides)
    return record


def _approved_shorts(records) -> set[str]:
    return {r.content_id for r in records if r.platform == "shorts" and r.generation_status == "valid"
            and r.review_status == "approved" and not r.superseded_by}


class _NoNetwork(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch.object(socket.socket, "connect", side_effect=AssertionError("network"))
        patcher.start()
        self.addCleanup(patcher.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.source = self.tmp / "staging"
        self.source.mkdir()
        self.prod = self.tmp / "prod" / "tak_media_archive.json"

    def _stage(self, records: list[dict]) -> None:
        payload = json.dumps(records, ensure_ascii=False, indent=2)
        (self.source / "tak_media_archive.json").write_text(payload, encoding="utf-8")
        # recover_media_archive.py는 generation pool 이름 규칙의 파일을 후보로 읽는다 - 같은 내용의 사본
        (self.source / "tak_media_generation_codespace_export.json").write_text(payload, encoding="utf-8")

    def _recover(self, *extra: str) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = recover_cli.main(["--source", str(self.source), "--production-archive", str(self.prod), *extra])
        return code, out.getvalue()


class SchemaAndDetectionTests(_NoNetwork):
    def test_legacy_export_schema_is_readable_without_migration(self) -> None:
        self._stage([_legacy("c1")])
        record = load_archive(self.source / "tak_media_archive.json")[0]
        self.assertIsNone(record.superseded_by)
        self.assertEqual((record.review_status, record.generation_id), ("approved", "gen-1"))

    def test_approved_shorts_detection_excludes_superseded_invalid_and_others(self) -> None:
        self._stage([
            _legacy("ok"),
            _legacy("rejected", generation_status="rejected", review_status="unreviewed", validation_errors=["x"]),
            _legacy("old", review_status="superseded", superseded_by="ok"),
            _legacy("thread", platform="threads"),
        ])
        self.assertEqual(_approved_shorts(load_archive(self.source / "tak_media_archive.json")), {"ok"})


class RecoveryFlowTests(_NoNetwork):
    def test_no_approval_writes_nothing(self) -> None:
        self._stage([_legacy("c1"), _legacy("c2")])
        code, out = self._recover()
        self.assertIn("NEW: 2", out)
        self.assertIn("Apply는 실행되지 않았습니다", out)
        self.assertFalse(self.prod.exists())

    def test_apply_without_flag_is_dry_run(self) -> None:
        self._stage([_legacy("c1")])
        self._recover("--approve", "c1")
        self.assertFalse(self.prod.exists())

    def test_only_approved_content_is_added_unchanged_and_rerun_is_identical(self) -> None:
        self._stage([_legacy("c1"), _legacy("c2")])
        code, out = self._recover("--approve", "c1", "--apply")
        self.assertEqual(code, 0, out)
        written = json.loads(self.prod.read_text(encoding="utf-8"))
        self.assertEqual([r["content_id"] for r in written], ["c1"])
        source = _legacy("c1")
        self.assertEqual({k: v for k, v in written[0].items() if k != "superseded_by"}, source)
        self.assertIsNone(written[0]["superseded_by"])
        before = self.prod.read_bytes()
        code, out = self._recover("--approve", "c1", "--apply")  # 같은 승인 재실행 - 중복 추가 없음
        self.assertIn("IDENTICAL: 1", out)
        self.assertEqual(len(json.loads(self.prod.read_text(encoding="utf-8"))), 1)
        self.assertEqual(self.prod.read_bytes(), before)

    def test_same_content_id_different_generation_is_conflict_and_not_applied(self) -> None:
        self.prod.parent.mkdir(parents=True)
        self.prod.write_text(json.dumps([_legacy("c1", generation_id="gen-OTHER", superseded_by=None)], ensure_ascii=False), encoding="utf-8")
        before = self.prod.read_bytes()
        self._stage([_legacy("c1")])
        code, out = self._recover("--approve", "c1", "--apply")
        self.assertIn("CONFLICT: 1", out)
        self.assertEqual(self.prod.read_bytes(), before)


def _export_available() -> bool:
    try:
        return subprocess.run(["git", "cat-file", "-e", f"{EXPORT_COMMIT}:data/tak_media_archive.json"],
                              cwd=ROOT, capture_output=True).returncode == 0
    except OSError:
        return False


@unittest.skipUnless(_export_available(), "Codespace export commit이 로컬 git에 없습니다(git fetch origin <branch> 필요).")
class RealExportDataTests(unittest.TestCase):
    @staticmethod
    def _blob(path: str) -> bytes:
        return subprocess.run(["git", "show", f"{EXPORT_COMMIT}:{path}"], cwd=ROOT, capture_output=True, check=True).stdout

    def test_real_export_is_compatible_and_has_five_approved_shorts_with_scripts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "tak_media_archive.json"
            archive.write_bytes(self._blob("data/tak_media_archive.json"))
            records = load_archive(archive)
        self.assertEqual(len(records), 18)
        self.assertEqual(len({r.content_id for r in records}), 18)
        approved = _approved_shorts(records)
        self.assertEqual(approved, EXPECTED_APPROVED_SHORTS)
        by_id = {r.content_id: r for r in records}
        for content_id in approved:
            script = json.loads(self._blob(f"data/shorts_scripts/{content_id}.json").decode("utf-8"))
            self.assertEqual((script["content_id"], script["knowledge_id"]), (content_id, by_id[content_id].knowledge_id))
            ShortsScript.from_dict(script)  # 현재 렌더러 입력 스키마로 읽힌다


if __name__ == "__main__":
    unittest.main()
