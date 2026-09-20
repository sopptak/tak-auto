"""scripts/collect_performance.py의 --confirm-live 안전 게이트 검증(6-02).

6-01에서 발견된 위험(이 Codespace에는 실제 THREADS_ACCESS_TOKEN/YOUTUBE_*가
환경변수로 이미 존재한다)에 대한 직접적인 대응이다. 이 파일은 다음을 증명한다:

    1. credential 환경변수가 있어도 --dry-run/--confirm-live 둘 다 없는
       "기본 실행"은 threads/youtube 클라이언트를 절대 생성하지 않는다.
    2. --confirm-live 없이는 어떤 경우에도 네트워크에 접근하지 않는다.
    3. --confirm-live를 명시하면(GitHub Actions가 아닌 한) 정상적으로
       진행된다 - 단 여기서도 실제 네트워크는 mock으로 대체해 검증한다.
    4. GitHub Actions 환경(GITHUB_ACTIONS=true)에서는 --confirm-live를 줘도
       거부된다.
    5. blog는 이 게이트의 영향을 받지 않는다(원래도 네트워크가 없다).

실제 환경변수(THREADS_ACCESS_TOKEN 등)는 이 파일 어디에서도 읽거나
참조하지 않는다 - 판단 로직은 credential의 "존재 여부"가 아니라 플래그
조합만으로 결정되므로, 이 세션의 실제 자격증명이 있든 없든 테스트 결과가
달라지지 않는다(그 자체가 이 설계의 핵심 안전 속성이다).
"""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from content_engine.performance.store import load_snapshots
from content_engine.threads_publisher import ThreadsClient
from content_engine.youtube_publisher import YouTubeClient
from scripts.collect_performance import _guard_live_network_call, main as collect_performance_main


