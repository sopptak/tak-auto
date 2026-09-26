"""6-43 YouTube content lineage / idempotency / processing lifecycle 검증.

실제 YouTube API는 호출하지 않는다(urlopen 차단 + 가짜 transport). ``data/``를 쓰지 않는다 - 전부 tempfile.
"""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from content_engine.media_archive import MediaArchiveRecord, save_archive
from content_engine.operator_summary import OperatorInputs, build_publish_status, build_youtube_uploads_row
from content_engine.shorts_adapter import save_approved_shorts_script
from content_engine.youtube_publisher import YouTubeAPIError, YouTubeClient
from content_engine.youtube_upload_history import (
    FAILED, PROCESSING, SUCCEEDED, UPLOADED, TestUploadAnnotation, YouTubeUploadHistory,
    YouTubeUploadHistoryError, file_sha256, lifecycle_state, migrate_history_records,
)
import scripts.migrate_youtube_publish_log as migrate_cli
import scripts.refresh_youtube_status as refresh_cli
import scripts.upload_youtube_short as uploader


def _status(processing: str = "succeeded", upload: str = "processed", reason: str = "", found: bool = True) -> dict:
    if not found:
        return {"items": []}
    return {"items": [{
        "snippet": {"title": "제목", "description": "", "publishedAt": "2026-09-26T00:00:00Z"},
        "status": {"privacyStatus": "private", "uploadStatus": upload},
        "processingDetails": {"processingStatus": processing, **({"processingFailureReason": reason} if reason else {})},
    }]}


def _record(**overrides) -> MediaArchiveRecord:
    defaults = dict(
        content_id="c1", knowledge_id="k1", platform="shorts", generation_status="valid",
        original_title="원본", original_body="본문", rewritten_title="제목", rewritten_body="본문입니다.",
        source_url="https://example.test/1", evidence=(), evidence_unit_ids=(),
        created_at="2026-01-01T00:00:00Z", review_status="approved", generation_id="gen-1",
    )
    defaults.update(overrides)
    return MediaArchiveRecord(**defaults)


