#!/usr/bin/env python3
"""Query official Naver DataLab relative search-interest ratios for keyword groups."""
from __future__ import annotations

import argparse
from datetime import date, timedelta
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tak_scout.naver_datalab import NaverDataLabError, NaverDataLabProvider


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group", action="append", required=True,
                        help="비교 그룹: 그룹명=키워드1,키워드2 (반복 가능)")
    parser.add_argument("--start", default=(date.today() - timedelta(days=30)).isoformat())
    parser.add_argument("--end", default=date.today().isoformat())
    parser.add_argument("--unit", choices=("date", "week", "month"), default="date")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "naver_datalab_trends.json")
    args = parser.parse_args(argv)
    groups = []
    for value in args.group:
        if "=" not in value:
            parser.error("--group 형식은 그룹명=키워드1,키워드2 입니다.")
        name, terms = value.split("=", 1)
        keywords = [term.strip() for term in terms.split(",") if term.strip()]
        if not name.strip() or not keywords:
            parser.error("그룹명과 키워드를 입력하세요.")
        groups.append({"groupName": name.strip(), "keywords": keywords})
    try:
        result = NaverDataLabProvider().search_trend(
            groups, start_date=args.start, end_date=args.end, time_unit=args.unit)
    except (NaverDataLabError, ValueError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print(f"네이버 데이터랩 상대 검색 관심도 저장: {args.output}")
    print("주의: 결과는 절대 검색량이 아닌 검색어 그룹별 상대 비율입니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
