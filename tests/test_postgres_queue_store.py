from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import os
import subprocess
import sys
import tempfile
from textwrap import dedent
import unittest
from unittest.mock import Mock, patch

from content_engine.postgres_queue_store import PostgresQueueStore, open_publishing_queue
from content_engine.publishing_queue import PublishingQueue, QueueError, QueueStoreError
from scripts import transfer_publishing_queue
from scripts.run_publishing_queue import run_once


class QueueBackendTests(unittest.TestCase):
    def test_connection_failure_logs_category_without_secret_or_hostname(self):
        import psycopg

        error = psycopg.OperationalError("certificate verify failed for private.example; password=private-token")
        store = PostgresQueueStore("unused", connect=Mock(side_effect=error))
        with self.assertLogs("content_engine.postgres_queue_store", level="WARNING") as captured:
            with self.assertRaises(QueueStoreError) as raised:
                store.ready()
        self.assertIn("(tls)", captured.output[0])
        for secret in ("private-token", "private.example"):
            self.assertNotIn(secret, str(raised.exception))
            self.assertNotIn(secret, captured.output[0])

    def test_unexpected_connection_failure_is_sanitized(self):
        error = RuntimeError("connect failed for private.example; password=private-token")
        store = PostgresQueueStore("unused", connect=Mock(side_effect=error))
        with self.assertLogs("content_engine.postgres_queue_store", level="WARNING") as captured:
            with self.assertRaises(QueueStoreError) as raised:
                store.ready()
        self.assertIn("(database_unavailable)", captured.output[0])
        for secret in ("private-token", "private.example"):
            self.assertNotIn(secret, str(raised.exception))
            self.assertNotIn(secret, captured.output[0])

    def test_postgres_configuration_never_falls_back_to_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "queue.json"
            for values in ({"TAK_AUTO_QUEUE_BACKEND": "unknown"}, {"TAK_AUTO_QUEUE_BACKEND": "postgres"}):
                with self.subTest(values=values), self.assertRaises(QueueStoreError):
                    open_publishing_queue(path, values)
            self.assertEqual(open_publishing_queue(path, {}).snapshot()["items"], [])
            self.assertFalse(path.exists())

    def test_disabled_worker_does_not_load_database_or_publisher(self):
        with patch("scripts.run_publishing_queue.open_publishing_queue") as open_queue, \
                patch("scripts.run_publishing_queue.load_publisher") as load_publisher:
            self.assertEqual(run_once("unused.json", enabled=False), [])
        open_queue.assert_not_called()
        load_publisher.assert_not_called()

    def test_import_preview_does_not_open_a_database(self):
        with patch.object(transfer_publishing_queue, "PostgresQueueStore") as store:
            self.assertEqual(transfer_publishing_queue.main(["--empty"]), 0)
        store.assert_not_called()

    def test_import_rejects_processing_and_changed_idempotency_key(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "queue.json"
            now = datetime(2026, 11, 24, tzinfo=timezone.utc)
            queue = PublishingQueue(path)
            queue.enqueue_approved(
                content_id="content", platform="threads", payload={"body": "승인된 문안"},
                scheduled_at=now + timedelta(seconds=5), approved_by="operator", now=now,
            )
            original = transfer_publishing_queue.load_import_state(path)
            for mutation in ({"status": "processing"}, {"idempotency_key": "different"}, {"approved": "true"}):
                with self.subTest(mutation=mutation):
                    state = dict(original, items=[dict(original["items"][0], **mutation)])
                    path.write_text(json.dumps(state), encoding="utf-8")
                    with self.assertRaises(QueueError):
                        transfer_publishing_queue.load_import_state(path)

    def test_export_round_trips_file_state_and_never_overwrites(self):
        state = {"version": 1, "items": [], "history": []}
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "export.json"
            transfer_publishing_queue.export_state(destination, state)
            with self.assertRaisesRegex(QueueError, "이미 있습니다"):
                transfer_publishing_queue.export_state(destination, dict(state, newer=True))
            self.assertEqual(transfer_publishing_queue.load_import_state(destination), state)
            self.assertEqual(list(destination.parent.iterdir()), [destination])


@unittest.skipUnless(os.getenv("TAK_TEST_QUEUE_POSTGRES_DSN"), "requires disposable local PostgreSQL")
class LocalPostgresQueueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        from psycopg.conninfo import conninfo_to_dict

        cls.psycopg = psycopg
        cls.dsn = os.environ["TAK_TEST_QUEUE_POSTGRES_DSN"]
        config = conninfo_to_dict(cls.dsn)
        if config.get("host") != "127.0.0.1" or "hostaddr" in config or "service" in config:
            raise ValueError("integration tests require an explicit loopback PostgreSQL server")
        # Require a fresh database. Do not repair or delete an existing schema.
        migration = next((Path(__file__).parents[1] / "supabase" / "migrations").glob("*_publishing_queue.sql"))
        with psycopg.connect(cls.dsn) as connection:
            connection.execute("CREATE ROLE anon NOLOGIN; CREATE ROLE authenticated NOLOGIN; CREATE ROLE service_role NOLOGIN")
            connection.execute(migration.read_text(encoding="utf-8"))

    def setUp(self):
        # Reset only the table created by this test class in its disposable database.
        with self.psycopg.connect(self.dsn) as connection:
            connection.execute("TRUNCATE tak_auto_private.publishing_queue")
        self.store = self._store("tak_auto_queue_runtime")
        self.importer = self._store("tak_auto_queue_importer")
        self.now = datetime(2026, 11, 24, tzinfo=timezone.utc)

    def _store(self, role):
        def connect(dsn, **options):
            options.update(sslmode="disable", sslrootcert=None, options=f"-c role={role}")
            return self.psycopg.connect(dsn, **options)

        return PostgresQueueStore(self.dsn, connect=connect)

    def _seed(self):
        self.assertTrue(self.importer.initialize({"version": 1, "items": [], "history": []}))
        queue = PublishingQueue("unused.json", store=self.store)
        queue.enqueue_approved(
            content_id="content", platform="threads", payload={"body": "승인된 문안"},
            scheduled_at=self.now + timedelta(seconds=1), approved_by="operator", now=self.now,
        )
        return queue

    def test_initial_import_and_permissions(self):
        state = {"version": 1, "items": [], "history": []}
        self.assertFalse(self.store.ready())
        with self.assertRaisesRegex(QueueStoreError, "초기화"):
            self.store.read()
        with self.assertRaises(QueueStoreError):
            self.store.initialize(state)
        self.assertTrue(self.importer.initialize(state))
        self.assertTrue(self.store.ready())
        self.assertFalse(self.importer.ready())
        self.assertFalse(self.importer.initialize(state))
        with self.assertRaisesRegex(QueueStoreError, "다른 데이터"):
            self.importer.initialize(dict(state, extra=True))
        with self.assertRaises(QueueStoreError):
            self.importer.write(0, state)
        for role in ("anon", "authenticated", "service_role"):
            with self.subTest(role=role), self.assertRaises(QueueStoreError):
                self._store(role).read()

    def test_concurrent_clients_claim_job_at_most_once(self):
        queue = self._seed()
        due = self.now + timedelta(seconds=2)
        child_worker = dedent("""
            from datetime import datetime
            from pathlib import Path
            import os
            import sys
            import time
            import psycopg
            from content_engine.postgres_queue_store import PostgresQueueStore
            from content_engine.publishing_queue import PublishingQueue, QueueStoreError

            directory = Path(sys.argv[1])
            worker = int(sys.argv[2])
            now = datetime.fromisoformat(sys.argv[3])

            def connect(dsn, **options):
                options.update(sslmode="disable", sslrootcert=None, options="-c role=tak_auto_queue_runtime")
                return psycopg.connect(dsn, **options)

            class SharedRead(PostgresQueueStore):
                def read(self):
                    result = super().read()
                    (directory / f"ready-{worker}").touch()
                    deadline = time.monotonic() + 8
                    while not (directory / f"ready-{1 - worker}").exists():
                        if time.monotonic() >= deadline:
                            raise TimeoutError("other worker did not reach the same revision")
                        time.sleep(.01)
                    return result

            def publisher(*_args):
                with (directory / "publisher-called").open("x", encoding="utf-8") as handle:
                    handle.write("post-123")
                return "post-123"

            store = SharedRead(os.environ["TAK_TEST_QUEUE_POSTGRES_DSN"], connect=connect)
            try:
                PublishingQueue(directory / "unused.json", store=store).run_due(publisher, enabled=True, now=now)
            except QueueStoreError:
                sys.exit(3)
        """)
        with tempfile.TemporaryDirectory() as directory:
            processes = [
                subprocess.Popen(
                    [sys.executable, "-c", child_worker, directory, str(worker), due.isoformat()],
                    cwd=Path(__file__).parents[1], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                )
                for worker in range(2)
            ]
            try:
                results = [process.communicate(timeout=20) for process in processes]
                self.assertEqual(sorted(process.returncode for process in processes), [0, 3], results)
                self.assertEqual((Path(directory) / "publisher-called").read_text(), "post-123")
                self.assertFalse((Path(directory) / "unused.json").exists())
            finally:
                for process in processes:
                    if process.poll() is None:
                        process.kill()
                        process.communicate()
        self.assertEqual(queue.snapshot()["history"][0]["remote_id"], "post-123")

    def test_outcome_conflict_leaves_processing_for_review_without_republishing(self):
        queue = self._seed()
        due = self.now + timedelta(seconds=2)

        def competing_write(*_args):
            other = self._store("tak_auto_queue_runtime")
            revision, state = other.read()
            self.assertEqual(state["items"][0]["status"], "processing")
            other.write(revision, state)
            return "post-123"

        publisher = Mock(side_effect=competing_write)
        with self.assertRaises(QueueStoreError):
            queue.run_due(publisher, enabled=True, now=due)
        self.assertEqual(queue.snapshot()["items"][0]["status"], "processing")
        result = queue.run_due(publisher, enabled=True, now=due + timedelta(minutes=6))
        self.assertEqual(result[0]["status"], "needs_review")
        publisher.assert_called_once()

    def test_unknown_claim_commit_never_calls_publisher(self):
        queue = self._seed()
        due = self.now + timedelta(seconds=2)
        write = self.store.write

        def write_then_disconnect(revision, state):
            write(revision, state)
            raise QueueStoreError("simulated lost commit acknowledgment")

        publisher = Mock(return_value="must-not-publish")
        with patch.object(self.store, "write", side_effect=write_then_disconnect):
            with self.assertRaises(QueueStoreError):
                queue.run_due(publisher, enabled=True, now=due)
        self.assertEqual(queue.snapshot()["items"][0]["status"], "processing")
        review = queue.run_due(publisher, enabled=True, now=due + timedelta(minutes=6))
        self.assertEqual(review[0]["status"], "needs_review")
        publisher.assert_not_called()

    def test_numeric_payload_survives_import_and_export_with_same_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.json"
            approval = {
                "content_id": "numeric-content", "platform": "threads",
                "payload": {"body": "문안", "weight": 1e20, "zero": -0.0},
                "scheduled_at": self.now + timedelta(seconds=1), "approved_by": "operator", "now": self.now,
            }
            original = PublishingQueue(source).enqueue_approved(**approval)
            imported = transfer_publishing_queue.load_import_state(source)
            self.assertTrue(self.importer.initialize(imported))
            self.assertFalse(self.importer.initialize(dict(reversed(tuple(imported.items())))))

            queue = PublishingQueue(root / "unused.json", store=self.store)
            self.assertEqual(queue.enqueue_approved(**approval)["id"], original["id"])
            before = queue.snapshot()["items"][0]
            self.assertIsInstance(before["payload"]["weight"], float)
            self.assertEqual(repr(before["payload"]["zero"]), "-0.0")
            destination = root / "export.json"
            transfer_publishing_queue.export_state(destination, queue.snapshot())
            self.assertEqual(transfer_publishing_queue.load_import_state(destination), imported)
