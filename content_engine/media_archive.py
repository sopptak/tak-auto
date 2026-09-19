"""TAK MEDIA 배치 결과 전체("모든 생성 결과") 영구 저장 아카이브.

5-27 설계 문서(docs/5-27_media_draft_persistence_investigation.md)의 설계안 구현.

기존 채널별 저장소(``content_engine/threads_review.py``의 Threads 검수 대기열,
``content_engine/blog_publish_pack.py``의 Blog 게시 후보)는 전부 "검증 통과(valid)한
것 중 일부"만 저장한다. 이 모듈은 그 앞단에서, ``run_media_batch()``가 만든
``MediaBatchReport``의 **모든** 항목(valid + rejected + error)을 하나도 버리지 않고
저장하는 역할만 가진다 - 실제 채널별 검수/발행 로직은 전혀 재구현하지 않는다.

저장 방식은 ``content_engine/threads_review.py``와 완전히 동일한 관례를 따른다:
JSON 배열 파일, 파일이 없거나 비어 있으면 빈 목록, ``tempfile`` + ``Path.replace()``로
원자적(atomic) 저장, ``content_id`` 기준 upsert.

``content_id``는 ``content_engine.publish_history.compute_content_id()``를 그대로
재사용한다 - 이 모듈은 식별자를 새로 계산하지 않는다.

이 모듈이 다루는 상태는 두 가지로 명확히 분리된다:
    - ``generation_status``: TAK MEDIA 배치/검증 단계의 결과(``valid``/``rejected``/
      ``error``). ``MediaBatchItem.status``를 그대로 옮겨온 것이며, 이 모듈이 판단을
      새로 내리지 않는다.
    - ``review_status``: 사람이 Dashboard에서 이 항목을 검토했는지 여부
      (``unreviewed``/``approved``/``dismissed``). 신규 항목은 항상 ``unreviewed``로
      시작하고, 이미 존재하는 항목을 다시 upsert할 때는 이전 ``review_status``를
      그대로 보존한다(재실행했다고 사람의 검토 상태가 초기화되면 안 된다).
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import tempfile
from typing import Any

from .pipeline import MediaBatchItem, MediaBatchReport
from .publish_history import compute_content_id


GENERATION_STATUSES = ("valid", "rejected", "error")
REVIEW_STATUSES = ("unreviewed", "approved", "dismissed")


class MediaArchiveError(ValueError):
    """아카이브 파일 구조가 올바르지 않을 때 발생한다."""


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


@dataclass(frozen=True)
class MediaArchiveRecord:
    """TAK MEDIA가 생성한 Draft 1건의 아카이브 레코드.

    ``content_id``는 ``compute_content_id()``가 계산한 값을 그대로 받아 저장할 뿐,
    이 클래스는 content_id를 계산하지 않는다(``archive_report()``가 계산해 넘긴다).
    """

    content_id: str
    knowledge_id: str
    platform: str
    generation_status: str
    original_title: str
    original_body: str
    rewritten_title: str | None
    rewritten_body: str | None
    source_url: str
    evidence: tuple[str, ...]
    evidence_unit_ids: tuple[str, ...]
    created_at: str
    validation_errors: tuple[str, ...] = ()
    error_message: str | None = None
    review_status: str = "unreviewed"
    # 5-29: 사람이 MEDIA Dashboard에서 직접 고친 최종 제목/본문. original_*(생성 전
    # 원본 draft)과 rewritten_*(AI 생성 결과)는 사람이 무엇을 하든 절대 덮어쓰지
    # 않는다 - edited_*는 이 두 값과 별도로 존재하는 "사람이 만든 세 번째 버전"이다.
    # 사람이 아직 수정하지 않았으면 None으로 남는다(빈 문자열이 아니라 None - "수정한
    # 적 없음"과 "빈 문자열로 수정함"을 구분하기 위함).
    edited_title: str | None = None
    edited_body: str | None = None

    def __post_init__(self) -> None:
        if not self.content_id:
            raise MediaArchiveError("content_id가 필요합니다.")
        if not self.knowledge_id:
            raise MediaArchiveError("knowledge_id가 필요합니다.")
        if self.generation_status not in GENERATION_STATUSES:
            raise MediaArchiveError(
                f"generation_status는 {GENERATION_STATUSES} 중 하나여야 합니다: {self.generation_status!r}"
            )
        if self.review_status not in REVIEW_STATUSES:
            raise MediaArchiveError(
                f"review_status는 {REVIEW_STATUSES} 중 하나여야 합니다: {self.review_status!r}"
            )

    @property
    def final_title(self) -> str:
        """downstream(Blog Pack/Shorts 변환/Threads pending)에 넘길 최종 제목.

        우선순위: 사람이 수정한 edited_title -> AI 생성 rewritten_title ->
        원본 original_title. edited_title/rewritten_title 자체는 이 프로퍼티가
        수정하지 않고 그대로 보존된다 - 여기서는 "무엇을 쓸지" 고르기만 한다.
        """
        if self.edited_title:
            return self.edited_title
        return self.rewritten_title or self.original_title

    @property
    def final_body(self) -> str:
        """final_title과 동일한 우선순위 규칙을 본문에 적용한다."""
        if self.edited_body:
            return self.edited_body
        return self.rewritten_body or self.original_body

    def to_dict(self) -> dict[str, Any]:
        return {
            "content_id": self.content_id,
            "knowledge_id": self.knowledge_id,
            "platform": self.platform,
            "generation_status": self.generation_status,
            "original_title": self.original_title,
            "original_body": self.original_body,
            "rewritten_title": self.rewritten_title,
            "rewritten_body": self.rewritten_body,
            "source_url": self.source_url,
            "evidence": list(self.evidence),
            "evidence_unit_ids": list(self.evidence_unit_ids),
            "created_at": self.created_at,
            "validation_errors": list(self.validation_errors),
            "error_message": self.error_message,
            "review_status": self.review_status,
            "edited_title": self.edited_title,
            "edited_body": self.edited_body,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MediaArchiveRecord":
        if not isinstance(data, dict):
            raise MediaArchiveError("아카이브 항목은 객체(dict)여야 합니다.")

        evidence = data.get("evidence") or []
        if not isinstance(evidence, (list, tuple)):
            raise MediaArchiveError("evidence는 목록(list) 구조여야 합니다.")

        evidence_unit_ids = data.get("evidence_unit_ids") or []
        if not isinstance(evidence_unit_ids, (list, tuple)):
            raise MediaArchiveError("evidence_unit_ids는 목록(list) 구조여야 합니다.")

        validation_errors = data.get("validation_errors") or []
        if not isinstance(validation_errors, (list, tuple)):
            raise MediaArchiveError("validation_errors는 목록(list) 구조여야 합니다.")

        return cls(
            content_id=str(data.get("content_id") or ""),
            knowledge_id=str(data.get("knowledge_id") or ""),
            platform=str(data.get("platform") or ""),
            generation_status=str(data.get("generation_status") or ""),
            original_title=str(data.get("original_title") or ""),
            original_body=str(data.get("original_body") or ""),
            rewritten_title=_optional_str(data.get("rewritten_title")),
            rewritten_body=_optional_str(data.get("rewritten_body")),
            source_url=str(data.get("source_url") or ""),
            evidence=tuple(str(value) for value in evidence),
            evidence_unit_ids=tuple(str(value) for value in evidence_unit_ids),
            created_at=str(data.get("created_at") or ""),
            validation_errors=tuple(str(value) for value in validation_errors),
            error_message=_optional_str(data.get("error_message")),
            review_status=str(data.get("review_status") or "unreviewed"),
            edited_title=_optional_str(data.get("edited_title")),
            edited_body=_optional_str(data.get("edited_body")),
        )

    @classmethod
    def from_item(
        cls,
        item: MediaBatchItem,
        review_status: str = "unreviewed",
        edited_title: str | None = None,
        edited_body: str | None = None,
    ) -> "MediaArchiveRecord":
        """``MediaBatchItem`` 1건에서 아카이브 레코드를 만든다. content_id는 이 함수가
        ``compute_content_id()``로 직접 계산한다(같은 KNOWLEDGE/플랫폼/원본 텍스트를
        재실행해도 값이 바뀌지 않는다 - rewritten 텍스트는 지문 계산에 쓰이지 않는다).

        ``edited_title``/``edited_body``는 이 함수가 스스로 채우지 않는다 - 재실행
        시 사람이 이미 남긴 수정 내용을 그대로 이어가고 싶다면 호출부(archive_report)가
        기존 레코드에서 읽어와 명시적으로 넘겨야 한다.
        """
        return cls(
            content_id=compute_content_id(item.to_dict()),
            knowledge_id=item.knowledge_id,
            platform=item.platform,
            generation_status=item.status,
            original_title=item.original_title,
            original_body=item.original_body,
            rewritten_title=item.rewritten_title,
            rewritten_body=item.rewritten_body,
            source_url=item.source_url,
            evidence=tuple(item.evidence),
            evidence_unit_ids=tuple(item.evidence_unit_ids),
            created_at=item.created_at,
            validation_errors=tuple(item.rejection_reasons),
            error_message=item.error_message,
            review_status=review_status,
            edited_title=edited_title,
            edited_body=edited_body,
        )


def load_archive(path: Path | str) -> list[MediaArchiveRecord]:
    """아카이브 파일을 읽는다. 파일이 없거나 비어 있으면 빈 목록을 반환한다."""
    target = Path(path)
    if not target.exists():
        return []
    raw_text = target.read_text(encoding="utf-8").strip()
    if not raw_text:
        return []
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as error:
        raise MediaArchiveError(f"아카이브 파일이 올바른 JSON이 아닙니다: {target}") from error
    if not isinstance(data, list):
        raise MediaArchiveError(f"아카이브 파일은 객체 목록(list) 구조여야 합니다: {target}")
    return [MediaArchiveRecord.from_dict(item) for item in data]


def save_archive(records: list[MediaArchiveRecord], path: Path | str) -> None:
    """레코드 목록을 원자적으로(tempfile + replace) 저장한다."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = [record.to_dict() for record in records]
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temp_path = Path(handle.name)
    temp_path.replace(target)


