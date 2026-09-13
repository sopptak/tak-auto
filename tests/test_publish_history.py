from pathlib import Path
import json
import tempfile
import unittest

from content_engine.publish_history import (
    PublishHistory,
    PublishHistoryError,
    PublishRecord,
    compute_content_id,
    select_unpublished_threads_item,
)


def _threads_item(**overrides):
    base = {
        "knowledge_id": "k-001",
        "platform": "threads",
        "status": "valid",
        "source_url": "https://example.test/source",
        "original_title": "원문 제목",
        "original_body": "원문 본문",
        "rewritten_title": "재작성 제목",
        "rewritten_body": "재작성 본문",
        "evidence_unit_ids": ["lesson:1"],
    }
    base.update(overrides)
    return base


class ComputeContentIdTests(unittest.TestCase):
    def test_same_stable_fields_produce_same_id(self):
        item_a = _threads_item(rewritten_body="첫 번째 재작성")
        item_b = _threads_item(rewritten_body="두 번째 재작성")  # LLM 재작성만 다름

        self.assertEqual(compute_content_id(item_a), compute_content_id(item_b))

    def test_different_evidence_unit_ids_produce_different_id(self):
        item_a = _threads_item(evidence_unit_ids=["lesson:1"])
        item_b = _threads_item(evidence_unit_ids=["lesson:2"])

        self.assertNotEqual(compute_content_id(item_a), compute_content_id(item_b))

    def test_different_platform_or_knowledge_produce_different_id(self):
        threads_item = _threads_item()
        shorts_item = _threads_item(platform="shorts")
        other_knowledge_item = _threads_item(knowledge_id="k-002")

        ids = {
            compute_content_id(threads_item),
            compute_content_id(shorts_item),
            compute_content_id(other_knowledge_item),
        }
        self.assertEqual(len(ids), 3)

    def test_content_id_is_deterministic_across_calls(self):
        item = _threads_item()
        self.assertEqual(compute_content_id(item), compute_content_id(item))

    def test_missing_optional_fields_do_not_raise(self):
        minimal_item = {"platform": "threads", "status": "valid"}
        content_id = compute_content_id(minimal_item)
        self.assertTrue(content_id.startswith("content-"))


class PublishHistoryStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.history_path = Path(self.tmp_dir.name) / "threads_publish_log.json"

    def test_missing_file_loads_as_empty(self):
        history = PublishHistory(self.history_path)
        self.assertEqual(history.load(), [])
        self.assertEqual(history.published_content_ids(), set())
        self.assertFalse(self.history_path.exists())

    def test_empty_file_loads_as_empty(self):
        self.history_path.write_text("", encoding="utf-8")
        history = PublishHistory(self.history_path)
        self.assertEqual(history.load(), [])

    def test_whitespace_only_file_loads_as_empty(self):
        self.history_path.write_text("   \n\t  ", encoding="utf-8")
        history = PublishHistory(self.history_path)
        self.assertEqual(history.load(), [])

    def test_corrupted_json_raises_publish_history_error(self):
        self.history_path.write_text("{not valid json", encoding="utf-8")
        history = PublishHistory(self.history_path)
        with self.assertRaises(PublishHistoryError):
            history.load()

    def test_non_list_json_raises_publish_history_error(self):
        self.history_path.write_text(json.dumps({"unexpected": "object"}), encoding="utf-8")
        history = PublishHistory(self.history_path)
        with self.assertRaises(PublishHistoryError):
            history.load()

    def test_append_creates_file_when_missing(self):
        history = PublishHistory(self.history_path)
        history.append(
            PublishRecord(
                content_id="content-abc123",
                published_at="2026-09-13T08:00:00+00:00",
                threads_post_id="th_post_1",
                knowledge_id="k-001",
                source_url="https://example.test/source",
            )
        )

        self.assertTrue(self.history_path.exists())
        records = history.load()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["content_id"], "content-abc123")
        self.assertEqual(records[0]["threads_post_id"], "th_post_1")
        self.assertIn("published_at", records[0])

    def test_append_preserves_existing_records(self):
        history = PublishHistory(self.history_path)
        history.append(
            PublishRecord(content_id="content-1", published_at="t1", threads_post_id="p1")
        )
        history.append(
            PublishRecord(content_id="content-2", published_at="t2", threads_post_id="p2")
        )

        records = history.load()
        self.assertEqual([r["content_id"] for r in records], ["content-1", "content-2"])
        self.assertEqual(history.published_content_ids(), {"content-1", "content-2"})

    def test_is_published_reflects_recorded_ids(self):
        history = PublishHistory(self.history_path)
        self.assertFalse(history.is_published("content-1"))
        history.append(
            PublishRecord(content_id="content-1", published_at="t1", threads_post_id="p1")
        )
        self.assertTrue(history.is_published("content-1"))
        self.assertFalse(history.is_published("content-2"))


class SelectUnpublishedThreadsItemTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.history_path = Path(self.tmp_dir.name) / "threads_publish_log.json"
        self.history = PublishHistory(self.history_path)

    def test_no_history_file_selects_first_valid_threads_item(self):
        items = [
            _threads_item(knowledge_id="k-001", evidence_unit_ids=["lesson:1"]),
            _threads_item(knowledge_id="k-002", evidence_unit_ids=["lesson:2"]),
        ]

        selection = select_unpublished_threads_item(items, self.history)

        self.assertIsNotNone(selection)
        selected_item, content_id = selection
        self.assertEqual(selected_item["knowledge_id"], "k-001")
        self.assertEqual(content_id, compute_content_id(items[0]))

    def test_empty_history_behaves_like_no_history(self):
        self.history_path.write_text("[]", encoding="utf-8")
        items = [_threads_item()]

        selection = select_unpublished_threads_item(items, self.history)

        self.assertIsNotNone(selection)

    def test_multiple_valid_candidates_uses_existing_order(self):
        items = [
            _threads_item(knowledge_id="k-001", evidence_unit_ids=["a:1"]),
            _threads_item(knowledge_id="k-002", evidence_unit_ids=["a:2"]),
            _threads_item(knowledge_id="k-003", evidence_unit_ids=["a:3"]),
        ]

        selection = select_unpublished_threads_item(items, self.history)

        self.assertEqual(selection[0]["knowledge_id"], "k-001")

    def test_already_published_item_is_skipped(self):
        first = _threads_item(knowledge_id="k-001", evidence_unit_ids=["a:1"])
        second = _threads_item(knowledge_id="k-002", evidence_unit_ids=["a:2"])
        self.history.append(
            PublishRecord(
                content_id=compute_content_id(first),
                published_at="t1",
                threads_post_id="p1",
            )
        )

        selection = select_unpublished_threads_item([first, second], self.history)

        self.assertEqual(selection[0]["knowledge_id"], "k-002")

    def test_all_items_already_published_returns_none(self):
        items = [
            _threads_item(knowledge_id="k-001", evidence_unit_ids=["a:1"]),
            _threads_item(knowledge_id="k-002", evidence_unit_ids=["a:2"]),
        ]
        for item in items:
            self.history.append(
                PublishRecord(
                    content_id=compute_content_id(item),
                    published_at="t",
                    threads_post_id="p",
                )
            )

        selection = select_unpublished_threads_item(items, self.history)

        self.assertIsNone(selection)

    def test_no_candidates_when_no_items(self):
        self.assertIsNone(select_unpublished_threads_item([], self.history))

    def test_invalid_status_items_are_ignored(self):
        items = [
            _threads_item(status="rejected", knowledge_id="k-001"),
            _threads_item(status="error", knowledge_id="k-002"),
        ]

        self.assertIsNone(select_unpublished_threads_item(items, self.history))

    def test_non_threads_platform_items_are_ignored(self):
        items = [
            _threads_item(platform="blog", knowledge_id="k-001"),
            _threads_item(platform="shorts", knowledge_id="k-002"),
        ]

        self.assertIsNone(select_unpublished_threads_item(items, self.history))

    def test_mixed_valid_and_invalid_selects_only_valid_threads(self):
        items = [
            _threads_item(platform="blog", status="valid", knowledge_id="k-blog"),
            _threads_item(platform="threads", status="rejected", knowledge_id="k-rejected"),
            _threads_item(platform="threads", status="valid", knowledge_id="k-good"),
        ]

        selection = select_unpublished_threads_item(items, self.history)

        self.assertEqual(selection[0]["knowledge_id"], "k-good")


if __name__ == "__main__":
    unittest.main()
