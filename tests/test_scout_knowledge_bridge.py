"""tak_scout.knowledge_bridge 검증.

외부 자료의 사실(SOURCE FACT/SOURCE URL)과 티몽의 의견(USER ANGLE/USER ORIGINAL
THOUGHT)이 KNOWLEDGE evidence에 명확히 구분되어 남는지, 답변하지 않은 후보는
KNOWLEDGE로 넘어가지 않는지를 검증한다.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tak_brain import KnowledgeRecord
from tak_scout.answers import InterviewAnswer
from tak_scout.collector import save_daily_pack_json
from tak_scout.knowledge_bridge import append_scout_knowledge, build_knowledge_from_interview
from tak_scout.models import ScoutCandidate


CANDIDATE = ScoutCandidate(
    scout_id="scout-abc123",
    title="기준금리 동결 소식",
    summary="중앙은행이 이번 달 기준금리를 동결했다.",
    source_url="https://example.test/news/1",
    published_at="2026-09-10T00:00:00+00:00",
    source_name="테스트 뉴스",
    category="finance",
)


class BuildKnowledgeFromInterviewTests(unittest.TestCase):
    def test_abc_answer_produces_user_angle_evidence(self):
        answer = InterviewAnswer.create(CANDIDATE.scout_id, "A")

        knowledge = build_knowledge_from_interview(CANDIDATE, answer)

        self.assertIsInstance(knowledge, KnowledgeRecord)
        self.assertEqual(knowledge.knowledge_review_status, "pending")
        self.assertEqual(knowledge.source_url, CANDIDATE.source_url)
        self.assertEqual(knowledge.source_raw_id, CANDIDATE.scout_id)
        self.assertTrue(any(item.startswith("SOURCE FACT:") for item in knowledge.evidence))
        self.assertTrue(any(item.startswith("SOURCE URL:") for item in knowledge.evidence))
        self.assertTrue(any(item.startswith("USER ANGLE:") for item in knowledge.evidence))
        self.assertFalse(any(item.startswith("USER ORIGINAL THOUGHT:") for item in knowledge.evidence))
        self.assertIsNone(knowledge.confidence)
        self.assertEqual(knowledge.inference_method, "rule_based_template")

    def test_option_d_produces_user_original_thought_evidence(self):
        answer = InterviewAnswer.create(CANDIDATE.scout_id, "D", "나는 이 정책이 시기상조라고 본다")

        knowledge = build_knowledge_from_interview(CANDIDATE, answer)

        evidence_text = " ".join(knowledge.evidence)
        self.assertIn("USER ORIGINAL THOUGHT: 나는 이 정책이 시기상조라고 본다", evidence_text)
        self.assertNotIn("USER ANGLE:", evidence_text)
        self.assertEqual(knowledge.opinion, "나는 이 정책이 시기상조라고 본다")

    def test_source_fact_and_user_angle_are_kept_separate_fields(self):
        answer = InterviewAnswer.create(CANDIDATE.scout_id, "B")
        knowledge = build_knowledge_from_interview(CANDIDATE, answer)

        self.assertEqual(knowledge.factual_information, CANDIDATE.summary)
        self.assertNotEqual(knowledge.opinion, knowledge.factual_information)

    def test_mismatched_scout_id_raises(self):
        other_answer = InterviewAnswer.create("scout-other", "A")
        with self.assertRaises(ValueError):
            build_knowledge_from_interview(CANDIDATE, other_answer)

    def test_finance_category_maps_to_domain_but_not_article_type(self):
        """6-04: category(=RSS 소스의 블랭킷 카테고리)는 domain/category 필드에는
        그대로 반영되지만(참고 정보), article_type에는 더 이상 영향을 주지 않는다 -
        source category만으로 "이 기사가 실제로 금융/대출 내용을 다룬다"고 단정할 수
        없기 때문이다(docs/6-04_*.md, knowledge-scout-b28b782b2a33 실제 재현 사례).
        SCOUT 경로에는 실제 본문을 분석하는 분류기(tak_brain.article_types.
        ArticleTypeClassifier)가 적용되지 않으므로, article_type은 항상 None이다."""
        answer = InterviewAnswer.create(CANDIDATE.scout_id, "C")
        knowledge = build_knowledge_from_interview(CANDIDATE, answer)
        self.assertIsNone(knowledge.article_type)
        # category/domain은 그대로 "금융"으로 남아야 한다 - blog_publish_pack.py의
        # is_review_required()가 이 값으로 사람 확인 필요 여부를 독립적으로 판정한다.
        self.assertEqual(knowledge.domain, "금융")
        self.assertEqual(knowledge.category, "금융")

    def test_knowledge_id_is_deterministic_for_same_answer(self):
        answer1 = InterviewAnswer.create(CANDIDATE.scout_id, "A")
        answer2 = InterviewAnswer.create(CANDIDATE.scout_id, "A")  # answered_at 값만 다름
        knowledge1 = build_knowledge_from_interview(CANDIDATE, answer1)
        knowledge2 = build_knowledge_from_interview(CANDIDATE, answer2)
        self.assertEqual(knowledge1.id, knowledge2.id)


class AppendScoutKnowledgeTests(unittest.TestCase):
    def _write_daily_pack(self, directory: Path, candidates: list[ScoutCandidate]) -> Path:
        path = Path(directory) / "daily.json"
        save_daily_pack_json(candidates, path)
        return path

    def test_unanswered_candidate_is_not_added_to_knowledge(self):
        with tempfile.TemporaryDirectory() as directory:
            daily_pack_path = self._write_daily_pack(directory, [CANDIDATE])
            answers_path = Path(directory) / "answers.json"  # 답변 없음
            knowledge_path = Path(directory) / "knowledge.json"

            created, skipped_unanswered, duplicates = append_scout_knowledge(
                daily_pack_path, answers_path, knowledge_path
            )

            self.assertEqual((created, skipped_unanswered, duplicates), (0, 1, 0))
            self.assertFalse(knowledge_path.exists() and json.loads(knowledge_path.read_text(encoding="utf-8")))

    def test_answered_candidate_is_added_as_pending_knowledge(self):
        with tempfile.TemporaryDirectory() as directory:
            daily_pack_path = self._write_daily_pack(directory, [CANDIDATE])
            answers_path = Path(directory) / "answers.json"
            answers_path.write_text(
                json.dumps([InterviewAnswer.create(CANDIDATE.scout_id, "A").to_dict()], ensure_ascii=False),
                encoding="utf-8",
            )
            knowledge_path = Path(directory) / "knowledge.json"

            created, skipped_unanswered, duplicates = append_scout_knowledge(
                daily_pack_path, answers_path, knowledge_path
            )

            self.assertEqual((created, skipped_unanswered, duplicates), (1, 0, 0))
            saved = json.loads(knowledge_path.read_text(encoding="utf-8"))
            self.assertEqual(len(saved), 1)
            self.assertEqual(saved[0]["knowledge_review_status"], "pending")

    def test_running_twice_does_not_duplicate(self):
        with tempfile.TemporaryDirectory() as directory:
            daily_pack_path = self._write_daily_pack(directory, [CANDIDATE])
            answers_path = Path(directory) / "answers.json"
            answers_path.write_text(
                json.dumps([InterviewAnswer.create(CANDIDATE.scout_id, "A").to_dict()], ensure_ascii=False),
                encoding="utf-8",
            )
            knowledge_path = Path(directory) / "knowledge.json"

            append_scout_knowledge(daily_pack_path, answers_path, knowledge_path)
            created, skipped_unanswered, duplicates = append_scout_knowledge(
                daily_pack_path, answers_path, knowledge_path
            )

            self.assertEqual((created, skipped_unanswered, duplicates), (0, 0, 1))
            saved = json.loads(knowledge_path.read_text(encoding="utf-8"))
            self.assertEqual(len(saved), 1)

    def test_existing_knowledge_from_other_pipeline_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            daily_pack_path = self._write_daily_pack(directory, [CANDIDATE])
            answers_path = Path(directory) / "answers.json"
            answers_path.write_text(
                json.dumps([InterviewAnswer.create(CANDIDATE.scout_id, "A").to_dict()], ensure_ascii=False),
                encoding="utf-8",
            )
            knowledge_path = Path(directory) / "knowledge.json"
            existing_record = {"id": "knowledge-existing", "source_raw_id": "raw-1", "source_url": "https://x"}
            knowledge_path.write_text(json.dumps([existing_record], ensure_ascii=False), encoding="utf-8")

            append_scout_knowledge(daily_pack_path, answers_path, knowledge_path)

            saved = json.loads(knowledge_path.read_text(encoding="utf-8"))
            ids = {item["id"] for item in saved}
            self.assertIn("knowledge-existing", ids)
            self.assertEqual(len(saved), 2)

    def test_only_answered_subset_is_added_when_multiple_candidates(self):
        second_candidate = ScoutCandidate(
            scout_id="scout-def456",
            title="다른 소식",
            summary="다른 요약",
            source_url="https://example.test/news/2",
            published_at="",
            source_name="테스트 뉴스",
            category="기타",
        )
        with tempfile.TemporaryDirectory() as directory:
            daily_pack_path = self._write_daily_pack(directory, [CANDIDATE, second_candidate])
            answers_path = Path(directory) / "answers.json"
            answers_path.write_text(
                json.dumps([InterviewAnswer.create(CANDIDATE.scout_id, "A").to_dict()], ensure_ascii=False),
                encoding="utf-8",
            )
            knowledge_path = Path(directory) / "knowledge.json"

            created, skipped_unanswered, duplicates = append_scout_knowledge(
                daily_pack_path, answers_path, knowledge_path
            )

            self.assertEqual((created, skipped_unanswered, duplicates), (1, 1, 0))


if __name__ == "__main__":
    unittest.main()