class _NoNetwork(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch("content_engine.youtube_publisher.urlopen", side_effect=AssertionError("network"))
        patcher.start()
        self.addCleanup(patcher.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.history_path = self.tmp / "youtube_publish_log.json"
        self.archive = self.tmp / "tak_media_archive.json"
        self.scripts_dir = self.tmp / "shorts_scripts"
        self.upload_calls = 0
        self.statuses: list = []

    def _mp4(self, name: str = "a.mp4", payload: bytes = b"mp4-a") -> Path:
        path = self.tmp / name
        path.write_bytes(payload)
        return path

    def _client(self) -> YouTubeClient:
        def upload(token, metadata, path, timeout):
            self.upload_calls += 1
            return {"id": f"vid{self.upload_calls}"}

        def status(token, video_id, timeout):
            item = self.statuses.pop(0) if self.statuses else _status()
            if isinstance(item, Exception):
                raise item
            return item

        return YouTubeClient("id", "secret", "refresh", token_transport=lambda *a: {"access_token": "t"},
                             upload_transport=upload, status_transport=status)

    def _upload(self, *extra: str, video: Path | None = None) -> tuple[int, str]:
        args = ["--video", str(video or self._mp4()), "--title", "제목", "--history", str(self.history_path),
                "--production-archive", str(self.archive), "--shorts-scripts-dir", str(self.scripts_dir), *extra]
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out), \
                mock.patch.object(YouTubeClient, "from_environment", side_effect=lambda *a, **k: self._client()):
            code = uploader.main(args)
        return code, out.getvalue()

    def _approve(self, record: MediaArchiveRecord | None = None, *others: MediaArchiveRecord) -> None:
        record = record or _record()
        save_archive([record, *others], self.archive)
        save_approved_shorts_script(_record(content_id=record.content_id, knowledge_id=record.knowledge_id), self.scripts_dir)

    def _history(self) -> list[dict]:
        return YouTubeUploadHistory(self.history_path).load()


class LineageAndIdempotencyTests(_NoNetwork):
    PROD = ("--content-id", "c1", "--knowledge-id", "k1")

    def test_production_upload_records_full_lineage(self) -> None:
        self._approve()
        video = self._mp4()
        code, _ = self._upload(*self.PROD, video=video)
        self.assertEqual(code, 0)
        record = self._history()[0]
        self.assertEqual(
            (record["content_id"], record["knowledge_id"], record["generation_id"], record["upload_mode"], record["video_id"]),
            ("c1", "k1", "gen-1", "production", "vid1"),
        )
        self.assertEqual(record["artifact_sha256"], file_sha256(video))
        self.assertEqual((record["processing_status"], record["upload_status"]), ("succeeded", "processed"))
        self.assertTrue(record["last_checked_at"])
        self.assertEqual(lifecycle_state(record), SUCCEEDED)

    def test_production_upload_without_content_id_is_blocked(self) -> None:
        code, out = self._upload()
        self.assertEqual((code, self.upload_calls), (1, 0))
        self.assertIn("content_id 없는 운영 업로드", out)
        self.assertFalse(self.history_path.exists())

    def test_explicit_test_upload_is_allowed_only_private_and_without_content_id(self) -> None:
        code, _ = self._upload("--test-upload", "--privacy", "unlisted")
        self.assertEqual((code, self.upload_calls), (1, 0))
        self._approve()
        code, _ = self._upload("--test-upload", *self.PROD)
        self.assertEqual((code, self.upload_calls), (1, 0))
        code, _ = self._upload("--test-upload", "--source-ref", "spec.json")
        self.assertEqual((code, self.upload_calls), (0, 1))
        record = self._history()[0]
        self.assertEqual((record["upload_mode"], record["content_id"], record["source_ref"]), ("test", "", "spec.json"))

    def test_same_content_id_same_generation_is_not_reuploaded(self) -> None:
        self._approve()
        self._upload(*self.PROD)
        code, out = self._upload(*self.PROD, video=self._mp4("b.mp4", b"mp4-b"))
        self.assertEqual((code, self.upload_calls), (0, 1))
        self.assertIn("이미 YouTube 업로드 이력", out)
        self.assertEqual(len(self._history()), 1)

    def test_same_content_id_different_generation_is_blocked_not_overwritten(self) -> None:
        self._approve()
        self._upload(*self.PROD)
        save_archive([_record(generation_id="gen-2")], self.archive)  # 정정본이 같은 content_id로 승격된 상황
        code, out = self._upload(*self.PROD, video=self._mp4("b.mp4", b"mp4-b"))
        self.assertEqual((code, self.upload_calls), (1, 1))
        self.assertIn("generation_id", out)
        self.assertEqual(self._history()[0]["generation_id"], "gen-1")

    def test_superseded_content_is_blocked(self) -> None:
        self._approve(_record(review_status="superseded", superseded_by="c2"), _record(content_id="c2"))
        code, out = self._upload(*self.PROD)
        self.assertEqual((code, self.upload_calls), (1, 0))
        self.assertIn("superseded", out.lower())

    def test_invalid_generation_is_blocked(self) -> None:
        save_archive([_record(generation_status="rejected")], self.archive)
        save_approved_shorts_script(_record(), self.scripts_dir)
        code, out = self._upload(*self.PROD)
        self.assertEqual((code, self.upload_calls), (1, 0))
        self.assertIn("generation_status", out)

    def test_same_mp4_under_another_content_id_is_blocked(self) -> None:
        self._approve(_record(), _record(content_id="c9", knowledge_id="k9"))
        save_approved_shorts_script(_record(content_id="c9", knowledge_id="k9"), self.scripts_dir)
        video = self._mp4()
        self._upload(*self.PROD, video=video)
        code, out = self._upload("--content-id", "c9", "--knowledge-id", "k9", video=video)
        self.assertEqual((code, self.upload_calls), (1, 1))
        self.assertIn("같은 MP4", out)

    def test_same_mp4_blocked_even_in_test_mode(self) -> None:
        video = self._mp4()
        self._upload("--test-upload", video=video)
        code, _ = self._upload("--test-upload", video=video)
        self.assertEqual((code, self.upload_calls), (1, 1))

    def test_processing_failure_keeps_video_id_and_reason(self) -> None:
        self._approve()
        self.statuses = [_status("failed", "failed", reason="uploadFailed")]
        code, _ = self._upload(*self.PROD)
        self.assertEqual(code, 0)  # 업로드 자체는 성공했다 - 기록을 남긴다
        record = self._history()[0]
        self.assertEqual((record["video_id"], record["processing_failure_reason"]), ("vid1", "uploadFailed"))
        self.assertEqual(lifecycle_state(record), FAILED)

    def test_status_query_failure_records_unknown_as_uploaded(self) -> None:
        self._approve()
        self.statuses = [YouTubeAPIError("403")]
        self._upload(*self.PROD)
        record = self._history()[0]
        self.assertEqual((record["processing_status"], lifecycle_state(record)), ("UNKNOWN", UPLOADED))

    def test_performance_targets_exclude_test_uploads(self) -> None:
        self._approve()
        self._upload(*self.PROD)
        self._upload("--test-upload", video=self._mp4("t.mp4", b"test"))
        targets = YouTubeUploadHistory(self.history_path).performance_targets()
        self.assertEqual(targets, [{"content_id": "c1", "knowledge_id": "k1", "video_id": "vid1", "uploaded_at": self._history()[0]["uploaded_at"]}])


class LifecycleTests(unittest.TestCase):
    def test_state_mapping(self) -> None:
        self.assertEqual(lifecycle_state({"processing_status": "succeeded"}), SUCCEEDED)
        self.assertEqual(lifecycle_state({"processing_status": "processing"}), PROCESSING)
        self.assertEqual(lifecycle_state({"processing_status": "WAITING_PROCESSING"}), PROCESSING)
        self.assertEqual(lifecycle_state({"processing_status": "terminated"}), FAILED)
        self.assertEqual(lifecycle_state({"upload_status": "rejected"}), FAILED)
        self.assertEqual(lifecycle_state({}), UPLOADED)

    def test_update_record_refuses_identity_fields_and_ambiguous_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            history = YouTubeUploadHistory(Path(tmp) / "h.json")
            history.write_records([{"video_id": "v"}, {"video_id": "v"}])
            with self.assertRaises(YouTubeUploadHistoryError):
                history.update_record("v", {"content_id": "x"})
            with self.assertRaises(YouTubeUploadHistoryError):
                history.update_record("v", {"processing_status": "succeeded"})


# 6-42 실제 기록과 같은 모양의 fixture(값은 가짜)
LEGACY_6_42 = [
    {"video_id": "old1", "uploaded_at": "2026-09-17T00:00:00+00:00", "title": "테스트", "privacy_status": "private",
     "video_path": "x.mp4", "tags": [], "url": "https://youtu.be/old1"},
    {"video_id": "real1", "uploaded_at": "2026-09-26T00:00:00+00:00", "title": "대출", "privacy_status": "private",
     "video_path": "f.mp4", "tags": [], "url": "https://youtu.be/real1", "content_id": "", "knowledge_id": "",
     "processing_status": "succeeded"},
]


class MigrationTests(unittest.TestCase):
    NOTE = TestUploadAnnotation("real1", "a" * 64, "spec.json")

    def test_migration_marks_modes_without_inventing_content_id(self) -> None:
        after = migrate_history_records(LEGACY_6_42, (self.NOTE,))
        self.assertEqual([r["upload_mode"] for r in after], ["legacy_unlinked", "test"])
        self.assertEqual(after[1]["artifact_sha256"], "a" * 64)
        self.assertEqual([r.get("content_id", "") for r in after], ["", ""])
        self.assertNotIn("content_id", after[0])  # 없던 식별 필드를 만들어 넣지 않는다
        self.assertEqual(LEGACY_6_42[1].get("upload_mode"), None)  # 입력은 그대로

    def test_migration_is_idempotent(self) -> None:
        once = migrate_history_records(LEGACY_6_42, (self.NOTE,))
        self.assertEqual(migrate_history_records(once, (self.NOTE,)), once)

    def test_conflicting_artifact_or_unknown_video_fails(self) -> None:
        once = migrate_history_records(LEGACY_6_42, (self.NOTE,))
        with self.assertRaises(YouTubeUploadHistoryError):
            migrate_history_records(once, (TestUploadAnnotation("real1", "b" * 64, ""),))
        with self.assertRaises(YouTubeUploadHistoryError):
            migrate_history_records(LEGACY_6_42, (TestUploadAnnotation("nope", "a" * 64, ""),))

    def test_cli_backup_then_write_and_failed_run_leaves_file_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "youtube_publish_log.json"
            path.write_text(json.dumps(LEGACY_6_42, ensure_ascii=False), encoding="utf-8")
            original = path.read_bytes()
            artifact = Path(tmp) / "f.mp4"
            artifact.write_bytes(b"real")
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                bad = migrate_cli.main(["--history", str(path), "--test-video", "nope", "--artifact", str(artifact)])
            self.assertEqual(bad, 1)
            self.assertEqual(path.read_bytes(), original)
            with contextlib.redirect_stdout(out):
                ok = migrate_cli.main(["--history", str(path), "--test-video", "real1", "--artifact", str(artifact)])
            self.assertEqual(ok, 0)
            backups = list(Path(tmp).glob("youtube_publish_log.backup-6-43-*.json"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), original)
            migrated = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(migrated[1]["artifact_sha256"], file_sha256(artifact))
            with contextlib.redirect_stdout(out):
                self.assertEqual(migrate_cli.main(["--history", str(path), "--test-video", "real1", "--artifact", str(artifact)]), 0)
            self.assertEqual(len(list(Path(tmp).glob("*.backup-6-43-*.json"))), 1)  # 재실행은 쓰지 않음


class RefreshStatusTests(_NoNetwork):
    def _refresh(self, *ids: str) -> tuple[int, str]:
        out = io.StringIO()
        args = ["--history", str(self.history_path)] + [x for v in ids for x in ("--video-id", v)]
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out), \
                mock.patch.object(YouTubeClient, "from_environment", side_effect=lambda *a, **k: self._client()) as factory:
            code = refresh_cli.main(args)
        self.factory_calls = factory.call_count
        return code, out.getvalue()

    def test_refresh_updates_lifecycle_fields_only(self) -> None:
        YouTubeUploadHistory(self.history_path).write_records([dict(LEGACY_6_42[1], processing_status="processing")])
        self.statuses = [_status()]
        code, _ = self._refresh("real1")
        record = self._history()[0]
        self.assertEqual(code, 0)
        self.assertEqual((record["processing_status"], record["upload_status"], lifecycle_state(record)), ("succeeded", "processed", SUCCEEDED))
        self.assertTrue(record["last_checked_at"])
        self.assertEqual(record["uploaded_at"], LEGACY_6_42[1]["uploaded_at"])
        self.assertEqual(self.upload_calls, 0)

    def test_unknown_video_is_refused_before_any_client(self) -> None:
        YouTubeUploadHistory(self.history_path).write_records(list(LEGACY_6_42))
        code, _ = self._refresh("someone-elses-video")
        self.assertEqual((code, self.factory_calls), (1, 0))

    def test_missing_video_records_reason(self) -> None:
        YouTubeUploadHistory(self.history_path).write_records(list(LEGACY_6_42))
        self.statuses = [_status(found=False)]
        code, _ = self._refresh("real1")
        self.assertEqual(code, 1)
        self.assertIn("찾을 수 없음", self._history()[1]["processing_failure_reason"])


