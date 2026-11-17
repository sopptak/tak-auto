"""General-purpose editorial relevance scoring for trend candidates.

This is deliberately separate from the legacy finance/auction-oriented SCOUT SCORE.
It ranks content candidates, not search demand or popularity.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re

from .models import ScoutCandidate

_ATTENTION = (
    "논란", "급변", "변화", "최초", "신기록", "확산", "충격", "위기", "논쟁",
    "출시", "공개", "발표", "금지", "허용", "인상", "인하", "급등", "급락",
    "controversy", "launch", "launched", "unveils", "announces", "record",
    "surge", "crash", "ban", "approved", "breakthrough", "warning",
)
_DISCUSSION = (
    "왜", "어떻게", "이유", "전망", "영향", "문제", "해결", "비교", "논쟁",
    "how", "why", "impact", "explained", "what it means", "versus", "vs",
)
_GENERIC = {"뉴스", "속보", "오늘", "이번", "관련", "기자", "사진", "영상", "단독"}


@dataclass(frozen=True)
class TrendCandidateScore:
    total: int
    breakdown: dict[str, int]
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {"score": self.total, "breakdown": dict(self.breakdown),
                "reasons": list(self.reasons),
                "measurement": "heuristic_editorial_relevance"}


def _age_hours(published_at: str, now: datetime) -> float | None:
    if not published_at:
        return None
    try:
        parsed = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0.0, (now - parsed).total_seconds() / 3600)


def score_trend_candidate(candidate: ScoutCandidate,
                          reference_time: datetime | None = None) -> TrendCandidateScore:
    now = reference_time or datetime.now(timezone.utc)
    text = f"{candidate.title} {candidate.summary}".lower()
    attention = tuple(term for term in _ATTENTION if term in text)
    discussion = tuple(term for term in _DISCUSSION if term in text)
    age = _age_hours(candidate.published_at, now)

    freshness = 0 if age is None else (30 if age <= 6 else 24 if age <= 24 else
                                       16 if age <= 72 else 8 if age <= 168 else 0)
    attention_score = min(25, len(attention) * 7)
    discussion_score = min(20, len(discussion) * 7)
    specificity = 10 if any(ch.isdigit() for ch in text) else 0
    specificity += 5 if any(len(token) >= 5 and token not in _GENERIC
                            for token in re.findall(r"[가-힣A-Za-z]{5,}", text)) else 0
    specificity = min(15, specificity)
    source_signal = 10 if candidate.source_name.strip() else 0

    breakdown = {
        "freshness": freshness,
        "attention_language": attention_score,
        "discussion_potential": discussion_score,
        "specificity": specificity,
        "source_metadata": source_signal,
    }
    reasons = []
    if age is not None:
        reasons.append(f"발행 후 약 {age:.0f}시간")
    if attention:
        reasons.append("주목 표현: " + ", ".join(attention[:3]))
    if discussion:
        reasons.append("설명·토론 요소: " + ", ".join(discussion[:3]))
    if specificity:
        reasons.append("숫자 또는 구체적 표현 포함")
    if not reasons:
        reasons.append("뚜렷한 편집 신호가 적어 제목과 원문 확인 필요")
    return TrendCandidateScore(sum(breakdown.values()), breakdown, tuple(reasons))


def rank_trend_candidates(candidates: list[ScoutCandidate],
                          reference_time: datetime | None = None
                          ) -> list[tuple[ScoutCandidate, TrendCandidateScore]]:
    scored = [(item, score_trend_candidate(item, reference_time)) for item in candidates]
    scored.sort(key=lambda pair: (-pair[1].total, pair[0].scout_id))
    return scored
