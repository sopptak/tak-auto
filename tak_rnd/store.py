"""JSON persistence and lifecycle operations for R&D Radar and IDEA Vault."""

from __future__ import annotations

from dataclasses import replace
from difflib import SequenceMatcher
import json
from pathlib import Path
import tempfile
from typing import Any
from uuid import uuid4

from .models import IDEA_STATUSES, RND_STATUSES, Idea, RndItem, normalized_title, utc_now


DEFAULT_RND_PATH = Path(__file__).resolve().parents[1] / "data" / "tak_rnd_items.json"
DEFAULT_IDEA_PATH = Path(__file__).resolve().parents[1] / "data" / "tak_idea_vault.json"


class RndStoreError(ValueError):
    """Raised when an R&D or IDEA JSON store is malformed."""


def _load(path: Path | str, model: type[RndItem] | type[Idea]) -> list[Any]:
    target = Path(path)
    if not target.exists():
        return []
    text = target.read_text(encoding="utf-8").strip()
    if not text:
        return []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise RndStoreError(f"저장소 JSON이 올바르지 않습니다: {target}") from error
    if not isinstance(payload, list):
        raise RndStoreError(f"저장소 최상위 구조는 목록이어야 합니다: {target}")
    try:
        return [model.from_dict(item) for item in payload]
    except (TypeError, ValueError) as error:
        raise RndStoreError(f"저장소 레코드가 올바르지 않습니다: {target}: {error}") from error


