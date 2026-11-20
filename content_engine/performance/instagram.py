"""Instagram Reels public media engagement fields (likes/comments)."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from content_engine.instagram_publisher import InstagramClient

from .models import PerformanceRecord


_FIELD_MAP = {"like_count": "likes", "comments_count": "comments"}


def normalize_instagram_media(raw_response: Any) -> dict[str, int]:
    """Map documented media fields to integer metrics, preserving omissions."""
    if not isinstance(raw_response, Mapping):
        return {}
    metrics: dict[str, int] = {}
    for field, metric in _FIELD_MAP.items():
        value = raw_response.get(field)
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(value, int):
            numeric = value
        elif isinstance(value, str) and value.strip().isdigit():
            numeric = int(value.strip())
        else:
            continue
        if numeric >= 0:
            metrics[metric] = numeric
    return metrics


def collect_instagram_performance(
    client: InstagramClient,
    *,
    media_id: str,
    content_id: str,
    knowledge_id: str,
    published_at: str,
    metric_collected_at: str,
    title: str = "",
) -> PerformanceRecord:
    """Collect likes/comments for an owned Instagram post or Reel."""
    raw = client.get_media_performance(media_id)
    metrics = normalize_instagram_media(raw)
    return PerformanceRecord(
        content_id=content_id,
        knowledge_id=knowledge_id,
        platform="instagram",
        published_at=published_at,
        metric_collected_at=metric_collected_at,
        metrics=metrics,
        source="instagram_api",
        title=title,
        external_id=media_id,
        raw=dict(raw),
        unavailable_metrics=tuple(metric for metric in _FIELD_MAP.values() if metric not in metrics),
        collection_status="collected",
    )
