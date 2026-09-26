"""6-52 Shorts V3 레이아웃 엔진 검증.

- fixture 10개(tests/fixtures/shorts_v3): schema 로드, 렌더(장면마다 실제 프레임), overflow, lineage
- 자동 레이아웃: 긴 제목 3줄 이내, footer 비면 CONTENT 확장, 이미지 없음/못 읽음 fallback, 긴 출처 말줄임
- template/content 분리: 템플릿 JSON 값만 바꿔도 프레임 위치가 바뀐다(코드 수정 없음)
- legacy ShortsScript adapter: 글자 보존, 출처 -> footer, lineage
- (ffmpeg가 있으면) 짧은 실제 MP4 + 품질 게이트

``data/`` 아래 어떤 파일도 만들거나 읽지 않는다 - 이미지는 tempfile에 생성.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from PIL import ImageStat

from content_engine.shorts_v3_adapter import document_from_shorts_script, source_label, split_to_fit
from content_engine.shorts_v3_document import (
    ShortsV3Document, V3DocumentError, build_v3_timeline, deep_merge, load_template,
)
from content_engine.shorts_v3_renderer import ShortsV3Renderer, V3LayoutError, soundtrack_spec
from content_engine.shorts_v2_scene import build_timeline
from tests.fixtures.shorts_v3_images import make_images
from content_engine.shorts_v3_pipeline import gate, media_issues, structure_issues  # 6-53: 오류 코드 게이트

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "shorts_v3"
HAS_FONTS = Path("C:/Windows/Fonts/NotoSansKR-VF.ttf").exists()
FFMPEG = os.environ.get("TAK_TEST_FFMPEG") or shutil.which("ffmpeg")


_images = make_images  # 6-53: tests/fixtures/shorts_v3_images.py로 옮김


@unittest.skipUnless(HAS_FONTS, "Noto Sans KR 폰트가 없는 환경입니다.")
class FixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        _images(cls.dir)
        for f in FIXTURES.glob("*.json"):
            shutil.copy(f, cls.dir / f.name)
        cls.docs = {f.stem: ShortsV3Document.load(cls.dir / f.name) for f in sorted(FIXTURES.glob("*.json"))}
        cls.renderers = {k: ShortsV3Renderer(d) for k, d in cls.docs.items()}

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_ten_fixtures_exist(self) -> None:
        self.assertEqual(len(self.docs), 10)

    def test_every_fixture_schema_render_overflow_lineage(self) -> None:
        for name, doc in self.docs.items():
            with self.subTest(name):
                r = self.renderers[name]
                report = r.layout_report()
                self.assertEqual(report["overflow"], [])
                # 6-53: 경로를 줬는데 없는/못 읽는 이미지는 렌더는 되지만(placeholder) 게이트가 막는다
                expected = {"IMAGE_MISSING", "IMAGE_DECODE_FAILED"} if name.startswith("03") else set()
                self.assertEqual(set(gate(structure_issues(doc, report))["codes"]), expected)
                for ts in r.timeline:  # 장면마다 실제 프레임을 그려 빈 화면이 아닌지 본다
                    frame = r.frame(ts.start + ts.duration * 0.6)
                    self.assertEqual(frame.size, (1080, 1920))
                    self.assertGreater(ImageStat.Stat(frame.convert("L")).stddev[0], 6)

    def test_long_title_fits_three_lines_in_title_frame(self) -> None:
        r = self.renderers["02_long_title_image_long_body"]
        self.assertLessEqual(sum(b.lines for b in r.title), 3)  # 6-53: 제목도 문단 블록 목록
        self.assertLess(r.layout_report()["title"]["bbox"][3], r.frames["title"][3] + 1)

    def test_scene_counts_2_4_5_6(self) -> None:
        counts = {k[:2]: len(d.scenes) for k, d in self.docs.items()}
        self.assertEqual((counts["09"], counts["04"], counts["10"], counts["05"]), (2, 4, 5, 6))

    def test_image_fallback_does_not_fail(self) -> None:
        statuses = [s["image"] for s in self.renderers["03_no_image"].layout_report()["scenes"][:3]]
        # 6-53: 경로가 없는 빈 슬롯(fallback:empty)과 파일이 없는 경우(fallback:missing)를 구분한다
        self.assertEqual(statuses, ["fallback:empty", "fallback:missing", "fallback:unreadable"])

    def test_landscape_and_portrait_images_are_cropped_to_slot(self) -> None:
        for name in ("06_image_top", "07_split"):
            for lay in self.renderers[name].layouts:
                if lay.image_rect:
                    self.assertEqual(lay.image_status, "loaded")
                    w, h = lay.image_rect[2] - lay.image_rect[0], lay.image_rect[3] - lay.image_rect[1]
                    self.assertAlmostEqual(lay.image.width / lay.image.height, w / h, places=1)

    def test_long_source_truncated_with_warning_not_failure(self) -> None:
        last = self.renderers["04_with_source"].layout_report()["scenes"][3]
        self.assertIn("source_truncated", last["warnings"])

    def test_footer_collapses_when_no_source_or_subtitle(self) -> None:
        with_src = self.renderers["04_with_source"].layouts[0].content
        without = self.renderers["05_without_source"].layouts[0].content
        self.assertGreater(without[3], with_src[3])

    def test_emphasis_field_marks_phrase(self) -> None:
        body = self.renderers["08_text_focus"].layouts[0].body
        self.assertTrue(any(b.marks for b in body))

    def test_document_overrides_brand_cta_progress_audio(self) -> None:
        d10, d09 = self.docs["10_five_scenes"], self.docs["09_two_short_scenes"]
        self.assertEqual((d10.brand["text"], d10.brand["cta"]), ("테스트 브랜드", "구독하고 다음 편 보기"))
        self.assertEqual(d10.audio["volume"], 0.8)
        self.assertEqual(d09.progress["position"], "top")

    def test_timeline_is_beat_aligned_and_feeds_v2_soundtrack(self) -> None:
        doc = self.docs["10_five_scenes"]
        timeline = build_v3_timeline(doc)
        spec = soundtrack_spec(doc, timeline)
        self.assertAlmostEqual(build_timeline(spec)[-1].end, timeline[-1].end)
        self.assertIsNone(timeline[-1].scene)  # 브랜드 엔드카드


@unittest.skipUnless(HAS_FONTS, "Noto Sans KR 폰트가 없는 환경입니다.")
class SeparationAndSchemaTests(unittest.TestCase):
    DOC = {"schema": "shorts_v3_document/1", "id": "t", "title": "제목", "lineage": {"content_id": "t"},
           "scenes": [{"layout": "text_focus", "body": "본문."}]}

    def test_template_values_move_frames_without_code_change(self) -> None:
        base = load_template("default")
        moved = deep_merge(base, {"frames": {"title": [90, 300, 910, 560]}})  # 6-53: 프레임끼리 겹치면 INVALID_TEMPLATE
        a = ShortsV3Renderer(ShortsV3Document.from_dict(self.DOC, template=base))
        b = ShortsV3Renderer(ShortsV3Document.from_dict(self.DOC, template=moved))
        self.assertGreater(b.title[0].bbox[1], a.title[0].bbox[1])

    def test_schema_errors(self) -> None:
        bad = [
            {**self.DOC, "scenes": []},
            {**self.DOC, "title": ""},
            {**self.DOC, "scenes": [{"layout": "chart", "body": "x"}]},
            {**self.DOC, "scenes": [{"layout": "text_focus"}]},
            {**self.DOC, "scenes": [{"layout": "text_focus", "body": "긴 문장을 한 번에 다 읽을 수는 없다.", "duration": 1.2}]},
            {**self.DOC, "schema": "other/9"},
        ]
        for data in bad:
            with self.subTest(data), self.assertRaises(V3DocumentError):
                ShortsV3Document.from_dict(data)

    def test_unfittable_body_is_reported_not_cut(self) -> None:
        doc = ShortsV3Document.from_dict({**self.DOC, "scenes": [{"layout": "split", "body": "가나다라마바사 " * 60}]})
        with self.assertRaises(V3LayoutError):
            ShortsV3Renderer(doc)


@unittest.skipUnless(HAS_FONTS, "Noto Sans KR 폰트가 없는 환경입니다.")
class LegacyAdapterTests(unittest.TestCase):
    SCRIPT = {
        "content_id": "content-test", "knowledge_id": "knowledge-test", "platform": "shorts", "title": "AI 의식 연구, 어디까지 허용할까?",
        "subtitle": "", "brand": "티몽의 지혜",
        "cards": ["Mustafa Suleyman says he believes rival AI firm Anthropic is in effect teaching Claude it \"may be conscious\".",
                  "나는 이런 논란을 투명한 연구와 감독 아래 제한적으로 허용하면서 사회적 논의를 이어가는 방식으로 다뤄야 한다고 생각합니다. "
                  "연구 범위와 실험 대상을 명확히 정하고, 독립적인 검토를 받아야 합니다. 검증 가능한 피해가 발생할 때만 연구를 중단해야 한다고 봅니다. "
                  "이 문장은 분할을 확인하려고 덧붙인 아주 긴 테스트 문장이며 실제 콘텐츠가 아닙니다. " * 3],
        "takeaway": "출처: https://www.bbc.co.uk/news/articles/c6n07ypqz8kzo?at_medium=RSS&at_campaign=rss",
    }

    def test_adapter_keeps_text_moves_source_and_lineage(self) -> None:
        doc_dict = document_from_shorts_script(self.SCRIPT, generation_id="gen-x", source_script="x.json")
        bodies = [s["body"] for s in doc_dict["scenes"]]
        strip = lambda s: re.sub(r"\s", "", s)  # noqa: E731
        self.assertEqual(strip("".join(bodies)), strip("".join(self.SCRIPT["cards"])))
        self.assertGreater(len(bodies), len(self.SCRIPT["cards"]))  # 긴 카드는 문장 경계에서 나뉜다
        self.assertTrue(all(s["source"] == "bbc.co.uk" for s in doc_dict["scenes"]))
        self.assertNotIn("출처", "".join(bodies))
        self.assertEqual((doc_dict["lineage"]["content_id"], doc_dict["lineage"]["generation_id"]), ("content-test", "gen-x"))
        doc = ShortsV3Document.from_dict(json.loads(json.dumps(doc_dict)))
        self.assertEqual(ShortsV3Renderer(doc).layout_report()["overflow"], [])

    def test_source_label_and_split(self) -> None:
        self.assertEqual(source_label(self.SCRIPT["takeaway"])[0], "bbc.co.uk")
        self.assertEqual(source_label("그냥 문장"), ("", ""))
        self.assertEqual(split_to_fit("짧다.", load_template("default")), ["짧다."])


@unittest.skipUnless(HAS_FONTS and FFMPEG, "ffmpeg(PATH 또는 TAK_TEST_FFMPEG)/폰트가 없는 환경입니다.")
class EncodeTests(unittest.TestCase):
    def test_short_mp4_passes_quality_gate(self) -> None:
        from content_engine.shorts_v3_renderer import render_short_v3
        from scripts.render_shorts_v2 import probe

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _images(tmp)
            shutil.copy(FIXTURES / "09_two_short_scenes.json", tmp / "doc.json")
            doc = ShortsV3Document.load(tmp / "doc.json")
            video = tmp / "out.mp4"
            result = render_short_v3(doc, video, ffmpeg_path=FFMPEG)
            ffprobe = str(Path(FFMPEG).with_name(Path(FFMPEG).name.replace("ffmpeg", "ffprobe")))
            if not Path(ffprobe).exists() and not shutil.which(ffprobe):
                self.skipTest("ffprobe 없음")
            info = probe(ffprobe, video)
            post, checks = media_issues(FFMPEG, video, info, doc, result.layout, tmp / "frames")
            verdict = gate(structure_issues(doc, result.layout) + post)
            self.assertEqual(verdict["status"], "PASS", verdict)


if __name__ == "__main__":
    unittest.main()
