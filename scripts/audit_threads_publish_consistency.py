#!/usr/bin/env python3
"""Threads pending draft(``data/tak_threads_pending.json``)와 실제 게시 이력
(``data/threads_publish_log.json``)의 전수 정합성을 점검하는 읽기 전용 CLI(6-15).

사람이 두 JSON 파일을 content_id별로 하나씩 대조하지 않아도, 코드가 먼저
CONSISTENT/PUBLISHED_BUT_PENDING_STALE/PENDING_WITHOUT_PUBLISH_LOG/FAILED/
ORPHAN/DUPLICATE로 분류해 보여준다. 판정 로직은
``content_engine.threads_consistency``(순수 함수)에 있다.

이 스크립트가 절대 하지 않는 것:
    - pending 파일이나 게시 이력 파일을 수정하는 것(Markdown 보고서 저장 제외) -
      완전한 읽기 전용 감사 도구다.
    - 실제 Threads API를 호출하는 것 - 이 스크립트는 관련 클라이언트를 전혀
      import하지 않는다.
    - 안전하게 동기화 가능(safe_to_sync)한 항목을 자동으로 복구하는 것 - 그
      복구는 기존 ``scripts/publish_approved_threads.py --id <content_id>
      --execute``가 이미 안전하게(게시 이력에 이미 기록이 있으므로 API를 다시
      호출하지 않고 pending 상태만 동기화) 수행한다. 같은 기능을 새로 만들지
      않는다 - 이 스크립트는 "어떤 content_id가 그 대상인지"만 보여준다.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_engine.publish_history import PublishHistory
from content_engine.threads_consistency import (
    CONSISTENT,
    DUPLICATE,
    FAILED,
    ORPHAN,
    PENDING_WITHOUT_PUBLISH_LOG,
    PUBLISHED_BUT_PENDING_STALE,
    audit_threads_consistency,
    save_consistency_report,
    summarize,
)
from content_engine.threads_review import ThreadsPendingError, load_pending


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Threads pending draft와 실제 게시 이력의 전수 정합성을 점검하는 읽기 전용 감사 CLI"
        )
    )
    parser.add_argument(
        "--pending",
        type=Path,
        default=ROOT / "data" / "tak_threads_pending.json",
        help="Threads 검수 대기 draft 경로 (기본값: data/tak_threads_pending.json)",
    )
    parser.add_argument(
        "--history",
        type=Path,
        default=ROOT / "data" / "threads_publish_log.json",
        help="Threads 게시 이력 경로 (기본값: data/threads_publish_log.json)",
    )
    parser.add_argument(
        "--report-output",
        type=Path,
        default=ROOT / "docs" / "threads_publish_consistency_latest.md",
        help="Markdown 보고서 저장 경로 (기본값: docs/threads_publish_consistency_latest.md)",
    )
    parser.add_argument(
        "--no-report",
        action="store_true",
        help="Markdown 보고서를 저장하지 않고 터미널 요약만 출력한다.",
    )
    parser.add_argument(
        "--fail-on-anomaly",
        action="store_true",
        help="ORPHAN/DUPLICATE가 하나라도 있으면 종료 코드를 1로 반환한다(기본값: 항상 0).",
    )
    args = parser.parse_args(argv)

    try:
        pending = load_pending(args.pending)
    except ThreadsPendingError as err:
        print(f"오류: pending 파일을 읽을 수 없습니다: {err}", file=sys.stderr)
        return 1

    history = PublishHistory(args.history)
    try:
        log_records = history.load()
    except Exception as err:  # noqa: BLE001 - PublishHistoryError는 ValueError 서브클래스
        print(f"오류: 게시 이력 파일을 읽을 수 없습니다: {err}", file=sys.stderr)
        return 1

    results = audit_threads_consistency(pending, log_records)
    summary = summarize(results)

    print("=== Threads Publish Consistency 요약 ===")
    print(f"전체 대상 content_id: {len(results)}")
    print(f"CONSISTENT: {summary[CONSISTENT]}")
    print(f"PUBLISHED_BUT_PENDING_STALE: {summary[PUBLISHED_BUT_PENDING_STALE]}")
    print(f"PENDING_WITHOUT_PUBLISH_LOG: {summary[PENDING_WITHOUT_PUBLISH_LOG]}")
    print(f"FAILED: {summary[FAILED]}")
    print(f"ORPHAN: {summary[ORPHAN]}")
    print(f"DUPLICATE: {summary[DUPLICATE]}")
    print()

    syncable = [r for r in results if r.safe_to_sync]
    if syncable:
        print("--- 안전하게 자동 동기화 가능(scripts/publish_approved_threads.py --execute) ---")
        for r in syncable:
            print(f"  {r.content_id}: pending status={r.pending_status!r} -> log post_id={r.log_post_id!r}")
        print()

    anomalies = [r for r in results if r.status in (ORPHAN, DUPLICATE)]
    if anomalies:
        print("--- 사람이 직접 확인해야 함(ORPHAN/DUPLICATE) ---")
        for r in anomalies:
            print(f"  [{r.status}] {r.content_id}: {'; '.join(r.reasons)}")
        print()

    if not args.no_report:
        try:
            save_consistency_report(results, args.report_output)
        except OSError as err:
            print(f"오류: 보고서 저장에 실패했습니다: {err}", file=sys.stderr)
            return 1
        print(f"Threads Publish Consistency 보고서 저장 완료: {args.report_output}")

    if args.fail_on_anomaly and (summary[ORPHAN] > 0 or summary[DUPLICATE] > 0):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
