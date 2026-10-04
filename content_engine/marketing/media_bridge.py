"""Marketing 후보 -> 기존 MEDIA Generation Pool 브리지(docs/6-82).

기존 MEDIA 모듈을 수정하지 않는다. 후보를 기존 ``pipeline.MediaBatchItem``으로 옮기고 기존
``media_archive.archive_generation_report()``로 generation pool 파일에 쓴다. 이후 검토(``/media/generations``)와
승격(``scripts/promote_media_generation.py``)은 기존 흐름을 그대로 쓴다.

경계:
    - pool에는 항상 review_status="unreviewed"로 들어간다. 이 모듈은 승인/승격/발행을 하지 않는다.
    - ``rewrite_status="not_requested"`` 후보는 RewriteValidator를 거치지 않았으므로 bridge하지 않는다
      (generation_status="valid"로 위장하지 않는다).
    - pool 파일 이름은 ``tak_media_generation_*.json`` 규칙을 지켜 대시보드/export가 자동 발견한다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from content_engine.media_archive import archive_generation_report, new_generation_id
from content_engine.pipeline import MediaBatchItem, MediaBatchReport
from content_engine.publish_history import compute_content_id

from .generation import generation_blockers, media_platform
from .models import MarketingBrief, MarketingError
from .store import _read, _write

GENERATION_POOL_GLOB = "tak_media_generation_*.json"  # scripts/audit_data_state.py, run_scout_dashboard.py와 같은 규칙
POOL_PREFIX = "tak_media_generation_marketing-"
# rewrite_status -> MEDIA generation_status. not_requested는 의도적으로 없다.
GENERATION_STATUS_BY_REWRITE = {"rewritten": "valid", "rejected": "rejected", "error": "error"}


def load_candidates(contents_path: Path | str, brief_id: str | None = None) -> list[dict[str, Any]]:
    rows = _read(contents_path)
    return [row for row in rows if brief_id is None or row.get("brief_id") == brief_id]


def pool_path_for(data_dir: Path | str, brief_id: str) -> Path:
    path = Path(data_dir) / f"{POOL_PREFIX}{brief_id}.json"
    if not fnmatch(path.name, GENERATION_POOL_GLOB):
        raise MarketingError(f"generation pool 이름 규칙 위반: {path.name}")
    return path


def candidate_to_batch_item(candidate: dict[str, Any]) -> MediaBatchItem:
    """후보 1건을 기존 MediaBatchItem으로 옮긴다. MEDIA content_id가 후보의 content_id와 같아야 한다."""
    rewrite_status = candidate.get("rewrite_status")
    status = GENERATION_STATUS_BY_REWRITE.get(rewrite_status)
    if status is None:
        raise MarketingError(
            f"bridge할 수 없는 rewrite_status={rewrite_status!r}: 검증(RewriteValidator)을 거친 후보만 MEDIA로 넘깁니다. "
            "generate --rewrite mock|llm으로 다시 생성하세요."
        )
    item = MediaBatchItem(
        knowledge_id=candidate["knowledge_id"],
        platform=media_platform(candidate["platform"]),
        status=status,
        original_title=candidate["original_title"],
        original_body=candidate["original_body"],
        rewritten_title=candidate.get("rewritten_title"),
        rewritten_body=candidate.get("rewritten_body"),
        source_url=candidate["source_url"],
        evidence=tuple(candidate.get("evidence") or ()),
        evidence_unit_ids=tuple(candidate.get("evidence_unit_ids") or ()),
        created_at=candidate["created_at"],
        rejection_reasons=tuple(candidate.get("validation_errors") or ()),
        error_message=candidate.get("rewrite_error") or None,
    )
    if compute_content_id(item.to_dict()) != candidate["content_id"]:
        raise MarketingError(f"MEDIA content_id가 후보와 다릅니다: {candidate['content_id']}")
    return item


@dataclass(frozen=True)
class BridgePlan:
    brief_id: str
    items: tuple[MediaBatchItem, ...]
    content_ids: tuple[str, ...]
    skipped: tuple[str, ...]  # "content_id: 사유"


def plan_bridge(brief: MarketingBrief, candidates: Sequence[dict[str, Any]]) -> BridgePlan:
    """파일을 쓰지 않는 계획. 게이트가 막히면 MarketingError."""
    blockers = generation_blockers(brief)
    if blockers:
        raise MarketingError("bridge 차단: " + " / ".join(blockers))
    items, content_ids, skipped = [], [], []
    for candidate in candidates:
        if candidate.get("brief_id") != brief.brief_id:
            continue
        if candidate.get("generation_id"):
            skipped.append(f"{candidate['content_id']}: 이미 bridge됨(generation_id={candidate['generation_id']})")
            continue
        try:
            items.append(candidate_to_batch_item(candidate))
        except MarketingError as error:
            skipped.append(f"{candidate['content_id']}: {error}")
            continue
        content_ids.append(candidate["content_id"])
    return BridgePlan(brief.brief_id, tuple(items), tuple(content_ids), tuple(skipped))


@dataclass(frozen=True)
class BridgeResult:
    brief_id: str
    pool_path: Path
    generation_id: str
    refs: tuple[tuple[str, str], ...]  # (content_id, generation_id)
    skipped: tuple[str, ...]


def bridge_to_generation_pool(
    brief: MarketingBrief, candidates: Sequence[dict[str, Any]], pool_path: Path | str, generation_id: str | None = None
) -> BridgeResult:
    """계획한 후보를 하나의 generation으로 pool에 쓴다(unreviewed). 쓸 후보가 없으면 pool을 건드리지 않는다."""
    plan = plan_bridge(brief, candidates)
    pool_path = Path(pool_path)
    if not fnmatch(pool_path.name, GENERATION_POOL_GLOB):
        raise MarketingError(f"generation pool 이름 규칙 위반: {pool_path.name}")
    generation_id = generation_id or new_generation_id(brief.brief_id)
    if plan.items:
        statuses = [item.status for item in plan.items]
        report = MediaBatchReport(
            total_knowledge_count=len({item.knowledge_id for item in plan.items}),
            approved_knowledge_count=len({item.knowledge_id for item in plan.items}),
            skipped_knowledge_count=0, total_draft_count=len(plan.items),
            valid_count=statuses.count("valid"), rejected_count=statuses.count("rejected"),
            error_count=statuses.count("error"), items=plan.items,
        )
        archive_generation_report(report, pool_path, generation_id=generation_id)
    refs = tuple((content_id, generation_id) for content_id in plan.content_ids)
    return BridgeResult(brief.brief_id, pool_path, generation_id, refs, plan.skipped)


def mark_bridged(contents_path: Path | str, result: BridgeResult) -> int:
    """후보 저장소에 generation_id/pool 파일명을 기록한다(재실행 시 중복 bridge 방지). 갱신 건수 반환."""
    refs = dict(result.refs)
    rows = _read(contents_path)
    updated = 0
    for row in rows:
        if row.get("brief_id") == result.brief_id and row.get("content_id") in refs and not row.get("generation_id"):
            row["generation_id"] = refs[row["content_id"]]
            row["media_pool"] = result.pool_path.name
            updated += 1
    if updated:
        _write(contents_path, rows)
    return updated
