"""6-53 Shorts V3 생산 레이아웃 엔진 - 단위 테스트(ffmpeg 없이, 프레임은 메모리에서만 그림).

테스트 매트릭스(docs/6-53 21장)의 렌더 없는 부분: 템플릿 검증(INVALID_TEMPLATE), 문서 검증 오류 코드,
텍스트 엔진(폰트 -> 줄 간격 -> 대체 기하 -> BLOCK), 문단, 이미지 fit(cover/contain/정사각형/기준점),
출처 객체/말줄임, 진행 표시(time/scene/off/top), 전환(cut/punch/fade/slide), lineage/render key,
배치 격리(검증 단계), approved archive -> 배치 항목. ``data/``를 읽거나 쓰지 않는다.
"""

from __future__ import annotations

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from PIL import ImageStat

from content_engine.shorts_v2_renderer import LOOKS
from content_engine.shorts_v3_document import V3RenderDocument, build_v3_timeline
from content_engine.shorts_v3_layout import LayoutEngine, fit_paragraphs
from content_engine.shorts_v3_pipeline import (
    BatchItem, approved_items, gate, item_from_shorts_script, lineage, render_batch, render_key, structure_issues,
)
from content_engine.shorts_v3_renderer import ShortsV3Renderer, V3LayoutError
from content_engine.shorts_v3_template import V3Error, deep_merge, load_template, resolve_template
from tests.fixtures.shorts_v3_images import make_images

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "shorts_v3_engine"
HAS_FONTS = Path("C:/Windows/Fonts/NotoSansKR-VF.ttf").exists()
BASE = {"schema": "shorts_v3_document/1", "id": "t", "title": "제목", "lineage": {"content_id": "t"},
        "scenes": [{"layout": "text_focus", "body": "본문."}]}
LONG_BODY = "연구 범위와 실험 대상을 명확히 정하고, 독립적인 검토를 받아야 합니다. " * 3


def doc_with(**changes) -> dict:
    d = copy.deepcopy(BASE)
    d.update(changes)
    return d


def scene(**fields) -> dict:
    return {"layout": "text_focus", **fields}


def codes(data: dict, base_dir: Path | str = ".") -> set[str]:
    doc = V3RenderDocument.from_dict(data, base_dir=base_dir)
    return set(gate(structure_issues(doc, LayoutEngine(doc).report()))["codes"])


class TemplateValidationTests(unittest.TestCase):
    def test_default_template_is_valid(self) -> None:
        self.assertEqual(load_template("default")["id"], "default")

    def test_invalid_templates(self) -> None:
        base = load_template("default")
        broken = {
            "missing key": {k: v for k, v in base.items() if k != "frames"},
            "bad canvas": deep_merge(base, {"canvas": {"width": 720}}),
            "frame outside safe": deep_merge(base, {"frames": {"title": [0, 0, 910, 540]}}),
            "frames overlap": deep_merge(base, {"frames": {"title": [90, 260, 910, 700]}}),
            "bad layout rect": deep_merge(base, {"layouts": {"split": {"image": [0, 0, 1.5, 1]}}}),
            "empty layout": deep_merge(base, {"layouts": {"x": {"scrim": True}}}),
            "bad text range": deep_merge(base, {"text": {"body": {"size_min": 80, "size_max": 40}}}),
            "bad audio": deep_merge(base, {"audio": {"background": "rock"}}),
            "bad progress": deep_merge(base, {"progress": {"position": "left"}}),
            "bad look": deep_merge(base, {"look": "neon"}),
            "footer rows too tall": deep_merge(base, {"footer_rows": {"progress": 200}}),
            "negative animation": deep_merge(base, {"animation": {"body_delay": -1}}),
            "missing animation": {k: v for k, v in base.items() if k != "animation"},
        }
        for name, tpl in broken.items():
            with self.subTest(name), self.assertRaises(V3Error) as ctx:
                resolve_template(tpl)
            self.assertEqual(ctx.exception.code, "INVALID_TEMPLATE")

    def test_missing_or_broken_template_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text("{not json", encoding="utf-8")
            for ref in (bad, Path(tmp) / "none.json", "no_such_template"):
                with self.subTest(str(ref)), self.assertRaises(V3Error) as ctx:
                    load_template(ref)
                self.assertEqual(ctx.exception.code, "INVALID_TEMPLATE")

    def test_document_cannot_break_template(self) -> None:
        with self.assertRaises(V3Error) as ctx:
            V3RenderDocument.from_dict(doc_with(progress={"position": "middle"}))
        self.assertEqual(ctx.exception.code, "INVALID_TEMPLATE")


