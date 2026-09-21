"""Threads pending draft(``data/tak_threads_pending.json``)와 실제 게시 이력
(``data/threads_publish_log.json``)의 전수 정합성 점검(6-15).

읽기 전용 순수 함수 모듈이다 - 어떤 파일도 쓰지 않는다(``content_engine.publish_audit``와
동일한 책임 분리 관례). 실제 복구는 이 모듈이 하지 않는다: 안전하게 복구 가능한
단일 케이스(승인된 draft가 실제로는 이미 게시됨)는 기존
``scripts/publish_approved_threads.py --execute``가 이미 안전하게(Threads API를
다시 호출하지 않고 게시 이력만으로 동기화) 처리하므로 이 모듈/CLI는 새 복구 로직을
만들지 않는다 - 그 판단에 필요한 "복구해도 되는 항목이 무엇인지"만 이 모듈이 보고한다.

분류(6-15 지시 8장이 요구한 6개 상태):
    - ``CONSISTENT``: pending 상태와 게시 이력이 서로 일치한다(published이면
      이력에도 있고 post_id도 같다, 또는 pending에 없고 이력에도 없다는 뜻은
      아니다 - 이력에만 있는 경우는 별도로 ORPHAN이다).
    - ``PUBLISHED_BUT_PENDING_STALE``: 게시 이력에는 실제 post_id가 있는데,
      pending 파일의 상태가 아직 "published"로 갱신되지 않았다. content_id가
      정확히 일치하고 이력에 중복이 없을 때만 안전한 자동 복구 후보다.
    - ``PENDING_WITHOUT_PUBLISH_LOG``: pending/approved 상태이고 게시 이력이
      없다 - 아직 게시 전이므로 정상이다.
    - ``FAILED``: pending 파일의 상태가 failed다(정보 제공용, 사람이 재승인
      여부를 판단해야 한다).
    - ``ORPHAN``: 한쪽에만 존재하거나(게시 이력에는 있지만 pending에는 없음)
      pending이 published라고 주장하는데 이력에 일치하는 근거가 없는 경우.
      게시 이력에만 있는 경우는 이 저장소의 기존 설계상 흔한 정상 상태일 수
      있다(오래된 pending 항목이 정리됐거나, pending 게이트 도입 이전에 게시된
      콘텐츠) - 그래도 사람이 한 번은 확인할 수 있도록 표시한다.
    - ``DUPLICATE``: 같은 content_id가 pending 파일 또는 게시 이력 파일에
      2번 이상 존재한다 - 정상적인 운영에서는 있을 수 없는 구조적 이상이다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .threads_review import ThreadsPendingDraft

CONSISTENT = "CONSISTENT"
PUBLISHED_BUT_PENDING_STALE = "PUBLISHED_BUT_PENDING_STALE"
PENDING_WITHOUT_PUBLISH_LOG = "PENDING_WITHOUT_PUBLISH_LOG"
FAILED = "FAILED"
ORPHAN = "ORPHAN"
DUPLICATE = "DUPLICATE"

THREADS_CONSISTENCY_STATUSES = (
    CONSISTENT,
    PUBLISHED_BUT_PENDING_STALE,
    PENDING_WITHOUT_PUBLISH_LOG,
    FAILED,
    ORPHAN,
    DUPLICATE,
)


@dataclass(frozen=True)
class ThreadsConsistencyResult:
    content_id: str
    status: str
    reasons: tuple[str, ...]
    pending_status: str | None
    knowledge_id: str
    source_url: str
    log_post_id: str | None
    log_published_at: str | None
    # 안전한 자동 복구(publish_approved_threads.py --execute) 대상이 되려면
    # True여야 한다 - 이 모듈은 실제 복구를 실행하지 않고 판정만 한다.
    safe_to_sync: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "content_id": self.content_id,
            "status": self.status,
            "reasons": list(self.reasons),
            "pending_status": self.pending_status,
            "knowledge_id": self.knowledge_id,
            "source_url": self.source_url,
            "log_post_id": self.log_post_id,
            "log_published_at": self.log_published_at,
            "safe_to_sync": self.safe_to_sync,
        }


def audit_threads_consistency(
    pending: Sequence[ThreadsPendingDraft],
    log_records: Sequence[dict[str, Any]],
) -> tuple[ThreadsConsistencyResult, ...]:
    """pending draft 전체와 게시 이력 전체를 대조해 content_id별 정합성을 판정한다."""

    pending_by_id: dict[str, list[ThreadsPendingDraft]] = {}
    for draft in pending:
        pending_by_id.setdefault(draft.content_id, []).append(draft)

    log_by_id: dict[str, list[dict[str, Any]]] = {}
    for record in log_records:
        content_id = str(record.get("content_id") or "")
        if content_id:
            log_by_id.setdefault(content_id, []).append(record)

    all_content_ids = sorted(set(pending_by_id) | set(log_by_id))
    results: list[ThreadsConsistencyResult] = []

    for content_id in all_content_ids:
        drafts = pending_by_id.get(content_id, [])
        logs = log_by_id.get(content_id, [])

        knowledge_id = drafts[0].knowledge_id if drafts else str((logs[0] if logs else {}).get("knowledge_id") or "")
        source_url = drafts[0].source_url if drafts else str((logs[0] if logs else {}).get("source_url") or "")
        log_post_id = str(logs[0].get("threads_post_id") or "") if logs else None
        log_published_at = str(logs[0].get("published_at") or "") if logs else None
        pending_status = drafts[0].status if drafts else None

        # 1. 구조적 이상(DUPLICATE) - 다른 어떤 판정보다 우선한다.
        if len(drafts) > 1:
            results.append(
                ThreadsConsistencyResult(
                    content_id,
                    DUPLICATE,
                    (f"pending 파일에 content_id가 {len(drafts)}번 존재합니다.",),
                    pending_status,
                    knowledge_id,
                    source_url,
                    log_post_id,
                    log_published_at,
                )
            )
            continue
        if len(logs) > 1:
            results.append(
                ThreadsConsistencyResult(
                    content_id,
                    DUPLICATE,
                    (f"게시 이력 파일에 content_id가 {len(logs)}번 존재합니다.",),
                    pending_status,
                    knowledge_id,
                    source_url,
                    log_post_id,
                    log_published_at,
                )
            )
            continue

        draft = drafts[0] if drafts else None
        log = logs[0] if logs else None

        # 2. pending에만 있는 경우
        if draft is not None and log is None:
            if draft.status == "published":
                results.append(
                    ThreadsConsistencyResult(
                        content_id,
                        ORPHAN,
                        ("pending 파일은 published 상태이지만 게시 이력에 일치하는 기록이 없습니다.",),
                        draft.status,
                        knowledge_id,
                        source_url,
                        None,
                        None,
                    )
                )
            elif draft.status == "failed":
                reason = f"failure_reason={draft.failure_reason!r}" if draft.failure_reason else "실패 사유 없음"
                results.append(
                    ThreadsConsistencyResult(
                        content_id, FAILED, (reason,), draft.status, knowledge_id, source_url, None, None
                    )
                )
            else:
                results.append(
                    ThreadsConsistencyResult(
                        content_id,
                        PENDING_WITHOUT_PUBLISH_LOG,
                        (f"status={draft.status} - 아직 게시 이력이 없습니다(정상).",),
                        draft.status,
                        knowledge_id,
                        source_url,
                        None,
                        None,
                    )
                )
            continue

        # 3. 게시 이력에만 있는 경우(pending에 없음) - 흔히 정상일 수 있으나 표시한다.
        if draft is None and log is not None:
            results.append(
                ThreadsConsistencyResult(
                    content_id,
                    ORPHAN,
                    ("게시 이력에는 있지만 pending 파일에 해당 content_id가 없습니다.",),
                    None,
                    knowledge_id,
                    source_url,
                    log_post_id,
                    log_published_at,
                )
            )
            continue

        # 4. 둘 다 있는 경우
        assert draft is not None and log is not None
        has_real_post_id = bool(log_post_id and log_post_id.strip())

        if draft.status == "published":
            if draft.threads_post_id and log_post_id and draft.threads_post_id == log_post_id:
                results.append(
                    ThreadsConsistencyResult(
                        content_id, CONSISTENT, (), draft.status, knowledge_id, source_url, log_post_id, log_published_at
                    )
                )
            else:
                results.append(
                    ThreadsConsistencyResult(
                        content_id,
                        ORPHAN,
                        (
                            f"pending의 threads_post_id({draft.threads_post_id!r})와 게시 이력의 "
                            f"threads_post_id({log_post_id!r})가 다릅니다.",
                        ),
                        draft.status,
                        knowledge_id,
                        source_url,
                        log_post_id,
                        log_published_at,
                    )
                )
            continue

        if draft.status == "failed":
            reason = f"failure_reason={draft.failure_reason!r}" if draft.failure_reason else "실패 사유 없음"
            results.append(
                ThreadsConsistencyResult(
                    content_id,
                    FAILED,
                    (reason, "게시 이력에도 기록이 있어 확인이 필요합니다."),
                    draft.status,
                    knowledge_id,
                    source_url,
                    log_post_id,
                    log_published_at,
                )
            )
            continue

        # status가 pending/approved인데 게시 이력에 실제 post_id가 있다 - stale.
        if has_real_post_id:
            # 6-15 지시 9장의 안전 조건: post_id 존재 + content_id 정확 일치(이미
            # 이 시점에서 dict 키로 보장됨) + 중복 없음(이미 위에서 배제) +
            # status == "approved"(publish_approved_threads.py --execute가 처리할
            # 수 있는 유일한 상태 - pending은 이 스크립트의 허용 전이 목록에
            # 없으므로 자동 복구 대상에서 제외하고 사람이 확인하게 한다).
            safe = draft.status == "approved"
            reasons = [
                f"게시 이력에 실제 post_id({log_post_id})가 있지만 pending 상태는 "
                f"여전히 {draft.status!r}입니다.",
            ]
            if not safe:
                reasons.append(
                    "status가 'approved'가 아니므로 publish_approved_threads.py --execute로 "
                    "자동 동기화할 수 없습니다 - 사람이 직접 확인해야 합니다."
                )
            results.append(
                ThreadsConsistencyResult(
                    content_id,
                    PUBLISHED_BUT_PENDING_STALE,
                    tuple(reasons),
                    draft.status,
                    knowledge_id,
                    source_url,
                    log_post_id,
                    log_published_at,
                    safe_to_sync=safe,
                )
            )
            continue

        # 게시 이력 레코드는 있지만 post_id가 비어 있다 - 이례적이므로 ORPHAN.
        results.append(
            ThreadsConsistencyResult(
                content_id,
                ORPHAN,
                ("게시 이력 레코드는 있지만 threads_post_id가 비어 있습니다.",),
                draft.status,
                knowledge_id,
                source_url,
                log_post_id,
                log_published_at,
            )
        )

    return tuple(results)


def summarize(results: Sequence[ThreadsConsistencyResult]) -> dict[str, int]:
    summary = {status: 0 for status in THREADS_CONSISTENCY_STATUSES}
    for result in results:
        summary[result.status] += 1
    return summary


def _md_escape(text: str) -> str:
    return text.replace("|", "\\|")


def render_consistency_markdown(
    results: Sequence[ThreadsConsistencyResult], generated_at: str | None = None
) -> str:
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    summary = summarize(results)

    lines = [
        "# Threads Publish Consistency",
        "",
        f"생성 시각(UTC): {generated_at}",
        "",
        "## Summary",
        "",
        f"- 전체 대상 content_id: {len(results)}",
        f"- CONSISTENT: {summary[CONSISTENT]}",
        f"- PUBLISHED_BUT_PENDING_STALE: {summary[PUBLISHED_BUT_PENDING_STALE]}",
        f"- PENDING_WITHOUT_PUBLISH_LOG: {summary[PENDING_WITHOUT_PUBLISH_LOG]}",
        f"- FAILED: {summary[FAILED]}",
        f"- ORPHAN: {summary[ORPHAN]}",
        f"- DUPLICATE: {summary[DUPLICATE]}",
        "",
        "⚠️ 이 보고서는 읽기 전용 점검 결과입니다. 어떤 파일도 이 보고서 생성 과정에서",
        "수정되지 않습니다. safe_to_sync=예인 항목만",
        "`python scripts/publish_approved_threads.py --id <content_id> --execute`로",
        "안전하게 동기화할 수 있습니다(이미 게시된 이력이 있으므로 실제 Threads API를",
        "다시 호출하지 않습니다).",
        "",
        "## 전체 내역",
        "",
        "| content_id | 상태 | pending status | log post_id | safe_to_sync | 사유 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        reasons = "; ".join(r.reasons) if r.reasons else "-"
        safe = "예" if r.safe_to_sync else "아니오"
        lines.append(
            f"| {r.content_id} | {r.status} | {r.pending_status or '-'} | {r.log_post_id or '-'} | "
            f"{safe} | {_md_escape(reasons)} |"
        )

    needs_review = [r for r in results if r.status in (ORPHAN, DUPLICATE, FAILED)]
    lines += ["", "## 사람이 확인해야 하는 항목", ""]
    if not needs_review:
        lines.append("사람이 확인해야 하는 이상 항목이 없습니다.")
    else:
        for r in needs_review:
            reasons = "; ".join(r.reasons) if r.reasons else "(사유 없음)"
            lines.append(f"- `{r.content_id}` ({r.status}): {reasons}")

    syncable = [r for r in results if r.safe_to_sync]
    lines += ["", "## 자동 복구 가능(safe_to_sync) 항목", ""]
    if not syncable:
        lines.append("자동 복구 가능한 항목이 없습니다.")
    else:
        for r in syncable:
            lines.append(
                f"- `{r.content_id}`: pending status={r.pending_status!r} -> 게시 이력 post_id={r.log_post_id!r}"
            )

    return "\n".join(lines) + "\n"


def save_consistency_report(
    results: Sequence[ThreadsConsistencyResult], path: Any, generated_at: str | None = None
) -> None:
    from pathlib import Path

    target_path = Path(path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(render_consistency_markdown(results, generated_at=generated_at), encoding="utf-8")
