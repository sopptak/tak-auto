"""TikTok Content Posting API Direct Post adapter for approved MP4 videos."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
from math import ceil
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import time


API_BASE = "https://open.tiktokapis.com"
UPLOAD_HOSTS = frozenset({
    "open-upload.tiktokapis.com",
    "upload.us.tiktokapis.com",
    "upload.tiktokapis.com",
})
MAX_VIDEO_BYTES = 100 * 1024 * 1024
MAX_CHUNK_BYTES = 64 * 1024 * 1024
MIN_CHUNK_BYTES = 5 * 1024 * 1024


class TikTokConfigurationError(ValueError):
    """Missing or invalid TikTok publishing configuration."""


class TikTokAPIError(RuntimeError):
    """TikTok API or media transfer failure."""


class TikTokPublishRejectedError(TikTokAPIError):
    """TikTok confirmed that the requested post failed."""


@dataclass(frozen=True)
class TikTokPublishResult:
    publish_id: str
    post_id: str = ""


TikTokJSONTransport = Callable[..., Mapping[str, object]]
TikTokUploadTransport = Callable[..., int]


def _json_request(method: str, url: str, *, access_token: str,
                  body: Mapping[str, object] | None = None,
                  timeout_seconds: float = 30.0) -> Mapping[str, object]:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != "open.tiktokapis.com":
        raise TikTokAPIError("허용되지 않은 TikTok API 주소입니다.")
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=UTF-8",
        "User-Agent": "TAK-AUTO/1.0",
    }
    data = json.dumps(body or {}, ensure_ascii=False).encode("utf-8") if method.upper() != "GET" else None
    request = Request(url, data=data, headers=headers, method=method.upper())
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read(1_000_001)
    except HTTPError as error:
        raise TikTokAPIError(f"TikTok API 요청 실패 (HTTP {error.code}).") from None
    except (URLError, TimeoutError, OSError):
        raise TikTokAPIError("TikTok API 통신 결과를 확인할 수 없습니다.") from None
    if len(raw) > 1_000_000:
        raise TikTokAPIError("TikTok API 응답이 너무 큽니다.")
    try:
        result = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise TikTokAPIError("TikTok API 응답을 해석하지 못했습니다.") from None
    if not isinstance(result, dict):
        raise TikTokAPIError("TikTok API 응답 형식이 올바르지 않습니다.")
    error = result.get("error")
    if isinstance(error, dict) and str(error.get("code") or "ok") != "ok":
        raise TikTokAPIError("TikTok이 요청을 거부했습니다. 앱 승인, 계정 권한, 영상 정보를 확인하세요.")
    return result


def _upload_chunk(upload_url: str, chunk: bytes, *, start: int, total: int,
                  timeout_seconds: float = 60.0) -> int:
    parsed = urlsplit(upload_url)
    if parsed.scheme != "https" or parsed.hostname not in UPLOAD_HOSTS or parsed.username or parsed.password:
        raise TikTokAPIError("TikTok에서 발급한 업로드 주소가 올바르지 않습니다.")
    end = start + len(chunk) - 1
    request = Request(
        upload_url,
        data=chunk,
        headers={
            "Content-Type": "video/mp4",
            "Content-Length": str(len(chunk)),
            "Content-Range": f"bytes {start}-{end}/{total}",
            "User-Agent": "TAK-AUTO/1.0",
        },
        method="PUT",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            response.read(1024)
            return int(response.status)
    except HTTPError as error:
        raise TikTokAPIError(f"TikTok 영상 전송 실패 (HTTP {error.code}).") from None
    except (URLError, TimeoutError, OSError):
        raise TikTokAPIError("TikTok 영상 전송 결과를 확인할 수 없습니다.") from None


@dataclass(frozen=True)
class TikTokClient:
    access_token: str
    open_id: str
    timeout_seconds: float = 30.0
    json_transport: TikTokJSONTransport = _json_request
    upload_transport: TikTokUploadTransport = _upload_chunk
    sleep: Callable[[float], None] = time.sleep

    def __post_init__(self) -> None:
        if not self.access_token.strip():
            raise TikTokConfigurationError("TikTok 액세스 토큰이 없습니다.")
        if not self.open_id.strip():
            raise TikTokConfigurationError("TikTok 계정 Open ID가 없습니다.")

    def _api(self, endpoint: str) -> str:
        if not endpoint.startswith("/v2/"):
            raise TikTokAPIError("TikTok API 경로가 올바르지 않습니다.")
        return API_BASE + endpoint

    def creator_info(self) -> Mapping[str, object]:
        response = self.json_transport(
            "POST", self._api("/v2/post/publish/creator_info/query/"),
            access_token=self.access_token, body={}, timeout_seconds=self.timeout_seconds,
        )
        data = response.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("privacy_level_options"), list):
            raise TikTokAPIError("TikTok 크리에이터 게시 설정을 확인하지 못했습니다.")
        return data

    def _upload_file(self, video_path: Path, upload_url: str) -> None:
        size = video_path.stat().st_size
        if size <= 0 or size > MAX_VIDEO_BYTES:
            raise ValueError("TikTok 영상은 1바이트 이상 100MB 이하여야 합니다.")
        if size <= MAX_CHUNK_BYTES:
            chunk_size = size
            chunk_count = 1
        else:
            chunk_count = ceil(size / MAX_CHUNK_BYTES)
            chunk_size = ceil(size / chunk_count)
        if chunk_size < MIN_CHUNK_BYTES and size >= MIN_CHUNK_BYTES:
            raise ValueError("TikTok 영상 청크 크기가 최소 5MB보다 작습니다.")

        offset = 0
        with video_path.open("rb") as handle:
            for index in range(chunk_count):
                chunk = handle.read(chunk_size)
                if not chunk:
                    raise ValueError("TikTok 영상 파일을 끝까지 읽지 못했습니다.")
                status = self.upload_transport(
                    upload_url, chunk, start=offset, total=size, timeout_seconds=60.0,
                )
                if status not in {200, 201, 206}:
                    raise TikTokAPIError("TikTok 영상 업로드 응답 상태가 올바르지 않습니다.")
                offset += len(chunk)
        if offset != size:
            raise ValueError("TikTok 영상 전송 길이가 원본 파일 크기와 일치하지 않습니다.")

    def publish_video(self, *, video_path: Path | str, title: str, privacy_level: str,
                      disable_comment: bool = False, disable_duet: bool = False,
                      disable_stitch: bool = False, is_aigc: bool = False,
                      poll_attempts: int = 12, poll_interval_seconds: float = 5.0) -> TikTokPublishResult:
        path = Path(video_path).expanduser()
        if not path.is_file() or path.suffix.lower() != ".mp4":
            raise ValueError("TikTok 게시 파일은 존재하는 MP4 파일이어야 합니다.")
        size = path.stat().st_size
        if size <= 0 or size > MAX_VIDEO_BYTES:
            raise ValueError("TikTok 영상은 1바이트 이상 100MB 이하여야 합니다.")
        if not title.strip() or len(title.encode("utf-16-le")) // 2 > 2200:
            raise ValueError("TikTok 캡션은 비어 있지 않고 UTF-16 기준 2,200자 이하여야 합니다.")
        if privacy_level not in {"PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR", "SELF_ONLY"}:
            raise ValueError("TikTok 공개 범위 값이 올바르지 않습니다.")
        if any(not isinstance(value, bool) for value in (disable_comment, disable_duet, disable_stitch, is_aigc)):
            raise ValueError("TikTok 게시 옵션은 true 또는 false여야 합니다.")
        if poll_attempts < 1 or poll_attempts > 30:
            raise ValueError("TikTok 게시 상태 확인 횟수는 1~30회여야 합니다.")

        creator = self.creator_info()
        privacy_options = {str(value) for value in creator.get("privacy_level_options", [])}
        if privacy_level not in privacy_options:
            raise ValueError("선택한 TikTok 공개 범위가 현재 계정에서 허용되지 않습니다.")

        # TikTok allows up to 64MB chunks; keep each chunk within that limit.
        chunk_count = 1 if size <= MAX_CHUNK_BYTES else ceil(size / MAX_CHUNK_BYTES)
        chunk_size = size if chunk_count == 1 else ceil(size / chunk_count)
        initialized = self.json_transport(
            "POST", self._api("/v2/post/publish/video/init/"),
            access_token=self.access_token,
            body={
                "post_info": {
                    "title": title.strip(),
                    "privacy_level": privacy_level,
                    "disable_comment": disable_comment,
                    "disable_duet": disable_duet,
                    "disable_stitch": disable_stitch,
                    "is_aigc": is_aigc,
                },
                "source_info": {
                    "source": "FILE_UPLOAD",
                    "video_size": size,
                    "chunk_size": chunk_size,
                    "total_chunk_count": chunk_count,
                },
            },
            timeout_seconds=self.timeout_seconds,
        )
        data = initialized.get("data")
        if not isinstance(data, dict):
            raise TikTokAPIError("TikTok 업로드 초기화 응답에 데이터가 없습니다.")
        publish_id = str(data.get("publish_id") or "").strip()
        upload_url = str(data.get("upload_url") or "").strip()
        if not publish_id or not upload_url:
            raise TikTokAPIError("TikTok 업로드 ID 또는 전송 주소가 응답에 없습니다.")
        self._upload_file(path, upload_url)

        for attempt in range(poll_attempts):
            status_response = self.json_transport(
                "POST", self._api("/v2/post/publish/status/fetch/"),
                access_token=self.access_token,
                body={"publish_id": publish_id},
                timeout_seconds=self.timeout_seconds,
            )
            status_data = status_response.get("data")
            if not isinstance(status_data, dict):
                raise TikTokAPIError("TikTok 게시 상태 응답을 해석할 수 없습니다.")
            status = str(status_data.get("status") or "").upper()
            if status == "PUBLISH_COMPLETE":
                post_ids = status_data.get("publicaly_available_post_id")
                post_id = str(post_ids[0]) if isinstance(post_ids, list) and post_ids else ""
                return TikTokPublishResult(publish_id=publish_id, post_id=post_id)
            if status == "FAILED":
                raise TikTokPublishRejectedError("TikTok 게시가 실패했습니다. 영상 형식과 실패 사유를 확인하세요.")
            if status not in {"PROCESSING_UPLOAD", "PROCESSING_DOWNLOAD"}:
                raise TikTokAPIError("TikTok 게시 상태를 확인할 수 없습니다.")
            if attempt < poll_attempts - 1:
                self.sleep(poll_interval_seconds)
        raise TikTokAPIError("TikTok 게시 결과 확인 시간이 초과되었습니다.")