class DocumentValidationTests(unittest.TestCase):
    CASES = {
        "INVALID_DOCUMENT": [doc_with(scenes=[]), doc_with(title=""), doc_with(schema="x/9"), doc_with(scenes="a"),
                             doc_with(lineage="x"), doc_with(scenes=[scene(body="a", source={"label": "출처"})])],
        "INVALID_DURATION": [doc_with(scenes=[scene(body="a", duration=0)]), doc_with(scenes=[scene(body="a", duration=-1)]),
                             doc_with(scenes=[scene(body="a", duration="abc")]), doc_with(scenes=[scene(body="a", duration=999)]),
                             doc_with(scenes=[scene(body="긴 문장은 1.2초 안에 다 읽을 수 없다.", duration=1.2)])],
        "INVALID_LAYOUT": [doc_with(scenes=[scene(layout="chart", body="a")])],
        "INVALID_TRANSITION": [doc_with(scenes=[scene(body="a", transition="spin")])],
        "INVALID_IMAGE_SPEC": [doc_with(scenes=[scene(layout="image_top", image={"path": "a.png", "fit": "stretch"})]),
                               doc_with(scenes=[scene(layout="image_top", image={"path": "a.png", "scale": 9})]),
                               doc_with(scenes=[scene(layout="image_top", image={"path": "a.png", "position": "middle"})]),
                               doc_with(scenes=[scene(layout="image_top", image=42)])],
        "EMPTY_SCENE": [doc_with(scenes=[scene()])],
        "TIMING_MISMATCH": [doc_with(expected_duration=60)],
    }

    def test_error_codes(self) -> None:
        for code, docs in self.CASES.items():
            for data in docs:
                with self.subTest(code=code, data=data), self.assertRaises(V3Error) as ctx:
                    V3RenderDocument.from_dict(data)
                self.assertEqual(ctx.exception.code, code)

    def test_minimal_documents_are_valid(self) -> None:
        V3RenderDocument.from_dict(doc_with(title="A"))  # 제목 1자, 장면 1개
        doc = V3RenderDocument.from_dict(doc_with(expected_duration=None))
        total = build_v3_timeline(doc)[-1].end
        V3RenderDocument.from_dict(doc_with(expected_duration=total))

    def test_render_document_exposes_ids_and_hashes(self) -> None:
        doc = V3RenderDocument.from_dict(doc_with(lineage={"content_id": "c1", "generation_id": "g1"}))
        self.assertEqual((doc.content_id, doc.generation_id), ("c1", "g1"))
        self.assertEqual(len(doc.document_sha256()), 64)
        self.assertEqual(len(doc.template_sha256()), 64)

    def test_latin_text_reads_faster_than_hangul(self) -> None:
        latin = V3RenderDocument.from_dict(doc_with(scenes=[scene(body="Mustafa Suleyman says he believes rival AI firm")]))
        hangul = V3RenderDocument.from_dict(doc_with(scenes=[scene(body="가" * 40)]))
        self.assertLess(build_v3_timeline(latin)[0].duration, build_v3_timeline(hangul)[0].duration)


