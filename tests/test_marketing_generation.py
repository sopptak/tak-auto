from dataclasses import replace
import json
import unittest

from content_engine.generator import generate_content_bundle
from content_engine.llm_provider import OpenAICompatibleRewriteProvider
from content_engine.marketing import EvidenceItem, build_content_prompt, render_prompt_text
from content_engine.rewrite import MockRewriteProvider, RewriteProvider, RewriteService
from tak_brain import KnowledgeRecord
from tests.test_marketing import approvable

MARKET = EvidenceItem(kind="market_demand", title="AI newsletter", url="https://x/1", snippet="5000 USD", provider="flippa")


def knowledge(kid="knowledge-gen-1", status="approved", **kw) -> KnowledgeRecord:
    def sentences(name, count):
        return " ".join(f"{name} 근거 {index}." for index in range(1, count + 1))

    values = dict(
        id=kid, source_url=f"https://example.test/{kid}", title="원문 제목", article_type="experience",
        knowledge_type="경험", experience=sentences("경험", 4), problem=sentences("문제", 6),
        action=sentences("행동", 8), result=sentences("결과", 4), lesson=sentences("교훈", 7),
        reusable_principle=sentences("원칙", 7), derived_insight=sentences("통찰", 3),
        evidence=("원문 근거 문장",), knowledge_review_status=status,
    )
    values.update(kw)
    return KnowledgeRecord(**values)


def approved_brief(platform="blog", knowledge_ids=("knowledge-gen-1",), **kw):
    base = approvable()
    values = dict(brief_id=f"brief-{platform}", platform=platform, evidence=(MARKET,), confidence=0.6,
                  knowledge_ids=tuple(knowledge_ids), status="approved")
    values.update(kw)
    return replace(base, **values)


class _RecordingProvider(RewriteProvider):
    def __init__(self):
        self.requests = []

    def rewrite(self, request):
        self.requests.append(request)
        return request.draft


def _echo_transport(captured):
    def transport(endpoint, headers, payload, timeout_seconds):
        captured.append(json.loads(payload["messages"][1]["content"]))
        prompt = captured[-1]
        return {"choices": [{"message": {"content": json.dumps(prompt["original_draft"], ensure_ascii=False)}}]}
    return transport


def _llm(captured):
    return OpenAICompatibleRewriteProvider(endpoint="https://llm.example.test/v1", api_key="test-key",
                                           model="test-model", transport=_echo_transport(captured))


class RewriteGuidanceTests(unittest.TestCase):
    def setUp(self):
        self.knowledge = knowledge()
        self.draft = generate_content_bundle(self.knowledge).blog
        self.guidance = render_prompt_text(build_content_prompt(approved_brief()))

    def test_default_has_no_guidance_and_prompt_unchanged(self):
        provider = _RecordingProvider()
        RewriteService(provider).rewrite(self.knowledge, self.draft)
        self.assertIsNone(provider.requests[0].marketing_guidance)
        captured = []
        result = RewriteService(_llm(captured)).rewrite(self.knowledge, self.draft)
        self.assertEqual(result.validation_status, "valid")
        self.assertNotIn("marketing_guidance", captured[0])
        self.assertNotIn("marketing_guidance_rule", captured[0])

    def test_guidance_reaches_request_and_llm_prompt(self):
        provider = _RecordingProvider()
        RewriteService(provider).rewrite(self.knowledge, self.draft, marketing_guidance=self.guidance)
        self.assertEqual(provider.requests[0].marketing_guidance, self.guidance)
        captured = []
        result = RewriteService(_llm(captured)).rewrite(self.knowledge, self.draft, marketing_guidance=self.guidance)
        self.assertEqual(result.validation_status, "valid")
        self.assertEqual(captured[0]["marketing_guidance"], self.guidance)
        self.assertIn("새 사실로 본문에 추가하지 않", captured[0]["marketing_guidance_rule"])
        self.assertIn("[생성 계약]", captured[0]["marketing_guidance"])
        # 사실 경계 계약은 그대로 유지된다.
        self.assertIn("새 사실·숫자·사람·기관·상품", captured[0]["prohibited_changes"])

    def test_empty_guidance_is_omitted(self):
        captured = []
        RewriteService(_llm(captured)).rewrite(self.knowledge, self.draft, marketing_guidance="")
        self.assertNotIn("marketing_guidance", captured[0])

    def test_mock_provider_ignores_guidance(self):
        result = RewriteService(MockRewriteProvider()).rewrite(self.knowledge, self.draft, marketing_guidance=self.guidance)
        self.assertEqual(result.rewritten_draft, self.draft)
        self.assertEqual(result.validation_status, "valid")


if __name__ == "__main__":
    unittest.main()
