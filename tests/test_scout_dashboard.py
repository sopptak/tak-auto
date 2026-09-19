"""TAK SCOUT Dashboard(scripts/run_scout_dashboard.py) 테스트.

5-9(MVP: 소재 목록/관심 없음/이미 답변함), 5-10 Phase 2(멀티턴 인터뷰: 최대 3턴
고정 템플릿 질문 -> review -> KNOWLEDGE 연결), 5-10 Phase 3-2(Dashboard ↔
InterviewLLMProvider 연결)를 함께 검증한다. 실제 네트워크는 어떤 테스트에서도
호출하지 않는다 - Phase 2 테스트는 애초에 llm_provider를 넘기지 않고(기본값
None, 4번째 테스트 클래스도 마찬가지), Phase 3-2 테스트는 아래 정의된
FakeInterviewLLMProvider만 주입한다(실제 InterviewLLMProvider/환경변수는 전혀
쓰지 않는다).

렌더링/저장 로직 일부는 서버 없이 직접 함수 호출로 검증하고, 멀티턴 흐름은
요청대로 실제 소켓을 여는 HTTP 통합 테스트로 검증한다(가능하면 실제 HTTP
요청 수준에서 라우트를 호출하라는 지시를 따름).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from html import escape as html_escape
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.request
from urllib.error import HTTPError
from urllib.parse import urlencode

from tak_brain.knowledge import load_knowledge_records
from tak_scout.answers import InterviewAnswer, load_answers, upsert_answer
from tak_scout.collector import save_daily_pack_json
from tak_scout.dashboard_state import skipped_scout_ids
from tak_scout.interview_llm import FollowUpDecision
from tak_scout.interview_session import InterviewTurnRecord, load_sessions
from tak_scout.models import ScoutCandidate
from tak_scout.scoring import rank_candidates
from tak_scout.title_translation import load_translations

from scripts.run_scout_dashboard import (
    DashboardConfig,
    find_candidate,
    get_display_titles,
    handle_skip_submission,
    make_handler_class,
    render_candidate_list_html,
)


def _finance_candidate(scout_id: str = "scout-finance-1") -> ScoutCandidate:
    return ScoutCandidate(
        scout_id=scout_id,
        title="Bank raises mortgage rate amid inflation warning",
        summary="Central bank raises interest rate as property prices rise",
        source_url=f"https://example.test/{scout_id}",
        published_at="2026-09-14T05:00:00+00:00",
        source_name="테스트 경제 뉴스",
        category="finance",
    )


def _lifestyle_candidate(scout_id: str = "scout-lifestyle-1") -> ScoutCandidate:
    return ScoutCandidate(
        scout_id=scout_id,
        title="How to protect your bike from thieves at uni",
        summary="Tips for new students to keep belongings safe",
        source_url=f"https://example.test/{scout_id}",
        published_at="2026-09-14T05:00:00+00:00",
        source_name="테스트 생활 뉴스",
        category="기타",
    )


class DashboardLogicTests(unittest.TestCase):
    """서버 없이 렌더링/저장 함수만 직접 호출하는 테스트(5-9 이관, 유지)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        directory = Path(self._tmp.name)

        self.finance = _finance_candidate()
        self.lifestyle = _lifestyle_candidate()
        self.candidates = [self.finance, self.lifestyle]

        self.daily_pack_path = directory / "tak_scout_daily.json"
        save_daily_pack_json(self.candidates, self.daily_pack_path)

        self.answers_path = directory / "tak_interview_answers.json"
        self.knowledge_path = directory / "tak_brain_knowledge.json"
        self.skipped_path = directory / "tak_scout_dashboard_skipped.json"
        self.sessions_path = directory / "tak_interview_sessions.json"
        self.config = DashboardConfig(
            daily_pack_path=self.daily_pack_path,
            answers_path=self.answers_path,
            knowledge_path=self.knowledge_path,
            skipped_path=self.skipped_path,
            sessions_path=self.sessions_path,
        )

    def test_list_reads_daily_pack_and_sorts_by_score(self):
        ranked = rank_candidates(self.candidates)
        html = render_candidate_list_html(ranked, frozenset(), frozenset())

        finance_pos = html.index(self.finance.title)
        lifestyle_pos = html.index(self.lifestyle.title)
        self.assertLess(finance_pos, lifestyle_pos)
        self.assertIn("아직 답변하지 않음", html)

    def test_list_shows_short_summary_for_each_candidate(self):
        ranked = rank_candidates(self.candidates)
        html = render_candidate_list_html(ranked, frozenset(), frozenset())

        self.assertIn(self.finance.summary, html)
        self.assertIn(self.lifestyle.summary, html)

    def test_find_candidate_returns_exact_match_or_none(self):
        found = find_candidate(self.candidates, self.finance.scout_id)
        self.assertEqual(found, self.finance)
        self.assertIsNone(find_candidate(self.candidates, "scout-does-not-exist"))

    # 18. 기존 "이미 답변함" 기능 유지: 최종 확정 답변(InterviewAnswer)이 있으면
    # 목록에 표시되는지. Phase 2에서는 answer가 finalize를 거쳐야 생기므로,
    # 여기서는 (인터뷰 흐름과 별개로) 목록 렌더링 로직 자체만 검증한다.
    def test_answered_candidate_shown_in_list(self):
        upsert_answer(
            self.answers_path,
            InterviewAnswer.create(self.finance.scout_id, "A"),
        )
        answered_ids = frozenset(a.scout_id for a in load_answers(self.answers_path))

        ranked = rank_candidates(self.candidates)
        html = render_candidate_list_html(ranked, answered_ids, frozenset())

        title_index = html.index(self.finance.title)
        finance_card = html[max(0, title_index - 400) : title_index]
        self.assertIn("이미 답변함", finance_card)

    # 17. 기존 "관심 없음" 기능 유지
    def test_skip_marks_not_interested(self):
        handle_skip_submission(self.lifestyle, self.config)

        self.assertIn(self.lifestyle.scout_id, skipped_scout_ids(self.skipped_path))

        ranked = rank_candidates(self.candidates)
        html = render_candidate_list_html(ranked, frozenset(), skipped_scout_ids(self.skipped_path))
        self.assertIn("관심 없음", html)
        self.assertIsNotNone(find_candidate(self.candidates, self.lifestyle.scout_id))


