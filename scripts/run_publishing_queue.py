#!/usr/bin/env python3
"""Run scheduled publishing queue work; external publishing is opt-in and adapter-gated."""
from __future__ import annotations

import argparse
import importlib
import os
from pathlib import Path
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_engine.publishing_queue import PublishingQueue


def load_publisher(spec: str):
    """Load an explicitly configured ``python.module:function`` publisher adapter."""
    module_name, separator, function_name = spec.partition(":")
    if not separator or not module_name or not function_name:
        raise ValueError("TAK_AUTO_PUBLISHER는 '모듈:함수' 형식이어야 합니다.")
    publisher = getattr(importlib.import_module(module_name), function_name, None)
    if not callable(publisher):
        raise ValueError("TAK_AUTO_PUBLISHER가 호출 가능한 함수를 가리키지 않습니다.")
    return publisher


def run_once(queue_path: Path | str, *, enabled: bool, publisher_spec: str = "", now=None):
    if not enabled:
        return []
    if not publisher_spec:
        raise RuntimeError("게시 기능이 켜졌지만 플랫폼 게시 어댑터가 설정되지 않았습니다. 작업은 실행하지 않았습니다.")
    publisher = load_publisher(publisher_spec)
    return PublishingQueue(queue_path).run_due(publisher, enabled=True, now=now)


def start_scheduler(queue_path: Path | str, *, interval_seconds: int = 30, stop_event=None):
    """Start a lightweight in-process scheduler so it shares the web app's persistent disk."""
    stop = stop_event or threading.Event()
    enabled = os.getenv("TAK_AUTO_PUBLISHING_ENABLED", "").strip().lower() == "true"
    publisher_spec = os.getenv("TAK_AUTO_PUBLISHER", "").strip()

    def loop():
        while not stop.is_set():
            try:
                run_once(queue_path, enabled=enabled, publisher_spec=publisher_spec)
            except Exception as error:
                print(f"게시 대기열 작업 오류: {type(error).__name__}: {error}", file=sys.stderr)
            stop.wait(interval_seconds)

    thread = threading.Thread(target=loop, name="tak-auto-publishing-queue", daemon=True)
    thread.start()
    return thread, stop


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", default=str(Path(os.getenv("TAK_AUTO_DATA_DIR", ROOT / "data")) / "tak_auto_publishing_queue.json"))
    parser.add_argument("--once", action="store_true", help="예약된 작업을 한 번 실행한 뒤 종료")
    parser.add_argument("--watch", action="store_true", help="예약된 작업을 주기적으로 확인")
    parser.add_argument("--interval", type=int, default=30, help="--watch 확인 간격(초)")
    args = parser.parse_args(argv)
    enabled = os.getenv("TAK_AUTO_PUBLISHING_ENABLED", "").strip().lower() == "true"
    publisher_spec = os.getenv("TAK_AUTO_PUBLISHER", "").strip()
    try:
        if args.once:
            results = run_once(args.queue, enabled=enabled, publisher_spec=publisher_spec)
            print(f"게시 기능 {'활성' if enabled else '비활성'} · 처리 결과 {len(results)}건")
            return 0
        if args.watch:
            if args.interval < 1:
                parser.error("--interval은 1초 이상이어야 합니다.")
            start_scheduler(args.queue, interval_seconds=args.interval)
            while True:
                time.sleep(3600)
        parser.print_help()
        return 0
    except (RuntimeError, ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
