import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).parents[1] / "scripts" / "render_youtube_short.py"


def _write_json(data) -> Path:
    handle = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    )
    json.dump(data, handle, ensure_ascii=False)
    handle.close()
    return Path(handle.name)


def _valid_script_dict(**overrides):
    data = {
        "title": "좋은 사람이 만만한 사람이 되지 않으려면",
        "subtitle": "사람에게 잘하되 내 중심까지 내주지는 마세요.",
        "cards": [
            "무조건 잘해주는 것과 좋은 사람이 되는 것은 다릅니다.",
            "선을 넘는 순간에는 분명하게 선을 그어야 합니다.",
        ],
        "takeaway": "좋은 사람이 되는 것과 만만한 사람이 되는 것은 다릅니다.",
        "brand": "티몽의 지혜",
    }
    data.update(overrides)
    return data


class RenderYouTubeShortCLITests(unittest.TestCase):
    def setUp(self):
        self.input_path = _write_json(_valid_script_dict())
        self.addCleanup(self.input_path.unlink, missing_ok=True)
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)

    def _run(self, args):
        return subprocess.run(
            [sys.executable, str(SCRIPT)] + args,
            capture_output=True,
            text=True,
        )

    def test_dry_run_executes_without_ffmpeg_call(self):
        output_path = Path(self.tmp_dir.name) / "preview.mp4"
        result = self._run(
            ["--input", str(self.input_path), "--output", str(output_path), "--dry-run"]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("TAK Shorts Render (Dry-run)", result.stdout)
        self.assertIn("카드 수: 2", result.stdout)
        self.assertIn("네트워크/렌더링 호출 없음", result.stdout)
        self.assertFalse(output_path.exists())

    def test_dry_run_rejects_missing_input_file(self):
        result = self._run(
            ["--input", "/nonexistent/script.json", "--output", "/tmp/out.mp4", "--dry-run"]
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("입력 파일을 찾을 수 없습니다", result.stderr)

    def test_dry_run_rejects_invalid_json(self):
        bad_path = Path(self.tmp_dir.name) / "bad.json"
        bad_path.write_text("{not valid json", encoding="utf-8")
        result = self._run(
            ["--input", str(bad_path), "--output", "/tmp/out.mp4", "--dry-run"]
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("올바른 JSON이 아닙니다", result.stderr)

    def test_dry_run_rejects_empty_cards(self):
        input_path = _write_json(_valid_script_dict(cards=[]))
        self.addCleanup(input_path.unlink, missing_ok=True)
        result = self._run(
            ["--input", str(input_path), "--output", "/tmp/out.mp4", "--dry-run"]
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cards가 비어 있습니다", result.stderr)

    def test_dry_run_rejects_missing_title(self):
        input_path = _write_json(_valid_script_dict(title="   "))
        self.addCleanup(input_path.unlink, missing_ok=True)
        result = self._run(
            ["--input", str(input_path), "--output", "/tmp/out.mp4", "--dry-run"]
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("title이 비어 있습니다", result.stderr)

    def test_dry_run_rejects_unknown_background_override(self):
        result = self._run(
            [
                "--input", str(self.input_path),
                "--output", "/tmp/out.mp4",
                "--background", "does_not_exist",
                "--dry-run",
            ]
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("알 수 없는 배경 스타일", result.stderr)

    def test_real_render_produces_playable_mp4(self):
        output_path = Path(self.tmp_dir.name) / "rendered.mp4"
        result = self._run(["--input", str(self.input_path), "--output", str(output_path)])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(output_path.exists())
        self.assertIn("1080x1920", result.stdout)
        self.assertIn("오디오 트랙: 없음", result.stdout)


if __name__ == "__main__":
    unittest.main()
