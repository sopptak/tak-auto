"""Threads 성과(조회수/좋아요/답글/리포스트/인용/공유) 수집(6-01).

content_engine.threads_publisher.ThreadsClient.get_media_insights()를 그대로
호출할 뿐, 이 모듈이 직접 HTTP 요청을 만들지 않는다 - 실제 네트워크 호출은
항상 ThreadsClient(주입된 transport)의 책임이므로, 이 모듈의 fetch 함수는
테스트에서 mock transport를 가진 client를 넘겨 검증한다.

metric 목록은 공식 문서(https://developers.facebook.com/documentation/threads/insights,
2026-09-20 웹 검색으로 확인 - 임의로 추정한 값이 아니다)의 media insights
엔드포인트 기준 views/likes/replies/reposts/quotes/shares다.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from content_engine.threads_publisher import DEFAULT_INSIGHTS_METRICS, ThreadsClient

from .models import PerformanceRecord


def normalize_threads_insights(raw_response: Any) -> dict[str, int]:
    """Threads insights API 응답을 ``{"views": 10, "likes": 2, ...}``로 정규화한다.

    실제 응답 형태: ``{"data": [{"name": "views", "period": "lifetime",
    "values": [{"value": 10}]}, ...]}`` (공식 문서 예시 구조). name/values가
    없거나 값이 정수가 아닌 항목은 조용히 건너뛴다(부분 응답도 최대한 활용).
    """
    if not isinstance(raw_response, dict):
        return {}
    entries = raw_response.get("data")
    if not isinstance(entries, list):
        return {}

    metrics: dict[str, int] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        values = entry.get("values")
        if not name or not isinstance(values, list) or not values:
            continue
        first_value = values[0]
        if not isinstance(first_value, dict):
            continue
        value = first_value.get("value")
        if isinstance(value, bool) or not isinstance(value, int):
            continue
        metrics[str(name)] = value
    return metrics


def collect_threads_performance(
    client: ThreadsClient,
    *,
    media_id: str,
    content_id: str,
    knowledge_id: str,
    published_at: str,
    metric_collected_at: str,
    title: str = "",
    metrics: Sequence[str] = DEFAULT_INSIGHTS_METRICS,
) -> PerformanceRecord:
    """Threads media 1건의 성과를 실제로 조회해 PerformanceRecord로 정규화한다.

    실제 네트워크 호출은 ``client.get_media_insights()``가 수행한다 - 이 함수를
    호출하는 것 자체가 실제 API 호출이라는 뜻이다(테스트에서는 mock transport를
    가진 client를 넘긴다).
    """
    raw = client.get_media_insights(media_id, metrics=metrics)
    normalized = normalize_threads_insights(raw)
    return PerformanceRecord(
        content_id=content_id,
        knowledge_id=knowledge_id,
        platform="threads",
        published_at=published_at,
        metric_collected_at=metric_collected_at,
        metrics=normalized,
        source="threads_api",
        title=title,
        external_id=media_id,
        raw=raw if isinstance(raw, dict) else None,
    )
