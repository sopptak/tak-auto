import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from content_engine.publishing_queue import PermanentPublishError, PublishUncertainError
from content_engine.threads_publisher import ThreadsAPIError
from content_engine.youtube_publisher import YouTubeAPIError
from content_engine.instagram_publisher import InstagramAPIError, InstagramClient
from content_engine.trend_publishers import publish


class TrendPublisherTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.data_dir = Path(self.temp_dir.name)
        self.client = Mock()
        self.client.publish_text.return_value = SimpleNamespace(id="threads-post-1")

    def test_threads_adapter_posts_only_text_and_records_history(self):
        with patch.dict("os.environ", {"TAK_AUTO_DATA_DIR": str(self.data_dir)}, clear=True), \
                patch("content_engine.trend_publishers.ThreadsClient.from_environment", return_value=self.client):
            remote_id = publish("threads", {
                "title": "제목", "body": "승인된 Threads 문안", "_content_id": "trend-thread-1",
            }, "queue-key")

        self.assertEqual(remote_id, "threads-post-1")
        self.client.publish_text.assert_called_once_with("승인된 Threads 문안")
        history = (self.data_dir / "threads_publish_log.json").read_text(encoding="utf-8")
        self.assertIn("trend-thread-1", history)
        self.assertIn("threads-post-1", history)

    def test_existing_threads_history_skips_remote_publish(self):
        with patch.dict("os.environ", {"TAK_AUTO_DATA_DIR": str(self.data_dir)}, clear=True), \
                patch("content_engine.trend_publishers.ThreadsClient.from_environment", return_value=self.client):
            publish("threads", {"body": "첫 게시", "_content_id": "same-content"}, "first-key")
            remote_id = publish("threads", {"body": "재시도", "_content_id": "same-content"}, "retry-key")

        self.assertEqual(remote_id, "threads-post-1")
        self.client.publish_text.assert_called_once_with("첫 게시")

    def test_youtube_shorts_uploads_mp4_as_private_and_returns_video_id(self):
        video = self.data_dir / "approved-short.mp4"
        video.write_bytes(b"test-video")
        youtube = Mock()
        youtube.upload_short.return_value = SimpleNamespace(video_id="youtube-video-1")
        with patch("content_engine.trend_publishers.YouTubeClient.from_environment", return_value=youtube):
            remote_id = publish("youtube_shorts", {
                "video_path": str(video),
                "title": "승인된 쇼츠 제목",
                "description": "설명",
                "tags": ["탁자동", "#shorts"],
            }, "youtube-key")
        self.assertEqual(remote_id, "youtube-video-1")
        youtube.upload_short.assert_called_once_with(
            video_path=video,
            title="승인된 쇼츠 제목",
            description="설명",
            tags=["탁자동", "#shorts"],
            privacy_status="private",
        )

    def test_youtube_shorts_requires_existing_mp4_before_oauth(self):
        with patch("content_engine.trend_publishers.YouTubeClient.from_environment") as factory:
            with self.assertRaisesRegex(PermanentPublishError, "존재하는 MP4"):
                publish("youtube_shorts", {
                    "video_path": str(self.data_dir / "missing.mp4"),
                    "title": "제목",
                }, "youtube-key")
        factory.assert_not_called()

    def test_youtube_shorts_ambiguous_upload_requires_manual_review(self):
        video = self.data_dir / "approved-short.mp4"
        video.write_bytes(b"test-video")
        youtube = Mock()
        youtube.upload_short.side_effect = YouTubeAPIError("connection reset")
        with patch("content_engine.trend_publishers.YouTubeClient.from_environment", return_value=youtube):
            with self.assertRaises(PublishUncertainError):
                publish("youtube_shorts", {
                    "video_path": str(video),
                    "title": "승인된 쇼츠 제목",
                }, "youtube-key")
        youtube.upload_short.assert_called_once()

    def test_instagram_client_creates_container_waits_then_publishes(self):
        calls = []
        responses = iter([
            {"id": "container-1"},
            {"status_code": "IN_PROGRESS"},
            {"status_code": "FINISHED"},
            {"id": "instagram-media-1"},
        ])

        def transport(method, url, *, access_token, fields=None, timeout_seconds=30.0):
            calls.append((method, url, fields))
            return next(responses)

        client = InstagramClient(
            access_token="test-token", instagram_user_id="123456789",
            transport=transport, sleep=lambda seconds: None,
        )
        result = client.publish_reel(
            video_url="https://cdn.example.test/approved.mp4",
            caption="승인된 릴스 문안", share_to_feed=False,
        )
        self.assertEqual(result.media_id, "instagram-media-1")
        self.assertEqual([call[0] for call in calls], ["POST", "GET", "GET", "POST"])
        self.assertEqual(calls[0][2]["media_type"], "REELS")
        self.assertEqual(calls[0][2]["video_url"], "https://cdn.example.test/approved.mp4")
        self.assertEqual(calls[0][2]["share_to_feed"], "false")
        self.assertEqual(calls[-1][2]["creation_id"], "container-1")

    def test_instagram_client_never_publishes_before_container_is_finished(self):
        calls = []
        def transport(method, url, *, access_token, fields=None, timeout_seconds=30.0):
            calls.append(method)
            return {"id": "container-1"} if method == "POST" and url.endswith("/media") else {"status_code": "ERROR"}

        client = InstagramClient(
            access_token="test-token", instagram_user_id="123456789",
            transport=transport, sleep=lambda seconds: None,
        )
        with self.assertRaises(InstagramAPIError):
            client.publish_reel(video_url="https://cdn.example.test/approved.mp4", caption="문안")
        self.assertEqual(calls, ["POST", "GET"])

    def test_instagram_adapter_requires_public_video_url_and_publish_scope(self):
        with patch.dict("os.environ", {
            "TAK_AUTO_DATA_DIR": str(self.data_dir),
            "TAK_AUTO_OAUTH_ENCRYPTION_KEY": "test-fernet-key",
        }, clear=True), patch("content_engine.trend_publishers.OAuthTokenVault") as vault_type:
            vault_type.return_value.get.return_value = {
                "access_token": "ig-token", "account_id": "123456789",
                "granted_scopes": "instagram_business_basic",
            }
            with self.assertRaisesRegex(PermanentPublishError, "게시 권한이 없습니다"):
                publish("instagram_reels", {
                    "video_url": "https://cdn.example.test/reel.mp4",
                    "caption": "승인된 릴스",
                }, "instagram-key")
        vault_type.return_value.get.assert_called_once_with("instagram_reels")

    def test_instagram_adapter_uses_encrypted_account_and_marks_api_failure_uncertain(self):
        with patch.dict("os.environ", {
            "TAK_AUTO_DATA_DIR": str(self.data_dir),
            "TAK_AUTO_OAUTH_ENCRYPTION_KEY": "test-fernet-key",
            "META_GRAPH_API_VERSION": "v27.0",
        }, clear=True), \
                patch("content_engine.trend_publishers.OAuthTokenVault") as vault_type, \
                patch("content_engine.trend_publishers.InstagramClient") as client_type:
            vault_type.return_value.get.return_value = {
                "access_token": "ig-private-token", "account_id": "123456789",
                "granted_scopes": "instagram_business_basic,instagram_business_content_publishing",
                "expires_at": "2099-01-01T00:00:00+00:00",
            }
            client_type.return_value.publish_reel.side_effect = InstagramAPIError("network lost")
            with self.assertRaises(PublishUncertainError):
                publish("instagram_reels", {
                    "video_url": "https://cdn.example.test/reel.mp4",
                    "caption": "승인된 릴스", "share_to_feed": True,
                }, "instagram-key")
        client_type.assert_called_once_with(
            access_token="ig-private-token", instagram_user_id="123456789", api_version="v27.0",
        )
        client_type.return_value.publish_reel.assert_called_once_with(
            video_url="https://cdn.example.test/reel.mp4",
            caption="승인된 릴스", share_to_feed=True,
        )

    def test_instagram_adapter_generates_short_lived_signed_url_from_media_asset(self):
        with patch.dict("os.environ", {
            "TAK_AUTO_DATA_DIR": str(self.data_dir),
            "TAK_AUTO_OAUTH_ENCRYPTION_KEY": "test-fernet-key",
            "TAK_AUTO_MEDIA_SIGNING_KEY": "test-signing-key-that-is-at-least-32-chars",
            "TAK_AUTO_PUBLIC_URL": "https://tak-auto.example.test",
        }, clear=True), \
                patch("content_engine.trend_publishers.OAuthTokenVault") as vault_type, \
                patch("content_engine.trend_publishers.MediaAssetStore") as store_type, \
                patch("content_engine.trend_publishers.InstagramClient") as client_type:
            vault_type.return_value.get.return_value = {
                "access_token": "ig-private-token", "account_id": "123456789",
                "granted_scopes": "instagram_business_basic,instagram_business_content_publishing",
                "expires_at": "2099-01-01T00:00:00+00:00",
            }
            store_type.return_value.signed_url.return_value = "https://tak-auto.example.test/media/assets/" + "a" * 32 + "?signed"
            client_type.return_value.publish_reel.return_value = SimpleNamespace(media_id="ig-media-asset-1")
            remote_id = publish("instagram_reels", {
                "media_asset_id": "a" * 32, "caption": "등록 영상 릴스",
            }, "instagram-key")
        self.assertEqual(remote_id, "ig-media-asset-1")
        store_type.return_value.signed_url.assert_called_once_with("a" * 32, ttl_seconds=48 * 60 * 60)
        client_type.return_value.publish_reel.assert_called_once_with(
            video_url="https://tak-auto.example.test/media/assets/" + "a" * 32 + "?signed",
            caption="등록 영상 릴스", share_to_feed=True,
        )

    def test_youtube_adapter_resolves_uploaded_media_asset_when_path_is_omitted(self):
        video_path = self.data_dir / "approved-short.mp4"
        video_path.write_bytes(b"test-video")
        youtube = Mock()
        youtube.upload_short.return_value = SimpleNamespace(video_id="youtube-asset-video")
        with patch.dict("os.environ", {
            "TAK_AUTO_DATA_DIR": str(self.data_dir),
            "TAK_AUTO_MEDIA_SIGNING_KEY": "test-signing-key-that-is-at-least-32-chars",
            "TAK_AUTO_PUBLIC_URL": "https://tak-auto.example.test",
        }, clear=True), \
                patch("content_engine.trend_publishers.MediaAssetStore") as store_type, \
                patch("content_engine.trend_publishers.YouTubeClient.from_environment", return_value=youtube):
            store_type.return_value.get_asset.return_value = SimpleNamespace(path=video_path)
            remote_id = publish("youtube_shorts", {
                "media_asset_id": "b" * 32, "title": "등록 MP4",
            }, "youtube-key")
        self.assertEqual(remote_id, "youtube-asset-video")
        store_type.return_value.get_asset.assert_called_once_with("b" * 32)
        youtube.upload_short.assert_called_once_with(
            video_path=video_path, title="등록 MP4", description="", tags=[], privacy_status="private",
        )

    def test_unsupported_platform_fails_closed_without_calling_threads(self):
        with patch("content_engine.trend_publishers.ThreadsClient.from_environment") as factory:
            with self.assertRaisesRegex(PermanentPublishError, "아직 준비되지 않았습니다"):
                publish("tiktok", {"body": "본문"}, "queue-key")
        factory.assert_not_called()

    def test_invalid_threads_text_fails_before_api_call(self):
        with patch("content_engine.trend_publishers.ThreadsClient.from_environment") as factory:
            with self.assertRaisesRegex(PermanentPublishError, "500자 이하"):
                publish("threads", {"body": "x" * 501}, "queue-key")
        factory.assert_not_called()

    def test_ambiguous_threads_api_error_requires_manual_review(self):
        self.client.publish_text.side_effect = ThreadsAPIError("network response lost")
        with patch.dict("os.environ", {"TAK_AUTO_DATA_DIR": str(self.data_dir)}, clear=True), \
                patch("content_engine.trend_publishers.ThreadsClient.from_environment", return_value=self.client):
            with self.assertRaises(PublishUncertainError):
                publish("threads", {"body": "승인된 문안", "_content_id": "uncertain-content"}, "queue-key")
        self.client.publish_text.assert_called_once_with("승인된 문안")
        self.assertFalse((self.data_dir / "threads_publish_log.json").exists())

    def test_uses_encrypted_oauth_token_only_when_publish_scope_is_granted(self):
        with patch.dict("os.environ", {
            "TAK_AUTO_DATA_DIR": str(self.data_dir),
            "TAK_AUTO_OAUTH_ENCRYPTION_KEY": "test-fernet-key",
        }, clear=True), \
                patch("content_engine.trend_publishers.OAuthTokenVault") as vault_type, \
                patch("content_engine.trend_publishers.ThreadsClient") as client_type:
            vault_type.return_value.get.return_value = {
                "access_token": "encrypted-vault-token",
                "granted_scopes": "threads_basic,threads_content_publish",
                "expires_at": "2099-01-01T00:00:00+00:00",
            }
            client_type.return_value.publish_text.return_value = SimpleNamespace(id="oauth-post-1")
            remote_id = publish("threads", {"body": "승인 대기열 문안", "_content_id": "oauth-thread"}, "queue-key")

        self.assertEqual(remote_id, "oauth-post-1")
        client_type.assert_called_once_with(access_token="encrypted-vault-token")
        client_type.return_value.publish_text.assert_called_once_with("승인 대기열 문안")

    def test_oauth_vault_token_without_publish_scope_fails_closed(self):
        with patch.dict("os.environ", {
            "TAK_AUTO_DATA_DIR": str(self.data_dir),
            "TAK_AUTO_OAUTH_ENCRYPTION_KEY": "test-fernet-key",
        }, clear=True), \
                patch("content_engine.trend_publishers.OAuthTokenVault") as vault_type, \
                patch("content_engine.trend_publishers.ThreadsClient") as client_type:
            vault_type.return_value.get.return_value = {
                "access_token": "profile-only-token", "granted_scopes": "threads_basic",
            }
            with self.assertRaisesRegex(PermanentPublishError, "게시 권한이 없습니다"):
                publish("threads", {"body": "게시하지 말아야 할 문안", "_content_id": "no-scope"}, "queue-key")
        client_type.assert_not_called()

    def test_expired_oauth_vault_token_fails_closed(self):
        with patch.dict("os.environ", {
            "TAK_AUTO_DATA_DIR": str(self.data_dir),
            "TAK_AUTO_OAUTH_ENCRYPTION_KEY": "test-fernet-key",
        }, clear=True), \
                patch("content_engine.trend_publishers.OAuthTokenVault") as vault_type, \
                patch("content_engine.trend_publishers.ThreadsClient") as client_type:
            vault_type.return_value.get.return_value = {
                "access_token": "expired-token",
                "granted_scopes": "threads_content_publish",
                "expires_at": "2000-01-01T00:00:00+00:00",
            }
            with self.assertRaisesRegex(PermanentPublishError, "토큰이 만료되었습니다"):
                publish("threads", {"body": "만료 토큰 문안", "_content_id": "expired"}, "queue-key")
        client_type.assert_not_called()


    def test_instagram_client_rejects_non_https_media_without_remote_calls(self):
        calls = []
        client = InstagramClient(
            access_token="test-token", instagram_user_id="123456789",
            transport=lambda *args, **kwargs: calls.append(args),
        )
        for url in ("http://cdn.example.test/reel.mp4", "/tmp/reel.mp4", "https:///missing-host.mp4"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                client.publish_reel(video_url=url, caption="문안")
        self.assertEqual(calls, [])

    def test_instagram_client_does_not_publish_when_processing_never_finishes(self):
        calls = []
        def transport(method, url, *, access_token, fields=None, timeout_seconds=30.0):
            calls.append((method, url))
            if method == "POST":
                return {"id": "container-1"}
            return {"status_code": "IN_PROGRESS"}

        client = InstagramClient(
            access_token="test-token", instagram_user_id="123456789",
            transport=transport, sleep=lambda seconds: None,
        )
        with self.assertRaisesRegex(InstagramAPIError, "아직 끝나지 않았습니다"):
            client.publish_reel(
                video_url="https://cdn.example.test/reel.mp4",
                caption="문안", poll_attempts=2,
            )
        self.assertEqual([method for method, _ in calls], ["POST", "GET", "GET"])
        self.assertFalse(any(url.endswith("/media_publish") for _, url in calls))

    def test_instagram_get_status_fields_are_query_parameters_and_token_stays_header(self):
        import json
        from urllib.parse import parse_qs, urlsplit
        from unittest.mock import Mock, patch
        from content_engine.instagram_publisher import _request_json

        response = Mock()
        response.read.return_value = json.dumps({"status_code": "FINISHED"}).encode("utf-8")
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        with patch("content_engine.instagram_publisher.urlopen", return_value=response) as opener:
            result = _request_json(
                "GET", "https://graph.instagram.com/v27.0/container-1",
                access_token="never-put-token-in-url",
                fields={"fields": "status_code,status"},
            )
        request = opener.call_args.args[0]
        self.assertEqual(result["status_code"], "FINISHED")
        self.assertEqual(parse_qs(urlsplit(request.full_url).query)["fields"], ["status_code,status"])
        self.assertNotIn("never-put-token-in-url", request.full_url)
        self.assertEqual(request.get_header("Authorization"), "Bearer never-put-token-in-url")


if __name__ == "__main__":
    unittest.main()
