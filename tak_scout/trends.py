"""Keyword extraction and normalization for collected-feed trend signals.

Normalization is intentionally conservative: explicit aliases and token cleanup only.
It does not claim semantic equivalence or infer search demand.
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
# Only unambiguous spelling/abbreviation aliases. Extend with evidence and tests.
_ALIASES = {
    "a.i": "ai", "인공지능": "ai", "artificial intelligence": "ai",
    "chat gpt": "chatgpt", "챗 지피티": "chatgpt",
    "유튜브": "youtube", "youtube": "youtube",
    "틱톡": "tiktok", "tiktok": "tiktok",
    "스마트폰": "스마트폰",
}
_PHRASE_MIN_TOKENS = 2
_PHRASE_MAX_TOKENS = 3


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


def normalize_keyword(keyword: str) -> str:
    value = re.sub(r"\\s+", " ", keyword.strip().lower())
    value = _ALIASES.get(value, value)
    return value


def extract_keywords(candidate: ScoutCandidate) -> tuple[str, ...]:
    """Extract individual terms and 2-3 token phrases from title/summary."""
    text = f"{candidate.title} {candidate.summary}".lower()
    tokens = [token for token in _TOKEN_RE.findall(text)
              if token not in _STOPWORDS and not token.isdigit()]
    keywords = []
    for token in tokens:
        normalized = normalize_keyword(token)
        if normalized and normalized not in keywords:
            keywords.append(normalized)
    # Phrase candidates preserve useful context (e.g. 스마트 안경, 생성형 AI).
    for size in range(_PHRASE_MIN_TOKENS, _PHRASE_MAX_TOKENS + 1):
        for index in range(len(tokens) - size + 1):
            phrase = normalize_keyword(" ".join(tokens[index:index + size]))
            if phrase and phrase not in keywords:
                keywords.append(phrase)
    return tuple(keywords)


def aggregate_trends(candidates: Iterable[ScoutCandidate]) -> list[TrendSignal]:
    """Rank terms by distinct collected items and distinct source names."""
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
    return sorted(signals, key=lambda signal: (
        signal.source_count, signal.candidate_count, signal.keyword), reverse=True)


def trend_coverage_label(signals: Iterable[TrendSignal]) -> str:
    count = len(tuple(signals))
    return f"수집 피드 내 반복 키워드 {count}개 (검색량·SNS 인기 측정 아님)"
