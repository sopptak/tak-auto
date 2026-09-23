"""KNOWLEDGE -> MEDIA 사이의 콘텐츠 전략/품질 Gate(6-37).

10월 1일 실제 운영에서, 승인된 KNOWLEDGE가 들어왔다고 해서 무조건
Blog + Shorts + Threads를 생성하지 않도록 한다. 이 모듈은 **후보와
근거만 제공한다** - 어떤 경우에도 자동으로 MEDIA를 생성하거나,
KNOWLEDGE/Production Archive를 수정하지 않는다(이 모듈에
``content_engine.pipeline``/``content_engine.media_archive``의 쓰기
함수를 import하지 않는다 - 순수 읽기/평가 함수만 존재한다).

핵심 경계:
    - "READY"는 "생성 가능한 후보"라는 뜻이지 "자동 생성하라"는 뜻이
      아니다(15장 Generation Policy).
    - 플랫폼(Threads/Blog/Shorts) 간 점수를 합산해 "가장 좋은 플랫폼"을
      정하지 않는다 - 각 플랫폼의 적합성을 독립적으로 기록한다(5장).
    - category(SCOUT source 성격)와 article_type(실제 본문 성격)을
      절대 혼동하지 않는다 - 6-04/6-32에서 이미 확인한 원칙을 그대로
      따른다(10장).
    - 출처가 없으면 AI가 출처를 지어내지 않는다(11장) - 이 모듈은
      evidence/source_url의 **존재 여부와 형식**만 확인하고, 내용을
      생성/보완하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from content_engine.blog_publish_pack import FINANCE_REVIEW_KEYWORDS
from content_engine.media_archive import MediaArchiveRecord
from tak_brain.models import KnowledgeRecord


class MediaStrategyError(ValueError):
    """MediaStrategyCandidate 구조가 올바르지 않을 때 발생한다."""


# --- 6장: Quality Gate 상태(Publish Readiness와 이름이 겹치지 않도록
# STRATEGY_ 접두어를 붙인다 - 이것은 "발행 가능 여부"가 아니라 "MEDIA 생성
# 전 전략/품질 상태"다) -------------------------------------------------------

STRATEGY_READY = "STRATEGY_READY"
STRATEGY_REVIEW_REQUIRED = "STRATEGY_REVIEW_REQUIRED"
STRATEGY_BLOCKED = "STRATEGY_BLOCKED"
STRATEGY_INSUFFICIENT_EVIDENCE = "STRATEGY_INSUFFICIENT_EVIDENCE"
STRATEGY_DUPLICATE_RISK = "STRATEGY_DUPLICATE_RISK"
STRATEGY_SUPERSEDED = "STRATEGY_SUPERSEDED"
STRATEGY_INVALID = "STRATEGY_INVALID"

STRATEGY_STATUSES = (
    STRATEGY_READY, STRATEGY_REVIEW_REQUIRED, STRATEGY_BLOCKED,
    STRATEGY_INSUFFICIENT_EVIDENCE, STRATEGY_DUPLICATE_RISK,
    STRATEGY_SUPERSEDED, STRATEGY_INVALID,
)
# 우선순위(가장 심각한 것이 이긴다) - content_engine.publish_audit의
# ERROR>ALREADY_PUBLISHED>SUPERSEDED>BLOCKED>NEEDS_HUMAN_REVIEW>READY
# 우선순위 패턴을 그대로 재사용한다(6-14/6-17 설계 원칙).
_STATUS_PRIORITY = {
    STRATEGY_INVALID: 0,
    STRATEGY_BLOCKED: 1,
    STRATEGY_SUPERSEDED: 2,
    STRATEGY_DUPLICATE_RISK: 3,
    STRATEGY_INSUFFICIENT_EVIDENCE: 4,
    STRATEGY_REVIEW_REQUIRED: 5,
    STRATEGY_READY: 6,
}

PLATFORMS = ("threads", "blog", "shorts")

EVIDENCE_SUFFICIENT = "SUFFICIENT"
EVIDENCE_INSUFFICIENT = "INSUFFICIENT"
EVIDENCE_MISSING = "MISSING"

NOVELTY_NO_MATCH = "NO_MATCH"
NOVELTY_POSSIBLE_DUPLICATE = "POSSIBLE_DUPLICATE"
NOVELTY_HIGH_DUPLICATE_RISK = "HIGH_DUPLICATE_RISK"

# --- 7장: Reason Codes(전부 사실 기반 - 추측/평가 문구를 넣지 않는다) -----------

SOURCE_MISSING = "SOURCE_MISSING"
SOURCE_WEAK = "SOURCE_WEAK"
EVIDENCE_INSUFFICIENT_CODE = "EVIDENCE_INSUFFICIENT"
HIGH_RISK_TOPIC = "HIGH_RISK_TOPIC"
DUPLICATE_RISK = "DUPLICATE_RISK"
RECENTLY_COVERED = "RECENTLY_COVERED"
SUPERSEDED_SOURCE = "SUPERSEDED_SOURCE"
PLATFORM_MISMATCH = "PLATFORM_MISMATCH"
KNOWLEDGE_NOT_APPROVED = "KNOWLEDGE_NOT_APPROVED"
ARTICLE_TYPE_UNKNOWN = "ARTICLE_TYPE_UNKNOWN"
CATEGORY_UNKNOWN = "CATEGORY_UNKNOWN"
DOMAIN_UNKNOWN = "DOMAIN_UNKNOWN"
MISSING_KNOWLEDGE_ID = "MISSING_KNOWLEDGE_ID"

# 10장: 고위험 주제 키워드. content_engine.blog_publish_pack.FINANCE_REVIEW_KEYWORDS
# (금융/대출/경매/부동산, 6-27에서 이미 검증됨)를 그대로 재사용하고, 이번에
# 지시된 세금/법률/투자/건강만 추가한다 - 기존 금융 안전장치를 다시 만들지
# 않는다.
HIGH_RISK_KEYWORDS = frozenset(FINANCE_REVIEW_KEYWORDS) | frozenset({"세금", "법률", "투자", "건강"})

# --- 12장: Content Angle(실제 본문을 생성하지 않고, 구조적 신호만으로 후보를
# 나열한다) ---------------------------------------------------------------------

ANGLE_FACT = "FACT"
ANGLE_EXPLANATION = "EXPLANATION"
ANGLE_ANALYSIS = "ANALYSIS"
ANGLE_PRACTICAL = "PRACTICAL"
ANGLE_QUESTION = "QUESTION"
ANGLE_SUMMARY = "SUMMARY"


def suggest_content_angles(knowledge: KnowledgeRecord) -> tuple[str, ...]:
    """KNOWLEDGE에 이미 채워진 필드만 보고 가능한 angle 후보를 나열한다 -
    실제 문장을 새로 만들지 않는다(13장 User Voice 보호와 동일한 원칙:
    AI가 표현을 대신 정하지 않는다)."""
    angles: list[str] = [ANGLE_FACT]
    if knowledge.lesson or knowledge.derived_insight:
        angles.append(ANGLE_EXPLANATION)
    if knowledge.judgment_rule or knowledge.opinion:
        angles.append(ANGLE_ANALYSIS)
    if knowledge.action or knowledge.result:
        angles.append(ANGLE_PRACTICAL)
    if knowledge.knowledge_type == "의견":
        angles.append(ANGLE_QUESTION)
    if knowledge.reusable_principle:
        angles.append(ANGLE_SUMMARY)
    return tuple(angles)


# --- 4장: Strategy Candidate -----------------------------------------------------


@dataclass(frozen=True)
class PlatformEligibility:
    """플랫폼 1개의 독립적인 적합성 판정. 다른 플랫폼과 점수를 합산하지
    않는다(5장) - 이 레코드 혼자로 완결된다."""

    platform: str
    status: str
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.platform not in PLATFORMS:
            raise MediaStrategyError(f"platform은 {PLATFORMS} 중 하나여야 합니다: {self.platform!r}")
        if self.status not in STRATEGY_STATUSES:
            raise MediaStrategyError(f"status는 {STRATEGY_STATUSES} 중 하나여야 합니다: {self.status!r}")

    def to_dict(self) -> dict[str, Any]:
        return {"platform": self.platform, "status": self.status, "reason_codes": list(self.reason_codes)}


@dataclass(frozen=True)
class MediaStrategyCandidate:
    """KNOWLEDGE 1건에 대한 전략 후보(4장). "추천"이지 "자동 발행"이
    아니다 - WHY THIS CONTENT / WHY THIS PLATFORM / WHY HUMAN REVIEW를
    설명하기 위한 근거 묶음이다."""

    knowledge_id: str
    source_url: str
    topic: str
    category: str
    domain: str
    article_type: str | None
    platform_eligibility: tuple[PlatformEligibility, ...]
    risk_flags: tuple[str, ...]
    evidence_quality: str
    novelty_signal: str
    human_review_required: bool
    reason_codes: tuple[str, ...]
    status: str
    content_angles: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.status not in STRATEGY_STATUSES:
            raise MediaStrategyError(f"status는 {STRATEGY_STATUSES} 중 하나여야 합니다: {self.status!r}")

    def eligibility_for(self, platform: str) -> PlatformEligibility | None:
        for item in self.platform_eligibility:
            if item.platform == platform:
                return item
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "knowledge_id": self.knowledge_id,
            "source_url": self.source_url,
            "topic": self.topic,
            "category": self.category,
            "domain": self.domain,
            "article_type": self.article_type,
            "platform_eligibility": [item.to_dict() for item in self.platform_eligibility],
            "risk_flags": list(self.risk_flags),
            "evidence_quality": self.evidence_quality,
            "novelty_signal": self.novelty_signal,
            "human_review_required": self.human_review_required,
            "reason_codes": list(self.reason_codes),
            "status": self.status,
            "content_angles": list(self.content_angles),
        }


# --- 11장: Source / Evidence -----------------------------------------------------


def _assess_evidence(knowledge: KnowledgeRecord) -> tuple[str, tuple[str, ...]]:
    """source_url/evidence의 존재/형식만 확인한다 - 내용을 채우거나
    추측하지 않는다."""
    reasons: list[str] = []
    if not knowledge.source_url:
        reasons.append(SOURCE_MISSING)
    elif not (knowledge.source_url.startswith("http://") or knowledge.source_url.startswith("https://")):
        reasons.append(SOURCE_WEAK)

    if not knowledge.evidence:
        reasons.append(EVIDENCE_INSUFFICIENT_CODE)

    if SOURCE_MISSING in reasons and EVIDENCE_INSUFFICIENT_CODE in reasons:
        quality = EVIDENCE_MISSING
    elif reasons:
        quality = EVIDENCE_INSUFFICIENT
    else:
        quality = EVIDENCE_SUFFICIENT
    return quality, tuple(reasons)


# --- 8장: Duplicate / Novelty ------------------------------------------------------


def _normalize_title(title: str) -> str:
    # tak_scout.collector._normalize_title()과 동일한 원칙(공백 정규화 +
    # 소문자화)을 이 모듈 안에서 독립적으로 구현한다 - SCOUT 패키지의 비공개
    # 함수를 패키지 경계 너머로 직접 import하지 않는다(기존 관례 유지).
    return " ".join(title.strip().lower().split())


def assess_novelty(
    knowledge: KnowledgeRecord,
    *,
    other_knowledge: list[KnowledgeRecord] = (),
    production_records: list[MediaArchiveRecord] = (),
) -> tuple[str, tuple[str, ...]]:
    """이 KNOWLEDGE와 같은 source_url/제목을 가진 기존 KNOWLEDGE/Production
    레코드가 있는지 확인한다. 동일 source_url이라도 자동으로 차단하지
    않는다 - NO_MATCH/POSSIBLE_DUPLICATE/HIGH_DUPLICATE_RISK 3단계로만
    구분해 사람이 최종 판단하게 한다(8장)."""
    normalized_title = _normalize_title(knowledge.title)
    same_url_other_knowledge = [
        k for k in other_knowledge if k.id != knowledge.id and k.source_url == knowledge.source_url and knowledge.source_url
    ]
    same_title_other_knowledge = [
        k for k in other_knowledge if k.id != knowledge.id and _normalize_title(k.title) == normalized_title and normalized_title
    ]
    same_url_production = [
        r for r in production_records if r.knowledge_id != knowledge.id and r.source_url == knowledge.source_url and knowledge.source_url
    ]

    if (same_url_other_knowledge and same_title_other_knowledge) or (same_url_production and same_title_other_knowledge):
        return NOVELTY_HIGH_DUPLICATE_RISK, (DUPLICATE_RISK,)
    if same_url_other_knowledge or same_title_other_knowledge or same_url_production:
        return NOVELTY_POSSIBLE_DUPLICATE, (RECENTLY_COVERED,)
    return NOVELTY_NO_MATCH, ()


# --- 9장: Superseded -----------------------------------------------------------


def _is_superseded_source(knowledge_id: str, production_records: list[MediaArchiveRecord]) -> bool:
    """이 knowledge_id에서 나온 Production 레코드가 하나 이상 있고, 그
    전부가 superseded 상태면 True. 아직 Production 레코드가 없는
    KNOWLEDGE는(정상적인 신규 후보) False다 - "생성된 적이 없다"와
    "생성됐지만 전부 superseded됐다"를 구분한다."""
    related = [r for r in production_records if r.knowledge_id == knowledge_id]
    if not related:
        return False
    return all(r.review_status == "superseded" for r in related)


# --- 10장: High-Risk Topic --------------------------------------------------------


def _high_risk_flags(knowledge: KnowledgeRecord) -> tuple[str, ...]:
    """category/domain(SCOUT/사람이 붙인 성격 태그)만 검사한다 -
    article_type으로 고위험 여부를 판단하지 않는다(6-04/6-32에서 이미
    확인한 "category로 article_type을 유추하지 않는다"는 원칙을 거꾸로도
    지킨다: 여기서도 article_type을 category 대용으로 쓰지 않는다).
    category/domain/article_type을 서로 독립적으로 유지한다."""
    flags = []
    if knowledge.category and knowledge.category in HIGH_RISK_KEYWORDS:
        flags.append(HIGH_RISK_TOPIC)
    elif knowledge.domain and any(keyword in knowledge.domain for keyword in HIGH_RISK_KEYWORDS):
        flags.append(HIGH_RISK_TOPIC)
    return tuple(flags)


# --- 5장: Platform Eligibility(각 플랫폼을 독립적으로 판단) ------------------------


def _evaluate_platform(
    platform: str, knowledge: KnowledgeRecord, *, base_status: str, base_reasons: tuple[str, ...]
) -> PlatformEligibility:
    """base_status(BLOCKED/SUPERSEDED/DUPLICATE_RISK/INSUFFICIENT_EVIDENCE 등
    KNOWLEDGE 수준에서 이미 확정된 상태)를 모든 플랫폼이 바닥으로 공유한다 -
    이 상태들은 콘텐츠 자체의 유효성 문제이므로 플랫폼과 무관하게 전파되는
    것이 맞다(9-16장 예시: 고위험 KNOWLEDGE는 Threads/Blog/Shorts 전부
    REVIEW_REQUIRED). base_status가 STRATEGY_READY일 때만 플랫폼별 추가
    신호(간단한 분량 휴리스틱, NLP 아님)를 독립적으로 반영한다."""
    if base_status != STRATEGY_READY:
        return PlatformEligibility(platform=platform, status=base_status, reason_codes=base_reasons)

    combined_text = " ".join(
        value for value in (knowledge.lesson, knowledge.experience, knowledge.reusable_principle, knowledge.derived_insight) if value
    )
    text_length = len(combined_text)
    evidence_count = len(knowledge.evidence)

    if platform == "threads":
        # Threads: 짧은 주장/관찰만으로도 충분하다 - evidence 1건 이상이면 READY.
        if evidence_count == 0:
            return PlatformEligibility(platform="threads", status=STRATEGY_REVIEW_REQUIRED, reason_codes=(PLATFORM_MISMATCH,))
        return PlatformEligibility(platform="threads", status=STRATEGY_READY)

    if platform == "blog":
        # Blog: 검색 의도/설명 가능성을 위해 최소한의 설명 분량이 필요하다
        # (단순 길이 휴리스틱 - 복잡한 NLP를 쓰지 않는다, 12장과 동일한 절제 원칙).
        if text_length < 80:
            return PlatformEligibility(platform="blog", status=STRATEGY_REVIEW_REQUIRED, reason_codes=(PLATFORM_MISMATCH,))
        return PlatformEligibility(platform="blog", status=STRATEGY_READY)

    # shorts: 카드뉴스 3~5포인트로 나눌 수 있을 만큼 evidence/서술이 있어야 한다.
    if evidence_count < 1 and text_length < 40:
        return PlatformEligibility(platform="shorts", status=STRATEGY_REVIEW_REQUIRED, reason_codes=(PLATFORM_MISMATCH,))
    return PlatformEligibility(platform="shorts", status=STRATEGY_READY)


# --- 3장/6장: 전체 평가 진입점 -----------------------------------------------------


def evaluate_media_strategy(
    knowledge: KnowledgeRecord,
    *,
    production_records: list[MediaArchiveRecord] = (),
    other_knowledge: list[KnowledgeRecord] = (),
) -> MediaStrategyCandidate:
    """KNOWLEDGE 1건을 평가해 MediaStrategyCandidate를 만든다. 파일을
    읽거나 쓰지 않는 순수 함수다 - 호출부가 production_records/
    other_knowledge를 미리 로드해 넘긴다(``content_engine.publish_audit``와
    동일한 관례)."""
    if not knowledge.id:
        return MediaStrategyCandidate(
            knowledge_id="", source_url=knowledge.source_url, topic=knowledge.title,
            category=knowledge.category or "", domain=knowledge.domain or "",
            article_type=knowledge.article_type, platform_eligibility=(),
            risk_flags=(), evidence_quality=EVIDENCE_MISSING, novelty_signal=NOVELTY_NO_MATCH,
            human_review_required=True, reason_codes=(MISSING_KNOWLEDGE_ID,), status=STRATEGY_INVALID,
        )

    reason_codes: list[str] = []
    risk_flags: list[str] = []

    # 1. 승인 여부(최우선 - 승인되지 않은 KNOWLEDGE는 그 무엇도 평가할 수 없다)
    if knowledge.knowledge_review_status != "approved":
        reason_codes.append(KNOWLEDGE_NOT_APPROVED)
        status = STRATEGY_BLOCKED
    else:
        status = STRATEGY_READY  # 아래에서 하향 조정될 수 있다.

    # 2. Superseded(9장)
    superseded = _is_superseded_source(knowledge.id, list(production_records))
    if superseded and status != STRATEGY_BLOCKED:
        reason_codes.append(SUPERSEDED_SOURCE)
        status = STRATEGY_SUPERSEDED

    # 3. Duplicate/Novelty(8장)
    novelty_signal, novelty_reasons = assess_novelty(
        knowledge, other_knowledge=list(other_knowledge), production_records=list(production_records)
    )
    reason_codes.extend(r for r in novelty_reasons if r not in reason_codes)
    if novelty_signal == NOVELTY_HIGH_DUPLICATE_RISK and _STATUS_PRIORITY[STRATEGY_DUPLICATE_RISK] < _STATUS_PRIORITY[status]:
        status = STRATEGY_DUPLICATE_RISK

    # 4. Source/Evidence(11장)
    evidence_quality, evidence_reasons = _assess_evidence(knowledge)
    reason_codes.extend(r for r in evidence_reasons if r not in reason_codes)
    if evidence_quality in (EVIDENCE_MISSING, EVIDENCE_INSUFFICIENT) and _STATUS_PRIORITY[STRATEGY_INSUFFICIENT_EVIDENCE] < _STATUS_PRIORITY[status]:
        status = STRATEGY_INSUFFICIENT_EVIDENCE

    # 5. High-risk topic(10장) - 차단하지 않고 사람 확인을 요구한다.
    risk_flags.extend(_high_risk_flags(knowledge))
    human_review_required = bool(risk_flags) or novelty_signal == NOVELTY_POSSIBLE_DUPLICATE
    if risk_flags:
        reason_codes.append(HIGH_RISK_TOPIC) if HIGH_RISK_TOPIC not in reason_codes else None
    if human_review_required and _STATUS_PRIORITY[STRATEGY_REVIEW_REQUIRED] < _STATUS_PRIORITY[status]:
        status = STRATEGY_REVIEW_REQUIRED

    # 6. 정보성 reason code(차단하지 않음, 6-04/6-32 원칙 - category로
    #    article_type을 유추하지 않는다. 이 코드들은 사실 기록일 뿐이다.)
    if knowledge.article_type is None:
        reason_codes.append(ARTICLE_TYPE_UNKNOWN)
    if not knowledge.category or knowledge.category == "기타":
        reason_codes.append(CATEGORY_UNKNOWN)
    if not knowledge.domain or knowledge.domain == "기타":
        reason_codes.append(DOMAIN_UNKNOWN)

    platform_eligibility = tuple(
        _evaluate_platform(platform, knowledge, base_status=status, base_reasons=tuple(reason_codes))
        for platform in PLATFORMS
    )

    return MediaStrategyCandidate(
        knowledge_id=knowledge.id,
        source_url=knowledge.source_url,
        topic=knowledge.title,
        category=knowledge.category or "",
        domain=knowledge.domain or "",
        article_type=knowledge.article_type,
        platform_eligibility=platform_eligibility,
        risk_flags=tuple(risk_flags),
        evidence_quality=evidence_quality,
        novelty_signal=novelty_signal,
        human_review_required=human_review_required,
        reason_codes=tuple(reason_codes),
        status=status,
        content_angles=suggest_content_angles(knowledge),
    )


# --- 14장: Generation Handoff -----------------------------------------------------


def build_generation_handoff(candidate: MediaStrategyCandidate, knowledge: KnowledgeRecord) -> dict[str, Any]:
    """Strategy Gate 결과 + 원본 KNOWLEDGE를 하나로 묶은 handoff 구조를
    만든다. **이 함수는 MEDIA를 생성하지 않는다** - 순수 데이터 조합일
    뿐이다("strategy READY != 자동 generation", 15장). ``knowledge``
    필드는 기존 ``content_engine.pipeline.generate_content_bundle()``이
    그대로 받는 형태(KnowledgeRecord)를 아무 변형 없이 담는다 - 기존
    generator를 다시 작성하지 않고, 이 handoff가 어댑터 역할만 한다."""
    if candidate.knowledge_id and knowledge.id != candidate.knowledge_id:
        raise MediaStrategyError(
            f"candidate.knowledge_id({candidate.knowledge_id!r})와 knowledge.id({knowledge.id!r})가 일치하지 않습니다."
        )
    return {
        "knowledge": knowledge,
        "strategy_candidate": candidate,
        "platform_eligibility": {item.platform: item.status for item in candidate.platform_eligibility},
        "risk_flags": candidate.risk_flags,
        "evidence_quality": candidate.evidence_quality,
        "human_review_required": candidate.human_review_required,
        "generation_permitted": candidate.status == STRATEGY_READY,
    }
