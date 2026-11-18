import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

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
            "facebook": {"title": "Facebook 제목", "body": "Facebook 전용 게시문"},
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

    def _valid_package(self):
        return {
            "blog": {
                "title": "블로그 제목", "meta_description": "검색 설명",
                "focus_keyword": "핵심 키워드", "body": "본문 " * 200,
            },
            "shorts": {
                "title": "쇼츠 제목", "hook": "첫 3초 후킹", "closing_cta": "댓글 남겨주세요",
                "duration_seconds": 60, "youtube_description": "설명",
                "instagram_caption": "릴스 문안", "tiktok_caption": "틱톡 문안",
                "hashtags": ["탁자동"],
                "scenes": [
                    {"time": f"00-0{i}초", "visual": "화면 구성", "caption": "자막", "narration": "내레이션"}
                    for i in range(5)
                ],
            },
            "threads": [
                {"title": "Threads 제목", "body": "Threads 본문"},
                {"title": "Threads 제목 2", "body": "Threads 본문 2"},
            ],
        }

    def test_generated_preview_carries_stable_knowledge_identity(self):
        package = self._valid_package()
        provider = Mock()
        provider.search.return_value = SimpleNamespace(
            answer=json.dumps(package, ensure_ascii=False),
            citations=["https://example.test/citation"],
            model="test-model",
        )
        item = {
            "keyword": "테스트 키워드",
            "category": "경제",
            "summary": "최근 주목할 만한 변화에 대한 요약입니다.",
            "why_now": "최근 발표된 제도 변화가 독자에게 영향을 주기 때문입니다.",
            "audience_question": "실제 생활에서 어떤 점을 확인해야 할까요?",
            "content_angle": "현장 적용 시 확인해야 할 핵심 사항을 정리합니다.",
            "key_points": [
                "첫 번째 독립 근거로 공식 발표 내용을 확인합니다.",
                "두 번째 독립 근거로 실제 적용 사례를 검토합니다.",
                "세 번째 독립 근거로 주의할 점을 비교합니다.",
            ],
            "source_urls": ["https://example.test/source"],
        }
        preview = run_trend_content_mvp._make_preview(
            item, {"citations": []}, provider=provider,
        )
        self.assertTrue(preview["knowledge_id"].startswith("trend-preview-"))
        self.assertEqual(preview["source_urls"][0], "https://example.test/source")
        identity_payload = json.dumps(
            {"keyword": "테스트 키워드", "source_urls": ["https://example.test/source"]},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        )
        expected_id = "trend-preview-" + __import__("hashlib").sha256(
            identity_payload.encode("utf-8")
        ).hexdigest()[:16]
        self.assertEqual(preview["knowledge_id"], expected_id)

        # Same topic + same source set is stable; a different source event gets a new lineage.
        repeated = run_trend_content_mvp._make_preview(
            item, {"citations": []}, provider=provider,
        )
        self.assertEqual(repeated["knowledge_id"], preview["knowledge_id"])
        different_event = dict(item, source_urls=["https://example.test/another-event"])
        other_preview = run_trend_content_mvp._make_preview(
            different_event, {"citations": []}, provider=provider,
        )
        self.assertNotEqual(other_preview["knowledge_id"], preview["knowledge_id"])

    def test_content_package_preserves_facebook_specific_copy(self):
        package = self._valid_package()
        package["facebook"] = {"title": "Facebook 전용 제목", "body": "Facebook 전용 본문"}
        parsed = run_trend_content_mvp._parse_content_package(json.dumps(package, ensure_ascii=False))
        self.assertEqual(parsed["facebook"]["title"], "Facebook 전용 제목")
        self.assertEqual(parsed["facebook"]["body"], "Facebook 전용 본문")

    def test_content_package_falls_back_for_legacy_missing_facebook_copy(self):
        package = self._valid_package()
        parsed = run_trend_content_mvp._parse_content_package(json.dumps(package, ensure_ascii=False))
        self.assertEqual(parsed["facebook"]["title"], "Threads 제목")
        self.assertEqual(parsed["facebook"]["body"], "Threads 본문")

    def test_threads_is_ready_without_a_video_asset(self):
        self.assertEqual(
            run_trend_content_mvp._queue_payload_for_platform(self.preview, "threads"),
            [{"title": "제목", "body": "승인된 Threads 원고"}],
        )

    def test_facebook_queue_uses_facebook_specific_copy(self):
        payload = run_trend_content_mvp._queue_payload_for_platform(
            self.preview, "facebook",
        )
        self.assertEqual(payload, [{
            "title": "Facebook 제목",
            "body": "Facebook 제목\n\nFacebook 전용 게시문",
        }])

    def test_facebook_queue_falls_back_to_threads_when_legacy_preview_has_no_facebook_copy(self):
        legacy_preview = dict(self.preview)
        legacy_preview.pop("facebook")
        payload = run_trend_content_mvp._queue_payload_for_platform(legacy_preview, "facebook")
        self.assertEqual(payload[0]["body"], "제목\n\n승인된 Threads 원고")

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
        self.assertEqual(payload[0]["caption"], "Instagram 캡션\n\n#탁자동 #shorts")

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
        self.assertEqual(payload[0]["title"], "TikTok 캡션\n\n#탁자동 #shorts")
        self.assertEqual(payload[0]["privacy_level"], "SELF_ONLY")
        self.assertTrue(payload[0]["is_aigc"])

    def test_unknown_platform_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "지원하지 않는"):
            run_trend_content_mvp._queue_payload_for_platform(self.preview, "unknown")


if __name__ == "__main__":
    unittest.main()
