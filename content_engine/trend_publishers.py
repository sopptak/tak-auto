"""Publisher adapters used by the approved trend-content queue.

Only approved Threads text jobs are automated. Other platforms fail closed until
their account, media, review, and API requirements have been implemented.
"""
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Mapping

from .publish_history import PublishHistory, PublishRecord
from .publishing_queue import PermanentPublishError, PublishUncertainError
from .threads_publisher import ThreadsAPIError, ThreadsClient, ThreadsConfigurationError


ROOT = Path(__file__).resolve().parents[1]


def _history_path() -> Path:
    return Path(os.getenv("TAK_AUTO_DATA_DIR", str(ROOT / "data"))) / "threads_publish_log.json"


def publish(platform: str, payload: Mapping[str, object], idempotency_key: str) -> str:
    """Publish one approved queue item and return the platform's remote ID."""
    if platform != "threads":
        raise PermanentPublishError(
            f"{platform} 게시 어댑터는 아직 준비되지 않았습니다. 작업은 게시되지 않았습니다."
        )

    content_id = str(payload.get("_content_id") or idempotency_key)
    text = str(payload.get("body") or payload.get("text") or "").strip()
    if not text:
        raise PermanentPublishError("Threads 게시 본문이 비어 있습니다.")
    if len(text) > 500:
        raise PermanentPublishError(f"Threads 게시 본문은 500자 이하여야 합니다: {len(text)}자")

    history = PublishHistory(_history_path())
    existing = next(
        (
            row for row in history.load()
            if row.get("content_id") == content_id and row.get("platform", "threads") == "threads"
        ),
        None,
    )
    if existing:
        remote_id = existing.get("threads_post_id") or existing.get("remote_id")
        if not remote_id:
            raise PublishUncertainError(
                "기존 Threads 이력에 게시 ID가 없습니다. 계정을 확인하세요."
            )
        return str(remote_id)

    try:
        client = ThreadsClient.from_environment()
    except ThreadsConfigurationError as error:
        raise PermanentPublishError(str(error)) from error

    try:
        result = client.publish_text(text)
    except ThreadsAPIError:
        # A transport failure can happen after the provider accepted a post.
        # Require a human check instead of retrying and risking a duplicate.
        raise PublishUncertainError(
            "Threads 응답을 확정할 수 없습니다. 계정 게시 목록을 확인하세요."
        ) from None

    try:
        history.append(PublishRecord(
            content_id=content_id,
            published_at=datetime.now(timezone.utc).isoformat(),
            threads_post_id=result.id,
            platform="threads",
        ))
    except (OSError, ValueError) as error:
        raise PublishUncertainError(
            "Threads 게시 성공 후 게시 이력을 저장하지 못했습니다. 재게시 전 계정을 확인하세요.",
            remote_id=result.id,
        ) from error
    return result.id
