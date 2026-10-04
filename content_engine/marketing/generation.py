"""승인된 MarketingBrief -> 기존 콘텐츠 생성기 어댑터(docs/6-80-marketing-brief-to-content.md).

새 생성 로직을 만들지 않는다. 기존 ``generate_content_bundle``(규칙 기반 초안)과 ``RewriteService``
(선택적 재작성 + 검증), ``short_draft_to_shorts_script``(YouTube용 구조 변환), ``compute_content_id``
(콘텐츠 식별자)를 그대로 호출하고, 브리프는 플랫폼 선택과 재작성 가이드(marketing_guidance)로만 쓴다.

경계:
    - approved이고 승인 조건을 현재 내용으로 다시 통과한 플랫폼 브리프만 생성한다(generation_blockers).
    - brief.knowledge_ids에 있고 approved인 KNOWLEDGE만 사용한다.
    - 후보는 항상 status="review_required"로 저장된다. 발행 코드를 import/호출하지 않는다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from blog_importer.models import utc_now
from content_engine.generator import generate_content_bundle
from content_engine.models import ContentBundle, ContentDraft, ShortDraft
from content_engine.publish_history import compute_content_id
from content_engine.rewrite import RewriteProvider, RewriteService
from content_engine.shorts_adapter import ShortsAdapterError, short_draft_to_shorts_script
from content_engine.shorts_script import ShortsScriptError
from tak_brain.models import KnowledgeRecord

from .briefs import readiness_blockers
from .models import STATUS_APPROVED, STATUS_REJECTED, MarketingBrief, MarketingError
from .prompt import build_content_prompt, render_prompt_text
from .store import _read, _write, link_content, load_briefs

CONTENTS_FILE = "tak_marketing_contents.json"
STATUS_REVIEW_REQUIRED = "review_required"
REWRITE_NOT_REQUESTED = "not_requested"
REWRITE_ERROR = "error"


def generation_blockers(brief: MarketingBrief) -> list[str]:
    """생성 단계로 넘기기 전에 해결해야 할 항목. 빈 목록이어야 생성할 수 있다."""
    blockers = []
    if brief.status == STATUS_REJECTED:
        blockers.append("rejected 브리프는 생성할 수 없습니다.")
    elif brief.status != STATUS_APPROVED:
        blockers.append(f"approved 브리프만 생성할 수 있습니다(현재 {brief.status}).")
    if not brief.platform:
        blockers.append("플랫폼 브리프가 아닙니다(platform 없음). platforms로 파생한 브리프를 승인하세요.")
    blockers += readiness_blockers(brief)
    return list(dict.fromkeys(blockers))


@dataclass(frozen=True)
class GenerationResult:
    brief_id: str
    platform: str
    candidates: tuple[dict[str, Any], ...] = ()
    blockers: tuple[str, ...] = ()  # 게이트 차단: 아무것도 생성하지 않았다
    skipped: tuple[str, ...] = ()  # KNOWLEDGE별 생성 불가 사유(insufficient_distinct_evidence 등)

    @property
    def reasons(self) -> tuple[str, ...]:
        """후보가 없을 때 사람이 읽을 사유."""
        if self.blockers:
            return self.blockers
        if not self.candidates:
            return self.skipped or ("생성된 후보가 없습니다.",)
        return ()


def _platform_drafts(bundle: ContentBundle, platform: str) -> tuple[ContentDraft, ...]:
    if platform == "blog":
        return (bundle.blog,) if bundle.blog is not None else ()
    if platform == "threads":
        return bundle.threads
    if platform in ("shorts", "youtube"):
        return bundle.shorts
    raise MarketingError(f"생성할 수 없는 platform: {platform!r}")


def _script_dict(draft: ShortDraft) -> dict[str, Any]:
    script = short_draft_to_shorts_script(draft)
    return {"title": script.title, "subtitle": script.subtitle, "cards": list(script.cards),
            "takeaway": script.takeaway, "brand": script.brand}


def _candidate(
    brief: MarketingBrief, knowledge: KnowledgeRecord, draft: ContentDraft, service: RewriteService | None,
    guidance: str, contract: Sequence[str], created_at: str,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "brief_id": brief.brief_id,
        "platform": brief.platform,
        "knowledge_id": knowledge.id,
        "status": STATUS_REVIEW_REQUIRED,
        "requires_human_review": True,
        "original_title": draft.title,
        "original_body": draft.body,
        "evidence_unit_ids": list(draft.evidence_unit_ids),
        "source_url": draft.source_url,
        "evidence": list(draft.evidence),
        "rewritten_title": None,
        "rewritten_body": None,
        "rewrite_status": REWRITE_NOT_REQUESTED,
        "validation_errors": [],
        "marketing_guidance": guidance,
        "generation_contract": list(contract),
        "created_at": created_at,
    }
    final_draft = draft
    if service is not None:
        try:
            result = service.rewrite(knowledge, draft, marketing_guidance=guidance)
        except Exception as error:  # provider 오류는 후보를 버리지 않고 원본 + 사유로 남긴다(pipeline과 동일)
            record.update(rewrite_status=REWRITE_ERROR, rewrite_error=str(error))
        else:
            record.update(rewritten_title=result.rewritten_draft.title, rewritten_body=result.rewritten_draft.body,
                          rewrite_status=result.rewrite_status, validation_errors=list(result.validation_errors))
            if result.rewrite_status == "rewritten":
                final_draft = result.rewritten_draft
    if brief.platform == "youtube":
        record["draft_platform"] = "shorts"
        try:
            record["shorts_script"] = _script_dict(final_draft)
        except (ShortsAdapterError, ShortsScriptError) as error:
            record.update(shorts_script=None, shorts_script_error=str(error))
    # 기존 식별 규칙 그대로(knowledge_id/platform/source_url/evidence_unit_ids/original_*).
    record["content_id"] = compute_content_id(record)
    return record


def generate_candidates(
    brief: MarketingBrief,
    knowledge_records: Sequence[KnowledgeRecord],
    provider: RewriteProvider | None = None,
    now: str | None = None,
) -> GenerationResult:
    """승인된 플랫폼 브리프 1개로 기존 생성기를 호출해 검토 대기 후보를 만든다(저장하지 않는다)."""
    blockers = generation_blockers(brief)
    if blockers:
        return GenerationResult(brief.brief_id, brief.platform, blockers=tuple(blockers))

    by_id = {record.id: record for record in knowledge_records if record.knowledge_review_status == "approved"}
    selected = [by_id[kid] for kid in dict.fromkeys(brief.knowledge_ids) if kid in by_id]
    if not selected:
        return GenerationResult(brief.brief_id, brief.platform, blockers=(
            f"brief.knowledge_ids({', '.join(brief.knowledge_ids) or '없음'})와 일치하는 approved KNOWLEDGE가 없습니다.",
        ))

    contract = build_content_prompt(brief)
    guidance = render_prompt_text(contract)
    service = RewriteService(provider) if provider is not None else None
    created_at = now or utc_now()
    candidates: list[dict[str, Any]] = []
    skipped: list[str] = []
    for knowledge in selected:
        try:
            bundle = generate_content_bundle(knowledge)
        except ValueError as error:
            skipped.append(f"{knowledge.id}: {error}")
            continue
        if bundle.status == "insufficient_distinct_evidence":
            skipped.append(f"{knowledge.id}: insufficient_distinct_evidence ({', '.join(bundle.unmet_requirement_ids)})")
            continue
        for draft in _platform_drafts(bundle, brief.platform):
            candidates.append(_candidate(brief, knowledge, draft, service, guidance,
                                         contract["generation_contract"], created_at))
    return GenerationResult(brief.brief_id, brief.platform, tuple(candidates), skipped=tuple(skipped))


def save_candidates(contents_path: Path | str, briefs_path: Path | str, result: GenerationResult) -> int:
    """후보를 review_required로 저장하고 브리프에 content_id를 연결한다. 새로 저장한 건수를 반환한다.

    저장 직전에 저장소의 브리프를 다시 읽어 게이트를 재확인한다(생성 후 편집/반려된 브리프 차단).
    같은 (brief_id, content_id)는 다시 저장하지 않으며 link_content도 중복 연결하지 않는다.
    """
    if result.blockers:
        raise MarketingError("차단된 생성 결과는 저장할 수 없습니다: " + " / ".join(result.blockers))
    current = next((item for item in load_briefs(briefs_path) if item.brief_id == result.brief_id), None)
    if current is None:
        raise MarketingError(f"브리프를 찾을 수 없습니다: {result.brief_id}")
    blockers = generation_blockers(current)
    if blockers:
        raise MarketingError("저장 시점에 생성 조건을 통과하지 못했습니다: " + " / ".join(blockers))
    if any(candidate["status"] != STATUS_REVIEW_REQUIRED or candidate["brief_id"] != result.brief_id
           for candidate in result.candidates):
        raise MarketingError("review_required 상태의 같은 브리프 후보만 저장할 수 있습니다.")

    rows = _read(contents_path)
    seen = {(row.get("brief_id"), row.get("content_id")) for row in rows}
    new = []
    for candidate in result.candidates:
        key = (candidate["brief_id"], candidate["content_id"])
        if key not in seen:
            seen.add(key)
            new.append(dict(candidate))
    if new:
        _write(contents_path, rows + new)
    for content_id in dict.fromkeys(candidate["content_id"] for candidate in result.candidates):
        link_content(briefs_path, result.brief_id, content_id)
    return len(new)
