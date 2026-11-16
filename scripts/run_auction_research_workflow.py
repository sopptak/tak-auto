#!/usr/bin/env python3
"""경매 콘텐츠 조사부터 pending KNOWLEDGE 연결까지 한 번에 실행한다.

기본 실행은 API 호출 없는 계획 확인이다. 실제 Perplexity 호출은 --execute가 필요하다.
KNOWLEDGE는 항상 pending으로 저장되며 승인·MEDIA 생성·게시를 수행하지 않는다.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tak_scout import PerplexityResearchProvider, load_daily_pack
from tak_scout.research import (
    research_candidates,
    save_research_markdown,
    save_research_records,
)
from tak_scout.research_knowledge import upsert_research_knowledge


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "data" / "tak_scout_daily.json")
    parser.add_argument("--research-output", type=Path, default=ROOT / "data" / "tak_scout_research.json")
    parser.add_argument("--markdown-output", type=Path, default=ROOT / "data" / "tak_scout_research.md")
    parser.add_argument("--knowledge-output", type=Path, default=ROOT / "data" / "tak_brain_knowledge.json")
    parser.add_argument("--id", help="특정 SCOUT 후보 ID만 처리")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--recency", choices=("day", "week", "month", "year", "none"), default="month")
    parser.add_argument("--domain", action="append", default=[])
    parser.add_argument("--execute", action="store_true", help="Perplexity 유료 API 조사와 저장을 실제 실행")
    args = parser.parse_args(argv)

    if args.limit < 1:
        parser.error("--limit은 1 이상이어야 합니다.")
    if not args.input.exists():
        parser.error(f"SCOUT 입력 파일을 찾을 수 없습니다: {args.input}")

    candidates = load_daily_pack(args.input)
    if args.id:
        candidates = [candidate for candidate in candidates if candidate.scout_id == args.id]
        if not candidates:
            parser.error(f"SCOUT 후보를 찾을 수 없습니다: {args.id}")
    else:
        candidates = candidates[:args.limit]
    if not candidates:
        parser.error("처리할 SCOUT 후보가 없습니다.")

    print(f"경매 조사 워크플로: 대상 {len(candidates)}건")
    for candidate in candidates:
        print(f"- {candidate.scout_id}: {candidate.title}")
    if not args.execute:
        print("계획 확인만 완료했습니다. API 호출·파일 변경은 없었습니다.")
        print("실제 조사 및 pending KNOWLEDGE 연결: --execute 옵션을 추가하세요.")
        return 0

    provider = PerplexityResearchProvider.from_environment()
    records = research_candidates(
        candidates,
        provider,
        recency=None if args.recency == "none" else args.recency,
        domains=tuple(args.domain),
        profile="auction",
    )
    save_research_records(records, args.research_output)
    save_research_markdown(records, args.markdown_output)

    created = updated = preserved = failed = 0
    for record in records:
        if record.status != "completed":
            failed += 1
            print(f"- {record.scout_id}: 조사 실패 ({record.error})")
            continue
        try:
            _knowledge, status = upsert_research_knowledge(record, args.knowledge_output)
            if status == "created":
                created += 1
            elif status == "updated_pending":
                updated += 1
            elif status == "already_approved":
                preserved += 1
            print(f"- {record.scout_id}: 조사 완료 / KNOWLEDGE {status}")
        except (OSError, ValueError) as error:
            failed += 1
            print(f"- {record.scout_id}: KNOWLEDGE 연결 실패 ({type(error).__name__})")

    print(
        f"완료: 조사 {len(records)}건 / pending 신규 {created}건 / "
        f"pending 갱신 {updated}건 / 승인 보존 {preserved}건 / 실패 {failed}건"
    )
    print(f"조사 JSON: {args.research_output}")
    print(f"조사 보고서: {args.markdown_output}")
    print(f"KNOWLEDGE: {args.knowledge_output}")
    print("안전 경계: 승인·MEDIA 생성·외부 게시 없음. pending 검토 후 다음 단계로 진행하세요.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
