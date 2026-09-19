"""TAK SCOUT SCORE: 오늘 수집된 후보 중 "먼저 볼 만한 소재"를 정렬하기 위한
단순하고 설명 가능한(rule-based, deterministic) 점수 매기기 MVP.

LLM을 쓰지 않는다. 제목/요약/category/published_at 같은 이미 있는 필드만 보고,
미리 정한 키워드 목록과 발행 시각만으로 점수를 계산한다. 같은 입력이면 언제
실행해도 같은 점수가 나온다(추천 이유도 실제로 일치한 키워드만 근거로 삼는다 -
과장하지 않는다).

키워드는 한국어/영어를 함께 둔다: data/scout_sources.json에 등록된 실제 source
(BBC Business, Hacker News)가 전부 영문 RSS라서, 한국어 키워드만으로는 오늘
실제 수집되는 소재를 거의 구분하지 못한다(실제 데이터로 확인한 결과이기도
하다 - 6번 문서 참고). 키워드는 단어 경계(\\b)를 기준으로 매칭해 "ai"가
"said"에, "rate"가 "corporate"에 우연히 걸리는 것을 막는다.

키워드 목록을 별도 설정 파일로 뺄지 검토했다: data/scout_sources.json은 사람이
RSS 주소를 직접 관리하는 "운영 데이터"라 파일로 분리되어 있지만, 이 파일의
키워드 목록은 점수 계산 로직과 강하게 묶여 있고 개수도 많지 않다(dimension당
15~30개). 이 저장소의 다른 규칙 기반 로직들(예: content_engine/rewrite.py의
_FACT_RISK_TERMS, tak_brain/article_types.py의 _RULES)도 같은 이유로 전부
코드 상수로 두고 있어, 이번에도 같은 방식을 따른다. 나중에 키워드가 크게
늘어나거나 사람이 자주 바꿔야 하는 시점이 오면 그때 분리를 재검토한다.

점수 구성(총 100점):
    A. 콘텐츠 관심도            0~25
    B. 티몽 전문성과의 연관성    0~25 (금융/대출/경매/부동산 실무 경험)
    C. 의견을 만들기 좋은 정도  0~20
    D. 수익화 관련성            0~15 (경제/금융/부동산/AI 등)
    E. 최신성                   0~15
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import re

from .models import ScoutCandidate


# --- 키워드 목록 (한국어 + 영어, 사람이 이해할 수 있는 수준으로 최소화) ---------

# A. 콘텐츠 관심도: 주목도가 높은(경보성/변화성) 표현.
_INTEREST_KEYWORDS = (
    "경고", "우려", "논란", "위기", "역대", "최초", "충격", "붕괴",
    "폭등", "폭락", "급등", "급락", "반등", "사고", "참사",
    "warning", "warns", "concern", "concerns", "crisis", "controversy",
    "shock", "shocking", "crash", "crashes", "plunge", "surge", "soar",
    "record", "fatal", "collapse", "frightened",
)

# B. 티몽 전문성과의 연관성: 금융/대출/경매/부동산 실무 키워드
# (tak_brain.models.CATEGORIES의 "금융, 대출, 경매, 부동산"과 의도적으로 맞춘다).
_EXPERTISE_KEYWORDS = (
    "금융", "대출", "은행", "이자", "금리", "여신",
    "부동산", "아파트", "전세", "월세", "임대료", "집값",
    "경매", "공매", "자영업", "소상공인", "창업",
    "bank", "banking", "loan", "mortgage", "rate", "rates",
    "property", "housing", "rent", "rents", "tenant", "tenants", "landlord",
    "auction", "foreclosure", "business",
)

# C. 의견을 만들기 좋은 정도: 정책/발표/논쟁성 문구(찬반이 갈리기 쉬운 표현).
_OPINION_KEYWORDS = (
    "발표", "정책", "법안", "규제", "경고", "논란", "촉구",
    "결정", "우려", "인상", "인하", "요구", "반발", "찬반",
    "announces", "announcement", "policy", "bill", "regulation",
    "regulations", "warns", "warning", "controversy", "urges", "urge",
    "calls for", "decision", "concern", "raise", "cut", "demand",
    "backlash", "debate", "downplays",
)

# D. 수익화 관련성: 경제/금융/부동산/AI 등 채널 방향과 맞닿은 넓은 범위.
_MONETIZATION_KEYWORDS = (
    "경제", "금융", "부동산", "금리", "물가", "인플레이션",
    "재테크", "투자", "자산", "증시", "주식",
    "economy", "economic", "finance", "financial", "real estate",
    "inflation", "investment", "invest", "asset", "assets",
    "stock market", "stocks", "tariff", "tariffs",
    "ai", "artificial intelligence", "chatgpt", "anthropic", "claude", "클로드",
)

# category 필드가 이미 있으면 그대로 재사용한다(새 필드를 만들지 않는다).
# 카테고리 하나만으로 후한 점수를 주면(예: BBC Business 전체가 "finance") 실제
# 내용과 무관한 기사도 다 높게 나오므로, 보조 신호로만 약하게 반영한다.
_FINANCE_LIKE_CATEGORIES = frozenset({"finance", "금융", "대출", "경매", "부동산"})

_RECENCY_TIERS: tuple[tuple[float, int], ...] = (
    (6, 15),
    (24, 12),
    (48, 8),
    (72, 4),
)


@dataclass(frozen=True)
class ScoutScore:
    """소재 1건의 SCOUT SCORE 계산 결과."""

    total: int
    breakdown: dict[str, int]
    matched_keywords: dict[str, tuple[str, ...]] = field(default_factory=dict)
    recommendation_reason: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "score": self.total,
            "score_breakdown": dict(self.breakdown),
            "recommendation_reason": self.recommendation_reason,
        }


def _find_keyword_hits(text: str, keywords: tuple[str, ...]) -> tuple[str, ...]:
    """단어 경계(\\b) 기준으로 키워드를 찾는다. 대소문자 무시.

    단순 substring 검사(`in`)는 "ai"가 "said"에, "rate"가 "corporate"에 우연히
    걸리는 문제가 있어(영문 키워드가 많아 실제로 자주 발생) \\b를 사용한다.
    """
    hits = []
    for keyword in keywords:
        pattern = r"\b" + re.escape(keyword) + r"\b"
        if re.search(pattern, text, re.IGNORECASE | re.UNICODE):
            hits.append(keyword)
    return tuple(hits)


def _has_number(text: str) -> bool:
    return any(character.isdigit() for character in text)


def _parse_datetime(published_at: str) -> datetime | None:
    if not published_at:
        return None
    try:
        parsed = datetime.fromisoformat(published_at)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _score_content_interest(text: str) -> tuple[int, tuple[str, ...]]:
    hits = _find_keyword_hits(text, _INTEREST_KEYWORDS)
    score = 5 + 5 * min(len(hits), 4)
    return min(score, 25), hits


def _score_expertise_relevance(candidate: ScoutCandidate, text: str) -> tuple[int, tuple[str, ...]]:
    hits = _find_keyword_hits(text, _EXPERTISE_KEYWORDS)
    score = 0
    if candidate.category in _FINANCE_LIKE_CATEGORIES:
        score += 3
    score += 5 * min(len(hits), 4)
    return min(score, 25), hits


def _score_opinion_potential(text: str) -> tuple[int, tuple[str, ...]]:
    hits = _find_keyword_hits(text, _OPINION_KEYWORDS)
    score = 4 + 4 * min(len(hits), 4)
    return min(score, 20), hits


def _score_monetization_relevance(candidate: ScoutCandidate, text: str) -> tuple[int, tuple[str, ...]]:
    hits = _find_keyword_hits(text, _MONETIZATION_KEYWORDS)
    score = 0
    if candidate.category in _FINANCE_LIKE_CATEGORIES:
        score += 2
    score += 4 * min(len(hits), 3)
    return min(score, 15), hits


def _score_recency(candidate: ScoutCandidate, reference_time: datetime) -> tuple[int, str]:
    parsed = _parse_datetime(candidate.published_at)
    if parsed is None:
        return 0, "발행 시각을 알 수 없음"
    hours_ago = (reference_time - parsed).total_seconds() / 3600
    if hours_ago < 0:
        hours_ago = 0
    for threshold, score in _RECENCY_TIERS:
        if hours_ago <= threshold:
            return score, f"발행 후 약 {hours_ago:.0f}시간 경과"
    return 0, f"발행 후 약 {hours_ago:.0f}시간 경과(오래됨)"


def _build_recommendation_reason(
    interest_hits: tuple[str, ...],
    expertise_hits: tuple[str, ...],
    opinion_hits: tuple[str, ...],
    monetization_hits: tuple[str, ...],
    recency_score: int,
    recency_note: str,
) -> str:
    """실제로 일치한 키워드/신호만 근거로 삼는다. 근거가 없으면 과장하지 않고
    그대로 "뚜렷한 신호가 없다"고 말한다."""
    sentences: list[str] = []

    expertise_and_monetization = tuple(
        dict.fromkeys((*expertise_hits, *monetization_hits))
    )  # 순서 유지 중복 제거
    if expertise_and_monetization:
        sentences.append(
            "금융/대출/경매/부동산/AI 등 관련 키워드(" + ", ".join(expertise_and_monetization) + ")가 포함되어 있음"
        )

    if opinion_hits:
        sentences.append("의견을 유도하는 표현(" + ", ".join(opinion_hits) + ")이 있어 관점을 붙이기 좋음")

    if interest_hits and not opinion_hits:
        sentences.append("주목도가 높은 표현(" + ", ".join(interest_hits) + ")이 포함됨")

    if recency_score >= 12:
        sentences.append(recency_note + "로 최신 소재임")

    if not sentences:
        return "금융/AI 관련 키워드나 의견을 유도하는 표현이 뚜렷하게 발견되지 않았습니다."

    return ". ".join(sentences) + "."


def score_candidate(candidate: ScoutCandidate, reference_time: datetime | None = None) -> ScoutScore:
    """소재 1건의 SCOUT SCORE를 계산한다. 순수 함수: 같은 입력 -> 같은 결과."""
    reference_time = reference_time or datetime.now(timezone.utc)
    text = f"{candidate.title} {candidate.summary}"

    interest_score, interest_hits = _score_content_interest(text)
    if _has_number(text):
        interest_score = min(25, interest_score + 3)

    expertise_score, expertise_hits = _score_expertise_relevance(candidate, text)
    opinion_score, opinion_hits = _score_opinion_potential(text)
    monetization_score, monetization_hits = _score_monetization_relevance(candidate, text)
    recency_score, recency_note = _score_recency(candidate, reference_time)

    breakdown = {
        "content_interest": interest_score,
        "expertise_relevance": expertise_score,
        "opinion_potential": opinion_score,
        "monetization_relevance": monetization_score,
        "recency": recency_score,
    }
    total = sum(breakdown.values())

    reason = _build_recommendation_reason(
        interest_hits, expertise_hits, opinion_hits, monetization_hits, recency_score, recency_note
    )

    matched_keywords = {
        "content_interest": interest_hits,
        "expertise_relevance": expertise_hits,
        "opinion_potential": opinion_hits,
        "monetization_relevance": monetization_hits,
    }

    return ScoutScore(total=total, breakdown=breakdown, matched_keywords=matched_keywords, recommendation_reason=reason)


def _sort_key(candidate: ScoutCandidate, score: ScoutScore) -> tuple[int, float, str]:
    """점수 내림차순, 동점이면 최신 발행 우선, 그래도 같으면 scout_id 오름차순.

    실행할 때마다 순서가 바뀌지 않도록 모든 동점 상황에 결정적인 기준을 둔다.
    """
    parsed = _parse_datetime(candidate.published_at)
    recency_key = parsed.timestamp() if parsed is not None else float("-inf")
    return (-score.total, -recency_key, candidate.scout_id)


def rank_candidates(
    candidates: list[ScoutCandidate], reference_time: datetime | None = None
) -> list[tuple[ScoutCandidate, ScoutScore]]:
    """모든 후보를 점수화하고 점수 내림차순으로 정렬해 (후보, 점수) 목록을 반환한다."""
    reference_time = reference_time or datetime.now(timezone.utc)
    scored = [(candidate, score_candidate(candidate, reference_time)) for candidate in candidates]
    scored.sort(key=lambda pair: _sort_key(pair[0], pair[1]))
    return scored


def top_candidates(
    candidates: list[ScoutCandidate], n: int = 10, reference_time: datetime | None = None
) -> list[tuple[ScoutCandidate, ScoutScore]]:
    """점수 상위 N건만 반환한다(기본 10건)."""
    return rank_candidates(candidates, reference_time)[:n]
