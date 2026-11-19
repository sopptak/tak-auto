"""Read-only Facebook Page post insights normalization and collection."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from content_engine.facebook_publisher import FacebookClient

from .models import PerformanceRecord


_METRIC_MAP = {
    "post_media_view": "views",
    "post_reactions_by_type_total": "reactions",
}


def _nonnegative_integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def normalize_facebook_insights(raw_response: Any) -> dict[str, int]:
    """Normalize current Page post insights without treating missing data as zero."""
    if not isinstance(raw_response, Mapping) or not isinstance(raw_response.get("data"), list):
        return {}
    metrics: dict[str, int] = {}
    for row in raw_response["data"]:
        if not isinstance(row, Mapping) or not isinstance(row.get("values"), list) or not row["values"]:
            continue
        values = row["values"][0]
        if not isinstance(values, Mapping):
            continue
        value = values.get("value")
        name = row.get("name")
        if name == "post_media_view":
            count = _nonnegative_integer(value)
            if count is not None:
                metrics["views"] = count
        elif name == "post_reactions_by_type_total" and isinstance(value, Mapping):
            counts = [_nonnegative_integer(count) for count in value.values()]
            if counts and all(count is not None for count in counts):
                metrics["reactions"] = sum(count for count in counts if count is not None)
    return metrics


def collect_facebook_performance(
    client: FacebookClient,
    *,
    post_id: str,
    content_id: str,
    knowledge_id: str,
    published_at: str,
    metric_collected_at: str,
    title: str = "",
) -> PerformanceRecord:
    raw = client.get_post_insights(post_id)
    metrics = normalize_facebook_insights(raw)
    return PerformanceRecord(
        content_id=content_id,
        knowledge_id=knowledge_id,
        platform="facebook",
        published_at=published_at,
        metric_collected_at=metric_collected_at,
        metrics=metrics,
        source="facebook_api",
        title=title,
        external_id=post_id,
        raw=dict(raw),
        unavailable_metrics=tuple(name for name in _METRIC_MAP.values() if name not in metrics),
        collection_status="collected",
    )
