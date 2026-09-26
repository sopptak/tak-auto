"""6-53 Shorts V3 통합 테스트 - 실제 ffmpeg 렌더(짧은 문서) + 품질 게이트 + 캐시 + 배치 격리.

ffmpeg(PATH 또는 TAK_TEST_FFMPEG)와 Noto Sans KR이 없으면 건너뛴다. 전부 tempfile, ``data/`` 미사용.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from content_engine import shorts_v3_pipeline
from content_engine.shorts_v3_pipeline import BatchItem, render_batch, render_item
from tests.fixtures.shorts_v3_images import make_images

HAS_FONTS = Path("C:/Windows/Fonts/NotoSansKR-VF.ttf").exists()
FFMPEG = os.environ.get("TAK_TEST_FFMPEG") or shutil.which("ffmpeg")


def short_doc(doc_id: str, **extra) -> dict:
    return {"schema": "shorts_v3_document/1", "id": doc_id, "title": "통합 테스트", "lineage": {"content_id": doc_id},
            "brand": {"end_card": False},
            "scenes": [{"layout": "image_top", "image": "images/landscape.png", "body": "하나.", "duration": 1.5, "source": "BBC"},
                       {"layout": "split", "image": {"path": "images/portrait.png", "fit": "contain"}, "body": "둘.",
                        "duration": 1.5, "transition": "slide"}], **extra}


@unittest.skipUnless(HAS_FONTS and FFMPEG, "ffmpeg(PATH 또는 TAK_TEST_FFMPEG)/폰트가 없는 환경입니다.")
class V3IntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        make_images(self.dir)
        self.out = self.dir / "out"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_audio_on_passes_gate_with_lineage(self) -> None:
        r = render_item(BatchItem("audio_on", short_doc("audio_on"), self.dir), self.out, ffmpeg=FFMPEG)
        self.assertEqual(r["status"], "success", r)
        report = json.loads(Path(r["report"]).read_text(encoding="utf-8"))
        self.assertEqual(report["probe"]["audio_codec"], "aac")
        self.assertEqual((report["probe"]["width"], report["probe"]["height"]), (1080, 1920))
        self.assertEqual(report["quality"]["status"], "PASS")
        for key in ("content_id", "document_sha256", "template_sha256", "render_key", "mp4_sha256"):
            self.assertTrue(report["lineage"][key])

    def test_audio_off_renders_silent_video(self) -> None:
        r = render_item(BatchItem("audio_off", short_doc("audio_off", audio={"enabled": False}), self.dir), self.out, ffmpeg=FFMPEG)
        self.assertEqual(r["status"], "success", r)
        report = json.loads(Path(r["report"]).read_text(encoding="utf-8"))
        self.assertIsNone(report["probe"]["audio_codec"])

    def test_same_render_key_is_cached_and_force_rerenders(self) -> None:
        item = BatchItem("cache", short_doc("cache"), self.dir)
        first = render_item(item, self.out, ffmpeg=FFMPEG)
        second = render_item(item, self.out, ffmpeg=FFMPEG)
        self.assertEqual((first["status"], second["status"]), ("success", "cached"))
        self.assertEqual(first["render_key"], second["render_key"])
        with mock.patch.object(shorts_v3_pipeline, "render_short_v3", wraps=shorts_v3_pipeline.render_short_v3) as spy:
            forced = render_item(item, self.out, ffmpeg=FFMPEG, force=True)
            self.assertEqual((forced["status"], spy.call_count), ("success", 1))
        changed = render_item(BatchItem("cache", short_doc("cache", title="제목 변경"), self.dir), self.out, ffmpeg=FFMPEG)
        self.assertEqual(changed["status"], "success")
        self.assertNotEqual(changed["render_key"], first["render_key"])

    def test_same_input_gives_byte_identical_mp4(self) -> None:
        item = BatchItem("det", short_doc("det"), self.dir)
        a = render_item(item, self.dir / "o1", ffmpeg=FFMPEG)
        b = render_item(item, self.dir / "o2", ffmpeg=FFMPEG)
        self.assertEqual(Path(a["output"]).read_bytes(), Path(b["output"]).read_bytes())

    def test_batch_keeps_going_after_failures(self) -> None:
        real = shorts_v3_pipeline.render_short_v3

        def flaky(doc, *args, **kwargs):
            if doc.id == "boom":
                raise RuntimeError("encoder exploded")
            return real(doc, *args, **kwargs)

        items = [BatchItem("ok", short_doc("ok"), self.dir), BatchItem("boom", short_doc("boom"), self.dir),
                 BatchItem("overflow", short_doc("overflow", title="아주 긴 제목 " * 40), self.dir),
                 BatchItem("missing_image", short_doc("missing_image", scenes=[{"layout": "image_top", "image": "images/none.png", "body": "a"}]), self.dir),
                 BatchItem("ok2", short_doc("ok2"), self.dir)]
        with mock.patch.object(shorts_v3_pipeline, "render_short_v3", side_effect=flaky):
            summary = render_batch(items, self.out, ffmpeg=FFMPEG)
        got = {r["name"]: (r["status"], r["reasons"]) for r in summary["results"]}
        self.assertEqual(got, {"ok": ("success", []), "boom": ("failed", ["RENDER_EXCEPTION"]),
                               "overflow": ("blocked", ["TITLE_OVERFLOW"]), "missing_image": ("blocked", ["IMAGE_MISSING"]),
                               "ok2": ("success", [])})
        self.assertTrue((self.out / "ok.mp4").exists() and (self.out / "ok2.mp4").exists())
        self.assertFalse((self.out / "overflow.mp4").exists())
        saved = json.loads((self.out / "batch_summary.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["counts"], {"success": 2, "failed": 1, "blocked": 2})


if __name__ == "__main__":
    unittest.main()
