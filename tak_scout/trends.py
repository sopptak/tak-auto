"""Cross-source trend signals for TAK SCOUT.

This module measures recurrence inside the feeds TAK SCOUT actually collected.
It does NOT claim to measure public search volume, social engagement, or overall
internet popularity. Those require dedicated trend-provider observations.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import re
from typing import Iterable

from .models import ScoutCandidate

_TOKEN_RE = re.compile(r"[가-힣A-Za-z0-9]{2,}")
_STOPWORDS = frozenset({
    "그리고", "그러나", "때문", "대한", "통해", "관련", "오늘", "이번",
    "지난", "이후", "에서", "으로", "하는", "했다", "한다", "있는",
    "있다", "없다", "the", "and", "for", "with", "from", "that",
    "this", "are", "was", "will", "have", "has", "its", "you",
})


@dataclass(frozen=True)
class TrendSignal:
    keyword: str
    candidate_count: int
    source_count: int
    candidate_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "keyword": self.keyword,
            "candidate_count": self.candidate_count,
            "source_count": self.source_count,
            "candidate_ids": list(self.candidate_ids),
            "measurement": "collected_feed_recurrence",
        }


def extract_keywords(candidate: ScoutCandidate) -> tuple[str, ...]:
    """Extract simple title/summary tokens; no unsupported semantic inference."""
    text = f"{candidate.title} {candidate.summary}".lower()
    return tuple(dict.fromkeys(
        token for token in _TOKEN_RE.findall(text)
        if token not in _STOPWORDS and not token.isdigit()
    ))


def aggregate_trends(candidates: Iterable[ScoutCandidate]) -> list[TrendSignal]:
    """Rank terms by how many distinct collected items and sources mention them."""
    mentions: dict[str, list[ScoutCandidate]] = defaultdict(list)
    for candidate in candidates:
        for keyword in extract_keywords(candidate):
            mentions[keyword].append(candidate)

    signals = []
    for keyword, items in mentions.items():
        unique_items = {item.scout_id: item for item in items}
        unique_sources = {item.source_name for item in unique_items.values() if item.source_name}
        if len(unique_items) < 2:
            continue
        signals.append(TrendSignal(
            keyword=keyword,
            candidate_count=len(unique_items),
            source_count=len(unique_sources),
            candidate_ids=tuple(sorted(unique_items)),
        ))
    return sorted(
        signals,
        key=lambda signal: (
            signal.source_count,
            signal.candidate_count,
            signal.keyword,
        ),
        reverse=True,
    )


def trend_coverage_label(signals: Iterable[TrendSignal]) -> str:
    """Describe only the observed scope, never general-population popularity."""
    count = len(tuple(signals))
    return f"수집 피드 내 반복 키워드 {count}개 (검색량·SNS 인기 측정 아님)"
