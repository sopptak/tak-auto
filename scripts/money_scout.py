#!/usr/bin/env python3
"""MONEY Browser Scout CLI(6-60) - 브라우저 에이전트가 읽어 온 결과를 MONEY로 넘기는 입구.

    py scripts/money_scout.py plan                         # 이번에 자동으로 열어도 되는 곳/안 되는 곳(정책 포함)
    py scripts/money_scout.py ingest 결과.json [--data-dir data] [--dry-run]

결과.json 형식(브라우저가 **읽은** 것만 - 로그인/응답/제출 없음):
    {"mode": "agent", "agent": "claude-in-chrome", "request_id": "req-…"(선택),
     "platforms": [{"platform": "panelnow", "page_url": "…/survey", "page_text": "<화면 글자>", "links": [{"text", "href"}]},
                   {"platform": "adpost", "status": "BROWSER_RESTRICTED"}, …]}

검사 → 개인정보 제거 → 정규화 → 중복 병합 → data/money_scout_staging.json 기록 → 통과한 것만 data/money_tasks.json 기회로.
화면 원문은 저장하지 않는다(sha256·길이만).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_engine import money_scout  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("plan")
    ing = sub.add_parser("ingest")
    ing.add_argument("raw", type=Path)
    ing.add_argument("--data-dir", type=Path, default=ROOT / "data")
    ing.add_argument("--dry-run", action="store_true", help="staging에만 기록하고 money_tasks에는 넣지 않음")
    args = parser.parse_args(argv)
    if args.command == "plan":
        print(json.dumps(money_scout.plan(), ensure_ascii=False, indent=2))
        return 0
    raw = json.loads(args.raw.read_text(encoding="utf-8"))
    run = money_scout.ingest(raw, tasks_path=args.data_dir / "money_tasks.json", staging_path=args.data_dir / "money_scout_staging.json",
                             promote_items=not args.dry_run)
    print(json.dumps({"scout_run_id": run["scout_run_id"], "overall": run["overall"], "errors": run["errors"],
                      "platforms": {k: {"status": v["status"], "found": v["found"], "promotable": v["promotable"], "review": v["review"]}
                                    for k, v in run["platforms"].items()},
                      "promotion": run.get("promotion")}, ensure_ascii=False, indent=2))
    return 0 if run["overall"] in ("SUCCESS", "PARTIAL_SUCCESS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
