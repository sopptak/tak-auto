"""Operator Control Center(6-38) - 10월 1일 실제 운영자가 한 화면에서 볼 수
있는 통합 관제판의 순수 집계 로직.

이 모듈은 **새 판정 로직을 만들지 않는다** - 6-14/6-17/6-19(publish_audit),
6-21(data_state), 6-26(YouTube eligibility), 6-33(show_operating_status),
6-37(media_strategy), 6-35/6-36(performance_insight/insight_report)이 이미
계산한 상태를 그대로 모아서 한 화면 분량으로 요약만 한다. 파일을 읽거나
쓰지 않는 순수 함수다 - 호출부(``scripts/operator_control_center.py``,
Dashboard route)가 각 저장소를 미리 로드해 ``OperatorInputs``로 넘긴다
(``content_engine.publish_audit.PublishAuditInputs``와 동일한 관례).

절대 원칙:
    - 이 모듈은 approve/dismiss/promote/publish/delete/restore/repair/
      regenerate 중 어떤 것도 실행하지 않는다(쓰기 함수를 import하지 않음).
    - 없는 운영 데이터를 있는 것처럼 만들지 않는다 - 파일이 없으면
      ``NOT_PRESENT``를 그대로 보여준다.
    - 플랫폼 간 순위를 만들지 않는다(Publish Status는 플랫폼별 독립 표시).
    - "다음 행동"은 최대 3개까지만, 우선순위 계산은 기존 상태 체계(Human
      Review/Blocked)만 재사용한다 - 새 점수 시스템을 만들지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from content_engine.data_state import CORRUPTED, EMPTY, NOT_PRESENT, VALID
from content_engine.insight_report import (
    PRIORITY_INCOMPARABLE,
    PRIORITY_INSUFFICIENT_DATA,
    PRIORITY_INVALID,
    PRIORITY_NEW,
    PRIORITY_REVIEWED,
    review_priority,
)
from content_engine.media_archive import MediaArchiveRecord
from content_engine.media_strategy import (
    PLATFORMS as STRATEGY_PLATFORMS,
    STRATEGY_BLOCKED,
    STRATEGY_READY,
    evaluate_media_strategy,
)
from content_engine.performance.models import PerformanceRecord
from content_engine.performance_insight import InsightRecord, STATUS_CANDIDATE
from content_engine.recovery_decision import (
    CONFLICT as RECOVERY_CONFLICT,
    REVIEW_REQUIRED as RECOVERY_REVIEW_REQUIRED,
)
from content_engine.publish_audit import (
    ALREADY_PUBLISHED,
    BLOCKED as PUBLISH_BLOCKED,
    ERROR as PUBLISH_ERROR,
    NEEDS_HUMAN_REVIEW,
    READY as PUBLISH_READY,
    SUPERSEDED,
    PublishAuditInputs,
    audit_archive,
)
from content_engine.threads_review import ThreadsPendingDraft
from tak_brain.models import KnowledgeRecord

# --- 13장: 전체 시스템 상태(기존 상태가 없으므로 이번에 최소 규칙만 정의) -------
# 6-28/6-29/6-31/6-33 문서가 반복적으로 써 온 상태 어휘를 그대로 재사용한다 -
# 새 이름을 만들지 않았다.

SYSTEM_READY = "READY"
SYSTEM_READY_WITH_HUMAN_STEP = "READY_WITH_HUMAN_STEP"
SYSTEM_NEEDS_REVIEW = "NEEDS_REVIEW"
SYSTEM_BLOCKED = "BLOCKED"
SYSTEM_EXTERNAL_DEPENDENCY = "EXTERNAL_DEPENDENCY"
SYSTEM_NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
SYSTEM_ERROR = "ERROR"

_SYSTEM_STATUS_PRIORITY = {
    SYSTEM_ERROR: 0,
    SYSTEM_BLOCKED: 1,
    SYSTEM_NEEDS_REVIEW: 2,
    SYSTEM_EXTERNAL_DEPENDENCY: 3,
    SYSTEM_READY_WITH_HUMAN_STEP: 4,
    SYSTEM_NOT_IMPLEMENTED: 5,
    SYSTEM_READY: 6,
}

TEST_PASS = "PASS"
TEST_FAIL = "FAIL"
TEST_UNKNOWN = "UNKNOWN"

# --- 6-39: RECOVERY 상태(정상/검토 필요/충돌/복구 필요, STATE A/B/C 구분) ----------
# CONFLICT/REVIEW_REQUIRED는 6-23 recovery_decision의 기존 7개 상태를 그대로
# 재사용한다(위에서 import) - 새로 만든 것은 "이 PC에서 git 이력상 존재했어야
# 할 데이터가 지금 없다"는, 기존 어디에도 없던 개념 하나(RECOVERY_REQUIRED)뿐이다.
RECOVERY_NOT_REQUIRED = "NOT_REQUIRED"
RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
RECOVERY_UNVERIFIED = "UNVERIFIED"


# --- 12장: STATUS -> WHY -> ACTION 공통 구조 -------------------------------------


@dataclass(frozen=True)
class StatusWhyAction:
    """모든 주요 상태가 공유하는 3단 구조(12장). ``detail_route``는 클릭 시
    이동할 기존 상세 화면 경로(15장 Detail Navigation) - 새 상세 화면을
    만들지 않고 기존 경로만 연결한다."""

    label: str
    status: str
    why: str = ""
    action: str = ""
    count: int | None = None
    detail_route: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "status": self.status,
            "why": self.why,
            "action": self.action,
            "count": self.count,
            "detail_route": self.detail_route,
        }


# --- 21/22장: 입력/출력 스키마 -----------------------------------------------------


@dataclass(frozen=True)
class OperatorInputs:
    """Operator Center가 필요로 하는 모든 미리 로드된 데이터(순수 값만) -
    이 클래스 자체는 파일을 읽지 않는다. ``None``은 "파일이 없어서 알 수
    없음"을 의미하고, 빈 튜플/컬렉션은 "파일은 있지만 레코드가 0건"을
    의미한다(6-21 NOT_PRESENT vs EMPTY 구분과 동일한 원칙)."""

    generated_at: str
    git_head: str = ""
    git_origin_main: str = ""
    git_working_tree_clean: bool | None = None
    test_status: str = TEST_UNKNOWN

    scout_candidate_count: int | None = None

    knowledge_status: str = NOT_PRESENT
    knowledge_records: tuple[KnowledgeRecord, ...] = ()

    generation_pool_found: bool = False
    generation_pool_records: tuple[MediaArchiveRecord, ...] = ()

    production_archive_status: str = NOT_PRESENT
    production_records: tuple[MediaArchiveRecord, ...] = ()
    # 6-39: git 이력에 이 파일이 커밋된 적이 있는지(호출부가 ``git log --all``로
    # 확인해서 넘긴다 - 이 모듈은 git을 호출하지 않는다). None=UNVERIFIED(확인
    # 불가), False=STATE A(정상, 한 번도 커밋된 적 없음), True=STATE B(커밋된
    # 적 있는데 지금 이 PC에는 없음 - 사람이 복구 여부를 확인해야 함).
    production_archive_ever_tracked: bool | None = None
    # 6-22 ``recovery_staging.validate_production_archive()``가 이미 계산하는
    # A~M 무결성 이슈 개수(호출부가 재사용해서 넘긴다 - 새 검증 로직 없음).
    production_archive_issue_count: int = 0

    threads_pending_status: str = NOT_PRESENT
    threads_pending: tuple[ThreadsPendingDraft, ...] = ()

    performance_status: str = NOT_PRESENT
    performance_records: tuple[PerformanceRecord, ...] = ()

    insight_status: str = NOT_PRESENT
    insight_records: tuple[InsightRecord, ...] = ()

    shorts_scripts_status: str = NOT_PRESENT
    blog_drafts_status: str = NOT_PRESENT

    threads_token_present: bool = False
    youtube_credentials_present: bool = False
    youtube_renderer_available: bool = False  # 6-40부터 content_engine/shorts_renderer.py 존재 -> 실제 실행에서는 True


@dataclass(frozen=True)
class OperatorSummary:
    system_status: str
    generated_at: str
    git_status: StatusWhyAction
    test_status: StatusWhyAction
    pipeline: tuple[StatusWhyAction, ...] = field(default_factory=tuple)
    human_actions: tuple[StatusWhyAction, ...] = field(default_factory=tuple)
    blocked_items: tuple[StatusWhyAction, ...] = field(default_factory=tuple)
    publish_status: tuple[StatusWhyAction, ...] = field(default_factory=tuple)
    data_health: tuple[StatusWhyAction, ...] = field(default_factory=tuple)
    performance: StatusWhyAction = None  # type: ignore[assignment]
    insights: StatusWhyAction = None  # type: ignore[assignment]
    recovery: StatusWhyAction = None  # type: ignore[assignment]
    next_actions: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "system_status": self.system_status,
            "generated_at": self.generated_at,
            "git_status": self.git_status.to_dict(),
            "test_status": self.test_status.to_dict(),
            "pipeline": [item.to_dict() for item in self.pipeline],
            "human_actions": [item.to_dict() for item in self.human_actions],
            "blocked_items": [item.to_dict() for item in self.blocked_items],
            "publish_status": [item.to_dict() for item in self.publish_status],
            "data_health": [item.to_dict() for item in self.data_health],
            "performance": self.performance.to_dict(),
            "insights": self.insights.to_dict(),
            "recovery": self.recovery.to_dict(),
            "next_actions": list(self.next_actions),
        }


# --- 4장: TODAY STATUS(Git/Test) -------------------------------------------------


def _build_git_status(inputs: OperatorInputs) -> StatusWhyAction:
    if not inputs.git_head or not inputs.git_origin_main:
        return StatusWhyAction(label="GIT", status="UNKNOWN", why="git 정보를 확인할 수 없습니다.", action="git status로 직접 확인하세요.")
    synced = inputs.git_head == inputs.git_origin_main
    clean = inputs.git_working_tree_clean
    if synced and clean:
        return StatusWhyAction(label="GIT", status="SYNCED", why=f"HEAD={inputs.git_head[:8]}", action="")
    if not synced:
        return StatusWhyAction(
            label="GIT", status="OUT_OF_SYNC",
            why=f"HEAD({inputs.git_head[:8]}) != origin/main({inputs.git_origin_main[:8]})",
            action="git fetch origin main && git status로 원인을 조사하세요(임의로 삭제하지 마세요).",
        )
    return StatusWhyAction(label="GIT", status="DIRTY", why="working tree에 커밋되지 않은 변경사항이 있습니다.", action="git status --short로 확인하세요.")


def _build_test_status(inputs: OperatorInputs) -> StatusWhyAction:
    if inputs.test_status == TEST_PASS:
        return StatusWhyAction(label="TEST", status=TEST_PASS, why="", action="")
    if inputs.test_status == TEST_FAIL:
        return StatusWhyAction(label="TEST", status=TEST_FAIL, why="최근 테스트 실행이 실패했습니다.", action="python -m unittest discover -s tests -p \"test_*.py\"로 원인을 확인하세요.")
    return StatusWhyAction(label="TEST", status=TEST_UNKNOWN, why="이번 실행에서 테스트를 수행하지 않았습니다.", action="python -m unittest discover -s tests -p \"test_*.py\"를 실행하세요.")


# --- 5장: PIPELINE STATUS ----------------------------------------------------------


def _build_scout_stage(inputs: OperatorInputs) -> StatusWhyAction:
    if inputs.scout_candidate_count is None:
        return StatusWhyAction(label="SCOUT", status=NOT_PRESENT, why="오늘 SCOUT를 아직 실행하지 않았습니다.", action="python scripts/run_scout.py", detail_route="/")
    return StatusWhyAction(label="SCOUT", status=PUBLISH_READY, count=inputs.scout_candidate_count, detail_route="/")


def _build_knowledge_stage(inputs: OperatorInputs) -> StatusWhyAction:
    if inputs.knowledge_status == NOT_PRESENT:
        return StatusWhyAction(label="KNOWLEDGE", status=NOT_PRESENT, why="KNOWLEDGE 파일이 없습니다.", action="")
    pending = [r for r in inputs.knowledge_records if r.knowledge_review_status == "pending"]
    if pending:
        return StatusWhyAction(
            label="KNOWLEDGE", status=NEEDS_HUMAN_REVIEW, count=len(pending),
            why="승인 대기 중인 KNOWLEDGE가 있습니다.",
            action="python scripts/review_knowledge.py --pending",
        )
    return StatusWhyAction(label="KNOWLEDGE", status=PUBLISH_READY, count=len(inputs.knowledge_records))


def _build_media_stage(inputs: OperatorInputs) -> StatusWhyAction:
    if not inputs.generation_pool_found:
        return StatusWhyAction(label="MEDIA", status=NOT_PRESENT, why="아직 MEDIA generation이 없습니다.", action="python scripts/run_media_batch.py --execute --as-generation", detail_route="/media/generations")
    total = len(inputs.generation_pool_records)
    return StatusWhyAction(label="MEDIA", status=PUBLISH_READY, count=total, detail_route="/media/generations")


def _build_human_review_stage(inputs: OperatorInputs) -> StatusWhyAction:
    unreviewed = [r for r in inputs.generation_pool_records if r.review_status == "unreviewed"]
    if unreviewed:
        return StatusWhyAction(
            label="HUMAN REVIEW", status="WAITING", count=len(unreviewed),
            why="검토 대기 중인 MEDIA generation이 있습니다.",
            action="Dashboard /media/generations에서 검토하세요.", detail_route="/media/generations",
        )
    return StatusWhyAction(label="HUMAN REVIEW", status=PUBLISH_READY, count=0, detail_route="/media/generations")


def _promotable_records(inputs: OperatorInputs) -> list[MediaArchiveRecord]:
    active_keys = {(r.content_id, r.generation_id) for r in inputs.production_records}
    return [
        r for r in inputs.generation_pool_records
        if r.review_status == "approved" and r.generation_status == "valid" and (r.content_id, r.generation_id) not in active_keys
    ]


def _build_promotion_stage(inputs: OperatorInputs) -> StatusWhyAction:
    promotable = _promotable_records(inputs)
    if promotable:
        return StatusWhyAction(
            label="PROMOTION", status=PUBLISH_READY, count=len(promotable),
            why="승인됐지만 아직 Production Archive에 반영되지 않은 항목이 있습니다.",
            action="python scripts/promote_media_generation.py --execute", detail_route="/media/generations",
        )
    return StatusWhyAction(label="PROMOTION", status=PUBLISH_READY, count=0)


def _build_production_stage(inputs: OperatorInputs) -> StatusWhyAction:
    return StatusWhyAction(
        label="PRODUCTION ARCHIVE", status=inputs.production_archive_status,
        count=len(inputs.production_records) if inputs.production_archive_status == VALID else None,
        why="아직 Production Archive가 없습니다(정상)." if inputs.production_archive_status == NOT_PRESENT else "",
    )


def _build_publish_stage(inputs: OperatorInputs, knowledge_by_id: dict[str, KnowledgeRecord]) -> StatusWhyAction:
    if not inputs.production_records:
        return StatusWhyAction(label="PUBLISH", status=NOT_PRESENT, why="게시 후보가 없습니다.")
    results = audit_archive(list(inputs.production_records), inputs=PublishAuditInputs(knowledge_by_id=knowledge_by_id))
    ready_count = sum(1 for r in results if r.status == PUBLISH_READY)
    action_count = sum(1 for r in results if r.status in (NEEDS_HUMAN_REVIEW, PUBLISH_BLOCKED))
    if action_count:
        return StatusWhyAction(label="PUBLISH", status="ACTION_REQUIRED", count=action_count, why="사람 확인이 필요한 게시 후보가 있습니다.", action="python scripts/audit_publish_candidates.py", detail_route="/publish-readiness")
    if ready_count:
        return StatusWhyAction(label="PUBLISH", status=PUBLISH_READY, count=ready_count, detail_route="/publish-readiness")
    return StatusWhyAction(label="PUBLISH", status=NOT_PRESENT, count=0, detail_route="/publish-readiness")


def _build_performance_stage(inputs: OperatorInputs) -> StatusWhyAction:
    if inputs.performance_status == NOT_PRESENT:
        return StatusWhyAction(label="PERFORMANCE", status=NOT_PRESENT, why="아직 수집된 성과 데이터가 없습니다.", action="python scripts/collect_performance.py", detail_route="/performance")
    return StatusWhyAction(label="PERFORMANCE", status=VALID, count=len(inputs.performance_records), detail_route="/performance")


def _build_insight_stage(inputs: OperatorInputs) -> StatusWhyAction:
    if inputs.insight_status == NOT_PRESENT:
        return StatusWhyAction(label="INSIGHT", status=NOT_PRESENT, why="아직 계산된 Insight가 없습니다.", action="python scripts/analyze_performance.py", detail_route="/performance/insights")
    review_needed = sum(1 for i in inputs.insight_records if review_priority(i) in (PRIORITY_NEW, PRIORITY_INSUFFICIENT_DATA, PRIORITY_INCOMPARABLE, PRIORITY_INVALID))
    if review_needed:
        return StatusWhyAction(label="INSIGHT", status=NEEDS_HUMAN_REVIEW, count=review_needed, why="검토가 필요한 Insight가 있습니다.", detail_route="/performance/insights")
    return StatusWhyAction(label="INSIGHT", status=PUBLISH_READY, count=len(inputs.insight_records), detail_route="/performance/insights")


def build_pipeline(inputs: OperatorInputs, knowledge_by_id: dict[str, KnowledgeRecord]) -> tuple[StatusWhyAction, ...]:
    """5장: SCOUT -> KNOWLEDGE -> MEDIA -> HUMAN REVIEW -> PROMOTION ->
    PRODUCTION -> PUBLISH -> PERFORMANCE -> INSIGHT 9단계 전부."""
    return (
        _build_scout_stage(inputs),
        _build_knowledge_stage(inputs),
        _build_media_stage(inputs),
        _build_human_review_stage(inputs),
        _build_promotion_stage(inputs),
        _build_production_stage(inputs),
        _build_publish_stage(inputs, knowledge_by_id),
        _build_performance_stage(inputs),
        _build_insight_stage(inputs),
    )


# --- 6장: HUMAN ACTION -------------------------------------------------------------


def build_human_actions(inputs: OperatorInputs) -> tuple[StatusWhyAction, ...]:
    """AI가 자동으로 해결할 수 없는 작업만 모은다 - 자동 실행 버튼은
    만들지 않는다(action 필드는 CLI 명령 안내 문자열일 뿐이다)."""
    actions: list[StatusWhyAction] = []

    pending_knowledge = [r for r in inputs.knowledge_records if r.knowledge_review_status == "pending"]
    if pending_knowledge:
        actions.append(StatusWhyAction(
            label="KNOWLEDGE REVIEW", status="ACTION_REQUIRED", count=len(pending_knowledge),
            why="승인 대기 중인 KNOWLEDGE가 있습니다.", action="python scripts/review_knowledge.py --pending", detail_route="/",
        ))

    unreviewed_media = [r for r in inputs.generation_pool_records if r.review_status == "unreviewed"]
    if unreviewed_media:
        actions.append(StatusWhyAction(
            label="MEDIA REVIEW", status="ACTION_REQUIRED", count=len(unreviewed_media),
            why="검토 대기 중인 MEDIA generation이 있습니다.", action="Dashboard /media/generations", detail_route="/media/generations",
        ))

    promotable = _promotable_records(inputs)
    if promotable:
        actions.append(StatusWhyAction(
            label="PROMOTION APPROVAL", status="ACTION_REQUIRED", count=len(promotable),
            why="승인됐지만 아직 Production Archive에 반영되지 않았습니다.",
            action="python scripts/promote_media_generation.py --execute", detail_route="/media/generations",
        ))

    pending_threads = [d for d in inputs.threads_pending if d.status == "pending"]
    if pending_threads:
        actions.append(StatusWhyAction(
            label="THREADS PUBLISH", status="ACTION_REQUIRED", count=len(pending_threads),
            why="검수 대기 중인 Threads 초안이 있습니다.", action="Dashboard /threads", detail_route="/threads",
        ))

    if not inputs.youtube_renderer_available:
        actions.append(StatusWhyAction(
            label="YOUTUBE OAUTH", status="ACTION_REQUIRED",
            why="Shorts Renderer가 아직 없습니다(docs/6-30 참고).",
            action="노트북1/Codespaces에서 renderer 확보 여부를 사람이 직접 확인하세요.",
        ))
    elif not inputs.youtube_credentials_present:
        actions.append(StatusWhyAction(
            label="YOUTUBE OAUTH", status="ACTION_REQUIRED",
            why="YouTube OAuth 환경변수가 설정되지 않았습니다.",
            action="python scripts/youtube_oauth_setup.py --check",
        ))

    approved_blog = sum(1 for r in inputs.production_records if r.platform == "blog" and r.review_status == "approved")
    if approved_blog:
        actions.append(StatusWhyAction(
            label="NAVER MANUAL PUBLISH", status="ACTION_REQUIRED", count=approved_blog,
            why="승인된 Blog 후보가 있습니다(자동 게시 없음, 의도된 설계).",
            action="python scripts/generate_blog_publish_pack.py --from-archive",
        ))

    return tuple(actions)


# --- 7장: BLOCKED / RISK ------------------------------------------------------------


def build_blocked_items(inputs: OperatorInputs) -> tuple[StatusWhyAction, ...]:
    """실제로 막혀 있는 것만 표시한다 - 경고를 많이 만드는 것이 목적이
    아니다."""
    blocked: list[StatusWhyAction] = []

    if not inputs.youtube_renderer_available:
        blocked.append(StatusWhyAction(
            label="YouTube", status="BLOCKED", why="Shorts Renderer 없음(EXTERNAL_MACHINE_REQUIRED, docs/6-30)",
            action="노트북1/Codespaces 확인 필요(이 세션에서는 접근 불가)",
        ))

    review_required_knowledge = [
        evaluate_media_strategy(r, production_records=list(inputs.production_records), other_knowledge=list(inputs.knowledge_records))
        for r in inputs.knowledge_records if r.knowledge_review_status == "approved"
    ]
    for candidate in review_required_knowledge:
        if candidate.status not in (STRATEGY_READY, STRATEGY_BLOCKED):
            blocked.append(StatusWhyAction(
                label=f"KNOWLEDGE {candidate.knowledge_id}", status=candidate.status,
                why=", ".join(candidate.reason_codes) or "전략 검토 필요",
                action="python scripts/audit_media_strategy.py", detail_route="/media/strategy",
            ))

    return tuple(blocked)


# --- 8장: PUBLISH STATUS(플랫폼 독립, 순위 없음) -----------------------------------


def build_publish_status(inputs: OperatorInputs, knowledge_by_id: dict[str, KnowledgeRecord]) -> tuple[StatusWhyAction, ...]:
    results = ()
    if inputs.production_records:
        results = audit_archive(list(inputs.production_records), inputs=PublishAuditInputs(knowledge_by_id=knowledge_by_id))

    def _platform_summary(platform_records) -> str:
        if not platform_records:
            return NOT_PRESENT
        statuses = {r.status for r in platform_records}
        if PUBLISH_ERROR in statuses:
            return PUBLISH_ERROR
        if ALREADY_PUBLISHED in statuses:
            return ALREADY_PUBLISHED
        if SUPERSEDED in statuses:
            return SUPERSEDED
        if PUBLISH_BLOCKED in statuses:
            return PUBLISH_BLOCKED
        if NEEDS_HUMAN_REVIEW in statuses:
            return NEEDS_HUMAN_REVIEW
        return PUBLISH_READY

    threads_records = [r for r in results if r.platform == "threads"]
    blog_records = [r for r in results if r.platform == "blog"]
    shorts_records = [r for r in results if r.platform == "shorts"]

    return (
        StatusWhyAction(label="Threads", status=_platform_summary(threads_records), count=len(threads_records) or None, detail_route="/threads"),
        StatusWhyAction(label="Blog", status=_platform_summary(blog_records), count=len(blog_records) or None, action="Naver 수동 게시(자동화 없음)"),
        StatusWhyAction(
            label="YouTube Shorts",
            status="BLOCKED" if not inputs.youtube_renderer_available else _platform_summary(shorts_records),
            count=len(shorts_records) or None,
            why="" if inputs.youtube_renderer_available else "Shorts Renderer 없음(docs/6-30)",
        ),
    )


# --- 9장: DATA HEALTH ----------------------------------------------------------------


def build_data_health(inputs: OperatorInputs) -> tuple[StatusWhyAction, ...]:
    def _row(label: str, status: str) -> StatusWhyAction:
        why = "파일이 없습니다(정상 - 임의로 만들지 않습니다)." if status == NOT_PRESENT else ""
        why = "파일 파싱에 실패했습니다." if status == CORRUPTED else why
        return StatusWhyAction(label=label, status=status, why=why)

    return (
        _row("Production Archive", inputs.production_archive_status),
        _row("Generation Pool", VALID if inputs.generation_pool_found else NOT_PRESENT),
        _row("KNOWLEDGE", inputs.knowledge_status),
        _row("Threads Pending", inputs.threads_pending_status),
        _row("Shorts Scripts", inputs.shorts_scripts_status),
        _row("Blog Drafts", inputs.blog_drafts_status),
        _row("Performance", inputs.performance_status),
        _row("Insight", inputs.insight_status),
    )


# --- 10장: PERFORMANCE / INSIGHT 요약(단독 필드) -----------------------------------


def build_performance_summary(inputs: OperatorInputs) -> StatusWhyAction:
    if inputs.performance_status == NOT_PRESENT:
        return StatusWhyAction(label="PERFORMANCE", status=NOT_PRESENT, why="아직 수집된 성과 데이터가 없습니다.", detail_route="/performance")
    platforms = sorted({r.platform for r in inputs.performance_records})
    return StatusWhyAction(
        label="PERFORMANCE", status=VALID, count=len(inputs.performance_records),
        why=f"플랫폼: {', '.join(platforms) or '(없음)'}", detail_route="/performance",
    )


def build_insight_summary(inputs: OperatorInputs) -> StatusWhyAction:
    """``_build_insight_stage()``(pipeline용)와 status 판정 규칙을 동일하게
    맞춘다 - 두 함수가 같은 데이터를 서로 다른 결론으로 보여주면 운영자가
    혼란스러우므로, "review가 필요하면 NEEDS_HUMAN_REVIEW"라는 규칙을
    공유한다(6-38에서 발견한 내부 일관성 버그를 수정 - 기존에는 이 함수만
    항상 VALID를 반환했다)."""
    if inputs.insight_status == NOT_PRESENT:
        return StatusWhyAction(label="INSIGHT", status=NOT_PRESENT, why="아직 계산된 Insight가 없습니다.", detail_route="/performance/insights")
    new_count = sum(1 for i in inputs.insight_records if review_priority(i) == PRIORITY_NEW)
    review_count = sum(1 for i in inputs.insight_records if review_priority(i) in (PRIORITY_INSUFFICIENT_DATA, PRIORITY_INCOMPARABLE, PRIORITY_INVALID))
    decision_count = sum(1 for i in inputs.insight_records if i.status == STATUS_CANDIDATE)
    status = NEEDS_HUMAN_REVIEW if review_count else VALID
    return StatusWhyAction(
        label="INSIGHT", status=status, count=len(inputs.insight_records),
        why=f"new={new_count}, review_required={review_count}, decision_required={decision_count}",
        detail_route="/performance/insights",
    )


# --- 6-39: RECOVERY(STATE A/B/C 구분, 6-21~6-23 재사용) -----------------------------


def build_recovery_status(inputs: OperatorInputs) -> StatusWhyAction:
    """Production Archive가 정상적으로 없는 것(STATE A)인지, 있었는데
    사라진 것(STATE B)인지, 있지만 검증/충돌이 필요한 것(STATE C)인지를
    구분한다(docs/6-39). 새 검증 로직을 만들지 않는다 - git 이력 존재
    여부(호출부가 ``git log --all``로 확인해 넘김)와 6-22
    ``recovery_staging.validate_production_archive()``가 이미 계산한 이슈
    개수만 재사용/집계한다."""
    if inputs.production_archive_status == NOT_PRESENT:
        if inputs.production_archive_ever_tracked is True:
            return StatusWhyAction(
                label="RECOVERY", status=RECOVERY_REQUIRED,
                why="Production Archive가 git 이력에는 존재했지만 현재 이 PC에는 없습니다(STATE B).",
                action="다른 PC의 데이터를 확인한 뒤 python scripts/audit_recovery_source.py --source <복사본>으로 검토하세요(docs/6-22, 6-23).",
            )
        if inputs.production_archive_ever_tracked is False:
            return StatusWhyAction(
                label="RECOVERY", status=RECOVERY_NOT_REQUIRED,
                why="Production Archive가 git에 커밋된 적이 없습니다 - 정상적인 fresh clone 상태입니다(STATE A).",
            )
        return StatusWhyAction(
            label="RECOVERY", status=RECOVERY_UNVERIFIED,
            why="git 이력을 확인할 수 없습니다(git 저장소가 아니거나 명령이 실패했습니다).",
            action="git log --all -- data/tak_media_archive.json으로 직접 확인하세요.",
        )
    if inputs.production_archive_status == CORRUPTED:
        return StatusWhyAction(
            label="RECOVERY", status=RECOVERY_REVIEW_REQUIRED,
            why="Production Archive 파일이 손상되어 파싱할 수 없습니다(STATE C).",
            action="git log로 이전 정상 버전을 확인하거나 python scripts/audit_recovery_source.py로 복구 후보를 검토하세요.",
        )
    if inputs.production_archive_issue_count:
        return StatusWhyAction(
            label="RECOVERY", status=RECOVERY_CONFLICT, count=inputs.production_archive_issue_count,
            why="Production Archive 내부 정합성 문제가 발견됐습니다(중복 content_id 등, STATE C).",
            action="python scripts/audit_recovery_source.py --source data --verbose로 상세를 확인하세요.",
        )
    return StatusWhyAction(label="RECOVERY", status=RECOVERY_NOT_REQUIRED)


# --- 11장: NEXT ACTION(최대 3개, 새 점수 시스템 없음) --------------------------------


def build_next_actions(human_actions: tuple[StatusWhyAction, ...], blocked_items: tuple[StatusWhyAction, ...]) -> tuple[str, ...]:
    """human_actions/blocked_items에 이미 나열된 순서를 그대로 따른다 -
    별도의 중요도 점수를 계산하지 않는다(사람이 이미 만든 순서: pending
    KNOWLEDGE -> MEDIA review -> Promotion -> Threads -> YouTube -> Blog가
    build_human_actions()의 코드 순서 자체다)."""
    ordered = [item.label for item in human_actions] + [item.label for item in blocked_items]
    seen: list[str] = []
    for label in ordered:
        if label not in seen:
            seen.append(label)
    return tuple(seen[:3])


# --- 13장: 전체 시스템 상태 ---------------------------------------------------------


def _determine_system_status(
    git_status: StatusWhyAction, pipeline: tuple[StatusWhyAction, ...], blocked_items: tuple[StatusWhyAction, ...],
    human_actions: tuple[StatusWhyAction, ...], recovery_status: StatusWhyAction,
) -> str:
    if git_status.status in ("OUT_OF_SYNC", "DIRTY", "UNKNOWN"):
        return SYSTEM_NEEDS_REVIEW
    if any(item.status == PUBLISH_ERROR for item in pipeline):
        return SYSTEM_ERROR
    # 6-39: RECOVERY_UNVERIFIED(확인 불가)는 escalate하지 않는다 - "모른다"를
    # "문제 있다"로 오판하지 않기 위함. 실제로 확인된 문제(RECOVERY_REQUIRED/
    # CONFLICT/REVIEW_REQUIRED)만 시스템 상태를 끌어올린다.
    if recovery_status.status in (RECOVERY_REQUIRED, RECOVERY_CONFLICT, RECOVERY_REVIEW_REQUIRED):
        return SYSTEM_NEEDS_REVIEW
    if any(item.status == "BLOCKED" for item in blocked_items):
        return SYSTEM_BLOCKED
    if human_actions:
        return SYSTEM_READY_WITH_HUMAN_STEP
    return SYSTEM_READY


# --- 진입점 --------------------------------------------------------------------------


def build_operator_summary(inputs: OperatorInputs) -> OperatorSummary:
    """모든 하위 집계를 조합해 OperatorSummary 1건을 만든다. 순수 함수 -
    파일을 읽거나 쓰지 않는다."""
    knowledge_by_id = {r.id: r for r in inputs.knowledge_records}

    git_status = _build_git_status(inputs)
    test_status = _build_test_status(inputs)
    pipeline = build_pipeline(inputs, knowledge_by_id)
    human_actions = build_human_actions(inputs)
    blocked_items = build_blocked_items(inputs)
    publish_status = build_publish_status(inputs, knowledge_by_id)
    data_health = build_data_health(inputs)
    performance = build_performance_summary(inputs)
    insights = build_insight_summary(inputs)
    recovery = build_recovery_status(inputs)
    next_actions = build_next_actions(human_actions, blocked_items)

    system_status = _determine_system_status(git_status, pipeline, blocked_items, human_actions, recovery)

    return OperatorSummary(
        system_status=system_status,
        generated_at=inputs.generated_at,
        git_status=git_status,
        test_status=test_status,
        pipeline=pipeline,
        human_actions=human_actions,
        blocked_items=blocked_items,
        publish_status=publish_status,
        data_health=data_health,
        performance=performance,
        insights=insights,
        recovery=recovery,
        next_actions=next_actions,
    )
