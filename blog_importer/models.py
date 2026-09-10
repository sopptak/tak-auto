"""블로그 원본의 표준 데이터 모델."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Mapping


class ValidationError(ValueError):
    """입력 원본이 표준 모델을 만족하지 않을 때 발생합니다."""


REQUIRED_FIELDS = ("id", "title", "published_at", "body", "source_url", "source")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class BlogPost:
    id: str
    title: str
    published_at: str
    body: str
    tags: tuple[str, ...] = field(default_factory=tuple)
    source_url: str = ""
    source: str = ""
    collected_at: str = field(default_factory=utc_now)
    content_hash: str = ""

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "BlogPost":
        missing = []
        for name in REQUIRED_FIELDS:
            value = data.get(name)
            if value is None or (isinstance(value, str) and not value.strip()):
                missing.append(name)
        if missing:
            raise ValidationError(f"필수 필드가 없습니다: {', '.join(missing)}")

        tags = data.get("tags", ())
        if isinstance(tags, str):
            tags = tuple(tag.strip() for tag in tags.split(",") if tag.strip())
        elif isinstance(tags, (list, tuple)):
            tags = tuple(str(tag).strip() for tag in tags if str(tag).strip())
        else:
            raise ValidationError("tags는 문자열 목록이어야 합니다.")

        post = cls(
            id=str(data["id"]).strip(),
            title=str(data["title"]).strip(),
            published_at=str(data["published_at"]).strip(),
            body=str(data["body"]),
            tags=tags,
            source_url=str(data["source_url"]).strip(),
            source=str(data["source"]).strip(),
            collected_at=str(data.get("collected_at") or utc_now()).strip(),
            content_hash="",
        )
        generated_hash = post.calculate_content_hash()
        supplied_hash = str(data.get("content_hash") or "").strip()
        if supplied_hash and supplied_hash != generated_hash:
            raise ValidationError("content_hash가 원본 내용과 일치하지 않습니다.")
        return cls(**{**asdict(post), "content_hash": generated_hash})

    def calculate_content_hash(self) -> str:
        payload = {
            "title": self.title,
            "published_at": self.published_at,
            "body": self.body,
            "tags": list(self.tags),
            "source_url": self.source_url,
            "source": self.source,
        }
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["tags"] = list(self.tags)
        return result