"""Threads "생성 -> 사람 검수 -> 발행" 흐름의 검수 대기(pending) draft 저장소.

5-11 설계 문서(docs/5-11_threads_human_review_design.md) Phase 1 구현.

이 모듈은 ``content_engine/publish_history.py``의 ``PublishHistory``/``PublishRecord``와
완전히 별도의 데이터 구조를 담당한다 - ``PublishHistory``는 "실제 게시에 성공한
콘텐츠만 기록하는 append-only 로그"이고(이 모듈은 그 파일이나 클래스를 전혀 건드리지
않는다), 이 모듈은 "아직 발행 전, 사람의 확인이 필요한 단계"의 상태만 다룬다(5-11
설계 8장). 두 구조는 오직 ``content_id``(``compute_content_id()``가 계산한 값을
그대로 재사용)로만 서로 대응된다 - 이 모듈은 content_id를 새로 계산하지 않는다.

저장 방식은 기존 ``PublishHistory``/``tak_scout.interview_session``과 동일한 관례를
따른다: JSON 배열 파일, 파일이 없거나 비어 있으면 빈 목록, ``tempfile`` +
``Path.replace()``로 원자적(atomic) 저장.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path
import tempfile
from typing import Any


VALID_STATUSES = ("pending", "approved", "published", "failed")

# "아직 발행되지 않은" 상태 - generate_threads_draft.py의 idempotency 판단 기준
# (5-11 설계 5장). published/failed는 미해결 상태로 취급하지 않는다: published는
# 종결 상태이고, failed는 사람이 다시 승인하기 전까지는 "처리 완료(실패)"로 본다 -
# 그래도 새 초안을 또 만들지는 않는다(failed 항목이 이미 존재한다는 사실 자체가
# "오늘의 검토 대상이 이미 있다"는 의미이므로, 자동 생성이 그걸 무시하고 새 draft를
# 더 만들면 검토 대기열이 통제 없이 계속 늘어난다).
UNRESOLVED_STATUSES = ("pending", "approved")

# 상태 전이 허용 목록. published는 종결 상태라 더 이상 전이가 없다.
_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"approved"}),
    "approved": frozenset({"published", "failed"}),
    "failed": frozenset({"approved"}),
    "published": frozenset(),
}


class ThreadsPendingError(ValueError):
    """pending draft 구조가 올바르지 않거나, 허용되지 않는 상태 전이를 시도할 때 발생한다."""


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


@dataclass(frozen=True)
class ThreadsPendingDraft:
    """Threads 초안 1건의 검수 대기 상태 전체.

    ``content_id``는 ``content_engine.publish_history.compute_content_id()``가 계산한
    값을 그대로 받아 저장할 뿐, 이 클래스는 content_id를 계산하지 않는다.
    """

    content_id: str
    knowledge_id: str
    source_url: str
    evidence_unit_ids: tuple[str, ...]
    article_type: str | None
    knowledge_type: str | None
    original_title: str
    original_body: str
    ai_rewritten_title: str
    ai_rewritten_body: str
    status: str
    created_at: str
    final_title: str | None = None
    final_body: str | None = None
    edited_by_user: bool = False
    approved_at: str | None = None
    published_at: str | None = None
    failed_at: str | None = None
    failure_reason: str | None = None
    threads_post_id: str | None = None

    def __post_init__(self) -> None:
        # 필수 필드 검증 - 이 두 값이 없으면 이 draft가 어떤 콘텐츠/이력과도 연결될
        # 수 없다(content_id는 PublishHistory와의 유일한 연결고리, knowledge_id는
        # rotation 정책의 기준).
        if not self.content_id:
            raise ThreadsPendingError("content_id가 필요합니다.")
        if not self.knowledge_id:
            raise ThreadsPendingError("knowledge_id가 필요합니다.")
        if self.status not in VALID_STATUSES:
            raise ThreadsPendingError(f"status는 {VALID_STATUSES} 중 하나여야 합니다: {self.status!r}")
        if not self.created_at:
            raise ThreadsPendingError("created_at이 필요합니다.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "content_id": self.content_id,
            "knowledge_id": self.knowledge_id,
            "source_url": self.source_url,
            "evidence_unit_ids": list(self.evidence_unit_ids),
            "article_type": self.article_type,
            "knowledge_type": self.knowledge_type,
            "original_title": self.original_title,
            "original_body": self.original_body,
            "ai_rewritten_title": self.ai_rewritten_title,
            "ai_rewritten_body": self.ai_rewritten_body,
            "final_title": self.final_title,
            "final_body": self.final_body,
            "edited_by_user": self.edited_by_user,
            "status": self.status,
            "created_at": self.created_at,
            "approved_at": self.approved_at,
            "published_at": self.published_at,
            "failed_at": self.failed_at,
            "failure_reason": self.failure_reason,
            "threads_post_id": self.threads_post_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ThreadsPendingDraft":
        if not isinstance(data, dict):
            raise ThreadsPendingError("draft 항목은 객체(dict)여야 합니다.")

        evidence_unit_ids = data.get("evidence_unit_ids") or []
        if not isinstance(evidence_unit_ids, (list, tuple)):
            raise ThreadsPendingError("evidence_unit_ids는 목록(list) 구조여야 합니다.")

        return cls(
            content_id=str(data.get("content_id") or ""),
            knowledge_id=str(data.get("knowledge_id") or ""),
            source_url=str(data.get("source_url") or ""),
            evidence_unit_ids=tuple(str(unit_id) for unit_id in evidence_unit_ids),
            article_type=_optional_str(data.get("article_type")),
            knowledge_type=_optional_str(data.get("knowledge_type")),
            original_title=str(data.get("original_title") or ""),
            original_body=str(data.get("original_body") or ""),
            ai_rewritten_title=str(data.get("ai_rewritten_title") or ""),
            ai_rewritten_body=str(data.get("ai_rewritten_body") or ""),
            final_title=_optional_str(data.get("final_title")),
            final_body=_optional_str(data.get("final_body")),
            edited_by_user=bool(data.get("edited_by_user") or False),
            status=str(data.get("status") or ""),
            created_at=str(data.get("created_at") or ""),
            approved_at=_optional_str(data.get("approved_at")),
            published_at=_optional_str(data.get("published_at")),
            failed_at=_optional_str(data.get("failed_at")),
            failure_reason=_optional_str(data.get("failure_reason")),
            threads_post_id=_optional_str(data.get("threads_post_id")),
        )


def load_pending(path: Path | str) -> list[ThreadsPendingDraft]:
    """pending 파일을 읽는다. 파일이 없거나 비어 있으면 빈 목록을 반환한다."""
    target = Path(path)
    if not target.exists():
        return []
    raw_text = target.read_text(encoding="utf-8").strip()
    if not raw_text:
        return []
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as error:
        raise ThreadsPendingError(f"pending 파일이 올바른 JSON이 아닙니다: {target}") from error
    if not isinstance(data, list):
        raise ThreadsPendingError(f"pending 파일은 객체 목록(list) 구조여야 합니다: {target}")
    return [ThreadsPendingDraft.from_dict(item) for item in data]


def save_pending(drafts: list[ThreadsPendingDraft], path: Path | str) -> None:
    """draft 목록을 원자적으로(tempfile + replace) 저장한다."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = [draft.to_dict() for draft in drafts]
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temp_path = Path(handle.name)
    temp_path.replace(target)


