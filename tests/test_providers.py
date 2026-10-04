"""외부 AI Provider 계층 검증. 실제 네트워크/API는 호출하지 않는다.

실제 Perplexity 호출 테스트는 TAK_RUN_INTEGRATION=1과 PERPLEXITY_API_KEY가 모두 있을 때만 실행된다.
"""

from __future__ import annotations

import json
import os
import unittest

from content_engine.followup import FollowUpCandidate
from content_engine.providers import (
    ClipProvider, ElevenLabsVoiceProvider, ImageProvider, MockClipProvider, MockImageProvider,
    MockResearchProvider, MockVideoProvider, MockVoiceProvider, OpusClipProvider, PerplexityResearchProvider,
    ProviderAuthError, ProviderError, ProviderNotConfiguredError, ProviderNotImplementedError,
    ProviderRequestError, ProviderResponseError, RecraftImageProvider, ResearchProvider, ResearchResult,
    RunwayVideoProvider, VideoProvider, VoiceProvider, available_providers, get_clip_provider,
    get_image_provider, get_research_provider, get_video_provider, get_voice_provider,
)
from content_engine.providers import perplexity as pplx
from content_engine.research_bridge import (
    accepted_followups_to_requests, followup_to_research_query, research_to_knowledge,
)

GOOD = {
    "id": "req-1",
    "results": [
        {"title": "A", "url": "https://News.Example.com/a", "snippet": "sa", "date": "2026-10-01"},
        {"title": "B", "url": "https://example.org/b", "snippet": "sb"},
    ],
}


def _transport(status=200, body=None, record=None):
    def call(url, headers, data, timeout):
        if record is not None:
            record.append((url, headers, json.loads(data)))
        return status, body if isinstance(body, str) else json.dumps(body if body is not None else GOOD)
    return call


def _perplexity(**kwargs):
    return PerplexityResearchProvider(api_key="test-key", **kwargs)


class ContractTests(unittest.TestCase):
    def test_all_mocks_satisfy_interfaces_and_return_standard_results(self):
        self.assertIsInstance(MockResearchProvider(), ResearchProvider)
        self.assertIsInstance(MockVoiceProvider(), VoiceProvider)
        self.assertIsInstance(MockImageProvider(), ImageProvider)
        self.assertIsInstance(MockVideoProvider(), VideoProvider)
        self.assertIsInstance(MockClipProvider(), ClipProvider)
        self.assertEqual(len(MockResearchProvider().research("q", max_results=3).sources), 3)
        self.assertEqual(MockVoiceProvider().synthesize("abc").metadata["chars"], 3)
        self.assertEqual(MockImageProvider().upscale("x.png").status, "completed")
        self.assertEqual(len(MockClipProvider().create_shorts("u", max_clips=2).clip_urls), 2)
        self.assertEqual(MockVideoProvider().generate("p", duration_seconds=5).duration_seconds, 5)

    def test_real_adapters_implement_interfaces(self):
        self.assertIsInstance(ElevenLabsVoiceProvider(api_key="k"), VoiceProvider)
        self.assertIsInstance(RecraftImageProvider(api_key="k"), ImageProvider)
        self.assertIsInstance(RunwayVideoProvider(api_key="k"), VideoProvider)
        self.assertIsInstance(OpusClipProvider(api_key="k"), ClipProvider)
        self.assertIsInstance(_perplexity(), ResearchProvider)


class SkeletonTests(unittest.TestCase):
    def test_missing_credentials_name_the_variable_only(self):
        cases = [
            (ElevenLabsVoiceProvider, "ELEVENLABS_API_KEY"),
            (RecraftImageProvider, "RECRAFT_API_KEY"),
            (RunwayVideoProvider, "RUNWAYML_API_SECRET"),
            (OpusClipProvider, "OPUSCLIP_API_KEY"),
        ]
        for cls, var in cases:
            with self.subTest(var=var):
                with self.assertRaises(ProviderNotConfiguredError) as ctx:
                    cls(environ={})
                self.assertIn(var, str(ctx.exception))

    def test_configured_skeletons_raise_not_implemented(self):
        with self.assertRaises(ProviderNotImplementedError):
            ElevenLabsVoiceProvider(environ={"ELEVENLABS_API_KEY": "k"}).synthesize("t")
        with self.assertRaises(ProviderNotImplementedError):
            RecraftImageProvider(api_key="k").generate("p")
        with self.assertRaises(ProviderNotImplementedError):
            RunwayVideoProvider(api_key="k").generate("p")
        with self.assertRaises(ProviderNotImplementedError):
            OpusClipProvider(api_key="k").create_shorts("u")


