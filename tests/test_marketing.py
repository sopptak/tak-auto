from dataclasses import replace
from pathlib import Path
import socket
import tempfile
import unittest
from unittest import mock

from content_engine.market_demand import (
    ManualMarketDemandProvider, build_idea_candidates, IdeaCandidate,
)
from content_engine.marketing import (
    DIMENSIONS, PLATFORMS, ASPECT_QUERIES, Design, Distribution, EvidenceItem, MarketingBrief, MarketingError,
    Psychology, Sales, Storytelling, append_briefs, attribute_lift, brief_from_idea, build_content_prompt,
    build_queries, collect_marketing_insights, derive_all_platform_briefs, derive_platform_brief, link_content,
    load_briefs, readiness_blockers, render_prompt_text, research_idea, run_research_tasks, score_brief,
    set_brief_status, split_metrics,
)
from content_engine.marketing.scoring import PROFILE_BALANCED, PROFILE_INSUFFICIENT, PROFILE_NICHE, PROFILE_VIRAL
from content_engine.performance.models import PerformanceRecord
from content_engine.providers.base import ProviderNotConfiguredError, ProviderRequestError, ResearchProvider
from content_engine.providers.mock import MockResearchProvider

LONG = "매주 3개 사례를 숫자로 보여주는 구체적인 문장"


def brief(**kw):
    return MarketingBrief(brief_id="b1", topic="AI 뉴스레터", **kw)


def full_viral():
    return brief(
        psychology=Psychology(attention=LONG, curiosity=LONG),
        storytelling=Storytelling(hook=LONG),
        design=Design(visual_hook=LONG, thumbnail_concept=LONG),
        distribution=Distribution(discovery_keyword=LONG, search_intent=LONG, distribution_angle=LONG),
    )


def full_niche():
    return brief(
        target_audience=LONG, customer_problem=LONG, desired_action=LONG,
        psychology=Psychology(trust=LONG, desire=LONG, social_proof=LONG),
        sales=Sales(target_customer=LONG, customer_problem=LONG, value_proposition=LONG, benefit=LONG,
                    objection=LONG, proof=LONG, offer=LONG, call_to_action=LONG, conversion_goal=LONG),
        storytelling=Storytelling(call_to_action=LONG),
    )


def make_idea_and_demands():
    demands = ManualMarketDemandProvider(rows=[
        {"source": "flippa", "title": "AI newsletter", "category": "newsletter", "price": 5000,
         "verified_transaction": "true", "competition_signal": 0.2, "demand_signal": 0.7, "url": "https://x/1"},
    ]).collect_demand("")
    idea = build_idea_candidates(demands, min_score=30)[0]
    return idea, demands


class ModelTests(unittest.TestCase):
    def test_validation(self):
        with self.assertRaises(MarketingError):
            MarketingBrief(brief_id="", topic="x")
        with self.assertRaises(MarketingError):
            brief(platform="tiktok")
        with self.assertRaises(MarketingError):
            brief(status="bogus")
        with self.assertRaises(MarketingError):
            brief(confidence=1.5)
        with self.assertRaises(MarketingError):
            brief(requires_human_review=False)
        with self.assertRaises(MarketingError):
            brief(distribution=Distribution(repurpose_targets="blog, tiktok"))
        with self.assertRaises(MarketingError):
            Psychology.from_dict({"nonsense": "x"})
        with self.assertRaises(MarketingError):
            Psychology.from_dict({"attention": 3})
        with self.assertRaises(MarketingError):
            EvidenceItem.from_dict({})
        with self.assertRaises(MarketingError):
            MarketingBrief.from_dict({"topic": "x"})

    def test_dimension_elements_match_spec(self):
        self.assertEqual(len(Psychology.element_names()), 9)
        self.assertEqual(len(Storytelling.element_names()), 7)
        self.assertEqual(len(Sales.element_names()), 9)
        self.assertEqual(len(Design.element_names()), 6)
        self.assertEqual(len(Distribution.element_names()), 6)
        self.assertEqual(set(DIMENSIONS), {"psychology", "storytelling", "sales", "design", "distribution"})

    def test_roundtrip_and_missing(self):
        item = replace(full_niche(), evidence=(EvidenceItem(kind="research", url="https://a"),))
        self.assertEqual(MarketingBrief.from_dict(item.to_dict()), item)
        self.assertIn("psychology.attention", item.missing_fields())
        self.assertNotIn("sales.offer", item.missing_fields())
        self.assertEqual(item.status, "draft")
        self.assertTrue(item.requires_human_review)


