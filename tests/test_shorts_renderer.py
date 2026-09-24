"""content_engine.shorts_renderer(6-40) 검증.

docs/6-30이 CASE C(EXTERNAL_MACHINE_REQUIRED)로 판정한 렌더러를 최소
사양으로 새로 구현한 모듈이다 - content_engine.shorts_script(무수정)를
재사용하고, Pillow + 로컬 ffmpeg만으로 실제 MP4를 만든다.

ffmpeg/한글 폰트가 없는 환경(CI 등)에서는 통합 테스트를 건너뛴다 - 이
저장소 기존 관례(``skipUnless``)를 그대로 따른다. 순수 로직(줄바꿈 등)은
ffmpeg 없이도 항상 실행된다.

이 테스트는 ``data/`` 아래 어떤 파일도 만들지 않는다 - 전부 tempfile.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import ImageDraw, ImageFont

from content_engine.shorts_script import ShortsScript

ROOT = Path(__file__).resolve().parents[1]
WINDOWS_FONT = Path("C:/Windows/Fonts/malgun.ttf")


def _discover_ffmpeg() -> str | None:
    """PATH -> TAK_TEST_FFMPEG 환경변수 순으로 찾는다(6-40 CLI 자체와 동일한
    "명시적 경로 지정" 원칙 - 이 저장소 코드에 개인 PC의 절대경로를
    하드코딩하지 않는다)."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    override = os.environ.get("TAK_TEST_FFMPEG")
    if override and Path(override).exists():
        return override
    return None


FFMPEG_PATH = _discover_ffmpeg()


def _sample_script(**overrides) -> ShortsScript:
    defaults = dict(
        title="테스트 제목",
        subtitle="부제입니다",
        cards=("첫 번째 카드 내용입니다.", "두 번째 카드 내용입니다."),
        takeaway="마무리 문장입니다.",
        brand="티몽의 지혜",
    )
    defaults.update(overrides)
    return ShortsScript(**defaults)


# --- 1. 줄바꿈 로직(6-40 1차 렌더링에서 발견한 실제 버그의 회귀 테스트) -------------


@unittest.skipUnless(WINDOWS_FONT.exists(), "한글 폰트(맑은 고딕)가 없는 환경입니다.")
class WrapByPixelWidthTests(unittest.TestCase):
    def setUp(self) -> None:
        from PIL import Image

        self.image = Image.new("RGB", (10, 10))
        self.draw = ImageDraw.Draw(self.image)
        self.font = ImageFont.truetype(str(WINDOWS_FONT), size=58)

    def test_does_not_split_a_word_in_the_middle(self) -> None:
        """1차 렌더링 육안 검사에서 발견한 실제 결함: "생각보다 큰 힘을
        발휘하더라\\n고요."처럼 어절 "발휘하더라고요."가 중간에 잘렸다.
        이제는 한 어절이 폭을 넘지 않는 한 항상 통째로 한 줄에 들어가야
        한다."""
        from content_engine.shorts_renderer import _wrap_by_pixel_width

        text = "연체 없이 오래 거래해온 기록이 생각보다 큰 힘을 발휘하더라고요."
        lines = _wrap_by_pixel_width(self.draw, text, self.font, max_width=760)
        words = text.split(" ")
        for word in words:
            self.assertTrue(
                any(word in line.split(" ") for line in lines),
                f"어절 {word!r}이 통째로 한 줄에 들어있지 않습니다(줄: {lines}).",
            )

    def test_explicit_newlines_are_respected_as_hard_breaks(self) -> None:
        from content_engine.shorts_renderer import _wrap_by_pixel_width

        lines = _wrap_by_pixel_width(self.draw, "짧은 줄\n또 다른 짧은 줄", self.font, max_width=2000)
        self.assertEqual(lines, ["짧은 줄", "또 다른 짧은 줄"])

    def test_extremely_long_single_word_falls_back_to_character_split(self) -> None:
        from content_engine.shorts_renderer import _wrap_by_pixel_width

        long_word = "가" * 40
        lines = _wrap_by_pixel_width(self.draw, long_word, self.font, max_width=200)
        self.assertGreater(len(lines), 1)
        self.assertEqual("".join(lines), long_word)


# --- 2. RenderStyle(주제별 강조색이 실제로 다른지) --------------------------------


class RenderStyleTests(unittest.TestCase):
    def test_three_preset_styles_have_distinct_accents(self) -> None:
        from content_engine.shorts_renderer import STYLE_AI, STYLE_FINANCE, STYLE_RELATIONS

        accents = {STYLE_FINANCE.accent, STYLE_RELATIONS.accent, STYLE_AI.accent}
        self.assertEqual(len(accents), 3, "세 프리셋의 강조색이 서로 달라야 한다(6-40 지시 8장 14번).")


