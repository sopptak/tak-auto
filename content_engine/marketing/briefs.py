"""IdeaCandidate(+MarketDemand, +리서치) -> MarketingBrief 초안, 그리고 콘텐츠 생성 게이트.

경계:
    - 시장 수요 근거가 없는 아이디어는 브리프로 만들지 않는다(MarketingError).
    - 초안은 근거(evidence)와 확실히 아는 값(카테고리 키워드)만 채운다. 심리/스토리/판매 요소는
      지어내지 않고 비워 두며 ``missing_fields()``로 사람이/LLM이 채울 목록을 노출한다.
    - 항상 draft + requires_human_review=True. 생성/발행을 실행하지 않는다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from blog_importer.models import utc_now
from content_engine.market_demand import IdeaCandidate, MarketDemand

from .models import (
    STATUS_APPROVED, STATUS_DRAFT, Distribution, EvidenceItem, MarketingBrief, MarketingError, compute_brief_id,
)
from .research_tasks import ResearchBundle
from .scoring import MarketingScore, score_brief

MIN_IDEA_SCORE = 40.0
MIN_READY_TOTAL = 50.0
MIN_READY_CONFIDENCE = 0.3


def market_evidence(demands: Sequence[MarketDemand]) -> tuple[EvidenceItem, ...]:
    items = []
    for demand in demands:
        price = f"{demand.price:g} {demand.currency}" if demand.price is not None else "가격 미상"
        signals = f"demand={demand.demand_signal}, competition={demand.competition_signal}"
        items.append(EvidenceItem(kind="market_demand", title=demand.title, url=demand.url,
                                  snippet=f"{price}; {signals}", provider=demand.source))
    return tuple(items)


def brief_confidence(evidence: Sequence[EvidenceItem]) -> float:
    """근거의 양/다양성에서 계산한 0~1 신뢰도. 사실 검증을 의미하지 않는다."""
    market = sum(1 for item in evidence if item.kind == "market_demand")
    research_urls = {item.url for item in evidence if item.kind == "research" and item.url}
    aspects = {item.aspect for item in evidence if item.aspect}
    return round(min(1.0, 0.2 * min(market, 2) + 0.05 * min(len(research_urls), 8) + 0.05 * min(len(aspects), 4)), 2)


def brief_from_idea(
    idea: IdeaCandidate,
    demands: Sequence[MarketDemand],
    bundle: ResearchBundle | None = None,
    knowledge_ids: Sequence[str] = (),
    min_idea_score: float = MIN_IDEA_SCORE,
    now: str | None = None,
) -> MarketingBrief:
    if idea.status == "rejected":
        raise MarketingError(f"거절된 아이디어는 브리프로 만들 수 없습니다: {idea.idea_id}")
    wanted = set(idea.demand_ids)
    linked = [demand for demand in demands if demand.demand_id in wanted]
    if not linked:
        raise MarketingError(f"시장 수요 근거가 없는 아이디어입니다: {idea.idea_id}")
    if idea.score < min_idea_score:
        raise MarketingError(f"기회 점수 {idea.score} < {min_idea_score}: {idea.idea_id}")
    evidence = market_evidence(linked) + (bundle.evidence if bundle else ())
    keyword = "" if idea.category == "uncategorized" else idea.category
    return MarketingBrief(
        brief_id=compute_brief_id(idea.title, "", idea.idea_id), topic=idea.title,
        distribution=Distribution(discovery_keyword=keyword), evidence=evidence,
        confidence=brief_confidence(evidence), idea_id=idea.idea_id, knowledge_ids=tuple(knowledge_ids),
        status=STATUS_DRAFT, requires_human_review=True, created_at=now or utc_now(),
    )


CORE_ELEMENTS = ("storytelling.hook", "sales.value_proposition", "sales.call_to_action", "psychology.pain")


def approval_blockers(brief: MarketingBrief) -> list[str]:
    """approved로 바꾸기 전에 해결해야 할 항목(상태 자체는 제외). 빈 목록이면 승인 가능."""
    from .suggestions import current_value

    blockers = []
    if brief.status == "rejected":
        blockers.append("rejected 브리프입니다.")
    if not any(item.kind == "market_demand" for item in brief.evidence):
        blockers.append("시장 수요 근거가 없습니다.")
    for name, value in (("target_audience", brief.target_audience), ("customer_problem", brief.customer_problem),
                        ("desired_action", brief.desired_action)):
        if not value.strip():
            blockers.append(f"{name}이(가) 비어 있습니다.")
    for key in CORE_ELEMENTS:
        if not current_value(brief, key):
            blockers.append(f"핵심 요소 {key}이(가) 비어 있습니다.")
    score: MarketingScore = score_brief(brief)
    if score.total_score < MIN_READY_TOTAL:
        blockers.append(f"마케팅 점수 {score.total_score} < {MIN_READY_TOTAL}")
    if score.confidence < MIN_READY_CONFIDENCE:
        blockers.append(f"점수 신뢰도 {score.confidence} < {MIN_READY_CONFIDENCE}(채워진 요소 부족)")
    return blockers


def readiness_blockers(brief: MarketingBrief) -> list[str]:
    """콘텐츠 생성에 쓰기 전에 해결해야 할 항목: 승인 상태 + 승인 조건을 현재 내용으로 다시 확인한다."""
    blockers = [] if brief.status == STATUS_APPROVED else ["사람이 approved로 승인하지 않았습니다."]
    return blockers + approval_blockers(brief)


def with_status(brief: MarketingBrief, status: str) -> MarketingBrief:
    """상태 변경. approved가 되어도 requires_human_review는 승인 기록으로서 유지한다."""
    return replace(brief, status=status)
