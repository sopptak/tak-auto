"""6-85 Perplexity Research Provider -> MarketingBrief 근거 연결. 실제 네트워크는 호출하지 않는다."""

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from content_engine.marketing import (
    EvidenceItem, MarketingError, MediaGenerationRef, append_briefs, apply_brief_research, load_briefs,
    research_brief, research_idea,
)
from content_engine.providers import perplexity as pplx
from content_engine.providers.base import (
    ProviderAuthError, ProviderNotConfiguredError, ProviderRequestError, ResearchSource,
)
from content_engine.providers.mock import MockResearchProvider
from content_engine.providers.perplexity import PerplexityResearchProvider
from scripts import marketing_brief as cli
from tests.test_marketing import make_idea_and_demands
from tests.test_marketing_generation import approved_brief, knowledge

FAKE_KEY = "pplx-test-not-a-real-key"
ONE_ASPECT = ("customer_problem",)


def perplexity_body(n=2, prefix="a"):
    return json.dumps({"id": "req-1", "results": [
        {"title": f"Source {prefix}{i}", "url": f"https://news.example.com/{prefix}/{i}",
         "snippet": f"고객 불만 {prefix}{i}", "date": "2026-10-01"} for i in range(1, n + 1)]})


def fake_transport(responses):
    """(status, body) 목록을 차례로 돌려주는 transport. 호출 기록을 남긴다."""
    calls = []

    def transport(url, headers, body, timeout):
        calls.append({"url": url, "headers": headers, "payload": json.loads(body)})
        item = responses[min(len(calls) - 1, len(responses) - 1)]
        if isinstance(item, Exception):
            raise item
        return item
    transport.calls = calls
    return transport


def draft_brief(**kw):
    values = dict(status="draft", knowledge_ids=("knowledge-exp-1",))
    values.update(kw)
    return approved_brief("youtube", **values)


