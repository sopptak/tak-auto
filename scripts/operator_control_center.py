#!/usr/bin/env python3
"""TAK AUTO Operator Control Center(6-38) - 10월 1일 실제 운영자가 한
화면에서 확인하는 통합 관제판. 읽기 전용 CLI다.

이 스크립트는 SCOUT/KNOWLEDGE/MEDIA/Production Archive/Threads pending/
Performance/Insight 파일을 **읽기만** 하고, git 상태(subprocess)와 환경변수
**존재 여부**(값은 절대 출력하지 않음)만 확인한다. 실제 집계 로직은
``content_engine.operator_summary``(순수 함수)에 있다 - 이 CLI는 로딩과
출력만 담당한다.

이 스크립트가 절대 하지 않는 것:
    - approve/dismiss/promote/publish/delete/restore/repair/regenerate
      (읽기 전용 - 6-38 16장 Read-only 원칙)
    - 실제 외부 API 호출
    - 존재하지 않는 파일을 자동으로 생성하는 것
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_engine.data_state import NOT_PRESENT, dir_status, json_file_status
from content_engine.media_archive import load_archive
from content_engine.operator_summary import OperatorInputs, StatusWhyAction, build_operator_summary
from content_engine.performance.store import load_snapshots
from content_engine.performance_insight import load_insights
from content_engine.threads_review import load_pending
from scripts.run_scout_dashboard import discover_generation_pool_paths
from tak_brain import load_knowledge_records
from tak_scout.collector import load_daily_pack


def _run_git(*args: str) -> tuple[int, str]:
    try:
        result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return 1, ""
    return result.returncode, result.stdout.strip()


def _load_operator_inputs(args: argparse.Namespace, test_status: str) -> OperatorInputs:
    _, head = _run_git("rev-parse", "HEAD")
    _, origin_main = _run_git("rev-parse", "origin/main")
    _, status_output = _run_git("status", "--short")
    working_tree_clean = status_output == ""

    scout_candidate_count = None
    if args.scout_daily.exists():
        try:
            scout_candidate_count = len(load_daily_pack(args.scout_daily))
        except (ValueError, OSError):
            scout_candidate_count = None

    knowledge_status, _ = json_file_status(args.knowledge)
    knowledge_records = ()
    if knowledge_status not in (NOT_PRESENT,):
        try:
            knowledge_records = tuple(load_knowledge_records(args.knowledge))
        except (ValueError, OSError):
            knowledge_records = ()

    generation_pool_paths = discover_generation_pool_paths(args.data_dir)
    generation_pool_records = tuple(
        record for path in generation_pool_paths for record in load_archive(path)
    )

    production_status, _ = json_file_status(args.production_archive)
    production_records = tuple(load_archive(args.production_archive)) if production_status != NOT_PRESENT else ()

    threads_pending_status, _ = json_file_status(args.threads_pending)
    threads_pending = tuple(load_pending(args.threads_pending)) if threads_pending_status != NOT_PRESENT else ()

    performance_status, _ = json_file_status(args.performance)
    performance_records = tuple(load_snapshots(args.performance)) if performance_status != NOT_PRESENT else ()

    insight_status, _ = json_file_status(args.insights)
    insight_records = tuple(load_insights(args.insights)) if insight_status != NOT_PRESENT else ()

    shorts_scripts_status, _ = dir_status(args.shorts_scripts, glob="*.json")
    blog_drafts_status, _ = dir_status(args.blog_drafts)

    return OperatorInputs(
        generated_at=datetime.now(timezone.utc).isoformat(),
        git_head=head, git_origin_main=origin_main, git_working_tree_clean=working_tree_clean,
        test_status=test_status,
        scout_candidate_count=scout_candidate_count,
        knowledge_status=knowledge_status, knowledge_records=knowledge_records,
        generation_pool_found=bool(generation_pool_paths), generation_pool_records=generation_pool_records,
        production_archive_status=production_status, production_records=production_records,
        threads_pending_status=threads_pending_status, threads_pending=threads_pending,
        performance_status=performance_status, performance_records=performance_records,
        insight_status=insight_status, insight_records=insight_records,
        shorts_scripts_status=shorts_scripts_status, blog_drafts_status=blog_drafts_status,
        threads_token_present=bool(os.environ.get("THREADS_ACCESS_TOKEN")),
        youtube_credentials_present=bool(
            os.environ.get("YOUTUBE_CLIENT_ID") and os.environ.get("YOUTUBE_CLIENT_SECRET") and os.environ.get("YOUTUBE_REFRESH_TOKEN")
        ),
        youtube_renderer_available=(ROOT / "content_engine" / "shorts_renderer.py").exists(),
    )


def _render_row(item: StatusWhyAction) -> str:
    parts = [f"{item.label}: {item.status}"]
    if item.count is not None:
        parts.append(f"({item.count}건)")
    line = " ".join(parts)
    if item.why:
        line += f"\n    WHY: {item.why}"
    if item.action:
        line += f"\n    ACTION: {item.action}"
    return line


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TAK AUTO Operator Control Center(읽기 전용).")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--scout-daily", type=Path, default=None)
    parser.add_argument("--knowledge", type=Path, default=None)
    parser.add_argument("--production-archive", type=Path, default=None)
    parser.add_argument("--threads-pending", type=Path, default=None)
    parser.add_argument("--performance", type=Path, default=None)
    parser.add_argument("--insights", type=Path, default=None)
    parser.add_argument("--shorts-scripts", type=Path, default=None)
    parser.add_argument("--blog-drafts", type=Path, default=None)
    parser.add_argument("--test-status", choices=("PASS", "FAIL", "UNKNOWN"), default="UNKNOWN", help="최근 테스트 실행 결과(이 CLI는 테스트를 직접 실행하지 않는다)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    data_dir = args.data_dir
    args.scout_daily = args.scout_daily or (data_dir / "tak_scout_daily.json")
    args.knowledge = args.knowledge or (data_dir / "tak_brain_knowledge.json")
    args.production_archive = args.production_archive or (data_dir / "tak_media_archive.json")
    args.threads_pending = args.threads_pending or (data_dir / "tak_threads_pending.json")
    args.performance = args.performance or (data_dir / "tak_performance.json")
    args.insights = args.insights or (data_dir / "tak_performance_insights.json")
    args.shorts_scripts = args.shorts_scripts or (data_dir / "shorts_scripts")
    args.blog_drafts = args.blog_drafts or (data_dir / "blog_drafts")

    inputs = _load_operator_inputs(args, args.test_status)
    summary = build_operator_summary(inputs)

    if args.json:
        print(json.dumps(summary.to_dict(), ensure_ascii=False, indent=2))
        return 0

    print("=== TAK AUTO Operator Control Center (읽기 전용) ===")
    print(f"generated_at: {summary.generated_at}")
    print(f"SYSTEM: {summary.system_status}\n")

    print("--- TODAY STATUS ---")
    print(_render_row(summary.git_status))
    print(_render_row(summary.test_status))

    print("\n--- PIPELINE STATUS ---")
    for item in summary.pipeline:
        print(_render_row(item))

    print("\n--- HUMAN ACTION ---")
    if not summary.human_actions:
        print("(없음)")
    for item in summary.human_actions:
        print(_render_row(item))

    print("\n--- BLOCKED / RISK ---")
    if not summary.blocked_items:
        print("(없음)")
    for item in summary.blocked_items:
        print(_render_row(item))

    print("\n--- PUBLISH STATUS ---")
    for item in summary.publish_status:
        print(_render_row(item))

    print("\n--- DATA HEALTH ---")
    for item in summary.data_health:
        print(_render_row(item))

    print("\n--- PERFORMANCE / INSIGHT ---")
    print(_render_row(summary.performance))
    print(_render_row(summary.insights))

    print("\n--- NEXT ACTION ---")
    if not summary.next_actions:
        print("(없음)")
    for index, action in enumerate(summary.next_actions, start=1):
        print(f"{index}. {action}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
