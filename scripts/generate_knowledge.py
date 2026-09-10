#!/usr/bin/env python3
"""저장된 RAW 전체를 유형별 KNOWLEDGE 초안으로 누적 변환합니다."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tak_brain import append_knowledge_file, load_knowledge_records, select_approved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TAK BRAIN KNOWLEDGE 파일럿 생성")
    parser.add_argument("--raw", default=str(ROOT / "data" / "tak_brain_raw.json"))
    parser.add_argument("--output", default=str(ROOT / "data" / "tak_brain_knowledge.json"))
    args = parser.parse_args(argv)

    created, duplicates, errors = append_knowledge_file(args.raw, args.output)
    records = load_knowledge_records(args.output)
    approved = select_approved(records)
    pending = tuple(record for record in records if record.knowledge_review_status == "pending")
    rejected = tuple(record for record in records if record.knowledge_review_status == "rejected")
    print(f"RAW 전체: {created + duplicates + errors}")
    print(f"KNOWLEDGE 전체: {len(records)}")
    print(f"신규: {created}")
    print(f"중복: {duplicates}")
    print(f"오류: {errors}")
    print(f"approved: {len(approved)}")
    print(f"pending: {len(pending)}")
    print(f"rejected: {len(rejected)}")
    for record in records:
        print(f"{record.id}\t{record.title}\t{record.domain}\t{record.knowledge_type}\t{record.knowledge_review_status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())