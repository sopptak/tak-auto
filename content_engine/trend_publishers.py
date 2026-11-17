"""Publisher adapters used by the approved trend-content queue.

Only approved Threads text jobs are automated. Other platforms fail closed until
their account, media, review, and API requirements have been implemented.
"""
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import re
from typing import Mapping

from .publish_history import PublishHistory, PublishRecord
from .publishing_queue import PermanentPublishError, PublishUncertainError
from .social_oauth import OAuthTokenVault, SocialOAuthError
from .threads_publisher import ThreadsAPIError, ThreadsClient, ThreadsConfigurationError


ROOT = Path(__file__).resolve().parents[1]


def _history_path() -> Path:
    return Path(os.getenv("TAK_AUTO_DATA_DIR", str(ROOT / "data"))) / "threads_publish_log.json"


def _threads_client() -> ThreadsClient:
    """Use the encrypted web connection when it grants publishing; keep legacy env fallback."""
    encryption_key = os.getenv("TAK_AUTO_OAUTH_ENCRYPTION_KEY", "").strip()
    if encryption_key:
        try:
            vault = OAuthTokenVault(
                Path(os.getenv("TAK_AUTO_DATA_DIR", str(ROOT / "data"))) / "social_oauth_tokens.enc",
                encryption_key,
            )
            connection = vault.get("threads")
        except SocialOAuthError as error:
            raise PermanentPublishError(str(error)) from error
        if connection is not None:
            scopes = {
                scope for scope in re.split(r"[,\s]+", str(connection.get("granted_scopes", ""))) if scope
            }
            if "threads_content_publish" not in scopes:
                raise PermanentPublishError(
                    "Threads 계정에 게시 권한이 없습니다. 계정을 다시 연결하고 게시 권한에 동의하세요."
                )
            token = str(connection.get("access_token", "")).strip()
            if not token:
                raise PermanentPublishError("암호화된 Threads 연결에 액세스 토큰이 없습니다. 다시 연결하세요.")
            expiry = str(connection.get("expires_at", "")).strip()
            if expiry:
                try:
                    expires_at = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
                    if expires_at.tzinfo is None:
                        expires_at = expires_at.replace(tzinfo=timezone.utc)
                except ValueError:
                    raise PermanentPublishError("Threads 토큰 만료일 형식을 확인할 수 없습니다. 다시 연결하세요.") from None
                if expires_at <= datetime.now(timezone.utc):
                    raise PermanentPublishError("Threads 토큰이 만료되었습니다. 계정을 다시 연결하세요.")
            return ThreadsClient(access_token=token)
    try:
        return ThreadsClient.from_environment()
    except ThreadsConfigurationError as error:
        raise PermanentPublishError(str(error)) from error


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

    client = _threads_client()

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
