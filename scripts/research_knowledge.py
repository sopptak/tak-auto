#!/usr/bin/env python3
"""리서치 Provider로 주제를 조사해 pending KNOWLEDGE 후보를 만든다(기본은 미리보기).

Provider 선택: --provider 또는 TAK_RESEARCH_PROVIDER, 기본은 PERPLEXITY_API_KEY가 있으면
perplexity, 없으면 mock. --write를 줘야만 data/tak_brain_knowledge.json에 pending으로 append한다.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_engine.providers import ProviderError, get_research_provider
from content_engine.research_bridge import research_to_knowledge


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query")
    parser.add_argument("--provider")
    parser.add_argument("--domain", action="append", dest="domains")
    parser.add_argument("--recency", choices=["hour", "day", "week", "month", "year"])
    parser.add_argument("--max-results", type=int, default=5)
    parser.add_argument("--knowledge-file", type=Path, default=ROOT / "data" / "tak_brain_knowledge.json")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)

    try:
        provider = get_research_provider(args.provider)
        result = provider.research(args.query, domains=args.domains, recency=args.recency, max_results=args.max_results)
        record = research_to_knowledge(result)
    except (ProviderError, ValueError) as error:
        print(f"오류: {error}", file=sys.stderr)
        return 1

    print(f"provider={result.provider} 출처 {len(result.sources)}건 -> {record.id} (pending)")
    for source in result.sources:
        print(f"- [{source.rank}] {source.title} {source.url}")
    if not args.write:
        print("저장하지 않음(--write 필요).")
        return 0

    data = json.loads(args.knowledge_file.read_text(encoding="utf-8")) if args.knowledge_file.exists() else []
    if any(item.get("id") == record.id for item in data):
        print("이미 존재하는 후보라 건너뜀.")
        return 0
    data.append(record.to_dict())
    tmp = args.knowledge_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(args.knowledge_file)
    print(f"저장: {args.knowledge_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
