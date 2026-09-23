"""Recovery Decision Model - 6-22가 만든 REPORT 위에 사람이 검토할 수 있는
판정 단위(per-candidate decision)와 보고서 전체의 권고 행동(RECOVERY_ACTION)을
얹는 계층(6-23, docs/6-23-recovery-review-and-approval-gate.md).

파이프라인에서 이 모듈이 담당하는 범위:

    SOURCE -> STAGING -> VALIDATION -> RECONCILIATION -> REPORT   (6-22)
    REPORT -> HUMAN REVIEW -> EXPLICIT APPROVAL                    (이 모듈)
    -> APPLY                                                       (recovery_apply.py)

핵심 설계 결정(6-23 지시 3장 - 기존 project terminology와 충돌하지 않게):

    - ``content_engine.publish_audit``의 READY/NEEDS_HUMAN_REVIEW/BLOCKED/
      ALREADY_PUBLISHED/SUPERSEDED/ERROR는 "이 콘텐츠를 지금 바로 게시할 수
      있는가"를 답한다.
    - 이 모듈의 SAFE_TO_REVIEW/REVIEW_REQUIRED/BLOCKED/IDENTICAL/
      ALREADY_PRESENT/CONFLICT/INVALID는 "이 recovery 후보를 production
      archive에 반영해도 되는가"를 답한다. 완전히 다른 질문이므로 이름이
      겹치는 BLOCKED조차 서로 다른 판정 함수(다른 입력, 다른 목적)에서
      나온다 - 혼동을 피하기 위해 이 문서와 코드 어디에도 두 축을 섞어 쓰지
      않는다(docs/6-23 2장 참고).

이 모듈은 recovery 후보를 **분류만** 한다 - 파일을 읽거나 쓰지 않는다(순수
함수). 실제 파일 접근은 ``content_engine.recovery_staging``(6-22)이 이미
담당하고, 이 모듈은 그 결과(``GenerationPoolItem``,
``DownstreamReconciliationItem``, ``ArchiveValidationReport``)를 입력으로만
받는다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from . import recovery_staging as rs
from .data_state import CORRUPTED, VALID
from .media_archive import MediaArchiveRecord

# --- 3장: Recovery Decision Model(per-candidate, 6-23 지시 3장의 7개 그대로) --

SAFE_TO_REVIEW = "SAFE_TO_REVIEW"
REVIEW_REQUIRED = "REVIEW_REQUIRED"
BLOCKED = "BLOCKED"
IDENTICAL = "IDENTICAL"
ALREADY_PRESENT = "ALREADY_PRESENT"
CONFLICT = "CONFLICT"
INVALID = "INVALID"

DECISION_STATUSES = (
    SAFE_TO_REVIEW,
    REVIEW_REQUIRED,
    BLOCKED,
    IDENTICAL,
    ALREADY_PRESENT,
    CONFLICT,
    INVALID,
)

# "Potential actions"(6-23 지시 9장 Recovery Report 형식)
ADD = "ADD"
REPLACE = "REPLACE"
SKIP = "SKIP"
BLOCK = "BLOCK"

_STATUS_TO_DEFAULT_ACTION = {
    SAFE_TO_REVIEW: ADD,
    REVIEW_REQUIRED: SKIP,
    BLOCKED: BLOCK,
    IDENTICAL: SKIP,
    ALREADY_PRESENT: SKIP,
    CONFLICT: BLOCK,
    INVALID: SKIP,
}

# 보고서 전체 수준의 최종 권고(6-23 지시 9장). REVIEW_REQUIRED/BLOCKED는
# per-candidate 상태와 같은 문자열을 의도적으로 재사용한다(둘 다 "사람이
# 봐야 한다"/"막혔다"는 같은 의미를 층만 다르게 표현하는 것이므로 새 이름을
# 만들지 않았다).
NO_ACTION = "NO_ACTION"
READY_FOR_EXPLICIT_APPLY = "READY_FOR_EXPLICIT_APPLY"

RECOVERY_ACTIONS = (NO_ACTION, REVIEW_REQUIRED, BLOCKED, READY_FOR_EXPLICIT_APPLY)


@dataclass(frozen=True)
class RecoveryDecision:
    """generation pool 후보 1건(=하나의 ``(content_id, generation_id)``)에 대한
    판정. ``record``는 승인/적용 시 그대로 쓰일 원본 레코드를 들고 있다."""

    content_id: str
    generation_id: str | None
    status: str  # DECISION_STATUSES 중 하나
    action: str  # ADD/REPLACE/SKIP/BLOCK
    reasons: tuple[str, ...]
    record: MediaArchiveRecord | None
    source_file: str

    def to_dict(self) -> dict[str, object]:
        return {
            "content_id": self.content_id,
            "generation_id": self.generation_id,
            "status": self.status,
            "action": self.action,
            "reasons": list(self.reasons),
            "source_file": self.source_file,
        }


def _decide_generation_item(
    item: rs.GenerationPoolItem,
    *,
    target_active_record: MediaArchiveRecord | None,
    duplicate_pair: bool,
) -> RecoveryDecision:
    if duplicate_pair:
        return RecoveryDecision(
            content_id=item.content_id,
            generation_id=item.generation_id,
            status=INVALID,
            action=SKIP,
            reasons=(
                "같은 (content_id, generation_id) 조합이 generation pool 파일 안에 "
                "중복 존재합니다(I) - 어느 것이 진짜인지 코드가 판단할 수 없습니다.",
            ),
            record=None,
            source_file=str(item.file),
        )

    if item.comparison == "CONTENT_ID_CONFLICT":
        return RecoveryDecision(
            content_id=item.content_id,
            generation_id=item.generation_id,
            status=CONFLICT,
            action=BLOCK,
            reasons=(item.detail,),
            record=item.record,
            source_file=str(item.file),
        )

    if item.comparison == "SOURCE_URL_MISMATCH":
        return RecoveryDecision(
            content_id=item.content_id,
            generation_id=item.generation_id,
            status=CONFLICT,
            action=BLOCK,
            reasons=(item.detail,),
            record=item.record,
            source_file=str(item.file),
        )

    if item.comparison == "GENERATION_ONLY":
        return RecoveryDecision(
            content_id=item.content_id,
            generation_id=item.generation_id,
            status=SAFE_TO_REVIEW,
            action=ADD,
            reasons=("target production archive에 이 content_id가 없습니다 - 신규 추가 후보.",),
            record=item.record,
            source_file=str(item.file),
        )

    # PRODUCTION_MATCH: target에 이미 같은 generation_id로 존재
    if target_active_record is None:
        return RecoveryDecision(
            content_id=item.content_id,
            generation_id=item.generation_id,
            status=INVALID,
            action=SKIP,
            reasons=(
                "내부 불일치: PRODUCTION_MATCH로 판정됐지만 target archive에서 "
                "활성 레코드를 다시 찾을 수 없습니다.",
            ),
            record=item.record,
            source_file=str(item.file),
        )

    if target_active_record.review_status == "superseded" and item.record.review_status != "superseded":
        return RecoveryDecision(
            content_id=item.content_id,
            generation_id=item.generation_id,
            status=BLOCKED,
            action=BLOCK,
            reasons=(
                f"target production의 이 레코드는 이미 superseded 상태입니다"
                f"(superseded_by={target_active_record.superseded_by!r}) - recovery source가 "
                "같은 generation_id를 다시 올리면 superseded 상태가 조용히 되살아날 위험이 "
                "있어 차단합니다(resurrection 금지, 6-23 지시 11장).",
            ),
            record=item.record,
            source_file=str(item.file),
        )

    if item.record.to_dict() == target_active_record.to_dict():
        return RecoveryDecision(
            content_id=item.content_id,
            generation_id=item.generation_id,
            status=IDENTICAL,
            action=SKIP,
            reasons=("target production archive와 완전히 동일합니다 - 적용할 필요 없음.",),
            record=item.record,
            source_file=str(item.file),
        )

    diff_fields = [
        name
        for name in ("review_status", "edited_title", "edited_body")
        if getattr(item.record, name) != getattr(target_active_record, name)
    ]
    return RecoveryDecision(
        content_id=item.content_id,
        generation_id=item.generation_id,
        status=ALREADY_PRESENT,
        action=SKIP,
        reasons=(
            f"같은 generation_id({item.generation_id})로 이미 target production에 존재하지만 "
            f"다음 필드가 다릅니다: {', '.join(diff_fields) or '(세부 필드)'} - 확인만 하고 "
            "자동 반영하지 않습니다.",
        ),
        record=item.record,
        source_file=str(item.file),
    )


@dataclass(frozen=True)
class RecoveryReport:
    """6-22 REPORT(구조 검증/reconciliation)에 6-23 Recovery Decision을 얹은
    보고서. ``target_archive_path``는 실제로 적용될 production archive
    경로다 — ``source_dir``의 archive와는 별개다(recovery는 "다른 컴퓨터의
    복사본"과 "이 컴퓨터의 실제 production"을 비교하는 작업이므로)."""

    source_dir: Path
    target_archive_path: Path
    source_archive: rs.ArchiveValidationReport
    target_archive: rs.ArchiveValidationReport
    candidates: tuple[RecoveryDecision, ...]
    threads_items: tuple[rs.DownstreamReconciliationItem, ...]
    shorts_items: tuple[rs.DownstreamReconciliationItem, ...]
    source_sha256: dict[str, str | None]
    approved_content_ids: tuple[str, ...]
    action: str

    def to_dict(self) -> dict[str, object]:
        return {
            "source_dir": str(self.source_dir),
            "target_archive_path": str(self.target_archive_path),
            "source_archive": self.source_archive.to_dict(),
            "target_archive": self.target_archive.to_dict(),
            "candidates": [c.to_dict() for c in self.candidates],
            "threads": [i.to_dict() for i in self.threads_items],
            "shorts": [i.to_dict() for i in self.shorts_items],
            "source_sha256": self.source_sha256,
            "approved_content_ids": list(self.approved_content_ids),
            "action": self.action,
        }

    def summary_counts(self) -> dict[str, int]:
        counts = {status: 0 for status in DECISION_STATUSES}
        for candidate in self.candidates:
            counts[candidate.status] += 1
        return counts


def build_recovery_report(
    source_dir: Path | str,
    target_archive_path: Path | str,
    *,
    approved_content_ids: Sequence[str] = (),
) -> RecoveryReport:
    """``source_dir``(예: 다른 PC에서 복사해 온 백업)를 ``target_archive_path``
    (실제로 반영될 production archive)와 비교해 사람이 검토할 보고서를
    만든다. 어떤 파일도 쓰지 않는다.

    ``source_dir``와 ``target_archive_path``를 둘 다 호출부가 명시적으로
    줘야 한다 - 어느 쪽도 ``data/`` 운영 디렉터리를 기본값으로 쓰지 않는다
    (6-22와 동일한 원칙).

    ``approved_content_ids``는 이 REPORT 자체가 무언가를 승인한다는 뜻이
    아니다(이 함수는 여전히 순수 조회다) - 오직 최종 ``action`` 필드가
    ``READY_FOR_EXPLICIT_APPLY``를 반환할 수 있는지 판단하는 데만 쓰인다.
    "Recovery는 자동 복구가 아니라 사람이 확인한 뒤 명시적으로 승인하는
    작업"이라는 원칙(6-23 지시 0장)에 따라, 아무것도 승인되지 않은 상태의
    보고서는 (완전히 깨끗해 보여도) ``READY_FOR_EXPLICIT_APPLY``를 절대
    반환하지 않는다 — 최선의 경우에도 ``REVIEW_REQUIRED``에 머문다.
    """
    root = Path(source_dir)
    target_path = Path(target_archive_path)

    inventory = rs.discover_source(root)
    source_archive_report = rs.validate_production_archive(inventory.archive.path)
    target_archive_report = rs.validate_production_archive(target_path)

    target_by_content_id = {record.content_id: record for record in target_archive_report.records}

    candidates: list[RecoveryDecision] = []
    for gen_file in inventory.generation_pool_files:
        items, issues = rs.validate_generation_pool_file(gen_file.path, target_archive_report.records)

        # I(중복) 이슈는 (content_id, generation_id) 쌍 단위이지만, 더
        # 신뢰할 수 있는 판정 방법은 content_id별 item 개수를 직접 세는
        # 것이다(같은 content_id가 이 파일에서 item으로 두 번 이상 나오면
        # 그 자체가 이미 이상 신호 - I 이슈와 사실상 같은 조건이다).
        content_id_counts: dict[str, int] = {}
        for item in items:
            content_id_counts[item.content_id] = content_id_counts.get(item.content_id, 0) + 1

        for item in items:
            is_duplicate = content_id_counts[item.content_id] > 1
            candidates.append(
                _decide_generation_item(
                    item,
                    target_active_record=target_by_content_id.get(item.content_id),
                    duplicate_pair=is_duplicate,
                )
            )

        # 파싱 자체가 실패한 레코드(schema error)는 GenerationPoolItem이 아예
        # 만들어지지 않으므로, 별도로 INVALID 후보를 추가해 "이 파일에 문제가
        # 있다"는 사실이 후보 목록에서 누락되지 않게 한다.
        for issue in issues:
            if issue.code == "I_DUPLICATE_CONTENT_GENERATION_PAIR":
                continue
            candidates.append(
                RecoveryDecision(
                    content_id=issue.content_id or "(알 수 없음)",
                    generation_id=None,
                    status=INVALID,
                    action=SKIP,
                    reasons=(issue.message,),
                    record=None,
                    source_file=str(gen_file.path),
                )
            )

    threads_items = tuple(rs.reconcile_threads_pending(inventory.threads_pending.path, target_archive_report.records))
    shorts_items = tuple(rs.reconcile_shorts_scripts(inventory.shorts_scripts.path, target_archive_report.records))

    # SAFE_TO_REVIEW 후보라도, 같은 content_id를 가리키는 downstream
    # artifact가 이미 SUPERSEDED 상태이거나 필드가 어긋나 있으면(6-23 지시
    # 12장 "old superseded content가 downstream artifact에 남아 있는 경우") 더
    # 신중히 봐야 하므로 REVIEW_REQUIRED로 승격한다 - action은 여전히 ADD가
    # 아니라 사람이 먼저 확인하라는 뜻에서 SKIP으로 바꾼다(승인 목록에 넣기
    # 전에 downstream 상황부터 봐야 한다는 신호).
    downstream_by_content_id: dict[str, list[rs.DownstreamReconciliationItem]] = {}
    for item in (*threads_items, *shorts_items):
        if item.content_id:
            downstream_by_content_id.setdefault(item.content_id, []).append(item)

    upgraded_candidates: list[RecoveryDecision] = []
    for candidate in candidates:
        related = downstream_by_content_id.get(candidate.content_id, [])
        needs_escalation = candidate.status == SAFE_TO_REVIEW and any(
            d.status == rs.SUPERSEDED or d.field_consistency == rs.MISMATCH for d in related
        )
        if needs_escalation:
            extra_reasons = tuple(
                f"downstream({d.artifact_type}) 상태={d.status}, field_consistency={d.field_consistency}"
                for d in related
                if d.status == rs.SUPERSEDED or d.field_consistency == rs.MISMATCH
            )
            upgraded_candidates.append(
                RecoveryDecision(
                    content_id=candidate.content_id,
                    generation_id=candidate.generation_id,
                    status=REVIEW_REQUIRED,
                    action=SKIP,
                    reasons=candidate.reasons + extra_reasons,
                    record=candidate.record,
                    source_file=candidate.source_file,
                )
            )
        else:
            upgraded_candidates.append(candidate)
    candidates = upgraded_candidates

    source_sha256 = {
        "archive": inventory.archive.sha256,
        "threads_pending": inventory.threads_pending.sha256,
        "knowledge": inventory.knowledge.sha256,
        **{gen_file.name: gen_file.sha256 for gen_file in inventory.generation_pool_files},
    }

    action = _determine_recovery_action(
        source_archive_report,
        target_archive_report,
        candidates,
        threads_items,
        shorts_items,
        approved_content_ids,
    )

    return RecoveryReport(
        source_dir=root,
        target_archive_path=target_path,
        source_archive=source_archive_report,
        target_archive=target_archive_report,
        candidates=tuple(candidates),
        threads_items=threads_items,
        shorts_items=shorts_items,
        source_sha256=source_sha256,
        approved_content_ids=tuple(dict.fromkeys(approved_content_ids)),
        action=action,
    )


def _determine_recovery_action(
    source_archive_report: rs.ArchiveValidationReport,
    target_archive_report: rs.ArchiveValidationReport,
    candidates: Sequence[RecoveryDecision],
    threads_items: Sequence[rs.DownstreamReconciliationItem],
    shorts_items: Sequence[rs.DownstreamReconciliationItem],
    approved_content_ids: Sequence[str],
) -> str:
    """보고서 전체 수준의 권고(6-23 지시 9장 RECOVERY_ACTION).

    ``READY_FOR_EXPLICIT_APPLY``는 오직 ``approved_content_ids``가 실제로
    주어졌고, 그 각각이 ``SAFE_TO_REVIEW`` 후보와 모호함 없이 대응할 때만
    나온다 — "아무도 승인하지 않았지만 구조적으로 깨끗해 보이는" 상태는
    ``READY_FOR_EXPLICIT_APPLY``가 아니라 ``REVIEW_REQUIRED``다(5장/0장
    "자동 approval 금지, Recovery는 사람이 명시적으로 승인하는 작업" 원칙 -
    보고서 자체가 "이건 승인해도 안전해 보인다"고 미리 판단해 버리면 그
    원칙이 깨진다).
    """
    if source_archive_report.status == CORRUPTED or target_archive_report.status == CORRUPTED:
        return BLOCKED

    blocking_candidates = [c for c in candidates if c.status in (CONFLICT, BLOCKED, INVALID)]
    if blocking_candidates or source_archive_report.issues:
        return BLOCKED

    if not candidates:
        return NO_ACTION

    downstream_conflicts = [
        item
        for item in (*threads_items, *shorts_items)
        if item.status == rs.CONTENT_ID_CONFLICT or item.status == rs.INVALID
    ]
    if downstream_conflicts:
        return REVIEW_REQUIRED

    if not approved_content_ids:
        return REVIEW_REQUIRED

    candidates_by_content_id: dict[str, list[RecoveryDecision]] = {}
    for candidate in candidates:
        candidates_by_content_id.setdefault(candidate.content_id, []).append(candidate)

    for content_id in approved_content_ids:
        matches = candidates_by_content_id.get(content_id)
        if not matches or len(matches) != 1 or matches[0].status != SAFE_TO_REVIEW:
            return REVIEW_REQUIRED

    return READY_FOR_EXPLICIT_APPLY


def render_recovery_report_text(report: RecoveryReport) -> str:
    """6-23 지시 9장 예시 형식과 같은 사람이 읽는 보고서. 파일을 쓰지 않는다."""
    counts = report.summary_counts()
    lines = [
        "Recovery Report",
        "",
        "Source:",
        str(report.source_dir),
        "SHA256(archive):",
        report.source_sha256.get("archive") or "(N/A)",
        "",
        "Archive:",
        f"record count: {report.source_archive.record_count}",
        f"status: {report.source_archive.status}",
        "",
        "Generation:",
        f"record count: {len(report.candidates)}",
        f"status: {'VALID' if not any(c.status == INVALID for c in report.candidates) else 'HAS_INVALID'}",
        "",
        "Downstream:",
        f"Threads: {len(report.threads_items)}",
        f"Shorts: {len(report.shorts_items)}",
        "Blog: 0 (이 코드베이스는 blog_drafts/를 생성하지 않음)",
        "",
        "Reconciliation:",
        f"IDENTICAL: {counts[IDENTICAL]}",
        f"NEW: {counts[SAFE_TO_REVIEW]}",
        f"CONFLICT: {counts[CONFLICT]}",
        f"BLOCKED: {counts[BLOCKED]}",
        f"INVALID: {counts[INVALID]}",
        f"SUPERSEDED: {sum(1 for i in (*report.threads_items, *report.shorts_items) if i.status == rs.SUPERSEDED)}",
        "",
        "Potential actions:",
        f"ADD: {sum(1 for c in report.candidates if c.action == ADD)}",
        f"REPLACE: {sum(1 for c in report.candidates if c.action == REPLACE)}",
        f"SKIP: {sum(1 for c in report.candidates if c.action == SKIP)}",
        f"BLOCK: {sum(1 for c in report.candidates if c.action == BLOCK)}",
        "",
        "Approval:",
        ("NOT_APPROVED" if not report.approved_content_ids else f"APPROVED: {', '.join(report.approved_content_ids)}"),
        "",
        "RECOVERY_ACTION:",
        report.action,
    ]
    return "\n".join(lines)
