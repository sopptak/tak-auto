#!/usr/bin/env python3
"""Build a daily trend report from collected public RSS candidates.

This command measures recurrence inside configured feeds, not public search volume.
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tak_scout.collector import load_daily_pack
from tak_scout.trend_history import (
    build_daily_report, load_history, observations_for_day,
    render_daily_report, save_history,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "data" / "tak_scout_daily.json")
    parser.add_argument("--history", type=Path, default=ROOT / "data" / "tak_auto_trend_history.json")
    parser.add_argument("--output-json", type=Path, default=ROOT / "data" / "tak_auto_trend_daily.json")
    parser.add_argument("--output-md", type=Path, default=ROOT / "data" / "tak_auto_trend_daily.md")
    parser.add_argument("--date", default=date.today().isoformat(), help="관측일 YYYY-MM-DD (테스트·재처리용)")
    args = parser.parse_args(argv)
    if not args.input.exists():
        parser.error(f"SCOUT 입력 파일이 없습니다: {args.input}")
    candidates = load_daily_pack(args.input)
    history = load_history(args.history)
    report = build_daily_report(candidates, history, args.date)
    updated = [row for row in history if row.observed_on != args.date]
    updated.extend(observations_for_day(candidates, args.date))
    save_history(updated, args.history)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.write_text(render_daily_report(report), encoding="utf-8")
    print(f"TAK AUTO 트렌드 리포트 생성: 후보 {len(candidates)}건")
    print(f"반복 키워드 {len(report['top_keywords'])}개 / 급상승 {len(report['rising_keywords'])}개 / 콘텐츠 기회 {len(report['content_opportunities'])}개")
    print("측정 범위: 등록 RSS 피드 내부 반복. 검색량·SNS 인기·경쟁도는 미측정.")
    print(f"JSON: {args.output_json}")
    print(f"Markdown: {args.output_md}")
    print(f"이력: {args.history}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
