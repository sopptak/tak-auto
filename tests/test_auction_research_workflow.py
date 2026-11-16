"""Tests for the one-command auction research workflow; no live API calls."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import importlib.util

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_auction_research_workflow.py"
SPEC = importlib.util.spec_from_file_location("run_auction_research_workflow", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class AuctionResearchWorkflowTests(TestCase):
    def test_preview_does_not_construct_provider_or_call_research(self):
        candidate = type("Candidate", (), {"scout_id": "s-1", "title": "경매 후보"})()
        with patch.object(MODULE, "load_daily_pack", return_value=[candidate]), \
             patch.object(MODULE.PerplexityResearchProvider, "from_environment") as provider, \
             patch.object(MODULE, "research_candidates") as research:
            result = MODULE.main(["--input", "ignored.json", "--limit", "1"])
        self.assertEqual(result, 0)
        provider.assert_not_called()
        research.assert_not_called()

    def test_execute_saves_research_and_hands_off_only_completed_records(self):
        candidate = type("Candidate", (), {"scout_id": "s-1", "title": "경매 후보"})()
        completed = type("Record", (), {
            "scout_id": "s-1", "status": "completed", "error": "",
        })()
        failed = type("Record", (), {
            "scout_id": "s-2", "status": "failed", "error": "RuntimeError",
        })()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(MODULE, "load_daily_pack", return_value=[candidate]), \
                 patch.object(MODULE.PerplexityResearchProvider, "from_environment", return_value=object()), \
                 patch.object(MODULE, "research_candidates", return_value=[completed, failed]), \
                 patch.object(MODULE, "save_research_records") as save_json, \
                 patch.object(MODULE, "save_research_markdown") as save_md, \
                 patch.object(MODULE, "upsert_research_knowledge", return_value=(object(), "created")) as handoff:
                result = MODULE.main([
                    "--input", "ignored.json",
                    "--research-output", str(root / "research.json"),
                    "--markdown-output", str(root / "research.md"),
                    "--knowledge-output", str(root / "knowledge.json"),
                    "--execute",
                ])
        self.assertEqual(result, 1)
        save_json.assert_called_once()
        save_md.assert_called_once()
        handoff.assert_called_once()
        self.assertEqual(handoff.call_args.args[0], completed)


if __name__ == "__main__":
    import unittest
    unittest.main()
