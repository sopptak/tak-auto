#!/usr/bin/env python3
"""승인된 KNOWLEDGE를 일괄 처리하여 콘텐츠 생성·재작성·검증하는 배치 파이프라인 CLI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_engine import (
    OpenAICompatibleRewriteProvider,
    archive_generation_report,
    archive_report,
    generate_media_batch_dry_run,
    run_media_batch_file,
)
from tak_brain import load_knowledge_records, select_approved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TAK MEDIA Batch Pipeline")
    parser.add_argument(
        "--input",
        type=Path,
        default=ROOT / "data" / "tak_brain_knowledge.json",
        help="읽기 전용 KNOWLEDGE JSON 경로 (기본값: data/tak_brain_knowledge.json)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "배치 결과 저장 JSON 경로 (선택, 이번 실행만의 스냅샷). "
            "지정하지 않아도 --execute 실행 결과는 --archive 경로에 항상 누적 보존된다."
        ),
    )
    parser.add_argument(
        "--archive",
        type=Path,
        default=ROOT / "data" / "tak_media_archive.json",
        help=(
            "--execute 실행 결과(Blog/Shorts/Threads 전체, valid/rejected/error 포함)를 "
            "content_id 기준으로 누적 보존하는 아카이브 경로 "
            "(기본값: data/tak_media_archive.json). --output과 달리 매 실행마다 결과가 "
            "쌓이며, --output을 지정하지 않아도 이 경로에는 항상 저장된다."
        ),
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="실제 LLM API 호출을 명시적으로 허용합니다.",
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
    parser.add_argument(
        "--as-generation",
        action="store_true",
        help=(
            "6-06: --archive를 production archive(content_id 단독 키, 슬롯당 활성 레코드 1개)가 "
            "아니라 'generation pool'로 취급합니다. 같은 content_id라도 매 실행마다 새 "
            "generation_id를 부여해 이전 결과를 덮어쓰지 않고 나란히 보존합니다(같은 KNOWLEDGE를 "
            "다시 생성해도 content_id가 우연히 겹치는 슬롯이 있을 수 있음 - "
            "docs/6-06_media_versioning_and_safe_promotion.md 3~4장). production archive에 "
            "반영하려면 사람이 검토/승인한 뒤 scripts/promote_media_generation.py로 명시적으로 "
            "승격해야 합니다 - 이 플래그만으로는 production archive가 전혀 바뀌지 않습니다."
        ),
    )
    args = parser.parse_args(argv)

    if not args.input.exists():
        print(f"오류: 입력 파일을 찾을 수 없습니다: {args.input}", file=sys.stderr)
        return 1

    records = load_knowledge_records(args.input)
    if args.id:
        records = tuple(record for record in records if record.id == args.id)
        if not records:
            print(f"오류: KNOWLEDGE ID를 찾을 수 없습니다: {args.id}", file=sys.stderr)
            return 1

    approved = tuple(select_approved(records))
    if args.limit and args.limit > 0:
        approved = approved[: args.limit]

    if not args.execute:
        dry_run_data = generate_media_batch_dry_run(approved, total_count=len(records))
        print("=== TAK MEDIA Batch Pipeline (Dry-run) ===")
        print(f"입력 파일: {args.input}")
        print(f"전체 KNOWLEDGE: {len(records)}건")
        print(f"승인 KNOWLEDGE: {len(approved)}건")
        print(f"예상 생성 Draft: {dry_run_data['summary']['total_draft_count']}건 (1 KNOWLEDGE당 Blog 1, Shorts 3, Threads 5)")
        print("네트워크 호출 없음. 실제 실행에는 --execute와 환경변수(TAK_MEDIA_LLM_API_KEY, TAK_MEDIA_LLM_ENDPOINT, TAK_MEDIA_LLM_MODEL)가 필요합니다.")

        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(dry_run_data, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"Dry-run 결과 저장 완료: {args.output}")

        return 0

    provider = OpenAICompatibleRewriteProvider.from_environment()
    report = run_media_batch_file(
        input_path=args.input,
        output_path=args.output,
        provider=provider,
        limit=args.limit,
        knowledge_id=args.id,
    )

    # --output 여부와 무관하게, --execute로 실제 생성된 결과는 항상 아카이브에
    # 남긴다(5-27 설계 문서: "--output을 깜빡해도 결과 자체는 사라지지 않는다").
    if args.as_generation:
        archived = archive_generation_report(report, args.archive)
        generation_ids = sorted({record.generation_id for record in archived if record.generation_id})
    else:
        archive_report(report, args.archive)
        generation_ids = []

    print("=== TAK MEDIA Batch Pipeline 실행 완료 ===")
    print(f"전체 KNOWLEDGE: {report.total_knowledge_count}건")
    print(f"승인 KNOWLEDGE 처리: {report.approved_knowledge_count}건 (건너뜀: {report.skipped_knowledge_count}건)")
    print(f"총 생성 Draft: {report.total_draft_count}건")
    print(f"  - Valid (검증 통과): {report.valid_count}건")
    print(f"  - Rejected (검증 실패): {report.rejected_count}건")
    print(f"  - Error (오류): {report.error_count}건")

    if args.output:
        print(f"결과 저장 완료: {args.output}")
    if args.as_generation:
        print(f"generation pool 저장 완료 (valid/rejected/error 전체 누적): {args.archive}")
        print(f"이번 실행의 generation_id: {', '.join(generation_ids) if generation_ids else '(없음)'}")
        print(
            "production archive는 전혀 바뀌지 않았습니다. 사람이 검토/승인한 뒤 "
            "scripts/promote_media_generation.py로 명시적으로 승격하세요."
        )
    else:
        print(f"아카이브 저장 완료 (valid/rejected/error 전체 누적): {args.archive}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
