from pathlib import Path
from dataclasses import replace
from io import BytesIO
import json
import subprocess
import sys
from urllib.error import HTTPError
import unittest
from unittest import mock

from content_engine.generator import build_content_brief, generate_content_bundle, generate_from_approved
from content_engine.llm_provider import LLMConfigurationError, LLMResponseError, OpenAICompatibleRewriteProvider, _http_transport
from content_engine.models import ContentBundle
from content_engine.rewrite import MockRewriteProvider, RewriteService
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


class RewriteLayerTests(unittest.TestCase):
    KNOWLEDGE_PATH = Path(__file__).parents[1] / "data" / "tak_brain_knowledge.json"

    def setUp(self) -> None:
        records = load_knowledge_records(self.KNOWLEDGE_PATH)
        self.knowledge = next(record for record in records if record.id == "knowledge-da6ddf5aa459")
        self.draft = generate_content_bundle(self.knowledge).blog
        self.service = RewriteService(MockRewriteProvider())

    def test_only_approved_knowledge_can_be_rewritten(self):
        pending = KnowledgeRecord(
            **{**self.knowledge.to_dict(), "knowledge_review_status": "pending"}
        )

        with self.assertRaises(ValueError):
            self.service.rewrite(pending, self.draft)

    def test_mock_rewrite_preserves_original_draft_and_metadata(self):
        result = self.service.rewrite(self.knowledge, self.draft)

        self.assertEqual(result.original_draft, self.draft)
        self.assertEqual(result.rewritten_draft, self.draft)
        self.assertEqual(result.rewritten_draft.source_url, self.draft.source_url)
        self.assertEqual(result.rewritten_draft.evidence, self.draft.evidence)
        self.assertEqual(result.rewrite_status, "rewritten")
        self.assertEqual(result.validation_status, "valid")
        self.assertEqual(result.validation_errors, ())

    def test_valid_rewritten_draft_is_returned_separately(self):
        rewritten = replace(self.draft, title=f"콘텐츠 {self.draft.title}")
        result = RewriteService(MockRewriteProvider(rewritten)).rewrite(self.knowledge, self.draft)

        self.assertEqual(result.original_draft, self.draft)
        self.assertEqual(result.rewritten_draft, rewritten)
        self.assertEqual(result.validation_status, "valid")

    def test_new_factual_expression_fails_validation(self):
        rewritten = replace(self.draft, body=f"새로운 성과를 냈다.\n\n{self.draft.body}")
        result = RewriteService(MockRewriteProvider(rewritten)).rewrite(self.knowledge, self.draft)

        self.assertEqual(result.rewrite_status, "rejected")
        self.assertEqual(result.validation_status, "invalid")
        self.assertTrue(any("사실 범위를 넓히는 표현" in error for error in result.validation_errors))

    def test_new_number_fails_validation(self):
        rewritten = replace(self.draft, body=f"999개의 성과.\n\n{self.draft.body}")
        result = RewriteService(MockRewriteProvider(rewritten)).rewrite(self.knowledge, self.draft)

        self.assertEqual(result.validation_status, "invalid")
        self.assertTrue(any("없는 숫자" in error for error in result.validation_errors))

    def test_source_url_and_evidence_changes_fail_validation(self):
        rewritten = replace(
            self.draft,
            source_url="https://example.test/changed",
            evidence=("변경된 근거",),
        )
        result = RewriteService(MockRewriteProvider(rewritten)).rewrite(self.knowledge, self.draft)

        self.assertEqual(result.validation_status, "invalid")
        self.assertIn("source_url이 원본 Draft와 다릅니다.", result.validation_errors)
        self.assertIn("evidence가 원본 Draft와 다릅니다.", result.validation_errors)

    def test_finance_rewrite_preserves_official_criteria_boundary(self):
        records = load_knowledge_records(self.KNOWLEDGE_PATH)
        finance = next(record for record in records if record.id == "knowledge-e1cc05264953")
        finance_draft = generate_content_bundle(finance).blog
        rewritten = replace(
            finance_draft,
            body=finance_draft.body.replace(
                "이 글의 금융 관련 내용은 원문 작성자의 설명이며, 금융기관의 공식 심사 기준으로 해석하지 않습니다.",
                "",
            ),
        )
        result = RewriteService(MockRewriteProvider(rewritten)).rewrite(finance, finance_draft)

        self.assertEqual(result.validation_status, "invalid")
        self.assertTrue(any("공식 기준 비해석 경계" in error for error in result.validation_errors))

    def test_finance_boundary_ending_variations(self):
        records = load_knowledge_records(self.KNOWLEDGE_PATH)
        finance = next(record for record in records if record.id == "knowledge-e1cc05264953")
        finance_draft = generate_content_bundle(finance).blog

        # PASS 케이스: 동일한 부정 의미의 활용형
        pass_cases = [
            "금융기관의 공식 심사 기준으로 해석하지 않습니다.",
            "금융기관의 공식 심사 기준으로 해석하지 않는다.",
            "금융기관의 공식 심사 기준으로 해석하지 않으며, 개인의 설명입니다.",
        ]
        for boundary_text in pass_cases:
            with self.subTest(boundary_text=boundary_text, expected="PASS"):
                rewritten_body = finance_draft.body.replace(
                    "이 글의 금융 관련 내용은 원문 작성자의 설명이며, 금융기관의 공식 심사 기준으로 해석하지 않습니다.",
                    f"이 글의 금융 관련 내용은 원문 작성자의 설명이며, {boundary_text}",
                )
                rewritten = replace(finance_draft, body=rewritten_body)
                result = RewriteService(MockRewriteProvider(rewritten)).rewrite(finance, finance_draft)
                self.assertEqual(result.validation_status, "valid", f"Unexpected validation error: {result.validation_errors}")

        # FAIL 케이스: 긍정 또는 공식 기준 확대 표현
        fail_cases = [
            "금융기관의 공식 심사 기준으로 해석할 수 있습니다.",
            "금융기관의 공식 심사 기준입니다.",
            "금융기관의 공식 심사 기준으로 볼 수 있습니다.",
            "금융기관의 공식 심사 기준에 해당합니다.",
        ]
        for boundary_text in fail_cases:
            with self.subTest(boundary_text=boundary_text, expected="FAIL"):
                rewritten_body = finance_draft.body.replace(
                    "이 글의 금융 관련 내용은 원문 작성자의 설명이며, 금융기관의 공식 심사 기준으로 해석하지 않습니다.",
                    f"이 글의 금융 관련 내용은 원문 작성자의 설명이며, {boundary_text}",
                )
                rewritten = replace(finance_draft, body=rewritten_body)
                result = RewriteService(MockRewriteProvider(rewritten)).rewrite(finance, finance_draft)
                self.assertEqual(result.validation_status, "invalid")
                self.assertTrue(
                    any("공식 기준" in err or "공식 심사 기준" in err for err in result.validation_errors),
                    f"Expected finance error in {result.validation_errors}",
                )

    def test_natural_korean_rewrite_with_new_connectives_is_allowed(self):
        rewritten = replace(
            self.draft,
            title="아이디어를 현실로 옮긴 시작",
            body="그리고 코딩을 몰라도 시작할 수 있다는 이야기를 자연스럽게 풀어냅니다.",
        )
        result = RewriteService(MockRewriteProvider(rewritten)).rewrite(self.knowledge, self.draft)

        self.assertEqual(result.validation_status, "valid")

    def test_particle_ending_and_sentence_order_changes_are_allowed(self):
        rewritten = replace(
            self.draft,
            body="문제가 생기면 수정하고 다시 테스트했다. 코딩을 몰라도 만들며 배울 수 있다는 교훈을 얻었다.",
        )
        result = RewriteService(MockRewriteProvider(rewritten)).rewrite(self.knowledge, self.draft)

        self.assertEqual(result.validation_status, "valid")

    def test_hook_improvement_is_allowed(self):
        rewritten = replace(self.draft, title="왜 지금 시작해야 할까")
        result = RewriteService(MockRewriteProvider(rewritten)).rewrite(self.knowledge, self.draft)

        self.assertEqual(result.validation_status, "valid")

    def test_known_fact_can_be_expressed_in_different_order(self):
        rewritten = replace(self.draft, body="테스터 12명이 비공개 테스트에 참여했다.")
        result = RewriteService(MockRewriteProvider(rewritten)).rewrite(self.knowledge, self.draft)

        self.assertEqual(result.validation_status, "valid")

    def test_new_person_or_institution_fails_validation(self):
        rewritten = replace(self.draft, body="김민수님과 한국은행이 함께했다.")
        result = RewriteService(MockRewriteProvider(rewritten)).rewrite(self.knowledge, self.draft)

        self.assertEqual(result.validation_status, "invalid")
        self.assertTrue(any("사람·기관·상품명" in error for error in result.validation_errors))

    def test_new_product_name_fails_validation(self):
        rewritten = replace(self.draft, body="TAK상품을 새로 출시했다.")
        result = RewriteService(MockRewriteProvider(rewritten)).rewrite(self.knowledge, self.draft)

        self.assertEqual(result.validation_status, "invalid")
        self.assertTrue(any("사람·기관·상품명" in error for error in result.validation_errors))

    def test_new_experience_fails_validation(self):
        rewritten = replace(self.draft, body="해외에서 창업한 경험이 있다.")
        result = RewriteService(MockRewriteProvider(rewritten)).rewrite(self.knowledge, self.draft)

        self.assertEqual(result.validation_status, "invalid")
        self.assertTrue(any("사실 범위를 넓히는 표현" in error for error in result.validation_errors))

    def test_finance_official_criteria_claim_fails_validation(self):
        records = load_knowledge_records(self.KNOWLEDGE_PATH)
        finance = next(record for record in records if record.id == "knowledge-e1cc05264953")
        finance_draft = generate_content_bundle(finance).blog
        rewritten = replace(finance_draft, body=f"{finance_draft.body}\n\n이는 금융기관의 공식 심사 기준입니다.")
        result = RewriteService(MockRewriteProvider(rewritten)).rewrite(finance, finance_draft)

        self.assertEqual(result.validation_status, "invalid")
        self.assertTrue(any("공식 심사 기준" in error for error in result.validation_errors))

    def test_new_legal_or_regulatory_claim_fails_validation(self):
        rewritten = replace(self.draft, body="대출 관련 법률은 이 방식을 요구한다.")
        result = RewriteService(MockRewriteProvider(rewritten)).rewrite(self.knowledge, self.draft)

        self.assertEqual(result.validation_status, "invalid")
        self.assertTrue(any("사실 범위를 넓히는 표현" in error for error in result.validation_errors))

    def test_normal_phrasings_with_method_or_way_are_allowed(self):
        for body in (
            "문제를 해결하는 방법이 여기에 있습니다.",
            "코딩을 몰라도 직접 앱을 만드는 법을 배웠습니다.",
            "시작하는 법과 반복하는 방법을 다룹니다.",
        ):
            with self.subTest(body=body):
                rewritten = replace(self.draft, body=body)
                result = RewriteService(MockRewriteProvider(rewritten)).rewrite(self.knowledge, self.draft)
                self.assertEqual(result.validation_status, "valid", f"Unexpected validation errors: {result.validation_errors}")

    def test_new_legal_regulations_or_specific_statutes_fail_validation(self):
        for phrase in ("관련 규정을 준수해야 한다.", "조례에 따른 기준이다.", "시행령에 명시되어 있다.", "법적 책임을 진다."):
            with self.subTest(phrase=phrase):
                rewritten = replace(self.draft, body=phrase)
                result = RewriteService(MockRewriteProvider(rewritten)).rewrite(self.knowledge, self.draft)
                self.assertEqual(result.validation_status, "invalid")
                self.assertTrue(any("사실 범위를 넓히는 표현" in error for error in result.validation_errors))

        # _ENTITY_PATTERN에 의한 구체적 법률명 차단 검증
        for statute in ("전자상거래법에 의거하여 처리했다.", "소비자보호법을 적용해야 한다.", "개인정보보호법에 따릅니다."):
            with self.subTest(statute=statute):
                rewritten = replace(self.draft, body=statute)
                result = RewriteService(MockRewriteProvider(rewritten)).rewrite(self.knowledge, self.draft)
                self.assertEqual(result.validation_status, "invalid")
                self.assertTrue(any("사람·기관·상품명" in error for error in result.validation_errors))

    def test_source_url_number_is_not_treated_as_new_number_error(self):
        # source_url contains '224407187378'
        self.assertIn("224407187378", self.draft.source_url)
        # Draft body has no 224407187378, rewrite keeps metadata source_url intact
        result = RewriteService(MockRewriteProvider(self.draft)).rewrite(self.knowledge, self.draft)
        self.assertEqual(result.validation_status, "valid")

    def test_nine_experiment_paraphrases_pass_validation(self):
        # 9개의 실제 paraphrase 표현들이 단어 활용형 및 자연스러운 한국어 문장 변형으로 통과하는지 검증
        cases = [
            ("blog", "결과물을 만들며 시도했던 경험은 결코 헛되지 않았습니다."),
            ("shorts_1", "문제를 해결하는 과정을 통해 알게 된 것을 실천에 옮깁니다."),
            ("shorts_2", "완벽을 기다리는 대신 시도하며 얻은 점이 분명히 있습니다."),
            ("shorts_3", "비개발자의 아이디어가 있어도 직접 구현할 수 있다고 생각했습니다."),
            ("threads_1", "문제마다 수정을 반복하면 해결할 수 있습니다."),
            ("threads_2", "직접 전달하며 제작했던 시도가 큰 도움이 되었습니다."),
            ("threads_3", "개발자도 코딩도 몰랐지만 스스로 정리하며 만들어갔습니다."),
            ("threads_4", "완벽할 때까지 기다릴 필요는 없다는 것을 경험으로 배웠다."),
            ("threads_5", "시도를 통해 배울 수 있어 기다릴 필요는 없다는 것을 배웠습니다."),
        ]
        for label, body in cases:
            with self.subTest(label=label):
                rewritten = replace(self.draft, body=body)
                result = RewriteService(MockRewriteProvider(rewritten)).rewrite(self.knowledge, self.draft)
                self.assertEqual(result.validation_status, "valid", f"{label} failed: {result.validation_errors}")

    def test_experience_style_rejects_third_person_summary(self):
        # 경험형 콘텐츠에서 3인칭 요약체 및 AI 메타 보고 표현 차단 검증
        third_person_cases = [
            "작성자는 직접 전달하며 제작했다는 경험을 남겼습니다.",
            "저자는 이 과정에서 큰 교훈을 얻었다고 합니다.",
            "원문에서는 ChatGPT를 활용했다고 설명합니다.",
            "글쓴이는 실패를 두려워하지 않고 도전했습니다.",
            "이 글은 비개발자가 앱을 만든 경험을 다룹니다.",
            "작성자의 설명에 따르면 다음과 같습니다.",
        ]
        for body in third_person_cases:
            with self.subTest(body=body):
                rewritten = replace(self.draft, body=body)
                result = RewriteService(MockRewriteProvider(rewritten)).rewrite(self.knowledge, self.draft)
                self.assertEqual(result.validation_status, "invalid")
                self.assertTrue(
                    any("3인칭 요약체" in error or "스타일" in error for error in result.validation_errors),
                    f"Expected style error in {result.validation_errors}",
                )

    def test_experience_style_allows_first_person_and_direct_narrative(self):
        # 1인칭 직접 서술 및 담백한 실행형 문장은 통과 검증
        first_person_cases = [
            "내가 직접 ChatGPT로 기획을 잡고 앱을 만들었다.",
            "직접 부딪혀보니 처음부터 완벽할 필요는 없었습니다.",
            "문제가 생기면 수정하고 다시 테스트하며 배웠습니다.",
        ]
        for body in first_person_cases:
            with self.subTest(body=body):
                rewritten = replace(self.draft, body=body)
                result = RewriteService(MockRewriteProvider(rewritten)).rewrite(self.knowledge, self.draft)
                self.assertEqual(result.validation_status, "valid", f"Unexpected error: {result.validation_errors}")

    def test_unmentioned_fact_risk_terms_fail_validation(self):
        for term in ("매출", "수익", "투자", "계약", "수상"):
            with self.subTest(term=term):
                rewritten = replace(self.draft, body=f"그 결과 높은 {term}을 달성했습니다.")
                result = RewriteService(MockRewriteProvider(rewritten)).rewrite(self.knowledge, self.draft)
                self.assertEqual(result.validation_status, "invalid")
                self.assertTrue(any("사실 범위를 넓히는 표현" in error for error in result.validation_errors))


