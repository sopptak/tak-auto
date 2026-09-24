"""scripts/render_youtube_short.py(6-40) CLI 검증.

``data/`` 아래 어떤 파일도 읽거나 쓰지 않는다 - ``--input``/``--output``
전부 tempfile을 가리킨다. ffmpeg가 없는 환경에서는 실제 렌더링 테스트를
건너뛴다(기존 저장소 관례).
"""

from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

import scripts.render_youtube_short as cli

ROOT = Path(__file__).resolve().parents[1]
WINDOWS_FONT = Path("C:/Windows/Fonts/malgun.ttf")


def _discover_ffmpeg() -> str | None:
    found = shutil.which("ffmpeg")
    if found:
        return found
    override = os.environ.get("TAK_TEST_FFMPEG")
    return override if override and Path(override).exists() else None


FFMPEG_PATH = _discover_ffmpeg()

_SAMPLE_PAYLOAD = {
    "title": "테스트 제목",
    "subtitle": "부제",
    "cards": ["카드 하나", "카드 둘"],
    "takeaway": "정리 문장",
    "brand": "티몽의 지혜",
}


class ParseHexColorTests(unittest.TestCase):
    def test_valid_hex_parses_to_rgb_tuple(self) -> None:
        self.assertEqual(cli._parse_hex_color("2E5B8A"), (0x2E, 0x5B, 0x8A))
        self.assertEqual(cli._parse_hex_color("#2E5B8A"), (0x2E, 0x5B, 0x8A))

    def test_invalid_hex_raises(self) -> None:
        import argparse

        with self.assertRaises(argparse.ArgumentTypeError):
            cli._parse_hex_color("notacolor")


class InvalidInputTests(unittest.TestCase):
    def test_missing_input_file_returns_nonzero_without_writing_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out.mp4"
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                code = cli.main(["--input", str(Path(tmp) / "missing.json"), "--output", str(output)])
            self.assertEqual(code, 1)
            self.assertFalse(output.exists())

    def test_malformed_script_json_returns_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bad_input = Path(tmp) / "bad.json"
            bad_input.write_text(json.dumps({"title": "제목만 있음"}), encoding="utf-8")  # cards/takeaway 없음
            output = Path(tmp) / "out.mp4"
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                code = cli.main(["--input", str(bad_input), "--output", str(output)])
            self.assertEqual(code, 1)
            self.assertFalse(output.exists())


@unittest.skipUnless(FFMPEG_PATH, "ffmpeg를 찾을 수 없습니다(PATH 또는 TAK_TEST_FFMPEG로 지정하세요).")
@unittest.skipUnless(WINDOWS_FONT.exists(), "한글 폰트(맑은 고딕)가 없는 환경입니다.")
class RealCliRenderTests(unittest.TestCase):
    def test_cli_renders_mp4_and_prints_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "script.json"
            input_path.write_text(json.dumps(_SAMPLE_PAYLOAD, ensure_ascii=False), encoding="utf-8")
            output_path = Path(tmp) / "out.mp4"

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = cli.main([
                    "--input", str(input_path), "--output", str(output_path),
                    "--ffmpeg", FFMPEG_PATH, "--accent", "2E5B8A",
                ])
            self.assertEqual(code, 0)
            self.assertTrue(output_path.exists())
            self.assertGreater(output_path.stat().st_size, 0)
            out = stdout.getvalue()
            self.assertIn("1080x1920", out)
            self.assertIn(str(output_path), out)


if __name__ == "__main__":
    unittest.main()
