"""scripts/collect_performance.py CLI 검증(6-01).

안전 원칙(이 파일 전체에 적용): 이 프로젝트 개발 환경에는 실제
THREADS_ACCESS_TOKEN/YOUTUBE_CLIENT_ID/YOUTUBE_CLIENT_SECRET/YOUTUBE_REFRESH_TOKEN이
이미 환경변수로 설정되어 있을 수 있다(6-01 조사에서 실제로 확인됨) - 이 CLI는
scripts/publish_threads.py/scripts/upload_youtube_short.py와 동일한 관례로
"--dry-run을 안 주면 진짜 호출"이 기본 동작이다. 그래서 이 테스트 파일은
platform=threads/youtube를 검증할 때 **반드시 --dry-run을 함께 넘긴다** -
실제 네트워크 호출을 유발하는 조합(threads/youtube + dry-run 없음)은 이 파일
어디에도 없다(H. 외부 API 호출은 mock에서만 실행 - 이 CLI 레벨에서는 아예
호출 자체를 하지 않는 것으로 그 원칙을 지킨다). platform=blog는 애초에
네트워크 코드가 없어(content_engine/performance/blog.py 참고) 안전하다.
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
