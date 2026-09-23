"""측정 시점을 게시 후 경과 시간 기준 window로 분류한다(6-34).

콘텐츠 성과는 게시 직후와 장기 성과가 다르다(예: Shorts는 24h 안에 대부분의
조회가 몰리고, Blog는 검색 유입으로 몇 주에 걸쳐 천천히 쌓인다) - 하나의
숫자로 "성과가 좋다/나쁘다"를 억지로 통일하지 않기 위해, 최소한의 표준
window(24h/72h/7d/30d)로만 분류한다. 이 모듈은 분류만 한다 - 어떤 window가
"좋은 성과"인지는 판단하지 않는다(사람이 판단, 6-34 15장 원칙).

새 저장 구조를 만들지 않는다 - 기존 ``PerformanceRecord.published_at``/
``metric_collected_at``(이미 저장되어 있는 필드)만으로 계산하는 순수 함수다.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .store import _parse_collected_at

WINDOW_24H = "24h"
WINDOW_72H = "72h"
WINDOW_7D = "7d"
WINDOW_30D = "30d"
WINDOW_BEYOND_30D = "beyond_30d"
WINDOW_UNKNOWN = "unknown"

# (window 이름, 그 window의 상한 시간) - 순서대로 검사해 처음 맞는 것을 쓴다.
_WINDOW_BOUNDS_HOURS: tuple[tuple[str, float], ...] = (
    (WINDOW_24H, 24),
    (WINDOW_72H, 72),
    (WINDOW_7D, 24 * 7),
    (WINDOW_30D, 24 * 30),
)


def classify_measurement_window(published_at: str, metric_collected_at: str) -> str:
    """게시 시각 대비 측정 시각의 경과 시간을 표준 window로 분류한다.

    둘 중 하나라도 파싱할 수 없거나, 측정 시각이 게시 시각보다 이전이면
    ``"unknown"``을 반환한다(추측하지 않는다) - 24h~30d 어디에도 속하지 않을
    만큼 오래됐으면(30일 초과) ``"beyond_30d"``.
    """
    published = _parse_collected_at(published_at)
    collected = _parse_collected_at(metric_collected_at)
    if published is None or collected is None:
        return WINDOW_UNKNOWN
    elapsed_hours = (collected - published).total_seconds() / 3600
    if elapsed_hours < 0:
        return WINDOW_UNKNOWN
    for name, upper_bound_hours in _WINDOW_BOUNDS_HOURS:
        if elapsed_hours <= upper_bound_hours:
            return name
    return WINDOW_BEYOND_30D