class RegistryTests(unittest.TestCase):
    def test_default_research_without_key_is_mock(self):
        self.assertEqual(get_research_provider(environ={}).name, "mock")

    def test_default_research_with_key_is_perplexity(self):
        self.assertEqual(get_research_provider(environ={"PERPLEXITY_API_KEY": "k"}).name, "perplexity")

    def test_env_selection_and_explicit_override(self):
        self.assertEqual(get_research_provider(environ={"TAK_RESEARCH_PROVIDER": "mock", "PERPLEXITY_API_KEY": "k"}).name, "mock")
        self.assertEqual(get_voice_provider("mock", environ={"TAK_VOICE_PROVIDER": "elevenlabs"}).name, "mock")
        self.assertEqual(get_image_provider(environ={"TAK_IMAGE_PROVIDER": "recraft", "RECRAFT_API_KEY": "k"}).name, "recraft")
        self.assertEqual(get_video_provider(environ={"TAK_VIDEO_PROVIDER": "runway", "RUNWAYML_API_SECRET": "k"}).name, "runway")
        self.assertEqual(get_clip_provider(environ={"TAK_CLIP_PROVIDER": "opusclip", "OPUSCLIP_API_KEY": "k"}).name, "opusclip")

    def test_explicit_real_provider_without_key_does_not_fall_back_to_mock(self):
        with self.assertRaises(ProviderNotConfiguredError):
            get_research_provider("perplexity", environ={})
        with self.assertRaises(ProviderNotConfiguredError):
            get_voice_provider(environ={"TAK_VOICE_PROVIDER": "elevenlabs"})

    def test_unknown_provider_and_kind(self):
        with self.assertRaises(ProviderError):
            get_research_provider("nope", environ={})
        with self.assertRaises(ProviderError):
            available_providers("nope")
        self.assertEqual(set(available_providers("clip")), {"opusclip", "mock"})


class PerplexityTests(unittest.TestCase):
    def test_missing_key(self):
        with self.assertRaises(ProviderNotConfiguredError):
            PerplexityResearchProvider(environ={})

    def test_normalization(self):
        result = _perplexity(transport=_transport()).research("질의")
        self.assertEqual((result.provider, result.request_id, result.query), ("perplexity", "req-1", "질의"))
        first, second = result.sources
        self.assertEqual((first.title, first.domain, first.published_at, first.rank), ("A", "news.example.com", "2026-10-01", 1))
        self.assertEqual((second.published_at, second.rank), ("", 2))

    def test_request_shape_and_auth_header(self):
        record = []
        _perplexity(transport=_transport(record=record)).research(" q ", domains=["a.com"], recency="week", max_results=3)
        url, headers, body = record[0]
        self.assertEqual(url, pplx.SEARCH_URL)
        self.assertEqual(headers["Authorization"], "Bearer test-key")
        self.assertEqual(body, {"query": "q", "max_results": 3, "search_domain_filter": ["a.com"], "search_recency_filter": "week"})

    def test_input_validation(self):
        provider = _perplexity(transport=_transport())
        for kwargs in ({"query": " "}, {"query": "q", "recency": "decade"}, {"query": "q", "max_results": 0}, {"query": "q", "max_results": 99}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                provider.research(**kwargs)

    def test_http_errors_map_to_internal_exceptions(self):
        with self.assertRaises(ProviderAuthError):
            _perplexity(transport=_transport(status=401, body="{}")).research("q")
        with self.assertRaises(ProviderAuthError):
            _perplexity(transport=_transport(status=403, body="{}")).research("q")
        with self.assertRaises(ProviderRequestError) as ctx:
            _perplexity(transport=_transport(status=500, body="boom")).research("q")
        self.assertEqual(ctx.exception.status_code, 500)

    def test_error_messages_never_contain_the_key(self):
        with self.assertRaises(ProviderAuthError) as ctx:
            _perplexity(transport=_transport(status=401, body="{}")).research("q")
        self.assertNotIn("test-key", str(ctx.exception))

    def test_malformed_responses(self):
        for body in ("not json", "[]", {"nothing": 1}, {"results": "x"}, {"results": [{"title": "no url"}]}, {"results": ["x"]}):
            with self.subTest(body=body), self.assertRaises(ProviderResponseError):
                _perplexity(transport=_transport(body=body)).research("q")

    def test_transport_failure_propagates_as_request_error(self):
        def broken(*_args):
            raise ProviderRequestError("down")
        with self.assertRaises(ProviderRequestError):
            _perplexity(transport=broken).research("q")


class BridgeTests(unittest.TestCase):
    def test_research_to_pending_knowledge(self):
        result = _perplexity(transport=_transport()).research("대출 금리")
        record = research_to_knowledge(result)
        self.assertEqual(record.knowledge_review_status, "pending")
        self.assertTrue(record.verification_required)
        self.assertEqual(record.source_url, "https://News.Example.com/a")
        self.assertTrue(record.id.startswith("knowledge-research-"))
        self.assertEqual(record.id, research_to_knowledge(result).id)
        self.assertEqual(len(record.evidence), 2)

    def test_empty_sources_rejected(self):
        with self.assertRaises(ValueError):
            research_to_knowledge(ResearchResult(provider="x", query="q"))

    def test_only_accepted_followups_become_requests(self):
        def cand(cid, status):
            return FollowUpCandidate(cid, "k1", "소재", "repurpose", "blog", "how_to", 70, "r", status=status)
        requests = accepted_followups_to_requests([cand("a", "candidate"), cand("b", "accepted"), cand("c", "rejected")])
        self.assertEqual([r["candidate_id"] for r in requests], ["b"])
        self.assertTrue(requests[0]["requires_human_review"])
        self.assertIn("방법", requests[0]["research_query"])
        self.assertIn("소재", followup_to_research_query(cand("a", "candidate")))


@unittest.skipUnless(
    os.environ.get("TAK_RUN_INTEGRATION") == "1" and os.environ.get("PERPLEXITY_API_KEY"),
    "실제 API 테스트: TAK_RUN_INTEGRATION=1 및 PERPLEXITY_API_KEY 필요",
)
class PerplexityIntegrationTests(unittest.TestCase):
    def test_live_search(self):
        result = PerplexityResearchProvider().research("Python 3.14 release", max_results=2)
        self.assertTrue(result.sources)


if __name__ == "__main__":
    unittest.main()
