"""Read-only diagnostics for local publishing queues; never call providers."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from html import escape
import json
from pathlib import Path
import re
from typing import Any

from .publishing_queue import MAX_ATTEMPTS, PLATFORMS, _attempt_count, _matches_approved_content

MAX_AUDIT_BYTES = 16 * 1024 * 1024
MAX_FINDINGS = 200
STATUSES = ("scheduled", "processing", "needs_review", "published", "failed", "rejected")
KEY_PATTERN = re.compile(r"[0-9a-f]{64}")


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None
    except (ValueError, OverflowError):
        return None


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _valid_key(value: Any) -> bool:
    return isinstance(value, str) and KEY_PATTERN.fullmatch(value) is not None


class _Report:
    def __init__(self):
        self.data = {
            "audit_version": 1, "scope": "local_queue_only", "status": "ok",
            "item_count": 0, "history_count": 0,
            "status_counts": {status: 0 for status in (*STATUSES, "unknown")},
            "error_count": 0, "warning_count": 0, "findings": [], "omitted_findings": 0,
        }

    def add(self, code: str, message: str, *, severity="error", section="queue", row=None):
        self.data[f"{severity}_count"] += 1
        if len(self.data["findings"]) < MAX_FINDINGS:
            self.data["findings"].append({
                "code": code, "severity": severity, "section": section, "row": row,
                "message": message,
            })
        else:
            self.data["omitted_findings"] += 1

    def finish(self):
        self.data["status"] = "blocked" if self.data["error_count"] else "attention" if self.data["warning_count"] else "ok"
        return self.data


def audit_queue_snapshot(data: Any, *, now: datetime | None = None) -> dict[str, Any]:
    """Return fixed diagnostic messages without copying payloads, IDs or secrets."""
    report = _Report()
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("audit time must include a timezone")
    current = current.astimezone(timezone.utc)
    if not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] != 1:
        report.add("queue_schema_invalid", "대기열 버전 또는 기본 형식을 확인하세요.")
        return report.finish()
    if not isinstance(data.get("items"), list) or not isinstance(data.get("history"), list):
        report.add("queue_schema_invalid", "대기열 항목과 게시 이력은 목록 형식이어야 합니다.")
        return report.finish()

    items, history = data["items"], data["history"]
    report.data.update(item_count=len(items), history_count=len(history))
    histories = {}
    history_keys = Counter()
    for row, record in enumerate(history, 1):
        if not isinstance(record, dict):
            report.add("history_record_invalid", "게시 이력 항목의 형식을 확인하세요.", section="history", row=row)
            continue
        key = record.get("idempotency_key")
        valid = (
            _valid_key(key) and _nonempty(record.get("content_id"))
            and isinstance(record.get("platform"), str) and record["platform"] in PLATFORMS
            and _nonempty(record.get("remote_id")) and _timestamp(record.get("published_at")) is not None
        )
        if not valid:
            report.add("history_record_invalid", "게시 이력의 식별값·외부 게시 ID·시각을 확인하세요.", section="history", row=row)
        if _valid_key(key):
            history_keys[key] += 1
            histories[key] = record if valid else None
            if history_keys[key] > 1:
                report.add("duplicate_history", "같은 작업의 게시 이력이 중복되어 있습니다. 플랫폼 게시 여부를 확인하세요.", section="history", row=row)

    ids, keys = set(), set()
    for row, item in enumerate(items, 1):
        if not isinstance(item, dict):
            report.data["status_counts"]["unknown"] += 1
            report.add("item_invalid", "대기열 항목이 객체 형식이 아닙니다.", section="items", row=row)
            continue
        status = item.get("status")
        known_status = isinstance(status, str) and status in STATUSES
        report.data["status_counts"][status if known_status else "unknown"] += 1
        if not known_status:
            report.add("status_invalid", "작업 상태 값이 올바르지 않습니다.", section="items", row=row)
        if not _matches_approved_content(item):
            report.add("content_integrity_invalid", "승인 당시 콘텐츠와 저장된 작업이 일치하지 않습니다. 원고와 플랫폼을 다시 검토하세요.", section="items", row=row)
        for field, seen in (("id", ids), ("idempotency_key", keys)):
            value = item.get(field)
            if isinstance(value, str):
                if value in seen:
                    report.add("duplicate_" + field, "같은 작업 식별값이 중복되어 있습니다. 중복 원인을 확인하세요.", section="items", row=row)
                seen.add(value)
        attempts = _attempt_count(item.get("attempts", 0))
        if attempts is None or attempts > MAX_ATTEMPTS:
            report.add("attempts_invalid", "시도 횟수 기록이 올바르지 않습니다. 플랫폼 게시 여부를 먼저 확인하세요.", section="items", row=row)
        if known_status and status in ("scheduled", "processing", "needs_review"):
            approval = item.get("approved")
            if approval is not True:
                report.add("approval_invalid", "명시적인 사람의 승인이 확인되지 않은 작업입니다.", section="items", row=row)
            if not _nonempty(item.get("approved_by")) or _timestamp(item.get("approved_at")) is None:
                report.add("approval_record_invalid", "승인자 또는 승인 시각 기록을 확인하세요.", section="items", row=row)
        if status == "scheduled":
            if _timestamp(item.get("next_attempt_at") or item.get("scheduled_at")) is None:
                report.add("schedule_invalid", "시간대가 포함된 예약 시각이 필요합니다.", section="items", row=row)
            if attempts is not None and attempts >= MAX_ATTEMPTS:
                report.add("attempt_limit_reached", "자동 시도 횟수에 도달한 예약 작업입니다.", severity="warning", section="items", row=row)
        elif status == "processing":
            updated = _timestamp(item.get("updated_at"))
            if updated is None:
                report.add("processing_time_invalid", "처리 시작 시각을 확인할 수 없습니다. 플랫폼 게시 여부를 확인하세요.", section="items", row=row)
            else:
                stale = (current - updated).total_seconds() >= 300
                report.add("processing_stale" if stale else "processing_active", "처리가 오래 중단된 작업입니다. 플랫폼 게시 여부를 확인하세요." if stale else "게시 처리 중인 작업입니다. 결과 저장을 기다리세요.", severity="warning", section="items", row=row)
        elif status == "needs_review":
            report.add("manual_review_required", "플랫폼에서 게시 여부를 확인한 뒤 완료 기록 또는 미게시 재시도를 선택하세요.", severity="warning", section="items", row=row)
        elif status == "failed":
            report.add("failed_job", "실패한 작업이 있습니다. 대시보드에서 원인을 검토하세요.", severity="warning", section="items", row=row)

        key = item.get("idempotency_key")
        record = histories.get(key) if _valid_key(key) else None
        if status == "published":
            if record is None or record.get("platform") != item.get("platform") or record.get("content_id") != item.get("content_id"):
                report.add("published_history_missing", "완료 상태와 일치하는 게시 이력이 없습니다. 플랫폼에서 결과를 확인하세요.", section="items", row=row)
        elif record is not None:
            report.add("history_status_mismatch", "게시 이력이 있는 작업의 대기열 상태가 완료와 다릅니다. 결과를 확인하세요.", severity="warning", section="items", row=row)
    return report.finish()


def audit_queue_file(path: Path | str, *, now: datetime | None = None) -> dict[str, Any]:
    """Read at most 16 MiB. No directory, lock file or queue mutation is performed."""
    report = _Report()
    try:
        with Path(path).open("rb") as handle:
            raw = handle.read(MAX_AUDIT_BYTES + 1)
    except FileNotFoundError:
        report.add("queue_missing", "대기열 파일이 없습니다. 신규 설치인지 파일 경로가 맞는지 확인하세요.")
        return report.finish()
    except OSError:
        report.add("queue_unreadable", "대기열 파일을 읽을 수 없습니다. 접근 권한과 저장소를 확인하세요.")
        return report.finish()
    if len(raw) > MAX_AUDIT_BYTES:
        report.add("queue_too_large", "대기열 파일이 진단 크기 한도인 16MiB를 초과했습니다.")
        return report.finish()
    try:
        data = json.loads(raw.decode("utf-8"), parse_constant=_reject_constant, object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, ValueError, RecursionError):
        report.add("queue_json_invalid", "대기열 파일의 UTF-8 JSON 형식을 확인하세요.")
        return report.finish()
    return audit_queue_snapshot(data, now=now)


def _reject_constant(value):
    raise ValueError("non-finite JSON numbers are not supported")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON fields are not supported")
        result[key] = value
    return result


def queue_audit_page(report: dict[str, Any]) -> str:
    """Render diagnostics without JavaScript, credentials or editable controls."""
    labels = {"ok": "검사 통과", "attention": "운영자 확인 필요", "blocked": "문제 해결 필요"}
    status = report["status"]
    rows = []
    for finding in report["findings"]:
        location = {"items": "대기열", "history": "게시 이력", "queue": "파일"}[finding["section"]]
        if finding["row"] is not None:
            location += f" {finding['row']}번"
        severity = "문제 해결" if finding["severity"] == "error" else "확인 필요"
        rows.append(f'<li><strong>{escape(location)} · {severity}</strong><p>{escape(finding["message"])}</p></li>')
    findings = "<ul>" + "".join(rows) + "</ul>" if rows else "<p>저장된 대기열에서 진단 문제가 발견되지 않았습니다.</p>"
    omitted = f'<p>추가 진단 {report["omitted_findings"]}건은 출력 한도로 생략했습니다.</p>' if report["omitted_findings"] else ""
    return f'''<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>대기열 진단 · TAK AUTO</title>
<style>body{{margin:0;background:#f4f6fa;color:#182338;font-family:system-ui,sans-serif;line-height:1.65}}main{{max-width:850px;margin:40px auto;padding:24px;background:white;border-radius:16px}}h1{{margin-top:12px}}a{{color:#1659bd}}.status{{padding:16px;border-left:5px solid #1659bd;background:#eef4ff}}li{{padding:12px 0;border-bottom:1px solid #e1e6ee}}li p{{margin:6px 0}}.scope{{color:#4e5d72}}@media(max-width:600px){{main{{margin:12px;padding:18px}}}}</style></head>
<body><main><a href="/">← 대시보드로 돌아가기</a><h1>게시 대기열 진단</h1>
<div class="status" role="status"><strong>{labels[status]}</strong><br>
작업 {report["item_count"]}건 · 이력 {report["history_count"]}건 · 문제 {report["error_count"]}건 · 확인 필요 {report["warning_count"]}건</div>
<p class="scope">이 화면은 저장된 파일만 읽습니다. 실제 게시를 실행하거나 작업 상태를 바꾸지 않습니다. 배포 상태·계정 권한·플랫폼 게시 결과는 별도로 확인해야 합니다.</p>
{findings}{omitted}<p>처리 중인 작업은 결과 저장 후 다시 확인하세요. 문제가 있는 행은 원본을 보존하고 플랫폼 기록과 대조하세요.</p>
<p><a href="/queue/diagnostics">진단 다시 확인</a> · <a href="/queue/diagnostics.json">JSON 보고서 보기</a></p></main></body></html>'''
