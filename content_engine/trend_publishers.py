"""Publisher adapters used by the approved trend-content queue.

Approved Threads text, Facebook Page text, YouTube Shorts MP4, Instagram Reels, and TikTok Direct Post jobs are supported.
Other platforms fail closed until their account, media, review, and API requirements are implemented.
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
from .youtube_publisher import YouTubeAPIError, YouTubeClient, YouTubeConfigurationError
from .instagram_publisher import InstagramAPIError, InstagramClient, InstagramConfigurationError
from .tiktok_publisher import TikTokAPIError, TikTokClient, TikTokConfigurationError, TikTokPublishRejectedError
from .facebook_publisher import FacebookAPIError, FacebookClient, FacebookConfigurationError
from .media_assets import MediaAssetError, MediaAssetStore


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


def _publish_youtube_short(payload: Mapping[str, object]) -> str:
    """Upload an approved MP4 as private first; public visibility is never implicit."""
    raw_path = str(payload.get("video_path") or payload.get("media_path") or "").strip()
    if not raw_path and payload.get("media_asset_id"):
        try:
            asset_store = MediaAssetStore(
                Path(os.getenv("TAK_AUTO_DATA_DIR", str(ROOT / "data"))) ,
                os.getenv("TAK_AUTO_MEDIA_SIGNING_KEY", ""),
                os.getenv("TAK_AUTO_PUBLIC_URL", ""),
            )
            raw_path = str(asset_store.get_asset(str(payload["media_asset_id"])).path)
        except MediaAssetError as error:
            raise PermanentPublishError(str(error)) from error
    if not raw_path:
        raise PermanentPublishError("YouTube Shorts 영상 파일 경로 또는 등록된 media_asset_id가 필요합니다.")
    video_path = Path(raw_path).expanduser()
    if not video_path.is_file() or video_path.suffix.lower() != ".mp4":
        raise PermanentPublishError("YouTube Shorts 게시 파일은 존재하는 MP4 파일이어야 합니다.")
    title = str(payload.get("title") or "").strip()
    if not title:
        raise PermanentPublishError("YouTube Shorts 제목이 비어 있습니다.")
    description = str(payload.get("description") or payload.get("body") or "")
    raw_tags = payload.get("tags") or []
    if isinstance(raw_tags, str):
        tags = [tag.strip() for tag in raw_tags.split() if tag.strip()]
    elif isinstance(raw_tags, (list, tuple)):
        tags = [str(tag).strip() for tag in raw_tags if str(tag).strip()]
    else:
        raise PermanentPublishError("YouTube Shorts 태그는 문자열 또는 목록이어야 합니다.")
    try:
        client = YouTubeClient.from_environment()
    except YouTubeConfigurationError as error:
        raise PermanentPublishError(str(error)) from error
    try:
        result = client.upload_short(
            video_path=video_path,
            title=title,
            description=description,
            tags=tags,
            privacy_status="private",
        )
    except YouTubeAPIError:
        # The upload may have reached YouTube even if its response was lost.
        # Never retry blindly; require an operator to reconcile the channel.
        raise PublishUncertainError(
            "YouTube 업로드 결과를 확정할 수 없습니다. 채널의 동영상 목록을 확인하세요."
        ) from None
    except ValueError as error:
        raise PermanentPublishError(str(error)) from error
    return result.video_id



def _publish_instagram_reel(payload: Mapping[str, object]) -> str:
    """Publish a reviewed Reel from a publicly reachable HTTPS media URL."""
    video_url = str(payload.get("video_url") or payload.get("media_url") or "").strip()
    if not video_url and payload.get("media_asset_id"):
        try:
            asset_store = MediaAssetStore(
                Path(os.getenv("TAK_AUTO_DATA_DIR", str(ROOT / "data"))),
                os.getenv("TAK_AUTO_MEDIA_SIGNING_KEY", ""),
                os.getenv("TAK_AUTO_PUBLIC_URL", ""),
            )
            video_url = asset_store.signed_url(str(payload["media_asset_id"]), ttl_seconds=48 * 60 * 60)
        except MediaAssetError as error:
            raise PermanentPublishError(str(error)) from error
    if not video_url:
        raise PermanentPublishError(
            "Instagram 릴스에는 등록된 media_asset_id 또는 공개 HTTPS 영상 URL이 필요합니다."
        )
    caption = str(payload.get("caption") or payload.get("body") or payload.get("text") or "").strip()
    if not caption:
        caption = str(payload.get("title") or "").strip()
    if len(caption) > 2200:
        raise PermanentPublishError("Instagram 릴스 캡션은 2,200자 이하여야 합니다.")
    encryption_key = os.getenv("TAK_AUTO_OAUTH_ENCRYPTION_KEY", "").strip()
    if not encryption_key:
        raise PermanentPublishError("Instagram 게시용 암호화 인증 저장소 설정이 없습니다.")
    try:
        vault = OAuthTokenVault(
            Path(os.getenv("TAK_AUTO_DATA_DIR", str(ROOT / "data"))) / "social_oauth_tokens.enc",
            encryption_key,
        )
        connection = vault.get("instagram_reels")
    except SocialOAuthError as error:
        raise PermanentPublishError(str(error)) from error
    if not connection:
        raise PermanentPublishError("Instagram 계정이 연결되지 않았습니다. 먼저 계정을 연결하세요.")
    scopes = {
        scope for scope in re.split(r"[,\s]+", str(connection.get("granted_scopes", ""))) if scope
    }
    required_scopes = {"instagram_business_basic", "instagram_business_content_publishing"}
    if not required_scopes.issubset(scopes):
        raise PermanentPublishError(
            "Instagram 계정에 릴스 게시 권한이 없습니다. 계정을 다시 연결하고 게시 권한에 동의하세요."
        )
    token = str(connection.get("access_token", "")).strip()
    account_id = str(connection.get("account_id", "")).strip()
    if not token or not account_id:
        raise PermanentPublishError("Instagram 인증 정보에 액세스 토큰 또는 계정 ID가 없습니다.")
    expiry = str(connection.get("expires_at", "")).strip()
    if expiry:
        try:
            expires_at = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
        except ValueError:
            raise PermanentPublishError("Instagram 토큰 만료일 형식을 확인할 수 없습니다.") from None
        if expires_at <= datetime.now(timezone.utc):
            raise PermanentPublishError("Instagram 토큰이 만료되었습니다. 계정을 다시 연결하세요.")
    try:
        client = InstagramClient(
            access_token=token,
            instagram_user_id=account_id,
            api_version=os.getenv("META_GRAPH_API_VERSION", "v27.0").strip(),
        )
    except InstagramConfigurationError as error:
        raise PermanentPublishError(str(error)) from error
    share_to_feed = payload.get("share_to_feed", True)
    if not isinstance(share_to_feed, bool):
        raise PermanentPublishError("Instagram share_to_feed 값은 true 또는 false여야 합니다.")
    try:
        result = client.publish_reel(
            video_url=video_url,
            caption=caption,
            share_to_feed=share_to_feed,
        )
    except ValueError as error:
        raise PermanentPublishError(str(error)) from error
    except InstagramAPIError:
        # Container creation, processing, or final publish may have reached Meta.
        # Require manual reconciliation instead of an automatic duplicate attempt.
        raise PublishUncertainError(
            "Instagram 릴스 게시 결과를 확정할 수 없습니다. 계정의 릴스 목록과 게시 상태를 확인하세요."
        ) from None
    return result.media_id



def _publish_tiktok_video(payload: Mapping[str, object]) -> str:
    """Direct-post an approved MP4 using the creator's currently allowed privacy options."""
    raw_path = str(payload.get("video_path") or payload.get("media_path") or "").strip()
    if not raw_path and payload.get("media_asset_id"):
        try:
            asset_store = MediaAssetStore(
                Path(os.getenv("TAK_AUTO_DATA_DIR", str(ROOT / "data"))),
                os.getenv("TAK_AUTO_MEDIA_SIGNING_KEY", ""),
                os.getenv("TAK_AUTO_PUBLIC_URL", ""),
            )
            raw_path = str(asset_store.get_asset(str(payload["media_asset_id"])).path)
        except MediaAssetError as error:
            raise PermanentPublishError(str(error)) from error
    if not raw_path:
        raise PermanentPublishError("TikTok 게시에는 등록된 media_asset_id 또는 MP4 파일 경로가 필요합니다.")
    video_path = Path(raw_path).expanduser()
    if not video_path.is_file() or video_path.suffix.lower() != ".mp4":
        raise PermanentPublishError("TikTok 게시 파일은 존재하는 MP4 파일이어야 합니다.")
    title = str(payload.get("title") or payload.get("caption") or payload.get("body") or "").strip()
    if not title or len(title.encode("utf-16-le")) // 2 > 2200:
        raise PermanentPublishError("TikTok 캡션은 비어 있지 않고 UTF-16 기준 2,200자 이하여야 합니다.")
    privacy_level = str(payload.get("privacy_level") or "").strip()
    if not privacy_level:
        raise PermanentPublishError(
            "TikTok privacy_level을 명시해야 합니다. 계정에서 허용된 공개 범위 중 하나를 선택하세요."
        )
    encryption_key = os.getenv("TAK_AUTO_OAUTH_ENCRYPTION_KEY", "").strip()
    if not encryption_key:
        raise PermanentPublishError("TikTok 게시용 암호화 인증 저장소 설정이 없습니다.")
    try:
        vault = OAuthTokenVault(
            Path(os.getenv("TAK_AUTO_DATA_DIR", str(ROOT / "data"))) / "social_oauth_tokens.enc",
            encryption_key,
        )
        connection = vault.get("tiktok")
    except SocialOAuthError as error:
        raise PermanentPublishError(str(error)) from error
    if not connection:
        raise PermanentPublishError("TikTok 계정이 연결되지 않았습니다. 먼저 계정을 연결하세요.")
    scopes = {
        scope for scope in re.split(r"[,\s]+", str(connection.get("granted_scopes", ""))) if scope
    }
    if "video.publish" not in scopes:
        raise PermanentPublishError(
            "TikTok 계정에 Direct Post 게시 권한이 없습니다. 계정을 다시 연결하고 video.publish에 동의하세요."
        )
    token = str(connection.get("access_token", "")).strip()
    open_id = str(connection.get("account_id", "")).strip()
    if not token or not open_id:
        raise PermanentPublishError("TikTok 인증 정보에 액세스 토큰 또는 Open ID가 없습니다.")
    expiry = str(connection.get("expires_at", "")).strip()
    if expiry:
        try:
            expires_at = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
        except ValueError:
            raise PermanentPublishError("TikTok 토큰 만료일 형식을 확인할 수 없습니다.") from None
        if expires_at <= datetime.now(timezone.utc):
            raise PermanentPublishError("TikTok 토큰이 만료되었습니다. 계정을 다시 연결하세요.")
    try:
        client = TikTokClient(access_token=token, open_id=open_id)
    except TikTokConfigurationError as error:
        raise PermanentPublishError(str(error)) from error
    options = {}
    for field in ("disable_comment", "disable_duet", "disable_stitch", "is_aigc"):
        value = payload.get(field, False)
        if not isinstance(value, bool):
            raise PermanentPublishError(f"TikTok {field} 값은 true 또는 false여야 합니다.")
        options[field] = value
    try:
        result = client.publish_video(
            video_path=video_path, title=title, privacy_level=privacy_level, **options,
        )
    except TikTokPublishRejectedError as error:
        raise PermanentPublishError(str(error)) from error
    except ValueError as error:
        raise PermanentPublishError(str(error)) from error
    except TikTokAPIError:
        # TikTok may have accepted the upload or completed the post before a response was lost.
        raise PublishUncertainError(
            "TikTok 게시 결과를 확정할 수 없습니다. TikTok 계정의 게시 목록을 확인하세요."
        ) from None
    return result.post_id or result.publish_id



