"""Persistent, approval-gated publishing queue for the trend content factory.

The queue deliberately has no platform API clients. A worker can only call a
publisher supplied by its caller, and the production entry point remains
disabled unless TAK_AUTO_PUBLISHING_ENABLED=true is explicitly configured.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import threading
from typing import Any

MAX_ATTEMPTS = 3
PLATFORMS = ("blog", "youtube_shorts", "threads", "instagram_reels", "tiktok")
_QUEUE_LOCK = threading.RLock()


class QueueError(ValueError):
    """Invalid queue state or operation."""


def _utc(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise QueueError("시간은 시간대 정보가 포함된 ISO 날짜여야 합니다.")
    return current.astimezone(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return _utc(value).isoformat(timespec="seconds")


def _read(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "items": [], "history": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise QueueError(f"게시 대기열 파일을 읽을 수 없습니다: {path}") from error
    if not isinstance(data, dict) or not isinstance(data.get("items"), list) or not isinstance(data.get("history"), list):
        raise QueueError("게시 대기열 파일의 형식이 올바르지 않습니다.")
    return data


def _write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def _identity(content_id: str, platform: str, payload: Mapping[str, Any]) -> str:
    canonical = json.dumps({"content_id": content_id, "platform": platform, "payload": payload}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class PublishingQueue:
    """JSON-backed queue with deterministic idempotency and per-platform history."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def snapshot(self) -> dict[str, Any]:
        with _QUEUE_LOCK:
            return _read(self.path)

    def enqueue_approved(
        self,
        *,
        content_id: str,
        platform: str,
        payload: Mapping[str, Any],
        scheduled_at: datetime,
        approved_by: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if platform not in PLATFORMS:
            raise QueueError("지원하지 않는 게시 플랫폼입니다.")
        if not content_id.strip() or not approved_by.strip():
            raise QueueError("콘텐츠 식별자와 승인자가 필요합니다.")
        scheduled = _utc(scheduled_at)
        current = _utc(now)
        if scheduled <= current:
            raise QueueError("예약 시각은 현재보다 뒤여야 합니다.")
        if not isinstance(payload, Mapping) or not payload:
            raise QueueError("게시할 콘텐츠가 비어 있습니다.")
        with _QUEUE_LOCK:
            data = _read(self.path)
            key = _identity(content_id, platform, payload)
            for item in data["items"]:
                if item.get("idempotency_key") == key:
                    return item
            item = {
                "id": key[:24], "idempotency_key": key, "content_id": content_id,
                "platform": platform, "payload": dict(payload), "status": "scheduled",
                "approved": True, "approved_by": approved_by.strip(), "approved_at": _iso(current),
                "scheduled_at": _iso(scheduled), "attempts": 0, "max_attempts": MAX_ATTEMPTS,
                "last_error": "", "next_attempt_at": _iso(scheduled),
                "created_at": _iso(current), "updated_at": _iso(current),
            }
            data["items"].append(item)
            _write(self.path, data)
            return item

    def reject(self, item_id: str, *, now: datetime | None = None) -> dict[str, Any]:
        with _QUEUE_LOCK:
            data = _read(self.path)
            item = self._find(data, item_id)
            if item["status"] == "published":
                raise QueueError("이미 게시된 작업은 거절할 수 없습니다.")
            item.update(status="rejected", updated_at=_iso(now))
            _write(self.path, data)
            return item

    @staticmethod
    def _find(data: dict[str, Any], item_id: str) -> dict[str, Any]:
        for item in data["items"]:
            if item.get("id") == item_id:
                return item
        raise QueueError("대기열 항목을 찾을 수 없습니다.")

    def run_due(
        self,
        publisher: Callable[[str, Mapping[str, Any], str], str],
        *,
        enabled: bool = False,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Run due approved jobs; `publisher` receives platform, payload and idempotency key."""
        if not enabled:
            return []
        current = _utc(now)
        with _QUEUE_LOCK:
            return self._run_due_locked(publisher, current)

    def _run_due_locked(self, publisher, current: datetime) -> list[dict[str, Any]]:
        data = _read(self.path)
        changed = False
        results = []
        published_keys = {record.get("idempotency_key") for record in data["history"]}
        for item in data["items"]:
            if item.get("status") != "scheduled" or not item.get("approved"):
                continue
            try:
                scheduled = datetime.fromisoformat(item.get("next_attempt_at") or item["scheduled_at"])
                if _utc(scheduled) > current:
                    continue
            except (KeyError, ValueError, TypeError):
                item.update(status="failed", last_error="예약 시각 형식이 올바르지 않습니다.", updated_at=_iso(current))
                changed = True
                results.append(item)
                continue
            key = item["idempotency_key"]
            if key in published_keys:
                item.update(status="published", updated_at=_iso(current))
                changed = True
                results.append(item)
                continue
            if item.get("attempts", 0) >= MAX_ATTEMPTS:
                item.update(status="failed", last_error=item.get("last_error") or "재시도 한도 초과", updated_at=_iso(current))
                changed = True
                results.append(item)
                continue
            item["attempts"] = int(item.get("attempts", 0)) + 1
            item.update(status="processing", updated_at=_iso(current))
            changed = True
            try:
                remote_id = publisher(item["platform"], item["payload"], key)
                record = {
                    "content_id": item["content_id"], "platform": item["platform"],
                    "remote_id": str(remote_id), "published_at": _iso(current),
                    "idempotency_key": key,
                }
                data["history"].append(record)
                published_keys.add(key)
                item.update(status="published", last_error="", updated_at=_iso(current), published_at=record["published_at"])
            except Exception as error:  # retain an auditable, bounded retry state
                retry_at = current + timedelta(seconds=min(60 * (2 ** (item["attempts"] - 1)), 3600))
                item.update(
                    status="failed" if item["attempts"] >= MAX_ATTEMPTS else "scheduled",
                    last_error=f"{type(error).__name__}: {error}"[:500], updated_at=_iso(current),
                    next_attempt_at=_iso(retry_at),
                )
            results.append(item)
        if changed:
            _write(self.path, data)
        return results


def queue_dashboard(
    snapshot: Mapping[str, Any], *, publishing_enabled: bool, pending_approvals: int = 0
) -> str:
    items = list(snapshot.get("items", []))
    history = list(snapshot.get("history", []))
    statuses = ("pending approval", "scheduled", "processing", "published", "failed", "rejected")
    counts = {status: sum(row.get("status") == status for row in items) for status in statuses}
    counts["pending approval"] = pending_approvals
    cards = []
    for item in sorted(items, key=lambda row: (row.get("scheduled_at", ""), row.get("created_at", ""))):
        title = item.get("payload", {}).get("title") or item.get("payload", {}).get("keyword") or item.get("content_id", "")
        cards.append(
            "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}/{}</td><td>{}</td></tr>".format(
                _html(title), _html(item.get("platform", "")), _html(item.get("status", "")),
                _html(item.get("scheduled_at", "")), item.get("attempts", 0), MAX_ATTEMPTS,
                _html(item.get("last_error", "")),
            )
        )
    history_rows = []
    for row in sorted(history, key=lambda entry: entry.get("published_at", ""), reverse=True)[:100]:
        history_rows.append("<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            _html(row.get("published_at", "")), _html(row.get("platform", "")),
            _html(row.get("content_id", "")), _html(row.get("remote_id", "")),
        ))
    summary = " · ".join(f"{_html(key)}: {value}" for key, value in counts.items())
    state = "활성화" if publishing_enabled else "비활성화 (기본값)"
    return f"""<section class="toolbar" id="publishing-queue">
<h2>게시 운영 대시보드</h2><p>실제 게시: <b>{state}</b></p><p>{summary}</p>
<h3>대기열</h3><table><thead><tr><th>콘텐츠</th><th>플랫폼</th><th>상태</th><th>예약 시각</th><th>시도</th><th>최근 오류</th></tr></thead>
<tbody>{''.join(cards) or '<tr><td colspan="6">대기열이 비어 있습니다.</td></tr>'}</tbody></table>
<h3>플랫폼별 게시 이력 ({len(history)})</h3><table><thead><tr><th>게시 시각</th><th>플랫폼</th><th>콘텐츠 ID</th><th>외부 게시 ID</th></tr></thead>
<tbody>{''.join(history_rows) or '<tr><td colspan="4">아직 게시 이력이 없습니다.</td></tr>'}</tbody></table>
</section>"""


def _html(value: Any) -> str:
    from html import escape
    return escape(str(value or ""))
