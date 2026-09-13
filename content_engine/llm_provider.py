"""OpenAI 호환 LLM을 RewriteProvider 계약에 연결하는 선택적 어댑터."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
import json
import os
from typing import Any
from urllib.request import Request, urlopen

from .models import BlogDraft, ContentDraft, ShortDraft, ThreadDraft
from .rewrite import RewriteProvider, RewriteRequest


class LLMConfigurationError(ValueError):
    """실제 LLM 호출에 필요한 환경 설정이 없을 때 발생한다."""


class LLMResponseError(ValueError):
    """LLM이 RewriteProvider 계약과 다른 응답을 반환할 때 발생한다."""


RewriteTransport = Callable[[str, Mapping[str, str], Mapping[str, object], float], Mapping[str, object]]


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
    with urlopen(request, timeout=timeout_seconds) as response:
        data = json.loads(response.read().decode("utf-8"))
    if not isinstance(data, dict):
        raise LLMResponseError("LLM 응답은 JSON 객체여야 합니다.")
    return data


@dataclass(frozen=True)
class OpenAICompatibleRewriteProvider(RewriteProvider):
    """OpenAI 호환 Chat Completions API 어댑터.

    인스턴스 생성만으로는 네트워크를 호출하지 않는다. RewriteService가 rewrite를
    호출할 때만 HTTP 요청이 발생한다.
    """

    endpoint: str
    api_key: str
    model: str
    timeout_seconds: float = 30.0
    transport: RewriteTransport = _http_transport

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
        transport: RewriteTransport = _http_transport,
    ) -> "OpenAICompatibleRewriteProvider":
        values = os.environ if environ is None else environ
        api_key = values.get("TAK_MEDIA_LLM_API_KEY", "")
        endpoint = values.get("TAK_MEDIA_LLM_ENDPOINT", "")
        model = values.get("TAK_MEDIA_LLM_MODEL", "")
        if not api_key:
            raise LLMConfigurationError("TAK_MEDIA_LLM_API_KEY 환경변수가 필요합니다.")
        if not endpoint:
            raise LLMConfigurationError("TAK_MEDIA_LLM_ENDPOINT 환경변수가 필요합니다.")
        if not model:
            raise LLMConfigurationError("TAK_MEDIA_LLM_MODEL 환경변수가 필요합니다.")
        return cls(endpoint=endpoint, api_key=api_key, model=model, transport=transport)

    def rewrite(self, request: RewriteRequest) -> ContentDraft:
        response = self.transport(
            self.endpoint,
            {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            {
                "model": self.model,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": self._system_prompt()},
                    {"role": "user", "content": self._user_prompt(request)},
                ],
            },
            self.timeout_seconds,
        )
        return self._draft_from_response(request.draft, response)

    @staticmethod
    def _system_prompt() -> str:
        return (
            "You rewrite Korean content within a closed factual boundary. Return only a JSON object with "
            "non-empty title and body strings. Preserve every factual claim, number, person, institution, "
            "product, experience, event, outcome, source URL, and evidence boundary supplied by the user. "
            "You may improve wording, grammar, sentence order, transitions, title, hook, and platform tone. "
            "Never add, infer, amplify, or replace facts. Never add legal or regulatory claims. For financial "
            "content, preserve the distinction between the author's observation and official institution criteria."
        )

    @staticmethod
    def _user_prompt(request: RewriteRequest) -> str:
        return json.dumps(
            {
                "contract_version": "tak-media-rewrite-v1",
                "platform": OpenAICompatibleRewriteProvider._platform_name(request.draft),
                "article_type": request.article_type,
                "knowledge_type": request.knowledge_type,
                "source_url": request.source_url,
                "evidence": request.evidence,
                "approved_knowledge_facts": OpenAICompatibleRewriteProvider._knowledge_facts(request.knowledge),
                "original_draft": {"title": request.draft.title, "body": request.draft.body},
                "allowed_changes": (
                    "조사와 어미 변경, 문장 순서 조정, 자연스러운 연결어, 제목과 훅 개선, "
                    "동일 의미의 한국어 재표현"
                ),
                "prohibited_changes": (
                    "새 사실·숫자·사람·기관·상품·사건·경험·성과 추가, 근거 없는 인과관계, "
                    "법률·규정 판단 추가, 금융기관 공식 기준으로의 확대"
                ),
                "validation_requirements": (
                    "source_url, evidence, 근거 단위 추적 정보는 원본 Draft와 동일하게 유지되며, "
                    "금융 초안의 공식 기준 비해석 문구는 삭제하거나 약화하지 않는다"
                ),
                "platform_requirements": OpenAICompatibleRewriteProvider._platform_requirements(request.draft),
                "response_schema": {"title": "string", "body": "string"},
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _platform_name(draft: ContentDraft) -> str:
        if isinstance(draft, BlogDraft):
            return "blog"
        if isinstance(draft, ShortDraft):
            return "shorts"
        if isinstance(draft, ThreadDraft):
            return "threads"
        return "content"

    @staticmethod
    def _platform_requirements(draft: ContentDraft) -> str:
        if isinstance(draft, BlogDraft):
            return "문단 사이의 연결을 자연스럽게 다듬되, 원문에 없는 원인·결과 관계를 만들지 않는다."
        if isinstance(draft, ShortDraft):
            return "말하듯 짧고 선명하게 다듬고, 훅은 본문을 그대로 반복하지 않는다."
        if isinstance(draft, ThreadDraft):
            return "짧고 독립적으로 읽히게 다듬되, 다른 Threads의 주장이나 사례를 추가하지 않는다."
        return "플랫폼 문체만 다듬고 사실 범위를 유지한다."

    @staticmethod
    def _knowledge_facts(knowledge) -> dict[str, str]:
        return {
            field_name: value
            for field_name in (
                "experience",
                "problem",
                "action",
                "result",
                "lesson",
                "reusable_principle",
                "derived_insight",
            )
            if isinstance(value := getattr(knowledge, field_name), str) and value.strip()
        }

    @staticmethod
    def _draft_from_response(original: ContentDraft, response: Mapping[str, object]) -> ContentDraft:
        try:
            choices = response["choices"]
            content = choices[0]["message"]["content"]  # type: ignore[index]
        except (KeyError, IndexError, TypeError) as error:
            raise LLMResponseError("LLM 응답에 choices[0].message.content가 필요합니다.") from error
        if not isinstance(content, str):
            raise LLMResponseError("LLM 재작성 내용은 문자열이어야 합니다.")
        try:
            rewritten = json.loads(content)
        except json.JSONDecodeError as error:
            raise LLMResponseError("LLM 재작성 내용은 title과 body를 가진 JSON이어야 합니다.") from error
        if not isinstance(rewritten, dict):
            raise LLMResponseError("LLM 재작성 내용은 JSON 객체여야 합니다.")
        title = rewritten.get("title")
        body = rewritten.get("body")
        if not isinstance(title, str) or not title.strip() or not isinstance(body, str) or not body.strip():
            raise LLMResponseError("LLM 재작성 JSON에는 비어 있지 않은 title과 body가 필요합니다.")
        return replace(original, title=title, body=body)
