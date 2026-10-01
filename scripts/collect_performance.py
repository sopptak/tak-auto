#!/usr/bin/env python3
"""승인/발행된 콘텐츠 1건의 실제 채널 성과(조회수/좋아요 등)를 수집해
data/tak_performance.json에 스냅샷으로 저장하는 CLI(6-01).

이 스크립트는 import만으로 외부 API를 호출하지 않는다. 실제 동작은 항상
`main()` 실행으로 시작한다. `--dry-run`은 실제 네트워크 호출과 저장을 하지 않는다.
scheduled Threads collection은 `--scheduled`로 기존 publish history, Performance
store, Threads Insights collector를 재사용한다. GitHub Actions live 호출에는 전용
opt-in 환경변수와 `--confirm-live`가 모두 필요하다.

6-02 안전장치: platform=threads/youtube는 ``--dry-run``도 ``--confirm-live``도
주지 않으면 **아무 것도 하지 않고 거부한다**(에러 메시지만 출력하고 종료 코드
1). 6-01에서 이 Codespace 환경에 실제 THREADS_ACCESS_TOKEN/YOUTUBE_*가 이미
존재한다는 사실이 확인됐기 때문에, "--dry-run을 깜빡 빼먹은 실행"이 곧바로
실제 API 호출로 이어지는 위험을 막기 위함이다. 실제 호출을 원하면 명시적으로
``--confirm-live``를 줘야 한다. GitHub Actions 환경(``GITHUB_ACTIONS=true``)에서는
``--confirm-live``를 줘도 기본 거부한다. 오직 versioned scheduled workflow가
``TAK_PERFORMANCE_ALLOW_GITHUB_ACTIONS=true``를 명시적으로 전달할 때만 허용한다.
platform=blog는 네트워크 호출이 아예 없으므로(content_engine/performance/blog.py)
이 게이트의 적용을 받지 않는다.

사용 예:
    # Blog(manual) - 네이버 블로그 관리자 페이지에서 사람이 직접 확인한 숫자
    python3 scripts/collect_performance.py --platform blog \\
        --content-id content-abc123 --knowledge-id knowledge-xyz \\
        --published-at 2026-09-15T00:00:00+00:00 \\
        --metric views=850 --metric likes=12

    # Threads - 실제 API 호출(THREADS_ACCESS_TOKEN 필요, --confirm-live 필수)
    python3 scripts/collect_performance.py --platform threads \\
        --content-id content-abc123 --knowledge-id knowledge-xyz \\
        --published-at 2026-09-15T00:00:00+00:00 \\
        --external-id 18114019807999154 --confirm-live

    # dry-run(입력 검증만, 네트워크/저장 없음 - 기존과 동일)
    python3 scripts/collect_performance.py --platform threads \\
        --content-id content-abc123 --knowledge-id knowledge-xyz \\
        --published-at 2026-09-15T00:00:00+00:00 \\
        --external-id 18114019807999154 --dry-run
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timezone
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_engine.performance.blog import build_manual_blog_performance_record
from content_engine.media_archive import load_archive
from content_engine.performance.schedule import select_due_threads_targets
from content_engine.performance.store import append_snapshot, load_snapshots
from content_engine.performance.threads import collect_threads_performance
from content_engine.performance.youtube import collect_youtube_performance
from content_engine.publish_history import PublishHistory
from content_engine.threads_publisher import ThreadsAPIError, ThreadsConfigurationError, ThreadsClient
from content_engine.threads_review import load_pending
from content_engine.youtube_publisher import YouTubeConfigurationError, YouTubeClient


def _parse_metric(raw: str) -> tuple[str, int]:
    if "=" not in raw:
        raise argparse.ArgumentTypeError(f"--metric은 key=value 형태여야 합니다: {raw!r}")
    key, _, value_text = raw.partition("=")
    key = key.strip()
    if not key:
        raise argparse.ArgumentTypeError(f"--metric의 key가 비어 있습니다: {raw!r}")
    try:
        value = int(value_text.strip())
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"--metric의 value는 정수여야 합니다: {raw!r}") from error
    return key, value


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="승인/발행된 콘텐츠의 채널별 성과를 수집해 성과 저장소에 스냅샷으로 추가"
    )
    parser.add_argument(
        "--scheduled",
        action="store_true",
        help="publish history에서 lineage가 확인된 Threads 게시물의 due 24h/72h snapshot을 수집합니다.",
    )
    parser.add_argument("--platform", choices=("threads", "youtube", "blog"))
    parser.add_argument("--content-id", help="archive/발행 이력의 content_id")
    parser.add_argument("--knowledge-id", help="원본 KNOWLEDGE ID")
    parser.add_argument("--published-at", help="원본 발행 시각(ISO 8601)")
    parser.add_argument(
        "--external-id",
        default="",
        help="platform별 원본 식별자: threads media id / youtube video id / blog url",
    )
    parser.add_argument("--title", default="", help="콘텐츠 제목(선택, 기록용)")
    parser.add_argument(
        "--metric",
        dest="metrics",
        action="append",
        type=_parse_metric,
        default=None,
        help="platform=blog 전용 수동 입력값. key=value 형태로 여러 번 지정 가능 "
        "(예: --metric views=850 --metric likes=12)",
    )
    parser.add_argument(
        "--collected-at",
        default=None,
        help="성과 수집 시각(ISO 8601). 생략하면 실행 시각(UTC)을 사용한다.",
    )
    parser.add_argument(
        "--store",
        type=Path,
        default=ROOT / "data" / "tak_performance.json",
        help="성과 저장소 경로 (기본값: data/tak_performance.json)",
    )
    parser.add_argument(
        "--publish-history",
        type=Path,
        default=ROOT / "data" / "threads_publish_log.json",
        help="scheduled 모드의 실제 Threads 발행 이력 경로",
    )
    parser.add_argument(
        "--production-archive",
        type=Path,
        default=ROOT / "data" / "tak_media_archive.json",
        help="scheduled 모드의 Production Archive 경로",
    )
    parser.add_argument(
        "--threads-pending",
        type=Path,
        default=ROOT / "data" / "tak_threads_pending.json",
        help="scheduled 모드의 Threads 게시 완료 상태 경로",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="실제 API 호출(threads/youtube)과 저장을 하지 않고, 무엇을 할지만 출력한다.",
    )
    parser.add_argument(
        "--confirm-live",
        action="store_true",
        help="platform=threads/youtube에서 실제 API를 호출하겠다는 명시적 동의(6-02). "
        "--dry-run도 이 플래그도 없으면 threads/youtube는 아무 것도 하지 않고 거부한다.",
    )
    return parser


def _is_running_in_github_actions(environ: Mapping[str, str] | None = None) -> bool:
    values = os.environ if environ is None else environ
    return values.get("GITHUB_ACTIONS", "").strip().lower() == "true"


def _guard_live_network_call(
    platform: str,
    dry_run: bool,
    confirm_live: bool,
    environ: Mapping[str, str] | None = None,
) -> str | None:
    """threads/youtube 실제 API 호출을 시도해도 되는지 판단한다.

    문제가 없으면 None, 거부해야 하면 사람이 읽을 오류 메시지를 반환한다 - 이
    함수는 어떤 네트워크 호출도, 어떤 클라이언트 생성도 하지 않는다(순수 판단
    함수라 인자 조합만으로 단위 테스트할 수 있다).
    """
    if dry_run:
        return None
    values = os.environ if environ is None else environ
    if _is_running_in_github_actions(values) and values.get("TAK_PERFORMANCE_ALLOW_GITHUB_ACTIONS") != "true":
        return (
            "GitHub Actions 환경의 실제 API 호출은 전용 opt-in 없이는 거부됩니다. "
            "로컬에서는 --confirm-live를 사용하세요."
        )
    if not confirm_live:
        return (
            f"platform={platform}는 --dry-run 또는 --confirm-live 중 하나를 반드시 지정해야 합니다. "
            "이 Codespace 환경에는 실제 API 자격증명이 있을 수 있어, 실수로 실제 호출이 되는 것을 "
            "막기 위한 안전장치입니다."
        )
    return None


def _run_scheduled(args: argparse.Namespace) -> int:
    try:
        history_records = PublishHistory(args.publish_history).load()
        production_records = load_archive(args.production_archive)
        pending_drafts = load_pending(args.threads_pending)
        performance_records = load_snapshots(args.store)
    except (OSError, ValueError) as error:
        print(f"오류: scheduled 성과 수집 입력을 읽을 수 없습니다: {error}", file=sys.stderr)
        return 1

    targets = select_due_threads_targets(
        history_records,
        production_records,
        pending_drafts,
        performance_records,
        now=datetime.now(timezone.utc),
    )
    if not targets:
        print(
            "측정 대기/완료: 현재 due target 없음 "
            "(24h/72h 미도달, 해당 window 이미 수집, 또는 lineage 검증 제외)."
        )
        return 0

    for target in targets:
        print(
            f"대상: content_id={target.content_id}, generation_id={target.generation_id}, "
            f"external_post_id={target.external_post_id}, window={target.measurement_window}"
        )

    if args.dry_run:
        print(f"[dry-run] due target {len(targets)}건. API 호출/저장 없음.")
        return 0

    guard_error = _guard_live_network_call("threads", False, args.confirm_live)
    if guard_error is not None:
        print(f"오류: {guard_error}", file=sys.stderr)
        return 1

    try:
        client = ThreadsClient.from_environment()
    except ThreadsConfigurationError as error:
        print(f"오류: {error}", file=sys.stderr)
        return 1

    failed = False
    for target in targets:
        try:
            record = collect_threads_performance(
                client,
                media_id=target.external_post_id,
                content_id=target.content_id,
                knowledge_id=target.knowledge_id,
                published_at=target.published_at,
                metric_collected_at=datetime.now(timezone.utc).isoformat(),
                title=target.title,
                generation_id=target.generation_id,
                measurement_window=target.measurement_window,
            )
            record = replace(record, metric_collected_at=datetime.now(timezone.utc).isoformat())
            added = append_snapshot(args.store, record)
        except (ThreadsAPIError, OSError, ValueError) as error:
            failed = True
            print(
                f"수집 실패: content_id={target.content_id}, window={target.measurement_window}: "
                f"{type(error).__name__}: {error}",
                file=sys.stderr,
            )
            continue

        if added:
            print(
                f"수집 완료: content_id={record.content_id}, window={record.measurement_window}, "
                f"metrics={record.metrics}, unavailable={record.unavailable_metrics}"
            )
        else:
            print(
                f"중복 건너뜀: content_id={record.content_id}, "
                f"external_post_id={record.external_post_id}, window={record.measurement_window}"
            )

    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.scheduled:
        if any(
            (
                args.platform,
                args.content_id,
                args.knowledge_id,
                args.published_at,
                args.external_id,
                args.title,
                args.metrics,
                args.collected_at,
            )
        ):
            parser.error("--scheduled는 개별 콘텐츠 입력 옵션과 함께 사용할 수 없습니다.")
        return _run_scheduled(args)

    if not all((args.platform, args.content_id, args.knowledge_id, args.published_at)):
        parser.error("수동 수집에는 --platform, --content-id, --knowledge-id, --published-at이 필요합니다.")

    collected_at = args.collected_at or datetime.now(timezone.utc).isoformat()

    if args.platform == "blog":
        metrics = dict(args.metrics or [])
        if not metrics:
            print("오류: platform=blog는 --metric key=value를 최소 1개 이상 지정해야 합니다.", file=sys.stderr)
            return 1
        if args.dry_run:
            print(f"[dry-run] Blog 수동 성과 기록 예정: content_id={args.content_id}, metrics={metrics}")
            return 0
        record = build_manual_blog_performance_record(
            content_id=args.content_id,
            knowledge_id=args.knowledge_id,
            published_at=args.published_at,
            metric_collected_at=collected_at,
            metrics=metrics,
            title=args.title,
            blog_url=args.external_id,
        )
        added = append_snapshot(args.store, record)
        _print_result(added, record, args.store)
        return 0

    if not args.external_id:
        print(f"오류: platform={args.platform}는 --external-id(원본 게시물/영상 id)가 필요합니다.", file=sys.stderr)
        return 1

    if args.platform == "threads":
        guard_error = _guard_live_network_call("threads", args.dry_run, args.confirm_live)
        if guard_error is not None:
            print(f"오류: {guard_error}", file=sys.stderr)
            return 1
        if args.dry_run:
            print(
                f"[dry-run] Threads insights 조회 예정: content_id={args.content_id}, "
                f"media_id={args.external_id} (실제 API 호출하지 않음)"
            )
            return 0
        try:
            client = ThreadsClient.from_environment()
        except ThreadsConfigurationError as error:
            print(f"오류: {error}", file=sys.stderr)
            return 1
        record = collect_threads_performance(
            client,
            media_id=args.external_id,
            content_id=args.content_id,
            knowledge_id=args.knowledge_id,
            published_at=args.published_at,
            metric_collected_at=collected_at,
            title=args.title,
        )
        added = append_snapshot(args.store, record)
        _print_result(added, record, args.store)
        return 0

    # platform == "youtube"
    guard_error = _guard_live_network_call("youtube", args.dry_run, args.confirm_live)
    if guard_error is not None:
        print(f"오류: {guard_error}", file=sys.stderr)
        return 1
    if args.dry_run:
        print(
            f"[dry-run] YouTube statistics 조회 예정: content_id={args.content_id}, "
            f"video_id={args.external_id} (실제 API 호출하지 않음)"
        )
        return 0
    try:
        client = YouTubeClient.from_environment()
    except YouTubeConfigurationError as error:
        print(f"오류: {error}", file=sys.stderr)
        return 1
    record = collect_youtube_performance(
        client,
        video_id=args.external_id,
        content_id=args.content_id,
        knowledge_id=args.knowledge_id,
        published_at=args.published_at,
        metric_collected_at=collected_at,
        title=args.title,
    )
    added = append_snapshot(args.store, record)
    _print_result(added, record, args.store)
    return 0


def _print_result(added: bool, record, store_path: Path) -> None:
    if added:
        print(f"성공: {record.platform} 성과 스냅샷 저장 완료 (content_id={record.content_id}, metrics={record.metrics})")
        print(f"저장소: {store_path}")
    else:
        if record.measurement_window:
            print(
                f"안내: 동일한 (content_id={record.content_id}, external_post_id="
                f"{record.external_post_id or record.external_id}, window={record.measurement_window}) "
                "스냅샷이 이미 있어 저장을 건너뛰었습니다(중복 방지)."
            )
        else:
            print(
                f"안내: 동일한 (content_id={record.content_id}, metric_collected_at={record.metric_collected_at}) "
                "스냅샷이 이미 있어 저장을 건너뛰었습니다(중복 방지)."
            )


if __name__ == "__main__":
    raise SystemExit(main())
