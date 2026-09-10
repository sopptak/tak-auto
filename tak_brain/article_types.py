"""RAW 제목과 본문을 근거로 글 유형을 분류합니다."""

from __future__ import annotations

from dataclasses import dataclass
import re

from .models import RawContent


ARTICLE_TYPES = (
    "experience",
    "finance",
    "workplace",
    "ai_business",
    "book_philosophy",
    "general",
)


@dataclass(frozen=True)
class ArticleClassification:
    article_type: str
    score: int
    evidence: tuple[str, ...]


class ArticleTypeClassifier:
    """제목과 본문 양쪽의 근거가 있는 경우에만 전문 유형을 선택합니다."""

    _RULES = {
        "finance": ("대출", "재무제표", "은행", "영업이익", "당기순이익", "이익률"),
        "workplace": ("직장", "상사", "동료", "직장생활", "신뢰", "인정", "무시", "거절"),
        "ai_business": ("AI", "수익", "돈", "만원", "번", "사업", "HARU"),
        "book_philosophy": ("고전", "장자", "손자병법", "책", "독서", "핵심 메시지", "비교", "행복", "이기는", "싸우"),
        "experience": ("앱", "직접", "만들기 시작", "경험", "테스트", "만들었다"),
    }

    def classify(self, raw: RawContent) -> ArticleClassification:
        title = raw.title.lower()
        body = raw.body.lower()
        scores: dict[str, int] = {}
        evidence: dict[str, list[str]] = {}
        for article_type, terms in self._RULES.items():
            title_hits = [term for term in terms if term.lower() in title]
            body_hits = [term for term in terms if term.lower() in body]
            if title_hits and body_hits:
                scores[article_type] = len(set(title_hits + body_hits)) + 1
                evidence[article_type] = tuple(sorted(set(title_hits + body_hits)))

        if not scores:
            return ArticleClassification("general", 0, ())
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        winner, winner_score = ranked[0]
        runner_score = ranked[1][1] if len(ranked) > 1 else 0
        if winner_score < 2 or winner_score == runner_score:
            return ArticleClassification("general", winner_score, ())
        return ArticleClassification(winner, winner_score, tuple(evidence[winner]))