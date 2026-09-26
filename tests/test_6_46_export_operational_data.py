"""scripts/export_operational_data.py(6-46) 검증 - 임시 source root만 사용, 네트워크 차단."""

from __future__ import annotations

import hashlib
import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from content_engine.media_archive import MediaArchiveRecord, save_archive
import scripts.export_operational_data as export


def _record(content_id: str, **overrides) -> MediaArchiveRecord:
    defaults = dict(
        content_id=content_id, knowledge_id="k1", platform="shorts", generation_status="valid",
        original_title="t", original_body="b", rewritten_title=None, rewritten_body=None,
        source_url="https://example.test", evidence=(), evidence_unit_ids=(), created_at="2026-09-26T00:00:00Z",
        review_status="approved", generation_id=f"gen-{content_id}",
    )
    defaults.update(overrides)
    return MediaArchiveRecord(**defaults)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ExportTests(unittest.TestCase):
    def setUp(self) -> None:
        # 이 모듈은 네트워크를 쓰면 안 된다 - 어떤 소켓 연결도 실패하게 만든다
        patcher = mock.patch.object(socket.socket, "connect", side_effect=AssertionError("network"))
        patcher.start()
        self.addCleanup(patcher.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "src"
        self.out = Path(tmp.name) / "package"
        data = self.root / "data"
        (data / "shorts_scripts").mkdir(parents=True)
        (data / "shorts").mkdir()
        save_archive([
            _record("ok"),
            _record("old", review_status="superseded", superseded_by="ok"),
            _record("bad", generation_status="rejected"),
            _record("wait", review_status="unreviewed"),
            _record("blog", platform="blog"),
        ], data / "tak_media_archive.json")
        save_archive([_record("pool1", review_status="approved", generation_id="gen-pool")], data / "tak_media_generation_20260926.json")
        (data / "shorts_scripts" / "ok.json").write_text(json.dumps({"content_id": "ok"}), encoding="utf-8")
        (data / "shorts" / "ok.mp4").write_bytes(b"mp4")
        (data / "youtube_publish_log.json").write_text(json.dumps([{"video_id": "v1", "content_id": "ok"}]), encoding="utf-8")
        (data / "tak_brain_knowledge.json").write_text("[]", encoding="utf-8")
        (data / "tak_threads_pending.json").write_text("{broken", encoding="utf-8")
        # 자격증명류 - 절대 package에 들어가면 안 된다
        (self.root / ".env").write_text("TAK_MEDIA_LLM_API_KEY=placeholder-not-real", encoding="utf-8")
        (data / "client_secret_x.json").write_text("{}", encoding="utf-8")
        (data / "token.json").write_text("{}", encoding="utf-8")
        self.before = {p: _sha(p) for p in self.root.rglob("*") if p.is_file()}

    def test_manifest_hashes_and_package_copies_match_source(self) -> None:
        manifest = export.build_package(self.root, self.out)
        rows = {r["path"]: r for r in manifest["files"]}
        archive = rows["data/tak_media_archive.json"]
        source = self.root / "data/tak_media_archive.json"
        self.assertEqual((archive["status"], archive["size"], archive["sha256_source"]), ("VALID", source.stat().st_size, _sha(source)))
        self.assertEqual(archive["sha256_package"], _sha(self.out / "data/tak_media_archive.json"))
        self.assertIn("data/shorts_scripts/ok.json", rows)
        self.assertIn("data/shorts/ok.mp4", rows)
        self.assertIn("data/tak_media_generation_20260926.json", rows)
        self.assertEqual(rows["data/tak_threads_pending.json"]["status"], "CORRUPTED")  # 숨기지 않고 표시
        self.assertEqual(rows["data/blog_publish_log.json"]["status"], "NOT_PRESENT")
        self.assertTrue((self.out / "export_manifest.json").exists())

    def test_credentials_are_excluded_and_listed(self) -> None:
        manifest = export.build_package(self.root, self.out)
        self.assertEqual(set(manifest["excluded_credential_files"]), {".env", "data/client_secret_x.json", "data/token.json"})
        copied = {p.name for p in self.out.rglob("*")}
        self.assertFalse({".env", "client_secret_x.json", "token.json"} & copied)

    def test_shorts_candidates_and_lineage(self) -> None:
        lineage = export.build_package(self.root, self.out, dry_run=True)["lineage"]
        self.assertEqual(lineage["production_archive"], "VALID")
        self.assertEqual(lineage["shorts_candidates"], [{
            "content_id": "ok", "knowledge_id": "k1", "generation_id": "gen-ok",
            "shorts_script": "data/shorts_scripts/ok.json", "mp4": "data/shorts/ok.mp4", "youtube_video_id": "v1",
        }])  # superseded/invalid/미승인/blog/pool(미승격)은 후보가 아니다
        self.assertEqual(lineage["content_ids"], ["bad", "blog", "ok", "old", "pool1", "wait"])
        self.assertIn("gen-pool", lineage["generation_ids"])

    def test_source_is_never_modified_and_dry_run_writes_nothing(self) -> None:
        export.build_package(self.root, self.out, dry_run=True)
        self.assertFalse(self.out.exists())
        export.build_package(self.root, self.out)
        self.assertEqual({p: _sha(p) for p in self.root.rglob("*") if p.is_file()}, self.before)

    def test_secret_value_in_data_aborts_and_removes_package(self) -> None:
        fake_secret = "ya29." + "a" * 30  # access token 모양의 가짜 값
        (self.root / "data/tak_scout_daily.json").write_text(json.dumps({"note": fake_secret}), encoding="utf-8")
        with self.assertRaises(export.ExportAborted) as ctx:
            export.build_package(self.root, self.out)
        self.assertIn("data/tak_scout_daily.json", str(ctx.exception))
        self.assertNotIn(fake_secret, str(ctx.exception))
        self.assertFalse(self.out.exists())

    def test_non_empty_output_is_not_overwritten(self) -> None:
        self.out.mkdir()
        (self.out / "keep.txt").write_text("x", encoding="utf-8")
        with self.assertRaises(export.ExportAborted):
            export.build_package(self.root, self.out)
        self.assertTrue((self.out / "keep.txt").exists())

    def test_absent_production_reports_zero_candidates(self) -> None:
        (self.root / "data/tak_media_archive.json").unlink()
        lineage = export.analyze_lineage(self.root)
        self.assertEqual((lineage["production_archive"], lineage["shorts_candidates"]), ("NOT_PRESENT", []))


if __name__ == "__main__":
    unittest.main()
