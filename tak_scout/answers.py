"""티몽의 인터뷰 답변(A/B/C/D + 직접 입력)을 저장하고 불러온다.

data/tak_interview_answers.json에 답변이 없는 소재는 TAK BRAIN KNOWLEDGE로 넘어가지
않는다(knowledge_bridge.append_scout_knowledge 참고).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import tempfile
from typing import Any

from blog_importer.models import utc_now


VALID_OPTIONS = ("A", "B", "C", "D")


class InterviewAnswerError(ValueError):
    """답변 구조가 올바르지 않을 때 발생한다."""


def _validate(selected_option: str, custom_answer: str) -> None:
    if selected_option not in VALID_OPTIONS:
        raise InterviewAnswerError(f"selected_option은 A/B/C/D 중 하나여야 합니다: {selected_option!r}")
    if selected_option == "D" and not custom_answer.strip():
        raise InterviewAnswerError("D(직접 입력)를 선택하면 custom_answer가 필요합니다.")


@dataclass(frozen=True)
class InterviewAnswer:
    scout_id: str
    selected_option: str
    custom_answer: str
    answered_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "scout_id": self.scout_id,
            "selected_option": self.selected_option,
            "custom_answer": self.custom_answer,
            "answered_at": self.answered_at,
        }

    @classmethod
    def create(cls, scout_id: str, selected_option: str, custom_answer: str = "") -> "InterviewAnswer":
        if not scout_id:
            raise InterviewAnswerError("scout_id가 필요합니다.")
        option = selected_option.strip().upper()
        custom_answer = custom_answer.strip()
        _validate(option, custom_answer)
        return cls(scout_id=scout_id, selected_option=option, custom_answer=custom_answer, answered_at=utc_now())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InterviewAnswer":
        scout_id = str(data.get("scout_id") or "")
        if not scout_id:
            raise InterviewAnswerError("scout_id가 필요합니다.")
        option = str(data.get("selected_option") or "").strip().upper()
        custom_answer = str(data.get("custom_answer") or "").strip()
        _validate(option, custom_answer)
        return cls(
            scout_id=scout_id,
            selected_option=option,
            custom_answer=custom_answer,
            answered_at=str(data.get("answered_at") or ""),
        )


def load_answers(path: Path | str) -> list[InterviewAnswer]:
    """답변 파일을 읽는다. 파일이 없거나 비어 있으면 빈 목록을 반환한다."""
    target = Path(path)
    if not target.exists():
        return []
    raw_text = target.read_text(encoding="utf-8").strip()
    if not raw_text:
        return []
    data = json.loads(raw_text)
    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        raise InterviewAnswerError("tak_interview_answers.json은 객체 목록이어야 합니다.")
    return [InterviewAnswer.from_dict(item) for item in data]


def save_answers(answers: list[InterviewAnswer], path: Path | str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = [answer.to_dict() for answer in answers]
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temp_path = Path(handle.name)
    temp_path.replace(target)


def upsert_answer(path: Path | str, answer: InterviewAnswer) -> list[InterviewAnswer]:
    """같은 scout_id의 기존 답변은 덮어쓰고, 새 scout_id는 추가한다."""
    by_scout_id = {existing.scout_id: existing for existing in load_answers(path)}
    by_scout_id[answer.scout_id] = answer
    result = list(by_scout_id.values())
    save_answers(result, path)
    return result
