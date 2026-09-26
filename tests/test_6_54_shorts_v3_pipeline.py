"""6-54 Shorts V3 자동 생산 파이프라인 - 단위 테스트(ffmpeg 없음).

asset resolver(메타데이터/오류 코드/캐시/정책), 이미지 fit·crop·기준점, 제목·본문·출처·진행 표시 엔진,
입력 정규화(resolve_content), render key/lineage, 배치 보고서, 기존 5개 후보 호환성.
``data/``는 5개 후보 호환성 테스트에서만 **읽는다**(전후 해시 비교).
"""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from content_engine.shorts_v3_assets import AssetRequest, AssetResolver, orientation_of, resolve_assets
from content_engine.shorts_v3_document import V3RenderDocument, readable_source
from content_engine.shorts_v3_layout import LayoutEngine
from content_engine.shorts_v3_pipeline import (
    ContentItem, batch_report_markdown, build_render_document, item_from_shorts_script, lineage, quality_gate,
    render_batch, render_key, resolve_content, structure_issues, visual_review,
)
from content_engine.shorts_v3_template import V3Error, deep_merge, load_template, resolve_template
from tests.fixtures.shorts_v3_images import make_images

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "shorts_v3_pipeline"
HAS_FONTS = Path("C:/Windows/Fonts/NotoSansKR-VF.ttf").exists()
BASE = {"schema": "shorts_v3_document/1", "id": "t", "title": "제목", "lineage": {"content_id": "c1", "generation_id": "g1"},
        "scenes": [{"layout": "text_focus", "body": "본문."}]}
BODY = "연구 범위와 실험 대상을 명확히 정하고, 독립적인 검토를 받아야 합니다."
QUAD = {"tl": (255, 0, 0), "tr": (0, 255, 0), "bl": (0, 0, 255), "br": (255, 255, 0)}


def doc_with(**changes) -> dict:
    d = copy.deepcopy(BASE)
    d.update(changes)
    return d


def issue_codes(doc: V3RenderDocument) -> list[str]:
    return [i["code"] for i in structure_issues(doc, LayoutEngine(doc).report())]