def upsert_pending(path: Path | str, draft: ThreadsPendingDraft) -> list[ThreadsPendingDraft]:
    """같은 content_id의 기존 draft는 덮어쓰고, 새 content_id는 추가한다."""
    by_content_id = {existing.content_id: existing for existing in load_pending(path)}
    by_content_id[draft.content_id] = draft
    result = list(by_content_id.values())
    save_pending(result, path)
    return result


def has_unresolved_draft(path: Path | str) -> bool:
    """pending 또는 approved 상태의 미해결 draft가 하나라도 있으면 True.

    generate_threads_draft.py가 이 값이 True일 때 새 draft 생성을 건너뛰는 데
    쓴다(5-11 설계 5장의 idempotency 요구사항). published/failed는 여기 포함되지
    않는다.
    """
    return any(draft.status in UNRESOLVED_STATUSES for draft in load_pending(path))


def _transition(draft: ThreadsPendingDraft, new_status: str, **fields: Any) -> ThreadsPendingDraft:
    allowed = _ALLOWED_TRANSITIONS.get(draft.status, frozenset())
    if new_status not in allowed:
        raise ThreadsPendingError(f"허용되지 않는 상태 전이입니다: {draft.status!r} -> {new_status!r}")
    return replace(draft, status=new_status, **fields)


def mark_approved(draft: ThreadsPendingDraft, final_title: str, final_body: str, approved_at: str) -> ThreadsPendingDraft:
    """pending -> approved 또는 failed -> approved(재시도)로 전이한다.

    final_title/final_body는 티몽이 수정했든 안 했든(그대로 승인) Dashboard가 항상
    전달하는 "최종 확정 텍스트"다. ai_rewritten_*과 다르면 edited_by_user=True로
    표시한다(수정 여부 자체는 표시용 정보일 뿐, content_id 계산에는 전혀 쓰이지
    않는다 - 5-11 설계 7장).
    """
    edited = (final_title != draft.ai_rewritten_title) or (final_body != draft.ai_rewritten_body)
    return _transition(
        draft,
        "approved",
        final_title=final_title,
        final_body=final_body,
        edited_by_user=edited,
        approved_at=approved_at,
    )


def mark_published(draft: ThreadsPendingDraft, threads_post_id: str, published_at: str) -> ThreadsPendingDraft:
    """approved -> published(종결). 실제 Threads API 성공 이후에만 호출되어야 한다."""
    return _transition(draft, "published", threads_post_id=threads_post_id, published_at=published_at)


def mark_failed(draft: ThreadsPendingDraft, failure_reason: str, failed_at: str) -> ThreadsPendingDraft:
    """approved -> failed. 실제 Threads API 실패 이후에만 호출되어야 한다."""
    return _transition(draft, "failed", failure_reason=failure_reason, failed_at=failed_at)
