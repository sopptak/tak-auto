"""Select due Threads performance windows from existing publishing records."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from content_engine.media_archive import MediaArchiveRecord
from content_engine.threads_review import ThreadsPendingDraft

from .models import PerformanceRecord


WINDOW_24H = "24h"
WINDOW_72H = "72h"


@dataclass(frozen=True)
class ScheduledPerformanceTarget:
    content_id: str
    knowledge_id: str
    generation_id: str
    external_post_id: str
    published_at: str
    measurement_window: str
    title: str


def _parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def select_due_threads_targets(
    publish_records: Sequence[Mapping[str, Any]],
    production_records: Sequence[MediaArchiveRecord],
    pending_drafts: Sequence[ThreadsPendingDraft],
    performance_records: Sequence[PerformanceRecord],
    *,
    now: datetime,
) -> tuple[ScheduledPerformanceTarget, ...]:
    """Return due 24h/72h targets whose publish lineage is unambiguous and valid.

    The latest reached milestone is selected. If the 24h run was missed and the
    post has already reached 72h, the current value is never mislabeled as 24h.
    """
    current_time = now.astimezone(timezone.utc) if now.tzinfo else now.replace(tzinfo=timezone.utc)

    histories_by_content: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for history in publish_records:
        content_id = str(history.get("content_id") or "")
        if content_id and history.get("platform") == "threads":
            histories_by_content[content_id].append(history)

    production_by_content: dict[str, list[MediaArchiveRecord]] = defaultdict(list)
    for record in production_records:
        production_by_content[record.content_id].append(record)

    pending_by_content: dict[str, list[ThreadsPendingDraft]] = defaultdict(list)
    for draft in pending_drafts:
        pending_by_content[draft.content_id].append(draft)

    collected_windows = {
        (record.content_id, record.external_id, record.measurement_window)
        for record in performance_records
        if record.platform == "threads" and record.measurement_window in (WINDOW_24H, WINDOW_72H)
    }

    targets: list[ScheduledPerformanceTarget] = []
    for content_id, matching_history in histories_by_content.items():
        if len(matching_history) != 1:
            continue
        history = matching_history[0]
        knowledge_id = str(history.get("knowledge_id") or "")
        post_id = str(history.get("threads_post_id") or "")
        history_published_at = str(history.get("published_at") or "")
        published_time = _parse_timestamp(history_published_at)
        if not knowledge_id or not post_id or published_time is None:
            continue

        matching_production = production_by_content.get(content_id, [])
        if len(matching_production) != 1:
            continue
        production = matching_production[0]
        if (
            production.platform != "threads"
            or production.knowledge_id != knowledge_id
            or production.generation_status != "valid"
            or production.review_status != "approved"
            or production.superseded_by
            or not production.generation_id
        ):
            continue

        matching_pending = pending_by_content.get(content_id, [])
        if len(matching_pending) != 1:
            continue
        pending = matching_pending[0]
        pending_published_at = _parse_timestamp(pending.published_at or "")
        if (
            pending.status != "published"
            or pending.knowledge_id != knowledge_id
            or pending.threads_post_id != post_id
            or pending_published_at != published_time
            or (production.source_url and pending.source_url != production.source_url)
            or (history.get("source_url") and history.get("source_url") != production.source_url)
        ):
            continue

        elapsed = current_time - published_time
        if elapsed < timedelta(hours=24):
            continue
        window = WINDOW_72H if elapsed >= timedelta(hours=72) else WINDOW_24H
        if (content_id, post_id, window) in collected_windows:
            continue

        targets.append(
            ScheduledPerformanceTarget(
                content_id=content_id,
                knowledge_id=knowledge_id,
                generation_id=production.generation_id,
                external_post_id=post_id,
                published_at=history_published_at,
                measurement_window=window,
                title=production.final_title,
            )
        )

    return tuple(sorted(targets, key=lambda target: (target.published_at, target.content_id)))
