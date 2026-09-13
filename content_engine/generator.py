"""승인된 KNOWLEDGE를 규칙 기반 TAK미디어 콘텐츠로 변환한다."""

from __future__ import annotations

from collections.abc import Iterable
import re

from tak_brain.models import KnowledgeRecord

from .models import (
    BlogDraft,
    ContentBrief,
    ContentBundle,
    EvidenceUnit,
    ShortDraft,
    ThreadDraft,
)


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
        sentences = tuple(
            sentence.strip()
            for sentence in _SENTENCE_BOUNDARY.split(value)
            if sentence.strip()
        )
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


def _units_for(brief: ContentBrief, *field_names: str) -> tuple[EvidenceUnit, ...]:
    units = tuple(
        unit
        for field_name in field_names
        for unit in brief.evidence_units
        if unit.field_name == field_name
    )
    return units or brief.evidence_units


def _pick(brief: ContentBrief, used_ids: set[str], *field_names: str) -> EvidenceUnit:
    candidates = _units_for(brief, *field_names)
    unit = next(
        (candidate for candidate in candidates if candidate.id not in used_ids),
        next((candidate for candidate in brief.evidence_units if candidate.id not in used_ids), candidates[0]),
    )
    used_ids.add(unit.id)
    return unit


def _restate(unit: EvidenceUnit, lead: str, ending: str) -> str:
    text = unit.text.rstrip(".!?").strip()
    return f'{lead}"{text}"{ending}'


def _draft(
    brief: ContentBrief,
    draft_type: type[BlogDraft] | type[ShortDraft] | type[ThreadDraft],
    title: str,
    body: str,
    units: tuple[EvidenceUnit, ...],
) -> BlogDraft | ShortDraft | ThreadDraft:
    return draft_type(
        title=title,
        body=body,
        evidence_unit_ids=tuple(unit.id for unit in units),
        **_draft_metadata(brief),
    )


def _blog(brief: ContentBrief) -> BlogDraft:
    used_ids: set[str] = set()
    problem = _pick(brief, used_ids, "problem")
    experience = _pick(brief, used_ids, "experience")
    action = _pick(brief, used_ids, "action")
    result = _pick(brief, used_ids, "result")
    lesson = _pick(brief, used_ids, "lesson", "derived_insight")
    principle = _pick(brief, used_ids, "reusable_principle", "derived_insight")
    body = "\n\n".join(
        (
            _restate(problem, "이야기는 ", "라는 문제에서 시작합니다."),
            _restate(experience, "기록에는 ", "라고 남아 있습니다."),
            _restate(action, "그 과정에서는 ", "라고 설명합니다."),
            _restate(result, "이어 ", "라는 결과를 확인했습니다."),
            _restate(lesson, "여기서 남은 교훈은 ", "라는 점입니다."),
            _restate(principle, "독자에게 적용할 원칙은 ", "라는 것입니다."),
        )
    )
    return _draft(
        brief,
        BlogDraft,
        "문제 해결을 위한 실행과 교훈",
        body,
        (problem, experience, action, result, lesson, principle),
    )


def _short(brief: ContentBrief, title: str, fields: tuple[str, ...], closing_fields: tuple[str, ...]) -> ShortDraft:
    used_ids: set[str] = set()
    hook = _pick(brief, used_ids, *fields)
    core = _pick(brief, used_ids, *fields, "experience", "action", "result")
    closing = _pick(brief, used_ids, *closing_fields)
    body = "\n\n".join(
        (
            f"훅\n{_restate(hook, '주목할 지점은 ', '입니다.')}",
            f"핵심 내용\n{_restate(core, '기록에는 ', '라고 적혀 있습니다.')}",
            f"마무리\n{_restate(closing, '여기서 확인할 수 있는 점은 ', '입니다.')}",
        )
    )
    return _draft(brief, ShortDraft, title, body, (hook, core, closing))


def _thread(brief: ContentBrief, title: str, fields: tuple[str, ...], explanation_fields: tuple[str, ...], conclusion_fields: tuple[str, ...]) -> ThreadDraft:
    used_ids: set[str] = set()
    claim = _pick(brief, used_ids, *fields)
    explanation = _pick(brief, used_ids, *explanation_fields)
    conclusion = _pick(brief, used_ids, *conclusion_fields)
    body = "\n\n".join(
        (
            f"주장\n{_restate(claim, '기록이 전하는 주장은 ', '입니다.')}",
            f"설명\n{_restate(explanation, '근거가 되는 내용은 ', '입니다.')}",
            f"결론\n{_restate(conclusion, '따라서 남는 기준은 ', '입니다.')}",
        )
    )
    return _draft(brief, ThreadDraft, title, body, (claim, explanation, conclusion))


def _complete_bundle(brief: ContentBrief) -> ContentBundle:
    return ContentBundle(
        blog=_blog(brief),
        shorts=(
            _short(brief, "문제에서 시작된 전환", ("problem",), ("lesson", "derived_insight")),
            _short(brief, "실행으로 옮긴 방법", ("action",), ("reusable_principle", "lesson")),
            _short(brief, "결과가 남긴 교훈", ("result",), ("lesson", "derived_insight")),
        ),
        threads=(
            _thread(brief, "교훈에서 찾은 기준", ("derived_insight", "lesson"), ("lesson", "derived_insight"), ("reusable_principle", "lesson")),
            _thread(brief, "경험으로 확인한 관찰", ("experience",), ("experience", "lesson"), ("lesson", "derived_insight")),
            _thread(brief, "실행에서 확인한 방법", ("action",), ("action", "experience"), ("reusable_principle", "lesson")),
            _thread(brief, "문제가 남긴 교훈", ("problem",), ("problem", "action"), ("lesson", "derived_insight")),
            _thread(brief, "적용할 원칙", ("reusable_principle",), ("reusable_principle", "derived_insight"), ("reusable_principle", "lesson")),
        ),
    )


def generate_content_bundle(knowledge: KnowledgeRecord) -> ContentBundle:
    """승인된 KNOWLEDGE 1개를 Blog 1개, Shorts 3개, Threads 5개로 변환한다."""
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
