"""기존 발행 이력에서 성과 baseline 레코드를 만드는 migration 함수(6-01).

이 모듈은 **파일을 읽지 않는다** - 이미 로드된 dict 목록(예:
``PublishHistory(path).load()``, ``YouTubeUploadHistory(path).load()``가 반환한
것)을 받아 ``PerformanceRecord``로 변환만 한다. 실제 production 로그 파일에 대해
이 함수를 실행하는 것은 이번 작업(6-01) 범위 밖이다 - 설계/구현/테스트까지만
하고, 실제 실행은 사람이 필요하다고 판단할 때 별도로 한다(18장 지시 - "실제
기존 데이터에 자동 migration을 실행해서 파일을 대량 변경하지 않는다").

만들어지는 레코드는 실제 성과 지표(views/likes 등)가 아니라 "발행이 있었다"는
사실만 옮긴 placeholder다(``metrics={}``, ``source="migration_baseline"``) -
실제 수치는 이후 collector가 별도로 채워야 한다.

**중요한 비대칭 발견(6-01 조사)**: threads_publish_log.json/blog_publish_log.json
(둘 다 content_engine.publish_history.PublishRecord 구조)은 처음부터
content_id/knowledge_id를 갖고 있어 그대로 옮길 수 있다. 반면
youtube_publish_log.json(content_engine.youtube_upload_history.YouTubeUploadRecord
구조)은 video_id/title/uploaded_at만 있고 content_id/knowledge_id가 전혀 없다
(YouTube 업로드 자체가 MEDIA archive와 연결되지 않은 채 설계되어 있다 - 5-13/5-14
당시에는 성과 추적을 고려하지 않았기 때문으로 보인다). 그래서 YouTube만
``video_id -> (content_id, knowledge_id)`` 매핑을 호출부가 별도로 제공해야 하며,
매핑이 없는 video_id는 조용히 건너뛴다(추측으로 지어내지 않는다).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from .models import PerformanceRecord


def migrate_threads_or_blog_baseline_records(
    publish_records: Iterable[Mapping[str, object]],
    platform: str,
) -> list[PerformanceRecord]:
    """PublishRecord.to_dict() 형태(content_id/published_at/threads_post_id/
    knowledge_id/platform/source_url을 가진 dict) 목록을 baseline
    PerformanceRecord로 변환한다. Threads/Blog 둘 다 이 구조를 공유하므로
    (content_engine.publish_history.PublishRecord) platform만 파라미터로 받는다.

    knowledge_id가 비어 있는 레코드(PublishRecord.knowledge_id는 빈 문자열이
    기본값이라 실제로 있을 수 있다)는 PerformanceRecord가 knowledge_id를
    필수로 요구하므로 건너뛴다 - 억지로 채우지 않는다.
    """
    if platform not in ("threads", "blog"):
        raise ValueError(f"platform은 'threads' 또는 'blog'여야 합니다: {platform!r}")

    results: list[PerformanceRecord] = []
    for item in publish_records:
        content_id = str(item.get("content_id") or "")
        knowledge_id = str(item.get("knowledge_id") or "")
        published_at = str(item.get("published_at") or "")
        if not content_id or not knowledge_id:
            continue
        results.append(
            PerformanceRecord(
                content_id=content_id,
                knowledge_id=knowledge_id,
                platform=platform,
                published_at=published_at,
                metric_collected_at=published_at or "unknown",
                metrics={},
                source="migration_baseline",
                external_id=str(item.get("threads_post_id") or ""),
            )
        )
    return results


def migrate_youtube_baseline_records(
    upload_records: Iterable[Mapping[str, object]],
    video_id_to_content: Mapping[str, tuple[str, str]],
) -> list[PerformanceRecord]:
    """YouTubeUploadRecord.to_dict() 형태 목록을 baseline PerformanceRecord로
    변환한다.

    ``video_id_to_content``는 ``{video_id: (content_id, knowledge_id)}`` 매핑을
    호출부가 명시적으로 제공해야 한다 - youtube_publish_log.json 자체에는 이 연결
    정보가 없기 때문이다(모듈 docstring 참고). 매핑에 없는 video_id는 조용히
    건너뛴다(추측하지 않는다).
    """
    results: list[PerformanceRecord] = []
    for item in upload_records:
        video_id = str(item.get("video_id") or "")
        mapping = video_id_to_content.get(video_id)
        if not video_id or mapping is None:
            continue
        content_id, knowledge_id = mapping
        if not content_id or not knowledge_id:
            continue
        uploaded_at = str(item.get("uploaded_at") or "")
        results.append(
            PerformanceRecord(
                content_id=content_id,
                knowledge_id=knowledge_id,
                platform="youtube",
                published_at=uploaded_at,
                metric_collected_at=uploaded_at or "unknown",
                metrics={},
                source="migration_baseline",
                title=str(item.get("title") or ""),
                external_id=video_id,
            )
        )
    return results
