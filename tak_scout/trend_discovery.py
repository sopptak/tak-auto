"""Perplexity-first discovery of broad, current Korean content trends.

The returned order is an editorial shortlist from cited web research, not measured
search volume, social reach, or a statistically verified popularity ranking.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import re
from typing import Any
from zoneinfo import ZoneInfo

from .perplexity_research import PerplexityResearchProvider, ResearchResult

KST = ZoneInfo("Asia/Seoul")


@dataclass(frozen=True)
class TrendItem:
    rank: int
    keyword: str
    category: str
    summary: str
    why_now: str
    audience_question: str
    content_angle: str
    blog_title: str
    shorts_hook: str
    key_points: tuple[str, ...]
    source_urls: tuple[str, ...]
    content_score: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank, "keyword": self.keyword, "category": self.category,
            "summary": self.summary, "why_now": self.why_now,
            "audience_question": self.audience_question,
            "content_angle": self.content_angle, "blog_title": self.blog_title,
            "shorts_hook": self.shorts_hook, "key_points": list(self.key_points),
            "source_urls": list(self.source_urls),
            "content_score": self.content_score,
        }


@dataclass(frozen=True)
class TrendDiscovery:
    researched_at: str
    period: str
    model: str
    query: str
    trends: tuple[TrendItem, ...]
    citations: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1, "researched_at": self.researched_at,
            "period": self.period, "model": self.model, "query": self.query,
            "trends": [item.to_dict() for item in self.trends],
            "citations": list(self.citations),
            "measurement_note": (
                "Perplexity가 최근 공개 웹 자료를 조사해 만든 편집 후보 목록입니다. "
                "검색량·SNS 도달·키워드 경쟁도를 직접 측정한 순위가 아닙니다."
            ),
        }


def build_trend_query(now: datetime | None = None) -> str:
    current = now or datetime.now(KST)
    date_text = current.astimezone(KST).strftime("%Y-%m-%d %H:%M KST")
    return f"""조사 기준 시각: {date_text}

한국어 콘텐츠 제작자를 위한 '최근 7일 이내 새롭게 주목받는 트렌드 키워드' 20개를 찾아주세요.
특정 업종에 한정하지 말고 AI·테크, 경제·금융, 정책·사회, 소비·생활, 건강, 여행·레저,
엔터테인먼트·문화, 스포츠, 교육·커리어 등 다양한 분야를 폭넓게 살펴보세요.

선정 기준:
- 최근 7일 이내 실제 발표·출시·사건·데이터·논의가 확인되는 주제
- 한국 이용자가 검색하거나 클릭할 만한 구체적인 질문과 정보 격차가 있는 주제
- 단순 상시 인기어보다 '왜 지금 관심을 가져야 하는가'를 설명할 수 있는 주제
- 서로 다른 분야가 고르게 포함되도록 하며, 특정 분야가 과도하게 점유하지 않도록 할 것
- 루머·출처 불명 주장·단순 광고성 키워드는 제외
- 자료가 부족한 항목은 억지로 채우지 말고 최대 20개까지만 제시

각 항목은 실제 출처를 확인하고, 확인된 사실과 해석을 구분하세요. 발행일과 사건 발생일을
혼동하지 말고, 오래된 사건을 최근 이슈처럼 포장하지 마세요. 법률·정책·금융·건강 주제는
가능하면 공식 1차 자료를 우선하세요. 출처 URL은 Perplexity가 인용한 URL 중 해당 항목을
직접 뒷받침하는 것만 넣으세요.

