"""6-56 Shorts Editor 완성 - 운영 시나리오 테스트(요청서 11장 A~Z + 승인/업로드/정지 화면/목록 필터/Range).

원본(Production) 파일은 6-55 StudioCase처럼 임시 폴더에 만든 복사본이고, 모든 테스트 뒤에 sha256이 같은지 본다.
ffmpeg가 필요한 테스트는 TAK_TEST_FFMPEG(또는 PATH의 ffmpeg)가 있을 때만 돈다.
"""

from __future__ import annotations

import hashlib
import io
import json
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from PIL import Image

from content_engine import shorts_studio as studio
from content_engine.shorts_studio import DraftError, apply_form, apply_meta, check, preview
from content_engine.shorts_v3_document import V3RenderDocument
from content_engine.shorts_v3_pipeline import render_key
from tests.test_6_55_shorts_studio import FFMPEG, HAS_FONTS, ROOT, SCRIPT, StudioCase, _record, sha

DID = "draft-content-studio-test01"


class EditorCase(StudioCase):
    def setUp(self) -> None:
        super().setUp()
        self.open()

    def doc(self) -> dict:
        return self.store.load(DID)["document"]

    def scene(self, i: int = 0) -> dict:
        return self.doc()["scenes"][i]


@unittest.skipUnless(HAS_FONTS, "Noto Sans KR 폰트가 없는 환경입니다.")
class EditWorkflowTests(EditorCase):
    def test_b_c_e_f_title_body_layout_duration_saved_as_new_versions(self) -> None:
        d, _, saved = self.edit({"title": "고친 제목", "s0_body": "고친 본문", "s0_layout": "image_top",
                                 "s0_image_path": self.img(), "s0_duration": "5"})
        self.assertTrue(saved)
        self.assertEqual((d["draft_version"], d["parent_version"]), (2, 1))
        s = self.scene()
        self.assertEqual((self.doc()["title"], s["body"], s["layout"], s["duration"]), ("고친 제목", "고친 본문", "image_top", 5.0))

    def test_d_image_replace_remove_and_advanced_path(self) -> None:
        self.edit({"s0_image_path": self.img("square.png")})
        self.assertEqual(self.scene()["image"]["path"], self.img("square.png"))
        self.edit({"s0_image_path": self.img("square.png"), "s0_image_custom": self.img("portrait.png")})  # 고급 입력이 우선
        self.assertEqual(self.scene()["image"]["path"], self.img("portrait.png"))
        self.edit({"s0_image_path": "", "s0_image_custom": ""})
        self.assertNotIn("image", self.scene())

    def test_g_frame_duplicate_move_delete(self) -> None:
        n = len(self.doc()["scenes"])
        self.edit({"s0_headline": "훅", "scene_op": "duplicate:0"})
        self.edit({"s1_headline": "둘째", "scene_op": "down:0"})
        scenes = self.doc()["scenes"]
        self.assertEqual((len(scenes), scenes[0]["headline"], scenes[1]["headline"]), (n + 1, "둘째", "훅"))
        self.edit({"scene_op": "up:1"})
        self.assertEqual(self.doc()["scenes"][0]["headline"], "훅")
        for op in ("up:0", f"down:{n}", "delete:99"):  # 경계 밖은 아무 일도 안 한다
            self.assertEqual(apply_form(self.doc(), {"scene_op": op}), self.doc())
        self.edit({"scene_op": "delete:1"})
        self.assertEqual(len(self.doc()["scenes"]), n)

    def test_emphasis_and_subtitle(self) -> None:
        _, report, _ = self.edit({"s0_body": "핵심은 기준입니다.", "s0_emphasis": "기준\n\n", "s0_subtitle": "한 줄 자막"})
        self.assertEqual((self.scene()["emphasis"], self.scene()["subtitle"]), (["기준"], "한 줄 자막"))
        self.assertNotIn("EMPHASIS_NOT_FOUND", report["warnings"])
        _, report, _ = self.edit({"s0_emphasis": "본문에 없는 말"})
        self.assertIn("EMPHASIS_NOT_FOUND", report["warnings"])

    def test_h_reset_and_i_version_fields(self) -> None:
        self.edit({"title": "바꿈"})
        d = self.store.reset_to_base(DID, self.entry)
        self.assertEqual((d["draft_version"], d["parent_version"], d["document"]["title"]), (3, 2, "원본 제목"))
        v = self.store.versions(DID)[-1]
        for key in ("draft_version", "parent_version", "updated_at", "modified_by", "document_sha256"):
            self.assertTrue(v.get(key) is not None, key)
        self.assertEqual(studio.draft_state(d, []), "DRAFT")

    def test_v_same_content_is_idempotent(self) -> None:
        d, _, saved = self.edit({"title": "같은 제목"})
        again, _, saved_again = self.edit({"title": "같은 제목"})
        self.assertEqual((saved, saved_again, again["draft_version"]), (True, False, d["draft_version"]))

    def test_meta_is_versioned_but_does_not_change_render_key(self) -> None:
        key = render_key(V3RenderDocument.from_dict(self.doc()))
        d = self.store.load(DID)
        new, _, saved = self.store.save(DID, d["document"], meta=apply_meta(d["meta"], {"meta_category": "역사", "meta_language": "ko"}))
        self.assertTrue(saved)
        self.assertEqual(new["meta"]["category"], "역사")
        self.assertEqual(render_key(V3RenderDocument.from_dict(new["document"])), key)
        self.assertEqual(d["meta"]["master_content_id"], "content-studio-test01")

    def test_render_document_keeps_content_and_design_in_one_contract(self) -> None:
        """콘텐츠(제목/본문/출처)와 장면 디자인(레이아웃/이미지/길이)은 한 V3 문서, 화면 틀은 템플릿. 분류는 meta."""
        doc = self.doc()
        self.assertEqual(doc["schema"], "shorts_v3_document/1")
        self.assertNotIn("category", json.dumps(doc, ensure_ascii=False))


