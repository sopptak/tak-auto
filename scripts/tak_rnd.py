#!/usr/bin/env python3
"""TAK AUTO R&D Radar and IDEA Vault operations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tak_rnd import (
    DEFAULT_IDEA_PATH,
    DEFAULT_RND_PATH,
    IDEA_STATUSES,
    RND_CATEGORIES,
    RND_STATUSES,
    RndStoreError,
    add_idea,
    add_rnd_item,
    import_rnd_items,
    load_ideas,
    load_rnd_items,
    priority_ideas,
    promote_rnd_to_idea,
    set_idea_canonical_id,
    set_idea_status,
    set_rnd_canonical_id,
    set_rnd_status,
    validation_ideas,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="TAK AUTO R&D Radar / IDEA Vault")
    parser.add_argument("--rnd-store", type=Path, default=DEFAULT_RND_PATH, help="R&D JSON 저장소")
    parser.add_argument("--idea-store", type=Path, default=DEFAULT_IDEA_PATH, help="IDEA JSON 저장소")
    commands = parser.add_subparsers(dest="command", required=True)

    add_rnd = commands.add_parser("add-rnd", help="외부 발견 정보 1건 등록")
    add_rnd.add_argument("--source", choices=("threads", "web", "github", "youtube", "manual", "aside", "other"), default="manual")
    add_rnd.add_argument("--url", default="")
    add_rnd.add_argument("--author", default="")
    add_rnd.add_argument("--source-item-id", default="")
    add_rnd.add_argument("--title", required=True)
    add_rnd.add_argument("--summary", default="")
    add_rnd.add_argument("--key-point", action="append", default=[])
    add_rnd.add_argument("--technology", action="append", default=[])
    add_rnd.add_argument("--category", action="append", choices=RND_CATEGORIES, default=[])
    add_rnd.add_argument("--notes", default="")

    import_rnd = commands.add_parser("import-rnd", help="Aside/browser-agent JSON 가져오기")
    import_rnd.add_argument("--file", type=Path, required=True)

    list_rnd = commands.add_parser("list-rnd", help="R&D 항목 조회")
    list_rnd.add_argument("--status", choices=RND_STATUSES)
    show_rnd = commands.add_parser("show-rnd", help="R&D 항목 상세 조회")
    show_rnd.add_argument("--id", required=True)

    add_idea_parser = commands.add_parser("add-idea", help="IDEA Vault에 아이디어 등록")
    add_idea_parser.add_argument("--title", required=True)
    add_idea_parser.add_argument("--description", required=True)
    add_idea_parser.add_argument("--why-important", required=True)
    add_idea_parser.add_argument("--area", action="append", default=[])
    add_idea_parser.add_argument("--expected-impact", default="")
    add_idea_parser.add_argument("--difficulty", choices=("low", "medium", "high", "unknown"), default="unknown")
    add_idea_parser.add_argument("--effort-hours", type=float)
    add_idea_parser.add_argument("--fit-score", type=int, choices=range(1, 6))
    add_idea_parser.add_argument("--impact-score", type=int, choices=range(1, 6))
    add_idea_parser.add_argument("--novelty-score", type=int, choices=range(1, 6))
    add_idea_parser.add_argument("--related-feature", action="append", default=[])
    add_idea_parser.add_argument("--related-content-id", action="append", default=[])
    add_idea_parser.add_argument("--validation-plan", default="")

    promote = commands.add_parser("promote", help="R&D 항목을 IDEA로 승격")
    promote.add_argument("--rnd-id", required=True)
    promote.add_argument("--idea-title")
    promote.add_argument("--description", default="TAK AUTO에 적용할 방법을 검토한다.")
    promote.add_argument("--why-important", default="TAK AUTO 적용 가치가 있다고 판단되어 검토한다.")
    promote.add_argument("--area", action="append", default=[])
    promote.add_argument("--expected-impact", default="")
    promote.add_argument("--difficulty", choices=("low", "medium", "high", "unknown"), default="unknown")
    promote.add_argument("--effort-hours", type=float)

    list_ideas = commands.add_parser("list-ideas", help="IDEA 목록 조회")
    list_ideas.add_argument("--status", choices=IDEA_STATUSES)
    show_idea = commands.add_parser("show-idea", help="IDEA 상세 조회")
    show_idea.add_argument("--id", required=True)
    set_status = commands.add_parser("set-status", help="R&D 또는 IDEA 상태 변경")
    set_status.add_argument("--type", choices=("rnd", "idea"), required=True)
    set_status.add_argument("--id", required=True)
    set_status.add_argument("--status", required=True)

    duplicates = commands.add_parser("duplicates", help="중복 후보 조회")
    duplicates.add_argument("--type", choices=("rnd", "idea", "all"), default="all")
    link = commands.add_parser("link-canonical", help="검토한 중복 항목을 canonical 레코드에 연결")
    link.add_argument("--type", choices=("rnd", "idea"), required=True)
    link.add_argument("--duplicate-id", required=True)
    link.add_argument("--canonical-id", required=True)
    commands.add_parser("priority", help="평가 입력이 있는 IDEA를 우선순위순 조회")
    commands.add_parser("needs-validation", help="검증 대기 IDEA 조회")
    return parser


def _print_record(record: Any) -> None:
    print(json.dumps(record.to_dict(), ensure_ascii=False, indent=2))


def _list_records(records: list[Any]) -> None:
    if not records:
        print("조회 결과가 없습니다.")
        return
    for record in records:
        title = record.title.replace("\n", " ")
        print(f"{record.id} | {record.status} | {title}")
        if getattr(record, "duplicate_candidate_ids", ()):
            print(f"  duplicate candidates: {', '.join(record.duplicate_candidate_ids)}")


def _print_ideas(records: list[Any]) -> None:
    if not records:
        print("조회 결과가 없습니다.")
        return
    for idea in records:
        score = "미평가" if idea.priority_score is None else str(idea.priority_score)
        print(f"{idea.id} | {idea.status} | priority {score} | {idea.title}")
        if idea.duplicate_candidate_ids:
            print(f"  duplicate candidates: {', '.join(idea.duplicate_candidate_ids)}")


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "add-rnd":
            item = add_rnd_item(
                {
                    "source": args.source,
                    "source_url": args.url,
                    "source_author": args.author,
                    "source_item_id": args.source_item_id,
                    "title": args.title,
                    "summary": args.summary,
                    "key_points": args.key_point,
                    "technologies": args.technology,
                    "categories": args.category or ["other"],
                    "notes": args.notes,
                },
                args.rnd_store,
            )
            print(f"R&D 등록: {item.id}" + (f" (중복 후보: {', '.join(item.duplicate_candidate_ids)})" if item.duplicate_candidate_ids else ""))
        elif args.command == "import-rnd":
            imported, duplicate_count = import_rnd_items(json.loads(args.file.read_text(encoding="utf-8")), args.rnd_store)
            print(f"R&D 가져오기: {len(imported)}건 (중복 후보 {duplicate_count}건)")
        elif args.command == "list-rnd":
            records = load_rnd_items(args.rnd_store)
            _list_records([item for item in records if args.status is None or item.status == args.status])
        elif args.command == "show-rnd":
            item = next((item for item in load_rnd_items(args.rnd_store) if item.id == args.id), None)
            if item is None:
                raise KeyError(f"R&D ID를 찾을 수 없습니다: {args.id}")
            _print_record(item)
        elif args.command == "add-idea":
            idea = add_idea(
                {
                    "title": args.title,
                    "description": args.description,
                    "why_important": args.why_important,
                    "application_areas": args.area,
                    "expected_impact": args.expected_impact,
                    "implementation_difficulty": args.difficulty,
                    "estimated_effort_hours": args.effort_hours,
                    "strategic_fit_score": args.fit_score,
                    "expected_impact_score": args.impact_score,
                    "novelty_score": args.novelty_score,
                    "related_features": args.related_feature,
                    "related_content_ids": args.related_content_id,
                    "validation_plan": args.validation_plan,
                },
                args.idea_store,
            )
            print(f"IDEA 등록: {idea.id} (priority {idea.priority_score if idea.priority_score is not None else '미평가'})")
        elif args.command == "promote":
            rnd = next((item for item in load_rnd_items(args.rnd_store) if item.id == args.rnd_id), None)
            if rnd is None:
                raise KeyError(f"R&D ID를 찾을 수 없습니다: {args.rnd_id}")
            idea = promote_rnd_to_idea(
                rnd.id,
                {
                    "title": args.idea_title or f"TAK AUTO 적용: {rnd.title}",
                    "description": args.description,
                    "why_important": args.why_important,
                    "application_areas": args.area,
                    "expected_impact": args.expected_impact,
                    "implementation_difficulty": args.difficulty,
                    "estimated_effort_hours": args.effort_hours,
                },
                args.rnd_store,
                args.idea_store,
            )
            print(f"IDEA 승격: {idea.id} <- {rnd.id}")
        elif args.command == "list-ideas":
            records = load_ideas(args.idea_store)
            _print_ideas([idea for idea in records if args.status is None or idea.status == args.status])
        elif args.command == "show-idea":
            idea = next((idea for idea in load_ideas(args.idea_store) if idea.id == args.id), None)
            if idea is None:
                raise KeyError(f"IDEA ID를 찾을 수 없습니다: {args.id}")
            _print_record(idea)
        elif args.command == "set-status":
            if args.type == "rnd":
                record = set_rnd_status(args.id, args.status, args.rnd_store)
            else:
                record = set_idea_status(args.id, args.status, args.idea_store)
            print(f"{record.id}: {record.status}")
        elif args.command == "duplicates":
            if args.type in {"rnd", "all"}:
                for item in load_rnd_items(args.rnd_store):
                    if item.duplicate_candidate_ids:
                        print(f"R&D {item.id}: {', '.join(item.duplicate_candidate_ids)}")
            if args.type in {"idea", "all"}:
                for idea in load_ideas(args.idea_store):
                    if idea.duplicate_candidate_ids:
                        print(f"IDEA {idea.id}: {', '.join(idea.duplicate_candidate_ids)}")
        elif args.command == "link-canonical":
            if args.type == "rnd":
                record = set_rnd_canonical_id(args.duplicate_id, args.canonical_id, args.rnd_store)
            else:
                record = set_idea_canonical_id(args.duplicate_id, args.canonical_id, args.idea_store)
            print(f"{record.id} -> canonical {record.canonical_id}")
        elif args.command == "priority":
            _print_ideas(priority_ideas(args.idea_store))
        elif args.command == "needs-validation":
            _print_ideas(validation_ideas(args.idea_store))
        return 0
    except (OSError, json.JSONDecodeError, RndStoreError, ValueError, KeyError) as error:
        print(f"오류: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())