class OperatorTests(_NoNetwork):
    def test_uploads_row_and_already_published_link(self) -> None:
        self._approve()
        self._upload("--content-id", "c1", "--knowledge-id", "k1")
        history = YouTubeUploadHistory(self.history_path)
        inputs = OperatorInputs(generated_at="t", production_records=(_record(),), youtube_history=history,
                                youtube_renderer_available=True)
        row = build_youtube_uploads_row(inputs)
        self.assertEqual((row.status, row.count), (SUCCEEDED, 1))
        self.assertIn("vid1[production] content_id=c1", row.why)
        shorts = next(r for r in build_publish_status(inputs, {}) if r.label == "YouTube Shorts")
        self.assertEqual({r.label for r in build_publish_status(inputs, {})}, {"Threads", "Blog", "YouTube Shorts"})
        self.assertEqual(shorts.status, "ALREADY_PUBLISHED")

    def test_legacy_record_without_keys_is_flagged(self) -> None:
        YouTubeUploadHistory(self.history_path).write_records(migrate_history_records(LEGACY_6_42, ()))
        row = build_youtube_uploads_row(OperatorInputs(generated_at="t", youtube_history=YouTubeUploadHistory(self.history_path)))
        self.assertIn("old1", row.action)

    def test_no_history_is_not_present(self) -> None:
        self.assertEqual(build_youtube_uploads_row(OperatorInputs(generated_at="t")).status, "NOT_PRESENT")


if __name__ == "__main__":
    unittest.main()
