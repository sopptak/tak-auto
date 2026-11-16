import unittest

from tak_scout.models import ScoutCandidate
from tak_scout.trends import aggregate_trends, extract_keywords, normalize_keyword


def item(sid, title, source):
    return ScoutCandidate(sid, title, "", f"https://{source}.example/{sid}",
                          "2026-11-16", source, "general")


class TrendNormalizationTests(unittest.TestCase):
    def test_aliases_normalize_unambiguous_ai_terms(self):
        self.assertEqual(normalize_keyword("인공지능"), "ai")
        self.assertEqual(normalize_keyword("Artificial Intelligence"), "ai")
        self.assertEqual(normalize_keyword("  CHATGPT "), "chatgpt")

    def test_extracts_two_and_three_word_phrases(self):
        terms = extract_keywords(item("1", "생성형 AI 스마트 안경 출시", "A"))
        self.assertIn("생성형 ai", terms)
        self.assertIn("ai 스마트", terms)
        self.assertIn("생성형 ai 스마트", terms)

    def test_aliases_aggregate_across_distinct_articles(self):
        signals = aggregate_trends([
            item("1", "인공지능 기술 변화", "A"),
            item("2", "Artificial Intelligence 활용", "B"),
        ])
        ai = next(signal for signal in signals if signal.keyword == "ai")
        self.assertEqual(ai.candidate_count, 2)
        self.assertEqual(ai.source_count, 2)


if __name__ == "__main__":
    unittest.main()
