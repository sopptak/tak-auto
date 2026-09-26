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
from content_engine.models import BlogDraft, ContentBundle
from content_engine.rewrite import MockRewriteProvider, RewriteService, RewriteValidator
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


class InterviewQAFormatTests(unittest.TestCase):
    """5-10 Phase 4-2 수정 #1: tak_scout 인터뷰가 만드는 "Q{n}. .../A{n}. ..."
    형식의 reusable_principle이 문장 분리와 충돌하지 않는지 검증한다(Phase 4-1에서
    실제 운영 KNOWLEDGE로 "Q1"이 label 조각으로 잘못 선택되는 버그가 재현됨).
    """

    def _interview_knowledge(self, reusable_principle: str) -> KnowledgeRecord:
        return KnowledgeRecord(
            id="knowledge-interview-qa",
            source_url="https://example.test/rent",
            title="임대료 상승 관련 기사",
            article_type="finance",
            knowledge_type="의견",
            lesson="The cost of renting is expected to rise by 4% or 5% a year by December.",
            reusable_principle=reusable_principle,
            evidence=("SOURCE FACT: ...",),
            knowledge_review_status="approved",
        )

    def test_single_turn_qa_format_produces_no_label_fragments(self):
        knowledge = self._interview_knowledge(
            "Q1. 최근 임대료 인상이 계속되고 있는데, 이에 대한 귀하의 생각은 무엇인가요?\n"
            "A1. 임대료가 계속 오르는 흐름을 보면서 가장 걱정되는 건, 소득은 물가만큼 안 오르는데 "
            "주거비만 먼저 뛴다는 점이다. 작년에 지인이 재계약 시점에 월세를 10% 넘게 올려달라는 "
            "요구를 받고, 결국 대중교통이 불편한 외곽으로 이사한 걸 옆에서 지켜봤다."
        )
        brief = build_content_brief(knowledge)
        principle_units = [u for u in brief.evidence_units if u.field_name == "reusable_principle"]

        self.assertTrue(principle_units, "reusable_principle evidence unit이 생성되어야 합니다.")
        for unit in principle_units:
            self.assertNotRegex(unit.text, r"^[AQ]\d+\.?$")  # 1. 깨진 label-only fragment 없음
            self.assertNotIn("무엇인가요", unit.text)  # 질문 문장이 섞이지 않음

    def test_qa_based_reusable_principle_is_picked_as_real_sentence(self):
        knowledge = self._interview_knowledge(
            "Q1. 이 소재에 대해 어떻게 생각하시나요?\n"
            "A1. 임대료 상승은 결국 세입자의 실질 소득 감소로 이어질 수 있어 우려된다."
        )
        bundle = generate_content_bundle(knowledge)

        self.assertEqual(bundle.status, "complete")
        self.assertIsNotNone(bundle.blog)
        # 2. Q/A 기반 reusable_principle이 정상적으로(사용자의 실제 답변으로) 선택된다.
        self.assertIn(
            "임대료 상승은 결국 세입자의 실질 소득 감소로 이어질 수 있어 우려된다",
            bundle.blog.body,
        )
        self.assertNotIn('"Q1"', bundle.blog.body)
        self.assertNotIn("어떻게 생각하시나요", bundle.blog.body)

    def test_multi_turn_qa_format_extracts_only_answers_in_order(self):
        knowledge = self._interview_knowledge(
            "Q1. 첫 번째 질문입니다.\nA1. 첫 번째 답변입니다.\n\n"
            "Q2. 두 번째 질문입니다.\nA2. 두 번째 답변입니다."
        )
        brief = build_content_brief(knowledge)
        texts = [u.text for u in brief.evidence_units if u.field_name == "reusable_principle"]

        self.assertEqual(texts, ["첫 번째 답변입니다.", "두 번째 답변입니다."])

    def test_non_qa_field_sentence_splitting_is_unchanged(self):
        # 3. Q/A 포맷이 아닌 일반 텍스트는 기존 문장 분리 동작 그대로 유지된다.
        knowledge = self._interview_knowledge("일반적인 원칙 문장입니다. 두 번째 문장도 있습니다.")
        brief = build_content_brief(knowledge)
        texts = [u.text for u in brief.evidence_units if u.field_name == "reusable_principle"]

        self.assertEqual(texts, ["일반적인 원칙 문장입니다.", "두 번째 문장도 있습니다."])