class ScoringTests(unittest.TestCase):
    def test_each_dimension_scored_independently(self):
        score = score_brief(brief(
            psychology=Psychology(attention=LONG), storytelling=Storytelling(hook="짧다"),
            sales=Sales(offer=LONG), design=Design(visual_hook=LONG), distribution=Distribution(audience=LONG)))
        self.assertEqual(score.psychology_score, 100.0)
        self.assertEqual(score.storytelling_score, 50.0)
        self.assertEqual(score.sales_score, 100.0)
        self.assertEqual(score.design_score, 100.0)
        self.assertEqual(score.distribution_score, 100.0)

    def test_missing_is_none_not_zero(self):
        score = score_brief(brief())
        for name in ("psychology_score", "storytelling_score", "sales_score", "design_score", "distribution_score",
                     "attention_score", "engagement_score", "conversion_score"):
            self.assertIsNone(getattr(score, name))
        self.assertEqual((score.total_score, score.confidence, score.profile), (0.0, 0.0, PROFILE_INSUFFICIENT))
        self.assertTrue(score.missing)

    def test_views_and_conversion_are_separated(self):
        viral, niche = score_brief(full_viral()), score_brief(full_niche())
        self.assertEqual(viral.profile, PROFILE_VIRAL)
        self.assertGreater(viral.attention_score, viral.conversion_score or 0)
        self.assertEqual(niche.profile, PROFILE_NICHE)
        self.assertGreater(niche.conversion_score, niche.attention_score or 0)

    def test_balanced_and_total_not_a_plain_sum(self):
        viral = full_viral()
        both = replace(full_niche(), storytelling=viral.storytelling, design=viral.design,
                       distribution=viral.distribution,
                       psychology=Psychology(attention=LONG, curiosity=LONG, urgency=LONG, loss_aversion=LONG,
                                             trust=LONG, desire=LONG, social_proof=LONG, identification=LONG))
        score = score_brief(both)
        self.assertEqual(score.profile, PROFILE_BALANCED)
        self.assertGreater(score.total_score, score_brief(full_viral()).total_score - 1)
        # 한 축만 강한 브리프는 약한 축 때문에 total이 관점 평균보다 낮다
        viral = score_brief(full_viral())
        mean_dims = sum(v for v in (viral.psychology_score, viral.storytelling_score, viral.design_score,
                                    viral.distribution_score) if v) / 4
        self.assertLess(viral.total_score, mean_dims)

    def test_deterministic(self):
        self.assertEqual(score_brief(full_niche()), score_brief(full_niche()))

    def test_confidence_reflects_coverage_and_evidence(self):
        low = score_brief(full_niche())
        high = score_brief(replace(full_niche(), confidence=1.0))
        self.assertGreater(high.confidence, low.confidence)
        self.assertLess(low.confidence, 1.0)

    def test_platform_weighting_changes_total(self):
        base = replace(full_viral(), design=Design(visual_hook="짧다"))
        self.assertNotEqual(score_brief(replace(base, platform="shorts")).total_score,
                            score_brief(replace(base, platform="blog")).total_score)


class PlatformTests(unittest.TestCase):
    def test_distinct_angles_per_platform(self):
        briefs = derive_all_platform_briefs(full_niche())
        self.assertEqual(set(briefs), set(PLATFORMS))
        angles = {b.distribution.distribution_angle for b in briefs.values()}
        self.assertEqual(len(angles), 4)
        self.assertEqual(len({b.brief_id for b in briefs.values()}), 4)
        blog = briefs["blog"]
        self.assertEqual(blog.distribution.target_platform, "blog")
        self.assertNotIn("blog", blog.distribution.repurpose_targets)
        self.assertEqual(blog.status, "draft")
        self.assertIn("검색 의도", blog.distribution.distribution_angle)
        self.assertIn("논쟁", briefs["threads"].distribution.distribution_angle)
        with self.assertRaises(MarketingError):
            derive_platform_brief(full_niche(), "tiktok")

    def test_derive_resets_approval_and_content_links(self):
        approved = replace(full_niche(), status="approved", content_ids=("c1",))
        derived = derive_platform_brief(approved, "shorts")
        self.assertEqual((derived.status, derived.content_ids), ("draft", ()))