class LLMRewriteExperimentTests(unittest.TestCase):
    KNOWLEDGE_PATH = Path(__file__).parents[1] / "data" / "tak_brain_knowledge.json"

    def setUp(self) -> None:
        records = load_knowledge_records(self.KNOWLEDGE_PATH)
        self.knowledge = next(record for record in records if record.id == "knowledge-da6ddf5aa459")
        self.draft = generate_content_bundle(self.knowledge).blog

    def test_provider_requires_explicit_environment_configuration(self):
        with self.assertRaises(LLMConfigurationError):
            OpenAICompatibleRewriteProvider.from_environment({})

    def test_http_error_exposes_only_safe_openai_error_fields(self):
        body = BytesIO(
            json.dumps(
                {
                    "error": {
                        "message": "Unsupported parameter: temperature",
                        "type": "invalid_request_error",
                        "code": "unsupported_parameter",
                        "param": "temperature",
                        "internal": "must not be exposed",
                    }
                }
            ).encode("utf-8")
        )

        with self.assertRaises(LLMResponseError) as raised:
            with mock.patch(
                "content_engine.llm_provider.urlopen",
                side_effect=HTTPError("https://llm.example.test", 400, "Bad Request", {}, body),
            ):
                _http_transport(
                    "https://llm.example.test",
                    {"Authorization": "Bearer secret-key"},
                    {"model": "test-model", "messages": []},
                    30.0,
                )

        message = str(raised.exception)
        self.assertIn("LLM HTTP 400", message)
        self.assertIn("message=Unsupported parameter: temperature", message)
        self.assertIn("type=invalid_request_error", message)
        self.assertIn("code=unsupported_parameter", message)
        self.assertIn("param=temperature", message)
        self.assertNotIn("secret-key", message)
        self.assertNotIn("internal", message)

    def test_provider_uses_openai_compatible_request_without_network(self):
        calls = []

        def transport(endpoint, headers, payload, timeout_seconds):
            calls.append((endpoint, headers, payload, timeout_seconds))
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "title": "왜 지금 시작해야 할까",
                                    "body": "코딩을 몰라도 시작할 수 있다는 이야기를 자연스럽게 풀어냅니다.",
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            }

        provider = OpenAICompatibleRewriteProvider.from_environment(
            {
                "TAK_MEDIA_LLM_API_KEY": "test-key",
                "TAK_MEDIA_LLM_ENDPOINT": "https://llm.example.test/v1/chat/completions",
                "TAK_MEDIA_LLM_MODEL": "test-model",
            },
            transport=transport,
        )
        result = RewriteService(provider).rewrite(self.knowledge, self.draft)

        self.assertEqual(result.validation_status, "valid")
        self.assertEqual(result.rewritten_draft.title, "왜 지금 시작해야 할까")
        self.assertEqual(len(calls), 1)
        endpoint, headers, payload, timeout_seconds = calls[0]
        self.assertEqual(endpoint, "https://llm.example.test/v1/chat/completions")
        self.assertEqual(headers["Authorization"], "Bearer test-key")
        self.assertEqual(payload["model"], "test-model")
        self.assertNotIn("temperature", payload)
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertEqual(timeout_seconds, 30.0)
        self.assertIn(self.knowledge.source_url, payload["messages"][1]["content"])
        self.assertIn(self.knowledge.evidence[0], payload["messages"][1]["content"])

    def test_experiment_script_defaults_to_network_free_dry_run(self):
        script = Path(__file__).parents[1] / "scripts" / "experiment_llm_rewrite.py"
        result = subprocess.run(
            [sys.executable, str(script)],
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertIn("dry-run: knowledge-da6ddf5aa459", result.stdout)
        self.assertIn("drafts: 9 (Blog 1, Shorts 3, Threads 5)", result.stdout)
        self.assertIn("네트워크 호출 없음", result.stdout)

    def test_prompt_contract_includes_validator_fact_boundary(self):
        captured = {}

        def transport(endpoint, headers, payload, timeout_seconds):
            captured["payload"] = payload
            user_prompt = json.loads(payload["messages"][1]["content"])
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(user_prompt["original_draft"], ensure_ascii=False)
                        }
                    }
                ]
            }

        provider = OpenAICompatibleRewriteProvider.from_environment(
            {
                "TAK_MEDIA_LLM_API_KEY": "test-key",
                "TAK_MEDIA_LLM_ENDPOINT": "https://llm.example.test/v1/chat/completions",
                "TAK_MEDIA_LLM_MODEL": "test-model",
            },
            transport=transport,
        )
        result = RewriteService(provider).rewrite(self.knowledge, self.draft)
        system_prompt = captured["payload"]["messages"][0]["content"]
        user_prompt = json.loads(captured["payload"]["messages"][1]["content"])

        self.assertEqual(result.validation_status, "valid")
        self.assertIn("Never add, infer, amplify", system_prompt)
        self.assertIn("first person", system_prompt)
        self.assertIn("작성자는", system_prompt)
        self.assertEqual(user_prompt["platform"], "blog")
        self.assertIn("새 사실·숫자·사람·기관·상품", user_prompt["prohibited_changes"])
        self.assertIn("법률·규정 판단", user_prompt["prohibited_changes"])
        self.assertIn("3인칭 요약체", user_prompt["prohibited_changes"])
        self.assertIn("1인칭 직접 서술", user_prompt["allowed_changes"])
        self.assertIn("source_url, evidence, 근거 단위 추적 정보", user_prompt["validation_requirements"])
        self.assertEqual(user_prompt["approved_knowledge_facts"]["experience"], self.knowledge.experience)

    def test_mock_llm_rewrites_all_nine_knowledge_001_drafts(self):
        calls = []

        def transport(endpoint, headers, payload, timeout_seconds):
            calls.append(payload)
            user_prompt = json.loads(payload["messages"][1]["content"])
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(user_prompt["original_draft"], ensure_ascii=False)
                        }
                    }
                ]
            }

        provider = OpenAICompatibleRewriteProvider.from_environment(
            {
                "TAK_MEDIA_LLM_API_KEY": "test-key",
                "TAK_MEDIA_LLM_ENDPOINT": "https://llm.example.test/v1/chat/completions",
                "TAK_MEDIA_LLM_MODEL": "test-model",
            },
            transport=transport,
        )
        bundle = generate_content_bundle(self.knowledge)
        drafts = (bundle.blog, *bundle.shorts, *bundle.threads)
        results = [RewriteService(provider).rewrite(self.knowledge, draft) for draft in drafts]
        prompts = [json.loads(call["messages"][1]["content"]) for call in calls]

        self.assertEqual(len(results), 9)
        self.assertTrue(all(result.validation_status == "valid" for result in results))
        self.assertEqual([prompt["platform"] for prompt in prompts], ["blog", "shorts", "shorts", "shorts", "threads", "threads", "threads", "threads", "threads"])
        self.assertTrue(all(prompt["source_url"] == self.knowledge.source_url for prompt in prompts))
        self.assertTrue(all(tuple(prompt["evidence"]) == self.knowledge.evidence for prompt in prompts))

    def test_finance_prompt_preserves_author_observation_boundary(self):
        records = load_knowledge_records(self.KNOWLEDGE_PATH)
        finance = next(record for record in records if record.id == "knowledge-e1cc05264953")
        finance_draft = generate_content_bundle(finance).blog
        captured = {}

        def transport(endpoint, headers, payload, timeout_seconds):
            captured["payload"] = payload
            user_prompt = json.loads(payload["messages"][1]["content"])
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(user_prompt["original_draft"], ensure_ascii=False)
                        }
                    }
                ]
            }

        provider = OpenAICompatibleRewriteProvider.from_environment(
            {
                "TAK_MEDIA_LLM_API_KEY": "test-key",
                "TAK_MEDIA_LLM_ENDPOINT": "https://llm.example.test/v1/chat/completions",
                "TAK_MEDIA_LLM_MODEL": "test-model",
            },
            transport=transport,
        )
        result = RewriteService(provider).rewrite(finance, finance_draft)
        system_prompt = captured["payload"]["messages"][0]["content"]
        user_prompt = json.loads(captured["payload"]["messages"][1]["content"])

        self.assertEqual(result.validation_status, "valid")
        self.assertEqual(user_prompt["article_type"], "finance")
        self.assertIn("author's observation and official institution criteria", system_prompt)
        self.assertIn("금융기관 공식 기준으로의 확대", user_prompt["prohibited_changes"])
        self.assertIn("공식 기준 비해석 문구", user_prompt["validation_requirements"])


if __name__ == "__main__":
    unittest.main()
