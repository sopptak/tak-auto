"""등록된 RSS source에서 후보를 모으고, 중복을 제거해 오늘의 TAK SCOUT 후보를 만든다."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import re
import tempfile
from typing import Any

from blog_importer.models import utc_now

from .models import ScoutCandidate
from .rss import ScoutRssError, fetch_rss, parse_rss_items


DEFAULT_MAX_CANDIDATES = 10

_WHITESPACE_PATTERN = re.compile(r"\s+")


@dataclass(frozen=True)
class SourceCollectionResult:
    """source 1건을 수집한 결과(성공/실패 모두 기록해 사람이 확인할 수 있게 한다)."""

    name: str
    url: str
    candidate_count: int
    error: str | None = None


def load_sources(path: Path | str) -> list[dict[str, Any]]:
    """data/scout_sources.json을 읽는다. {"sources": [...]} 구조만 허용한다."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("sources"), list):
        raise ValueError("scout_sources.json은 {'sources': [...]} 구조여야 합니다.")
    if not all(isinstance(item, dict) for item in data["sources"]):
        raise ValueError("sources의 각 항목은 객체여야 합니다.")
    return data["sources"]


def collect_from_source(source: dict[str, Any], timeout: float = 20.0) -> list[ScoutCandidate]:
    name = str(source.get("name") or "")
    url = str(source.get("url") or "")
    category = str(source.get("category") or "기타")
    if not url:
        raise ScoutRssError(f"source에 url이 없습니다: {source}")
    xml_text = fetch_rss(url, timeout=timeout)
    return parse_rss_items(xml_text, source_name=name or url, category=category)


def collect_all(
    sources: list[dict[str, Any]], timeout: float = 20.0
) -> tuple[list[ScoutCandidate], list[SourceCollectionResult]]:
    """모든 source를 순회해 후보를 모은다. source 1건의 실패가 전체 수집을 막지 않는다."""
    all_candidates: list[ScoutCandidate] = []
    results: list[SourceCollectionResult] = []
    for source in sources:
        name = str(source.get("name") or source.get("url") or "unknown")
        url = str(source.get("url") or "")
        try:
            fetched = collect_from_source(source, timeout=timeout)
        except ScoutRssError as error:
            results.append(SourceCollectionResult(name=name, url=url, candidate_count=0, error=str(error)))
            continue
        all_candidates.extend(fetched)
        results.append(SourceCollectionResult(name=name, url=url, candidate_count=len(fetched)))
    return all_candidates, results


def _normalize_url(url: str) -> str:
    return url.strip().lower().rstrip("/")


def _normalize_title(title: str) -> str:
    return _WHITESPACE_PATTERN.sub(" ", title.strip().lower())


def dedupe_candidates(candidates: list[ScoutCandidate]) -> list[ScoutCandidate]:
    """같은 URL이거나 제목이 사실상 같은 후보는 먼저 나온 것만 남긴다."""
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    result: list[ScoutCandidate] = []
    for candidate in candidates:
        url_key = _normalize_url(candidate.source_url)
        title_key = _normalize_title(candidate.title)
        if url_key in seen_urls or title_key in seen_titles:
            continue
        seen_urls.add(url_key)
        seen_titles.add(title_key)
        result.append(candidate)
    return result


def select_candidates(
    candidates: list[ScoutCandidate], max_count: int = DEFAULT_MAX_CANDIDATES
) -> list[ScoutCandidate]:
    """수집 순서를 유지한 채 최대 max_count개만 남긴다."""
    return candidates[:max_count]


def build_daily_pack(
    sources: list[dict[str, Any]],
    max_count: int = DEFAULT_MAX_CANDIDATES,
    timeout: float = 20.0,
) -> tuple[list[ScoutCandidate], list[SourceCollectionResult]]:
    """source 목록에서 수집 -> 중복 제거 -> 선정까지 한 번에 수행한다."""
    raw_candidates, results = collect_all(sources, timeout=timeout)
    deduped = dedupe_candidates(raw_candidates)
    selected = select_candidates(deduped, max_count=max_count)
    return selected, results


def _write_json_atomic(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temp_path = Path(handle.name)
    temp_path.replace(path)


def save_daily_pack_json(
    candidates: list[ScoutCandidate], path: Path | str, generated_at: str | None = None
) -> None:
    payload = {
        "generated_at": generated_at or utc_now(),
        "candidate_count": len(candidates),
        "candidates": [candidate.to_dict() for candidate in candidates],
    }
    _write_json_atomic(payload, Path(path))


def load_daily_pack(path: Path | str) -> list[ScoutCandidate]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("candidates"), list):
        raise ValueError("tak_scout_daily.json 구조가 올바르지 않습니다.")
    return [ScoutCandidate.from_dict(item) for item in data["candidates"]]


def _why_notable(candidate: ScoutCandidate) -> str:
    """근거 없는 과장을 피한 최소 안내 문구. 최종 판단은 사람(티몽)이 한다."""
    return (
        f"{candidate.source_name}({candidate.category})에서 다룬 소재이며, "
        "TAK INTERVIEW에서 의견을 더할지 사람이 직접 판단해야 한다."
    )


def render_daily_pack_markdown(candidates: list[ScoutCandidate], generated_at: str | None = None) -> str:
    generated_at = generated_at or utc_now()
    lines = [
        "# 오늘의 TAK SCOUT",
        "",
        f"생성 시각(UTC): {generated_at}",
        f"오늘의 후보: {len(candidates)}건",
        "",
    ]
    if not candidates:
        lines.append("오늘 수집된 새 소재가 없습니다.")
    for index, candidate in enumerate(candidates, start=1):
        lines.extend(
            [
                f"## {index}. {candidate.title}",
                "",
                f"출처: {candidate.source_name} ({candidate.category})",
                f"발행일: {candidate.published_at or '알 수 없음'}",
                f"원문: {candidate.source_url}",
                f"요약: {candidate.summary or '(요약 없음)'}",
                "",
                f"왜 주목할 만한가: {_why_notable(candidate)}",
                "",
                f"scout_id: {candidate.scout_id}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def save_daily_pack_markdown(
    candidates: list[ScoutCandidate], path: Path | str, generated_at: str | None = None
) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_daily_pack_markdown(candidates, generated_at=generated_at), encoding="utf-8")
