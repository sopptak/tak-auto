"""TAK AUTO 성과(Performance) 데이터 기반(6-01).

KNOWLEDGE -> MEDIA -> HUMAN REVIEW -> PUBLISH 다음 단계인
"실제 채널 성과 수집 -> 콘텐츠별 성과 기록 -> 분석"을 위한 패키지.

이 패키지가 절대 하지 않는 것(6-01 설계 결정, docs/6-01_operational_loop_and_performance.md
15장 참고):
    - 성과 데이터를 TAK BRAIN/SCOUT scoring에 자동으로 반영하는 것 (그런 코드가
      아예 없다 - 사람이 분석 결과를 보고 판단하는 단계까지만 만든다)
    - 실제 외부 API를 이 패키지의 import만으로 호출하는 것 (fetch는 항상
      명시적으로 client를 만들고 메서드를 호출해야 실행된다)
"""

from .models import PerformanceRecord, PerformanceRecordError
from .store import (
    append_snapshot,
    append_snapshots,
    latest_snapshot_per_content,
    load_snapshots,
    snapshots_for_content,
)
from .summary import (
    ContentPerformanceSummary,
    pick_headline_metric,
    render_text_trend,
    summarize_content_history,
)

__all__ = [
    "PerformanceRecord",
    "PerformanceRecordError",
    "append_snapshot",
    "append_snapshots",
    "latest_snapshot_per_content",
    "load_snapshots",
    "snapshots_for_content",
    "ContentPerformanceSummary",
    "pick_headline_metric",
    "render_text_trend",
    "summarize_content_history",
]
