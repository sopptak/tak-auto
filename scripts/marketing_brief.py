#!/usr/bin/env python3
"""AI Marketing Intelligence CLI. 모든 하위 명령은 기본이 미리보기이며 --write가 있어야 data/에 저장한다.

  draft IDEA_ID [--research PROVIDER]  아이디어 -> (리서치 -> pending KNOWLEDGE) -> 브리프 초안
  score BRIEF_ID                        마케팅 점수(조회/참여/전환 분리)
  platforms BRIEF_ID                    blog/threads/shorts/youtube 브리프 파생
  status BRIEF_ID STATUS                draft/approved/rejected (사람이 승인)
  link BRIEF_ID CONTENT_ID              브리프와 콘텐츠 연결(성과 귀속)
  prompt BRIEF_ID [--allow-draft]       콘텐츠 생성 프롬프트 계약 출력
  insights                              성과 -> 마케팅 속성 lift

자동 발행/생성은 하지 않는다. 외부 API는 --research를 줄 때만 호출한다.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_engine.market_demand import load_demands, load_ideas
from content_engine.marketing import (
    MarketingError, append_briefs, attribute_lift, brief_from_idea, build_content_prompt, collect_marketing_insights,
    derive_all_platform_briefs, link_content, load_briefs, render_prompt_text, research_idea, score_brief,
    set_brief_status,
)
from content_engine.performance.store import latest_snapshot_per_content
from content_engine.providers import ProviderError, get_research_provider


def _append_knowledge(path: Path, records) -> int:
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    seen = {item.get("id") for item in data}
    new = [record.to_dict() for record in records if record.id not in seen]
    if new:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data + new, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
    return len(new)


def _find(briefs, brief_id):
    for brief in briefs:
        if brief.brief_id == brief_id:
            return brief
    raise MarketingError(f"브리프를 찾을 수 없습니다: {brief_id}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--write", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    draft = sub.add_parser("draft")
    draft.add_argument("idea_id")
    draft.add_argument("--research", metavar="PROVIDER", help="mock|perplexity (생략하면 리서치 없이 시장 근거만)")
    sub.add_parser("score").add_argument("brief_id")
    sub.add_parser("platforms").add_argument("brief_id")
    status = sub.add_parser("status")
    status.add_argument("brief_id")
    status.add_argument("new_status")
    link = sub.add_parser("link")
    link.add_argument("brief_id")
    link.add_argument("content_id")
    prompt = sub.add_parser("prompt")
    prompt.add_argument("brief_id")
    prompt.add_argument("--allow-draft", action="store_true")
    sub.add_parser("insights")
    args = parser.parse_args(argv)

    data = args.data_dir
    briefs_path = data / "tak_marketing_briefs.json"
    try:
        if args.command == "draft":
            ideas = {idea.idea_id: idea for idea in load_ideas(data / "tak_idea_candidates.json")}
            if args.idea_id not in ideas:
                raise MarketingError(f"아이디어를 찾을 수 없습니다: {args.idea_id}")
            bundle, knowledge = None, []
            if args.research:
                bundle = research_idea(ideas[args.idea_id], get_research_provider(args.research))
                knowledge = bundle.knowledge_records()
                for aspect, message in bundle.errors.items():
                    print(f"경고: {aspect} 실패: {message}", file=sys.stderr)
            brief = brief_from_idea(ideas[args.idea_id], load_demands(data / "tak_market_demands.json"), bundle,
                                    [record.id for record in knowledge])
            print(f"{brief.brief_id} draft, 근거 {len(brief.evidence)}건, confidence {brief.confidence}")
            print("채워야 할 요소:", ", ".join(brief.missing_fields()))
            if args.write:
                added = append_briefs(briefs_path, [brief])
                saved = _append_knowledge(data / "tak_brain_knowledge.json", knowledge)
                print(f"저장: 브리프 {added}건, pending KNOWLEDGE {saved}건")
            else:
                print("(미리보기: 저장하려면 --write)")
        elif args.command == "score":
            print(json.dumps(score_brief(_find(load_briefs(briefs_path), args.brief_id)).to_dict(), ensure_ascii=False, indent=2))
        elif args.command == "platforms":
            derived = derive_all_platform_briefs(_find(load_briefs(briefs_path), args.brief_id))
            for platform, item in derived.items():
                print(f"- {platform}: {item.brief_id} {item.distribution.distribution_angle}")
            if args.write:
                print(f"저장: {append_briefs(briefs_path, list(derived.values()))}건")
        elif args.command == "status":
            print(set_brief_status(briefs_path, args.brief_id, args.new_status).status)
        elif args.command == "link":
            print(link_content(briefs_path, args.brief_id, args.content_id).content_ids)
        elif args.command == "prompt":
            contract = build_content_prompt(_find(load_briefs(briefs_path), args.brief_id), allow_draft=args.allow_draft)
            print(render_prompt_text(contract))
        elif args.command == "insights":
            perf = data / "tak_performance.json"
            snapshots = latest_snapshot_per_content(perf) if perf.exists() else {}
            insights = collect_marketing_insights(load_briefs(briefs_path), snapshots)
            print(f"연결된 콘텐츠 성과 {len(insights)}건")
            for metric in ("conversion_rate", "engagement_rate"):
                for attribute, row in attribute_lift(insights, metric).items():
                    if row["lift"] is not None:
                        print(f"{metric} {attribute}: lift {row['lift']} (n={row['n_with']}/{row['n_without']})")
    except (MarketingError, ProviderError, ValueError, OSError) as error:
        print(f"오류: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
