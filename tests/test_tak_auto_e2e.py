"""TAK OPERATOR MVP(scripts/tak_auto.py) E2E 테스트.

scripts/tak_auto.run_operator를 통해 SCOUT -> 소재 선택 -> INTERVIEW -> BRAIN
(KNOWLEDGE) -> 승인 -> TAK MEDIA 전체 흐름이 실제로 끝까지 동작하는지 검증한다.

실제 RSS 네트워크나 실제 LLM/Threads API는 호출하지 않는다: RSS 응답은 fetch_rss를
patch해 대체하고, 사용자 입력은 스크립트된 답변 목록으로 대체하며, TAK MEDIA는
run_operator의 기본값(MockRewriteProvider, --execute 미지정)을 그대로 사용한다.
이 테스트는 Threads/Naver 실제 게시를 전혀 수행하지 않는다(run_operator 자체가
그런 호출을 하지 않는다).
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tak_brain.knowledge import load_knowledge_records
from tak_scout.answers import load_answers
from tak_scout.collector import build_daily_pack, load_daily_pack, save_daily_pack_json

from scripts.tak_auto import format_candidate_list, run_operator


FEED_XML = """<rss version="2.0"><channel>
<item>
  <title>중앙은행, 기준금리 동결 발표</title>
  <link>https://example.test/news/rate-hold</link>
  <description>중앙은행이 이번 회의에서 기준금리를 동결하기로 결정했다.</description>
  <pubDate>Thu, 10 Sep 2026 09:00:00 +0900</pubDate>
</item>
<item>
  <title>수도권 아파트 거래량 반등</title>
  <link>https://example.test/news/apartment-rebound</link>
  <description>수도권 아파트 거래량이 두 달 연속 늘었다.</description>
  <pubDate>Thu, 10 Sep 2026 10:00:00 +0900</pubDate>
