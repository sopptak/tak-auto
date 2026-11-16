#!/usr/bin/env python3
"""저장된 Perplexity 조사 결과를 TAK BRAIN pending KNOWLEDGE 초안으로 연결한다."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tak_scout.research import load_research_records
from tak_scout.research_knowledge import upsert_research_knowledge


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "data" / "tak_scout_research.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "tak_brain_knowledge.json")
    parser.add_argument("--id", help="특정 SCOUT ID 1건만 변환")
    parser.add_argument("--limit", type=int, default=3, help="한 번에 연결할 최대 조사 건수")
    args = parser.parse_args(argv)

    if args.limit < 1:
        parser.error("--limit은 1 이상이어야 합니다.")
    if not args.input.exists():
        parser.error(f"조사 파일을 찾을 수 없습니다: {args.input}")

    records = load_research_records(args.input)
    if args.id:
        records = [record for record in records if record.scout_id == args.id]
        if not records:
            parser.error(f"조사 결과를 찾을 수 없습니다: {args.id}")
    else:
        records = records[:args.limit]

    created = updated = approved = failed = 0
    for record in records:
        try:
            _knowledge, status = upsert_research_knowledge(record, args.output)
            if status == "created":
                created += 1
            elif status == "updated_pending":
                updated += 1
            elif status == "already_approved":
                approved += 1
            print(f"- {record.scout_id}: {status}")
        except (OSError, ValueError) as error:
            failed += 1
            print(f"- {record.scout_id}: 실패 ({type(error).__name__})", file=sys.stderr)

    print(
        f"TAK BRAIN 연결 결과: 전체 {len(records)}건 / 신규 {created}건 / "
        f"pending 갱신 {updated}건 / 승인 보존 {approved}건 / 실패 {failed}건"
    )
    print(f"KNOWLEDGE: {args.output}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