class DashboardMultiTurnHttpTests(unittest.TestCase):
    """실제로 소켓을 열어 멀티턴 인터뷰(Phase 2) 전체 흐름을 검증한다."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.directory = Path(self._tmp.name)

        self.candidate = _finance_candidate("scout-http-1")
        self.other_candidate = _lifestyle_candidate("scout-http-2")
        self.daily_pack_path = self.directory / "tak_scout_daily.json"
        save_daily_pack_json([self.candidate, self.other_candidate], self.daily_pack_path)

        self.answers_path = self.directory / "tak_interview_answers.json"
        self.knowledge_path = self.directory / "tak_brain_knowledge.json"
        self.skipped_path = self.directory / "tak_scout_dashboard_skipped.json"
        self.sessions_path = self.directory / "tak_interview_sessions.json"

        self.config = DashboardConfig(
            daily_pack_path=self.daily_pack_path,
            answers_path=self.answers_path,
            knowledge_path=self.knowledge_path,
            skipped_path=self.skipped_path,
            sessions_path=self.sessions_path,
        )
        self._start_server()

    def _start_server(self) -> None:
        handler_class = make_handler_class(self.config)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler_class)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._shutdown)

    def _shutdown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def _get(self, path: str) -> tuple[int, str]:
        with urllib.request.urlopen(self._url(path), timeout=5) as response:
            return response.status, response.read().decode("utf-8")

    def _post(self, path: str, data: dict[str, str] | None = None) -> tuple[int, str]:
        body = urlencode(data or {}).encode()
        request = urllib.request.Request(self._url(path), data=body, method="POST")
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.read().decode("utf-8")

    # 1, 2. 첫 접속 시 session 생성 + generated_by == "template"
    def test_first_visit_creates_session_with_template_turn_one(self):
        status, body = self._get(f"/candidate/{self.candidate.scout_id}")
        self.assertEqual(status, 200)
        self.assertIn("이 소재에 대해 어떻게 생각하시나요?", body)
        self.assertIn("질문 1 / 3", body)

        sessions = load_sessions(self.sessions_path)
        self.assertEqual(len(sessions), 1)
        session = sessions[0]
        self.assertEqual(session.status, "in_progress")
        self.assertEqual(len(session.turns), 1)
        self.assertEqual(session.turns[0].generated_by, "template")
        self.assertIsNone(session.turns[0].selected_option)

    # 13. 새로고침 후 기존 session 복원(같은 turn을 다시 만들지 않음)
    def test_revisiting_before_answering_does_not_recreate_session(self):
        self._get(f"/candidate/{self.candidate.scout_id}")
        first_created_at = load_sessions(self.sessions_path)[0].created_at

        self._get(f"/candidate/{self.candidate.scout_id}")  # 새로고침 흉내
        sessions = load_sessions(self.sessions_path)

        self.assertEqual(len(sessions), 1)
        self.assertEqual(len(sessions[0].turns), 1)
        self.assertEqual(sessions[0].created_at, first_created_at)

    # 3~9, 13: A -> Turn2 -> D(직접입력) -> Turn3 -> B -> 완료, 매 단계 검증
    def test_full_three_turn_flow_a_then_d_then_b(self):
        scout_id = self.candidate.scout_id

        self._get(f"/candidate/{scout_id}")  # turn 1 생성

        # 3. A 답변 저장
        status, body = self._post(f"/candidate/{scout_id}/answer", {"option": "A"})
        self.assertEqual(status, 200)
        # 8. 2턴째 질문 생성
        self.assertIn("그렇게 생각하게 된 이유나 경험이 있나요?", body)
        self.assertIn("질문 2 / 3", body)

        sessions = load_sessions(self.sessions_path)
        self.assertEqual(sessions[0].status, "in_progress")
        self.assertEqual(len(sessions[0].turns), 2)
        self.assertEqual(sessions[0].turns[0].selected_option, "A")
        self.assertEqual(sessions[0].turns[0].custom_answer, "")
        self.assertIsNotNone(sessions[0].turns[0].answered_at)
        # 새로고침해도 turn이 또 늘어나지 않는지(같은 turn 2를 유지)
        self._get(f"/candidate/{scout_id}")
        self.assertEqual(len(load_sessions(self.sessions_path)[0].turns), 2)

        # 6, 7. D 직접입력 저장 + 원문 보존
        custom_text = "신기술은 두려워 말고 부딪혀서 느껴봐야 한다."
        status, body = self._post(
            f"/candidate/{scout_id}/answer", {"option": "D", "custom_answer": custom_text}
        )
        self.assertEqual(status, 200)
        # 9. 3턴째 질문 생성
        self.assertIn("이 주제에 대해 다른 사람에게 가장 전하고 싶은 생각은 무엇인가요?", body)
        self.assertIn("질문 3 / 3", body)

        sessions = load_sessions(self.sessions_path)
        self.assertEqual(len(sessions[0].turns), 3)
        self.assertEqual(sessions[0].turns[1].selected_option, "D")
        self.assertEqual(sessions[0].turns[1].custom_answer, custom_text)  # 원문 그대로

        # 4, 5, 10, 11, 12. B 답변 -> 3턴 완료, status/completed_at, 4턴 없음
        status, body = self._post(f"/candidate/{scout_id}/answer", {"option": "B"})
        self.assertEqual(status, 200)
        self.assertIn("인터뷰 결과", body)  # review 화면으로 리다이렉트됨

        sessions = load_sessions(self.sessions_path)
        session = sessions[0]
        self.assertEqual(session.status, "completed")
        self.assertIsNotNone(session.completed_at)
        self.assertEqual(len(session.turns), 3)  # 12. 4턴이 생성되지 않음
        self.assertEqual(session.turns[2].selected_option, "B")

        # 15. review 화면 정상 표시
        status, review_body = self._get(f"/candidate/{scout_id}/review")
        self.assertEqual(status, 200)
        self.assertIn(self.candidate.title, review_body)
        self.assertIn(self.candidate.source_url, review_body)
        self.assertIn("이 소재에 대해 어떻게 생각하시나요?", review_body)
        self.assertIn("긍정적으로 본다", review_body)  # A 선택지 텍스트
        self.assertIn(custom_text, review_body)  # D 원문 그대로
        self.assertIn("신중하게 접근해야 한다", review_body)  # turn 3의 B 선택지 텍스트
        self.assertIn("이 내용으로 KNOWLEDGE 만들기", review_body)
        self.assertIn("다시 답변하기", review_body)

        # 16. KNOWLEDGE 생성 버튼이 기존 bridge와 연결됨
        status, finalize_body = self._post(f"/candidate/{scout_id}/finalize")
        self.assertEqual(status, 200)
        self.assertIn("저장되었습니다", finalize_body)

        answers = load_answers(self.answers_path)
        self.assertEqual(len(answers), 1)
        self.assertEqual(answers[0].scout_id, scout_id)
        self.assertEqual(answers[0].selected_option, "D")
        self.assertIn(custom_text, answers[0].custom_answer)  # 직접입력 원문 보존
        self.assertIn("긍정적으로 본다", answers[0].custom_answer)
        self.assertIn("신중하게 접근해야 한다", answers[0].custom_answer)

        records = load_knowledge_records(self.knowledge_path)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].knowledge_review_status, "pending")  # 자동 승인 없음
        evidence_text = " ".join(records[0].evidence)
        self.assertIn("SOURCE FACT:", evidence_text)
        self.assertIn("SOURCE URL:", evidence_text)
        self.assertIn("USER ORIGINAL THOUGHT:", evidence_text)
        self.assertIn(custom_text, evidence_text)

        # 18. 이미 답변함이 목록에 반영되는지(실제 HTTP로 재확인)
        status, list_body = self._get("/")
        self.assertEqual(status, 200)
        title_index = list_body.index(self.candidate.title)
        card = list_body[max(0, title_index - 400) : title_index]
        self.assertIn("이미 답변함", card)

    def test_invalid_option_does_not_crash_or_advance_turn(self):
        scout_id = self.candidate.scout_id
        self._get(f"/candidate/{scout_id}")

        request = urllib.request.Request(
            self._url(f"/candidate/{scout_id}/answer"), data=urlencode({"option": "Z"}).encode(), method="POST"
        )
        with self.assertRaises(HTTPError) as ctx:
            urllib.request.urlopen(request, timeout=5)
        self.assertEqual(ctx.exception.code, 400)
        error_body = ctx.exception.read().decode("utf-8")
        ctx.exception.close()
        self.assertIn("오류", error_body)

        sessions = load_sessions(self.sessions_path)
        self.assertEqual(len(sessions[0].turns), 1)
        self.assertIsNone(sessions[0].turns[0].selected_option)

    def test_option_d_without_custom_answer_is_rejected(self):
        scout_id = self.candidate.scout_id
        self._get(f"/candidate/{scout_id}")

        request = urllib.request.Request(
            self._url(f"/candidate/{scout_id}/answer"), data=urlencode({"option": "D"}).encode(), method="POST"
        )
        with self.assertRaises(HTTPError) as ctx:
            urllib.request.urlopen(request, timeout=5)
        self.assertEqual(ctx.exception.code, 400)
        ctx.exception.close()

        sessions = load_sessions(self.sessions_path)
        self.assertIsNone(sessions[0].turns[0].selected_option)  # 저장되지 않음

    def test_review_before_completion_redirects_back_to_interview(self):
        scout_id = self.candidate.scout_id
        self._get(f"/candidate/{scout_id}")
        self._post(f"/candidate/{scout_id}/answer", {"option": "A"})  # 아직 2턴째

        status, body = self._get(f"/candidate/{scout_id}/review")
        self.assertEqual(status, 200)
        self.assertIn("질문 2 / 3", body)  # review가 아니라 인터뷰 화면으로 안내됨

    # 9. 다시 답변하기: 기존 답변 데이터가 유실되지 않는지
    def test_restart_resets_session_but_keeps_finalized_answer(self):
        scout_id = self.candidate.scout_id
        self._get(f"/candidate/{scout_id}")
        self._post(f"/candidate/{scout_id}/answer", {"option": "A"})
        self._post(f"/candidate/{scout_id}/answer", {"option": "B"})
        self._post(f"/candidate/{scout_id}/answer", {"option": "C"})
        self._post(f"/candidate/{scout_id}/finalize")

        answers_before = load_answers(self.answers_path)
        self.assertEqual(len(answers_before), 1)

        status, body = self._post(f"/candidate/{scout_id}/restart")
        self.assertEqual(status, 200)
        self.assertIn("질문 1 / 3", body)  # turn 1부터 다시 시작

        session = load_sessions(self.sessions_path)[0]
        self.assertEqual(session.status, "in_progress")
        self.assertEqual(len(session.turns), 1)
        self.assertIsNone(session.turns[0].selected_option)

        # restart만으로는 이미 확정된 답변이 사라지지 않는다.
        answers_after = load_answers(self.answers_path)
        self.assertEqual(answers_before, answers_after)

    # 14. 프로세스 경계를 넘어 session 복원
    def test_session_survives_server_restart(self):
        scout_id = self.candidate.scout_id
        self._get(f"/candidate/{scout_id}")
        self._post(f"/candidate/{scout_id}/answer", {"option": "A"})

        # 서버 프로세스를 껐다가 같은 세션 파일로 다시 켠다(진짜 프로세스는 아니지만
        # 서버 인스턴스를 완전히 새로 만들어 메모리 상태가 없다는 것을 확인한다).
        self._shutdown()
        self._start_server()

        status, body = self._get(f"/candidate/{scout_id}")
        self.assertEqual(status, 200)
        self.assertIn("그렇게 생각하게 된 이유나 경험이 있나요?", body)  # turn 2 그대로 복원됨

        sessions = load_sessions(self.sessions_path)
        self.assertEqual(len(sessions[0].turns), 2)

    # 17. 기존 "관심 없음" 기능 유지(실제 HTTP)
    def test_skip_over_http_still_works(self):
        status, _ = self._post(f"/candidate/{self.other_candidate.scout_id}/skip")
        self.assertEqual(status, 200)
        self.assertIn(self.other_candidate.scout_id, skipped_scout_ids(self.skipped_path))

        status, list_body = self._get("/")
        self.assertEqual(status, 200)
        title_index = list_body.index(self.other_candidate.title)
        card = list_body[max(0, title_index - 400) : title_index]
        self.assertIn("관심 없음", card)

    def test_unknown_scout_id_returns_404_on_new_routes(self):
        for suffix in ("/review",):
            with self.assertRaises(HTTPError) as ctx:
                urllib.request.urlopen(self._url(f"/candidate/does-not-exist{suffix}"), timeout=5)
            self.assertEqual(ctx.exception.code, 404)
            ctx.exception.close()

        for suffix in ("/finalize", "/restart"):
            request = urllib.request.Request(self._url(f"/candidate/does-not-exist{suffix}"), data=b"", method="POST")
            with self.assertRaises(HTTPError) as ctx:
                urllib.request.urlopen(request, timeout=5)
            self.assertEqual(ctx.exception.code, 404)
            ctx.exception.close()


def _llm_turn(
    turn_number: int,
    question: str,
    option_a: str,
    option_b: str,
    option_c: str,
    option_d: str = "직접 입력",
) -> InterviewTurnRecord:
    """LLM이 만든 것처럼 보이는 InterviewTurnRecord를 만든다(테스트 전용)."""
    return InterviewTurnRecord(
        turn=turn_number,
        question=question,
        option_a=option_a,
        option_b=option_b,
        option_c=option_c,
        option_d=option_d,
        generated_by="llm",
        selected_option=None,
        custom_answer="",
        answered_at=None,
    )


def _is_exception_class(value) -> bool:
    return isinstance(value, type) and issubclass(value, BaseException)


@dataclass
class FakeInterviewLLMProvider:
    """5-10 Phase 3-2 Dashboard 통합 테스트 전용 Fake provider. 실제 네트워크 없음.

    tak_scout.interview_llm.InterviewLLMProvider와 같은 두 메서드
    (generate_first_question, decide_next_turn)만 구현한다 - 상속 관계는 없다
    (duck typing). 각 메서드는 미리 채워둔 결과를 순서대로 하나씩 꺼내 반환하고,
    호출 인자를 그대로 기록해 두어 "언제/몇 번 호출됐는지", "candidate/source_fact/
    turns_so_far가 무엇으로 전달됐는지"를 테스트에서 검증할 수 있게 한다.

    결과 목록에 예외 클래스(예: `RuntimeError`)를 넣어 두면 그 자리에서 실제로
    그 예외를 던진다(Dashboard의 방어 코드 - 11번 테스트 - 를 검증하기 위함).
    """

    first_question_results: list = field(default_factory=list)
    decide_results: list = field(default_factory=list)
    first_question_calls: list = field(default_factory=list)
    decide_calls: list = field(default_factory=list)
    translate_titles_results: list = field(default_factory=list)
    translate_titles_calls: list = field(default_factory=list)

    def generate_first_question(self, candidate, source_fact):
        self.first_question_calls.append((candidate, source_fact))
        if not self.first_question_results:
            return None
        result = self.first_question_results.pop(0)
        if _is_exception_class(result):
            raise result("fake llm failure")
        return result

    def decide_next_turn(self, candidate, source_fact, turns_so_far):
        self.decide_calls.append((candidate, source_fact, turns_so_far))
        if not self.decide_results:
            return None
        result = self.decide_results.pop(0)
        if _is_exception_class(result):
            raise result("fake llm failure")
        return result

    def translate_titles(self, titles):
        self.translate_titles_calls.append(titles)
        if not self.translate_titles_results:
            return None
        result = self.translate_titles_results.pop(0)
        if _is_exception_class(result):
            raise result("fake llm failure")
        return result


class DashboardLLMIntegrationTests(unittest.TestCase):
    """5-10 Phase 3-2: Dashboard ↔ InterviewLLMProvider 연결을 FakeInterviewLLMProvider로 검증한다.

    이 클래스의 어떤 테스트도 tak_scout.interview_llm.InterviewLLMProvider(실제
    HTTP transport를 가진 클래스)나 환경변수를 참조하지 않는다 - FakeInterviewLLMProvider만
    make_handler_class(config, llm_provider=fake)로 주입한다.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.directory = Path(self._tmp.name)

        self.candidate = _finance_candidate("scout-llm-1")
        self.daily_pack_path = self.directory / "tak_scout_daily.json"
        save_daily_pack_json([self.candidate], self.daily_pack_path)

        self.answers_path = self.directory / "tak_interview_answers.json"
        self.knowledge_path = self.directory / "tak_brain_knowledge.json"
        self.skipped_path = self.directory / "tak_scout_dashboard_skipped.json"
        self.sessions_path = self.directory / "tak_interview_sessions.json"

        self.config = DashboardConfig(
            daily_pack_path=self.daily_pack_path,
            answers_path=self.answers_path,
            knowledge_path=self.knowledge_path,
            skipped_path=self.skipped_path,
            sessions_path=self.sessions_path,
        )

    def _start_server(self, llm_provider) -> None:
        handler_class = make_handler_class(self.config, llm_provider=llm_provider)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler_class)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._shutdown)

    def _shutdown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def _get(self, path: str) -> tuple[int, str]:
        with urllib.request.urlopen(self._url(path), timeout=5) as response:
            return response.status, response.read().decode("utf-8")

    def _post(self, path: str, data: dict[str, str] | None = None) -> tuple[int, str]:
        body = urlencode(data or {}).encode()
        request = urllib.request.Request(self._url(path), data=body, method="POST")
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.read().decode("utf-8")

    # [Turn 1] 1. LLM 성공 -> generated_by == "llm"
    def test_llm_first_question_success_sets_generated_by_llm(self):
        fake = FakeInterviewLLMProvider(
            first_question_results=[_llm_turn(1, "LLM이 만든 첫 질문입니다", "가", "나", "다")]
        )
        self._start_server(fake)
        scout_id = self.candidate.scout_id

        status, body = self._get(f"/candidate/{scout_id}")

        self.assertEqual(status, 200)
        self.assertIn("LLM이 만든 첫 질문입니다", body)
        self.assertEqual(len(fake.first_question_calls), 1)

        session = load_sessions(self.sessions_path)[0]
        self.assertEqual(session.turns[0].generated_by, "llm")
        self.assertEqual(session.turns[0].question, "LLM이 만든 첫 질문입니다")

    # [Turn 1] 2. LLM 실패(None) -> template fallback
    def test_llm_first_question_failure_falls_back_to_template(self):
        fake = FakeInterviewLLMProvider(first_question_results=[None])
        self._start_server(fake)
        scout_id = self.candidate.scout_id

        status, body = self._get(f"/candidate/{scout_id}")

        self.assertEqual(status, 200)
        self.assertIn("이 소재에 대해 어떻게 생각하시나요?", body)  # 기존 template 문구 그대로
        self.assertEqual(len(fake.first_question_calls), 1)

        session = load_sessions(self.sessions_path)[0]
        self.assertEqual(session.turns[0].generated_by, "template")

    # [Turn 1] 3. option_d가 이상한 값이어도 최종 D는 "직접 입력"
    def test_llm_first_question_option_d_is_forced_to_direct_input(self):
        fake = FakeInterviewLLMProvider(
            first_question_results=[_llm_turn(1, "질문", "가", "나", "다", option_d="이상한 값")]
        )
        self._start_server(fake)
        scout_id = self.candidate.scout_id

        self._get(f"/candidate/{scout_id}")

        session = load_sessions(self.sessions_path)[0]
        self.assertEqual(session.turns[0].option_d, "직접 입력")

    # [Turn 2] 4, 5. 첫 답변 후 sufficient=False -> 다음 질문 표시 + session 저장
    def test_sufficient_false_shows_and_stores_next_turn(self):
        fake = FakeInterviewLLMProvider(
            first_question_results=[None],  # turn 1은 template으로
            decide_results=[
                FollowUpDecision(
                    sufficient=False,
                    next_turn=_llm_turn(2, "LLM 후속 질문입니다", "라", "마", "바"),
                    perspective_summary="지금까지 파악한 관점",
                )
            ],
        )
        self._start_server(fake)
        scout_id = self.candidate.scout_id
        self._get(f"/candidate/{scout_id}")  # turn 1 생성(template)

        status, body = self._post(f"/candidate/{scout_id}/answer", {"option": "A"})

        self.assertEqual(status, 200)
        self.assertIn("LLM 후속 질문입니다", body)
        self.assertEqual(len(fake.decide_calls), 1)

        session = load_sessions(self.sessions_path)[0]
        self.assertEqual(len(session.turns), 2)
        self.assertEqual(session.turns[1].question, "LLM 후속 질문입니다")
        self.assertEqual(session.turns[1].generated_by, "llm")
        self.assertEqual(session.perspective_summary, "지금까지 파악한 관점")

        # decide_next_turn에 넘겨진 turns_so_far에는 방금 답한 turn 1이 포함되어야 한다.
        _candidate_arg, _source_fact_arg, turns_so_far = fake.decide_calls[0]
        self.assertEqual(len(turns_so_far), 1)
        self.assertEqual(turns_so_far[0].selected_option, "A")

    # [Turn 2] 6, 7. sufficient=True -> 즉시 completed, review 이동, perspective_summary 저장
    def test_sufficient_true_completes_immediately_and_shows_review(self):
        fake = FakeInterviewLLMProvider(
            first_question_results=[None],
            decide_results=[
                FollowUpDecision(sufficient=True, next_turn=None, perspective_summary="AI가 파악한 최종 관점")
            ],
        )
        self._start_server(fake)
        scout_id = self.candidate.scout_id
        self._get(f"/candidate/{scout_id}")

        status, body = self._post(f"/candidate/{scout_id}/answer", {"option": "A"})

        self.assertEqual(status, 200)
        self.assertIn("인터뷰 결과", body)  # review 화면으로 리다이렉트됨
        self.assertIn("AI가 충분하다고 판단해 인터뷰를 마쳤습니다.", body)
        self.assertIn("AI가 파악한 최종 관점", body)

        session = load_sessions(self.sessions_path)[0]
        self.assertEqual(session.status, "completed")
        self.assertIsNotNone(session.completed_at)
        self.assertEqual(len(session.turns), 1)  # turn 2가 생성되지 않음(조기 완료)
        self.assertEqual(session.perspective_summary, "AI가 파악한 최종 관점")

    # [Turn 3] 8, 9. turn 3에서는 LLM(decide_next_turn)을 호출하지 않고 무조건 completed
    def test_turn_three_never_calls_decide_next_turn_and_completes(self):
        fake = FakeInterviewLLMProvider(
            first_question_results=[None],
            decide_results=[
                FollowUpDecision(sufficient=False, next_turn=_llm_turn(2, "질문2", "가", "나", "다"), perspective_summary="s1"),
                FollowUpDecision(sufficient=False, next_turn=_llm_turn(3, "질문3", "라", "마", "바"), perspective_summary="s2"),
            ],
        )
        self._start_server(fake)
        scout_id = self.candidate.scout_id
        self._get(f"/candidate/{scout_id}")
        self._post(f"/candidate/{scout_id}/answer", {"option": "A"})  # turn1 답변 -> decide 1회
        self._post(f"/candidate/{scout_id}/answer", {"option": "B"})  # turn2 답변 -> decide 2회
        self.assertEqual(len(fake.decide_calls), 2)

        status, body = self._post(f"/candidate/{scout_id}/answer", {"option": "C"})  # turn3 답변

        self.assertEqual(status, 200)
        self.assertIn("인터뷰 결과", body)
        self.assertEqual(len(fake.decide_calls), 2)  # 호출 횟수 그대로(3번째 호출 없음)

        session = load_sessions(self.sessions_path)[0]
        self.assertEqual(session.status, "completed")
        self.assertEqual(len(session.turns), 3)
        # 3턴을 다 채워서 끝난 경우이므로 "조기 완료" 안내는 나오지 않는다.
        status, review_body = self._get(f"/candidate/{scout_id}/review")
        self.assertNotIn("AI가 충분하다고 판단해 인터뷰를 마쳤습니다.", review_body)

    # [Failure] 10. decide_next_turn() == None -> template fallback
    def test_decide_next_turn_none_falls_back_to_template(self):
        fake = FakeInterviewLLMProvider(first_question_results=[None], decide_results=[None])
        self._start_server(fake)
        scout_id = self.candidate.scout_id
        self._get(f"/candidate/{scout_id}")

        status, body = self._post(f"/candidate/{scout_id}/answer", {"option": "A"})

        self.assertEqual(status, 200)
        self.assertIn("그렇게 생각하게 된 이유나 경험이 있나요?", body)  # 기존 template 문구

        session = load_sessions(self.sessions_path)[0]
        self.assertEqual(session.turns[1].generated_by, "template")

    # [Failure] 11. LLM이 예외를 던져도 Dashboard 500 없이 정상 fallback
    def test_llm_exception_does_not_crash_dashboard(self):
        fake = FakeInterviewLLMProvider(
            first_question_results=[RuntimeError],
            decide_results=[RuntimeError],
        )
        self._start_server(fake)
        scout_id = self.candidate.scout_id

        status, body = self._get(f"/candidate/{scout_id}")
        self.assertEqual(status, 200)
        self.assertIn("이 소재에 대해 어떻게 생각하시나요?", body)  # template fallback

        status, body = self._post(f"/candidate/{scout_id}/answer", {"option": "A"})
        self.assertEqual(status, 200)
        self.assertIn("그렇게 생각하게 된 이유나 경험이 있나요?", body)  # template fallback

    # [Resume] 12. in_progress session 재진입 -> 저장된 질문 사용, LLM 재호출 없음
    def test_resuming_in_progress_session_does_not_call_llm_again(self):
        fake = FakeInterviewLLMProvider(
            first_question_results=[_llm_turn(1, "LLM 질문", "가", "나", "다")]
        )
        self._start_server(fake)
        scout_id = self.candidate.scout_id

        self._get(f"/candidate/{scout_id}")  # session 생성(LLM 1회 호출)
        self._get(f"/candidate/{scout_id}")  # 재진입(새로고침)
        self._get(f"/candidate/{scout_id}")  # 한 번 더

        self.assertEqual(len(fake.first_question_calls), 1)  # 늘어나지 않음

    # [Resume] 13. completed session 재진입 -> review로 이동
    def test_resuming_completed_session_redirects_to_review(self):
        fake = FakeInterviewLLMProvider(
            first_question_results=[None],
            decide_results=[FollowUpDecision(sufficient=True, next_turn=None, perspective_summary="요약")],
        )
        self._start_server(fake)
        scout_id = self.candidate.scout_id
        self._get(f"/candidate/{scout_id}")
        self._post(f"/candidate/{scout_id}/answer", {"option": "A"})  # 즉시 completed

        status, body = self._get(f"/candidate/{scout_id}")
        self.assertEqual(status, 200)
        self.assertIn("인터뷰 결과", body)  # /review로 redirect됨

    # [Direct Input] 14, 15. LLM 경로에서도 D 직접 입력 원문이 그대로 유지된다(특수문자 포함)
    def test_direct_input_preserved_through_llm_flow(self):
        custom_text = "특수문자!! @#$%\n두 번째 줄\t탭도 포함 — 그대로 보존되어야 한다."
        fake = FakeInterviewLLMProvider(
            first_question_results=[_llm_turn(1, "LLM 첫 질문", "가", "나", "다")],
            decide_results=[
                FollowUpDecision(sufficient=True, next_turn=None, perspective_summary="직접입력 기반 요약")
            ],
        )
        self._start_server(fake)
        scout_id = self.candidate.scout_id
        self._get(f"/candidate/{scout_id}")

        status, body = self._post(
            f"/candidate/{scout_id}/answer", {"option": "D", "custom_answer": custom_text}
        )
        self.assertEqual(status, 200)
        self.assertIn("인터뷰 결과", body)

        session = load_sessions(self.sessions_path)[0]
        self.assertEqual(session.turns[0].custom_answer, custom_text)  # 원문 그대로, 재작성 없음

        # decide_next_turn에 넘어간 previous turn도 원문 그대로였는지(간접 확인):
        # FakeInterviewLLMProvider는 turns_so_far를 그대로 기록해 두므로 직접 검사 가능.
        _candidate_arg, _source_fact_arg, turns_so_far = fake.decide_calls[0]
        self.assertEqual(turns_so_far[0].custom_answer, custom_text)

        status, review_body = self._get(f"/candidate/{scout_id}/review")
        self.assertIn(custom_text, review_body)

    # [Finalize] 16, 17, 18. LLM으로 완료된 세션도 기존 finalize/KNOWLEDGE 구조를 그대로 따른다
    def test_finalize_after_llm_driven_session_keeps_existing_knowledge_structure(self):
        custom_text = "LLM 인터뷰를 통해 얻은 티몽의 실제 생각이다."
        fake = FakeInterviewLLMProvider(
            first_question_results=[_llm_turn(1, "LLM 질문 1", "가", "나", "다")],
            decide_results=[
                FollowUpDecision(
                    sufficient=False,
                    next_turn=_llm_turn(2, "LLM 질문 2", "라", "마", "바"),
                    perspective_summary="1턴 후 요약",
                ),
                FollowUpDecision(sufficient=True, next_turn=None, perspective_summary="최종 요약"),
            ],
        )
        self._start_server(fake)
        scout_id = self.candidate.scout_id

        self._get(f"/candidate/{scout_id}")
        self._post(f"/candidate/{scout_id}/answer", {"option": "A"})
        self._post(f"/candidate/{scout_id}/answer", {"option": "D", "custom_answer": custom_text})

        session = load_sessions(self.sessions_path)[0]
        self.assertEqual(session.status, "completed")
        self.assertEqual(len(session.turns), 2)

        status, finalize_body = self._post(f"/candidate/{scout_id}/finalize")
        self.assertEqual(status, 200)
        self.assertIn("저장되었습니다", finalize_body)

        answers = load_answers(self.answers_path)
        self.assertEqual(len(answers), 1)
        self.assertEqual(answers[0].selected_option, "D")  # 멀티턴 합성은 항상 D(기존 규칙 그대로)
        self.assertIn(custom_text, answers[0].custom_answer)
        self.assertIn("LLM 질문 1", answers[0].custom_answer)

        records = load_knowledge_records(self.knowledge_path)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].knowledge_review_status, "pending")  # 자동 승인 없음(기존 그대로)
        evidence_text = " ".join(records[0].evidence)
        self.assertIn("SOURCE FACT:", evidence_text)
        self.assertIn("SOURCE URL:", evidence_text)
        self.assertIn("USER ORIGINAL THOUGHT:", evidence_text)
        self.assertIn(custom_text, evidence_text)
        # perspective_summary(AI 요약)는 SOURCE FACT/URL에도, USER ORIGINAL THOUGHT에도
        # 섞여 들어가지 않는다 - KNOWLEDGE는 여전히 사용자가 실제로 입력한 원문만 담는다.
        self.assertNotIn("최종 요약", evidence_text)
        self.assertNotIn("1턴 후 요약", evidence_text)


