#!/usr/bin/env python3
"""TAK OPERATOR MVP: SCOUT -> INTERVIEW -> BRAIN(KNOWLEDGE) -> 승인 -> MEDIA
전체 흐름을 하나의 CLI 진입점으로 잇는다.

이 스크립트는 새 비즈니스 로직을 구현하지 않는다. 각 단계는 이미 구현되고 테스트된
기존 함수를 그대로 호출만 한다(scripts/run_daily.py와 같은 원칙):

    tak_scout.load_daily_pack                   TAK SCOUT 오늘의 소재 읽기
    tak_scout.build_interview_question          TAK INTERVIEW 질문 생성(4지선다 + D)
    tak_scout.InterviewAnswer / upsert_answer    답변 저장
    tak_scout.append_scout_knowledge             TAK BRAIN KNOWLEDGE 생성(pending)
    tak_scout.build_knowledge_from_interview     방금 만든 KNOWLEDGE 조회(id 계산)
    tak_brain.load_knowledge_records             KNOWLEDGE 조회
    tak_brain.review_knowledge_file              승인(approved) 처리
    content_engine.run_media_batch_file          TAK MEDIA 배치 실행(Blog/Shorts/Threads)
    content_engine.OpenAICompatibleRewriteProvider  --execute일 때만 실제 LLM 호출

이 스크립트가 절대 하지 않는 것:
    - Threads 실제 게시 (scripts/publish_threads.py 등은 호출하지 않는다)
    - Naver Blog 게시
    - Validator/LLM prompt 수정
    - GitHub Actions 수정

TAK MEDIA 단계는 기본적으로 MockRewriteProvider를 사용해 네트워크 호출 없이 즉시
valid/rejected 결과를 보여준다. 실제 LLM을 쓰려면 --execute와 환경변수
(TAK_MEDIA_LLM_API_KEY, TAK_MEDIA_LLM_ENDPOINT, TAK_MEDIA_LLM_MODEL)가 필요하다
(scripts/run_media_batch.py의 --execute와 동일한 규칙).
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_engine import (
    LLMConfigurationError,
    MediaBatchReport,
    MockRewriteProvider,
    OpenAICompatibleRewriteProvider,
    RewriteProvider,
    archive_report,
    run_media_batch_file,
)
from tak_brain import KnowledgeRecord, load_knowledge_records, review_knowledge_file
from tak_scout import (
    InterviewAnswer,
    InterviewAnswerError,
    InterviewQuestion,
    ScoutCandidate,
    append_scout_knowledge,
    build_interview_question,
    build_knowledge_from_interview,
    load_answers,
    load_daily_pack,
    upsert_answer,
)

InputFunc = Callable[[str], str]
PrintFunc = Callable[..., None]


class OperatorCancelled(Exception):
    """사용자가 흐름 중간에 입력을 중단했을 때(EOF 등) 사용한다."""


def _prompt(input_func: InputFunc, prompt_text: str) -> str:
    try:
        return input_func(prompt_text)
    except (EOFError, StopIteration) as error:
        raise OperatorCancelled("입력이 중단되었습니다.") from error


def print_banner(print_func: PrintFunc = print) -> None:
    print_func("=" * 40)
    print_func("          TAK AUTO")
    print_func("=" * 40)


def format_candidate_list(
    candidates: list[ScoutCandidate],
    answered_scout_ids: frozenset[str] = frozenset(),
) -> str:
    """오늘의 소재 목록을 표시용 문자열로 만든다.

    data/tak_interview_answers.json에 이미 답변이 있는 scout_id는 제목 뒤에
    "[이미 답변함]"을 붙인다. 표시만 추가할 뿐, tak_interview_answers.json의
    데이터 구조나 판단 로직(InterviewAnswer/upsert_answer)은 전혀 바꾸지 않는다.
    """
    lines = ["", "오늘의 소재", ""]
    for index, candidate in enumerate(candidates, start=1):
        summary = candidate.summary.strip() or "(요약 없음)"
        marker = " [이미 답변함]" if candidate.scout_id in answered_scout_ids else ""
        lines.append(f"{index}. {candidate.title}{marker}")
        lines.append(f"   출처: {candidate.source_name or '알 수 없음'}")
        lines.append(f"   요약: {summary}")
        lines.append("")
    return "\n".join(lines).rstrip("\n")


def select_candidate(
    candidates: list[ScoutCandidate],
    input_func: InputFunc = input,
    print_func: PrintFunc = print,
    answered_scout_ids: frozenset[str] = frozenset(),
) -> ScoutCandidate:
    if not candidates:
        raise OperatorCancelled("오늘의 SCOUT 소재가 없습니다. 먼저 scripts/run_scout.py를 실행하세요.")
    print_func(format_candidate_list(candidates, answered_scout_ids))
    while True:
        raw = _prompt(input_func, "\n번호 선택: ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(candidates):
            selected = candidates[int(raw) - 1]
            if selected.scout_id in answered_scout_ids:
                print_func(
                    "\n이 소재에는 이미 답변이 있습니다.\n"
                    "기존 답변을 다시 사용하거나 새로운 답변으로 덮어쓸 수 있습니다."
                )
            return selected
        print_func(f"1부터 {len(candidates)} 사이의 번호를 입력하세요.")


def show_question(
    candidate: ScoutCandidate, question: InterviewQuestion, print_func: PrintFunc = print
) -> None:
    print_func("")
    print_func("선택한 소재:")
    print_func("")
    print_func(f"제목: {candidate.title}")
    print_func(f"출처: {candidate.source_name or '알 수 없음'} ({candidate.source_url})")
    print_func("")
    print_func("질문:")
    print_func(question.question)
    print_func("")
    print_func(question.option_a)
    print_func(question.option_b)
    print_func(question.option_c)
    print_func(question.option_d)


def collect_answer(
    candidate: ScoutCandidate,
    question: InterviewQuestion,
    input_func: InputFunc = input,
    print_func: PrintFunc = print,
) -> InterviewAnswer:
    while True:
        raw = _prompt(input_func, "\n선택 (A/B/C/D): ").strip().upper()
        custom_answer = ""
        if raw == "D":
            custom_answer = _prompt(input_func, "직접 입력: ").strip()
        try:
            return InterviewAnswer.create(candidate.scout_id, raw, custom_answer)
        except InterviewAnswerError as error:
            print_func(f"오류: {error} (다시 선택하세요)")


def display_knowledge(record: KnowledgeRecord, print_func: PrintFunc = print) -> None:
    print_func("")
    print_func("KNOWLEDGE 생성 완료")
    print_func("")
    print_func(f"id: {record.id}")
    print_func(f"제목: {record.title}")
    print_func(f"도메인: {record.domain}")
    print_func("")
    for line in record.evidence:
        print_func(f"  {line}")
    print_func("")
    print_func(f"현재 상태: {record.knowledge_review_status}")


def ask_approval(input_func: InputFunc = input, print_func: PrintFunc = print) -> bool:
    while True:
        raw = _prompt(input_func, "\n승인하시겠습니까? (Y=승인 / N=보류): ").strip().upper()
        if raw in ("Y", "N"):
            return raw == "Y"
        print_func("Y 또는 N을 입력하세요.")


_PLATFORM_LABELS = {"blog": "Blog", "shorts": "Shorts", "threads": "Threads"}


def display_media_report(report: MediaBatchReport, print_func: PrintFunc = print) -> None:
    print_func("")
    print_func("결과:")
    print_func("")
    counters: dict[str, int] = {}
    for item in report.items:
        label = _PLATFORM_LABELS.get(item.platform, item.platform)
        if label == "Blog":
            display_label = "Blog"
        else:
            counters[label] = counters.get(label, 0) + 1
            display_label = f"{label} {counters[label]}"
        print_func(f"{display_label:<12} {item.status}")
    print_func("")
    print_func(
        f"총 {report.total_draft_count}건 "
        f"(valid {report.valid_count}, rejected {report.rejected_count}, error {report.error_count})"
    )


def run_operator(
    *,
    daily_pack_path: Path,
    answers_path: Path,
    knowledge_path: Path,
    media_output_path: Path,
    media_archive_path: Path,
    execute: bool = False,
    input_func: InputFunc = input,
    print_func: PrintFunc = print,
) -> int:
    """SCOUT -> INTERVIEW -> KNOWLEDGE -> 승인 -> MEDIA 전체 흐름을 1회 실행한다.

    Threads/Naver 실제 게시는 이 함수에서 절대 호출하지 않는다.
    """
    print_banner(print_func)

    try:
        candidates = load_daily_pack(daily_pack_path)
    except (OSError, ValueError) as error:
        print_func(f"오류: 오늘의 SCOUT 결과를 읽을 수 없습니다: {error}")
        return 1

    try:
        answered_scout_ids = frozenset(answer.scout_id for answer in load_answers(answers_path))
    except (OSError, ValueError) as error:
        print_func(f"오류: 기존 답변을 읽을 수 없습니다: {error}")
        return 1

    try:
        candidate = select_candidate(candidates, input_func, print_func, answered_scout_ids)
        question = build_interview_question(candidate)
        show_question(candidate, question, print_func)
        answer = collect_answer(candidate, question, input_func, print_func)
    except OperatorCancelled as error:
        print_func(f"\n중단: {error}")
        return 1

    upsert_answer(answers_path, answer)

    created, skipped_unanswered, duplicates = append_scout_knowledge(
        daily_pack_path, answers_path, knowledge_path
    )
    print_func(
        f"\nTAK BRAIN: 신규 KNOWLEDGE {created}건 생성"
        f" (미답변 건너뜀 {skipped_unanswered}건, 중복 {duplicates}건)"
    )

    expected = build_knowledge_from_interview(candidate, answer)
    records_by_id = {record.id: record for record in load_knowledge_records(knowledge_path)}
    record = records_by_id.get(expected.id)
    if record is None:
        print_func("오류: 생성된 KNOWLEDGE를 찾을 수 없습니다.")
        return 1

    display_knowledge(record, print_func)

    try:
        approve = ask_approval(input_func, print_func)
    except OperatorCancelled as error:
        print_func(f"\n중단: {error}")
        return 1

    if not approve:
        print_func("\n보류되었습니다. TAK MEDIA를 실행하지 않습니다.")
        return 0

    approved_record = review_knowledge_file(
        knowledge_path, record.id, "approved", review_note="TAK OPERATOR MVP 승인"
    )
    print_func(f"\nKNOWLEDGE 승인 완료: {approved_record.id} -> {approved_record.knowledge_review_status}")

    provider: RewriteProvider
    if execute:
        try:
            provider = OpenAICompatibleRewriteProvider.from_environment()
        except LLMConfigurationError as error:
            print_func(f"오류: 실제 LLM 설정이 올바르지 않습니다: {error}")
            return 1
        print_func("\nTAK MEDIA 실행 중 (--execute: 실제 LLM 호출)...")
    else:
        provider = MockRewriteProvider()
        print_func(
            "\nTAK MEDIA 실행 중 (--execute 없이 실행: MockRewriteProvider 사용, "
            "실제 LLM 호출 없음)..."
        )

    report = run_media_batch_file(
        input_path=knowledge_path,
        output_path=media_output_path,
        provider=provider,
        knowledge_id=approved_record.id,
    )

    # --media-output 여부와 무관하게 실제 생성 결과 전체(valid/rejected/error)를
    # 아카이브에 누적 보존한다 (5-27 설계 문서).
    archive_report(report, media_archive_path)

    display_media_report(report, print_func)
    print_func(f"\n배치 결과 저장: {media_output_path}")
    print_func(f"아카이브 저장: {media_archive_path}")
    print_func(
        "\n안내: 위 결과는 Draft이며, Threads 실제 게시/Naver Blog 게시는 "
        "이 스크립트에서 수행하지 않습니다. 사람이 별도로 검토·게시하세요."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="TAK AUTO: SCOUT -> INTERVIEW -> KNOWLEDGE -> 승인 -> MEDIA 통합 CLI (TAK OPERATOR MVP)"
    )
    parser.add_argument(
        "--daily-pack", type=Path, default=ROOT / "data" / "tak_scout_daily.json",
        help="TAK SCOUT 결과 경로 (기본값: data/tak_scout_daily.json)",
    )
    parser.add_argument(
        "--answers", type=Path, default=ROOT / "data" / "tak_interview_answers.json",
        help="TAK INTERVIEW 답변 저장 경로 (기본값: data/tak_interview_answers.json)",
    )
    parser.add_argument(
        "--knowledge", type=Path, default=ROOT / "data" / "tak_brain_knowledge.json",
        help="KNOWLEDGE 누적 저장 경로 (기본값: data/tak_brain_knowledge.json)",
    )
    parser.add_argument(
        "--media-output", type=Path, default=ROOT / "data" / "tak_media_batch_operator.json",
        help="TAK MEDIA 배치 결과 저장 경로 (기본값: data/tak_media_batch_operator.json)",
    )
    parser.add_argument(
        "--media-archive", type=Path, default=ROOT / "data" / "tak_media_archive.json",
        help=(
            "TAK MEDIA 배치 결과 전체(valid/rejected/error 포함)를 content_id 기준으로 "
            "누적 보존하는 아카이브 경로 (기본값: data/tak_media_archive.json)"
        ),
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help=(
            "TAK MEDIA 단계에서 실제 LLM API를 호출한다"
            "(환경변수 TAK_MEDIA_LLM_API_KEY/ENDPOINT/MODEL 필요). "
            "지정하지 않으면 MockRewriteProvider로 네트워크 호출 없이 실행한다."
        ),
    )
    args = parser.parse_args(argv)

    return run_operator(
        daily_pack_path=args.daily_pack,
        answers_path=args.answers,
        knowledge_path=args.knowledge,
        media_output_path=args.media_output,
        media_archive_path=args.media_archive,
        execute=args.execute,
    )


if __name__ == "__main__":
    raise SystemExit(main())