@unittest.skipUnless(HAS_FONTS, "Noto Sans KR 폰트가 없는 환경입니다.")
class GateTests(EditorCase):
    def test_l_pass_and_m_blocked_with_scene_numbered_sentences(self) -> None:
        ok = check(self.doc(), ROOT)
        self.assertEqual(ok["verdict"], "PASS")
        _, bad, _ = self.edit({"s1_body": "연구 범위와 실험 대상을 명확히 정하고, 독립적인 검토를 받아야 합니다. " * 15})
        self.assertEqual(bad["verdict"], "BLOCKED")
        item = next(i for i in bad["items"] if i["code"] == "BODY_OVERFLOW")
        self.assertTrue(item["text"].startswith("장면 2: 본문이 화면에 들어가지 않습니다"), item)

    def test_n_missing_asset_and_o_p_q_r_long_text(self) -> None:
        cases = [({"s0_layout": "image_top", "s0_image_path": str(self.dir / "없음.png")}, "BLOCKED", "ASSET_MISSING"),
                 ({"title": "아주 긴 제목이 계속 이어집니다 " * 8}, "BLOCKED", "TITLE_OVERFLOW"),
                 ({"s0_body": "긴 본문 " * 150}, "BLOCKED", "BODY_OVERFLOW"),
                 ({"s0_source_value": "아주 긴 출처 이름이 계속 이어지는 보고서 제목 2026년 9월 발행 부록 자료 모음 그리고 더"}, "WARNING", "SOURCE_TRUNCATED")]
        for form, verdict, code in cases:
            with self.subTest(code):
                report = check(apply_form(self.doc(), form), ROOT)
                self.assertEqual(report["verdict"], verdict)
                self.assertIn(code, [i["code"] for i in report["items"]])

    def test_s_t_u_korean_english_numbers_symbols_render_with_font(self) -> None:
        for text in ("한글 본문입니다. 신기술을 마주하는 기준.", "English body: AI models may be conscious?",
                     "숫자·기호 1,234.5% → 2026-09-27 (A/B) #1 · “인용” … 「책」 €10"):
            with self.subTest(text):
                report = check(apply_form(self.doc(), {"s0_body": text, "title": text[:20]}), ROOT)
                self.assertEqual(report["verdict"], "PASS", report["items"])

    def test_unsupported_script_is_flagged_not_silent(self) -> None:
        report = check(apply_form(self.doc(), {"s0_body": "مرحبا بالعالم 😀"}), ROOT)
        self.assertIn("FONT_GLYPH_MISSING", report["warnings"])
        self.assertEqual(studio.missing_glyphs("가A1%あ漢", "C:/Windows/Fonts/NotoSansKR-VF.ttf"), [])

    def test_source_missing_and_image_ratio_warnings(self) -> None:
        report = check(apply_form(self.doc(), {"s0_source_value": "", "s1_source_value": "", "s2_source_value": ""}), ROOT)
        self.assertIn("SOURCE_MISSING", report["warnings"])
        report = check(apply_form(self.doc(), {"s0_layout": "image_top", "s0_image_path": self.img("portrait.png")}), ROOT)
        self.assertIn("IMAGE_RATIO_CROP", report["warnings"])
        self.assertEqual(report["verdict"], "WARNING")
        report = check(apply_form(self.doc(), {"s0_layout": "image_top", "s0_image_path": self.img("portrait.png"), "s0_image_fit": "contain"}), ROOT)
        self.assertNotIn("IMAGE_RATIO_CROP", report["warnings"])


