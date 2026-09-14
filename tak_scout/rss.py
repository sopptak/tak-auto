"""공개 RSS 피드에서 TAK SCOUT 후보를 만드는 최소 파서.

이 모듈은 RSS 2.0 XML만 읽는다. 개별 기사 페이지를 따라가거나 로그인, 캡차, 접근
제한을 우회하지 않으며, 본문 전체를 가져오지 않고 title/description(요약)/link/
pubDate만 사용한다.
"""

from __future__ import annotations

from email.utils import parsedate_to_datetime
import html
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

from .models import ScoutCandidate, compute_scout_id


class ScoutRssError(ValueError):
    """RSS 접근 또는 구조가 올바르지 않을 때 발생한다."""


_TAG_PATTERN = re.compile(r"<[^>]+>")
_WHITESPACE_PATTERN = re.compile(r"\s+")
MAX_SUMMARY_LENGTH = 200


def fetch_rss(url: str, timeout: float = 20.0) -> str:
    """RSS XML 원문을 가져온다. 네트워크/HTTP 오류는 ScoutRssError로 통일한다."""
    request = urllib.request.Request(url, headers={"User-Agent": "TAK-SCOUT/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 (공개 RSS만 사용)
            status = getattr(response, "status", 200)
            if status < 200 or status >= 300:
                raise ScoutRssError(f"RSS HTTP 상태 오류: {status} ({url})")
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError) as error:
        raise ScoutRssError(f"RSS 접근 실패: {url} ({error})") from error


def _clean_summary(raw: str, limit: int = MAX_SUMMARY_LENGTH) -> str:
    """HTML 태그를 걷어내고 짧은 요약만 남긴다(원문 전체를 저장하지 않는다)."""
    text = html.unescape(_TAG_PATTERN.sub(" ", raw or ""))
    text = _WHITESPACE_PATTERN.sub(" ", text).strip()
    if len(text) > limit:
        text = text[:limit].rstrip() + "…"
    return text


def _published_at(item: ET.Element) -> str:
    raw_date = (item.findtext("pubDate") or "").strip()
    if not raw_date:
        raw_date = (item.findtext("{http://purl.org/dc/elements/1.1/}date") or "").strip()
    if not raw_date:
        return ""
    try:
        return parsedate_to_datetime(raw_date).isoformat()
    except (TypeError, ValueError, OverflowError):
        # 표준 형식이 아니어도 수집 자체를 막지 않고 원문 표기를 그대로 남긴다.
        return raw_date


def parse_rss_items(xml_text: str, source_name: str, category: str) -> list[ScoutCandidate]:
    """RSS 2.0 XML에서 후보 목록을 만든다.

    제목과 원문 URL이 없는 item은 조용히 건너뛴다(피드 하나의 일부 결함이 전체 수집을
    막지 않도록 한다). XML 자체가 깨졌을 때만 ScoutRssError를 발생시킨다.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as error:
        raise ScoutRssError(f"RSS XML 파싱 실패: {error}") from error

    channel = root.find("channel")
    items = channel.findall("item") if channel is not None else root.findall(".//item")

    candidates: list[ScoutCandidate] = []
    for item in items:
        title = (item.findtext("title") or "").strip()
        source_url = (item.findtext("link") or "").strip()
        if not title or not source_url:
            continue
        summary = _clean_summary(item.findtext("description") or item.findtext("summary") or "")
        candidates.append(
            ScoutCandidate(
                scout_id=compute_scout_id(title, source_url),
                title=title,
                summary=summary,
                source_url=source_url,
                published_at=_published_at(item),
                source_name=source_name,
                category=category,
            )
        )
    return candidates
