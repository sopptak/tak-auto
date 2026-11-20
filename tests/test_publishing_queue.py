import json
import tempfile
import unittest
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from content_engine.publishing_queue import (
    MAX_ATTEMPTS, PermanentPublishError, PublishUncertainError, PublishingQueue,
    QueueError, queue_dashboard,
)
from scripts.run_publishing_queue import run_once


class PublishingQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.path = Path(self.temp_dir.name) / "queue.json"
        self.queue = PublishingQueue(self.path)
        self.now = datetime(2026, 11, 17, 0, 0, tzinfo=timezone.utc)

    def enqueue(self, *, platform="blog", payload=None, when=None):
        return self.queue.enqueue_approved(
            content_id="trend-content-1", platform=platform,
            payload=payload or {"title": "검토된 제목", "body": "검토된 원고"},
            scheduled_at=when or self.now + timedelta(minutes=1),
            approved_by="operator", now=self.now,
        )

    def test_enqueue_persists_approval_and_is_idempotent(self):
        first = self.enqueue()
        second = self.enqueue()
        self.assertEqual(first["id"], second["id"])
        self.assertTrue(first["approved"])
        self.assertEqual(first["status"], "scheduled")
        self.assertEqual(first["max_attempts"], MAX_ATTEMPTS)
        self.assertEqual(len(PublishingQueue(self.path).snapshot()["items"]), 1)
        if os.name == "posix":
            self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_facebook_is_an_allowed_approved_queue_platform(self):
        item = self.enqueue(platform="facebook")
        self.assertEqual(item["platform"], "facebook")

    def test_approval_requires_timezone_future_schedule_and_supported_platform(self):
        with self.assertRaises(QueueError):
            self.enqueue(when=self.now - timedelta(seconds=1))
        with self.assertRaises(QueueError):
            self.enqueue(when=datetime(2026, 11, 18))
        with self.assertRaises(QueueError):
            self.enqueue(platform="unknown")

    def test_disabled_worker_does_not_call_publisher_or_change_queue(self):
        self.enqueue()
        called = []
        result = self.queue.run_due(lambda *args: called.append(args), enabled=False, now=self.now + timedelta(minutes=2))
        self.assertEqual(result, [])
        self.assertEqual(called, [])
        self.assertEqual(self.queue.snapshot()["items"][0]["attempts"], 0)

    def test_future_job_waits_and_success_records_platform_history(self):
        item = self.enqueue()
        calls = []
        publisher = lambda platform, payload, key: calls.append((platform, payload["_content_id"], key)) or "remote-42"
        self.assertEqual(self.queue.run_due(publisher, enabled=True, now=self.now), [])
        due = self.now + timedelta(minutes=2)
        result = self.queue.run_due(publisher, enabled=True, now=due)
        self.assertEqual(result[0]["status"], "published")
        self.assertEqual(calls, [("blog", item["content_id"], item["idempotency_key"])])
        self.assertNotIn("_content_id", item["payload"])
        history = self.queue.snapshot()["history"]
        self.assertEqual(history[0]["platform"], "blog")
        self.assertEqual(history[0]["remote_id"], "remote-42")
        self.assertEqual(self.queue.run_due(publisher, enabled=True, now=due), [])
        self.assertEqual(len(calls), 1)

    def test_reject_cannot_hide_inflight_or_uncertain_publish_state(self):
        item = self.enqueue()
        for status in ("processing", "needs_review"):
            with self.subTest(status=status):
                data = self.queue.snapshot()
                data["items"][0]["status"] = status
                self.path.write_text(json.dumps(data), encoding="utf-8")
                with self.assertRaisesRegex(QueueError, "게시 결과를 확인"):
                    self.queue.reject(item["id"], now=self.now + timedelta(minutes=2))
                self.assertEqual(self.queue.snapshot()["items"][0]["status"], status)

    def test_reject_marks_scheduled_work_as_rejected(self):
        item = self.enqueue()
        rejected = self.queue.reject(item["id"], now=self.now + timedelta(seconds=1))
        self.assertEqual(rejected["status"], "rejected")

    def test_reject_fails_closed_for_malformed_state(self):
        item = self.enqueue()
        data = self.queue.snapshot()
        data["items"][0]["status"] = ["scheduled"]
        self.path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(QueueError, "현재 상태"):
            self.queue.reject(item["id"], now=self.now + timedelta(seconds=1))

    def test_published_history_retains_knowledge_source_and_title(self):
        self.enqueue(platform="facebook", payload={
            "title": "Facebook 제목", "body": "승인된 본문",
            "_knowledge_id": "trend-preview-k123",
            "_source_url": "https://example.test/source",
        })
        self.queue.run_due(
            lambda *_args: "123_456", enabled=True,
            now=self.now + timedelta(minutes=2),
        )
        history = self.queue.snapshot()["history"][0]
        self.assertEqual(history["knowledge_id"], "trend-preview-k123")
        self.assertEqual(history["source_url"], "https://example.test/source")
        self.assertEqual(history["title"], "Facebook 제목")

    def test_retry_backoff_stops_after_three_attempts(self):
        self.enqueue()
        first_time = self.now + timedelta(minutes=2)
        calls = []

        def fail(*_args):
            calls.append(1)
            raise RuntimeError("temporary outage")

        first = self.queue.run_due(fail, enabled=True, now=first_time)[0]
        self.assertEqual(first["status"], "scheduled")
        self.assertEqual(first["attempts"], 1)
        self.assertEqual(self.queue.run_due(fail, enabled=True, now=first_time + timedelta(seconds=59)), [])
        second_time = first_time + timedelta(seconds=61)
        second = self.queue.run_due(fail, enabled=True, now=second_time)[0]
        self.assertEqual(second["attempts"], 2)
        third = self.queue.run_due(fail, enabled=True, now=second_time + timedelta(seconds=121))[0]
        self.assertEqual(third["status"], "failed")
        self.assertEqual(third["attempts"], MAX_ATTEMPTS)
        self.assertEqual(len(calls), MAX_ATTEMPTS)
        self.assertEqual(self.queue.run_due(fail, enabled=True, now=second_time + timedelta(days=1)), [])

    def test_uncertain_result_is_persisted_for_human_review_without_retry(self):
        self.enqueue()
        calls = []

        def uncertain(*_args):
            calls.append(1)
            in_flight = self.queue.snapshot()["items"][0]
            self.assertEqual(in_flight["status"], "processing")
            self.assertEqual(in_flight["attempts"], 1)
            raise PublishUncertainError("provider response was lost", remote_id="post-123")

        result = self.queue.run_due(uncertain, enabled=True, now=self.now + timedelta(minutes=2))[0]
        self.assertEqual(result["status"], "needs_review")
        self.assertEqual(result["remote_id"], "post-123")
        self.assertEqual(self.queue.run_due(uncertain, enabled=True, now=self.now + timedelta(days=1)), [])
        self.assertEqual(len(calls), 1)

    def test_processing_item_with_timezone_free_timestamp_requires_review(self):
        self.enqueue()
        data = self.queue.snapshot()
        data["items"][0].update(status="processing", updated_at="2026-11-17T00:02:00")
        self.path.write_text(json.dumps(data), encoding="utf-8")
        calls = []

        result = self.queue.run_due(
            lambda *_args: calls.append(1) or "should-not-publish",
            enabled=True,
            now=self.now + timedelta(minutes=10),
        )

        self.assertEqual(result[0]["status"], "needs_review")
        self.assertIn("게시 여부를 먼저 확인", result[0]["last_error"])
        self.assertEqual(calls, [])

    def test_malformed_attempt_count_requires_review_without_retry_or_publish(self):
        for malformed in ("unknown", -1, 1.5, True, False, None):
            with self.subTest(attempts=malformed):
                item = self.enqueue()
                data = self.queue.snapshot()
                data["items"][0].update(status="needs_review", attempts=malformed)
                self.path.write_text(json.dumps(data), encoding="utf-8")
                html = queue_dashboard(data, publishing_enabled=True)
                self.assertIn("확인 필요", html)
                self.assertNotIn("/queue/retry", html)
                calls = []
                result = self.queue.run_due(
                    lambda *args: calls.append(args) or "must-not-publish",
                    enabled=True, now=self.now + timedelta(minutes=2),
                )[0]
                self.assertEqual(result["status"], "needs_review")
                self.assertEqual(result["attempts"], MAX_ATTEMPTS)
                self.assertIn("시도 횟수 기록", result["last_error"])
                self.assertEqual(calls, [])
                with self.assertRaisesRegex(QueueError, "최대 시도"):
                    self.queue.retry_after_review(
                        item["id"], scheduled_at=self.now + timedelta(minutes=3),
                        reviewed_by="operator", now=self.now + timedelta(minutes=2),
                    )
                self.path.unlink(missing_ok=True)

    def test_queue_reader_rejects_non_object_items_and_history_rows(self):
        for field in ("items", "history"):
            with self.subTest(field=field):
                data = {"version": 1, "items": [], "history": []}
                data[field].append("not an object")
                self.path.write_text(json.dumps(data), encoding="utf-8")
                with self.assertRaisesRegex(QueueError, "항목 형식"):
                    self.queue.snapshot()
                self.path.unlink(missing_ok=True)

    def test_empty_remote_id_is_uncertain_and_requires_human_review(self):
        for remote_id in ("", "   ", None):
            with self.subTest(remote_id=remote_id):
                self.enqueue(payload={"title": f"콘텐츠 {remote_id!r}"})
                result = self.queue.run_due(
                    lambda *_args: remote_id, enabled=True,
                    now=self.now + timedelta(minutes=2),
                )[0]
                self.assertEqual(result["status"], "needs_review")
                self.assertIn("외부 게시 ID가 없습니다", result["last_error"])
                self.assertEqual(self.queue.snapshot()["history"], [])
                self.assertEqual(
                    self.queue.run_due(lambda *_args: "should-not-retry", enabled=True,
                                       now=self.now + timedelta(days=1)),
                    [],
                )
                self.path.unlink(missing_ok=True)

    def test_permanent_adapter_error_is_not_retried(self):
        self.enqueue()
        calls = []

        def unsupported(*_args):
            calls.append(1)
            raise PermanentPublishError("platform not supported")

        result = self.queue.run_due(unsupported, enabled=True, now=self.now + timedelta(minutes=2))[0]
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["attempts"], 1)
        self.assertEqual(self.queue.run_due(unsupported, enabled=True, now=self.now + timedelta(days=1)), [])
        self.assertEqual(len(calls), 1)

    def test_operator_can_confirm_uncertain_post_and_record_remote_history(self):
        item = self.enqueue()
        due = self.now + timedelta(minutes=2)
        self.queue.run_due(
            lambda *_args: (_ for _ in ()).throw(PublishUncertainError("response lost")),
            enabled=True, now=due,
        )
        resolved = self.queue.confirm_published(
            item["id"], remote_id="https://threads.example/post/123", reviewed_by="operator", now=due + timedelta(minutes=1),
        )
        self.assertEqual(resolved["status"], "published")
        self.assertEqual(resolved["last_review"]["decision"], "confirmed_published")
        self.assertEqual([event["decision"] for event in resolved["review_history"]], ["confirmed_published"])
        self.assertEqual(self.queue.snapshot()["history"][0]["remote_id"], "https://threads.example/post/123")

    def test_operator_can_retry_only_after_confirming_not_published(self):
        item = self.enqueue()
        due = self.now + timedelta(minutes=2)
        self.queue.run_due(
            lambda *_args: (_ for _ in ()).throw(PublishUncertainError("response lost")),
            enabled=True, now=due,
        )
        retry_at = due + timedelta(minutes=1)
        reviewed = self.queue.retry_after_review(
            item["id"], scheduled_at=retry_at, reviewed_by="operator", now=due + timedelta(seconds=1),
        )
        self.assertEqual(reviewed["status"], "scheduled")
        self.assertEqual(reviewed["attempts"], 1)
        self.assertEqual(reviewed["last_review"]["decision"], "confirmed_not_published")
        self.assertEqual([event["decision"] for event in reviewed["review_history"]], ["confirmed_not_published"])
        calls = []
        self.queue.run_due(lambda *_args: calls.append(1) or "remote-after-check", enabled=True, now=retry_at)
        self.assertEqual(calls, [1])

    def test_review_history_retains_each_decision_across_retry_and_confirmation(self):
        item = self.enqueue()
        first_due = self.now + timedelta(minutes=2)
        uncertain = lambda *_args: (_ for _ in ()).throw(PublishUncertainError("response lost"))

        self.queue.run_due(uncertain, enabled=True, now=first_due)
        retry_at = first_due + timedelta(minutes=2)
        self.queue.retry_after_review(
            item["id"], scheduled_at=retry_at, reviewed_by="first-operator",
            now=first_due + timedelta(seconds=30),
        )
        self.queue.run_due(uncertain, enabled=True, now=retry_at)
        resolved = self.queue.confirm_published(
            item["id"], remote_id="remote-2", reviewed_by="second-operator",
            now=retry_at + timedelta(seconds=30),
        )

        self.assertEqual(
            [event["decision"] for event in resolved["review_history"]],
            ["confirmed_not_published", "confirmed_published"],
        )
        self.assertEqual(resolved["review_history"][0]["reviewed_by"], "first-operator")
        self.assertEqual(resolved["review_history"][1]["remote_id"], "remote-2")
        html = queue_dashboard({"items": [resolved], "history": []}, publishing_enabled=False)
        self.assertIn("운영자 확인 기록 (2)", html)
        self.assertIn("미게시 확인 후 재시도 예약", html)
        self.assertIn("게시 완료 확인", html)

    def test_dashboard_escapes_review_history_fields(self):
        html = queue_dashboard({
            "items": [{
                "id": "queue-1", "content_id": "content-1", "platform": "threads",
                "status": "published", "attempts": 1, "max_attempts": MAX_ATTEMPTS,
                "review_history": [{
                    "decision": "confirmed_published", "reviewed_by": "<script>alert(1)</script>",
                    "reviewed_at": "<img src=x>", "remote_id": "<iframe>remote</iframe>",
                }],
            }],
            "history": [],
        }, publishing_enabled=False)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertIn("&lt;img src=x&gt;", html)
        self.assertIn("&lt;iframe&gt;remote&lt;/iframe&gt;", html)
        self.assertNotIn("<script>alert(1)</script>", html)

    def test_malformed_review_history_prevents_reconciliation_without_mutation(self):
        item = self.enqueue()
        self.queue.run_due(
            lambda *_args: (_ for _ in ()).throw(PublishUncertainError("response lost")),
            enabled=True, now=self.now + timedelta(minutes=2),
        )
        data = self.queue.snapshot()
        data["items"][0]["review_history"] = "corrupted"
        self.path.write_text(json.dumps(data), encoding="utf-8")

        with self.assertRaisesRegex(QueueError, "검토 이력 형식"):
            self.queue.confirm_published(
                item["id"], remote_id="remote-1", reviewed_by="operator",
                now=self.now + timedelta(minutes=3),
            )
        self.assertEqual(self.queue.snapshot()["items"][0]["status"], "needs_review")
        self.assertEqual(self.queue.snapshot()["history"], [])

    def test_dashboard_offers_manual_reconciliation_only_when_required(self):
        item = self.enqueue()
        data = self.queue.snapshot()
        data["items"][0]["status"] = "needs_review"
        html = queue_dashboard(data, publishing_enabled=False)
        self.assertIn("/queue/confirm-published", html)
        self.assertIn("/queue/retry", html)
        self.assertIn(item["id"], html)

    def test_platforms_have_separate_idempotency_and_history(self):
        self.enqueue(platform="blog")
        self.enqueue(platform="threads")
        calls = []
        self.queue.run_due(lambda platform, _payload, _key: calls.append(platform) or platform,
                           enabled=True, now=self.now + timedelta(minutes=2))
        self.assertEqual(set(calls), {"blog", "threads"})
        self.assertEqual({row["platform"] for row in self.queue.snapshot()["history"]}, {"blog", "threads"})

    def test_dashboard_shows_disabled_state_counts_queue_and_history(self):
        self.enqueue()
        html = queue_dashboard(self.queue.snapshot(), publishing_enabled=False)
        self.assertIn("비활성화 (기본값)", html)
        self.assertIn("scheduled: 1", html)
        self.assertIn("검토된 제목", html)

    def test_cli_worker_is_disabled_by_default_and_fails_closed_without_adapter(self):
        self.enqueue()
        with patch("scripts.run_publishing_queue.load_publisher") as load_publisher:
            self.assertEqual(run_once(self.path, enabled=False,
                                      publisher_spec="scripts.run_publishing_queue:load_publisher"), [])
        load_publisher.assert_not_called()
        with self.assertRaisesRegex(RuntimeError, "어댑터"):
            run_once(self.path, enabled=True)
        self.assertEqual(self.queue.snapshot()["items"][0]["attempts"], 0)


if __name__ == "__main__":
    unittest.main()

