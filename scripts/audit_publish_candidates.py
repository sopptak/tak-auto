#!/usr/bin/env python3
"""Production Archive를 자동으로 점검해 "지금 바로 게시 후보로 쓸 수 있는
콘텐츠"를 사람이 대시보드를 열지 않고도 파악할 수 있게 하는 CLI(6-14).

기존 MEDIA archive(data/tak_media_archive.json), KNOWLEDGE, Threads pending,
채널별 publish log(blog/threads/youtube), Shorts Script 디렉터리를 전부
읽기만 한다 - 어떤 파일도 쓰지 않는다(Publish Readiness Markdown 보고서 저장
제외). 실제 판정 로직은 content_engine.publish_audit(순수 함수)에 있다.

이 스크립트가 절대 하지 않는 것:
    - review_status를 바꾸는 것 (승인/보류는 여전히 /media, /media/generations의
      사람 승인만으로 이뤄진다 - 이 CLI는 임의로 콘텐츠를 승인하지 않는다)
    - 실제 외부 게시(Naver/Threads/YouTube) - 이 CLI는 관련 클라이언트를 전혀
      import하지 않는다
    - LLM 호출 - archive에 이미 저장된 결과만 읽는다
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_engine.media_archive import load_archive
from content_engine.publish_audit import (
    ALREADY_PUBLISHED,
    BLOCKED,
    ERROR,
    NEEDS_HUMAN_REVIEW,
    READY,
    SUPERSEDED,
    PublishAuditInputs,
    audit_archive,
    save_readiness_report,
    summarize,
)
from content_engine.publish_history import PublishHistory
from content_engine.threads_review import load_pending
from content_engine.youtube_upload_history import YouTubeUploadHistory
from tak_brain import load_knowledge_records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Production Archive를 자동 점검해 게시 후보를 READY/NEEDS_HUMAN_REVIEW/"
            "BLOCKED/ALREADY_PUBLISHED/ERROR로 분류하는 읽기 전용 감사 CLI"
        )
    )
    parser.add_argument(
        "--archive",
        type=Path,
        default=ROOT / "data" / "tak_media_archive.json",
        help="읽기 전용 MEDIA(Production) archive 경로 (기본값: data/tak_media_archive.json)",
    )
    parser.add_argument(
        "--knowledge",
        type=Path,
        default=ROOT / "data" / "tak_brain_knowledge.json",
        help="읽기 전용 KNOWLEDGE JSON 경로 (기본값: data/tak_brain_knowledge.json)",
    )
    parser.add_argument(
        "--threads-pending",
        type=Path,
        default=ROOT / "data" / "tak_threads_pending.json",
        help="Threads 검수 대기 draft 경로 (기본값: data/tak_threads_pending.json)",
    )
    parser.add_argument(
        "--blog-history",
        type=Path,
        default=ROOT / "data" / "blog_publish_log.json",
        help="Blog 게시 이력 경로 (기본값: data/blog_publish_log.json)",
    )
    parser.add_argument(
        "--threads-history",
        type=Path,
        default=ROOT / "data" / "threads_publish_log.json",
        help="Threads 게시 이력 경로 (기본값: data/threads_publish_log.json)",
    )
    parser.add_argument(
        "--youtube-history",
        type=Path,
        default=ROOT / "data" / "youtube_publish_log.json",
        help="YouTube 업로드 이력 경로 (기본값: data/youtube_publish_log.json)",
    )
    parser.add_argument(
        "--shorts-scripts-dir",
        type=Path,
        default=ROOT / "data" / "shorts_scripts",
        help="ShortsScript JSON 디렉터리 (기본값: data/shorts_scripts)",
    )
    parser.add_argument(
        "--shorts-dir",
        type=Path,
        default=ROOT / "data" / "shorts",
        help="렌더링된 MP4 디렉터리, 참고 정보 표시용 (기본값: data/shorts)",
    )
    parser.add_argument(
        "--report-output",
        type=Path,
        default=ROOT / "docs" / "publish_readiness_latest.md",
        help="Publish Readiness Markdown 보고서 저장 경로 (기본값: docs/publish_readiness_latest.md)",
    )
    parser.add_argument(
        "--no-report",
        action="store_true",
        help="Markdown 보고서를 저장하지 않고 터미널 요약만 출력한다.",
    )
    parser.add_argument(
        "--fail-on-error",
        action="store_true",
        help="ERROR로 분류된 레코드가 하나라도 있으면 종료 코드를 1로 반환한다(기본값: 항상 0).",
    )
    args = parser.parse_args(argv)

    try:
        archive_records = load_archive(args.archive)
    except (OSError, ValueError) as err:
        print(f"오류: MEDIA archive를 읽을 수 없습니다: {err}", file=sys.stderr)
        return 1

    try:
        knowledge_records = load_knowledge_records(args.knowledge)
    except (OSError, ValueError) as err:
        print(f"오류: KNOWLEDGE 파일을 읽을 수 없습니다: {err}", file=sys.stderr)
        return 1
    knowledge_by_id = {record.id: record for record in knowledge_records}

    try:
        threads_pending = tuple(load_pending(args.threads_pending))
    except ValueError as err:
        print(f"오류: Threads pending 파일을 읽을 수 없습니다: {err}", file=sys.stderr)
        return 1

    inputs = PublishAuditInputs(
        knowledge_by_id=knowledge_by_id,
        blog_history=PublishHistory(args.blog_history),
        threads_history=PublishHistory(args.threads_history),
        threads_pending=threads_pending,
        youtube_history=YouTubeUploadHistory(args.youtube_history),
        shorts_scripts_path=args.shorts_scripts_dir,
        shorts_dir_path=args.shorts_dir,
    )

    results = audit_archive(archive_records, inputs=inputs)
    summary = summarize(results)

    print("=== Publish Readiness 요약 ===")
    print(f"전체 Production 콘텐츠: {len(results)}")
    print(f"게시 가능(READY): {summary[READY]}")
    print(f"사람 검토 필요(NEEDS_HUMAN_REVIEW): {summary[NEEDS_HUMAN_REVIEW]}")
    print(f"게시 차단(BLOCKED): {summary[BLOCKED]}")
    print(f"이미 게시됨(ALREADY_PUBLISHED): {summary[ALREADY_PUBLISHED]}")
    print(f"정정본으로 대체됨(SUPERSEDED): {summary[SUPERSEDED]}")
    print(f"오류(ERROR): {summary[ERROR]}")
    print()

    ready_results = [r for r in results if r.status == READY]
    if ready_results:
        print("--- READY(지금 바로 게시 준비 가능) ---")
        for r in ready_results:
            print(f"  [{r.platform}] {r.content_id} - {r.title}")
        print()

    review_results = [r for r in results if r.status == NEEDS_HUMAN_REVIEW]
    if review_results:
        print("--- NEEDS_HUMAN_REVIEW(게시 전 사람의 최종 확인 필요) ---")
        for r in review_results:
            print(f"  [{r.platform}] {r.content_id} - {r.title} ({'; '.join(r.reasons)})")
        print()

    superseded_results = [r for r in results if r.status == SUPERSEDED]
    if superseded_results:
        print("--- SUPERSEDED(정정본으로 대체됨 - 활성 후보 아님) ---")
        for r in superseded_results:
            print(f"  [{r.platform}] {r.content_id} - {r.title} ({'; '.join(r.reasons)})")
        print()

    error_results = [r for r in results if r.status == ERROR]
    if error_results:
        print("--- ERROR(데이터를 직접 조사해야 함) ---")
        for r in error_results:
            print(f"  [{r.platform}] {r.content_id}: {'; '.join(r.reasons)}")
        print()

    if not args.no_report:
        try:
            save_readiness_report(results, args.report_output)
        except OSError as err:
            print(f"오류: Publish Readiness 보고서 저장에 실패했습니다: {err}", file=sys.stderr)
            return 1
        print(f"Publish Readiness 보고서 저장 완료: {args.report_output}")

    if args.fail_on_error and summary[ERROR] > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
