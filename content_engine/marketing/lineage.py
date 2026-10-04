"""(content_id, generation_id) -> brief_id lineage 조회(6-82). 읽기 전용 순수 함수.

같은 content_id는 기존 배치 generation과 marketing generation이 공유할 수 있다(같은 콘텐츠 슬롯).
그래서 성과를 브리프에 귀속할 때는 content_id만이 아니라 generation_id까지 맞춰 본다.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from content_engine.media_archive import MediaArchiveRecord
from content_engine.performance.models import PerformanceRecord

from .models import MarketingBrief


def resolve_brief(briefs: Sequence[MarketingBrief], content_id: str, generation_id: str) -> str | None:
    """이 (content_id, generation_id)를 MEDIA로 넘긴 브리프 id. 없으면 None(예: 기존 배치 generation)."""
    for brief in briefs:
        if generation_id in brief.generation_ids_for(content_id):
            return brief.brief_id
    return None


def active_generation_ids(archive_records: Iterable[MediaArchiveRecord]) -> dict[str, str | None]:
    """production archive의 content_id별 활성 레코드 generation_id(content_id 단독 키 저장소)."""
    return {record.content_id: record.generation_id for record in archive_records}


def snapshot_generation_id(
    record: PerformanceRecord, active: Mapping[str, str | None] | None = None
) -> str | None:
    """성과 스냅샷이 어느 generation의 성과인가: 스냅샷의 generation_id, 없으면 production 활성 레코드의 값."""
    if record.generation_id:
        return record.generation_id
    if active is not None:
        return active.get(record.content_id)
    return None
