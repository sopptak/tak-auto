"""공개 네이버 게시물 HTML의 본문 영역을 점검하는 제한적 프로토타입."""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request


class NaverPostError(ValueError):
    """공개 게시물 HTML을 읽거나 해석할 수 없을 때 발생합니다."""


@dataclass(frozen=True)
class PublicPostExtraction:
    title: str
    published_at: str | None
    body: str
    frame_url: str | None
    page_status: int
    frame_status: int | None


class _PostHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title_parts: list[str] = []
        self.date_parts: list[str] = []
        self.body_parts: list[str] = []
        self.frame_src: str | None = None
        self._title_depth = 0
        self._date_depth = 0
        self._body_depth = 0
        self._ignored_depth = 0
        self._stack: list[tuple[bool, bool, bool, bool]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        lower_classes = {value.lower() for value in classes}
        is_title = tag == "title"
        is_date = "se_publishdate" in lower_classes
        is_body = "se-main-container" in classes
        is_ignored = tag in {"script", "style"}
        self._stack.append((is_title, is_date, is_body, is_ignored))
        self._title_depth += is_title
        self._date_depth += is_date
        self._body_depth += is_body
        self._ignored_depth += is_ignored
        if attributes.get("id") == "mainFrame" and attributes.get("src"):
            self.frame_src = attributes["src"]

    def handle_endtag(self, tag: str) -> None:
        if not self._stack:
            return
        is_title, is_date, is_body, is_ignored = self._stack.pop()
        self._title_depth -= is_title
        self._date_depth -= is_date
        self._body_depth -= is_body
        self._ignored_depth -= is_ignored

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        if self._title_depth:
            self.title_parts.append(data)
        if self._date_depth:
            self.date_parts.append(data)
        if self._body_depth:
            self.body_parts.append(data)


def _clean(parts: list[str]) -> str:
    return " ".join(" ".join(parts).split())


def find_frame_url(html: str, page_url: str) -> str | None:
    parser = _PostHtmlParser()
    parser.feed(html)
    return urllib.parse.urljoin(page_url, parser.frame_src) if parser.frame_src else None


def parse_public_post(html: str, page_url: str, page_status: int = 200, frame_status: int | None = None) -> PublicPostExtraction:
    parser = _PostHtmlParser()
    parser.feed(html)
    title = _clean(parser.title_parts)
    body = _clean(parser.body_parts)
    if not title:
        raise NaverPostError("게시물 제목을 찾지 못했습니다.")
    if not body:
        raise NaverPostError("se-main-container 본문을 찾지 못했습니다.")
    frame_url = urllib.parse.urljoin(page_url, parser.frame_src) if parser.frame_src else None
    return PublicPostExtraction(title, _clean(parser.date_parts) or None, body, frame_url, page_status, frame_status)


def _fetch(url: str, timeout: float) -> tuple[str, int, str]:
    request = urllib.request.Request(url, headers={"User-Agent": "TAK-AUTO/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = getattr(response, "status", 200)
            return response.read().decode(response.headers.get_content_charset() or "utf-8"), status, response.geturl()
    except (urllib.error.URLError, urllib.error.HTTPError, UnicodeDecodeError) as error:
        raise NaverPostError(f"공개 게시물 접근 실패: {error}") from error


def fetch_public_post(url: str, timeout: float = 20.0) -> PublicPostExtraction:
    html, page_status, final_url = _fetch(url, timeout)
    frame_url = find_frame_url(html, final_url)
    if frame_url:
        frame_html, frame_status, frame_final_url = _fetch(frame_url, timeout)
        return parse_public_post(frame_html, frame_final_url, page_status, frame_status)
    return parse_public_post(html, final_url, page_status)


def parse_public_post_file(path: str | Path, page_url: str) -> PublicPostExtraction:
    return parse_public_post(Path(path).read_text(encoding="utf-8"), page_url)