"""표준 마케팅 리서치 task: 하나의 주제를 8개 관점의 질의로 나누어 ResearchProvider로 조사한다.

결과는 사실이 아니라 '검증 대상 근거'다: EvidenceItem으로 출처를 보존하고, KNOWLEDGE 후보는
research_bridge와 동일하게 pending + verification_required=True로만 만든다. 이 모듈은 파일을 쓰지 않는다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from content_engine.providers.base import (
    ProviderAuthError, ProviderError, ProviderNotConfiguredError, ProviderNotImplementedError,
    ResearchProvider, ResearchResult,
)
from content_engine.research_bridge import research_to_knowledge
from tak_brain.models import KnowledgeRecord

from .models import EvidenceItem

ASPECT_QUERIES: dict[str, str] = {
    "market_demand": "{topic} 시장 수요 규모 성장 추세",
    "competitors": "{topic} 경쟁 서비스 대안 비교",
    "customer_problem": "{topic} 고객이 겪는 문제 불만 후기",
    "search_intent": "{topic} 사람들이 검색하는 질문 검색 의도",
    "recurring_questions": "{topic} 자주 묻는 질문 반복되는 궁금증",
    "pricing_signals": "{topic} 가격 요금 구매 의사 결제",
    "competitor_positioning": "{topic} 경쟁자 포지셔닝 메시지 차별점",
    "content_angles": "{topic} 콘텐츠 앵글 인기 주제 반응이 좋은 형식",
}
DEFAULT_ASPECTS = tuple(ASPECT_QUERIES)
# 설정/인증 문제는 숨기지 않고 즉시 올린다(조용한 부분 실패 방지).
_FATAL = (ProviderNotConfiguredError, ProviderNotImplementedError, ProviderAuthError)


@dataclass(frozen=True)
class ResearchBundle:
    topic: str
    results: dict[str, ResearchResult] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def evidence(self) -> tuple[EvidenceItem, ...]:
        items: list[EvidenceItem] = []
        for aspect, result in self.results.items():
            for source in result.sources:
                items.append(EvidenceItem(kind="research", title=source.title or source.domain, url=source.url,
                                          snippet=source.snippet, provider=result.provider, aspect=aspect))
        return tuple(items)

    def knowledge_records(self) -> list[KnowledgeRecord]:
        """출처가 있는 aspect만 pending KNOWLEDGE 후보로 변환한다(저장은 호출자 몫)."""
        records = []
        for aspect, result in self.results.items():
            if result.sources:
                records.append(research_to_knowledge(result, title=f"{self.topic} - {aspect}"))
        return records


def build_queries(topic: str, aspects: Sequence[str] = DEFAULT_ASPECTS) -> dict[str, str]:
    if not topic.strip():
        raise ValueError("topic이 비어 있습니다.")
    unknown = [aspect for aspect in aspects if aspect not in ASPECT_QUERIES]
    if unknown:
        raise ValueError(f"알 수 없는 aspect: {unknown}")
    return {aspect: ASPECT_QUERIES[aspect].format(topic=topic.strip()) for aspect in aspects}


def run_research_tasks(
    topic: str, provider: ResearchProvider, aspects: Sequence[str] = DEFAULT_ASPECTS, max_results: int = 5
) -> ResearchBundle:
    results: dict[str, ResearchResult] = {}
    errors: dict[str, str] = {}
    for aspect, query in build_queries(topic, aspects).items():
        try:
            results[aspect] = provider.research(query, max_results=max_results)
        except _FATAL:
            raise
        except ProviderError as error:
            errors[aspect] = str(error)
    return ResearchBundle(topic=topic.strip(), results=results, errors=errors)


def research_idea(idea, provider: ResearchProvider, aspects: Sequence[str] = DEFAULT_ASPECTS, max_results: int = 5) -> ResearchBundle:
    """IdeaCandidate.research_query를 먼저 조사하고 표준 aspect task를 이어서 실행한다."""
    first = provider.research(idea.research_query, max_results=max_results) if idea.research_query.strip() else None
    bundle = run_research_tasks(idea.title, provider, aspects, max_results)
    if first is None:
        return bundle
    return ResearchBundle(topic=bundle.topic, results={"idea_query": first, **bundle.results}, errors=bundle.errors)
