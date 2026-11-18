import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from content_engine.media_assets import MediaAssetStore
from scripts import run_trend_content_mvp


class TrendContentQueueRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.data_dir = Path(self.temp_dir.name)
        self.preview = {
            "keyword": "테스트 키워드",
            "threads": [{"title": "제목", "body": "승인된 Threads 원고"}],
            "blog": {"title": "블로그 제목", "body": "블로그 본문"},
            "shorts": [{
                "title": "쇼츠 제목", "body": "영상 대본",
                "youtube_description": "YouTube 설명",
                "instagram_caption": "Instagram 캡션",
                "tiktok_caption": "TikTok 캡션",
                "hashtags": ["탁자동", "#shorts"],
            }],
        }
        self.environment = patch.dict(os.environ, {
            "TAK_AUTO_MEDIA_SIGNING_KEY": "test-signing-key-that-is-at-least-32-chars",
            "TAK_AUTO_PUBLIC_URL": "https://tak-auto.example.test",
        }, clear=False)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.data_dir_patch = patch.object(run_trend_content_mvp, "DATA_DIR", self.data_dir)
        self.data_dir_patch.start()
        self.addCleanup(self.data_dir_patch.stop)
        payload = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64
        self.asset = MediaAssetStore(
            self.data_dir, os.environ["TAK_AUTO_MEDIA_SIGNING_KEY"],
            os.environ["TAK_AUTO_PUBLIC_URL"],
        ).save_stream(io.BytesIO(payload), len(payload), "approved.mp4")

    def test_threads_is_ready_without_a_video_asset(self):
        self.assertEqual(
            run_trend_content_mvp._queue_payload_for_platform(self.preview, "threads"),
            [{"title": "제목", "body": "승인된 Threads 원고"}],
        )

    def test_youtube_queue_uses_uploaded_mp4_path_and_metadata(self):
        payload = run_trend_content_mvp._queue_payload_for_platform(
            self.preview, "youtube_shorts", self.asset.asset_id,
        )
        self.assertEqual(payload[0]["video_path"], str(self.asset.path))
        self.assertEqual(payload[0]["title"], "쇼츠 제목")
        self.assertEqual(payload[0]["description"], "YouTube 설명")
        self.assertEqual(payload[0]["tags"], ["탁자동", "shorts"])

    def test_instagram_queue_stores_asset_reference_for_runtime_signed_url(self):
        payload = run_trend_content_mvp._queue_payload_for_platform(
            self.preview, "instagram_reels", self.asset.asset_id,
        )
        self.assertEqual(payload[0]["media_asset_id"], self.asset.asset_id)
        self.assertEqual(payload[0]["caption"], "Instagram 캡션\\n\\n#탁자동 #shorts")

    def test_video_platforms_require_an_uploaded_media_asset(self):
        for platform in ("youtube_shorts", "instagram_reels", "tiktok"):
            with self.subTest(platform=platform), self.assertRaisesRegex(ValueError, "미디어 자산"):
                run_trend_content_mvp._queue_payload_for_platform(self.preview, platform, "")

    def test_blog_remains_manual_until_a_blog_publisher_exists(self):
        with self.assertRaisesRegex(ValueError, "수동 게시"):
            run_trend_content_mvp._queue_payload_for_platform(self.preview, "blog")

    def test_tiktok_queue_requires_explicit_privacy_and_uses_registered_video(self):
        with self.assertRaisesRegex(ValueError, "공개 범위"):
            run_trend_content_mvp._queue_payload_for_platform(
                self.preview, "tiktok", self.asset.asset_id,
            )
        payload = run_trend_content_mvp._queue_payload_for_platform(
            self.preview, "tiktok", self.asset.asset_id, "SELF_ONLY", True,
        )
        self.assertEqual(payload[0]["media_asset_id"], self.asset.asset_id)
        self.assertEqual(payload[0]["title"], "TikTok 캡션\\n\\n#탁자동 #shorts")
        self.assertEqual(payload[0]["privacy_level"], "SELF_ONLY")
        self.assertTrue(payload[0]["is_aigc"])

    def test_unknown_platform_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "지원하지 않는"):
            run_trend_content_mvp._queue_payload_for_platform(self.preview, "unknown")


if __name__ == "__main__":
    unittest.main()