class GuardTests(StudioCase):
    def test_x_same_content_id_other_generation_is_not_mixed(self) -> None:
        d = self.open()
        other = {**self.entry, "generation_id": "gen-other"}
        with self.assertRaises(DraftError) as ctx:
            self.store.open_draft(other)
        self.assertEqual(ctx.exception.code, "GENERATION_MISMATCH")
        r = preview(self.store, d["draft_id"], self.dir / "out", ffmpeg="x", entry=other)
        self.assertEqual((r["status"], r["error_code"]), ("blocked", "GENERATION_MISMATCH"))
        with self.assertRaises(DraftError):
            self.store.reset_to_base(d["draft_id"], other)

    def test_y_superseded_content_cannot_be_opened_rendered_or_approved(self) -> None:
        d = self.open()
        sup = {**self.entry, "review_status": "superseded", "superseded_by": "content-new"}
        with self.assertRaises(DraftError) as ctx:
            self.store.open_draft(sup)
        self.assertEqual(ctx.exception.code, "SUPERSEDED")
        r = preview(self.store, d["draft_id"], self.dir / "out", ffmpeg="x", mode="final", entry=sup)
        self.assertEqual(r["error_code"], "SUPERSEDED")
        self.assertIn("SUPERSEDED", studio.approval_blockers(self.store, d["draft_id"], sup))
        self.assertEqual(list((self.dir / "out").rglob("*.mp4")), [])

    def test_approval_requires_final_render(self) -> None:
        d = self.open()
        self.assertEqual(studio.approval_blockers(self.store, d["draft_id"], self.entry), ["APPROVAL_NOT_READY"])
        with self.assertRaises(DraftError):
            studio.approve(self.store, d["draft_id"], self.entry)
        self.assertEqual(self.store.approvals(d["draft_id"]), [])

    def test_upload_validation(self) -> None:
        assets = self.dir / "assets"
        buf = io.BytesIO()
        Image.new("RGB", (640, 480), (10, 120, 200)).save(buf, "JPEG")
        saved = studio.store_asset(buf.getvalue(), "내 사진 (1).jpg", assets)
        self.assertEqual((saved.parent.name, saved.suffix), ("uploads", ".jpg"))
        self.assertEqual(studio.store_asset(buf.getvalue(), "다른 이름.jpg", assets).read_bytes(), saved.read_bytes())
        small = io.BytesIO()
        Image.new("RGB", (100, 100)).save(small, "PNG")
        gif = io.BytesIO()
        Image.new("RGB", (400, 400)).save(gif, "GIF")
        for data in (b"not an image", small.getvalue(), gif.getvalue(), b""):
            with self.subTest(len(data)), self.assertRaises(DraftError) as ctx:
                studio.store_asset(data, "x.png", assets)
            self.assertEqual(ctx.exception.code, "UPLOAD_INVALID")

    @unittest.skipUnless(HAS_FONTS, "Noto Sans KR 폰트가 없는 환경입니다.")
    def test_scene_frames_use_real_renderer_and_cache(self) -> None:
        d = self.open()
        frames = studio.scene_frames(self.store, d["draft_id"])
        self.assertIsNone(frames["error"])
        self.assertEqual(len(frames["frames"]), len(d["document"]["scenes"]) + 1)  # + 엔드카드
        self.assertTrue(frames["frames"][-1]["end_card"])
        png = self.store._dir(d["draft_id"]) / "frames" / frames["frames"][0]["file"]
        self.assertEqual(Image.open(png).size, (360, 640))
        self.assertEqual(studio.scene_frames(self.store, d["draft_id"]), frames)  # 캐시
        self.edit({"s0_layout": "image_top", "s0_image_path": str(self.dir / "없음.png")})
        self.assertIsNone(studio.scene_frames(self.store, d["draft_id"])["error"])  # 없는 이미지는 빈 틀로 그려 위치를 보여준다(렌더는 게이트가 막음)
        self.edit({"s0_body": "긴 본문 " * 150})
        self.assertEqual(studio.scene_frames(self.store, d["draft_id"])["error"], "BODY_OVERFLOW")

    def test_draft_state_derivation(self) -> None:
        d = {"draft_version": 2, "note": "편집", "check": {"verdict": "PASS"}}
        self.assertEqual(studio.draft_state(None, []), "NO_DRAFT")
        self.assertEqual(studio.draft_state(d, []), "EDITED")
        self.assertEqual(studio.draft_state(d, [{"draft_version": 2, "status": "success", "mode": "preview"}]), "PREVIEW_READY")
        self.assertEqual(studio.draft_state(d, [{"draft_version": 2, "status": "skipped", "mode": "final"}]), "RENDERED")
        self.assertEqual(studio.draft_state(d, [{"draft_version": 2, "status": "blocked"}]), "BLOCKED")
        self.assertEqual(studio.draft_state(d, [{"draft_version": 1, "status": "success", "mode": "final"}]), "EDITED")
        self.assertEqual(studio.draft_state(d, [], [{"draft_version": 2}]), "APPROVED")
        self.assertEqual(studio.draft_state(d, [], [{"draft_version": 1}]), "EDITED")  # 승인 후 고치면 승인이 아니다
        self.assertEqual(studio.draft_state({**d, "check": {"verdict": "BLOCKED"}}, []), "BLOCKED")


