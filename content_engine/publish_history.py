"""Threads 게시 이력 저장과 미게시 콘텐츠 자동 선정.

TAK MEDIA 배치 결과(``MediaBatchItem``/배치 JSON)의 구조는 변경하지 않는다. 이 모듈은
배치 결과 항목(dict)에서 결정적(deterministic) 식별자를 계산하고, 그 식별자를 기준으로
"이미 게시한 콘텐츠"를 로컬 JSON 이력 파일에 기록·조회하는 책임만 가진다.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Any


DEFAULT_HISTORY_FILENAME = "threads_publish_log.json"


class PublishHistoryError(ValueError):
    """게시 이력 파일이 없거나 예상한 JSON 구조와 다를 때 발생한다."""


def compute_content_id(item: Mapping[str, Any]) -> str:
    """배치 결과 항목에서 안정적이고 결정적인 콘텐츠 식별자를 계산한다.

    knowledge_id, platform, source_url, evidence_unit_ids, original_title, original_body처럼
    같은 KNOWLEDGE로 배치를 다시 실행해도 값이 바뀌지 않는 필드만 사용한다. rewritten_title과
    rewritten_body는 LLM 호출마다 결과가 달라질 수 있으므로 식별자 계산에 사용하지 않는다.
    """
    evidence_unit_ids = item.get("evidence_unit_ids") or []
    if not isinstance(evidence_unit_ids, (list, tuple)):
        raise PublishHistoryError("evidence_unit_ids는 목록(list) 구조여야 합니다.")

    fingerprint_source = {
        "knowledge_id": str(item.get("knowledge_id") or ""),
        "platform": str(item.get("platform") or ""),
        "source_url": str(item.get("source_url") or ""),
        "evidence_unit_ids": [str(unit_id) for unit_id in evidence_unit_ids],
        "original_title": str(item.get("original_title") or ""),
        "original_body": str(item.get("original_body") or ""),
    }
    fingerprint = json.dumps(fingerprint_source, ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:16]
    return f"content-{digest}"


@dataclass(frozen=True)
class PublishRecord:
    """게시 이력 한 건. 실제 게시 성공 후에만 생성되어야 한다."""

    content_id: str
    published_at: str
    threads_post_id: str
    knowledge_id: str = ""
    platform: str = "threads"
    source_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "content_id": self.content_id,
            "published_at": self.published_at,
            "threads_post_id": self.threads_post_id,
            "knowledge_id": self.knowledge_id,
            "platform": self.platform,
            "source_url": self.source_url,
        }


class PublishHistory:
    """``data/threads_publish_log.json``에 게시 이력을 저장하고 조회하는 저장소."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def load(self) -> list[dict[str, Any]]:
        """이력 파일을 읽는다. 파일이 없거나 비어 있으면 빈 목록을 반환한다."""
        if not self.path.exists():
            return []
        raw_text = self.path.read_text(encoding="utf-8").strip()
        if not raw_text:
            return []
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError as error:
            raise PublishHistoryError(f"게시 이력 파일이 올바른 JSON이 아닙니다: {self.path}") from error
        if not isinstance(data, list) or not all(isinstance(record, dict) for record in data):
            raise PublishHistoryError(f"게시 이력 파일은 객체 목록(list) 구조여야 합니다: {self.path}")
        return data

    def published_content_ids(self) -> set[str]:
        return {
            record["content_id"]
            for record in self.load()
            if isinstance(record.get("content_id"), str) and record["content_id"]
        }

    def is_published(self, content_id: str) -> bool:
        return content_id in self.published_content_ids()

    def append(self, record: PublishRecord) -> None:
        """이력을 한 건 추가하고 파일에 원자적으로(atomic) 저장한다."""
        records = self.load()
        records.append(record.to_dict())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=self.path.parent, delete=False
        ) as handle:
            json.dump(records, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            temp_path = Path(handle.name)
        temp_path.replace(self.path)


def _used_knowledge_ids(history: PublishHistory) -> set[str]:
    """게시 이력에 한 번이라도 등장한 knowledge_id 집합을 반환한다.

    "최근 N일" 같은 시간 기반 쿨다운이 아니라, history 전체를 대상으로
    "이 KNOWLEDGE가 예전에 한 번이라도 게시된 적이 있는가"만 본다
    (5-10 Phase 4-4 rotation 정책의 기준).
    """
    return {
        str(record.get("knowledge_id") or "")
        for record in history.load()
        if isinstance(record.get("knowledge_id"), str) and record.get("knowledge_id")
    }


def select_unpublished_threads_item(
    items: Sequence[Mapping[str, Any]],
    history: PublishHistory,
) -> tuple[Mapping[str, Any], str] | None:
    """검증 통과(valid)한 Threads 콘텐츠 중 아직 게시하지 않은 항목 하나를 선택한다.

    - platform == "threads"
    - status == "valid"
    - 게시 이력에 없는 content_id

    위 조건을 모두 만족하는 후보들을 입력 순서(배치 결과의 기존 순서) 그대로 모은 뒤,
    같은 KNOWLEDGE가 연속으로 반복 게시되지 않도록 다음 우선순위로 하나를 고른다
    (5-10 Phase 4-4 - KNOWLEDGE 간 순환/rotation):

    1순위: knowledge_id가 게시 이력에 **한 번도 등장한 적 없는** 후보를, 후보 목록의
           원래 순서대로 가장 먼저 찾아 선택한다 - 아직 소개하지 않은 다른 KNOWLEDGE를
           우선한다.
    2순위(폴백): 그런 후보가 하나도 없다면(=순환할 새 KNOWLEDGE가 남아있지 않다면)
           기존과 동일하게, 후보 목록에서 가장 앞선 항목을 그대로 선택한다.

    이력에 없는 content_id만 후보가 된다는 기존 중복 방지 규칙, "최근 N일" 같은
    시간 기반 쿨다운, history 저장 방식은 전혀 바뀌지 않는다. 후보가 없으면
    ``None``을 반환한다.
    """
    published_ids = history.published_content_ids()
    candidates: list[tuple[Mapping[str, Any], str]] = []
    for item in items:
        if item.get("platform") != "threads" or item.get("status") != "valid":
            continue
        content_id = compute_content_id(item)
        if content_id in published_ids:
            continue
        candidates.append((item, content_id))

    if not candidates:
        return None

    used_knowledge_ids = _used_knowledge_ids(history)
    for item, content_id in candidates:
        if str(item.get("knowledge_id") or "") not in used_knowledge_ids:
            return item, content_id

    return candidates[0]
