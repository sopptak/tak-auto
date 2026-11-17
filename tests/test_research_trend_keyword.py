import unittest
from unittest.mock import patch
from pathlib import Path
import tempfile
import json

from tak_scout.models import ScoutCandidate
from tak_scout.collector import save_daily_pack_json
from tak_scout.research import ResearchRecord
from scripts import research_trend_keyword


class FakeProvider:
    def search(self, query, **kwargs):
        from tak_scout.perplexity_research import ResearchResult
        return ResearchResult(query, "검토용 조사 결과", ("https://example.com/source",), "fake")


class TrendKeywordResearchTests(unittest.TestCase):
    def test_selects_only_evidence_candidates_and_persists_research(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = ScoutCandidate("s1", "AI 산업 변화", "AI 시장 변화", "https://example.com/a",
                                        "2026-11-17", "Example", "tech")
            unrelated = ScoutCandidate("s2", "여행 정보", "관광", "https://example.com/b",
                                       "2026-11-17", "Other", "general")
            pack = root / "candidates.json"
            save_daily_pack_json([candidate, unrelated], pack)
            report = root / "report.json"
            report.write_text(json.dumps({"content_opportunities": [
                {"keyword": "ai", "candidate_ids": ["s1"]}
            ]}), encoding="utf-8")
            output, markdown = root / "research.json", root / "research.md"
            with patch.object(research_trend_keyword.PerplexityResearchProvider,
                              "from_environment", return_value=FakeProvider()):
                status = research_trend_keyword.main([
                    "--keyword", "AI", "--report", str(report), "--candidates", str(pack),
                    "--output", str(output), "--markdown", str(markdown),
                ])
            self.assertEqual(status, 0)
            saved = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(saved["record_count"], 1)
            self.assertEqual(saved["records"][0]["scout_id"], "s1")
            self.assertIn("검토용 조사 결과", markdown.read_text(encoding="utf-8"))

    def test_rejects_keyword_without_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pack = root / "candidates.json"
            save_daily_pack_json([], pack)
            report = root / "report.json"
            report.write_text(json.dumps({"content_opportunities": []}), encoding="utf-8")
            with self.assertRaises(SystemExit):
                research_trend_keyword.main([
                    "--keyword", "없는 키워드", "--report", str(report),
                    "--candidates", str(pack),
                ])


if __name__ == "__main__":
    unittest.main()
