"""Perplexity Agent API 기반 TAK SCOUT 조사 provider.

공개 웹 검색 결과를 바탕으로 조사 답변과 원문 URL을 반환한다.
네트워크 호출은 search() 시점에만 발생하며 API 키는 환경변수에서만 읽는다.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from content_engine import LLMConfigurationError, LLMResponseError


DEFAULT_ENDPOINT = "https://api.perplexity.ai/v1/agent"
DEFAULT_MODEL = "perplexity/sonar"
DEFAULT_TIMEOUT_SECONDS = 45.0
LEGACY_MODEL_ALIASES = {"sonar-pro": DEFAULT_MODEL, "sonar": DEFAULT_MODEL}

ResearchTransport = Callable[
    [str, Mapping[str, str], Mapping[str, object], float],
    Mapping[str, object],
]


@dataclass(frozen=True)
class ResearchResult:
    """Perplexity 조사 결과. answer는 모델 응답, citations는 검증된 원문 URL."""

    query: str
    answer: str
    citations: tuple[str, ...]
    model: str


def _safe_http_error_message(error: HTTPError) -> str:
    """오류 본문에서 메시지만 추출한다. 인증 헤더/API 키는 로그에 남기지 않는다."""
    try:
        payload = json.loads(error.read().decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, OSError):
        payload = {}
    message = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(message, dict):
        message = message.get("message")
    if not isinstance(message, str) or not message.strip():
        message = "응답 본문을 확인할 수 없습니다."
    return f"Perplexity HTTP {error.code}: {message[:300]}"


def _http_transport(
    endpoint: str,
    headers: Mapping[str, str],
    payload: Mapping[str, object],
    timeout_seconds: float,
) -> Mapping[str, object]:
    request = Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=dict(headers),
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
            raw = response.read().decode("utf-8")
    except HTTPError as error:
        raise LLMResponseError(_safe_http_error_message(error)) from None
    except URLError as error:
        raise LLMResponseError(f"Perplexity 연결 실패: {error.reason}") from None
    except TimeoutError:
        raise LLMResponseError("Perplexity 요청이 시간 초과되었습니다.") from None

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as error:
        raise LLMResponseError("Perplexity 응답이 유효한 JSON이 아닙니다.") from error
    if not isinstance(data, dict):
        raise LLMResponseError("Perplexity 응답은 JSON 객체여야 합니다.")
    return data


def _valid_http_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return value


def _extract_response_text(response: Mapping[str, object]) -> str:
    """Agent API의 output[]에서 message/output_text 텍스트를 모은다."""
    output = response.get("output", [])
    if not isinstance(output, list):
        raise LLMResponseError("Perplexity Agent 응답의 output이 목록이 아닙니다.")

    chunks: list[str] = []
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        content = item.get("content", [])
        if not isinstance(content, list):
            continue
        for part in content:
            if (
                isinstance(part, dict)
                and part.get("type") == "output_text"
                and isinstance(part.get("text"), str)
            ):
                chunks.append(part["text"])

    answer = "".join(chunks).strip()
    if not answer:
        raise LLMResponseError("Perplexity Agent 응답에 output_text가 없습니다.")
    return answer


def _extract_citations(response: Mapping[str, object]) -> tuple[str, ...]:
    """Agent API output[]의 search_results item에서 원문 URL을 추출한다."""
    output = response.get("output", [])
    if not isinstance(output, list):
        return ()
    citations: list[str] = []
    seen: set[str] = set()
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "search_results":
            continue
        results = item.get("results", [])
        if not isinstance(results, list):
            continue
        for result in results:
            if not isinstance(result, dict):
                continue
            url = _valid_http_url(result.get("url"))
            if url and url not in seen:
                citations.append(url)
                seen.add(url)
    return tuple(citations)


@dataclass(frozen=True)
class PerplexityResearchProvider:
    """Perplexity Agent API client. Transport 주입으로 네트워크 없는 테스트가 가능하다."""

    api_key: str
    model: str = DEFAULT_MODEL
    endpoint: str = DEFAULT_ENDPOINT
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    transport: ResearchTransport = _http_transport

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
        transport: ResearchTransport = _http_transport,
    ) -> "PerplexityResearchProvider":
        values = os.environ if environ is None else environ
        api_key = values.get("TAK_SCOUT_PERPLEXITY_API_KEY", "").strip()
        if not api_key:
            raise LLMConfigurationError(
                "TAK_SCOUT_PERPLEXITY_API_KEY 환경변수가 필요합니다."
            )
        model = values.get("TAK_SCOUT_PERPLEXITY_MODEL", DEFAULT_MODEL).strip()
        model = LEGACY_MODEL_ALIASES.get(model, model)
        endpoint = values.get("TAK_SCOUT_PERPLEXITY_ENDPOINT", DEFAULT_ENDPOINT).strip()
        if not model:
            raise LLMConfigurationError("TAK_SCOUT_PERPLEXITY_MODEL 값이 비어 있습니다.")
        if not endpoint:
            raise LLMConfigurationError("TAK_SCOUT_PERPLEXITY_ENDPOINT 값이 비어 있습니다.")
        parsed = urlparse(endpoint)
        if parsed.scheme != "https" or not parsed.netloc:
            raise LLMConfigurationError("Perplexity endpoint는 HTTPS URL이어야 합니다.")
        return cls(
            api_key=api_key,
            model=model,
            endpoint=endpoint,
            transport=transport,
        )

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def search(
        self,
        query: str,
        *,
        system_prompt: str = (
            "당신은 사실 검증 중심의 리서치 어시스턴트입니다. "
            "확인된 사실과 추론을 구분하고, 모르는 내용은 모른다고 밝히세요. "
            "핵심 주장에는 출처를 연결하고 과장하지 마세요."
        ),
        search_recency_filter: str | None = None,
        search_domain_filter: tuple[str, ...] = (),
    ) -> ResearchResult:
        """웹 검색을 수행하고 답변 및 Agent API가 반환한 원문 URL을 돌려준다."""
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query는 비어 있지 않은 문자열이어야 합니다.")

        filters: dict[str, object] = {}
        if search_recency_filter:
            if search_recency_filter not in {"hour", "day", "week", "month", "year"}:
                raise ValueError(
                    "search_recency_filter는 hour/day/week/month/year 중 하나여야 합니다."
                )
            filters["search_recency_filter"] = search_recency_filter
        if search_domain_filter:
            domains = [domain.strip().lower() for domain in search_domain_filter if domain.strip()]
            if len(domains) > 20:
                raise ValueError("search_domain_filter는 최대 20개까지 지정할 수 있습니다.")
            if any("/" in domain or "://" in domain or len(domain) > 253 for domain in domains):
                raise ValueError("search_domain_filter에는 유효한 도메인만 지정해야 합니다.")
            if domains:
                filters["search_domain_filter"] = domains

        web_search: dict[str, object] = {"type": "web_search"}
        if filters:
            web_search["filters"] = filters
        payload: dict[str, object] = {
            "model": self.model,
            "instructions": system_prompt,
            "input": query.strip(),
            "tools": [web_search],
            "tool_choice": {"type": "web_search"},
        }
        response = self.transport(
            self.endpoint, self._headers(), payload, self.timeout_seconds
        )

        status = response.get("status")
        if status in {"failed", "cancelled"}:
            error = response.get("error")
            message = error.get("message") if isinstance(error, dict) else None
            raise LLMResponseError(
                f"Perplexity Agent 작업 {status}: "
                + (message[:300] if isinstance(message, str) and message else "상세 오류 없음")
            )
        if status == "incomplete":
            details = response.get("incomplete_details")
            reason = details.get("reason") if isinstance(details, dict) else None
            raise LLMResponseError(
                f"Perplexity Agent 응답이 불완전합니다: {reason or '원인 미상'}"
            )
        if status not in {None, "completed"}:
            raise LLMResponseError(f"Perplexity Agent 상태가 완료되지 않았습니다: {status}")

        answer = _extract_response_text(response)
        response_model = response.get("model")
        model = (
            response_model.strip()
            if isinstance(response_model, str) and response_model.strip()
            else self.model
        )
        return ResearchResult(
            query=query.strip(),
            answer=answer,
            citations=_extract_citations(response),
            model=model,
        )
