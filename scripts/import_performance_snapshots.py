#!/usr/bin/env python3
"""수동으로 준비한 JSON 파일에서 성과 스냅샷을 일괄 저장소에 추가하는
읽기 파일 전용 CLI(6-34 21장).

``scripts/collect_performance.py``는 1건씩 CLI 인자(`--metric key=value`)로
입력받는다 - 여러 건을 한 번에(예: 네이버 블로그 관리자 페이지에서 여러
글의 조회수를 한 번에 확인한 뒤 옮겨 적을 때, 또는 API에서 이미 여러 건을
JSON으로 export한 경우) 넣으려면 CLI 인자를 여러 번 반복 조합해야 해서
번거롭다. 이 스크립트는 그 대신 JSON 배열 파일 하나를 받아
``content_engine.performance.store.append_snapshots()``(이미 있는 idempotent
bulk 저장 함수)를 그대로 호출한다 - 새 저장/중복 방지 로직을 만들지 않는다.

입력 파일 형식: PerformanceRecord.to_dict()와 동일한 필드를 가진 객체의
JSON 배열. 예:

    [
      {
        "content_id": "content-abc123",
        "knowledge_id": "knowledge-xyz",
        "platform": "blog",
        "published_at": "2026-09-15T00:00:00+00:00",
        "metric_collected_at": "2026-09-16T00:00:00+00:00",
        "metrics": {"views": 850, "likes": 12},
        "source": "manual"
      }
    ]

이 스크립트는 실제 네트워크 호출을 전혀 하지 않는다(파일만 읽는다). 실제
운영 성과 저장소(data/tak_performance.json)를 이 세션에서 실행하지 않았다 -
--output을 명시해야 하며 기본값을 두지 않는다(실수로 실제 운영 파일을
건드리는 것을 막기 위해, scripts/promote_media_generation.py의 batch
promotion과 동일한 안전 원칙).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_engine.performance.models import PerformanceRecord, PerformanceRecordError
from content_engine.performance.quality import check_metric_quality, quality_status
from content_engine.performance.store import append_snapshots, load_snapshots


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="JSON 배열 파일의 성과 스냅샷을 저장소에 일괄 추가하는 CLI(idempotent, 실제 API 호출 없음)."
    )
    parser.add_argument("--input", type=Path, required=True, help="PerformanceRecord 목록 JSON 파일 경로")
    parser.add_argument("--output", type=Path, required=True, help="성과 스냅샷 저장소 경로(실수 방지를 위해 기본값 없음)")
    args = parser.parse_args(argv)

    if not args.input.exists():
        print(f"오류: 입력 파일을 찾을 수 없습니다: {args.input}", file=sys.stderr)
        return 1

    try:
        raw_text = args.input.read_text(encoding="utf-8")
        data = json.loads(raw_text)
    except (OSError, json.JSONDecodeError) as error:
        print(f"오류: 입력 파일을 읽을 수 없습니다: {error}", file=sys.stderr)
        return 1

    if not isinstance(data, list):
        print("오류: 입력 파일은 객체 목록(JSON 배열)이어야 합니다.", file=sys.stderr)
        return 1

    records: list[PerformanceRecord] = []
    for index, item in enumerate(data):
        try:
            records.append(PerformanceRecord.from_dict(item))
        except PerformanceRecordError as error:
            print(f"오류: {index}번째 레코드가 올바르지 않습니다: {error}", file=sys.stderr)
            return 1

    if not records:
        print("입력 파일에 레코드가 없습니다. 아무 것도 하지 않았습니다.")
        return 0

    existing = load_snapshots(args.output)
    existing_by_content: dict[str, list[PerformanceRecord]] = {}
    for record in existing:
        existing_by_content.setdefault(record.content_id, []).append(record)
    existing_keys = {(record.content_id, record.metric_collected_at) for record in existing}

    for record in records:
        if (record.content_id, record.metric_collected_at) in existing_keys:
            continue  # 이미 저장된 스냅샷 - 품질 경고도 새로 추가되지 않으므로 건너뛴다.
        previous_candidates = sorted(
            existing_by_content.get(record.content_id, []),
            key=lambda r: r.metric_collected_at,
        )
        previous = previous_candidates[-1] if previous_candidates else None
        issues = check_metric_quality(record, previous=previous)
        status = quality_status(issues)
        if issues:
            print(f"경고({status}): content_id={record.content_id}")
            for issue in issues:
                print(f"  - {issue.code}: {issue.message}")

    added = append_snapshots(args.output, records)
    skipped = len(records) - added
    print(f"완료: {added}건 추가, {skipped}건 건너뜀(이미 존재하는 (content_id, metric_collected_at) 조합).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
