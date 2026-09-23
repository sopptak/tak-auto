"""성과 스냅샷의 통계적 이상을 감지한다(6-34 13장).

``PerformanceRecord.__post_init__()``(models.py)이 이미 구조적 오류(필수
필드 누락, metrics가 정수가 아님 등)를 막는다 - 그 레코드는 애초에 생성될 수
없으므로 이 모듈이 다시 검사하지 않는다. 이 모듈은 **구조적으로는 유효하지만
값 자체가 의심스러운 경우**(음수 조회수, 조회수 감소, 좋아요가 조회수보다
많음)를 감지해 경고만 한다 - 저장을 막지 않는다(``WARNING``). 실제로 틀린
값인지, 플랫폼 API의 정상적인 보정(예: 스팸성 조회 필터링으로 조회수가
줄어드는 경우가 실제로 있다)인지 이 모듈은 판단할 근거가 없기 때문이다 -
최종 판단은 사람이 한다(6-34 15장 원칙과 동일).

``BLOCKED``는 실제로 저장소에 넣을 수 없는 구조적 문제
(``PerformanceRecordError``, JSON 파싱 실패 등, models.py/store.py가 이미
막는다)에만 쓴다 - 이 모듈 자체는 아무것도 막지 않고 라벨만 붙인다.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import PerformanceRecord

VALID = "VALID"
WARNING = "WARNING"


@dataclass(frozen=True)
class MetricQualityIssue:
    code: str
    message: str


def check_metric_quality(
    record: PerformanceRecord, previous: PerformanceRecord | None = None
) -> tuple[MetricQualityIssue, ...]:
    """레코드 1건(및 선택적으로 이전 스냅샷)에서 발견된 이상 목록을 반환한다.

    빈 튜플이면 이상 없음(``VALID``) - 하나라도 있으면 호출부가 ``WARNING``으로
    표시하면 된다. 저장 자체를 막지 않는다.
    """
    issues: list[MetricQualityIssue] = []

    for name, value in sorted(record.metrics.items()):
        if value < 0:
            issues.append(MetricQualityIssue("negative_metric", f"{name}이(가) 음수입니다: {value}"))

    views = record.metrics.get("views")
    likes = record.metrics.get("likes")
    if views is not None and likes is not None and likes > views:
        issues.append(MetricQualityIssue("likes_exceed_views", f"likes({likes})가 views({views})보다 많습니다."))

    if previous is not None and previous.content_id == record.content_id:
        for name in sorted(set(previous.metrics) & set(record.metrics)):
            if record.metrics[name] < previous.metrics[name]:
                issues.append(
                    MetricQualityIssue(
                        "metric_decreased",
                        f"{name}이(가) 이전 스냅샷({previous.metrics[name]}) 대비 감소했습니다: {record.metrics[name]}",
                    )
                )

    return tuple(issues)


def quality_status(issues: tuple[MetricQualityIssue, ...]) -> str:
    return WARNING if issues else VALID
