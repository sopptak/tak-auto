#!/usr/bin/env python3
"""Recovery Report -> Human Review -> Explicit Approval -> Apply 전체 파이프라인의
CLI(6-23, docs/6-23-recovery-review-and-approval-gate.md).

기본 동작은 언제나 DRY-RUN이다 - ``--apply``를 명시해야만 실제로
``--production-archive``를 갱신한다(``scripts/promote_media_generation.py``,
``scripts/supersede_media_record.py``와 동일한 안전 관례).

이 스크립트가 절대 하지 않는 것:
    - 자동 승인. ``--approve <content_id>``로 사람이 하나씩 명시하지 않은
      content_id는 어떤 경우에도 적용되지 않는다(5장/4장 원칙).
    - downstream artifact(Threads pending/Shorts scripts/Blog drafts) 수정.
      이 스크립트는 production archive 1개 파일만 쓴다.
    - 실제 Threads/YouTube/Naver 게시, LLM 호출, 외부 DB 연결.

사용 예(전부 읽기 전용 - 아무것도 쓰지 않음):
    python scripts/recover_media_archive.py --source <복사본 경로> \\
        --production-archive data/tak_media_archive.json

승인 + 실제 반영(주의 - 이 저장소 6-23 작업 범위에서는 절대 실행하지 않았다):
    python scripts/recover_media_archive.py --source <복사본 경로> \\
        --production-archive <경로> --approve content-1 --approve content-2 --apply
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_engine.recovery_apply import apply_recovery, evaluate_apply_guard, reevaluate_before_apply
from content_engine.recovery_decision import build_recovery_report, render_recovery_report_text


def _print_candidates(report) -> None:
    print()
    print("=== Candidates(generation pool) ===")
    if not report.candidates:
        print("(대상 없음)")
    for candidate in report.candidates:
        reasons = "; ".join(candidate.reasons) if candidate.reasons else "-"
        print(
            f"  [{candidate.status}/{candidate.action}] content_id={candidate.content_id} "
            f"generation_id={candidate.generation_id} - {reasons}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Recovery source를 실제 production archive와 대조해 Report -> Human Review -> "
            "Explicit Approval -> Apply 파이프라인을 실행한다. 기본은 DRY-RUN(아무것도 쓰지 "
            "않음)이며, --apply를 명시하고 --approve로 각 content_id를 하나씩 승인해야만 "
            "실제로 반영한다."
        )
    )
    parser.add_argument(
        "--source",
        type=Path,
        required=True,
        help="검사할 recovery source 디렉터리. data/ 운영 디렉터리를 기본값으로 쓰지 않는다.",
    )
    parser.add_argument(
        "--production-archive",
        type=Path,
        required=True,
        help="실제로 비교·반영될 production archive 경로. 기본값이 없다(안전장치).",
    )
    parser.add_argument(
        "--approve",
        action="append",
        default=[],
        metavar="CONTENT_ID",
        help="이 content_id를 명시적으로 승인한다. 여러 번 줄 수 있다. 생략하면 아무것도 승인되지 않는다.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="실제로 production archive를 갱신한다. 생략하면 DRY-RUN(계획만 출력, 파일 변경 없음).",
    )
    parser.add_argument("--json", action="store_true", help="사람이 읽는 요약 대신 JSON으로 출력한다.")
    parser.add_argument("--verbose", action="store_true", help="후보별 상세 내역까지 출력한다.")
    args = parser.parse_args(argv)

    report = build_recovery_report(args.source, args.production_archive, approved_content_ids=args.approve)

    if args.json and not args.approve and not args.apply:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        return 0

    print(render_recovery_report_text(report))
    if args.verbose:
        _print_candidates(report)

    if not args.approve:
        print()
        print("승인된 content_id가 없습니다(--approve 미지정) - 여기서 멈춥니다. Apply는 실행되지 않았습니다.")
        return 0

    guard = evaluate_apply_guard(report, args.approve, expected_source_sha256=report.source_sha256)

    print()
    print(f"=== Apply Guard [{'PASS' if guard.passed else 'BLOCK'}] ===")
    if guard.failures:
        for failure in guard.failures:
            print(f"  [{failure.check}] {failure.message}")
    else:
        print(f"  승인된 {len(guard.approved_records)}건 모두 가드를 통과했습니다.")

    if not args.apply:
        print()
        print("dry-run 완료(--apply 없음). 실제로 반영하려면 --apply를 추가하세요.")
        return 0 if guard.passed else 1

    if not guard.passed:
        print()
        print("Apply Guard를 통과하지 못해 아무것도 쓰지 않았습니다.")
        return 1

    drift = reevaluate_before_apply(build_recovery_report, args.source, args.production_archive, args.approve)
    if drift is not None:
        print()
        print(f"=== Apply 직전 재검증 실패 [{drift.check}] ===")
        print(f"  {drift.message}")
        print("아무것도 쓰지 않았습니다.")
        return 1

    result = apply_recovery(args.production_archive, guard.approved_records)
    print()
    print(f"=== Apply 결과 [{'SUCCESS' if result.success else 'FAILED'}] ===")
    print(f"  {result.message}")
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
