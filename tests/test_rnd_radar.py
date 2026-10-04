import json
from pathlib import Path
import tempfile
import unittest

from tak_rnd import (
    Idea,
    RndStoreError,
    add_idea,
    add_rnd_item,
    canonicalize_url,
    import_rnd_items,
    load_ideas,
    load_rnd_items,
    priority_ideas,
    promote_rnd_to_idea,
    set_rnd_canonical_id,
    set_idea_status,
    set_rnd_status,
    validation_ideas,
)


class RndRadarTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        self.rnd_path = root / "tak_rnd_items.json"
        self.idea_path = root / "tak_idea_vault.json"

    def test_add_and_reload_aside_shaped_rnd_item(self):
        imported, duplicate_count = import_rnd_items(
            {
                "source": "threads",
                "url": "https://threads.net/@example/post/abc",
                "author": "@example",
                "captured_at": "2026-10-04T00:00:00+00:00",
                "title": "Aside 브라우저 에이전트",
                "text": "브라우저 작업을 에이전트가 보조한다.",
                "media": ["https://example.test/image.png"],
                "tags": ["Aside", "browser"],
            },
            self.rnd_path,
        )
        repeated, repeated_duplicate_count = import_rnd_items(
            {
                "source": "threads",
                "url": "https://threads.net/@example/post/abc?utm_source=share",
                "author": "@example",
                "captured_at": "2026-10-04T00:00:00+00:00",
                "title": "Aside 브라우저 에이전트",
                "text": "브라우저 작업을 에이전트가 보조한다.",
            },
            self.rnd_path,
        )

        saved = load_rnd_items(self.rnd_path)[0]
        self.assertEqual(duplicate_count, 0)
        self.assertEqual(repeated, [])
        self.assertEqual(repeated_duplicate_count, 1)
        self.assertEqual(len(load_rnd_items(self.rnd_path)), 1)
        self.assertTrue(imported[0].id.startswith("rnd-"))
        self.assertEqual(saved.source_author, "@example")
        self.assertEqual(saved.summary, "브라우저 작업을 에이전트가 보조한다.")
        self.assertEqual(saved.technologies, ("Aside", "browser"))
        self.assertEqual(saved.media, ("https://example.test/image.png",))
        self.assertEqual(saved.canonical_url, "https://threads.net/@example/post/abc")

    def test_url_validation_and_canonical_duplicates_keep_both_items(self):
        first = add_rnd_item(
            {"source": "web", "url": "https://EXAMPLE.test/tool/?utm_campaign=x", "title": "Browser tool"},
            self.rnd_path,
        )
        second = add_rnd_item(
            {"source": "github", "url": "https://example.test/tool#overview", "title": "Different name"},
            self.rnd_path,
        )

        self.assertEqual(second.duplicate_candidate_ids, (first.id,))
        self.assertEqual(len(load_rnd_items(self.rnd_path)), 2)
        self.assertEqual(canonicalize_url("https://example.test/a/?fbclid=x#part"), "https://example.test/a")
        with self.assertRaises(ValueError):
            add_rnd_item({"url": "javascript:alert(1)", "title": "Unsafe"}, self.rnd_path)

    def test_same_source_item_and_title_are_duplicate_candidates_not_deletions(self):
        first = add_rnd_item(
            {"source": "threads", "source_item_id": "post-1", "title": "Same title"}, self.rnd_path
        )
        second = add_rnd_item(
            {"source": "threads", "source_item_id": "post-1", "title": "Same title"}, self.rnd_path
        )

        self.assertEqual(second.duplicate_candidate_ids, (first.id,))
        self.assertEqual(len(load_rnd_items(self.rnd_path)), 2)

    def test_model_validation_and_old_optional_fields(self):
        record = {
            "id": "rnd-legacy",
            "captured_at": "2026-10-04T00:00:00+00:00",
            "source": "manual",
            "source_url": "",
            "title": "Legacy-compatible item",
            "summary": "Short note",
        }
        self.rnd_path.write_text(json.dumps([record]), encoding="utf-8")
        self.assertEqual(load_rnd_items(self.rnd_path)[0].status, "captured")
        with self.assertRaises(ValueError):
            add_rnd_item({"title": "Bad score", "relevance_score": 6}, self.rnd_path)
        with self.assertRaises(ValueError):
            add_rnd_item({"title": "Missing scheme URL", "url": "example.test"}, self.rnd_path)
        with self.assertRaises(ValueError):
            add_rnd_item({"title": "Bad timestamp", "captured_at": "yesterday"}, self.rnd_path)

    def test_human_can_link_duplicate_to_canonical_without_deleting_it(self):
        canonical = add_rnd_item({"title": "Canonical"}, self.rnd_path)
        duplicate = add_rnd_item({"title": "Canonical"}, self.rnd_path)
        linked = set_rnd_canonical_id(duplicate.id, canonical.id, self.rnd_path)
        self.assertEqual(linked.canonical_id, canonical.id)
        self.assertEqual(len(load_rnd_items(self.rnd_path)), 2)

    def test_import_is_all_or_nothing_for_invalid_batch(self):
        before = b"[]\n"
        self.rnd_path.write_bytes(before)
        with self.assertRaises(ValueError):
            import_rnd_items(
                [{"title": "Valid"}, {"title": "Invalid URL", "url": "file:///tmp/test"}],
                self.rnd_path,
            )
        self.assertEqual(self.rnd_path.read_bytes(), before)

    def test_malformed_store_is_reported_without_overwrite(self):
        self.rnd_path.write_text("{bad", encoding="utf-8")
        with self.assertRaises(RndStoreError):
            load_rnd_items(self.rnd_path)

    def test_rnd_status_updates_persist(self):
        item = add_rnd_item({"title": "Status update"}, self.rnd_path)
        updated = set_rnd_status(item.id, "reviewing", self.rnd_path)
        self.assertEqual(updated.status, "reviewing")
        self.assertEqual(load_rnd_items(self.rnd_path)[0].status, "reviewing")
        with self.assertRaises(RndStoreError):
            set_rnd_status(item.id, "published", self.rnd_path)


class IdeaVaultTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        self.rnd_path = root / "tak_rnd_items.json"
        self.idea_path = root / "tak_idea_vault.json"

    def _idea(self, title, **overrides):
        return {
            "title": title,
            "description": "브라우저 실행 레이어 연계",
            "why_important": "반복 작업 시간을 줄인다.",
            "application_areas": ["browser automation"],
            "expected_impact": "수동 탐색 시간을 줄인다.",
            **overrides,
        }

    def test_create_idea_and_priority_sorting(self):
        unranked = add_idea(self._idea("Unranked"), self.idea_path)
        low = add_idea(
            self._idea(
                "Lower priority", strategic_fit_score=2, expected_impact_score=2,
                novelty_score=2, implementation_difficulty="high", estimated_effort_hours=8,
            ),
            self.idea_path,
        )
        high = add_idea(
            self._idea(
                "Higher priority", strategic_fit_score=5, expected_impact_score=5,
                novelty_score=4, implementation_difficulty="low", estimated_effort_hours=2,
                related_content_ids=["content-123"],
            ),
            self.idea_path,
        )

        self.assertEqual(high.priority_score, 23)
        self.assertIsNone(unranked.priority_score)
        self.assertEqual([idea.id for idea in priority_ideas(self.idea_path)], [high.id, low.id])
        self.assertEqual(load_ideas(self.idea_path)[2].related_content_ids, ("content-123",))
        set_idea_status(high.id, "rejected", self.idea_path)
        self.assertEqual([idea.id for idea in priority_ideas(self.idea_path)], [low.id])

    def test_promote_rnd_to_idea_keeps_explicit_lineage(self):
        item = add_rnd_item({"source": "web", "title": "Aside browser agent"}, self.rnd_path)
        idea = promote_rnd_to_idea(
            item.id,
            self._idea("Connect Aside to TAK AUTO", source_rnd_ids="rnd-related"),
            self.rnd_path,
            self.idea_path,
        )

        self.assertEqual(idea.source_rnd_ids, ("rnd-related", item.id))
        self.assertEqual(load_rnd_items(self.rnd_path)[0].status, "promoted")
        self.assertEqual(len(load_ideas(self.idea_path)), 1)

    def test_idea_status_and_validation_queue_persist(self):
        idea = add_idea(self._idea("Needs validation"), self.idea_path)
        implemented = set_idea_status(idea.id, "implemented", self.idea_path)
        self.assertTrue(implemented.implemented_at)
        self.assertEqual(load_ideas(self.idea_path)[0].status, "implemented")
        self.assertEqual([item.id for item in validation_ideas(self.idea_path)], [idea.id])
        set_idea_status(idea.id, "parked", self.idea_path)
        self.assertEqual(validation_ideas(self.idea_path), [])

        next_idea = add_idea(self._idea("Validation completed"), self.idea_path)
        set_idea_status(next_idea.id, "validated", self.idea_path)
        self.assertNotIn(next_idea.id, [item.id for item in validation_ideas(self.idea_path)])

    def test_idea_validation_and_duplicate_candidate(self):
        first = add_idea(self._idea("Shared R&D", source_rnd_ids=["rnd-1"]), self.idea_path)
        duplicate = add_idea(self._idea("Different title", source_rnd_ids=["rnd-1"]), self.idea_path)
        self.assertEqual(duplicate.duplicate_candidate_ids, (first.id,))
        self.assertEqual(len(load_ideas(self.idea_path)), 2)
        with self.assertRaises(ValueError):
            Idea.from_mapping(self._idea("Bad effort", estimated_effort_hours=-1))
        with self.assertRaises(ValueError):
            Idea.from_mapping(self._idea("Bad status", status="published"))
        title = "Browser execution layer"
        similar_base = add_idea(self._idea(title), self.idea_path)
        similar = add_idea(self._idea("Browser execution layerr"), self.idea_path)
        self.assertEqual(similar.duplicate_candidate_ids, (similar_base.id,))
        with self.assertRaises(ValueError):
            Idea.from_mapping(self._idea("Non-finite effort", estimated_effort_hours="nan"))


if __name__ == "__main__":
    unittest.main()