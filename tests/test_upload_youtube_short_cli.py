"""scripts/upload_youtube_short.py 검증.

실제 YouTube API는 절대 호출하지 않는다. ``content_engine.youtube_publisher.YouTubeClient``의
``from_environment``를 patch해서 Fake 클라이언트(또는 호출 시 예외를 던지는 Mock)로
대체한다 - 기존 ``tests/test_publish_approved_threads.py``와 동일한 방법론이다.

과거에는 이 파일이 실제 CLI를 서브프로세스로 띄워 테스트했는데, 서브프로세스는 기본적으로
부모 프로세스의 환경변수를 그대로 물려받는다. 이 Codespace처럼 YOUTUBE_CLIENT_ID/SECRET/
REFRESH_TOKEN이 전역으로 설정된 환경에서는 "자격증명이 없을 때"를 검증하려던 테스트가
실제로는 자격증명을 물려받아 --dry-run 없이 실제 YouTube API를 호출해버렸다(5-17 실측:
실제 계정에 테스트 영상이 업로드됨). 이제는 서브프로세스 대신 ``main()``을 같은 프로세스에서
직접 호출하고 ``YouTubeClient.from_environment``를 항상 patch하므로, 이 환경에 실제
자격증명이 있는지 여부와 무관하게 실제 네트워크 호출이 결정적으로 일어나지 않는다.
"""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from content_engine.media_archive import MediaArchiveRecord, save_archive
from content_engine.shorts_adapter import save_approved_shorts_script
from content_engine.youtube_publisher import (
    YouTubeAPIError,
    YouTubeClient,
    YouTubeConfigurationError,
    YouTubeUploadResult,
)
from content_engine.youtube_upload_history import YouTubeUploadHistory, YouTubeUploadRecord
from scripts.upload_youtube_short import main


class FakeYouTubeClient:
    """실제 네트워크를 전혀 만들지 않는 가짜 클라이언트. upload_short 호출 인자를 기록한다."""

    def __init__(self, result: YouTubeUploadResult | None = None, error: Exception | None = None):
        self.result = result or YouTubeUploadResult(video_id="fake_video_id")
        self.error = error
        self.upload_short_calls: list[dict[str, object]] = []

    def upload_short(self, **kwargs):
        self.upload_short_calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.result


def _make_temp_mp4() -> Path:
    handle = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    handle.write(b"fake-mp4-bytes")
    handle.close()
    return Path(handle.name)


