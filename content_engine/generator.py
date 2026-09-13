"""승인된 KNOWLEDGE를 규칙 기반 TAK미디어 콘텐츠로 변환한다."""

from __future__ import annotations

from collections.abc import Iterable

from tak_brain.models import KnowledgeRecord

from .models import (
    BlogDraft,
    ContentBrief,
    ContentBundle,
    ShortDraft,
    ThreadDraft,
)


def _required_text(knowledge: KnowledgeRecord, field_name: str) -> str:
    value = getattr(knowledge, field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"KNOWLEDGE의 {field_name} 필드가 필요합니다.")
    return value


def build_content_brief(knowledge: KnowledgeRecord) -> ContentBrief:
    """승인된 KNOWLEDGE에서 콘텐츠에 필요한 최소 사실 집합을 만든다."""
    if knowledge.knowledge_review_status != "approved":
        raise ValueError("승인된 KNOWLEDGE만 콘텐츠로 변환할 수 있습니다.")
    if not knowledge.source_url:
        raise ValueError("KNOWLEDGE의 source_url이 필요합니다.")
    if not knowledge.evidence:
        raise ValueError("KNOWLEDGE의 evidence가 필요합니다.")

    return ContentBrief(
        knowledge_id=_required_text(knowledge, "id"),
        title=_required_text(knowledge, "title"),
        source_url=knowledge.source_url,
        experience=_required_text(knowledge, "experience"),
        problem=_required_text(knowledge, "problem"),
        action=_required_text(knowledge, "action"),
        result=_required_text(knowledge, "result"),
        lesson=_required_text(knowledge, "lesson"),
        reusable_principle=_required_text(knowledge, "reusable_principle"),
        evidence=tuple(knowledge.evidence),
    )


def _draft_metadata(brief: ContentBrief) -> dict[str, object]:
    return {"source_url": brief.source_url, "evidence": brief.evidence}


def generate_blog(brief: ContentBrief) -> BlogDraft:
    """KNOWLEDGE의 필드를 고정 섹션으로 조합해 블로그 1개를 만든다."""
    body = "\n\n".join(
        (
            f"경험\n{brief.experience}",
            f"문제\n{brief.problem}",
            f"시도\n{brief.action}",
            f"결과\n{brief.result}",
            f"배운 점\n{brief.lesson}",
            f"재사용 원칙\n{brief.reusable_principle}",
        )
    )
    return BlogDraft(title=brief.title, body=body, **_draft_metadata(brief))


def generate_shorts(brief: ContentBrief) -> tuple[ShortDraft, ...]:
    """경험의 문제·시도·결과를 각각 Shorts 3개로 조합한다."""
    sections = (
        ("문제", brief.problem),
        ("시도", brief.action),
        ("결과", brief.result),
    )
    return tuple(
        ShortDraft(
            title=f"{brief.title} | {label}",
            body=f"{label}\n{value}",
            **_draft_metadata(brief),
        )
        for label, value in sections
    )


def generate_threads(brief: ContentBrief) -> tuple[ThreadDraft, ...]:
    """경험의 흐름과 재사용 원칙을 Threads 5개로 조합한다."""
    sections = (
        ("경험", brief.experience),
        ("문제", brief.problem),
        ("시도", brief.action),
        ("결과", brief.result),
        ("원칙", brief.reusable_principle),
    )
    return tuple(
        ThreadDraft(
            title=f"{brief.title} | {label}",
            body=f"{label}\n{value}",
            **_draft_metadata(brief),
        )
        for label, value in sections
    )


def generate_content_bundle(knowledge: KnowledgeRecord) -> ContentBundle:
    """승인된 KNOWLEDGE 1개를 Blog 1개, Shorts 3개, Threads 5개로 변환한다."""
    brief = build_content_brief(knowledge)
    bundle = ContentBundle(
        blog=generate_blog(brief),
        shorts=generate_shorts(brief),
        threads=generate_threads(brief),
    )
    bundle.validate_counts()
    return bundle


def generate_from_approved(records: Iterable[KnowledgeRecord]) -> ContentBundle:
    """입력 목록에서 승인된 KNOWLEDGE가 정확히 1개일 때 콘텐츠 묶음을 만든다."""
    approved = tuple(record for record in records if record.knowledge_review_status == "approved")
    if len(approved) != 1:
        raise ValueError("승인된 KNOWLEDGE는 정확히 1개여야 합니다.")
    return generate_content_bundle(approved[0])