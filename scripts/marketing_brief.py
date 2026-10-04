#!/usr/bin/env python3
"""AI Marketing Intelligence CLI. draft/platforms/suggest/generate/bridge는 기본이 미리보기이며 --write가 있어야 data/에 저장한다.

  draft IDEA_ID [--research PROVIDER]  아이디어 -> (리서치 -> pending KNOWLEDGE) -> 브리프 초안
  score BRIEF_ID                        마케팅 점수(조회/참여/전환 분리)
  platforms BRIEF_ID                    blog/threads/shorts/youtube 브리프 파생
  status BRIEF_ID STATUS                draft/approved/rejected (사람이 승인)
  link BRIEF_ID CONTENT_ID              브리프와 콘텐츠 연결(성과 귀속)
  prompt BRIEF_ID [--allow-draft]       콘텐츠 생성 프롬프트 계약 출력
  insights                              성과 -> 마케팅 속성 lift

  suggest BRIEF_ID                      근거 기반 빈칸 제안(--write면 제안 저장소에 추가, 브리프는 그대로)
  review BRIEF_ID                       요소/빈칸/대기 제안/승인·생성 차단 사유 요약
  set BRIEF_ID DIM.ELEM VALUE           사람이 요소를 직접 수정(approved였다면 draft로 돌아간다)
  approve BRIEF_ID | reject BRIEF_ID    사람의 승인(승인 조건 통과 필요) / 반려
  suggestion accept|reject SUGGESTION_ID  제안 반영/거절
  generate BRIEF_ID [--rewrite mock|llm]  승인 브리프 -> 기존 생성기 -> review_required 후보
                                        (기본 미리보기, --write일 때만 data/tak_marketing_contents.json 저장)
  bridge BRIEF_ID                       저장된 후보 -> 기존 MEDIA generation pool(unreviewed)
                                        (기본 미리보기, --write일 때만 data/tak_media_generation_marketing-<brief_id>.json).
                                        검토는 대시보드 /media/generations, 승격은 scripts/promote_media_generation.py

set/approve/reject/suggestion/status/link는 사람의 결정이므로 실행 즉시 브리프 저장소에 반영된다.
자동 발행은 하지 않는다. 외부 API는 --research 또는 generate --rewrite llm을 줄 때만 호출한다.
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
    CONTENTS_FILE, MarketingError, append_briefs, bridge_to_generation_pool, load_candidates, mark_bridged, plan_bridge,
    pool_path_for, append_suggestions, approval_blockers, attribute_lift,
    brief_from_idea, build_content_prompt, collect_marketing_insights, derive_all_platform_briefs, generate_candidates,
    generation_blockers, link_content, load_briefs, load_suggestions, render_prompt_text, research_idea,
    resolve_suggestion, save_candidates, score_brief, set_brief_status, suggest_elements, update_element,
)
from content_engine.marketing.models import DIMENSIONS
from content_engine.rewrite import MockRewriteProvider
from tak_brain.knowledge import load_knowledge_records
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


def _rewrite_provider(name: str | None):
    if name is None:
        return None
    if name == "mock":
        return MockRewriteProvider()
    # llm만 외부 API를 쓴다. 키/엔드포인트는 환경변수에서만 읽는다.
    from content_engine.llm_provider import OpenAICompatibleRewriteProvider
    return OpenAICompatibleRewriteProvider.from_environment()


def _print_review(brief, suggestions) -> None:
    score = score_brief(brief)
    print(f"{brief.brief_id} [{brief.status}] platform={brief.platform or '공통'} topic={brief.topic}")
    print(f"점수 total={score.total_score} confidence={score.confidence} profile={score.profile}")
    for name in ("target_audience", "customer_problem", "desired_action"):
        print(f"  brief.{name}: {getattr(brief, name) or '(비어 있음)'}")
    for name in DIMENSIONS:
        for element, value in brief.dimension(name).filled().items():
            print(f"  {name}.{element}: {value}")
    print("빈 요소:", ", ".join(brief.missing_fields()) or "없음")
    pending = [item for item in suggestions if item.brief_id == brief.brief_id and item.status == "suggested"]
    print(f"대기 중인 제안 {len(pending)}건")
    for item in pending:
        print(f"  {item.suggestion_id} {item.key} (confidence {item.confidence}, {item.basis}): {item.suggested_value}")
    blockers = approval_blockers(brief)
    print("승인 차단:", " / ".join(blockers) if blockers else "없음(approve 가능)")
    blockers = generation_blockers(brief)
    print("생성 차단:", " / ".join(blockers) if blockers else "없음(generate 가능)")
    print(f"연결된 콘텐츠 {len(brief.content_ids)}건")


def _print_candidates(result) -> None:
    print(f"{result.brief_id} platform={result.platform}: 후보 {len(result.candidates)}건 (status=review_required)")
    for candidate in result.candidates:
        title = candidate["rewritten_title"] if candidate["rewrite_status"] == "rewritten" else candidate["original_title"]
        print(f"- {candidate['content_id']} {candidate['knowledge_id']} rewrite={candidate['rewrite_status']} | {title}")
        for error in candidate.get("validation_errors") or ():
            print(f"    검증 오류: {error}")
        if candidate.get("rewrite_error"):
            print(f"    재작성 오류: {candidate['rewrite_error']}")
        if candidate.get("shorts_script_error"):
            print(f"    ShortsScript 변환 실패: {candidate['shorts_script_error']}")
    for reason in result.reasons:
        print(f"사유: {reason}")


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
    sub.add_parser("suggest").add_argument("brief_id")
    sub.add_parser("review").add_argument("brief_id")
    set_cmd = sub.add_parser("set")
    set_cmd.add_argument("brief_id")
    set_cmd.add_argument("key", metavar="DIM.ELEM")
    set_cmd.add_argument("value")
    sub.add_parser("approve").add_argument("brief_id")
    sub.add_parser("reject").add_argument("brief_id")
    suggestion = sub.add_parser("suggestion")
    suggestion.add_argument("action", choices=("accept", "reject"))
    suggestion.add_argument("suggestion_id")
    generate = sub.add_parser("generate")
    generate.add_argument("brief_id")
    generate.add_argument("--rewrite", choices=("mock", "llm"), help="생략하면 규칙 기반 초안만(재작성 없음)")
    sub.add_parser("bridge").add_argument("brief_id")
    args = parser.parse_args(argv)

    data = args.data_dir
    briefs_path = data / "tak_marketing_briefs.json"
    suggestions_path = data / "tak_marketing_suggestions.json"
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
        elif args.command == "suggest":
            items = suggest_elements(_find(load_briefs(briefs_path), args.brief_id))
            for item in items:
                print(f"- {item.suggestion_id} {item.key} (confidence {item.confidence}, {item.basis}): {item.suggested_value}")
            print(f"제안 {len(items)}건 (근거가 없는 요소는 제안하지 않습니다)")
            if args.write:
                print(f"저장: {append_suggestions(suggestions_path, items)}건 (브리프는 accept 전까지 바뀌지 않습니다)")
            else:
                print("(미리보기: 저장하려면 --write)")
        elif args.command == "review":
            suggestions = load_suggestions(suggestions_path) if suggestions_path.exists() else []
            _print_review(_find(load_briefs(briefs_path), args.brief_id), suggestions)
        elif args.command == "set":
            updated = update_element(briefs_path, args.brief_id, args.key, args.value)
            print(f"{args.key} 저장, status={updated.status}")
        elif args.command in ("approve", "reject"):
            status = "approved" if args.command == "approve" else "rejected"
            print(set_brief_status(briefs_path, args.brief_id, status).status)
        elif args.command == "suggestion":
            resolved = resolve_suggestion(suggestions_path, briefs_path, args.suggestion_id, args.action == "accept")
            print(f"{resolved.suggestion_id} {resolved.status} ({resolved.key})")
        elif args.command == "generate":
            brief = _find(load_briefs(briefs_path), args.brief_id)
            blockers = generation_blockers(brief)
            if blockers:
                raise MarketingError("생성 차단: " + " / ".join(blockers))
            knowledge = load_knowledge_records(data / "tak_brain_knowledge.json")
            result = generate_candidates(brief, knowledge, provider=_rewrite_provider(args.rewrite))
            _print_candidates(result)
            if result.blockers:
                return 2
            if args.write and result.candidates:
                saved = save_candidates(data / CONTENTS_FILE, briefs_path, result)
                print(f"저장: 후보 {saved}건(review_required), 브리프 연결 {len(result.candidates)}건. 발행하지 않습니다.")
            elif not args.write:
                print("(미리보기: 저장하려면 --write. 저장해도 review_required이며 발행하지 않습니다)")
        elif args.command == "bridge":
            brief = _find(load_briefs(briefs_path), args.brief_id)
            candidates = load_candidates(data / CONTENTS_FILE, brief.brief_id)
            plan = plan_bridge(brief, candidates)
            pool = pool_path_for(data, brief.brief_id)
            print(f"{brief.brief_id}: bridge 대상 {len(plan.items)}건 -> {pool.name} (review_status=unreviewed)")
            for item, content_id in zip(plan.items, plan.content_ids):
                print(f"- {content_id} {item.platform} generation_status={item.status}")
            for reason in plan.skipped:
                print(f"제외: {reason}")
            if not args.write:
                print("(미리보기: 저장하려면 --write. 승인/승격/발행은 하지 않습니다)")
            elif plan.items:
                result = bridge_to_generation_pool(brief, candidates, pool)
                mark_bridged(data / CONTENTS_FILE, result)
                print(f"저장: generation_id={result.generation_id}, {len(result.refs)}건. "
                      "검토는 /media/generations, 승격은 promote_media_generation.py로 사람이 진행합니다.")
    except (MarketingError, ProviderError, ValueError, OSError) as error:
        print(f"오류: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
