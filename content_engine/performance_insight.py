"""Performance Insight(6-35) - Performance 원자료에서 계산한 파생 분석 결과.

핵심 경계(절대 원칙, docs/6-35-performance-feedback-loop.md 참고):
    - Performance(``content_engine/performance/``)는 원자료(source of truth)다 -
      이 모듈은 그 파일/레코드를 어디에서도 쓰지 않는다(읽기만 한다).
    - Insight는 Performance를 분석한 **파생** 결과다 - 별도 저장소
      (``data/tak_performance_insights.json``, 이 모듈이 실제로 만들지는
      않는다)에 독립적으로 저장한다.
    - Insight 분석/재생성이 Performance 원자료를 수정하지 않는다.
    - Insight가 KNOWLEDGE/MEDIA를 자동으로 수정/생성하지 않는다 - 이 모듈에는
      ``content_engine.media_archive``/``tak_brain`` 쓰기 함수를 import하지
      않는다.
    - "이게 최고다"/"이걸 써라" 같은 자동 콘텐츠 전략 판단을 만들지 않는다 -
      중립적 상태값(INCREASING/ABOVE_BASELINE 등)과 근거만 제공한다. 최종
      해석은 사람이 한다.

이 모듈이 새로 만드는 저장 구조는 ``content_engine/performance/store.py``와
동일한 관례(append-only, tempfile + Path.replace() 원자적 저장, 중복 키는
조용히 건너뜀)를 그대로 재사용한다 - 새 패턴을 만들지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics
import tempfile
from typing import Any

from content_engine.performance.models import PerformanceRecord
from content_engine.performance.window import classify_measurement_window


# --- 상수 ------------------------------------------------------------------

SCOPES = ("content", "generation", "knowledge", "platform")

INSIGHT_TYPES = ("trend", "comparison", "anomaly", "traceability", "monetization", "distribution")
# distribution/monetization은 6-35에서 FUTURE로만 문서화했다(5장) - 이
# 목록에는 있지만 분석 함수는 아직 없다("실제로 구현할 가치가 있는 것만
# IMPLEMENTED"). 나중에 만들 때 이 상수를 먼저 바꾸지 않아도 되게 미리
# 예약해 둔다.

STATUS_CANDIDATE = "candidate"
STATUS_ACCEPTED = "accepted"
STATUS_REJECTED = "rejected"
STATUSES = (STATUS_CANDIDATE, STATUS_ACCEPTED, STATUS_REJECTED)

# Trend
TREND_INCREASING = "INCREASING"
TREND_DECREASING = "DECREASING"
TREND_STABLE = "STABLE"
TREND_UNKNOWN = "UNKNOWN"

# Comparison(baseline)
ABOVE_BASELINE = "ABOVE_BASELINE"
BELOW_BASELINE = "BELOW_BASELINE"
NEAR_BASELINE = "NEAR_BASELINE"
COMPARISON_UNKNOWN = "UNKNOWN"
INCOMPARABLE = "INCOMPARABLE"

# Anomaly
OUTLIER_DETECTED = "OUTLIER_DETECTED"
NO_OUTLIER = "NO_OUTLIER"

# Traceability
CONSISTENT = "CONSISTENT"
INCONSISTENT = "INCONSISTENT"

# 공통(sample 부족)
INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"

# 8장 지시: 표본이 부족하면 강제로 Insight를 만들지 않는다 - 최소 3건
# (첫값/끝값만으로는 "추세"를 말하기 부족하다고 판단, 중간값이 최소 1개는
# 있어야 한다). 6장/9장의 synthetic 표본 테스트(1/2/3/5/10/20)가 이 경계값을
# 검증한다.
MIN_SAMPLE_SIZE = 3

# NEAR_BASELINE으로 볼 허용 오차(±20%) - 통계 기능을 과도하게 만들지 않기
# 위해 단순 비율 기준만 쓴다(10장 지시와 동일한 절제 원칙).
BASELINE_TOLERANCE_RATIO = 0.2

# outlier 판정 배수 - 나머지 값들의 중앙값보다 이 배수 이상 크거나 작으면
# outlier로 본다(단순하고 설명 가능한 방법, 10장 지시).
OUTLIER_RATIO = 3.0

# MediaArchiveRecord.platform(콘텐츠 생성 단위: "blog"/"shorts"/"threads")과
# PerformanceRecord.platform(실제 게시 채널: "blog"/"youtube"/"threads")은
# 이름이 다르다 - "shorts"로 생성된 콘텐츠가 YouTube에 업로드되기
# 때문이다(content_engine/performance/youtube.py, migration.py가 이미
# platform="youtube"를 하드코딩하고 있다 - 6-35에서 처음 발견, 이 모듈이
# 두 값을 혼동하지 않도록 명시적 매핑을 제공한다).
MEDIA_PLATFORM_TO_PERFORMANCE_PLATFORM: dict[str, str] = {
    "blog": "blog",
    "shorts": "youtube",
    "threads": "threads",
}


class InsightError(ValueError):
    """Insight 레코드 구조가 올바르지 않을 때 발생한다."""


@dataclass(frozen=True)
class InsightRecord:
    """Insight 1건(6-35 4장). Performance와 마찬가지로 append-only 스냅샷이다 -
    같은 입력 데이터로 재분석하면 ``insight_id``가 동일해(``compute_insight_id()``
    가 evidence의 내용까지 지문에 포함) 자연히 idempotent하다(23장).

    ``confidence`` 필드를 두지 않았다 - 근거 없는 신뢰도 점수를 지어내지
    않기 위해서다(5장 지시 "필요 없는 필드는 제거한다"). 대신 ``sample_size``
    (명시적 표본 수)만 남겨, 신뢰도 판단은 사람이 sample_size와 evidence를
    보고 직접 한다.
    """

    insight_id: str
    created_at: str
    analysis_window: str
    scope: str
    scope_id: str
    platform: str
    metric: str
    insight_type: str
    result: str
    observation: str
    evidence: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    sample_size: int = 0
    status: str = STATUS_CANDIDATE

    def __post_init__(self) -> None:
        if not self.insight_id:
            raise InsightError("insight_id가 필요합니다.")
        if self.scope not in SCOPES:
            raise InsightError(f"scope는 {SCOPES} 중 하나여야 합니다: {self.scope!r}")
        if self.insight_type not in INSIGHT_TYPES:
            raise InsightError(f"insight_type은 {INSIGHT_TYPES} 중 하나여야 합니다: {self.insight_type!r}")
        if self.status not in STATUSES:
            raise InsightError(f"status는 {STATUSES} 중 하나여야 합니다: {self.status!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "insight_id": self.insight_id,
            "created_at": self.created_at,
            "analysis_window": self.analysis_window,
            "scope": self.scope,
            "scope_id": self.scope_id,
            "platform": self.platform,
            "metric": self.metric,
            "insight_type": self.insight_type,
            "result": self.result,
            "observation": self.observation,
            "evidence": [dict(item) for item in self.evidence],
            "sample_size": self.sample_size,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InsightRecord":
        if not isinstance(data, dict):
            raise InsightError("Insight 레코드는 객체(dict)여야 합니다.")
        evidence_raw = data.get("evidence") or []
        if not isinstance(evidence_raw, list):
            raise InsightError("evidence는 목록(list) 구조여야 합니다.")
        return cls(
            insight_id=str(data.get("insight_id") or ""),
            created_at=str(data.get("created_at") or ""),
            analysis_window=str(data.get("analysis_window") or ""),
            scope=str(data.get("scope") or ""),
            scope_id=str(data.get("scope_id") or ""),
            platform=str(data.get("platform") or ""),
            metric=str(data.get("metric") or ""),
            insight_type=str(data.get("insight_type") or ""),
            result=str(data.get("result") or ""),
            observation=str(data.get("observation") or ""),
            evidence=tuple(item for item in evidence_raw if isinstance(item, dict)),
            sample_size=int(data.get("sample_size") or 0),
            status=str(data.get("status") or STATUS_CANDIDATE),
        )


def compute_insight_id(
    *, scope: str, scope_id: str, platform: str, metric: str, analysis_window: str, insight_type: str,
    evidence: tuple[dict[str, Any], ...],
) -> str:
    """분석에 사용된 입력 전체(scope/metric/window/evidence)의 결정적
    지문을 만든다 - 같은 Performance 스냅샷 집합으로 다시 분석하면 항상
    같은 insight_id가 나오므로(``content_engine.publish_history.compute_content_id()``와
    동일한 설계 원칙, 6-34 11장에서 이미 확인한 패턴), 저장소가 이 값을
    dedup key로 쓰면 자연히 idempotent해진다(23장)."""
    fingerprint_source = {
        "scope": scope,
        "scope_id": scope_id,
        "platform": platform,
        "metric": metric,
        "analysis_window": analysis_window,
        "insight_type": insight_type,
        "evidence": [
            {"content_id": e.get("content_id", ""), "metric_collected_at": e.get("metric_collected_at", ""), "value": e.get("value")}
            for e in evidence
        ],
    }
    fingerprint = json.dumps(fingerprint_source, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:16]
    return f"insight-{digest}"


def _evidence_from_records(records: list[PerformanceRecord], metric: str) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "content_id": record.content_id,
            "metric_collected_at": record.metric_collected_at,
            "value": record.metrics.get(metric),
        }
        for record in records
        if metric in record.metrics
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- Trend(9장) ---------------------------------------------------------------


def analyze_trend(
    records: list[PerformanceRecord],
    *,
    scope: str,
    scope_id: str,
    platform: str,
    metric: str,
    analysis_window: str = "all",
) -> InsightRecord:
    """metric의 시계열이 증가/감소/보합인지 분류한다. 표본이
    ``MIN_SAMPLE_SIZE`` 미만이면 ``INSUFFICIENT_SAMPLE``을 반환한다(8장) -
    Insight를 억지로 만들지 않는다."""
    ordered = sorted(
        (r for r in records if metric in r.metrics),
        key=lambda r: r.metric_collected_at,
    )
    evidence = _evidence_from_records(ordered, metric)
    values = [item["value"] for item in evidence]

    if len(values) < MIN_SAMPLE_SIZE:
        result = INSUFFICIENT_SAMPLE
        observation = f"표본이 부족합니다({len(values)}건, 최소 {MIN_SAMPLE_SIZE}건 필요) - 추세를 판단하지 않습니다."
    else:
        first, last = values[0], values[-1]
        if first == 0 and last == 0:
            result = TREND_STABLE
        elif last > first:
            result = TREND_INCREASING
        elif last < first:
            result = TREND_DECREASING
        else:
            result = TREND_STABLE
        trend_text = " → ".join(f"{v:,}" for v in values)
        observation = f"{trend_text} ({result})"

    insight_id = compute_insight_id(
        scope=scope, scope_id=scope_id, platform=platform, metric=metric,
        analysis_window=analysis_window, insight_type="trend", evidence=evidence,
    )
    return InsightRecord(
        insight_id=insight_id, created_at=_now(), analysis_window=analysis_window,
        scope=scope, scope_id=scope_id, platform=platform, metric=metric,
        insight_type="trend", result=result, observation=observation,
        evidence=evidence, sample_size=len(values),
    )


# --- Anomaly / Outlier(10장) --------------------------------------------------


def detect_anomaly(
    records: list[PerformanceRecord],
    *,
    scope: str,
    scope_id: str,
    platform: str,
    metric: str,
    analysis_window: str = "all",
) -> InsightRecord:
    """가장 최근 값이 나머지 값들의 중앙값 대비 ``OUTLIER_RATIO`` 배 이상
    벗어나면 outlier로 본다(단순 median 기반, 10장 지시: 통계 기능을 과도하게
    만들지 않는다). 표본 부족 시 ``INSUFFICIENT_SAMPLE``."""
    ordered = sorted(
        (r for r in records if metric in r.metrics),
        key=lambda r: r.metric_collected_at,
    )
    evidence = _evidence_from_records(ordered, metric)
    values = [item["value"] for item in evidence]

    if len(values) < MIN_SAMPLE_SIZE:
        result = INSUFFICIENT_SAMPLE
        observation = f"표본이 부족합니다({len(values)}건, 최소 {MIN_SAMPLE_SIZE}건 필요) - outlier를 판단하지 않습니다."
    else:
        latest = values[-1]
        rest = values[:-1]
        rest_median = statistics.median(rest) if rest else 0
        if rest_median == 0:
            is_outlier = latest != 0
        else:
            is_outlier = abs(latest - rest_median) >= rest_median * OUTLIER_RATIO
        result = OUTLIER_DETECTED if is_outlier else NO_OUTLIER
        observation = f"최신값 {latest:,}, 나머지 중앙값 {rest_median:,.0f} ({result})"

    insight_id = compute_insight_id(
        scope=scope, scope_id=scope_id, platform=platform, metric=metric,
        analysis_window=analysis_window, insight_type="anomaly", evidence=evidence,
    )
    return InsightRecord(
        insight_id=insight_id, created_at=_now(), analysis_window=analysis_window,
        scope=scope, scope_id=scope_id, platform=platform, metric=metric,
        insight_type="anomaly", result=result, observation=observation,
        evidence=evidence, sample_size=len(values),
    )


# --- Comparison / Baseline(6/7장) ----------------------------------------------


def check_comparable(
    *, platform_a: str, window_a: str, platform_b: str, window_b: str
) -> bool:
    """서로 다른 조건(platform/measurement window)의 데이터를 비교해도
    되는지 판정한다(6장 - "YouTube 24h views vs Blog 30d views를 같은
    기준으로 비교하지 않는다"). content_type/knowledge_id/generation_id/
    content_id는 호출부가 scope/scope_id로 이미 분리해서 넘기므로(각
    scope는 항상 단일 platform 값을 갖는다, 11/13장), 이 함수는 platform과
    window만 검사한다."""
    return platform_a == platform_b and window_a == window_b


def compare_to_baseline(
    target_value: int,
    baseline_records: list[PerformanceRecord],
    *,
    scope: str,
    scope_id: str,
    platform: str,
    metric: str,
    analysis_window: str,
    target_platform: str | None = None,
    target_window: str | None = None,
) -> InsightRecord:
    """target_value(예: 이 콘텐츠의 최신 조회수)를 baseline(같은 platform +
    같은 measurement window의 다른 콘텐츠 평균)과 비교한다(7장). 자동으로
    BEST/WORST/WINNER를 만들지 않는다 - ABOVE_BASELINE/BELOW_BASELINE/
    NEAR_BASELINE/UNKNOWN 중립 상태만 반환한다.

    ``target_platform``/``target_window``를 명시하면 baseline과 조건이
    일치하는지 먼저 검사해 불일치 시 ``INCOMPARABLE``을 반환한다(6장).
    """
    if target_platform is not None and target_platform != platform:
        result = INCOMPARABLE
        observation = f"platform이 다릅니다(target={target_platform!r}, baseline={platform!r}) - 비교하지 않습니다."
        evidence: tuple[dict[str, Any], ...] = ()
        sample_size = 0
    elif target_window is not None and target_window != analysis_window:
        result = INCOMPARABLE
        observation = f"measurement window가 다릅니다(target={target_window!r}, baseline={analysis_window!r}) - 비교하지 않습니다."
        evidence = ()
        sample_size = 0
    else:
        baseline_values = [
            r.metrics[metric] for r in baseline_records
            if metric in r.metrics and classify_measurement_window(r.published_at, r.metric_collected_at) == analysis_window
        ]
        evidence = tuple(
            {"content_id": r.content_id, "metric_collected_at": r.metric_collected_at, "value": r.metrics.get(metric)}
            for r in baseline_records if metric in r.metrics
        )
        sample_size = len(baseline_values)
        if sample_size < MIN_SAMPLE_SIZE:
            result = COMPARISON_UNKNOWN
            observation = f"baseline 표본이 부족합니다({sample_size}건, 최소 {MIN_SAMPLE_SIZE}건 필요)."
        else:
            baseline_mean = statistics.mean(baseline_values)
            if baseline_mean == 0:
                result = COMPARISON_UNKNOWN
                observation = "baseline 평균이 0이라 비교할 수 없습니다."
            else:
                ratio = (target_value - baseline_mean) / baseline_mean
                if ratio > BASELINE_TOLERANCE_RATIO:
                    result = ABOVE_BASELINE
                elif ratio < -BASELINE_TOLERANCE_RATIO:
                    result = BELOW_BASELINE
                else:
                    result = NEAR_BASELINE
                observation = f"target={target_value:,}, baseline 평균={baseline_mean:,.1f}({sample_size}건) ({result})"

    insight_id = compute_insight_id(
        scope=scope, scope_id=scope_id, platform=platform, metric=metric,
        analysis_window=analysis_window, insight_type="comparison", evidence=evidence,
    )
    return InsightRecord(
        insight_id=insight_id, created_at=_now(), analysis_window=analysis_window,
        scope=scope, scope_id=scope_id, platform=platform, metric=metric,
        insight_type="comparison", result=result, observation=observation,
        evidence=evidence, sample_size=sample_size,
    )


# --- Traceability(13/25장) ------------------------------------------------------


def check_traceability(
    *, content_id: str, knowledge_id: str, generation_id: str, performance_records: list[PerformanceRecord]
) -> InsightRecord:
    """이 content_id의 Performance 스냅샷들이 실제로 같은 knowledge_id를
    가리키는지 확인한다(identity 체인 무결성) - KNOWLEDGE/MEDIA를 수정하지
    않고 읽기만 한다."""
    matching = [r for r in performance_records if r.content_id == content_id]
    mismatched = [r for r in matching if r.knowledge_id != knowledge_id]
    evidence = tuple(
        {"content_id": r.content_id, "metric_collected_at": r.metric_collected_at, "value": r.knowledge_id}
        for r in matching
    )
    if not matching:
        result = INCONSISTENT
        observation = f"content_id={content_id}에 대한 성과 레코드가 없습니다 - 추적할 수 없습니다."
    elif mismatched:
        result = INCONSISTENT
        observation = f"content_id={content_id}의 일부 레코드가 다른 knowledge_id를 가리킵니다: {sorted({r.knowledge_id for r in mismatched})}"
    else:
        result = CONSISTENT
        observation = f"content_id={content_id}의 모든 성과 레코드가 knowledge_id={knowledge_id}와 일치합니다."

    insight_id = compute_insight_id(
        scope="content", scope_id=content_id, platform="", metric="__identity__",
        analysis_window="all", insight_type="traceability", evidence=evidence,
    )
    return InsightRecord(
        insight_id=insight_id, created_at=_now(), analysis_window="all",
        scope="content", scope_id=content_id, platform="", metric="__identity__",
        insight_type="traceability", result=result, observation=observation,
        evidence=evidence, sample_size=len(matching),
    )


# --- 저장소(content_engine/performance/store.py와 동일한 관례) ------------------


def load_insights(path: Path | str) -> list[InsightRecord]:
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
        raise InsightError(f"Insight 저장소 파일이 올바른 JSON이 아닙니다: {target}") from error
    if not isinstance(data, list):
        raise InsightError(f"Insight 저장소 파일은 목록(list) 구조여야 합니다: {target}")
    return [InsightRecord.from_dict(item) for item in data]


def _save(records: list[InsightRecord], path: Path | str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = [record.to_dict() for record in records]
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temp_path = Path(handle.name)
    temp_path.replace(target)


def append_insights(path: Path | str, records: list[InsightRecord]) -> int:
    """여러 건을 한 번에 추가한다 - insight_id가 같으면(즉 같은 입력
    데이터로 재분석한 결과라면) 건너뛴다(23장 idempotency). status는
    새 레코드로 덮어쓰지 않는다 - 이미 사람이 accepted/rejected로
    검토한 것을 재분석이 조용히 candidate로 되돌리면 안 되기 때문이다."""
    existing = load_insights(path)
    existing_ids = {item.insight_id for item in existing}
    added = 0
    for record in records:
        if record.insight_id in existing_ids:
            continue
        existing.append(record)
        existing_ids.add(record.insight_id)
        added += 1
    if added:
        _save(existing, path)
    return added


def append_insight(path: Path | str, record: InsightRecord) -> bool:
    return append_insights(path, [record]) > 0


def insights_for_scope(path: Path | str, scope: str, scope_id: str) -> list[InsightRecord]:
    return [r for r in load_insights(path) if r.scope == scope and r.scope_id == scope_id]


def set_insight_status(path: Path | str, insight_id: str, new_status: str) -> InsightRecord:
    """사람의 검토 결과(19장: CANDIDATE -> ACCEPTED/REJECTED)를 반영한다.
    status 외의 어떤 필드도 바꾸지 않는다(분석 결과 자체는 불변) - accepted
    되어도 KNOWLEDGE/MEDIA를 자동으로 바꾸는 코드는 이 함수 어디에도
    없다(사람이 검토했다는 사실만 기록한다)."""
    if new_status not in STATUSES:
        raise InsightError(f"status는 {STATUSES} 중 하나여야 합니다: {new_status!r}")
    records = load_insights(path)
    updated_record: InsightRecord | None = None
    result: list[InsightRecord] = []
    for record in records:
        if record.insight_id == insight_id:
            updated_record = InsightRecord(
                insight_id=record.insight_id, created_at=record.created_at,
                analysis_window=record.analysis_window, scope=record.scope,
                scope_id=record.scope_id, platform=record.platform, metric=record.metric,
                insight_type=record.insight_type, result=record.result,
                observation=record.observation, evidence=record.evidence,
                sample_size=record.sample_size, status=new_status,
            )
            result.append(updated_record)
        else:
            result.append(record)
    if updated_record is None:
        raise InsightError(f"insight_id를 찾을 수 없습니다: {insight_id}")
    _save(result, path)
    return updated_record
