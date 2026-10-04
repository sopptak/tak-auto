import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from scripts.tak_workforce import main


class WorkforceCLITests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.task_path = Path(self.temp_dir.name) / "tasks.json"

    def run_cli(self, *args):
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            result = main(["--task-store", str(self.task_path), *args])
        return result, out.getvalue(), err.getvalue()

    def test_agent_and_tool_commands_list_and_show_registry_items(self):
        code, output, _ = self.run_cli("agent", "list")
        self.assertEqual(code, 0)
        self.assertEqual(output.count("AGENT-"), 12)
        code, output, _ = self.run_cli("agent", "show", "AGENT-09")
        self.assertEqual(code, 0)
        self.assertIn("bypass_publishing_gate", output)
        code, output, _ = self.run_cli("tool", "list")
        self.assertEqual(code, 0)
        self.assertEqual(output.count("TOOL-"), 16)
        code, output, _ = self.run_cli("tool", "show", "TOOL-01")
        self.assertEqual(code, 0)
        self.assertIn('"status": "CANDIDATE"', output)

    def test_task_create_route_status_and_approval_commands(self):
        code, output, _ = self.run_cli(
            "task", "create", "--type", "rnd_analysis", "--input-ref", "rnd:rnd-123"
        )
        self.assertEqual(code, 0)
        task_id = output.split(" | ", 1)[0].removeprefix("Task 생성: ")
        code, output, _ = self.run_cli("task", "route", task_id)
        self.assertEqual(code, 0)
        self.assertIn("AGENT-03", output)
        code, output, _ = self.run_cli("task", "status", task_id, "--status", "RUNNING")
        self.assertEqual(code, 0)
        code, output, _ = self.run_cli(
            "task", "create", "--type", "publish_preparation", "--action", "actual_threads_publish"
        )
        self.assertEqual(code, 0)
        approval_task_id = output.split(" | ", 1)[0].removeprefix("Task 생성: ")
        self.assertIn("approval=PENDING", output)
        self.run_cli("task", "route", approval_task_id)
        code, output, _ = self.run_cli("task", "approval", approval_task_id, "--decision", "APPROVED")
        self.assertEqual(code, 0)
        self.assertIn("status=ASSIGNED", output)

    def test_candidate_tool_selection_is_never_executable(self):
        _, output, _ = self.run_cli("task", "create", "--type", "shorts_production")
        task_id = output.split(" | ", 1)[0].removeprefix("Task 생성: ")
        self.run_cli("task", "route", task_id)
        code, output, _ = self.run_cli("tool", "select", task_id)
        self.assertEqual(code, 0)
        self.assertIn("executable=no", output)
        self.assertIn("Krea", output)


if __name__ == "__main__":
    unittest.main()