class TitleTranslationTests(unittest.TestCase):
    """5-20: SCOUT 후보 제목의 한국어 표시용 번역(캐시 + LLM fallback)을 검증한다.

    실제 네트워크는 호출하지 않는다 - FakeInterviewLLMProvider만 주입한다.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.directory = Path(self._tmp.name)
        self.translations_path = self.directory / "tak_scout_title_translations.json"

        self.candidate = ScoutCandidate(
            scout_id="scout-jpmorgan-1",
            title="We simply don't know - JP Morgan struggling to forecast oil prices due to Trump's war with Iran",
            summary="JP Morgan says it cannot reliably forecast oil prices given the conflict.",
            source_url="https://example.test/jpmorgan-oil",
            published_at="2026-09-18T17:57:30+00:00",
            source_name="BBC Business",
            category="finance",
        )
        self.display_title = "정말 알 수 없다 — JP모건, 이란 전쟁으로 유가 전망에 어려움"

    def test_english_title_gets_korean_display_title(self):
        fake = FakeInterviewLLMProvider(
            translate_titles_results=[{self.candidate.scout_id: self.display_title}]
        )
        display_titles = get_display_titles([self.candidate], fake, self.translations_path)

        self.assertEqual(display_titles[self.candidate.scout_id], self.display_title)

    def test_source_title_is_never_modified(self):
        fake = FakeInterviewLLMProvider(
            translate_titles_results=[{self.candidate.scout_id: self.display_title}]
        )
        original_title = self.candidate.title
        get_display_titles([self.candidate], fake, self.translations_path)

        self.assertEqual(self.candidate.title, original_title)
        self.assertNotEqual(self.candidate.title, self.display_title)

    def test_llm_missing_falls_back_to_source_title(self):
        display_titles = get_display_titles([self.candidate], None, self.translations_path)
        self.assertEqual(display_titles[self.candidate.scout_id], self.candidate.title)

    def test_llm_failure_falls_back_to_source_title(self):
        fake = FakeInterviewLLMProvider(translate_titles_results=[RuntimeError])
        display_titles = get_display_titles([self.candidate], fake, self.translations_path)
        self.assertEqual(display_titles[self.candidate.scout_id], self.candidate.title)

    def test_llm_returning_none_falls_back_to_source_title(self):
        fake = FakeInterviewLLMProvider(translate_titles_results=[None])
        display_titles = get_display_titles([self.candidate], fake, self.translations_path)
        self.assertEqual(display_titles[self.candidate.scout_id], self.candidate.title)

    def test_cached_translation_is_not_requested_again(self):
        fake = FakeInterviewLLMProvider(
            translate_titles_results=[{self.candidate.scout_id: self.display_title}]
        )
        first = get_display_titles([self.candidate], fake, self.translations_path)
        second = get_display_titles([self.candidate], fake, self.translations_path)

        self.assertEqual(first[self.candidate.scout_id], self.display_title)
        self.assertEqual(second[self.candidate.scout_id], self.display_title)
        # 두 번째 호출에서는 캐시에 이미 있으므로 LLM이 다시 호출되지 않아야 한다.
        self.assertEqual(len(fake.translate_titles_calls), 1)

    def test_translation_cached_to_disk_survives_process_boundary(self):
        fake = FakeInterviewLLMProvider(
            translate_titles_results=[{self.candidate.scout_id: self.display_title}]
        )
        get_display_titles([self.candidate], fake, self.translations_path)

        cached = load_translations(self.translations_path)
        self.assertEqual(len(cached), 1)
        self.assertEqual(cached[0].scout_id, self.candidate.scout_id)
        self.assertEqual(cached[0].display_title, self.display_title)
        self.assertEqual(cached[0].source_title, self.candidate.title)

        # 새 provider 인스턴스(호출 기록이 비어 있음)로도 캐시만으로 번역이 나온다.
        fresh_fake = FakeInterviewLLMProvider()
        display_titles = get_display_titles([self.candidate], fresh_fake, self.translations_path)
        self.assertEqual(display_titles[self.candidate.scout_id], self.display_title)
        self.assertEqual(fresh_fake.translate_titles_calls, [])

    def test_batch_call_covers_multiple_uncached_candidates_in_one_call(self):
        other = _lifestyle_candidate("scout-other-1")
        fake = FakeInterviewLLMProvider(
            translate_titles_results=[
                {
                    self.candidate.scout_id: self.display_title,
                    other.scout_id: "신입생을 위한 자전거 도난 방지 팁",
                }
            ]
        )
        display_titles = get_display_titles([self.candidate, other], fake, self.translations_path)

        self.assertEqual(display_titles[self.candidate.scout_id], self.display_title)
        self.assertEqual(display_titles[other.scout_id], "신입생을 위한 자전거 도난 방지 팁")
        # 후보 2건이었지만 배치 호출은 정확히 1번만 일어나야 한다(개별 호출 금지).
        self.assertEqual(len(fake.translate_titles_calls), 1)
        self.assertEqual(len(fake.translate_titles_calls[0]), 2)

    def test_partial_translation_falls_back_only_for_missing_candidate(self):
        other = _lifestyle_candidate("scout-other-2")
        fake = FakeInterviewLLMProvider(
            # other의 번역은 응답에서 빠짐(부분 실패) - other만 원문 fallback이어야 한다.
            translate_titles_results=[{self.candidate.scout_id: self.display_title}]
        )
        display_titles = get_display_titles([self.candidate, other], fake, self.translations_path)

        self.assertEqual(display_titles[self.candidate.scout_id], self.display_title)
        self.assertEqual(display_titles[other.scout_id], other.title)

    def test_score_and_ranking_unaffected_by_translation(self):
        """5번 요구사항: 한국어 표시 제목 추가가 기존 TOP N 정렬/점수 계산에 영향을 주지 않는다."""
        candidates = [self.candidate, _lifestyle_candidate("scout-other-3")]
        ranked_before = rank_candidates(candidates)

        fake = FakeInterviewLLMProvider(
            translate_titles_results=[{self.candidate.scout_id: self.display_title}]
        )
        get_display_titles(candidates, fake, self.translations_path)
        ranked_after = rank_candidates(candidates)

        self.assertEqual(
            [(c.scout_id, s.total) for c, s in ranked_before],
            [(c.scout_id, s.total) for c, s in ranked_after],
        )

    def test_list_html_shows_korean_title_first_and_english_original_small(self):
        display_titles = {self.candidate.scout_id: self.display_title}
        ranked = rank_candidates([self.candidate])
        html = render_candidate_list_html(ranked, frozenset(), frozenset(), display_titles)

        ko_pos = html.index(self.display_title)
        en_pos = html.index(html_escape(self.candidate.title))
        self.assertLess(ko_pos, en_pos)
        self.assertIn('class="title-ko"', html)
        self.assertIn('class="title-en"', html)

    def test_list_html_without_translation_shows_only_original_title(self):
        """번역이 없는(fallback) 후보는 영어 원문 보조 표시를 중복해서 보여주지 않는다."""
        ranked = rank_candidates([self.candidate])
        html = render_candidate_list_html(ranked, frozenset(), frozenset(), {})

        self.assertIn(html_escape(self.candidate.title), html)
        self.assertNotIn('class="title-en"', html)


class TitleTranslationOverHttpTests(unittest.TestCase):
    """실제 소켓을 여는 HTTP 통합 테스트로 목록/인터뷰 화면의 한국어 제목 표시를 확인한다."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.directory = Path(self._tmp.name)

        self.candidate = ScoutCandidate(
            scout_id="scout-jpmorgan-http-1",
            title="We simply don't know - JP Morgan struggling to forecast oil prices due to Trump's war with Iran",
            summary="JP Morgan says it cannot reliably forecast oil prices given the conflict.",
            source_url="https://example.test/jpmorgan-oil",
            published_at="2026-09-18T17:57:30+00:00",
            source_name="BBC Business",
            category="finance",
        )
        self.display_title = "정말 알 수 없다 — JP모건, 이란 전쟁으로 유가 전망에 어려움"

        self.daily_pack_path = self.directory / "tak_scout_daily.json"
        save_daily_pack_json([self.candidate], self.daily_pack_path)

        self.config = DashboardConfig(
            daily_pack_path=self.daily_pack_path,
            answers_path=self.directory / "tak_interview_answers.json",
            knowledge_path=self.directory / "tak_brain_knowledge.json",
            skipped_path=self.directory / "tak_scout_dashboard_skipped.json",
            sessions_path=self.directory / "tak_interview_sessions.json",
            title_translations_path=self.directory / "tak_scout_title_translations.json",
        )

    def _start_server(self, llm_provider) -> None:
        handler_class = make_handler_class(self.config, llm_provider=llm_provider)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler_class)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._shutdown)

    def _shutdown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def _get(self, path: str) -> tuple[int, str]:
        with urllib.request.urlopen(self._url(path), timeout=5) as response:
            return response.status, response.read().decode("utf-8")

    def test_candidate_list_page_shows_korean_title(self):
        fake = FakeInterviewLLMProvider(
            translate_titles_results=[{self.candidate.scout_id: self.display_title}]
        )
        self._start_server(fake)

        status, body = self._get("/")

        self.assertEqual(status, 200)
        self.assertIn(self.display_title, body)
        self.assertIn(html_escape(self.candidate.title), body)  # 원문도 작게 함께 표시

    def test_interview_turn_page_shows_korean_title_first(self):
        fake = FakeInterviewLLMProvider(
            translate_titles_results=[{self.candidate.scout_id: self.display_title}]
        )
        self._start_server(fake)

        status, body = self._get(f"/candidate/{self.candidate.scout_id}")

        self.assertEqual(status, 200)
        heading_pos = body.index(f"<h1>{self.display_title}</h1>")
        original_pos = body.index(html_escape(self.candidate.title), heading_pos)
        self.assertLess(heading_pos, original_pos)

    def test_second_page_load_reuses_cached_translation(self):
        fake = FakeInterviewLLMProvider(
            translate_titles_results=[{self.candidate.scout_id: self.display_title}]
        )
        self._start_server(fake)

        self._get("/")
        self._get("/")  # 새로고침

        self.assertEqual(len(fake.translate_titles_calls), 1)

    def test_llm_unset_shows_original_title_only(self):
        self._start_server(None)

        status, body = self._get("/")

        self.assertEqual(status, 200)
        self.assertIn(html_escape(self.candidate.title), body)
        self.assertNotIn('class="title-en"', body)


if __name__ == "__main__":
    unittest.main()