class MonthNumberFalsePositiveTests(unittest.TestCase):
    """5-10 Phase 4-2 수정 #2: 날짜의 영→한 표기 변환(예: December -> 12월)이
    RewriteValidator._new_number_errors에서 "새 숫자 추가"로 오탐되지 않는지
    검증한다(Phase 4-1에서 "by December" -> "12월"이 실제로 오탐된 것을 재현).
    """

    @staticmethod
    def _draft(body: str) -> BlogDraft:
        return BlogDraft(title="", body=body, source_url="https://example.test", evidence=())

    def test_december_to_month_12_is_allowed(self):
        source = "The cost of renting is expected to rise by 4% or 5% a year by December."
        errors = RewriteValidator._new_number_errors(
            source, self._draft("12월까지 4%에서 5% 상승할 것으로 예상됩니다.")
        )
        self.assertEqual(errors, ())

    def test_january_to_month_1_is_allowed(self):
        source = "The meeting is scheduled for January."
        errors = RewriteValidator._new_number_errors(source, self._draft("1월에 회의가 예정되어 있습니다."))
        self.assertEqual(errors, ())

    def test_march_to_month_3_is_allowed(self):
        source = "The report is due in March."
        errors = RewriteValidator._new_number_errors(source, self._draft("3월에 보고서가 마감됩니다."))
        self.assertEqual(errors, ())

    def test_december_with_unrelated_new_number_still_fails(self):
        source = "The rate is expected to rise by December."
        errors = RewriteValidator._new_number_errors(source, self._draft("12월에 30% 상승할 것으로 예상됩니다."))
        self.assertTrue(any("30" in error for error in errors))
        self.assertFalse(any(error.endswith(": 12") for error in errors))

    def test_number_matching_month_number_but_not_a_date_still_fails(self):
        # "12"가 "12월"(날짜)이 아니라 금액 등 다른 새 사실로 쓰이면 여전히 거부돼야 한다 -
        # 월 이름이 source에 있다고 해서 숫자 12를 광범위하게 허용하지 않는다.
        source = "The rate is expected to rise by December."
        errors = RewriteValidator._new_number_errors(source, self._draft("이번 분기 매출이 12억원입니다."))
        self.assertTrue(any("12" in error for error in errors))

    def test_existing_new_number_insertion_still_fails_without_month_name(self):
        # source에 월 이름이 전혀 없으면 이번 수정의 영향을 받지 않고 기존 동작 그대로다.
        errors = RewriteValidator._new_number_errors("Sales rose by 5%.", self._draft("Sales rose by 12%."))
        self.assertTrue(any("12" in error for error in errors))


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

        # PASS 케이스: 동일한 부정 의미의 활용형 및 자연스러운 안전 경계 표현
        pass_cases = [
            "금융기관의 공식 심사 기준으로 해석하지 않습니다.",
            "금융기관의 공식 심사 기준으로 해석하지 않는다.",
            "금융기관의 공식 심사 기준으로 해석하지 않으며, 개인의 설명입니다.",
            "금융기관의 공식 기준으로 확대하지 않는다.",
            "금융기관의 공식 기준으로 확대해석하지 않습니다.",
            "은행의 공식 기준이라고 단정하는 내용이 아니다.",
            "원문 작성자의 설명이며 공식 기준으로 해석하지 않는다.",
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

        # FAIL 케이스: 긍정 또는 공식 기준 확대/주장 표현
        fail_cases = [
            "금융기관의 공식 심사 기준으로 해석할 수 있습니다.",
            "금융기관의 공식 심사 기준입니다.",
            "금융기관의 공식 심사 기준으로 볼 수 있습니다.",
            "금융기관의 공식 심사 기준에 해당합니다.",
            "금융기관이 반드시 이렇게 심사한다.",
            "은행의 공식 심사 기준이다.",
            "금융기관에서는 이 기준을 적용한다.",
            "은행이 가장 먼저 보는 공식 기준이다.",
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
                    any(
                        "공식 기준" in err
                        or "공식 심사 기준" in err
                        or "사실 범위를 넓히는 표현" in err
                        for err in result.validation_errors
                    ),
                    f"Expected finance/fact scope error in {result.validation_errors}",
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

    def test_threads_draft_exceeding_500_chars_is_rejected(self):
        threads_draft = generate_content_bundle(self.knowledge).threads[0]
        rewritten = replace(threads_draft, body="가" * 501)
        result = RewriteService(MockRewriteProvider(rewritten)).rewrite(self.knowledge, threads_draft)

        self.assertEqual(result.validation_status, "invalid")
        self.assertTrue(any("Threads text exceeds 500 characters: 501" in error for error in result.validation_errors))

    def test_generated_thread_draft_body_is_within_500_chars(self):
        long_knowledge = KnowledgeRecord(
            id="knowledge-long-threads",
            source_url="https://example.test/long",
            title="아주 긴 내용의 KNOWLEDGE",
            article_type="experience",
            knowledge_type="경험",
            experience="가" * 300 + ".",
            problem="나" * 300 + ".",
            action="다" * 300 + ".",
            result="라" * 300 + ".",
            lesson="마" * 300 + ".",
            reusable_principle="바" * 300 + ".",
            derived_insight="사" * 300 + ".",
            evidence=("원문 근거",),
            knowledge_review_status="approved",
        )
        bundle = generate_content_bundle(long_knowledge)
        for thread_draft in bundle.threads:
            self.assertLessEqual(len(thread_draft.body.strip()), 500)

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


class FinanceBoundaryPromptTests(unittest.TestCase):
    """5-10 Phase 4-3: 금융 Blog rewrite에서 안전 경계 문구가 LLM prompt에
    명시적으로(그대로 보존해야 할 문장으로) 전달되는지, 그리고 Validator의
    안전 기준은 전혀 낮아지지 않았는지 검증한다. 실제 네트워크는 쓰지 않는다.
    """

    KNOWLEDGE_PATH = Path(__file__).parents[1] / "data" / "tak_brain_knowledge.json"
    # find_finance_boundary_sentence는 content_engine.rewrite._SENTENCE_PATTERN
    # (r"[^.!?\n]+")으로 문장을 나누므로, 문장 끝 마침표는 포함하지 않는다 -
    # 이는 RewriteValidator의 기존 문장 분리 관례와 동일하다(예: _fact_scope_errors).
    BOUNDARY_SENTENCE = "이 글의 금융 관련 내용은 원문 작성자의 설명이며, 금융기관의 공식 심사 기준으로 해석하지 않습니다"

    def setUp(self) -> None:
        records = load_knowledge_records(self.KNOWLEDGE_PATH)
        self.finance = next(r for r in records if r.id == "knowledge-e1cc05264953")
        self.finance_draft = generate_content_bundle(self.finance).blog
        self.assertIn(self.BOUNDARY_SENTENCE, self.finance_draft.body)

        self.non_finance = next(r for r in records if r.id == "knowledge-da6ddf5aa459")
        self.non_finance_draft = generate_content_bundle(self.non_finance).blog

    def _provider(self, responder):
        captured: dict = {}

        def transport(endpoint, headers, payload, timeout_seconds):
            captured["payload"] = payload
            return responder(payload)

        provider = OpenAICompatibleRewriteProvider.from_environment(
            {
                "TAK_MEDIA_LLM_API_KEY": "test-key",
                "TAK_MEDIA_LLM_ENDPOINT": "https://llm.example.test/v1/chat/completions",
                "TAK_MEDIA_LLM_MODEL": "test-model",
            },
            transport=transport,
        )
        return provider, captured

    @staticmethod
    def _echo_original_draft(payload):
        user_prompt = json.loads(payload["messages"][1]["content"])
        return {"choices": [{"message": {"content": json.dumps(user_prompt["original_draft"], ensure_ascii=False)}}]}

    def test_finance_prompt_includes_boundary_sentence_verbatim_field(self):
        provider, captured = self._provider(self._echo_original_draft)
        RewriteService(provider).rewrite(self.finance, self.finance_draft)

        user_prompt = json.loads(captured["payload"]["messages"][1]["content"])
        system_prompt = captured["payload"]["messages"][0]["content"]
        self.assertEqual(user_prompt["finance_boundary_sentence_required_verbatim"], self.BOUNDARY_SENTENCE)
        self.assertIn("finance_boundary_sentence_required_verbatim", system_prompt)
        self.assertIn("character-for-character", system_prompt)

    # A. 금융 Blog rewrite에서 금융 경계 문구가 유지되는 경우 PASS
    def test_a_finance_rewrite_preserving_boundary_sentence_passes(self):
        def responder(payload):
            user_prompt = json.loads(payload["messages"][1]["content"])
            boundary = user_prompt["finance_boundary_sentence_required_verbatim"]
            body = f"임대료가 계속 오르는 흐름이 걱정됩니다. {boundary}"
            return {"choices": [{"message": {"content": json.dumps({"title": "제목", "body": body}, ensure_ascii=False)}}]}

        provider, _ = self._provider(responder)
        result = RewriteService(provider).rewrite(self.finance, self.finance_draft)

        self.assertEqual(result.validation_status, "valid")
        self.assertIn(self.BOUNDARY_SENTENCE, result.rewritten_draft.body)

    # B. 금융 Blog rewrite에서 경계 문구가 삭제되면 기존 validator가 REJECT하는 안전성 유지
    def test_b_finance_rewrite_dropping_boundary_sentence_is_rejected(self):
        def responder(payload):
            body = "임대료가 계속 오르는 흐름이 걱정됩니다."  # 경계 문구 없음
            return {"choices": [{"message": {"content": json.dumps({"title": "제목", "body": body}, ensure_ascii=False)}}]}

        provider, captured = self._provider(responder)
        result = RewriteService(provider).rewrite(self.finance, self.finance_draft)

        self.assertEqual(result.validation_status, "invalid")
        self.assertTrue(any("공식 기준 비해석 경계" in error for error in result.validation_errors))
        # prompt에는 여전히 "그대로 보존하라"는 지시가 담겨 있었다(이번 수정이 검증을
        # 느슨하게 만든 게 아니라, LLM이 지시를 어긴 경우까지 여전히 잡아낸다).
        user_prompt = json.loads(captured["payload"]["messages"][1]["content"])
        self.assertIn("finance_boundary_sentence_required_verbatim", user_prompt)

    # C. 금융 Blog rewrite에서 경계 문구의 의미가 바뀌면 REJECT
    def test_c_finance_rewrite_altering_boundary_sentence_meaning_is_rejected(self):
        def responder(payload):
            body = "임대료가 계속 오르는 흐름이 걱정됩니다. 이는 금융기관의 공식 심사 기준입니다."
            return {"choices": [{"message": {"content": json.dumps({"title": "제목", "body": body}, ensure_ascii=False)}}]}

        provider, _ = self._provider(responder)
        result = RewriteService(provider).rewrite(self.finance, self.finance_draft)

        self.assertEqual(result.validation_status, "invalid")

    # D. 일반(비금융) Blog rewrite에는 금융 경계 문구 강제가 적용되지 않음
    def test_d_non_finance_prompt_has_no_boundary_field(self):
        provider, captured = self._provider(self._echo_original_draft)
        result = RewriteService(provider).rewrite(self.non_finance, self.non_finance_draft)

        self.assertEqual(result.validation_status, "valid")
        user_prompt = json.loads(captured["payload"]["messages"][1]["content"])
        self.assertNotIn("finance_boundary_sentence_required_verbatim", user_prompt)

    # F. 기존 Shorts/Threads rewrite 동작에 변화 없음(경계 문구 자체가 원본에 없으므로
    # 필드가 추가되지 않는다 - _criterion_blog에서만 경계 문구를 덧붙이기 때문)
    def test_f_finance_shorts_and_threads_prompts_unaffected(self):
        bundle = generate_content_bundle(self.finance)
        for draft in (*bundle.shorts, *bundle.threads):
            with self.subTest(platform=type(draft).__name__):
                provider, captured = self._provider(self._echo_original_draft)
                result = RewriteService(provider).rewrite(self.finance, draft)

                self.assertEqual(result.validation_status, "valid")
                user_prompt = json.loads(captured["payload"]["messages"][1]["content"])
                self.assertNotIn("finance_boundary_sentence_required_verbatim", user_prompt)


if __name__ == "__main__":
    unittest.main()
