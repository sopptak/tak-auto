"""외부 리서치 결과 -> KNOWLEDGE 후보, 승인된 후속 후보 -> 생성 요청 변환(순수 함수).

경계:
    - 모든 KNOWLEDGE 후보는 pending + verification_required=True로 시작한다. 사람이 review를
      거쳐야만 기존 콘텐츠 파이프라인(select_approved)이 사용한다 - 자동 승인/발행 없음.
    - 이 모듈은 네트워크를 호출하지 않고 파일도 쓰지 않는다(저장은 호출 스크립트의 몫).
"""

from __future__ import annotations

from collections.abc import Sequence
import hashlib
from typing import Any

from blog_importer.models import utc_now
from content_engine.followup import STATUS_ACCEPTED, FollowUpCandidate, FollowUpError
from content_engine.providers.base import ResearchResult
from tak_brain.models import KnowledgeRecord

INFERENCE_METHOD = "external_research"
MAX_EVIDENCE = 5


def research_to_knowledge(result: ResearchResult, title: str | None = None, domain: str | None = None) -> KnowledgeRecord:
    """리서치 결과를 pending KNOWLEDGE 후보로 변환한다. 출처가 하나도 없으면 거부한다."""
    if not result.sources:
        raise ValueError("출처가 없는 리서치 결과는 KNOWLEDGE 후보로 만들 수 없습니다.")
    top = result.sources[0]
    fingerprint = f"{result.provider}|{result.query}|" + "|".join(source.url for source in result.sources)
    digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:12]
    evidence = tuple(
        f"{source.title or source.domain}: {source.snippet}".strip(": ") + f" ({source.url})"
        for source in result.sources[:MAX_EVIDENCE]
    )
    return KnowledgeRecord(
        id=f"knowledge-research-{digest}",
        source_raw_id=f"research:{result.provider}:{digest}",
        source_url=top.url,
        title=title or result.query,
        domain=domain,
        knowledge_type="research",
        factual_information=" / ".join(source.snippet for source in result.sources[:3] if source.snippet) or None,
        evidence=evidence,
        inference_method=INFERENCE_METHOD,
        confidence=None,
        created_at=utc_now(),
        knowledge_review_status="pending",
        verification_required=True,
    )


def followup_to_research_query(candidate: FollowUpCandidate) -> str:
    """후속 후보의 소재와 검색 의도로 리서치 질의를 만든다."""
    suffix = {
        "how_to": "방법 가이드",
        "comparison": "비교 차이",
        "problem_solving": "문제 해결 주의점",
        "informational": "최신 정보",
    }.get(candidate.search_intent, "관련 사례")
    return f"{candidate.title} {suffix}"


def accepted_followups_to_requests(candidates: Sequence[FollowUpCandidate]) -> list[dict[str, Any]]:
    """사람이 accepted로 바꾼 후보만 콘텐츠 생성 요청으로 변환한다(다음 단계 입력, 발행 아님).

    요청은 항상 requires_human_review=True이며, 이 함수는 어떤 생성/발행도 실행하지 않는다.
    """
    requests: list[dict[str, Any]] = []
    for candidate in candidates:
        if candidate.status != STATUS_ACCEPTED:
            continue
        if not candidate.knowledge_id:
            raise FollowUpError(f"knowledge_id가 없는 후보: {candidate.candidate_id}")
        requests.append(
            {
                "candidate_id": candidate.candidate_id,
                "knowledge_id": candidate.knowledge_id,
                "target_platform": candidate.target_platform,
                "search_intent": candidate.search_intent,
                "research_query": followup_to_research_query(candidate),
                "requires_human_review": True,
            }
        )
    return requests
