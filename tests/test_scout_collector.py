"""tak_scout.collector 검증. RSS 네트워크 호출은 fetch_rss를 patch해 대체한다."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tak_scout.collector import (
    build_daily_pack,
    dedupe_candidates,
    load_daily_pack,
    load_sources,
    save_daily_pack_json,
    save_daily_pack_markdown,
    select_candidates,
)
from tak_scout.models import ScoutCandidate
from tak_scout.rss import ScoutRssError


FEED_A = """<rss version="2.0"><channel>
<item><title>공통 기사</title><link>https://example.test/a/1</link><description>A 요약</description>
<pubDate>Thu, 10 Sep 2026 10:00:00 +0900</pubDate></item>
<item><title>A만의 기사</title><link>https://example.test/a/2</link><description>A 요약2</description>
<pubDate>Thu, 10 Sep 2026 11:00:00 +0900</pubDate></item>
</channel></rss>"""

# 같은 기사(URL 동일)를 다른 소스가 다시 내보내는 경우
FEED_B = """<rss version="2.0"><channel>
<item><title>공통 기사</title><link>https://example.test/a/1</link><description>B가 본 동일 기사</description>
<pubDate>Thu, 10 Sep 2026 12:00:00 +0900</pubDate></item>
<item><title>B만의 기사</title><link>https://example.test/b/2</link><description>B 요약</description>
<pubDate>Thu, 10 Sep 2026 13:00:00 +0900</pubDate></item>
</channel></rss>"""


class LoadSourcesTests(unittest.TestCase):
    def test_load_sources_reads_sources_key(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sources.json"
            path.write_text(
                '{"sources": [{"name": "테스트", "url": "https://example.test/rss.xml", "category": "finance"}]}',
                encoding="utf-8",
            )
            sources = load_sources(path)
            self.assertEqual(len(sources), 1)
            self.assertEqual(sources[0]["name"], "테스트")

    def test_load_sources_rejects_wrong_structure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sources.json"
            path.write_text("[]", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_sources(path)


class DedupeCandidatesTests(unittest.TestCase):
    def test_dedupe_by_normalized_url(self):
        candidates = [
            ScoutCandidate("scout-1", "제목1", "요약1", "https://example.test/x", "", "소스A", "기타"),
            ScoutCandidate("scout-2", "제목1-복사", "요약2", "https://example.test/x/", "", "소스B", "기타"),
        ]
        result = dedupe_candidates(candidates)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].scout_id, "scout-1")

    def test_dedupe_by_normalized_title(self):
        candidates = [
            ScoutCandidate("scout-1", "  같은 제목  ", "요약1", "https://example.test/1", "", "소스A", "기타"),
            ScoutCandidate("scout-2", "같은 제목", "요약2", "https://example.test/2", "", "소스B", "기타"),
        ]
        result = dedupe_candidates(candidates)
        self.assertEqual(len(result), 1)

    def test_distinct_candidates_are_kept(self):
        candidates = [
            ScoutCandidate("scout-1", "제목1", "요약1", "https://example.test/1", "", "소스A", "기타"),
            ScoutCandidate("scout-2", "제목2", "요약2", "https://example.test/2", "", "소스A", "기타"),
        ]
        self.assertEqual(len(dedupe_candidates(candidates)), 2)


class SelectCandidatesTests(unittest.TestCase):
    def test_limits_to_max_count_preserving_order(self):
        candidates = [
            ScoutCandidate(f"scout-{i}", f"제목{i}", "", f"https://example.test/{i}", "", "소스", "기타")
            for i in range(15)
        ]
        selected = select_candidates(candidates, max_count=10)
        self.assertEqual(len(selected), 10)
        self.assertEqual(selected[0].scout_id, "scout-0")


class BuildDailyPackTests(unittest.TestCase):
    def test_collects_dedupes_and_reports_per_source(self):
        sources = [
            {"name": "소스A", "url": "https://example.test/a.xml", "category": "finance"},
            {"name": "소스B", "url": "https://example.test/b.xml", "category": "tech"},
        ]

        def fake_fetch(url, timeout=20.0):
            return FEED_A if url.endswith("a.xml") else FEED_B

        with patch("tak_scout.collector.fetch_rss", side_effect=fake_fetch):
            candidates, results = build_daily_pack(sources, max_count=10)

        # 공통 기사가 중복 제거되어 3건만 남는다 (공통 1 + A만 1 + B만 1)
        self.assertEqual(len(candidates), 3)
        self.assertEqual(len(results), 2)
        self.assertIsNone(results[0].error)
        self.assertEqual(results[0].candidate_count, 2)

    def test_one_source_failure_does_not_block_others(self):
        sources = [
            {"name": "실패소스", "url": "https://example.test/broken.xml", "category": "기타"},
            {"name": "정상소스", "url": "https://example.test/a.xml", "category": "finance"},
        ]

        def fake_fetch(url, timeout=20.0):
            if "broken" in url:
                raise ScoutRssError("접근 실패")
            return FEED_A

        with patch("tak_scout.collector.fetch_rss", side_effect=fake_fetch):
            candidates, results = build_daily_pack(sources, max_count=10)

        self.assertEqual(len(candidates), 2)
        self.assertIsNotNone(results[0].error)
        self.assertIsNone(results[1].error)

    def test_max_count_limits_selection(self):
        sources = [{"name": "소스A", "url": "https://example.test/a.xml", "category": "finance"}]
        with patch("tak_scout.collector.fetch_rss", return_value=FEED_A):
            candidates, _ = build_daily_pack(sources, max_count=1)
        self.assertEqual(len(candidates), 1)


class DailyPackRoundTripTests(unittest.TestCase):
    def test_save_and_load_json_round_trip(self):
        candidates = [
            ScoutCandidate("scout-1", "제목1", "요약1", "https://example.test/1", "2026-09-10", "소스", "finance"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            json_path = Path(directory) / "daily.json"
            md_path = Path(directory) / "daily.md"
            save_daily_pack_json(candidates, json_path)
            save_daily_pack_markdown(candidates, md_path)

            loaded = load_daily_pack(json_path)
            self.assertEqual(loaded, candidates)

            md_text = md_path.read_text(encoding="utf-8")
            self.assertIn("# 오늘의 TAK SCOUT", md_text)
            self.assertIn("제목1", md_text)
            self.assertIn("scout_id: scout-1", md_text)

    def test_load_daily_pack_rejects_wrong_structure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "daily.json"
            path.write_text("[]", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_daily_pack(path)


if __name__ == "__main__":
    unittest.main()
