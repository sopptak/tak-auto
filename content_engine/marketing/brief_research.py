"""기존 MarketingBrief에 외부 조사 근거를 붙인다(docs/6-85). Perplexity는 조사/근거 수집 Provider다.

새 Provider/모델을 만들지 않는다: ``ResearchProvider``(providers/), ``research_tasks``의 8개 aspect 질의와
``ResearchBundle.evidence``(EvidenceItem), ``research_bridge.research_to_knowledge``(pending +
verification_required KNOWLEDGE 후보)를 그대로 쓴다.

경계:
    - 조사 결과는 '검증 전 근거'다. KNOWLEDGE 후보는 항상 pending + verification_required=True이며 자동 승인하지 않는다.
    - 조사 KNOWLEDGE는 brief.knowledge_ids(생성 입력)에 연결하지 않는다. 생성 입력은 사람이 승인한
      경험/판단 KNOWLEDGE를 knowledge add로 연결한다(6-83).
    - 브리프에는 evidence만 추가하고 confidence를 다시 계산한다. status/knowledge_ids/content_ids/media_generations는 그대로.
    - approved 브리프에는 쓰지 않는다: 검토하지 않은 근거가 재승인 없이 생성 프롬프트에 들어가면 승인 게이트를 우회한다.
      rejected 브리프도 쓰지 않는다. 미리보기는 가능하다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

from content_engine.market_demand import IdeaCandidate
from content_engine.providers.base import ResearchProvider
from tak_brain.models import KnowledgeRecord

from .briefs import brief_confidence
from .models import STATUS_APPROVED, STATUS_REJECTED, EvidenceItem, MarketingBrief, MarketingError
from .research_tasks import DEFAULT_ASPECTS, build_queries, research_idea, run_research_tasks
from .store import _update


@dataclass(frozen=True)
class BriefResearch:
    brief_id: str
    provider: str
    queries: dict[str, str]
    source_counts: dict[str, int]  # aspect -> 출처 수
    new_evidence: tuple[EvidenceItem, ...]
    duplicate_evidence: int  # 이미 브리프에 있거나 이번 조사 안에서 중복된 근거 수
    knowledge: tuple[KnowledgeRecord, ...]  # pending + verification_required 후보
    errors: dict[str, str] = field(default_factory=dict)  # aspect -> 오류(설정/인증 오류는 예외로 올라온다)
    write_blockers: tuple[str, ...] = ()

    @property
    def has_results(self) -> bool:
        return bool(self.new_evidence or self.knowledge)


def research_write_blockers(brief: MarketingBrief) -> list[str]:
    if brief.status == STATUS_REJECTED:
        return ["rejected 브리프에는 근거를 추가할 수 없습니다."]
    if brief.status == STATUS_APPROVED:
        return ["approved 브리프에는 근거를 추가하지 않습니다: 검토하지 않은 근거가 재승인 없이 생성에 쓰이게 됩니다. "
                "set으로 수정(draft 전환) 후 조사하거나 새 브리프를 만드세요."]
    return []


def research_brief(
    brief: MarketingBrief,
    provider: ResearchProvider,
    idea: IdeaCandidate | None = None,
    aspects: Sequence[str] = DEFAULT_ASPECTS,
    max_results: int = 5,
) -> BriefResearch:
    """조사만 하고 아무것도 쓰지 않는다. 설정/인증 오류는 ProviderError로 올라온다."""
    if idea is not None:
        bundle = research_idea(idea, provider, aspects, max_results)
        queries = {**({"idea_query": idea.research_query} if idea.research_query.strip() else {}),
                   **build_queries(idea.title, aspects)}
    else:
        bundle = run_research_tasks(brief.topic, provider, aspects, max_results)
        queries = build_queries(brief.topic, aspects)
    seen = {item.evidence_id for item in brief.evidence}
    new, duplicates = [], 0
    for item in bundle.evidence:
        if item.evidence_id in seen:
            duplicates += 1
            continue
        seen.add(item.evidence_id)
        new.append(item)
    knowledge = tuple(bundle.knowledge_records())
    for record in knowledge:  # research_bridge 계약을 다시 확인한다(자동 승인 금지).
        if record.knowledge_review_status != "pending" or not record.verification_required:
            raise MarketingError(f"조사 KNOWLEDGE는 pending + verification_required여야 합니다: {record.id}")
    return BriefResearch(
        brief_id=brief.brief_id, provider=getattr(provider, "name", ""), queries=queries,
        source_counts={aspect: len(result.sources) for aspect, result in bundle.results.items()},
        new_evidence=tuple(new), duplicate_evidence=duplicates, knowledge=knowledge, errors=dict(bundle.errors),
        write_blockers=tuple(research_write_blockers(brief)),
    )


def apply_brief_research(path: Path | str, research: BriefResearch) -> MarketingBrief:
    """브리프에 새 근거만 추가하고 confidence를 다시 계산한다. 저장 직전 게이트를 다시 확인한다."""
    def apply(brief: MarketingBrief) -> MarketingBrief:
        blockers = research_write_blockers(brief)
        if blockers:
            raise MarketingError(" / ".join(blockers))
        known = {item.evidence_id for item in brief.evidence}
        evidence = brief.evidence + tuple(item for item in research.new_evidence if item.evidence_id not in known)
        # 근거를 추가해서 confidence가 내려가지 않게 한다(기존 값이 다른 경로로 정해졌을 수 있다).
        return replace(brief, evidence=evidence, confidence=max(brief.confidence, brief_confidence(evidence)))
    return _update(path, research.brief_id, apply)
