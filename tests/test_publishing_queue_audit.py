import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from content_engine.publishing_queue import PublishingQueue
from content_engine.publishing_queue_audit import audit_queue_file, audit_queue_snapshot
from scripts.audit_publishing_queue import main


class PublishingQueueAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "queue.json"
        self.now = datetime(2026, 11, 22, tzinfo=timezone.utc)
        self.queue = PublishingQueue(self.path)
        self.queue.enqueue_approved(
            content_id="private-content", platform="blog",
            payload={"title": "private-title", "body": "secret-token-sentinel"},
            scheduled_at=self.now + timedelta(minutes=1),
            approved_by="private-operator", now=self.now,
        )
        self.data = self.queue.snapshot()

    def audit(self, data=None):
        return audit_queue_snapshot(self.data if data is None else data, now=self.now)

    def codes(self, report):
        return {item["code"] for item in report["findings"]}

    def test_healthy_scheduled_and_published_queues_pass(self):
        self.assertEqual(self.audit()["status"], "ok")
        self.queue.run_due(lambda *_: "private-remote", enabled=True, now=self.now + timedelta(minutes=2))
        report = audit_queue_file(self.path, now=self.now)
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["history_count"], 1)
        self.assertEqual(report["status_counts"]["published"], 1)

    def test_corrupt_approval_payload_schedule_and_counts_are_blocked(self):
        changes = (
            ("payload", {"body": "secret-token-sentinel"}, "content_integrity_invalid"),
            ("approved", "false", "approval_invalid"),
            ("approved_by", "", "approval_record_invalid"),
            ("approved_at", "2026-11-22", "approval_record_invalid"),
            ("attempts", True, "attempts_invalid"),
            ("attempts", -1, "attempts_invalid"),
            ("attempts", 4, "attempts_invalid"),
            ("next_attempt_at", "secret-token-sentinel", "schedule_invalid"),
            ("status", [], "status_invalid"),
        )
        for field, value, code in changes:
            with self.subTest(field=field, value=value):
                data = copy.deepcopy(self.data)
                data["items"][0][field] = value
                report = self.audit(data)
                self.assertEqual(report["status"], "blocked")
                self.assertIn(code, self.codes(report))
                output = json.dumps(report)
                for private in ("secret-token-sentinel", "private-title", "private-content", "private-operator"):
                    self.assertNotIn(private, output)

    def test_processing_and_manual_review_have_actionable_warnings(self):
        item = self.data["items"][0]
        for status, age, expected in (
            ("processing", 0, "processing_active"),
            ("processing", 300, "processing_stale"),
            ("needs_review", 0, "manual_review_required"),
            ("failed", 0, "failed_job"),
        ):
            with self.subTest(status=status, age=age):
                item.update(status=status, updated_at=(self.now - timedelta(seconds=age)).isoformat())
                report = self.audit()
                self.assertEqual(report["status"], "attention")
                self.assertIn(expected, self.codes(report))

    def test_published_status_requires_matching_history(self):
        self.data["items"][0]["status"] = "published"
        self.assertIn("published_history_missing", self.codes(self.audit()))
        self.queue.run_due(lambda *_: "remote", enabled=True, now=self.now + timedelta(minutes=2))
        data = self.queue.snapshot()
        data["history"][0]["platform"] = "threads"
        self.assertIn("published_history_missing", self.codes(self.audit(data)))

    def test_duplicate_jobs_and_history_are_blocked(self):
        self.queue.run_due(lambda *_: "remote", enabled=True, now=self.now + timedelta(minutes=2))
        data = self.queue.snapshot()
        data["items"].append(copy.deepcopy(data["items"][0]))
        data["history"].append(copy.deepcopy(data["history"][0]))
        report = self.audit(data)
        self.assertEqual(report["status"], "blocked")
        self.assertTrue({"duplicate_id", "duplicate_idempotency_key", "duplicate_history"} <= self.codes(report))

    def test_schema_and_malformed_records_fail_without_tracebacks(self):
        for data in (None, [], {}, {"version": True}, {"version": 2}, {"version": 1, "items": {}, "history": []}):
            with self.subTest(data=data):
                self.assertEqual(audit_queue_snapshot(data)["status"], "blocked")
        self.data["items"] = [None, {"status": {"secret": "value"}}]
        self.data["history"] = [None, {"idempotency_key": []}]
        report = self.audit()
        self.assertEqual(report["status_counts"]["unknown"], 2)
        self.assertIn("history_record_invalid", self.codes(report))

    def test_snapshot_and_file_diagnostics_do_not_mutate_or_create_files(self):
        original = copy.deepcopy(self.data)
        self.audit()
        self.assertEqual(self.data, original)
        path = Path(self.temp.name) / "read-only.json"
        path.write_text(json.dumps(self.data), encoding="utf-8")
        before = path.read_bytes()
        entries = set(path.parent.iterdir())
        self.assertEqual(audit_queue_file(path)["status"], "ok")
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(set(path.parent.iterdir()), entries)

    def test_missing_file_does_not_create_parent(self):
        path = Path(self.temp.name) / "missing" / "queue.json"
        self.assertIn("queue_missing", self.codes(audit_queue_file(path)))
        self.assertFalse(path.parent.exists())

    def test_invalid_json_encoding_and_nonfinite_numbers_are_rejected(self):
        for raw in (b"{", b"\xff", b'{"version":NaN}', b'{"version":Infinity}',
                    b'{"version":1,"items":[],"history":[],"history":[]}',
                    b'{"version":1,"items":[{"approved":true,"approved":false}],"history":[]}'):
            with self.subTest(raw=raw):
                self.path.write_bytes(raw)
                self.assertIn("queue_json_invalid", self.codes(audit_queue_file(self.path)))

    def test_size_limit_and_read_errors_return_safe_messages(self):
        with patch("content_engine.publishing_queue_audit.MAX_AUDIT_BYTES", 10):
            self.assertIn("queue_too_large", self.codes(audit_queue_file(self.path)))
        with patch.object(Path, "open", side_effect=PermissionError("private-path-secret")):
            report = audit_queue_file(self.path)
        self.assertIn("queue_unreadable", self.codes(report))
        self.assertNotIn("private-path-secret", json.dumps(report))

    def test_findings_output_is_bounded_and_counts_are_complete(self):
        self.data["items"] = [None] * 205
        report = self.audit()
        self.assertEqual(report["error_count"], 205)
        self.assertEqual(len(report["findings"]), 200)
        self.assertEqual(report["omitted_findings"], 5)

    def test_cli_exit_codes_json_and_human_output(self):
        for status, expected in (("scheduled", 0), ("needs_review", 1), ("published", 2)):
            with self.subTest(status=status):
                self.data["items"][0]["status"] = status
                self.path.write_text(json.dumps(self.data), encoding="utf-8")
                output = io.StringIO()
                with redirect_stdout(output):
                    result = main(["--queue", str(self.path), "--json"])
                self.assertEqual(result, expected)
                self.assertEqual(json.loads(output.getvalue())["scope"], "local_queue_only")
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(["--queue", str(self.path)]), 2)
        self.assertIn("문제 해결 필요", output.getvalue())
        self.assertNotIn("secret-token-sentinel", output.getvalue())


if __name__ == "__main__":
    unittest.main()
