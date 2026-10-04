#!/usr/bin/env python3
"""성과/발행 이력에서 후속·재활용 콘텐츠 후보를 만든다(기본은 미리보기, --write로 저장).

콘텐츠를 생성하거나 발행하지 않는다. 입력 파일은 읽기만 한다.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_engine.followup import append_candidates, build_followup_candidates, load_candidates, set_candidate_status, STATUSES
from content_engine.performance.store import latest_snapshot_per_content
from tak_brain.knowledge import load_knowledge_records

DATA = ROOT / "data"


def _load_list(path: Path) -> list:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DATA)
    parser.add_argument("--write", action="store_true", help="후보를 data/tak_followup_candidates.json에 append한다.")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--set-status", nargs=2, metavar=("CANDIDATE_ID", "STATUS"), help=f"후보 상태 변경 {STATUSES}")
    args = parser.parse_args(argv)
    store = args.data_dir / "tak_followup_candidates.json"

    if args.set_status:
        updated = set_candidate_status(store, args.set_status[0], args.set_status[1])
        print(f"{updated.candidate_id}: {updated.status}")
        return 0

    knowledge_path = args.data_dir / "tak_brain_knowledge.json"
    knowledge = load_knowledge_records(knowledge_path) if knowledge_path.exists() else []
    perf_path = args.data_dir / "tak_performance.json"
    performance = latest_snapshot_per_content(perf_path) if perf_path.exists() else {}
    candidates = build_followup_candidates(
        knowledge,
        publish_logs=_load_list(args.data_dir / "threads_publish_log.json"),
        archive_records=_load_list(args.data_dir / "tak_media_archive.json"),
        latest_performance=performance,
    )
    print(f"후속 후보 {len(candidates)}건 (미리보기 상위 {args.limit})")
    for item in candidates[: args.limit]:
        print(f"- [{item.priority}] {item.kind}->{item.target_platform} ({item.search_intent}) {item.title} :: {item.reason}")
    if args.write:
        added = append_candidates(store, candidates)
        print(f"저장: 신규 {added}건, 누적 {len(load_candidates(store))}건 -> {store}")
    else:
        print("저장하지 않음(--write 필요).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
