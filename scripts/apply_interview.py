#!/usr/bin/env python3
"""TAK INTERVIEW 답변을 TAK BRAIN KNOWLEDGE(pending)로 연결하는 CLI.

아직 답변하지 않은 TAK SCOUT 후보는 KNOWLEDGE로 넘어가지 않는다. 새로 만들어지는
KNOWLEDGE는 review_knowledge.py로 사람이 승인하기 전까지 pending 상태이며, TAK MEDIA
콘텐츠 생성 대상이 아니다(기존 승인 흐름과 동일).
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tak_scout.knowledge_bridge import append_scout_knowledge


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TAK INTERVIEW 답변 -> TAK BRAIN KNOWLEDGE 연결")
    parser.add_argument(
        "--daily-pack",
        type=Path,
        default=ROOT / "data" / "tak_scout_daily.json",
        help="TAK SCOUT 결과 경로 (기본값: data/tak_scout_daily.json)",
    )
    parser.add_argument(
        "--answers",
        type=Path,
        default=ROOT / "data" / "tak_interview_answers.json",
        help="TAK INTERVIEW 답변 경로 (기본값: data/tak_interview_answers.json)",
    )
    parser.add_argument(
        "--knowledge",
        type=Path,
        default=ROOT / "data" / "tak_brain_knowledge.json",
        help="KNOWLEDGE 누적 저장 경로 (기본값: data/tak_brain_knowledge.json)",
    )
    args = parser.parse_args(argv)

    try:
        created, skipped_unanswered, duplicates = append_scout_knowledge(
            args.daily_pack, args.answers, args.knowledge
        )
    except (OSError, ValueError) as err:
        print(f"오류: {err}", file=sys.stderr)
        return 1

    print(f"신규 KNOWLEDGE(pending): {created}건")
    print(f"미답변으로 건너뜀: {skipped_unanswered}건")
    print(f"이미 연결됨(중복): {duplicates}건")
    print(f"저장 위치: {args.knowledge}")
    print("다음 단계: python3 scripts/review_knowledge.py --pending 로 검토한 뒤 --id <ID> --approve 하세요.")
    print("승인 후에는 기존 TAK MEDIA 파이프라인(run_media_batch.py, run_daily.py 등)을 그대로 사용합니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
