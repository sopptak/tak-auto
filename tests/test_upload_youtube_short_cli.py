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

from content_engine.youtube_publisher import (
    YouTubeAPIError,
    YouTubeClient,
    YouTubeConfigurationError,
    YouTubeUploadResult,
)
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
