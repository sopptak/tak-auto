"""Static safety checks for the scheduled Threads Performance workflow."""

from __future__ import annotations

from pathlib import Path
import unittest


WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "daily-performance-collection.yml"


class PerformanceWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = WORKFLOW.read_text(encoding="utf-8")
        cls.on_block = cls.source.split("permissions:", 1)[0]

    def test_has_daily_schedule_and_manual_dispatch(self):
        self.assertIn("schedule:", self.on_block)
        self.assertIn("cron: '30 7 * * *'", self.on_block)
        self.assertIn("workflow_dispatch:", self.on_block)
        self.assertNotIn("push:", self.on_block)

    def test_manual_dispatch_defaults_to_dry_run(self):
        dispatch = self.on_block.split("workflow_dispatch:", 1)[1]
        self.assertIn("default: true", dispatch)

    def test_live_step_requires_confirm_live_and_existing_thread_secret(self):
        live_step = self.source.split("id: collect_live", 1)[1].split("# If a later target", 1)[0]
        self.assertIn("--scheduled --confirm-live", live_step)
        self.assertIn("secrets.THREADS_ACCESS_TOKEN", live_step)
        self.assertIn('TAK_PERFORMANCE_ALLOW_GITHUB_ACTIONS: "true"', live_step)

    def test_dry_run_step_does_not_receive_credentials(self):
        dry_step = self.source.split("id: collect_dry_run", 1)[1].split("- name: Collect due", 1)[0]
        self.assertIn("--scheduled --dry-run", dry_step)
        self.assertNotIn("THREADS_ACCESS_TOKEN", dry_step)
        self.assertNotIn("secrets.", dry_step)

    def test_concurrency_queues_overlapping_runs(self):
        self.assertIn("group: tak-performance-collection", self.source)
        self.assertIn("cancel-in-progress: false", self.source)

    def test_only_performance_store_is_committed(self):
        self.assertIn("git add data/tak_performance.json", self.source)
        self.assertIn("if [ -f data/tak_performance.json ]", self.source)
        self.assertIn("git diff --cached --quiet -- data/tak_performance.json", self.source)
        self.assertNotIn("git add data/threads_publish_log.json", self.source)

    def test_successful_partial_data_is_committed_even_if_collector_fails(self):
        diff_step = self.source.split("id: performance_diff", 1)[1].split("- name: Commit and push", 1)[0]
        self.assertIn("always()", diff_step)
        self.assertIn("steps.collect_live.outcome == 'failure'", diff_step)
        self.assertIn("steps.collect_live.outcome == 'success'", diff_step)


if __name__ == "__main__":
    unittest.main()