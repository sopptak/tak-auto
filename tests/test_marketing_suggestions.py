from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from content_engine.marketing import (
    EvidenceItem, MarketingError, Suggestion, append_briefs, append_suggestions, approval_blockers,
    brief_from_idea, load_briefs, load_suggestions, resolve_suggestion, set_brief_status, set_element,
    suggest_elements, update_element,
)
from tests.test_marketing import approvable, brief, make_idea_and_demands

LONG = "x" * 40


def research(aspect, snippet, provider="perplexity", url="https://src/1"):
    return EvidenceItem(kind="research", title=aspect, url=url, snippet=snippet, provider=provider, aspect=aspect)


class SuggestionTests(unittest.TestCase):
    def test_no_evidence_no_suggestion(self):
        self.assertEqual(suggest_elements(brief()), [])

    def test_grounded_and_human_review(self):
        b = brief(evidence=(research("customer_problem", "지점장은 보고서 작성에 주 5시간을 쓴다는 불만이 반복된다"),
                            research("search_intent", "AI 보고서 자동화 방법", url="https://src/2")))
        sugs = {s.key: s for s in suggest_elements(b)}
        self.assertIn("psychology.pain", sugs)
        self.assertIn("distribution.search_intent", sugs)
        self.assertNotIn("psychology.social_proof", sugs)
        for s in sugs.values():
            self.assertTrue(s.requires_human_review)
            self.assertEqual(s.status, "suggested")
            self.assertTrue(s.evidence_ids)
            self.assertLessEqual(s.confidence, 0.6)
        self.assertIn("5시간", sugs["psychology.pain"].suggested_value)  # 인용만, 새 수치 없음
        self.assertEqual(suggest_elements(b), suggest_elements(b))  # 결정적

    def test_filled_elements_skipped_and_mock_low_confidence(self):
        from content_engine.marketing import Psychology
        b = brief(psychology=Psychology(pain=LONG), evidence=(research("customer_problem", "p", provider="mock"),))
        sugs = {s.key: s for s in suggest_elements(b)}
        self.assertNotIn("psychology.pain", sugs)
        self.assertEqual(sugs["sales.customer_problem"].confidence, 0.1)

    def test_strategy_suggestions_are_not_factual(self):
        sugs = suggest_elements(brief(platform="threads"))
        self.assertTrue(sugs)
        self.assertTrue(all(s.basis == "strategy" and not s.evidence_ids for s in sugs))

    def test_evidence_suggestion_requires_evidence_ids(self):
        with self.assertRaises(MarketingError):
            Suggestion("s", "b", "psychology", "pain", "v", (), "r", 0.5)
        with self.assertRaises(MarketingError):
            Suggestion("s", "b", "psychology", "pain", "v", ("e",), "r", 0.5, requires_human_review=False)

    def test_accept_reject_workflow(self):
        b = brief(evidence=(research("customer_problem", "반복되는 불만"),))
        with tempfile.TemporaryDirectory() as tmp:
            bp, sp = Path(tmp) / "b.json", Path(tmp) / "s.json"
            append_briefs(bp, [b])
            sugs = suggest_elements(b)
            self.assertEqual(append_suggestions(sp, sugs), len(sugs))
            self.assertEqual(append_suggestions(sp, sugs), 0)
            pain = next(s for s in sugs if s.key == "psychology.pain")
            self.assertEqual(load_briefs(bp)[0].psychology.pain, "")  # 제안만으로는 바뀌지 않음
            resolve_suggestion(sp, bp, pain.suggestion_id, accept=True)
            self.assertIn("반복되는 불만", load_briefs(bp)[0].psychology.pain)
            with self.assertRaises(MarketingError):
                resolve_suggestion(sp, bp, pain.suggestion_id, accept=True)
            other = next(s for s in sugs if s.key == "sales.customer_problem")
            self.assertEqual(resolve_suggestion(sp, bp, other.suggestion_id, accept=False).status, "rejected")
            self.assertEqual(load_briefs(bp)[0].sales.customer_problem, "")
            self.assertEqual({s.status for s in load_suggestions(sp)} >= {"accepted", "rejected"}, True)


class ApprovalTests(unittest.TestCase):
    def ready(self):
        idea, demands = make_idea_and_demands()
        draft = brief_from_idea(idea, demands)
        return replace(approvable(), brief_id=draft.brief_id, evidence=draft.evidence, confidence=0.6, platform="blog")

    def test_blockers_and_valid_approve(self):
        self.assertTrue(approval_blockers(brief()))
        ready = self.ready()
        self.assertEqual(approval_blockers(ready), [])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "b.json"
            append_briefs(path, [ready])
            self.assertEqual(set_brief_status(path, ready.brief_id, "approved").status, "approved")

    def test_invalid_approve_rejected_per_condition(self):
        ready = self.ready()
        for name, broken in {
            "demand": replace(ready, evidence=()),
            "audience": replace(ready, target_audience=""),
            "core": set_element(ready, "storytelling.hook", ""),
        }.items():
            self.assertTrue(approval_blockers(broken), name)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "b.json"
            weak = replace(ready, evidence=())
            append_briefs(path, [weak])
            with self.assertRaises(MarketingError):
                set_brief_status(path, weak.brief_id, "approved")
            self.assertEqual(load_briefs(path)[0].status, "draft")

    def test_edit_resets_approved_and_rejected_is_terminal(self):
        ready = self.ready()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "b.json"
            append_briefs(path, [ready])
            set_brief_status(path, ready.brief_id, "approved")
            self.assertEqual(update_element(path, ready.brief_id, "design.visual_hook", "새 값").status, "draft")
            set_brief_status(path, ready.brief_id, "rejected")
            with self.assertRaises(MarketingError):
                update_element(path, ready.brief_id, "design.visual_hook", "다시")
            with self.assertRaises(MarketingError):
                set_brief_status(path, ready.brief_id, "approved")
            with self.assertRaises(MarketingError):
                set_brief_status(path, ready.brief_id, "draft")

    def test_bad_key(self):
        with self.assertRaises(MarketingError):
            set_element(brief(), "psychology.nope", "x")
        with self.assertRaises(MarketingError):
            set_element(brief(), "nodot", "x")


if __name__ == "__main__":
    unittest.main()
