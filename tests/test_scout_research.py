"""Tests for TAK SCOUT research orchestration; no live API calls."""
from pathlib import Path
import json
import tempfile
import unittest
from tak_scout.models import ScoutCandidate
from tak_scout.perplexity_research import ResearchResult
from tak_scout.research import research_candidate, research_candidates, save_research_records, render_research_markdown

def make_candidate(sid="scout-1"):
    return ScoutCandidate(sid, "경매 제도 변경", "RSS 요약", "https://example.test/a",
                          "2026-11-15", "테스트 출처", "경매")

class FakeProvider:
    def __init__(self, fail=False): self.fail, self.calls = fail, 0
    def search(self, query, **kwargs):
        self.calls += 1
        if self.fail: raise RuntimeError("do not persist secret")
        return ResearchResult(query, "확인된 사실과 해석", ("https://example.test/source",), "sonar-pro")

class ResearchTests(unittest.TestCase):
    def test_success_keeps_scout_lineage_and_citations(self):
        r = research_candidate(make_candidate(), FakeProvider())
        self.assertEqual(r.scout_id, "scout-1")
        self.assertEqual(r.status, "completed")
        self.assertEqual(r.citations, ("https://example.test/source",))
    def test_failure_does_not_leak_exception_message(self):
        r = research_candidate(make_candidate(), FakeProvider(True))
        self.assertEqual(r.status, "failed")
        self.assertEqual(r.error, "RuntimeError")
    def test_batch_continues_after_failure(self):
        class P:
            def __init__(self): self.n=0
            def search(self, q, **kw):
                self.n += 1
                if self.n == 1: raise RuntimeError()
                return ResearchResult(q, "ok", (), "sonar-pro")
        rows = research_candidates([make_candidate("a"), make_candidate("b")], P())
        self.assertEqual([r.status for r in rows], ["failed", "completed"])
    def test_save_and_render(self):
        r = research_candidate(make_candidate(), FakeProvider())
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "research.json"
            save_research_records([r], p)
            data = json.loads(p.read_text(encoding="utf-8"))
        self.assertEqual(data["records"][0]["scout_id"], "scout-1")
        self.assertIn("https://example.test/source", render_research_markdown([r]))

if __name__ == "__main__": unittest.main()