@unittest.skipUnless(HAS_FONTS and FFMPEG, "ffmpeg(PATH 또는 TAK_TEST_FFMPEG)/폰트가 없는 환경입니다.")
class RenderApprovalTests(EditorCase):
    def test_j_k_z_preview_then_final_then_approve_then_edit_invalidates(self) -> None:
        self.edit({"title": "렌더 테스트", "s0_layout": "split", "s0_image_path": self.img("square.png")})
        out = self.dir / "out"
        p = preview(self.store, DID, out, ffmpeg=FFMPEG, mode="preview", entry=self.entry)
        f = preview(self.store, DID, out, ffmpeg=FFMPEG, mode="final", entry=self.entry)
        for r, mode in ((p, "preview"), (f, "final")):
            with self.subTest(mode):
                self.assertEqual((r["status"], r["quality"], r["mode"]), ("success", "PASS", mode), r.get("errors"))
                self.assertEqual((r["media"]["width"], r["media"]["height"]), (1080, 1920))
                self.assertTrue(r["output_path"].endswith(f"-v0002-{mode}.mp4"))
                self.assertEqual(r["lineage"]["draft_version"], 2)
                self.assertEqual(r["lineage"]["mp4_sha256"], sha(Path(r["output_path"])))
        # 같은 문서·렌더러: 길이·프레임 수·장면 배치가 같고, 인코더 설정(템플릿 해시)만 다르다
        self.assertEqual((p["duration"], p["media"]["frames"], p["layouts"]), (f["duration"], f["media"]["frames"], f["layouts"]))
        self.assertNotEqual(p["lineage"]["template_sha256"], f["lineage"]["template_sha256"])
        m = json.loads(Path(f["manifest_path"]).read_text(encoding="utf-8"))
        self.assertEqual((m["origin"]["kind"], m["origin"]["mode"], m["origin"]["draft_version"]), ("shorts_draft", "final", 2))
        self.assertEqual(preview(self.store, DID, out, ffmpeg=FFMPEG, mode="final")["status"], "skipped")  # V idempotency
        self.assertEqual(studio.draft_state(self.store.load(DID), self.store.previews(DID)), "RENDERED")
        a = studio.approve(self.store, DID, self.entry)
        self.assertEqual((a["draft_version"], a["mp4_sha256"], a["render_key"]), (2, f["sha256"], f["render_key"]))
        self.assertEqual(a["publish_contract"]["artifact_sha256"], f["sha256"])
        self.assertEqual(studio.draft_state(self.store.load(DID), self.store.previews(DID), self.store.approvals(DID)), "APPROVED")
        self.edit({"title": "승인 후 수정"})
        self.assertNotEqual(studio.draft_state(self.store.load(DID), self.store.previews(DID), self.store.approvals(DID)), "APPROVED")
        studio.revoke_approval(self.store, DID)
        self.assertTrue(all(x["revoked"] for x in self.store.approvals(DID)))

    def test_approval_blocked_when_source_changed_after_draft(self) -> None:
        preview(self.store, DID, self.dir / "out", ffmpeg=FFMPEG, mode="final", entry=self.entry)
        changed = self.dir / "changed"
        changed.mkdir()
        (changed / "content-studio-test01.json").write_text(json.dumps({**SCRIPT, "title": "원본 변경"}, ensure_ascii=False), encoding="utf-8")
        entry = {**self.entry, "script_path": str(changed / "content-studio-test01.json")}
        self.assertEqual(studio.approval_blockers(self.store, DID, entry), ["BASE_CHANGED"])
        self.assertEqual(studio.approval_blockers(self.store, DID, self.entry), [])


