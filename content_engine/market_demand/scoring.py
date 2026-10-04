"""OpportunityScore 계산(결정적, 네트워크/LLM 없음).

요소(각 0~100, 근거 없으면 None):
    transaction  실제 거래 여부(metadata.verified_transaction / sold)
    price        가격 수준(USD 환산 가능할 때만)
    recurring    반복 수요 가능성(metadata.recurring / monthly_revenue / 키워드)
    competition  경쟁 정도(경쟁이 낮을수록 높음; competition_signal 반전)
    automation   AI 자동화 가능성(키워드 규칙)
    fit          TAK AUTO가 만들 수 있는 콘텐츠/서비스와의 적합성(키워드 규칙)

모르는 요소는 0점이 아니라 None이며 total은 알려진 요소의 가중 평균, confidence는 알려진 가중치
비율이다. 키워드 규칙은 1차 필터일 뿐이며 최종 판단은 사람이 한다(근거는 evidence에 남는다).
"""

from __future__ import annotations

import math

from .models import MarketDemand, OpportunityScore, SCORE_FACTORS

WEIGHTS = {"transaction": 0.25, "price": 0.15, "recurring": 0.15, "competition": 0.15, "automation": 0.15, "fit": 0.15}
_KRW_PER_USD = 1400.0
_TRUE = (True, "true", "yes", "y", "1", 1)

AUTOMATION_KEYWORDS = (
    "newsletter", "뉴스레터", "blog", "블로그", "content", "콘텐츠", "seo", "template", "템플릿", "summary", "요약",
    "report", "리포트", "directory", "데이터", "curation", "큐레이션", "ai ", " ai", "automation", "자동화",
    "transcri", "번역", "translation", "script", "대본", "shorts", "쇼츠", "social", "thread",
)
FIT_KEYWORDS = (
    "blog", "블로그", "newsletter", "뉴스레터", "shorts", "쇼츠", "threads", "youtube", "유튜브", "content",
    "콘텐츠", "seo", "video script", "대본", "social media", "소셜", "finance", "금융", "대출", "자기계발",
    "직장", "ai tool", "ai 활용",
)
RECURRING_KEYWORDS = ("subscription", "구독", "recurring", "monthly", "월간", "newsletter", "뉴스레터", "saas", "membership")


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, value))


def _text(demand: MarketDemand) -> str:
    return f" {demand.title} {demand.category} {demand.description} ".lower()


def _hits(text: str, keywords: tuple[str, ...]) -> list[str]:
    return [keyword.strip() for keyword in keywords if keyword in text]


def _price_usd(demand: MarketDemand) -> float | None:
    if demand.price is None:
        return None
    currency = demand.currency.upper()
    if currency == "USD":
        return demand.price
    if currency == "KRW":
        return demand.price / _KRW_PER_USD
    return None


def score_demand(demand: MarketDemand) -> OpportunityScore:
    meta = demand.metadata
    text = _text(demand)
    factors: dict[str, float | None] = {name: None for name in SCORE_FACTORS}
    evidence: dict[str, str] = {}

    transaction = meta.get("verified_transaction", meta.get("sold"))
    if transaction is not None:
        verified = transaction in _TRUE
        factors["transaction"] = 100.0 if verified else 20.0
        evidence["transaction"] = "실제 거래 확인됨" if verified else "거래 확인 안 됨(리스팅/게시 수준)"

    usd = _price_usd(demand)
    if usd is not None:
        # $10 -> 약 33, $100 -> 약 67, $1,000 이상 -> 100
        factors["price"] = _clamp(math.log10(max(usd, 1.0)) / 3.0 * 100.0)
        evidence["price"] = f"약 ${usd:,.0f}"

    recurring = meta.get("recurring")
    revenue = meta.get("monthly_revenue")
    recurring_hits = _hits(text, RECURRING_KEYWORDS)
    if recurring is not None:
        factors["recurring"] = 90.0 if recurring in _TRUE else 20.0
        evidence["recurring"] = f"recurring={recurring}"
    elif revenue not in (None, ""):
        factors["recurring"] = 80.0
        evidence["recurring"] = f"월 매출 {revenue} 보고됨"
    elif recurring_hits:
        factors["recurring"] = 60.0
        evidence["recurring"] = "키워드: " + ", ".join(recurring_hits[:3])
    elif demand.demand_signal is not None:
        factors["recurring"] = _clamp(demand.demand_signal * 100.0)
        evidence["recurring"] = f"demand_signal={demand.demand_signal:.2f}로 대체"

    if demand.competition_signal is not None:
        factors["competition"] = _clamp((1.0 - demand.competition_signal) * 100.0)
        evidence["competition"] = f"competition_signal={demand.competition_signal:.2f}"

    if text.strip():
        auto_hits = _hits(text, AUTOMATION_KEYWORDS)
        factors["automation"] = _clamp(25.0 + 25.0 * len(auto_hits)) if auto_hits else 20.0
        evidence["automation"] = ("키워드: " + ", ".join(auto_hits[:4])) if auto_hits else "자동화 관련 키워드 없음"
        fit_hits = _hits(text, FIT_KEYWORDS)
        factors["fit"] = _clamp(25.0 + 25.0 * len(fit_hits)) if fit_hits else 15.0
        evidence["fit"] = ("키워드: " + ", ".join(fit_hits[:4])) if fit_hits else "TAK 콘텐츠/서비스와 겹치는 키워드 없음"

    known = {name: value for name, value in factors.items() if value is not None}
    weight_sum = sum(WEIGHTS[name] for name in known)
    total = sum(WEIGHTS[name] * value for name, value in known.items()) / weight_sum if weight_sum else 0.0
    return OpportunityScore(total=round(total, 1), confidence=round(weight_sum / sum(WEIGHTS.values()), 2),
                            factors=factors, evidence=evidence)
