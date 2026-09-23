#!/usr/bin/env python3
"""Performance/Insight 저장소를 읽어 운영 리포트를 출력하는 읽기 전용
CLI(6-36 14장).

이 스크립트는 새 분석을 수행하지 않는다 - 이미 계산되어 저장된
Performance 스냅샷(``--performance``)과 Insight(``--insights``)를 읽어
``content_engine/insight_report.py``의 집계 함수로 정리만 한다. 어떤
파일도 쓰지 않는다(완전한 읽기 전용) - Insight를 새로 계산하려면
``scripts/analyze_performance.py``(6-35)를, 사람이 검토 결정을 남기려면
``content_engine.insight_report.record_decision()``을 Python에서 직접
호출해야 한다(이 CLI에는 쓰기 옵션이 없다).
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_engine.insight_report import (
    build_daily_report,
    build_weekly_report,
    render_daily_report_text,
    render_weekly_report_text,
)
from content_engine.performance.store import load_snapshots
from content_engine.performance_insight import load_insights


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Performance/Insight 저장소를 읽어 운영 리포트를 출력하는 읽기 전용 CLI."
    )
    parser.add_argument("--performance", type=Path, required=True, help="Performance 스냅샷 저장소 경로(읽기 전용)")
    parser.add_argument("--insights", type=Path, required=True, help="Insight 저장소 경로(읽기 전용)")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--daily", action="store_true")
    mode.add_argument("--weekly", action="store_true")
    parser.add_argument("--window-start", required=True, help="기간 시작(ISO 8601)")
    parser.add_argument("--window-end", required=True, help="기간 끝(ISO 8601)")
    parser.add_argument("--platform", default=None, help="platform으로 필터링(선택)")
    parser.add_argument("--knowledge-id", default=None, help="knowledge_id로 필터링(선택)")
    parser.add_argument("--content-id", default=None, help="content_id로 필터링(선택)")
    args = parser.parse_args(argv)

    if not args.performance.exists():
        print(f"오류: Performance 저장소를 찾을 수 없습니다: {args.performance}", file=sys.stderr)
        return 1
    if not args.insights.exists():
        print(f"오류: Insight 저장소를 찾을 수 없습니다: {args.insights}", file=sys.stderr)
        return 1

    performance_records = load_snapshots(args.performance)
    insight_records = load_insights(args.insights)

    if args.platform:
        performance_records = [r for r in performance_records if r.platform == args.platform]
        insight_records = [r for r in insight_records if r.platform == args.platform]
    if args.knowledge_id:
        performance_records = [r for r in performance_records if r.knowledge_id == args.knowledge_id]
        insight_records = [r for r in insight_records if r.scope_id == args.knowledge_id and r.scope == "knowledge"]
    if args.content_id:
        performance_records = [r for r in performance_records if r.content_id == args.content_id]
        insight_records = [r for r in insight_records if r.scope_id == args.content_id and r.scope == "content"]

    if args.daily:
        report = build_daily_report(
            performance_records, insight_records, window_start=args.window_start, window_end=args.window_end
        )
        print(render_daily_report_text(report))
    else:
        report = build_weekly_report(insight_records, window_start=args.window_start, window_end=args.window_end)
        print(render_weekly_report_text(report))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
