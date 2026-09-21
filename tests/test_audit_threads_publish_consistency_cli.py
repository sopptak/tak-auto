"""scripts/audit_threads_publish_consistency.py CLI 검증(6-15).

Threads API는 이 스크립트가 애초에 import조차 하지 않는다(스크립트 docstring
참고) - 순수 로컬 파일 입출력만으로 검증한다. 이 CLI는 어떤 입력 파일도 쓰지
않는다(--report-output만 예외).
"""

from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import json
import tempfile
import unittest

from scripts.audit_threads_publish_consistency import main


class AuditThreadsPublishConsistencyCLITests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.tmp_path = Path(self.tmp_dir.name)
        self.pending_path = self.tmp_path / "pending.json"
        self.history_path = self.tmp_path / "history.json"
        self.report_path = self.tmp_path / "report.md"

    def _base_args(self, extra: list[str] | None = None) -> list[str]:
        return [
            "--pending", str(self.pending_path),
            "--history", str(self.history_path),
            "--report-output", str(self.report_path),
        ] + (extra or [])

    def _write_pending(self, drafts: list[dict]) -> None:
        self.pending_path.write_text(json.dumps(drafts, ensure_ascii=False), encoding="utf-8")

    def _write_history(self, records: list[dict]) -> None:
        self.history_path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")

    def _draft(self, content_id: str, status: str, **overrides) -> dict:
        record = {
            "content_id": content_id,
            "knowledge_id": "knowledge-x",
            "source_url": "https://example.com",
            "evidence_unit_ids": ["lesson:1"],
            "article_type": None,
            "knowledge_type": "의견",
            "original_title": "원문",
            "original_body": "본문",
            "ai_rewritten_title": "제목",
            "ai_rewritten_body": "본문",
            "status": status,
            "created_at": "2026-09-01T00:00:00+00:00",
        }
        record.update(overrides)
        return record

    def test_missing_files_are_treated_as_empty_and_report_zero(self):
        buffer = StringIO()
        with redirect_stdout(buffer):
            exit_code = main(self._base_args())
        self.assertEqual(exit_code, 0)
        self.assertIn("전체 대상 content_id: 0", buffer.getvalue())
        self.assertTrue(self.report_path.exists())

    def test_dry_run_never_writes_pending_or_history(self):
        self._write_pending([self._draft("content-1", "approved")])
        self._write_history(
            [{"content_id": "content-1", "published_at": "x", "threads_post_id": "post-1",
              "knowledge_id": "knowledge-x", "platform": "threads", "source_url": "https://example.com"}]
        )
        before_pending = self.pending_path.read_text(encoding="utf-8")
        before_history = self.history_path.read_text(encoding="utf-8")

        buffer = StringIO()
        with redirect_stdout(buffer):
            exit_code = main(self._base_args())
        self.assertEqual(exit_code, 0)

        self.assertEqual(self.pending_path.read_text(encoding="utf-8"), before_pending)
        self.assertEqual(self.history_path.read_text(encoding="utf-8"), before_history)
        self.assertIn("PUBLISHED_BUT_PENDING_STALE: 1", buffer.getvalue())
        self.assertIn("content-1", buffer.getvalue())

    def test_no_report_flag_skips_markdown_file(self):
        buffer = StringIO()
        with redirect_stdout(buffer):
            main(self._base_args(["--no-report"]))
        self.assertFalse(self.report_path.exists())

    def test_fail_on_anomaly_returns_nonzero_only_when_requested(self):
        self._write_history(
            [{"content_id": "content-orphan", "published_at": "x", "threads_post_id": "post-1",
              "knowledge_id": "knowledge-x", "platform": "threads", "source_url": "https://example.com"}]
        )
        buffer = StringIO()
        with redirect_stdout(buffer):
            default_exit = main(self._base_args())
        self.assertEqual(default_exit, 0)

        buffer2 = StringIO()
        with redirect_stdout(buffer2):
            strict_exit = main(self._base_args(["--fail-on-anomaly"]))
        self.assertEqual(strict_exit, 1)


if __name__ == "__main__":
    unittest.main()