def upsert_archive(path: Path | str, records: list[MediaArchiveRecord]) -> list[MediaArchiveRecord]:
    """같은 content_id의 기존 레코드는 덮어쓰고, 새 content_id는 추가한다.

    ``threads_review.upsert_pending()``과 동일한 upsert 관례(마지막에 넘긴 값이
    이긴다)를 따른다.
    """
    by_content_id = {existing.content_id: existing for existing in load_archive(path)}
    for record in records:
        by_content_id[record.content_id] = record
    result = list(by_content_id.values())
    save_archive(result, path)
    return result


def archive_report(report: MediaBatchReport, path: Path | str) -> list[MediaArchiveRecord]:
    """``MediaBatchReport``의 모든 항목(valid + rejected + error)을 아카이브에 upsert한다.

    이미 아카이브에 있던 content_id라면, 사람이 이미 매긴 ``review_status``와
    사람이 이미 남긴 ``edited_title``/``edited_body``를 그대로 보존한 채
    생성/검증 결과(rewritten_*, validation_errors 등)만 최신값으로 갱신한다 -
    재실행이 사람의 검토 상태나 수정 내용을 되돌리지 않는다.
    """
    existing_by_content_id = {existing.content_id: existing for existing in load_archive(path)}

    new_records: list[MediaArchiveRecord] = []
    for item in report.items:
        content_id = compute_content_id(item.to_dict())
        prior = existing_by_content_id.get(content_id)
        review_status = prior.review_status if prior is not None else "unreviewed"
        edited_title = prior.edited_title if prior is not None else None
        edited_body = prior.edited_body if prior is not None else None
        new_records.append(
            MediaArchiveRecord.from_item(
                item, review_status=review_status, edited_title=edited_title, edited_body=edited_body
            )
        )

    return upsert_archive(path, new_records)
