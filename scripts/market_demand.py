#!/usr/bin/env python3
"""시장 수요 데이터 -> 기회 점수 -> 사업 아이디어 후보. 기본은 미리보기, --write로 저장.

실제 마켓플레이스 크롤러는 없다. 사람이 확인한 데이터를 --input FILE(JSON/CSV)로 넣는다.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_engine.market_demand import (
    IDEA_STATUSES, MarketDemandError, append_demands, append_ideas, available_market_providers,
    build_idea_candidates, get_market_demand_provider, set_idea_status,
)
from content_engine.providers.base import ProviderError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", default="manual", help=f"선택: {', '.join(available_market_providers())}")
    parser.add_argument("--input", type=Path, help="manual provider용 JSON/CSV 파일")
    parser.add_argument("--query", default="", help="제목/카테고리/설명 필터")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--min-score", type=float, default=40.0)
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--write", action="store_true", help="수요/아이디어를 data/에 append한다.")
    parser.add_argument("--set-status", nargs=2, metavar=("IDEA_ID", "STATUS"), help=f"상태 변경 {IDEA_STATUSES}")
    args = parser.parse_args(argv)
    ideas_path = args.data_dir / "tak_idea_candidates.json"
    try:
        if args.set_status:
            idea = set_idea_status(ideas_path, *args.set_status)
            print(f"{idea.idea_id} -> {idea.status}")
            return 0
        kwargs = {"path": args.input} if args.provider == "manual" else {}
        provider = get_market_demand_provider(args.provider, **kwargs)
        demands = provider.collect_demand(args.query, args.limit)
    except (MarketDemandError, ProviderError, OSError, ValueError) as error:
        print(f"오류: {error}", file=sys.stderr)
        return 2

    ideas = build_idea_candidates(demands, min_score=args.min_score, top_n=args.top)
    print(f"수요 {len(demands)}건 -> 아이디어 후보 {len(ideas)}건")
    for idea in ideas:
        print(f"- [{idea.score:5.1f} / conf {idea.confidence:.2f}] {idea.title}\n    {idea.rationale}")
    if args.write:
        added_demands = append_demands(args.data_dir / "tak_market_demands.json", demands)
        added_ideas = append_ideas(ideas_path, ideas)
        print(f"저장: 수요 {added_demands}건, 아이디어 {added_ideas}건 신규")
    else:
        print("(미리보기: 저장하려면 --write)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
