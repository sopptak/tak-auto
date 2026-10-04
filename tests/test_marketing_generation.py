from dataclasses import replace
import ast
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from content_engine.generator import generate_content_bundle
from content_engine.llm_provider import OpenAICompatibleRewriteProvider
from content_engine.marketing import (
    STATUS_REVIEW_REQUIRED, EvidenceItem, MarketingError, append_briefs, build_content_prompt, generate_candidates,
    generation_blockers, load_briefs, render_prompt_text, save_candidates,
)
from content_engine.marketing import generation as generation_module
from content_engine.models import ShortDraft
from content_engine.publish_history import compute_content_id
from content_engine.shorts_adapter import short_draft_to_shorts_script
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


class GateTests(unittest.TestCase):
    def test_draft_brief_blocked(self):
        result = generate_candidates(approved_brief(status="draft"), [knowledge()])
        self.assertFalse(result.candidates)
        self.assertTrue(any("approved" in item for item in result.blockers))

    def test_rejected_brief_blocked(self):
        b = approved_brief(status="rejected")
        self.assertTrue(any("rejected" in item for item in generation_blockers(b)))
        self.assertFalse(generate_candidates(b, [knowledge()]).candidates)

    def test_unapproved_suggested_brief_blocked(self):
        result = generate_candidates(approved_brief(status="suggested"), [knowledge()])
        self.assertFalse(result.candidates)
        self.assertTrue(result.blockers)

    def test_approved_but_content_no_longer_ready_blocked(self):
        b = approved_brief(evidence=())  # 시장 근거가 사라진 approved 브리프
        self.assertIn("시장 수요 근거가 없습니다.", generation_blockers(b))
        self.assertFalse(generate_candidates(b, [knowledge()]).candidates)

    def test_platformless_brief_blocked(self):
        b = approved_brief(platform="")
        self.assertTrue(any("platform" in item for item in generation_blockers(b)))
        self.assertFalse(generate_candidates(b, [knowledge()]).candidates)

    def test_ready_brief_has_no_blockers(self):
        self.assertEqual(generation_blockers(approved_brief()), [])

    def test_no_approved_knowledge(self):
        for records in ([], [knowledge(status="pending")], [knowledge(kid="other")]):
            result = generate_candidates(approved_brief(), records)
            self.assertFalse(result.candidates)
            self.assertIn("approved KNOWLEDGE가 없습니다", result.blockers[0])
        result = generate_candidates(approved_brief(knowledge_ids=()), [knowledge()])
        self.assertIn("없음", result.blockers[0])

    def test_insufficient_distinct_evidence(self):
        empty = knowledge(experience=None, problem=None, action=None, result=None, lesson=None,
                          reusable_principle=None, derived_insight=None)
        self.assertEqual(generate_content_bundle(empty).status, "insufficient_distinct_evidence")
        result = generate_candidates(approved_brief(), [empty])
        self.assertEqual(result.candidates, ())
        self.assertEqual(result.blockers, ())
        self.assertIn("insufficient_distinct_evidence", result.reasons[0])


