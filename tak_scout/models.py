"""TAK SCOUT가 수집한 외부 소재 후보의 최소 데이터 모델.

인터넷 원문 전체를 복사해서 저장하지 않는다. 제목, 짧은 요약, 원문 URL, 발행일,
출처, category 중심으로만 후보를 표현한다.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any


# category별로 인터뷰 질문에 쓸 자연스러운 주어. 등록되지 않은 category는 기본값을 쓴다.
_CATEGORY_SUBJECT_LABELS = {
    "finance": "이 경제 이슈",
    "금융": "이 금융 이슈",
    "tech": "이 기술 이슈",
}
_DEFAULT_SUBJECT_LABEL = "이 이슈"


def compute_scout_id(title: str, source_url: str) -> str:
    """제목과 원문 URL로 deterministic한 scout_id를 만든다.

    같은 입력이면 언제 실행해도 같은 scout_id가 나오므로, 이 값을 기준으로 중복 소재를
    판단할 수 있다.
    """
    normalized = f"{title.strip().lower()}|{source_url.strip().lower()}"
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]
    return f"scout-{digest}"


@dataclass(frozen=True)
class ScoutCandidate:
    """TAK SCOUT가 만든 소재 후보 1건."""

    scout_id: str
    title: str
    summary: str
    source_url: str
    published_at: str
    source_name: str
    category: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "scout_id": self.scout_id,
            "title": self.title,
            "summary": self.summary,
            "source_url": self.source_url,
            "published_at": self.published_at,
            "source_name": self.source_name,
            "category": self.category,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScoutCandidate":
        scout_id = str(data.get("scout_id") or "")
        title = str(data.get("title") or "")
        source_url = str(data.get("source_url") or "")
        if not scout_id or not title or not source_url:
            raise ValueError("scout_id, title, source_url은 필수입니다.")
        return cls(
            scout_id=scout_id,
            title=title,
            summary=str(data.get("summary") or ""),
            source_url=source_url,
            published_at=str(data.get("published_at") or ""),
            source_name=str(data.get("source_name") or ""),
            category=str(data.get("category") or "기타"),
        )


def subject_label(candidate: ScoutCandidate) -> str:
    """인터뷰 질문과 KNOWLEDGE 문장에 함께 쓰는, category 기반 자연스러운 주어."""
    return _CATEGORY_SUBJECT_LABELS.get(candidate.category, _DEFAULT_SUBJECT_LABEL)