class ResearchTests(unittest.TestCase):
    def test_standard_queries(self):
        queries = build_queries("AI 뉴스레터")
        self.assertEqual(set(queries), set(ASPECT_QUERIES))
        self.assertEqual(len(queries), 8)
        with self.assertRaises(ValueError):
            build_queries("x", ["nope"])
        with self.assertRaises(ValueError):
            build_queries(" ")

    def test_research_to_evidence_and_pending_knowledge(self):
        bundle = run_research_tasks("AI 뉴스레터", MockResearchProvider(), aspects=["market_demand", "competitors"])
        self.assertTrue(bundle.evidence)
        self.assertTrue(all(item.kind == "research" and item.url and item.provider == "mock" for item in bundle.evidence))
        self.assertEqual({item.aspect for item in bundle.evidence}, {"market_demand", "competitors"})
        records = bundle.knowledge_records()
        self.assertEqual(len(records), 2)
        for record in records:
            self.assertEqual(record.knowledge_review_status, "pending")
            self.assertTrue(record.verification_required)

    def test_partial_failure_recorded_but_config_error_raised(self):
        class Flaky(ResearchProvider):
            name = "flaky"

            def research(self, query, **kw):
                if "경쟁 서비스" in query:
                    raise ProviderRequestError("boom")
                return MockResearchProvider().research(query, **kw)

        bundle = run_research_tasks("x", Flaky(), aspects=["market_demand", "competitors"])
        self.assertIn("competitors", bundle.errors)
        self.assertIn("market_demand", bundle.results)

        class Unconfigured(ResearchProvider):
            name = "u"

            def research(self, query, **kw):
                raise ProviderNotConfiguredError("no key")

        with self.assertRaises(ProviderNotConfiguredError):
            run_research_tasks("x", Unconfigured())

    def test_idea_research_query_used_first(self):
        idea, _ = make_idea_and_demands()
        bundle = research_idea(idea, MockResearchProvider(), aspects=["market_demand"])
        self.assertEqual(list(bundle.results)[0], "idea_query")
        self.assertEqual(bundle.results["idea_query"].query, idea.research_query)

    def test_no_network(self):
        with mock.patch.object(socket, "socket", side_effect=AssertionError("network")):
            research_idea(make_idea_and_demands()[0], MockResearchProvider(), aspects=["market_demand"])


class FlowTests(unittest.TestCase):
    def test_market_demand_to_brief(self):
        idea, demands = make_idea_and_demands()
        bundle = research_idea(idea, MockResearchProvider(), aspects=["customer_problem"])
        item = brief_from_idea(idea, demands, bundle, knowledge_ids=[r.id for r in bundle.knowledge_records()], now="t")
        self.assertEqual((item.status, item.requires_human_review, item.idea_id), ("draft", True, idea.idea_id))
        kinds = {e.kind for e in item.evidence}
        self.assertEqual(kinds, {"market_demand", "research"})
        self.assertEqual(item.distribution.discovery_keyword, "newsletter")
        self.assertGreater(item.confidence, 0)
        self.assertTrue(item.missing_fields())
        self.assertEqual(item.psychology.filled(), {})  # 지어내지 않는다
        self.assertEqual(item, brief_from_idea(idea, demands, bundle, knowledge_ids=[r.id for r in bundle.knowledge_records()], now="t"))

    def test_idea_without_market_demand_is_refused(self):
        idea, demands = make_idea_and_demands()
        with self.assertRaises(MarketingError):
            brief_from_idea(idea, [], None)
        with self.assertRaises(MarketingError):
            brief_from_idea(replace(idea, demand_ids=("demand-other",)), demands)
        with self.assertRaises(MarketingError):
            brief_from_idea(replace(idea, score=10.0), demands)
        with self.assertRaises(MarketingError):
            brief_from_idea(replace(idea, status="rejected"), demands)

    def test_prompt_gate_and_contract(self):
        idea, demands = make_idea_and_demands()
        draft = brief_from_idea(idea, demands)
        with self.assertRaises(MarketingError):
            build_content_prompt(draft)
        self.assertTrue(build_content_prompt(draft, allow_draft=True)["is_draft_brief"])
        ready = replace(full_niche(), status="approved", evidence=draft.evidence, confidence=0.6,
                        platform="blog")
        self.assertEqual(readiness_blockers(ready), [])
        contract = build_content_prompt(ready)
        self.assertEqual([s["id"] for s in contract["thinking_steps"]][0], "market_problem")
        self.assertEqual(len(contract["thinking_steps"]), 8)
        self.assertTrue(contract["requires_human_review"])
        self.assertEqual(contract["platform_strategy"]["angle"], "검색 의도 + 문제 해결")
        text = render_prompt_text(contract)
        self.assertIn("시장에 어떤 문제가 있는가?", text)
        self.assertIn("evidence에 없는 사실", text)
        no_demand = replace(ready, evidence=())
        self.assertTrue(any("시장 수요" in b for b in readiness_blockers(no_demand)))

    def test_store_roundtrip_and_link(self):
        idea, demands = make_idea_and_demands()
        item = brief_from_idea(idea, demands)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "b.json"
            self.assertEqual(append_briefs(path, [item]), 1)
            self.assertEqual(append_briefs(path, [item]), 0)
            self.assertEqual(set_brief_status(path, item.brief_id, "approved").status, "approved")
            self.assertEqual(append_briefs(path, [item]), 0)  # 편집/승인된 브리프는 덮어쓰지 않음
            link_content(path, item.brief_id, "c1")
            link_content(path, item.brief_id, "c1")
            loaded = load_briefs(path)
            self.assertEqual((loaded[0].status, loaded[0].content_ids), ("approved", ("c1",)))
            with self.assertRaises(MarketingError):
                set_brief_status(path, "none", "approved")
            with self.assertRaises(MarketingError):
                set_brief_status(path, item.brief_id, "bogus")


