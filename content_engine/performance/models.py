"""성과(Performance) 데이터 모델(6-01).

콘텐츠 1건의 특정 시점 성과 스냅샷을 표현한다. 성과는 시간이 지나며 바뀐다
(예: 발행 1일차 조회수 100 -> 7일차 2,300)는 것이 설계의 핵심 전제이므로,
"현재값 하나만 덮어쓰는" 구조가 아니라 스냅샷을 계속 append하는 시계열
구조로 저장한다(store.py가 그 저장 방식을 담당하고, 이 모듈은 레코드 1건의
형태만 정의한다).

content_engine.media_archive.MediaArchiveRecord와 동일한 관례를 따른다:
    - content_id는 이 모듈이 새로 계산하지 않는다. 이미
      content_engine.publish_history.compute_content_id()로 계산되어 archive/
      발행 이력에 저장된 값을 그대로 받아 쓴다 - 성과 데이터가 원본 KNOWLEDGE/
      MEDIA와 같은 식별자 체계를 공유해야 나중에 "이 성과가 어떤 KNOWLEDGE에서
      나왔는가"를 조인할 수 있다.
    - dataclass(frozen=True) + to_dict()/from_dict() 왕복 변환.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


PLATFORMS = ("threads", "youtube", "blog")

# collector가 성과를 어떻게 얻었는지 - "이 숫자를 얼마나 신뢰할 것인가" 판단에 쓴다.
#   threads_api / youtube_api : 공식 API 응답을 그대로 정규화한 값
#   manual                    : 사람이 직접 입력한 값(Naver Blog처럼 공개 조회 API가
#                                없는 채널, 또는 API 실패 시 수동 보정)
#   migration_baseline        : 기존 발행 이력(threads_publish_log.json 등)에서
#                                옮겨온 "발행 사실"일 뿐 실제 성과 지표가 아니다.
#                                metrics가 비어 있을 수 있다.
SOURCES = ("threads_api", "youtube_api", "manual", "migration_baseline")


class PerformanceRecordError(ValueError):
    """PerformanceRecord 구조가 올바르지 않을 때 발생한다."""


@dataclass(frozen=True)
class PerformanceRecord:
    """콘텐츠 1건의 특정 수집 시점(metric_collected_at) 성과 스냅샷 1건."""

    content_id: str
    knowledge_id: str
    platform: str
    published_at: str
    metric_collected_at: str
    metrics: dict[str, int] = field(default_factory=dict)
    source: str = "manual"
    title: str = ""
    # 플랫폼별 원본 식별자: threads post id / youtube video id / blog url 등.
    external_id: str = ""
    # collector가 실제로 받은 원본 응답(정규화 이전) - 감사/디버깅용. 저장하지
    # 않아도(None) 기능상 문제 없다.
    raw: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if not self.content_id:
            raise PerformanceRecordError("content_id가 필요합니다.")
        if not self.knowledge_id:
            raise PerformanceRecordError("knowledge_id가 필요합니다.")
        if self.platform not in PLATFORMS:
            raise PerformanceRecordError(
                f"platform은 {PLATFORMS} 중 하나여야 합니다: {self.platform!r}"
            )
        if self.source not in SOURCES:
            raise PerformanceRecordError(f"source는 {SOURCES} 중 하나여야 합니다: {self.source!r}")
        if not self.metric_collected_at:
            raise PerformanceRecordError("metric_collected_at이 필요합니다.")
        if not isinstance(self.metrics, dict):
            raise PerformanceRecordError("metrics는 dict 구조여야 합니다.")
        for key, value in self.metrics.items():
            if not isinstance(value, int) or isinstance(value, bool):
                raise PerformanceRecordError(f"metrics[{key!r}]는 정수여야 합니다: {value!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "content_id": self.content_id,
            "knowledge_id": self.knowledge_id,
            "platform": self.platform,
            "published_at": self.published_at,
            "metric_collected_at": self.metric_collected_at,
            "metrics": dict(self.metrics),
            "source": self.source,
            "title": self.title,
            "external_id": self.external_id,
            "raw": self.raw,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PerformanceRecord":
        if not isinstance(data, dict):
            raise PerformanceRecordError("성과 레코드는 객체(dict)여야 합니다.")
        metrics = data.get("metrics") or {}
        if not isinstance(metrics, dict):
            raise PerformanceRecordError("metrics는 dict 구조여야 합니다.")
        try:
            normalized_metrics = {str(key): int(value) for key, value in metrics.items()}
        except (TypeError, ValueError) as error:
            raise PerformanceRecordError(f"metrics 값은 정수로 변환 가능해야 합니다: {metrics!r}") from error

        raw = data.get("raw")
        return cls(
            content_id=str(data.get("content_id") or ""),
            knowledge_id=str(data.get("knowledge_id") or ""),
            platform=str(data.get("platform") or ""),
            published_at=str(data.get("published_at") or ""),
            metric_collected_at=str(data.get("metric_collected_at") or ""),
            metrics=normalized_metrics,
            source=str(data.get("source") or "manual"),
            title=str(data.get("title") or ""),
            external_id=str(data.get("external_id") or ""),
            raw=raw if isinstance(raw, dict) else None,
        )
