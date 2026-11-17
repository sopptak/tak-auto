import unittest
from unittest.mock import patch

from scripts import start_tak_auto_mvp


class StartTakAutoMvpTests(unittest.TestCase):
    @patch("scripts.start_tak_auto_mvp.subprocess.run")
    def test_skip_collect_builds_report_without_starting_dashboard(self, run):
        run.return_value.returncode = 0
        code = start_tak_auto_mvp.main(["--skip-collect", "--no-dashboard"])
        self.assertEqual(code, 0)
        self.assertEqual(run.call_count, 1)
        command = run.call_args.args[0]
        self.assertIn("scripts/run_trend_report.py", command)

    @patch("scripts.start_tak_auto_mvp.subprocess.run")
    def test_default_runs_collect_report_and_dashboard(self, run):
        run.return_value.returncode = 0
        code = start_tak_auto_mvp.main([])
        self.assertEqual(code, 0)
        self.assertEqual(run.call_count, 3)
        commands = [call.args[0] for call in run.call_args_list]
        self.assertIn("scripts/run_scout.py", commands[0])
        self.assertIn("scripts/run_trend_report.py", commands[1])
        self.assertIn("scripts/run_scout_dashboard.py", commands[2])

    @patch("scripts.start_tak_auto_mvp.subprocess.run")
    def test_stops_when_collection_fails(self, run):
        run.return_value.returncode = 1
        code = start_tak_auto_mvp.main([])
        self.assertEqual(code, 1)
        self.assertEqual(run.call_count, 1)


if __name__ == "__main__":
    unittest.main()
