"""YouTube Data API v3 공식 방식(OAuth 2.0)을 통한 YouTube Shorts 업로드 클라이언트.

content_engine.threads_publisher와 동일한 설계 원칙을 따른다:
    - 표준 라이브러리(urllib)만 사용, 외부 의존성 추가 없음
    - access_token/refresh_token은 환경변수로만 주입받고 코드에 하드코딩하지 않음
    - 오류 메시지에 토큰 등 민감정보를 노출하지 않음
    - transport를 주입 가능하게 만들어 실제 네트워크 호출 없이 테스트 가능

이 모듈은 "완성된 MP4를 업로드하는 것"만 책임진다. 영상 생성(TAK MEDIA), Threads 게시,
TAK BRAIN 로직은 전혀 건드리지 않는다.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"

# YouTube Shorts 카드뉴스/정보형 콘텐츠 기본 카테고리: "People & Blogs"
DEFAULT_CATEGORY_ID = "22"

VALID_PRIVACY_STATUSES = ("private", "unlisted", "public")


class YouTubeConfigurationError(ValueError):
    """YouTube API 호출에 필요한 OAuth 환경 설정이 없을 때 발생한다."""


class YouTubeAPIError(ValueError):
    """YouTube OAuth 토큰 갱신 또는 업로드 API 호출이 실패했을 때 발생한다."""


@dataclass(frozen=True)
class YouTubeUploadResult:
    """YouTube 업로드 성공 결과."""

    video_id: str

    @property
    def url(self) -> str:
        return f"https://youtu.be/{self.video_id}"


def _safe_http_error_message(prefix: str, error: HTTPError) -> str:
    """HTTP 에러 응답에서 민감정보(토큰 등)를 제외하고 안전한 오류 필드만 추출한다."""
    details: list[str] = []
    try:
        body = json.loads(error.read().decode("utf-8"))
        error_obj = body.get("error", {}) if isinstance(body, dict) else {}
        if isinstance(error_obj, dict):
            message = error_obj.get("message") or error_obj.get("error_description")
            if message:
                details.append(f"message={message}")
            code = error_obj.get("code")
            if code is not None:
                details.append(f"code={code}")
            errors_list = error_obj.get("errors")
            if isinstance(errors_list, list):
                for item in errors_list:
                    if isinstance(item, dict) and item.get("reason"):
                        details.append(f"reason={item['reason']}")
        elif isinstance(body, dict) and body.get("error"):
            # OAuth 토큰 엔드포인트 오류는 {"error": "invalid_grant", "error_description": "..."}
            # 형태의 평면(flat) 구조를 쓴다 (Google API의 {"error": {...}} 중첩 구조와 다름).
            details.append(f"error={body.get('error')}")
            description = body.get("error_description")
            if description:
                details.append(f"error_description={description}")
    except (UnicodeDecodeError, json.JSONDecodeError, OSError):
        pass
    detail_text = "; ".join(details) if details else "YouTube API 오류 상세를 읽을 수 없습니다."
    return f"{prefix} HTTP {error.code}: {detail_text}"


def _default_token_transport(
    client_id: str,
    client_secret: str,
    refresh_token: str,
    timeout_seconds: float,
) -> Mapping[str, object]:
    """refresh_token으로 새 access_token을 발급받는다 (OAuth 2.0 표준 토큰 갱신)."""
    payload = urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
    ).encode("utf-8")
    request = Request(
        TOKEN_URL,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise YouTubeAPIError(_safe_http_error_message("YouTube OAuth Token", error)) from None
    except Exception as error:
        raise YouTubeAPIError(f"YouTube OAuth 토큰 갱신 통신 실패: {type(error).__name__}") from None

    if not isinstance(data, dict) or not data.get("access_token"):
        raise YouTubeAPIError("YouTube OAuth 토큰 응답에 access_token이 없습니다.")
    return data


def _default_upload_transport(
    access_token: str,
    metadata: Mapping[str, object],
    video_path: Path,
    timeout_seconds: float,
) -> Mapping[str, object]:
    """YouTube Data API v3 resumable upload 프로토콜로 영상을 업로드한다.

    1) 메타데이터(JSON)만 POST해 업로드 세션을 열고 Location 헤더를 받는다.
    2) 그 Location으로 영상 바이너리를 PUT한다.
    """
    init_headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Type": "video/mp4",
    }
    query = urlencode({"uploadType": "resumable", "part": "snippet,status"})
    init_request = Request(
        f"{UPLOAD_URL}?{query}",
        data=json.dumps(metadata).encode("utf-8"),
        headers=init_headers,
        method="POST",
    )
    try:
        with urlopen(init_request, timeout=timeout_seconds) as response:
            upload_session_url = response.headers.get("Location")
    except HTTPError as error:
        raise YouTubeAPIError(_safe_http_error_message("YouTube Upload Init", error)) from None
    except Exception as error:
        raise YouTubeAPIError(f"YouTube 업로드 세션 생성 실패: {type(error).__name__}") from None

    if not upload_session_url:
        raise YouTubeAPIError("YouTube 업로드 세션 응답에 Location 헤더가 없습니다.")

    video_bytes = video_path.read_bytes()
    upload_request = Request(
        upload_session_url,
        data=video_bytes,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "video/mp4",
        },
        method="PUT",
    )
    try:
        with urlopen(upload_request, timeout=timeout_seconds) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise YouTubeAPIError(_safe_http_error_message("YouTube Upload", error)) from None
    except Exception as error:
        raise YouTubeAPIError(f"YouTube 영상 업로드 통신 실패: {type(error).__name__}") from None

    if not isinstance(data, dict) or not data.get("id"):
        raise YouTubeAPIError("YouTube 업로드 응답에 video id가 누락되었습니다.")
    return data


YouTubeTokenTransport = Callable[[str, str, str, float], Mapping[str, object]]
YouTubeUploadTransport = Callable[[str, Mapping[str, object], Path, float], Mapping[str, object]]


@dataclass(frozen=True)
class YouTubeClient:
    """YouTube Data API v3 OAuth 2.0 클라이언트 (Access/Refresh Token 구조)."""

    client_id: str
    client_secret: str
    refresh_token: str
    timeout_seconds: float = 120.0
    token_transport: YouTubeTokenTransport = _default_token_transport
    upload_transport: YouTubeUploadTransport = _default_upload_transport

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
        token_transport: YouTubeTokenTransport = _default_token_transport,
        upload_transport: YouTubeUploadTransport = _default_upload_transport,
    ) -> "YouTubeClient":
        values = os.environ if environ is None else environ
        client_id = values.get("YOUTUBE_CLIENT_ID", "").strip()
        client_secret = values.get("YOUTUBE_CLIENT_SECRET", "").strip()
        refresh_token = values.get("YOUTUBE_REFRESH_TOKEN", "").strip()

        missing = [
            name
            for name, value in (
                ("YOUTUBE_CLIENT_ID", client_id),
                ("YOUTUBE_CLIENT_SECRET", client_secret),
                ("YOUTUBE_REFRESH_TOKEN", refresh_token),
            )
            if not value
        ]
        if missing:
            raise YouTubeConfigurationError(
                "다음 환경변수가 필요합니다: " + ", ".join(missing)
            )

        return cls(
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=refresh_token,
            token_transport=token_transport,
            upload_transport=upload_transport,
        )

    def _get_access_token(self) -> str:
        data = self.token_transport(
            self.client_id, self.client_secret, self.refresh_token, self.timeout_seconds
        )
        return str(data["access_token"])

    def upload_short(
        self,
        video_path: Path | str,
        title: str,
        description: str = "",
        tags: Sequence[str] | None = None,
        privacy_status: str = "private",
        category_id: str = DEFAULT_CATEGORY_ID,
    ) -> YouTubeUploadResult:
        """9:16 MP4 Shorts 영상 1건을 업로드한다.

        실제 네트워크 호출(access_token 발급, 업로드) 전에 입력값을 모두 검증한다 -
        잘못된 입력으로 불필요한 API 호출이 일어나지 않게 하기 위함이다.
        """
        path = Path(video_path)
        if not path.exists():
            raise ValueError(f"영상 파일을 찾을 수 없습니다: {path}")
        if path.suffix.lower() != ".mp4":
            raise ValueError(f"영상 파일은 .mp4여야 합니다: {path}")

        clean_title = (title or "").strip()
        if not clean_title:
            raise ValueError("YouTube 영상 제목이 비어 있습니다.")
        if len(clean_title) > 100:
            raise ValueError(f"YouTube title exceeds 100 characters: {len(clean_title)}")

        if privacy_status not in VALID_PRIVACY_STATUSES:
            raise ValueError(
                f"privacy_status는 {VALID_PRIVACY_STATUSES} 중 하나여야 합니다 "
                f"(입력값: {privacy_status})"
            )

        clean_tags = [tag.strip() for tag in (tags or []) if tag and tag.strip()]

        metadata: dict[str, object] = {
            "snippet": {
                "title": clean_title,
                "description": description or "",
                "tags": clean_tags,
                "categoryId": category_id,
            },
            "status": {
                "privacyStatus": privacy_status,
                "selfDeclaredMadeForKids": False,
            },
        }

        access_token = self._get_access_token()
        response = self.upload_transport(access_token, metadata, path, self.timeout_seconds)

        video_id = response.get("id")
        if not video_id:
            raise YouTubeAPIError("YouTube 업로드 응답에 video id가 누락되었습니다.")
        return YouTubeUploadResult(video_id=str(video_id))
