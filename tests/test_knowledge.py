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


if __name__ == "__main__":
    unittest.main()
