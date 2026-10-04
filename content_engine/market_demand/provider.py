"""MarketDemandProvider 인터페이스와 기본 구현(Mock, 수동 입력).

실제 마켓플레이스(Fello, Flippa, Empire Flippers, Acquire, SideProject, Fiverr)용 자동 수집기는
만들지 않는다. 각 사이트의 공식 API 존재 여부와 자동 수집의 약관 적합성을 이 프로젝트에서 확인하지
못했기 때문이다. 대신 사람이 확인한 데이터를 JSON/CSV로 넣는 ``ManualMarketDemandProvider``가
모든 소스의 공통 입구다. 나중에 공식 API가 확인되면 ``MarketDemandProvider``를 구현해
``register_provider()``로 추가하면 하위 단계(점수/아이디어)는 바뀌지 않는다.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Mapping
import csv
import json
from pathlib import Path
from typing import Any

from content_engine.providers.base import ProviderError, ProviderNotConfiguredError, utc_now_iso

from .models import MarketDemand, MarketDemandError, OpportunityScore, compute_demand_id
from .scoring import score_demand

KNOWN_SOURCES = ("fello", "flippa", "empire_flippers", "acquire", "sideproject", "fiverr")
_FIELDS = ("source", "title", "category", "description", "price", "currency", "demand_signal",
           "competition_signal", "url", "collected_at")
_META_BOOL_COLUMNS = ("verified_transaction", "recurring")
_META_COLUMNS = ("monthly_revenue",)


class MarketDemandProvider(ABC):
    name: str = ""

    @abstractmethod
    def search_marketplace(self, query: str, limit: int = 20) -> list[Mapping[str, Any]]:
        """소스에서 원시 항목을 가져온다(벤더 형식 그대로, 이 provider 안에서만 쓰인다)."""

    @abstractmethod
    def normalize(self, raw: Mapping[str, Any]) -> MarketDemand:
        """원시 항목 1건을 표준 ``MarketDemand``로 변환한다."""

    def collect_demand(self, query: str, limit: int = 20) -> list[MarketDemand]:
        collected_at = utc_now_iso()
        result: list[MarketDemand] = []
        for raw in self.search_marketplace(query, limit)[:limit]:
            demand = self.normalize(raw)
            if not demand.collected_at:
                demand = MarketDemand.from_dict({**demand.to_dict(), "collected_at": collected_at})
            result.append(demand)
        return result

    def score_opportunity(self, demand: MarketDemand) -> OpportunityScore:
        return score_demand(demand)


def _truthy(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    return str(value).strip().lower() in ("true", "yes", "y", "1")


def normalize_row(raw: Mapping[str, Any], default_source: str = "manual") -> MarketDemand:
    """사람이 입력한 행(JSON 객체/CSV 행)을 MarketDemand로 변환한다. 필드 이름은 _FIELDS를 따른다."""
    source = str(raw.get("source") or default_source).strip().lower().replace(" ", "_")
    title = str(raw.get("title") or "").strip()
    url = str(raw.get("url") or "").strip()
    metadata: dict[str, Any] = dict(raw.get("metadata") or {})
    for key in _META_BOOL_COLUMNS:
        flag = _truthy(raw.get(key))
        if flag is not None:
            metadata[key] = flag
    for key in _META_COLUMNS:
        if raw.get(key) not in (None, ""):
            metadata[key] = raw[key]
    metadata.setdefault("input_method", "manual")
    price = raw.get("price")
    try:
        price_value = None if price in (None, "") else float(str(price).replace(",", "").replace("$", ""))
    except ValueError as error:
        raise MarketDemandError(f"price를 숫자로 읽을 수 없습니다: {price!r}") from error
    return MarketDemand.from_dict({
        "demand_id": compute_demand_id(source, title, url), "source": source, "title": title,
        "category": raw.get("category"), "description": raw.get("description"), "price": price_value,
        "currency": raw.get("currency") or "USD", "demand_signal": raw.get("demand_signal"),
        "competition_signal": raw.get("competition_signal"), "url": url,
        "collected_at": raw.get("collected_at") or "", "metadata": metadata,
    })


def load_rows(path: Path | str) -> list[dict[str, Any]]:
    target = Path(path)
    if not target.exists():
        raise MarketDemandError(f"파일이 없습니다: {target}")
    if target.suffix.lower() == ".csv":
        with target.open(encoding="utf-8-sig", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    data = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        raise MarketDemandError("JSON 입력은 객체 목록이어야 합니다.")
    return data


class ManualMarketDemandProvider(MarketDemandProvider):
    """사람이 확인해 넣은 JSON/CSV 또는 dict 목록을 읽는 Provider(모든 마켓플레이스 공통)."""

    name = "manual"

    def __init__(self, rows: Iterable[Mapping[str, Any]] | None = None, path: Path | str | None = None, **_ignored) -> None:
        if rows is None and path is None:
            raise ProviderNotConfiguredError("manual provider에는 rows 또는 path(JSON/CSV)가 필요합니다.")
        self._rows = list(rows) if rows is not None else load_rows(path)  # type: ignore[arg-type]

    def search_marketplace(self, query, limit=20):
        needle = (query or "").strip().lower()
        rows = [row for row in self._rows
                if not needle or needle in " ".join(str(row.get(key) or "") for key in ("title", "category", "description")).lower()]
        return rows[:limit]

    def normalize(self, raw):
        return normalize_row(raw)


class MockMarketDemandProvider(MarketDemandProvider):
    name = "mock"

    def __init__(self, **_ignored) -> None:
        pass

    def search_marketplace(self, query, limit=20):
        base = [
            {"source": "mock", "title": f"AI newsletter business ({query})", "category": "newsletter",
             "description": "weekly AI newsletter with subscription revenue", "price": 8000, "demand_signal": 0.7,
             "competition_signal": 0.4, "url": "https://example.com/mock/1", "verified_transaction": "true",
             "monthly_revenue": 600},
            {"source": "mock", "title": f"Logo design gig ({query})", "category": "design", "price": 50,
             "demand_signal": 0.5, "competition_signal": 0.9, "url": "https://example.com/mock/2"},
        ]
        return base[:limit]

    def normalize(self, raw):
        return normalize_row(raw)


_REGISTRY: dict[str, Callable[..., MarketDemandProvider]] = {
    "manual": ManualMarketDemandProvider,
    "mock": MockMarketDemandProvider,
}


def register_provider(name: str, factory: Callable[..., MarketDemandProvider]) -> None:
    if name in _REGISTRY:
        raise ProviderError(f"이미 등록된 provider입니다: {name}")
    _REGISTRY[name] = factory


def available_market_providers() -> tuple[str, ...]:
    return tuple(_REGISTRY)


def get_market_demand_provider(name: str, **kwargs: Any) -> MarketDemandProvider:
    if name in KNOWN_SOURCES and name not in _REGISTRY:
        raise ProviderNotConfiguredError(
            f"{name}: 자동 수집기가 없습니다(공식 API/약관 미확인). 확인한 데이터를 --provider manual 로 입력하세요."
        )
    if name not in _REGISTRY:
        raise ProviderError(f"알 수 없는 market demand provider {name!r} (선택 가능: {', '.join(_REGISTRY)})")
    return _REGISTRY[name](**kwargs)
