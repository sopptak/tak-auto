#!/usr/bin/env python3
"""Start the TAK AUTO MVP: collect public RSS, build trends, then open the dashboard.

All runtime data stays under data/ (git-ignored). External research is only triggered
by an explicit dashboard action and requires TAK_SCOUT_PERPLEXITY_API_KEY.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable


def run_step(command: list[str], label: str) -> int:
    print(f"\n=== {label} ===", flush=True)
    result = subprocess.run(command, cwd=ROOT, check=False)
    if result.returncode:
        print(f"실패: {label} (종료 코드 {result.returncode})", file=sys.stderr)
    return result.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", help="기본값은 로컬 전용")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--max", type=int, default=30, help="SCOUT 후보 최대 수")
    parser.add_argument("--skip-collect", action="store_true", help="기존 data 파일로 대시보드만 시작")
    parser.add_argument("--no-dashboard", action="store_true", help="수집·리포트 생성만 수행")
    args = parser.parse_args(argv)

    if args.port < 1 or args.port > 65535:
        parser.error("--port는 1~65535 범위여야 합니다.")
    if args.max < 1:
        parser.error("--max는 1 이상이어야 합니다.")

    if not args.skip_collect:
        code = run_step(
            [PYTHON, "scripts/run_scout.py", "--max", str(args.max)],
            "1/2 공개 RSS 수집 및 SCOUT 후보 생성",
        )
        if code:
            return code

    code = run_step([PYTHON, "scripts/run_trend_report.py"], "2/2 트렌드 리포트 생성")
    if code:
        return code

    if args.no_dashboard:
        print("\n완료: data/tak_scout_daily.* 및 data/tak_auto_trend_daily.* 생성")
        return 0

    print("\n=== TAK AUTO MVP 준비 상태 ===")
    print("Perplexity 심층 조사:", "연결 가능" if os.environ.get("TAK_SCOUT_PERPLEXITY_API_KEY") else "API 키 미설정(조사 버튼은 비활성)")
    print("네이버 데이터랩:", "연결 가능" if os.environ.get("NAVER_DATALAB_CLIENT_ID") and os.environ.get("NAVER_DATALAB_CLIENT_SECRET") else "미설정(RSS 트렌드만 표시)")
    print("미디어 LLM:", "연결 가능" if all(os.environ.get(k) for k in ("TAK_MEDIA_LLM_API_KEY", "TAK_MEDIA_LLM_ENDPOINT", "TAK_MEDIA_LLM_MODEL")) else "미설정(초안은 규칙 기반 경로)")
    print(f"대시보드: http://{args.host}:{args.port}")
    print("중단: Ctrl+C")
    return run_step(
        [PYTHON, "scripts/run_scout_dashboard.py", "--host", args.host, "--port", str(args.port)],
        "TAK AUTO Dashboard 실행",
    )


if __name__ == "__main__":
    raise SystemExit(main())
