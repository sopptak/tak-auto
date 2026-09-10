import json
from pathlib import Path
import tempfile
import unittest

from blog_importer.pilot import import_directory


class PilotImportTests(unittest.TestCase):
    def test_imports_ten_posts_and_preserves_input_files(self):
        with tempfile.TemporaryDirectory() as directory:
            input_dir = Path(directory) / "input"
            output_path = Path(directory) / "data" / "raw.json"
            input_dir.mkdir()
            for index in range(10):
                (input_dir / f"post-{index:02d}.json").write_text(
                    json.dumps(self._post(index), ensure_ascii=False), encoding="utf-8"
                )
            before = {path.name: path.read_bytes() for path in input_dir.iterdir()}

            report = import_directory(input_dir, output_path)

            self.assertEqual(report.total_posts, 10)
            self.assertEqual(report.new_posts, 10)
            self.assertEqual(report.duplicate_posts, 0)
            self.assertEqual(report.validation_errors, 0)
            self.assertEqual(before, {path.name: path.read_bytes() for path in input_dir.iterdir()})
            records = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(len(records), 10)
            for index, record in enumerate(records):
                raw = record["raw"]
                expected = self._post(index)
                self.assertEqual(raw["body"], expected["body"])
                self.assertEqual(raw["source_url"], expected["source_url"])
                self.assertEqual(raw["published_at"], expected["published_at"])

    def test_second_import_reports_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            input_dir = Path(directory) / "input"
            output_path = Path(directory) / "raw.json"
            input_dir.mkdir()
            (input_dir / "post.json").write_text(json.dumps(self._post(1)), encoding="utf-8")

            first = import_directory(input_dir, output_path)
            second = import_directory(input_dir, output_path)

            self.assertEqual(first.new_posts, 1)
            self.assertEqual(second.total_posts, 1)
            self.assertEqual(second.new_posts, 0)
            self.assertEqual(second.duplicate_posts, 1)

    def test_invalid_file_and_empty_body_are_counted(self):
        with tempfile.TemporaryDirectory() as directory:
            input_dir = Path(directory) / "input"
            input_dir.mkdir()
            (input_dir / "broken.json").write_text("{broken", encoding="utf-8")
            empty = self._post(2)
            empty["body"] = "   "
            (input_dir / "empty.json").write_text(json.dumps(empty), encoding="utf-8")

            report = import_directory(input_dir, Path(directory) / "raw.json")

            self.assertEqual(report.total_posts, 0)
            self.assertEqual(report.validation_errors, 2)

    def test_risk_flags_are_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            input_dir = Path(directory) / "input"
            input_dir.mkdir()
            post = self._post(3)
            post["body"] = "연락처 010-1234-5678과 기관 내부 대외비를 포함합니다."
            (input_dir / "risk.json").write_text(json.dumps(post, ensure_ascii=False), encoding="utf-8")

            report = import_directory(input_dir, Path(directory) / "raw.json")

            self.assertEqual(report.privacy_risks, 1)
            self.assertEqual(report.internal_information_risks, 1)

    @staticmethod
    def _post(index: int) -> dict:
        return {
            "id": f"pilot-{index:02d}",
            "title": f"파일럿 글 {index}",
            "published_at": "2024-01-01",
            "body": f"파일럿 원문 {index}",
            "tags": ["파일럿"],
            "source_url": f"https://blog.example.test/{index}",
            "source": "manual_naver_export",
        }


if __name__ == "__main__":
    unittest.main()