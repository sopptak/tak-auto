"""Persistent, approval-gated publishing queue for the trend content factory.

The queue calls only a publisher supplied by its worker. The production entry
point remains disabled unless TAK_AUTO_PUBLISHING_ENABLED=true is explicit.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
from typing import Any, Protocol

from .atomic_file import replace_file

MAX_ATTEMPTS = 3
PLATFORMS = ("blog", "youtube_shorts", "threads", "facebook", "instagram_reels", "tiktok")
_QUEUE_LOCK = threading.RLock()


_PROCESS_LOCK_STATE = threading.local()


@contextmanager
def _cross_process_lock(queue_path: Path):
    """Serialize file-backed queue operations across local worker processes."""
    lock_path = queue_path.with_name(f".{queue_path.name}.lock")
    lock_key = str(lock_path.resolve())
    held_paths = getattr(_PROCESS_LOCK_STATE, "held_paths", None)
    if held_paths is None:
        held_paths = set()
        _PROCESS_LOCK_STATE.held_paths = held_paths
    if lock_key in held_paths:
        yield
        return

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    try:
        try:
            os.chmod(lock_path, 0o600)
        except OSError:
            pass
        if os.name == "nt":
            import errno
            import msvcrt
            import time

            # Locking beyond EOF is supported by Windows. Keep the lock file
            # empty so simultaneous initialization cannot race on a seed write.
            handle.seek(0)
            while True:
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError as error:
                    if error.errno not in {errno.EACCES, errno.EDEADLK}:
                        raise
                    time.sleep(0.05)
            held_paths.add(lock_key)
            try:
                yield
            finally:
                held_paths.remove(lock_key)
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            held_paths.add(lock_key)
            try:
                yield
            finally:
                held_paths.remove(lock_key)
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


class QueueError(ValueError):
    """Invalid queue state or operation."""


class QueueStoreError(QueueError):
    """Shared queue storage is unavailable or a concurrent write took precedence."""


class QueueStore(Protocol):
    def ready(self) -> bool: ...

    def read(self) -> tuple[int, dict[str, Any]]: ...

    def write(self, revision: int, state: dict[str, Any]) -> int: ...


class PermanentPublishError(RuntimeError):
    """An adapter/configuration issue that should not be retried automatically."""


class PublishUncertainError(RuntimeError):
    """The provider may have accepted the post; stop and require manual reconciliation."""

    def __init__(self, message: str, *, remote_id: str = "") -> None:
        super().__init__(message)
        self.remote_id = remote_id


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
    return _validate_state(data)


def _validate_state(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict) or not isinstance(data.get("items"), list) or not isinstance(data.get("history"), list):
        raise QueueError("게시 대기열 파일의 형식이 올바르지 않습니다.")
    if not all(isinstance(item, dict) for item in data["items"]) or not all(
        isinstance(record, dict) for record in data["history"]
    ):
        raise QueueError("게시 대기열 항목 형식이 올바르지 않습니다.")
    return data


def _attempt_count(value: Any) -> int | None:
    """Return a valid stored attempt count; ambiguous values must fail closed."""
    if type(value) is not int or value < 0:
        return None
    return value


def _record_review(item: dict[str, Any], review: dict[str, Any]) -> None:
    history = item.get("review_history", [])
    if not isinstance(history, list) or not all(isinstance(entry, dict) for entry in history):
        raise QueueError("게시 작업의 수동 검토 이력 형식이 올바르지 않습니다.")
    history.append(review)
    item["review_history"] = history
    # Keep the most recent decision available to older dashboard consumers.
    item["last_review"] = review


def _write(path: Path, data: dict[str, Any]) -> None:
    """Atomically persist queue state and flush it before acknowledging the mutation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            temporary_path = Path(handle.name)
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(temporary_path, 0o600)
        except OSError:
            pass
        replace_file(temporary_path, path)
        temporary_path = None
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

