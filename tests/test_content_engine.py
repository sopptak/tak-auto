from pathlib import Path
import unittest

from content_engine.generator import build_content_brief, generate_content_bundle, generate_from_approved
from content_engine.models import ContentBundle
from tak_brain import KnowledgeRecord, load_knowledge_records, select_approved


class ContentEngineTests(unittest.TestCase):
    KNOWLEDGE_PATH = Path(__file__).parents[1] / "data" / "tak_brain_knowledge.json"

    def setUp(self) -> None:
        records = load_knowledge_records(self.KNOWLEDGE_PATH)
        self.knowledge = next(record for record in select_approved(records) if record.id == records[0].id)

    def _complete_knowledge(self, derived_insight: str | None = None) -> KnowledgeRecord:
        def sentences(field_name: str, count: int) -> str:
            return " ".join(f"{field_name} 근거 {index}." for index in range(1, count + 1))

        return KnowledgeRecord(
            id="knowledge-complete",
            source_url="https://example.test/complete",
            title="원문 제목은 콘텐츠 제목에 사용하지 않는다",
            article_type="experience",
            knowledge_type="경험",
            experience=sentences("경험", 4),
            problem=sentences("문제", 6),
            action=sentences("행동", 8),
            result=sentences("결과", 4),
            lesson=sentences("교훈", 7),
            reusable_principle=sentences("원칙", 7),
            derived_insight=derived_insight or sentences("통찰", 3),
            evidence=("원문 근거",),
            knowledge_review_status="approved",
        )

    def test_evidence_units_have_stable_field_index_ids(self):
        brief = build_content_brief(self._complete_knowledge())

        self.assertEqual(brief.evidence_units[0].id, "experience:1")
        self.assertEqual(brief.evidence_units[2].id, "experience:3")
        self.assertIn("problem:4", {unit.id for unit in brief.evidence_units})
        self.assertIn("derived_insight:3", {unit.id for unit in brief.evidence_units})

    def test_complete_knowledge_generates_exact_bundle_counts(self):
        bundle = generate_content_bundle(self._complete_knowledge())

        self.assertIsInstance(bundle, ContentBundle)
        self.assertEqual(bundle.status, "complete")
        self.assertIsNotNone(bundle.blog)
        self.assertEqual(len(bundle.shorts), 3)
        self.assertEqual(len(bundle.threads), 5)

    def test_outputs_preserve_source_url_and_evidence(self):
        knowledge = self._complete_knowledge()
        bundle = generate_content_bundle(knowledge)
        drafts = (bundle.blog, *bundle.shorts, *bundle.threads)

        for draft in drafts:
            self.assertIsNotNone(draft)
            self.assertEqual(draft.source_url, knowledge.source_url)
            self.assertEqual(draft.evidence, knowledge.evidence)

    def test_evidence_units_are_not_repeated_within_a_draft(self):
        bundle = generate_content_bundle(self._complete_knowledge())
        drafts = (bundle.blog, *bundle.shorts, *bundle.threads)

        for draft in drafts:
            self.assertEqual(len(draft.evidence_unit_ids), len(set(draft.evidence_unit_ids)))
            self.assertNotIn(draft.title, draft.body)

    def test_blog_uses_message_title_and_narrative_without_field_headings(self):
        knowledge = self._complete_knowledge()
        blog = generate_content_bundle(knowledge).blog

        self.assertIsNotNone(blog)
        self.assertNotEqual(blog.title, knowledge.title)
        self.assertEqual(blog.title, "직접 시도하며 얻은 교훈")
        for heading in ("문제제기", "경험/내용", "시도한 내용"):
            self.assertNotIn(f"{heading}\n", blog.body)

    def test_platforms_use_their_assigned_perspectives(self):
        bundle = generate_content_bundle(self._complete_knowledge())

        self.assertTrue(bundle.shorts[0].evidence_unit_ids[0].startswith("problem:"))
        self.assertTrue(bundle.shorts[1].evidence_unit_ids[0].startswith("action:"))
        self.assertTrue(bundle.shorts[2].evidence_unit_ids[0].startswith("result:"))
        self.assertTrue(bundle.threads[0].evidence_unit_ids[0].startswith(("lesson:", "derived_insight:")))
        self.assertTrue(bundle.threads[1].evidence_unit_ids[0].startswith("experience:"))
        self.assertTrue(bundle.threads[2].evidence_unit_ids[0].startswith("action:"))
        self.assertTrue(bundle.threads[3].evidence_unit_ids[0].startswith("problem:"))
        self.assertTrue(bundle.threads[4].evidence_unit_ids[0].startswith("reusable_principle:"))

    def test_derived_insight_is_used_only_when_present(self):
        complete = generate_content_bundle(self._complete_knowledge())
        used_ids = {
            unit_id
            for draft in (complete.blog, *complete.shorts, *complete.threads)
            for unit_id in draft.evidence_unit_ids
        }
        self.assertTrue(any(unit_id.startswith("derived_insight:") for unit_id in used_ids))

        without_insight = KnowledgeRecord(
            **{**self._complete_knowledge().to_dict(), "derived_insight": None}
        )
        brief = build_content_brief(without_insight)
        self.assertFalse(any(unit.field_name == "derived_insight" for unit in brief.evidence_units))

    def test_insufficient_evidence_requires_no_content_evidence(self):
        knowledge = KnowledgeRecord(
            id="knowledge-empty",
            source_url="https://example.test/empty",
            title="근거 없는 기록",
            evidence=("원문 근거",),
            knowledge_review_status="approved",
        )
        bundle = generate_content_bundle(knowledge)

        self.assertEqual(bundle.status, "insufficient_distinct_evidence")
        self.assertIsNone(bundle.blog)
        self.assertEqual(bundle.shorts, ())
        self.assertEqual(bundle.threads, ())
        self.assertTrue(bundle.unmet_requirement_ids)

    def test_knowledge_001_generates_a_complete_bundle(self):
        bundle = generate_content_bundle(self.knowledge)

        self.assertEqual(bundle.status, "complete")
        self.assertIsNotNone(bundle.blog)
        self.assertEqual(len(bundle.shorts), 3)
        self.assertEqual(len(bundle.threads), 5)

    def test_finance_content_uses_no_invented_experience_process_or_result(self):
        records = load_knowledge_records(self.KNOWLEDGE_PATH)
        finance = next(record for record in records if record.id == "knowledge-e1cc05264953")
        bundle = generate_content_bundle(finance)
        output = "\n".join(draft.body for draft in (bundle.blog, *bundle.shorts, *bundle.threads))

        self.assertEqual(bundle.blog.title, "재무 판단에서 함께 볼 기준")
        self.assertNotIn("그 과정", output)
        self.assertNotIn("결과를 기록", output)
        self.assertNotIn("경험을 다룹니다", output)
        self.assertIn("공식 심사 기준으로 해석하지 않습니다", bundle.blog.body)

    def test_workplace_criterion_content_does_not_imply_missing_fields(self):
        records = load_knowledge_records(self.KNOWLEDGE_PATH)
        workplace_ids = ("knowledge-da8e52862a79", "knowledge-a3f43f9bb62e")

        for knowledge_id in workplace_ids:
            with self.subTest(knowledge_id=knowledge_id):
                knowledge = next(record for record in records if record.id == knowledge_id)
                bundle = generate_content_bundle(knowledge)
                output = "\n".join(draft.body for draft in (bundle.blog, *bundle.shorts, *bundle.threads))

                self.assertEqual(bundle.blog.title, "판단에 앞서 확인할 기준")
                self.assertNotIn("그 과정", output)
                self.assertNotIn("결과를 기록", output)
                self.assertNotIn("경험을 다룹니다", output)

    def test_generation_does_not_add_topic_specific_facts(self):
        bundle = generate_content_bundle(self._complete_knowledge())
        output = "\n".join(
            draft.body for draft in (bundle.blog, *bundle.shorts, *bundle.threads)
        )

        for invented_topic in ("앱", "AI", "코딩", "테스트", "사용자"):
            self.assertNotIn(invented_topic, output)

    def test_output_does_not_copy_complete_evidence_sentences(self):
        knowledge = self._complete_knowledge()
        bundle = generate_content_bundle(knowledge)
        output = "\n".join(
            (draft.title + "\n" + draft.body)
            for draft in (bundle.blog, *bundle.shorts, *bundle.threads)
        )

        for unit in build_content_brief(knowledge).evidence_units:
            self.assertNotIn(unit.text, output)

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
