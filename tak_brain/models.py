"""원본(RAW)과 분석(KNOWLEDGE)을 분리한 모델."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from blog_importer.models import BlogPost, utc_now


CATEGORIES = ("금융", "대출", "경매", "부동산", "인간관계", "심리", "자기계발", "독서", "건강", "가족", "골프", "기타")
KNOWLEDGE_TYPES = ("경험", "사례", "판단기준", "정보", "의견")
_PRIVACY_PATTERN = re.compile(r"주민등록번호|주민번호|개인정보|010[- ]?\d{3,4}[- ]?\d{4}|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
_FINANCIAL_PATTERN = re.compile(r"계좌(?:번호)?|카드번호|비공개 금융정보|고객(?:명|번호|정보)|특정 고객")
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
    extraction_method: str
    extraction_status: str

    @classmethod
    def from_post(cls, post: BlogPost) -> "RawContent":
        return cls(
            post.id,
            post.title,
            post.published_at,
            post.body,
            post.tags,
            post.source_url,
            post.source,
            post.collected_at,
            post.content_hash,
            post.extraction_method,
            post.extraction_status,
        )


@dataclass(frozen=True)
class KnowledgeRecord:
    id: str = ""
    source_raw_id: str = ""
    source_url: str = ""
    title: str = ""
    domain: str | None = None
    experience: str | None = None
    problem: str | None = None
    action: str | None = None
    decision: str | None = None
    result: str | None = None
    lesson: str | None = None
    reusable_principle: str | None = None
    evidence: tuple[str, ...] = ()
    derived_insight: str | None = None
    inference_method: str | None = None
    confidence: float | None = None
    created_at: str = ""
    knowledge_review_status: str = "pending"
    reviewed_at: str | None = None
    review_note: str | None = None
    category: str | None = None
    knowledge_type: str | None = None
    summary: str | None = None
    key_points: tuple[str, ...] = ()
    case: str | None = None
    judgment_rule: str | None = None
    opinion: str | None = None
    factual_information: str | None = None
    current_validity: str | None = None
    verification_required: bool = False
    privacy_risk: bool = False
    internal_information_risk: bool = False

    def to_dict(self) -> dict[str, Any]:
        result = {
            "id": self.id,
            "source_raw_id": self.source_raw_id,
            "source_url": self.source_url,
            "title": self.title,
            "domain": self.domain,
            "knowledge_type": self.knowledge_type,
            "experience": self.experience,
            "problem": self.problem,
            "action": self.action,
            "decision": self.decision,
            "result": self.result,
            "lesson": self.lesson,
            "reusable_principle": self.reusable_principle,
            "evidence": list(self.evidence),
            "derived_insight": self.derived_insight,
            "inference_method": self.inference_method,
            "confidence": self.confidence,
            "created_at": self.created_at,
            "knowledge_review_status": self.knowledge_review_status,
            "reviewed_at": self.reviewed_at,
            "review_note": self.review_note,
            "category": self.category,
            "key_points": list(self.key_points),
            "case": self.case,
            "judgment_rule": self.judgment_rule,
            "opinion": self.opinion,
            "factual_information": self.factual_information,
            "current_validity": self.current_validity,
            "verification_required": self.verification_required,
            "privacy_risk": self.privacy_risk,
            "internal_information_risk": self.internal_information_risk,
        }
        return result


@dataclass(frozen=True)
class BrainRecord:
    raw: RawContent
    metadata: dict[str, Any]
    knowledge: KnowledgeRecord | None = None


def build_metadata(post: BlogPost) -> dict[str, Any]:
    searchable = f"{post.title}\n{post.body}"
    privacy_risk = bool(_PRIVACY_PATTERN.search(searchable) or _FINANCIAL_PATTERN.search(searchable))
    internal_information_risk = bool(_INTERNAL_PATTERN.search(searchable))
    risk_flags = []
    if privacy_risk:
        risk_flags.append("privacy_or_financial")
    if internal_information_risk:
        risk_flags.append("internal_information")
    return {
        "content_hash": post.content_hash,
        "source": post.source,
        "collected_at": post.collected_at or utc_now(),
        "tags": list(post.tags),
        "extraction_method": post.extraction_method,
        "extraction_status": post.extraction_status,
        "privacy_risk": privacy_risk,
        "internal_information_risk": internal_information_risk,
        "risk_flag": bool(risk_flags),
        "risk_flags": risk_flags,
        "false_positive_possible": bool(risk_flags),
        "review_status": "pending",
        "verification_required": True,
    }