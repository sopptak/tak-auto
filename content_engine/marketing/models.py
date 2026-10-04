"""MarketingBrief: 콘텐츠를 만들기 전에 '사람의 행동을 유도하는 구조'를 데이터로 고정한다.

5개 관점(psychology/storytelling/sales/design/distribution)은 각각 이름 있는 요소의 문자열
필드다. 빈 문자열은 "아직 모름"이며 점수에서 0점이 아니라 결측으로 처리된다. LLM 없이도
저장/검증/점수화할 수 있고, 값은 사람이나 (나중에) LLM이 채운다. 브리프는 항상 draft로 시작하고
사람이 approved로 바꿔야 콘텐츠 생성 프롬프트에 쓸 수 있다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, fields
import hashlib
from typing import Any, ClassVar

PLATFORMS = ("blog", "threads", "shorts", "youtube")

STATUS_DRAFT = "draft"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
BRIEF_STATUSES = (STATUS_DRAFT, STATUS_APPROVED, STATUS_REJECTED)


class MarketingError(ValueError):
    """마케팅 브리프/저장소 구조 또는 사용 규칙 위반."""


class _Dimension:
    NAME: ClassVar[str] = ""

    @classmethod
    def element_names(cls) -> tuple[str, ...]:
        return tuple(f.name for f in fields(cls))  # type: ignore[arg-type]

    def filled(self) -> dict[str, str]:
        return {name: getattr(self, name).strip() for name in self.element_names() if getattr(self, name).strip()}

    def missing(self) -> tuple[str, ...]:
        return tuple(name for name in self.element_names() if not getattr(self, name).strip())

    def to_dict(self) -> dict[str, str]:
        return {name: getattr(self, name) for name in self.element_names()}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None):
        data = data or {}
        unknown = set(data) - set(cls.element_names())
        if unknown:
            raise MarketingError(f"{cls.NAME}에 알 수 없는 요소: {sorted(unknown)}")
        values = {}
        for key, value in data.items():
            if value is not None and not isinstance(value, str):
                raise MarketingError(f"{cls.NAME}.{key}는 문자열이어야 합니다.")
            values[key] = value or ""
        return cls(**values)


@dataclass(frozen=True)
class Psychology(_Dimension):
    NAME: ClassVar[str] = "psychology"
    attention: str = ""
    curiosity: str = ""
    pain: str = ""
    desire: str = ""
    trust: str = ""
    social_proof: str = ""
    loss_aversion: str = ""
    urgency: str = ""
    identification: str = ""


@dataclass(frozen=True)
class Storytelling(_Dimension):
    NAME: ClassVar[str] = "storytelling"
    hook: str = ""
    problem: str = ""
    tension: str = ""
    insight: str = ""
    transformation: str = ""
    conclusion: str = ""
    call_to_action: str = ""


@dataclass(frozen=True)
class Sales(_Dimension):
    NAME: ClassVar[str] = "sales"
    target_customer: str = ""
    customer_problem: str = ""
    value_proposition: str = ""
    benefit: str = ""
    objection: str = ""
    proof: str = ""
    offer: str = ""
    call_to_action: str = ""
    conversion_goal: str = ""


@dataclass(frozen=True)
class Design(_Dimension):
    NAME: ClassVar[str] = "design"
    visual_hook: str = ""
    readability: str = ""
    information_hierarchy: str = ""
    thumbnail_concept: str = ""
    visual_clarity: str = ""
    brand_consistency: str = ""


@dataclass(frozen=True)
class Distribution(_Dimension):
    NAME: ClassVar[str] = "distribution"
    target_platform: str = ""
    search_intent: str = ""
    discovery_keyword: str = ""
    audience: str = ""
    distribution_angle: str = ""
    repurpose_targets: str = ""  # 쉼표로 구분한 플랫폼 목록


DIMENSIONS: dict[str, type[_Dimension]] = {
    "psychology": Psychology, "storytelling": Storytelling, "sales": Sales,
    "design": Design, "distribution": Distribution,
}


@dataclass(frozen=True)
class EvidenceItem:
    """리서치/시장 데이터 출처. 사실로 확정된 것이 아니라 '검증 대상 근거'다."""

    kind: str  # research | market_demand | knowledge | manual
    title: str = ""
    url: str = ""
    snippet: str = ""
    provider: str = ""
    aspect: str = ""  # research_tasks의 aspect

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "title": self.title, "url": self.url, "snippet": self.snippet,
                "provider": self.provider, "aspect": self.aspect}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EvidenceItem":
        if not data.get("kind"):
            raise MarketingError("evidence.kind는 필수입니다.")
        return cls(**{key: str(data.get(key) or "") for key in ("kind", "title", "url", "snippet", "provider", "aspect")})


def compute_brief_id(topic: str, platform: str, idea_id: str = "") -> str:
    raw = f"{idea_id}|{topic.strip().lower()}|{platform}"
    return "brief-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class MarketingBrief:
    brief_id: str
    topic: str
    target_audience: str = ""
    customer_problem: str = ""
    desired_action: str = ""
    psychology: Psychology = field(default_factory=Psychology)
    storytelling: Storytelling = field(default_factory=Storytelling)
    sales: Sales = field(default_factory=Sales)
    design: Design = field(default_factory=Design)
    distribution: Distribution = field(default_factory=Distribution)
    evidence: tuple[EvidenceItem, ...] = ()
    confidence: float = 0.0  # 0~1, 근거의 양/출처 다양성에서 계산(점수 confidence와 별개)
    platform: str = ""  # ""이면 플랫폼 공통 브리프
    idea_id: str = ""
    knowledge_ids: tuple[str, ...] = ()
    content_ids: tuple[str, ...] = ()  # 이 브리프로 만든 콘텐츠(성과 귀속용)
    status: str = STATUS_DRAFT
    requires_human_review: bool = True
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.brief_id.strip() or not self.topic.strip():
            raise MarketingError("brief_id와 topic은 필수입니다.")
        if self.platform and self.platform not in PLATFORMS:
            raise MarketingError(f"알 수 없는 platform: {self.platform!r} (선택: {PLATFORMS})")
        if self.status not in BRIEF_STATUSES:
            raise MarketingError(f"알 수 없는 status: {self.status!r}")
        if not 0.0 <= self.confidence <= 1.0:
            raise MarketingError("confidence는 0~1 범위여야 합니다.")
        if not self.requires_human_review and self.status != STATUS_APPROVED:
            raise MarketingError("requires_human_review=False는 approved 브리프에서만 허용됩니다.")
        for name, cls in DIMENSIONS.items():
            if not isinstance(getattr(self, name), cls):
                raise MarketingError(f"{name}은(는) {cls.__name__}여야 합니다.")
        platforms = [p.strip() for p in self.distribution.repurpose_targets.split(",") if p.strip()]
        bad = [p for p in platforms if p not in PLATFORMS]
        if bad:
            raise MarketingError(f"repurpose_targets에 알 수 없는 플랫폼: {bad}")

    def dimension(self, name: str) -> _Dimension:
        return getattr(self, name)

    def missing_fields(self) -> list[str]:
        """사람이/LLM이 채워야 할 요소(``dimension.element``)."""
        return [f"{name}.{element}" for name in DIMENSIONS for element in self.dimension(name).missing()]

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "brief_id": self.brief_id, "topic": self.topic, "target_audience": self.target_audience,
            "customer_problem": self.customer_problem, "desired_action": self.desired_action,
            "evidence": [item.to_dict() for item in self.evidence], "confidence": self.confidence,
            "platform": self.platform, "idea_id": self.idea_id, "knowledge_ids": list(self.knowledge_ids),
            "content_ids": list(self.content_ids), "status": self.status,
            "requires_human_review": self.requires_human_review, "created_at": self.created_at,
        }
        for name in DIMENSIONS:
            data[name] = self.dimension(name).to_dict()
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MarketingBrief":
        try:
            dims = {name: kind.from_dict(data.get(name)) for name, kind in DIMENSIONS.items()}
            return cls(
                brief_id=str(data["brief_id"]), topic=str(data["topic"]),
                target_audience=str(data.get("target_audience") or ""),
                customer_problem=str(data.get("customer_problem") or ""),
                desired_action=str(data.get("desired_action") or ""),
                evidence=tuple(EvidenceItem.from_dict(item) for item in data.get("evidence") or ()),
                confidence=float(data.get("confidence") or 0.0), platform=str(data.get("platform") or ""),
                idea_id=str(data.get("idea_id") or ""), knowledge_ids=tuple(data.get("knowledge_ids") or ()),
                content_ids=tuple(data.get("content_ids") or ()), status=str(data.get("status") or STATUS_DRAFT),
                requires_human_review=bool(data.get("requires_human_review", True)),
                created_at=str(data.get("created_at") or ""), **dims,
            )
        except KeyError as error:
            raise MarketingError(f"필수 필드가 없습니다: {error}") from error
        except (TypeError, ValueError, AttributeError) as error:
            if isinstance(error, MarketingError):
                raise
            raise MarketingError(f"브리프 구조 오류: {error}") from error