def _identity(content_id: str, platform: str, payload: Mapping[str, Any]) -> str:
    canonical = json.dumps({"content_id": content_id, "platform": platform, "payload": payload}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _matches_approved_content(item: Mapping[str, Any]) -> bool:
    """Reject content that no longer matches the identity approved by the operator."""
    content_id, platform, payload = item.get("content_id"), item.get("platform"), item.get("payload")
    if not isinstance(content_id, str) or not content_id.strip():
        return False
    if not isinstance(platform, str) or platform not in PLATFORMS:
        return False
    if not isinstance(payload, dict) or not payload:
        return False
    try:
        key = _identity(content_id, platform, payload)
    except (TypeError, ValueError):
        return False
    return item.get("idempotency_key") == key and item.get("id") == key[:24]


def _history_record(item: Mapping[str, Any], remote_id: str, current: datetime) -> dict[str, Any]:
    payload = item.get("payload")
    if not isinstance(payload, Mapping):
        payload = {}
    return {
        "content_id": item["content_id"], "platform": item["platform"],
        "remote_id": remote_id, "published_at": _iso(current),
        "idempotency_key": item["idempotency_key"],
        "knowledge_id": str(payload.get("_knowledge_id") or ""),
        "source_url": str(payload.get("_source_url") or ""),
        "title": str(payload.get("title") or payload.get("keyword") or ""),
    }


class PublishingQueue:
    """Approval-gated queue with deterministic idempotency and per-platform history."""

    def __init__(self, path: Path | str, *, store: QueueStore | None = None) -> None:
        self.path = Path(path)
        self._store = store

    @contextmanager
    def _edit(self) -> Iterator[tuple[dict[str, Any], Callable[[], None]]]:
        with _QUEUE_LOCK:
            if self._store is None:
                with _cross_process_lock(self.path):
                    data = _read(self.path)
                    yield data, lambda: _write(self.path, data)
                return

            store = self._store
            revision, state = store.read()
            try:
                data = _validate_state(state)
            except QueueError:
                raise QueueStoreError("Postgres 게시 대기열의 저장 형식이 올바르지 않습니다.") from None

            def save() -> None:
                nonlocal revision
                revision = store.write(revision, data)

            yield data, save

    def snapshot(self) -> dict[str, Any]:
        with self._edit() as (data, _save):
            return data

    def storage_ready(self) -> bool:
        return self._store is None or self._store.ready()

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
        with self._edit() as (data, save):
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
            save()
            return item

    def reject(self, item_id: str, *, now: datetime | None = None) -> dict[str, Any]:
        with self._edit() as (data, save):
            item = self._find(data, item_id)
            status = item.get("status")
            if status == "published":
                raise QueueError("이미 게시된 작업은 거절할 수 없습니다.")
            if status in ("processing", "needs_review"):
                raise QueueError("게시 결과를 확인해야 하는 작업은 거절할 수 없습니다. 플랫폼에서 게시 여부를 먼저 확인하세요.")
            if status not in ("scheduled", "failed", "rejected"):
                raise QueueError("현재 상태의 작업은 거절할 수 없습니다.")
            item.update(status="rejected", updated_at=_iso(now))
            save()
            return item

    def confirm_published(
        self, item_id: str, *, remote_id: str, reviewed_by: str, now: datetime | None = None
    ) -> dict[str, Any]:
        """Resolve an uncertain job after an operator confirms it was published."""
        if not remote_id.strip() or not reviewed_by.strip():
            raise QueueError("외부 게시 ID와 확인한 운영자 이름이 필요합니다.")
        current = _utc(now)
        with self._edit() as (data, save):
            item = self._find(data, item_id)
            if item.get("status") != "needs_review":
                raise QueueError("수동 검토 상태인 작업만 게시 완료로 확인할 수 있습니다.")
            key = item["idempotency_key"]
            existing = next((row for row in data["history"] if row.get("idempotency_key") == key), None)
            if existing:
                raise QueueError("이 작업의 게시 이력이 이미 존재합니다.")
            record = _history_record(item, remote_id.strip(), current)
            record["reconciled_by"] = reviewed_by.strip()
            review = {
                "decision": "confirmed_published", "reviewed_by": reviewed_by.strip(),
                "reviewed_at": _iso(current), "remote_id": remote_id.strip(),
            }
            _record_review(item, review)
            data["history"].append(record)
            item.update(
                status="published", remote_id=remote_id.strip(), published_at=record["published_at"],
                updated_at=_iso(current), last_error="",
            )
            save()
            return item

    def retry_after_review(
        self, item_id: str, *, scheduled_at: datetime, reviewed_by: str, now: datetime | None = None
    ) -> dict[str, Any]:
        """Retry only after a person confirms the platform did not publish the job."""
        if not reviewed_by.strip():
            raise QueueError("확인한 운영자 이름이 필요합니다.")
        current = _utc(now)
        scheduled = _utc(scheduled_at)
        if scheduled <= current:
            raise QueueError("재시도 예약 시각은 현재보다 뒤여야 합니다.")
        with self._edit() as (data, save):
            item = self._find(data, item_id)
            if item.get("status") != "needs_review":
                raise QueueError("수동 검토 상태인 작업만 다시 예약할 수 있습니다.")
            if item.get("approved") is not True:
                raise QueueError("게시 승인 기록이 올바르지 않아 다시 예약할 수 없습니다.")
            attempts = _attempt_count(item.get("attempts", 0))
            if attempts is None or attempts >= MAX_ATTEMPTS:
                raise QueueError("최대 시도 횟수에 도달해 다시 예약할 수 없습니다.")
            review = {
                "decision": "confirmed_not_published", "reviewed_by": reviewed_by.strip(),
                "reviewed_at": _iso(current), "scheduled_at": _iso(scheduled),
            }
            _record_review(item, review)
            item.update(
                status="scheduled", scheduled_at=_iso(scheduled), next_attempt_at=_iso(scheduled),
                updated_at=_iso(current), last_error="",
            )
            save()
            return item

    def close_unpublished(
        self, item_id: str, *, reviewed_by: str, now: datetime | None = None
    ) -> dict[str, Any]:
        """Close an uncertain job after an operator confirms it was not published."""
        if not reviewed_by.strip():
            raise QueueError("확인한 운영자 이름이 필요합니다.")
        reviewed_at = _iso(now)
        with self._edit() as (data, save):
            item = self._find(data, item_id)
            if item.get("status") != "needs_review":
                raise QueueError("수동 검토 상태인 작업만 미게시로 종료할 수 있습니다.")
            key = item["idempotency_key"]
            if any(row.get("idempotency_key") == key for row in data["history"]):
                raise QueueError("이 작업의 게시 이력이 이미 존재합니다.")
            _record_review(item, {
                "decision": "closed_unpublished", "reviewed_by": reviewed_by.strip(),
                "reviewed_at": reviewed_at,
            })
            item.update(status="rejected", updated_at=reviewed_at, next_attempt_at="")
            save()
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
        with self._edit() as (data, save):
            return self._run_due_locked(publisher, current, data, save)

    def _run_due_locked(self, publisher, current: datetime, data, save) -> list[dict[str, Any]]:
        changed = False
        results = []
        published_keys = {record.get("idempotency_key") for record in data["history"]}
        for item in data["items"]:
            attempts = _attempt_count(item.get("attempts", 0))
            if item.get("status") in {"scheduled", "processing", "needs_review"} and attempts is None:
                item.update(
                    status="needs_review", attempts=MAX_ATTEMPTS,
                    last_error="시도 횟수 기록이 올바르지 않습니다. 게시 여부를 먼저 확인하세요.",
                    updated_at=_iso(current),
                )
                changed = True
                results.append(item)
                continue
            if item.get("status") == "processing":
                try:
                    started = datetime.fromisoformat(item["updated_at"])
                    is_stale = (current - _utc(started)).total_seconds() >= 300
                except (KeyError, ValueError, TypeError):
                    # Missing or malformed timestamps are ambiguous. Treat the
                    # processing marker as stale and require an operator check.
                    is_stale = True
                if is_stale:
                    item.update(
                        status="needs_review",
                        last_error="작업 중단 또는 응답 저장 실패 가능성: 플랫폼 게시 여부를 먼저 확인하세요.",
                        updated_at=_iso(current),
                    )
                    changed = True
                    results.append(item)
                continue
            if item.get("status") != "scheduled":
                continue
            if item.get("approved") is not True:
                item.update(
                    status="failed", last_error="게시 승인 기록이 올바르지 않습니다.",
                    updated_at=_iso(current),
                )
                changed = True
                results.append(item)
                continue
            if not _matches_approved_content(item):
                item.update(
                    status="failed", updated_at=_iso(current),
                    last_error="승인 당시 콘텐츠와 저장된 작업이 일치하지 않습니다. 원고와 플랫폼을 다시 확인하세요.",
                )
                changed = True
                results.append(item)
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
            if attempts >= MAX_ATTEMPTS:
                item.update(status="failed", last_error=item.get("last_error") or "재시도 한도 초과", updated_at=_iso(current))
                changed = True
                results.append(item)
                continue
            item["attempts"] = attempts + 1
            item.update(status="processing", updated_at=_iso(current))
            # Persist the in-flight marker before calling a platform. If the process
            # dies after the platform accepts a post, the next run will require a
            # human check instead of blindly posting the same content again.
            save()
            changed = False
            try:
                # Give built-in adapters the queue's stable content identity while
                # keeping this internal field out of the stored/editor payload.
                payload_for_adapter = dict(item["payload"])
                payload_for_adapter["_content_id"] = item["content_id"]
                remote_id = publisher(item["platform"], payload_for_adapter, key)
                normalized_remote_id = remote_id.strip() if isinstance(remote_id, str) else ""
                if not normalized_remote_id:
                    raise PublishUncertainError(
                        "게시 응답에 외부 게시 ID가 없습니다. 플랫폼 게시 여부를 확인하세요."
                    )
                record = _history_record(item, normalized_remote_id, current)
                data["history"].append(record)
                published_keys.add(key)
                item.update(
                    status="published", remote_id=normalized_remote_id, last_error="",
                    updated_at=_iso(current), published_at=record["published_at"],
                )
            except PublishUncertainError as error:
                item.update(
                    status="needs_review", last_error=f"{type(error).__name__}: {error}"[:500],
                    remote_id=getattr(error, "remote_id", ""), updated_at=_iso(current),
                )
            except PermanentPublishError as error:
                item.update(
                    status="failed", last_error=f"{type(error).__name__}: {error}"[:500],
                    updated_at=_iso(current),
                )
            except Exception as error:  # retain an auditable, bounded retry state
                retry_at = current + timedelta(seconds=min(60 * (2 ** (item["attempts"] - 1)), 3600))
                item.update(
                    status="failed" if item["attempts"] >= MAX_ATTEMPTS else "scheduled",
                    last_error=f"{type(error).__name__}: {error}"[:500], updated_at=_iso(current),
                    next_attempt_at=_iso(retry_at),
                )
            # Save this outcome before moving on to the next queue item.
            save()
            results.append(item)
        if changed:
            save()
        return results


def queue_dashboard(
    snapshot: Mapping[str, Any], *, publishing_enabled: bool, pending_approvals: int = 0
) -> str:
    items = list(snapshot.get("items", []))
    history = list(snapshot.get("history", []))
    statuses = ("pending approval", "scheduled", "processing", "needs_review", "published", "failed", "rejected")
    counts = {status: sum(row.get("status") == status for row in items) for status in statuses}
    counts["pending approval"] = pending_approvals
    cards = []
    for item in sorted(items, key=lambda row: (row.get("scheduled_at", ""), row.get("created_at", ""))):
        payload = item.get("payload")
        payload = payload if isinstance(payload, Mapping) else {}
        title = payload.get("title") or payload.get("keyword") or item.get("content_id", "")
        attempts = _attempt_count(item.get("attempts", 0))
        attempts_label = str(attempts) if attempts is not None else "확인 필요"
        status = item.get("status", "")
        review = item.get("last_review")
        status_label = status
        if status == "rejected" and isinstance(review, Mapping) and review.get("decision") == "closed_unpublished":
            status_label = "미게시 확인 후 종료"
        actions = ""
        if status == "needs_review":
            item_id = _html(item.get("id", ""))
            if item.get("approved") is not True:
                retry_action = "<span>게시 승인 기록 확인 필요</span>"
            elif attempts is not None and attempts < MAX_ATTEMPTS:
                retry_action = f'<form method="post" action="/queue/retry"><input type="hidden" name="item_id" value="{item_id}"><button type="submit" class="secondary">미게시 확인 후 재시도</button></form>'
            else:
                retry_action = "<span>최대 시도 횟수 도달</span>"
            actions = f'''<form method="post" action="/queue/confirm-published" class="queue-form"><input type="hidden" name="item_id" value="{item_id}"><label>외부 게시 ID<input name="remote_id" required></label><button type="submit">게시 완료로 기록</button></form>{retry_action}
<form method="post" action="/queue/close-unpublished" class="queue-form"><input type="hidden" name="item_id" value="{item_id}"><label><input type="checkbox" name="confirmed_unpublished" value="yes" required>플랫폼에 게시되지 않았음을 확인했습니다</label><button type="submit" class="secondary">재시도 없이 종료</button></form>'''
        review_history = item.get("review_history", [])
        if isinstance(review_history, list) and review_history:
            labels = {
                "confirmed_published": "게시 완료 확인",
                "confirmed_not_published": "미게시 확인 후 재시도 예약",
                "closed_unpublished": "미게시 확인 후 종료",
            }
            review_rows = []
            for review in review_history[-20:]:
                if not isinstance(review, Mapping):
                    continue
                decision = labels.get(str(review.get("decision") or ""), str(review.get("decision") or "확인 기록"))
                parts = [f"<strong>{_html(decision)}</strong>", _html(review.get("reviewed_by", "")), _html(review.get("reviewed_at", ""))]
                if review.get("remote_id"):
                    parts.append("외부 게시 ID: " + _html(review["remote_id"]))
                if review.get("scheduled_at"):
                    parts.append("재시도 예약: " + _html(review["scheduled_at"]))
                review_rows.append("<li>" + " · ".join(parts) + "</li>")
            if review_rows:
                omitted = f"<p>최근 20건만 표시합니다. 전체 {len(review_history)}건.</p>" if len(review_history) > 20 else ""
                actions += (
                    '<details class="queue-review-history"><summary>운영자 확인 기록 '
                    f'({len(review_history)})</summary>{omitted}<ol>{"".join(review_rows)}</ol></details>'
                )
        cards.append(
            "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}/{}</td><td>{}</td><td>{}</td></tr>".format(
                _html(title), _html(item.get("platform", "")), _html(status_label),
                _html(item.get("scheduled_at", "")), _html(attempts_label), MAX_ATTEMPTS,
                _html(item.get("last_error", "")), actions,
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
<h3>대기열</h3><p class="meta">수동 확인 상태는 플랫폼에서 게시 여부를 확인한 뒤 아래 동작으로 이력을 정리하거나 제한된 재시도를 할 수 있습니다.</p><table><thead><tr><th>콘텐츠</th><th>플랫폼</th><th>상태</th><th>예약 시각</th><th>시도</th><th>최근 오류</th><th>수동 확인</th></tr></thead>
<tbody>{''.join(cards) or '<tr><td colspan="7">대기열이 비어 있습니다.</td></tr>'}</tbody></table>
<h3>플랫폼별 게시 이력 ({len(history)})</h3><table><thead><tr><th>게시 시각</th><th>플랫폼</th><th>콘텐츠 ID</th><th>외부 게시 ID</th></tr></thead>
<tbody>{''.join(history_rows) or '<tr><td colspan="4">아직 게시 이력이 없습니다.</td></tr>'}</tbody></table>
</section>"""


def _html(value: Any) -> str:
    from html import escape
    return escape(str(value or ""))

