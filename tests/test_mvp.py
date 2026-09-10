import json
from pathlib import Path
import tempfile
import unittest

from blog_importer import ValidationError, import_files, load_file
from tak_brain import BrainRepository


FIXTURES = Path(__file__).parent / "fixtures" / "sample_posts"


class ImportPipelineTests(unittest.TestCase):
    def test_imports_json_and_markdown_samples(self):
        result = import_files([FIXTURES])

        self.assertEqual(len(result.posts), 3)
        self.assertEqual(result.duplicate_count, 0)
        self.assertTrue(all(post.content_hash for post in result.posts))

    def test_required_fields_are_validated(self):
        with self.assertRaises(ValidationError):
            load_file(self._write_json({"title": "제목", "body": "본문"}))

    def test_hash_is_stable_and_duplicate_is_prevented(self):
        result = import_files([FIXTURES / "finance.json", FIXTURES / "finance.json"])

        self.assertEqual(len(result.posts), 1)
        self.assertEqual(result.duplicate_count, 1)
        self.assertEqual(result.posts[0].content_hash, result.posts[0].calculate_content_hash())

    def test_raw_is_preserved_and_metadata_is_generated(self):
        posts = import_files([FIXTURES]).posts
        repository = BrainRepository()
        self.assertEqual(repository.add_many(list(posts)), 3)

        risk_post = next(post for post in posts if post.id == "sample-risk-001")
        risk_record = repository.get_by_hash(risk_post.content_hash)
        self.assertIsNotNone(risk_record)
        assert risk_record is not None
        self.assertEqual(risk_record.raw.body, risk_post.body)
        self.assertEqual(risk_record.raw.source_url, risk_post.source_url)
        self.assertIsNone(risk_record.knowledge)
        self.assertTrue(risk_record.metadata["privacy_risk"])
        self.assertTrue(risk_record.metadata["internal_information_risk"])
        self.assertTrue(risk_record.metadata["verification_required"])

    def _write_json(self, data: dict) -> Path:
        handle = tempfile.NamedTemporaryFile(mode="w", suffix=".json", encoding="utf-8", delete=False)
        with handle:
            json.dump(data, handle)
        self.addCleanup(lambda: Path(handle.name).unlink(missing_ok=True))
        return Path(handle.name)


if __name__ == "__main__":
    unittest.main()