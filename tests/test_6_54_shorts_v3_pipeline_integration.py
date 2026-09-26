"""6-54 Shorts V3 파이프라인 통합 테스트 - 실제 ffmpeg 렌더.

manifest 계약, idempotency(SKIP / 손상·삭제 시 재렌더), 오디오(존재·길이·fade·volume), 전환 4종 실제 렌더,
fixture 5개 배치(4 성공 + 1 ASSET_MISSING), 배치 보고서. 전부 tempfile, ``data/`` 미사용.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from content_engine.shorts_v3_pipeline import ContentItem, item_from_document, render_batch, render_item
from tests.fixtures.shorts_v3_images import make_images

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "shorts_v3_pipeline"
HAS_FONTS = Path("C:/Windows/Fonts/NotoSansKR-VF.ttf").exists()
FFMPEG = os.environ.get("TAK_TEST_FFMPEG") or shutil.which("ffmpeg")


def short_doc(doc_id: str, **extra) -> dict:
    return {"schema": "shorts_v3_document/1", "id": doc_id, "title": "파이프라인 통합", "brand": {"end_card": False},
            "lineage": {"content_id": doc_id, "generation_id": "gen-test", "source_script_sha256": "0" * 64},
            "scenes": [{"layout": "image_top", "image": "images/square.png", "body": "하나.", "duration": 1.5, "source": "BBC"},
                       {"layout": "text_focus", "body": "둘.", "duration": 1.5}], **extra}


@unittest.skipUnless(HAS_FONTS and FFMPEG, "ffmpeg(PATH 또는 TAK_TEST_FFMPEG)/폰트가 없는 환경입니다.")
class PipelineIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        make_images(self.dir)
        self.out = self.dir / "out"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def render(self, name: str, **extra) -> dict:
        return render_item(ContentItem(name, short_doc(name, **extra), self.dir), self.out, ffmpeg=FFMPEG)

    def test_manifest_contract(self) -> None:
        r = self.render("manifest")
        self.assertEqual(r["status"], "success", r)
        m = json.loads(Path(r["manifest_path"]).read_text(encoding="utf-8"))
        self.assertEqual(m["schema"], "shorts_v3_manifest/1")
        for key in ("content_id", "generation_id", "source_script_sha256", "document_sha256", "template_sha256",
                    "asset_sha256", "mp4_sha256", "renderer_version", "render_key"):
            self.assertTrue(m["lineage"].get(key), key)
        self.assertEqual(m["assets"]["0"]["orientation"], "square")
        self.assertEqual((m["output"]["width"], m["output"]["height"], m["output"]["video_codec"], m["output"]["audio_codec"]),
                         (1080, 1920, "h264", "aac"))
        self.assertEqual(m["output"]["frames"], round(m["output"]["duration"] * 30))
        self.assertEqual(m["publish_contract"]["artifact_sha256"], m["output"]["sha256"])
        self.assertEqual(m["visual_review"]["image_types"], ["square", None])
        self.assertEqual(m["quality"]["status"], "PASS")

    def test_idempotency_skip_and_repair(self) -> None:
        first = self.render("idem")
        again = self.render("idem")
        self.assertEqual((again["status"], again["reasons"]), ("skipped", ["ALREADY_RENDERED"]))
        video = Path(first["output_path"])
        video.write_bytes(video.read_bytes()[:1000])  # 손상
        repaired = self.render("idem")
        self.assertEqual((repaired["status"], repaired["rerender_reason"]), ("success", "ARTIFACT_CHANGED"))
        self.assertEqual(repaired["sha256"], first["sha256"])  # 같은 입력 -> 같은 MP4
        video.unlink()
        self.assertEqual(self.render("idem")["rerender_reason"], "ARTIFACT_MISSING")

    def test_audio_fade_and_volume(self) -> None:
        loud = json.loads(Path(self.render("loud")["manifest_path"]).read_text(encoding="utf-8"))
        quiet = json.loads(Path(self.render("quiet", audio={"volume": 0.5})["manifest_path"]).read_text(encoding="utf-8"))
        for m in (loud, quiet):
            self.assertAlmostEqual(m["output"]["duration"], 3.0, delta=0.05)
            self.assertLess(m["audio_levels"]["tail"], m["audio_levels"]["middle"] * 0.5)  # fade out
        ratio = quiet["audio_levels"]["middle"] / loud["audio_levels"]["middle"]
        self.assertTrue(0.35 < ratio < 0.65, ratio)

    def test_all_transitions_render_without_blank_or_missing_frames(self) -> None:
        shutil.copy(FIXTURES / "transitions.json", self.dir / "transitions.json")
        r = render_item(item_from_document(self.dir / "transitions.json"), self.out, ffmpeg=FFMPEG)
        self.assertEqual(r["status"], "success", r)
        m = json.loads(Path(r["manifest_path"]).read_text(encoding="utf-8"))
        self.assertEqual(m["visual_review"]["transitions"], ["punch", "cut", "dissolve", "slide", "punch"])
        self.assertTrue(m["media_checks"]["no_blank_scene"])
        self.assertEqual(m["output"]["frames"], round(m["layout"]["total"] * 30))

    def test_fixture_batch_four_success_one_asset_missing(self) -> None:
        names = ["ratio_portrait", "ratio_landscape", "ratio_square", "long_text", "broken_asset"]
        for n in names:
            shutil.copy(FIXTURES / f"{n}.json", self.dir / f"{n}.json")
        summary = render_batch([self.dir / f"{n}.json" for n in names], self.out, ffmpeg=FFMPEG)
        got = {r["name"].removeprefix("fixture-654-"): (r["status"], r["error_code"]) for r in summary["results"]}
        self.assertEqual(got, {"ratio_portrait": ("success", None), "ratio_landscape": ("success", None),
                               "ratio_square": ("success", None), "long_text": ("success", None),
                               "broken_asset": ("blocked", "ASSET_MISSING")})
        self.assertEqual((summary["total"], summary["success"], summary["failed"]), (5, 4, 1))
        self.assertFalse((self.out / "fixture-654-broken_asset.mp4").exists())
        self.assertIn("ASSET_MISSING", (self.out / "batch_report.md").read_text(encoding="utf-8"))
        self.assertGreater(summary["performance"]["avg_render_seconds"], 0)


if __name__ == "__main__":
    unittest.main()