class GenerationTests(unittest.TestCase):
    def setUp(self):
        self.knowledge = knowledge()
        self.bundle = generate_content_bundle(self.knowledge)

    def generate(self, platform, **kw):
        return generate_candidates(approved_brief(platform), [self.knowledge], now="2026-10-04T00:00:00Z", **kw)

    def test_blog(self):
        result = self.generate("blog")
        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(result.candidates[0]["original_body"], self.bundle.blog.body)

    def test_threads(self):
        result = self.generate("threads")
        self.assertEqual([c["original_body"] for c in result.candidates], [d.body for d in self.bundle.threads])

    def test_shorts(self):
        result = self.generate("shorts")
        self.assertEqual([c["original_body"] for c in result.candidates], [d.body for d in self.bundle.shorts])
        self.assertNotIn("shorts_script", result.candidates[0])

    def test_youtube_shorts_script(self):
        result = self.generate("youtube")
        self.assertEqual(len(result.candidates), len(self.bundle.shorts))
        for candidate, draft in zip(result.candidates, self.bundle.shorts):
            script = short_draft_to_shorts_script(draft)
            self.assertEqual(candidate["draft_platform"], "shorts")
            self.assertEqual(candidate["shorts_script"]["title"], script.title)
            self.assertEqual(candidate["shorts_script"]["cards"], list(script.cards))
            self.assertEqual(candidate["shorts_script"]["takeaway"], script.takeaway)

    def test_record_fields(self):
        for platform in ("blog", "threads", "shorts", "youtube"):
            for candidate in self.generate(platform).candidates:
                self.assertEqual(candidate["brief_id"], f"brief-{platform}")
                self.assertEqual(candidate["platform"], platform)
                self.assertEqual(candidate["knowledge_id"], self.knowledge.id)
                self.assertEqual(candidate["status"], STATUS_REVIEW_REQUIRED)
                self.assertEqual(candidate["source_url"], self.knowledge.source_url)
                self.assertEqual(candidate["evidence"], list(self.knowledge.evidence))
                self.assertTrue(candidate["evidence_unit_ids"])
                self.assertEqual(candidate["created_at"], "2026-10-04T00:00:00Z")
                self.assertTrue(candidate["generation_contract"])
                self.assertEqual(candidate["rewrite_status"], "not_requested")
                self.assertIsNone(candidate["rewritten_body"])

    def test_content_id_matches_existing_rule(self):
        candidate = self.generate("threads").candidates[0]
        self.assertTrue(candidate["content_id"].startswith("content-"))
        self.assertEqual(candidate["content_id"], compute_content_id(candidate))
        expected = compute_content_id({
            "knowledge_id": self.knowledge.id, "platform": "threads", "source_url": self.knowledge.source_url,
            "evidence_unit_ids": list(self.bundle.threads[0].evidence_unit_ids),
            "original_title": self.bundle.threads[0].title, "original_body": self.bundle.threads[0].body,
        })
        self.assertEqual(candidate["content_id"], expected)

    def test_only_brief_knowledge_used(self):
        other = knowledge(kid="knowledge-other")
        result = generate_candidates(approved_brief("blog"), [other, self.knowledge])
        self.assertEqual({c["knowledge_id"] for c in result.candidates}, {self.knowledge.id})

    def test_mock_rewrite_provider_path(self):
        rewritten = replace(self.bundle.blog, title="다듬은 제목")
        result = self.generate("blog", provider=MockRewriteProvider(rewritten))
        candidate = result.candidates[0]
        self.assertEqual(candidate["rewrite_status"], "rewritten")
        self.assertEqual(candidate["rewritten_title"], "다듬은 제목")
        self.assertEqual(candidate["original_title"], self.bundle.blog.title)
        # 재작성 결과는 content_id에 영향을 주지 않는다.
        self.assertEqual(candidate["content_id"], self.generate("blog").candidates[0]["content_id"])

    def test_rejected_rewrite_keeps_original_and_errors(self):
        bad = replace(self.bundle.blog, body=self.bundle.blog.body + " 매출 999 증가.")
        candidate = self.generate("blog", provider=MockRewriteProvider(bad)).candidates[0]
        self.assertEqual(candidate["rewrite_status"], "rejected")
        self.assertTrue(candidate["validation_errors"])
        self.assertEqual(candidate["status"], STATUS_REVIEW_REQUIRED)

    def test_provider_error_recorded(self):
        class Boom(RewriteProvider):
            def rewrite(self, request):
                raise RuntimeError("llm down")
        candidate = self.generate("blog", provider=Boom()).candidates[0]
        self.assertEqual(candidate["rewrite_status"], "error")
        self.assertIn("llm down", candidate["rewrite_error"])

    def test_marketing_guidance_passed(self):
        provider = _RecordingProvider()
        brief = approved_brief("threads")
        result = generate_candidates(brief, [self.knowledge], provider=provider)
        expected = render_prompt_text(build_content_prompt(brief))
        self.assertEqual(len(provider.requests), len(self.bundle.threads))
        self.assertTrue(all(request.marketing_guidance == expected for request in provider.requests))
        self.assertEqual(result.candidates[0]["marketing_guidance"], expected)
        self.assertIn("반전", result.candidates[0]["generation_contract"])


class SaveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.contents = Path(self.tmp.name) / "tak_marketing_contents.json"
        self.briefs = Path(self.tmp.name) / "tak_marketing_briefs.json"
        self.brief = approved_brief("threads")
        append_briefs(self.briefs, [self.brief])
        self.result = generate_candidates(self.brief, [knowledge()])

    def test_save_review_required_and_link(self):
        self.assertEqual(save_candidates(self.contents, self.briefs, self.result), 5)
        rows = json.loads(self.contents.read_text(encoding="utf-8"))
        self.assertEqual(len(rows), 5)
        self.assertTrue(all(row["status"] == "review_required" for row in rows))
        self.assertTrue(all(row["brief_id"] == self.brief.brief_id for row in rows))
        linked = load_briefs(self.briefs)[0].content_ids
        self.assertEqual(list(linked), [row["content_id"] for row in rows])
        self.assertEqual(load_briefs(self.briefs)[0].status, "approved")
        self.assertFalse(list(Path(self.tmp.name).glob("*.tmp")))  # 원자적 쓰기 잔여물 없음

    def test_no_duplicate_save_or_link(self):
        save_candidates(self.contents, self.briefs, self.result)
        self.assertEqual(save_candidates(self.contents, self.briefs, self.result), 0)
        self.assertEqual(len(json.loads(self.contents.read_text(encoding="utf-8"))), 5)
        content_ids = load_briefs(self.briefs)[0].content_ids
        self.assertEqual(len(content_ids), 5)
        self.assertEqual(len(set(content_ids)), 5)

    def test_existing_rows_preserved(self):
        self.contents.write_text(json.dumps([{"brief_id": "x", "content_id": "content-x"}]), encoding="utf-8")
        save_candidates(self.contents, self.briefs, self.result)
        rows = json.loads(self.contents.read_text(encoding="utf-8"))
        self.assertEqual(rows[0], {"brief_id": "x", "content_id": "content-x"})
        self.assertEqual(len(rows), 6)

    def test_blocked_result_not_saved(self):
        blocked = generate_candidates(approved_brief("threads", status="draft"), [knowledge()])
        with self.assertRaises(MarketingError):
            save_candidates(self.contents, self.briefs, blocked)
        self.assertFalse(self.contents.exists())

    def test_brief_changed_after_generation_not_saved(self):
        from content_engine.marketing import update_element
        update_element(self.briefs, self.brief.brief_id, "sales.offer", "새 오퍼 문구를 사람이 수정함")  # -> draft
        with self.assertRaises(MarketingError):
            save_candidates(self.contents, self.briefs, self.result)
        self.assertFalse(self.contents.exists())
        self.assertEqual(load_briefs(self.briefs)[0].content_ids, ())


class NoPublishTests(unittest.TestCase):
    def test_generation_module_imports_no_publisher(self):
        tree = ast.parse(Path(generation_module.__file__).read_text(encoding="utf-8"))
        modules = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        modules |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        self.assertFalse([name for name in modules if "publish" in name and name != "content_engine.publish_history"])

    def test_generate_and_save_without_network_or_publish(self):
        from content_engine import threads_publisher, youtube_publisher
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch("urllib.request.urlopen", side_effect=AssertionError("network")) as urlopen, \
                mock.patch.object(threads_publisher.ThreadsClient, "__init__", side_effect=AssertionError("publish")) as threads, \
                mock.patch.object(youtube_publisher, "urlopen", side_effect=AssertionError("publish"), create=True) as youtube:
            briefs = Path(tmp) / "b.json"
            brief = approved_brief("youtube")
            append_briefs(briefs, [brief])
            result = generate_candidates(brief, [knowledge()], provider=MockRewriteProvider())
            save_candidates(Path(tmp) / "c.json", briefs, result)
            urlopen.assert_not_called()
            threads.assert_not_called()
            youtube.assert_not_called()
            rows = json.loads((Path(tmp) / "c.json").read_text(encoding="utf-8"))
            self.assertTrue(rows and all(row["status"] == "review_required" for row in rows))
            self.assertFalse(any("published" in json.dumps(row) for row in rows))


if __name__ == "__main__":
    unittest.main()
