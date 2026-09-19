"""TAK SCOUT Interview 2.0(5-10)의 멀티턴 인터뷰 "세션" 데이터 계층.

이 모듈은 오직 데이터 구조와 저장/로드만 담당한다(5-10 설계 문서의
Phase 1). 질문 생성, LLM 호출, 충분성 판단, Dashboard 라우팅은 이후
Phase에서 다룬다 - 이 파일은 그런 로직을 전혀 포함하지 않는다.

data/tak_interview_answers.json(기존 InterviewAnswer, tak_scout/answers.py)과는
완전히 분리된 파일 data/tak_interview_sessions.json에 저장한다. 이 파일은
scout_id당 세션 1개를 담고, 세션 안에 턴(질문+답변)이 여러 개 들어간다.
기존 InterviewAnswer/answers.py/knowledge_bridge.py/interview.py는 이 모듈을
전혀 참조하지 않으며, 이 모듈도 그 파일들을 import하지 않는다 - 완전히
독립적인 신규 계층이다(5-10 설계 문서 5~6번 참고).

같은 패턴을 그대로 따른다(tak_scout/answers.py 참고):
    load_sessions()   파일이 없거나 비어 있으면 빈 목록
    save_sessions()   tempfile + os.replace로 원자적 저장
    upsert_session()  scout_id 기준으로 덮어쓰기(중복 없음)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import tempfile
from typing import Any


VALID_STATUSES = ("in_progress", "completed")


class InterviewSessionError(ValueError):
    """세션/턴 구조가 올바르지 않을 때 발생한다."""


@dataclass(frozen=True)
class InterviewTurnRecord:
    """인터뷰 세션 안의 턴(질문 1개 + 그 답) 1건."""

    turn: int
    question: str
    option_a: str
    option_b: str
    option_c: str
    option_d: str
    generated_by: str
    selected_option: str | None
    custom_answer: str
    answered_at: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn": self.turn,
            "question": self.question,
            "option_a": self.option_a,
            "option_b": self.option_b,
            "option_c": self.option_c,
            "option_d": self.option_d,
            "generated_by": self.generated_by,
            "selected_option": self.selected_option,
            "custom_answer": self.custom_answer,
            "answered_at": self.answered_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InterviewTurnRecord":
        if not isinstance(data, dict):
            raise InterviewSessionError("turn 항목은 객체여야 합니다.")

        turn = data.get("turn")
        if not isinstance(turn, int) or isinstance(turn, bool):
            raise InterviewSessionError(f"turn은 정수여야 합니다: {turn!r}")

        question = str(data.get("question") or "")
        if not question:
            raise InterviewSessionError("question이 필요합니다.")

        selected_option = data.get("selected_option")
        if selected_option is not None:
            selected_option = str(selected_option)

        answered_at = data.get("answered_at")
        if answered_at is not None:
            answered_at = str(answered_at)

        return cls(
            turn=turn,
            question=question,
            option_a=str(data.get("option_a") or ""),
            option_b=str(data.get("option_b") or ""),
            option_c=str(data.get("option_c") or ""),
            option_d=str(data.get("option_d") or ""),
            generated_by=str(data.get("generated_by") or ""),
            selected_option=selected_option,
            custom_answer=str(data.get("custom_answer") or ""),
            answered_at=answered_at,
        )


@dataclass(frozen=True)
class InterviewSession:
    """소재 1건(scout_id)에 대한 멀티턴 인터뷰 세션 전체."""

    scout_id: str
    status: str
    turns: tuple[InterviewTurnRecord, ...]
    perspective_summary: str
    created_at: str
    updated_at: str
    completed_at: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "scout_id": self.scout_id,
            "status": self.status,
            "turns": [turn.to_dict() for turn in self.turns],
            "perspective_summary": self.perspective_summary,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InterviewSession":
        if not isinstance(data, dict):
            raise InterviewSessionError("session 항목은 객체여야 합니다.")

        scout_id = str(data.get("scout_id") or "")
        if not scout_id:
            raise InterviewSessionError("scout_id가 필요합니다.")

        status = str(data.get("status") or "")
        if status not in VALID_STATUSES:
            raise InterviewSessionError(f"status는 {VALID_STATUSES} 중 하나여야 합니다: {status!r}")

        raw_turns = data.get("turns")
        if not isinstance(raw_turns, list):
            raise InterviewSessionError("turns는 목록이어야 합니다.")
        turns = tuple(InterviewTurnRecord.from_dict(item) for item in raw_turns)

        completed_at = data.get("completed_at")
        if completed_at is not None:
            completed_at = str(completed_at)

        return cls(
            scout_id=scout_id,
            status=status,
            turns=turns,
            perspective_summary=str(data.get("perspective_summary") or ""),
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
            completed_at=completed_at,
        )


def load_sessions(path: Path | str) -> list[InterviewSession]:
    """세션 파일을 읽는다. 파일이 없거나 비어 있으면 빈 목록을 반환한다."""
    target = Path(path)
    if not target.exists():
        return []
    raw_text = target.read_text(encoding="utf-8").strip()
    if not raw_text:
        return []
    data = json.loads(raw_text)
    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        raise InterviewSessionError("tak_interview_sessions.json은 객체 목록이어야 합니다.")
    return [InterviewSession.from_dict(item) for item in data]


def save_sessions(sessions: list[InterviewSession], path: Path | str) -> None:
    """세션 목록을 원자적으로(tempfile + replace) 저장한다."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = [session.to_dict() for session in sessions]
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temp_path = Path(handle.name)
    temp_path.replace(target)


def upsert_session(path: Path | str, session: InterviewSession) -> list[InterviewSession]:
    """같은 scout_id의 기존 세션은 덮어쓰고, 새 scout_id는 추가한다."""
    by_scout_id = {existing.scout_id: existing for existing in load_sessions(path)}
    by_scout_id[session.scout_id] = session
    result = list(by_scout_id.values())
    save_sessions(result, path)
    return result