def _publish_facebook_page_post(payload: Mapping[str, object]) -> str:
    """Publish approved text to the selected Facebook Page, never to a personal profile."""
    message = str(payload.get("body") or payload.get("message") or payload.get("text") or "").strip()
    if not message:
        raise PermanentPublishError("Facebook 페이지 게시 본문이 비어 있습니다.")
    encryption_key = os.getenv("TAK_AUTO_OAUTH_ENCRYPTION_KEY", "").strip()
    if not encryption_key:
        raise PermanentPublishError("Facebook 게시용 암호화 인증 저장소 설정이 없습니다.")
    try:
        vault = OAuthTokenVault(
            Path(os.getenv("TAK_AUTO_DATA_DIR", str(ROOT / "data"))) / "social_oauth_tokens.enc",
            encryption_key,
        )
        connection = vault.get("facebook")
    except SocialOAuthError as error:
        raise PermanentPublishError(str(error)) from error
    if not connection:
        raise PermanentPublishError("Facebook 페이지가 연결되지 않았습니다. 먼저 페이지를 연결하세요.")
    scopes = {
        scope for scope in re.split(r"[,\s]+", str(connection.get("granted_scopes", ""))) if scope
    }
    required_scopes = {"pages_show_list", "pages_read_engagement", "pages_manage_posts"}
    if not required_scopes.issubset(scopes):
        raise PermanentPublishError(
            "Facebook 페이지 게시 권한이 부족합니다. pages_manage_posts 및 pages_read_engagement 권한으로 다시 연결하세요."
        )
    token = str(connection.get("access_token", "")).strip()
    page_id = str(connection.get("account_id", "")).strip()
    if not token or not page_id:
        raise PermanentPublishError("Facebook 연결에 페이지 액세스 토큰 또는 페이지 ID가 없습니다.")
    page_tasks = connection.get("tasks", [])
    if not isinstance(page_tasks, list) or "CREATE_CONTENT" not in page_tasks:
        raise PermanentPublishError(
            "선택한 Facebook 페이지에 CREATE_CONTENT 작업 권한이 없습니다. 게시 권한이 있는 페이지를 다시 연결하세요."
        )
    expiry = str(connection.get("expires_at", "")).strip()
    if expiry:
        try:
            expires_at = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
        except ValueError:
            raise PermanentPublishError("Facebook 토큰 만료일 형식을 확인할 수 없습니다.") from None
        if expires_at <= datetime.now(timezone.utc):
            raise PermanentPublishError("Facebook 페이지 토큰이 만료되었습니다. 페이지를 다시 연결하세요.")
    try:
        client = FacebookClient(
            access_token=token,
            page_id=page_id,
            api_version=os.getenv("META_GRAPH_API_VERSION", "v27.0").strip(),
        )
        result = client.publish_text(message)
    except FacebookConfigurationError as error:
        raise PermanentPublishError(str(error)) from error
    except ValueError as error:
        raise PermanentPublishError(str(error)) from error
    except FacebookAPIError:
        # The remote page may have accepted the post before a transport failure.
        raise PublishUncertainError(
            "Facebook 게시 결과를 확정할 수 없습니다. 페이지 게시물 목록을 확인한 뒤 재시도하세요."
        ) from None
    return result.post_id


def publish(platform: str, payload: Mapping[str, object], idempotency_key: str) -> str:
    """Publish one approved queue item and return the platform's remote ID."""
    if platform == "youtube_shorts":
        return _publish_youtube_short(payload)
    if platform == "instagram_reels":
        return _publish_instagram_reel(payload)
    if platform == "tiktok":
        return _publish_tiktok_video(payload)
    if platform == "facebook":
        return _publish_facebook_page_post(payload)
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
