"""TAK미디어 콘텐츠 엔진의 입력 요약과 출력 모델."""

from __future__ import annotations

from dataclasses import dataclass


BLOG_COUNT = 1
SHORTS_COUNT = 3
THREADS_COUNT = 5


@dataclass(frozen=True)
class ContentBrief:
    """KNOWLEDGE에서 콘텐츠 변환에 사용할 사실과 근거만 담는다."""

    knowledge_id: str
    title: str
    source_url: str
    experience: str
    problem: str
    action: str
    result: str
    lesson: str
    reusable_principle: str
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class ContentDraft:
    title: str
    body: str
    source_url: str
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class BlogDraft(ContentDraft):
    pass


@dataclass(frozen=True)
class ShortDraft(ContentDraft):
    pass


@dataclass(frozen=True)
class ThreadDraft(ContentDraft):
    pass


@dataclass(frozen=True)
class ContentBundle:
    blog: BlogDraft
    shorts: tuple[ShortDraft, ...]
    threads: tuple[ThreadDraft, ...]

    def validate_counts(self) -> None:
        if len((self.blog,)) != BLOG_COUNT:
            raise ValueError(f"블로그 콘텐츠 수는 {BLOG_COUNT}개여야 합니다.")
        if len(self.shorts) != SHORTS_COUNT:
            raise ValueError(f"Shorts 콘텐츠 수는 {SHORTS_COUNT}개여야 합니다.")
        if len(self.threads) != THREADS_COUNT:
            raise ValueError(f"Threads 콘텐츠 수는 {THREADS_COUNT}개여야 합니다.")