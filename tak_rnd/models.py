"""R&D Radar items and implementation ideas for TAK AUTO."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import math
import re
from typing import Any, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4


RND_CATEGORIES = (
    "ai", "ai_agent", "claude_code", "github", "automation", "browser_automation",
    "content", "seo", "threads", "youtube", "shorts", "multilingual", "data",
    "monetization", "other",
)
SOURCES = ("threads", "web", "github", "youtube", "manual", "aside", "other")
DIFFICULTIES = ("low", "medium", "high", "unknown")
EVIDENCE_STATUSES = ("unverified", "partial", "verified", "disputed")
RND_STATUSES = ("captured", "reviewing", "promoted", "archived", "rejected")
IDEA_STATUSES = (
    "captured", "triaged", "research", "proposed", "approved", "implementing",
    "implemented", "validated", "rejected", "parked",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _string(value: Any, field_name: str, *, required: bool = False) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ValueError(f"{field_name}은 문자열이어야 합니다.")
    normalized = value.strip()
    if required and not normalized:
        raise ValueError(f"{field_name}은 필수입니다.")
    return normalized


def _string_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{field_name}은 문자열 목록이어야 합니다.")
    result = tuple(str(item).strip() for item in value if str(item).strip())
    return tuple(dict.fromkeys(result))


def _score(value: Any, field_name: str) -> int | None:
    if value is None or value == "":
        return None
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 5:
        raise ValueError(f"{field_name}은 1~5 정수여야 합니다.")
    return value


def _timestamp(value: Any, field_name: str) -> str:
    timestamp = _string(value, field_name, required=True)
    try:
        datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{field_name}은 ISO 8601 시각이어야 합니다.") from error
    return timestamp


def canonicalize_url(value: str) -> str:
    """Normalize an HTTP(S) URL for safe duplicate comparison."""
    url = _string(value, "source_url")
    if not url:
        return ""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as error:
        raise ValueError("source_url 형식이 올바르지 않습니다.") from error
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        raise ValueError("source_url은 사용자 정보가 없는 http(s) URL이어야 합니다.")
    host = parts.hostname.lower()
    if any(character.isspace() for character in host):
        raise ValueError("source_url의 호스트가 올바르지 않습니다.")
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError as error:
        raise ValueError("source_url의 호스트가 올바르지 않습니다.") from error
    netloc = f"[{host}]" if ":" in host else host
    if port is not None and not (parts.scheme.lower() == "http" and port == 80) and not (
        parts.scheme.lower() == "https" and port == 443
    ):
        netloc = f"{netloc}:{port}"
    query = [
        (key, item)
        for key, item in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in {"fbclid", "gclid"}
    ]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), netloc, path, urlencode(query), ""))


def _generated_rnd_id(source: str, canonical_url: str, source_item_id: str, title: str) -> str:
    identity = canonical_url or source_item_id
    if not identity:
        return f"rnd-{uuid4().hex[:12]}"
    normalized = f"{source.strip().lower()}|{identity.strip().lower()}|{title.strip().casefold()}"
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]
    return f"rnd-{digest}"


def _validate_choice(value: str, choices: tuple[str, ...], name: str) -> str:
    if value not in choices:
        raise ValueError(f"{name}은 {choices} 중 하나여야 합니다: {value!r}")
    return value


@dataclass(frozen=True)
class RndItem:
    id: str
    captured_at: str
    source: str
    source_url: str
    canonical_url: str
    source_author: str
    source_item_id: str
    title: str
    summary: str
    key_points: tuple[str, ...] = ()
    technologies: tuple[str, ...] = ()
    categories: tuple[str, ...] = ("other",)
    media: tuple[str, ...] = ()
    relevance_score: int | None = None
    novelty_score: int | None = None
    expected_impact_score: int | None = None
    implementation_difficulty: str = "unknown"
    evidence_status: str = "unverified"
    duplicate_candidate_ids: tuple[str, ...] = ()
    canonical_id: str | None = None
    notes: str = ""
    status: str = "captured"
    last_updated_at: str = ""

    def __post_init__(self) -> None:
        for name in ("id", "title"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name}은 필수입니다.")
        _timestamp(self.captured_at, "captured_at")
        _validate_choice(self.source, SOURCES, "source")
        _validate_choice(self.implementation_difficulty, DIFFICULTIES, "implementation_difficulty")
        _validate_choice(self.evidence_status, EVIDENCE_STATUSES, "evidence_status")
        _validate_choice(self.status, RND_STATUSES, "status")
        if self.source_url and canonicalize_url(self.source_url) != self.canonical_url:
            raise ValueError("canonical_url이 source_url과 일치하지 않습니다.")
        if not self.source_url and self.canonical_url:
            raise ValueError("source_url이 없으면 canonical_url을 지정할 수 없습니다.")
        for name in ("relevance_score", "novelty_score", "expected_impact_score"):
            _score(getattr(self, name), name)
        if self.canonical_id == self.id:
            raise ValueError("canonical_id는 자기 자신의 id일 수 없습니다.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "captured_at": self.captured_at,
            "source": self.source,
            "source_url": self.source_url,
            "canonical_url": self.canonical_url,
            "source_author": self.source_author,
            "source_item_id": self.source_item_id,
            "title": self.title,
            "summary": self.summary,
            "key_points": list(self.key_points),
            "technologies": list(self.technologies),
            "categories": list(self.categories),
            "media": list(self.media),
            "relevance_score": self.relevance_score,
            "novelty_score": self.novelty_score,
            "expected_impact_score": self.expected_impact_score,
            "implementation_difficulty": self.implementation_difficulty,
            "evidence_status": self.evidence_status,
            "duplicate_candidate_ids": list(self.duplicate_candidate_ids),
            "canonical_id": self.canonical_id,
            "notes": self.notes,
            "status": self.status,
            "last_updated_at": self.last_updated_at,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "RndItem":
        if not isinstance(data, Mapping):
            raise ValueError("R&D 입력은 객체여야 합니다.")
        source = _string(data.get("source", data.get("platform", "manual")), "source").lower()
        url = _string(data.get("source_url", data.get("url", "")), "source_url")
        canonical_url = canonicalize_url(url)
        title = _string(data.get("title"), "title", required=True)
        categories = _string_tuple(data.get("categories", data.get("category", ("other",))), "categories")
        categories = tuple(category.lower().replace(" ", "_") for category in categories) or ("other",)
        invalid_categories = tuple(category for category in categories if category not in RND_CATEGORIES)
        if invalid_categories:
            raise ValueError(f"지원하지 않는 categories입니다: {invalid_categories}")
        captured_at = _timestamp(data.get("captured_at") or utc_now(), "captured_at")
        source_item_id = _string(data.get("source_item_id", ""), "source_item_id")
        item_id = _string(
            data.get("id") or _generated_rnd_id(source, canonical_url, source_item_id, title),
            "id",
            required=True,
        )
        return cls(
            id=item_id,
            captured_at=captured_at,
            source=source,
            source_url=url,
            canonical_url=canonical_url,
            source_author=_string(data.get("source_author", data.get("author", "")), "source_author"),
            source_item_id=source_item_id,
            title=title,
            summary=_string(data.get("summary", data.get("text", "")), "summary"),
            key_points=_string_tuple(data.get("key_points"), "key_points"),
            technologies=_string_tuple(data.get("technologies", data.get("tags")), "technologies"),
            categories=categories,
            media=_string_tuple(data.get("media"), "media"),
            relevance_score=_score(data.get("relevance_score"), "relevance_score"),
            novelty_score=_score(data.get("novelty_score"), "novelty_score"),
            expected_impact_score=_score(data.get("expected_impact_score"), "expected_impact_score"),
            implementation_difficulty=_string(data.get("implementation_difficulty") or "unknown", "implementation_difficulty"),
            evidence_status=_string(data.get("evidence_status") or "unverified", "evidence_status"),
            duplicate_candidate_ids=_string_tuple(data.get("duplicate_candidate_ids"), "duplicate_candidate_ids"),
            canonical_id=_string(data.get("canonical_id"), "canonical_id") or None,
            notes=_string(data.get("notes"), "notes"),
            status=_string(data.get("status") or "captured", "status"),
            last_updated_at=_string(data.get("last_updated_at") or captured_at, "last_updated_at"),
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RndItem":
        return cls.from_mapping(data)


@dataclass(frozen=True)
class Idea:
    id: str
    created_at: str
    source_rnd_ids: tuple[str, ...]
    title: str
    description: str
    why_important: str
    application_areas: tuple[str, ...]
    expected_impact: str
    implementation_difficulty: str = "unknown"
    estimated_effort_hours: float | None = None
    strategic_fit_score: int | None = None
    expected_impact_score: int | None = None
    novelty_score: int | None = None
    status: str = "captured"
    related_features: tuple[str, ...] = ()
    needs_validation: bool = True
    validation_plan: str = ""
    implemented_at: str | None = None
    implementation_result: str = ""
    outcome: str = ""
    related_content_ids: tuple[str, ...] = ()
    duplicate_candidate_ids: tuple[str, ...] = ()
    canonical_id: str | None = None
    last_updated_at: str = ""

    def __post_init__(self) -> None:
        for name in ("id", "title", "description", "why_important"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name}은 필수입니다.")
        _timestamp(self.created_at, "created_at")
        _validate_choice(self.implementation_difficulty, DIFFICULTIES, "implementation_difficulty")
        _validate_choice(self.status, IDEA_STATUSES, "status")
        for name in ("strategic_fit_score", "expected_impact_score", "novelty_score"):
            _score(getattr(self, name), name)
        if self.estimated_effort_hours is not None and (
            isinstance(self.estimated_effort_hours, bool)
            or not isinstance(self.estimated_effort_hours, (int, float))
            or not math.isfinite(self.estimated_effort_hours)
            or self.estimated_effort_hours < 0
        ):
            raise ValueError("estimated_effort_hours는 0 이상의 숫자여야 합니다.")
        if self.canonical_id == self.id:
            raise ValueError("canonical_id는 자기 자신의 id일 수 없습니다.")

    @property
    def priority_score(self) -> int | None:
        difficulty = {"low": 1, "medium": 3, "high": 5}.get(self.implementation_difficulty)
        if self.strategic_fit_score is None or self.expected_impact_score is None or self.novelty_score is None or difficulty is None:
            return None
        return 2 * self.strategic_fit_score + 2 * self.expected_impact_score + self.novelty_score - difficulty

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "source_rnd_ids": list(self.source_rnd_ids),
            "title": self.title,
            "description": self.description,
            "why_important": self.why_important,
            "application_areas": list(self.application_areas),
            "expected_impact": self.expected_impact,
            "implementation_difficulty": self.implementation_difficulty,
            "estimated_effort_hours": self.estimated_effort_hours,
            "strategic_fit_score": self.strategic_fit_score,
            "expected_impact_score": self.expected_impact_score,
            "novelty_score": self.novelty_score,
            "priority_score": self.priority_score,
            "status": self.status,
            "related_features": list(self.related_features),
            "needs_validation": self.needs_validation,
            "validation_plan": self.validation_plan,
            "implemented_at": self.implemented_at,
            "implementation_result": self.implementation_result,
            "outcome": self.outcome,
            "related_content_ids": list(self.related_content_ids),
            "duplicate_candidate_ids": list(self.duplicate_candidate_ids),
            "canonical_id": self.canonical_id,
            "last_updated_at": self.last_updated_at,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "Idea":
        if not isinstance(data, Mapping):
            raise ValueError("IDEA 입력은 객체여야 합니다.")
        effort = data.get("estimated_effort_hours")
        try:
            effort = None if effort is None or effort == "" else float(effort)
        except (TypeError, ValueError) as error:
            raise ValueError("estimated_effort_hours는 0 이상의 숫자여야 합니다.") from error
        created_at = _timestamp(data.get("created_at") or utc_now(), "created_at")
        needs_validation = data.get("needs_validation", True)
        if not isinstance(needs_validation, bool):
            raise ValueError("needs_validation은 boolean이어야 합니다.")
        return cls(
            id=_string(data.get("id") or f"idea-{uuid4().hex[:12]}", "id", required=True),
            created_at=created_at,
            source_rnd_ids=_string_tuple(data.get("source_rnd_ids"), "source_rnd_ids"),
            title=_string(data.get("title"), "title", required=True),
            description=_string(data.get("description"), "description", required=True),
            why_important=_string(data.get("why_important"), "why_important", required=True),
            application_areas=_string_tuple(data.get("application_areas"), "application_areas"),
            expected_impact=_string(data.get("expected_impact"), "expected_impact"),
            implementation_difficulty=_string(data.get("implementation_difficulty") or "unknown", "implementation_difficulty"),
            estimated_effort_hours=effort,
            strategic_fit_score=_score(data.get("strategic_fit_score"), "strategic_fit_score"),
            expected_impact_score=_score(data.get("expected_impact_score"), "expected_impact_score"),
            novelty_score=_score(data.get("novelty_score"), "novelty_score"),
            status=_string(data.get("status") or "captured", "status"),
            related_features=_string_tuple(data.get("related_features"), "related_features"),
            needs_validation=needs_validation,
            validation_plan=_string(data.get("validation_plan"), "validation_plan"),
            implemented_at=_string(data.get("implemented_at"), "implemented_at") or None,
            implementation_result=_string(data.get("implementation_result"), "implementation_result"),
            outcome=_string(data.get("outcome"), "outcome"),
            related_content_ids=_string_tuple(data.get("related_content_ids"), "related_content_ids"),
            duplicate_candidate_ids=_string_tuple(data.get("duplicate_candidate_ids"), "duplicate_candidate_ids"),
            canonical_id=_string(data.get("canonical_id"), "canonical_id") or None,
            last_updated_at=_string(data.get("last_updated_at") or created_at, "last_updated_at"),
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Idea":
        return cls.from_mapping(data)


def normalized_title(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().casefold())