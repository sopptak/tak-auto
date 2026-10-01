"""Scheduled collector tests use temporary data and a mocked Threads transport."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
import io
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from content_engine.media_archive import MediaArchiveRecord, upsert_archive
from content_engine.performance.models import PerformanceRecord
from content_engine.performance.store import append_snapshot, load_snapshots
from content_engine.publish_history import PublishHistory, PublishRecord
from content_engine.threads_publisher import ThreadsAPIError, ThreadsClient
from content_engine.threads_review import ThreadsPendingDraft, save_pending
from scripts.collect_performance import main as collect_performance_main


class ScheduledPerformanceCLITests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.store = self.root / "tak_performance.json"
        self.history_path = self.root / "threads_publish_log.json"
        self.archive_path = self.root / "tak_media_archive.json"
        self.pending_path = self.root / "tak_threads_pending.json"
        self.content_id = "content-scheduled-1"
        self.knowledge_id = "knowledge-scheduled-1"
        self.generation_id = "generation-scheduled-1"
        self.post_id = "18085925933320004"

    def _seed(self, hours_ago: float) -> str:
        published_at = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
        history = PublishHistory(self.history_path)
        history.append(
            PublishRecord(
                content_id=self.content_id,
                published_at=published_at,
                threads_post_id=self.post_id,
                knowledge_id=self.knowledge_id,
                platform="threads",
                source_url="https://example.test/article",
            )
        )
        upsert_archive(
            self.archive_path,
            [
                MediaArchiveRecord(
                    content_id=self.content_id,
                    knowledge_id=self.knowledge_id,
                    platform="threads",
                    generation_status="valid",
                    original_title="original",
                    original_body="body",
                    rewritten_title="title",
                    rewritten_body="body",
                    source_url="https://example.test/article",
                    evidence=(),
                    evidence_unit_ids=(),
                    created_at=published_at,
                    review_status="approved",
                    generation_id=self.generation_id,
                )
            ],
        )
        save_pending(
            [
                ThreadsPendingDraft(
                    content_id=self.content_id,
                    knowledge_id=self.knowledge_id,
                    source_url="https://example.test/article",
                    evidence_unit_ids=(),
                    article_type=None,
                    knowledge_type="의견",
                    original_title="original",
                    original_body="body",
                    ai_rewritten_title="title",
                    ai_rewritten_body="body",
                    status="published",
                    created_at=published_at,
                    published_at=published_at,
                    threads_post_id=self.post_id,
                )
            ],
            self.pending_path,
        )
        return published_at

    def _args(self, *extra: str) -> list[str]:
        return [
            "--scheduled",
            "--store", str(self.store),
            "--publish-history", str(self.history_path),
            "--production-archive", str(self.archive_path),
            "--threads-pending", str(self.pending_path),
            *extra,
        ]

    def _run(self, args: list[str]) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = collect_performance_main(args)
        return result, stdout.getvalue(), stderr.getvalue()

    def test_before_24h_reports_waiting_and_never_creates_api_client(self):
        self._seed(hours_ago=23)
        with mock.patch.object(
            ThreadsClient, "from_environment", side_effect=AssertionError("no API before due")
        ) as client_factory:
            exit_code, output, _stderr = self._run(self._args("--confirm-live"))

        self.assertEqual(exit_code, 0)
        self.assertIn("측정 대기", output)
        client_factory.assert_not_called()
        self.assertFalse(self.store.exists())

    def test_scheduled_mode_rejects_manual_snapshot_arguments(self):
        with self.assertRaises(SystemExit):
            self._run(self._args("--title", "manual override"))

    def test_dry_run_due_target_does_not_call_api_or_save(self):
        self._seed(hours_ago=25)
        with mock.patch.object(
            ThreadsClient, "from_environment", side_effect=AssertionError("dry-run only")
        ) as client_factory:
            exit_code, output, _stderr = self._run(self._args("--dry-run"))

        self.assertEqual(exit_code, 0)
        self.assertIn("window=24h", output)
        self.assertIn("API 호출/저장 없음", output)
        client_factory.assert_not_called()
        self.assertFalse(self.store.exists())

    def test_api_failure_creates_no_snapshot_and_returns_failure(self):
        self._seed(hours_ago=25)

        def fail_transport(*_args):
            raise ThreadsAPIError("temporary API failure")

        fake_client = ThreadsClient(access_token="fake", transport=fail_transport)
        with mock.patch.dict(
            "os.environ",
            {"GITHUB_ACTIONS": "true", "TAK_PERFORMANCE_ALLOW_GITHUB_ACTIONS": "true"},
        ), mock.patch.object(ThreadsClient, "from_environment", return_value=fake_client):
            exit_code, _output, stderr = self._run(self._args("--confirm-live"))

        self.assertEqual(exit_code, 1)
        self.assertIn("temporary API failure", stderr)
        self.assertEqual(load_snapshots(self.store), [])

    def test_partial_metrics_are_saved_with_actual_zero_and_unavailable_fields(self):
        self._seed(hours_ago=25)
        fake_client = ThreadsClient(
            access_token="fake",
            transport=lambda *_args: {
                "data": [
                    {"name": "views", "values": [{"value": 0}]},
                    {"name": "likes", "values": [{"value": 2}]},
                ]
            },
        )
        with mock.patch.dict(
            "os.environ",
            {"GITHUB_ACTIONS": "true", "TAK_PERFORMANCE_ALLOW_GITHUB_ACTIONS": "true"},
        ), mock.patch.object(ThreadsClient, "from_environment", return_value=fake_client):
            exit_code, output, _stderr = self._run(self._args("--confirm-live"))

        self.assertEqual(exit_code, 0)
        self.assertIn("'views': 0", output)
        record = load_snapshots(self.store)[0]
        self.assertEqual(record.metrics, {"views": 0, "likes": 2})
        self.assertEqual(record.unavailable_metrics, ("replies", "reposts", "quotes", "shares"))
        self.assertEqual(record.generation_id, self.generation_id)
        self.assertEqual(record.measurement_window, "24h")
        self.assertEqual(record.external_post_id, self.post_id)
        self.assertEqual(record.collection_status, "collected")

    def test_already_collected_window_is_not_called_or_duplicated(self):
        published_at = self._seed(hours_ago=30)
        append_snapshot(
            self.store,
            PerformanceRecord(
                content_id=self.content_id,
                knowledge_id=self.knowledge_id,
                platform="threads",
                published_at=published_at,
                metric_collected_at=datetime.now(timezone.utc).isoformat(),
                metrics={"views": 1},
                source="threads_api",
                external_id=self.post_id,
                external_post_id=self.post_id,
                generation_id=self.generation_id,
                measurement_window="24h",
                collection_status="collected",
            ),
        )
        with mock.patch.object(
            ThreadsClient, "from_environment", side_effect=AssertionError("window already collected")
        ) as client_factory:
            exit_code, output, _stderr = self._run(self._args("--confirm-live"))

        self.assertEqual(exit_code, 0)
        self.assertIn("측정 대기", output)
        client_factory.assert_not_called()
        self.assertEqual(len(load_snapshots(self.store)), 1)


if __name__ == "__main__":
    unittest.main()