def quadrant_image(path: Path, size=(1200, 800)) -> None:
    """네 사분면이 서로 다른 색인 이미지 - crop 기준점 검사용."""
    w, h = size
    img = Image.new("RGB", size)
    for key, box in {"tl": (0, 0, w // 2, h // 2), "tr": (w // 2, 0, w, h // 2), "bl": (0, h // 2, w // 2, h), "br": (w // 2, h // 2, w, h)}.items():
        img.paste(QUAD[key], box)
    img.save(path)


class TempDirCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        make_images(self.dir)

    def tearDown(self) -> None:
        self._tmp.cleanup()


class AssetResolverTests(TempDirCase):
    def test_metadata_for_three_orientations(self) -> None:
        r = AssetResolver()
        expected = {"landscape.png": (1600, 900, "landscape"), "portrait.png": (700, 1200, "portrait"), "square.png": (1000, 1000, "square")}
        for name, (w, h, orient) in expected.items():
            a = r.resolve(AssetRequest(f"images/{name}", self.dir, alt="대체 글", source="출처"))
            self.assertTrue(a.ok, a)
            self.assertEqual((a.width, a.height, a.orientation, a.format, a.filename), (w, h, orient, "PNG", name))
            self.assertAlmostEqual(a.aspect_ratio, round(w / h, 4))
            self.assertEqual(a.sha256, hashlib.sha256((self.dir / "images" / name).read_bytes()).hexdigest())
            self.assertEqual((a.alt, a.source, a.bytes), ("대체 글", "출처", (self.dir / "images" / name).stat().st_size))

    def test_failure_codes(self) -> None:
        Image.new("RGB", (400, 400)).save(self.dir / "images" / "pic.gif")
        Image.new("RGB", (100, 80)).save(self.dir / "images" / "tiny.png")
        good = (self.dir / "images" / "landscape.png").read_bytes()
        (self.dir / "images" / "truncated.png").write_bytes(good[: len(good) // 3])
        r = AssetResolver(min_width=320, min_height=320)
        cases = {"none.png": "ASSET_MISSING", "pic.gif": "ASSET_UNSUPPORTED_FORMAT", "not_an_image.png": "ASSET_DECODE_FAILED",
                 "truncated.png": "ASSET_DECODE_FAILED", "tiny.png": "ASSET_TOO_SMALL"}
        for name, code in cases.items():
            with self.subTest(name):
                a = r.resolve(AssetRequest(f"images/{name}", self.dir))
                self.assertFalse(a.ok)
                self.assertEqual(a.code, code)
                self.assertTrue(a.message)

    def test_hash_and_decode_are_cached(self) -> None:
        shutil.copy(self.dir / "images" / "square.png", self.dir / "images" / "square_copy.png")
        r = AssetResolver()
        a1 = r.resolve(AssetRequest("images/square.png", self.dir))
        r.resolve(AssetRequest("images/square.png", self.dir))
        a2 = r.resolve(AssetRequest("images/square_copy.png", self.dir))
        self.assertEqual(r.hash_computations, 2)  # 같은 파일은 한 번만 해시
        self.assertEqual(a1.sha256, a2.sha256)
        self.assertIs(r.load(a1), r.load(a2))  # 같은 내용은 한 번만 디코드
        self.assertEqual(r.decodes, 1)
        with self.assertRaises(ValueError):
            r.load(r.resolve(AssetRequest("images/none.png", self.dir)))

    def test_orientation_tolerance(self) -> None:
        self.assertEqual([orientation_of(1000, 1000), orientation_of(1040, 1000), orientation_of(1200, 1000), orientation_of(900, 1000)],
                         ["square", "square", "landscape", "portrait"])

    def test_resolve_assets_skips_empty_slots(self) -> None:
        doc = V3RenderDocument.from_dict(doc_with(scenes=[{"layout": "image_top", "body": "a"},
                                                         {"layout": "image_top", "image": "images/square.png", "body": "b"}]), base_dir=self.dir)
        self.assertEqual(list(resolve_assets(doc)), [1])


@unittest.skipUnless(HAS_FONTS, "Noto Sans KR 폰트가 없는 환경입니다.")
class AssetPolicyTests(TempDirCase):
    def test_missing_asset_blocks_by_default_and_warns_with_fallback_policy(self) -> None:
        data = doc_with(scenes=[{"layout": "image_top", "image": "images/none.png", "body": "a"}])
        block = V3RenderDocument.from_dict(data, base_dir=self.dir)
        self.assertEqual(quality_gate(structure_issues(block, LayoutEngine(block).report()))["codes"], ["ASSET_MISSING"])
        tpl = deep_merge(load_template("default"), {"image": {"on_missing": "fallback"}})
        lenient = V3RenderDocument.from_dict(data, base_dir=self.dir, template=tpl)
        verdict = quality_gate(structure_issues(lenient, LayoutEngine(lenient).report()))
        self.assertEqual((verdict["status"], [w["code"] for w in verdict["warnings"]]), ("PASS", ["ASSET_MISSING"]))

    def test_layout_can_require_an_image(self) -> None:
        tpl = deep_merge(load_template("default"), {"layouts": {"image_full": {"image_required": True}}})
        doc = V3RenderDocument.from_dict(doc_with(scenes=[{"layout": "image_full", "headline": "a"}]), template=tpl)
        self.assertIn("ASSET_REQUIRED", issue_codes(doc))


@unittest.skipUnless(HAS_FONTS, "Noto Sans KR 폰트가 없는 환경입니다.")
class ImageFitTests(TempDirCase):
    def _prepared(self, image: dict, layout: str = "image_top") -> Image.Image:
        quadrant_image(self.dir / "images" / "quad.png")
        doc = V3RenderDocument.from_dict(doc_with(scenes=[{"layout": layout, "image": {"path": "images/quad.png", **image}, "body": "a"}]),
                                         base_dir=self.dir)
        return LayoutEngine(doc).layouts[0].image

    def _center(self, img: Image.Image) -> tuple:
        return img.getpixel((img.width // 2, img.height // 2))

    def test_cover_focal_point_selects_quadrant(self) -> None:
        # split 슬롯은 세로로 길어서 가로 이미지를 cover로 자르면 기준점 쪽 사분면이 가운데에 온다
        for position, quad in (({"x": 0.0, "y": 0.0}, "tl"), ({"x": 1.0, "y": 0.0}, "tr"), ("left", None), ({"x": 1.0, "y": 1.0}, "br")):
            with self.subTest(position):
                img = self._prepared({"fit": "cover", "position": position, "scale": 2.0}, layout="split")
                if quad:
                    self.assertEqual(self._center(img), QUAD[quad])

    def test_crop_is_cover_alias(self) -> None:
        a = self._prepared({"fit": "crop", "position": "right"}, layout="split")
        b = self._prepared({"fit": "cover", "position": "right"}, layout="split")
        self.assertEqual(a.tobytes(), b.tobytes())

    def test_contain_keeps_whole_image(self) -> None:
        img = self._prepared({"fit": "contain"}, layout="split")
        colors = {img.getpixel((x, y)) for x in range(0, img.width, 7) for y in range(0, img.height, 7)}
        for rgb in QUAD.values():
            self.assertIn(rgb, colors)

    def test_prepared_image_matches_slot_ratio_for_all_orientations(self) -> None:
        for name in ("landscape", "portrait", "square"):
            for layout in ("image_top", "split", "image_full"):
                with self.subTest(name=name, layout=layout):
                    doc = V3RenderDocument.from_dict(doc_with(scenes=[{"layout": layout, "image": f"images/{name}.png", "headline": "a"}]),
                                                     base_dir=self.dir)
                    lay = LayoutEngine(doc).layouts[0]
                    w, h = lay.image_rect[2] - lay.image_rect[0], lay.image_rect[3] - lay.image_rect[1]
                    self.assertEqual(lay.asset.orientation, name)
                    self.assertAlmostEqual(lay.image.width / lay.image.height, w / h, places=1)

    def test_invalid_position_values(self) -> None:
        for bad in ({"x": "left"}, [0.1], "middle"):
            with self.subTest(bad), self.assertRaises(V3Error) as ctx:
                V3RenderDocument.from_dict(doc_with(scenes=[{"layout": "image_top", "image": {"path": "a.png", "position": bad}}]))
            self.assertEqual(ctx.exception.code, "INVALID_IMAGE_SPEC")


@unittest.skipUnless(HAS_FONTS, "Noto Sans KR 폰트가 없는 환경입니다.")
class TitleBodySourceTests(unittest.TestCase):
    def test_title_one_two_three_lines_and_centering(self) -> None:
        titles = {1: "짧은 제목", 2: "두 줄이 되는 조금 더 긴 제목 한 줄 더", 3: "세 줄이 되도록 아주 길게 쓴 제목 문장이 이어지고 또 이어져서 결국 세 번째 줄까지"}
        for lines, title in titles.items():
            with self.subTest(lines):
                engine = LayoutEngine(V3RenderDocument.from_dict(doc_with(title=title)))
                self.assertEqual(sum(b.lines for b in engine.title), lines)
                top, bottom = engine.title[0].bbox[1], engine.title[-1].bbox[3]
                rect = engine.title_rect
                self.assertLessEqual(abs((top + bottom) / 2 - (rect[1] + rect[3]) / 2), 2)  # 세로 가운데

    def test_body_reflow_order(self) -> None:
        results = {}
        for label, body in (("short", "짧다."), ("medium", BODY * 2), ("long", BODY * 3), ("very_long", BODY * 6)):
            doc = V3RenderDocument.from_dict(doc_with(scenes=[{"layout": "image_top", "headline": "헤드라인", "body": body}]))
            lay = LayoutEngine(doc).layouts[0]
            results[label] = (lay.variant, bool(lay.body))
        self.assertEqual(results, {"short": ("primary", True), "medium": ("primary", True),
                                   "long": ("fallback", True), "very_long": ("fallback", False)})
        very = V3RenderDocument.from_dict(doc_with(scenes=[{"layout": "image_top", "headline": "헤드라인", "body": BODY * 6}]))
        self.assertIn("BODY_OVERFLOW", issue_codes(very))

    def test_source_labels(self) -> None:
        tpl = load_template("default")
        self.assertEqual([readable_source(v, tpl) for v in (
            "https://www.bbc.co.uk/news/articles/x?at_medium=RSS", "https://edition.bbc.com/a", "https://www.reuters.com/world/x",
            "https://example.org/very/long/path", "책 「사피엔스」")], ["BBC", "BBC", "Reuters", "example.org", "책 「사피엔스」"])
        for source, expected in (("BBC", "출처 · BBC"), ({"label": "자료", "value": "Reuters"}, "자료 · Reuters")):
            doc = V3RenderDocument.from_dict(doc_with(scenes=[{"layout": "text_focus", "body": "a", "source": source}]))
            self.assertEqual(doc.scenes[0].source.display(doc.template), expected)

    def test_source_absent_collapses_footer(self) -> None:
        with_src = LayoutEngine(V3RenderDocument.from_dict(doc_with(scenes=[{"layout": "text_focus", "body": "a", "source": "BBC"}]))).layouts[0]
        without = LayoutEngine(V3RenderDocument.from_dict(doc_with())).layouts[0]
        self.assertGreater(without.content[3], with_src.content[3])
        self.assertEqual(without.source, [])


@unittest.skipUnless(HAS_FONTS, "Noto Sans KR 폰트가 없는 환경입니다.")
class ProgressEngineTests(unittest.TestCase):
    def test_scene_counts_one_to_six_without_overlap(self) -> None:
        for n in range(1, 7):
            for position in ("footer", "top"):
                with self.subTest(n=n, position=position):
                    scenes = [{"layout": "text_focus", "body": f"장면 {k}.", "source": "BBC"} for k in range(n)]
                    doc = V3RenderDocument.from_dict(doc_with(scenes=scenes, progress={"position": position}))
                    engine = LayoutEngine(doc)
                    self.assertEqual(engine.report()["overflow"], [])
                    self.assertEqual(set(engine.progress_boxes()), {"bar", "counter"})

    def test_progress_off_has_no_boxes(self) -> None:
        self.assertEqual(LayoutEngine(V3RenderDocument.from_dict(doc_with(progress=False))).progress_boxes(), {})

    def test_overlap_is_detected(self) -> None:
        # 진행 표시 줄을 거의 없애면 번호가 출처 줄과 겹친다 -> PROGRESS_OVERLAP
        tpl = deep_merge(load_template("default"), {"footer_rows": {"progress": 8, "gap": 0}})
        doc = V3RenderDocument.from_dict(doc_with(scenes=[{"layout": "text_focus", "body": "a",
                                                           "source": "아주 긴 출처 이름이 줄 끝까지 이어지는 보고서 제목과 발행일 정보"}]), template=tpl)
        self.assertIn("PROGRESS_OVERLAP", issue_codes(doc))


class TemplateEncoderTests(unittest.TestCase):
    def test_encoder_is_validated_template_data(self) -> None:
        self.assertEqual(load_template("default")["encoder"], {"preset": "medium", "crf": 20})
        for bad in ({"preset": "turbo"}, {"crf": 60}):
            with self.subTest(bad), self.assertRaises(V3Error) as ctx:
                resolve_template(load_template("default"), {"encoder": bad})
            self.assertEqual(ctx.exception.code, "INVALID_TEMPLATE")
        for bad in ({"image": {"on_missing": "ignore"}}, {"source_labels": ["BBC"]}):
            with self.subTest(bad), self.assertRaises(V3Error):
                resolve_template(load_template("default"), bad)


@unittest.skipUnless(HAS_FONTS, "Noto Sans KR 폰트가 없는 환경입니다.")
class InputKeyLineageTests(TempDirCase):
    def test_resolve_content_normalizes_all_inputs(self) -> None:
        script = self.dir / "script.json"
        script.write_text(json.dumps({"content_id": "c-s", "knowledge_id": "k", "title": "제목", "subtitle": "", "cards": ["카드."],
                                      "takeaway": "출처: https://www.bbc.co.uk/news/a"}, ensure_ascii=False), encoding="utf-8")
        document = self.dir / "doc.json"
        document.write_text(json.dumps(doc_with(), ensure_ascii=False), encoding="utf-8")
        broken = self.dir / "broken.json"
        broken.write_text("{", encoding="utf-8")
        items = [resolve_content(x) for x in (script, document, doc_with(id="inline"), broken, ContentItem("keep", doc_with()))]
        self.assertEqual([i.origin.get("kind") for i in items[:3]], ["shorts_script", "document", "inline"])
        self.assertEqual(items[3].error.code, "INVALID_DOCUMENT")
        self.assertEqual(items[4].name, "keep")
        for item in (items[0], items[1], items[2], items[4]):
            self.assertIsInstance(build_render_document(item), V3RenderDocument)
        self.assertEqual(build_render_document(items[0]).scenes[0].source.display(load_template("default")), "출처 · BBC")

    def test_render_key_inputs(self) -> None:
        base = V3RenderDocument.from_dict(doc_with())
        k = render_key(base)
        changed = {
            "generation_id": doc_with(lineage={"content_id": "c1", "generation_id": "g2"}),
            "content_id": doc_with(lineage={"content_id": "c2", "generation_id": "g1"}),
            "audio": doc_with(audio={"volume": 0.9}),
        }
        for name, data in changed.items():
            with self.subTest(name):
                self.assertNotEqual(k, render_key(V3RenderDocument.from_dict(data)))
        tpl = deep_merge(load_template("default"), {"encoder": {"preset": "slow"}})
        self.assertNotEqual(k, render_key(V3RenderDocument.from_dict(doc_with(), template=tpl)))
        self.assertEqual(k, render_key(V3RenderDocument.from_dict(doc_with())))

    def test_lineage_fields(self) -> None:
        doc = V3RenderDocument.from_dict(doc_with(scenes=[{"layout": "image_top", "image": "images/square.png", "body": "a"}],
                                                  lineage={"content_id": "c1", "generation_id": "g1", "source_script_sha256": "abc"}),
                                         base_dir=self.dir)
        lin = lineage(doc)
        for key in ("content_id", "generation_id", "source_script_sha256", "document_sha256", "template_sha256", "asset_sha256",
                    "renderer_version", "render_key"):
            self.assertIn(key, lin)
        self.assertEqual(lin["asset_sha256"]["images/square.png"], hashlib.sha256((self.dir / "images/square.png").read_bytes()).hexdigest())

    def test_visual_review_summary(self) -> None:
        doc = V3RenderDocument.from_dict(doc_with(scenes=[{"layout": "image_top", "image": "images/portrait.png", "body": "a", "source": "BBC"},
                                                         {"layout": "split", "body": "b"}, {"layout": "text_focus", "body": "c"}]),
                                         base_dir=self.dir)
        engine = LayoutEngine(doc)
        review = visual_review(doc, engine.report(), engine.assets, None)
        self.assertEqual(review["image_types"], ["portrait", "placeholder", None])
        self.assertEqual((review["scene_count"], review["sources"][0], review["audio"]), (3, "출처 · BBC", False))


@unittest.skipUnless(HAS_FONTS, "Noto Sans KR 폰트가 없는 환경입니다.")
class BatchReportTests(TempDirCase):
    def test_fixture_batch_validate_isolates_broken_asset(self) -> None:
        for f in FIXTURES.glob("*.json"):
            shutil.copy(f, self.dir / f.name)
        summary = render_batch(sorted(self.dir.glob("*.json")), self.dir / "out", validate_only=True)
        by = {r["name"].removeprefix("fixture-654-"): (r["status"], r["error_code"]) for r in summary["results"]}
        self.assertEqual(by.pop("broken_asset"), ("blocked", "ASSET_MISSING"))
        self.assertTrue(all(v == ("validated", None) for v in by.values()), by)
        self.assertEqual((summary["total"], summary["success"], summary["failed"]), (6, 5, 1))

    def test_markdown_report_has_required_columns(self) -> None:
        summary = {"renderer_version": "v", "total": 2, "success": 1, "failed": 1, "counts": {"success": 1, "blocked": 1},
                   "performance": {"total_seconds": 1.0, "rendered": 1, "avg_render_seconds": 1.0, "output_bytes": 10},
                   "results": [{"name": "a", "content_id": "c", "generation_id": "g", "template": "default", "layouts": ["split"],
                                "status": "success", "output_path": "x/a.mp4", "duration": 3.0, "sha256": "f" * 64, "reasons": []},
                               {"name": "b", "content_id": "d", "generation_id": None, "template": None, "layouts": None,
                                "status": "blocked", "reasons": ["ASSET_MISSING"]}]}
        md = batch_report_markdown(summary)
        for text in ("| name | content_id | generation_id | template | layouts | status | output | duration | sha256 | error |",
                     "| a | c | g | default | split | success | a.mp4 | 3.0 | ffffffffffffffff | - |", "ASSET_MISSING"):
            self.assertIn(text, md)


@unittest.skipUnless(HAS_FONTS, "Noto Sans KR 폰트가 없는 환경입니다.")
class FiveCandidateCompatibilityTests(unittest.TestCase):
    """6-51 후보 5개: ShortsScript -> adapter -> Render Document -> 검증. 원본은 읽기만 한다."""
    CANDIDATES = [("data/shorts_scripts", "content-e787c9201b94a948", None),
                  ("data/shorts_scripts", "content-3ae2d78568210164", None),
                  ("artifacts/6-48-recovery-staging/data/shorts_scripts", "content-ec0c38b9a20c424c", "gen-20260920T033856-6e8d98fb"),
                  ("artifacts/6-48-recovery-staging/data/shorts_scripts", "content-e3b8d986ea6db98e", "gen-20260920T033856-6e8d98fb"),
                  ("artifacts/6-48-recovery-staging/data/shorts_scripts", "content-91869ed8be17f3f3", "gen-20260920T033856-6e8d98fb")]

    def test_candidates_validate(self) -> None:
        present = [(ROOT / d / f"{c}.json", c, g) for d, c, g in self.CANDIDATES if (ROOT / d / f"{c}.json").exists()]
        if not present:
            self.skipTest("후보 ShortsScript가 이 환경에 없습니다.")
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p, _, _ in present}
        with tempfile.TemporaryDirectory() as tmp:
            items = [item_from_shorts_script(p, generation_id=g, name=c) for p, c, g in present]
            summary = render_batch(items, Path(tmp), validate_only=True)
        for r, (_, c, g) in zip(summary["results"], present):
            with self.subTest(c):
                self.assertEqual((r["status"], r["content_id"], r["generation_id"]), ("validated", c, g))
        self.assertEqual(before, {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in before})


class ContentAgnosticGuardTests(unittest.TestCase):
    """렌더 엔진 코드에 특정 콘텐츠(content_id, generation_id, 제목, 문장)가 들어가면 안 된다(6-54 9장)."""
    ENGINE = ["shorts_v3_template.py", "shorts_v3_document.py", "shorts_v3_assets.py", "shorts_v3_layout.py",
              "shorts_v3_renderer.py", "shorts_v3_pipeline.py", "shorts_v3_adapter.py", "shorts_v3_contract.py"]

    def test_engine_has_no_content_specific_strings(self) -> None:
        import re
        sources = {n: (ROOT / "content_engine" / n).read_text(encoding="utf-8") for n in self.ENGINE}
        needles = set()
        for d in ("data/shorts_scripts", "artifacts/6-48-recovery-staging/data/shorts_scripts", "tests/fixtures/shorts_v3",
                  "tests/fixtures/shorts_v3_engine", "tests/fixtures/shorts_v3_pipeline"):
            for f in (ROOT / d).glob("*.json") if (ROOT / d).exists() else []:
                data = json.loads(f.read_text(encoding="utf-8"))
                needles |= {data.get("title"), data.get("content_id"), (data.get("lineage") or {}).get("generation_id")}
                needles |= {c[:20] for c in data.get("cards", [])} | {s.get("body", "")[:20] for s in data.get("scenes", [])}
        needles = {n for n in needles if n and len(n) >= 6}
        self.assertGreater(len(needles), 10)
        for name, src in sources.items():
            with self.subTest(name):
                self.assertIsNone(re.search(r"content-[0-9a-f]{16}|gen-\d{8}T", src))
                self.assertEqual([n for n in needles if n in src], [])


@unittest.skipUnless(HAS_FONTS, "Noto Sans KR 폰트가 없는 환경입니다.")
class EditorContractTests(TempDirCase):
    def test_editable_fields_come_from_template(self) -> None:
        from content_engine.shorts_v3_contract import editable_fields
        fields = editable_fields()
        self.assertEqual(fields["scene"]["layout"], ["image_full", "image_top", "split", "text_focus"])
        self.assertIn("slide", fields["scene"]["transition"])
        self.assertIn("lineage", fields["read_only"])
        tpl = deep_merge(load_template("default"), {"layouts": {"quote": {"text": [0.1, 0.1, 0.9, 0.9]}}})
        self.assertIn("quote", editable_fields(tpl)["scene"]["layout"])  # 레이아웃 추가 = 템플릿만

    def test_check_document_gives_codes_without_rendering(self) -> None:
        from content_engine.shorts_v3_contract import check_document
        ok = check_document(doc_with(scenes=[{"layout": "image_top", "image": "images/square.png", "body": "a"}]), self.dir)
        self.assertTrue(ok["ok"])
        self.assertEqual(len(ok["scenes"]), 2)  # 장면 + 엔드카드
        bad = check_document(doc_with(scenes=[{"layout": "image_top", "image": "images/none.png", "body": "a"}]), self.dir)
        self.assertEqual((bad["ok"], bad["codes"]), (False, ["ASSET_MISSING"]))
        self.assertEqual(check_document(doc_with(scenes=[]))["codes"], ["INVALID_DOCUMENT"])

    def test_resolve_asset_entry_point_and_provider_interface(self) -> None:
        from content_engine.shorts_v3_assets import AssetProvider, resolve_asset
        self.assertTrue(resolve_asset(AssetRequest("images/portrait.png", self.dir)).ok)
        with self.assertRaises(NotImplementedError):
            AssetProvider().search("query")


if __name__ == "__main__":
    unittest.main()