class ResearchBriefTests(unittest.TestCase):
    def test_mock_research_success_and_policy(self):
        brief = draft_brief()
        result = research_brief(brief, MockResearchProvider(), aspects=ONE_ASPECT, max_results=3)
        self.assertEqual(result.provider, "mock")
        self.assertEqual(result.source_counts, {"customer_problem": 3})
        self.assertEqual(len(result.new_evidence), 3)
        for item in result.new_evidence:
            self.assertEqual((item.kind, item.provider, item.aspect), ("research", "mock", "customer_problem"))
            self.assertTrue(item.url)
        self.assertEqual(len(result.knowledge), 1)
        record = result.knowledge[0]
        self.assertEqual(record.knowledge_review_status, "pending")
        self.assertTrue(record.verification_required)
        self.assertEqual(record.knowledge_type, "research")
        self.assertEqual(record.inference_method, "external_research")
        # 경험/판단 필드는 비어 있다: 조사 결과와 사람의 경험 KNOWLEDGE를 섞지 않는다.
        self.assertTrue(all(getattr(record, name) in (None, "") for name in
                            ("experience", "problem", "action", "result", "lesson")))
        self.assertEqual(result.write_blockers, ())

    def test_perplexity_response_parsing(self):
        transport = fake_transport([(200, perplexity_body(2))])
        provider = PerplexityResearchProvider(environ={"PERPLEXITY_API_KEY": FAKE_KEY}, transport=transport)
        result = research_brief(draft_brief(), provider, aspects=ONE_ASPECT, max_results=2)
        self.assertEqual(result.provider, "perplexity")
        self.assertEqual([item.url for item in result.new_evidence],
                         ["https://news.example.com/a/1", "https://news.example.com/a/2"])
        self.assertEqual(result.new_evidence[0].snippet, "고객 불만 a1")
        call = transport.calls[0]
        self.assertEqual(call["url"], pplx.SEARCH_URL)
        self.assertEqual(call["payload"], {"query": "AI 뉴스레터 고객이 겪는 문제 불만 후기", "max_results": 2})
        self.assertEqual(call["headers"]["Authorization"], f"Bearer {FAKE_KEY}")
        # raw 응답 전체는 저장하지 않는다: 근거/KNOWLEDGE에는 구조화한 출처만 남는다.
        stored = json.dumps([item.to_dict() for item in result.new_evidence] +
                            [result.knowledge[0].to_dict()], ensure_ascii=False)
        self.assertNotIn("req-1", stored)
        self.assertNotIn(FAKE_KEY, stored)

    def test_api_key_missing(self):
        with self.assertRaises(ProviderNotConfiguredError) as ctx:
            PerplexityResearchProvider(environ={})
        self.assertIn("PERPLEXITY_API_KEY", str(ctx.exception))

    def test_http_failure_is_recorded_per_aspect(self):
        transport = fake_transport([(500, "oops"), (200, perplexity_body(1, "b"))])
        provider = PerplexityResearchProvider(environ={"PERPLEXITY_API_KEY": FAKE_KEY}, transport=transport)
        result = research_brief(draft_brief(), provider, aspects=("customer_problem", "search_intent"), max_results=1)
        self.assertIn("HTTP 오류(500)", result.errors["customer_problem"])
        self.assertEqual(result.source_counts, {"search_intent": 1})
        self.assertEqual(len(result.new_evidence), 1)

    def test_timeout_is_recorded_per_aspect(self):
        transport = fake_transport([ProviderRequestError("Perplexity 요청 실패: TimeoutError")])
        provider = PerplexityResearchProvider(environ={"PERPLEXITY_API_KEY": FAKE_KEY}, transport=transport)
        result = research_brief(draft_brief(), provider, aspects=ONE_ASPECT)
        self.assertIn("TimeoutError", result.errors["customer_problem"])
        self.assertFalse(result.has_results)

    def test_auth_failure_stops_everything(self):
        transport = fake_transport([(401, "denied")])
        provider = PerplexityResearchProvider(environ={"PERPLEXITY_API_KEY": FAKE_KEY}, transport=transport)
        with self.assertRaises(ProviderAuthError) as ctx:
            research_brief(draft_brief(), provider, aspects=("customer_problem", "search_intent"))
        self.assertNotIn(FAKE_KEY, str(ctx.exception))
        self.assertEqual(len(transport.calls), 1)

    def test_malformed_response_and_missing_source_url(self):
        for body in ("not json", json.dumps({"results": "x"}),
                     json.dumps({"results": [{"title": "no url", "snippet": "s"}]})):
            transport = fake_transport([(200, body), (200, perplexity_body(1, "c"))])
            provider = PerplexityResearchProvider(environ={"PERPLEXITY_API_KEY": FAKE_KEY}, transport=transport)
            result = research_brief(draft_brief(), provider, aspects=("customer_problem", "search_intent"),
                                    max_results=1)
            self.assertIn("customer_problem", result.errors, body)
            # 형식이 깨진 aspect의 출처는 하나도 들어오지 않는다(url 없는 근거 없음).
            self.assertTrue(all(item.url for item in result.new_evidence))
            self.assertEqual([item.aspect for item in result.new_evidence], ["search_intent"])

    def test_duplicate_evidence(self):
        same = [ResearchSource(title="S", url="https://x/1", snippet="dup")] * 2
        provider = MockResearchProvider(sources=same)
        result = research_brief(draft_brief(), provider, aspects=ONE_ASPECT, max_results=2)
        self.assertEqual((len(result.new_evidence), result.duplicate_evidence), (1, 1))
        brief = draft_brief(evidence=draft_brief().evidence + result.new_evidence)
        again = research_brief(brief, provider, aspects=ONE_ASPECT, max_results=2)
        self.assertEqual((len(again.new_evidence), again.duplicate_evidence), (0, 2))

    def test_idea_query_failure_is_not_fatal(self):
        idea, _ = make_idea_and_demands()
        transport = fake_transport([(503, "busy"), (200, perplexity_body(1, "d"))])
        provider = PerplexityResearchProvider(environ={"PERPLEXITY_API_KEY": FAKE_KEY}, transport=transport)
        bundle = research_idea(idea, provider, aspects=ONE_ASPECT, max_results=1)
        self.assertIn("idea_query", bundle.errors)
        self.assertIn("customer_problem", bundle.results)


class ApplyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "tak_marketing_briefs.json"

    def test_apply_adds_only_evidence(self):
        brief = replace(draft_brief(), content_ids=("content-a",),
                        media_generations=(MediaGenerationRef("content-a", "gen-1"),))
        append_briefs(self.path, [brief])
        result = research_brief(brief, MockResearchProvider(), aspects=ONE_ASPECT, max_results=2)
        updated = apply_brief_research(self.path, result)
        self.assertEqual(updated.evidence, brief.evidence + result.new_evidence)
        self.assertGreaterEqual(updated.confidence, brief.confidence)
        self.assertEqual(replace(updated, evidence=brief.evidence, confidence=brief.confidence), brief)
        self.assertEqual(apply_brief_research(self.path, result).evidence, updated.evidence)  # 재적용해도 중복 없음

    def test_approved_and_rejected_briefs_not_written(self):
        for status in ("approved", "rejected"):
            brief = approved_brief("youtube", status=status, brief_id=f"brief-{status}")
            append_briefs(self.path, [brief])
            result = research_brief(brief, MockResearchProvider(), aspects=ONE_ASPECT)
            self.assertTrue(result.write_blockers)
            before = self.path.read_bytes()
            with self.assertRaises(MarketingError):
                apply_brief_research(self.path, result)
            self.assertEqual(self.path.read_bytes(), before)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name)
        self.briefs = self.data / "tak_marketing_briefs.json"
        self.knowledge_path = self.data / "tak_brain_knowledge.json"
        self.knowledge_path.write_text(json.dumps([knowledge("knowledge-exp-1").to_dict()], ensure_ascii=False),
                                       encoding="utf-8")
        self.brief = draft_brief()
        append_briefs(self.briefs, [self.brief])

    def run_cli(self, *args, environ=None):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err), mock.patch.dict("os.environ", environ or {}, clear=True):
            code = cli.main(["--data-dir", str(self.data), *args])
        return code, out.getvalue() + err.getvalue()

    def digests(self):
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(self.data.iterdir())}

    def stored(self):
        return next(b for b in load_briefs(self.briefs) if b.brief_id == self.brief.brief_id)

    def test_provider_is_required(self):
        with self.assertRaises(SystemExit):
            self.run_cli("research", self.brief.brief_id)

    def test_preview_does_not_write(self):
        before = self.digests()
        code, out = self.run_cli("research", self.brief.brief_id, "--provider", "mock", "--aspect", "customer_problem")
        self.assertEqual(code, 0)
        for text in ("provider=mock", "customer_problem", "출처 5건", "새 근거 5건", "pending + verification_required",
                     "미리보기"):
            self.assertIn(text, out)
        self.assertEqual(self.digests(), before)

    def test_write_saves_evidence_and_pending_knowledge_only(self):
        code, out = self.run_cli("--write", "research", self.brief.brief_id, "--provider", "mock",
                                 "--aspect", "customer_problem", "--aspect", "search_intent", "--max-results", "2")
        self.assertEqual(code, 0, out)
        stored = self.stored()
        # 2개 aspect x 2건. mock 출처 url이 aspect마다 같아도 aspect가 달라 별개 근거다.
        self.assertEqual(len(stored.evidence), len(self.brief.evidence) + 4)
        self.assertEqual(stored.status, "draft")
        self.assertEqual(stored.knowledge_ids, self.brief.knowledge_ids)
        records = json.loads(self.knowledge_path.read_text(encoding="utf-8"))
        research = [r for r in records if r["knowledge_type"] == "research"]
        self.assertEqual(len(research), 2)
        self.assertTrue(all(r["knowledge_review_status"] == "pending" and r["verification_required"] for r in research))
        self.assertFalse([r for r in records if r["knowledge_review_status"] == "approved" and r["knowledge_type"] == "research"])
        exp = next(r for r in records if r["id"] == "knowledge-exp-1")
        self.assertEqual(exp, knowledge("knowledge-exp-1").to_dict())  # 기존 KNOWLEDGE 불변

        # 재실행: 근거/KNOWLEDGE 중복 없음, 사람이 승인한 조사 KNOWLEDGE를 pending으로 되돌리지 않음
        records[1]["knowledge_review_status"] = "approved"
        self.knowledge_path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
        before = self.digests()
        code, out = self.run_cli("--write", "research", self.brief.brief_id, "--provider", "mock",
                                 "--aspect", "customer_problem", "--aspect", "search_intent", "--max-results", "2")
        self.assertEqual(code, 0)  # 모두 중복: 변경 없음
        self.assertIn("새 조사 결과가 없습니다(모두 중복)", out)
        self.assertIn("0건 신규, 2건 이미 있음", out)
        self.assertEqual(self.digests(), before)
        self.assertEqual(json.loads(self.knowledge_path.read_text(encoding="utf-8"))[1]["knowledge_review_status"],
                         "approved")

    def test_perplexity_cli_uses_env_key_and_fake_transport(self):
        transport = fake_transport([(200, perplexity_body(2))])
        with mock.patch.object(pplx, "_urllib_transport", transport):
            code, out = self.run_cli("--write", "research", self.brief.brief_id, "--provider", "perplexity",
                                     "--aspect", "customer_problem", environ={"PERPLEXITY_API_KEY": FAKE_KEY})
        self.assertEqual(code, 0, out)
        self.assertIn("provider=perplexity", out)
        self.assertNotIn(FAKE_KEY, out)
        self.assertEqual(len(transport.calls), 1)
        self.assertNotIn(FAKE_KEY, self.briefs.read_text(encoding="utf-8") + self.knowledge_path.read_text(encoding="utf-8"))

    def test_perplexity_cli_without_key_fails_cleanly(self):
        before = self.digests()
        with mock.patch.object(pplx, "_urllib_transport", side_effect=AssertionError("network")) as transport:
            code, out = self.run_cli("--write", "research", self.brief.brief_id, "--provider", "perplexity")
        self.assertEqual(code, 2)
        self.assertIn("PERPLEXITY_API_KEY", out)
        transport.assert_not_called()
        self.assertEqual(self.digests(), before)

    def test_perplexity_http_error_everywhere_writes_nothing(self):
        before = self.digests()
        with mock.patch.object(pplx, "_urllib_transport", fake_transport([(500, "down")])):
            code, out = self.run_cli("--write", "research", self.brief.brief_id, "--provider", "perplexity",
                                     environ={"PERPLEXITY_API_KEY": FAKE_KEY})
        self.assertEqual(code, 2)
        self.assertIn("HTTP 오류(500)", out)
        self.assertEqual(self.digests(), before)

    def test_approved_brief_not_written_and_lineage_untouched(self):
        approved = replace(approved_brief("youtube", brief_id="brief-approved"), content_ids=("content-a",),
                           media_generations=(MediaGenerationRef("content-a", "gen-1"),))
        append_briefs(self.briefs, [approved])
        for name, text in (("tak_marketing_contents.json", '[{"content_id": "content-a"}]'),
                           ("tak_media_generation_marketing-brief-approved.json", "[]"),
                           ("tak_media_archive.json", "[]"), ("tak_performance.json", "[]")):
            (self.data / name).write_text(text, encoding="utf-8")
        before = self.digests()
        code, out = self.run_cli("--write", "research", "brief-approved", "--provider", "mock",
                                 "--aspect", "customer_problem")
        self.assertEqual(code, 2)
        self.assertIn("approved 브리프에는 근거를 추가하지 않습니다", out)
        self.assertEqual(self.digests(), before)
        # 미리보기는 가능하다.
        code, out = self.run_cli("research", "brief-approved", "--provider", "mock", "--aspect", "customer_problem")
        self.assertEqual(code, 0)
        self.assertIn("저장 불가", out)

    def test_draft_research_preserves_other_data_and_lineage(self):
        brief = replace(draft_brief(brief_id="brief-edited"), content_ids=("content-a",),
                        media_generations=(MediaGenerationRef("content-a", "gen-1"),))
        append_briefs(self.briefs, [brief])
        for name in ("tak_marketing_contents.json", "tak_media_archive.json", "tak_performance.json",
                     "tak_media_generation_marketing-brief-edited.json"):
            (self.data / name).write_text('[{"sentinel": 1}]', encoding="utf-8")
        before = {k: v for k, v in self.digests().items()
                  if k not in ("tak_marketing_briefs.json", "tak_brain_knowledge.json")}
        code, out = self.run_cli("--write", "research", "brief-edited", "--provider", "mock",
                                 "--aspect", "customer_problem")
        self.assertEqual(code, 0, out)
        after = {k: v for k, v in self.digests().items()
                 if k not in ("tak_marketing_briefs.json", "tak_brain_knowledge.json")}
        self.assertEqual(after, before)
        stored = next(b for b in load_briefs(self.briefs) if b.brief_id == "brief-edited")
        self.assertEqual((stored.status, stored.knowledge_ids, stored.content_ids, stored.media_generations),
                         (brief.status, brief.knowledge_ids, brief.content_ids, brief.media_generations))

    def test_rejected_brief_not_written(self):
        rejected = approved_brief("blog", status="rejected", brief_id="brief-rejected")
        append_briefs(self.briefs, [rejected])
        before = self.digests()
        code, out = self.run_cli("--write", "research", "brief-rejected", "--provider", "mock",
                                 "--aspect", "customer_problem")
        self.assertEqual(code, 2)
        self.assertIn("rejected 브리프", out)
        self.assertEqual(self.digests(), before)


if __name__ == "__main__":
    unittest.main()
