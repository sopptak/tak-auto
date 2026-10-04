"""6-83 MarketingBrief <-> 승인 KNOWLEDGE 연결."""

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
import io
import json
from pathlib import Path
import tempfile
import unittest

from content_engine.marketing import (
    MarketingBrief, MarketingError, MediaGenerationRef, append_briefs, check_knowledge_link, check_knowledge_unlink,
    generate_candidates, generation_blockers, link_knowledge, load_briefs, unlink_knowledge,
)
from scripts import marketing_brief as cli
from tests.test_marketing_generation import approved_brief, knowledge

RECORDS = [knowledge("k-approved"), knowledge("k-approved-2"), knowledge("k-pending", status="pending"),
           knowledge("k-rejected", status="rejected")]


class CheckTests(unittest.TestCase):
    def test_link_check_fields(self):
        brief = approved_brief("blog", knowledge_ids=("k-approved",))
        ok = check_knowledge_link(brief, "k-approved-2", RECORDS)
        self.assertTrue(ok.exists and ok.approved and ok.can_link)
        self.assertEqual(ok.knowledge_status, "approved")
        self.assertFalse(ok.already_linked)
        dup = check_knowledge_link(brief, "k-approved", RECORDS)
        self.assertTrue(dup.already_linked)
        self.assertFalse(dup.can_link)
        self.assertEqual(dup.blockers, ())
        for kid, status in (("k-pending", "pending"), ("k-rejected", "rejected")):
            check = check_knowledge_link(brief, kid, RECORDS)
            self.assertEqual(check.knowledge_status, status)
            self.assertFalse(check.approved or check.can_link)
            self.assertIn("approved KNOWLEDGE만", check.blockers[0])
        missing = check_knowledge_link(brief, "k-missing", RECORDS)
        self.assertFalse(missing.exists)
        self.assertIsNone(missing.knowledge_status)
        rejected_brief = check_knowledge_link(replace(brief, status="rejected"), "k-approved-2", RECORDS)
        self.assertIn("rejected 브리프", rejected_brief.blockers[0])

    def test_unlink_check_last_knowledge_warning(self):
        brief = approved_brief("blog", knowledge_ids=("k-approved",))
        check = check_knowledge_unlink(brief, "k-approved")
        self.assertTrue(check.can_unlink)
        self.assertEqual(check.remaining, ())
        self.assertTrue(any("마지막 KNOWLEDGE" in warning for warning in check.warnings))
        self.assertFalse(check_knowledge_unlink(brief, "k-other").can_unlink)
        self.assertFalse(check_knowledge_unlink(replace(brief, status="rejected"), "k-approved").can_unlink)

    def test_gate_blocks_brief_without_knowledge(self):
        self.assertEqual(generation_blockers(approved_brief("blog")), [])
        brief = approved_brief("blog", knowledge_ids=())
        self.assertTrue(any("연결된 KNOWLEDGE 없음" in item for item in generation_blockers(brief)))
        self.assertFalse(generate_candidates(brief, [knowledge()]).candidates)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "tak_marketing_briefs.json"
        self.brief = replace(approved_brief("youtube", knowledge_ids=("k-approved",)), content_ids=("content-a",),
                             media_generations=(MediaGenerationRef("content-a", "gen-1"),))
        append_briefs(self.path, [self.brief])

    def stored(self):
        return load_briefs(self.path)[0]

    def test_link_approved_keeps_status_and_lineage(self):
        linked = link_knowledge(self.path, self.brief.brief_id, "k-approved-2", RECORDS)
        self.assertEqual(linked.knowledge_ids, ("k-approved", "k-approved-2"))
        self.assertEqual(self.stored(), replace(self.brief, knowledge_ids=("k-approved", "k-approved-2")))

    def test_link_does_not_approve_draft_brief(self):
        path = Path(self.tmp.name) / "draft.json"
        draft = approved_brief("blog", status="draft", knowledge_ids=())
        append_briefs(path, [draft])
        self.assertEqual(link_knowledge(path, draft.brief_id, "k-approved", RECORDS).status, "draft")

    def test_link_blocked_cases_do_not_write(self):
        before = self.path.read_bytes()
        for kid in ("k-pending", "k-rejected", "k-missing"):
            with self.assertRaises(MarketingError):
                link_knowledge(self.path, self.brief.brief_id, kid, RECORDS)
        self.assertEqual(self.path.read_bytes(), before)

    def test_link_duplicate_is_noop(self):
        self.assertEqual(link_knowledge(self.path, self.brief.brief_id, "k-approved", RECORDS).knowledge_ids,
                         ("k-approved",))

    def test_unlink_only_changes_knowledge_ids(self):
        link_knowledge(self.path, self.brief.brief_id, "k-approved-2", RECORDS)
        unlinked = unlink_knowledge(self.path, self.brief.brief_id, "k-approved")
        self.assertEqual(unlinked, replace(self.brief, knowledge_ids=("k-approved-2",)))
        last = unlink_knowledge(self.path, self.brief.brief_id, "k-approved-2")
        self.assertEqual(last.knowledge_ids, ())
        self.assertEqual(last.status, "approved")
        self.assertEqual(last.content_ids, ("content-a",))
        self.assertEqual(last.media_generations, (MediaGenerationRef("content-a", "gen-1"),))
        self.assertTrue(any("연결된 KNOWLEDGE 없음" in item for item in generation_blockers(last)))
        with self.assertRaises(MarketingError):
            unlink_knowledge(self.path, self.brief.brief_id, "k-approved-2")

    def test_rejected_brief_blocked(self):
        path = Path(self.tmp.name) / "rejected.json"
        rejected = approved_brief("blog", status="rejected", knowledge_ids=("k-approved",))
        append_briefs(path, [rejected])
        before = path.read_bytes()
        with self.assertRaises(MarketingError):
            link_knowledge(path, rejected.brief_id, "k-approved-2", RECORDS)
        with self.assertRaises(MarketingError):
            unlink_knowledge(path, rejected.brief_id, "k-approved")
        self.assertEqual(path.read_bytes(), before)

    def test_legacy_json_without_knowledge_ids(self):
        path = Path(self.tmp.name) / "legacy.json"
        row = approved_brief("blog", knowledge_ids=()).to_dict()
        for key in ("knowledge_ids", "media_generations", "content_ids"):
            row.pop(key)
        path.write_text(json.dumps([row], ensure_ascii=False), encoding="utf-8")
        self.assertEqual(load_briefs(path)[0].knowledge_ids, ())
        linked = link_knowledge(path, row["brief_id"], "k-approved", RECORDS)
        self.assertEqual(linked.knowledge_ids, ("k-approved",))
        saved = json.loads(path.read_text(encoding="utf-8"))[0]
        self.assertEqual(saved["knowledge_ids"], ["k-approved"])
        self.assertEqual(MarketingBrief.from_dict(saved), linked)


if __name__ == "__main__":
    unittest.main()
