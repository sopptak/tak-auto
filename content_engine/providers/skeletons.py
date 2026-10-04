"""ElevenLabs / Recraft / Runway / OpusClip Adapter 골격.

현재 프로젝트에서 각 서비스의 API 계약을 검증하지 못했으므로(credential 없음) 가짜 호출을
만들지 않는다. 생성 시 credential만 검증하고, 실제 호출 메서드는 ProviderNotImplementedError를
낸다. 실제 구현은 각 TODO 위치에 해당 서비스 공식 문서를 확인한 뒤 채운다.
"""

from __future__ import annotations

from collections.abc import Mapping

from .base import (
    ClipProvider, ClipResult, ImageProvider, MediaGenerationResult, ProviderNotImplementedError,
    VideoProvider, VideoResult, VoiceProvider, VoiceResult, require_env,
)


def _todo(service: str, operation: str) -> ProviderNotImplementedError:
    return ProviderNotImplementedError(
        f"{service}.{operation}: API 연동이 아직 구현되지 않았습니다(docs/providers.md 참고)."
    )


class ElevenLabsVoiceProvider(VoiceProvider):
    name = "elevenlabs"
    ENV_KEY = "ELEVENLABS_API_KEY"

    def __init__(self, api_key: str | None = None, environ: Mapping[str, str] | None = None) -> None:
        self._api_key = api_key or require_env(self.ENV_KEY, environ)

    def synthesize(self, text, voice_id=None, output_path=None) -> VoiceResult:
        raise _todo("elevenlabs", "synthesize")  # TODO: text-to-speech 호출 + 오디오 local_path 저장


class RecraftImageProvider(ImageProvider):
    name = "recraft"
    ENV_KEY = "RECRAFT_API_KEY"

    def __init__(self, api_key: str | None = None, environ: Mapping[str, str] | None = None) -> None:
        self._api_key = api_key or require_env(self.ENV_KEY, environ)

    def generate(self, prompt, size=None, style=None) -> MediaGenerationResult:
        raise _todo("recraft", "generate")  # TODO: 이미지 생성 + 임시 URL 다운로드/보존

    def edit(self, image_path, prompt) -> MediaGenerationResult:
        raise _todo("recraft", "edit")

    def upscale(self, image_path) -> MediaGenerationResult:
        raise _todo("recraft", "upscale")


class RunwayVideoProvider(VideoProvider):
    name = "runway"
    ENV_KEY = "RUNWAYML_API_SECRET"

    def __init__(self, api_key: str | None = None, environ: Mapping[str, str] | None = None) -> None:
        self._api_key = api_key or require_env(self.ENV_KEY, environ)

    def generate(self, prompt, image_path=None, duration_seconds=None) -> VideoResult:
        raise _todo("runway", "generate")  # TODO: 비동기 task 생성 -> 폴링 -> 결과 보존


class OpusClipProvider(ClipProvider):
    name = "opusclip"
    ENV_KEY = "OPUSCLIP_API_KEY"

    def __init__(self, api_key: str | None = None, environ: Mapping[str, str] | None = None) -> None:
        self._api_key = api_key or require_env(self.ENV_KEY, environ)

    def create_shorts(self, source_video_url, max_clips=3) -> ClipResult:
        raise _todo("opusclip", "create_shorts")  # TODO: project 생성 -> 클립 조회
