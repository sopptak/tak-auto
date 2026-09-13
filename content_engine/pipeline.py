"""승인된 KNOWLEDGE를 일괄 처리하는 TAK미디어 배치 파이프라인."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from tak_brain.models import KnowledgeRecord
from tak_brain.knowledge import load_knowledge_records, select_approved

from .generator import generate_content_bundle
from .models import BlogDraft, ContentDraft, ShortDraft, ThreadDraft
from .rewrite import MockRewriteProvider, RewriteProvider, RewriteService


@dataclass(frozen=True)
class MediaBatchItem:
    """배치 파이프라인에서 처리된 개별 콘텐츠 초안 결과."""

    knowledge_id: str
    platform: str
    status: str  # "valid", "rejected", "error"
    original_title: str
    original_body: str
    rewritten_title: str | None
    rewritten_body: str | None
    source_url: str
    evidence: tuple[str, ...]
    evidence_unit_ids: tuple[str, ...]
    rejection_reasons: tuple[str, ...] = ()
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "knowledge_id": self.knowledge_id,
            "platform": self.platform,
            "status": self.status,
            "original_title": self.original_title,
            "original_body": self.original_body,
            "rewritten_title": self.rewritten_title,
            "rewritten_body": self.rewritten_body,
            "source_url": self.source_url,
            "evidence": list(self.evidence),
            "evidence_unit_ids": list(self.evidence_unit_ids),
            "rejection_reasons": list(self.rejection_reasons),
            "error_message": self.error_message,
        }


@dataclass(frozen=True)
class MediaBatchReport:
    """전체 배치 파이프라인 실행 결과 요약 및 항목 목록."""

    total_knowledge_count: int
    approved_knowledge_count: int
    skipped_knowledge_count: int
    total_draft_count: int
    valid_count: int
    rejected_count: int
    error_count: int
    items: tuple[MediaBatchItem, ...]

    @property
    def valid_items(self) -> tuple[MediaBatchItem, ...]:
        return tuple(item for item in self.items if item.status == "valid")

    @property
    def rejected_items(self) -> tuple[MediaBatchItem, ...]:
        return tuple(item for item in self.items if item.status == "rejected")

    @property
    def error_items(self) -> tuple[MediaBatchItem, ...]:
        return tuple(item for item in self.items if item.status == "error")

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": {
                "total_knowledge_count": self.total_knowledge_count,
                "approved_knowledge_count": self.approved_knowledge_count,
                "skipped_knowledge_count": self.skipped_knowledge_count,
                "total_draft_count": self.total_draft_count,
                "valid_count": self.valid_count,
                "rejected_count": self.rejected_count,
                "error_count": self.error_count,
            },
            "valid_items": [item.to_dict() for item in self.valid_items],
            "rejected_items": [item.to_dict() for item in self.rejected_items],
            "error_items": [item.to_dict() for item in self.error_items],
            "all_items": [item.to_dict() for item in self.items],
        }

    def save_json(self, path: Path | str) -> None:
        target_path = Path(path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def _platform_name(draft: ContentDraft) -> str:
    if isinstance(draft, BlogDraft):
        return "blog"
    if isinstance(draft, ShortDraft):
        return "shorts"
    if isinstance(draft, ThreadDraft):
        return "threads"
    return "content"


def run_media_batch(
    records: Iterable[KnowledgeRecord],
    service: RewriteService | None = None,
    provider: RewriteProvider | None = None,
) -> MediaBatchReport:
    """승인된 KNOWLEDGE 목록을 받아 1건당 9개 Draft를 생성 및 Rewrite·검증한다."""
    records_list = tuple(records)
    total_count = len(records_list)
    approved_records = tuple(select_approved(records_list))
    skipped_count = total_count - len(approved_records)

    rewrite_service = service or RewriteService(provider or MockRewriteProvider())

    items: list[MediaBatchItem] = []

    for knowledge in approved_records:
        try:
            bundle = generate_content_bundle(knowledge)
        except Exception as error:
            items.append(
                MediaBatchItem(
                    knowledge_id=knowledge.id,
                    platform="bundle",
                    status="error",
                    original_title=knowledge.title,
                    original_body="",
                    rewritten_title=None,
                    rewritten_body=None,
                    source_url=knowledge.source_url or "",
                    evidence=tuple(knowledge.evidence or ()),
                    evidence_unit_ids=(),
                    rejection_reasons=(),
                    error_message=f"Content bundle generation failed: {error}",
                )
            )
            continue

        if bundle.status != "complete" or bundle.blog is None:
            items.append(
                MediaBatchItem(
                    knowledge_id=knowledge.id,
                    platform="bundle",
                    status="error",
                    original_title=knowledge.title,
                    original_body="",
                    rewritten_title=None,
                    rewritten_body=None,
                    source_url=knowledge.source_url or "",
                    evidence=tuple(knowledge.evidence or ()),
                    evidence_unit_ids=(),
                    rejection_reasons=tuple(bundle.unmet_requirement_ids),
                    error_message=f"Incomplete content bundle: {bundle.status}",
                )
            )
            continue

        drafts: tuple[ContentDraft, ...] = (bundle.blog, *bundle.shorts, *bundle.threads)

        for draft in drafts:
            platform = _platform_name(draft)
            try:
                result = rewrite_service.rewrite(knowledge, draft)
                if result.validation_status == "valid":
                    status = "valid"
                    rewritten_title = result.rewritten_draft.title
                    rewritten_body = result.rewritten_draft.body
                else:
                    status = "rejected"
                    rewritten_title = result.rewritten_draft.title if result.rewritten_draft else None
                    rewritten_body = result.rewritten_draft.body if result.rewritten_draft else None

                items.append(
                    MediaBatchItem(
                        knowledge_id=knowledge.id,
                        platform=platform,
                        status=status,
                        original_title=draft.title,
                        original_body=draft.body,
                        rewritten_title=rewritten_title,
                        rewritten_body=rewritten_body,
                        source_url=draft.source_url,
                        evidence=draft.evidence,
                        evidence_unit_ids=draft.evidence_unit_ids,
                        rejection_reasons=result.validation_errors,
                        error_message=None,
                    )
                )
            except Exception as error:
                items.append(
                    MediaBatchItem(
                        knowledge_id=knowledge.id,
                        platform=platform,
                        status="error",
                        original_title=draft.title,
                        original_body=draft.body,
                        rewritten_title=None,
                        rewritten_body=None,
                        source_url=draft.source_url,
                        evidence=draft.evidence,
                        evidence_unit_ids=draft.evidence_unit_ids,
                        rejection_reasons=(),
                        error_message=str(error),
                    )
                )

    total_draft_count = len(items)
    valid_count = sum(1 for item in items if item.status == "valid")
    rejected_count = sum(1 for item in items if item.status == "rejected")
    error_count = sum(1 for item in items if item.status == "error")

    return MediaBatchReport(
        total_knowledge_count=total_count,
        approved_knowledge_count=len(approved_records),
        skipped_knowledge_count=skipped_count,
        total_draft_count=total_draft_count,
        valid_count=valid_count,
        rejected_count=rejected_count,
        error_count=error_count,
        items=tuple(items),
    )


def run_media_batch_file(
    input_path: Path | str,
    output_path: Path | str | None = None,
    service: RewriteService | None = None,
    provider: RewriteProvider | None = None,
    limit: int | None = None,
    knowledge_id: str | None = None,
) -> MediaBatchReport:
    """KNOWLEDGE JSON 파일 경로에서 승인 기록을 읽어 배치를 실행하고 필요 시 결과를 저장한다."""
    records = load_knowledge_records(input_path)
    if knowledge_id:
        records = tuple(record for record in records if record.id == knowledge_id)
    if limit is not None and limit > 0:
        approved_only = tuple(select_approved(records))[:limit]
        # limit 적용 시 승인 목록 제한
        records = approved_only

    report = run_media_batch(records, service=service, provider=provider)
    if output_path:
        report.save_json(output_path)
    return report
