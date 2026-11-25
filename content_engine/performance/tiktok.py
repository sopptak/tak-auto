"""Read-only TikTok owned-video statistics normalization and collection."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from content_engine.tiktok_publisher import TikTokClient

from .models import PerformanceRecord


_FIELD_MAP = {
    "view_count": "views",
    "like_count": "likes",
    "comment_count": "comments",
    "share_count": "shares",
}


def normalize_tiktok_video(raw_response: Any) -> dict[str, int]:
    if not isinstance(raw_response, Mapping):
        return {}
    metrics: dict[str, int] = {}
    for field, metric in _FIELD_MAP.items():
        value = raw_response.get(field)
        if isinstance(value, bool):
            continue
        if isinstance(value, int) and value >= 0:
            metrics[metric] = value
        elif isinstance(value, str) and value.strip().isdigit():
            metrics[metric] = int(value.strip())
    return metrics


def collect_tiktok_performance(
    client: TikTokClient,
    *,
    video_id: str,
    content_id: str,
    knowledge_id: str,
    published_at: str,
    metric_collected_at: str,
    title: str = "",
) -> PerformanceRecord:
    raw = client.get_video_statistics(video_id)
    metrics = normalize_tiktok_video(raw)
    return PerformanceRecord(
        content_id=content_id,
        knowledge_id=knowledge_id,
        platform="tiktok",
        published_at=published_at,
        metric_collected_at=metric_collected_at,
        metrics=metrics,
        source="tiktok_api",
        title=title,
        external_id=video_id,
        raw=dict(raw),
        unavailable_metrics=tuple(metric for metric in _FIELD_MAP.values() if metric not in metrics),
        collection_status="collected",
    )
