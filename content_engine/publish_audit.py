"""Production Archive의 콘텐츠가 실제로 게시될 준비가 됐는지 자동으로 점검하는
읽기 전용 감사(audit) 모듈(6-14).

목적: 사람이 `/media`, `/media/generations`를 하나씩 열어 확인하지 않아도,
"이 콘텐츠는 지금 바로 게시 후보로 쓸 수 있는가"를 코드가 먼저 판정해 보여준다.
이 모듈은 어떤 파일도 쓰지 않는다(순수 함수 + 읽기 전용 조회) - 판정에 필요한
정보는 전부 기존 저장소(``MediaArchiveRecord``, ``PublishHistory``,
``ThreadsPendingDraft``, ``YouTubeUploadHistory``, ShortsScript 파일 존재 여부)를
그대로 재사용해서 얻는다. 새 저장소나 새 승인 개념을 만들지 않는다.

절대 원칙(6-14 지시 3장): 이 모듈은 콘텐츠를 임의로 승인하지 않는다.
``review_status != "approved"``인 레코드는 어떤 경우에도 READY가 될 수 없다.

분류(``PUBLISH_READINESS_STATUSES``):
    - ``READY``: 승인됐고, 필수 조건을 전부 만족하고, 아직 게시되지 않았고,
      민감(금융/부동산/대출) 콘텐츠도 아니다 - 지금 바로 Publish Pack에
      포함/게시 준비할 수 있다.
    - ``NEEDS_HUMAN_REVIEW``: READY의 다른 모든 조건은 만족하지만,
      ``content_engine.blog_publish_pack.is_review_required()``가 True인
      민감 콘텐츠다(기존 5-10 설계의 "review_required" 개념을 그대로 재사용 -
      새 판정 기준을 만들지 않는다). 승인은 됐지만 실제 게시 직전에 사람이
      한 번 더 확인해야 한다.
    - ``BLOCKED``: 정상적인 이유로 아직 게시 후보가 될 수 없다(미승인/보류/
      검증 실패/필수 필드 누락/Shorts Script 미생성 등).
    - ``ALREADY_PUBLISHED``: 해당 채널의 실제 게시 이력에 이미 있다 - 다시
      게시하면 안 된다.
    - ``ERROR``: 정상적인 운영에서는 있을 수 없는 구조적 이상(같은 content_id가
      production archive에 두 번 이상 존재하는 경우 등). 사람이 데이터를
      직접 조사해야 한다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tak_brain import KnowledgeRecord

from .blog_publish_pack import is_review_required
from .media_archive import MediaArchiveRecord
from .publish_history import PublishHistory
from .shorts_adapter import shorts_script_output_path
from .threads_review import ThreadsPendingDraft
from .youtube_upload_history import YouTubeUploadHistory


READY = "READY"
NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"
BLOCKED = "BLOCKED"
ALREADY_PUBLISHED = "ALREADY_PUBLISHED"
ERROR = "ERROR"

PUBLISH_READINESS_STATUSES = (READY, NEEDS_HUMAN_REVIEW, BLOCKED, ALREADY_PUBLISHED, ERROR)

PLATFORMS = ("blog", "shorts", "threads")


@dataclass(frozen=True)
class PublishAuditResult:
    """콘텐츠(production archive record) 1건에 대한 감사 결과."""

    content_id: str
    knowledge_id: str
    platform: str
    status: str
    reasons: tuple[str, ...]
    title: str
    source_url: str
    review_status: str
    generation_status: str
    # 채널별 참고 정보(보고서 렌더링/판정 사유 표시용) - 있으면 채운다.
    threads_pending_status: str | None = None
    shorts_script_exists: bool | None = None
    shorts_mp4_exists: bool | None = None
    external_id: str | None = None  # threads_post_id / video_id / (blog는 이력이 URL만 가짐)

    def to_dict(self) -> dict[str, Any]:
        return {
            "content_id": self.content_id,
            "knowledge_id": self.knowledge_id,
            "platform": self.platform,
            "status": self.status,
            "reasons": list(self.reasons),
            "title": self.title,
            "source_url": self.source_url,
            "review_status": self.review_status,
            "generation_status": self.generation_status,
            "threads_pending_status": self.threads_pending_status,
            "shorts_script_exists": self.shorts_script_exists,
            "shorts_mp4_exists": self.shorts_mp4_exists,
            "external_id": self.external_id,
        }


@dataclass(frozen=True)
class PublishAuditInputs:
    """감사에 필요한 모든 읽기 전용 소스를 한 번에 묶는다.

    호출부(CLI/테스트)가 각 저장소를 원하는 경로로 로드해 넘기기만 하면 되고,
    이 모듈은 파일 경로를 전혀 알지 못한다(순수 함수 원칙 유지).
    """

    knowledge_by_id: dict[str, KnowledgeRecord] = field(default_factory=dict)
    blog_history: PublishHistory | None = None
    threads_history: PublishHistory | None = None
    threads_pending: tuple[ThreadsPendingDraft, ...] = ()
    youtube_history: YouTubeUploadHistory | None = None
    shorts_scripts_path: Path | str | None = None
    shorts_dir_path: Path | str | None = None  # data/shorts/<content_id>.mp4 확인용


def _find_pending_draft(
    pending: tuple[ThreadsPendingDraft, ...], content_id: str
) -> ThreadsPendingDraft | None:
    for draft in pending:
        if draft.content_id == content_id:
            return draft
    return None


def audit_record(
    record: MediaArchiveRecord,
    *,
    duplicate_content_ids: frozenset[str],
    inputs: PublishAuditInputs,
) -> PublishAuditResult:
    """레코드 1건을 감사한다. 이 함수는 어떤 파일도 읽거나 쓰지 않는다 - 필요한
    정보는 전부 ``inputs``(이미 로드된 데이터)에서만 얻는다(호출부가 배치
    전체에 대해 파일을 한 번만 읽고 재사용하도록 하기 위함)."""

    title = record.final_title
    knowledge = inputs.knowledge_by_id.get(record.knowledge_id)

    def _result(status: str, *reasons: str, **extra: Any) -> PublishAuditResult:
        return PublishAuditResult(
            content_id=record.content_id,
            knowledge_id=record.knowledge_id,
            platform=record.platform,
            status=status,
            reasons=tuple(reasons),
            title=title,
            source_url=record.source_url,
            review_status=record.review_status,
            generation_status=record.generation_status,
            **extra,
        )

    # 1. 구조적 이상(ERROR) - 같은 content_id가 production archive에 두 번 이상
    #    있으면(정상 운영에서는 upsert_archive()의 단독 키 upsert가 이를 막지만,
    #    방어적으로 확인한다) 사람이 데이터를 직접 조사해야 한다.
    if record.content_id in duplicate_content_ids:
        return _result(
            ERROR,
            f"content_id가 production archive에 중복 존재합니다: {record.content_id}",
        )

    # 2. 이미 게시됐는가(채널별 실제 게시 이력) - 이 사실은 다른 어떤 조건보다
    #    우선한다(승인/보류 상태와 무관하게, 한 번 게시된 것은 다시 게시 대상이
    #    되면 안 된다).
    threads_pending_status: str | None = None
    if record.platform == "blog" and inputs.blog_history is not None:
        if inputs.blog_history.is_published(record.content_id):
            return _result(ALREADY_PUBLISHED, "Blog 게시 이력에 이미 기록됨")
    elif record.platform == "threads":
        draft = _find_pending_draft(inputs.threads_pending, record.content_id)
        threads_pending_status = draft.status if draft is not None else None
        already_in_history = (
            inputs.threads_history is not None
            and inputs.threads_history.is_published(record.content_id)
        )
        if already_in_history or (draft is not None and draft.status == "published"):
            return _result(
                ALREADY_PUBLISHED,
                "Threads 게시 이력에 이미 기록됨",
                threads_pending_status=threads_pending_status,
                external_id=draft.threads_post_id if draft else None,
            )
    elif record.platform == "shorts" and inputs.youtube_history is not None:
        if inputs.youtube_history.is_published(record.content_id):
            return _result(ALREADY_PUBLISHED, "YouTube 업로드 이력에 이미 기록됨")

    # 3. 정상적인 차단 사유(BLOCKED) - 여러 개면 전부 모아서 보여준다.
    blocking_reasons: list[str] = []

    if record.generation_status != "valid":
        blocking_reasons.append(f"generation_status가 valid가 아님: {record.generation_status}")
    if record.review_status != "approved":
        blocking_reasons.append(f"review_status가 approved가 아님: {record.review_status}")
    if not title.strip():
        blocking_reasons.append("제목이 비어 있음")
    if not (record.final_body or "").strip():
        blocking_reasons.append("본문이 비어 있음")
    if not record.source_url.strip():
        blocking_reasons.append("source_url이 없음")

    shorts_script_exists: bool | None = None
    shorts_mp4_exists: bool | None = None
    if record.platform == "shorts":
        if inputs.shorts_scripts_path is not None:
            script_path = shorts_script_output_path(inputs.shorts_scripts_path, record.content_id)
            shorts_script_exists = script_path.exists()
            if not shorts_script_exists:
                blocking_reasons.append("ShortsScript 파일이 아직 생성되지 않음")
        if inputs.shorts_dir_path is not None:
            mp4_path = Path(inputs.shorts_dir_path) / f"{record.content_id}.mp4"
            shorts_mp4_exists = mp4_path.exists()

    if blocking_reasons:
        return _result(
            BLOCKED,
            *blocking_reasons,
            threads_pending_status=threads_pending_status,
            shorts_script_exists=shorts_script_exists,
            shorts_mp4_exists=shorts_mp4_exists,
        )

    # 4. 여기까지 왔으면 승인됐고, 필수 조건을 전부 만족하고, 아직 게시되지
    #    않았다. 금융/부동산/대출처럼 민감한 콘텐츠는 기존 5-10
    #    is_review_required() 판정을 그대로 재사용해 한 단계 더 확인하도록
    #    NEEDS_HUMAN_REVIEW로 내린다(승인을 취소하는 것이 아니라, "게시
    #    직전에 사람이 한 번 더 보라"는 표시일 뿐이다).
    if is_review_required(knowledge):
        return _result(
            NEEDS_HUMAN_REVIEW,
            "금융/부동산/대출 등 민감 콘텐츠 - 게시 전 사람의 최종 확인 필요",
            threads_pending_status=threads_pending_status,
            shorts_script_exists=shorts_script_exists,
            shorts_mp4_exists=shorts_mp4_exists,
        )

    return _result(
        READY,
        threads_pending_status=threads_pending_status,
        shorts_script_exists=shorts_script_exists,
        shorts_mp4_exists=shorts_mp4_exists,
    )


def audit_archive(
    records: list[MediaArchiveRecord], *, inputs: PublishAuditInputs
) -> tuple[PublishAuditResult, ...]:
    """production archive 전체를 감사한다. ``records``의 순서를 그대로 보존한다."""
    content_id_counts: dict[str, int] = {}
    for record in records:
        content_id_counts[record.content_id] = content_id_counts.get(record.content_id, 0) + 1
    duplicate_content_ids = frozenset(
        content_id for content_id, count in content_id_counts.items() if count > 1
    )

    return tuple(
        audit_record(record, duplicate_content_ids=duplicate_content_ids, inputs=inputs)
        for record in records
    )


def summarize(results: tuple[PublishAuditResult, ...]) -> dict[str, int]:
    """상태별 건수 요약. 항상 5개 상태 키를 전부 포함한다(0건이어도 표시)."""
    summary = {status: 0 for status in PUBLISH_READINESS_STATUSES}
    for result in results:
        summary[result.status] += 1
    return summary


# --- Markdown 보고서(6-14 지시 4장) --------------------------------------------
#
# 사람이 /media, /media/generations를 열지 않아도 지금 상태를 한 번에 파악할 수
# 있도록 한다. 이 렌더러도 순수 함수다 - 파일 쓰기는 save_readiness_report()만
# 담당한다(기존 content_engine.blog_publish_pack.render_markdown()/
# save_markdown()과 동일한 책임 분리 관례).


def _truncate(text: str, limit: int = 60) -> str:
    text = text.replace("\n", " ").strip()
    if len(text) > limit:
        return text[:limit] + "…"
    return text


def _md_escape(text: str) -> str:
    return text.replace("|", "\\|")


def _blog_table(results: Sequence[PublishAuditResult]) -> str:
    rows = [r for r in results if r.platform == "blog"]
    if not rows:
        return "오늘 대상 Blog 콘텐츠가 없습니다.\n"
    header = "| content_id | 제목 | review_status | publish readiness | source | 사유 |\n"
    header += "| --- | --- | --- | --- | --- | --- |\n"
    lines = [header]
    for r in rows:
        reasons = "; ".join(r.reasons) if r.reasons else "-"
        lines.append(
            f"| {r.content_id} | {_md_escape(_truncate(r.title))} | {r.review_status} | "
            f"{r.status} | {_md_escape(_truncate(r.source_url, 40))} | {_md_escape(reasons)} |\n"
        )
    return "".join(lines)


def _threads_table(results: Sequence[PublishAuditResult]) -> str:
    rows = [r for r in results if r.platform == "threads"]
    if not rows:
        return "오늘 대상 Threads 콘텐츠가 없습니다.\n"
    header = "| content_id | publish readiness | pending 상태 | 실제 게시 가능 여부 |\n"
    header += "| --- | --- | --- | --- |\n"
    lines = [header]
    for r in rows:
        ready = "예" if r.status == READY else "아니오"
        pending = r.threads_pending_status or "(pending draft 없음)"
        lines.append(f"| {r.content_id} | {r.status} | {pending} | {ready} |\n")
    return "".join(lines)


def _shorts_table(results: Sequence[PublishAuditResult]) -> str:
    rows = [r for r in results if r.platform == "shorts"]
    if not rows:
        return "오늘 대상 Shorts 콘텐츠가 없습니다.\n"
    header = (
        "| content_id | script 존재 | MP4 존재 | YouTube 게시 여부 | 중복 여부 | "
        "업로드 준비 상태 |\n"
    )
    header += "| --- | --- | --- | --- | --- | --- |\n"
    lines = [header]
    for r in rows:
        script = "예" if r.shorts_script_exists else "아니오"
        mp4 = "예" if r.shorts_mp4_exists else "아니오"
        uploaded = "예" if r.status == ALREADY_PUBLISHED else "아니오"
        duplicate = "예" if r.status == ERROR else "아니오"
        lines.append(
            f"| {r.content_id} | {script} | {mp4} | {uploaded} | {duplicate} | {r.status} |\n"
        )
    return "".join(lines)


def _blocked_section(results: Sequence[PublishAuditResult]) -> str:
    rows = [r for r in results if r.status in (BLOCKED, ERROR)]
    if not rows:
        return "차단되거나 오류로 판정된 콘텐츠가 없습니다.\n"
    lines = []
    for r in rows:
        reasons = "; ".join(r.reasons) if r.reasons else "(사유 없음)"
        lines.append(f"- `{r.content_id}` ({r.platform}, {r.status}): {reasons}\n")
    return "".join(lines)


def render_readiness_markdown(
    results: Sequence[PublishAuditResult], generated_at: str | None = None
) -> str:
    """사람이 링크를 열지 않아도 읽을 수 있는 Publish Readiness Markdown 보고서."""
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    summary = summarize(tuple(results))
    approved_count = sum(1 for r in results if r.review_status == "approved")

    header = [
        "# Publish Readiness",
        "",
        f"생성 시각(UTC): {generated_at}",
        "",
        "## Summary",
        "",
        f"- 전체 Production 콘텐츠: {len(results)}",
        f"- 승인 콘텐츠(review_status==approved): {approved_count}",
        f"- 게시 가능(READY): {summary[READY]}",
        f"- 사람 검토 필요(NEEDS_HUMAN_REVIEW): {summary[NEEDS_HUMAN_REVIEW]}",
        f"- 게시 차단(BLOCKED): {summary[BLOCKED]}",
        f"- 이미 게시됨(ALREADY_PUBLISHED): {summary[ALREADY_PUBLISHED]}",
        f"- 오류(ERROR): {summary[ERROR]}",
        "",
        "⚠️ 이 보고서는 읽기 전용 점검 결과입니다. 어떤 콘텐츠도 이 보고서 생성",
        "과정에서 승인/게시되지 않습니다. review_status==approved가 아닌 콘텐츠는",
        "이 도구가 절대로 READY로 표시하지 않습니다.",
        "",
        "## Blog",
        "",
    ]
    body = [
        _blog_table(results),
        "",
        "## Threads",
        "",
        _threads_table(results),
        "",
        "## Shorts / YouTube",
        "",
        _shorts_table(results),
        "",
        "## Blocked",
        "",
        _blocked_section(results),
    ]
    return "\n".join(header) + "\n".join(body)


def save_readiness_report(
    results: Sequence[PublishAuditResult], path: Path | str, generated_at: str | None = None
) -> None:
    """Publish Readiness 보고서를 Markdown 파일로 저장한다(매 실행마다 새로
    덮어쓰는 휘발성 보고서 - idempotent, 실행할 때마다 최신 상태를 반영한다)."""
    target_path = Path(path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(render_readiness_markdown(results, generated_at=generated_at), encoding="utf-8")
