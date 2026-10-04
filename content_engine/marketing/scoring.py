"""MarketingScore: 결정적 규칙 기반 점수(LLM/네트워크 없음).

- 요소 품질(0~100): 비어 있으면 결측(None), 채워졌으면 50 + 구체성 보너스(길이 25, 숫자/4단어 이상 25).
- 5개 관점 점수 = 채워진 요소 품질의 평균. 결측은 0점이 아니라 제외되고 confidence를 낮춘다.
- 조회수 가능성과 판매 가능성을 분리한다: attention / engagement / conversion 세 축은
  ``AXIS_WEIGHTS`` 표의 (관점.요소, 가중치)로 따로 계산한다. 같은 요소도 축마다 다른 비중을 갖는다.
- total은 단순 평균이 아니라 관점 평균(60%)과 가장 약한 축(40%)의 혼합이어서 한 축만 강한
  브리프가 높게 나오지 않는다. 대신 ``profile``이 "조회형/전환형"을 구분해 보여준다.
키워드 규칙이 아니라 '구조가 채워졌는지와 구체성'만 본다 - 내용의 질은 사람이 검토한다.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from .models import DIMENSIONS, MarketingBrief

AXIS_WEIGHTS: dict[str, dict[str, float]] = {
    "attention": {
        "psychology.attention": 1.0, "psychology.curiosity": 0.8, "psychology.urgency": 0.6,
        "psychology.loss_aversion": 0.6, "storytelling.hook": 1.0, "design.visual_hook": 1.0,
        "design.thumbnail_concept": 0.8, "distribution.discovery_keyword": 0.6,
        "distribution.search_intent": 0.5, "distribution.distribution_angle": 0.4,
    },
    "engagement": {
        "psychology.identification": 1.0, "psychology.pain": 0.6, "psychology.curiosity": 0.6,
        "psychology.social_proof": 0.5, "storytelling.problem": 0.6, "storytelling.tension": 1.0,
        "storytelling.insight": 1.0, "storytelling.transformation": 0.8, "design.readability": 0.8,
        "design.information_hierarchy": 0.6, "distribution.audience": 0.5,
        "brief.target_audience": 0.5, "brief.customer_problem": 0.6,
    },
    "conversion": {
        "psychology.trust": 1.0, "psychology.desire": 1.0, "psychology.social_proof": 0.8,
        "psychology.urgency": 0.5, "psychology.loss_aversion": 0.5, "storytelling.call_to_action": 0.7,
        "storytelling.conclusion": 0.3, "sales.target_customer": 0.6, "sales.customer_problem": 0.8,
        "sales.value_proposition": 1.0, "sales.benefit": 0.8, "sales.objection": 1.0, "sales.proof": 1.0,
        "sales.offer": 1.0, "sales.call_to_action": 1.0, "sales.conversion_goal": 1.0,
        "brief.desired_action": 1.0, "brief.customer_problem": 0.8,
    },
}

# 플랫폼별로 어떤 관점이 더 중요한지(합이 1일 필요 없음, 가중 평균에만 쓰임).
PLATFORM_DIMENSION_WEIGHTS: dict[str, dict[str, float]] = {
    "": {name: 1.0 for name in DIMENSIONS},
    "blog": {"psychology": 0.8, "storytelling": 0.8, "sales": 1.2, "design": 0.6, "distribution": 1.4},
    "threads": {"psychology": 1.3, "storytelling": 1.0, "sales": 0.7, "design": 0.4, "distribution": 1.0},
    "shorts": {"psychology": 1.2, "storytelling": 1.0, "sales": 0.6, "design": 1.4, "distribution": 0.8},
    "youtube": {"psychology": 1.0, "storytelling": 1.4, "sales": 1.0, "design": 1.0, "distribution": 0.8},
}

PROFILE_INSUFFICIENT = "insufficient_data"
PROFILE_VIRAL = "attention_without_conversion"  # 조회형
PROFILE_NICHE = "conversion_without_attention"  # 전환형(조회는 낮아도 판매 가능)
PROFILE_BALANCED = "balanced"
PROFILE_WEAK = "weak"
MIN_AXIS_CONFIDENCE = 0.3
STRONG, WEAK_BELOW, GAP = 65.0, 45.0, 20.0


@dataclass(frozen=True)
class MarketingScore:
    psychology_score: float | None
    storytelling_score: float | None
    sales_score: float | None
    design_score: float | None
    distribution_score: float | None
    attention_score: float | None
    engagement_score: float | None
    conversion_score: float | None
    total_score: float
    confidence: float
    profile: str
    missing: tuple[str, ...]

    def to_dict(self) -> dict:
        return {name: getattr(self, name) if name != "missing" else list(self.missing) for name in self.__dataclass_fields__}


def element_quality(text: str) -> float | None:
    text = (text or "").strip()
    if not text:
        return None
    score = 50.0
    if len(text) >= 15:
        score += 25.0
    if re.search(r"\d", text) or len(text.split()) >= 4:
        score += 25.0
    return score


def _qualities(brief: MarketingBrief) -> dict[str, float | None]:
    result: dict[str, float | None] = {}
    for name in DIMENSIONS:
        for element, text in brief.dimension(name).to_dict().items():
            result[f"{name}.{element}"] = element_quality(text)
    for element in ("target_audience", "customer_problem", "desired_action"):
        result[f"brief.{element}"] = element_quality(getattr(brief, element))
    return result


def _weighted(qualities: dict[str, float | None], weights: dict[str, float]) -> tuple[float | None, float]:
    known = {key: weight for key, weight in weights.items() if qualities.get(key) is not None}
    total_weight = sum(weights.values())
    if not known:
        return None, 0.0
    score = sum(qualities[key] * weight for key, weight in known.items()) / sum(known.values())
    return round(score, 1), sum(known.values()) / total_weight


def classify_profile(attention: float | None, engagement: float | None, conversion: float | None,
                     attention_conf: float, conversion_conf: float) -> str:
    """조회형/전환형 분류. 한 축의 근거가 거의 없으면 그 축은 0점으로 보고(구조가 없으면 약하다),
    두 축 모두 근거가 부족할 때만 insufficient_data다."""
    if max(attention_conf, conversion_conf) < MIN_AXIS_CONFIDENCE:
        return PROFILE_INSUFFICIENT
    attention_eff = attention if attention is not None and attention_conf >= MIN_AXIS_CONFIDENCE else 0.0
    conversion_eff = conversion if conversion is not None and conversion_conf >= MIN_AXIS_CONFIDENCE else 0.0
    if attention_eff >= STRONG and conversion_eff <= attention_eff - GAP:
        return PROFILE_VIRAL
    if conversion_eff >= STRONG and attention_eff <= conversion_eff - GAP:
        return PROFILE_NICHE
    if max(attention_eff, conversion_eff) < WEAK_BELOW:
        return PROFILE_WEAK
    return PROFILE_BALANCED


def score_brief(brief: MarketingBrief) -> MarketingScore:
    qualities = _qualities(brief)
    dim_scores: dict[str, float | None] = {}
    for name in DIMENSIONS:
        values = [qualities[f"{name}.{element}"] for element in brief.dimension(name).element_names()]
        known = [value for value in values if value is not None]
        dim_scores[name] = round(sum(known) / len(known), 1) if known else None

    axes = {axis: _weighted(qualities, weights) for axis, weights in AXIS_WEIGHTS.items()}
    axis_scores = {axis: pair[0] for axis, pair in axes.items()}

    platform_weights = PLATFORM_DIMENSION_WEIGHTS[brief.platform]
    known_dims = {name: score for name, score in dim_scores.items() if score is not None}
    if known_dims:
        mean = sum(platform_weights[name] * score for name, score in known_dims.items()) / sum(
            platform_weights[name] for name in known_dims
        )
        # 근거가 거의 없는 축은 약한 축으로 본다(구조가 없는 축을 건너뛰고 높은 total을 주지 않는다).
        weakest = min(
            (score if score is not None and axes[axis][1] >= MIN_AXIS_CONFIDENCE else 0.0)
            for axis, score in axis_scores.items()
        )
        total = round(0.6 * mean + 0.4 * weakest, 1)
    else:
        total = 0.0

    filled = sum(value is not None for value in qualities.values())
    coverage = filled / len(qualities)
    return MarketingScore(
        psychology_score=dim_scores["psychology"], storytelling_score=dim_scores["storytelling"],
        sales_score=dim_scores["sales"], design_score=dim_scores["design"],
        distribution_score=dim_scores["distribution"],
        attention_score=axis_scores["attention"], engagement_score=axis_scores["engagement"],
        conversion_score=axis_scores["conversion"], total_score=total,
        confidence=round(coverage * (0.5 + 0.5 * brief.confidence), 2),
        profile=classify_profile(axis_scores["attention"], axis_scores["engagement"], axis_scores["conversion"],
                                 axes["attention"][1], axes["conversion"][1]),
        missing=tuple(brief.missing_fields()),
    )
