import json
from pathlib import Path
import unittest

from blog_importer.models import BlogPost
from tak_brain import ArticleTypeClassifier, RawContent, append_knowledge_file, transform_raw
from tak_brain.knowledge_transformers import (
    AIBusinessKnowledgeTransformer,
    BookPhilosophyKnowledgeTransformer,
    ExperienceKnowledgeTransformer,
    FinanceKnowledgeTransformer,
    GeneralKnowledgeTransformer,
    WorkplaceKnowledgeTransformer,
    TRANSFORMERS,
)


class ArticleTypePipelineTests(unittest.TestCase):
    FIXTURES = (
        ("experience", "앱을 직접 만들기 시작했다", "직접 앱을 만들고 테스트했다."),
        ("experience", "직접 만든 제품의 경험", "처음부터 직접 만들었다. 문제가 생겨 수정했다."),
        ("finance", "은행 대출과 재무제표", "은행 대출은 매출, 영업이익, 당기순이익을 함께 본다."),
        ("finance", "대출 판단기준", "재무제표의 이익률과 매출 증가 추이를 확인한다."),
        ("workplace", "직장에서 신뢰받는 방법", "작은 약속을 지키면 상사와 동료의 신뢰를 얻는다."),
        ("workplace", "직장 거절과 신뢰", "업무를 거절하는 말과 직장 내 신뢰를 다룬다."),
        ("ai_business", "AI로 첫 수익을 기다린다", "AI로 HARU를 시작했고 첫 수익을 기다린다."),
        ("book_philosophy", "장자가 말하는 비교", "장자의 핵심 메시지와 자유로운 삶을 정리한다."),
        ("book_philosophy", "손자병법의 승리 전략", "손자병법은 싸우기 전에 이길 상황을 만든다고 말한다."),
        ("general", "새로운 기록", "특정 유형을 판단할 근거가 부족한 기록이다."),
    )

    EXPECTED_TRANSFORMERS = {
        "experience": ExperienceKnowledgeTransformer,
        "finance": FinanceKnowledgeTransformer,
        "workplace": WorkplaceKnowledgeTransformer,
        "ai_business": AIBusinessKnowledgeTransformer,
        "book_philosophy": BookPhilosophyKnowledgeTransformer,
        "general": GeneralKnowledgeTransformer,
    }

    def _raw(self, index: int, title: str, body: str) -> RawContent:
        post = BlogPost.from_mapping(
            {
                "id": f"fixture-{index}",
                "title": title,
                "published_at": "2026-09-10T00:00:00+00:00",
                "body": body,
                "source_url": f"https://fixture.test/{index}",
                "source": "test",
            }
        )
        return RawContent.from_post(post)

    def test_classifies_all_fixture_types_from_title_and_body(self):
        classifier = ArticleTypeClassifier()
        for index, (expected, title, body) in enumerate(self.FIXTURES):
            with self.subTest(expected=expected, title=title):
                classification = classifier.classify(self._raw(index, title, body))
                self.assertEqual(classification.article_type, expected)

    def test_dispatches_to_matching_transformer_and_common_validation(self):
        classifier = ArticleTypeClassifier()
        for index, (expected, title, body) in enumerate(self.FIXTURES):
            raw = self._raw(index, title, body)
            knowledge = transform_raw(raw)
            self.assertEqual(classifier.classify(raw).article_type, expected)
            self.assertIsInstance(TRANSFORMERS[expected](), self.EXPECTED_TRANSFORMERS[expected])
            self.assertEqual(knowledge.article_type, expected)
            self.assertEqual(knowledge.source_raw_id, raw.id)
            self.assertEqual(knowledge.source_url, raw.source_url)
            self.assertIsNone(knowledge.confidence)
            self.assertEqual(knowledge.knowledge_review_status, "pending")

    def test_type_specific_safety_rules(self):
        finance = transform_raw(self._raw(2, self.FIXTURES[2][1], self.FIXTURES[2][2]))
        workplace = transform_raw(self._raw(4, self.FIXTURES[4][1], self.FIXTURES[4][2]))
        ai_business = transform_raw(self._raw(6, self.FIXTURES[6][1], self.FIXTURES[6][2]))
        book = transform_raw(self._raw(7, self.FIXTURES[7][1], self.FIXTURES[7][2]))
        general = transform_raw(self._raw(9, self.FIXTURES[9][1], self.FIXTURES[9][2]))

        self.assertNotIn("앱", finance.experience or "")
        self.assertNotIn("대출", workplace.lesson or "")
        self.assertIsNone(ai_business.result)
        self.assertIsNone(book.experience)
        self.assertIsNone(general.experience)
        self.assertIsNone(general.derived_insight)

    def test_workplace_observation_does_not_invent_experience_or_topic(self):
        raw = self._raw(10, "직장에서 일 잘해도 인정받지 못하는 이유", "직장에서는 신뢰와 인정의 차이를 관찰할 수 있다. 다른 사람의 거절 사례도 언급한다.")
        knowledge = transform_raw(raw)

        self.assertEqual(knowledge.article_type, "workplace")
        self.assertIsNone(knowledge.experience)
        self.assertIsNone(knowledge.lesson)
        self.assertIsNone(knowledge.reusable_principle)

    def test_ai_business_does_not_treat_title_goal_as_revenue(self):
        raw = self._raw(11, "AI로 번 첫 1만원을 기다린다", "AI 프로젝트를 시작했고 첫 수익을 기다리는 중이다.")
        knowledge = transform_raw(raw)

        self.assertEqual(knowledge.article_type, "ai_business")
        self.assertIsNone(knowledge.result)

    def test_workplace_title_topic_takes_priority_over_incidental_terms(self):
        raw = self._raw(12, "거절을 잘하는 사람이 직장에서 더 신뢰받는 이유", "작은 약속과 거절 방식이 신뢰에 영향을 준다.")
        knowledge = transform_raw(raw)

        self.assertIn("거절", knowledge.lesson or "")
        self.assertIn("거절", knowledge.reusable_principle or "")

    def test_batch_generation_preserves_approved_and_deduplicates_source(self):
        import tempfile

        raws = []
        for index, (_, title, body) in enumerate(self.FIXTURES[:2]):
            raw = self._raw(index, title, body)
            raws.append(
                {
                    "raw": {
                        "id": raw.id,
                        "title": raw.title,
                        "published_at": raw.published_at,
                        "body": raw.body,
                        "tags": list(raw.tags),
                        "source_url": raw.source_url,
                        "source": raw.source,
                    }
                }
            )
        approved = transform_raw(self._raw(0, self.FIXTURES[0][1], self.FIXTURES[0][2])).to_dict()
        approved["knowledge_review_status"] = "approved"
        with tempfile.TemporaryDirectory() as directory:
            from pathlib import Path

            raw_path = Path(directory) / "raw.json"
            knowledge_path = Path(directory) / "knowledge.json"
            raw_path.write_text(json.dumps(raws, ensure_ascii=False), encoding="utf-8")
            knowledge_path.write_text(json.dumps([approved], ensure_ascii=False), encoding="utf-8")

            created, duplicates, errors = append_knowledge_file(raw_path, knowledge_path)
            saved = json.loads(knowledge_path.read_text(encoding="utf-8"))

        self.assertEqual((created, duplicates, errors), (1, 1, 0))
        self.assertEqual(saved[0]["knowledge_review_status"], "approved")
        self.assertEqual(len({item["source_raw_id"] for item in saved}), 2)

    def test_existing_knowledge_001_remains_approved(self):
        record = next(
            item
            for item in json.loads(Path("data/tak_brain_knowledge.json").read_text(encoding="utf-8"))
            if item["id"] == "knowledge-da6ddf5aa459"
        )
        self.assertEqual(record["knowledge_review_status"], "approved")
        self.assertEqual(record["source_raw_id"], "https://blog.naver.com/tmong2/224407187378")


if __name__ == "__main__":
    unittest.main()