def _multipart(fields: dict, files: dict) -> tuple[bytes, str]:
    boundary = "----tak656boundary"
    out = b""
    for k, v in fields.items():
        out += f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
    for k, (name, data) in files.items():
        out += f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"; filename="{name}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode() + data + b"\r\n"
    return out + f"--{boundary}--\r\n".encode(), f"multipart/form-data; boundary={boundary}"


class EditorHttpTests(StudioCase):
    def setUp(self) -> None:
        super().setUp()
        from scripts.run_scout_dashboard import DashboardConfig, make_handler_class

        self.assets = self.dir / "asset_root"
        self.config = DashboardConfig(
            daily_pack_path=self.dir / "d.json", answers_path=self.dir / "a.json", knowledge_path=self.dir / "k.json",
            skipped_path=self.dir / "s.json", sessions_path=self.dir / "ss.json", media_archive_path=self.archive,
            shorts_scripts_path=self.scripts, shorts_drafts_path=self.dir / "drafts", shorts_studio_out_path=self.dir / "out",
            shorts_studio_extra_sources=(), shorts_asset_dirs=(self.assets, self.dir / "images"),
            fact_check_manifest_path=self.dir / "none.json", ffmpeg=FFMPEG or "ffmpeg-does-not-exist")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler_class(self.config))
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close(), thread.join(5)))

    def req(self, path: str, data: bytes | None = None, headers: dict | None = None) -> tuple[int, str, bytes, dict]:
        request = urllib.request.Request(f"http://127.0.0.1:{self.server.server_address[1]}{path}", data=data, headers=headers or {})
        try:
            with urllib.request.urlopen(request, timeout=180) as resp:
                return resp.status, resp.geturl(), resp.read(), dict(resp.headers)
        except urllib.error.HTTPError as error:
            return error.code, path, error.read(), dict(error.headers)

    def post(self, path: str, form: dict) -> tuple[int, str, str]:
        status, url, body, _ = self.req(path, urllib.parse.urlencode(form).encode())
        return status, url, body.decode("utf-8", "replace")

    @unittest.skipUnless(HAS_FONTS, "Noto Sans KR 폰트가 없는 환경입니다.")
    def test_a_editor_load_shows_frames_gate_and_sections(self) -> None:
        _, url, html = self.post("/shorts-studio/open", {"content_id": "content-studio-test01"})
        self.assertTrue(url.endswith(f"/shorts-studio/{DID}"))
        for text in ("Frame 1 · Hook", "장면 화면", "품질 검사", "PASS", "엔딩 화면", "마지막 CTA 문구", "분야", "언어",
                     "이미지 바꾸기", "내 컴퓨터에서 새 이미지 올리기", "보여줄 부분", "고급 정보", "되돌리기 / 버전", "/frame/"):
            with self.subTest(text):
                self.assertIn(text, html)
        frame = __import__("re").search(r'/shorts-studio/[^"]+/frame/([0-9a-f]{16})/(scene01\.png)', html)
        status, _, body, headers = self.req(frame.group(0))
        self.assertEqual((status, headers["Content-Type"], body[:4]), (200, "image/png", b"\x89PNG"))
        for bad in (f"/shorts-studio/{DID}/frame/zzzz/scene01.png", f"/shorts-studio/{DID}/frame/{frame.group(1)}/..%2F..%2Fcurrent.json"):
            self.assertEqual(self.req(bad)[0], 404)

    @unittest.skipUnless(HAS_FONTS, "Noto Sans KR 폰트가 없는 환경입니다.")
    def test_d_upload_image_through_editor_form(self) -> None:
        self.post("/shorts-studio/open", {"content_id": "content-studio-test01"})
        buf = io.BytesIO()
        Image.new("RGB", (900, 600), (200, 60, 60)).save(buf, "PNG")
        body, ctype = _multipart({"expected_version": "1", "action": "save", "s0_layout": "image_top", "s0_image_path": "", "s0_headline": ""},
                                 {"s0_image_upload": ("업로드.png", buf.getvalue())})
        status, url, html, _ = self.req(f"/shorts-studio/{DID}/save", body, {"Content-Type": ctype})
        self.assertIn("notice=saved", url)
        image = self.store.load(DID)["document"]["scenes"][0]["image"]["path"]
        self.assertTrue((Path(image) if Path(image).is_absolute() else ROOT / image).is_file())
        self.assertIn("uploads", image)
        body, ctype = _multipart({"expected_version": "2"}, {"s0_image_upload": ("bad.png", b"nope")})
        status, _, html, _ = self.req(f"/shorts-studio/{DID}/save", body, {"Content-Type": ctype})
        self.assertEqual(status, 400)
        self.assertIn("UPLOAD_INVALID", html.decode())
        self.assertEqual(self.store.load(DID)["draft_version"], 2)

    @unittest.skipUnless(HAS_FONTS, "Noto Sans KR 폰트가 없는 환경입니다.")
    def test_list_filters_and_search(self) -> None:
        self.post("/shorts-studio/open", {"content_id": "content-studio-test01"})
        self.post(f"/shorts-studio/{DID}/save", {"expected_version": "1", "title": "검색될 제목"})
        _, _, html, _ = self.req("/shorts-studio?state=EDITED")
        self.assertIn("검색될 제목", html.decode())
        _, _, html, _ = self.req("/shorts-studio?state=APPROVED")
        self.assertNotIn("검색될 제목", html.decode())
        _, _, html, _ = self.req("/shorts-studio?q=%EC%97%86%EB%8A%94")  # "없는"
        self.assertIn("조건에 맞는 콘텐츠가 없습니다", html.decode())

    def test_superseded_row_is_locked_in_list(self) -> None:
        self.archive.write_text(json.dumps([_record("content-studio-test01", review_status="superseded") | {"superseded_by": "content-new"}]),
                                encoding="utf-8")
        self.protected[self.archive] = sha(self.archive)
        _, _, html, _ = self.req("/shorts-studio")
        html = html.decode()
        self.assertIn("Superseded(잠김)", html)
        self.assertNotIn('name="content_id" value="content-studio-test01"', html)
        status, _, body = self.post("/shorts-studio/open", {"content_id": "content-studio-test01"})
        self.assertEqual(status, 409)
        self.assertIn("SUPERSEDED", body)

    @unittest.skipUnless(FFMPEG and HAS_FONTS, "ffmpeg/폰트가 없는 환경입니다.")
    def test_video_supports_range_requests(self) -> None:
        self.post("/shorts-studio/open", {"content_id": "content-studio-test01"})
        _, url, _ = self.post(f"/shorts-studio/{DID}/save", {"expected_version": "1", "action": "preview"})
        self.assertIn("notice=preview", url)
        path = f"/shorts-studio/{DID}/file/{DID}-v0001-preview.mp4"
        status, _, full, headers = self.req(path)
        self.assertEqual((status, headers["Accept-Ranges"]), (200, "bytes"))
        status, _, part, headers = self.req(path, headers={"Range": "bytes=100-199"})
        self.assertEqual((status, part, headers["Content-Range"]), (206, full[100:200], f"bytes 100-199/{len(full)}"))
        status, _, tail, _ = self.req(path, headers={"Range": "bytes=-10"})
        self.assertEqual((status, tail), (206, full[-10:]))
        self.assertEqual(self.req(path, headers={"Range": f"bytes={len(full) + 5}-"})[0], 416)


