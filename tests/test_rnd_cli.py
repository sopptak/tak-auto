import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from scripts.tak_rnd import main


class RndRadarCLITests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        self.rnd_path = root / "rnd.json"
        self.idea_path = root / "ideas.json"

    def _run(self, *args):
        output = io.StringIO()
        errors = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = main(
                [
                    "--rnd-store", str(self.rnd_path),
                    "--idea-store", str(self.idea_path),
                    *args,
                ]
            )
        return code, output.getvalue(), errors.getvalue()

    def test_cli_add_import_query_promote_status_priority_and_validation(self):
        code, output, _ = self._run(
            "add-rnd", "--source", "threads", "--url", "https://threads.net/post/1",
            "--title", "Aside 브라우저 에이전트", "--summary", "브라우저 작업",
        )
        self.assertEqual(code, 0)
        rnd_id = output.split(": ", 1)[1].strip()

        code, output, _ = self._run("list-rnd")
        self.assertEqual(code, 0)
        self.assertIn(rnd_id, output)
        code, output, _ = self._run("promote", "--rnd-id", rnd_id, "--idea-title", "Browser execution layer")
        self.assertEqual(code, 0)
        self.assertIn(rnd_id, output)
        idea_id = json.loads(self.idea_path.read_text(encoding="utf-8"))[0]["id"]

        code, output, _ = self._run("set-status", "--type", "idea", "--id", idea_id, "--status", "approved")
        self.assertEqual(code, 0)
        self.assertIn("approved", output)
        code, output, _ = self._run("needs-validation")
        self.assertEqual(code, 0)
        self.assertIn(idea_id, output)

    def test_json_import_and_duplicate_command(self):
        input_path = Path(self.temp_dir.name) / "aside.json"
        input_path.write_text(
            json.dumps(
                {
                    "source": "threads", "url": "https://threads.net/post/2", "author": "@maker",
                    "title": "Same post", "text": "Useful idea", "tags": ["AI Agent"],
                }
            ),
            encoding="utf-8",
        )
        code, output, _ = self._run("import-rnd", "--file", str(input_path))
        self.assertEqual(code, 0)
        self.assertIn("1건", output)
        code, _, _ = self._run("import-rnd", "--file", str(input_path))
        self.assertEqual(code, 0)
        code, output, _ = self._run("duplicates", "--type", "rnd")
        self.assertEqual(code, 0)
        self.assertEqual(output, "")
        self.assertEqual(len(json.loads(self.rnd_path.read_text(encoding="utf-8"))), 1)

    def test_malformed_import_returns_error_without_store_write(self):
        input_path = Path(self.temp_dir.name) / "bad.json"
        input_path.write_text("{broken", encoding="utf-8")
        code, _, error = self._run("import-rnd", "--file", str(input_path))
        self.assertEqual(code, 1)
        self.assertIn("오류", error)
        self.assertFalse(self.rnd_path.exists())


if __name__ == "__main__":
    unittest.main()