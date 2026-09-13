from pathlib import Path
from dataclasses import replace
import json
import subprocess
import sys
import tempfile
import unittest

from content_engine.models import ContentDraft
from content_engine.pipeline import (
    MediaBatchItem,
    MediaBatchReport,
    generate_media_batch_dry_run,
    run_media_batch,
    run_media_batch_file,
)
from content_engine.rewrite import MockRewriteProvider, RewriteProvider, RewriteRequest, RewriteService
from tak_brain import KnowledgeRecord, load_knowledge_records


class MediaBatchPipelineTests(unittest.TestCase):
    KNOWLEDGE_PATH = Path(__file__).parents[1] / "data" / "tak_brain_knowledge.json"

    def setUp(self) -> None:
        self.records = load_knowledge_records(self.KNOWLEDGE_PATH)
        self.approved_records = tuple(r for r in self.records if r.knowledge_review_status == "approved")

    def test_pipeline_selects_only_approved_knowledge(self):
        # 승인된 레코드 1개와 pending 레코드 1개 혼합
        approved = self.approved_records[0]
        pending = KnowledgeRecord(
            **{**approved.to_dict(), "id": "knowledge-pending-test", "knowledge_review_status": "pending"}
        )

        report = run_media_batch([approved, pending])

        self.assertEqual(report.total_knowledge_count, 2)
        self.assertEqual(report.approved_knowledge_count, 1)
        self.assertEqual(report.skipped_knowledge_count, 1)
        self.assertEqual(report.total_draft_count, 9)
        self.assertTrue(all(item.knowledge_id == approved.id for item in report.items))

    def test_single_approved_knowledge_generates_nine_drafts(self):
        approved = self.approved_records[0]
        report = run_media_batch([approved])

        self.assertEqual(report.total_draft_count, 9)
        platforms = [item.platform for item in report.items]
        self.assertEqual(platforms.count("blog"), 1)
        self.assertEqual(platforms.count("shorts"), 3)
        self.assertEqual(platforms.count("threads"), 5)

    def test_valid_and_rejected_items_are_properly_separated(self):
        approved = self.approved_records[0]

        class PartiallyFailingProvider(RewriteProvider):
            def rewrite(self, request: RewriteRequest) -> ContentDraft:
                # blog는 정상, shorts는 새 숫자 추가로 거절 유도
                if isinstance(request.draft, ContentDraft) and request.draft.title == "직접 시도하며 얻은 교훈":
                    return request.draft
                return replace(request.draft, body=f"999999 새 숫자\n\n{request.draft.body}")

        report = run_media_batch([approved], provider=PartiallyFailingProvider())

        self.assertEqual(report.valid_count, 1)
        self.assertEqual(report.rejected_count, 8)
        self.assertEqual(report.error_count, 0)
        self.assertEqual(len(report.valid_items), 1)
        self.assertEqual(len(report.rejected_items), 8)
        self.assertEqual(report.valid_items[0].platform, "blog")

    def test_rejection_reasons_are_preserved(self):
        approved = self.approved_records[0]

        class RejectingProvider(RewriteProvider):
            def rewrite(self, request: RewriteRequest) -> ContentDraft:
                return replace(request.draft, body=f"999999 새 숫자\n\n{request.draft.body}")

        report = run_media_batch([approved], provider=RejectingProvider())

        self.assertEqual(report.rejected_count, 9)
        for item in report.rejected_items:
            self.assertEqual(item.status, "rejected")
            self.assertTrue(any("없는 숫자" in reason for reason in item.rejection_reasons))

    def test_metadata_traceability_is_preserved_in_batch_items(self):
        approved = self.approved_records[0]
        report = run_media_batch([approved])

        for item in report.items:
            self.assertEqual(item.knowledge_id, approved.id)
            self.assertEqual(item.source_url, approved.source_url)
            self.assertEqual(item.evidence, approved.evidence)
            self.assertTrue(len(item.evidence_unit_ids) > 0)

    def test_llm_exception_is_captured_as_error_without_halting_batch(self):
        approved_1 = self.approved_records[0]
        approved_2 = self.approved_records[1]

        class CrashingProvider(RewriteProvider):
            def __init__(self):
                self.call_count = 0

            def rewrite(self, request: RewriteRequest) -> ContentDraft:
                self.call_count += 1
                if request.knowledge.id == approved_1.id and self.call_count == 1:
                    raise RuntimeError("Temporary LLM network error")
                return request.draft

        report = run_media_batch([approved_1, approved_2], provider=CrashingProvider())

        self.assertEqual(report.total_knowledge_count, 2)
        self.assertEqual(report.approved_knowledge_count, 2)
        self.assertEqual(report.total_draft_count, 18)
        self.assertEqual(report.error_count, 1)
        self.assertEqual(report.valid_count, 17)
        self.assertEqual(report.rejected_count, 0)

        error_item = report.error_items[0]
        self.assertEqual(error_item.status, "error")
        self.assertIn("Temporary LLM network error", str(error_item.error_message))
        self.assertEqual(error_item.knowledge_id, approved_1.id)

    def test_report_json_serialization_and_save(self):
        approved = self.approved_records[0]
        report = run_media_batch([approved])

        data = report.to_dict()
        self.assertIn("summary", data)
        self.assertIn("valid_items", data)
        self.assertIn("rejected_items", data)
        self.assertIn("error_items", data)
        self.assertIn("all_items", data)
        self.assertEqual(data["summary"]["total_draft_count"], 9)

        with tempfile.TemporaryDirectory() as tmp_dir:
            out_path = Path(tmp_dir) / "output" / "batch_report.json"
            report.save_json(out_path)
            self.assertTrue(out_path.exists())
            loaded = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(loaded["summary"]["valid_count"], 9)

    def test_run_media_batch_file_with_limit_and_id(self):
        approved = self.approved_records[0]
        report = run_media_batch_file(self.KNOWLEDGE_PATH, limit=1, knowledge_id=approved.id)

        self.assertEqual(report.approved_knowledge_count, 1)
        self.assertEqual(report.total_draft_count, 9)

    def test_generate_media_batch_dry_run_structure(self):
        result = generate_media_batch_dry_run(self.approved_records, total_count=len(self.records))

        self.assertEqual(result["summary"]["mode"], "dry_run")
        self.assertEqual(result["summary"]["approved_knowledge_count"], len(self.approved_records))
        self.assertEqual(result["summary"]["total_draft_count"], len(self.approved_records) * 9)
        self.assertEqual(len(result["items"]), len(self.approved_records) * 9)

        for item in result["items"]:
            self.assertIn("knowledge_id", item)
            self.assertIn("article_type", item)
            self.assertIn("knowledge_type", item)
            self.assertIn("platform", item)
            self.assertIn("title_template", item)
            self.assertIn("evidence_unit_ids", item)
            self.assertIn("source_url", item)
            self.assertIn("evidence", item)
            self.assertEqual(item["status"], "dry_run")
            self.assertTrue(len(item["evidence_unit_ids"]) > 0)

    def test_cli_dry_run(self):
        script = Path(__file__).parents[1] / "scripts" / "run_media_batch.py"
        result = subprocess.run(
            [sys.executable, str(script), "--limit", "2"],
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertIn("TAK MEDIA Batch Pipeline (Dry-run)", result.stdout)
        self.assertIn("승인 KNOWLEDGE: 2건", result.stdout)
        self.assertIn("예상 생성 Draft: 18건", result.stdout)
        self.assertIn("네트워크 호출 없음", result.stdout)

    def test_cli_dry_run_saves_json_output(self):
        script = Path(__file__).parents[1] / "scripts" / "run_media_batch.py"

        with tempfile.TemporaryDirectory() as tmp_dir:
            out_path = Path(tmp_dir) / "dryrun_report.json"
            result = subprocess.run(
                [sys.executable, str(script), "--output", str(out_path)],
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertIn("Dry-run 결과 저장 완료", result.stdout)
            self.assertTrue(out_path.exists())

            data = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(data["summary"]["approved_knowledge_count"], 4)
            self.assertEqual(data["summary"]["total_draft_count"], 36)
            self.assertEqual(len(data["items"]), 36)
            first_item = data["items"][0]
            self.assertIn("knowledge_id", first_item)
            self.assertIn("article_type", first_item)
            self.assertIn("knowledge_type", first_item)
            self.assertIn("platform", first_item)
            self.assertIn("title_template", first_item)
            self.assertIn("evidence_unit_ids", first_item)


if __name__ == "__main__":
    unittest.main()
