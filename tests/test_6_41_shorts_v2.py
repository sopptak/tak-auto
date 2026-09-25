"""6-41 Shorts 2.0(장면 설계 + 모던 스타일 렌더러 + 합성 사운드트랙) 검증.

- 장면 설계 규칙(HOOK 우선, 박자 동기화, 읽기 시간, 최대 3줄, 25~45초)
- 렌더러 회귀: 첫 프레임 HOOK 가시성, 디졸브 시 문장 겹침 없음, RGB 알파 블렌딩,
  안전영역 검사, 폰트를 줄이지 않고 실패하는 줄 수 제한
- 사운드트랙: 길이 일치, 무음 아님, 결정적 출력
- (ffmpeg가 있으면) 실제 부분 렌더 + ffprobe 규격 확인

``data/`` 아래 어떤 파일도 만들지 않는다 - 전부 tempfile.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path

from PIL import Image

from content_engine.shorts_script import ShortsScript
from content_engine.shorts_v2_scene import (
    SAFE_BOTTOM, SAFE_LEFT, SAFE_RIGHT, SAFE_TOP, Scene, SceneSpecError, ShortSpec, build_timeline,
    item_reveal_times, scene_beats, total_seconds,
)

ROOT = Path(__file__).resolve().parents[1]
SPEC_DIR = ROOT / "content_engine" / "shorts_v2_specs"
SPEC_NAMES = ("finance", "human", "ai")
NOTO = Path("C:/Windows/Fonts/NotoSansKR-VF.ttf")
NOTO_SERIF = Path("C:/Windows/Fonts/NotoSerifKR-VF.ttf")
HAS_FONTS = NOTO.exists() and NOTO_SERIF.exists()


def _discover_ffmpeg() -> str | None:
    found = shutil.which("ffmpeg")
    if found:
        return found
    override = os.environ.get("TAK_TEST_FFMPEG")
    return override if override and Path(override).exists() else None


FFMPEG = _discover_ffmpeg()


def _spec_dict(name: str) -> dict:
    return json.loads((SPEC_DIR / f"{name}.json").read_text(encoding="utf-8"))


class SceneSpecTests(unittest.TestCase):
    def test_three_specs_load_with_distinct_styles_and_valid_length(self) -> None:
        styles = set()
        for name in SPEC_NAMES:
            spec = ShortSpec.load(SPEC_DIR / f"{name}.json")
            styles.add(spec.style)
            self.assertEqual(spec.scenes[0].role, "HOOK")
            self.assertTrue(25 <= total_seconds(spec) <= 45, name)
            self.assertLessEqual(build_timeline(spec)[0].duration, 3.0, f"{name} HOOK이 너무 김")
        self.assertEqual(styles, {"finance", "human", "ai"})

    def test_every_scene_boundary_lands_on_a_beat(self) -> None:
        for name in SPEC_NAMES:
            spec = ShortSpec.load(SPEC_DIR / f"{name}.json")
            for ts in build_timeline(spec):
                beats = ts.start / spec.beat_seconds
                self.assertAlmostEqual(beats, round(beats), places=6, msg=f"{name} scene {ts.index}")

    def test_beats_shorter_than_reading_time_are_rejected(self) -> None:
        scene = Scene(role="INFO", text="이 문장은 꽤 길어서 한 박자 안에는 절대로 다 읽을 수가 없습니다", beats=1)
        with self.assertRaises(SceneSpecError):
            scene_beats(scene, 0.5)

    def test_duration_grows_with_text_length_when_beats_omitted(self) -> None:
        short = scene_beats(Scene(role="INFO", text="짧다"), 0.5)
        long = scene_beats(Scene(role="INFO", text="이건 훨씬 긴 문장이라서\n읽는 시간이 더 필요하다"), 0.5)
        self.assertGreater(long, short)

    def test_list_items_reveal_on_beats_inside_the_scene(self) -> None:
        spec = ShortSpec.load(SPEC_DIR / "ai.json")
        for ts in build_timeline(spec):
            times = item_reveal_times(ts, spec.beat_seconds)
            for t in times:
                self.assertTrue(ts.start < t <= ts.end - 1.0, "마지막 항목도 1초 이상 보여야 한다")

    def test_more_than_three_lines_rejected(self) -> None:
        data = _spec_dict("finance")
        data["scenes"][1]["text"] = "하나\n둘\n셋\n넷"
        with self.assertRaises(SceneSpecError):
            ShortSpec.from_dict(data)

    def test_first_scene_must_be_hook(self) -> None:
        data = _spec_dict("finance")
        data["scenes"][0]["role"] = "PROBLEM"
        with self.assertRaises(SceneSpecError):
            ShortSpec.from_dict(data)

    def test_emphasis_markup(self) -> None:
        scene = Scene(role="HOOK", text="은행은 점수 *하나로*\n결정하지 않아요.")
        self.assertEqual(scene.emphasis, ("하나로",))
        self.assertNotIn("*", scene.plain_text)


@unittest.skipUnless(HAS_FONTS, "Noto Sans/Serif KR 폰트가 없는 환경입니다.")
class RendererTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from content_engine.shorts_v2_renderer import ShortsV2Renderer

        cls.renderers = {name: ShortsV2Renderer(ShortSpec.load(SPEC_DIR / f"{name}.json")) for name in SPEC_NAMES}

    @staticmethod
    def _bright_pixels(img: Image.Image, box: tuple[int, int, int, int]) -> int:
        gray = img.convert("L").crop(box)
        return sum(gray.histogram()[200:])

    def test_all_text_elements_inside_safe_area(self) -> None:
        # ShortsV2Renderer 생성 자체가 안전영역 검사를 수행한다 - 여기서는 결과를 한 번 더 확인
        for name, renderer in self.renderers.items():
            for assets in renderer.assets:
                for x0, y0, x1, y1 in assets.boxes:
                    self.assertGreaterEqual(x0, SAFE_LEFT, name)
                    self.assertGreaterEqual(y0, SAFE_TOP, name)
                    self.assertLessEqual(x1, SAFE_RIGHT, name)
                    self.assertLessEqual(y1, SAFE_BOTTOM, name)

    def test_hook_text_visible_on_very_first_frame(self) -> None:
        """1차 렌더링 결함 회귀: t=0 프레임에 HOOK 문장이 없었다(등장 애니메이션 대기)."""
        for name, renderer in self.renderers.items():
            text = renderer.assets[0].text
            self.assertIsNotNone(text, name)
            self.assertGreater(self._bright_pixels(renderer.frame(0.0), text.bbox), 2000, name)

    def test_dissolve_does_not_overlap_two_sentences(self) -> None:
        """2차 렌더링 결함 회귀: human 디졸브 중 이전/다음 문장이 겹쳐 보였다."""
        renderer = self.renderers["human"]
        cut = renderer.timeline[1].start
        box = renderer.assets[0].text.bbox
        self.assertLess(self._bright_pixels(renderer.frame(cut + 0.1), box), 300)

    def test_semi_transparent_sprite_blends_on_rgb_frame(self) -> None:
        """1차 미리보기 결함 회귀: RGBA 프레임에서는 반투명 요소가 불투명하게 나왔다."""
        from content_engine.shorts_v2_renderer import _blit

        frame = Image.new("RGB", (4, 4), (0, 0, 0))
        _blit(frame, Image.new("RGBA", (4, 4), (255, 255, 255, 64)), 0, 0)
        self.assertTrue(55 <= frame.getpixel((1, 1))[0] <= 75)

    def test_too_many_lines_fails_instead_of_shrinking_font(self) -> None:
        from content_engine.shorts_renderer import ShortsRenderError
        from content_engine.shorts_v2_renderer import LOOKS, layout_text

        with self.assertRaises(ShortsRenderError):
            layout_text("아주 길고 긴 문장을 한 화면에 억지로 넣으려고 하면 세 줄을 넘어서 결국 실패해야만 한다", LOOKS["ai"], 900)

    def test_consecutive_emphasized_words_share_one_mark(self) -> None:
        from content_engine.shorts_v2_renderer import LOOKS, layout_text

        block = layout_text("*뭘 찾을지* 정하는 힘", LOOKS["ai"], 900)
        self.assertEqual(len(block.marks), 1)

    def test_every_scene_renders_a_non_black_frame(self) -> None:
        for name, renderer in self.renderers.items():
            for ts in renderer.timeline:
                frame = renderer.frame(ts.start + ts.duration * 0.7)
                self.assertEqual(frame.size, (1080, 1920))
                self.assertGreater(max(frame.convert("L").getextrema()), 150, f"{name} scene {ts.index}")


class SoundtrackTests(unittest.TestCase):
    def _tiny_spec(self) -> ShortSpec:
        # from_dict를 거치지 않아 25초 제한 없이 짧은 사운드트랙만 검증한다
        return ShortSpec(id="t", style="ai", bpm=120, idea="", scenes=(
            Scene(role="HOOK", text="짧다", beats=4, audio=("impact",)),
            Scene(role="INFO", text="목록", layout="list", items=("a", "b"), audio=("whoosh",), music="break"),
        ))

    def test_wav_length_matches_timeline_and_is_not_silent(self) -> None:
        from content_engine.shorts_v2_audio import synthesize_soundtrack

        spec = self._tiny_spec()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.wav"
            seconds = synthesize_soundtrack(spec, path)
            self.assertAlmostEqual(seconds, total_seconds(spec), places=2)
            with wave.open(str(path)) as handle:
                frames = handle.readframes(handle.getnframes())
            self.assertGreater(max(frames), 0)

    def test_deterministic(self) -> None:
        from content_engine.shorts_v2_audio import synthesize_soundtrack

        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp) / "a.wav", Path(tmp) / "b.wav"
            synthesize_soundtrack(self._tiny_spec(), a)
            synthesize_soundtrack(self._tiny_spec(), b)
            self.assertEqual(a.read_bytes(), b.read_bytes())


class CompatibilityTests(unittest.TestCase):
    def test_6_40_card_script_maps_to_scene_plan_and_is_gated(self) -> None:
        """6-40 카드뉴스 대본도 v2 장면 설계로 옮길 수 있지만, 짧은 카드뉴스는 길이 규칙에 걸린다."""
        from content_engine.shorts_v2_renderer import spec_from_shorts_script

        script = ShortsScript(title="제목", subtitle="부제", cards=("카드 하나",), takeaway="마무리")
        with self.assertRaises(SceneSpecError):
            spec_from_shorts_script(script)


class IsolationTests(unittest.TestCase):
    def test_modules_do_not_touch_production_data(self) -> None:
        for rel in ("content_engine/shorts_v2_scene.py", "content_engine/shorts_v2_audio.py",
                    "content_engine/shorts_v2_renderer.py", "scripts/render_shorts_v2.py"):
            source = (ROOT / rel).read_text(encoding="utf-8")
            # 문서화 주석의 ``data/`` 언급은 허용 - 실제 경로 문자열/네트워크 모듈 import만 금지
            for forbidden in ('"data/', "'data/", '"data"', "tak_media_archive", "tak_threads_pending",
                              "import requests", "import urllib", "from urllib", "http.client", "socket"):
                self.assertFalse(forbidden in source, f"{rel}: {forbidden}")


@unittest.skipUnless(FFMPEG and HAS_FONTS, "ffmpeg(PATH 또는 TAK_TEST_FFMPEG)/폰트가 없는 환경입니다.")
class EncodeTests(unittest.TestCase):
    def test_partial_render_is_1080x1920_h264_with_aac(self) -> None:
        from content_engine.shorts_v2_renderer import render_short_v2

        ffprobe = str(Path(FFMPEG).with_name(Path(FFMPEG).name.replace("ffmpeg", "ffprobe")))
        spec = ShortSpec.load(SPEC_DIR / "ai.json")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "part.mp4"
            render_short_v2(spec, out, ffmpeg_path=FFMPEG, max_seconds=1.0)
            probe = json.loads(subprocess.run(
                [ffprobe, "-v", "error", "-show_entries", "stream=codec_name,codec_type,width,height", "-of", "json", str(out)],
                capture_output=True, text=True, check=True).stdout)
        streams = {s["codec_type"]: s for s in probe["streams"]}
        self.assertEqual((streams["video"]["codec_name"], streams["video"]["width"], streams["video"]["height"]), ("h264", 1080, 1920))
        self.assertEqual(streams["audio"]["codec_name"], "aac")


if __name__ == "__main__":
    unittest.main()
