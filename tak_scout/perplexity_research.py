"""Perplexity Agent API provider with background execution and bounded polling."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from content_engine import LLMConfigurationError, LLMResponseError

DEFAULT_ENDPOINT = "https://api.perplexity.ai/v1/agent"
DEFAULT_MODEL = "perplexity/sonar"
DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_MAX_WAIT_SECONDS = 85.0
LEGACY_MODEL_ALIASES = {"sonar-pro": DEFAULT_MODEL, "sonar": DEFAULT_MODEL}

ResearchTransport = Callable[[str, Mapping[str, str], Mapping[str, object], float], Mapping[str, object]]
ResearchPollTransport = Callable[[str, Mapping[str, str], float], Mapping[str, object]]


@dataclass(frozen=True)
class ResearchResult:
    query: str
    answer: str
    citations: tuple[str, ...]
    model: str


def _decode_response(raw: str) -> Mapping[str, object]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as error:
        raise LLMResponseError("Perplexity 응답이 유효한 JSON이 아닙니다.") from error
    if not isinstance(data, dict):
        raise LLMResponseError("Perplexity 응답은 JSON 객체여야 합니다.")
    return data


def _safe_http_error_message(error: HTTPError) -> str:
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


def _http_transport(endpoint, headers, payload, timeout_seconds):
    request = Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=dict(headers),
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
            return _decode_response(response.read().decode("utf-8"))
    except HTTPError as error:
        raise LLMResponseError(_safe_http_error_message(error)) from None
    except (URLError, TimeoutError) as error:
        raise LLMResponseError("Perplexity 요청 연결 또는 응답이 시간 초과되었습니다.") from None


def _http_poll_transport(url, headers, timeout_seconds):
    request = Request(url, headers=dict(headers), method="GET")
    try:
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
            return _decode_response(response.read().decode("utf-8"))
    except HTTPError as error:
        raise LLMResponseError(_safe_http_error_message(error)) from None
    except (URLError, TimeoutError):
        raise LLMResponseError("Perplexity 작업 상태 확인이 시간 초과되었습니다.") from None


def _valid_http_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    parsed = urlparse(value)
    return value if parsed.scheme in {"http", "https"} and parsed.netloc else None


def _extract_response_text(response: Mapping[str, object]) -> str:
    output = response.get("output", [])
    if not isinstance(output, list):
        raise LLMResponseError("Perplexity Agent 응답의 output이 목록이 아닙니다.")
    chunks = []
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        content = item.get("content", [])
        if not isinstance(content, list):
            continue
        chunks.extend(
            part["text"] for part in content
            if isinstance(part, dict)
            and part.get("type") == "output_text"
            and isinstance(part.get("text"), str)
        )
    answer = "".join(chunks).strip()
    if not answer:
        raise LLMResponseError("Perplexity Agent 응답에 output_text가 없습니다.")
    return answer


def _extract_citations(response: Mapping[str, object]) -> tuple[str, ...]:
    output = response.get("output", [])
    if not isinstance(output, list):
        return ()
    citations, seen = [], set()
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "search_results":
            continue
        results = item.get("results", [])
        if not isinstance(results, list):
            continue
        for result in results:
            url = _valid_http_url(result.get("url")) if isinstance(result, dict) else None
            if url and url not in seen:
                citations.append(url)
                seen.add(url)
    return tuple(citations)


@dataclass(frozen=True)
class PerplexityResearchProvider:
    api_key: str
    model: str = DEFAULT_MODEL
    endpoint: str = DEFAULT_ENDPOINT
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_wait_seconds: float = DEFAULT_MAX_WAIT_SECONDS
    transport: ResearchTransport = _http_transport
    poll_transport: ResearchPollTransport = _http_poll_transport
    sleep: Callable[[float], None] = time.sleep

    @classmethod
    def from_environment(cls, environ=None, transport=_http_transport, poll_transport=_http_poll_transport, sleep=time.sleep):
        values = os.environ if environ is None else environ
        api_key = values.get("TAK_SCOUT_PERPLEXITY_API_KEY", "").strip()
        if not api_key:
            raise LLMConfigurationError("TAK_SCOUT_PERPLEXITY_API_KEY 환경변수가 필요합니다.")
        model = values.get("TAK_SCOUT_PERPLEXITY_MODEL", DEFAULT_MODEL).strip()
        model = LEGACY_MODEL_ALIASES.get(model, model)
        endpoint = values.get("TAK_SCOUT_PERPLEXITY_ENDPOINT", DEFAULT_ENDPOINT).strip()
        if not model or not endpoint:
            raise LLMConfigurationError("Perplexity 모델 또는 endpoint 설정이 비어 있습니다.")
        parsed = urlparse(endpoint)
        if parsed.scheme != "https" or not parsed.netloc:
            raise LLMConfigurationError("Perplexity endpoint는 HTTPS URL이어야 합니다.")
        try:
            timeout = max(5.0, min(float(values.get("TAK_SCOUT_PERPLEXITY_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)), 30.0))
            max_wait = max(20.0, min(float(values.get("TAK_SCOUT_PERPLEXITY_MAX_WAIT_SECONDS", DEFAULT_MAX_WAIT_SECONDS)), 90.0))
        except ValueError as error:
            raise LLMConfigurationError("Perplexity timeout 환경변수는 숫자여야 합니다.") from error
        return cls(
            api_key=api_key, model=model, endpoint=endpoint,
            timeout_seconds=timeout, max_wait_seconds=max_wait,
            transport=transport, poll_transport=poll_transport, sleep=sleep,
        )

    def _headers(self):
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def _wait_for_completion(self, response: Mapping[str, object]) -> Mapping[str, object]:
        status = response.get("status")
        if status not in {"queued", "in_progress"}:
            return response
        response_id = response.get("id")
        if not isinstance(response_id, str) or not response_id:
            raise LLMResponseError("Perplexity가 비동기 작업 ID를 반환하지 않았습니다.")
        poll_url = "https://api.perplexity.ai/v1/responses/" + response_id
        deadline = time.monotonic() + self.max_wait_seconds
        delay = 2.0
        while time.monotonic() < deadline:
            self.sleep(delay)
            remaining = deadline - time.monotonic()
            response = self.poll_transport(poll_url, self._headers(), min(self.timeout_seconds, max(5.0, remaining)))
            status = response.get("status")
            if status not in {"queued", "in_progress"}:
                return response
            delay = min(delay * 1.5, 8.0)
        raise LLMResponseError(
            "Perplexity 조사가 아직 진행 중입니다. 잠시 후 다시 시도해 주세요. "
            "요청을 중복 실행하지 않도록 잠시 기다려 주세요."
        )

    def search(self, query: str, *, system_prompt: str = (
        "당신은 사실 검증 중심의 리서치 어시스턴트입니다. 확인된 사실과 추론을 구분하고, "
        "모르는 내용은 모른다고 밝히며, 핵심 주장에 출처를 연결하세요."
    ), search_recency_filter: str | None = None, search_domain_filter: tuple[str, ...] = ()) -> ResearchResult:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query는 비어 있지 않은 문자열이어야 합니다.")
        filters = {}
        if search_recency_filter:
            if search_recency_filter not in {"hour", "day", "week", "month", "year"}:
                raise ValueError("search_recency_filter는 hour/day/week/month/year 중 하나여야 합니다.")
            filters["search_recency_filter"] = search_recency_filter
        if search_domain_filter:
            domains = [domain.strip().lower() for domain in search_domain_filter if domain.strip()]
            if len(domains) > 20 or any("/" in domain or "://" in domain or len(domain) > 253 for domain in domains):
                raise ValueError("search_domain_filter에는 최대 20개의 유효한 도메인을 지정해야 합니다.")
            if domains:
                filters["search_domain_filter"] = domains

        web_search = {"type": "web_search"}
        if filters:
            web_search["filters"] = filters
        payload = {
            "model": self.model,
            "instructions": system_prompt,
            "input": query.strip(),
            "tools": [web_search],
            "tool_choice": {"type": "web_search"},
            "background": True,
            "max_steps": 3,
        }
        response = self.transport(self.endpoint, self._headers(), payload, self.timeout_seconds)
        response = self._wait_for_completion(response)
        status = response.get("status")
        if status in {"failed", "cancelled"}:
            error = response.get("error")
            message = error.get("message") if isinstance(error, dict) else None
            raise LLMResponseError(
                f"Perplexity Agent 작업 {status}: " +
                (message[:300] if isinstance(message, str) and message else "상세 오류 없음")
            )
        if status == "incomplete":
            details = response.get("incomplete_details")
            reason = details.get("reason") if isinstance(details, dict) else None
            raise LLMResponseError(f"Perplexity Agent 응답이 불완전합니다: {reason or '원인 미상'}")
        if status not in {None, "completed"}:
            raise LLMResponseError(f"Perplexity Agent 상태가 완료되지 않았습니다: {status}")
        answer = _extract_response_text(response)
        response_model = response.get("model")
        model = response_model.strip() if isinstance(response_model, str) and response_model.strip() else self.model
        return ResearchResult(query=query.strip(), answer=answer, citations=_extract_citations(response), model=model)
