"""시장 수요 저장소와 아이디어 후보 생성.

저장소는 append-only(demand_id 중복은 건너뜀)이고 원자적 쓰기를 쓴다. 아이디어 후보는 항상
``candidate``로 시작하며 채택/거절은 사람이 한다. 이 모듈은 콘텐츠를 생성·발행하지 않는다.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Any

from blog_importer.models import utc_now

from .models import IDEA_STATUSES, IdeaCandidate, MarketDemand, MarketDemandError
from .scoring import score_demand


def _read(path: Path | str) -> list[dict[str, Any]]:
    target = Path(path)
    if not target.exists():
        return []
    data = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        raise MarketDemandError(f"{target.name}은(는) 객체 목록이어야 합니다.")
    return data


def _write(path: Path | str, rows: list[dict[str, Any]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, delete=False, suffix=".tmp") as handle:
        handle.write(json.dumps(rows, ensure_ascii=False, indent=2) + "\n")
        temp = Path(handle.name)
    temp.replace(target)


def load_demands(path: Path | str) -> list[MarketDemand]:
    return [MarketDemand.from_dict(row) for row in _read(path)]


def append_demands(path: Path | str, demands: Sequence[MarketDemand]) -> int:
    rows = _read(path)
    seen = {row.get("demand_id") for row in rows}
    added = 0
    for demand in demands:
        if demand.demand_id not in seen:
            rows.append(demand.to_dict())
            seen.add(demand.demand_id)
            added += 1
    if added:
        _write(path, rows)
    return added


def build_idea_candidates(
    demands: Sequence[MarketDemand], min_score: float = 40.0, top_n: int = 10, now: str | None = None
) -> list[IdeaCandidate]:
    """카테고리별로 수요를 묶어 점수 순 아이디어 후보를 만든다(카테고리가 없으면 'uncategorized')."""
    groups: dict[str, list[tuple[MarketDemand, Any]]] = defaultdict(list)
    for demand in demands:
        groups[(demand.category or "uncategorized").strip().lower()].append((demand, score_demand(demand)))

    created_at = now or utc_now()
    ideas: list[IdeaCandidate] = []
    for category, items in groups.items():
        items.sort(key=lambda pair: -pair[1].total)
        total = sum(score.total for _, score in items) / len(items)
        confidence = sum(score.confidence for _, score in items) / len(items)
        if total < min_score:
            continue
        top, top_score = items[0]
        ids = tuple(sorted(demand.demand_id for demand, _ in items))
        sources = tuple(sorted({demand.source for demand, _ in items}))
        strongest = max(
            (name for name, value in top_score.factors.items() if value is not None),
            key=lambda name: top_score.factors[name], default="",
        )
        ideas.append(IdeaCandidate(
            idea_id="idea-" + hashlib.sha256((category + "|" + "|".join(ids)).encode("utf-8")).hexdigest()[:16],
            title=f"{category}: {top.title}",
            category=category,
            score=round(total, 1),
            confidence=round(confidence, 2),
            demand_ids=ids,
            sources=sources,
            rationale=(f"수요 {len(items)}건({', '.join(sources)}), 대표 항목 점수 {top_score.total}"
                       + (f", 가장 강한 요소 {strongest}: {top_score.evidence.get(strongest, '')}" if strongest else "")),
            research_query=f"{category} {top.title} 시장 수요 경쟁 현황",
            created_at=created_at,
        ))
    ideas.sort(key=lambda idea: (-idea.score, -idea.confidence, idea.idea_id))
    return ideas[:top_n]


def load_ideas(path: Path | str) -> list[IdeaCandidate]:
    return [IdeaCandidate.from_dict(row) for row in _read(path)]


def append_ideas(path: Path | str, ideas: Sequence[IdeaCandidate]) -> int:
    rows = _read(path)
    seen = {row.get("idea_id") for row in rows}
    new = [idea for idea in ideas if idea.idea_id not in seen]
    if new:
        _write(path, rows + [idea.to_dict() for idea in new])
    return len(new)


def set_idea_status(path: Path | str, idea_id: str, status: str) -> IdeaCandidate:
    if status not in IDEA_STATUSES:
        raise MarketDemandError(f"알 수 없는 status: {status!r}")
    rows = _read(path)
    for row in rows:
        if row.get("idea_id") == idea_id:
            row["status"] = status
            _write(path, rows)
            return IdeaCandidate.from_dict(row)
    raise MarketDemandError(f"아이디어를 찾을 수 없습니다: {idea_id}")