class GuardLiveNetworkCallPureFunctionTests(unittest.TestCase):
    """순수 판단 함수 자체를 직접 검증한다 - 네트워크/CLI 없이 빠르게 전체 조합을 커버."""

    def test_dry_run_always_allowed_regardless_of_confirm_live(self):
        self.assertIsNone(_guard_live_network_call("threads", dry_run=True, confirm_live=False))
        self.assertIsNone(_guard_live_network_call("threads", dry_run=True, confirm_live=True))

    def test_no_dry_run_no_confirm_live_is_rejected(self):
        error = _guard_live_network_call("threads", dry_run=False, confirm_live=False)
        self.assertIsNotNone(error)
        self.assertIn("--dry-run", error)
        self.assertIn("--confirm-live", error)

    def test_confirm_live_without_github_actions_is_allowed(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            error = _guard_live_network_call("threads", dry_run=False, confirm_live=True)
        self.assertIsNone(error)

    def test_confirm_live_inside_github_actions_is_rejected(self):
        with mock.patch.dict("os.environ", {"GITHUB_ACTIONS": "true"}):
            error = _guard_live_network_call("youtube", dry_run=False, confirm_live=True)
        self.assertIsNotNone(error)
        self.assertIn("GitHub Actions", error)

    def test_github_actions_value_is_case_insensitive(self):
        with mock.patch.dict("os.environ", {"GITHUB_ACTIONS": "True"}):
            error = _guard_live_network_call("youtube", dry_run=False, confirm_live=True)
        self.assertIsNotNone(error)


class CollectPerformanceLiveGateCLITests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.store_path = Path(self.tmp_dir.name) / "tak_performance.json"

    def _run(self, argv: list[str]) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = collect_performance_main(argv)
        return exit_code, stdout.getvalue(), stderr.getvalue()

    def _assert_client_never_created(self, client_cls, argv: list[str]) -> tuple[int, str, str]:
        with mock.patch.object(
            client_cls, "from_environment", side_effect=AssertionError("실제 API가 호출되면 안 됩니다")
        ) as mocked:
            exit_code, stdout, stderr = self._run(argv)
        mocked.assert_not_called()
        return exit_code, stdout, stderr

    # --- 1/2. 기본 실행(플래그 없음)은 threads/youtube를 절대 호출하지 않는다 -----

    def test_threads_without_any_flag_never_creates_client(self):
        exit_code, _stdout, stderr = self._assert_client_never_created(
            ThreadsClient,
            [
                "--platform", "threads",
                "--content-id", "content-1",
                "--knowledge-id", "knowledge-1",
                "--published-at", "2026-09-10T00:00:00+00:00",
                "--external-id", "18114019807999154",
                "--store", str(self.store_path),
            ],
        )
        self.assertEqual(exit_code, 1)
        self.assertFalse(self.store_path.exists())
        self.assertIn("--confirm-live", stderr)

    def test_youtube_without_any_flag_never_creates_client(self):
        exit_code, _stdout, stderr = self._assert_client_never_created(
            YouTubeClient,
            [
                "--platform", "youtube",
                "--content-id", "content-1",
                "--knowledge-id", "knowledge-1",
                "--published-at", "2026-09-10T00:00:00+00:00",
                "--external-id", "h2X1fFMDffc",
                "--store", str(self.store_path),
            ],
        )
        self.assertEqual(exit_code, 1)
        self.assertFalse(self.store_path.exists())
        self.assertIn("--confirm-live", stderr)

    # --- 3. --confirm-live면 진행된다(단, from_environment는 mock으로 대체) -------

    def test_threads_confirm_live_proceeds_with_mocked_client(self):
        def fake_transport(method, url, headers, payload, timeout):
            return {"data": [{"name": "views", "values": [{"value": 42}]}]}

        fake_client = ThreadsClient(access_token="fake-token", transport=fake_transport)
        with mock.patch.object(ThreadsClient, "from_environment", return_value=fake_client):
            exit_code, output, _stderr = self._run(
                [
                    "--platform", "threads",
                    "--content-id", "content-1",
                    "--knowledge-id", "knowledge-1",
                    "--published-at", "2026-09-10T00:00:00+00:00",
                    "--external-id", "18114019807999154",
                    "--store", str(self.store_path),
                    "--confirm-live",
                ]
            )
        self.assertEqual(exit_code, 0)
        self.assertIn("성공", output)
        snapshots = load_snapshots(self.store_path)
        self.assertEqual(snapshots[0].metrics, {"views": 42})
        self.assertEqual(snapshots[0].source, "threads_api")

    def test_youtube_confirm_live_proceeds_with_mocked_client(self):
        fake_client = YouTubeClient(
            client_id="cid",
            client_secret="secret",
            refresh_token="rtoken",
            token_transport=lambda *a: {"access_token": "t"},
            stats_transport=lambda *a: {"items": [{"statistics": {"viewCount": "10"}}]},
        )
        with mock.patch.object(YouTubeClient, "from_environment", return_value=fake_client):
            exit_code, output, _stderr = self._run(
                [
                    "--platform", "youtube",
                    "--content-id", "content-1",
                    "--knowledge-id", "knowledge-1",
                    "--published-at", "2026-09-10T00:00:00+00:00",
                    "--external-id", "h2X1fFMDffc",
                    "--store", str(self.store_path),
                    "--confirm-live",
                ]
            )
        self.assertEqual(exit_code, 0)
        self.assertIn("성공", output)
        snapshots = load_snapshots(self.store_path)
        self.assertEqual(snapshots[0].metrics, {"views": 10})

    # --- 4. GitHub Actions에서는 --confirm-live도 거부된다 -----------------------

    def test_confirm_live_inside_github_actions_still_refuses(self):
        with mock.patch.dict("os.environ", {"GITHUB_ACTIONS": "true"}):
            exit_code, _stdout, stderr = self._assert_client_never_created(
                ThreadsClient,
                [
                    "--platform", "threads",
                    "--content-id", "content-1",
                    "--knowledge-id", "knowledge-1",
                    "--published-at", "2026-09-10T00:00:00+00:00",
                    "--external-id", "18114019807999154",
                    "--store", str(self.store_path),
                    "--confirm-live",
                ],
            )
        self.assertEqual(exit_code, 1)
        self.assertIn("GitHub Actions", stderr)

    # --- 5. blog는 게이트의 영향을 받지 않는다 -----------------------------------

    def test_blog_does_not_require_confirm_live(self):
        exit_code, output, _stderr = self._run(
            [
                "--platform", "blog",
                "--content-id", "content-blog-1",
                "--knowledge-id", "knowledge-blog-1",
                "--published-at", "2026-09-10T00:00:00+00:00",
                "--metric", "views=100",
                "--store", str(self.store_path),
            ]
        )
        self.assertEqual(exit_code, 0)
        self.assertIn("성공", output)

    # --- 5-bis. 오류 메시지에 토큰 값이 노출되지 않는다 ---------------------------

    def test_configuration_error_after_confirm_live_does_not_leak_token(self):
        from content_engine.threads_publisher import ThreadsConfigurationError

        secret_token = "super-secret-token-value"
        with mock.patch.object(
            ThreadsClient,
            "from_environment",
            side_effect=ThreadsConfigurationError("THREADS_ACCESS_TOKEN 환경변수가 필요합니다."),
        ):
            exit_code, _stdout, stderr = self._run(
                [
                    "--platform", "threads",
                    "--content-id", "content-1",
                    "--knowledge-id", "knowledge-1",
                    "--published-at", "2026-09-10T00:00:00+00:00",
                    "--external-id", "18114019807999154",
                    "--store", str(self.store_path),
                    "--confirm-live",
                ]
            )
        self.assertEqual(exit_code, 1)
        self.assertNotIn(secret_token, stderr)


if __name__ == "__main__":
    unittest.main()
