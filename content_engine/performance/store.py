"""성과 스냅샷 저장소(6-01).

content_engine.media_archive/threads_review와 동일한 관례(JSON 배열 파일,
tempfile + Path.replace() 원자적 저장)를 따르되, 이 저장소는 upsert가 아니라
**append-only 시계열**이다 - 같은 content_id라도 수집 시점(metric_collected_at)이
다르면 새 스냅샷으로 계속 쌓인다. archive/publish_history가 "최신 상태 하나"를
관리하는 것과 달리, 성과는 "Day1 -> Day7 변화"를 보존해야 의미가 있기 때문이다.

같은 content_id + 같은 metric_collected_at 조합으로 두 번 저장을 시도하면(예:
같은 CLI 실행을 실수로 재실행) 중복 스냅샷을 만들지 않고 조용히 건너뛴다
(daily-media-prepare.yml의 "이미 생성된 Shorts는 재생성하지 않는다"와 동일한
idempotent 원칙).
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile

from .models import PerformanceRecord


DEFAULT_STORE_FILENAME = "tak_performance.json"


class PerformanceStoreError(ValueError):
    """성과 저장소 파일 구조가 올바르지 않을 때 발생한다."""


def _parse_collected_at(value: str) -> datetime | None:
    """metric_collected_at을 정렬 가능한 datetime으로 파싱한다.

    ``tak_scout.scoring._parse_datetime()``과 동일한 규칙(tz-naive는 UTC로
    간주)을 이 모듈에 그대로 복제했다 - content_engine이 tak_scout을 import하지
    않는 기존 패키지 경계를 유지하기 위함이다(6-02 조사, 기존 구조 변경 아님).
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _sort_key(record: PerformanceRecord) -> tuple[int, datetime | str]:
    """시각순 정렬 키(6-02).

    이전에는 ``metric_collected_at`` 문자열을 그대로 사전식(lexicographic)
    비교했다 - 값이 전부 같은 timezone offset(예: 전부 "+00:00")의 동일한
    ISO 8601 포맷이면 우연히 맞아떨어지지만, timezone-naive 값과 aware 값이
    섞이거나 offset이 다른(`+09:00` 등) 값이 섞이면 실제 시간 순서와 어긋날 수
    있다. 파싱 가능하면 실제 datetime으로 비교하고(tz-naive는 UTC로 간주),
    파싱할 수 없는 값(빈 문자열, 잘못된 포맷)은 맨 앞으로 보내 최소한 예외 없이
    동작하게 한다 - 튜플의 첫 원소(0/1)로 "파싱 성공 여부"를 먼저 비교해 파싱
    실패 항목과 datetime을 직접 비교하다 TypeError가 나는 것을 막는다.
    """
    parsed = _parse_collected_at(record.metric_collected_at)
    if parsed is None:
        return (0, record.metric_collected_at)
    return (1, parsed)


def load_snapshots(path: Path | str) -> list[PerformanceRecord]:
    """저장소 파일을 읽는다. 파일이 없거나 비어 있으면 빈 목록을 반환한다."""
    target = Path(path)
    if not target.exists():
        return []
    raw_text = target.read_text(encoding="utf-8").strip()
    if not raw_text:
        return []
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as error:
        raise PerformanceStoreError(f"성과 저장소 파일이 올바른 JSON이 아닙니다: {target}") from error
    if not isinstance(data, list):
        raise PerformanceStoreError(f"성과 저장소 파일은 목록(list) 구조여야 합니다: {target}")
    return [PerformanceRecord.from_dict(item) for item in data]


def _save(records: list[PerformanceRecord], path: Path | str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = [record.to_dict() for record in records]
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temp_path = Path(handle.name)
    temp_path.replace(target)


def _snapshot_key(record: PerformanceRecord) -> tuple[str, str]:
    """중복 판정 키 - 일부러 ``source``를 포함하지 않는다(6-02 검토 결과).

    (content_id, metric_collected_at)이 같다는 것은 "같은 콘텐츠를 같은 순간에
    측정했다"는 뜻이다 - source(threads_api/youtube_api/manual/migration_baseline)가
    다르더라도 같은 순간의 측정치라면 저장소 입장에서는 여전히 "이미 가진 값"으로
    취급하는 것이 맞다고 판단했다: 두 값이 서로 다르면 어느 쪽이 맞는지 이 모듈이
    판단할 근거가 없고, 조용히 나중 값으로 덮어쓰는 것도(정확한 값을 잃을 위험)
    바람직하지 않기 때문이다. "같은 순간에 다른 source로 다시 측정해 이전 값을
    명시적으로 교정하고 싶다"는 요구가 실제로 생기면, 그때 append_snapshot에
    ``overwrite=True`` 같은 별도 옵션을 추가하는 것을 권장한다(지금은 실제 운영
    데이터가 없어 이 요구가 검증되지 않았으므로 미리 만들지 않는다 - 17장 원칙).
    """
    return (record.content_id, record.metric_collected_at)


def append_snapshot(path: Path | str, record: PerformanceRecord) -> bool:
    """스냅샷 1건을 추가한다.

    이미 동일한 (content_id, metric_collected_at) 스냅샷이 있으면 아무 것도
    저장하지 않고 False를 반환한다. 새로 추가했으면 True를 반환한다.
    """
    return append_snapshots(path, [record]) > 0


def append_snapshots(path: Path | str, records: list[PerformanceRecord]) -> int:
    """여러 건을 한 번에 추가한다(파일 쓰기는 변경이 있을 때 1회만 일어난다).

    실제로 새로 추가된 건수를 반환한다(이미 존재하는 스냅샷은 건너뛴다).
    """
    existing = load_snapshots(path)
    existing_keys = {_snapshot_key(item) for item in existing}
    added = 0
    for record in records:
        key = _snapshot_key(record)
        if key in existing_keys:
            continue
        existing.append(record)
        existing_keys.add(key)
        added += 1
    if added:
        _save(existing, path)
    return added


def snapshots_for_content(path: Path | str, content_id: str) -> list[PerformanceRecord]:
    """특정 content_id의 스냅샷을 수집 시각(metric_collected_at) 오름차순으로 반환한다."""
    items = [record for record in load_snapshots(path) if record.content_id == content_id]
    return sorted(items, key=_sort_key)


def latest_snapshot_per_content(path: Path | str) -> dict[str, PerformanceRecord]:
    """content_id별로 가장 최근(metric_collected_at 기준) 스냅샷만 골라 반환한다."""
    latest: dict[str, PerformanceRecord] = {}
    for record in load_snapshots(path):
        current = latest.get(record.content_id)
        if current is None or _sort_key(record) > _sort_key(current):
            latest[record.content_id] = record
    return latest
