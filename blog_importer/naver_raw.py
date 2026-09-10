"""네이버 RSS 메타데이터와 공개 HTML 본문을 RAW로 결합합니다."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Callable

from .models import BlogPost
from .naver_post import NaverPostError, PublicPostExtraction, fetch_public_post
from .naver_rss import NaverRssError, fetch_rss, parse_rss
from .pilot import append_posts
from tak_brain.models import build_metadata


_RELATIVE_DATE_PATTERN = re.compile(r"(?:\d+\s*(?:분|시간|일|주|개월|년)\s*전|어제|오늘|방금)")
PostFetcher = Callable[[str, float], PublicPostExtraction]


@dataclass
class NaverRawReport:
    total: int = 0
    new: int = 0
    duplicate: int = 0
    full: int = 0
    partial: int = 0
    failed: int = 0
    risk_flags: int = 0
    errors: int = 0
    error_messages: list[str] = field(default_factory=list)
    sample_titles: list[str] = field(default_factory=list)


def is_absolute_date(value: str | None) -> bool:
    return bool(value and value.strip() and not _RELATIVE_DATE_PATTERN.search(value))


def select_published_at(rss_published_at: str, html_published_at: str | None) -> str:
    """RSS 절대 날짜를 우선하고 HTML 상대 날짜는 저장하지 않습니다."""
    if is_absolute_date(rss_published_at):
        return rss_published_at
    if is_absolute_date(html_published_at):
        return str(html_published_at).strip()
    return ""


def _make_post(record, body: str, extraction_method: str, extraction_status: str, html_published_at: str | None) -> BlogPost:
    published_at = select_published_at(record.post.published_at, html_published_at)
    if not published_at:
        raise ValueError(f"절대 게시일을 확인할 수 없습니다: {record.post.source_url}")
    return BlogPost.from_mapping(
        {
            "id": record.post.id,
            "title": record.post.title,
            "published_at": published_at,
            "body": body,
            "tags": record.post.tags,
            "source_url": record.post.source_url,
            "source": record.post.source,
            "extraction_method": extraction_method,
            "extraction_status": extraction_status,
        }
    )


def collect_naver_rss(
    rss_url: str,
    output_path: str,
    limit: int = 10,
    timeout: float = 20.0,
    post_fetcher: PostFetcher = fetch_public_post,
) -> NaverRawReport:
    if limit < 1:
        raise ValueError("limit은 1 이상이어야 합니다.")
    records = parse_rss(fetch_rss(rss_url, timeout=timeout), limit=limit)
    report = NaverRawReport(total=len(records))
    posts: list[BlogPost] = []

    for record in records:
        html_published_at: str | None = None
        try:
            extraction = post_fetcher(record.post.source_url, timeout)
            html_published_at = extraction.published_at
            post = _make_post(record, extraction.body, "naver_public_html", "full", html_published_at)
            report.full += 1
        except (NaverPostError, OSError, ValueError) as error:
            report.errors += 1
            report.error_messages.append(f"{record.post.source_url}: {error}")
            try:
                post = _make_post(record, record.post.body, "naver_rss_description", "partial", html_published_at)
                report.partial += 1
            except ValueError as fallback_error:
                report.failed += 1
                report.error_messages.append(f"{record.post.source_url}: {fallback_error}")
                continue
        posts.append(post)
        if len(report.sample_titles) < 3:
            report.sample_titles.append(post.title)
        metadata = build_metadata(post)
        if metadata["privacy_risk"] or metadata["internal_information_risk"]:
            report.risk_flags += 1

    report.new, report.duplicate = append_posts(posts, output_path)
    return report
