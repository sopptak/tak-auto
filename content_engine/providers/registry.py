"""Provider 선택(Factory). 선택 우선순위: 인자 > TAK_<KIND>_PROVIDER 환경변수 > 기본값.

research 기본값은 PERPLEXITY_API_KEY가 있으면 perplexity, 없으면 mock이다. 그 외 종류의 기본값은
mock이다. 이름을 명시(인자/환경변수)했는데 credential이 없으면 mock으로 조용히 대체하지 않고
오류를 낸다.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import os
from typing import Any

from . import mock, perplexity, skeletons
from .base import ProviderError

_FACTORIES: dict[str, dict[str, Callable[..., Any]]] = {
    "research": {"perplexity": perplexity.PerplexityResearchProvider, "mock": mock.MockResearchProvider},
    "voice": {"elevenlabs": skeletons.ElevenLabsVoiceProvider, "mock": mock.MockVoiceProvider},
    "image": {"recraft": skeletons.RecraftImageProvider, "mock": mock.MockImageProvider},
    "video": {"runway": skeletons.RunwayVideoProvider, "mock": mock.MockVideoProvider},
    "clip": {"opusclip": skeletons.OpusClipProvider, "mock": mock.MockClipProvider},
}
_DEFAULT_REAL = {"research": ("perplexity", perplexity.ENV_KEY)}


def available_providers(kind: str) -> tuple[str, ...]:
    if kind not in _FACTORIES:
        raise ProviderError(f"알 수 없는 provider 종류: {kind!r}")
    return tuple(_FACTORIES[kind])


def _get(kind: str, name: str | None, environ: Mapping[str, str] | None, **kwargs: Any) -> Any:
    values = os.environ if environ is None else environ
    options = available_providers(kind)
    chosen = (name or values.get(f"TAK_{kind.upper()}_PROVIDER") or "").strip().lower()
    if not chosen:
        real = _DEFAULT_REAL.get(kind)
        chosen = real[0] if real and (values.get(real[1]) or "").strip() else "mock"
    if chosen not in options:
        raise ProviderError(f"알 수 없는 {kind} provider {chosen!r} (선택 가능: {', '.join(options)})")
    factory = _FACTORIES[kind][chosen]
    if chosen == "mock":
        return factory(**kwargs)
    return factory(environ=values, **kwargs)


def get_research_provider(name: str | None = None, environ: Mapping[str, str] | None = None, **kwargs: Any):
    return _get("research", name, environ, **kwargs)


def get_voice_provider(name: str | None = None, environ: Mapping[str, str] | None = None, **kwargs: Any):
    return _get("voice", name, environ, **kwargs)


def get_image_provider(name: str | None = None, environ: Mapping[str, str] | None = None, **kwargs: Any):
    return _get("image", name, environ, **kwargs)


def get_video_provider(name: str | None = None, environ: Mapping[str, str] | None = None, **kwargs: Any):
    return _get("video", name, environ, **kwargs)


def get_clip_provider(name: str | None = None, environ: Mapping[str, str] | None = None, **kwargs: Any):
    return _get("clip", name, environ, **kwargs)