@unittest.skipUnless(HAS_FONTS, "Noto Sans KR 폰트가 없는 환경입니다.")
class TextEngineTests(unittest.TestCase):
    def test_line_gap_tightens_before_blocking(self) -> None:
        look = LOOKS["ai"]
        spec = {"size_max": 40, "size_min": 40, "max_lines": 3, "line_gap_min": 1.1}
        text = "가나다라마바사아자차 카타파하가나다라마바 사아자차카타파하가나"  # 폭 610px에서 어절 하나씩 3줄
        loose = fit_paragraphs(text, look, (90, 0, 700, 1000), spec)
        height = loose[0].bbox[3] - loose[0].bbox[1]
        self.assertEqual(loose[0].lines, 3)
        tight = fit_paragraphs(text, look, (90, 0, 700, height - 4), spec)
        self.assertIsNotNone(tight)
        self.assertLess(tight[0].bbox[3] - tight[0].bbox[1], height)
        self.assertIsNone(fit_paragraphs(text, look, (90, 0, 700, 60), spec))  # 그래도 안 되면 None(자르지 않음)

    def test_paragraphs_are_stacked(self) -> None:
        blocks = fit_paragraphs("첫 문단.\n\n둘째 문단.", LOOKS["ai"], (90, 600, 910, 1200), load_template("default")["text"]["body"])
        self.assertEqual(len(blocks), 2)
        self.assertGreater(blocks[1].bbox[1], blocks[0].bbox[3])

    def test_fallback_geometry_expands_text_region(self) -> None:
        # 이 길이는 image_top 기본 기하(텍스트 44%)에는 안 들어가고 대체 기하(58%)에는 들어간다
        doc = V3RenderDocument.from_dict(doc_with(scenes=[scene(layout="image_top", headline="헤드라인", body=LONG_BODY)]))
        lay = LayoutEngine(doc).layouts[0]
        self.assertEqual(lay.variant, "fallback")
        self.assertTrue(lay.body)

    def test_overflow_codes(self) -> None:
        cases = {
            "TITLE_OVERFLOW": doc_with(title="아주 긴 제목 " * 40),
            "BODY_OVERFLOW": doc_with(scenes=[scene(layout="split", body="가나다라마바사 " * 60)]),
            "HEADLINE_OVERFLOW": doc_with(scenes=[scene(headline="헤드라인이 너무 길다 " * 20)]),
            "SUBTITLE_OVERFLOW": doc_with(scenes=[scene(body="a", subtitle="자막이 너무 길어서 한 줄에 들어가지 않는다 " * 4)]),
        }
        for code, data in cases.items():
            with self.subTest(code):
                self.assertIn(code, codes(data))
                with self.assertRaises(V3LayoutError) as ctx:
                    ShortsV3Renderer(V3RenderDocument.from_dict(data))
                self.assertEqual(ctx.exception.code, code)

    def test_short_and_long_title_stay_in_title_frame(self) -> None:
        for title in ("A", "AI 의식 연구, 어디까지 허용해야 할까? 제목이 아주 길어도 세 줄 안에서 줄어들어야 한다"):
            engine = LayoutEngine(V3RenderDocument.from_dict(doc_with(title=title)))
            self.assertEqual(engine.report()["overflow"], [])
            self.assertLessEqual(engine.report()["title"]["lines"], 3)
            self.assertLessEqual(engine.report()["title"]["bbox"][3], engine.frames["title"][3])


