"""scripts/run_scout.py 검증(5-19): 후보 선정이 수집 순서가 아니라 TAK SCOUT SCORE
(tak_scout.scoring, LLM 없는 rule-based 점수) 기준인지 확인한다.

실제 RSS 네트워크 호출은 절대 하지 않는다 - tak_scout.collector.fetch_rss를
patch해 고정된 XML 문자열로 대체한다(tests/test_scout_collector.py와 동일한
방법론).
"""

from __future__ import annotations

from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import StringIO
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from scripts.run_scout import main
from tak_scout.collector import load_daily_pack


REPO_ROOT = Path(__file__).resolve().parents[1]

# item이 하나도 없는 RSS 피드(빈 channel). 실제 source가 오늘 아무것도 내보내지
# 않았을 때(네트워크는 정상이지만 신규 글이 없는 경우 등)를 흉내낸다.
_EMPTY_FEED = """<rss version="2.0"><channel></channel></rss>"""


# 일부러 "낮은 점수" 기사를 피드에서 먼저, "높은 점수" 기사를 나중에 배치한다.
# 수집 순서(도착 순)로 자르면 낮은 점수 기사가 선택되지만, 점수 기준으로
# 선정하면 높은 점수 기사가 선택되어야 한다.
_FEED = """<rss version="2.0"><channel>
<item>
  <title>오늘 날씨는 맑음</title>
  <link>https://example.test/low-score</link>
  <description>특별한 내용 없는 일반 기사입니다.</description>
</item>
<item>
  <title>은행 대출 금리 급등 경고</title>
  <link>https://example.test/high-score</link>
  <description>금융 전문가들이 대출 금리 인상에 대해 우려를 표했습니다.</description>
</item>
</channel></rss>"""


def _write_sources(directory: Path) -> Path:
    path = directory / "sources.json"
    path.write_text(
        json.dumps({"sources": [{"name": "테스트 소스", "url": "https://example.test/rss.xml", "category": "finance"}]}),
        encoding="utf-8",
    )
    return path


class RunScoutScoreBasedSelectionTests(unittest.TestCase):
    def test_selects_higher_scoring_candidate_over_earlier_arrival(self):
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            sources_path = _write_sources(directory)
            output_json = directory / "tak_scout_daily.json"
            output_md = directory / "tak_scout_daily.md"

            with patch("tak_scout.collector.fetch_rss", return_value=_FEED):
                exit_code = main(
                    [
                        "--sources", str(sources_path),
                        "--output-json", str(output_json),
                        "--output-md", str(output_md),
                        "--max", "1",
                    ]
                )

            self.assertEqual(exit_code, 0)
            candidates = load_daily_pack(output_json)
            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0].title, "은행 대출 금리 급등 경고")

    def test_max_limits_candidate_count_after_scoring(self):
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            sources_path = _write_sources(directory)
            output_json = directory / "tak_scout_daily.json"
            output_md = directory / "tak_scout_daily.md"

            with patch("tak_scout.collector.fetch_rss", return_value=_FEED):
                exit_code = main(
                    [
                        "--sources", str(sources_path),
                        "--output-json", str(output_json),
                        "--output-md", str(output_md),
                        "--max", "5",
                    ]
                )

            self.assertEqual(exit_code, 0)
            candidates = load_daily_pack(output_json)
            # 피드에는 2건만 있으므로 --max 5를 줘도 2건만 저장된다.
            self.assertEqual(len(candidates), 2)
            # 점수가 높은 기사가 먼저 와야 한다(정렬도 점수 기준).
            self.assertEqual(candidates[0].title, "은행 대출 금리 급등 경고")

    def test_markdown_output_is_also_written(self):
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            sources_path = _write_sources(directory)
            output_json = directory / "tak_scout_daily.json"
            output_md = directory / "tak_scout_daily.md"

            with patch("tak_scout.collector.fetch_rss", return_value=_FEED):
                main(
                    [
                        "--sources", str(sources_path),
                        "--output-json", str(output_json),
                        "--output-md", str(output_md),
                        "--max", "1",
                    ]
                )

            self.assertTrue(output_md.exists())
            self.assertIn("은행 대출 금리 급등 경고", output_md.read_text(encoding="utf-8"))

    def test_stdout_prints_top_candidates_with_scores(self):
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            sources_path = _write_sources(directory)
            output_json = directory / "tak_scout_daily.json"
            output_md = directory / "tak_scout_daily.md"

            captured = StringIO()
            with patch("tak_scout.collector.fetch_rss", return_value=_FEED):
                with redirect_stdout(captured):
                    exit_code = main(
                        [
                            "--sources", str(sources_path),
                            "--output-json", str(output_json),
                            "--output-md", str(output_md),
                            "--max", "5",
                        ]
                    )

            self.assertEqual(exit_code, 0)
            output = captured.getvalue()

            # 피드 2건이 모두 선정되므로 TOP 2 블록이 출력되어야 한다.
            self.assertIn("=== TAK SCOUT TOP 2 ===", output)
            self.assertIn("=== END TOP 2 ===", output)

            # 점수가 높은 후보가 1번으로, source/URL/A~E 세부 점수까지 출력되어야 한다.
            self.assertIn("1. [총점", output)
            self.assertIn("은행 대출 금리 급등 경고", output)
            self.assertIn("Source: 테스트 소스", output)
            self.assertIn("URL: https://example.test/high-score", output)
            self.assertIn("A: ", output)
            self.assertIn("B: ", output)
            self.assertIn("C: ", output)
            self.assertIn("D: ", output)
            self.assertIn("E: ", output)

            # TOP 블록의 순서가 실제 JSON에 저장된 순위(점수 내림차순)와 일치해야 한다.
            candidates = load_daily_pack(output_json)
            top_block_index = output.index("=== TAK SCOUT TOP 2 ===")
            end_block_index = output.index("=== END TOP 2 ===")
            top_block = output[top_block_index:end_block_index]
            first_title_pos = top_block.index(candidates[0].title)
            second_title_pos = top_block.index(candidates[1].title)
            self.assertLess(first_title_pos, second_title_pos)

    def test_zero_candidates_prints_empty_top_block_without_error(self):
        """오늘 수집된 소재가 하나도 없어도(score 정보 자체가 없는 경우) 예외 없이
        TOP 0 블록을 출력해야 한다."""
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            sources_path = _write_sources(directory)
            output_json = directory / "tak_scout_daily.json"
            output_md = directory / "tak_scout_daily.md"

            captured = StringIO()
            with patch("tak_scout.collector.fetch_rss", return_value=_EMPTY_FEED):
                with redirect_stdout(captured):
                    exit_code = main(
                        [
                            "--sources", str(sources_path),
                            "--output-json", str(output_json),
                            "--output-md", str(output_md),
                            "--max", "5",
                        ]
                    )

            self.assertEqual(exit_code, 0)
            output = captured.getvalue()
            self.assertIn("=== TAK SCOUT TOP 0 ===", output)
            self.assertIn("=== END TOP 0 ===", output)

            candidates = load_daily_pack(output_json)
            self.assertEqual(candidates, [])