</item>
</channel></rss>"""


def _scripted_input(answers: list[str]):
    iterator = iter(answers)

    def _input(_prompt: str) -> str:
        return next(iterator)

    return _input


class TakAutoOperatorE2ETests(unittest.TestCase):
    def _build_daily_pack(self, directory: Path) -> Path:
        sources = [{"name": "테스트 경제 뉴스", "url": "https://example.test/rss.xml", "category": "finance"}]
        with patch("tak_scout.collector.fetch_rss", return_value=FEED_XML):
            candidates, _ = build_daily_pack(sources, max_count=10)
        self.assertEqual(len(candidates), 2)
        daily_pack_path = directory / "tak_scout_daily.json"
        save_daily_pack_json(candidates, daily_pack_path)
        return daily_pack_path

    def test_full_flow_select_answer_approve_media(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            daily_pack_path = self._build_daily_pack(directory)
            answers_path = directory / "tak_interview_answers.json"
            knowledge_path = directory / "tak_brain_knowledge.json"
            media_output_path = directory / "tak_media_batch_operator.json"

            # 1번 소재 선택 -> D(직접 입력) -> 커스텀 의견 -> 승인(Y)
            input_func = _scripted_input(["1", "D", "이번 동결은 성장보다 물가를 더 우선한 결정으로 보인다", "Y"])

            printed: list[str] = []
            exit_code = run_operator(
                daily_pack_path=daily_pack_path,
                answers_path=answers_path,
                knowledge_path=knowledge_path,
                media_output_path=media_output_path,
                media_archive_path=directory / "tak_media_archive.json",
                execute=False,
                input_func=input_func,
                print_func=printed.append,
            )

            self.assertEqual(exit_code, 0)
            output_text = "\n".join(printed)

            # TAK INTERVIEW 답변이 저장되었는지
            self.assertTrue(answers_path.exists())

            # TAK BRAIN: KNOWLEDGE가 pending으로 생성된 뒤 승인(approved)까지 반영됐는지
            records = load_knowledge_records(knowledge_path)
            self.assertEqual(len(records), 1)
            record = records[0]
            self.assertEqual(record.knowledge_review_status, "approved")

            evidence_text = " ".join(record.evidence)
            self.assertIn("SOURCE FACT:", evidence_text)
            self.assertIn("SOURCE URL:", evidence_text)
            self.assertIn("USER ORIGINAL THOUGHT:", evidence_text)
            self.assertIn("이번 동결은 성장보다 물가를 더 우선한 결정으로 보인다", evidence_text)

            # TAK MEDIA: 1 KNOWLEDGE -> Blog 1 + Shorts 3 + Threads 5 = 9 Draft
            self.assertTrue(media_output_path.exists())
            self.assertIn("총 9건", output_text)
            self.assertIn("KNOWLEDGE 승인 완료", output_text)
            self.assertIn("결과:", output_text)

            # 이 흐름은 Threads/Naver 게시를 전혀 하지 않는다는 안내가 출력되는지
            self.assertIn("Threads 실제 게시/Naver Blog 게시는", output_text)

    def test_hold_does_not_run_media(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            daily_pack_path = self._build_daily_pack(directory)
            answers_path = directory / "tak_interview_answers.json"
            knowledge_path = directory / "tak_brain_knowledge.json"
            media_output_path = directory / "tak_media_batch_operator.json"

            # 2번 소재 선택 -> A 선택 -> 보류(N)
            input_func = _scripted_input(["2", "A", "N"])

            printed: list[str] = []
            exit_code = run_operator(
                daily_pack_path=daily_pack_path,
                answers_path=answers_path,
                knowledge_path=knowledge_path,
                media_output_path=media_output_path,
                media_archive_path=directory / "tak_media_archive.json",
                execute=False,
                input_func=input_func,
                print_func=printed.append,
            )

            self.assertEqual(exit_code, 0)
            records = load_knowledge_records(knowledge_path)
            self.assertEqual(len(records), 1)
            # 보류했으므로 pending 상태 그대로 유지되고, TAK MEDIA는 실행되지 않는다.
            self.assertEqual(records[0].knowledge_review_status, "pending")
            self.assertFalse(media_output_path.exists())


    def test_unanswered_candidate_has_no_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            daily_pack_path = self._build_daily_pack(directory)
            candidates = load_daily_pack(daily_pack_path)

            # 아직 아무도 답변하지 않은 상태(answered_scout_ids가 비어 있음)라면
            # 목록 어디에도 "[이미 답변함]"이 나오지 않는다.
            rendered = format_candidate_list(candidates, frozenset())
            self.assertNotIn("[이미 답변함]", rendered)

    def test_answered_candidate_shows_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            daily_pack_path = self._build_daily_pack(directory)
            candidates = load_daily_pack(daily_pack_path)
            first_scout_id = candidates[0].scout_id

            rendered = format_candidate_list(candidates, frozenset({first_scout_id}))
            lines = rendered.splitlines()
            first_candidate_line = next(line for line in lines if line.startswith("1. "))
            second_candidate_line = next(line for line in lines if line.startswith("2. "))
            self.assertIn("[이미 답변함]", first_candidate_line)
            self.assertNotIn("[이미 답변함]", second_candidate_line)

    def test_reselecting_answered_candidate_warns_and_reuses_upsert_logic(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            daily_pack_path = self._build_daily_pack(directory)
            answers_path = directory / "tak_interview_answers.json"
            knowledge_path = directory / "tak_brain_knowledge.json"
            media_output_path = directory / "tak_media_batch_operator.json"

            # 1회차: 1번 소재를 A로 답하고 보류(N) -> 답변 1건 저장됨
            first_input = _scripted_input(["1", "A", "N"])
            first_printed: list[str] = []
            exit_code_1 = run_operator(
                daily_pack_path=daily_pack_path,
                answers_path=answers_path,
                knowledge_path=knowledge_path,
                media_output_path=media_output_path,
                media_archive_path=directory / "tak_media_archive.json",
                execute=False,
                input_func=first_input,
                print_func=first_printed.append,
            )
            self.assertEqual(exit_code_1, 0)
            answers_after_first = load_answers(answers_path)
            self.assertEqual(len(answers_after_first), 1)
            self.assertEqual(answers_after_first[0].selected_option, "A")

            # 2회차: 같은 1번 소재를 다시 골라 B로 덮어쓰고 보류(N)
            # -> 목록에 [이미 답변함] 표시, 선택 시 경고 문구, 기존 upsert_answer가
            #    새 KNOWLEDGE를 중복 추가하지 않고 답변만 1건으로 유지되는지 확인한다.
            second_input = _scripted_input(["1", "B", "N"])
            second_printed: list[str] = []
            exit_code_2 = run_operator(
                daily_pack_path=daily_pack_path,
                answers_path=answers_path,
                knowledge_path=knowledge_path,
                media_output_path=media_output_path,
                media_archive_path=directory / "tak_media_archive.json",
                execute=False,
                input_func=second_input,
                print_func=second_printed.append,
            )
            self.assertEqual(exit_code_2, 0)

            output_text = "\n".join(second_printed)
            self.assertIn("[이미 답변함]", output_text)
            self.assertIn("이 소재에는 이미 답변이 있습니다.", output_text)
            self.assertIn("기존 답변을 다시 사용하거나 새로운 답변으로 덮어쓸 수 있습니다.", output_text)

            # upsert_answer 로직 그대로: 같은 scout_id는 덮어써서 답변이 여전히 1건.
            answers_after_second = load_answers(answers_path)
            self.assertEqual(len(answers_after_second), 1)
            self.assertEqual(answers_after_second[0].selected_option, "B")

            # KNOWLEDGE id는 scout_id+선택지+직접입력 내용으로 결정되는 해시라서,
            # 답변 내용이 A -> B로 바뀌면 새 결정적 id가 생겨 기존 append_scout_knowledge
            # 로직 그대로 KNOWLEDGE가 1건 더 늘어난다(A 기반 1건 + B 기반 1건 = 2건).
            # 이는 새로 만든 동작이 아니라 knowledge_bridge의 기존 설계이며, 여기서는
            # "선택 시 깨지지 않고 정상적으로 이어지는지"만 확인한다.
            records = load_knowledge_records(knowledge_path)
            self.assertEqual(len(records), 2)

            # 3회차: 방금과 완전히 같은 답(B)을 다시 제출하면, 기존 중복 처리
            # 로직(append_scout_knowledge)이 동일 id를 중복 추가하지 않아야 한다.
            third_input = _scripted_input(["1", "B", "N"])
            third_printed: list[str] = []
            exit_code_3 = run_operator(
                daily_pack_path=daily_pack_path,
                answers_path=answers_path,
                knowledge_path=knowledge_path,
                media_output_path=media_output_path,
                media_archive_path=directory / "tak_media_archive.json",
                execute=False,
                input_func=third_input,
                print_func=third_printed.append,
            )
            self.assertEqual(exit_code_3, 0)
            self.assertIn("중복 1건", "\n".join(third_printed))
            records_after_third = load_knowledge_records(knowledge_path)
            self.assertEqual(len(records_after_third), 2)


if __name__ == "__main__":
    unittest.main()
