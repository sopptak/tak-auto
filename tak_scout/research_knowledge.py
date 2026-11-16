"""Perplexity 조사 결과를 TAK BRAIN의 사람 검토용 KNOWLEDGE 초안으로 연결한다.

조사 결과는 작성자의 개인 경험이나 의견으로 변환하지 않는다. 외부 정보로 분류하고
항상 pending으로 저장한다. 승인된 동일 ID 레코드는 재조사로 덮어쓰지 않는다.
"""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile

from blog_importer.models import utc_now
from tak_brain.knowledge import load_knowledge_records, validate_knowledge
from tak_brain.models import KnowledgeRecord

from .research import ResearchRecord
from .research_quality import assess_research_quality


def _knowledge_id(scout_id: str) -> str:
    digest = hashlib.sha256(scout_id.encode("utf-8")).hexdigest()[:16]
    return f"knowledge-research-{digest}"


def build_knowledge_from_research(record: ResearchRecord) -> KnowledgeRecord:
    """외부 조사 결과를 정보형 pending KNOWLEDGE로 변환한다."""
    if record.status != "completed" or not record.answer.strip():
        raise ValueError("완료된 Perplexity 조사 결과만 KNOWLEDGE로 변환할 수 있습니다.")
    if not record.scout_id or not record.candidate_url:
        raise ValueError("SCOUT ID와 원문 URL이 필요합니다.")

    evidence = [
        f"SCOUT SOURCE: {record.candidate_url}",
        f"RESEARCH PROVIDER: Perplexity {record.model or 'model unknown'}",
        f"RESEARCHED AT: {record.researched_at}",
    ]
    evidence.extend(f"PERPLEXITY CITATION: {url}" for url in record.citations)
    quality = assess_research_quality(record)
    evidence.append(
        f"RESEARCH RECORD COMPLETENESS: {quality.level} ({quality.score}/100); "
        "not a factual verification"
    )
    evidence.extend(f"RESEARCH REVIEW WARNING: {warning}" for warning in quality.warnings)

    knowledge = KnowledgeRecord(
        id=_knowledge_id(record.scout_id),
        source_raw_id=f"research:{record.scout_id}",
        source_url=record.candidate_url,
        title=record.candidate_title,
        article_type=None,
        domain="외부 조사",
        category="기타",
        knowledge_type="정보",
        lesson=record.answer,
        evidence=tuple(evidence),
        inference_method="rule_based_template",
        confidence=None,
        created_at=record.researched_at or utc_now(),
        knowledge_review_status="pending",
        summary=record.answer[:500],
        key_points=(),
        factual_information=record.answer,
        current_validity="조사 시점 기준이며 최신성 및 원문 확인 필요",
        verification_required=True,
    )
    validate_knowledge(knowledge)
    return knowledge


def upsert_research_knowledge(
    record: ResearchRecord, path: Path | str
) -> tuple[KnowledgeRecord, str]:
    """연결 결과와 상태를 반환한다: created, updated_pending, already_approved."""
    target = Path(path)
    if target.exists():
        data = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
            raise ValueError("KNOWLEDGE 파일은 객체 목록이어야 합니다.")
    else:
        data = []

    knowledge = build_knowledge_from_research(record)
    existing_index = next(
        (i for i, item in enumerate(data) if item.get("id") == knowledge.id), None
    )
    if existing_index is not None:
        existing = data[existing_index]
        if existing.get("knowledge_review_status") == "approved":
            approved = next((item for item in load_knowledge_records(target) if item.id == knowledge.id), None)
            if approved is None:
                raise ValueError("승인된 KNOWLEDGE를 다시 읽을 수 없습니다.")
            return approved, "already_approved"
        if existing.get("knowledge_review_status") not in {"pending", None, ""}:
            raise ValueError("기존 KNOWLEDGE가 pending 상태가 아니므로 자동 갱신하지 않습니다.")
        # 재조사 결과를 pending 초안에 반영하되 생성 시각과 검토 메모는 보존한다.
        knowledge = replace(
            knowledge,
            created_at=str(existing.get("created_at") or knowledge.created_at),
            review_note=existing.get("review_note"),
        )
        data[existing_index] = knowledge.to_dict()
        status = "updated_pending"
    else:
        data.append(knowledge.to_dict())
        status = "created"

    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, delete=False) as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(target)
    return knowledge, status
