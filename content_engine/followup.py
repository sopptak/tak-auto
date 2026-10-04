"""후속 콘텐츠 후보 생성(성과 -> 후속 콘텐츠 연결, 재활용).

파이프라인의 끊긴 고리를 잇는다:
    승인된 KNOWLEDGE + 발행 이력 + 성과 스냅샷 -> 후속/재활용 후보(candidate)

경계(6-35 Insight 원칙과 동일):
    - 모든 입력은 읽기만 한다. Performance/발행 이력/KNOWLEDGE/MEDIA를 수정하지 않는다.
    - 후보는 별도 저장소에만 append하며 status는 항상 candidate로 시작한다 -
      채택/거절은 사람이 한다. 이 모듈은 콘텐츠를 생성하거나 발행하지 않는다.
    - 후보의 근거(발행 이력/성과 수치)를 evidence에 그대로 남긴다.

후보 종류:
    repurpose - 이미 발행된 KNOWLEDGE가 아직 없는 채널(blog/shorts/threads)로 재활용.
    amplify   - 성과가 중앙값을 넘는 콘텐츠의 같은 소재를 다른 채널/각도로 확장.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import statistics
import tempfile
from typing import Any
from urllib.parse import urlparse

from blog_importer.models import utc_now
from content_engine.performance.models import PerformanceRecord
from tak_brain.models import KnowledgeRecord

PLATFORMS = ("blog", "shorts", "threads")

KIND_REPURPOSE = "repurpose"
KIND_AMPLIFY = "amplify"

STATUS_CANDIDATE = "candidate"
STATUS_ACCEPTED = "accepted"
STATUS_REJECTED = "rejected"
STATUSES = (STATUS_CANDIDATE, STATUS_ACCEPTED, STATUS_REJECTED)

INTENT_HOW_TO = "how_to"
INTENT_COMPARISON = "comparison"
INTENT_PROBLEM = "problem_solving"
INTENT_INFO = "informational"
INTENT_EXPERIENCE = "experience"

# 순서가 우선순위다(앞에서 먼저 매칭된 의도를 쓴다).
_INTENT_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (INTENT_COMPARISON, ("비교", " vs ", "차이", "어떤 게", "뭐가 좋")),
    (INTENT_HOW_TO, ("방법", "하는 법", "하는법", "어떻게", "가이드", "단계", "만들기", "시작하")),
    (INTENT_PROBLEM, ("문제", "실수", "해결", "왜 ", "오류", "위험", "주의", "손해", "부담")),
    (INTENT_INFO, ("이란", "뜻", "기준", "정리", "지표", "전망", "발표", "증가", "감소", "금리", "대출")),
)

# 채널별로 검색 유입에 의미가 큰 정도(blog가 가장 크다).
_PLATFORM_BASE_PRIORITY = {"blog": 60, "shorts": 50, "threads": 40}
_HEADLINE_METRICS = ("views", "likes", "replies", "reposts", "quotes", "shares")


class FollowUpError(ValueError):
    """후속 후보 저장소가 예상한 구조가 아닐 때 발생한다."""


def classify_search_intent(title: str, text: str = "") -> str:
    """제목/본문 키워드로 검색 의도를 결정적으로 분류한다(LLM/네트워크 없음)."""
    haystack = f"{title} {text}".lower()
    for intent, keywords in _INTENT_KEYWORDS:
        if any(keyword in haystack for keyword in keywords):
            return intent
    return INTENT_EXPERIENCE


@dataclass(frozen=True)
class FollowUpCandidate:
    candidate_id: str
    knowledge_id: str
    title: str
    kind: str
    target_platform: str
    search_intent: str
    priority: int
    reason: str
    evidence: dict[str, Any] = field(default_factory=dict)
    status: str = STATUS_CANDIDATE
    created_at: str = ""

    def __post_init__(self) -> None:
        if self.kind not in (KIND_REPURPOSE, KIND_AMPLIFY):
            raise FollowUpError(f"알 수 없는 kind: {self.kind!r}")
        if self.target_platform not in PLATFORMS:
            raise FollowUpError(f"알 수 없는 target_platform: {self.target_platform!r}")
        if self.status not in STATUSES:
            raise FollowUpError(f"알 수 없는 status: {self.status!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "knowledge_id": self.knowledge_id,
            "title": self.title,
            "kind": self.kind,
            "target_platform": self.target_platform,
            "search_intent": self.search_intent,
            "priority": self.priority,
            "reason": self.reason,
            "evidence": self.evidence,
            "status": self.status,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FollowUpCandidate":
        try:
            return cls(
                candidate_id=str(data["candidate_id"]),
                knowledge_id=str(data["knowledge_id"]),
                title=str(data.get("title", "")),
                kind=str(data["kind"]),
                target_platform=str(data["target_platform"]),
                search_intent=str(data.get("search_intent", INTENT_EXPERIENCE)),
                priority=int(data.get("priority", 0)),
                reason=str(data.get("reason", "")),
                evidence=dict(data.get("evidence") or {}),
                status=str(data.get("status", STATUS_CANDIDATE)),
                created_at=str(data.get("created_at", "")),
            )
        except KeyError as error:
            raise FollowUpError(f"후속 후보에 필수 필드가 없습니다: {error}") from error


def compute_candidate_id(knowledge_id: str, kind: str, target_platform: str) -> str:
    raw = f"{knowledge_id}|{kind}|{target_platform}"
    return "followup-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _is_blog_source(source_url: str) -> bool:
    host = urlparse(source_url or "").netloc.lower()
    return host.endswith("blog.naver.com") or host.endswith("tistory.com")


def _headline_value(record: PerformanceRecord) -> int:
    metrics = record.metrics or {}
    return sum(int(metrics.get(name, 0) or 0) for name in _HEADLINE_METRICS)


def _covered_platforms(
    knowledge: KnowledgeRecord,
    publish_logs: Iterable[Mapping[str, Any]],
    archive_records: Iterable[Mapping[str, Any]],
) -> tuple[set[str], set[str]]:
    """(발행/초안으로 이미 다룬 채널, 실제 발행된 채널)을 돌려준다."""
    published: set[str] = set()
    covered: set[str] = set()
    if _is_blog_source(knowledge.source_url):
        published.add("blog")
        covered.add("blog")
    for entry in publish_logs:
        if entry.get("knowledge_id") == knowledge.id and entry.get("platform") in PLATFORMS:
            published.add(str(entry["platform"]))
            covered.add(str(entry["platform"]))
    for entry in archive_records:
        if entry.get("knowledge_id") == knowledge.id and entry.get("platform") in PLATFORMS:
            covered.add(str(entry["platform"]))
    return covered, published


def build_followup_candidates(
    knowledge_records: Sequence[KnowledgeRecord],
    publish_logs: Sequence[Mapping[str, Any]] = (),
    archive_records: Sequence[Mapping[str, Any]] = (),
    latest_performance: Mapping[str, PerformanceRecord] | None = None,
    now: str | None = None,
) -> list[FollowUpCandidate]:
    """승인된 KNOWLEDGE만 대상으로 후속/재활용 후보를 우선순위 순으로 만든다."""
    created_at = now or utc_now()
    approved = [record for record in knowledge_records if record.knowledge_review_status == "approved"]
    performance = dict(latest_performance or {})

    per_knowledge: dict[str, int] = {}
    for record in performance.values():
        per_knowledge[record.knowledge_id] = per_knowledge.get(record.knowledge_id, 0) + _headline_value(record)
    positive = [value for value in per_knowledge.values() if value > 0]
    median = statistics.median(positive) if positive else 0

    candidates: list[FollowUpCandidate] = []
    for knowledge in approved:
        covered, published = _covered_platforms(knowledge, publish_logs, archive_records)
        if not published:
            # 한 번도 발행되지 않은 소재는 후속이 아니라 일반 발행 대기열의 몫이다.
            continue
        intent = classify_search_intent(knowledge.title, getattr(knowledge, "problem", "") or "")
        score = per_knowledge.get(knowledge.id, 0)
        amplified = score > 0 and score >= median
        for platform in PLATFORMS:
            if platform in covered:
                continue
            kind = KIND_AMPLIFY if amplified else KIND_REPURPOSE
            priority = _PLATFORM_BASE_PRIORITY[platform]
            if platform == "blog" and intent in (INTENT_HOW_TO, INTENT_PROBLEM, INTENT_COMPARISON, INTENT_INFO):
                priority += 10  # 검색 의도가 분명한 주제는 블로그 검색 유입에 유리하다.
            if amplified:
                priority += 20
            evidence: dict[str, Any] = {
                "published_platforms": sorted(published),
                "covered_platforms": sorted(covered),
                "headline_total": score,
                "median_total": median,
            }
            reason = (
                f"{'/'.join(sorted(published))}에 발행된 소재이고 {platform} 변환본이 아직 없음"
                + (f"; 성과 합계 {score}이(가) 중앙값 {median} 이상" if amplified else "")
            )
            candidates.append(
                FollowUpCandidate(
                    candidate_id=compute_candidate_id(knowledge.id, kind, platform),
                    knowledge_id=knowledge.id,
                    title=knowledge.title,
                    kind=kind,
                    target_platform=platform,
                    search_intent=intent,
                    priority=priority,
                    reason=reason,
                    evidence=evidence,
                    created_at=created_at,
                )
            )
    return sorted(candidates, key=lambda item: (-item.priority, item.knowledge_id, item.target_platform))


def load_candidates(path: Path | str) -> list[FollowUpCandidate]:
    target = Path(path)
    if not target.exists():
        return []
    data = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise FollowUpError("후속 후보 파일은 객체 목록이어야 합니다.")
    return [FollowUpCandidate.from_dict(item) for item in data]


def _save(records: list[FollowUpCandidate], path: Path | str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps([record.to_dict() for record in records], ensure_ascii=False, indent=2)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, delete=False, suffix=".tmp") as handle:
        handle.write(payload + "\n")
        temp_path = Path(handle.name)
    temp_path.replace(target)


def append_candidates(path: Path | str, candidates: Sequence[FollowUpCandidate]) -> int:
    """새 후보만 append한다. 이미 있는 candidate_id는 상태(accepted/rejected)를 보존하며 건너뛴다."""
    existing = load_candidates(path)
    seen = {record.candidate_id for record in existing}
    added = [candidate for candidate in candidates if candidate.candidate_id not in seen]
    if added:
        _save(existing + added, path)
    return len(added)


def set_candidate_status(path: Path | str, candidate_id: str, new_status: str) -> FollowUpCandidate:
    if new_status not in STATUSES:
        raise FollowUpError(f"알 수 없는 status: {new_status!r}")
    records = load_candidates(path)
    for index, record in enumerate(records):
        if record.candidate_id == candidate_id:
            updated = FollowUpCandidate(**{**record.__dict__, "status": new_status})
            records[index] = updated
            _save(records, path)
            return updated
    raise FollowUpError(f"후보를 찾을 수 없습니다: {candidate_id}")
