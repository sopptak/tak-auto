import unittest
from dataclasses import replace

from content_engine.generator import generate_content_bundle
from tak_scout.research import ResearchRecord
from tak_scout.research_knowledge import build_knowledge_from_research


class ResearchMediaBridgeTests(unittest.TestCase):
    def test_approved_research_knowledge_generates_traceable_media_bundle(self):
        research = ResearchRecord(
            scout_id="trend-bridge-test",
            candidate_title="생성형 AI 산업 동향",
            candidate_url="https://example.test/source",
            source_name="Example",
            candidate_published_at="2026-11-16",
            researched_at="2026-11-17T09:00:00+09:00",
            query="생성형 AI 최근 동향",
            answer=(
                "첫 번째 조사 사실은 공개 자료에서 확인된 기술 도입 흐름입니다.\n\n"
                "두 번째 조사 사실은 산업별 활용 사례가 서로 다른 속도로 확산된다는 점입니다.\n\n"
                "세 번째 조사 사실은 비용과 데이터 관리가 도입 판단의 주요 변수라는 점입니다."
            ),
            citations=("https://example.test/citation",),
            model="sonar-pro",
        )
        pending = build_knowledge_from_research(research)
        self.assertGreaterEqual(len(pending.key_points), 3)
        approved = replace(pending, knowledge_review_status="approved")

        bundle = generate_content_bundle(approved)

        self.assertEqual(bundle.status, "complete")
        self.assertIsNotNone(bundle.blog)
        self.assertEqual(len(bundle.shorts), 3)
        self.assertEqual(len(bundle.threads), 5)
        for draft in (bundle.blog, *bundle.shorts, *bundle.threads):
            self.assertTrue(draft.evidence_unit_ids)
            self.assertEqual(draft.source_url, research.candidate_url)
            self.assertTrue(any("PERPLEXITY CITATION" in item for item in draft.evidence))
        self.assertTrue(any("factual_information" in item or "key_point" in item
                            for draft in (*bundle.shorts, *bundle.threads)
                            for item in draft.evidence_unit_ids))


if __name__ == "__main__":
    unittest.main()
