"""tak_scout.interview_session(5-10 Phase 1) 단위 테스트.

멀티턴 인터뷰 "세션" 데이터 계층만 검증한다. LLM/Dashboard/기존 답변 파일은
이 테스트에서 전혀 다루지 않는다(Phase 1 범위 밖).
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tak_scout.interview_session import (
    InterviewSession,
    InterviewSessionError,
    InterviewTurnRecord,
    load_sessions,
    save_sessions,
    upsert_session,
)


def _turn(
    turn: int = 1,
    question: str = "이 이슈에 대해 어떻게 생각하시나요?",
    selected_option: str | None = None,
    custom_answer: str = "",
    answered_at: str | None = None,
    generated_by: str = "template",
) -> InterviewTurnRecord:
    return InterviewTurnRecord(
        turn=turn,
        question=question,
        option_a="A. 적극적으로 경험해봐야 한다",
        option_b="B. 위험성을 먼저 봐야 한다",
        option_c="C. 아직 판단하기 이르다",
        option_d="D. 직접 입력",
        generated_by=generated_by,
        selected_option=selected_option,
        custom_answer=custom_answer,
        answered_at=answered_at,
    )


def _session(
    scout_id: str = "scout-abc123",
    status: str = "in_progress",
    turns: tuple[InterviewTurnRecord, ...] = (),
    perspective_summary: str = "",
    completed_at: str | None = None,
) -> InterviewSession:
    return InterviewSession(
        scout_id=scout_id,
        status=status,
        turns=turns,
        perspective_summary=perspective_summary,
        created_at="2026-09-14T06:00:00+00:00",
        updated_at="2026-09-14T06:00:00+00:00",
        completed_at=completed_at,
    )


class InterviewTurnRecordTests(unittest.TestCase):
    # 1. InterviewTurnRecord 생성
    def test_construction(self):
        turn = _turn(turn=1, selected_option="D", custom_answer="신기술은 두려워 말고 부딪혀서 느껴봐야 한다.")
        self.assertEqual(turn.turn, 1)
        self.assertEqual(turn.generated_by, "template")
        self.assertEqual(turn.selected_option, "D")
        self.assertEqual(turn.custom_answer, "신기술은 두려워 말고 부딪혀서 느껴봐야 한다.")

    def test_turn_dict_round_trip(self):
        turn = _turn(turn=2, selected_option="A", answered_at="2026-09-14T06:05:00+00:00", generated_by="llm")
        restored = InterviewTurnRecord.from_dict(turn.to_dict())
        self.assertEqual(turn, restored)

    def test_turn_with_no_answer_yet_uses_none(self):
        turn = _turn(turn=1)  # selected_option/answered_at 기본값 None
        self.assertIsNone(turn.selected_option)
        self.assertIsNone(turn.answered_at)
        restored = InterviewTurnRecord.from_dict(turn.to_dict())
        self.assertIsNone(restored.selected_option)
        self.assertIsNone(restored.answered_at)

    def test_invalid_turn_type_is_rejected(self):
        with self.assertRaises(InterviewSessionError):
            InterviewTurnRecord.from_dict({"turn": "1", "question": "Q"})

    def test_missing_question_is_rejected(self):
        with self.assertRaises(InterviewSessionError):
            InterviewTurnRecord.from_dict({"turn": 1, "question": ""})


class InterviewSessionModelTests(unittest.TestCase):
    # 2. InterviewSession 생성
    def test_construction(self):
        session = _session(turns=(_turn(),))
        self.assertEqual(session.scout_id, "scout-abc123")
        self.assertEqual(session.status, "in_progress")
        self.assertEqual(len(session.turns), 1)
        self.assertIsNone(session.completed_at)

    # 3. session -> dict -> session round trip
    def test_session_dict_round_trip(self):
        session = _session(
            turns=(
                _turn(turn=1, selected_option="D", custom_answer="첫 답변"),
                _turn(turn=2, selected_option="A"),
            ),
            perspective_summary="신기술을 직접 경험해야 한다는 입장",
        )
        restored = InterviewSession.from_dict(session.to_dict())
        self.assertEqual(session, restored)
        self.assertEqual(restored.turns[0].custom_answer, "첫 답변")
        self.assertEqual(restored.turns[1].turn, 2)

    # 9. completed_at None 처리
    def test_completed_at_none_round_trips_as_none(self):
        session = _session(status="in_progress", completed_at=None)
        payload = session.to_dict()
        self.assertIsNone(payload["completed_at"])
        restored = InterviewSession.from_dict(payload)
        self.assertIsNone(restored.completed_at)

    def test_completed_session_keeps_completed_at(self):
        session = _session(status="completed", completed_at="2026-09-14T06:10:00+00:00")
        restored = InterviewSession.from_dict(session.to_dict())
        self.assertEqual(restored.status, "completed")
        self.assertEqual(restored.completed_at, "2026-09-14T06:10:00+00:00")

    def test_invalid_status_is_rejected(self):
        with self.assertRaises(InterviewSessionError):
            InterviewSession.from_dict({**_session().to_dict(), "status": "unknown"})

    def test_missing_scout_id_is_rejected(self):
        with self.assertRaises(InterviewSessionError):
            InterviewSession.from_dict({**_session().to_dict(), "scout_id": ""})


class InterviewSessionFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "tak_interview_sessions.json"

    # 7. session 파일이 없어도 정상적으로 빈 목록 반환
    def test_load_missing_file_returns_empty_list(self):
        self.assertEqual(load_sessions(self.path), [])

    def test_load_empty_file_returns_empty_list(self):
        self.path.write_text("", encoding="utf-8")
        self.assertEqual(load_sessions(self.path), [])

    def test_load_rejects_non_list_structure(self):
        self.path.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
        with self.assertRaises(InterviewSessionError):
            load_sessions(self.path)

    # 4. 파일 저장 -> 로드
    def test_save_then_load_round_trip(self):
        sessions = [_session(scout_id="scout-1", turns=(_turn(turn=1, selected_option="A"),))]
        save_sessions(sessions, self.path)

        loaded = load_sessions(self.path)
        self.assertEqual(loaded, sessions)

    # 10. JSON이 사람이 읽기 쉬운 구조인지 (들여쓰기, 필드명이 그대로 보이는지)
    def test_saved_json_is_human_readable(self):
        save_sessions([_session(scout_id="scout-1", turns=(_turn(turn=1, selected_option="A"),))], self.path)

        raw_text = self.path.read_text(encoding="utf-8")
        self.assertIn("\n", raw_text)  # 한 줄로 뭉쳐 있지 않음(들여쓰기 있음)
        data = json.loads(raw_text)
        self.assertIsInstance(data, list)
        self.assertEqual(
            set(data[0].keys()),
            {"scout_id", "status", "turns", "perspective_summary", "created_at", "updated_at", "completed_at"},
        )
        self.assertEqual(
            set(data[0]["turns"][0].keys()),
            {
                "turn", "question", "option_a", "option_b", "option_c", "option_d",
                "generated_by", "selected_option", "custom_answer", "answered_at",
            },
        )

    # 5. scout_id 기준 upsert
    def test_upsert_adds_new_scout_id(self):
        upsert_session(self.path, _session(scout_id="scout-1"))
        result = upsert_session(self.path, _session(scout_id="scout-2"))

        self.assertEqual({session.scout_id for session in result}, {"scout-1", "scout-2"})

    def test_upsert_overwrites_existing_scout_id(self):
        upsert_session(self.path, _session(scout_id="scout-1", status="in_progress", turns=(_turn(turn=1),)))
        updated = _session(
            scout_id="scout-1",
            status="completed",
            turns=(_turn(turn=1, selected_option="D", custom_answer="최종 답변"),),
            completed_at="2026-09-14T06:20:00+00:00",
        )
        result = upsert_session(self.path, updated)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].status, "completed")
        self.assertEqual(result[0].turns[0].custom_answer, "최종 답변")

    # 6. 기존 session을 upsert하면 중복이 생기지 않는지
    def test_upsert_same_scout_id_twice_does_not_duplicate(self):
        upsert_session(self.path, _session(scout_id="scout-1"))
        upsert_session(self.path, _session(scout_id="scout-1", status="completed", completed_at="2026-09-14T06:30:00+00:00"))

        loaded = load_sessions(self.path)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].status, "completed")

    # 8. turn 여러 개를 정상적으로 저장/로드
    def test_multiple_turns_are_saved_and_loaded_in_order(self):
        turns = (
            _turn(turn=1, selected_option="A", answered_at="2026-09-14T06:00:00+00:00"),
            _turn(turn=2, selected_option="D", custom_answer="후속 답변", answered_at="2026-09-14T06:05:00+00:00"),
            _turn(turn=3, selected_option="B", answered_at="2026-09-14T06:10:00+00:00"),
        )
        upsert_session(self.path, _session(scout_id="scout-1", turns=turns, status="completed"))

        loaded = load_sessions(self.path)
        self.assertEqual(len(loaded[0].turns), 3)
        self.assertEqual([turn.turn for turn in loaded[0].turns], [1, 2, 3])
        self.assertEqual(loaded[0].turns[1].custom_answer, "후속 답변")

    def test_upsert_persists_across_process_boundary(self):
        # 파일을 통해서만 상태를 주고받는지(메모리 캐시에 의존하지 않는지) 확인.
        upsert_session(self.path, _session(scout_id="scout-1"))

        reloaded_first = load_sessions(self.path)
        self.assertEqual(len(reloaded_first), 1)

        upsert_session(self.path, _session(scout_id="scout-2"))
        reloaded_second = load_sessions(self.path)
        self.assertEqual(len(reloaded_second), 2)


if __name__ == "__main__":
    unittest.main()
