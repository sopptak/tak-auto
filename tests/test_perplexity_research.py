"""Perplexity Agent API research provider의 설정, 요청, 응답 검증 테스트."""

from __future__ import annotations

import unittest

from content_engine import LLMConfigurationError, LLMResponseError
from tak_scout.perplexity_research import PerplexityResearchProvider


def agent_response(answer="검증 결과입니다.", model="perplexity/sonar"):
    return {
        "status": "completed",
        "model": model,
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": answer}],
            },
            {
                "type": "search_results",
                "results": [
                    {"url": "https://example.test/a", "title": "A"},
                    {"url": "https://example.test/a", "title": "A duplicate"},
                    {"url": "javascript:alert(1)", "title": "Invalid"},
                    {"url": "https://example.test/b", "title": "B"},
                ],
            },
        ],
    }


class PerplexityResearchProviderTests(unittest.TestCase):
    def test_from_environment_requires_api_key(self):
        with self.assertRaises(LLMConfigurationError):
            PerplexityResearchProvider.from_environment(environ={})

    def test_from_environment_uses_agent_api_defaults(self):
        provider = PerplexityResearchProvider.from_environment(
            environ={"TAK_SCOUT_PERPLEXITY_API_KEY": "test-key"}
        )
        self.assertEqual(provider.model, "perplexity/sonar")
        self.assertEqual(provider.endpoint, "https://api.perplexity.ai/v1/agent")

    def test_legacy_sonar_pro_environment_model_is_mapped(self):
        provider = PerplexityResearchProvider.from_environment(
            environ={
                "TAK_SCOUT_PERPLEXITY_API_KEY": "test-key",
                "TAK_SCOUT_PERPLEXITY_MODEL": "sonar-pro",
            }
        )
        self.assertEqual(provider.model, "perplexity/sonar")

    def test_rejects_non_https_endpoint(self):
        with self.assertRaises(LLMConfigurationError):
            PerplexityResearchProvider.from_environment(
                environ={
                    "TAK_SCOUT_PERPLEXITY_API_KEY": "test-key",
                    "TAK_SCOUT_PERPLEXITY_ENDPOINT": "http://example.test/api",
                }
            )

    def test_search_uses_agent_request_and_extracts_answer_and_sources(self):
        calls = []

        def fake_transport(endpoint, headers, payload, timeout):
            calls.append((endpoint, headers, payload, timeout))
            return agent_response()

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
        endpoint, headers, payload, _timeout = calls[0]
        self.assertEqual(endpoint, "https://api.perplexity.ai/v1/agent")
        self.assertEqual(headers["Authorization"], "Bearer test-key")
        self.assertEqual(payload["model"], "perplexity/sonar")
        self.assertEqual(payload["input"], "최근 AI 정책 동향")
        self.assertIn("instructions", payload)
        self.assertEqual(payload["tool_choice"], {"type": "web_search"})
        self.assertEqual(payload["tools"][0]["type"], "web_search")
        self.assertEqual(
            payload["tools"][0]["filters"],
            {
                "search_recency_filter": "week",
                "search_domain_filter": ["gov.kr", "example.com"],
            },
        )
        self.assertNotIn("messages", payload)
        self.assertNotIn("search_recency_filter", payload)

    def test_empty_query_is_rejected_before_transport(self):
        provider = PerplexityResearchProvider(api_key="test-key")
        with self.assertRaises(ValueError):
            provider.search("  ")

    def test_invalid_recency_is_rejected(self):
        provider = PerplexityResearchProvider(api_key="test-key")
        with self.assertRaises(ValueError):
            provider.search("query", search_recency_filter="decade")

    def test_invalid_domain_filter_is_rejected(self):
        provider = PerplexityResearchProvider(api_key="test-key")
        with self.assertRaises(ValueError):
            provider.search("query", search_domain_filter=("https://example.com/path",))

    def test_failed_agent_run_raises_even_when_transport_returns_response(self):
        provider = PerplexityResearchProvider(
            api_key="test-key",
            transport=lambda *_: {
                "status": "failed",
                "error": {"message": "provider failed"},
                "output": [],
            },
        )
        with self.assertRaisesRegex(LLMResponseError, "provider failed"):
            provider.search("query")

    def test_incomplete_agent_run_raises(self):
        provider = PerplexityResearchProvider(
            api_key="test-key",
            transport=lambda *_: {
                "status": "incomplete",
                "incomplete_details": {"reason": "max_output_tokens"},
                "output": [],
            },
        )
        with self.assertRaises(LLMResponseError):
            provider.search("query")

    def test_malformed_response_raises_response_error(self):
        provider = PerplexityResearchProvider(
            api_key="test-key",
            transport=lambda *_: {"status": "completed", "output": []},
        )
        with self.assertRaises(LLMResponseError):
            provider.search("query")


    def test_search_uses_background_mode_and_polls_until_completed(self):
        post_calls = []
        poll_calls = []
        def fake_transport(endpoint, headers, payload, timeout):
            post_calls.append((endpoint, payload))
            return {"id": "resp_test123", "status": "queued"}
        def fake_poll(url, headers, timeout):
            poll_calls.append(url)
            return agent_response()
        provider = PerplexityResearchProvider(
            api_key="test-key",
            transport=fake_transport,
            poll_transport=fake_poll,
            sleep=lambda _delay: None,
        )
        result = provider.search("최근 AI 정책 동향")
        self.assertEqual(result.answer, "검증 결과입니다.")
        self.assertTrue(post_calls[0][1]["background"])
        self.assertEqual(post_calls[0][1]["max_steps"], 3)
        self.assertEqual(
            poll_calls,
            ["https://api.perplexity.ai/v1/responses/resp_test123"],
        )

    def test_search_times_out_cleanly_when_background_run_never_finishes(self):
        provider = PerplexityResearchProvider(
            api_key="test-key",
            max_wait_seconds=20,
            transport=lambda *_: {"id": "resp_slow", "status": "in_progress"},
            poll_transport=lambda *_: {"id": "resp_slow", "status": "in_progress"},
            sleep=lambda _delay: None,
        )
        with self.assertRaisesRegex(LLMResponseError, "아직 진행 중"):
            provider.search("slow query")


if __name__ == "__main__":
    unittest.main()
