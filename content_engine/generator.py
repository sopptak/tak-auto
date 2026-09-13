"""승인된 KNOWLEDGE를 유형별 규칙 기반 TAK미디어 콘텐츠로 변환한다."""

from __future__ import annotations

from collections.abc import Iterable
import re

from tak_brain.models import KnowledgeRecord

from .models import BlogDraft, ContentBrief, ContentBundle, EvidenceUnit, ShortDraft, ThreadDraft


_CONTENT_FIELDS = (
    "experience",
    "problem",
    "action",
    "result",
    "lesson",
    "reusable_principle",
    "derived_insight",
)
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")


def _required_text(knowledge: KnowledgeRecord, field_name: str) -> str:
    value = getattr(knowledge, field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"KNOWLEDGE의 {field_name} 필드가 필요합니다.")
    return value


def _evidence_units(knowledge: KnowledgeRecord) -> tuple[EvidenceUnit, ...]:
    units = []
    for field_name in _CONTENT_FIELDS:
        value = getattr(knowledge, field_name)
        if not isinstance(value, str) or not value.strip():
            continue
        sentences = tuple(sentence.strip() for sentence in _SENTENCE_BOUNDARY.split(value) if sentence.strip())
        units.extend(
            EvidenceUnit(f"{field_name}:{index}", field_name, sentence)
            for index, sentence in enumerate(sentences, start=1)
        )
    return tuple(units)


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
        article_type=knowledge.article_type,
        knowledge_type=knowledge.knowledge_type,
        source_url=knowledge.source_url,
        experience=knowledge.experience,
        problem=knowledge.problem,
        action=knowledge.action,
        result=knowledge.result,
        lesson=knowledge.lesson,
        reusable_principle=knowledge.reusable_principle,
        derived_insight=knowledge.derived_insight,
        evidence=tuple(knowledge.evidence),
        evidence_units=_evidence_units(knowledge),
    )


def _draft_metadata(brief: ContentBrief) -> dict[str, object]:
    return {"source_url": brief.source_url, "evidence": brief.evidence}


def _profile(brief: ContentBrief) -> str:
    if brief.article_type == "finance":
        return "finance"
    if brief.article_type == "book_philosophy":
        return "book"
    if brief.knowledge_type == "경험" or brief.article_type in {"experience", "ai_business"}:
        return "experience"
    return "criterion"


def _pick(brief: ContentBrief, used_ids: set[str], *field_names: str) -> EvidenceUnit | None:
    for field_name in field_names:
        for unit in brief.evidence_units:
            if unit.field_name == field_name and unit.id not in used_ids:
                used_ids.add(unit.id)
                return unit
    return None


def _quote(unit: EvidenceUnit | None, lead: str, ending: str) -> str | None:
    if unit is None:
        return None
    return f'{lead}"{unit.text.rstrip(".!?").strip()}"{ending}'


def _body(*paragraphs: str | None) -> str:
    return "\n\n".join(paragraph for paragraph in paragraphs if paragraph)


def _draft(
    brief: ContentBrief,
    draft_type: type[BlogDraft] | type[ShortDraft] | type[ThreadDraft],
    title: str,
    body: str,
    units: tuple[EvidenceUnit | None, ...],
) -> BlogDraft | ShortDraft | ThreadDraft:
    used_units = tuple(unit for unit in units if unit is not None)
    return draft_type(
        title=title,
        body=body,
        evidence_unit_ids=tuple(unit.id for unit in used_units),
        **_draft_metadata(brief),
    )


def _experience_blog(brief: ContentBrief) -> BlogDraft:
    used_ids: set[str] = set()
    problem = _pick(brief, used_ids, "problem")
    experience = _pick(brief, used_ids, "experience")
    action = _pick(brief, used_ids, "action")
    result = _pick(brief, used_ids, "result")
    lesson = _pick(brief, used_ids, "lesson", "derived_insight")
    principle = _pick(brief, used_ids, "reusable_principle")
    return _draft(
        brief,
        BlogDraft,
        "직접 시도하며 얻은 교훈",
        _body(
            _quote(problem, "처음 마주한 문제는 ", "였습니다."),
            _quote(experience, "이 글은 ", "라는 경험을 다룹니다."),
            _quote(action, "작성자는 ", "고 적었습니다."),
            _quote(result, "그 뒤 ", "라는 결과를 기록했습니다."),
            _quote(lesson, "이 경험에서 얻은 교훈은 ", "입니다."),
            _quote(principle, "다음에 적용할 원칙은 ", "입니다."),
        ),
        (problem, experience, action, result, lesson, principle),
    )


def _criterion_blog(brief: ContentBrief, profile: str) -> BlogDraft:
    used_ids: set[str] = set()
    question = _pick(brief, used_ids, "problem")
    observation = _pick(brief, used_ids, "lesson", "derived_insight")
    principle = _pick(brief, used_ids, "reusable_principle")
    caution = (
        "이 글의 금융 관련 내용은 원문 작성자의 설명이며, 금융기관의 공식 심사 기준으로 해석하지 않습니다."
        if profile == "finance"
        else None
    )
    title = "재무 판단에서 함께 볼 기준" if profile == "finance" else "판단에 앞서 확인할 기준"
    return _draft(
        brief,
        BlogDraft,
        title,
        _body(
            _quote(question, "글은 ", "라는 질문을 던집니다."),
            _quote(observation, "원문에서는 ", "고 설명합니다."),
            _quote(principle, "이를 적용할 때는 ", "는 원칙을 제시합니다."),
            caution,
        ),
        (question, observation, principle),
    )


