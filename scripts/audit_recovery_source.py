#!/usr/bin/env python3
"""외부 source 디렉터리(예: 다른 PC에서 복사해 온 운영 데이터 백업)를 실제
Production Archive에 반영하기 전에 먼저 검증만 하는 읽기 전용 CLI(6-22,
docs/6-22-recovery-staging-and-reconciliation.md).

이 스크립트는:
    - 어떤 파일도 생성/수정/삭제하지 않는다 - 항상 DRY-RUN이다.
    - ``data/`` 운영 디렉터리를 기본 source로 쓰지 않는다 - ``--source``를
      반드시 명시해야 한다.
    - 파일 내용(특히 secrets)을 절대 출력하지 않는다 - 존재 여부/크기/SHA256/
      JSON 유효성/최상위 타입/record 개수/충돌 판정만 보여준다.
    - 실제 운영 데이터를 반영하는 ``--apply``류 옵션이 없다 - 그런 옵션은
      이번 6-22 범위에서 구현하지 않았다(설계만
      docs/6-22-recovery-staging-and-reconciliation.md 9장에 문서화).

판정 로직(A~M 오류 코드, downstream reconciliation 8개 상태)은 전부
``content_engine.recovery_staging``에 있다 - 이 스크립트는 그 결과를 사람이
읽을 수 있게 출력만 한다.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_engine.recovery_staging import build_reconciliation_report, render_report_text


def _print_verbose(report) -> None:
    print()
    print("=== Archive issues ===")
    if not report.archive_report.issues:
        print("(없음)")
    for issue in report.archive_report.issues:
        print(f"  [{issue.code}] content_id={issue.content_id} - {issue.message}")

    print()
    print("=== Generation pool ===")
    if not report.generation_items and not report.generation_issues:
        print("(대상 없음)")
    for item in report.generation_items:
        print(
            f"  [{item.comparison}] content_id={item.content_id} generation_id={item.generation_id} "
            f"- {item.detail}"
        )
    for issue in report.generation_issues:
        print(f"  [{issue.code}] content_id={issue.content_id} - {issue.message}")

    print()
    print("=== Threads pending reconciliation ===")
    if not report.threads_items:
        print("(대상 없음)")
    for item in report.threads_items:
        reasons = "; ".join(item.reasons) if item.reasons else "-"
        print(
            f"  [{item.status}] content_id={item.content_id} field_consistency={item.field_consistency} "
            f"- {reasons}"
        )

    print()
    print("=== Shorts scripts reconciliation ===")
    if not report.shorts_items:
        print("(대상 없음)")
    for item in report.shorts_items:
        reasons = "; ".join(item.reasons) if item.reasons else "-"
        print(
            f"  [{item.status}] content_id={item.content_id} field_consistency={item.field_consistency} "
            f"- {reasons}"
        )


def _print_strict_exit_hint(report) -> None:
    print()
    print(f"(--strict: conflicts={report.conflicts}, warnings={report.warnings})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Recovery source 디렉터리를 읽기 전용으로 검증·대조하는 CLI. 실제 운영 "
            "데이터는 절대 반영하지 않는다(--apply 없음, 항상 DRY-RUN)."
        )
    )
    parser.add_argument(
        "--source",
        type=Path,
        required=True,
        help=(
            "검사할 recovery source 디렉터리(예: 다른 PC의 data/ 디렉터리를 복사해 온 "
            "경로). data/ 운영 디렉터리를 기본값으로 쓰지 않는다 - 항상 명시해야 한다."
        ),
    )
    parser.add_argument("--json", action="store_true", help="사람이 읽는 요약 대신 JSON으로 출력한다.")
    parser.add_argument(
        "--verbose", action="store_true", help="archive/generation/downstream 항목별 상세 내역까지 출력한다."
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="conflicts 또는 warnings가 1건이라도 있으면 종료 코드를 1로 반환한다(기본값: 항상 0).",
    )
    args = parser.parse_args(argv)

    report = build_reconciliation_report(args.source)

    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(render_report_text(report))
        if args.verbose:
            _print_verbose(report)
        if args.strict:
            _print_strict_exit_hint(report)

    if args.strict and (report.conflicts > 0 or report.warnings > 0):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
