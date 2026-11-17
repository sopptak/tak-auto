#!/usr/bin/env python3
"""Research selected TAK SCOUT candidates with Perplexity and save separate artifacts."""
from __future__ import annotations
import argparse
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from tak_scout import load_daily_pack, PerplexityResearchProvider
from tak_scout.research import research_candidates, save_research_markdown, save_research_records

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=str(ROOT / "data" / "tak_scout_daily.json"))
    parser.add_argument("--output", default=str(ROOT / "data" / "tak_scout_research.json"))
    parser.add_argument("--markdown", default=str(ROOT / "data" / "tak_scout_research.md"))
    parser.add_argument("--id", help="조사할 scout_id 하나")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--recency", choices=("day","week","month","year","none"), default="month")
    parser.add_argument("--domain", action="append", default=[])
    parser.add_argument("--profile", choices=("auction", "general"), default="general",
                        help="조사 프로필 (기본값: 범용 트렌드; 경매는 명시적으로 선택)")
    args = parser.parse_args()
    if args.limit < 1: parser.error("--limit은 1 이상이어야 합니다.")
    candidates = load_daily_pack(args.input)
    if args.id:
        candidates = [c for c in candidates if c.scout_id == args.id]
        if not candidates: parser.error(f"SCOUT 후보를 찾을 수 없습니다: {args.id}")
    else: candidates = candidates[:args.limit]
    if not candidates: parser.error("조사할 SCOUT 후보가 없습니다.")
    provider = PerplexityResearchProvider.from_environment()
    records = research_candidates(candidates, provider,
        recency=None if args.recency == "none" else args.recency,
        domains=tuple(args.domain), profile=args.profile)
    save_research_records(records, args.output)
    save_research_markdown(records, args.markdown)
    done = sum(r.status == "completed" for r in records)
    failed = len(records) - done
    print(f"심층 조사: 전체 {len(records)}건 / 성공 {done}건 / 실패 {failed}건")
    print(f"JSON: {args.output}\nMarkdown: {args.markdown}")
    for r in records: print(f"- {r.scout_id}: {r.status} / citations {len(r.citations)}")
    return 0 if failed == 0 else 1

if __name__ == "__main__": raise SystemExit(main())
