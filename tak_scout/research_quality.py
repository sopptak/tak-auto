"""Deterministic quality signals for external research; never claims factual verification."""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from .research import ResearchRecord


@dataclass(frozen=True)
class ResearchQuality:
    level: str
    score: int
    citation_count: int
    unique_hosts: int
    checks: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def requires_human_review(self) -> bool:
        return bool(self.warnings)


def assess_research_quality(record: ResearchRecord) -> ResearchQuality:
    """Assess completeness/provenance only. It does not verify claims or source contents."""
    checks: list[str] = []
    warnings: list[str] = []
    valid_urls: list[str] = []
    for raw in record.citations:
        parsed = urlparse(raw)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            valid_urls.append(raw)
    hosts = {urlparse(url).hostname.lower() for url in valid_urls if urlparse(url).hostname}
    score = 0

    if record.status == "completed" and record.answer.strip():
        checks.append("조사 응답 존재")
        score += 20
    else:
        warnings.append("조사 응답이 없거나 완료 상태가 아닙니다.")

    if record.candidate_url and urlparse(record.candidate_url).scheme in {"http", "https"}:
        checks.append("SCOUT 원문 URL 기록")
        score += 15
    else:
        warnings.append("SCOUT 원문 URL을 확인할 수 없습니다.")

    if record.candidate_published_at.strip():
        checks.append("원문 발행일 기록")
        score += 10
    else:
        warnings.append("원문 발행일 미확인")

    if record.researched_at.strip():
        checks.append("조사 시각 기록")
        score += 10
    else:
        warnings.append("조사 시각 미기록")

    if len(valid_urls) >= 3:
        checks.append("인용 URL 3개 이상")
        score += 25
    elif valid_urls:
        warnings.append(f"인용 URL이 {len(valid_urls)}개뿐입니다. 핵심 주장별 근거를 추가 확인하세요.")
        score += 10
    else:
        warnings.append("유효한 인용 URL이 없습니다.")

    if len(hosts) >= 2:
        checks.append("서로 다른 출처 도메인 2개 이상")
        score += 20
    elif hosts:
        warnings.append("출처 도메인이 하나뿐입니다. 독립적인 교차 확인이 필요합니다.")
        score += 5
    else:
        warnings.append("출처 도메인을 확인할 수 없습니다.")

    if warnings:
        level = "review_required"
    elif score >= 80:
        level = "completeness_good"
    else:
        level = "review_required"
    return ResearchQuality(level, min(score, 100), len(valid_urls), len(hosts),
                           tuple(checks), tuple(warnings))
