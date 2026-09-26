"""6-44 운영 경로 E2E 리허설(실제 YouTube API 없음, 임시 디렉터리만 사용).

실제 CLI를 순서대로 실행해 lineage가 끊기지 않는지 확인한다:
    Production Archive(approved/valid, content_id+generation_id)
    -> scripts/generate_approved_shorts_script.py  (ShortsScript, content_id 내장)
    -> scripts/render_youtube_short.py             (6-40 운영 렌더러, 실제 MP4 - ffmpeg 있을 때만)
    -> scripts/upload_youtube_short.py             (가짜 YouTube 클라이언트, PRIVATE)
    -> publish log(content_id -> artifact_sha256 -> video_id, processing 상태)
    -> 같은 content_id 재시도(dry-run/live) 차단
    -> Operator "YouTube Uploads" / "YouTube Shorts: ALREADY_PUBLISHED"

이 PC의 실제 data/(Production Archive 없음)는 읽지도 쓰지도 않는다.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from content_engine.media_archive import MediaArchiveRecord, save_archive
from content_engine.operator_summary import OperatorInputs, build_operator_summary
from content_engine.youtube_publisher import YouTubeClient
from content_engine.youtube_upload_history import SUCCEEDED, FAILED, YouTubeUploadHistory, file_sha256, lifecycle_state
import scripts.generate_approved_shorts_script as generate_cli
import scripts.render_youtube_short as render_cli
import scripts.upload_youtube_short as upload_cli


def _ffmpeg() -> str | None:
    found = shutil.which("ffmpeg")
    override = os.environ.get("TAK_TEST_FFMPEG")
    return found or (override if override and Path(override).exists() else None)


FFMPEG = _ffmpeg()
HAS_KOREAN_FONT = Path("C:/Windows/Fonts/malgun.ttf").exists()


def _record(**overrides) -> MediaArchiveRecord:
    defaults = dict(
        content_id="content-e2e0001", knowledge_id="knowledge-e2e", platform="shorts", generation_status="valid",
        original_title="은행이 대출 심사에서 먼저 보는 것",
        original_body="첫째, 매달 갚을 수 있는지 봅니다.\n\n둘째, 이미 있는 빚을 합쳐 봅니다.\n\n셋째, 거래 기록과 연체 여부를 봅니다.\n\n신청 전에 소득 대비 빚부터 계산해 보세요.",
        rewritten_title=None, rewritten_body=None, source_url="https://example.test/e2e",
        evidence=(), evidence_unit_ids=(), created_at="2026-09-26T00:00:00Z",
        review_status="approved", generation_id="gen-e2e-1",
    )
    defaults.update(overrides)
    return MediaArchiveRecord(**defaults)


def _status(processing: str) -> dict:
    return {"items": [{
        "snippet": {"title": "t", "description": "", "publishedAt": "2026-09-26T00:00:00Z"},
        "status": {"privacyStatus": "private", "uploadStatus": "processed" if processing == "succeeded" else "uploaded"},
        "processingDetails": {"processingStatus": processing, **({"processingFailureReason": "transcodeFailed"} if processing == "failed" else {})},
    }]}


class E2ERehearsal(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch("content_engine.youtube_publisher.urlopen", side_effect=AssertionError("network"))
        patcher.start()
        self.addCleanup(patcher.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.archive = self.tmp / "tak_media_archive.json"
        self.scripts_dir = self.tmp / "shorts_scripts"
        self.history_path = self.tmp / "youtube_publish_log.json"
        self.api_uploads = 0
        self.statuses = [_status("processing"), _status("succeeded")]
        self.privacy_sent: list[str] = []

    def _client(self) -> YouTubeClient:
        def upload(token, metadata, path, timeout):
            self.api_uploads += 1
            self.privacy_sent.append(metadata["status"]["privacyStatus"])
            return {"id": f"video-e2e-{self.api_uploads}"}

        return YouTubeClient("id", "secret", "refresh", token_transport=lambda *a: {"access_token": "t"},
                             upload_transport=upload, status_transport=lambda *a: self.statuses.pop(0))

    def _run(self, module, *args: str) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out), \
                mock.patch.object(YouTubeClient, "from_environment", side_effect=lambda *a, **k: self._client()), \
                mock.patch("content_engine.youtube_publisher.time.sleep"):
            code = module.main(list(args))
        return code, out.getvalue()

    def _upload(self, video: Path, *extra: str) -> tuple[int, str]:
        return self._run(upload_cli, "--video", str(video), "--title", "은행이 대출 심사에서 먼저 보는 것",
                         "--content-id", "content-e2e0001", "--knowledge-id", "knowledge-e2e", "--privacy", "private",
                         "--history", str(self.history_path), "--production-archive", str(self.archive),
                         "--shorts-scripts-dir", str(self.scripts_dir), *extra)

    def _prepare_script(self, *records: MediaArchiveRecord) -> Path:
        save_archive(list(records or (_record(),)), self.archive)
        code, out = self._run(generate_cli, "--archive", str(self.archive), "--output-dir", str(self.scripts_dir),
                              "--content-id", "content-e2e0001")
        self.assertEqual(code, 0, out)
        script = self.scripts_dir / "content-e2e0001.json"
        self.assertEqual(json.loads(script.read_text(encoding="utf-8"))["content_id"], "content-e2e0001")
        return script

    def _assert_lineage_and_duplicate_guard(self, video: Path) -> None:
        code, out = self._upload(video)
        self.assertEqual((code, self.api_uploads, self.privacy_sent), (0, 1, ["private"]), out)
        record = YouTubeUploadHistory(self.history_path).load()[0]
        self.assertEqual(
            (record["content_id"], record["knowledge_id"], record["generation_id"], record["upload_mode"], record["video_id"]),
            ("content-e2e0001", "knowledge-e2e", "gen-e2e-1", "production", "video-e2e-1"),
        )
        self.assertEqual(record["artifact_sha256"], file_sha256(video))
        self.assertEqual((record["processing_status"], record["upload_status"], lifecycle_state(record)), ("succeeded", "processed", SUCCEEDED))
        self.assertTrue(record["uploaded_at"] and record["last_checked_at"])

        # 같은 content_id 두 번째 시도: dry-run과 live 모두 API 호출 없이 차단(멱등)
        for extra in (("--dry-run",), ()):
            code, out = self._upload(video, *extra)
            self.assertIn("이미 YouTube 업로드 이력에 있습니다", out)
        self.assertEqual(self.api_uploads, 1)
        self.assertEqual(len(YouTubeUploadHistory(self.history_path).load()), 1)

        summary = build_operator_summary(OperatorInputs(
            generated_at="t", production_records=(_record(),), youtube_history=YouTubeUploadHistory(self.history_path),
            youtube_renderer_available=True, youtube_credentials_present=True,
        ))
        self.assertIn("video-e2e-1[production] content_id=content-e2e0001 privacy=private lifecycle=SUCCEEDED", summary.youtube_uploads.why)
        shorts = next(r for r in summary.publish_status if r.label == "YouTube Shorts")
        self.assertEqual(shorts.status, "ALREADY_PUBLISHED")

    @unittest.skipUnless(FFMPEG and HAS_KOREAN_FONT, "ffmpeg(PATH 또는 TAK_TEST_FFMPEG)/한글 폰트가 없는 환경입니다.")
    def test_full_chain_with_real_renderer(self) -> None:
        script = self._prepare_script()
        video = self.tmp / "content-e2e0001.mp4"
        code, out = self._run(render_cli, "--input", str(script), "--output", str(video), "--ffmpeg", FFMPEG)
        self.assertEqual(code, 0, out)
        self.assertGreater(video.stat().st_size, 10_000)
        self._assert_lineage_and_duplicate_guard(video)

    def test_chain_without_renderer(self) -> None:
        self._prepare_script()
        video = self.tmp / "placeholder.mp4"
        video.write_bytes(b"not-a-real-mp4-but-hashable")
        self._assert_lineage_and_duplicate_guard(video)

    def test_processing_failure_is_persisted_with_video_id(self) -> None:
        self._prepare_script()
        video = self.tmp / "v.mp4"
        video.write_bytes(b"v")
        self.statuses = [_status("failed")]
        code, _ = self._upload(video)
        record = YouTubeUploadHistory(self.history_path).load()[0]
        self.assertEqual((code, record["video_id"], record["processing_failure_reason"], lifecycle_state(record)),
                         (0, "video-e2e-1", "transcodeFailed", FAILED))

    def test_pre_upload_guards_block_before_api(self) -> None:
        video = self.tmp / "v.mp4"
        video.write_bytes(b"v")
        cases = {
            "unapproved": _record(review_status="unreviewed"),
            "invalid": _record(generation_status="rejected"),
            "superseded": _record(review_status="superseded", superseded_by="content-e2e0002"),
        }
        for name, record in cases.items():
            with self.subTest(name):
                self._prepare_script()  # 승인 당시 만든 ShortsScript가 남아 있는 상황
                others = [_record(content_id="content-e2e0002")] if name == "superseded" else []
                save_archive([record, *others], self.archive)
                code, _ = self._upload(video)
                self.assertEqual((code, self.api_uploads), (1, 0))
        save_archive([_record()], self.archive)
        (self.scripts_dir / "content-e2e0001.json").unlink()
        code, out = self._upload(video)  # ShortsScript 없음
        self.assertEqual((code, self.api_uploads), (1, 0), out)
        code, out = self._run(upload_cli, "--video", str(video), "--title", "t", "--history", str(self.history_path))
        self.assertEqual((code, self.api_uploads), (1, 0))  # content_id 없음
        self.assertIn("content_id 없는 운영 업로드", out)


if __name__ == "__main__":
    unittest.main()
