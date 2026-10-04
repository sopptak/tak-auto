"""네트워크/credential 없이 쓰는 결정적 Mock Provider(테스트·로컬 개발용)."""

from __future__ import annotations

from .base import (
    ClipProvider, ClipResult, ImageProvider, MediaGenerationResult, ResearchProvider,
    ResearchResult, ResearchSource, VideoProvider, VideoResult, VoiceProvider, VoiceResult,
)


class MockResearchProvider(ResearchProvider):
    name = "mock"

    def __init__(self, sources: list[ResearchSource] | None = None, **_ignored) -> None:
        self._sources = sources
        self.calls: list[dict] = []

    def research(self, query, domains=None, recency=None, max_results=5):
        self.calls.append({"query": query, "domains": domains, "recency": recency, "max_results": max_results})
        sources = self._sources or [
            ResearchSource(
                title=f"Mock source {i} for {query}", url=f"https://example.com/mock/{i}",
                snippet=f"mock snippet {i}", domain="example.com", rank=i,
            )
            for i in range(1, max_results + 1)
        ]
        return ResearchResult(
            provider=self.name, request_id="mock-research", query=query, sources=tuple(sources[:max_results])
        )


class MockVoiceProvider(VoiceProvider):
    name = "mock"

    def __init__(self, **_ignored) -> None:
        pass

    def synthesize(self, text, voice_id=None, output_path=None):
        return VoiceResult(
            provider=self.name, request_id="mock-voice", local_path=output_path or "",
            metadata={"chars": len(text), "voice_id": voice_id},
        )


class MockImageProvider(ImageProvider):
    name = "mock"

    def __init__(self, **_ignored) -> None:
        pass

    def generate(self, prompt, size=None, style=None):
        return MediaGenerationResult(
            provider=self.name, request_id="mock-image", metadata={"prompt": prompt, "style": style}
        )

    def edit(self, image_path, prompt):
        return MediaGenerationResult(provider=self.name, request_id="mock-image-edit", metadata={"source": image_path})

    def upscale(self, image_path):
        return MediaGenerationResult(
            provider=self.name, request_id="mock-image-upscale", metadata={"source": image_path}
        )


class MockVideoProvider(VideoProvider):
    name = "mock"

    def __init__(self, **_ignored) -> None:
        pass

    def generate(self, prompt, image_path=None, duration_seconds=None):
        return VideoResult(
            provider=self.name, request_id="mock-video", duration_seconds=duration_seconds,
            metadata={"prompt": prompt},
        )


class MockClipProvider(ClipProvider):
    name = "mock"

    def __init__(self, **_ignored) -> None:
        pass

    def create_shorts(self, source_video_url, max_clips=3):
        urls = tuple(f"mock://clip/{i}" for i in range(1, max_clips + 1))
        return ClipResult(
            provider=self.name, request_id="mock-clip", clip_urls=urls, metadata={"source": source_video_url}
        )
