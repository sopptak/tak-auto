#!/usr/bin/env python3
"""Research one trend keyword using its collected RSS evidence and Perplexity.

This creates research records for human review; it does not create approved KNOWLEDGE
or publish content.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tak_scout import PerplexityResearchProvider, load_daily_pack
from tak_scout.research import research_candidate, upsert_research_record
from tak_scout.trend_history import load_history


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keyword", required=True, help="조사할 트렌드 키워드")
    parser.add_argument("--report", type=Path, default=ROOT / "data" / "tak_auto_trend_daily.json")
    parser.add_argument("--candidates", type=Path, default=ROOT / "data" / "tak_scout_daily.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "tak_scout_research.json")
    parser.add_argument("--markdown", type=Path, default=ROOT / "data" / "tak_scout_research.md")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--recency", choices=("day", "week", "month", "year", "none"), default="month")
    parser.add_argument("--profile", choices=("general", "auction"), default="general")
    args = parser.parse_args(argv)
    if args.limit < 1:
        parser.error("--limit은 1 이상이어야 합니다.")

    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
        pack = load_daily_pack(args.candidates)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        parser.error(f"트렌드 자료를 읽을 수 없습니다: {exc}")

    opportunity = next(
        (row for row in report.get("content_opportunities", [])
         if str(row.get("keyword", "")).casefold() == args.keyword.casefold()),
        None,
    )
    if opportunity is None:
        parser.error(f"오늘의 콘텐츠 기회 목록에서 키워드를 찾을 수 없습니다: {args.keyword}")

    candidate_ids = set(str(x) for x in opportunity.get("candidate_ids", []))
    selected = [item for item in pack if item.scout_id in candidate_ids]
    if not selected:
        # Older reports may not carry IDs; conservative fallback uses exact keyword match
        # against candidate title/summary and never invents a supporting article.
        selected = [item for item in pack
                    if args.keyword.casefold() in f"{item.title} {item.summary}".casefold()]
    selected = selected[:args.limit]
    if not selected:
        parser.error("선택 키워드를 뒷받침하는 수집 소재가 없습니다.")

    provider = PerplexityResearchProvider.from_environment()
    records = []
    for candidate in selected:
        base = (
            f"이번 조사 키워드: {args.keyword}\n"
            "이 키워드가 실제로 무엇을 가리키는지부터 확인하고, 최근 동향·핵심 사실·"
            "이해관계자 영향·반론·불확실성을 조사하세요. 검색 수요나 인기도를 확인하지 "
            "못하면 추정하지 마세요. 출처가 뒷받침하지 않는 주장을 만들지 마세요.\n\n"
        )
        from dataclasses import replace
        enriched = replace(candidate, summary=(base + candidate.summary)[:4000])
        records.append(research_candidate(
            enriched, provider,
            recency=None if args.recency == "none" else args.recency,
            profile=args.profile,
        ))

    for record in records:
        upsert_research_record(args.output, record)

    from tak_scout.research import load_research_records, save_research_markdown
    save_research_markdown(load_research_records(args.output), args.markdown)
    succeeded = sum(item.status == "completed" for item in records)
    print(f"키워드 조사: {args.keyword} / 근거 소재 {len(records)}건 / 성공 {succeeded}건")
    print(f"저장: {args.output}")
    print(f"검토 문서: {args.markdown}")
    print("다음 단계: 기존 TAK SCOUT Dashboard의 /research에서 결과를 확인하고 KNOWLEDGE 검토 초안을 만드세요.")
    return 0 if succeeded == len(records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
