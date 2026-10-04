"""MarketingBrief 저장소(append-only 아님: 사람이 채우고 승인하므로 brief_id 기준 갱신 허용).

원자적 쓰기(tempfile + replace). 기존 KNOWLEDGE/성과/후속 후보 저장소는 건드리지 않는다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
import json
from pathlib import Path
import tempfile

from tak_brain.models import KnowledgeRecord

from .briefs import approval_blockers
from .editing import set_element
from .knowledge_links import check_knowledge_link, check_knowledge_unlink
from .suggestions import Suggestion, apply_suggestion, with_status as suggestion_with_status
from .models import (
    BRIEF_STATUSES, STATUS_APPROVED, STATUS_REJECTED, MarketingBrief, MarketingError, MediaGenerationRef,
)


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
    """상태 전이. approved는 승인 게이트를 통과해야 하고, rejected 브리프는 되살릴 수 없다."""
    if status not in BRIEF_STATUSES:
        raise MarketingError(f"알 수 없는 status: {status!r}")

    def apply(brief: MarketingBrief) -> MarketingBrief:
        if brief.status == STATUS_REJECTED and status != STATUS_REJECTED:
            raise MarketingError("rejected 브리프는 되살릴 수 없습니다. 새 브리프를 만드세요.")
        if status == STATUS_APPROVED:
            blockers = approval_blockers(brief)
            if blockers:
                raise MarketingError("승인 조건 미충족: " + " / ".join(blockers))
        return replace(brief, status=status)

    return _update(path, brief_id, apply)


def update_element(path: Path | str, brief_id: str, key: str, value: str) -> MarketingBrief:
    return _update(path, brief_id, lambda brief: set_element(brief, key, value))


def link_content(path: Path | str, brief_id: str, content_id: str) -> MarketingBrief:
    """브리프로 만든 콘텐츠를 연결한다(성과 귀속의 키)."""
    def apply(brief: MarketingBrief) -> MarketingBrief:
        if content_id in brief.content_ids:
            return brief
        return replace(brief, content_ids=brief.content_ids + (content_id,))
    return _update(path, brief_id, apply)


def link_media_generation(path: Path | str, brief_id: str, content_id: str, generation_id: str) -> MarketingBrief:
    """MEDIA pool로 넘긴 (content_id, generation_id)를 브리프에 기록한다(중복 없음). content_ids에도 연결한다."""
    ref = MediaGenerationRef(content_id, generation_id)

    def apply(brief: MarketingBrief) -> MarketingBrief:
        content_ids = brief.content_ids if content_id in brief.content_ids else brief.content_ids + (content_id,)
        refs = brief.media_generations if ref in brief.media_generations else brief.media_generations + (ref,)
        return replace(brief, content_ids=content_ids, media_generations=refs)
    return _update(path, brief_id, apply)


def link_knowledge(path: Path | str, brief_id: str, knowledge_id: str, records: Sequence[KnowledgeRecord]) -> MarketingBrief:
    """approved KNOWLEDGE를 브리프에 연결한다(knowledge_ids만 변경, 이미 연결되어 있으면 그대로)."""
    def apply(brief: MarketingBrief) -> MarketingBrief:
        check = check_knowledge_link(brief, knowledge_id, records)
        if check.blockers:
            raise MarketingError("KNOWLEDGE 연결 불가: " + " / ".join(check.blockers))
        if check.already_linked:
            return brief
        return replace(brief, knowledge_ids=brief.knowledge_ids + (knowledge_id,))
    return _update(path, brief_id, apply)


def unlink_knowledge(path: Path | str, brief_id: str, knowledge_id: str) -> MarketingBrief:
    """브리프에서 KNOWLEDGE 연결을 해제한다(knowledge_ids만 변경. status/content_ids/lineage는 그대로)."""
    def apply(brief: MarketingBrief) -> MarketingBrief:
        check = check_knowledge_unlink(brief, knowledge_id)
        if check.blockers:
            raise MarketingError("KNOWLEDGE 연결 해제 불가: " + " / ".join(check.blockers))
        return replace(brief, knowledge_ids=check.remaining)
    return _update(path, brief_id, apply)


# --- suggestion 저장소(브리프와 분리: 제안은 사람이 accept하기 전까지 브리프를 바꾸지 않는다) ---

def load_suggestions(path: Path | str) -> list[Suggestion]:
    return [Suggestion.from_dict(row) for row in _read(path)]


def append_suggestions(path: Path | str, suggestions: Sequence[Suggestion]) -> int:
    rows = _read(path)
    seen = {row.get("suggestion_id") for row in rows}
    new = [item for item in suggestions if item.suggestion_id not in seen]
    if new:
        _write(path, rows + [item.to_dict() for item in new])
    return len(new)


def resolve_suggestion(
    suggestions_path: Path | str, briefs_path: Path | str, suggestion_id: str, accept: bool
) -> Suggestion:
    """사람이 제안을 accept(브리프에 반영) 또는 reject한다. accept는 값이 비어 있는 요소에만 가능하다."""
    rows = _read(suggestions_path)
    for index, row in enumerate(rows):
        if row.get("suggestion_id") != suggestion_id:
            continue
        suggestion = Suggestion.from_dict(row)
        if suggestion.status != "suggested":
            raise MarketingError(f"이미 처리된 제안입니다: {suggestion.status}")
        if accept:
            _update(briefs_path, suggestion.brief_id, lambda brief: apply_suggestion(brief, suggestion))
        resolved = suggestion_with_status(suggestion, "accepted" if accept else "rejected")
        rows[index] = resolved.to_dict()
        _write(suggestions_path, rows)
        return resolved
    raise MarketingError(f"제안을 찾을 수 없습니다: {suggestion_id}")


def _update(path, brief_id, fn) -> MarketingBrief:
    rows = _read(path)
    for index, row in enumerate(rows):
        if row.get("brief_id") == brief_id:
            updated = fn(MarketingBrief.from_dict(row))
            rows[index] = updated.to_dict()
            _write(path, rows)
            return updated
    raise MarketingError(f"브리프를 찾을 수 없습니다: {brief_id}")
