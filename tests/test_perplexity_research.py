"""Perplexity research provider의 설정, 요청, 응답 검증 테스트."""

from __future__ import annotations

import unittest

from content_engine import LLMConfigurationError, LLMResponseError
from tak_scout.perplexity_research import PerplexityResearchProvider


class PerplexityResearchProviderTests(unittest.TestCase):
    def test_from_environment_requires_api_key(self):
        with self.assertRaises(LLMConfigurationError):
            PerplexityResearchProvider.from_environment(environ={})

    def test_from_environment_uses_safe_defaults(self):
        provider = PerplexityResearchProvider.from_environment(
            environ={"TAK_SCOUT_PERPLEXITY_API_KEY": "test-key"}
        )
        self.assertEqual(provider.model, "sonar-pro")
        self.assertEqual(provider.endpoint, "https://api.perplexity.ai/chat/completions")

    def test_rejects_non_https_endpoint(self):
        with self.assertRaises(LLMConfigurationError):
            PerplexityResearchProvider.from_environment(
                environ={
                    "TAK_SCOUT_PERPLEXITY_API_KEY": "test-key",
                    "TAK_SCOUT_PERPLEXITY_ENDPOINT": "http://example.test/api",
                }
            )

    def test_search_returns_answer_and_deduplicated_http_citations(self):
        calls = []

        def fake_transport(endpoint, headers, payload, timeout):
            calls.append((endpoint, headers, payload, timeout))
            return {
                "model": "sonar-pro",
                "choices": [{"message": {"content": "검증 결과입니다."}}],
                "citations": [
                    "https://example.test/a",
                    "https://example.test/a",
                    "javascript:alert(1)",
                    "https://example.test/b",
                ],
            }

        provider = PerplexityResearchProvider(
            api_key="test-key", transport=fake_transport
        )
        result = provider.search(
            "최근 AI 정책 동향",
            search_recency_filter="week",
            search_domain_filter=("gov.kr", "example.com"),
        )

        self.assertEqual(result.query, "최근 AI 정책 동향")
        self.assertEqual(result.answer, "검증 결과입니다.")
        self.assertEqual(
            result.citations,
            ("https://example.test/a", "https://example.test/b"),
        )
        self.assertEqual(calls[0][1]["Authorization"], "Bearer test-key")
        self.assertEqual(calls[0][2]["search_recency_filter"], "week")
        self.assertEqual(calls[0][2]["search_domain_filter"], ["gov.kr", "example.com"])

    def test_empty_query_is_rejected_before_transport(self):
        provider = PerplexityResearchProvider(api_key="test-key")
        with self.assertRaises(ValueError):
            provider.search("  ")

    def test_invalid_recency_is_rejected(self):
        provider = PerplexityResearchProvider(api_key="test-key")
        with self.assertRaises(ValueError):
            provider.search("query", search_recency_filter="decade")

    def test_malformed_response_raises_response_error(self):
        provider = PerplexityResearchProvider(
            api_key="test-key",
            transport=lambda *_: {"choices": []},
        )
        with self.assertRaises(LLMResponseError):
            provider.search("query")


if __name__ == "__main__":
    unittest.main()
