"""MarketingBrief <-> 승인 KNOWLEDGE 연결 관리(docs/6-83). 순수 함수: 연결 가능 여부와 미리보기 정보만 계산한다.

원칙:
    - KNOWLEDGE 승인 상태를 우회하지 않는다. approved KNOWLEDGE만 연결할 수 있다.
    - 연결은 브리프 승인과 별개다. 브리프 status는 바꾸지 않는다.
    - 바꾸는 것은 brief.knowledge_ids뿐이다. content_ids/media_generations(lineage)와 생성/MEDIA/성과 데이터는 그대로다.
    - rejected 브리프는 편집할 수 없다(editing.set_element와 같은 규칙).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from tak_brain.models import KnowledgeRecord

from .models import STATUS_APPROVED, STATUS_REJECTED, MarketingBrief


@dataclass(frozen=True)
class KnowledgeLinkCheck:
    brief_id: str
    knowledge_id: str
    brief_status: str
    exists: bool
    knowledge_status: str | None  # pending | approved | rejected, 없으면 None
    already_linked: bool
    blockers: tuple[str, ...]

    @property
    def approved(self) -> bool:
        return self.knowledge_status == "approved"

    @property
    def can_link(self) -> bool:
        return not self.blockers and not self.already_linked


@dataclass(frozen=True)
class KnowledgeUnlinkCheck:
    brief_id: str
    knowledge_id: str
    brief_status: str
    linked: bool
    remaining: tuple[str, ...]  # 제거 후 남는 knowledge_ids
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def can_unlink(self) -> bool:
        return not self.blockers


def _find(records: Sequence[KnowledgeRecord], knowledge_id: str) -> KnowledgeRecord | None:
    return next((record for record in records if record.id == knowledge_id), None)


def check_knowledge_link(
    brief: MarketingBrief, knowledge_id: str, records: Sequence[KnowledgeRecord]
) -> KnowledgeLinkCheck:
    record = _find(records, knowledge_id)
    status = record.knowledge_review_status if record is not None else None
    blockers = []
    if brief.status == STATUS_REJECTED:
        blockers.append("rejected 브리프에는 KNOWLEDGE를 연결할 수 없습니다.")
    if record is None:
        blockers.append(f"KNOWLEDGE를 찾을 수 없습니다: {knowledge_id}")
    elif status != "approved":
        blockers.append(f"approved KNOWLEDGE만 연결할 수 있습니다(현재 {status}). 기존 KNOWLEDGE 검토로 먼저 승인하세요.")
    return KnowledgeLinkCheck(
        brief_id=brief.brief_id, knowledge_id=knowledge_id, brief_status=brief.status, exists=record is not None,
        knowledge_status=status, already_linked=knowledge_id in brief.knowledge_ids, blockers=tuple(blockers),
    )


def check_knowledge_unlink(brief: MarketingBrief, knowledge_id: str) -> KnowledgeUnlinkCheck:
    linked = knowledge_id in brief.knowledge_ids
    remaining = tuple(kid for kid in brief.knowledge_ids if kid != knowledge_id)
    blockers, warnings = [], []
    if brief.status == STATUS_REJECTED:
        blockers.append("rejected 브리프는 편집할 수 없습니다.")
    if not linked:
        blockers.append(f"연결되어 있지 않은 KNOWLEDGE입니다: {knowledge_id}")
    if linked and not remaining:
        warnings.append("마지막 KNOWLEDGE를 제거합니다: 이후 이 브리프로는 generate/bridge가 차단됩니다"
                        "(이미 만든 후보/MEDIA/성과 데이터는 그대로 남습니다).")
    if linked and brief.status == STATUS_APPROVED:
        warnings.append("approved 브리프입니다: 브리프 승인 상태는 그대로 두고 KNOWLEDGE 연결만 바꿉니다.")
    if linked and brief.content_ids:
        warnings.append(f"이미 연결된 콘텐츠 {len(brief.content_ids)}건과 lineage는 변경하지 않습니다.")
    return KnowledgeUnlinkCheck(
        brief_id=brief.brief_id, knowledge_id=knowledge_id, brief_status=brief.status, linked=linked,
        remaining=remaining, blockers=tuple(blockers), warnings=tuple(warnings),
    )
