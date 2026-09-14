"""tak_scout.answers 검증."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from tak_scout.answers import InterviewAnswer, InterviewAnswerError, load_answers, save_answers, upsert_answer


class InterviewAnswerCreateTests(unittest.TestCase):
    def test_abc_option_does_not_require_custom_answer(self):
        answer = InterviewAnswer.create("scout-1", "a")
        self.assertEqual(answer.selected_option, "A")
        self.assertEqual(answer.custom_answer, "")
        self.assertTrue(answer.answered_at)

    def test_option_d_requires_custom_answer(self):
        with self.assertRaises(InterviewAnswerError):
            InterviewAnswer.create("scout-1", "D", "")

    def test_option_d_with_custom_answer_succeeds(self):
        answer = InterviewAnswer.create("scout-1", "d", "내가 직접 입력한 생각")
        self.assertEqual(answer.selected_option, "D")
        self.assertEqual(answer.custom_answer, "내가 직접 입력한 생각")

    def test_invalid_option_is_rejected(self):
        with self.assertRaises(InterviewAnswerError):
            InterviewAnswer.create("scout-1", "E")

    def test_missing_scout_id_is_rejected(self):
        with self.assertRaises(InterviewAnswerError):
            InterviewAnswer.create("", "A")


class AnswersFileTests(unittest.TestCase):
    def test_load_answers_returns_empty_list_when_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "answers.json"
            self.assertEqual(load_answers(path), [])

    def test_save_and_load_round_trip(self):
        answers = [InterviewAnswer.create("scout-1", "A"), InterviewAnswer.create("scout-2", "D", "내 생각")]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "answers.json"
            save_answers(answers, path)
            loaded = load_answers(path)
            self.assertEqual(loaded, answers)

    def test_upsert_overwrites_existing_scout_id(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "answers.json"
            upsert_answer(path, InterviewAnswer.create("scout-1", "A"))
            upsert_answer(path, InterviewAnswer.create("scout-1", "B"))

            loaded = load_answers(path)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].selected_option, "B")

    def test_upsert_appends_new_scout_id(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "answers.json"
            upsert_answer(path, InterviewAnswer.create("scout-1", "A"))
            upsert_answer(path, InterviewAnswer.create("scout-2", "B"))

            loaded = load_answers(path)
            self.assertEqual({a.scout_id for a in loaded}, {"scout-1", "scout-2"})

    def test_load_answers_rejects_wrong_structure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "answers.json"
            path.write_text('{"not": "a list"}', encoding="utf-8")
            with self.assertRaises(InterviewAnswerError):
                load_answers(path)


if __name__ == "__main__":
    unittest.main()
