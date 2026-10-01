"""24h/72h Threads target selection and full lineage checks."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import unittest

from content_engine.media_archive import MediaArchiveRecord
from content_engine.performance.models import PerformanceRecord
from content_engine.performance.schedule import select_due_threads_targets
from content_engine.publish_history import PublishRecord
from content_engine.threads_review import ThreadsPendingDraft


PUBLISHED_AT = "2026-10-01T07:23:23.502999+00:00"
CONTENT_ID = "content-p0"
KNOWLEDGE_ID = "knowledge-p0"
GENERATION_ID = "generation-p0"
POST_ID = "18085925933320004"


def _production(**overrides) -> MediaArchiveRecord:
    values = {
        "content_id": CONTENT_ID,
        "knowledge_id": KNOWLEDGE_ID,
        "platform": "threads",
        "generation_status": "valid",
        "original_title": "Original title",
        "original_body": "Original body",
        "rewritten_title": "Published title",
        "rewritten_body": "Published body",
        "source_url": "https://example.test/source",
        "evidence": (),
        "evidence_unit_ids": (),
        "created_at": PUBLISHED_AT,
        "review_status": "approved",
        "generation_id": GENERATION_ID,
    }
    values.update(overrides)
    return MediaArchiveRecord(**values)


def _pending(**overrides) -> ThreadsPendingDraft:
    values = {
        "content_id": CONTENT_ID,
        "knowledge_id": KNOWLEDGE_ID,
        "source_url": "https://example.test/source",
        "evidence_unit_ids": (),
        "article_type": None,
        "knowledge_type": "의견",
        "original_title": "Original title",
        "original_body": "Original body",
        "ai_rewritten_title": "Published title",
        "ai_rewritten_body": "Published body",
        "status": "published",
        "created_at": PUBLISHED_AT,
        "published_at": PUBLISHED_AT,
        "threads_post_id": POST_ID,
    }
    values.update(overrides)
    return ThreadsPendingDraft(**values)


def _history(**overrides) -> dict[str, str]:
    values = PublishRecord(
        content_id=CONTENT_ID,
        published_at=PUBLISHED_AT,
        threads_post_id=POST_ID,
        knowledge_id=KNOWLEDGE_ID,
        platform="threads",
        source_url="https://example.test/source",
    ).to_dict()
    values.update(overrides)
    return values


class SelectDueThreadsTargetsTests(unittest.TestCase):
    def _select(self, *, hours_after=0, history=None, production=None, pending=None, records=()):
        now = datetime.fromisoformat(PUBLISHED_AT).replace(tzinfo=timezone.utc)
        now += timedelta(hours=hours_after)
        return select_due_threads_targets(
            [history or _history()],
            [production or _production()],
            [pending or _pending()],
            list(records),
            now=now,
        )

    def test_before_24_hours_is_not_due(self):
        self.assertEqual(self._select(hours_after=23.99), ())

    def test_exactly_24_hours_selects_24h(self):
        targets = self._select(hours_after=24)
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0].measurement_window, "24h")
        self.assertEqual(targets[0].generation_id, GENERATION_ID)
        self.assertEqual(targets[0].external_post_id, POST_ID)

    def test_at_72_hours_selects_72h_not_a_late_24h(self):
        targets = self._select(hours_after=72)
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0].measurement_window, "72h")

    def test_existing_24h_snapshot_advances_to_72h_when_due(self):
        snapshot = PerformanceRecord(
            content_id=CONTENT_ID,
            knowledge_id=KNOWLEDGE_ID,
            platform="threads",
            published_at=PUBLISHED_AT,
            metric_collected_at="2026-10-02T07:23:23+00:00",
            metrics={"views": 10},
            source="threads_api",
            external_id=POST_ID,
            generation_id=GENERATION_ID,
            measurement_window="24h",
        )
        self.assertEqual(self._select(hours_after=48, records=(snapshot,)), ())
        targets = self._select(hours_after=72, records=(snapshot,))
        self.assertEqual([target.measurement_window for target in targets], ["72h"])

    def test_same_window_is_not_selected_twice(self):
        snapshot = PerformanceRecord(
            content_id=CONTENT_ID,
            knowledge_id=KNOWLEDGE_ID,
            platform="threads",
            published_at=PUBLISHED_AT,
            metric_collected_at="2026-10-02T08:00:00+00:00",
            metrics={"views": 10},
            source="threads_api",
            external_id=POST_ID,
            generation_id=GENERATION_ID,
            measurement_window="24h",
        )
        self.assertEqual(self._select(hours_after=30, records=(snapshot,)), ())

    def test_knowledge_id_mismatch_is_excluded(self):
        targets = self._select(history=_history(knowledge_id="wrong-knowledge"))
        self.assertEqual(targets, ())

    def test_pending_post_id_mismatch_is_excluded(self):
        targets = self._select(pending=_pending(threads_post_id="test-post"))
        self.assertEqual(targets, ())

    def test_non_published_legacy_or_test_pending_is_excluded(self):
        self.assertEqual(self._select(pending=_pending(status="approved")), ())

    def test_legacy_history_without_linked_production_is_excluded(self):
        targets = select_due_threads_targets(
            [_history()],
            [],
            [_pending()],
            [],
            now=datetime.fromisoformat(PUBLISHED_AT).replace(tzinfo=timezone.utc)
            + timedelta(hours=25),
        )
        self.assertEqual(targets, ())

    def test_content_id_without_matching_production_lineage_is_excluded(self):
        targets = select_due_threads_targets(
            [_history(content_id="content-test-orphan")],
            [_production()],
            [_pending()],
            [],
            now=datetime.fromisoformat(PUBLISHED_AT).replace(tzinfo=timezone.utc)
            + timedelta(hours=25),
        )
        self.assertEqual(targets, ())

    def test_superseded_production_is_excluded(self):
        superseded = replace(_production(), review_status="superseded", superseded_by="content-new")
        self.assertEqual(self._select(production=superseded), ())

    def test_missing_generation_id_is_excluded(self):
        self.assertEqual(self._select(production=_production(generation_id=None)), ())

    def test_duplicate_publish_history_is_ambiguous_and_excluded(self):
        targets = select_due_threads_targets(
            [_history(), _history(threads_post_id="second-post")],
            [_production()],
            [_pending()],
            [],
            now=datetime.fromisoformat(PUBLISHED_AT).replace(tzinfo=timezone.utc),
        )
        self.assertEqual(targets, ())