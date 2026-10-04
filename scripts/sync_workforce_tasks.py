#!/usr/bin/env python3
"""Sync the P2-02 AI Workforce task board with the real content pipeline.

This CLI reuses the exact same loaders as ``scripts/operator_control_center.py``
(KNOWLEDGE, MEDIA generation pool, Production Archive) and
``scripts/collect_performance.py`` (Threads performance due-schedule) to
read the pipeline's current state, then calls
``content_engine.workforce_bridge.sync_pipeline_tasks()`` to create/refresh
``tak_workforce`` Task records for whatever still needs attention.

It never writes to any content-pipeline file (KNOWLEDGE/MEDIA/PERFORMANCE
are read-only here) and never approves/promotes/publishes anything - it
only writes to ``data/tak_ai_tasks.json`` (the AI Workforce task store).

Usage:
    python3 -m scripts.sync_workforce_tasks
    python3 -m scripts.sync_workforce_tasks --data-dir data --tasks data/tak_ai_tasks.json
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_engine.data_state import NOT_PRESENT, json_file_status
from content_engine.media_archive import load_archive
from content_engine.performance.schedule import select_due_threads_targets
from content_engine.performance.store import load_snapshots
from content_engine.publish_history import PublishHistory
from content_engine.threads_review import load_pending
from content_engine.workforce_bridge import sync_pipeline_tasks
from scripts.run_scout_dashboard import discover_generation_pool_paths
from tak_brain import load_knowledge_records
from tak_workforce.tasks import DEFAULT_TASK_PATH


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--knowledge", type=Path, default=None)
    parser.add_argument("--production-archive", type=Path, default=None)
    parser.add_argument("--threads-pending", type=Path, default=None)
    parser.add_argument("--performance", type=Path, default=None)
    parser.add_argument("--publish-history", type=Path, default=None)
    parser.add_argument("--tasks", type=Path, default=DEFAULT_TASK_PATH, help="tak_workforce Task 저장소 경로")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    data_dir: Path = args.data_dir
    knowledge_path = args.knowledge or (data_dir / "tak_brain_knowledge.json")
    production_path = args.production_archive or (data_dir / "tak_media_archive.json")
    threads_pending_path = args.threads_pending or (data_dir / "tak_threads_pending.json")
    performance_path = args.performance or (data_dir / "tak_performance.json")
    publish_history_path = args.publish_history or (data_dir / "threads_publish_log.json")

    knowledge_records = ()
    if json_file_status(knowledge_path)[0] != NOT_PRESENT:
        try:
            knowledge_records = tuple(load_knowledge_records(knowledge_path))
        except (ValueError, OSError) as error:
            print(f"경고: KNOWLEDGE를 읽을 수 없어 건너뜁니다: {error}", file=sys.stderr)

    generation_pool_records = tuple(
        record for path in discover_generation_pool_paths(data_dir) for record in load_archive(path)
    )

    production_records = ()
    if json_file_status(production_path)[0] != NOT_PRESENT:
        try:
            production_records = tuple(load_archive(production_path))
        except (ValueError, OSError) as error:
            print(f"경고: Production Archive를 읽을 수 없어 건너뜁니다: {error}", file=sys.stderr)

    performance_due_content_ids: tuple[str, ...] = ()
    try:
        history_records = PublishHistory(publish_history_path).load()
        pending_drafts = load_pending(threads_pending_path)
        performance_records = load_snapshots(performance_path)
        targets = select_due_threads_targets(
            history_records,
            list(production_records),
            pending_drafts,
            performance_records,
            now=datetime.now(timezone.utc),
        )
        performance_due_content_ids = tuple(target.content_id for target in targets)
    except (OSError, ValueError) as error:
        print(f"경고: 성과 측정 due target을 계산할 수 없어 건너뜁니다: {error}", file=sys.stderr)

    result = sync_pipeline_tasks(
        knowledge_records=knowledge_records,
        generation_pool_records=generation_pool_records,
        production_records=production_records,
        performance_due_content_ids=performance_due_content_ids,
        path=args.tasks,
    )

    print(f"생성된 task: {len(result.created_task_ids)}건")
    for task_id in result.created_task_ids:
        print(f"  + {task_id}")
    print(f"이미 열려있는 task라서 건너뜀: {len(result.skipped_existing_refs)}건")
    print(f"이미 해당 단계를 지나서 건너뜀: {len(result.skipped_terminal_refs)}건")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
