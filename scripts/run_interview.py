#!/usr/bin/env python3
"""TAK SCOUT 후보에 대한 인터뷰 질문을 만들고, 원하면 터미널에서 바로 답변을 받는 CLI.

동작 순서:

1. data/tak_scout_daily.json을 읽어 후보마다 4지선다(A/B/C/D) 질문을 만든다.
   D는 항상 "내 생각 직접 입력"을 의미한다.
2. data/tak_interview_questions.json / .md로 저장한다(사람이 읽기 위함).
3. --interactive를 주면 아직 답변하지 않은 소재만 터미널에서 차례로 물어보고,
   그 결과를 data/tak_interview_answers.json에 저장한다.
   --interactive 없이 실행하면 질문만 만들고, data/tak_interview_answers.json을
   직접 편집해 답할 수도 있다는 안내만 출력한다.

이미 답변한 소재는 다시 KNOWLEDGE로 중복 연결되지 않는다(scripts/apply_interview.py 참고).
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tak_scout.answers import InterviewAnswer, InterviewAnswerError, load_answers, upsert_answer
from tak_scout.collector import load_daily_pack
from tak_scout.interview import (
    InterviewQuestion,
    build_interview_questions,
    save_questions_json,
    save_questions_markdown,
)


def _ask_interactively(
    questions: list[InterviewQuestion], answers_path: Path, already_answered: set[str]
) -> int:
    answered_count = 0
    for question in questions:
        if question.scout_id in already_answered:
            continue
        print()
        print(question.question)
        print(f"  {question.option_a}")
        print(f"  {question.option_b}")
        print(f"  {question.option_c}")
        print(f"  {question.option_d}")
        try:
            choice = input("선택 (A/B/C/D, 건너뛰려면 Enter): ").strip().upper()
        except EOFError:
            break
        if not choice:
            print("  건너뜀")
            continue
        custom_answer = ""
        if choice == "D":
            try:
                custom_answer = input("  직접 입력: ").strip()
            except EOFError:
                custom_answer = ""
        try:
            answer = InterviewAnswer.create(question.scout_id, choice, custom_answer)
        except InterviewAnswerError as error:
            print(f"  오류: {error} (건너뜀)")
            continue
        upsert_answer(answers_path, answer)
        already_answered.add(question.scout_id)
        answered_count += 1
        print("  저장 완료")
    return answered_count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TAK INTERVIEW 질문 생성 및 답변 수집")
    parser.add_argument(
        "--daily-pack",
        type=Path,
        default=ROOT / "data" / "tak_scout_daily.json",
        help="TAK SCOUT 결과 경로 (기본값: data/tak_scout_daily.json)",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=ROOT / "data" / "tak_interview_questions.json",
        help="질문 저장 경로(JSON, 기본값: data/tak_interview_questions.json)",
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=ROOT / "data" / "tak_interview_questions.md",
        help="질문 저장 경로(Markdown, 기본값: data/tak_interview_questions.md)",
    )
    parser.add_argument(
        "--answers",
        type=Path,
        default=ROOT / "data" / "tak_interview_answers.json",
        help="답변 저장 경로 (기본값: data/tak_interview_answers.json)",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="터미널에서 바로 A/B/C/D 답변을 입력받는다",
    )
    args = parser.parse_args(argv)

    try:
        candidates = load_daily_pack(args.daily_pack)
    except (OSError, ValueError) as err:
        print(f"오류: {args.daily_pack}를 읽을 수 없습니다: {err}", file=sys.stderr)
        return 1

    if not candidates:
        print("오늘 생성된 TAK SCOUT 후보가 없습니다. 먼저 python3 scripts/run_scout.py를 실행하세요.")
        return 0

    questions = build_interview_questions(candidates)
    save_questions_json(questions, args.output_json)
    save_questions_markdown(questions, args.output_md)

    print(f"TAK INTERVIEW: 질문 {len(questions)}건 생성")
    print(f"JSON 저장: {args.output_json}")
    print(f"MD 저장: {args.output_md}")

    try:
        existing = {answer.scout_id for answer in load_answers(args.answers)}
    except InterviewAnswerError as err:
        print(f"오류: 기존 답변 파일을 읽을 수 없습니다: {err}", file=sys.stderr)
        return 1

    unanswered_count = sum(1 for question in questions if question.scout_id not in existing)

    if args.interactive:
        answered_count = _ask_interactively(questions, args.answers, set(existing))
        print(f"인터뷰 완료: 이번에 {answered_count}건 답변")
    else:
        print(f"아직 답변하지 않은 소재: {unanswered_count}건")
        print("터미널에서 바로 답하려면: python3 scripts/run_interview.py --interactive")
        print(f"또는 {args.answers} 파일을 직접 편집해 A/B/C/D 답변을 추가할 수 있습니다.")

    print("다음 단계: python3 scripts/apply_interview.py 로 답변을 KNOWLEDGE에 연결하세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
