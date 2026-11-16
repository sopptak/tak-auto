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

def build_research_query(candidate: ScoutCandidate, *, profile: str = "auction") -> str:
    """Build a source-led research brief. Auction is the default TAK AUTO content profile."""
    if profile not in {"auction", "general"}:
        raise ValueError("profile는 auction 또는 general이어야 합니다.")
    common = (
        "다음 소재를 한국어로 심층 조사하세요. 조사 기준일과 원문 발행일을 구분하고, "
        "확인된 사실·해석·추정을 명확히 나누세요. 핵심 주장마다 근거 URL과 해당 근거가 "
        "뒷받침하는 내용을 연결하세요. 상충하는 자료, 반대 근거, 불확실성도 숨기지 마세요. "
        "법률·금융·정책은 공식 1차 자료를 우선하고, 보도자료·기사·블로그는 보조자료로 "
        "취급하세요. 법령은 조문과 시행일, 판례는 법원·선고일·사건번호를 확인하고 "
        "확인할 수 없으면 미확인으로 표시하세요. 자료에 없는 숫자·사실·사례를 만들지 마세요."
    )
    if profile == "auction":
        focus = (
            " 이 콘텐츠는 국내 부동산 법원경매 실무를 우선합니다. 다음 항목 중 소재와 "
            "직접 관련된 것만 조사하세요: 경매와 공매의 구분, 매각절차와 기일, 말소기준권리, "
            "등기부 권리관계, 임차인의 대항력·우선변제권·최우선변제, 배당요구 종기, "
            "인수되는 권리와 소멸하는 권리, 유치권·법정지상권·분묘기지권, 명도 및 인도명령, "
            "취득세·부가가치세 등 비용, 금융기관 경락잔금대출의 심사 변수. 모든 항목을 "
            "기계적으로 나열하지 말고 해당 소재에 필요한 쟁점만 선택하세요. 법률 판단은 "
            "국가법령정보센터·대법원 종합법률정보·대한민국 법원 경매정보 등 공식 원문을 "
            "우선 확인하고, 대출 가능액은 확정·승인처럼 표현하지 말고 조건과 변수로 구분하세요. "
            "다음 순서로 답하세요: 1) 사건·제도 핵심 2) 적용 법령·공식 근거와 기준일 "
            "3) 경매 참여자 및 채권자·임차인별 영향 4) 실무 체크리스트 5) 반론·위험·예외 "
            "6) 콘텐츠로 설명할 때 오해하기 쉬운 표현 7) 추가 확인 질문."
        )
    else:
        focus = (
            " 소재의 분야에 맞는 쟁점을 선택하고 다음 순서로 답하세요: 1) 핵심 사실 "
            "2) 배경과 최근 변화 3) 이해관계자별 영향 4) 반론·위험·불확실성 "
            "5) 콘텐츠 확인 질문."
        )
    return (
        common + focus + "\\n\\n"
        f"제목: {candidate.title}\\n출처: {candidate.source_name}\\n"
        f"발행일: {candidate.published_at or '미확인'}\\n"
        f"기존 요약: {candidate.summary or '없음'}\\n"
        f"원문 URL: {candidate.source_url}\\n카테고리: {candidate.category}"
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


def load_research_records(path: Path | str) -> list[ResearchRecord]:
    """조사 저장소를 읽는다. 파일이 없으면 빈 목록, 잘못된 구조는 오류로 드러낸다."""
    target = Path(path)
    if not target.exists():
        return []
    data = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("records"), list):
        raise ValueError("TAK SCOUT research JSON 구조가 올바르지 않습니다.")
    records: list[ResearchRecord] = []
    for item in data["records"]:
        if not isinstance(item, dict):
            continue
        records.append(ResearchRecord(
            scout_id=str(item.get("scout_id") or ""),
            candidate_title=str(item.get("candidate_title") or ""),
            candidate_url=str(item.get("candidate_url") or ""),
            source_name=str(item.get("source_name") or ""),
            candidate_published_at=str(item.get("candidate_published_at") or ""),
            researched_at=str(item.get("researched_at") or ""),
            query=str(item.get("query") or ""),
            answer=str(item.get("answer") or ""),
            citations=tuple(url for url in item.get("citations", []) if isinstance(url, str)),
            model=str(item.get("model") or ""),
            status=str(item.get("status") or "completed"),
            error=str(item.get("error") or ""),
        ))
    return records


def upsert_research_record(path: Path | str, record: ResearchRecord) -> None:
    """동일 scout_id의 재조사는 기존 레코드를 대체하고 다른 소재는 보존한다."""
    records = load_research_records(path)
    by_id = {item.scout_id: item for item in records}
    by_id[record.scout_id] = record
    save_research_records(list(by_id.values()), path)
