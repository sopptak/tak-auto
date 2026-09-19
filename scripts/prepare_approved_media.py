#!/usr/bin/env python3
"""승인된(review_status=='approved') MEDIA archive 항목을 채널별 downstream
단계까지 한 번에 준비하는 얇은 오케스트레이터 CLI(5-29).

이 스크립트는 새 비즈니스 로직을 만들지 않는다 - 이미 각자 단독으로 안전하게
동작하는(외부 API 호출 없는) 기존 CLI 2개를 순서대로 함수 호출할 뿐이다
(scripts/run_daily.py가 scripts.publish_threads.main(...)을 함수로 호출하는
기존 관례와 동일):

    scripts.generate_blog_publish_pack.main([..., "--from-archive"])
    scripts.generate_approved_shorts_script.main([...])

Threads는 이 스크립트가 "준비"할 것이 없다 - MEDIA 승인 시점에 이미
content_engine.threads_review.upsert_pending()으로 자동 연결되어 있다
(docs/5-29_media_operational_pipeline.md 4장 "결정 1" 참고). 대신 현재
data/tak_threads_pending.json의 상태별 건수를 읽기 전용으로 요약 출력한다.

이 스크립트가 절대 하지 않는 것:
    - 실제 발행(Threads API, YouTube 업로드, Naver 게시) - 아래 두 하위 CLI
      모두 발행 코드를 import하지 않는다(각자의 docstring/구현 참고).
    - LLM 호출 - "--from-archive"/Shorts CLI 둘 다 이미 archive에 저장된
      결과만 읽는다.
    - MP4 렌더링 - content_engine.shorts_renderer는 이 스크립트가 참조하지
      않는다.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_engine.threads_review import load_pending
from scripts.generate_approved_shorts_script import main as generate_shorts_script_main
from scripts.generate_blog_publish_pack import main as generate_blog_publish_pack_main


def _print_threads_summary(pending_path: Path) -> None:
    drafts = load_pending(pending_path)
    counts: dict[str, int] = {}
    for draft in drafts:
        counts[draft.status] = counts.get(draft.status, 0) + 1

    print("[Threads] 준비할 작업 없음 (MEDIA 승인 시점에 이미 pending queue로 자동 연결됨)")
    if not drafts:
        print(f"[Threads] 현재 {pending_path}에 draft가 없습니다.")
        return
    summary = ", ".join(f"{status} {count}건" for status, count in sorted(counts.items()))
    print(f"[Threads] 현재 상태: {summary} (총 {len(drafts)}건, 경로: {pending_path})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "승인된 MEDIA archive 항목을 Blog Publishing Pack + Shorts ShortsScript로 "
            "한 번에 준비하는 오케스트레이터 (실제 발행/렌더링/LLM 호출 없음)"
        )
    )
    parser.add_argument(
        "--knowledge",
        type=Path,
        default=ROOT / "data" / "tak_brain_knowledge.json",
        help="읽기 전용 KNOWLEDGE JSON 경로 (기본값: data/tak_brain_knowledge.json)",
    )
    parser.add_argument(
        "--archive",
        type=Path,
        default=ROOT / "data" / "tak_media_archive.json",
        help="읽기 전용 MEDIA archive 경로 (기본값: data/tak_media_archive.json)",
    )
    parser.add_argument(
        "--blog-history",
        type=Path,
        default=ROOT / "data" / "blog_publish_log.json",
        help="Blog 게시 이력 경로 (기본값: data/blog_publish_log.json)",
    )
    parser.add_argument(
        "--blog-pack-output",
        type=Path,
        default=ROOT / "data" / "blog_publish_pack_daily.md",
        help="Blog Publishing Pack Markdown 저장 경로 (기본값: data/blog_publish_pack_daily.md)",
    )
    parser.add_argument(
        "--blog-max",
        type=int,
        default=None,
        help="오늘 생성할 Blog 게시 후보의 최대 개수 (기본값: generate_blog_publish_pack.py의 기본값)",
    )
    parser.add_argument(
        "--shorts-output-dir",
        type=Path,
        default=ROOT / "data" / "shorts_scripts",
        help="ShortsScript JSON 저장 디렉터리 (기본값: data/shorts_scripts)",
    )
    parser.add_argument(
        "--threads-pending",
        type=Path,
        default=ROOT / "data" / "tak_threads_pending.json",
        help="Threads pending queue 경로, 읽기 전용 요약 출력용 (기본값: data/tak_threads_pending.json)",
    )
    args = parser.parse_args(argv)

    print("=== 1/3: Blog Publishing Pack 준비 (--from-archive) ===")
    blog_argv = [
        "--knowledge", str(args.knowledge),
        "--archive", str(args.archive),
        "--history", str(args.blog_history),
        "--pack-output", str(args.blog_pack_output),
        "--from-archive",
    ]
    if args.blog_max is not None:
        blog_argv.extend(["--max", str(args.blog_max)])
    blog_exit_code = generate_blog_publish_pack_main(blog_argv)

    print("\n=== 2/3: Shorts ShortsScript 준비 ===")
    shorts_exit_code = generate_shorts_script_main(
        [
            "--archive", str(args.archive),
            "--output-dir", str(args.shorts_output_dir),
        ]
    )

    print("\n=== 3/3: Threads pending 현황 (읽기 전용) ===")
    _print_threads_summary(args.threads_pending)

    exit_code = max(blog_exit_code, shorts_exit_code)
    print(f"\n완료 (종료 코드: {exit_code}). 실제 발행/업로드/게시는 이 스크립트가 하지 않습니다.")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
