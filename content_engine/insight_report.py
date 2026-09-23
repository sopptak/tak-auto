"""Performance Insight 운영 레이어(6-36).

6-35(``content_engine/performance_insight.py``)가 Insight를 **분석**한다면,
이 모듈은 이미 계산된 Insight를 **운영 관점에서 정리**한다 - 새 분석을
수행하지 않는다(3장 지시: "Report는 분석을 새로 수행하는 시스템이 아니라
이미 생성된 Insight를 운영 관점에서 정리하는 계층"). 이 모듈이 읽는
것은 항상 이미 만들어진 ``InsightRecord``/``PerformanceRecord`` 목록뿐이고,
``content_engine.performance``/``content_engine.performance_insight``의
분석 함수를 다시 호출하지 않는다.

책임 분리(19장 API Boundary):
    - Performance Provider: ``content_engine/performance/*``(6-34, 원자료 수집/저장)
    - Insight Analyzer: ``content_engine/performance_insight.py``(6-35, 분석)
    - Insight Store: ``content_engine/performance_insight.py``의 저장 함수(6-35)
    - **Report Generator: 이 모듈**(6-36, 운영 정리)
    - Human Review: 이 모듈의 ``record_decision()``(6-36) - 사람이 직접 호출

절대 원칙(0/8/18장과 동일):
    - "최고 콘텐츠"/"최악 콘텐츠"/"1위 플랫폼" 같은 평가/랭킹을 만들지 않는다.
    - Accepted Insight가 KNOWLEDGE/MEDIA를 자동으로 바꾸지 않는다(이 모듈은
      ``content_engine.media_archive``/``tak_brain``의 쓰기 함수를 import하지
      않는다).
    - reviewer_note는 항상 사람이 직접 입력한 텍스트로만 취급한다 - AI가
      사람을 대신해 판단 사유를 지어내지 않는다(9장).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
from typing import Any

from content_engine.media_archive import MediaArchiveRecord
from content_engine.performance.models import PerformanceRecord
from content_engine.performance.quality import check_metric_quality, quality_status, WARNING
from content_engine.performance_insight import (
    COMPARISON_UNKNOWN,
    INCOMPARABLE,
    INCONSISTENT,
    INSUFFICIENT_SAMPLE,
    STATUS_ACCEPTED,
    STATUS_CANDIDATE,
    STATUS_REJECTED,
    InsightError,
    InsightRecord,
    load_insights,
    set_insight_status,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- 7장: Insight 우선순위(검토 필요 상태, "좋고 나쁨" 아님) -----------------------

PRIORITY_NEW = "NEW"
PRIORITY_REVIEWED = "REVIEWED"
PRIORITY_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
PRIORITY_INCOMPARABLE = "INCOMPARABLE"
PRIORITY_INVALID = "INVALID"

_NO_REVIEW_NEEDED_RESULTS = frozenset({INSUFFICIENT_SAMPLE, COMPARISON_UNKNOWN, INCOMPARABLE, INCONSISTENT})


def review_priority(insight: InsightRecord) -> str:
    """이 Insight가 지금 검토가 필요한 상태인지 분류한다. "좋다/나쁘다"가
    아니라 "사람이 봐야 하는가"만 판단한다."""
    if insight.status in (STATUS_ACCEPTED, STATUS_REJECTED):
        return PRIORITY_REVIEWED
    if insight.result == INSUFFICIENT_SAMPLE:
        return PRIORITY_INSUFFICIENT_DATA
    if insight.result == INCOMPARABLE:
        return PRIORITY_INCOMPARABLE
    if insight.insight_type == "traceability" and insight.result == INCONSISTENT:
        return PRIORITY_INVALID
    return PRIORITY_NEW


# --- 9장: Decision Record ----------------------------------------------------------


class DecisionError(ValueError):
    """DecisionRecord 구조가 올바르지 않을 때 발생한다."""


@dataclass(frozen=True)
class DecisionRecord:
    """사람이 Insight를 검토한 결정 이력 1건(append-only, 9장). ``reviewer_note``는
    운영자가 직접 입력한 자유 텍스트로만 취급한다 - 이 모듈은 어떤 경우에도
    이 값을 스스로 생성하지 않는다. 실명/이메일 등 개인정보를 요구하는
    필드를 두지 않았다."""

    insight_id: str
    decision: str
    reviewed_at: str
    reviewer_note: str = ""

    def __post_init__(self) -> None:
        if not self.insight_id:
            raise DecisionError("insight_id가 필요합니다.")
        if self.decision not in (STATUS_ACCEPTED, STATUS_REJECTED):
            raise DecisionError(f"decision은 {STATUS_ACCEPTED!r} 또는 {STATUS_REJECTED!r}여야 합니다: {self.decision!r}")
        if not self.reviewed_at:
            raise DecisionError("reviewed_at이 필요합니다.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "insight_id": self.insight_id,
            "decision": self.decision,
            "reviewed_at": self.reviewed_at,
            "reviewer_note": self.reviewer_note,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DecisionRecord":
        if not isinstance(data, dict):
            raise DecisionError("Decision 레코드는 객체(dict)여야 합니다.")
        return cls(
            insight_id=str(data.get("insight_id") or ""),
            decision=str(data.get("decision") or ""),
            reviewed_at=str(data.get("reviewed_at") or ""),
            reviewer_note=str(data.get("reviewer_note") or ""),
        )


def load_decisions(path: Path | str) -> list[DecisionRecord]:
    target = Path(path)
    if not target.exists():
        return []
    raw_text = target.read_text(encoding="utf-8").strip()
    if not raw_text:
        return []
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as error:
        raise DecisionError(f"Decision 저장소 파일이 올바른 JSON이 아닙니다: {target}") from error
    if not isinstance(data, list):
        raise DecisionError(f"Decision 저장소 파일은 목록(list) 구조여야 합니다: {target}")
    return [DecisionRecord.from_dict(item) for item in data]


def _save_decisions(records: list[DecisionRecord], path: Path | str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = [record.to_dict() for record in records]
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temp_path = Path(handle.name)
    temp_path.replace(target)


def record_decision(
    *, insights_path: Path | str, decisions_path: Path | str, insight_id: str, decision: str, reviewer_note: str = ""
) -> DecisionRecord:
    """사람의 검토 결정을 기록한다 - InsightRecord.status를 갱신하고(6-35
    ``set_insight_status()`` 재사용, 새 상태 전이 로직을 만들지 않는다),
    별도 append-only 이력(``DecisionRecord``)에 "언제/무엇을/왜"를 남긴다.
    이 함수를 호출하는 것 자체가 "사람이 지금 결정했다"는 사실을 의미한다 -
    이 모듈 어디에도 이 함수를 자동으로 호출하는 코드가 없다."""
    set_insight_status(insights_path, insight_id, decision)
    record = DecisionRecord(insight_id=insight_id, decision=decision, reviewed_at=_now(), reviewer_note=reviewer_note)
    existing = load_decisions(decisions_path)
    existing.append(record)
    _save_decisions(existing, decisions_path)
    return record


def decisions_for_insight(path: Path | str, insight_id: str) -> list[DecisionRecord]:
    return [d for d in load_decisions(path) if d.insight_id == insight_id]


# --- 10장: Evidence Drill-down -------------------------------------------------------


def drill_down_evidence(
    insight: InsightRecord,
    performance_records: list[PerformanceRecord],
    media_records: list[MediaArchiveRecord] | None = None,
) -> tuple[dict[str, Any], ...]:
    """Insight -> Evidence -> Performance snapshot -> content_id -> knowledge_id
    -> generation_id -> platform까지 역추적한다. ``media_records``를 주면
    content_id로 generation_id를 조회해서 함께 보여준다(6-34/6-35에서 이미
    확인했듯 PerformanceRecord 자체에는 generation_id가 없으므로, 이 값은
    항상 Production Archive를 읽기 전용으로 조회해서 채운다 - 저장하지
    않는다, 12장). 존재하지 않는 identity는 ``None``으로 남긴다 - 억지로
    연결하지 않는다."""
    performance_by_key = {
        (record.content_id, record.metric_collected_at): record for record in performance_records
    }
    media_by_content_id = {record.content_id: record for record in (media_records or ())}

    results = []
    for item in insight.evidence:
        content_id = str(item.get("content_id") or "")
        metric_collected_at = str(item.get("metric_collected_at") or "")
        snapshot = performance_by_key.get((content_id, metric_collected_at))
        media_record = media_by_content_id.get(content_id)
        results.append(
            {
                "content_id": content_id,
                "metric_collected_at": metric_collected_at,
                "value": item.get("value"),
                "knowledge_id": snapshot.knowledge_id if snapshot else None,
                "platform": snapshot.platform if snapshot else None,
                "generation_id": media_record.generation_id if media_record else None,
            }
        )
    return tuple(results)


# --- 13장: Monetization attribution(설계만, 실제 계산은 없음) ----------------------

MONETIZATION_DIRECT = "DIRECT"
MONETIZATION_INDIRECT = "INDIRECT"
MONETIZATION_NOT_APPLICABLE = "NOT_APPLICABLE"

# 이 값이 metrics에 있으면 "이 콘텐츠 자체에 직접 귀속된 수익"으로 본다.
# 실제로 이 키를 채우는 collector는 아직 없다(6-34/6-35 결론 유지) - 값이
# 들어오면 어떻게 분류할지만 미리 설계해 둔다(13장 지시).
_DIRECT_REVENUE_METRIC_KEYS = frozenset({"revenue"})
# 간접 귀속(knowledge_id/campaign/source 단위로만 알 수 있는 수익)을 표시할
# 필드 이름 - 아직 어떤 collector도 채우지 않는다.
_INDIRECT_REVENUE_METRIC_KEYS = frozenset({"attributed_revenue_estimate"})


def classify_monetization_attribution(record: PerformanceRecord) -> str:
    """이 스냅샷이 직접/간접/해당없음 중 어디에 속하는지 분류한다. 실제
    수익 데이터가 없는 현재 상태에서는 거의 항상 ``NOT_APPLICABLE``이다 -
    없는 데이터로 추정값을 만들지 않는다(0장 지시). ``_INDIRECT_REVENUE_METRIC_KEYS``로
    표시된 값은 반드시 "추정"이라는 사실이 명확해야 한다 - 실제 revenue와
    같은 신뢰도로 취급하면 안 된다(직접 귀속과 간접 귀속을 분리, 13장)."""
    if any(key in record.metrics for key in _DIRECT_REVENUE_METRIC_KEYS):
        return MONETIZATION_DIRECT
    if any(key in record.metrics for key in _INDIRECT_REVENUE_METRIC_KEYS):
        return MONETIZATION_INDIRECT
    return MONETIZATION_NOT_APPLICABLE


# --- 4/5장: Daily Report -------------------------------------------------------------


@dataclass(frozen=True)
class DailyReportSummary:
    window_start: str
    window_end: str
    measured_content_count: int
    valid_metric_count: int
    invalid_metric_count: int
    candidate_count: int
    accepted_count: int
    rejected_count: int
    insufficient_sample_count: int
    incomparable_count: int


def _in_window(timestamp: str, window_start: str, window_end: str) -> bool:
    # ISO 8601 문자열은 동일 형식이면 사전식 비교가 시간 순서와 일치한다
    # (content_engine.performance.store._parse_collected_at과 달리 여기서는
    # datetime 파싱을 다시 하지 않는다 - 호출부가 이미 정규화된 값을 넘긴다고
    # 가정하는 대신, 파싱 실패에 안전하도록 단순 문자열 비교만 쓴다. 값이
    # 없거나 범위 밖이면 그냥 False - 크래시하지 않는다).
    if not timestamp:
        return False
    return window_start <= timestamp <= window_end


def build_daily_report(
    performance_records: list[PerformanceRecord],
    insight_records: list[InsightRecord],
    *,
    window_start: str,
    window_end: str,
) -> DailyReportSummary:
    """이미 계산된 Performance/Insight 목록을 기간으로 필터링해서 세기만
    한다 - 새 분석을 수행하지 않는다(3장)."""
    windowed_performance = [r for r in performance_records if _in_window(r.metric_collected_at, window_start, window_end)]
    measured_content_ids = {r.content_id for r in windowed_performance}

    valid_count = 0
    invalid_count = 0
    for record in windowed_performance:
        issues = check_metric_quality(record)
        if quality_status(issues) == WARNING:
            invalid_count += 1
        else:
            valid_count += 1

    windowed_insights = [r for r in insight_records if _in_window(r.created_at, window_start, window_end)]
    candidate_count = sum(1 for i in windowed_insights if i.status == STATUS_CANDIDATE)
    accepted_count = sum(1 for i in windowed_insights if i.status == STATUS_ACCEPTED)
    rejected_count = sum(1 for i in windowed_insights if i.status == STATUS_REJECTED)
    insufficient_count = sum(1 for i in windowed_insights if i.result == INSUFFICIENT_SAMPLE)
    incomparable_count = sum(1 for i in windowed_insights if i.result == INCOMPARABLE)

    return DailyReportSummary(
        window_start=window_start, window_end=window_end,
        measured_content_count=len(measured_content_ids),
        valid_metric_count=valid_count, invalid_metric_count=invalid_count,
        candidate_count=candidate_count, accepted_count=accepted_count, rejected_count=rejected_count,
        insufficient_sample_count=insufficient_count, incomparable_count=incomparable_count,
    )


# --- 6장: Weekly Report ---------------------------------------------------------------


@dataclass(frozen=True)
class WeeklyReportSummary:
    window_start: str
    window_end: str
    trend_by_platform: dict[str, tuple[InsightRecord, ...]] = field(default_factory=dict)
    comparison_by_platform: dict[str, tuple[InsightRecord, ...]] = field(default_factory=dict)
    platform_insights: dict[str, tuple[InsightRecord, ...]] = field(default_factory=dict)
    knowledge_insights: dict[str, tuple[InsightRecord, ...]] = field(default_factory=dict)
    monetization_insights: tuple[InsightRecord, ...] = ()
    data_quality_notes: tuple[str, ...] = ()


def _group_by(records: list[InsightRecord], key_fn) -> dict[str, tuple[InsightRecord, ...]]:
    grouped: dict[str, list[InsightRecord]] = {}
    for record in records:
        grouped.setdefault(key_fn(record), []).append(record)
    return {key: tuple(values) for key, values in grouped.items()}


def build_weekly_report(
    insight_records: list[InsightRecord], *, window_start: str, window_end: str
) -> WeeklyReportSummary:
    """TREND/BASELINE/PLATFORM/KNOWLEDGE/MONETIZATION/DATA QUALITY를 각각
    분리해서 그룹화만 한다 - **서로 다른 platform/analysis_window를 절대
    합치지 않는다**(6장 핵심 지시). 예: Threads 7d와 Blog 30d는 각자
    독립된 key(platform)로만 묶이고, 평균 등 어떤 계산도 이 함수는 하지
    않는다(이미 계산된 값을 그대로 나열만 한다)."""
    windowed = [r for r in insight_records if _in_window(r.created_at, window_start, window_end)]

    trend_records = [r for r in windowed if r.insight_type == "trend"]
    comparison_records = [r for r in windowed if r.insight_type == "comparison"]
    monetization_records = tuple(r for r in windowed if r.insight_type == "monetization")

    data_quality_notes = tuple(
        f"{r.scope}={r.scope_id}({r.platform}/{r.metric}): {r.result}"
        for r in windowed
        if r.result in (INSUFFICIENT_SAMPLE, INCOMPARABLE, COMPARISON_UNKNOWN, INCONSISTENT)
    )

    return WeeklyReportSummary(
        window_start=window_start, window_end=window_end,
        trend_by_platform=_group_by(trend_records, lambda r: r.platform or "(unspecified)"),
        comparison_by_platform=_group_by(comparison_records, lambda r: r.platform or "(unspecified)"),
        platform_insights=_group_by([r for r in windowed if r.scope == "platform"], lambda r: r.scope_id),
        knowledge_insights=_group_by([r for r in windowed if r.scope == "knowledge"], lambda r: r.scope_id),
        monetization_insights=monetization_records,
        data_quality_notes=data_quality_notes,
    )


# --- 15장: 사람이 읽는 텍스트 렌더링 --------------------------------------------------


def render_daily_report_text(report: DailyReportSummary) -> str:
    lines = [
        "PERFORMANCE INSIGHT REPORT (DAILY)",
        "",
        f"Window: {report.window_start} ~ {report.window_end}",
        "",
        "Data:",
        f"- measured: {report.measured_content_count}",
        f"- valid metrics: {report.valid_metric_count}",
        f"- invalid metrics(warning): {report.invalid_metric_count}",
        "",
        "Insights:",
        f"- candidate: {report.candidate_count}",
        f"- accepted: {report.accepted_count}",
        f"- rejected: {report.rejected_count}",
        f"- insufficient sample: {report.insufficient_sample_count}",
        f"- incomparable: {report.incomparable_count}",
    ]
    return "\n".join(lines)


def render_weekly_report_text(report: WeeklyReportSummary) -> str:
    lines = [
        "PERFORMANCE INSIGHT REPORT (WEEKLY)",
        "",
        f"Window: {report.window_start} ~ {report.window_end}",
        "",
        "Platforms (trend):",
    ]
    if not report.trend_by_platform:
        lines.append("- (없음)")
    for platform, records in sorted(report.trend_by_platform.items()):
        lines.append(f"- {platform}: {len(records)}건")
        for r in records:
            lines.append(f"    {r.scope_id}: {r.result} - {r.observation}")

    lines.append("")
    lines.append("Knowledge:")
    if not report.knowledge_insights:
        lines.append("- (없음)")
    for knowledge_id, records in sorted(report.knowledge_insights.items()):
        lines.append(f"- {knowledge_id}: {len(records)}건")

    lines.append("")
    lines.append("Monetization:")
    lines.append(f"- {len(report.monetization_insights)}건(FUTURE - 실제 revenue 데이터 없음, 6-35/6-36 결론 유지)")

    lines.append("")
    lines.append("Warnings:")
    if not report.data_quality_notes:
        lines.append("- (없음)")
    for note in report.data_quality_notes:
        lines.append(f"- {note}")

    return "\n".join(lines)
