import unittest

from tak_scout.models import ScoutCandidate
from tak_scout.trends import aggregate_trends, extract_keywords, trend_coverage_label


def candidate(scout_id, title, source):
    return ScoutCandidate(
        scout_id=scout_id,
        title=title,
        summary="",
        source_url=f"https://example.com/{scout_id}",
        published_at="2026-11-16T08:00:00+09:00",
        source_name=source,
        category="tech",
    )


class TrendAggregationTests(unittest.TestCase):
    def test_extract_keywords_deduplicates_tokens(self):
        item = candidate("a", "AI AI 기술 변화", "Feed A")
        self.assertEqual(extract_keywords(item).count("ai"), 1)
        self.assertIn("기술", extract_keywords(item))

    def test_only_repeated_terms_are_reported(self):
        items = [
            candidate("a", "AI 기술 변화", "Feed A"),
            candidate("b", "AI 기술 산업", "Feed B"),
            candidate("c", "단독 이슈", "Feed C"),
        ]
        signals = aggregate_trends(items)
        by_keyword = {signal.keyword: signal for signal in signals}
        self.assertIn("ai", by_keyword)
        self.assertEqual(by_keyword["ai"].candidate_count, 2)
        self.assertEqual(by_keyword["ai"].source_count, 2)
        self.assertNotIn("단독", by_keyword)

    def test_repeated_items_from_one_source_do_not_fake_cross_source_signal(self):
        items = [
            candidate("a", "시장 변화", "Feed A"),
            candidate("b", "시장 전망", "Feed A"),
        ]
        signal = next(item for item in aggregate_trends(items) if item.keyword == "시장")
        self.assertEqual(signal.candidate_count, 2)
        self.assertEqual(signal.source_count, 1)

    def test_measurement_label_discloses_limit(self):
        label = trend_coverage_label(aggregate_trends([]))
        self.assertIn("검색량·SNS 인기 측정 아님", label)


if __name__ == "__main__":
    unittest.main()
