"""Instagram Reels publishing through the Instagram Login Graph API.

The media must be reachable at a public HTTPS URL: Meta fetches it from its
servers. This adapter deliberately does not accept local filesystem paths.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
import time


class InstagramConfigurationError(ValueError):
    """Missing or invalid Instagram publishing configuration."""


class InstagramAPIError(RuntimeError):
    """Instagram Graph API or transport failure."""


@dataclass(frozen=True)
class InstagramPublishResult:
    media_id: str


def _request_json(method: str, url: str, *, access_token: str,
                  fields: Mapping[str, object] | None = None,
                  timeout_seconds: float = 30.0) -> Mapping[str, object]:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != "graph.instagram.com":
        raise InstagramAPIError("허용되지 않은 Instagram API 주소입니다.")
    headers = {"Accept": "application/json", "Authorization": f"Bearer {access_token}",
               "User-Agent": "TAK-AUTO/1.0"}
    body = None
    if fields is not None:
        body = urlencode({key: str(value) for key, value in fields.items()}).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    request = Request(url, data=body, headers=headers, method=method.upper())
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read(1_000_001)
    except HTTPError as error:
        # Do not expose response bodies, tokens, or request URLs.
        raise InstagramAPIError(f"Instagram API 요청 실패 (HTTP {error.code}).") from None
    except (URLError, TimeoutError, OSError):
        raise InstagramAPIError("Instagram API 통신 결과를 확인할 수 없습니다.") from None
    if len(raw) > 1_000_000:
        raise InstagramAPIError("Instagram API 응답이 너무 큽니다.")
    try:
        result = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise InstagramAPIError("Instagram API 응답을 해석하지 못했습니다.") from None
    if not isinstance(result, dict):
        raise InstagramAPIError("Instagram API 응답 형식이 올바르지 않습니다.")
    if result.get("error"):
        raise InstagramAPIError("Instagram이 요청을 거부했습니다. 계정 권한과 영상 URL을 확인하세요.")
    return result


InstagramTransport = Callable[..., Mapping[str, object]]


@dataclass(frozen=True)
class InstagramClient:
    access_token: str
    instagram_user_id: str
    api_version: str = "v27.0"
    timeout_seconds: float = 30.0
    transport: InstagramTransport = _request_json
    sleep: Callable[[float], None] = time.sleep

    def __post_init__(self) -> None:
        if not self.access_token.strip():
            raise InstagramConfigurationError("Instagram 액세스 토큰이 없습니다.")
        if not self.instagram_user_id.strip() or not self.instagram_user_id.isdigit():
            raise InstagramConfigurationError("Instagram 프로페셔널 계정 ID가 올바르지 않습니다.")
        if not self.api_version.startswith("v") or not self.api_version[1:].replace(".", "").isdigit():
            raise InstagramConfigurationError("META_GRAPH_API_VERSION 설정을 확인하세요.")

    @property
    def _base(self) -> str:
        return f"https://graph.instagram.com/{self.api_version}"

    def publish_reel(self, *, video_url: str, caption: str, share_to_feed: bool = True,
                     poll_attempts: int = 6, poll_interval_seconds: float = 10.0) -> InstagramPublishResult:
        parsed = urlsplit(video_url.strip())
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Instagram 릴스 영상은 공개 HTTPS URL이어야 합니다.")
        if len(caption) > 2200:
            raise ValueError("Instagram 릴스 캡션은 2,200자 이하여야 합니다.")
        if poll_attempts < 1 or poll_attempts > 12:
            raise ValueError("영상 처리 확인 횟수는 1~12회여야 합니다.")

        # Step 1: ask Meta to fetch the publicly hosted video into a media container.
        container = self.transport(
            "POST", f"{self._base}/{self.instagram_user_id}/media",
            access_token=self.access_token,
            fields={"media_type": "REELS", "video_url": video_url.strip(),
                    "caption": caption, "share_to_feed": str(bool(share_to_feed)).lower()},
            timeout_seconds=self.timeout_seconds,
        )
        container_id = str(container.get("id") or "").strip()
        if not container_id:
            raise InstagramAPIError("Instagram 릴스 컨테이너 ID가 응답에 없습니다.")

        # Step 2: wait for Meta to finish fetching/transcoding the video.
        status: Mapping[str, object] = {}
        for attempt in range(poll_attempts):
            status = self.transport(
                "GET", f"{self._base}/{container_id}",
                access_token=self.access_token,
                fields={"fields": "status_code,status"},
                timeout_seconds=self.timeout_seconds,
            )
            code = str(status.get("status_code") or "").upper()
            if code == "FINISHED":
                break
            if code in {"ERROR", "EXPIRED"}:
                raise InstagramAPIError("Instagram 영상 컨테이너 처리에 실패했습니다. 영상 형식과 공개 URL을 확인하세요.")
            if code not in {"IN_PROGRESS", "PUBLISHED"}:
                raise InstagramAPIError("Instagram 영상 처리 상태를 확인할 수 없습니다.")
            if attempt < poll_attempts - 1:
                self.sleep(poll_interval_seconds)
        else:
            raise InstagramAPIError("Instagram 영상 처리가 아직 끝나지 않았습니다. 게시하지 않았습니다.")

        # Step 3: publish only after the container is FINISHED.
        published = self.transport(
            "POST", f"{self._base}/{self.instagram_user_id}/media_publish",
            access_token=self.access_token,
            fields={"creation_id": container_id},
            timeout_seconds=self.timeout_seconds,
        )
        media_id = str(published.get("id") or "").strip()
        if not media_id:
            raise InstagramAPIError("Instagram 게시 응답에 미디어 ID가 없습니다.")
        return InstagramPublishResult(media_id=media_id)
