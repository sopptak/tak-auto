"""6-55 Shorts Content Studio - Draft 저장소 / 편집 / 검증 / 미리보기 / Dashboard 라우트.

원본(Production Archive + ShortsScript)은 임시 폴더에 만든 복사본을 쓰고, 모든 흐름 뒤에 sha256이 같은지 본다.
ffmpeg가 필요한 테스트는 TAK_TEST_FFMPEG(또는 PATH의 ffmpeg)가 있을 때만 돈다(6-54 통합 테스트와 같은 규칙).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from content_engine import shorts_studio
from content_engine.shorts_studio import DraftError, DraftStore, apply_form, check, list_sources, preview, render_drafts
from content_engine.shorts_v3_document import V3RenderDocument
from content_engine.shorts_v3_pipeline import render_key
from tests.fixtures.shorts_v3_images import make_images

ROOT = Path(__file__).resolve().parents[1]
HAS_FONTS = Path("C:/Windows/Fonts/NotoSansKR-VF.ttf").exists()
FFMPEG = os.environ.get("TAK_TEST_FFMPEG") or shutil.which("ffmpeg")

SCRIPT = {
    "content_id": "content-studio-test01", "knowledge_id": "knowledge-test", "platform": "shorts",
    "title": "원본 제목", "subtitle": "",
    "cards": ["첫 번째 카드 문장입니다.", "두 번째 카드 문장입니다."],
    "takeaway": "출처: https://www.bbc.co.uk/news/articles/test", "brand": "티몽의 지혜", "created_at": "2026-09-20T00:00:00+00:00",
}


def _record(content_id: str, platform: str = "shorts", review_status: str = "approved", generation_id: str | None = "gen-test") -> dict:
    return {"content_id": content_id, "knowledge_id": "knowledge-test", "platform": platform, "generation_status": "valid",
            "original_title": "t", "original_body": "b", "rewritten_title": "t", "rewritten_body": "b",
            "source_url": "https://www.bbc.co.uk/news/articles/test", "evidence": [], "evidence_unit_ids": [],
            "created_at": "2026-09-20T00:00:00+00:00", "validation_errors": [], "error_message": None,
            "review_status": review_status, "edited_title": None, "edited_body": None, "generation_id": generation_id}


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class StudioCase(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.scripts = self.dir / "shorts_scripts"
        self.scripts.mkdir()
        (self.scripts / "content-studio-test01.json").write_text(json.dumps(SCRIPT, ensure_ascii=False), encoding="utf-8")
        self.archive = self.dir / "tak_media_archive.json"
        self.archive.write_text(json.dumps([_record("content-studio-test01"), _record("content-no-script"),
                                            _record("content-threads", platform="threads")]), encoding="utf-8")
        make_images(self.dir)
        self.store = DraftStore(self.dir / "drafts", ROOT)
        self.entry = list_sources([(self.archive, self.scripts)])[0]
        self.protected = {p: sha(p) for p in (self.archive, self.scripts / "content-studio-test01.json")}

    def tearDown(self) -> None:
        self.assertEqual(self.protected, {p: sha(p) for p in self.protected}, "원본(Production) 파일이 바뀌었습니다")

    def open(self) -> dict:
        return self.store.open_draft(self.entry)

    def edit(self, form: dict) -> tuple[dict, dict, bool]:
        draft = self.store.load("draft-content-studio-test01")
        return self.store.save(draft["draft_id"], apply_form(draft["document"], form))

    def img(self, name: str = "landscape.png") -> str:
        return str(self.dir / "images" / name)


class ContentSelectorTests(StudioCase):
    def test_lists_only_shorts_with_script_and_dedupes_sources(self) -> None:
        other = self.dir / "other_archive.json"
        other.write_text(json.dumps([_record("content-studio-test01", review_status="unreviewed")]), encoding="utf-8")
        entries = list_sources([(self.archive, self.scripts), (other, self.scripts), (self.dir / "missing.json", self.scripts)],
                               {"content-studio-test01": "FACT_CHECK_PASSED"})
        self.assertEqual([e["content_id"] for e in entries], ["content-studio-test01"])
        e = entries[0]
        self.assertEqual((e["title"], e["generation_id"], e["platform"], e["review_status"], e["fact_check"]),
                         ("원본 제목", "gen-test", "shorts", "approved", "FACT_CHECK_PASSED"))

    def test_fact_checks_from_manifest(self) -> None:
        m = self.dir / "manifest.json"
        m.write_text(json.dumps({"videos": [{"content_id": "a", "fact_check": "FACT_CHECK_PARTIAL"}]}), encoding="utf-8")
        self.assertEqual(shorts_studio.load_fact_checks(m), {"a": "FACT_CHECK_PARTIAL"})
        self.assertEqual(shorts_studio.load_fact_checks(self.dir / "none.json"), {})


class DraftModelTests(StudioCase):
    def test_draft_creation_clones_source(self) -> None:
        d = self.open()
        self.assertEqual((d["schema"], d["draft_id"], d["draft_version"], d["status"]),
                         ("shorts_draft/1", "draft-content-studio-test01", 1, "draft"))
        self.assertEqual(d["base_content_sha256"], sha(self.scripts / "content-studio-test01.json"))
        self.assertEqual((d["content_id"], d["generation_id"]), ("content-studio-test01", "gen-test"))
        self.assertEqual(d["document"]["title"], "원본 제목")
        self.assertEqual(d["document"]["lineage"]["content_id"], "content-studio-test01")
        for key in ("created_at", "updated_at", "base"):
            self.assertIn(key, d)
        self.assertTrue((self.dir / "drafts" / d["draft_id"] / "versions" / "v0001.json").exists())

    def test_draft_loading_and_reopen_keeps_edits(self) -> None:
        self.open()
        self.edit({"title": "사람이 고친 제목"})
        again = self.open()  # 같은 콘텐츠를 다시 골라도 편집 내용을 원본으로 덮어쓰지 않는다
        self.assertEqual((again["draft_version"], again["document"]["title"]), (2, "사람이 고친 제목"))
        self.assertEqual(self.store.load(again["draft_id"]), again)
        self.assertEqual([d["draft_id"] for d in self.store.list()], ["draft-content-studio-test01"])

    def test_missing_and_malicious_draft_ids(self) -> None:
        for bad in ("draft-none", "../data", "..\\x", "a/b", "", "shorts_scripts", "draft-../x"):
            with self.subTest(bad), self.assertRaises(DraftError) as ctx:
                self.store.load(bad)
            self.assertEqual(ctx.exception.code, "DRAFT_NOT_FOUND")
        with self.assertRaises(DraftError):
            self.store.open_draft({**self.entry, "content_id": "../../escape"})

    def test_save_versions_are_immutable_snapshots(self) -> None:
        d = self.open()
        v1 = self.dir / "drafts" / d["draft_id"] / "versions" / "v0001.json"
        before = sha(v1)
        _, _, saved = self.edit({"title": "v2 제목"})
        self.edit({"title": "v3 제목"})
        self.assertTrue(saved)
        self.assertEqual(sha(v1), before)
        self.assertEqual([v["draft_version"] for v in self.store.versions(d["draft_id"])], [1, 2, 3])
        self.assertEqual(self.store.load_version(d["draft_id"], 2)["document"]["title"], "v2 제목")
        self.assertEqual(self.store.load(d["draft_id"])["draft_version"], 3)

    def test_unchanged_save_does_not_bump_version(self) -> None:
        d = self.open()
        draft, _, saved = self.store.save(d["draft_id"], d["document"])
        self.assertFalse(saved)
        self.assertEqual(draft["draft_version"], 1)

    def test_stale_editor_gets_conflict(self) -> None:
        d = self.open()
        self.edit({"title": "다른 탭에서 저장"})
        with self.assertRaises(DraftError) as ctx:
            self.store.save(d["draft_id"], apply_form(d["document"], {"title": "늦은 저장"}), expected_version=1)
        self.assertEqual(ctx.exception.code, "DRAFT_CONFLICT")

    def test_revert_to_previous_version(self) -> None:
        d = self.open()
        self.edit({"title": "v2"})
        self.edit({"title": "v3"})
        reverted = self.store.revert(d["draft_id"], 1)
        self.assertEqual((reverted["draft_version"], reverted["document"]["title"]), (4, "원본 제목"))
        self.assertEqual(len(self.store.versions(d["draft_id"])), 4)  # 기록은 지우지 않는다

    def test_reset_to_production_content(self) -> None:
        d = self.open()
        self.edit({"title": "바꿈", "s0_body": "바꾼 본문", "s0_layout": "split"})
        reset = self.store.reset_to_base(d["draft_id"], self.entry)
        self.assertEqual(reset["document"], self.store.load_version(d["draft_id"], 1)["document"])
        self.assertEqual((reset["draft_version"], reset["note"]), (3, "원본으로 초기화"))


class EditingTests(StudioCase):
    def setUp(self) -> None:
        super().setUp()
        self.open()

    def scene(self, i: int = 0) -> dict:
        return self.store.load("draft-content-studio-test01")["document"]["scenes"][i]

    def test_title_short_long_multiline_stored_verbatim(self) -> None:
        for title in ("짧", "AI 의식 연구, 어디까지 허용할까? 사람이 직접 고친 긴 제목", "첫 줄\n둘째 줄"):
            with self.subTest(title):
                d, _, _ = self.edit({"title": title})
                self.assertEqual(d["document"]["title"], title)

    def test_empty_title_rejected(self) -> None:
        with self.assertRaises(DraftError) as ctx:
            self.edit({"title": "   "})
        self.assertEqual(ctx.exception.code, "TITLE_EMPTY")

    def test_overflowing_title_is_saved_but_flagged(self) -> None:
        d, report, saved = self.edit({"title": "아주 긴 제목 " * 20})
        self.assertTrue(saved)
        self.assertIn("TITLE_OVERFLOW", report["codes"])
        self.assertFalse(report["ok"])

    def test_field_too_long_rejected(self) -> None:
        with self.assertRaises(DraftError) as ctx:
            self.edit({"s0_body": "가" * (shorts_studio.MAX_FIELD_CHARS + 1)})
        self.assertEqual(ctx.exception.code, "FIELD_TOO_LONG")

    def test_body_and_headline_edit_without_rewriting(self) -> None:
        body = "첫 문단입니다.\n\n둘째 문단, 사람이 쓴 그대로."
        self.edit({"s0_body": body, "s0_headline": "헤드라인"})
        self.assertEqual((self.scene()["body"], self.scene()["headline"]), (body, "헤드라인"))
        self.edit({"s0_headline": ""})  # 빈 값 = 지우기
        self.assertNotIn("headline", self.scene())

    def test_long_body_saved_and_overflow_reported(self) -> None:
        long = "연구 범위와 실험 대상을 명확히 정하고, 독립적인 검토를 받아야 합니다. " * 12
        d, report, _ = self.edit({"s0_body": long})
        self.assertEqual(d["document"]["scenes"][0]["body"], long.strip())  # 요약하거나 자르지 않는다
        self.assertIn("BODY_OVERFLOW", report["codes"])

    def test_image_edit_path_fit_position(self) -> None:
        d, report, _ = self.edit({"s0_layout": "image_top", "s0_image_path": self.img(), "s0_image_fit": "contain",
                                  "s0_image_position": "0.25, 0.75"})
        self.assertEqual(self.scene()["image"], {"path": self.img(), "fit": "contain", "position": {"x": 0.25, "y": 0.75}})
        self.assertTrue(report["ok"], report)
        self.edit({"s0_image_path": self.img("portrait.png"), "s0_image_position": "top"})
        self.assertEqual(self.scene()["image"]["position"], "top")
        self.edit({"s0_image_path": ""})
        self.assertNotIn("image", self.scene())

    def test_missing_image_blocks_preview_with_asset_missing(self) -> None:
        _, report, saved = self.edit({"s0_layout": "image_top", "s0_image_path": str(self.dir / "없음.png")})
        self.assertTrue(saved)
        self.assertEqual(report["codes"], ["ASSET_MISSING"])
        self.assertIn("IMAGE_MISSING", shorts_studio.describe("ASSET_MISSING"))

    def test_invalid_image_spec_rejected(self) -> None:
        for form in ({"s0_image_fit": "stretch"}, {"s0_image_position": "a,b"}, {"s0_image_position": "middle"}):
            with self.subTest(form), self.assertRaises(DraftError) as ctx:
                self.edit({"s0_image_path": self.img(), **form})
            self.assertEqual(ctx.exception.code, "INVALID_IMAGE_SPEC")

    def test_every_layout_can_be_selected(self) -> None:
        for layout in ("image_top", "split", "text_focus", "image_full"):
            with self.subTest(layout):
                _, report, _ = self.edit({"s0_layout": layout, "s0_image_path": self.img()})
                self.assertEqual(self.scene()["layout"], layout)
                self.assertTrue(report["ok"], report)

    def test_invalid_layout_rejected(self) -> None:
        with self.assertRaises(DraftError) as ctx:
            self.edit({"s0_layout": "carousel"})
        self.assertEqual(ctx.exception.code, "INVALID_LAYOUT")

    def test_source_edit(self) -> None:
        self.edit({"s0_source_value": "Reuters"})
        self.assertEqual(self.scene()["source"], "Reuters")
        self.edit({"s0_source_value": "사피엔스", "s0_source_label": "책"})
        self.assertEqual(self.scene()["source"], {"label": "책", "value": "사피엔스"})
        self.edit({"s0_source_value": ""})  # 출처 없음 허용
        self.assertNotIn("source", self.scene())
        _, report, _ = self.edit({"s0_source_value": "아주 긴 출처 이름이 계속 이어지는 보고서 제목 2026년 9월 발행 부록 자료 모음 그리고 더"})
        self.assertIn("SOURCE_TRUNCATED", report["warnings"])

    def test_duration_validation(self) -> None:
        self.edit({"s0_duration": "4"})
        self.assertEqual(self.scene()["duration"], 4.0)
        for bad in ("0", "-1", "abc", "0.1", "999"):
            with self.subTest(bad), self.assertRaises(DraftError) as ctx:
                self.edit({"s0_duration": bad})
            self.assertEqual(ctx.exception.code, "INVALID_DURATION")
        _, report, _ = self.edit({"s0_duration": ""})  # 비우면 자동
        self.assertNotIn("duration", self.scene())
        self.assertAlmostEqual(sum(s["duration"] for s in report["scenes"]), report["total"], places=3)

    def test_progress_edit(self) -> None:
        d, _, _ = self.edit({"progress_enabled": "off"})
        self.assertEqual(d["document"]["progress"], {"enabled": False})
        self.assertFalse(V3RenderDocument.from_dict(d["document"]).progress["enabled"])
        d, _, _ = self.edit({"progress_enabled": "on", "progress_position": "top"})
        self.assertEqual(V3RenderDocument.from_dict(d["document"]).progress["position"], "top")
        with self.assertRaises(DraftError) as ctx:
            self.edit({"progress_position": "middle"})
        self.assertEqual(ctx.exception.code, "INVALID_TEMPLATE")

    def test_audio_edit_and_volume_validation(self) -> None:
        d, _, _ = self.edit({"audio_enabled": "off", "audio_volume": "0.5", "audio_background": "human"})
        audio = V3RenderDocument.from_dict(d["document"]).audio
        self.assertEqual((audio["enabled"], audio["volume"], audio["background"]), (False, 0.5, "human"))
        for bad in ("loud", "5", "-1"):
            with self.subTest(bad), self.assertRaises(DraftError) as ctx:
                self.edit({"audio_volume": bad})
            self.assertEqual(ctx.exception.code, "INVALID_TEMPLATE")

    def test_scene_duplicate_and_delete(self) -> None:
        d, _, _ = self.edit({"scene_op": "duplicate:0"})
        scenes = d["document"]["scenes"]
        self.assertEqual(scenes[0], scenes[1])
        count = len(scenes)
        d, _, _ = self.edit({"s1_body": "복제한 장면을 고친 본문", "scene_op": "delete:0"})
        self.assertEqual(len(d["document"]["scenes"]), count - 1)
        self.assertEqual(d["document"]["scenes"][0]["body"], "복제한 장면을 고친 본문")
        for bad in ("delete:99", "explode:0", "delete:x"):
            self.assertEqual(apply_form(d["document"], {"scene_op": bad}), d["document"])
        one = {**d["document"], "scenes": d["document"]["scenes"][:1]}
        self.assertEqual(len(apply_form(one, {"scene_op": "delete:0"})["scenes"]), 1)  # 마지막 장면은 지우지 않는다

    def test_base_drift_detected_without_touching_source(self) -> None:
        d = self.store.load("draft-content-studio-test01")
        self.assertIsNone(shorts_studio.base_drift(d, self.entry))
        self.assertEqual(shorts_studio.base_drift(d, None), "SOURCE_NOT_FOUND")
        copy_dir = self.dir / "changed"
        copy_dir.mkdir()
        changed = copy_dir / "content-studio-test01.json"
        changed.write_text(json.dumps({**SCRIPT, "title": "원본이 바뀜"}, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(shorts_studio.base_drift(d, {**self.entry, "script_path": str(changed)}), "BASE_CHANGED")

    def test_apply_form_does_not_mutate_input(self) -> None:
        doc = self.store.load("draft-content-studio-test01")["document"]
        frozen = json.dumps(doc, sort_keys=True, ensure_ascii=False)
        apply_form(doc, {"title": "x", "s0_body": "y", "s0_image_path": "z.png", "progress_enabled": "off"})
        self.assertEqual(json.dumps(doc, sort_keys=True, ensure_ascii=False), frozen)

    def test_render_key_follows_content_not_version(self) -> None:
        v1 = self.store.load("draft-content-studio-test01")["document"]
        key1 = render_key(V3RenderDocument.from_dict(v1))
        self.edit({"title": "바꾼 제목"})
        key2 = render_key(V3RenderDocument.from_dict(self.store.load("draft-content-studio-test01")["document"]))
        reverted = self.store.revert("draft-content-studio-test01", 1)
        self.assertNotEqual(key1, key2)
        self.assertEqual(render_key(V3RenderDocument.from_dict(reverted["document"])), key1)


class ErrorAndSafetyTests(StudioCase):
    def test_required_error_codes_have_human_text(self) -> None:
        for code in ("TITLE_OVERFLOW", "BODY_OVERFLOW", "SOURCE_OVERFLOW", "ASSET_MISSING", "INVALID_DURATION",
                     "INVALID_LAYOUT", "INVALID_TEMPLATE", "RENDER_FAILED", "QUALITY_GATE_FAILED"):
            with self.subTest(code):
                self.assertNotEqual(shorts_studio.describe(code), code)
                self.assertNotIn("Traceback", shorts_studio.describe(code))

    def test_studio_never_imports_production_writers_or_network(self) -> None:
        import ast
        tree = ast.parse((ROOT / "content_engine" / "shorts_studio.py").read_text(encoding="utf-8"))
        imported = {a.name for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
        imported |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        called = {getattr(n.func, "id", getattr(n.func, "attr", None)) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for name in ("upsert_archive", "upsert_generation_archive", "save_approved_shorts_script", "mark_approved",
                     "supersede_record", "requests", "urllib.request", "http.client", "socket", "content_engine.llm_provider",
                     "content_engine.youtube_publisher", "content_engine.threads_publisher"):
            with self.subTest(name):
                self.assertNotIn(name, imported | called)
        self.assertEqual({m for m in imported if m and m.startswith("content_engine.media_archive")}, {"content_engine.media_archive"})
        self.assertEqual({a for a in imported if a in ("load_archive", "upsert_archive")}, {"load_archive"})

    def test_preview_blocked_before_render_writes_no_mp4(self) -> None:
        d = self.open()
        self.edit({"s0_layout": "image_top", "s0_image_path": str(self.dir / "없음.png")})
        out = self.dir / "out"
        r = preview(self.store, d["draft_id"], out, ffmpeg="ffmpeg-does-not-exist")
        self.assertEqual((r["status"], r["error_code"]), ("blocked", "ASSET_MISSING"))
        self.assertEqual(r["lineage"]["draft_version"], 2)
        self.assertEqual(list(out.rglob("*.mp4")), [])
        self.assertEqual(self.store.previews(d["draft_id"])[-1]["error_code"], "ASSET_MISSING")

    @unittest.skipUnless(HAS_FONTS, "Noto Sans KR 폰트가 없는 환경입니다.")
    def test_render_exception_becomes_render_failed(self) -> None:
        d = self.open()
        r = preview(self.store, d["draft_id"], self.dir / "out", ffmpeg=str(self.dir / "no-ffmpeg.exe"))
        self.assertEqual((r["status"], r["error_code"]), ("failed", "RENDER_FAILED"))
        self.assertTrue(r["messages"][0])
        self.assertNotIn("traceback", r)  # 화면용 기록에는 traceback을 싣지 않는다

    def test_batch_isolates_failures(self) -> None:
        d = self.open()
        self.edit({"s0_layout": "image_top", "s0_image_path": str(self.dir / "없음.png")})
        summary = render_drafts(self.store, [d["draft_id"], "draft-none", "../bad"], self.dir / "out", ffmpeg="x")
        self.assertEqual((summary["total"], summary["success"], summary["failed"]), (3, 0, 3))
        self.assertEqual([r["error_code"] for r in summary["results"]], ["ASSET_MISSING", "DRAFT_NOT_FOUND", "DRAFT_NOT_FOUND"])


@unittest.skipUnless(HAS_FONTS and FFMPEG, "ffmpeg(PATH 또는 TAK_TEST_FFMPEG)/폰트가 없는 환경입니다.")
class PreviewRenderTests(StudioCase):
    def test_preview_render_quality_gate_and_lineage(self) -> None:
        d = self.open()
        self.edit({"title": "편집한 제목", "s0_layout": "image_top", "s0_image_path": self.img(), "s0_source_value": "Reuters"})
        out = self.dir / "out"
        r = preview(self.store, d["draft_id"], out, ffmpeg=FFMPEG)
        self.assertEqual((r["status"], r["quality"], r["error_code"]), ("success", "PASS", None), r)
        self.assertTrue(Path(r["output_path"]).exists())
        self.assertEqual((r["media"]["width"], r["media"]["height"], r["media"]["video_codec"], r["media"]["audio_codec"]),
                         (1080, 1920, "h264", "aac"))
        lin = r["lineage"]
        self.assertEqual((lin["draft_id"], lin["draft_version"], lin["base_content_id"], lin["generation_id"]),
                         (d["draft_id"], 2, "content-studio-test01", "gen-test"))
        self.assertEqual(lin["base_content_sha256"], d["base_content_sha256"])
        for key in ("document_sha256", "template_sha256", "asset_sha256", "render_key", "mp4_sha256"):
            self.assertTrue(lin.get(key), key)
        self.assertEqual(lin["mp4_sha256"], sha(Path(r["output_path"])))
        manifest = json.loads(Path(r["manifest_path"]).read_text(encoding="utf-8"))
        self.assertEqual((manifest["origin"]["kind"], manifest["origin"]["draft_version"]), ("shorts_draft", 2))
        again = preview(self.store, d["draft_id"], out, ffmpeg=FFMPEG)  # 같은 버전 = 같은 render key -> 다시 렌더하지 않음
        self.assertEqual(again["status"], "skipped")
        self.assertEqual(len(self.store.previews(d["draft_id"])), 2)

    def test_batch_preview_success_and_failure(self) -> None:
        d = self.open()
        summary = render_drafts(self.store, [d["draft_id"], "draft-none"], self.dir / "out", ffmpeg=FFMPEG)
        self.assertEqual([r["status"] for r in summary["results"]], ["success", "blocked"])
        self.assertEqual((summary["success"], summary["failed"]), (1, 1))


class DashboardRouteTests(StudioCase):
    def setUp(self) -> None:
        super().setUp()
        from scripts.run_scout_dashboard import DashboardConfig, make_handler_class

        self.config = DashboardConfig(
            daily_pack_path=self.dir / "d.json", answers_path=self.dir / "a.json", knowledge_path=self.dir / "k.json",
            skipped_path=self.dir / "s.json", sessions_path=self.dir / "ss.json", media_archive_path=self.archive,
            shorts_scripts_path=self.scripts, shorts_drafts_path=self.dir / "drafts", shorts_studio_out_path=self.dir / "out",
            shorts_studio_extra_sources=(), shorts_asset_dirs=(self.dir / "images",), fact_check_manifest_path=self.dir / "none.json",
            ffmpeg="ffmpeg-does-not-exist",
        )
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler_class(self.config))
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close(), thread.join(5)))

    def request(self, path: str, form: dict | None = None) -> tuple[int, str, str]:
        data = urllib.parse.urlencode(form or {}).encode() if form is not None else None
        req = urllib.request.Request(f"http://127.0.0.1:{self.server.server_address[1]}{path}", data=data)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status, resp.geturl(), resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as error:
            return error.code, path, error.read().decode("utf-8", "replace")

    def test_selector_open_edit_save_reset_flow(self) -> None:
        status, _, html = self.request("/shorts-studio")
        self.assertEqual(status, 200)
        for text in ("content-studio-test01", "원본 제목", "gen-test", "approved"):
            self.assertIn(text, html)
        self.assertNotIn("content-no-script", html)
        status, url, html = self.request("/shorts-studio/open", {"content_id": "content-studio-test01"})
        self.assertTrue(url.endswith("/shorts-studio/draft-content-studio-test01"))
        for field in ('name="title"', 's0_layout', 's0_image_path', 's0_body', 's0_source_value', 's0_duration',
                      'progress_enabled', 'audio_volume', 'Save Draft', 'Render Preview', '원본 Production Content로 초기화'):
            self.assertIn(field, html)
        form = {"expected_version": "1", "action": "save", "title": "웹에서 고친 제목", "s0_layout": "split",
                "s0_body": "웹 본문", "s0_source_value": "BBC", "s0_image_path": self.img(), "s0_headline": ""}
        status, url, html = self.request("/shorts-studio/draft-content-studio-test01/save", form)
        self.assertIn("notice=saved", url)
        draft = self.store.load("draft-content-studio-test01")
        self.assertEqual((draft["draft_version"], draft["document"]["title"], draft["document"]["scenes"][0]["layout"]),
                         (2, "웹에서 고친 제목", "split"))
        self.assertIn("/shorts-studio/asset?path=", html)  # 현재 이미지 썸네일
        status, _, html = self.request("/shorts-studio/draft-content-studio-test01/reset", {"target": "base"})
        self.assertEqual(self.store.load("draft-content-studio-test01")["document"]["title"], "원본 제목")

    def test_invalid_save_keeps_user_input_and_explains(self) -> None:
        self.request("/shorts-studio/open", {"content_id": "content-studio-test01"})
        status, _, html = self.request("/shorts-studio/draft-content-studio-test01/save",
                                       {"expected_version": "1", "title": "고친 제목", "s0_duration": "-3"})
        self.assertEqual(status, 400)
        self.assertIn("INVALID_DURATION", html)
        self.assertIn("고친 제목", html)  # 입력한 값을 잃지 않는다
        self.assertNotIn("Traceback", html)
        self.assertEqual(self.store.load("draft-content-studio-test01")["draft_version"], 1)

    def test_preview_button_shows_error_code_not_traceback(self) -> None:
        self.request("/shorts-studio/open", {"content_id": "content-studio-test01"})
        status, url, html = self.request("/shorts-studio/draft-content-studio-test01/save",
                                         {"expected_version": "1", "action": "preview", "s0_layout": "image_top",
                                          "s0_image_path": str(self.dir / "없음.png")})
        self.assertIn("notice=preview", url)
        self.assertIn("ASSET_MISSING", html)
        self.assertNotIn("Traceback", html)

    def test_file_routes_do_not_leak_other_files(self) -> None:
        self.request("/shorts-studio/open", {"content_id": "content-studio-test01"})
        for path in ("/shorts-studio/asset?path=data/tak_media_archive.json", "/shorts-studio/asset?path=C:/Windows/win.ini",
                     "/shorts-studio/asset?path=../../secret.png", "/shorts-studio/draft-content-studio-test01/file/..%2F..%2Fx.mp4",
                     "/shorts-studio/..%2Fdata/file/x.mp4"):
            with self.subTest(path):
                self.assertEqual(self.request(path)[0], 404)
        status, _, _ = self.request(f"/shorts-studio/asset?path={urllib.parse.quote(self.img())}")
        self.assertEqual(status, 200)

    def test_editor_has_no_approve_publish_or_secret_inputs(self) -> None:
        _, _, html = self.request("/shorts-studio/open", {"content_id": "content-studio-test01"})
        import re
        controls = " ".join(re.findall(r'(?:action|name|type)="([^"]*)"', html)).lower()
        self.assertIn("/save", controls)
        # 6-56: 사람 승인(Draft 저장소 기록)과 이미지 업로드는 요구사항이 됐다. 승인은 Draft 범위 route만 허용.
        self.assertEqual(re.findall(r'action="([^"]*approve[^"]*)"', html), ["/shorts-studio/draft-content-studio-test01/approve"])
        for word in ("publish", "youtube", "threads", "naver", "api_key", "token", "password", "secret", "dismiss"):
            with self.subTest(word):
                self.assertNotIn(word, controls)


if __name__ == "__main__":
    unittest.main()
