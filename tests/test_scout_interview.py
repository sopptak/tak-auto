"""tak_scout.interview 검증."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from tak_scout.interview import (
    build_interview_question,
    build_interview_questions,
    load_questions,
    render_questions_markdown,
    save_questions_json,
    save_questions_markdown,
)
from tak_scout.models import ScoutCandidate


class BuildInterviewQuestionTests(unittest.TestCase):
    def test_creates_four_options_with_d_meaning_custom_input(self):
        candidate = ScoutCandidate("scout-1", "금리 인상 소식", "요약", "https://example.test/1", "", "소스", "finance")

        question = build_interview_question(candidate)

        self.assertIn(candidate.title, question.question)
        self.assertTrue(question.option_a.startswith("A."))
        self.assertTrue(question.option_b.startswith("B."))
        self.assertTrue(question.option_c.startswith("C."))
        self.assertTrue(question.option_d.startswith("D."))
        self.assertIn("직접 입력", question.option_d)

    def test_category_influences_subject_wording(self):
        finance = ScoutCandidate("scout-1", "제목", "", "https://example.test/1", "", "소스", "finance")
        other = ScoutCandidate("scout-2", "제목", "", "https://example.test/2", "", "소스", "기타")

        finance_question = build_interview_question(finance)
        other_question = build_interview_question(other)

        self.assertIn("경제 이슈", finance_question.question)
        self.assertNotEqual(finance_question.question, other_question.question)

    def test_build_interview_questions_preserves_order(self):
        candidates = [
            ScoutCandidate(f"scout-{i}", f"제목{i}", "", f"https://example.test/{i}", "", "소스", "기타")
            for i in range(3)
        ]
        questions = build_interview_questions(candidates)
        self.assertEqual([q.scout_id for q in questions], ["scout-0", "scout-1", "scout-2"])


class QuestionsRoundTripTests(unittest.TestCase):
    def test_save_and_load_json_round_trip(self):
        candidate = ScoutCandidate("scout-1", "제목", "요약", "https://example.test/1", "", "소스", "기타")
        questions = build_interview_questions([candidate])

        with tempfile.TemporaryDirectory() as directory:
            json_path = Path(directory) / "questions.json"
            md_path = Path(directory) / "questions.md"
            save_questions_json(questions, json_path)
            save_questions_markdown(questions, md_path)

            loaded = load_questions(json_path)
            self.assertEqual(loaded, questions)

            md_text = md_path.read_text(encoding="utf-8")
            self.assertIn("# TAK INTERVIEW 질문", md_text)
            self.assertIn("scout_id: scout-1", md_text)

    def test_render_markdown_handles_empty_list(self):
        text = render_questions_markdown([])
        self.assertIn("생성된 질문이 없습니다.", text)


if __name__ == "__main__":
    unittest.main()
