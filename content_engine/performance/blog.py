"""Naver Blog 성과(조회수 등) 수동 입력(6-01).

조사 결과(2026-09-20 웹 검색): 네이버는 블로그 글 1건의 조회수/검색 유입을
조회할 수 있는 공식 공개 API를 제공하지 않는다 - 네이버 블로그 통계는
블로그 소유자가 네이버 블로그 관리자 페이지("통계" 메뉴)에 로그인해서만 볼 수
있고, 이를 외부에서 자동으로 긁어오는 것은 이 프로젝트의 기존 원칙(공식 API만
사용, 스크래핑/비공식 접근 금지 - content_engine/threads_publisher.py,
content_engine/youtube_publisher.py와 동일한 원칙)과 맞지 않는다.

따라서 Blog는 fetch(자동 수집) 함수를 만들지 않는다. 대신 사람이 네이버 블로그
관리자 페이지에서 직접 확인한 숫자를 수동으로 입력하는 것까지만 지원한다 -
이 모듈은 그 수동 입력값을 다른 채널과 동일한 PerformanceRecord 형태로
정규화하는 책임만 가진다(불가능한 자동화를 억지로 만들지 않는다, 6-01 8장 지시).
"""

from __future__ import annotations

from .models import PerformanceRecord

# 네이버 블로그 관리자 페이지("통계" 메뉴)에서 사람이 직접 확인할 수 있는 지표.
# 이 목록 밖의 키를 metrics에 넣어도 막지는 않는다(PerformanceRecord는 metrics
# 형태만 검증하고 키 이름 화이트리스트는 두지 않는다) - 다만 CLI 도움말/문서에서는
# 이 세 가지를 기본 예시로 안내한다.
MANUAL_METRIC_HINTS: tuple[str, ...] = ("views", "likes", "comments")


def build_manual_blog_performance_record(
    *,
    content_id: str,
    knowledge_id: str,
    published_at: str,
    metric_collected_at: str,
    metrics: dict[str, int],
    title: str = "",
    blog_url: str = "",
) -> PerformanceRecord:
    """사람이 네이버 블로그 관리자 페이지에서 직접 확인한 값으로 레코드를 만든다.

    실제 네트워크 호출이 전혀 없다 - metrics는 호출부(scripts/collect_performance.py
    --platform blog)가 사람 입력(CLI 인자 또는 파일)에서 그대로 받아온 값이다.
    """
    return PerformanceRecord(
        content_id=content_id,
        knowledge_id=knowledge_id,
        platform="blog",
        published_at=published_at,
        metric_collected_at=metric_collected_at,
        metrics=dict(metrics),
        source="manual",
        title=title,
        external_id=blog_url,
        raw=None,
    )