def snap(content_id, metrics, platform="threads"):
    return PerformanceRecord(content_id=content_id, knowledge_id="k", platform=platform, published_at="2026-01-01",
                             metric_collected_at="2026-01-02", metrics=metrics)


class InsightTests(unittest.TestCase):
    def test_split_metrics(self):
        split = split_metrics({"views": 1000, "likes": 30, "replies": 20, "clicks": 5, "leads": 5})
        self.assertEqual((split["attention"], split["engagement"], split["conversion"]), (1000.0, 50.0, 10.0))
        self.assertEqual((split["engagement_rate"], split["conversion_rate"]), (0.05, 0.01))
        empty = split_metrics({"views": 100})
        self.assertIsNone(empty["conversion"])
        self.assertIsNone(empty["conversion_rate"])
        self.assertIsNone(split_metrics({})["attention"])

    def test_performance_to_marketing_attributes_and_lift(self):
        viral = replace(full_viral(), brief_id="v", content_ids=("cv",), platform="shorts")
        niche = replace(full_niche(), brief_id="n", content_ids=("cn", "missing"), platform="blog")
        snaps = {"cv": snap("cv", {"views": 10000, "likes": 500}, "youtube"),
                 "cn": snap("cn", {"views": 200, "likes": 5, "clicks": 20}, "blog")}
        insights = collect_marketing_insights([viral, niche], snaps)
        self.assertEqual({i.brief_id for i in insights}, {"v", "n"})  # 연결 없는 content_id는 제외
        by = {i.brief_id: i for i in insights}
        self.assertIn("psychology.attention", by["v"].attributes)
        self.assertIn("platform.blog", by["n"].attributes)
        self.assertGreater(by["v"].predicted["attention"], by["v"].predicted["conversion"] or 0)
        self.assertIsNone(by["v"].observed["conversion_rate"])  # 측정 안 됨 != 0
        self.assertEqual(by["n"].observed["conversion_rate"], 0.1)
        lift = attribute_lift(insights, "conversion_rate")
        self.assertEqual(set(lift), set(by["n"].attributes))  # 측정된 콘텐츠의 속성만
        self.assertIsNone(lift["sales.offer"]["lift"])  # 비교군 없음
        both = attribute_lift(insights, "engagement_rate")
        self.assertIsNotNone(both["sales.offer"]["lift"])
        self.assertLess(both["sales.offer"]["lift"], 0)

    def test_unlinked_brief_yields_nothing(self):
        self.assertEqual(collect_marketing_insights([full_viral()], {"c": snap("c", {"views": 1})}), [])


if __name__ == "__main__":
    unittest.main()


class CliTests(unittest.TestCase):
    def test_draft_flow(self):
        from content_engine.market_demand import append_demands, append_ideas
        from scripts import marketing_brief as cli
        idea, demands = make_idea_and_demands()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            append_demands(root / "tak_market_demands.json", demands)
            append_ideas(root / "tak_idea_candidates.json", [idea])
            base = ["--data-dir", tmp]
            self.assertEqual(cli.main(base + ["draft", idea.idea_id, "--research", "mock"]), 0)
            self.assertFalse((root / "tak_marketing_briefs.json").exists())
            self.assertEqual(cli.main(base + ["--write", "draft", idea.idea_id, "--research", "mock"]), 0)
            briefs = load_briefs(root / "tak_marketing_briefs.json")
            self.assertEqual(len(briefs), 1)
            import json
            knowledge = json.loads((root / "tak_brain_knowledge.json").read_text(encoding="utf-8"))
            self.assertTrue(all(k["knowledge_review_status"] == "pending" for k in knowledge))
            bid = briefs[0].brief_id
            self.assertEqual(cli.main(base + ["score", bid]), 0)
            self.assertEqual(cli.main(base + ["--write", "platforms", bid]), 0)
            self.assertEqual(len(load_briefs(root / "tak_marketing_briefs.json")), 5)
            self.assertEqual(cli.main(base + ["prompt", bid]), 2)  # draft는 게이트에서 거부
            self.assertEqual(cli.main(base + ["prompt", bid, "--allow-draft"]), 0)
            self.assertEqual(cli.main(base + ["insights"]), 0)
            self.assertEqual(cli.main(base + ["draft", "nope"]), 2)
