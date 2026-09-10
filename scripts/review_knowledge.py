#!/usr/bin/env python3
"""KNOWLEDGE review 상태를 조회하고 JSON 저장소에 반영합니다."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tak_brain import assess_knowledge_quality, list_pending_knowledge, review_knowledge_file


_DETAIL_FIELDS = (
    "id", "title", "domain", "knowledge_type", "experience", "problem",
    "action", "decision", "result", "lesson", "reusable_principle", "evidence",
    "derived_insight", "inference_method", "confidence", "knowledge_review_status",
    "source_raw_id", "source_url",
)


def _print_detail(record) -> None:
    quality, reason, recommendation = assess_knowledge_quality(record)
    for field in _DETAIL_FIELDS:
        print(f"{field}: {getattr(record, field)}")
    print(f"quality: {quality}")
    print(f"quality_reason: {reason}")
    print(f"approval_recommendation: {recommendation}")


def _print_report(record, number: int) -> None:
    quality, reason, recommendation = assess_knowledge_quality(record)
    key_judgment = record.lesson or record.derived_insight or record.reusable_principle or "핵심 판단 없음"
    caution = reason if quality != "A" else "현재 자동 판정상 주요 주의사항 없음"
    print(f"[{number:03d}]")
    print(f"제목: {record.title}")
    print(f"유형: {record.article_type or 'legacy'}")
    print(f"도메인: {record.domain}")
    print(f"품질: {quality}")
    print(f"핵심 판단: {key_judgment}")
    print(f"주의사항: {caution}")
    print(f"승인 권고: {recommendation}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TAK BRAIN KNOWLEDGE review")
    parser.add_argument("--input", default=str(ROOT / "data" / "tak_brain_knowledge.json"))
    parser.add_argument("--pending", action="store_true", help="pending KNOWLEDGE 목록")
    parser.add_argument("--report", action="store_true", help="pending KNOWLEDGE CEO 요약 report")
    parser.add_argument("--show", dest="show_id", help="검토용 KNOWLEDGE 요약")
    parser.add_argument("--id", dest="knowledge_id", help="KNOWLEDGE ID")
    decision = parser.add_mutually_exclusive_group()
    decision.add_argument("--approve", action="store_true")
    decision.add_argument("--reject", action="store_true")
    parser.add_argument("--note", help="review 메모")
    args = parser.parse_args(argv)

    if args.pending or args.report:
        records = list_pending_knowledge(args.input)
        if args.report:
            for number, record in enumerate(records, 1):
                _print_report(record, number)
                if number != len(records):
                    print()
        else:
            for number, record in enumerate(records, 1):
                print(f"[{number:03d}]")
                _print_detail(record)
                if number != len(records):
                    print()
        return 0

    if args.show_id:
        from tak_brain import load_knowledge_records

        record = next((item for item in load_knowledge_records(args.input) if item.id == args.show_id), None)
        if record is None:
            parser.error(f"KNOWLEDGE ID를 찾을 수 없습니다: {args.show_id}")
        _print_detail(record)
        return 0

    if not args.knowledge_id or not (args.approve or args.reject):
        parser.error("--pending 또는 --id와 --approve/--reject 조합이 필요합니다.")
    status = "approved" if args.approve else "rejected"
    try:
        record = review_knowledge_file(args.input, args.knowledge_id, status, args.note)
    except (OSError, ValueError, KeyError) as error:
        parser.error(str(error))
    print(f"{record.id}: {record.knowledge_review_status}")
    print(f"source_raw_id: {record.source_raw_id}")
    print(f"source_url: {record.source_url}")
    print(f"reviewed_at: {record.reviewed_at}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())