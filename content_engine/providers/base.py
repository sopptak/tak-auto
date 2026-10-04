"""외부 AI 서비스 Provider 공통 모델/예외/인터페이스.

외부 API 응답(vendor JSON)은 각 Provider 안에서 이 모듈의 표준 모델로 변환하고,
콘텐츠 엔진에는 표준 모델만 전달한다. 모든 Provider 호출은 사람이 시작한 명시적
호출이며, 이 계층은 어떤 플랫폼에도 발행하지 않는다.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
import os
from typing import Any

STATUS_COMPLETED = "completed"
STATUS_PENDING = "pending"
STATUS_FAILED = "failed"
STATUSES = (STATUS_COMPLETED, STATUS_PENDING, STATUS_FAILED)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProviderError(RuntimeError):
    """Provider 계층의 모든 오류의 기반 클래스."""


class ProviderNotConfiguredError(ProviderError):
    """필요한 credential/설정이 없다."""


class ProviderNotImplementedError(ProviderError):
    """Adapter 골격만 있고 실제 API 호출이 아직 구현되지 않았다."""


class ProviderRequestError(ProviderError):
    """네트워크 실패, HTTP 오류 등 요청 자체가 실패했다."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ProviderAuthError(ProviderRequestError):
    """인증/권한 오류(HTTP 401/403)."""


class ProviderResponseError(ProviderError):
    """응답이 예상한 형식이 아니다."""


@dataclass(frozen=True)
class ResultBase:
    provider: str
    request_id: str = ""
    status: str = STATUS_COMPLETED
    created_at: str = field(default_factory=utc_now_iso)
    # 벤더가 준 URL은 임시일 수 있다 - 보존이 필요하면 내려받아 local_path에 둔다.
    output_url: str = ""
    local_path: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    error: str = ""

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ProviderError(f"알 수 없는 status: {self.status!r}")


@dataclass(frozen=True)
class ResearchSource:
    title: str
    url: str
    snippet: str = ""
    domain: str = ""
    published_at: str = ""
    rank: int = 0


@dataclass(frozen=True)
class ResearchResult(ResultBase):
    query: str = ""
    sources: tuple[ResearchSource, ...] = ()


@dataclass(frozen=True)
class VoiceResult(ResultBase):
    duration_seconds: float | None = None


@dataclass(frozen=True)
class MediaGenerationResult(ResultBase):
    width: int | None = None
    height: int | None = None


@dataclass(frozen=True)
class VideoResult(ResultBase):
    duration_seconds: float | None = None


@dataclass(frozen=True)
class ClipResult(ResultBase):
    clip_urls: tuple[str, ...] = ()


class ResearchProvider(ABC):
    name: str = ""

    @abstractmethod
    def research(
        self,
        query: str,
        domains: list[str] | None = None,
        recency: str | None = None,
        max_results: int = 5,
    ) -> ResearchResult: ...

    def search(self, query: str, **kwargs: Any) -> ResearchResult:
        return self.research(query, **kwargs)


class VoiceProvider(ABC):
    name: str = ""

    @abstractmethod
    def synthesize(self, text: str, voice_id: str | None = None, output_path: str | None = None) -> VoiceResult: ...


class ImageProvider(ABC):
    name: str = ""

    @abstractmethod
    def generate(self, prompt: str, size: str | None = None, style: str | None = None) -> MediaGenerationResult: ...

    @abstractmethod
    def edit(self, image_path: str, prompt: str) -> MediaGenerationResult: ...

    @abstractmethod
    def upscale(self, image_path: str) -> MediaGenerationResult: ...


class VideoProvider(ABC):
    name: str = ""

    @abstractmethod
    def generate(
        self, prompt: str, image_path: str | None = None, duration_seconds: int | None = None
    ) -> VideoResult: ...


class ClipProvider(ABC):
    name: str = ""

    @abstractmethod
    def create_shorts(self, source_video_url: str, max_clips: int = 3) -> ClipResult: ...


def require_env(name: str, environ: Mapping[str, str] | None = None) -> str:
    """환경변수 값을 돌려주고, 없으면 값 없이 변수명만 담은 오류를 낸다."""
    values = os.environ if environ is None else environ
    value = (values.get(name) or "").strip()
    if not value:
        raise ProviderNotConfiguredError(f"환경변수 {name}이(가) 설정되지 않았습니다.")
    return value
