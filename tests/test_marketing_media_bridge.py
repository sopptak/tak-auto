"""6-82 Marketing 후보 -> 기존 MEDIA Generation Pool 브리지."""

from contextlib import redirect_stderr, redirect_stdout
import ast
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from content_engine.marketing import (
    MarketingError, append_briefs, bridge_to_generation_pool, candidate_to_batch_item, generate_candidates,
    load_candidates, mark_bridged, plan_bridge, pool_path_for, save_candidates,
)
from content_engine.marketing import media_bridge as bridge_module
from content_engine.media_archive import load_archive
from content_engine.rewrite import MockRewriteProvider
import scripts.audit_data_state as audit_module
from scripts import marketing_brief as cli
from scripts.run_scout_dashboard import discover_generation_pool_paths, handle_generation_review_submission
from tests.test_marketing_generation import approved_brief, knowledge


class BridgeFixture(unittest.TestCase):
    platform = "youtube"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name)
        self.briefs = self.data / "tak_marketing_briefs.json"
        self.contents = self.data / "tak_marketing_contents.json"
        self.brief = approved_brief(self.platform)
        append_briefs(self.briefs, [self.brief])
        (self.data / "tak_brain_knowledge.json").write_text(
            json.dumps([knowledge().to_dict()], ensure_ascii=False), encoding="utf-8")

    def generate(self, provider=MockRewriteProvider()):
        result = generate_candidates(self.brief, [knowledge()], provider=provider)
        save_candidates(self.contents, self.briefs, result)
        return load_candidates(self.contents, self.brief.brief_id)

    def bridge(self, candidates, generation_id="gen-test-1"):
        pool = pool_path_for(self.data, self.brief.brief_id)
        result = bridge_to_generation_pool(self.brief, candidates, pool, generation_id=generation_id)
        mark_bridged(self.contents, result)
        return result


class MappingTests(BridgeFixture):
    def test_youtube_candidate_becomes_shorts_batch_item_with_same_content_id(self):
        for candidate in self.generate():
            item = candidate_to_batch_item(candidate)
            self.assertEqual(item.platform, "shorts")
            self.assertEqual(item.status, "valid")
            self.assertEqual(item.original_body, candidate["original_body"])
            self.assertEqual(item.evidence_unit_ids, tuple(candidate["evidence_unit_ids"]))

    def test_status_mapping(self):
        candidate = self.generate()[0]
        for rewrite, generation in (("rewritten", "valid"), ("rejected", "rejected"), ("error", "error")):
            self.assertEqual(candidate_to_batch_item({**candidate, "rewrite_status": rewrite}).status, generation)

    def test_not_requested_is_never_valid(self):
        candidates = self.generate(provider=None)
        self.assertTrue(all(c["rewrite_status"] == "not_requested" for c in candidates))
        with self.assertRaises(MarketingError):
            candidate_to_batch_item(candidates[0])
        plan = plan_bridge(self.brief, candidates)
        self.assertEqual(plan.items, ())
        self.assertTrue(all("not_requested" in reason for reason in plan.skipped))
        result = self.bridge(candidates)
        self.assertEqual(result.refs, ())
        self.assertFalse(pool_path_for(self.data, self.brief.brief_id).exists())

    def test_tampered_content_id_rejected(self):
        candidate = {**self.generate()[0], "content_id": "content-0000000000000000"}
        with self.assertRaises(MarketingError):
            candidate_to_batch_item(candidate)


