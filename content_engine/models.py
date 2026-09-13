"""TAK미디어 콘텐츠 엔진의 입력 요약과 출력 모델."""

from __future__ import annotations

from dataclasses import dataclass


BLOG_COUNT = 1
SHORTS_COUNT = 3
THREADS_COUNT = 5


@dataclass(frozen=True)
class EvidenceUnit:
    """승인된 KNOWLEDGE 필드에서 분해한 콘텐츠 추적용 근거 단위."""

    id: str
    field_name: str
    text: str


@dataclass(frozen=True)
class ContentBrief:
    """KNOWLEDGE에서 콘텐츠 변환에 사용할 사실과 근거만 담는다."""

    knowledge_id: str
    title: str
    source_url: str
    experience: str | None
    problem: str | None
    action: str | None
    result: str | None
    lesson: str | None
    reusable_principle: str | None
    derived_insight: str | None
    evidence: tuple[str, ...]
    evidence_units: tuple[EvidenceUnit, ...]


@dataclass(frozen=True)
class ContentDraft:
    title: str
    body: str
    source_url: str
    evidence: tuple[str, ...]
    evidence_unit_ids: tuple[str, ...] = ()


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
    blog: BlogDraft | None
    shorts: tuple[ShortDraft, ...]
    threads: tuple[ThreadDraft, ...]
    status: str = "complete"
    unmet_requirement_ids: tuple[str, ...] = ()

    def validate_counts(self) -> None:
        if self.status == "insufficient_distinct_evidence":
            if self.blog is not None or self.shorts or self.threads:
                raise ValueError("근거 부족 묶음에는 부분 콘텐츠를 포함할 수 없습니다.")
            return
        if self.status != "complete":
            raise ValueError("알 수 없는 콘텐츠 생성 상태입니다.")
        if self.blog is None:
            raise ValueError("완성된 콘텐츠 묶음에는 블로그가 필요합니다.")
        if len((self.blog,)) != BLOG_COUNT:
            raise ValueError(f"블로그 콘텐츠 수는 {BLOG_COUNT}개여야 합니다.")
        if len(self.shorts) != SHORTS_COUNT:
            raise ValueError(f"Shorts 콘텐츠 수는 {SHORTS_COUNT}개여야 합니다.")
        if len(self.threads) != THREADS_COUNT:
            raise ValueError(f"Threads 콘텐츠 수는 {THREADS_COUNT}개여야 합니다.")