"""Market Demand 표준 모델: 시장 수요 데이터 -> 기회 점수 -> 사업 아이디어 후보.

외부 마켓플레이스의 응답 형식을 콘텐츠 엔진 전체에 퍼뜨리지 않기 위해, 모든 소스는
``MarketDemand``로 정규화된다. 점수는 근거(evidence)와 함께 결정적으로 계산되며, 알 수 없는
요소는 0점으로 취급하지 않고 None으로 두어 confidence에 반영한다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import hashlib
from typing import Any

IDEA_CANDIDATE = "candidate"
IDEA_ACCEPTED = "accepted"
IDEA_REJECTED = "rejected"
IDEA_STATUSES = (IDEA_CANDIDATE, IDEA_ACCEPTED, IDEA_REJECTED)

SCORE_FACTORS = ("transaction", "price", "recurring", "competition", "automation", "fit")


class MarketDemandError(ValueError):
    """시장 수요 데이터/저장소가 예상한 구조가 아닐 때 발생한다."""


def _signal(value: Any, name: str) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise MarketDemandError(f"{name}은(는) 0~1 숫자여야 합니다: {value!r}") from error
    if not 0.0 <= number <= 1.0:
        raise MarketDemandError(f"{name}은(는) 0~1 범위여야 합니다: {value!r}")
    return number


@dataclass(frozen=True)
class MarketDemand:
    demand_id: str
    source: str
    title: str
    category: str = ""
    description: str = ""
    price: float | None = None
    currency: str = "USD"
    demand_signal: float | None = None  # 0~1, 모르면 None
    competition_signal: float | None = None  # 0~1(높을수록 경쟁이 치열), 모르면 None
    url: str = ""
    collected_at: str = ""
    # 예: verified_transaction(bool), recurring(bool), monthly_revenue, input_method("manual"|...)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.source.strip() or not self.title.strip():
            raise MarketDemandError("source와 title은 필수입니다.")
        if self.price is not None and self.price < 0:
            raise MarketDemandError("price는 음수일 수 없습니다.")
        _signal(self.demand_signal, "demand_signal")
        _signal(self.competition_signal, "competition_signal")

    def to_dict(self) -> dict[str, Any]:
        return {
            "demand_id": self.demand_id, "source": self.source, "title": self.title, "category": self.category,
            "description": self.description, "price": self.price, "currency": self.currency,
            "demand_signal": self.demand_signal, "competition_signal": self.competition_signal,
            "url": self.url, "collected_at": self.collected_at, "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MarketDemand":
        try:
            price = data.get("price")
            return cls(
                demand_id=str(data["demand_id"]), source=str(data["source"]), title=str(data["title"]),
                category=str(data.get("category") or ""), description=str(data.get("description") or ""),
                price=None if price in (None, "") else float(price), currency=str(data.get("currency") or "USD"),
                demand_signal=_signal(data.get("demand_signal"), "demand_signal"),
                competition_signal=_signal(data.get("competition_signal"), "competition_signal"),
                url=str(data.get("url") or ""), collected_at=str(data.get("collected_at") or ""),
                metadata=dict(data.get("metadata") or {}),
            )
        except KeyError as error:
            raise MarketDemandError(f"필수 필드가 없습니다: {error}") from error
        except (TypeError, ValueError) as error:
            if isinstance(error, MarketDemandError):
                raise
            raise MarketDemandError(f"잘못된 값: {error}") from error


def compute_demand_id(source: str, title: str, url: str = "") -> str:
    raw = f"{source.strip().lower()}|{(url or title).strip().lower()}"
    return "demand-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class OpportunityScore:
    total: float  # 0~100, 알려진 요소만으로 가중 평균
    confidence: float  # 0~1, 알려진 요소의 가중치 비율
    factors: Mapping[str, float | None]  # 요소별 0~100, 근거 없으면 None
    evidence: Mapping[str, str]  # 요소별 점수 근거(사람이 검토할 수 있게)

    def to_dict(self) -> dict[str, Any]:
        return {"total": self.total, "confidence": self.confidence, "factors": dict(self.factors),
                "evidence": dict(self.evidence)}


@dataclass(frozen=True)
class IdeaCandidate:
    idea_id: str
    title: str
    category: str
    score: float
    confidence: float
    demand_ids: tuple[str, ...]
    sources: tuple[str, ...]
    rationale: str
    research_query: str  # 리서치 Provider(content_engine.providers)로 검증할 질의
    status: str = IDEA_CANDIDATE
    created_at: str = ""

    def __post_init__(self) -> None:
        if self.status not in IDEA_STATUSES:
            raise MarketDemandError(f"알 수 없는 status: {self.status!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "idea_id": self.idea_id, "title": self.title, "category": self.category, "score": self.score,
            "confidence": self.confidence, "demand_ids": list(self.demand_ids), "sources": list(self.sources),
            "rationale": self.rationale, "research_query": self.research_query, "status": self.status,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "IdeaCandidate":
        try:
            return cls(
                idea_id=str(data["idea_id"]), title=str(data["title"]), category=str(data.get("category") or ""),
                score=float(data["score"]), confidence=float(data.get("confidence", 0.0)),
                demand_ids=tuple(data.get("demand_ids") or ()), sources=tuple(data.get("sources") or ()),
                rationale=str(data.get("rationale") or ""), research_query=str(data.get("research_query") or ""),
                status=str(data.get("status") or IDEA_CANDIDATE), created_at=str(data.get("created_at") or ""),
            )
        except (KeyError, TypeError, ValueError) as error:
            if isinstance(error, MarketDemandError):
                raise
            raise MarketDemandError(f"아이디어 후보 구조 오류: {error}") from error
