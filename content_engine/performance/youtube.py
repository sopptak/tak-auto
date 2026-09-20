"""YouTube Shorts 성과(조회수/좋아요/댓글) 수집(6-01).

content_engine.youtube_publisher.YouTubeClient.get_video_statistics()를 그대로
호출할 뿐, 이 모듈이 직접 HTTP 요청을 만들지 않는다.

필드 매핑은 공식 문서(https://developers.google.com/youtube/v3/docs/videos/list,
2026-09-20 웹 검색으로 확인)의 videos.list(part=statistics) 응답 기준
statistics.viewCount/likeCount/commentCount다. YouTube Data API는 큰 숫자를
문자열로 반환하므로 정수로 변환한다.
"""

from __future__ import annotations

from typing import Any

from content_engine.youtube_publisher import YouTubeClient

from .models import PerformanceRecord


_STATISTICS_FIELD_MAP: dict[str, str] = {
    "viewCount": "views",
    "likeCount": "likes",
    "commentCount": "comments",
}


def normalize_youtube_statistics(raw_item: Any) -> dict[str, int]:
    """videos.list 응답의 items[i] 1건을 ``{"views": 123, "likes": 4, ...}``로 정규화한다."""
    if not isinstance(raw_item, dict):
        return {}
    statistics = raw_item.get("statistics")
    if not isinstance(statistics, dict):
        return {}

    metrics: dict[str, int] = {}
    for api_field, metric_name in _STATISTICS_FIELD_MAP.items():
        value = statistics.get(api_field)
        if value is None:
            continue
        try:
            metrics[metric_name] = int(value)
        except (TypeError, ValueError):
            continue
    return metrics


def collect_youtube_performance(
    client: YouTubeClient,
    *,
    video_id: str,
    content_id: str,
    knowledge_id: str,
    published_at: str,
    metric_collected_at: str,
    title: str = "",
) -> PerformanceRecord:
    """YouTube 영상 1건의 성과를 실제로 조회해 PerformanceRecord로 정규화한다.

    실제 네트워크 호출은 ``client.get_video_statistics()``가 수행한다(내부적으로
    refresh_token -> access_token 발급도 함께 일어난다).
    """
    raw = client.get_video_statistics([video_id])
    items = raw.get("items") if isinstance(raw, dict) else None
    item = items[0] if isinstance(items, list) and items else {}
    normalized = normalize_youtube_statistics(item)
    return PerformanceRecord(
        content_id=content_id,
        knowledge_id=knowledge_id,
        platform="youtube",
        published_at=published_at,
        metric_collected_at=metric_collected_at,
        metrics=normalized,
        source="youtube_api",
        title=title,
        external_id=video_id,
        raw=raw if isinstance(raw, dict) else None,
    )
