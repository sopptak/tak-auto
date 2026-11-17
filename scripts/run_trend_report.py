#!/usr/bin/env python3
"""Build a daily trend report from collected public RSS candidates.

This command measures recurrence inside configured feeds, not public search volume.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tak_scout.collector import load_daily_pack
from tak_scout.naver_datalab import NaverDataLabError, NaverDataLabProvider
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
    parser.add_argument("--date", default=datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat(), help="관측일 YYYY-MM-DD (KST 기준, 테스트·재처리용)")
    args = parser.parse_args(argv)
    if not args.input.exists():
        parser.error(f"SCOUT 입력 파일이 없습니다: {args.input}")
    candidates = load_daily_pack(args.input)
    history = load_history(args.history)
    report = build_daily_report(candidates, history, args.date)

    # Optional official search-interest data; RSS recurrence remains a separate metric.
    datalab = NaverDataLabProvider()
    if not datalab.client_id or not datalab.client_secret:
        report["naver_datalab"] = {
            "status": "not_configured",
            "measurement": "naver_datalab_relative_ratio",
            "message": "인증정보 미설정: NAVER_DATALAB_CLIENT_ID / NAVER_DATALAB_CLIENT_SECRET",
        }
    else:
        keywords = [row["keyword"] for row in report["top_keywords"][:5]]
        if not keywords:
            report["naver_datalab"] = {
                "status": "skipped",
                "measurement": "naver_datalab_relative_ratio",
                "message": "비교할 반복 키워드가 없습니다.",
            }
        else:
            try:
                result = datalab.search_trend(
                    [{"groupName": keyword[:30], "keywords": [keyword]}
                     for keyword in keywords],
                    start_date=(date.fromisoformat(args.date) - timedelta(days=29)).isoformat(),
                    end_date=args.date,
                    time_unit="date",
                )
                report["naver_datalab"] = {
                    "status": "success",
                    "measurement": "naver_datalab_relative_ratio",
                    "note": "각 키워드 그룹의 상대 검색 관심도입니다. 절대 검색량 또는 그룹 간 직접 비교값이 아닙니다.",
                    "result": result.to_dict(),
                }
            except (NaverDataLabError, ValueError) as exc:
                # An external metric outage must not block the RSS daily report.
                report["naver_datalab"] = {
                    "status": "error",
                    "measurement": "naver_datalab_relative_ratio",
                    "message": str(exc),
                }
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
    print("네이버 데이터랩: " + report["naver_datalab"]["status"])
    print(f"JSON: {args.output_json}")
    print(f"Markdown: {args.output_md}")
    print(f"이력: {args.history}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