def _save(records: list[RndItem] | list[Idea], path: Path | str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, delete=False) as handle:
        json.dump([record.to_dict() for record in records], handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temp_path = Path(handle.name)
    temp_path.replace(target)


def load_rnd_items(path: Path | str = DEFAULT_RND_PATH) -> list[RndItem]:
    return _load(path, RndItem)


def load_ideas(path: Path | str = DEFAULT_IDEA_PATH) -> list[Idea]:
    return _load(path, Idea)


def _find_rnd_duplicates(item: RndItem, existing: list[RndItem]) -> tuple[str, ...]:
    title = normalized_title(item.title)
    matches = []
    for candidate in existing:
        same_url = bool(item.canonical_url and item.canonical_url == candidate.canonical_url)
        same_source_item = bool(
            item.source_item_id
            and item.source == candidate.source
            and item.source_item_id == candidate.source_item_id
        )
        same_title = title == normalized_title(candidate.title)
        if same_url or same_source_item or same_title:
            matches.append(candidate.id)
    return tuple(matches)


def add_rnd_item(data: dict[str, Any] | RndItem, path: Path | str = DEFAULT_RND_PATH) -> RndItem:
    records = load_rnd_items(path)
    item = data if isinstance(data, RndItem) else RndItem.from_mapping(data)
    if any(record.id == item.id for record in records):
        if isinstance(data, RndItem) or data.get("id"):
            raise RndStoreError(f"이미 사용 중인 R&D ID입니다: {item.id}")
        item = replace(item, id=f"rnd-{uuid4().hex[:12]}")
    duplicates = _find_rnd_duplicates(item, records)
    if duplicates:
        item = replace(item, duplicate_candidate_ids=tuple(dict.fromkeys((*item.duplicate_candidate_ids, *duplicates))))
    records.append(item)
    _save(records, path)
    return item


def import_rnd_items(payload: Any, path: Path | str = DEFAULT_RND_PATH) -> tuple[list[RndItem], int]:
    """Import Aside/browser-agent JSON; keep possible duplicates as separate records."""
    if isinstance(payload, dict):
        payload = payload.get("items", [payload])
    if not isinstance(payload, list):
        raise RndStoreError("가져오기 JSON은 객체, 객체 목록 또는 {'items': [...]}여야 합니다.")
    records = load_rnd_items(path)
    imported: list[RndItem] = []
    duplicate_count = 0
    known_by_id = {record.id: record for record in records}
    for entry in payload:
        item = RndItem.from_mapping(entry)
        existing = known_by_id.get(item.id)
        if existing is not None:
            if (
                existing.source == item.source
                and existing.canonical_url == item.canonical_url
                and existing.source_item_id == item.source_item_id
                and normalized_title(existing.title) == normalized_title(item.title)
            ):
                duplicate_count += 1
                continue
            raise RndStoreError(f"이미 사용 중인 R&D ID가 다른 항목에 연결되어 있습니다: {item.id}")
        existing_source_item = next(
            (
                candidate
                for candidate in [*records, *imported]
                if item.source_item_id
                and candidate.source == item.source
                and candidate.source_item_id == item.source_item_id
            ),
            None,
        )
        if existing_source_item is not None:
            duplicate_count += 1
            continue
        duplicates = _find_rnd_duplicates(item, [*records, *imported])
        if duplicates:
            duplicate_count += 1
            item = replace(item, duplicate_candidate_ids=tuple(dict.fromkeys((*item.duplicate_candidate_ids, *duplicates))))
        imported.append(item)
        known_by_id[item.id] = item
    if imported:
        _save([*records, *imported], path)
    return imported, duplicate_count


def set_rnd_status(item_id: str, status: str, path: Path | str = DEFAULT_RND_PATH) -> RndItem:
    if status not in RND_STATUSES:
        raise RndStoreError(f"status는 {RND_STATUSES} 중 하나여야 합니다.")
    records = load_rnd_items(path)
    for index, item in enumerate(records):
        if item.id == item_id:
            updated = replace(item, status=status, last_updated_at=utc_now())
            records[index] = updated
            _save(records, path)
            return updated
    raise KeyError(f"R&D ID를 찾을 수 없습니다: {item_id}")


def set_rnd_canonical_id(
    duplicate_id: str, canonical_id: str, path: Path | str = DEFAULT_RND_PATH
) -> RndItem:
    records = load_rnd_items(path)
    if duplicate_id == canonical_id or not any(item.id == canonical_id for item in records):
        raise RndStoreError("canonical R&D ID가 없거나 duplicate ID와 같습니다.")
    for index, item in enumerate(records):
        if item.id == duplicate_id:
            updated = replace(item, canonical_id=canonical_id, last_updated_at=utc_now())
            records[index] = updated
            _save(records, path)
            return updated
    raise KeyError(f"R&D ID를 찾을 수 없습니다: {duplicate_id}")


def _find_idea_duplicates(idea: Idea, existing: list[Idea]) -> tuple[str, ...]:
    title = normalized_title(idea.title)
    source_ids = set(idea.source_rnd_ids)
    return tuple(
        item.id
        for item in existing
        if title == normalized_title(item.title)
        or SequenceMatcher(None, title, normalized_title(item.title)).ratio() >= 0.84
        or bool(source_ids.intersection(item.source_rnd_ids))
    )


def add_idea(data: dict[str, Any] | Idea, path: Path | str = DEFAULT_IDEA_PATH) -> Idea:
    records = load_ideas(path)
    idea = data if isinstance(data, Idea) else Idea.from_mapping(data)
    if any(record.id == idea.id for record in records):
        raise RndStoreError(f"이미 사용 중인 IDEA ID입니다: {idea.id}")
    duplicates = _find_idea_duplicates(idea, records)
    if duplicates:
        idea = replace(idea, duplicate_candidate_ids=tuple(dict.fromkeys((*idea.duplicate_candidate_ids, *duplicates))))
    records.append(idea)
    _save(records, path)
    return idea


def promote_rnd_to_idea(
    item_id: str,
    idea_data: dict[str, Any],
    rnd_path: Path | str = DEFAULT_RND_PATH,
    idea_path: Path | str = DEFAULT_IDEA_PATH,
) -> Idea:
    item = next((record for record in load_rnd_items(rnd_path) if record.id == item_id), None)
    if item is None:
        raise KeyError(f"R&D ID를 찾을 수 없습니다: {item_id}")
    source_ids = idea_data.get("source_rnd_ids", ())
    if isinstance(source_ids, str):
        source_ids = (source_ids,)
    payload = {**idea_data, "source_rnd_ids": tuple(dict.fromkeys((*source_ids, item.id)))}
    idea = add_idea(payload, idea_path)
    set_rnd_status(item.id, "promoted", rnd_path)
    return idea


def set_idea_status(idea_id: str, status: str, path: Path | str = DEFAULT_IDEA_PATH) -> Idea:
    if status not in IDEA_STATUSES:
        raise RndStoreError(f"status는 {IDEA_STATUSES} 중 하나여야 합니다.")
    records = load_ideas(path)
    for index, idea in enumerate(records):
        if idea.id == idea_id:
            updates: dict[str, Any] = {"status": status, "last_updated_at": utc_now()}
            if status == "validated":
                updates["needs_validation"] = False
            if status == "implemented" and idea.implemented_at is None:
                updates["implemented_at"] = utc_now()
            updated = replace(idea, **updates)
            records[index] = updated
            _save(records, path)
            return updated
    raise KeyError(f"IDEA ID를 찾을 수 없습니다: {idea_id}")


def set_idea_canonical_id(
    duplicate_id: str, canonical_id: str, path: Path | str = DEFAULT_IDEA_PATH
) -> Idea:
    records = load_ideas(path)
    if duplicate_id == canonical_id or not any(item.id == canonical_id for item in records):
        raise RndStoreError("canonical IDEA ID가 없거나 duplicate ID와 같습니다.")
    for index, idea in enumerate(records):
        if idea.id == duplicate_id:
            updated = replace(idea, canonical_id=canonical_id, last_updated_at=utc_now())
            records[index] = updated
            _save(records, path)
            return updated
    raise KeyError(f"IDEA ID를 찾을 수 없습니다: {duplicate_id}")


def priority_ideas(path: Path | str = DEFAULT_IDEA_PATH) -> list[Idea]:
    ideas = [
        idea for idea in load_ideas(path)
        if idea.priority_score is not None
        and idea.status not in {"implemented", "validated", "rejected", "parked"}
    ]
    return sorted(ideas, key=lambda idea: (-int(idea.priority_score or 0), idea.created_at, idea.id))


def validation_ideas(path: Path | str = DEFAULT_IDEA_PATH) -> list[Idea]:
    return [
        idea for idea in load_ideas(path)
        if idea.needs_validation and idea.status not in {"validated", "rejected", "parked"}
    ]