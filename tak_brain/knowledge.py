"""규칙 기반 RAW -> KNOWLEDGE 변환과 검토 경계."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import fields, replace
from pathlib import Path
import json
import re
import tempfile
from typing import Any, Iterable

from blog_importer.models import BlogPost, utc_now

from .models import KnowledgeRecord, RawContent


class KnowledgeTransformer(ABC):
    """외부 AI 없이도 교체 가능한 KNOWLEDGE 생성 인터페이스."""

    @abstractmethod
    def transform(self, raw: RawContent) -> KnowledgeRecord:
        raise NotImplementedError


class RuleBasedKnowledgeTransformer(KnowledgeTransformer):
    """원문에 확인되는 사실과 제한적인 해석을 분리하는 템플릿 변환기."""

    _TESTER_PATTERN = re.compile(r"테스터\s*(\d+)명")

    def transform(self, raw: RawContent) -> KnowledgeRecord:
        body = raw.body
        tester_match = self._TESTER_PATTERN.search(body)
        tester_text = f"테스터 {tester_match.group(1)}명이 참여한 " if tester_match else ""
        has_private_test = "비공개 테스트" in body
        evidence = [f"제목에 '{raw.title}'이 기록되어 있다."]
        if has_private_test:
            detail = "본문에서 비공개 테스트가 확인된다."
            if tester_match:
                detail = f"본문에서 비공개 테스트와 테스터 {tester_match.group(1)}명 참여가 확인된다."
            evidence.append(detail)
        else:
            evidence.append("본문 원문은 이 KNOWLEDGE의 근거로 읽혔으며, 추가 사실은 생성하지 않았다.")

        experience = "개발을 모르는 작성자가 앱을 직접 만든 경험을 기록한 사례이다."
        problem = "개발 지식이 없는 상태에서 앱을 만들며 구현과 검증을 진행해야 하는 상황이었다."
        action = f"앱을 만들고 {tester_text}테스트를 진행했다." if has_private_test else "앱 제작을 직접 시도했다."
        result = f"{tester_text}앱 제작 결과를 테스트 단계까지 진행했다." if tester_match else "앱 제작 경험이 원문에 기록되어 있다."
        lesson = "낯선 기술 영역도 직접 작은 결과물을 만들며 경험을 축적할 수 있다는 사례다."
        reusable_principle = "새로운 작업은 작은 결과물을 먼저 만들고 실제 사용자의 테스트로 검증한다."
        return KnowledgeRecord(
            id=f"knowledge-{raw.content_hash[:12]}",
            source_raw_id=raw.id,
            source_url=raw.source_url,
            title=raw.title,
            domain="자기계발",
            knowledge_type="경험",
            experience=experience,
            problem=problem,
            action=action,
            decision="개발을 모르는 상태에서도 앱 제작을 직접 시도하기로 했다.",
            result=result,
            lesson=lesson,
            reusable_principle=reusable_principle,
            evidence=tuple(evidence),
            derived_insight="작은 결과물을 먼저 만들고 사용자 테스트로 검증하는 원칙으로 일반화한 부분은 규칙 기반 템플릿이 도출한 정리다.",
            inference_method="rule_based_template",
            created_at=utc_now(),
            knowledge_review_status="pending",
            category="자기계발",
            case="비개발자의 앱 제작 사례",
            judgment_rule="낯선 영역은 직접 시도하고 테스트하면서 검증한다.",
            current_validity="확인 필요",
            verification_required=True,
        )


def transform_raw(raw: RawContent, transformer: KnowledgeTransformer | None = None) -> KnowledgeRecord:
    return (transformer or RuleBasedKnowledgeTransformer()).transform(raw)


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