"""TAK SCOUT 후보마다 티몽의 의견을 끌어내는 4지선다 + 직접 입력 질문을 만든다.

완벽한 AI 인터뷰 시스템을 만들지 않는다. 소재마다 question/option_a..d 구조를 만들고,
D는 항상 "내 생각 직접 입력"을 의미한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
from typing import Any

from blog_importer.models import utc_now

from .models import ScoutCandidate, subject_label


@dataclass(frozen=True)
class InterviewQuestion:
    """TAK SCOUT 후보 1건에 대한 인터뷰 질문."""

    scout_id: str
    title: str
    question: str
    option_a: str
    option_b: str
    option_c: str
    option_d: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "scout_id": self.scout_id,
            "title": self.title,
            "question": self.question,
            "option_a": self.option_a,
            "option_b": self.option_b,
            "option_c": self.option_c,
            "option_d": self.option_d,
        }


def build_interview_question(candidate: ScoutCandidate) -> InterviewQuestion:
    """소재 내용(제목/category)에 맞춰 선택지를 조금 더 구체적으로 만든다."""
    subject = subject_label(candidate)
    return InterviewQuestion(
        scout_id=candidate.scout_id,
        title=candidate.title,
        question=f"[{candidate.title}] {subject}에 대해 어떻게 생각하시나요?",
        option_a=f"A. {subject}를 긍정적으로 본다",
        option_b=f"B. {subject}를 부정적으로 본다",
        option_c="C. 상황을 더 지켜봐야 한다",
        option_d="D. 기타 / 내 생각 직접 입력",
    )


def build_interview_questions(candidates: list[ScoutCandidate]) -> list[InterviewQuestion]:
    return [build_interview_question(candidate) for candidate in candidates]


def save_questions_json(
    questions: list[InterviewQuestion], path: Path | str, generated_at: str | None = None
) -> None:
    payload = {
        "generated_at": generated_at or utc_now(),
        "question_count": len(questions),
        "questions": [question.to_dict() for question in questions],
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_questions(path: Path | str) -> list[InterviewQuestion]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("questions"), list):
        raise ValueError("tak_interview_questions.json 구조가 올바르지 않습니다.")
    questions: list[InterviewQuestion] = []
    for item in data["questions"]:
        if not isinstance(item, dict):
            raise ValueError("questions의 각 항목은 객체여야 합니다.")
        questions.append(
            InterviewQuestion(
                scout_id=str(item.get("scout_id") or ""),
                title=str(item.get("title") or ""),
                question=str(item.get("question") or ""),
                option_a=str(item.get("option_a") or ""),
                option_b=str(item.get("option_b") or ""),
                option_c=str(item.get("option_c") or ""),
                option_d=str(item.get("option_d") or ""),
            )
        )
    return questions


def render_questions_markdown(questions: list[InterviewQuestion], generated_at: str | None = None) -> str:
    generated_at = generated_at or utc_now()
    lines = [
        "# TAK INTERVIEW 질문",
        "",
        f"생성 시각(UTC): {generated_at}",
        f"질문 수: {len(questions)}",
        "",
        "D를 선택하면 항상 '내 생각 직접 입력'을 의미합니다.",
        "",
    ]
    if not questions:
        lines.append("생성된 질문이 없습니다.")
    for index, question in enumerate(questions, start=1):
        lines.extend(
            [
                f"### [{index}] {question.question}",
                "",
                question.option_a,
                question.option_b,
                question.option_c,
                question.option_d,
                "",
                f"scout_id: {question.scout_id}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def save_questions_markdown(
    questions: list[InterviewQuestion], path: Path | str, generated_at: str | None = None
) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_questions_markdown(questions, generated_at=generated_at), encoding="utf-8")
