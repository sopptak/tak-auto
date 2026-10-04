"""content_engine.followup 검증: 성과/발행 이력 -> 후속·재활용 후보."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from content_engine.followup import (
    INTENT_COMPARISON,
    INTENT_EXPERIENCE,
    INTENT_HOW_TO,
    KIND_AMPLIFY,
    KIND_REPURPOSE,
    FollowUpError,
    append_candidates,
    build_followup_candidates,
    classify_search_intent,
    load_candidates,
    set_candidate_status,
)
from content_engine.performance.models import PerformanceRecord
from tak_brain.models import KnowledgeRecord

NOW = "2026-10-04T00:00:00+00:00"


def _knowledge(kid, status="approved", url="https://example.com/a", title="소재"):
    return KnowledgeRecord(id=kid, title=title, source_url=url, knowledge_review_status=status)


def _perf(content_id, kid, views):
    return PerformanceRecord(
        content_id=content_id, knowledge_id=kid, platform="threads",
        published_at="2026-10-01T00:00:00+00:00", metric_collected_at="2026-10-02T00:00:00+00:00",
        metrics={"views": views},
    )


class IntentTests(unittest.TestCase):
    def test_classification(self):
        self.assertEqual(classify_search_intent("A와 B 비교"), INTENT_COMPARISON)
        self.assertEqual(classify_search_intent("앱 만드는 방법"), INTENT_HOW_TO)
        self.assertEqual(classify_search_intent("그냥 내 이야기"), INTENT_EXPERIENCE)


class BuildTests(unittest.TestCase):
    def test_unpublished_and_unapproved_are_skipped(self):
        records = [_knowledge("k1"), _knowledge("k2", status="pending")]
        logs = [{"knowledge_id": "k2", "platform": "threads"}]
        self.assertEqual(build_followup_candidates(records, logs, now=NOW), [])

    def test_repurpose_targets_missing_platforms_only(self):
        logs = [{"knowledge_id": "k1", "platform": "threads"}]
        archive = [{"knowledge_id": "k1", "platform": "shorts"}]
        result = build_followup_candidates([_knowledge("k1")], logs, archive, now=NOW)
        self.assertEqual([c.target_platform for c in result], ["blog"])
        self.assertEqual(result[0].kind, KIND_REPURPOSE)

    def test_naver_source_counts_as_blog(self):
        logs = [{"knowledge_id": "k1", "platform": "threads"}]
        record = _knowledge("k1", url="https://blog.naver.com/x/1")
        result = build_followup_candidates([record], logs, now=NOW)
        self.assertEqual([c.target_platform for c in result], ["shorts"])

    def test_high_performance_becomes_amplify_and_ranks_first(self):
        logs = [{"knowledge_id": "k1", "platform": "threads"}, {"knowledge_id": "k2", "platform": "threads"}]
        perf = {"c1": _perf("c1", "k1", 500), "c2": _perf("c2", "k2", 5), "c3": _perf("c3", "k2", 1)}
        result = build_followup_candidates([_knowledge("k1"), _knowledge("k2")], logs, latest_performance=perf, now=NOW)
        self.assertEqual(result[0].knowledge_id, "k1")
        self.assertEqual(result[0].kind, KIND_AMPLIFY)
        self.assertTrue(all(c.kind == KIND_REPURPOSE for c in result if c.knowledge_id == "k2"))

    def test_deterministic_ids(self):
        logs = [{"knowledge_id": "k1", "platform": "threads"}]
        first = build_followup_candidates([_knowledge("k1")], logs, now=NOW)
        second = build_followup_candidates([_knowledge("k1")], logs, now="2027-01-01T00:00:00+00:00")
        self.assertEqual([c.candidate_id for c in first], [c.candidate_id for c in second])


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "followups.json"
        logs = [{"knowledge_id": "k1", "platform": "threads"}]
        self.candidates = build_followup_candidates([_knowledge("k1")], logs, now=NOW)

    def test_append_is_idempotent_and_preserves_status(self):
        self.assertEqual(append_candidates(self.path, self.candidates), 2)
        cid = self.candidates[0].candidate_id
        set_candidate_status(self.path, cid, "accepted")
        self.assertEqual(append_candidates(self.path, self.candidates), 0)
        statuses = {c.candidate_id: c.status for c in load_candidates(self.path)}
        self.assertEqual(statuses[cid], "accepted")

    def test_invalid_status_and_unknown_id(self):
        append_candidates(self.path, self.candidates)
        with self.assertRaises(FollowUpError):
            set_candidate_status(self.path, self.candidates[0].candidate_id, "bogus")
        with self.assertRaises(FollowUpError):
            set_candidate_status(self.path, "nope", "accepted")

    def test_missing_file_is_empty_and_bad_structure_errors(self):
        self.assertEqual(load_candidates(self.path), [])
        self.path.write_text(json.dumps({"a": 1}), encoding="utf-8")
        with self.assertRaises(FollowUpError):
            load_candidates(self.path)


if __name__ == "__main__":
    unittest.main()
