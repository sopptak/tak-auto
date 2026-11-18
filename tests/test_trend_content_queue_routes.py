import unittest

from scripts.run_trend_content_mvp import _queue_payload_for_platform


class TrendContentQueueRouteTests(unittest.TestCase):
    def setUp(self):
        self.preview = {
            "threads": [{"title": "제목", "body": "승인된 Threads 원고"}],
            "blog": {"title": "블로그 제목", "body": "블로그 본문"},
            "shorts": [{"title": "쇼츠 제목", "body": "영상 대본"}],
        }

    def test_threads_is_the_only_platform_currently_ready_for_auto_queue(self):
        self.assertEqual(
            _queue_payload_for_platform(self.preview, "threads"),
            [{"title": "제목", "body": "승인된 Threads 원고"}],
        )

    def test_blog_remains_manual_until_a_blog_publisher_exists(self):
        with self.assertRaisesRegex(ValueError, "수동 게시"):
            _queue_payload_for_platform(self.preview, "blog")

    def test_youtube_requires_a_real_mp4_media_handoff(self):
        with self.assertRaisesRegex(ValueError, "완성 MP4"):
            _queue_payload_for_platform(self.preview, "youtube_shorts")

    def test_instagram_requires_a_public_https_video_url(self):
        with self.assertRaisesRegex(ValueError, "공개 HTTPS"):
            _queue_payload_for_platform(self.preview, "instagram_reels")

    def test_tiktok_is_blocked_until_its_publisher_is_implemented(self):
        with self.assertRaisesRegex(ValueError, "준비 중"):
            _queue_payload_for_platform(self.preview, "tiktok")

    def test_unknown_platform_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "지원하지 않는"):
            _queue_payload_for_platform(self.preview, "unknown")


if __name__ == "__main__":
    unittest.main()
