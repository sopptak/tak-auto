#!/usr/bin/env python3
"""승인 KNOWLEDGE로부터 하루치 네이버 블로그 게시 후보(Blog Publishing Pack)를 생성하는 CLI.

이 스크립트는 네이버 블로그에 자동으로 게시하지 않는다. 네이버 로그인 자동화, 브라우저
자동 게시, 캡차 우회는 구현하지 않으며 앞으로도 이 스크립트의 책임이 아니다. 대신 TAK MEDIA가
이미 생성/검증한 BlogDraft 중 아직 게시 이력에 없는 후보를 최대 N개(기본 5개) 골라, 사람이
네이버 블로그에 직접 복사/붙여넣기하고 예약 발행하기 좋은 Markdown 파일로 저장한다.

    tak_brain.load_knowledge_records / select_approved   (TAK BRAIN)
    content_engine.pipeline.run_media_batch              (TAK MEDIA, 기존 로직 그대로)
    content_engine.blog_publish_pack.build_blog_publish_pack / save_markdown

실제 "게시 완료" 기록은 이 스크립트가 하지 않는다. 사람이 실제로 네이버에 게시를 마친 뒤
scripts/mark_blog_published.py로 명시적으로 기록해야 다음 실행에서 같은 콘텐츠가 후보에서
빠진다.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_engine.blog_publish_pack import (
    DEFAULT_MAX_CANDIDATES,
    build_blog_publish_pack,
    build_blog_publish_pack_from_archive,
    save_markdown,
)
from content_engine.llm_provider import LLMConfigurationError, OpenAICompatibleRewriteProvider
from content_engine.media_archive import archive_report, load_archive
from content_engine.pipeline import run_media_batch
from content_engine.publish_history import PublishHistory
from tak_brain import load_knowledge_records, select_approved


def _run_from_archive(args: argparse.Namespace, knowledge_records: list) -> int:
    """--from-archive 모드: LLM을 호출하지 않고, 이미 MEDIA Dashboard에서 승인된
    archive 항목만으로 Publishing Pack을 만든다. run_media_batch/archive_report/
    --output 저장은 이 모드에서 전혀 실행하지 않는다(새로 생성할 것이 없으므로)."""
    archive_records = load_archive(args.archive)
    if args.id:
        knowledge_ids = {record.id for record in knowledge_records}
        archive_records = [record for record in archive_records if record.knowledge_id in knowledge_ids]

    history = PublishHistory(args.history)
    items = build_blog_publish_pack_from_archive(archive_records, knowledge_records, history, max_count=args.max)

    try:
        save_markdown(items, args.pack_output)
    except OSError as err:
        print(f"오류: Blog Publishing Pack 저장에 실패했습니다: {err}", file=sys.stderr)
        return 1

    review_count = sum(1 for item in items if item.review_required)
    print(
        f"[--from-archive] Blog Publishing Pack 생성 완료: {len(items)}건 "
        f"(사람 확인 필요 {review_count}건) → {args.pack_output}"
    )
    print("안내: 네이버 블로그 게시는 자동으로 수행되지 않습니다. 사람이 내용을 검토한 뒤")
    print("네이버 블로그에 직접 복사/붙여넣기하고 예약 발행해야 합니다.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="TAK AUTO 네이버 블로그 게시 후보(Blog Publishing Pack) 생성기"
    )
    parser.add_argument(
        "--knowledge",
        type=Path,
        default=ROOT / "data" / "tak_brain_knowledge.json",
        help="읽기 전용 KNOWLEDGE JSON 경로 (기본값: data/tak_brain_knowledge.json)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data" / "tak_media_batch_blog.json",
        help=(
            "TAK MEDIA 배치 결과 저장 경로 (기본값: data/tak_media_batch_blog.json). "
            "매 실행마다 새로 생성/덮어쓰는 휘발성 파일이며 git에 커밋하지 않는다."
        ),
    )
    parser.add_argument(
        "--history",
        type=Path,
        default=ROOT / "data" / "blog_publish_log.json",
        help=(
            "Blog 게시 이력 JSON 경로 (기본값: data/blog_publish_log.json). "
            "Threads 이력(data/threads_publish_log.json)과는 별도 파일이다."
        ),
    )
    parser.add_argument(
        "--pack-output",
        type=Path,
        default=ROOT / "data" / "blog_publish_pack_daily.md",
        help="사람이 복사/붙여넣기할 Markdown 결과 경로 (기본값: data/blog_publish_pack_daily.md)",
    )
    parser.add_argument(
        "--archive",
        type=Path,
        default=ROOT / "data" / "tak_media_archive.json",
        help=(
            "TAK MEDIA 배치 결과 전체(Pack에 포함되지 않는 Shorts/Threads, rejected/error "
            "포함)를 content_id 기준으로 누적 보존하는 아카이브 경로 "
            "(기본값: data/tak_media_archive.json)"
        ),
    )
    parser.add_argument(
        "--max",
        type=int,
        default=DEFAULT_MAX_CANDIDATES,
        help=f"오늘 생성할 Blog 게시 후보의 최대 개수 (기본값: {DEFAULT_MAX_CANDIDATES})",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="TAK MEDIA 단계에서 처리할 승인 KNOWLEDGE 최대 개수 제한(선택)",
    )
    parser.add_argument(
        "--id",
        type=str,
        default=None,
        help=(
            "특정 KNOWLEDGE ID 1건만 대상으로 실행(선택, 기본값: 승인된 전체 KNOWLEDGE). "
            "scripts/run_media_batch.py --id와 동일한 관례 - 다른 KNOWLEDGE는 LLM 호출 대상이 되지 않는다."
        ),
    )
    parser.add_argument(
        "--from-archive",
        action="store_true",
        help=(
            "TAK MEDIA를 다시 실행(LLM 호출)하지 않고, 이미 MEDIA Dashboard에서 사람이 "
            "승인(review_status == approved)한 --archive의 Blog 항목만으로 Publishing "
            "Pack을 만든다(5-29). 이 모드에서는 --output/--limit이 쓰이지 않는다."
        ),
    )
    args = parser.parse_args(argv)

    try:
        records = load_knowledge_records(args.knowledge)
    except (OSError, ValueError) as err:
        print(f"오류: KNOWLEDGE 파일을 읽을 수 없습니다: {err}", file=sys.stderr)
        return 1

    if args.id:
        records = [record for record in records if record.id == args.id]
        if not records:
            print(f"오류: KNOWLEDGE ID를 찾을 수 없습니다: {args.id}", file=sys.stderr)
            return 1

    if args.from_archive:
        return _run_from_archive(args, records)

    approved = list(select_approved(records))
    if args.limit is not None and args.limit > 0:
        approved = approved[: args.limit]

    if not approved:
        print("승인된 KNOWLEDGE가 없습니다. 오늘 생성할 Blog 게시 후보가 없어 정상 종료합니다.")
        history = PublishHistory(args.history)
        save_markdown((), args.pack_output)
        print(f"빈 Blog Publishing Pack 저장 완료: {args.pack_output}")
        return 0

    print(f"TAK BRAIN: 승인 KNOWLEDGE {len(approved)}건 확인")

    try:
        provider = OpenAICompatibleRewriteProvider.from_environment()
    except LLMConfigurationError as err:
        print(f"오류: TAK MEDIA LLM 설정이 올바르지 않습니다: {err}", file=sys.stderr)
        return 1

    print("TAK MEDIA: 배치 실행 중 (콘텐츠 생성 + LLM 재작성 + 검증)...")
    try:
        report = run_media_batch(approved, provider=provider)
    except Exception as err:
        print(
            f"오류: TAK MEDIA 배치 실행에 실패했습니다: {type(err).__name__}: {err}",
            file=sys.stderr,
        )
        return 1

    print(
        "TAK MEDIA 완료: "
        f"총 Draft {report.total_draft_count}건 "
        f"(valid {report.valid_count}, rejected {report.rejected_count}, error {report.error_count})"
    )

    # Pack에는 Blog valid 항목 일부만 들어간다. 나머지(Shorts/Threads, rejected/error
    # 포함)가 그냥 버려지지 않도록 배치 결과 전체를 먼저 아카이브에 남긴다(5-27 설계 문서).
    try:
        archive_report(report, args.archive)
    except OSError as err:
        print(f"오류: 배치 결과 아카이브 저장에 실패했습니다: {err}", file=sys.stderr)
        return 1

    try:
        report.save_json(args.output)
    except OSError as err:
        print(f"오류: 배치 결과 저장에 실패했습니다: {err}", file=sys.stderr)
        return 1

    print(f"배치 결과 저장 완료: {args.output}")

    history = PublishHistory(args.history)
    items = build_blog_publish_pack(report, approved, history, max_count=args.max)

    try:
        save_markdown(items, args.pack_output)
    except OSError as err:
        print(f"오류: Blog Publishing Pack 저장에 실패했습니다: {err}", file=sys.stderr)
        return 1

    review_count = sum(1 for item in items if item.review_required)
    print(
        f"Blog Publishing Pack 생성 완료: {len(items)}건 "
        f"(사람 확인 필요 {review_count}건) → {args.pack_output}"
    )
    print("안내: 네이버 블로그 게시는 자동으로 수행되지 않습니다. 사람이 내용을 검토한 뒤")
    print("네이버 블로그에 직접 복사/붙여넣기하고 예약 발행해야 합니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