@unittest.skipUnless(HAS_FONTS, "Noto Sans KR 폰트가 없는 환경입니다.")
class SlotFooterProgressTransitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        make_images(cls.dir)
        for f in FIXTURES.glob("*.json"):
            shutil.copy(f, cls.dir / f.name)
        cls.docs = {f.stem: V3RenderDocument.load(cls.dir / f.name) for f in FIXTURES.glob("*.json")}

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_fixtures_layout_clean_and_frames_render(self) -> None:
        for name, doc in self.docs.items():
            with self.subTest(name):
                r = ShortsV3Renderer(doc)
                self.assertEqual(gate(structure_issues(doc, r.layout_report()))["status"], "PASS")
                for ts in r.timeline:
                    for frac in (0.05, 0.6):  # 전환 중 + 안정 구간
                        frame = r.frame(ts.start + ts.duration * frac)
                        self.assertEqual(frame.size, (1080, 1920))
                        self.assertGreater(ImageStat.Stat(frame.convert("L")).stddev[0], 6)

    def test_square_contain_and_focal_point(self) -> None:
        lays = LayoutEngine(self.docs["square_contain"]).layouts
        self.assertEqual([l.image_status for l in lays[:3]], ["loaded"] * 3)
        for lay in lays[:3]:
            w, h = lay.image_rect[2] - lay.image_rect[0], lay.image_rect[3] - lay.image_rect[1]
            self.assertAlmostEqual(lay.image.width / lay.image.height, w / h, places=1)
        # cover + 기준점(왼쪽 아래 빨간 사각형) -> 준비된 이미지 가운데가 빨간색 쪽
        r, g, b = lays[1].image.getpixel((lays[1].image.width // 2, lays[1].image.height // 2))
        self.assertGreater(r, g)

    def test_source_object_label_and_long_source(self) -> None:
        lays = LayoutEngine(self.docs["paragraphs_source_object"]).layouts
        self.assertEqual(len(lays[0].body), 2)  # 문단 2개
        self.assertEqual(self.docs["paragraphs_source_object"].scenes[1].source.display(self.docs["paragraphs_source_object"].template),
                         "자료 · 책 「사피엔스」")
        long = V3RenderDocument.from_dict(doc_with(scenes=[scene(body="a", source="아주 긴 출처 설명이 계속 이어지는 책 제목 " * 4)]))
        issues = LayoutEngine(long).report()["issues"]
        self.assertEqual([i["code"] for i in issues], ["SOURCE_TRUNCATED"])
        self.assertEqual(gate(issues)["status"], "PASS")  # 경고일 뿐

    def test_progress_modes(self) -> None:
        r_on = ShortsV3Renderer(V3RenderDocument.from_dict(doc_with(scenes=[scene(body="a"), scene(body="b")])))
        r_off = ShortsV3Renderer(V3RenderDocument.from_dict(doc_with(progress=False, scenes=[scene(body="a"), scene(body="b")])))
        row = r_on.engine.progress_row()
        box = (row[0], row[1], row[2], row[3])
        t = r_on.timeline[1].start + 0.5
        on = ImageStat.Stat(r_on.frame(t).crop(box).convert("L")).mean[0]
        off = ImageStat.Stat(r_off.frame(t).crop(box).convert("L")).mean[0]
        self.assertGreater(on, off + 1)  # 진행 바 + 번호가 그려진다
        self.assertIsNone(r_off.engine.progress_row())
        top = ShortsV3Renderer(V3RenderDocument.from_dict(doc_with(progress={"position": "top"})))
        self.assertIsNone(top.engine.progress_row())

    def test_transitions_resolve_from_data(self) -> None:
        doc = self.docs["paragraphs_source_object"]
        self.assertEqual([doc.transition_of(s) for s in doc.scenes], ["punch", "dissolve", "slide", "cut"])

    def test_image_slot_status_codes(self) -> None:
        data = doc_with(scenes=[scene(layout="image_top", body="a"), scene(layout="image_top", image="images/none.png", body="b"),
                                scene(layout="image_top", image="images/not_an_image.png", body="c")])
        data["scenes"][0]["layout"] = "image_top"
        self.assertEqual(codes(data, self.dir), {"ASSET_MISSING", "ASSET_DECODE_FAILED"})  # 6-54: asset resolver 코드
        issues = LayoutEngine(V3RenderDocument.from_dict(data, base_dir=self.dir)).report()["issues"]
        self.assertIn("IMAGE_SLOT_EMPTY", [i["code"] for i in issues if i["severity"] == "warning"])


@unittest.skipUnless(HAS_FONTS, "Noto Sans KR 폰트가 없는 환경입니다.")
class LineageBatchTests(unittest.TestCase):
    def test_render_key_changes_with_content_template_and_image(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            make_images(tmp)
            data = doc_with(scenes=[scene(layout="image_top", image="images/landscape.png", body="a")])
            k1 = render_key(V3RenderDocument.from_dict(data, base_dir=tmp))
            self.assertEqual(k1, render_key(V3RenderDocument.from_dict(copy.deepcopy(data), base_dir=tmp)))
            self.assertNotEqual(k1, render_key(V3RenderDocument.from_dict(doc_with(title="다른 제목", scenes=data["scenes"]), base_dir=tmp)))
            self.assertNotEqual(k1, render_key(V3RenderDocument.from_dict(doc_with(audio={"volume": 0.5}, scenes=data["scenes"]), base_dir=tmp)))
            shutil.copy(tmp / "images" / "portrait.png", tmp / "images" / "landscape.png")  # 이미지만 교체
            self.assertNotEqual(k1, render_key(V3RenderDocument.from_dict(data, base_dir=tmp)))
            lin = lineage(V3RenderDocument.from_dict(data, base_dir=tmp))
            for key in ("content_id", "document_sha256", "template_sha256", "template_id", "asset_sha256", "renderer_version", "render_key"):
                self.assertIn(key, lin)

    def test_batch_validate_isolates_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            items = [
                BatchItem("ok", doc_with()),
                BatchItem("overflow", doc_with(title="아주 긴 제목 " * 40)),
                BatchItem("bad", doc_with(scenes=[])),
                item_from_shorts_script(Path(tmp) / "missing.json"),
                BatchItem("ok2", doc_with(title="두 번째")),
            ]
            summary = render_batch(items, Path(tmp) / "out", validate_only=True)
            statuses = [(r["name"], r["status"], r["reasons"]) for r in summary["results"]]
            self.assertEqual(statuses, [("ok", "validated", []), ("overflow", "blocked", ["TITLE_OVERFLOW"]),
                                        ("bad", "blocked", ["INVALID_DOCUMENT"]), ("missing", "blocked", ["SHORTS_SCRIPT_MISSING"]),
                                        ("ok2", "validated", [])])
            self.assertFalse((Path(tmp) / "out").exists())  # 검증만 할 때는 아무것도 쓰지 않는다

    def test_approved_items_reads_archive_only(self) -> None:
        from content_engine.media_archive import MediaArchiveRecord, save_archive

        def record(cid: str, **kw) -> MediaArchiveRecord:
            base = dict(content_id=cid, knowledge_id="k", platform="shorts", generation_status="valid", original_title="t",
                        original_body="b", rewritten_title="t", rewritten_body="b", source_url="", evidence=(),
                        evidence_unit_ids=(), created_at="2026-09-26T00:00:00+00:00", review_status="approved")
            return MediaArchiveRecord(**{**base, **kw})

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            archive, scripts = tmp / "archive.json", tmp / "scripts"
            scripts.mkdir()
            save_archive([record("c-ok", generation_id="g1"), record("c-noscript"), record("c-unreviewed", review_status="unreviewed"),
                          record("c-threads", platform="threads")], archive)
            (scripts / "c-ok.json").write_text(json.dumps({"content_id": "c-ok", "knowledge_id": "k", "title": "제목", "subtitle": "",
                                                             "cards": ["카드 하나."], "takeaway": "출처: https://example.com/a"},
                                                            ensure_ascii=False), encoding="utf-8")
            before = archive.read_bytes()
            items = approved_items(archive, scripts)
            self.assertEqual([i.name for i in items], ["c-ok", "c-noscript"])
            self.assertEqual(items[0].document["lineage"]["generation_id"], "g1")
            self.assertEqual(items[1].error.code, "SHORTS_SCRIPT_MISSING")
            self.assertEqual(archive.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