class _FixedFeedRequestHandler(BaseHTTPRequestHandler):
    """어떤 경로로 요청이 와도 고정된 RSS XML을 돌려주는 최소 HTTP 핸들러."""

    feed_body: bytes = b""

    def do_GET(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler가 요구하는 이름)
        self.send_response(200)
        self.send_header("Content-Type", "application/rss+xml; charset=utf-8")
        self.send_header("Content-Length", str(len(self.feed_body)))
        self.end_headers()
        self.wfile.write(self.feed_body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass  # 테스트 출력이 서버 접근 로그로 지저분해지지 않게 한다.


class RunScoutProductionEntrypointTests(unittest.TestCase):
    """실제 GitHub Actions가 실행하는 것과 동일한 방식(별도 프로세스로
    `python3 scripts/run_scout.py ...` 실행)으로 TOP N 출력이 나오는지 확인한다.

    main()을 직접 호출하는 다른 테스트들과 달리, 여기서는 스크립트를 서브프로세스로
    실행해 `if __name__ == "__main__":` 진입점 자체를 검증한다 - "테스트에서만
    출력되고 실제 CLI 실행에서는 출력되지 않는" 회귀를 다시 잡아낼 수 있도록 한다.
    외부 네트워크 호출은 하지 않지만, 실제 fetch_rss 경로(urllib.request.urlopen ->
    HTTP GET -> status/헤더 확인)를 그대로 통과시키기 위해 로컬 루프백 HTTP 서버를
    띄워 응답한다(운영 환경의 http(s) RSS source와 동일한 프로토콜 경로).
    """

    def test_subprocess_cli_run_prints_top_n_block(self):
        handler_class = type(
            "_TestFeedHandler", (_FixedFeedRequestHandler,), {"feed_body": _FEED.encode("utf-8")}
        )
        server = HTTPServer(("127.0.0.1", 0), handler_class)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        try:
            feed_url = f"http://127.0.0.1:{server.server_port}/feed.xml"

            with tempfile.TemporaryDirectory() as directory_name:
                directory = Path(directory_name)
                sources_path = directory / "sources.json"
                sources_path.write_text(
                    json.dumps(
                        {
                            "sources": [
                                {
                                    "name": "테스트 소스",
                                    "url": feed_url,
                                    "category": "finance",
                                }
                            ]
                        }
                    ),
                    encoding="utf-8",
                )
                output_json = directory / "tak_scout_daily.json"
                output_md = directory / "tak_scout_daily.md"

                result = self._run_cli(sources_path, output_json, output_md)

                self.assertEqual(result.returncode, 0, msg=result.stderr)
                self.assertIn("=== TAK SCOUT TOP 2 ===", result.stdout)
                self.assertIn("=== END TOP 2 ===", result.stdout)
                self.assertIn("1. [총점", result.stdout)
                self.assertIn("은행 대출 금리 급등 경고", result.stdout)
                self.assertIn("Source: 테스트 소스", result.stdout)
                self.assertIn("A: ", result.stdout)
                self.assertIn("B: ", result.stdout)
                self.assertIn("C: ", result.stdout)
                self.assertIn("D: ", result.stdout)
                self.assertIn("E: ", result.stdout)
                self.assertTrue(output_json.exists())
                self.assertTrue(output_md.exists())
        finally:
            server.shutdown()
            server_thread.join(timeout=5)

    @staticmethod
    def _run_cli(sources_path: Path, output_json: Path, output_md: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "run_scout.py"),
                "--sources", str(sources_path),
                "--output-json", str(output_json),
                "--output-md", str(output_md),
                "--max", "5",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )


if __name__ == "__main__":
    unittest.main()
