import json
from pathlib import Path
import tempfile
import unittest

from blog_importer.models import BlogPost
from tak_brain import (
    RawContent,
    list_pending_knowledge,
    load_knowledge_records,
    review_knowledge_file,
    select_approved,
    transform_raw,
)


class KnowledgeReviewPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        post = BlogPost.from_mapping(
            {
                "id": "raw-review-001",
                "title": "검토 fixture",
                "published_at": "2026-09-10T00:00:00+00:00",
                "body": "앱을 만들고 테스트했다.",
                "source_url": "https://blog.example.test/review-001",
                "source": "test",
            }
        )
        self.record = transform_raw(RawContent.from_post(post)).to_dict()

    def _write_fixture(self, records: list[dict] | None = None) -> Path:
        handle = tempfile.NamedTemporaryFile(mode="w", suffix=".json", encoding="utf-8", delete=False)
        with handle:
            json.dump(records or [self.record], handle, ensure_ascii=False)
        path = Path(handle.name)
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        return path

    def test_pending_to_approved_persists_review_fields_and_sources(self):
        path = self._write_fixture()
        updated = review_knowledge_file(path, self.record["id"], "approved", "확인 완료")
        saved = load_knowledge_records(path)[0]

        self.assertEqual(updated.knowledge_review_status, "approved")
        self.assertEqual(saved.knowledge_review_status, "approved")
        self.assertTrue(saved.reviewed_at)
        self.assertEqual(saved.review_note, "확인 완료")
        self.assertEqual(saved.source_raw_id, self.record["source_raw_id"])
        self.assertEqual(saved.source_url, self.record["source_url"])

    def test_pending_to_rejected_persists_note(self):
        path = self._write_fixture()
        review_knowledge_file(path, self.record["id"], "rejected", "근거 재검토 필요")
        saved = load_knowledge_records(path)[0]

        self.assertEqual(saved.knowledge_review_status, "rejected")
        self.assertEqual(saved.review_note, "근거 재검토 필요")
        self.assertTrue(saved.reviewed_at)

    def test_missing_id_errors_without_changing_file(self):
        path = self._write_fixture()
        before = path.read_bytes()

        with self.assertRaises(KeyError):
            review_knowledge_file(path, "knowledge-missing", "approved")

        self.assertEqual(path.read_bytes(), before)

    def test_approved_filter_excludes_pending_and_rejected(self):
        pending = load_knowledge_records(self._write_fixture())[0]
        approved = review_knowledge_file(self._write_fixture(), self.record["id"], "approved")
        rejected = review_knowledge_file(self._write_fixture(), self.record["id"], "rejected")

        self.assertEqual(select_approved([pending, approved, rejected]), (approved,))

    def test_pending_listing_and_repeat_approval_preserve_data(self):
        path = self._write_fixture()
        self.assertEqual([record.id for record in list_pending_knowledge(path)], [self.record["id"]])
        first = review_knowledge_file(path, self.record["id"], "approved")
        original = {key: value for key, value in self.record.items() if key not in {"knowledge_review_status", "reviewed_at", "review_note"}}
        second = review_knowledge_file(path, self.record["id"], "approved")
        saved = load_knowledge_records(path)[0].to_dict()

        self.assertEqual(second.knowledge_review_status, "approved")
        self.assertNotIn(self.record["id"], [record.id for record in list_pending_knowledge(path)])
        self.assertEqual({key: saved[key] for key in original}, original)
        self.assertTrue(first.reviewed_at)
        self.assertTrue(second.reviewed_at)


if __name__ == "__main__":
    unittest.main()