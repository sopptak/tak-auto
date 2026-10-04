"""MarketingBrief 빈칸 제안(Element Suggestion). 근거 기반 추출만 하며 확정하지 않는다.

원칙:
    - 제안 값은 evidence의 snippet을 그대로(길이만 자르고) 인용하는 형식이다. 문장을 새로 지어내지 않으므로
      존재하지 않는 통계/후기/시장 규모/거래/가격/사회적 증거가 생길 수 없다.
    - 근거(evidence)가 없는 요소는 제안 자체를 만들지 않는다. 예외는 플랫폼 전략에서 오는 '구조' 요소
      (distribution.distribution_angle 등)뿐이며 basis="strategy"로 구분되고 사실 주장이 아니다.
    - 이미 채워진 요소는 제안하지 않는다(사람의 입력 우선).
    - 모든 제안은 requires_human_review=True, status="suggested"로 시작한다. 반영은 사람이 accept할 때만 일어난다.
    - social_proof/proof/offer 가격 등 '사실처럼 보이는' 요소는 해당 aspect 출처가 있을 때만, 인용 형태로 제안한다.
      mock Provider 출처는 신뢰도를 최저로 낮춘다.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
import hashlib
from typing import Any

from .models import DIMENSIONS, EvidenceItem, MarketingBrief, MarketingError
from .platforms import STRATEGIES

SUGGESTION_STATUSES = ("suggested", "accepted", "rejected")
BASIS_EVIDENCE = "evidence"
BASIS_STRATEGY = "strategy"
MAX_QUOTE = 160
MOCK_PROVIDERS = ("mock",)

# (aspect, 제안할 요소, 인용 라벨). 요소 키는 "dimension.element" 또는 "brief.<field>".
EVIDENCE_RULES: tuple[tuple[str, str, str], ...] = (
    ("customer_problem", "brief.customer_problem", "조사된 고객 문제"),
    ("customer_problem", "psychology.pain", "고객이 겪는 문제"),
    ("customer_problem", "sales.customer_problem", "조사된 고객 문제"),
    ("search_intent", "distribution.search_intent", "검색 의도"),
    ("recurring_questions", "psychology.curiosity", "반복해서 나오는 질문"),
    ("competitor_positioning", "sales.value_proposition", "경쟁자 포지셔닝(차별화 필요)"),
    ("competitors", "sales.objection", "비교 대상/대안"),
    ("pricing_signals", "sales.offer", "관찰된 가격 신호(참고용)"),
    ("market_demand", "psychology.desire", "시장 수요 신호"),
    ("content_angles", "storytelling.hook", "반응이 있는 콘텐츠 앵글"),
)


@dataclass(frozen=True)
class Suggestion:
    suggestion_id: str
    brief_id: str
    dimension: str  # psychology|storytelling|sales|design|distribution|brief
    element: str
    suggested_value: str
    evidence_ids: tuple[str, ...]
    rationale: str
    confidence: float  # 0~1
    basis: str = BASIS_EVIDENCE
    status: str = "suggested"
    requires_human_review: bool = True

    def __post_init__(self) -> None:
        if self.status not in SUGGESTION_STATUSES:
            raise MarketingError(f"알 수 없는 suggestion status: {self.status!r}")
        if not self.requires_human_review:
            raise MarketingError("suggestion은 항상 사람의 검토가 필요합니다.")
        if not self.suggested_value.strip():
            raise MarketingError("빈 제안 값은 만들 수 없습니다.")
        if self.basis == BASIS_EVIDENCE and not self.evidence_ids:
            raise MarketingError("근거 기반 제안에는 evidence_ids가 필요합니다.")
        if not 0.0 <= self.confidence <= 1.0:
            raise MarketingError("confidence는 0~1 범위여야 합니다.")

    @property
    def key(self) -> str:
        return f"{self.dimension}.{self.element}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "suggestion_id": self.suggestion_id, "brief_id": self.brief_id, "dimension": self.dimension,
            "element": self.element, "suggested_value": self.suggested_value, "evidence_ids": list(self.evidence_ids),
            "rationale": self.rationale, "confidence": self.confidence, "basis": self.basis, "status": self.status,
            "requires_human_review": self.requires_human_review,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Suggestion":
        try:
            return cls(
                suggestion_id=str(data["suggestion_id"]), brief_id=str(data["brief_id"]),
                dimension=str(data["dimension"]), element=str(data["element"]),
                suggested_value=str(data["suggested_value"]), evidence_ids=tuple(data.get("evidence_ids") or ()),
                rationale=str(data.get("rationale") or ""), confidence=float(data.get("confidence", 0.0)),
                basis=str(data.get("basis") or BASIS_EVIDENCE), status=str(data.get("status") or "suggested"),
                requires_human_review=bool(data.get("requires_human_review", True)),
            )
        except (KeyError, TypeError, ValueError) as error:
            if isinstance(error, MarketingError):
                raise
            raise MarketingError(f"suggestion 구조 오류: {error}") from error


def split_key(key: str) -> tuple[str, str]:
    dimension, _, element = key.partition(".")
    if dimension == "brief":
        if element not in ("target_audience", "customer_problem", "desired_action"):
            raise MarketingError(f"알 수 없는 브리프 필드: {key}")
        return dimension, element
    if dimension not in DIMENSIONS or element not in DIMENSIONS[dimension].element_names():
        raise MarketingError(f"알 수 없는 요소: {key!r} (형식: dimension.element)")
    return dimension, element


def current_value(brief: MarketingBrief, key: str) -> str:
    dimension, element = split_key(key)
    holder = brief if dimension == "brief" else brief.dimension(dimension)
    return getattr(holder, element).strip()


def _quote(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= MAX_QUOTE else text[: MAX_QUOTE - 1].rstrip() + "…"


def _confidence(items: Sequence[EvidenceItem]) -> float:
    """출처 수/다양성으로 0~0.6. 검증 전 근거이므로 0.6을 넘지 않으며 mock 출처는 0.1이다."""
    if all(item.provider in MOCK_PROVIDERS for item in items):
        return 0.1
    distinct = {item.url or item.title for item in items}
    return round(min(0.6, 0.25 + 0.1 * (len(distinct) - 1)), 2)


def suggest_elements(brief: MarketingBrief, extra_evidence: Sequence[EvidenceItem] = ()) -> list[Suggestion]:
    """빈 요소에 대한 근거 기반 제안 목록. 근거가 없으면 빈 목록이다."""
    evidence = [*brief.evidence, *extra_evidence]
    by_aspect: dict[str, list[EvidenceItem]] = {}
    for item in evidence:
        if item.snippet.strip():
            by_aspect.setdefault(item.aspect or item.kind, []).append(item)

    suggestions: list[Suggestion] = []
    for aspect, key, label in EVIDENCE_RULES:
        items = by_aspect.get(aspect)
        if not items or current_value(brief, key):
            continue
        dimension, element = split_key(key)
        top = items[0]
        value = f"{label}: {_quote(top.snippet)}"
        suggestions.append(Suggestion(
            suggestion_id=_suggestion_id(brief.brief_id, key, [item.evidence_id for item in items]),
            brief_id=brief.brief_id, dimension=dimension, element=element, suggested_value=value,
            evidence_ids=tuple(dict.fromkeys(item.evidence_id for item in items[:3])),
            rationale=f"{aspect} 조사 결과 {len(items)}건의 출처에서 인용({top.provider or top.kind}). 검증 전 근거입니다.",
            confidence=_confidence(items),
        ))

    strategy = STRATEGIES.get(brief.platform)
    if strategy is not None:
        structural = {
            "distribution.distribution_angle": strategy.angle,
            "distribution.target_platform": strategy.platform,
        }
        for key, value in structural.items():
            if current_value(brief, key):
                continue
            dimension, element = split_key(key)
            suggestions.append(Suggestion(
                suggestion_id=_suggestion_id(brief.brief_id, key, [strategy.platform]),
                brief_id=brief.brief_id, dimension=dimension, element=element, suggested_value=value,
                evidence_ids=(), rationale=f"{strategy.platform} 플랫폼 전략의 구조 기본값(사실 주장이 아님).",
                confidence=0.5, basis=BASIS_STRATEGY,
            ))
    return suggestions


def _suggestion_id(brief_id: str, key: str, parts: Sequence[str]) -> str:
    raw = "|".join([brief_id, key, *parts])
    return "sug-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:14]


def apply_suggestion(brief: MarketingBrief, suggestion: Suggestion) -> MarketingBrief:
    """사람이 accept한 제안을 브리프에 반영한다(이미 값이 있으면 거부)."""
    if suggestion.brief_id != brief.brief_id:
        raise MarketingError("다른 브리프의 제안입니다.")
    if current_value(brief, suggestion.key):
        raise MarketingError(f"{suggestion.key}에는 이미 값이 있습니다. set으로 직접 수정하세요.")
    from .editing import set_element
    return set_element(brief, suggestion.key, suggestion.suggested_value)


def with_status(suggestion: Suggestion, status: str) -> Suggestion:
    if status not in SUGGESTION_STATUSES:
        raise MarketingError(f"알 수 없는 suggestion status: {status!r}")
    return replace(suggestion, status=status)
