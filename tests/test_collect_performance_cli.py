"""scripts/collect_performance.py CLI 검증(6-01, 6-02).

안전 원칙(이 파일 전체에 적용): 이 프로젝트 개발 환경에는 실제
THREADS_ACCESS_TOKEN/YOUTUBE_CLIENT_ID/YOUTUBE_CLIENT_SECRET/YOUTUBE_REFRESH_TOKEN이
이미 환경변수로 설정되어 있을 수 있다(6-01 조사에서 실제로 확인됨). 6-02에서
platform=threads/youtube에 `--confirm-live` 게이트를 추가해, `--dry-run`도
`--confirm-live`도 없는 "기본 실행"은 이제 threads/youtube 클라이언트를 아예
생성하지 않는다(안전한 기본값으로 바뀌었다 - `tests/test_collect_performance_
live_gate.py` 참고). 그래도 이 파일은 여전히 예방 차원에서 **--dry-run 없이
threads/youtube를 실행하는 조합은 만들지 않는다** - `--confirm-live`가 필요한
"성공 경로"는 `content_engine.threads_publisher.ThreadsClient.from_environment`/
`content_engine.youtube_publisher.YouTubeClient.from_environment`를 항상 patch한
채로만 검증한다(tests/test_upload_youtube_short_cli.py가 이미 증명한 안전한
방법론과 동일 - 실제 네트워크를 만들지 않는다). platform=blog는 애초에 네트워크
코드가 없어(content_engine/performance/blog.py 참고) 안전하다.
"""

from __future__ import annotations

from contextlib import redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest

from content_engine.performance.store import load_snapshots
from scripts.collect_performance import main as collect_performance_main


class CollectPerformanceCLITests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.store_path = Path(self.tmp_dir.name) / "tak_performance.json"

    def _run(self, argv: list[str]) -> tuple[int, str]:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = collect_performance_main(argv)
        return exit_code, buffer.getvalue()

    # --- G. Blog manual metric import 저장 -------------------------------------

    def test_blog_manual_metrics_are_saved(self):
        exit_code, output = self._run(
            [
                "--platform", "blog",
                "--content-id", "content-blog-1",
                "--knowledge-id", "knowledge-blog-1",
                "--published-at", "2026-09-10T00:00:00+00:00",
                "--metric", "views=850",
                "--metric", "likes=12",
                "--store", str(self.store_path),
            ]
        )
        self.assertEqual(exit_code, 0)
        self.assertIn("성공", output)

        snapshots = load_snapshots(self.store_path)
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0].metrics, {"views": 850, "likes": 12})
        self.assertEqual(snapshots[0].source, "manual")

    def test_blog_requires_at_least_one_metric(self):
        exit_code, _output = self._run(
            [
                "--platform", "blog",
                "--content-id", "content-blog-1",
                "--knowledge-id", "knowledge-blog-1",
                "--published-at", "2026-09-10T00:00:00+00:00",
                "--store", str(self.store_path),
            ]
        )
        self.assertEqual(exit_code, 1)
        self.assertFalse(self.store_path.exists())

    def test_blog_dry_run_does_not_save(self):
        exit_code, output = self._run(
            [
                "--platform", "blog",
                "--content-id", "content-blog-1",
                "--knowledge-id", "knowledge-blog-1",
                "--published-at", "2026-09-10T00:00:00+00:00",
                "--metric", "views=850",
                "--store", str(self.store_path),
                "--dry-run",
            ]
        )
        self.assertEqual(exit_code, 0)
        self.assertIn("dry-run", output)
        self.assertFalse(self.store_path.exists())

    def test_duplicate_blog_run_reports_skip_without_error(self):
        argv = [
            "--platform", "blog",
            "--content-id", "content-blog-1",
            "--knowledge-id", "knowledge-blog-1",
            "--published-at", "2026-09-10T00:00:00+00:00",
            "--metric", "views=850",
            "--collected-at", "2026-09-17T00:00:00+00:00",
            "--store", str(self.store_path),
        ]
        self._run(argv)
        exit_code, output = self._run(argv)
        self.assertEqual(exit_code, 0)
        self.assertIn("건너뛰었습니다", output)
        self.assertEqual(len(load_snapshots(self.store_path)), 1)

    # --- H. threads/youtube는 --dry-run에서만 검증(실제 API 호출 금지) ----------

    def test_threads_dry_run_never_touches_network_or_store(self):
        exit_code, output = self._run(
            [
                "--platform", "threads",
                "--content-id", "content-threads-1",
                "--knowledge-id", "knowledge-threads-1",
                "--published-at", "2026-09-10T00:00:00+00:00",
                "--external-id", "18114019807999154",
                "--store", str(self.store_path),
                "--dry-run",
            ]
        )
        self.assertEqual(exit_code, 0)
        self.assertIn("dry-run", output)
        self.assertFalse(self.store_path.exists())

    def test_threads_requires_external_id(self):
        exit_code, _output = self._run(
            [
                "--platform", "threads",
                "--content-id", "content-threads-1",
                "--knowledge-id", "knowledge-threads-1",
                "--published-at", "2026-09-10T00:00:00+00:00",
                "--store", str(self.store_path),
                "--dry-run",
            ]
        )
        self.assertEqual(exit_code, 1)

    def test_youtube_dry_run_never_touches_network_or_store(self):
        exit_code, output = self._run(
            [
                "--platform", "youtube",
                "--content-id", "content-yt-1",
                "--knowledge-id", "knowledge-yt-1",
                "--published-at", "2026-09-10T00:00:00+00:00",
                "--external-id", "h2X1fFMDffc",
                "--store", str(self.store_path),
                "--dry-run",
            ]
        )
        self.assertEqual(exit_code, 0)
        self.assertIn("dry-run", output)
        self.assertFalse(self.store_path.exists())

    def test_youtube_requires_external_id(self):
        exit_code, _output = self._run(
            [
                "--platform", "youtube",
                "--content-id", "content-yt-1",
                "--knowledge-id", "knowledge-yt-1",
                "--published-at", "2026-09-10T00:00:00+00:00",
                "--store", str(self.store_path),
                "--dry-run",
            ]
        )
        self.assertEqual(exit_code, 1)


if __name__ == "__main__":
    unittest.main()
