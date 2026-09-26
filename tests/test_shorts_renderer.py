from pathlib import Path
import tempfile
import unittest

from PIL import ImageFont

from content_engine.shorts_renderer import (
    BACKGROUND_VARIANTS,
    CANVAS_SIZE,
    ShortsRenderError,
    build_screen_image,
    pick_background_variant,
    probe_video,
    render_shorts_video,
    wrap_text,
    _load_font,
)
from content_engine.shorts_script import ShortsScript, build_screen_plan


def _make_script(**overrides) -> ShortsScript:
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
    return ShortsScript(**data)


class WrapTextTests(unittest.TestCase):
    def setUp(self):
        self.font = _load_font("body_sans", 48)

    def test_short_text_stays_on_one_line(self):
        lines = wrap_text("짧은 문장.", self.font, max_width=900)
        self.assertEqual(lines, ["짧은 문장."])

    def test_long_text_wraps_into_multiple_lines(self):
        text = "무조건 잘해주는 것과 좋은 사람이 되는 것은 다릅니다 정말로 그렇습니다 반드시 기억하세요"
        lines = wrap_text(text, self.font, max_width=400)
        self.assertGreater(len(lines), 1)
        for line in lines:
            self.assertLessEqual(self.font.getlength(line), 400)

    def test_wrapping_preserves_all_characters(self):
        text = "무조건 잘해주는 것과 좋은 사람이 되는 것은 다릅니다 정말로 그렇습니다"
        lines = wrap_text(text, self.font, max_width=350)
        rejoined = "".join(lines).replace(" ", "")
        original = text.replace(" ", "")
        self.assertEqual(rejoined, original)

    def test_empty_text_returns_no_lines(self):
        self.assertEqual(wrap_text("   ", self.font, max_width=900), [])

    def test_single_very_long_word_is_broken_without_dropping_characters(self):
        word = "가" * 40
        lines = wrap_text(word, self.font, max_width=200)
        self.assertGreater(len(lines), 1)
        self.assertEqual("".join(lines), word)


class BackgroundVariantTests(unittest.TestCase):
    def test_pick_is_deterministic_for_same_script(self):
        script = _make_script()
        first = pick_background_variant(script)
        second = pick_background_variant(script)
        self.assertEqual(first, second)
        self.assertIn(first, BACKGROUND_VARIANTS)

    def test_explicit_override_is_respected(self):
        script = _make_script()
        variant = pick_background_variant(script, override="hanji_paper")
        self.assertEqual(variant, "hanji_paper")

    def test_unknown_override_raises_clear_error(self):
        script = _make_script()
        with self.assertRaises(ShortsRenderError):
            pick_background_variant(script, override="does_not_exist")


class BuildScreenImageTests(unittest.TestCase):
    def test_cover_card_and_takeaway_render_to_canvas_size(self):
        script = _make_script()
        plans = build_screen_plan(script)
        for index, plan in enumerate(plans):
            image = build_screen_image(script, plan, "book_desk", index, len(plans))
            self.assertEqual(image.size, CANVAS_SIZE)
            self.assertEqual(image.mode, "RGB")

    def test_all_background_variants_render_without_error(self):
        script = _make_script()
        plans = build_screen_plan(script)
        cover_plan = plans[0]
        for variant in BACKGROUND_VARIANTS:
            image = build_screen_image(script, cover_plan, variant, 0, len(plans))
            self.assertEqual(image.size, CANVAS_SIZE)


class RenderShortsVideoIntegrationTests(unittest.TestCase):
    """실제 ffmpeg를 호출해 MP4를 생성하는 느린 통합 테스트."""

    def test_render_produces_valid_mp4_with_expected_properties(self):
        script = _make_script()
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "nested" / "output.mp4"
            result = render_shorts_video(script, output_path)

            self.assertTrue(output_path.exists())
            self.assertEqual((result.width, result.height), CANVAS_SIZE)
            self.assertFalse(result.has_audio)
            self.assertGreater(result.duration_seconds, 0)
            self.assertEqual(result.screen_count, 1 + len(script.cards) + 1)

            probe = probe_video(output_path)
            self.assertEqual((probe.width, probe.height), CANVAS_SIZE)
            self.assertFalse(probe.has_audio)

    def test_more_cards_produce_longer_video(self):
        short_script = _make_script(cards=["카드 하나만 있는 경우입니다."])
        long_script = _make_script(
            cards=[
                "무조건 잘해주는 것과 좋은 사람이 되는 것은 다릅니다.",
                "모든 부탁을 들어주다 보면 상대가 그것을 당연하게 생각할 수 있습니다.",
                "선을 넘는 순간에는 분명하게 선을 그어야 합니다.",
                "거절해야 할 때 거절하는 것도 나를 지키는 방법입니다.",
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            short_path = Path(tmp) / "short.mp4"
            long_path = Path(tmp) / "long.mp4"
            short_result = render_shorts_video(short_script, short_path)
            long_result = render_shorts_video(long_script, long_path)

        self.assertGreater(long_result.duration_seconds, short_result.duration_seconds)

    def test_output_directory_is_created_automatically(self):
        script = _make_script()
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "does" / "not" / "exist" / "out.mp4"
            self.assertFalse(output_path.parent.exists())
            render_shorts_video(script, output_path)
            self.assertTrue(output_path.exists())


if __name__ == "__main__":
    unittest.main()
