#!/usr/bin/env python3
"""KNOWLEDGE -> MEDIA 콘텐츠 전략/품질 Gate를 점검하는 읽기 전용
CLI(6-37).

기존 KNOWLEDGE(data/tak_brain_knowledge.json)와 Production Archive
(data/tak_media_archive.json)를 읽기만 한다 - 어떤 파일도 쓰지 않는다.
판정 로직은 순수 함수(``content_engine.media_strategy.evaluate_media_strategy()``)에
있다.

이 스크립트가 절대 하지 않는 것:
    - MEDIA를 생성하는 것(``content_engine.pipeline``을 import하지 않는다)
    - KNOWLEDGE 승인 상태를 바꾸는 것
    - Production Archive를 수정하는 것
    - 실제 외부 API 호출

"STRATEGY_READY"는 "지금 생성해도 되는 후보"라는 뜻일 뿐, 이 CLI가 자동으로
생성을 실행하지 않는다(15장 Generation Policy).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_engine.media_archive import load_archive
from content_engine.media_strategy import PLATFORMS, STRATEGY_STATUSES, evaluate_media_strategy
from tak_brain import load_knowledge_records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="KNOWLEDGE -> MEDIA 콘텐츠 전략/품질 Gate를 점검하는 읽기 전용 CLI."
    )
    parser.add_argument(
        "--knowledge", type=Path, default=ROOT / "data" / "tak_brain_knowledge.json",
        help="읽기 전용 KNOWLEDGE JSON 경로 (기본값: data/tak_brain_knowledge.json)",
    )
    parser.add_argument(
        "--production-archive", type=Path, default=ROOT / "data" / "tak_media_archive.json",
        help="Production Archive 경로, 읽기 전용(superseded/duplicate 판정용) (기본값: data/tak_media_archive.json)",
    )
    parser.add_argument("--knowledge-id", default=None, help="특정 knowledge_id 1건만 평가")
    parser.add_argument("--platform", choices=PLATFORMS, default=None, help="특정 platform eligibility만 출력")
    parser.add_argument("--status", choices=STRATEGY_STATUSES, default=None, help="특정 status인 것만 출력")
    parser.add_argument("--all", action="store_true", help="모든 KNOWLEDGE(승인 여부 무관)를 평가")
    parser.add_argument("--json", action="store_true", help="사람이 읽는 표 대신 JSON으로 출력")
    args = parser.parse_args(argv)

    try:
        records = load_knowledge_records(args.knowledge)
    except (OSError, ValueError) as error:
        print(f"오류: KNOWLEDGE 파일을 읽을 수 없습니다: {error}", file=sys.stderr)
        return 1

    if args.knowledge_id:
        records = [r for r in records if r.id == args.knowledge_id]
        if not records:
            print(f"오류: knowledge_id를 찾을 수 없습니다: {args.knowledge_id}", file=sys.stderr)
            return 1
    elif not args.all:
        records = [r for r in records if r.knowledge_review_status == "approved"]

    production_records = load_archive(args.production_archive)

    candidates = [
        evaluate_media_strategy(record, production_records=production_records, other_knowledge=records)
        for record in records
    ]

    if args.status:
        candidates = [c for c in candidates if c.status == args.status]

    if args.json:
        payload = [c.to_dict() for c in candidates]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if not candidates:
        print("평가할 KNOWLEDGE가 없습니다.")
        return 0

    print("=== Media Strategy Gate (읽기 전용) ===")
    for candidate in candidates:
        print(f"\nknowledge_id: {candidate.knowledge_id}")
        print(f"  topic: {candidate.topic}")
        print(f"  status: {candidate.status}")
        print(f"  category/domain/article_type: {candidate.category!r} / {candidate.domain!r} / {candidate.article_type!r}")
        print(f"  reason_codes: {', '.join(candidate.reason_codes) or '(없음)'}")
        print(f"  risk_flags: {', '.join(candidate.risk_flags) or '(없음)'}")
        print(f"  evidence_quality: {candidate.evidence_quality}")
        print(f"  novelty_signal: {candidate.novelty_signal}")
        print(f"  human_review_required: {candidate.human_review_required}")
        print(f"  content_angles: {', '.join(candidate.content_angles)}")
        for item in candidate.platform_eligibility:
            if args.platform and item.platform != args.platform:
                continue
            print(f"  platform[{item.platform}]: {item.status}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