반드시 아래 JSON 객체 하나만 출력하세요. 마크다운 코드펜스나 JSON 앞뒤 설명은 쓰지 마세요.
{{
  "trends": [
    {{
      "rank": 1,
      "keyword": "구체적인 키워드",
      "category": "AI·테크 등 분야",
      "summary": "무슨 일이 일어났는지 확인된 사실 중심으로 2~3문장",
      "why_now": "최근 7일 안에 주목받는 이유와 날짜",
      "audience_question": "독자가 실제로 궁금해할 질문",
      "content_angle": "검색 유입을 노릴 차별화된 설명 관점",
      "blog_title": "검색 의도에 맞는 구체적인 블로그 제목",
      "shorts_hook": "첫 3초에 시선을 잡을 쇼츠 도입 문장",
      "key_points": ["확인된 핵심 사실 1", "핵심 사실 2", "독자에게 미치는 영향"],
      "source_urls": ["https://..."]
    }}
  ]
}}
순위는 검색량 순위가 아니라 근거의 최신성·한국 독자 관련성·설명 가치에 따른 편집 후보 순서입니다."""


def _decode_json_object(answer: str) -> dict[str, Any]:
    text = answer.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3].strip()
    decoder = json.JSONDecoder()
    start = text.find("{")
    if start < 0:
        raise ValueError("Perplexity 응답에서 JSON 객체를 찾지 못했습니다.")
    try:
        payload, _end = decoder.raw_decode(text[start:])
    except json.JSONDecodeError as error:
        raise ValueError("Perplexity 트렌드 응답의 JSON 형식이 올바르지 않습니다.") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("trends"), list):
        raise ValueError("Perplexity 응답에 trends 목록이 필요합니다.")
    return payload


def _clean_text(value: object, field: str, *, required: bool = True) -> str:
    if not isinstance(value, str):
        if required:
            raise ValueError(f"트렌드 필드 {field}가 문자열이 아닙니다.")
        return ""
    cleaned = value.strip()
    if required and not cleaned:
        raise ValueError(f"트렌드 필드 {field}가 비어 있습니다.")
    return cleaned


def _tokens(value: str) -> set[str]:
    normalized = re.sub(r"[^0-9a-z가-힣]+", " ", value.casefold())
    return {token for token in normalized.split() if len(token) > 1}


def _near_duplicate(left: str, right: str) -> bool:
    a, b = _tokens(left), _tokens(right)
    if not a or not b:
        return False
    overlap = len(a & b) / len(a | b)
    containment = len(a & b) / min(len(a), len(b))
    return overlap >= 0.62 or (containment >= 0.82 and min(len(a), len(b)) >= 2)


def _content_score(*, keyword: str, summary: str, why_now: str,
                   question: str, angle: str, points: tuple[str, ...],
                   source_urls: tuple[str, ...]) -> int:
    """Editorial score, not measured search volume or predicted views."""
    score = 20
    score += min(20, len(source_urls) * 10)
    score += min(15, len(points) * 5)
    score += 10 if len(summary) >= 45 else 0
    score += 10 if len(why_now) >= 25 else 0
    score += 10 if "?" in question or "？" in question else 0
    score += 10 if len(angle) >= 25 else 0
    score += 5 if len(keyword) >= 5 else 0
    return min(100, score)


def _category_key(category: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", category.casefold())


def parse_trend_result(result: ResearchResult, *, researched_at: str | None = None) -> TrendDiscovery:
    payload = _decode_json_object(result.answer)
    allowed_urls = set(result.citations)
    candidates: list[TrendItem] = []
    seen_keywords: set[str] = set()
    for raw in payload["trends"][:40]:
        if not isinstance(raw, dict):
            continue
        keyword = _clean_text(raw.get("keyword"), "keyword")
        summary = _clean_text(raw.get("summary"), "summary")
        why_now = _clean_text(raw.get("why_now"), "why_now")
        question = _clean_text(raw.get("audience_question"), "audience_question")
        angle = _clean_text(raw.get("content_angle"), "content_angle")
        category = _clean_text(raw.get("category"), "category", required=False) or "기타"
        normalized = " ".join(_tokens(keyword))
        if not normalized or normalized in seen_keywords:
            continue
        raw_points = raw.get("key_points", [])
        points = tuple(
            item.strip() for item in raw_points
            if isinstance(item, str) and len(item.strip()) >= 12
        ) if isinstance(raw_points, list) else ()
        urls = raw.get("source_urls", [])
        source_urls = tuple(dict.fromkeys(
            url for url in urls if isinstance(url, str) and url in allowed_urls
        )) if isinstance(urls, list) else ()
        # Do not attach unrelated global citations to a trend with no matching source.
        if not source_urls:
            continue
        candidates.append(TrendItem(
            rank=0, keyword=keyword, category=category, summary=summary,
            why_now=why_now, audience_question=question, content_angle=angle,
            blog_title=_clean_text(raw.get("blog_title"), "blog_title"),
            shorts_hook=_clean_text(raw.get("shorts_hook"), "shorts_hook"),
            key_points=points, source_urls=source_urls,
            content_score=_content_score(
                keyword=keyword, summary=summary, why_now=why_now,
                question=question, angle=angle, points=points,
                source_urls=source_urls,
            ),
        ))
        seen_keywords.add(normalized)

    # Greedy editorial selection: prioritize quality while limiting same-category
    # concentration and rejecting near-identical keyword/title concepts.
    selected: list[TrendItem] = []
    category_counts: dict[str, int] = {}
    remaining = sorted(candidates, key=lambda item: item.content_score, reverse=True)
    while remaining and len(selected) < 20:
        eligible = [
            item for item in remaining
            if category_counts.get(_category_key(item.category), 0) < 4
            and not any(_near_duplicate(item.keyword, chosen.keyword)
                        or _near_duplicate(item.blog_title, chosen.blog_title)
                        for chosen in selected)
        ]
        if not eligible:
            break
        chosen = eligible[0]
        selected.append(chosen)
        key = _category_key(chosen.category)
        category_counts[key] = category_counts.get(key, 0) + 1
        remaining.remove(chosen)

    trends = [TrendItem(**{**item.__dict__, "rank": index})
              for index, item in enumerate(selected, 1)]
    if len(trends) < 5:
        raise ValueError(
            f"출처·중복·품질 검증 후 유효한 트렌드가 {len(trends)}개뿐입니다. 최소 5개가 필요합니다."
        )
    return TrendDiscovery(
        researched_at=researched_at or datetime.now(KST).isoformat(timespec="seconds"),
        period="최근 7일", model=result.model, query=result.query,
        trends=tuple(trends), citations=result.citations,
    )


def discover_trends(provider: PerplexityResearchProvider, *, now: datetime | None = None) -> TrendDiscovery:
    query = build_trend_query(now)
    result = provider.search(query, search_recency_filter="week")
    return parse_trend_result(result)
