from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest

from scripts.view_media_batch import format_item, format_summary, load_and_view, render_batch_report


class MediaViewerTests(unittest.TestCase):
    SAMPLE_JSON = Path(__file__).parents[1] / "data" / "tak_media_batch_e2e_test.json"

    def setUp(self) -> None:
        self.sample_data = {
            "summary": {
                "total_knowledge_count": 2,
                "approved_knowledge_count": 1,
                "skipped_knowledge_count": 1,
                "total_draft_count": 9,
                "valid_count": 7,
                "rejected_count": 1,
                "error_count": 1,
            },
            "all_items": [
                {
                    "knowledge_id": "k-001",
                    "platform": "blog",
                    "status": "valid",
                    "original_title": "원본 블로그 제목",
                    "original_body": "원본 블로그 본문",
                    "rewritten_title": "재작성 블로그 제목",
                    "rewritten_body": "재작성 블로그 본문",
                    "source_url": "https://example.test/source1",
                    "evidence": ["근거 문장 1", "근거 문장 2"],
                    "evidence_unit_ids": ["problem:1", "action:1"],
                    "rejection_reasons": [],
                    "error_message": None,
                },
                {
                    "knowledge_id": "k-001",
                    "platform": "shorts",
                    "status": "rejected",
                    "original_title": "원본 쇼츠 제목",
                    "original_body": "원본 쇼츠 본문",
                    "rewritten_title": "재작성 쇼츠 제목",
                    "rewritten_body": "재작성 쇼츠 본문",
                    "source_url": "https://example.test/source1",
                    "evidence": ["근거 문장 1"],
                    "evidence_unit_ids": ["problem:1"],
                    "rejection_reasons": ["원문 근거에 없는 숫자가 추가되었습니다: 999"],
                    "error_message": None,
                },
                {
                    "knowledge_id": "k-001",
                    "platform": "threads",
                    "status": "error",
                    "original_title": "원본 스레드 제목",
                    "original_body": "원본 스레드 본문",
                    "rewritten_title": None,
                    "rewritten_body": None,
                    "source_url": "https://example.test/source1",
                    "evidence": ["근거 문장 1"],
                    "evidence_unit_ids": ["problem:1"],
                    "rejection_reasons": [],
                    "error_message": "LLM API connection timeout",
                },
            ],
        }

    def test_format_summary_contains_all_metrics(self):
        summary_text = format_summary(self.sample_data["summary"])

        self.assertIn("전체 KNOWLEDGE: 2건", summary_text)
        self.assertIn("승인 KNOWLEDGE: 1건", summary_text)
        self.assertIn("건너뜀: 1건", summary_text)
        self.assertIn("전체 Draft: 9건", summary_text)
        self.assertIn("Valid (검증 통과): 7건", summary_text)
        self.assertIn("Rejected (검증 거절): 1건", summary_text)
        self.assertIn("Error (오류): 1건", summary_text)

    def test_load_and_view_renders_nine_items_if_present(self):
        if not self.SAMPLE_JSON.exists():
            self.skipTest(f"{self.SAMPLE_JSON} 파일이 없습니다.")

        output = load_and_view(self.SAMPLE_JSON)

        self.assertIn("TAK MEDIA CONTENT REVIEW", output)
        self.assertIn("전체 Draft: 9건", output)
        self.assertIn("[1] BLOG | VALID", output)
        self.assertIn("[2] SHORTS | VALID", output)
        self.assertIn("[9] THREADS | VALID", output)

    def test_platform_filter(self):
        output = render_batch_report(self.sample_data, platform_filter="blog")

        self.assertIn("[1] BLOG | VALID", output)
        self.assertNotIn("[2] SHORTS", output)
        self.assertNotIn("THREADS", output)
        self.assertIn("표시 항목: 1건", output)

    def test_status_filter(self):
        output_valid = render_batch_report(self.sample_data, status_filter="valid")
        self.assertIn("[1] BLOG | VALID", output_valid)
        self.assertNotIn("REJECTED", output_valid)
        self.assertNotIn("ERROR", output_valid)

        output_rejected = render_batch_report(self.sample_data, status_filter="rejected")
        self.assertIn("SHORTS | REJECTED", output_rejected)
        self.assertNotIn("BLOG | VALID", output_rejected)

        output_error = render_batch_report(self.sample_data, status_filter="error")
        self.assertIn("THREADS | ERROR", output_error)
        self.assertNotIn("BLOG | VALID", output_error)

    def test_source_url_and_evidence_rendering(self):
        output = render_batch_report(self.sample_data)

        self.assertIn("SOURCE: https://example.test/source1", output)
        self.assertIn("EVIDENCE UNITS: problem:1, action:1", output)
        self.assertIn("- 근거 문장 1", output)
        self.assertIn("- 근거 문장 2", output)

    def test_rejection_reason_and_error_message_rendering(self):
        output = render_batch_report(self.sample_data)

        self.assertIn("REJECTION REASONS", output)
        self.assertIn("- 원문 근거에 없는 숫자가 추가되었습니다: 999", output)
        self.assertIn("ERROR MESSAGE", output)
        self.assertIn("LLM API connection timeout", output)

    def test_invalid_json_handling(self):
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as tmp_file:
            tmp_file.write("INVALID JSON CONTENT {")
            tmp_path = tmp_file.name

        try:
            with self.assertRaises(ValueError) as ctx:
                load_and_view(tmp_path)
            self.assertIn("유효하지 않은 JSON", str(ctx.exception))
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_nonexistent_file_handling(self):
        nonexistent = Path("/nonexistent/path/to/report.json")

        with self.assertRaises(FileNotFoundError) as ctx:
            load_and_view(nonexistent)
        self.assertIn("입력 파일을 찾을 수 없습니다", str(ctx.exception))

    def test_cli_execution(self):
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as tmp_file:
            json.dump(self.sample_data, tmp_file, ensure_ascii=False)
            tmp_path = tmp_file.name

        script = Path(__file__).parents[1] / "scripts" / "view_media_batch.py"

        try:
            res = subprocess.run(
                [sys.executable, str(script), "--input", tmp_path, "--platform", "shorts"],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertIn("SHORTS | REJECTED", res.stdout)
            self.assertNotIn("BLOG | VALID", res.stdout)
        finally:
            Path(tmp_path).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
