#!/usr/bin/env python3
"""Threads "승인된 초안 발행" 전용 CLI (5-11 설계 문서 Phase 2, 9-2장).

``data/tak_threads_pending.json``에서 ``status == "approved"``인 draft만 대상으로,
기존 ``content_engine.threads_publisher.ThreadsClient``를 그대로 재사용해 실제
Threads Graph API에 게시한다. 새 Threads API 클라이언트는 만들지 않는다.

이 스크립트가 절대 하지 않는 것:
    - pending인 draft를 발행하는 것 (승인 전이므로 final_title/final_body가 없다)
    - published인 draft를 다시 발행하는 것 (종결 상태)
    - failed인 draft를 자동으로 재발행하는 것 (사람이 다시 approved로 되돌려야만
      이 스크립트의 대상이 된다 - ``content_engine.threads_review.mark_approved``의
      failed -> approved 재승인 전이를 통해서만 가능하다)
    - ai_rewritten_title/ai_rewritten_body를 직접 발행하는 것 (반드시 final_*을 쓴다)
    - ``--execute`` 없이 실제 Threads API를 호출하는 것 (기본 실행과 ``--dry-run``은
      항상 안전하다)
    - 실패 시 PublishHistory를 갱신하는 것 (성공 시에만 기록한다 - 기존
      ``scripts/publish_threads.py``와 동일한 계약)

기존 완전 자동 발행 경로(``scripts/run_daily.py``, ``scripts/publish_threads.py``,
``.github/workflows/daily-threads-post.yml``)는 이 스크립트에서 전혀 import하지
않고, 한 줄도 수정하지 않는다.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from blog_importer.models import utc_now
from content_engine import ThreadsAPIError, ThreadsClient, ThreadsConfigurationError
from content_engine.publish_history import PublishHistory, PublishRecord
from content_engine.threads_review import (
    ThreadsPendingDraft,
    ThreadsPendingError,
    load_pending,
    mark_failed,
    mark_published,
    upsert_pending,
)


def load_approved_drafts(
    pending_path: Path | str, content_id: str | None = None
) -> list[ThreadsPendingDraft]:
    """pending 파일에서 status == "approved"인 draft만 골라 반환한다.

    ``content_id``가 주어지면 그 항목 하나로 더 좁힌다. 이 함수는 파일을 갱신하지
    않는다(읽기 전용) - dry-run과 execute가 완전히 동일한 "대상 목록 결정" 로직을
    공유하기 위함이다.
    """
    drafts = load_pending(pending_path)
    approved = [draft for draft in drafts if draft.status == "approved"]
    if content_id is not None:
        approved = [draft for draft in approved if draft.content_id == content_id]
    return approved


def validate_final_text(draft: ThreadsPendingDraft) -> str | None:
    """final_title/final_body가 비어 있으면 오류 메시지를, 문제 없으면 None을 반환한다."""
    if draft.final_title is None or not draft.final_title.strip():
        return f"content_id={draft.content_id}: final_title이 없습니다. 발행할 수 없습니다."
    if draft.final_body is None or not draft.final_body.strip():
        return f"content_id={draft.content_id}: final_body가 없습니다. 발행할 수 없습니다."
    return None


def _find_history_record(history: PublishHistory, content_id: str) -> dict[str, Any]:
    for record in history.load():
        if record.get("content_id") == content_id:
            return record
    return {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="승인된(approved) Threads 초안을 발행하는 CLI (5-11 Phase 3)"
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=ROOT / "data" / "tak_threads_pending.json",
        help="검수 대기 draft 경로 (기본값: data/tak_threads_pending.json)",
    )
    parser.add_argument(
        "--history",
        type=Path,
        default=ROOT / "data" / "threads_publish_log.json",
        help="게시 이력 JSON 경로 (기본값: data/threads_publish_log.json)",
    )
    parser.add_argument(
        "--id",
        type=str,
        default=None,
        help="특정 content_id 1건만 발행 대상으로 제한",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="실제 Threads API를 호출하지 않고 발행 예정 내용만 보여줍니다(기본 동작과 동일).",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="실제로 Threads API를 호출해 게시합니다. 이 플래그가 없으면 절대 게시하지 않습니다.",
    )
    args = parser.parse_args(argv)

    if args.dry_run and args.execute:
        print("오류: --dry-run과 --execute를 동시에 지정할 수 없습니다.", file=sys.stderr)
        return 1

    # 기본 실행(둘 다 안 준 경우)도 --dry-run과 완전히 동일하게 안전해야 한다
    # (요구사항 7, 8) - 오직 --execute가 명시적으로 있을 때만 실제로 게시한다.
    execute = args.execute

    try:
        approved = load_approved_drafts(args.input, content_id=args.id)
    except ThreadsPendingError as err:
        print(f"오류: {err}", file=sys.stderr)
        return 1

    if args.id and not approved:
        print(f"오류: 지정한 content_id의 승인된(approved) 초안을 찾을 수 없습니다: {args.id}", file=sys.stderr)
        return 1

    if not approved:
        print("발행할 승인된(approved) Threads 초안이 없습니다.")
        return 0

    history = PublishHistory(args.history)
    exit_code = 0

    for draft in approved:
        validation_error = validate_final_text(draft)
        if validation_error:
            print(f"오류: {validation_error}", file=sys.stderr)
            exit_code = 1
            continue

        if history.is_published(draft.content_id):
            print(
                f"안내: content_id={draft.content_id}는 이미 게시 이력에 존재합니다. "
                "Threads API를 호출하지 않습니다."
            )
            if execute:
                record = _find_history_record(history, draft.content_id)
                synced = mark_published(
                    draft,
                    threads_post_id=str(record.get("threads_post_id") or ""),
                    published_at=str(record.get("published_at") or utc_now()),
                )
                upsert_pending(args.input, synced)
            continue

        if not execute:
            print(f"=== [DRY-RUN] 발행 예정: content_id={draft.content_id} (knowledge_id={draft.knowledge_id}) ===")
            print(f"제목: {draft.final_title}")
            print(f"본문: {draft.final_body}")
            print("Threads API 호출 없음. 실제 게시하려면 --execute를 사용하세요.")
            print("-" * 50)
            continue

        try:
            client = ThreadsClient.from_environment()
            result = client.publish_text(draft.final_body)
        except (ThreadsConfigurationError, ThreadsAPIError, ValueError) as err:
            failed = mark_failed(draft, failure_reason=str(err), failed_at=utc_now())
            upsert_pending(args.input, failed)
            print(f"오류: content_id={draft.content_id} 발행 실패: {err}", file=sys.stderr)
            exit_code = 1
            continue

        published_at = utc_now()
        try:
            history.append(
                PublishRecord(
                    content_id=draft.content_id,
                    published_at=published_at,
                    threads_post_id=result.id,
                    knowledge_id=draft.knowledge_id,
                    platform="threads",
                    source_url=draft.source_url,
                )
            )
        except OSError as history_err:
            print(
                f"경고: content_id={draft.content_id} 게시는 성공했지만 게시 이력 저장에 실패했습니다: {history_err}",
                file=sys.stderr,
            )

        updated = mark_published(draft, threads_post_id=result.id, published_at=published_at)
        upsert_pending(args.input, updated)
        print(f"발행 성공: content_id={draft.content_id} (Threads Post ID: {result.id})")

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
