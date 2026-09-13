"""Threads 공식 Graph API를 통한 콘텐츠 게시 클라이언트."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
import os
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class ThreadsConfigurationError(ValueError):
    """Threads API 호출에 필요한 환경 설정이 없을 때 발생한다."""


class ThreadsAPIError(ValueError):
    """Threads Graph API 호출이 실패하거나 비정상 응답을 반환할 때 발생한다."""


@dataclass(frozen=True)
class ThreadsPublishResult:
    """Threads 게시 성공 결과."""

    id: str


@dataclass(frozen=True)
class ThreadsProfile:
    """Threads 계정 프로필 정보."""

    id: str
    username: str
    name: str | None = None


ThreadsTransport = Callable[[str, str, Mapping[str, str], Mapping[str, object] | None, float], Mapping[str, object]]


def _default_http_transport(
    method: str,
    url: str,
    headers: Mapping[str, str],
    payload: Mapping[str, object] | None,
    timeout_seconds: float,
) -> Mapping[str, object]:
    data_bytes = None
    if payload is not None and method.upper() == "POST":
        data_bytes = urlencode({k: str(v) for k, v in payload.items() if v is not None}).encode("utf-8")

    request = Request(
        url,
        data=data_bytes,
        headers=dict(headers),
        method=method.upper(),
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise ThreadsAPIError(_safe_http_error_message(error)) from None
    except Exception as error:
        raise ThreadsAPIError(f"Threads API 통신 실패: {type(error).__name__}") from None

    if not isinstance(data, dict):
        raise ThreadsAPIError("Threads API 응답은 JSON 객체여야 합니다.")
    return data


def _safe_http_error_message(error: HTTPError) -> str:
    """HTTP 에러 응답에서 민감정보(토큰 등)를 제외하고 안전한 오류 필드만 추출한다."""
    details = []
    try:
        body = json.loads(error.read().decode("utf-8"))
        error_obj = body.get("error", {}) if isinstance(body, dict) else {}
        if isinstance(error_obj, dict):
            for field in ("message", "type", "code", "error_subcode", "fbtrace_id"):
                val = error_obj.get(field)
                if val is not None and str(val):
                    details.append(f"{field}={val}")
    except (UnicodeDecodeError, json.JSONDecodeError, OSError):
        pass
    detail_text = "; ".join(details) if details else "Threads API 오류 상세를 읽을 수 없습니다."
    return f"Threads HTTP {error.code}: {detail_text}"


@dataclass(frozen=True)
class ThreadsClient:
    """Threads Graph API 클라이언트."""

    access_token: str
    api_base: str = "https://graph.threads.net"
    timeout_seconds: float = 30.0
    transport: ThreadsTransport = _default_http_transport

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
        transport: ThreadsTransport = _default_http_transport,
    ) -> "ThreadsClient":
        values = os.environ if environ is None else environ
        token = values.get("THREADS_ACCESS_TOKEN", "").strip()
        if not token:
            raise ThreadsConfigurationError("THREADS_ACCESS_TOKEN 환경변수가 필요합니다.")
        api_base = values.get("THREADS_API_BASE", "https://graph.threads.net").rstrip("/")
        return cls(access_token=token, api_base=api_base, transport=transport)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/x-www-form-urlencoded",
        }

    def get_profile(self) -> ThreadsProfile:
        """GET /me?fields=id,username,name 호출하여 현재 인증된 계정 정보를 조회한다."""
        query = urlencode({"fields": "id,username,name"})
        url = f"{self.api_base}/me?{query}"
        response = self.transport("GET", url, self._headers(), None, self.timeout_seconds)

        profile_id = response.get("id")
        username = response.get("username")
        if not profile_id or not username:
            raise ThreadsAPIError("Threads 프로필 응답에 id와 username이 필요합니다.")
        return ThreadsProfile(
            id=str(profile_id),
            username=str(username),
            name=str(response.get("name")) if response.get("name") is not None else None,
        )

    def publish_text(
        self,
        text: str,
        reply_control: str | None = None,
        topic_tag: str | None = None,
    ) -> ThreadsPublishResult:
        """POST /me/threads로 텍스트 콘텐츠를 단건 게시한다."""
        clean_text = text.strip() if text else ""
        if not clean_text:
            raise ValueError("게시할 Threads 텍스트가 비어 있습니다.")
        if len(clean_text) > 500:
            raise ValueError(f"Threads text exceeds 500 characters: {len(clean_text)}")

        url = f"{self.api_base}/me/threads"
        payload: dict[str, object] = {
            "media_type": "TEXT",
            "text": clean_text,
            "auto_publish_text": "true",
        }
        if reply_control:
            payload["reply_control"] = reply_control
        if topic_tag:
            payload["topic_tag"] = topic_tag

        response = self.transport("POST", url, self._headers(), payload, self.timeout_seconds)
        thread_id = response.get("id")
        if not thread_id:
            raise ThreadsAPIError("Threads 게시 응답에 게시물 id가 누락되었습니다.")
        return ThreadsPublishResult(id=str(thread_id))
