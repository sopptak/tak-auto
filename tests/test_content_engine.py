import json
from pathlib import Path
import unittest

from content_engine.generator import generate_content_bundle, generate_from_approved
from content_engine.models import ContentBundle
from tak_brain import KnowledgeRecord, load_knowledge_records, select_approved


class ContentEngineTests(unittest.TestCase):
    KNOWLEDGE_PATH = Path(__file__).parents[1] / "data" / "tak_brain_knowledge.json"

    def setUp(self) -> None:
        records = load_knowledge_records(self.KNOWLEDGE_PATH)
        self.knowledge = next(record for record in select_approved(records) if record.id == records[0].id)

    def test_approved_knowledge_generates_exact_bundle_counts(self):
        bundle = generate_content_bundle(self.knowledge)

        self.assertIsInstance(bundle, ContentBundle)
        self.assertEqual(len((bundle.blog,)), 1)
        self.assertEqual(len(bundle.shorts), 3)
        self.assertEqual(len(bundle.threads), 5)

    def test_outputs_preserve_source_url_and_evidence(self):
        bundle = generate_content_bundle(self.knowledge)
        drafts = (bundle.blog, *bundle.shorts, *bundle.threads)

        for draft in drafts:
            with self.subTest(title=draft.title):
                self.assertEqual(draft.source_url, self.knowledge.source_url)
                self.assertEqual(draft.evidence, self.knowledge.evidence)

        self.assertIn(self.knowledge.experience, bundle.blog.body)
        self.assertIn(self.knowledge.result, bundle.shorts[2].body)
        self.assertIn(self.knowledge.reusable_principle, bundle.threads[4].body)

    def test_unapproved_knowledge_is_rejected(self):
        pending = KnowledgeRecord(
            **{**self.knowledge.to_dict(), "knowledge_review_status": "pending"}
        )

        with self.assertRaises(ValueError):
            generate_content_bundle(pending)

    def test_input_list_must_contain_exactly_one_approved_knowledge(self):
        with self.assertRaises(ValueError):
            generate_from_approved(())

        with self.assertRaises(ValueError):
            generate_from_approved((self.knowledge, self.knowledge))

    def test_source_data_is_not_modified(self):
        before = self.KNOWLEDGE_PATH.read_bytes()
        generate_content_bundle(self.knowledge)
        self.assertEqual(self.KNOWLEDGE_PATH.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()