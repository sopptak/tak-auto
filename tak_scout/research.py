"""Perplexity research orchestration for TAK SCOUT candidates."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import json
import tempfile
from typing import Protocol
from blog_importer.models import utc_now
from .models import ScoutCandidate
from .perplexity_research import ResearchResult

class ResearchProvider(Protocol):
    def search(self, query: str, **kwargs: object) -> ResearchResult: ...

@dataclass(frozen=True)
class ResearchRecord:
    scout_id: str
    candidate_title: str
    candidate_url: str
    source_name: str
    candidate_published_at: str
    researched_at: str
    query: str
    answer: str
    citations: tuple[str, ...]
    model: str
    status: str = "completed"
    error: str = ""
    def to_dict(self) -> dict[str, object]:
        return {
            "scout_id": self.scout_id, "candidate_title": self.candidate_title,
            "candidate_url": self.candidate_url, "source_name": self.source_name,
            "candidate_published_at": self.candidate_published_at,
            "researched_at": self.researched_at, "query": self.query,
            "answer": self.answer, "citations": list(self.citations),
            "model": self.model, "status": self.status, "error": self.error,
        }

def build_research_query(candidate: ScoutCandidate) -> str:
    return (
        "다음 소재를 한국어로 심층 조사하세요. 확인된 사실과 해석을 구분하고 "
        "원문 발행일과 조사 기준일을 구분하세요. 핵심 주장마다 출처를 제시하고 "
        "반대 근거와 불확실성을 포함하세요. 법률·금융·정책은 공식 1차 자료를 "
        "우선하세요. 다음 순서로 답하세요: 1) 핵심 사실 2) 배경과 최근 변화 "
        "3) 이해관계자별 영향 4) 반론·위험·불확실성 5) 콘텐츠 확인 질문.\n\n"
        f"제목: {candidate.title}\n출처: {candidate.source_name}\n"
        f"발행일: {candidate.published_at or '미확인'}\n"
        f"기존 요약: {candidate.summary or '없음'}\n"
        f"원문 URL: {candidate.source_url}\n카테고리: {candidate.category}"
    )

def research_candidate(candidate: ScoutCandidate, provider: ResearchProvider, *,
                        recency: str | None = "month", domains: tuple[str, ...] = ()) -> ResearchRecord:
    query = build_research_query(candidate)
    try:
        result = provider.search(query, search_recency_filter=recency, search_domain_filter=domains)
    except Exception as error:  # one failure must not stop the batch; never persist exception text/secrets
        return ResearchRecord(candidate.scout_id, candidate.title, candidate.source_url,
            candidate.source_name, candidate.published_at, utc_now(), query, "", (), "",
            status="failed", error=type(error).__name__)
    return ResearchRecord(candidate.scout_id, candidate.title, candidate.source_url,
        candidate.source_name, candidate.published_at, utc_now(), query,
        result.answer, result.citations, result.model)

def research_candidates(candidates: list[ScoutCandidate], provider: ResearchProvider, *,
                        recency: str | None = "month", domains: tuple[str, ...] = ()) -> list[ResearchRecord]:
    return [research_candidate(c, provider, recency=recency, domains=domains) for c in candidates]

def save_research_records(records: list[ResearchRecord], path: Path | str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {"generated_at": utc_now(), "record_count": len(records),
        "completed_count": sum(r.status == "completed" for r in records),
        "failed_count": sum(r.status == "failed" for r in records),
        "records": [r.to_dict() for r in records]}
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temp = Path(handle.name)
    temp.replace(target)

def render_research_markdown(records: list[ResearchRecord]) -> str:
    lines = ["# TAK SCOUT 심층 조사", "", f"조사 건수: {len(records)}", "",
        "> AI 조사 결과는 검토용 초안이다. 법률·금융·정책 주장은 인용 원문과 기준일을 사람이 확인해야 한다.", ""]
    for i, r in enumerate(records, 1):
        lines.extend([f"## {i}. {r.candidate_title}", "", f"- 상태: {r.status}",
            f"- 원래 소재: {r.candidate_url}", f"- 출처: {r.source_name}",
            f"- 원문 발행일: {r.candidate_published_at or '미확인'}",
            f"- 조사 시각: {r.researched_at}", ""])
        if r.status == "completed":
            lines.extend([r.answer, "", "### 인용 출처", ""])
            lines.extend([f"- {u}" for u in r.citations] or ["- 인용 URL 없음"])
        else:
            lines.append(f"조사 실패: {r.error}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"

def save_research_markdown(records: list[ResearchRecord], path: Path | str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_research_markdown(records), encoding="utf-8")
