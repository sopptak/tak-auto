"""MarketingBrief 저장소(append-only 아님: 사람이 채우고 승인하므로 brief_id 기준 갱신 허용).

원자적 쓰기(tempfile + replace). 기존 KNOWLEDGE/성과/후속 후보 저장소는 건드리지 않는다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
import json
from pathlib import Path
import tempfile

from .models import BRIEF_STATUSES, MarketingBrief, MarketingError


def _read(path: Path | str) -> list[dict]:
    target = Path(path)
    if not target.exists():
        return []
    data = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        raise MarketingError(f"{target.name}은(는) 객체 목록이어야 합니다.")
    return data


def _write(path: Path | str, rows: list[dict]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, delete=False, suffix=".tmp") as handle:
        handle.write(json.dumps(rows, ensure_ascii=False, indent=2) + "\n")
        temp = Path(handle.name)
    temp.replace(target)


def load_briefs(path: Path | str) -> list[MarketingBrief]:
    return [MarketingBrief.from_dict(row) for row in _read(path)]


def append_briefs(path: Path | str, briefs: Sequence[MarketingBrief]) -> int:
    """없는 brief_id만 추가한다(이미 사람이 편집한 브리프를 덮어쓰지 않는다)."""
    rows = _read(path)
    seen = {row.get("brief_id") for row in rows}
    new = [brief for brief in briefs if brief.brief_id not in seen]
    if new:
        _write(path, rows + [brief.to_dict() for brief in new])
    return len(new)


def set_brief_status(path: Path | str, brief_id: str, status: str) -> MarketingBrief:
    if status not in BRIEF_STATUSES:
        raise MarketingError(f"알 수 없는 status: {status!r}")
    return _update(path, brief_id, lambda brief: replace(brief, status=status))


def link_content(path: Path | str, brief_id: str, content_id: str) -> MarketingBrief:
    """브리프로 만든 콘텐츠를 연결한다(성과 귀속의 키)."""
    def apply(brief: MarketingBrief) -> MarketingBrief:
        if content_id in brief.content_ids:
            return brief
        return replace(brief, content_ids=brief.content_ids + (content_id,))
    return _update(path, brief_id, apply)


def _update(path, brief_id, fn) -> MarketingBrief:
    rows = _read(path)
    for index, row in enumerate(rows):
        if row.get("brief_id") == brief_id:
            updated = fn(MarketingBrief.from_dict(row))
            rows[index] = updated.to_dict()
            _write(path, rows)
            return updated
    raise MarketingError(f"브리프를 찾을 수 없습니다: {brief_id}")