# --- 3. ffmpeg 부재 시 에러 처리 ---------------------------------------------------


class MissingFfmpegTests(unittest.TestCase):
    def test_missing_ffmpeg_raises_clear_error_without_writing_anything(self) -> None:
        from content_engine.shorts_renderer import ShortsRenderError, render_shorts_video

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out.mp4"
            with mock.patch("shutil.which", return_value=None):
                with self.assertRaises(ShortsRenderError):
                    render_shorts_video(_sample_script(), output, ffmpeg_path="definitely-not-a-real-binary")
            self.assertFalse(output.exists())


# --- 4. 소스 정적 검사: data/ 를 전혀 참조하지 않는다 ------------------------------


class NoOperationalDataAccessTests(unittest.TestCase):
    def test_renderer_source_never_references_data_directory(self) -> None:
        source = (ROOT / "content_engine" / "shorts_renderer.py").read_text(encoding="utf-8")
        self.assertNotIn('"data/', source)
        self.assertNotIn("'data/", source)

    def test_renderer_does_not_import_write_functions(self) -> None:
        source = (ROOT / "content_engine" / "shorts_renderer.py").read_text(encoding="utf-8")
        for forbidden in ("upsert_archive", "save_archive", "youtube_publisher", "threads_publisher"):
            self.assertNotIn(forbidden, source)


# --- 5. 실제 렌더링(ffmpeg 필요, 없으면 skip) ---------------------------------------


@unittest.skipUnless(FFMPEG_PATH, "ffmpeg를 찾을 수 없습니다(PATH 또는 TAK_TEST_FFMPEG로 지정하세요).")
@unittest.skipUnless(WINDOWS_FONT.exists(), "한글 폰트(맑은 고딕)가 없는 환경입니다.")
class RealRenderIntegrationTests(unittest.TestCase):
    def test_render_produces_playable_1080x1920_h264_no_audio_mp4(self) -> None:
        from content_engine.shorts_renderer import DEFAULT_FPS, HEIGHT, WIDTH, render_shorts_video

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out.mp4"
            result = render_shorts_video(_sample_script(), output, ffmpeg_path=FFMPEG_PATH)

            self.assertTrue(output.exists())
            self.assertGreater(output.stat().st_size, 0)
            self.assertEqual(result.width, WIDTH)
            self.assertEqual(result.height, HEIGHT)
            self.assertEqual(result.fps, DEFAULT_FPS)
            self.assertGreater(result.planned_duration_seconds, 0)

            ffprobe = shutil.which("ffprobe") or os.environ.get("TAK_TEST_FFPROBE")
            if ffprobe and Path(ffprobe).exists():
                probe = subprocess.run(
                    [ffprobe, "-v", "error", "-show_entries", "stream=width,height,codec_name,codec_type",
                     "-of", "json", str(output)],
                    capture_output=True, text=True, check=True,
                )
                data = json.loads(probe.stdout)
                video_streams = [s for s in data["streams"] if s["codec_type"] == "video"]
                audio_streams = [s for s in data["streams"] if s["codec_type"] == "audio"]
                self.assertEqual(len(video_streams), 1)
                self.assertEqual(video_streams[0]["width"], WIDTH)
                self.assertEqual(video_streams[0]["height"], HEIGHT)
                self.assertEqual(video_streams[0]["codec_name"], "h264")
                self.assertEqual(audio_streams, [], "오디오 트랙이 없어야 한다(6-40 지시 최소 사양).")

    def test_render_does_not_leave_frame_files_when_work_dir_omitted(self) -> None:
        from content_engine.shorts_renderer import render_shorts_video

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "nested"
            output = output_dir / "out.mp4"
            render_shorts_video(_sample_script(), output, ffmpeg_path=FFMPEG_PATH)
            remaining = {p.name for p in output_dir.iterdir()}
            self.assertEqual(remaining, {"out.mp4"}, "임시 프레임 PNG가 정리되지 않고 남아있습니다.")

    def test_from_dict_round_trip_renders_successfully(self) -> None:
        """실제 6-40 대본 JSON 스키마(``ShortsScript.from_dict``)로도 정상
        렌더링되는지 확인한다 - CLI가 실제로 쓰는 경로와 동일하다."""
        from content_engine.shorts_renderer import render_shorts_video

        payload = {
            "title": "짧은 제목",
            "subtitle": "부제",
            "cards": ["카드 하나", "카드 둘", "카드 셋"],
            "takeaway": "정리 문장입니다.",
            "brand": "티몽의 지혜",
        }
        script = ShortsScript.from_dict(payload)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out.mp4"
            result = render_shorts_video(script, output, ffmpeg_path=FFMPEG_PATH)
            self.assertTrue(output.exists())
            self.assertEqual(result.scene_count, 5)  # cover + 3 cards + takeaway


if __name__ == "__main__":
    unittest.main()
