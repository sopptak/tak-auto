"""네이버가 제공하는 RSS 입력 어댑터.

이 모듈은 RSS XML만 읽습니다. 개별 블로그 페이지를 따라가거나 로그인·접근 제한을
우회하지 않습니다.
"""

from __future__ import annotations

from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from pathlib import Path
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

from .models import BlogPost, ValidationError


class NaverRssError(ValueError):
    """RSS 접근 또는 구조가 올바르지 않을 때 발생합니다."""


@dataclass(frozen=True)
class NaverRssRecord:
    post: BlogPost
    body_is_complete: bool
    body_source: str = "rss_description"


def fetch_rss(url: str, timeout: float = 20.0) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "TAK-AUTO/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = getattr(response, "status", 200)
            if status < 200 or status >= 300:
                raise NaverRssError(f"RSS HTTP 상태 오류: {status}")
            return response.read().decode(response.headers.get_content_charset() or "utf-8")
    except (urllib.error.URLError, urllib.error.HTTPError, UnicodeDecodeError) as error:
        raise NaverRssError(f"RSS 접근 실패: {error}") from error


def _required_text(item: ET.Element, name: str) -> str:
    value = (item.findtext(name) or "").strip()
    if not value:
        raise NaverRssError(f"RSS item 필드가 없습니다: {name}")
    return value


def _published_at(raw_date: str) -> str:
    try:
        return parsedate_to_datetime(raw_date).isoformat()
    except (TypeError, ValueError, OverflowError) as error:
        raise NaverRssError(f"RSS 날짜를 해석할 수 없습니다: {raw_date}") from error


def _tags(item: ET.Element) -> tuple[str, ...]:
    values = []
    for category in item.findall("category"):
        value = (category.text or "").strip()
        if value:
            values.append(value)
    tag_text = (item.findtext("tag") or "").strip()
    values.extend(tag.strip() for tag in tag_text.split(",") if tag.strip())
    return tuple(dict.fromkeys(values))


def parse_rss(xml_text: str, limit: int = 10) -> list[NaverRssRecord]:
    if limit < 1:
        raise ValueError("limit은 1 이상이어야 합니다.")
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as error:
        raise NaverRssError(f"RSS XML 파싱 실패: {error}") from error

    records = []
    for item in root.findall("./channel/item")[:limit]:
        title = _required_text(item, "title")
        source_url = _required_text(item, "link")
        raw_id = (item.findtext("guid") or source_url).strip()
        description = (item.findtext("description") or "").strip()
        if not description:
            raise NaverRssError(f"RSS item 본문/요약이 없습니다: {source_url}")
        body_is_complete = not description.endswith(".......")
        post = BlogPost.from_mapping(
            {
                "id": raw_id,
                "title": title,
                "published_at": _published_at(_required_text(item, "pubDate")),
                "body": description,
                "tags": _tags(item),
                "source_url": source_url,
                "source": "naver_rss",
            }
        )
        records.append(NaverRssRecord(post=post, body_is_complete=body_is_complete))
    return records


def parse_rss_file(path: str | Path, limit: int = 10) -> list[NaverRssRecord]:
    return parse_rss(Path(path).read_text(encoding="utf-8"), limit=limit)