@unittest.skipUnless(HAS_FONTS, "Noto Sans KR 폰트가 없는 환경입니다.")
class RealCandidateEditorTests(unittest.TestCase):
    """실제 후보 5개(있을 때): 원본 -> Draft -> 검사. Draft는 임시 폴더, 원본 해시는 전후 동일."""

    def test_five_candidates_open_and_check(self) -> None:
        import tempfile

        sources = [(ROOT / "data/tak_media_archive.json", ROOT / "data/shorts_scripts"),
                   (ROOT / "artifacts/6-48-recovery-staging/data/tak_media_archive.json", ROOT / "artifacts/6-48-recovery-staging/data/shorts_scripts")]
        entries = studio.list_sources(sources)
        if not entries:
            self.skipTest("후보 데이터가 이 환경에 없습니다.")
        files = [p for a, s in sources if a.exists() for p in [a, *s.glob("*.json")]]
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
        with tempfile.TemporaryDirectory() as tmp:
            store = studio.DraftStore(tmp, ROOT)
            for e in entries:
                with self.subTest(e["content_id"]):
                    d = store.open_draft(e)
                    report = check(d["document"], ROOT)
                    self.assertIn(report["verdict"], ("PASS", "WARNING"), report["items"])
                    self.assertEqual(studio.guard(d, e), [])
        self.assertEqual(before, {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in before})


if __name__ == "__main__":
    unittest.main()
