#!/usr/bin/env python3
"""로컬 RAW 한 건을 검토 대기 KNOWLEDGE로 변환합니다."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tak_brain import load_raw_records, transform_raw


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TAK BRAIN KNOWLEDGE 생성")
    parser.add_argument("--input", default=str(ROOT / "data" / "tak_brain_raw.json"))
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--output", default=str(ROOT / "data" / "tak_brain_knowledge.json"))
    args = parser.parse_args(argv)

    raws = [raw for raw in load_raw_records(args.input) if raw.source_url == args.source_url]
    if len(raws) != 1:
        parser.error(f"source_url에 해당하는 RAW가 {len(raws)}개입니다.")
    knowledge = transform_raw(raws[0])
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps([knowledge.to_dict()], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"KNOWLEDGE ID: {knowledge.id}")
    print(f"제목: {knowledge.title}")
    print(f"domain: {knowledge.domain}")
    print(f"knowledge_type: {knowledge.knowledge_type}")
    print(f"experience 요약: {knowledge.experience}")
    print(f"problem 요약: {knowledge.problem}")
    print(f"lesson 요약: {knowledge.lesson}")
    print(f"reusable_principle 요약: {knowledge.reusable_principle}")
    print(f"ai_inference: {'있음' if knowledge.ai_inference else '없음'}")
    print(f"confidence: {knowledge.confidence:.2f}")
    print(f"review_status: {knowledge.knowledge_review_status}")
    print(f"source RAW 연결 여부: {'예' if knowledge.source_raw_id and knowledge.source_url else '아니오'}")
    print(f"KNOWLEDGE 저장: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
