"""규칙 기반 RAW -> KNOWLEDGE 변환과 검토 경계."""

from __future__ import annotations

from dataclasses import fields, replace
from pathlib import Path
import json
import tempfile
from typing import Any, Iterable

from blog_importer.models import BlogPost, utc_now

from .article_types import ArticleTypeClassifier
from .knowledge_transformers import KnowledgeTransformer, TRANSFORMERS
from .models import KnowledgeRecord, RawContent


class RuleBasedKnowledgeTransformer(KnowledgeTransformer):
    """분류 결과에 맞는 유형별 변환기로 위임하는 호환 dispatcher."""

    def __init__(self, classifier: ArticleTypeClassifier | None = None) -> None:
        self.classifier = classifier or ArticleTypeClassifier()

    def transform(self, raw: RawContent) -> KnowledgeRecord:
        classification = self.classifier.classify(raw)
        transformer = TRANSFORMERS[classification.article_type]()
        return transformer.transform(raw, classification)


def transform_raw(raw: RawContent, transformer: KnowledgeTransformer | None = None) -> KnowledgeRecord:
    knowledge = (transformer or RuleBasedKnowledgeTransformer()).transform(raw)
    validate_knowledge(knowledge)
    return knowledge


def append_knowledge_file(
    raw_path: str | Path,
    knowledge_path: str | Path,
) -> tuple[int, int, int]:
    """기존 KNOWLEDGE를 보존하면서 RAW별 신규 초안만 누적합니다."""
    output_path = Path(knowledge_path)
    raw_records = load_raw_records(raw_path)
    if output_path.exists():
        data = json.loads(output_path.read_text(encoding="utf-8"))
        if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
            raise ValueError("KNOWLEDGE 파일은 객체 목록이어야 합니다.")
    else:
        data = []

    existing_source_ids = {item.get("source_raw_id") for item in data}
    created = 0
    duplicates = 0
    errors = 0
    for raw in raw_records:
        if raw.id in existing_source_ids:
            duplicates += 1
            continue
        try:
            knowledge = transform_raw(raw)
        except (ValueError, KeyError, TypeError):
            errors += 1
            continue
        data.append(knowledge.to_dict())
        existing_source_ids.add(raw.id)
        created += 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=output_path.parent, delete=False) as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary_path = Path(handle.name)
    temporary_path.replace(output_path)
    return created, duplicates, errors


def validate_knowledge(knowledge: KnowledgeRecord) -> None:
    if not knowledge.source_raw_id or not knowledge.source_url:
        raise ValueError("KNOWLEDGE는 source_raw_id와 source_url이 필요합니다.")
    if knowledge.confidence is not None:
        raise ValueError("현재 규칙 기반 KNOWLEDGE의 confidence는 null이어야 합니다.")
    if knowledge.inference_method != "rule_based_template":
        raise ValueError("inference_method는 rule_based_template이어야 합니다.")
    if knowledge.knowledge_review_status != "pending":
        raise ValueError("새로 생성되는 KNOWLEDGE는 pending이어야 합니다.")


def raw_from_record(record: dict[str, Any]) -> RawContent:
    raw_data = record.get("raw", record)
    if not isinstance(raw_data, dict):
        raise ValueError("RAW 레코드는 객체여야 합니다.")
    return RawContent.from_post(BlogPost.from_mapping(raw_data))


def load_raw_records(path: str | Path) -> list[RawContent]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("RAW 파일은 객체 목록이어야 합니다.")
    return [raw_from_record(record) for record in data]


def select_approved(records: Iterable[KnowledgeRecord]) -> tuple[KnowledgeRecord, ...]:
    """승인된 KNOWLEDGE만 이후 콘텐츠 생성 대상으로 선택합니다."""
    return tuple(record for record in records if record.knowledge_review_status == "approved")


def set_review_status(record: KnowledgeRecord, status: str) -> KnowledgeRecord:
    if status not in {"pending", "approved", "rejected"}:
        raise ValueError("knowledge_review_status는 pending, approved, rejected 중 하나여야 합니다.")
    return replace(record, knowledge_review_status=status)


def _knowledge_from_dict(data: dict[str, Any]) -> KnowledgeRecord:
    field_names = {field.name for field in fields(KnowledgeRecord)}
    values = {key: value for key, value in data.items() if key in field_names}
    values["evidence"] = tuple(values.get("evidence", ()))
    values["key_points"] = tuple(values.get("key_points", ()))
    return KnowledgeRecord(**values)


def load_knowledge_records(path: str | Path) -> list[KnowledgeRecord]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        raise ValueError("KNOWLEDGE 파일은 객체 목록이어야 합니다.")
    return [_knowledge_from_dict(item) for item in data]


def list_pending_knowledge(path: str | Path) -> tuple[KnowledgeRecord, ...]:
    return tuple(record for record in load_knowledge_records(path) if record.knowledge_review_status == "pending")


def assess_knowledge_quality(record: KnowledgeRecord) -> tuple[str, str, str]:
    """저장된 KNOWLEDGE를 사람 검토용 A/B/C로 보수적으로 분류합니다."""
    if not record.source_raw_id or not record.source_url or not record.evidence:
        return "C", "출처 연결 또는 원문 근거가 부족합니다.", "거절"
    if record.article_type == "general":
        return "B", "글 유형이 불확실해 사람이 내용과 추출 적합성을 확인해야 합니다.", "수정검토"
    if record.article_type == "book_philosophy" and record.experience:
        return "C", "책의 주장이 작성자의 개인 경험처럼 기록되어 있습니다.", "거절"
    if record.article_type == "finance" and record.experience:
        return "B", "일반 금융 설명과 작성자의 개인 경험을 분리해 확인해야 합니다.", "수정검토"
    if record.article_type == "ai_business" and record.result and "기다" in record.title:
        return "C", "수익 목표와 실제 결과가 혼동될 가능성이 있습니다.", "거절"
    if record.article_type == "workplace" and not record.lesson and not record.reusable_principle:
        return "B", "직장 관찰의 핵심 판단기준이 부족해 사람이 보강해야 합니다.", "수정검토"
    return "A", "유형과 원문 근거가 연결되어 있으며 명백한 과잉 생성이 없습니다.", "승인"


def review_knowledge_file(
    path: str | Path,
    knowledge_id: str,
    status: str,
    review_note: str | None = None,
) -> KnowledgeRecord:
    if status not in {"pending", "approved", "rejected"}:
        raise ValueError("review status는 pending, approved, rejected 중 하나여야 합니다.")
    output_path = Path(path)
    data = json.loads(output_path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        raise ValueError("KNOWLEDGE 파일은 객체 목록이어야 합니다.")

    target = next((item for item in data if item.get("id") == knowledge_id), None)
    if target is None:
        raise KeyError(f"KNOWLEDGE ID를 찾을 수 없습니다: {knowledge_id}")
    target["knowledge_review_status"] = status
    target["reviewed_at"] = utc_now()
    if review_note is not None:
        target["review_note"] = review_note

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=output_path.parent, delete=False) as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary_path = Path(handle.name)
    temporary_path.replace(output_path)
    return _knowledge_from_dict(target)