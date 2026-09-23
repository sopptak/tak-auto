#!/usr/bin/env python3
"""Performance 원자료를 읽어 Insight 후보(candidate)를 계산하는 읽기 전용
CLI(6-35 22장).

이 스크립트는 Performance 저장소(``--performance``)를 **읽기만** 한다 -
어떤 경우에도 그 파일을 수정하지 않는다. ``--output``을 명시하지 않으면
결과를 화면에 출력만 하고 아무 파일도 만들지 않는다(완전히 읽기 전용).
``--output``을 명시하면 계산된 Insight를 그 경로에 추가하지만(이미
idempotent한 ``content_engine.performance_insight.append_insight()``를
그대로 쓴다), 실제 운영 경로(``data/tak_performance_insights.json``)를
기본값으로 두지 않았다 - 실수로 실제 파일을 건드리지 않도록
``scripts/import_performance_snapshots.py``와 동일한 안전 원칙을 따른다.

계산된 Insight는 항상 ``status="candidate"``로 만들어진다 - 이 CLI가
자동으로 accepted 처리하지 않는다. 사람이 검토 후
``content_engine.performance_insight.set_insight_status()``로 명시적으로
accept/reject해야 한다(19장, 자동 행동으로 이어지지 않음).
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_engine.performance.store import load_snapshots
from content_engine.performance_insight import (
    SCOPES,
    analyze_trend,
    append_insight,
    detect_anomaly,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Performance 스냅샷에서 Insight candidate를 계산하는 읽기 전용 CLI."
    )
    parser.add_argument("--performance", type=Path, required=True, help="Performance 스냅샷 저장소 경로(읽기 전용)")
    parser.add_argument("--scope", required=True, choices=SCOPES)
    parser.add_argument("--scope-id", required=True, help="scope에 해당하는 값(content_id/generation_id/knowledge_id/platform)")
    parser.add_argument("--platform", required=True, help="이 분석의 platform(threads/youtube/blog)")
    parser.add_argument("--metric", default="views")
    parser.add_argument("--analysis-window", default="all")
    parser.add_argument("--type", choices=("trend", "anomaly"), default="trend")
    parser.add_argument("--output", type=Path, default=None, help="명시하면 결과를 이 경로에 추가(idempotent). 생략하면 출력만 하고 저장하지 않음.")
    args = parser.parse_args(argv)

    if not args.performance.exists():
        print(f"오류: Performance 저장소를 찾을 수 없습니다: {args.performance}", file=sys.stderr)
        return 1

    records = load_snapshots(args.performance)
    scoped_records = [
        r
        for r in records
        if (args.scope == "content" and r.content_id == args.scope_id)
        or (args.scope == "knowledge" and r.knowledge_id == args.scope_id)
        or (args.scope == "platform" and r.platform == args.scope_id)
        or (args.scope == "generation")  # generation_id는 PerformanceRecord에 없다(6-34/6-35 11장 결론) - content 필터로 대체 안내만 한다.
    ]
    if args.scope == "generation":
        print(
            "안내: PerformanceRecord에는 generation_id가 없습니다(6-35 14장 결론 - "
            "content_id가 이미 generation-invariant하므로 불필요). --scope content로 다시 실행하세요.",
            file=sys.stderr,
        )
        return 1

    if args.type == "trend":
        insight = analyze_trend(
            scoped_records, scope=args.scope, scope_id=args.scope_id, platform=args.platform,
            metric=args.metric, analysis_window=args.analysis_window,
        )
    else:
        insight = detect_anomaly(
            scoped_records, scope=args.scope, scope_id=args.scope_id, platform=args.platform,
            metric=args.metric, analysis_window=args.analysis_window,
        )

    print(f"=== Insight Candidate [{insight.insight_type}] ===")
    print(f"scope: {insight.scope}={insight.scope_id}")
    print(f"metric: {insight.metric}")
    print(f"sample_size: {insight.sample_size}")
    print(f"result: {insight.result}")
    print(f"observation: {insight.observation}")
    print(f"status: {insight.status}")

    if args.output:
        added = append_insight(args.output, insight)
        print(f"\n저장 완료: {args.output}(추가={added}, 이미 존재하면 False)")
    else:
        print("\n--output이 없어 저장하지 않았습니다(읽기 전용 실행).")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
