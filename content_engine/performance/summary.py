"""content_id 1건의 시계열 스냅샷을 사람이 읽을 수 있는 추이로 요약한다(6-02).

/performance 화면(scripts/run_scout_dashboard.py)이 이 모듈을 호출해 "성과가
시간에 따라 어떻게 변했는지"를 보여준다. 이 모듈은 순수 함수로만 구성되어
있고(파일을 읽거나 쓰지 않는다), 이미 store.py가 로드한 PerformanceRecord
목록만 입력으로 받는다 - Dashboard 라우트가 store.snapshots_for_content()로
읽어온 뒤 이 모듈에 넘기는 구조다(책임 분리, media_archive.py를 읽기만 하고
가공은 scripts/run_scout_dashboard.py의 렌더 함수가 하는 기존 관례와 동일).

metric 종류는 플랫폼마다 다르므로(Threads: views/likes/replies/reposts/quotes/
shares, YouTube: views/likes/comments, Blog: 사람이 입력한 임의의 키) 이 모듈
어디에도 특정 metric 이름을 하드코딩하지 않는다 - 실제 스냅샷에 들어있는 키만
사용한다. 없는 metric을 0으로 지어내지 않는다: 두 스냅샷을 비교할 때 한쪽에만
있는 metric은 변화량 계산에서 제외한다(0으로 가정하지 않는다 - 그 채널이
"조회수 0"이었는지 "애초에 그 시점엔 그 metric을 수집하지 않았는지" 구분할 수
없기 때문이다).
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import PerformanceRecord
from .store import _sort_key


@dataclass(frozen=True)
class ContentPerformanceSummary:
    """content_id 1건의 전체 스냅샷 이력을 요약한 결과.

    ``history``는 시간순(오름차순)으로 정렬된 전체 스냅샷 목록이다 - trend
    렌더링(render_text_trend)이 first/previous/latest만 조합해서 재구성하면
    스냅샷이 2개뿐일 때 first와 previous가 같은 레코드를 가리켜 "100 → 100 →
    850"처럼 값이 중복 표시되는 문제가 있었다(6-02에서 발견/수정) - 전체 이력을
    그대로 들고 있으면 이 문제가 원천적으로 없다.
    """

    content_id: str
    platform: str
    first: PerformanceRecord
    latest: PerformanceRecord
    previous: PerformanceRecord | None
    snapshot_count: int
    history: tuple[PerformanceRecord, ...]

    @property
    def baseline_is_migration(self) -> bool:
        """첫 스냅샷이 실제 성과가 아니라 발행 사실만 옮긴 placeholder인지.

        True면 변화량(delta)을 "실제 성과 비교의 기준점"으로 오해하면 안 된다
        (6-02 4장 지시) - 화면이 이 값을 보고 경고 문구를 함께 보여준다.
        """
        return self.first.source == "migration_baseline"

    def metric_delta(self) -> dict[str, int]:
        """최초 스냅샷 대비 최신 스냅샷의 변화량. 두 스냅샷 모두에 있는
        metric만 계산한다(없는 쪽을 0으로 가정하지 않는다). 스냅샷이 1개뿐이면
        (변화를 말할 수 없으므로) 빈 dict를 반환한다."""
        if self.snapshot_count < 2:
            return {}
        common_keys = set(self.first.metrics) & set(self.latest.metrics)
        return {key: self.latest.metrics[key] - self.first.metrics[key] for key in sorted(common_keys)}

    def previous_metric_delta(self) -> dict[str, int]:
        """바로 이전 스냅샷 대비 최신 스냅샷의 변화량(최근 추세 확인용)."""
        if self.previous is None:
            return {}
        common_keys = set(self.previous.metrics) & set(self.latest.metrics)
        return {key: self.latest.metrics[key] - self.previous.metrics[key] for key in sorted(common_keys)}


def summarize_content_history(records: list[PerformanceRecord]) -> ContentPerformanceSummary | None:
    """content_id 1건의 스냅샷 목록(순서 무관)을 요약한다. 비어있으면 None."""
    if not records:
        return None
    ordered = sorted(records, key=_sort_key)
    first = ordered[0]
    latest = ordered[-1]
    previous = ordered[-2] if len(ordered) >= 2 else None
    return ContentPerformanceSummary(
        content_id=latest.content_id,
        platform=latest.platform,
        first=first,
        latest=latest,
        previous=previous,
        snapshot_count=len(ordered),
        history=tuple(ordered),
    )


def pick_headline_metric(records: list[PerformanceRecord]) -> str | None:
    """추이(sparkline)에 쓸 대표 metric 1개를 고른다.

    하드코딩하지 않는다 - 스냅샷에 실제로 등장한 metric 이름 중에서, 관례적으로
    가장 "조회 규모"를 나타내는 이름("views")이 있으면 그것을 쓰고, 없으면 실제
    등장한 metric 이름을 알파벳순으로 정렬해 첫 번째를 쓴다(플랫폼이 늘어나도
    이 함수를 수정할 필요가 없다).
    """
    all_keys: set[str] = set()
    for record in records:
        all_keys.update(record.metrics.keys())
    if not all_keys:
        return None
    if "views" in all_keys:
        return "views"
    return sorted(all_keys)[0]


def render_text_trend(records: list[PerformanceRecord], metric_name: str) -> str:
    """지정한 metric의 시계열 값을 "100 → 430 → 2,300" 형태의 텍스트로 만든다.

    metric_name이 없는 스냅샷은 건너뛴다(0으로 채우지 않는다). 값이 하나도 없으면
    빈 문자열을 반환한다.
    """
    ordered = sorted(records, key=_sort_key)
    values = [record.metrics[metric_name] for record in ordered if metric_name in record.metrics]
    if not values:
        return ""
    return " → ".join(f"{value:,}" for value in values)
