#!/usr/bin/env python3
"""TAK MEDIA 배치 실행 결과 JSON을 사람이 검토하기 쉬운 텍스트/Markdown 형태로 출력하는 CLI Viewer."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def format_summary(summary: dict[str, Any]) -> str:
    lines = [
        "SUMMARY",
        f"- 전체 KNOWLEDGE: {summary.get('total_knowledge_count', 0)}건",
        f"- 승인 KNOWLEDGE: {summary.get('approved_knowledge_count', 0)}건",
        f"- 건너뜀: {summary.get('skipped_knowledge_count', 0)}건",
        f"- 전체 Draft: {summary.get('total_draft_count', 0)}건",
        f"- Valid (검증 통과): {summary.get('valid_count', 0)}건",
        f"- Rejected (검증 거절): {summary.get('rejected_count', 0)}건",
        f"- Error (오류): {summary.get('error_count', 0)}건",
    ]
    return "\n".join(lines)


def format_item(item: dict[str, Any], index: int) -> str:
    platform = item.get("platform", "CONTENT").upper()
    status = item.get("status", "UNKNOWN").upper()
    knowledge_id = item.get("knowledge_id", "")
    source_url = item.get("source_url", "")
    evidence_units = ", ".join(item.get("evidence_unit_ids", [])) or "(없음)"

    lines = [
        "-" * 60,
        f"[{index}] {platform} | {status}",
        f"KNOWLEDGE: {knowledge_id}",
        f"SOURCE: {source_url}",
        f"EVIDENCE UNITS: {evidence_units}",
        "",
        "ORIGINAL",
        f"제목: {item.get('original_title', '')}",
        "본문:",
        item.get("original_body", "").strip(),
        "",
        "REWRITTEN",
        f"제목: {item.get('rewritten_title') or '(없음)'}",
        "본문:",
        (item.get("rewritten_body") or "(없음)").strip(),
        "",
        "EVIDENCE",
    ]

    evidence_list = item.get("evidence", [])
    if evidence_list:
        for ev in evidence_list:
            lines.append(f"- {ev}")
    else:
        lines.append("- (없음)")

    rejection_reasons = item.get("rejection_reasons", [])
    if rejection_reasons:
        lines.append("")
        lines.append("REJECTION REASONS")
        for reason in rejection_reasons:
            lines.append(f"- {reason}")

    error_message = item.get("error_message")
    if error_message:
        lines.append("")
        lines.append("ERROR MESSAGE")
        lines.append(str(error_message))

    return "\n".join(lines)


def render_batch_report(
    data: dict[str, Any],
    platform_filter: str | None = None,
    status_filter: str | None = None,
) -> str:
    summary = data.get("summary", {})
    all_items = data.get("all_items", [])

    filtered_items = []
    for item in all_items:
        if platform_filter and item.get("platform", "").lower() != platform_filter.lower():
            continue
        if status_filter and item.get("status", "").lower() != status_filter.lower():
            continue
        filtered_items.append(item)

    sections = [
        "=" * 60,
        "TAK MEDIA CONTENT REVIEW",
        "=" * 60,
        "",
        format_summary(summary),
    ]

    if platform_filter or status_filter:
        filter_descs = []
        if platform_filter:
            filter_descs.append(f"플랫폼={platform_filter.upper()}")
        if status_filter:
            filter_descs.append(f"상태={status_filter.upper()}")
        sections.append(f"\n[필터 적용: {', '.join(filter_descs)} | 표시 항목: {len(filtered_items)}건]")

    if not filtered_items:
        sections.append("\n표시할 콘텐츠가 없습니다.")
    else:
        for idx, item in enumerate(filtered_items, start=1):
            sections.append("")
            sections.append(format_item(item, idx))

    return "\n".join(sections)


def load_and_view(
    input_path: Path | str,
    platform_filter: str | None = None,
    status_filter: str | None = None,
) -> str:
    path = Path(input_path)
    if not path.exists():
        raise FileNotFoundError(f"입력 파일을 찾을 수 없습니다: {path}")

    try:
        content = path.read_text(encoding="utf-8")
        data = json.loads(content)
    except json.JSONDecodeError as err:
        raise ValueError(f"유효하지 않은 JSON 파일입니다: {err}") from err

    if not isinstance(data, dict):
        raise ValueError("JSON의 최상위 구조는 객체여야 합니다.")

    return render_batch_report(data, platform_filter=platform_filter, status_filter=status_filter)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TAK MEDIA Batch Report Viewer")
    parser.add_argument(
        "--input",
        type=Path,
        default=ROOT / "data" / "tak_media_batch_e2e_test.json",
        help="배치 결과 JSON 경로 (기본값: data/tak_media_batch_e2e_test.json)",
    )
    parser.add_argument(
        "--platform",
        choices=["blog", "shorts", "threads"],
        default=None,
        help="특정 플랫폼만 필터링하여 출력 (blog, shorts, threads)",
    )
    parser.add_argument(
        "--status",
        choices=["valid", "rejected", "error"],
        default=None,
        help="특정 상태만 필터링하여 출력 (valid, rejected, error)",
    )
    args = parser.parse_args(argv)

    try:
        output = load_and_view(
            input_path=args.input,
            platform_filter=args.platform,
            status_filter=args.status,
        )
        print(output)
        return 0
    except (FileNotFoundError, ValueError) as err:
        print(f"오류: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
