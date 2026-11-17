import unittest
from datetime import datetime, timezone

from tak_scout.models import ScoutCandidate
from tak_scout.trend_scoring import rank_trend_candidates, score_trend_candidate


class GeneralTrendScoringTests(unittest.TestCase):
    def test_recent_explanatory_story_scores_higher_than_old_plain_item(self):
        now = datetime(2026, 11, 16, 12, tzinfo=timezone.utc)
        recent = ScoutCandidate("recent", "새 AI 기술 출시, 왜 주목받나", "시장 영향 분석",
                                "https://example.test/a", "2026-11-16T10:00:00+00:00",
                                "Source A", "tech")
        old = ScoutCandidate("old", "일반 소식", "내용", "https://example.test/b",
                             "2026-11-01T10:00:00+00:00", "Source B", "general")
        self.assertGreater(score_trend_candidate(recent, now).total,
                           score_trend_candidate(old, now).total)

    def test_score_explains_its_observable_signals(self):
        item = ScoutCandidate("x", "논란과 변화, 왜 중요한가", "영향과 전망",
                              "https://example.test/x", "2026-11-16T11:00:00+00:00",
                              "Source", "general")
        score = score_trend_candidate(item, datetime(2026, 11, 16, 12, tzinfo=timezone.utc))
        self.assertGreater(score.breakdown["attention_language"], 0)
        self.assertGreater(score.breakdown["discussion_potential"], 0)
        self.assertTrue(score.reasons)

    def test_ranking_is_deterministic_for_equal_inputs(self):
        items = [ScoutCandidate("b", "일반 제목", "", "https://e.test/b", "", "S", "general"),
                 ScoutCandidate("a", "일반 제목", "", "https://e.test/a", "", "S", "general")]
        ranked = rank_trend_candidates(items, datetime(2026, 11, 16, tzinfo=timezone.utc))
        self.assertEqual([x.scout_id for x, _ in ranked], ["a", "b"])


if __name__ == "__main__":
    unittest.main()
