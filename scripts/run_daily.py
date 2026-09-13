#!/usr/bin/env python3
"""TAK BRAIN → TAK MEDIA → Threads 전체 흐름을 하나로 잇는 일일 실행 오케스트레이터.

이 스크립트는 새 로직을 구현하지 않는다. 각 단계는 이미 구현되고 테스트된 기존 함수를
그대로 호출만 한다.

    tak_brain.load_knowledge_records / select_approved   (TAK BRAIN)
    content_engine.pipeline.run_media_batch              (TAK MEDIA)
    content_engine.llm_provider.OpenAICompatibleRewriteProvider.from_environment
    scripts.publish_threads.main(["--auto", ...])         (Threads 게시 + 게시 이력)

GitHub Actions/cron/Secrets 연동은 이 스크립트의 책임이 아니다. 이 스크립트는 단일 진입점
으로서, 실행 환경(로컬 또는 CI)에 필요한 환경변수(THREADS_ACCESS_TOKEN, TAK_MEDIA_LLM_*)가
이미 준비되어 있다고 가정한다.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_engine.llm_provider import LLMConfigurationError, OpenAICompatibleRewriteProvider
from content_engine.pipeline import run_media_batch
from scripts.publish_threads import main as publish_threads_main
from tak_brain import load_knowledge_records, select_approved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="TAK BRAIN -> TAK MEDIA -> Threads 일일 실행 오케스트레이터"
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
        default=ROOT / "data" / "tak_media_batch_daily.json",
        help=(
            "TAK MEDIA 배치 결과 저장 경로 (기본값: data/tak_media_batch_daily.json). "
            "매 실행마다 새로 생성/덮어쓰는 휘발성 파일이며 git에 커밋하지 않는다."
        ),
    )
    parser.add_argument(
        "--history",
        type=Path,
        default=ROOT / "data" / "threads_publish_log.json",
        help="게시 이력 JSON 경로 (기본값: data/threads_publish_log.json)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Threads API 게시만 건너뛴다(publish_threads.py --dry-run으로 위임). "
            "TAK MEDIA 단계는 dry-run 여부와 무관하게 동일한 provider로 실제 LLM을 호출한다."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="처리할 승인 KNOWLEDGE 최대 개수 제한",
    )
    parser.add_argument(
        "--id",
        type=str,
        default=None,
        help="특정 KNOWLEDGE ID 1건만 대상으로 실행",
    )
    args = parser.parse_args(argv)

    # 1단계: TAK BRAIN - 승인된 KNOWLEDGE 로드
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

    approved = list(select_approved(records))
    if args.limit is not None and args.limit > 0:
        approved = approved[: args.limit]

    if not approved:
        print("승인된 KNOWLEDGE가 없습니다. 오늘 처리할 콘텐츠가 없어 정상 종료합니다.")
        return 0

    print(f"TAK BRAIN: 승인 KNOWLEDGE {len(approved)}건 확인")

    # 2단계: TAK MEDIA - provider는 반드시 실제 LLM 어댑터를 명시적으로 생성한다.
    # dry-run이라는 이유로 MockRewriteProvider로 조용히 바꾸지 않는다: run_daily.py의
    # --dry-run은 "Threads API 게시"만 건너뛰는 스위치이며, TAK MEDIA 재작성 단계는
    # 운영 경로와 동일하게 실제 LLM을 호출한다.
    if args.dry_run:
        print(
            "안내: --dry-run은 Threads 게시 단계만 건너뜁니다. "
            "TAK MEDIA 단계는 이 provider로 실제 LLM API를 호출합니다."
        )

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

    # 3단계: 배치 결과 저장 (휘발성 파일, git 비영속)
    try:
        report.save_json(args.output)
    except OSError as err:
        print(f"오류: 배치 결과 저장에 실패했습니다: {err}", file=sys.stderr)
        return 1

    print(f"배치 결과 저장 완료: {args.output}")

    # 4단계: Threads 게시 - 기존 publish_threads.py의 --auto 로직을 그대로 재사용한다.
    # 자동 선정/게시 이력 기록 로직은 여기서 다시 구현하지 않는다.
    publish_argv = [
        "--input", str(args.output),
        "--auto",
        "--history", str(args.history),
    ]
    if args.dry_run:
        publish_argv.append("--dry-run")

    print("Threads 게시 단계 실행 중 (scripts/publish_threads.py --auto)...")
    return publish_threads_main(publish_argv)


if __name__ == "__main__":
    raise SystemExit(main())
