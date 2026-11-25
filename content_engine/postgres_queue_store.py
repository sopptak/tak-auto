"""Optimistic Postgres storage for the TAK AUTO publishing queue."""
from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
import json
import logging
import os
from pathlib import Path
from typing import Any

from .publishing_queue import PublishingQueue, QueueStoreError

_LOGGER = logging.getLogger(__name__)


def _failure_category(error: Exception) -> str:
    code = getattr(error, "sqlstate", None)
    message = str(error).lower()
    if code in {"28000", "28P01"} or "password authentication failed" in message or "tenant or user not found" in message:
        return "authentication"
    if "certificate" in message or "ssl error" in message:
        return "tls"
    if code == "42501":
        return "permissions"
    if code in {"42P01", "3F000"}:
        return "schema"
    if "timeout" in message or "timed out" in message or code in {"55P03", "57014"}:
        return "timeout"
    if isinstance(error, ValueError):
        return "configuration"
    return "database_unavailable"


def _encode_state(state: dict[str, Any]) -> str:
    return json.dumps(state, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))


class PostgresQueueStore:
    """Each write commits independently and checks the revision that was read."""

    def __init__(self, dsn: str, *, ssl_root_cert: str = "system", connect=None) -> None:
        if not dsn.strip():
            raise QueueStoreError("게시 대기열 데이터베이스 연결 설정이 없습니다.")
        self._dsn = dsn
        self._ssl_root_cert = ssl_root_cert
        self._connect = connect

    @contextmanager
    def _connection(self):
        try:
            import psycopg
        except ImportError:
            raise QueueStoreError("Postgres 게시 대기열에 필요한 드라이버가 없습니다.") from None

        connect = self._connect or psycopg.connect
        try:
            with connect(
                self._dsn, sslmode="verify-full", sslrootcert=self._ssl_root_cert,
                gssencmode="disable", target_session_attrs="read-write",
                connect_timeout=5, prepare_threshold=None,
            ) as connection:
                connection.execute("SET LOCAL statement_timeout = '5s'")
                connection.execute("SET LOCAL lock_timeout = '2s'")
                yield connection
        except (psycopg.Error, ValueError, OSError) as error:
            # Do not expose server messages, credentials, or the queue payload.
            _LOGGER.warning("Postgres queue connection check failed (%s)", _failure_category(error))
            raise QueueStoreError("게시 대기열 데이터베이스 요청을 완료하지 못했습니다.") from None

    def read(self) -> tuple[int, dict[str, Any]]:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT revision, state FROM tak_auto_private.publishing_queue WHERE singleton"
            ).fetchone()
        if row is None:
            raise QueueStoreError("Postgres 게시 대기열을 먼저 초기화하세요.")
        return row

    def ready(self) -> bool:
        """Check initialization and runtime grants without retrieving draft content."""
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT EXISTS (SELECT 1 FROM tak_auto_private.publishing_queue WHERE singleton)
                    AND has_column_privilege('tak_auto_private.publishing_queue', 'revision', 'UPDATE')
                    AND has_column_privilege('tak_auto_private.publishing_queue', 'state', 'UPDATE')
                """
            ).fetchone()
        return bool(row and row[0])

    def write(self, revision: int, state: dict[str, Any]) -> int:
        with self._connection() as connection:
            from psycopg.types.json import Json

            row = connection.execute(
                """UPDATE tak_auto_private.publishing_queue
                   SET revision = revision + 1, state = %s
                   WHERE singleton AND revision = %s
                   RETURNING revision""",
                (Json(state, dumps=_encode_state), revision),
            ).fetchone()
        if row is None:
            raise QueueStoreError("다른 요청이 게시 대기열을 변경했습니다. 새로고침 후 상태를 확인하세요.")
        return row[0]

    def initialize(self, state: dict[str, Any]) -> bool:
        """Insert an initial snapshot, or verify a repeated identical import."""
        with self._connection() as connection:
            encoded = _encode_state(state)
            inserted = connection.execute(
                """INSERT INTO tak_auto_private.publishing_queue (singleton, state)
                   VALUES (true, %s::json)
                   ON CONFLICT (singleton) DO NOTHING RETURNING singleton""",
                (encoded,),
            ).fetchone()
            if inserted:
                return True
            matching = connection.execute(
                "SELECT state::text = %s FROM tak_auto_private.publishing_queue WHERE singleton",
                (encoded,),
            ).fetchone()
        if matching and matching[0]:
            return False
        raise QueueStoreError("Postgres 대기열에 다른 데이터가 있어 가져오기를 중단했습니다.")


def open_publishing_queue(
    path: Path | str, environ: Mapping[str, str] | None = None,
) -> PublishingQueue:
    values = os.environ if environ is None else environ
    backend = queue_backend(values)
    if backend == "file":
        return PublishingQueue(path)
    if backend != "postgres":
        raise QueueStoreError("지원하지 않는 게시 대기열 저장 방식입니다.")
    store = PostgresQueueStore(
        values.get("TAK_AUTO_QUEUE_DSN", ""),
        ssl_root_cert=values.get("TAK_AUTO_QUEUE_SSL_ROOT_CERT", "").strip() or "system",
    )
    return PublishingQueue(path, store=store)


def queue_backend(environ: Mapping[str, str]) -> str:
    return environ.get("TAK_AUTO_QUEUE_BACKEND", "file").strip().lower()
