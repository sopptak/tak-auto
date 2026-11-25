#!/usr/bin/env python3
"""게시 대기열을 읽기 전용으로 진단합니다. 실제 게시와 파일 변경은 하지 않습니다."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_engine.publishing_queue_audit import audit_queue_file


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, default=Path(os.getenv("TAK_AUTO_DATA_DIR", ROOT / "data")) / "tak_auto_publishing_queue.json")
    parser.add_argument("--json", action="store_true", help="기계가 읽을 수 있는 JSON 보고서 출력")
    args = parser.parse_args(argv)
    report = audit_queue_file(args.queue)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        labels = {"ok": "검사 통과", "attention": "운영자 확인 필요", "blocked": "문제 해결 필요"}
        print(f"게시 대기열 진단: {labels[report['status']]}")
        print("검사 범위: 저장된 대기열. 실제 서비스 배포·계정 권한·외부 게시 결과는 별도 확인 대상입니다.")
        print(f"작업 {report['item_count']}건 · 이력 {report['history_count']}건 · 오류 {report['error_count']}건 · 확인 필요 {report['warning_count']}건")
        for finding in report["findings"]:
            location = {"items": "대기열", "history": "게시 이력", "queue": "파일"}[finding["section"]]
            if finding["row"] is not None:
                location += f" {finding['row']}번"
            print(f"- {location}: {finding['message']}")
        if report["omitted_findings"]:
            print(f"추가 진단 {report['omitted_findings']}건은 출력 한도로 생략했습니다.")
    return {"ok": 0, "attention": 1, "blocked": 2}[report["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