class UploadYouTubeShortCLITests(unittest.TestCase):
    def setUp(self):
        self.video_path = _make_temp_mp4()
        self.addCleanup(self.video_path.unlink, missing_ok=True)
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.history_path = Path(self.tmp_dir.name) / "youtube_publish_log.json"
        self.archive_path = Path(self.tmp_dir.name) / "tak_media_archive.json"
        self.shorts_scripts_dir = Path(self.tmp_dir.name) / "shorts_scripts"

    def _make_eligible(self, content_id: str, knowledge_id: str) -> list[str]:
        """6-26: --content-id를 준 업로드는 이제 production archive
        review_status=="approved" + ShortsScript 존재까지 확인한다
        (Eligibility Contract, docs/6-26-youtube-publish-readiness.md 4-5장).
        이 헬퍼는 그 조건을 만족하는 최소 fixture를 만들고, main()에 전달할
        --production-archive/--shorts-scripts-dir 인자를 반환한다."""
        record = MediaArchiveRecord(
            content_id=content_id,
            knowledge_id=knowledge_id,
            platform="shorts",
            generation_status="valid",
            original_title="원본 제목",
            original_body="원본 본문입니다.",
            rewritten_title="재작성 제목",
            rewritten_body="재작성 본문입니다.",
            source_url="https://example.test/source",
            evidence=(),
            evidence_unit_ids=(),
            created_at="2026-01-01T00:00:00Z",
            review_status="approved",
        )
        save_archive([record], self.archive_path)
        save_approved_shorts_script(record, self.shorts_scripts_dir)
        return [
            "--production-archive", str(self.archive_path),
            "--shorts-scripts-dir", str(self.shorts_scripts_dir),
        ]

    def _run(self, args: list[str]) -> tuple[int, str, str]:
        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                exit_code = main(args)
            except SystemExit as exc:  # argparse가 잘못된 옵션에서 발생시킴
                exit_code = exc.code
        return exit_code, stdout.getvalue(), stderr.getvalue()

    def _assert_from_environment_not_called(self, args: list[str]) -> tuple[int, str, str]:
        with mock.patch.object(
            YouTubeClient,
            "from_environment",
            side_effect=AssertionError("YouTube API가 호출되면 안 됩니다"),
        ) as mocked:
            exit_code, stdout, stderr = self._run(args)
        mocked.assert_not_called()
        return exit_code, stdout, stderr

    def test_dry_run_executes_without_network_or_token(self):
        exit_code, stdout, _stderr = self._assert_from_environment_not_called(
            [
                "--video", str(self.video_path),
                "--title", "테스트 Shorts 제목",
                "--description", "테스트 설명",
                "--tags", "인생,명언,채근담",
                "--privacy", "private",
                "--dry-run",
            ]
        )
        self.assertEqual(exit_code, 0)
        self.assertIn("YouTube Shorts Upload (Dry-run)", stdout)
        self.assertIn("테스트 Shorts 제목", stdout)
        self.assertIn("['인생', '명언', '채근담']", stdout)
        self.assertIn("네트워크 호출 없음", stdout)
        self.assertIn("Dry-run에서는 업로드 이력을 기록하지 않습니다", stdout)

    def test_dry_run_rejects_missing_video_file(self):
        exit_code, _stdout, stderr = self._assert_from_environment_not_called(
            ["--video", "/nonexistent/short.mp4", "--title", "제목", "--dry-run"]
        )
        self.assertNotEqual(exit_code, 0)
        self.assertIn("영상 파일을 찾을 수 없습니다", stderr)

    def test_dry_run_rejects_non_mp4_file(self):
        with tempfile.NamedTemporaryFile(suffix=".mov", delete=False) as tmp:
            tmp.write(b"data")
            bad_path = Path(tmp.name)
        self.addCleanup(bad_path.unlink, missing_ok=True)

        exit_code, _stdout, stderr = self._assert_from_environment_not_called(
            ["--video", str(bad_path), "--title", "제목", "--dry-run"]
        )
        self.assertNotEqual(exit_code, 0)
        self.assertIn(".mp4여야 합니다", stderr)

    def test_dry_run_rejects_empty_title(self):
        exit_code, _stdout, stderr = self._assert_from_environment_not_called(
            ["--video", str(self.video_path), "--title", "   ", "--dry-run"]
        )
        self.assertNotEqual(exit_code, 0)
        self.assertIn("--title이 비어 있습니다", stderr)

    def test_dry_run_rejects_title_exceeding_100_chars(self):
        exit_code, _stdout, stderr = self._assert_from_environment_not_called(
            ["--video", str(self.video_path), "--title", "가" * 101, "--dry-run"]
        )
        self.assertNotEqual(exit_code, 0)
        self.assertIn("YouTube title exceeds 100 characters: 101", stderr)

    def test_cli_rejects_invalid_privacy_choice(self):
        exit_code, _stdout, _stderr = self._assert_from_environment_not_called(
            ["--video", str(self.video_path), "--title", "제목", "--privacy", "everyone", "--dry-run"]
        )
        self.assertNotEqual(exit_code, 0)

    def test_live_without_credentials_fails_with_clear_configuration_error(self):
        with mock.patch.object(
            YouTubeClient,
            "from_environment",
            side_effect=YouTubeConfigurationError(
                "다음 환경변수가 필요합니다: YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN"
            ),
        ):
            exit_code, _stdout, stderr = self._run(
                ["--video", str(self.video_path), "--title", "제목", "--history", str(self.history_path)]
            )
        self.assertNotEqual(exit_code, 0)
        self.assertIn("설정 오류", stderr)
        self.assertIn("YOUTUBE_CLIENT_ID", stderr)
        self.assertFalse(self.history_path.exists())

    def test_live_success_uploads_via_mock_and_records_history(self):
        fake_client = FakeYouTubeClient(result=YouTubeUploadResult(video_id="fake_video_id"))
        with mock.patch.object(YouTubeClient, "from_environment", return_value=fake_client):
            exit_code, stdout, _stderr = self._run(
                [
                    "--video", str(self.video_path),
                    "--title", "실제 업로드 없이 기록되는 제목",
                    "--tags", "인생,명언",
                    "--privacy", "private",
                    "--history", str(self.history_path),
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("fake_video_id", stdout)
        self.assertEqual(len(fake_client.upload_short_calls), 1)
        self.assertEqual(fake_client.upload_short_calls[0]["title"], "실제 업로드 없이 기록되는 제목")

        records = json.loads(self.history_path.read_text(encoding="utf-8"))
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["video_id"], "fake_video_id")
        self.assertEqual(records[0]["title"], "실제 업로드 없이 기록되는 제목")

    # --- 6-02: --content-id/--knowledge-id 연결 -----------------------------

    def test_dry_run_shows_content_id_and_knowledge_id_when_given(self):
        eligibility_args = self._make_eligible("content-abc123", "knowledge-xyz")
        exit_code, stdout, _stderr = self._assert_from_environment_not_called(
            [
                "--video", str(self.video_path),
                "--title", "제목",
                "--content-id", "content-abc123",
                "--knowledge-id", "knowledge-xyz",
                "--dry-run",
                *eligibility_args,
            ]
        )
        self.assertEqual(exit_code, 0)
        self.assertIn("content_id: content-abc123", stdout)
        self.assertIn("knowledge_id: knowledge-xyz", stdout)

    def test_dry_run_shows_placeholder_when_content_id_omitted(self):
        exit_code, stdout, _stderr = self._assert_from_environment_not_called(
            ["--video", str(self.video_path), "--title", "제목", "--dry-run"]
        )
        self.assertEqual(exit_code, 0)
        self.assertIn("content_id: (없음", stdout)
        self.assertIn("knowledge_id: (없음", stdout)

    def test_content_id_without_knowledge_id_is_rejected(self):
        exit_code, _stdout, stderr = self._assert_from_environment_not_called(
            [
                "--video", str(self.video_path),
                "--title", "제목",
                "--content-id", "content-abc123",
                "--dry-run",
            ]
        )
        self.assertNotEqual(exit_code, 0)
        self.assertIn("둘 다 지정하거나 둘 다 생략해야 합니다", stderr)

    def test_knowledge_id_without_content_id_is_rejected(self):
        exit_code, _stdout, stderr = self._assert_from_environment_not_called(
            [
                "--video", str(self.video_path),
                "--title", "제목",
                "--knowledge-id", "knowledge-xyz",
                "--dry-run",
            ]
        )
        self.assertNotEqual(exit_code, 0)
        self.assertIn("둘 다 지정하거나 둘 다 생략해야 합니다", stderr)

    def test_live_success_stores_content_id_and_knowledge_id_in_history(self):
        eligibility_args = self._make_eligible("content-abc123", "knowledge-xyz")
        fake_client = FakeYouTubeClient(result=YouTubeUploadResult(video_id="fake_video_id"))
        with mock.patch.object(YouTubeClient, "from_environment", return_value=fake_client):
            exit_code, _stdout, _stderr = self._run(
                [
                    "--video", str(self.video_path),
                    "--title", "제목",
                    "--content-id", "content-abc123",
                    "--knowledge-id", "knowledge-xyz",
                    "--history", str(self.history_path),
                    *eligibility_args,
                ]
            )

        self.assertEqual(exit_code, 0)
        records = json.loads(self.history_path.read_text(encoding="utf-8"))
        self.assertEqual(records[0]["content_id"], "content-abc123")
        self.assertEqual(records[0]["knowledge_id"], "knowledge-xyz")

    def test_live_success_without_ids_stores_empty_strings_backward_compatibly(self):
        # 기존 사용자가 --content-id/--knowledge-id 없이 쓰던 명령이 그대로 동작해야 한다.
        fake_client = FakeYouTubeClient(result=YouTubeUploadResult(video_id="fake_video_id"))
        with mock.patch.object(YouTubeClient, "from_environment", return_value=fake_client):
            exit_code, _stdout, _stderr = self._run(
                ["--video", str(self.video_path), "--title", "제목", "--history", str(self.history_path)]
            )

        self.assertEqual(exit_code, 0)
        records = json.loads(self.history_path.read_text(encoding="utf-8"))
        self.assertEqual(records[0]["content_id"], "")
        self.assertEqual(records[0]["knowledge_id"], "")

    # --- 6-13: content_id 중복 게시 방지 --------------------------------------

    def test_dry_run_skips_already_uploaded_content_id_without_touching_history(self):
        history = YouTubeUploadHistory(self.history_path)
        history.append(
            YouTubeUploadRecord(
                video_id="already_uploaded_vid",
                uploaded_at="2026-09-20T00:00:00+00:00",
                title="이전 업로드",
                privacy_status="private",
                content_id="content-dup-001",
                knowledge_id="knowledge-dup",
            )
        )

        exit_code, stdout, _stderr = self._assert_from_environment_not_called(
            [
                "--video", str(self.video_path),
                "--title", "새로 시도한 제목",
                "--content-id", "content-dup-001",
                "--knowledge-id", "knowledge-dup",
                "--history", str(self.history_path),
                "--dry-run",
            ]
        )

        self.assertEqual(exit_code, 0)
        self.assertIn("이미 YouTube 업로드 이력에 있습니다", stdout)
        self.assertIn("already_uploaded_vid", stdout)
        records = json.loads(self.history_path.read_text(encoding="utf-8"))
        self.assertEqual(len(records), 1)  # 새 레코드가 추가되지 않았다.

    def test_live_skips_upload_and_does_not_call_api_for_duplicate_content_id(self):
        history = YouTubeUploadHistory(self.history_path)
        history.append(
            YouTubeUploadRecord(
                video_id="already_uploaded_vid",
                uploaded_at="2026-09-20T00:00:00+00:00",
                title="이전 업로드",
                privacy_status="private",
                content_id="content-dup-002",
                knowledge_id="knowledge-dup",
            )
        )

        exit_code, stdout, _stderr = self._assert_from_environment_not_called(
            [
                "--video", str(self.video_path),
                "--title", "새로 시도한 제목",
                "--content-id", "content-dup-002",
                "--knowledge-id", "knowledge-dup",
                "--history", str(self.history_path),
            ]
        )

        self.assertEqual(exit_code, 0)
        self.assertIn("이미 YouTube 업로드 이력에 있습니다", stdout)
        records = json.loads(self.history_path.read_text(encoding="utf-8"))
        self.assertEqual(len(records), 1)

    def test_live_uploads_normally_when_content_id_is_new(self):
        eligibility_args = self._make_eligible("content-dup-003", "knowledge-dup")
        history = YouTubeUploadHistory(self.history_path)
        history.append(
            YouTubeUploadRecord(
                video_id="unrelated_vid",
                uploaded_at="2026-09-20T00:00:00+00:00",
                title="다른 업로드",
                privacy_status="private",
                content_id="content-other",
                knowledge_id="knowledge-other",
            )
        )
        fake_client = FakeYouTubeClient(result=YouTubeUploadResult(video_id="brand_new_vid"))
        with mock.patch.object(YouTubeClient, "from_environment", return_value=fake_client):
            exit_code, stdout, _stderr = self._run(
                [
                    "--video", str(self.video_path),
                    "--title", "새 제목",
                    "--content-id", "content-dup-003",
                    "--knowledge-id", "knowledge-dup",
                    "--history", str(self.history_path),
                    *eligibility_args,
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("brand_new_vid", stdout)
        self.assertEqual(len(fake_client.upload_short_calls), 1)
        records = json.loads(self.history_path.read_text(encoding="utf-8"))
        self.assertEqual(len(records), 2)

    def test_live_api_error_reported_without_recording_history(self):
        fake_client = FakeYouTubeClient(error=YouTubeAPIError("YouTube Upload HTTP 500: message=internal error"))
        with mock.patch.object(YouTubeClient, "from_environment", return_value=fake_client):
            exit_code, _stdout, stderr = self._run(
                ["--video", str(self.video_path), "--title", "제목", "--history", str(self.history_path)]
            )

        self.assertNotEqual(exit_code, 0)
        self.assertIn("YouTube API 오류", stderr)
        self.assertFalse(self.history_path.exists())


if __name__ == "__main__":
    unittest.main()