def _book_blog(brief: ContentBrief) -> BlogDraft:
    used_ids: set[str] = set()
    interpretation = _pick(brief, used_ids, "lesson")
    principle = _pick(brief, used_ids, "reusable_principle")
    insight = _pick(brief, used_ids, "derived_insight")
    return _draft(
        brief,
        BlogDraft,
        "원문 맥락에서 읽는 생각",
        _body(
            _quote(interpretation, "이 글은 책의 생각을 ", "고 정리합니다."),
            _quote(insight, "작성자의 해석은 ", "입니다."),
            _quote(principle, "다른 상황에 적용할 때는 ", "는 원칙을 따릅니다."),
        ),
        (interpretation, insight, principle),
    )


def _blog(brief: ContentBrief, profile: str) -> BlogDraft:
    if profile == "experience":
        return _experience_blog(brief)
    if profile == "book":
        return _book_blog(brief)
    return _criterion_blog(brief, profile)


def _short(brief: ContentBrief, title: str, fields: tuple[str, ...], closing_fields: tuple[str, ...]) -> ShortDraft:
    used_ids: set[str] = set()
    hook = _pick(brief, used_ids, *fields)
    detail = _pick(brief, used_ids, *fields)
    closing = _pick(brief, used_ids, *closing_fields)
    return _draft(
        brief,
        ShortDraft,
        title,
        _body(
            _quote(hook, "", "."),
            _quote(detail, "원문은 이어 ", "고 설명합니다."),
            _quote(closing, "남는 기준은 ", "입니다."),
        ),
        (hook, detail, closing),
    )


def _thread(brief: ContentBrief, title: str, fields: tuple[str, ...], supporting_fields: tuple[str, ...]) -> ThreadDraft:
    used_ids: set[str] = set()
    message = _pick(brief, used_ids, *fields)
    supporting = _pick(brief, used_ids, *supporting_fields)
    return _draft(
        brief,
        ThreadDraft,
        title,
        _body(
            _quote(message, "", "."),
            _quote(supporting, "원문은 ", "고 덧붙입니다."),
        ),
        (message, supporting),
    )


def _experience_content(brief: ContentBrief) -> tuple[tuple[ShortDraft, ...], tuple[ThreadDraft, ...]]:
    return (
        (
            _short(brief, "문제에서 시작된 전환", ("problem",), ("lesson", "derived_insight")),
            _short(brief, "실행으로 옮긴 방법", ("action",), ("reusable_principle", "lesson")),
            _short(brief, "결과가 남긴 교훈", ("result",), ("lesson", "derived_insight")),
        ),
        (
            _thread(brief, "교훈에서 찾은 기준", ("derived_insight", "lesson"), ("reusable_principle",)),
            _thread(brief, "경험으로 확인한 관찰", ("experience",), ("lesson",)),
            _thread(brief, "실행에서 확인한 방법", ("action",), ("reusable_principle",)),
            _thread(brief, "문제가 남긴 교훈", ("problem",), ("lesson",)),
            _thread(brief, "적용할 원칙", ("reusable_principle",), ("derived_insight", "lesson")),
        ),
    )


def _criterion_content(brief: ContentBrief, profile: str) -> tuple[tuple[ShortDraft, ...], tuple[ThreadDraft, ...]]:
    question_fields = ("problem", "lesson")
    principle_fields = ("reusable_principle", "lesson")
    caution_fields = ("lesson", "reusable_principle")
    short_titles = (
        "재무 판단의 출발점" if profile == "finance" else "판단이 시작되는 질문",
        "함께 살펴볼 기준",
        "적용 전에 확인할 점",
    )
    return (
        (
            _short(brief, short_titles[0], question_fields, principle_fields),
            _short(brief, short_titles[1], principle_fields, ("lesson",)),
            _short(brief, short_titles[2], caution_fields, principle_fields),
        ),
        (
            _thread(brief, "원문이 제시한 판단", ("lesson", "derived_insight"), principle_fields),
            _thread(brief, "판단 기준의 범위", principle_fields, ("lesson",)),
            _thread(brief, "확인할 항목", ("lesson",), principle_fields),
            _thread(brief, "질문에서 얻는 기준", question_fields, ("lesson",)),
            _thread(brief, "적용 원칙", principle_fields, ("derived_insight", "lesson")),
        ),
    )


def _book_content(brief: ContentBrief) -> tuple[tuple[ShortDraft, ...], tuple[ThreadDraft, ...]]:
    return _criterion_content(brief, "book")


def _complete_bundle(brief: ContentBrief) -> ContentBundle:
    profile = _profile(brief)
    if profile == "experience":
        shorts, threads = _experience_content(brief)
    elif profile == "book":
        shorts, threads = _book_content(brief)
    else:
        shorts, threads = _criterion_content(brief, profile)
    return ContentBundle(blog=_blog(brief, profile), shorts=shorts, threads=threads)


def generate_content_bundle(knowledge: KnowledgeRecord) -> ContentBundle:
    """승인된 KNOWLEDGE 1개를 유형에 맞는 Blog, Shorts, Threads로 변환한다."""
    brief = build_content_brief(knowledge)
    if not brief.evidence_units:
        return ContentBundle(
            blog=None,
            shorts=(),
            threads=(),
            status="insufficient_distinct_evidence",
            unmet_requirement_ids=("approved_knowledge_content",),
        )
    bundle = _complete_bundle(brief)
    bundle.validate_counts()
    return bundle


def generate_from_approved(records: Iterable[KnowledgeRecord]) -> ContentBundle:
    """입력 목록에서 승인된 KNOWLEDGE가 정확히 1개일 때 콘텐츠 묶음을 만든다."""
    approved = tuple(record for record in records if record.knowledge_review_status == "approved")
    if len(approved) != 1:
        raise ValueError("승인된 KNOWLEDGE는 정확히 1개여야 합니다.")
    return generate_content_bundle(approved[0])
