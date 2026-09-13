#!/usr/bin/env python3
"""승인된 KNOWLEDGE를 일괄 처리하여 콘텐츠 생성·재작성·검증하는 배치 파이프라인 CLI."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_engine import (
    OpenAICompatibleRewriteProvider,
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
        help="배치 결과 저장 JSON 경로 (선택)",
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
        print("=== TAK MEDIA Batch Pipeline (Dry-run) ===")
        print(f"입력 파일: {args.input}")
        print(f"전체 KNOWLEDGE: {len(records)}건")
        print(f"승인 KNOWLEDGE: {len(approved)}건")
        print(f"예상 생성 Draft: {len(approved) * 9}건 (1 KNOWLEDGE당 Blog 1, Shorts 3, Threads 5)")
        print("네트워크 호출 없음. 실제 실행에는 --execute와 환경변수(TAK_MEDIA_LLM_API_KEY, TAK_MEDIA_LLM_ENDPOINT, TAK_MEDIA_LLM_MODEL)가 필요합니다.")
        return 0

    provider = OpenAICompatibleRewriteProvider.from_environment()
    report = run_media_batch_file(
        input_path=args.input,
        output_path=args.output,
        provider=provider,
        limit=args.limit,
        knowledge_id=args.id,
    )

    print("=== TAK MEDIA Batch Pipeline 실행 완료 ===")
    print(f"전체 KNOWLEDGE: {report.total_knowledge_count}건")
    print(f"승인 KNOWLEDGE 처리: {report.approved_knowledge_count}건 (건너뜀: {report.skipped_knowledge_count}건)")
    print(f"총 생성 Draft: {report.total_draft_count}건")
    print(f"  - Valid (검증 통과): {report.valid_count}건")
    print(f"  - Rejected (검증 실패): {report.rejected_count}건")
    print(f"  - Error (오류): {report.error_count}건")

    if args.output:
        print(f"결과 저장 완료: {args.output}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
