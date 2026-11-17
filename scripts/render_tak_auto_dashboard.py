#!/usr/bin/env python3
"""Render the daily TAK AUTO HTML dashboard from committed JSON snapshots."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tak_scout.dashboard import render_dashboard


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=ROOT / "data" / "tak_auto_trend_daily.json")
    parser.add_argument("--candidates", type=Path, default=ROOT / "data" / "tak_scout_daily.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "tak_auto_dashboard.html")
    args = parser.parse_args(argv)
    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
        pack = json.loads(args.candidates.read_text(encoding="utf-8"))
        candidates = pack.get("candidates", [])
        if not isinstance(report, dict) or not isinstance(candidates, list):
            raise ValueError("입력 JSON 구조가 올바르지 않습니다.")
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        parser.error(f"대시보드 입력을 읽을 수 없습니다: {exc}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_dashboard(report, candidates), encoding="utf-8")
    print(f"TAK AUTO 대시보드 생성: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
