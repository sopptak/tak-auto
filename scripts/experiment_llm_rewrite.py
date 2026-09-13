#!/usr/bin/env python3
"""KNOWLEDGE 001의 LLM Rewrite Layer 실험을 위한 명시적 실행 스크립트."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_engine.generator import generate_content_bundle
from content_engine.llm_provider import OpenAICompatibleRewriteProvider
from content_engine.rewrite import RewriteService
from tak_brain import load_knowledge_records


KNOWLEDGE_ID = "knowledge-da6ddf5aa459"


def _drafts_for_experiment(knowledge_path: Path):
    records = load_knowledge_records(knowledge_path)
    knowledge = next((record for record in records if record.id == KNOWLEDGE_ID), None)
    if knowledge is None:
        raise KeyError(f"KNOWLEDGE를 찾을 수 없습니다: {KNOWLEDGE_ID}")
    bundle = generate_content_bundle(knowledge)
    if bundle.status != "complete" or bundle.blog is None:
        raise ValueError(f"실험용 콘텐츠를 생성할 수 없습니다: {bundle.status}")
    return knowledge, (bundle.blog, *bundle.shorts, *bundle.threads)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TAK MEDIA LLM Rewrite experiment")
    parser.add_argument(
        "--input",
        type=Path,
        default=ROOT / "data" / "tak_brain_knowledge.json",
        help="읽기 전용 KNOWLEDGE JSON 경로",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="실제 LLM API 호출을 명시적으로 허용합니다.",
    )
    args = parser.parse_args(argv)

    knowledge, drafts = _drafts_for_experiment(args.input)
    if not args.execute:
        print(f"dry-run: {knowledge.id}")
        print(f"drafts: {len(drafts)} (Blog 1, Shorts 3, Threads 5)")
        print("네트워크 호출 없음. 실제 호출에는 --execute와 TAK_MEDIA_LLM_API_KEY, TAK_MEDIA_LLM_ENDPOINT, TAK_MEDIA_LLM_MODEL이 필요합니다.")
        return 0

    provider = OpenAICompatibleRewriteProvider.from_environment()
    service = RewriteService(provider)
    for index, draft in enumerate(drafts, start=1):
        result = service.rewrite(knowledge, draft)
        print(f"[{index}] {type(draft).__name__}: {result.rewrite_status}/{result.validation_status}")
        if result.validation_errors:
            print("; ".join(result.validation_errors))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
