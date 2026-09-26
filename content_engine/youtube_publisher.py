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
from dataclasses import dataclass, replace
import json
import os
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"

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


def _default_stats_transport(
    access_token: str,
    video_ids: Sequence[str],
    timeout_seconds: float,
) -> Mapping[str, object]:
    """YouTube Data API v3 videos.list(part=statistics)를 호출한다(6-01, 성과 수집).

    공식 문서(https://developers.google.com/youtube/v3/docs/videos/list) 기준
    statistics.viewCount/likeCount/commentCount를 응답한다(웹 검색으로 확인, 임의
    추정 아님). 한 번에 최대 50개 id를 조회할 수 있다 - 이 함수는 그 제한을
    강제하지 않는다(호출부 YouTubeClient.get_video_statistics()가 미리 검증한다).
    """
    query = urlencode({"part": "statistics", "id": ",".join(video_ids)})
    request = Request(
        f"{VIDEOS_URL}?{query}",
        headers={"Authorization": f"Bearer {access_token}"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise YouTubeAPIError(_safe_http_error_message("YouTube Statistics", error)) from None
    except Exception as error:
        raise YouTubeAPIError(f"YouTube 통계 조회 통신 실패: {type(error).__name__}") from None

    if not isinstance(data, dict):
        raise YouTubeAPIError("YouTube 통계 응답 형식이 올바르지 않습니다.")
    return data


def _default_status_transport(
    access_token: str,
    video_id: str,
    timeout_seconds: float,
) -> Mapping[str, object]:
    """videos.list(part=snippet,status,processingDetails)로 업로드한 영상 1건의 상태를
    조회한다(6-42). processingDetails는 영상 소유자에게만 반환된다(공식 문서 기준).
    """
    query = urlencode({"part": "snippet,status,processingDetails", "id": video_id})
    request = Request(
        f"{VIDEOS_URL}?{query}",
        headers={"Authorization": f"Bearer {access_token}"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise YouTubeAPIError(_safe_http_error_message("YouTube Video Status", error)) from None
    except Exception as error:
        raise YouTubeAPIError(f"YouTube 영상 상태 조회 통신 실패: {type(error).__name__}") from None

    if not isinstance(data, dict):
        raise YouTubeAPIError("YouTube 영상 상태 응답 형식이 올바르지 않습니다.")
    return data


# 6-42: processingDetails.processingStatus 공식 값은 processing/succeeded/failed/terminated.
# bounded polling이 끝났는데도 processing이면 이 값으로 기록한다(무한 polling 금지).
WAITING_PROCESSING = "WAITING_PROCESSING"
# 상태 조회 자체가 실패했을 때(권한/네트워크 등) - 업로드 성공 여부와는 별개로 기록한다.
STATUS_UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class YouTubeVideoStatus:
    """videos.list로 다시 읽은 업로드 영상의 메타데이터/처리 상태(6-42)."""

    video_id: str
    found: bool
    title: str = ""
    description: str = ""
    privacy_status: str = ""
    upload_status: str = ""
    processing_status: str = ""
    published_at: str = ""
    # 6-43: 처리/업로드 실패 사유(processingDetails.processingFailureReason, status.failureReason/rejectionReason)
    failure_reason: str = ""

    @classmethod
    def from_response(cls, video_id: str, data: Mapping[str, object]) -> "YouTubeVideoStatus":
        items = data.get("items") if isinstance(data, Mapping) else None
        if not isinstance(items, list) or not items or not isinstance(items[0], dict):
            return cls(video_id=video_id, found=False)
        item = items[0]
        snippet = item.get("snippet") or {}
        status = item.get("status") or {}
        processing = item.get("processingDetails") or {}
        return cls(
            video_id=video_id,
            found=True,
            title=str(snippet.get("title", "")),
            description=str(snippet.get("description", "")),
            privacy_status=str(status.get("privacyStatus", "")),
            upload_status=str(status.get("uploadStatus", "")),
            processing_status=str(processing.get("processingStatus", "")),
            published_at=str(snippet.get("publishedAt", "")),
            failure_reason=str(
                processing.get("processingFailureReason") or status.get("failureReason") or status.get("rejectionReason") or ""
            ),
        )


YouTubeTokenTransport = Callable[[str, str, str, float], Mapping[str, object]]
YouTubeUploadTransport = Callable[[str, Mapping[str, object], Path, float], Mapping[str, object]]
YouTubeStatsTransport = Callable[[str, Sequence[str], float], Mapping[str, object]]
YouTubeStatusTransport = Callable[[str, str, float], Mapping[str, object]]


@dataclass(frozen=True)
class YouTubeClient:
    """YouTube Data API v3 OAuth 2.0 클라이언트 (Access/Refresh Token 구조)."""

    client_id: str
    client_secret: str
    refresh_token: str
    timeout_seconds: float = 120.0
    token_transport: YouTubeTokenTransport = _default_token_transport
    upload_transport: YouTubeUploadTransport = _default_upload_transport
    stats_transport: YouTubeStatsTransport = _default_stats_transport
    status_transport: YouTubeStatusTransport = _default_status_transport

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
        token_transport: YouTubeTokenTransport = _default_token_transport,
        upload_transport: YouTubeUploadTransport = _default_upload_transport,
        stats_transport: YouTubeStatsTransport = _default_stats_transport,
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
            stats_transport=stats_transport,
        )

    def _get_access_token(self) -> str:
        data = self.token_transport(
            self.client_id, self.client_secret, self.refresh_token, self.timeout_seconds
        )
        return str(data["access_token"])

    def get_video_statistics(self, video_ids: Sequence[str]) -> Mapping[str, object]:
        """videos.list(part=statistics)로 영상 조회수/좋아요/댓글 수를 조회한다(6-01).

        최대 50개 id를 한 번에 조회할 수 있다(YouTube Data API 공식 제한). access_token은
        업로드와 동일하게 refresh_token으로 매번 새로 발급받는다. 원본 응답을 그대로
        반환하고 정규화하지 않는다 - 정규화는 content_engine.performance.youtube의 책임이다.
        """
        if not video_ids:
            raise ValueError("video_ids가 비어 있습니다.")
        if len(video_ids) > 50:
            raise ValueError(f"video_ids는 최대 50개까지 가능합니다: {len(video_ids)}개 전달됨")
        access_token = self._get_access_token()
        return self.stats_transport(access_token, list(video_ids), self.timeout_seconds)

    def get_video_status(self, video_id: str) -> YouTubeVideoStatus:
        """업로드한 영상 1건의 제목/설명/공개 상태/처리 상태를 다시 조회한다(6-42)."""
        if not video_id:
            raise ValueError("video_id가 비어 있습니다.")
        access_token = self._get_access_token()
        return YouTubeVideoStatus.from_response(video_id, self.status_transport(access_token, video_id, self.timeout_seconds))

    def wait_for_processing(
        self,
        video_id: str,
        *,
        attempts: int = 6,
        interval_seconds: float = 10.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> YouTubeVideoStatus:
        """processingStatus가 processing이 아닐 때까지 최대 ``attempts``회 조회한다.
        끝까지 processing이면 processing_status를 WAITING_PROCESSING으로 바꿔 돌려준다."""
        status = self.get_video_status(video_id)
        for _ in range(attempts - 1):
            if status.processing_status != "processing":
                return status
            sleep(interval_seconds)
            status = self.get_video_status(video_id)
        if status.processing_status == "processing":
            return replace(status, processing_status=WAITING_PROCESSING)
        return status

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
