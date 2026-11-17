import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tak_scout.models import ScoutCandidate
from tak_scout.trend_history import (
    build_daily_report, load_history, observations_for_day,
    rising_keywords, save_history, render_daily_report,
)


def candidate(sid, title, source):
    return ScoutCandidate(sid, title, "", f"https://{source}.example/item/{sid}",
                          "2026-11-16", source, "general")


class TrendHistoryTests(unittest.TestCase):
    def test_daily_history_is_idempotent_for_same_day(self):
        rows = observations_for_day([
            candidate("a", "AI 스마트 안경", "source-a"),
            candidate("b", "AI 스마트 안경 활용", "source-b"),
        ], "2026-11-16")
        with TemporaryDirectory() as folder:
            path = Path(folder) / "history.json"
            save_history(rows, path)
            save_history(rows + rows, path)
            loaded = load_history(path)
        self.assertEqual(len(loaded), len(rows))
        self.assertEqual(loaded[0].source_count, 2)

    def test_rising_means_only_observed_feed_count_increase(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "history.json"
            before = observations_for_day([
                candidate("a", "AI 스마트 안경", "source-a"),
                candidate("b", "AI 스마트 안경 활용", "source-b"),
            ], "2026-11-15")
            today = observations_for_day([
                candidate("a", "AI 스마트 안경", "source-a"),
                candidate("b", "AI 스마트 안경 활용", "source-b"),
                candidate("c", "AI 스마트 안경 시장", "source-c"),
            ], "2026-11-16")
            save_history(before + today, path)
            rising = rising_keywords(load_history(path), "2026-11-16")
        ai_rising = next(row for row in rising if row["keyword"] == "ai")
        self.assertEqual(ai_rising["previous_count"], 2)
        self.assertEqual(ai_rising["current_count"], 3)

    def test_first_observation_has_no_rising_claim(self):
        today = observations_for_day([
            candidate("a", "생성형 인공지능", "source-a"),
            candidate("b", "생성형 인공지능 활용", "source-b"),
        ], "2026-11-16")
        self.assertEqual(rising_keywords(today, "2026-11-16"), [])

    def test_markdown_report_discloses_datalab_relative_ratio(self):
        report = {
            "generated_on": "2026-11-17",
            "measurement_scope": "등록된 공개 RSS 수집 피드 내부",
            "top_keywords": [], "rising_keywords": [],
            "content_opportunities": [],
            "limitations": [],
            "naver_datalab": {
                "status": "success",
                "result": {"results": [
                    {"title": "인공지능", "data": [{"ratio": 71.2}]}
                ]},
            },
        }
        markdown = render_daily_report(report)
        self.assertIn("네이버 데이터랩 상대 검색 관심도", markdown)
        self.assertIn("절대 검색량이 아닙니다", markdown)
        self.assertIn("71.2", markdown)

    def test_daily_report_discloses_missing_search_and_competition_metrics(self):
        candidates = [
            candidate("a", "AI 스마트 안경", "source-a"),
            candidate("b", "AI 스마트 안경 활용", "source-b"),
        ]
        report = build_daily_report(candidates, [], "2026-11-16")
        self.assertIn("검색량 미확인", report["content_opportunities"][0]["limitations"])
        self.assertTrue(any("검색량" in x for x in report["limitations"]))
        self.assertEqual(report["rising_keywords"], [])


if __name__ == "__main__":
    unittest.main()
