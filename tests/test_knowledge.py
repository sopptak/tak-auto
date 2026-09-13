import ast
import inspect
import textwrap
import unittest

from blog_importer.models import BlogPost
from tak_brain import KnowledgeRecord, RawContent, select_approved, set_review_status, transform_raw


class KnowledgePipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        post = BlogPost.from_mapping(
            {
                "id": "raw-app-001",
                "title": "개발을 모르는 내가 앱을 만들다",
                "published_at": "2026-09-10T00:00:00+00:00",
                "body": "개발을 모르는 상태에서 앱을 만들고 비공개 테스트를 진행했다. 테스터 12명이 참여했다.",
                "source_url": "https://blog.example.test/app-001",
                "source": "naver_rss",
            }
        )
        self.raw = RawContent.from_post(post)

    def test_raw_to_knowledge_preserves_source_and_separates_evidence(self):
        knowledge = transform_raw(self.raw)

        self.assertTrue(knowledge.id)
        self.assertEqual(knowledge.source_raw_id, self.raw.id)
        self.assertEqual(knowledge.source_url, self.raw.source_url)
        self.assertEqual(knowledge.knowledge_type, "경험")
        self.assertTrue(knowledge.evidence)
        self.assertIn("비공개 테스트", knowledge.evidence[-1])
        self.assertIsNotNone(knowledge.derived_insight)
        self.assertEqual(knowledge.inference_method, "rule_based_template")
        self.assertIsNone(knowledge.confidence)
        self.assertEqual(knowledge.knowledge_review_status, "pending")
        self.assertNotIn(self.raw.body, knowledge.lesson or "")

    def test_only_approved_knowledge_is_selectable(self):
        pending = transform_raw(self.raw)
        approved = set_review_status(pending, "approved")
        rejected = set_review_status(transform_raw(self.raw), "rejected")

        self.assertEqual(select_approved([pending, approved, rejected]), (approved,))

    def test_invalid_review_status_is_rejected(self):
        with self.assertRaises(ValueError):
            set_review_status(transform_raw(self.raw), "published")

    def test_schema_has_no_ai_inference_or_duplicate_experience_field(self):
        fields = [
            node.target.id
            for node in ast.walk(ast.parse(textwrap.dedent(inspect.getsource(KnowledgeRecord))))
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
        ]

        self.assertNotIn("ai_inference", fields)
        self.assertEqual(fields.count("experience"), 1)

    def test_book_knowledge_keeps_financial_claims_separate_from_book_claims(self):
        post = BlogPost.from_mapping(
            {
                "id": "raw-sun-tzu-finance-001",
                "title": "이기는 사람은 절대 무작정 싸우지 않는다",
                "published_at": "2026-09-10T00:00:00+00:00",
                "body": (
                    "손자병법의 핵심 메시지. 지점장의 현장 인사이트 대출 심사를 하다 보면 "
                    "성공하는 기업들의 공통점이 보입니다. 현금흐름을 계산하고, 위험을 분석합니다. "
                    "리스크 관리의 교과서라고 설명합니다."
                ),
                "source_url": "https://blog.example.test/sun-tzu-finance-001",
                "source": "naver_rss",
            }
        )

        knowledge = transform_raw(RawContent.from_post(post))

        self.assertIsNone(knowledge.experience)
        self.assertTrue(any("손자병법의 핵심 메시지와 해석" in item for item in knowledge.evidence))
        financial_evidence = next(item for item in knowledge.evidence if "작성자의 주장·관찰" in item)
        self.assertNotIn("지점장의 대출 심사 현장 관찰", financial_evidence)
        self.assertIn("작성자의 금융 관련 주장·관찰", knowledge.lesson)
        self.assertIn("작성자의 금융 관련 주장·관찰", knowledge.reusable_principle)


if __name__ == "__main__":
    unittest.main()
