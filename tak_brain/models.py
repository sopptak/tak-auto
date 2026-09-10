"""원본(RAW)과 분석(KNOWLEDGE)을 분리한 모델."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from blog_importer.models import BlogPost, utc_now


CATEGORIES = ("금융", "대출", "경매", "부동산", "인간관계", "심리", "자기계발", "독서", "건강", "가족", "골프", "기타")
KNOWLEDGE_TYPES = ("경험", "사례", "판단기준", "정보", "의견")
_PRIVACY_PATTERN = re.compile(r"주민등록번호|주민번호|개인정보|010[- ]?\d{3,4}[- ]?\d{4}|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
_INTERNAL_PATTERN = re.compile(r"내부정보|대외비|비공개|기관 내부|internal", re.IGNORECASE)


@dataclass(frozen=True)
class RawContent:
    id: str
    title: str
    published_at: str
    body: str
    tags: tuple[str, ...]
    source_url: str
    source: str
    collected_at: str
    content_hash: str

    @classmethod
    def from_post(cls, post: BlogPost) -> "RawContent":
        return cls(post.id, post.title, post.published_at, post.body, post.tags, post.source_url, post.source, post.collected_at, post.content_hash)


@dataclass(frozen=True)
class KnowledgeRecord:
    category: str | None = None
    knowledge_type: str | None = None
    summary: str | None = None
    key_points: tuple[str, ...] = ()
    experience: str | None = None
    case: str | None = None
    judgment_rule: str | None = None
    opinion: str | None = None
    factual_information: str | None = None
    current_validity: str | None = None
    verification_required: bool = False
    privacy_risk: bool = False
    internal_information_risk: bool = False


@dataclass(frozen=True)
class BrainRecord:
    raw: RawContent
    metadata: dict[str, Any]
    knowledge: KnowledgeRecord | None = None


def build_metadata(post: BlogPost) -> dict[str, Any]:
    searchable = f"{post.title}\n{post.body}"
    return {
        "content_hash": post.content_hash,
        "source": post.source,
        "collected_at": post.collected_at or utc_now(),
        "tags": list(post.tags),
        "privacy_risk": bool(_PRIVACY_PATTERN.search(searchable)),
        "internal_information_risk": bool(_INTERNAL_PATTERN.search(searchable)),
        "verification_required": True,
    }