class PoolTests(BridgeFixture):
    def test_pool_written_unreviewed_and_discovered(self):
        candidates = self.generate()
        result = self.bridge(candidates)
        pool = pool_path_for(self.data, self.brief.brief_id)
        self.assertEqual(result.pool_path, pool)
        self.assertEqual(bridge_module.GENERATION_POOL_GLOB, audit_module.GENERATION_POOL_GLOB)
        self.assertIn(pool, discover_generation_pool_paths(self.data))
        records = load_archive(pool)
        self.assertEqual(len(records), 3)
        for record in records:
            self.assertEqual(record.review_status, "unreviewed")
            self.assertEqual(record.generation_status, "valid")
            self.assertEqual(record.platform, "shorts")
            self.assertEqual(record.generation_id, "gen-test-1")
        self.assertEqual({r.content_id for r in records}, {c["content_id"] for c in candidates})
        self.assertEqual(set(result.refs), {(c["content_id"], "gen-test-1") for c in candidates})

    def test_default_generation_id_uses_existing_format(self):
        result = self.bridge(self.generate(), generation_id=None)
        self.assertTrue(result.generation_id.startswith("gen-"))

    def test_rebridge_is_idempotent_and_keeps_human_review(self):
        candidates = self.generate()
        self.bridge(candidates)
        pool = pool_path_for(self.data, self.brief.brief_id)
        first = load_archive(pool)[0]
        approved, error = handle_generation_review_submission((pool,), first.content_id, first.generation_id, "approved")
        self.assertIsNone(error)
        self.assertEqual(approved.review_status, "approved")

        again = self.bridge(load_candidates(self.contents, self.brief.brief_id), generation_id="gen-test-2")
        self.assertEqual(again.refs, ())
        self.assertTrue(all("이미 bridge됨" in reason for reason in again.skipped))
        records = load_archive(pool)
        self.assertEqual(len(records), 3)
        self.assertEqual({r.generation_id for r in records}, {"gen-test-1"})
        self.assertEqual(next(r for r in records if r.content_id == first.content_id).review_status, "approved")
        rows = json.loads(self.contents.read_text(encoding="utf-8"))
        self.assertTrue(all(row["generation_id"] == "gen-test-1" and row["media_pool"] == pool.name for row in rows))
        self.assertTrue(all(row["status"] == "review_required" for row in rows))

    def test_blocked_brief_not_bridged(self):
        candidates = self.generate()
        for status in ("draft", "rejected", "suggested"):
            with self.assertRaises(MarketingError):
                bridge_to_generation_pool(approved_brief(self.platform, status=status), candidates,
                                          pool_path_for(self.data, self.brief.brief_id))
        self.assertFalse(pool_path_for(self.data, self.brief.brief_id).exists())

    def test_pool_name_rule_enforced(self):
        with self.assertRaises(MarketingError):
            bridge_to_generation_pool(self.brief, self.generate(), self.data / "tak_media_archive.json")
        self.assertFalse((self.data / "tak_media_archive.json").exists())

    def test_rejected_rewrite_goes_to_pool_as_rejected(self):
        from dataclasses import replace
        from content_engine.generator import generate_content_bundle
        bad = replace(generate_content_bundle(knowledge()).shorts[0], body="매출 999 증가.")
        self.generate(provider=MockRewriteProvider(bad))
        self.bridge(load_candidates(self.contents))
        statuses = {r.generation_status for r in load_archive(pool_path_for(self.data, self.brief.brief_id))}
        self.assertEqual(statuses, {"rejected"})


class SafetyTests(BridgeFixture):
    def test_bridge_never_approves_promotes_or_touches_production(self):
        production = self.data / "tak_media_archive.json"
        self.bridge(self.generate())
        self.assertFalse(production.exists())
        records = load_archive(pool_path_for(self.data, self.brief.brief_id))
        self.assertTrue(all(r.review_status == "unreviewed" for r in records))

    def test_bridge_module_imports_only_pool_apis(self):
        tree = ast.parse(Path(bridge_module.__file__).read_text(encoding="utf-8"))
        imported = {
            (node.module, alias.name) for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        media = {(module, name) for module, name in imported if module and module.startswith("content_engine.")
                 and not module.startswith("content_engine.marketing")}
        self.assertEqual(media, {
            ("content_engine.media_archive", "archive_generation_report"),
            ("content_engine.media_archive", "new_generation_id"),
            ("content_engine.pipeline", "MediaBatchItem"),
            ("content_engine.pipeline", "MediaBatchReport"),
            ("content_engine.publish_history", "compute_content_id"),
        })
        names = {name for _, name in imported} | {
            node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        for forbidden in ("upsert_archive", "save_archive", "promote", "publish", "setattr"):
            self.assertFalse([name for name in names if forbidden in name.lower()], forbidden)


class CliTests(BridgeFixture):
    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(["--data-dir", str(self.data), *args])
        return code, out.getvalue(), err.getvalue()

    def test_bridge_preview_then_write(self):
        self.assertEqual(self.run_cli("--write", "generate", self.brief.brief_id, "--rewrite", "mock")[0], 0)
        pool = pool_path_for(self.data, self.brief.brief_id)
        code, out, _ = self.run_cli("bridge", self.brief.brief_id)
        self.assertEqual(code, 0)
        self.assertIn("bridge 대상 3건", out)
        self.assertIn("미리보기", out)
        self.assertFalse(pool.exists())

        code, out, _ = self.run_cli("--write", "bridge", self.brief.brief_id)
        self.assertEqual(code, 0)
        self.assertEqual(len(load_archive(pool)), 3)
        code, out, _ = self.run_cli("--write", "bridge", self.brief.brief_id)
        self.assertIn("이미 bridge됨", out)
        self.assertEqual(len(load_archive(pool)), 3)

    def test_bridge_cli_skips_not_requested(self):
        self.run_cli("--write", "generate", self.brief.brief_id)
        code, out, _ = self.run_cli("--write", "bridge", self.brief.brief_id)
        self.assertEqual(code, 0)
        self.assertIn("bridge 대상 0건", out)
        self.assertFalse(pool_path_for(self.data, self.brief.brief_id).exists())

    def test_bridge_cli_no_network(self):
        self.run_cli("--write", "generate", self.brief.brief_id, "--rewrite", "mock")
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("network")) as urlopen:
            self.assertEqual(self.run_cli("--write", "bridge", self.brief.brief_id)[0], 0)
        urlopen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
