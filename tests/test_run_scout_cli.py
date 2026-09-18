"""scripts/run_scout.py 검증(5-19): 후보 선정이 수집 순서가 아니라 TAK SCOUT SCORE
(tak_scout.scoring, LLM 없는 rule-based 점수) 기준인지 확인한다.

실제 RSS 네트워크 호출은 절대 하지 않는다 - tak_scout.collector.fetch_rss를
patch해 고정된 XML 문자열로 대체한다(tests/test_scout_collector.py와 동일한
방법론).
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.run_scout import main
from tak_scout.collector import load_daily_pack


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


if __name__ == "__main__":
    unittest.main()
