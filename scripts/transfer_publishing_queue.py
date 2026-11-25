#!/usr/bin/env python3
"""Validate, import or export a TAK AUTO publishing queue snapshot."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_engine.postgres_queue_store import PostgresQueueStore
from content_engine.publishing_queue import PLATFORMS, QueueError, _identity, _validate_state


def _unique_object(pairs):
    value = dict(pairs)
    if len(value) != len(pairs):
        raise QueueError("원본 게시 대기열 JSON에 중복 필드가 있습니다.")
    return value


def _reject_nonfinite(_value):
    raise QueueError("원본 게시 대기열 JSON에 유효하지 않은 숫자가 있습니다.")


def load_import_state(source: Path) -> dict:
    try:
        state = json.loads(
            source.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_object, parse_constant=_reject_nonfinite,
        )
    except QueueError:
        raise
    except (OSError, ValueError, RecursionError):
        raise QueueError("원본 게시 대기열 JSON을 읽을 수 없습니다.") from None
    return validate_transfer_state(state)


def validate_transfer_state(state: dict) -> dict:
    state = _validate_state(state)
    if type(state.get("version")) is not int or state["version"] != 1:
        raise QueueError("가져올 게시 대기열의 버전이 지원되지 않습니다.")

    statuses = {"scheduled", "needs_review", "published", "failed", "rejected"}
    item_ids = set()
    item_keys = set()
    for item in state["items"]:
        item_id = item.get("id")
        key = item.get("idempotency_key")
        status = item.get("status")
        if not isinstance(item_id, str) or not item_id.strip() or item_id in item_ids:
            raise QueueError("원본 게시 작업 식별자가 비어 있거나 중복됩니다.")
        if not isinstance(key, str) or not key.strip() or key in item_keys:
            raise QueueError("원본 게시 작업의 중복 방지 키가 비어 있거나 중복됩니다.")
        if status == "processing":
            raise QueueError("처리 중인 게시 작업을 먼저 확인한 후 대기열 이전을 다시 실행하세요.")
        platform = item.get("platform")
        if not isinstance(status, str) or status not in statuses or platform not in PLATFORMS:
            raise QueueError("원본 게시 작업 상태나 플랫폼이 올바르지 않습니다.")
        if status == "scheduled" and item.get("approved") is not True:
            raise QueueError("명시적 승인이 없는 예약 작업이 포함되어 있습니다.")
        content_id = item.get("content_id")
        payload = item.get("payload")
        if not isinstance(content_id, str) or not content_id.strip() or not isinstance(payload, dict):
            raise QueueError("원본 게시 작업의 콘텐츠 식별자나 내용이 올바르지 않습니다.")
        try:
            expected_key = _identity(content_id, platform, payload)
        except (UnicodeError, ValueError):
            raise QueueError("원본 게시 작업의 내용을 검증할 수 없습니다.") from None
        if key != expected_key or item_id != key[:24]:
            raise QueueError("원본 게시 작업의 중복 방지 키가 내용과 일치하지 않습니다.")
        item_ids.add(item_id)
        item_keys.add(key)

    history_keys = set()
    for record in state["history"]:
        key = record.get("idempotency_key")
        remote_id = record.get("remote_id")
        if not isinstance(key, str) or not key.strip() or key in history_keys:
            raise QueueError("원본 게시 이력의 중복 방지 키가 비어 있거나 중복됩니다.")
        if not isinstance(remote_id, str) or not remote_id.strip():
            raise QueueError("유효한 외부 게시 ID가 없는 이력이 포함되어 있습니다.")
        history_keys.add(key)
    try:
        encoded = json.dumps(state, ensure_ascii=False, allow_nan=False)
        encoded.encode("utf-8")
    except (UnicodeError, ValueError):
        raise QueueError("원본 게시 대기열에 Postgres가 저장할 수 없는 값이 있습니다.") from None
    return state


def export_state(destination: Path, state: dict) -> None:
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=destination.parent, delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(state, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary_path, destination)
        try:
            directory_fd = os.open(destination.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    except FileExistsError:
        raise QueueError("대기열 내보내기 경로에 파일이 이미 있습니다.") from None
    except OSError:
        raise QueueError("대기열을 새 파일로 내보내지 못했습니다.") from None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--source", type=Path, help="정지된 파일 대기열의 JSON 복사본")
    source.add_argument("--empty", action="store_true", help="기존 데이터가 없는 신규 설치")
    source.add_argument("--export", type=Path, help="Postgres 대기열을 새 JSON 파일로 저장")
    parser.add_argument("--apply", action="store_true", help="Postgres에 초기 상태 삽입")
    args = parser.parse_args(argv)
    try:
        publishing_enabled = os.getenv("TAK_AUTO_PUBLISHING_ENABLED", "").strip().lower() == "true"
        root_cert = os.getenv("TAK_AUTO_QUEUE_SSL_ROOT_CERT", "").strip() or "system"
        if args.export is not None:
            if args.apply:
                parser.error("--export에는 --apply가 필요하지 않습니다.")
            if publishing_enabled:
                raise QueueError("내보내기 전에 실제 게시 기능을 끄세요.")
            store = PostgresQueueStore(os.getenv("TAK_AUTO_QUEUE_DSN", ""), ssl_root_cert=root_cert)
            revision, state = store.read()
            export_state(args.export, validate_transfer_state(state))
            print(f"내보내기 완료 · 리비전 {revision} · 대기열 {len(state['items'])}건 · 게시 이력 {len(state['history'])}건")
            return 0
        state = {"version": 1, "items": [], "history": []} if args.empty else load_import_state(args.source)
        print(f"검증 완료 · 대기열 {len(state['items'])}건 · 게시 이력 {len(state['history'])}건")
        if not args.apply:
            return 0
        if publishing_enabled:
            raise QueueError("가져오기 전에 실제 게시 기능을 끄세요.")
        store = PostgresQueueStore(
            os.getenv("TAK_AUTO_QUEUE_IMPORT_DSN", ""),
            ssl_root_cert=root_cert,
        )
        if store.initialize(state):
            print("Postgres 대기열을 초기화했습니다.")
        else:
            print("Postgres에 동일한 대기열이 이미 저장되어 있습니다.")
        return 0
    except QueueError as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
