#!/usr/bin/env python3
"""10월 1일 실제 운영자가 아침에 가장 먼저 실행할, 파이프라인 단계별
현재 상태를 한 번에 보여주는 읽기 전용(read-only) CLI(6-33).

``scripts/audit_data_state.py``(6-21)는 "파일이 존재하고 유효한 JSON인가"를
파일 단위로 보여준다. 이 스크립트는 그것과 겹치지 않는다 - 대신 "SCOUT
후보가 몇 건인가, KNOWLEDGE pending이 몇 건인가, Generation Pool의 검수
현황은 어떤가, Production Archive의 Publish Readiness 요약은 어떤가"처럼
**파이프라인 단계별 숫자**를 보여준다. 이 스크립트도 어떤 파일을
생성/수정/삭제하지 않는다 - 기존 로더/요약 함수(``tak_brain.list_pending_knowledge``,
``scripts.run_scout_dashboard.discover_generation_pool_paths``/
``summarize_generation_reviews``, ``content_engine.publish_audit.audit_archive``/
``summarize``)를 그대로 재사용해서 조합만 한다. 새 판정 로직을 만들지 않는다.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_engine.media_archive import load_archive
from content_engine.publish_audit import PublishAuditInputs, audit_archive, summarize
from content_engine.threads_review import load_pending
from scripts.run_scout_dashboard import discover_generation_pool_paths, summarize_generation_reviews
from tak_brain import list_pending_knowledge, load_knowledge_records
from tak_scout.collector import load_daily_pack


def _scout_status(scout_daily_path: Path) -> str:
    if not scout_daily_path.exists():
        return "없음(아직 오늘 SCOUT를 실행하지 않았습니다) -> python scripts/run_scout.py"
    try:
        candidates = load_daily_pack(scout_daily_path)
    except (ValueError, OSError) as error:
        return f"오류: {error}"
    return f"{len(candidates)}건 수집됨"


def _knowledge_status(knowledge_path: Path) -> str:
    if not knowledge_path.exists():
        return "없음(아직 KNOWLEDGE 파일이 없습니다)"
    try:
        pending = list_pending_knowledge(knowledge_path)
    except (ValueError, OSError) as error:
        return f"오류: {error}"
    if not pending:
        return "pending 없음(승인 대기 없음)"
    return f"pending {len(pending)}건 -> python scripts/review_knowledge.py --pending"


def _generation_pool_status(data_dir: Path) -> str:
    paths = discover_generation_pool_paths(data_dir)
    if not paths:
        return "없음(아직 MEDIA generation이 없습니다)"
    records = [record for path in paths for record in load_archive(path)]
    summary = summarize_generation_reviews(records)
    return (
        f"{summary['total']}건(valid {summary['valid']}/rejected {summary['rejected']}/"
        f"error {summary['error']}) - review: approved {summary['approved']}/"
        f"unreviewed {summary['unreviewed']}/dismissed {summary['dismissed']}"
    )


def _production_archive_status(archive_path: Path, knowledge_path: Path) -> str:
    if not archive_path.exists():
        return "없음(아직 Production Archive가 없습니다 - 정상, 빈 archive를 임의로 만들지 마세요)"
    records = load_archive(archive_path)
    if not records:
        return "0건(파일은 있지만 레코드 없음)"
    knowledge_by_id = {}
    if knowledge_path.exists():
        try:
            knowledge_by_id = {r.id: r for r in load_knowledge_records(knowledge_path)}
        except (ValueError, OSError):
            knowledge_by_id = {}
    results = audit_archive(records, inputs=PublishAuditInputs(knowledge_by_id=knowledge_by_id))
    counts = summarize(results)
    parts = ", ".join(f"{status} {count}" for status, count in counts.items() if count)
    return parts or "0건"


def _threads_pending_status(pending_path: Path) -> str:
    drafts = load_pending(pending_path)
    if not drafts:
        return "없음"
    by_status: dict[str, int] = {}
    for draft in drafts:
        by_status[draft.status] = by_status.get(draft.status, 0) + 1
    return ", ".join(f"{status} {count}" for status, count in sorted(by_status.items()))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "10월 1일 파이프라인 단계별 현재 상태를 한 번에 보여주는 읽기 전용 CLI. "
            "어떤 파일도 생성/수정하지 않는다."
        )
    )
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--scout-daily", type=Path, default=None)
    parser.add_argument("--knowledge", type=Path, default=None)
    parser.add_argument("--production-archive", type=Path, default=None)
    parser.add_argument("--threads-pending", type=Path, default=None)
    args = parser.parse_args(argv)

    data_dir = args.data_dir
    scout_daily_path = args.scout_daily or (data_dir / "tak_scout_daily.json")
    knowledge_path = args.knowledge or (data_dir / "tak_brain_knowledge.json")
    archive_path = args.production_archive or (data_dir / "tak_media_archive.json")
    threads_pending_path = args.threads_pending or (data_dir / "tak_threads_pending.json")

    print("=== TAK AUTO 운영 현재 상태 (읽기 전용) ===")
    print(f"데이터 디렉터리: {data_dir}")
    print()
    print(f"1. SCOUT: {_scout_status(scout_daily_path)}")
    print(f"2. KNOWLEDGE: {_knowledge_status(knowledge_path)}")
    print(f"3. MEDIA / Generation Pool: {_generation_pool_status(data_dir)}")
    print(f"4. Production Archive / Publish Readiness: {_production_archive_status(archive_path, knowledge_path)}")
    print(f"5. Threads pending: {_threads_pending_status(threads_pending_path)}")
    print()
    print("YouTube: BLOCKED(Shorts Renderer 없음, docs/6-30 참고)")
    print("Blog: Publish Pack + 사람이 직접 Naver에 게시(자동 게시 없음)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
