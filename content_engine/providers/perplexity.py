"""Perplexity Search API ResearchProvider (https://docs.perplexity.ai/api-reference/search-post).

표준 라이브러리(urllib)만 사용한다. API key는 PERPLEXITY_API_KEY 환경변수에서만 읽는다.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .base import (
    ProviderAuthError, ProviderRequestError, ProviderResponseError, ResearchProvider,
    ResearchResult, ResearchSource, require_env,
)

ENV_KEY = "PERPLEXITY_API_KEY"
SEARCH_URL = "https://api.perplexity.ai/search"
RECENCY_VALUES = ("hour", "day", "week", "month", "year")
MAX_RESULTS_LIMIT = 20
MAX_DOMAINS = 20

# (url, headers, body_bytes, timeout) -> (status_code, body_text)
Transport = Callable[[str, dict[str, str], bytes, float], tuple[int, str]]


def _urllib_transport(url: str, headers: dict[str, str], body: bytes, timeout: float) -> tuple[int, str]:
    request = Request(url, data=body, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8")
    except HTTPError as error:
        return error.code, error.read().decode("utf-8", errors="replace")
    except (URLError, TimeoutError, OSError) as error:
        raise ProviderRequestError(f"Perplexity 요청 실패: {type(error).__name__}") from error


class PerplexityResearchProvider(ResearchProvider):
    name = "perplexity"

    def __init__(
        self,
        api_key: str | None = None,
        environ: Mapping[str, str] | None = None,
        transport: Transport | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._api_key = api_key or require_env(ENV_KEY, environ)
        self._transport = transport or _urllib_transport
        self._timeout = timeout

    def research(self, query, domains=None, recency=None, max_results=5):
        if not query or not query.strip():
            raise ValueError("query가 비어 있습니다.")
        if recency is not None and recency not in RECENCY_VALUES:
            raise ValueError(f"recency는 {RECENCY_VALUES} 중 하나여야 합니다.")
        if not 1 <= max_results <= MAX_RESULTS_LIMIT:
            raise ValueError(f"max_results는 1~{MAX_RESULTS_LIMIT}이어야 합니다.")
        payload: dict[str, Any] = {"query": query.strip(), "max_results": max_results}
        if domains:
            payload["search_domain_filter"] = list(domains)[:MAX_DOMAINS]
        if recency:
            payload["search_recency_filter"] = recency

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        status, text = self._transport(SEARCH_URL, headers, json.dumps(payload).encode("utf-8"), self._timeout)
        if status in (401, 403):
            raise ProviderAuthError(f"Perplexity 인증 실패(HTTP {status})", status)
        if status != 200:
            raise ProviderRequestError(f"Perplexity HTTP 오류({status})", status)
        return self._normalize(query.strip(), text)

    def _normalize(self, query: str, text: str) -> ResearchResult:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as error:
            raise ProviderResponseError("Perplexity 응답이 JSON이 아닙니다.") from error
        if not isinstance(data, dict) or not isinstance(data.get("results"), list):
            raise ProviderResponseError("Perplexity 응답에 results 목록이 없습니다.")
        sources: list[ResearchSource] = []
        for index, item in enumerate(data["results"], start=1):
            if not isinstance(item, dict) or not item.get("url"):
                raise ProviderResponseError(f"results[{index - 1}]에 url이 없습니다.")
            url = str(item["url"])
            sources.append(
                ResearchSource(
                    title=str(item.get("title") or ""),
                    url=url,
                    snippet=str(item.get("snippet") or ""),
                    domain=urlparse(url).netloc.lower(),
                    published_at=str(item.get("date") or ""),
                    rank=index,
                )
            )
        return ResearchResult(
            provider=self.name, request_id=str(data.get("id") or ""), query=query, sources=tuple(sources)
        )
