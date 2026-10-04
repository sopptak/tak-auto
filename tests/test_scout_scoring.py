"""tak_scout.scoring (TAK SCOUT SCORE MVP) 단위 테스트.

LLM을 쓰지 않는 순수 rule-based 로직이므로, 실제 네트워크/외부 API 호출 없이
전부 결정적으로(deterministic) 검증할 수 있다.
"""

from __future__ import annotations

from datetime import datetime, timezone
import unittest

from tak_scout.models import ScoutCandidate
from tak_scout.scoring import rank_candidates, score_candidate, top_candidates


_REFERENCE_TIME = datetime(2026, 9, 14, 12, 0, 0, tzinfo=timezone.utc)


def _candidate(
    scout_id: str,
    title: str,
    summary: str = "",
    category: str = "finance",
    hours_ago: float = 2.0,
) -> ScoutCandidate:
    published = _REFERENCE_TIME.timestamp() - hours_ago * 3600
    published_at = datetime.fromtimestamp(published, tz=timezone.utc).isoformat()
    return ScoutCandidate(
        scout_id=scout_id,
        title=title,
        summary=summary,
        source_url=f"https://example.test/{scout_id}",
        published_at=published_at,
        source_name="테스트 소스",
        category=category,
    )


class ScoutScoringTests(unittest.TestCase):
    def test_same_input_produces_same_score(self):
        candidate = _candidate(
            "scout-a", "Bank raises mortgage rate amid inflation warning", "central bank warns of housing crisis"
        )
        first = score_candidate(candidate, reference_time=_REFERENCE_TIME)
        second = score_candidate(candidate, reference_time=_REFERENCE_TIME)

        self.assertEqual(first.total, second.total)
        self.assertEqual(first.breakdown, second.breakdown)
        self.assertEqual(first.recommendation_reason, second.recommendation_reason)

    def test_finance_and_ai_candidate_gets_relevance_score(self):
        candidate = _candidate(
            "scout-finance-ai",
            "Central bank raises interest rate as AI investment surges",
            "Regulators announce new policy on bank loans and AI adoption",
        )
        score = score_candidate(candidate, reference_time=_REFERENCE_TIME)

        # 전문성(B)과 수익화 관련성(D) 모두 기본값보다 뚜렷하게 높아야 한다.
        self.assertGreater(score.breakdown["expertise_relevance"], 5)
        self.assertGreater(score.breakdown["monetization_relevance"], 2)
        self.assertIn("금융/대출/경매/부동산/AI", score.recommendation_reason)

    def test_generic_lifestyle_candidate_scores_lower_than_finance_candidate(self):
        finance_candidate = _candidate(
            "scout-finance",
            "Bank warns of mortgage rate rise as housing market cools",
            "Central bank raises interest rate, tenants face higher rent",
            hours_ago=2.0,
        )
        lifestyle_candidate = _candidate(
            "scout-lifestyle",
            "How to protect your laptop, phone and bike from thieves at uni",
            "Tips for new students to keep belongings safe",
            category="기타",
            hours_ago=2.0,
        )

        finance_score = score_candidate(finance_candidate, reference_time=_REFERENCE_TIME)
        lifestyle_score = score_candidate(lifestyle_candidate, reference_time=_REFERENCE_TIME)

        self.assertLess(lifestyle_score.total, finance_score.total)
        # 생활 팁 소재는 전문성/수익화 관련 점수가 거의 없어야 한다(신뢰 가능한 근거만 반영).
        self.assertLessEqual(lifestyle_score.breakdown["expertise_relevance"], 5)
        self.assertLessEqual(lifestyle_score.breakdown["monetization_relevance"], 2)

    def test_breakdown_sums_to_total(self):
        candidates = [
            _candidate("scout-1", "Amazon pauses work with cargo firm after fatal crash", hours_ago=3),
            _candidate("scout-2", "How to protect your laptop, phone and bike from thieves at uni", hours_ago=80),
            _candidate(
                "scout-3",
                "Anthropic boss calls for AI development to slow down",
                "The call comes amid growing concerns about AI risk",
                hours_ago=30,
            ),
        ]
        for candidate in candidates:
            score = score_candidate(candidate, reference_time=_REFERENCE_TIME)
            self.assertEqual(sum(score.breakdown.values()), score.total)

    def test_top_n_sorting_is_deterministic(self):
        candidates = [
            _candidate("scout-b", "Bank raises interest rate amid inflation warning", hours_ago=1),
            _candidate("scout-a", "Bank raises interest rate amid inflation warning", hours_ago=1),
            _candidate("scout-c", "How to protect your bike from thieves", category="기타", hours_ago=1),
            _candidate("scout-d", "AI staff frightened for humanity future, Anthropic warns", hours_ago=10),
        ]

        first_run = rank_candidates(candidates, reference_time=_REFERENCE_TIME)
        second_run = rank_candidates(list(reversed(candidates)), reference_time=_REFERENCE_TIME)

        first_order = [candidate.scout_id for candidate, _ in first_run]
        second_order = [candidate.scout_id for candidate, _ in second_run]
        self.assertEqual(first_order, second_order)

        # scout-a, scout-b는 완전히 동일한 제목/카테고리/발행시각 -> 점수도 동일.
        # 동점 최종 타이브레이크는 scout_id 오름차순이므로 a가 b보다 먼저 나와야 한다.
        self.assertLess(first_order.index("scout-a"), first_order.index("scout-b"))

        totals = [score.total for _, score in first_run]
        self.assertEqual(totals, sorted(totals, reverse=True))

    def test_top_candidates_respects_n(self):
        candidates = [_candidate(f"scout-{i}", f"Bank news {i} about interest rate", hours_ago=i) for i in range(15)]
        top5 = top_candidates(candidates, n=5, reference_time=_REFERENCE_TIME)
        self.assertEqual(len(top5), 5)


if __name__ == "__main__":
    unittest.main()
