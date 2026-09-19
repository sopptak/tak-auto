#!/usr/bin/env python3
"""Threads "초안 생성" 전용 CLI (5-11 설계 문서 Phase 1).

기존 완전 자동 발행 경로(``scripts/run_daily.py`` -> ``scripts/publish_threads.py``)는
이 스크립트에서 전혀 import하지 않고, 한 줄도 수정하지 않는다. 이 스크립트는 그
경로와 완전히 독립적으로 존재하는 새 진입점이다.

흐름은 ``run_daily.py``의 1~3단계(TAK BRAIN 로드 -> TAK MEDIA 배치 -> Threads
rotation 선정)를 그대로 재사용하되, 마지막에 실제로 게시하는 대신
``data/tak_threads_pending.json``에 검수 대기(pending) draft 1건을 쓰고 끝난다.

이 스크립트가 절대 하지 않는 것(5-11 설계 문서 그대로):
    - ``ThreadsClient``를 import하지 않는다 (실수로도 실제 게시 코드 경로가 존재하지
      않도록 원천 차단).
    - Threads API를 호출하지 않는다.
    - ``PublishHistory``에 기록하지 않는다(읽기만 한다 - rotation 판단에 필요).
    - ``compute_content_id()``를 다시 계산하지 않는다 -
      ``select_unpublished_threads_item()``이 반환한 값을 그대로 쓴다.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from blog_importer.models import utc_now
from content_engine.llm_provider import LLMConfigurationError, OpenAICompatibleRewriteProvider
from content_engine.media_archive import archive_report
from content_engine.pipeline import run_media_batch
from content_engine.publish_history import PublishHistory, select_unpublished_threads_item
from content_engine.threads_review import ThreadsPendingDraft, has_unresolved_draft, upsert_pending
from tak_brain import load_knowledge_records, select_approved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Threads 초안 생성 전용 CLI (5-11 Phase 1 - 실제 게시는 하지 않음)"
    )
    parser.add_argument(
        "--knowledge",
        type=Path,
        default=ROOT / "data" / "tak_brain_knowledge.json",
        help="읽기 전용 KNOWLEDGE JSON 경로 (기본값: data/tak_brain_knowledge.json)",
    )
    parser.add_argument(
        "--history",
        type=Path,
        default=ROOT / "data" / "threads_publish_log.json",
        help="게시 이력 JSON 경로 (기본값: data/threads_publish_log.json, 읽기 전용)",
    )
    parser.add_argument(
        "--pending",
        type=Path,
        default=ROOT / "data" / "tak_threads_pending.json",
        help="검수 대기 draft 저장 경로 (기본값: data/tak_threads_pending.json)",
    )
    parser.add_argument(
        "--archive",
        type=Path,
        default=ROOT / "data" / "tak_media_archive.json",
        help=(
            "TAK MEDIA 배치 결과 전체(이 스크립트가 rotation으로 고르지 않은 나머지 "
            "Blog/Shorts/Threads 후보 포함, valid/rejected/error 전부)를 content_id "
            "기준으로 누적 보존하는 아카이브 경로 (기본값: data/tak_media_archive.json)"
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="처리할 승인 KNOWLEDGE 최대 개수 제한",
    )
    parser.add_argument(
        "--id",
        type=str,
        default=None,
        help="특정 KNOWLEDGE ID 1건만 대상으로 실행",
    )
    args = parser.parse_args(argv)

    # idempotency: 이미 검토 대기 중(pending/approved)인 draft가 있으면, 실제 LLM을
    # 호출하는 비싼 TAK MEDIA 배치조차 실행하지 않고 그대로 정상 종료한다(5-11 설계
    # 5장). published/failed 항목은 여기 포함되지 않는다 - 그건 이미 "처리 완료"된
    # 상태다.
    if has_unresolved_draft(args.pending):
        print("안내: 이미 검토 대기 중(pending/approved)인 Threads 초안이 있어 새로 생성하지 않습니다.")
        return 0

    # 1단계: TAK BRAIN - 승인된 KNOWLEDGE 로드 (run_daily.py와 동일한 로직 그대로)
    try:
        records = load_knowledge_records(args.knowledge)
    except (OSError, ValueError) as err:
        print(f"오류: KNOWLEDGE 파일을 읽을 수 없습니다: {err}", file=sys.stderr)
        return 1

    if args.id:
        records = [record for record in records if record.id == args.id]
        if not records:
            print(f"오류: KNOWLEDGE ID를 찾을 수 없습니다: {args.id}", file=sys.stderr)
            return 1

    approved = list(select_approved(records))
    if args.limit is not None and args.limit > 0:
        approved = approved[: args.limit]

    if not approved:
        print("승인된 KNOWLEDGE가 없습니다. 오늘 생성할 초안이 없어 정상 종료합니다.")
        return 0

    # article_type/knowledge_type을 pending draft에 함께 저장하기 위한 조회용 맵
    # (5-11 설계 6장). MediaBatchItem에는 이 필드가 없으므로 KNOWLEDGE 원본에서 찾는다.
    knowledge_by_id = {record.id: record for record in approved}

    print(f"TAK BRAIN: 승인 KNOWLEDGE {len(approved)}건 확인")

    # 2단계: TAK MEDIA - run_daily.py와 동일하게 실제 LLM provider를 명시적으로 만든다.
    try:
        provider = OpenAICompatibleRewriteProvider.from_environment()
    except LLMConfigurationError as err:
        print(f"오류: TAK MEDIA LLM 설정이 올바르지 않습니다: {err}", file=sys.stderr)
        return 1

    print("TAK MEDIA: 배치 실행 중 (콘텐츠 생성 + LLM 재작성 + 검증)...")
    try:
        report = run_media_batch(approved, provider=provider)
    except Exception as err:
        print(
            f"오류: TAK MEDIA 배치 실행에 실패했습니다: {type(err).__name__}: {err}",
            file=sys.stderr,
        )
        return 1

    print(
        "TAK MEDIA 완료: "
        f"총 Draft {report.total_draft_count}건 "
        f"(valid {report.valid_count}, rejected {report.rejected_count}, error {report.error_count})"
    )

    # 이 스크립트는 9건 중 rotation으로 고른 1건만 tak_threads_pending.json에 넘긴다
    # (아래 3~4단계). 나머지 8건(다른 Threads 후보, Blog, Shorts, rejected/error 포함)이
    # 그냥 버려지지 않도록, rotation 선정 전에 배치 결과 전체를 먼저 아카이브에
    # 남긴다(5-27 설계 문서).
    archive_report(report, args.archive)

    # 3단계: Threads rotation 선정 - 기존 select_unpublished_threads_item()을 그대로
    # 재사용한다(5-10 Phase 4-4 rotation 정책 무수정). PublishHistory는 읽기만 한다 -
    # 여기서는 절대 append()하지 않는다.
    valid_threads_items = [
        item.to_dict() for item in report.items if item.platform == "threads" and item.status == "valid"
    ]
    history = PublishHistory(args.history)
    selection = select_unpublished_threads_item(valid_threads_items, history)

    if selection is None:
        print("생성할 초안 없음: 검증 통과했지만 아직 게시하지 않은 Threads 콘텐츠가 없습니다.")
        return 0

    item, content_id = selection
    knowledge_id = str(item.get("knowledge_id") or "")
    knowledge = knowledge_by_id.get(knowledge_id)

    # 4단계: pending draft 저장. status는 항상 "pending", final_title/final_body는
    # 항상 None(승인 전이므로) - 5-11 설계 6장 그대로.
    draft = ThreadsPendingDraft(
        content_id=content_id,
        knowledge_id=knowledge_id,
        source_url=str(item.get("source_url") or ""),
        evidence_unit_ids=tuple(item.get("evidence_unit_ids") or ()),
        article_type=knowledge.article_type if knowledge else None,
        knowledge_type=knowledge.knowledge_type if knowledge else None,
        original_title=str(item.get("original_title") or ""),
        original_body=str(item.get("original_body") or ""),
        ai_rewritten_title=str(item.get("rewritten_title") or ""),
        ai_rewritten_body=str(item.get("rewritten_body") or ""),
        status="pending",
        created_at=utc_now(),
    )
    upsert_pending(args.pending, draft)

    print(f"Threads 초안 생성 완료 (검수 대기): content_id={content_id} KNOWLEDGE={knowledge_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
