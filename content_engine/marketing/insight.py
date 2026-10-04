"""성과 -> 마케팅 속성 연결(Marketing Insight). 읽기 전용 순수 함수.

'어떤 심리/스토리/판매 구조가 실제 성과를 만들었는가'를 분석할 수 있도록, 브리프에서 쓰인 요소
(attributes), 발행 전 예측 점수, 성과를 attention/engagement/conversion으로 분리한 지표를
콘텐츠 단위로 묶는다. 조회수 하나로 뭉개지 않는다. 측정되지 않은 지표는 0이 아니라 None이다.
표본이 적으면 lift는 방향 참고용일 뿐 통계적 결론이 아니다(sample 수를 함께 반환).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from content_engine.performance.models import PerformanceRecord

from .models import DIMENSIONS, MarketingBrief
from .scoring import score_brief

ATTENTION_METRICS = ("views", "impressions", "reach", "plays")
ENGAGEMENT_METRICS = ("likes", "replies", "comments", "reposts", "quotes", "shares", "saves")
CONVERSION_METRICS = ("clicks", "leads", "conversions", "conversion", "purchases")


def split_metrics(metrics: Mapping[str, int]) -> dict[str, float | None]:
    def total(names):
        present = [metrics[name] for name in names if name in metrics]
        return float(sum(present)) if present else None

    attention, engagement, conversion = total(ATTENTION_METRICS), total(ENGAGEMENT_METRICS), total(CONVERSION_METRICS)

    def rate(value):
        if value is None or not attention:
            return None
        return round(value / attention, 4)

    return {"attention": attention, "engagement": engagement, "conversion": conversion,
            "engagement_rate": rate(engagement), "conversion_rate": rate(conversion)}


def marketing_attributes(brief: MarketingBrief) -> tuple[str, ...]:
    """브리프에서 실제로 채워진 요소(``dimension.element``) + 플랫폼."""
    attrs = [f"{name}.{element}" for name in DIMENSIONS for element in brief.dimension(name).filled()]
    if brief.platform:
        attrs.append(f"platform.{brief.platform}")
    return tuple(attrs)


@dataclass(frozen=True)
class MarketingInsight:
    brief_id: str
    content_id: str
    platform: str
    attributes: tuple[str, ...]
    predicted: Mapping[str, float | None]  # attention/engagement/conversion/total
    observed: Mapping[str, float | None]  # split_metrics 결과
    metric_collected_at: str = ""

    def to_dict(self) -> dict:
        return {"brief_id": self.brief_id, "content_id": self.content_id, "platform": self.platform,
                "attributes": list(self.attributes), "predicted": dict(self.predicted),
                "observed": dict(self.observed), "metric_collected_at": self.metric_collected_at}


def collect_marketing_insights(
    briefs: Sequence[MarketingBrief], latest_snapshots: Mapping[str, PerformanceRecord]
) -> list[MarketingInsight]:
    """content_ids로 브리프와 연결된 콘텐츠의 최신 성과만 묶는다(연결 없는 성과는 무시)."""
    insights = []
    for brief in briefs:
        score = score_brief(brief)
        predicted = {"attention": score.attention_score, "engagement": score.engagement_score,
                     "conversion": score.conversion_score, "total": score.total_score}
        for content_id in brief.content_ids:
            record = latest_snapshots.get(content_id)
            if record is None:
                continue
            insights.append(MarketingInsight(
                brief_id=brief.brief_id, content_id=content_id, platform=record.platform or brief.platform,
                attributes=marketing_attributes(brief), predicted=predicted,
                observed=split_metrics(record.metrics), metric_collected_at=record.metric_collected_at,
            ))
    return insights


def attribute_lift(insights: Sequence[MarketingInsight], metric: str = "conversion_rate") -> dict[str, dict]:
    """속성이 있는 콘텐츠와 없는 콘텐츠의 평균 지표 차이. 양쪽 표본이 모두 있어야 lift를 계산한다."""
    measured = [item for item in insights if item.observed.get(metric) is not None]
    attributes = sorted({attr for item in measured for attr in item.attributes})
    result: dict[str, dict] = {}
    for attr in attributes:
        with_attr = [item.observed[metric] for item in measured if attr in item.attributes]
        without = [item.observed[metric] for item in measured if attr not in item.attributes]
        mean_with = sum(with_attr) / len(with_attr)
        mean_without = sum(without) / len(without) if without else None
        result[attr] = {
            "mean_with": round(mean_with, 4), "mean_without": None if mean_without is None else round(mean_without, 4),
            "lift": None if mean_without is None else round(mean_with - mean_without, 4),
            "n_with": len(with_attr), "n_without": len(without),
        }
    return result
