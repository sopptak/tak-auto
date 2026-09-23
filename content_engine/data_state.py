"""파일/디렉터리의 존재·유효성 상태를 판정하는 순수 함수 모음(6-21,
docs/6-21-data-sync-and-recovery-architecture.md).

원래 ``scripts/audit_data_state.py``에만 있던 판정 로직을 6-22(Recovery
Staging, docs/6-22-recovery-staging-and-reconciliation.md)가 그대로
재사용하기 위해 공유 모듈로 옮겼다 - "6-21에서 정의한 NOT_PRESENT/EMPTY/
VALID/CORRUPTED 상태 체계를 재사용하고 새로 중복 정의하지 말라"는 6-22 지시를
따른 것이며, 상태 판정 규칙 자체는 6-21에서 조금도 바꾸지 않았다.

네 가지 상태만 쓴다:
    - ``NOT_PRESENT``: 파일/디렉터리가 없음
    - ``EMPTY``: 있지만 내용이 없음(0바이트, 공백만, 또는 빈 디렉터리)
    - ``VALID``: 있고 파싱 가능(JSON) 또는 내용이 있음(디렉터리에 항목 존재)
    - ``CORRUPTED``: 있지만 파싱할 수 없음(JSON 파싱 실패)
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path

NOT_PRESENT = "NOT_PRESENT"
EMPTY = "EMPTY"
VALID = "VALID"
CORRUPTED = "CORRUPTED"

STATUSES = (NOT_PRESENT, EMPTY, VALID, CORRUPTED)


def json_file_status(path: Path | str) -> tuple[str, int | None]:
    """JSON 파일의 (status, record_count)를 반환한다.

    ``record_count``는 ``VALID``일 때만 채워진다 - 최상위가 list/dict면 그
    길이, 그 외(스칼라 값 등 비정상 최상위 타입)면 ``None``이다. 빈 배열
    (``[]``)은 ``EMPTY``가 아니라 ``VALID``/0건이다 - "파일이 없음"과 "파일은
    있고 유효한 JSON이지만 레코드가 0건"은 서로 다른 상태이기 때문이다.
    """
    target = Path(path)
    if not target.exists():
        return NOT_PRESENT, None
    raw = target.read_text(encoding="utf-8", errors="replace")
    if not raw.strip():
        return EMPTY, None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return CORRUPTED, None
    if isinstance(data, (list, dict)):
        return VALID, len(data)
    return VALID, None


def text_file_status(path: Path | str) -> str:
    """비-JSON 텍스트 파일(예: ``.md``)의 상태(``NOT_PRESENT``/``EMPTY``/``VALID``)."""
    target = Path(path)
    if not target.exists():
        return NOT_PRESENT
    if target.stat().st_size == 0:
        return EMPTY
    return VALID


def dir_status(path: Path | str, glob: str = "*") -> tuple[str, int | None]:
    """디렉터리의 (status, glob에 매칭되는 항목 수)를 반환한다.

    디렉터리가 있지만 실제로는 파일이면(예상치 못한 상태) ``CORRUPTED``로
    표시한다 - 디렉터리를 기대한 자리에 파일이 있는 것은 구조적 이상이다.
    """
    target = Path(path)
    if not target.exists():
        return NOT_PRESENT, None
    if not target.is_dir():
        return CORRUPTED, None
    entries = sorted(target.glob(glob))
    if not entries:
        return EMPTY, 0
    return VALID, len(entries)


def format_mtime(path: Path | str) -> str:
    target = Path(path)
    if not target.exists():
        return "-"
    ts = target.stat().st_mtime
    return datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )
