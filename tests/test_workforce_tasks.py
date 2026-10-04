import json
from pathlib import Path
import tempfile
import unittest

from tak_workforce.models import Task
from tak_workforce.tasks import (
    TaskStoreError,
    create_task,
    get_task,
    load_tasks,
    route_task,
    set_task_approval,
    set_task_status,
)


class WorkforceTaskTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.path = Path(self.temp_dir.name) / "tasks.json"

    def test_create_route_and_parent_task_persist(self):
        parent = create_task("rnd_analysis", input_refs=["rnd:rnd-test"], path=self.path)
        routed = route_task(parent.task_id, self.path)
        self.assertEqual((routed.assigned_to, routed.department, routed.status), ("AGENT-03", "Market Analysis", "ASSIGNED"))
        child = create_task(
            "idea_strategy", created_by="AGENT-03", input_refs=["idea:idea-test"],
            parent_task_id=parent.task_id, path=self.path,
        )
        child = route_task(child.task_id, self.path)
        self.assertEqual(child.assigned_to, "AGENT-04")
        self.assertEqual(child.parent_task_id, parent.task_id)
        self.assertEqual(len(load_tasks(self.path)), 2)
        self.assertEqual(get_task(child.task_id, self.path), child)

    def test_invalid_agent_parent_task_type_and_priority_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "agent_id"):
            create_task("rnd_analysis", created_by="AGENT-99", path=self.path)
        with self.assertRaisesRegex(ValueError, "agent_id"):
            create_task("rnd_analysis", assigned_to="AGENT-99", path=self.path)
        with self.assertRaises(TaskStoreError):
            create_task("rnd_analysis", parent_task_id="task-missing", path=self.path)
        with self.assertRaises(TaskStoreError):
            create_task("unknown", path=self.path)
        with self.assertRaises(TaskStoreError):
            create_task("rnd_analysis", priority="P0", path=self.path)

    def test_sensitive_actions_require_approval_before_route_run_or_completion(self):
        task = create_task(
            "publish_preparation", requested_actions=["actual_threads_publish"], path=self.path
        )
        self.assertTrue(task.approval_required)
        self.assertEqual(task.approval_status, "PENDING")
        task = route_task(task.task_id, self.path)
        self.assertEqual((task.assigned_to, task.status), ("AGENT-09", "WAITING_APPROVAL"))
        with self.assertRaises(TaskStoreError):
            set_task_status(task.task_id, "RUNNING", path=self.path)
        with self.assertRaises(TaskStoreError):
            set_task_status(task.task_id, "COMPLETED", path=self.path)
        task = set_task_approval(task.task_id, "approved", self.path)
        self.assertEqual((task.approval_status, task.status), ("APPROVED", "ASSIGNED"))
        task = set_task_status(task.task_id, "RUNNING", path=self.path)
        task = set_task_status(task.task_id, "COMPLETED", result_summary="사람 승인 후 완료 기록", path=self.path)
        self.assertEqual(task.status, "COMPLETED")

    def test_running_task_cannot_be_rerouted(self):
        task = create_task("engineering", assigned_to="AGENT-10", path=self.path)
        task = set_task_status(task.task_id, "RUNNING", path=self.path)
        with self.assertRaises(TaskStoreError):
            route_task(task.task_id, self.path)
        with self.assertRaises(TaskStoreError):
            set_task_status(task.task_id, "ASSIGNED", path=self.path)

    def test_distribution_agent_tasks_are_held_and_rejection_cancels(self):
        task = create_task("publish_preparation", assigned_to="AGENT-09", path=self.path)
        self.assertEqual((task.approval_required, task.status), (True, "WAITING_APPROVAL"))
        rejected = set_task_approval(task.task_id, "rejected", self.path)
        self.assertEqual((rejected.approval_status, rejected.status), ("REJECTED", "CANCELLED"))

    def test_invalid_status_and_transition_and_retry_count(self):
        task = create_task("engineering", assigned_to="AGENT-10", path=self.path)
        with self.assertRaises(TaskStoreError):
            set_task_status(task.task_id, "DONE", path=self.path)
        task = set_task_status(task.task_id, "RUNNING", path=self.path)
        task = set_task_status(task.task_id, "FAILED", error="local test failure", path=self.path)
        task = set_task_status(task.task_id, "ASSIGNED", path=self.path)
        self.assertEqual(task.retry_count, 1)
        with self.assertRaises(TaskStoreError):
            set_task_status(task.task_id, "COMPLETED", path=self.path)

    def test_malformed_task_store_is_rejected(self):
        self.path.write_text(json.dumps([{"task_id": "invalid"}]), encoding="utf-8")
        with self.assertRaises(TaskStoreError):
            load_tasks(self.path)

    def test_task_model_rejects_inconsistent_approval_and_retry(self):
        raw = {
            "task_id": "task-test", "created_at": "2026-10-04T00:00:00+00:00",
            "created_by": "AGENT-01", "assigned_to": "", "department": "Unassigned",
            "task_type": "rnd_analysis", "priority": "NORMAL", "input_refs": [], "output_refs": [],
            "status": "PENDING", "approval_required": True, "approval_status": "NOT_REQUIRED",
            "parent_task_id": None, "retry_count": 0, "result_summary": "", "error": "",
        }
        with self.assertRaises(ValueError):
            Task.from_mapping(raw)
        raw["approval_required"] = False
        raw["retry_count"] = -1
        with self.assertRaises(ValueError):
            Task.from_mapping(raw)


if __name__ == "__main__":
    unittest.main()