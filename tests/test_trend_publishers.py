import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from content_engine.publishing_queue import PermanentPublishError, PublishUncertainError
from content_engine.threads_publisher import ThreadsAPIError
from content_engine.youtube_publisher import YouTubeAPIError
from content_engine.instagram_publisher import InstagramAPIError, InstagramClient
from content_engine.tiktok_publisher import TikTokAPIError, TikTokClient, TikTokPublishRejectedError
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
                "_knowledge_id": "trend-preview-k123", "_source_url": "https://example.test/source",
            }, "queue-key")

        self.assertEqual(remote_id, "threads-post-1")
        self.client.publish_text.assert_called_once_with("승인된 Threads 문안")
        history = (self.data_dir / "threads_publish_log.json").read_text(encoding="utf-8")
        self.assertIn("trend-thread-1", history)
        self.assertIn("threads-post-1", history)
        self.assertIn('"knowledge_id": "trend-preview-k123"', history)
        self.assertIn('"source_url": "https://example.test/source"', history)
        self.assertIn('"title": "제목"', history)

    def test_existing_threads_history_skips_remote_publish(self):
        with patch.dict("os.environ", {"TAK_AUTO_DATA_DIR": str(self.data_dir)}, clear=True), \
                patch("content_engine.trend_publishers.ThreadsClient.from_environment", return_value=self.client):
            publish("threads", {"body": "첫 게시", "_content_id": "same-content"}, "first-key")
            remote_id = publish("threads", {"body": "재시도", "_content_id": "same-content"}, "retry-key")

        self.assertEqual(remote_id, "threads-post-1")
        self.client.publish_text.assert_called_once_with("첫 게시")

    def test_malformed_history_id_requires_review_without_reposting(self):
        history_path = self.data_dir / "threads_publish_log.json"
        for platform in ("threads", "facebook"):
            with self.subTest(platform=platform):
                history = json.dumps([{
                    "platform": platform, "content_id": "same-content", "remote_id": {"invalid": "id"},
                }])
                history_path.write_text(history, encoding="utf-8")
                with patch.dict("os.environ", {"TAK_AUTO_DATA_DIR": str(self.data_dir)}, clear=True), \
                        patch("content_engine.trend_publishers._threads_client") as threads_client, \
                        patch("content_engine.trend_publishers.FacebookClient") as facebook_client:
                    with self.assertRaises(PublishUncertainError):
                        publish(platform, {"body": "검토된 문안", "_content_id": "same-content"}, "queue-key")
                    threads_client.assert_not_called()
                    facebook_client.assert_not_called()
                self.assertEqual(history_path.read_text(encoding="utf-8"), history)

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

    def test_youtube_shorts_uses_encrypted_oauth_refresh_token_and_upload_scope(self):
        video = self.data_dir / "approved-oauth-short.mp4"
        video.write_bytes(b"test-video")
        youtube = Mock()
        youtube.upload_short.return_value = SimpleNamespace(video_id="oauth-youtube-video")
        with patch.dict("os.environ", {
            "TAK_AUTO_DATA_DIR": str(self.data_dir),
            "TAK_AUTO_OAUTH_ENCRYPTION_KEY": "vault-key",
            "YOUTUBE_OAUTH_CLIENT_ID": "web-client-id",
            "YOUTUBE_OAUTH_CLIENT_SECRET": "web-client-secret",
        }, clear=True):
            with patch(
                "content_engine.trend_publishers.YouTubeClient.from_environment_or_oauth",
                return_value=youtube,
            ) as client_factory:
                remote_id = publish("youtube_shorts", {
                    "video_path": str(video), "title": "OAuth 승인 쇼츠",
                }, "youtube-oauth-key")
                client_factory.assert_called_once_with(
                    required_scope="https://www.googleapis.com/auth/youtube.upload",
                )
        self.assertEqual(remote_id, "oauth-youtube-video")
        youtube.upload_short.assert_called_once()

    def test_youtube_shorts_oauth_connection_without_upload_scope_fails_closed(self):
        video = self.data_dir / "approved-no-scope.mp4"
        video.write_bytes(b"test-video")
        with patch.dict("os.environ", {
            "TAK_AUTO_DATA_DIR": str(self.data_dir),
            "TAK_AUTO_OAUTH_ENCRYPTION_KEY": "vault-key",
        }, clear=True):
            with patch("content_engine.social_oauth.OAuthTokenVault") as vault_type:
                with patch("content_engine.trend_publishers.YouTubeClient.from_environment") as legacy_factory:
                    vault_type.return_value.get.return_value = {
                        "refresh_token": "refresh", "granted_scopes": "youtube.readonly",
                    }
                    with self.assertRaisesRegex(PermanentPublishError, "youtube.upload"):
                        publish("youtube_shorts", {
                            "video_path": str(video), "title": "권한 없는 쇼츠",
                        }, "youtube-no-scope")
        legacy_factory.assert_not_called()
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

    def test_instagram_adapter_rejects_obsolete_publishing_scope(self):
        with patch.dict("os.environ", {
            "TAK_AUTO_DATA_DIR": str(self.data_dir),
            "TAK_AUTO_OAUTH_ENCRYPTION_KEY": "test-fernet-key",
        }, clear=True), patch("content_engine.trend_publishers.OAuthTokenVault") as vault_type:
            vault_type.return_value.get.return_value = {
                "access_token": "ig-token", "account_id": "123456789",
                "granted_scopes": "instagram_business_basic,instagram_business_content_publishing",
            }
            with self.assertRaisesRegex(PermanentPublishError, "게시 권한이 없습니다"):
                publish("instagram_reels", {
                    "video_url": "https://cdn.example.test/reel.mp4",
                    "caption": "승인된 릴스",
                }, "instagram-old-scope-key")

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
                "granted_scopes": "instagram_business_basic,instagram_business_content_publish",
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
                "granted_scopes": "instagram_business_basic,instagram_business_content_publish",
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

    def test_facebook_client_publishes_page_feed_text_with_page_token(self):
        from content_engine.facebook_publisher import FacebookClient

        calls = []
        def transport(method, url, **kwargs):
            calls.append((method, url, kwargs))
            return {"id": "123_456"}
        client = FacebookClient(
            access_token="page-access-token", page_id="123", transport=transport,
        )
        result = client.publish_text("승인된 Facebook 페이지 문안")
        self.assertEqual(result.post_id, "123_456")
        self.assertEqual(calls[0][0], "POST")
        self.assertEqual(calls[0][1], "https://graph.facebook.com/v27.0/123/feed")
        self.assertEqual(calls[0][2]["access_token"], "page-access-token")
        self.assertEqual(calls[0][2]["fields"]["message"], "승인된 Facebook 페이지 문안")

    def test_facebook_transport_rejects_untrusted_hosts_before_network_call(self):
        from content_engine.facebook_publisher import FacebookAPIError, _request_json
        with patch("content_engine.facebook_publisher.build_opener") as opener:
            with self.assertRaises(FacebookAPIError):
                _request_json("POST", "https://example.com/v27.0/123/feed",
                              access_token="page-token", fields={"message": "문안"})
        opener.assert_not_called()

    def test_facebook_adapter_requires_page_publish_scopes(self):
        with patch.dict("os.environ", {
            "TAK_AUTO_DATA_DIR": str(self.data_dir),
            "TAK_AUTO_OAUTH_ENCRYPTION_KEY": "test-fernet-key",
        }, clear=True), patch("content_engine.trend_publishers.OAuthTokenVault") as vault_type, \
                patch("content_engine.trend_publishers.FacebookClient") as client_type:
            vault_type.return_value.get.return_value = {
                "access_token": "page-token", "account_id": "123", "tasks": ["CREATE_CONTENT"],
                "granted_scopes": "pages_show_list,pages_read_engagement",
            }
            with self.assertRaisesRegex(PermanentPublishError, "게시 권한이 부족"):
                publish("facebook", {"body": "승인 문안"}, "facebook-key")
        client_type.assert_not_called()

    def test_facebook_adapter_posts_to_selected_page_and_returns_post_id(self):
        with patch.dict("os.environ", {
            "TAK_AUTO_DATA_DIR": str(self.data_dir),
            "TAK_AUTO_OAUTH_ENCRYPTION_KEY": "test-fernet-key",
        }, clear=True), patch("content_engine.trend_publishers.OAuthTokenVault") as vault_type, \
                patch("content_engine.trend_publishers.FacebookClient") as client_type:
            vault_type.return_value.get.return_value = {
                "access_token": "page-token", "account_id": "123", "tasks": ["CREATE_CONTENT"],
                "account_name": "탁자동 페이지",
                "granted_scopes": "pages_show_list,pages_read_engagement,pages_manage_posts",
            }
            client_type.return_value.publish_text.return_value = SimpleNamespace(post_id="123_456")
            remote_id = publish("facebook", {
                "title": "Facebook 제목", "body": "승인 문안",
                "_content_id": "facebook-content-1",
                "_knowledge_id": "trend-preview-k123",
                "_source_url": "https://example.test/source",
            }, "facebook-key")
            duplicate_id = publish("facebook", {"body": "변경된 재시도 문안", "_content_id": "facebook-content-1"}, "facebook-retry")
        self.assertEqual(remote_id, "123_456")
        self.assertEqual(duplicate_id, "123_456")
        client_type.assert_called_once_with(
            access_token="page-token", page_id="123", api_version="v27.0",
        )
        client_type.return_value.publish_text.assert_called_once_with("승인 문안")
        history = (self.data_dir / "threads_publish_log.json").read_text(encoding="utf-8")
        self.assertIn("facebook-content-1", history)
        self.assertIn('"platform": "facebook"', history)
        self.assertIn('"remote_id": "123_456"', history)
        self.assertIn('"knowledge_id": "trend-preview-k123"', history)
        self.assertIn('"source_url": "https://example.test/source"', history)
        self.assertIn('"title": "Facebook 제목"', history)

    def test_facebook_ambiguous_api_failure_requires_manual_review(self):
        from content_engine.facebook_publisher import FacebookAPIError
        with patch.dict("os.environ", {
            "TAK_AUTO_DATA_DIR": str(self.data_dir),
            "TAK_AUTO_OAUTH_ENCRYPTION_KEY": "test-fernet-key",
        }, clear=True), patch("content_engine.trend_publishers.OAuthTokenVault") as vault_type, \
                patch("content_engine.trend_publishers.FacebookClient") as client_type:
            vault_type.return_value.get.return_value = {
                "access_token": "page-token", "account_id": "123", "tasks": ["CREATE_CONTENT"],
                "granted_scopes": "pages_show_list pages_read_engagement pages_manage_posts",
            }
            client_type.return_value.publish_text.side_effect = FacebookAPIError("network")
            with self.assertRaises(PublishUncertainError):
                publish("facebook", {"body": "승인 문안"}, "facebook-key")

    def test_unsupported_platform_fails_closed_without_calling_threads(self):
        with patch("content_engine.trend_publishers.ThreadsClient.from_environment") as factory:
            with self.assertRaisesRegex(PermanentPublishError, "아직 준비되지 않았습니다"):
                publish("snapchat", {"body": "본문"}, "queue-key")
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
        from unittest.mock import MagicMock, patch
        from content_engine.instagram_publisher import _request_json

        response = MagicMock()
        response.read.return_value = json.dumps({"status_code": "FINISHED"}).encode("utf-8")
        response.__enter__.return_value = response
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


    def test_tiktok_direct_post_queries_creator_uploads_and_waits_for_publish(self):
        video = self.data_dir / "approved-tiktok.mp4"
        video.write_bytes(b"mp4-test-data")
        calls = []
        responses = iter([
            {"data": {"privacy_level_options": ["SELF_ONLY", "PUBLIC_TO_EVERYONE"],
                      "comment_disabled": True, "duet_disabled": False, "stitch_disabled": True},
             "error": {"code": "ok"}},
            {"data": {"publish_id": "publish-1", "upload_url": "https://open-upload.tiktokapis.com/video/?upload_id=1&upload_token=secret"}, "error": {"code": "ok"}},
            {"data": {"status": "PROCESSING_UPLOAD"}, "error": {"code": "ok"}},
            {"data": {"status": "PUBLISH_COMPLETE", "publicaly_available_post_id": ["post-1"]}, "error": {"code": "ok"}},
        ])
        uploads = []
        def json_transport(method, url, *, access_token, body=None, timeout_seconds=30.0):
            calls.append((method, url, body))
            return next(responses)
        def upload_transport(url, chunk, *, start, total, timeout_seconds=60.0):
            uploads.append((url, chunk, start, total))
            return 201
        client = TikTokClient(access_token="test-token", open_id="open-id-1",
                              json_transport=json_transport, upload_transport=upload_transport,
                              sleep=lambda seconds: None)
        result = client.publish_video(video_path=video, title="승인된 TikTok 문안",
                                      privacy_level="SELF_ONLY", is_aigc=True)
        self.assertEqual(result.publish_id, "publish-1")
        self.assertEqual(result.post_id, "post-1")
        self.assertEqual([call[1].split("/v2/")[1] for call in calls], [
            "post/publish/creator_info/query/", "post/publish/video/init/",
            "post/publish/status/fetch/", "post/publish/status/fetch/",
        ])
        self.assertEqual(calls[1][2]["post_info"]["privacy_level"], "SELF_ONLY")
        self.assertTrue(calls[1][2]["post_info"]["is_aigc"])
        self.assertTrue(calls[1][2]["post_info"]["disable_comment"])
        self.assertFalse(calls[1][2]["post_info"]["disable_duet"])
        self.assertTrue(calls[1][2]["post_info"]["disable_stitch"])
        self.assertEqual(len(uploads), 1)
        self.assertEqual(uploads[0][1], b"mp4-test-data")
        self.assertEqual(uploads[0][2:], (0, len(b"mp4-test-data")))

    def test_tiktok_direct_post_rejects_privacy_not_allowed_by_creator(self):
        video = self.data_dir / "approved-tiktok.mp4"
        video.write_bytes(b"mp4-test-data")
        calls = []
        def json_transport(method, url, *, access_token, body=None, timeout_seconds=30.0):
            calls.append(url)
            return {"data": {"privacy_level_options": ["SELF_ONLY"]}, "error": {"code": "ok"}}
        client = TikTokClient(access_token="test-token", open_id="open-id-1", json_transport=json_transport)
        with self.assertRaisesRegex(ValueError, "현재 계정에서 허용"):
            client.publish_video(video_path=video, title="문안", privacy_level="PUBLIC_TO_EVERYONE")
        self.assertEqual(len(calls), 1)

    def test_tiktok_direct_post_failure_is_not_reported_as_success(self):
        video = self.data_dir / "approved-tiktok.mp4"
        video.write_bytes(b"mp4-test-data")
        responses = iter([
            {"data": {"privacy_level_options": ["SELF_ONLY"]}, "error": {"code": "ok"}},
            {"data": {"publish_id": "publish-2", "upload_url": "https://open-upload.tiktokapis.com/video/?upload_id=2"}, "error": {"code": "ok"}},
            {"data": {"status": "FAILED", "fail_reason": "file_format_check_failed"}, "error": {"code": "ok"}},
        ])
        client = TikTokClient(access_token="test-token", open_id="open-id-1",
                              json_transport=lambda *args, **kwargs: next(responses),
                              upload_transport=lambda *args, **kwargs: 201, sleep=lambda seconds: None)
        with self.assertRaises(TikTokPublishRejectedError):
            client.publish_video(video_path=video, title="문안", privacy_level="SELF_ONLY")

    def test_tiktok_direct_post_chunks_large_files_sequentially(self):
        video = self.data_dir / "large-tiktok.mp4"
        with video.open("wb") as handle:
            handle.seek(10 * 1024 * 1024)
            handle.write(b"x")
        uploads = []
        responses = iter([
            {"data": {"privacy_level_options": ["SELF_ONLY"]}, "error": {"code": "ok"}},
            {"data": {"publish_id": "publish-3", "upload_url": "https://open-upload.tiktokapis.com/video/?upload_id=3"}, "error": {"code": "ok"}},
            {"data": {"status": "PUBLISH_COMPLETE", "publicaly_available_post_id": []}, "error": {"code": "ok"}},
        ])
        client = TikTokClient(access_token="test-token", open_id="open-id-1",
                              json_transport=lambda *args, **kwargs: next(responses),
                              upload_transport=lambda url, chunk, *, start, total, timeout_seconds=60.0:
                                  (uploads.append((len(chunk), start, total)) or 201),
                              sleep=lambda seconds: None)
        with patch("content_engine.tiktok_publisher.MAX_CHUNK_BYTES", 6 * 1024 * 1024):
            result = client.publish_video(video_path=video, title="문안", privacy_level="SELF_ONLY")
        self.assertEqual(result.publish_id, "publish-3")
        self.assertEqual(uploads, [
            (5 * 1024 * 1024, 0, 10 * 1024 * 1024 + 1),
            (5 * 1024 * 1024 + 1, 5 * 1024 * 1024, 10 * 1024 * 1024 + 1),
        ])

    def test_tiktok_adapter_requires_video_publish_scope_and_explicit_privacy(self):
        video = self.data_dir / "not-needed.mp4"
        video.write_bytes(b"mp4-test-data")
        with patch.dict("os.environ", {"TAK_AUTO_DATA_DIR": str(self.data_dir),
                                      "TAK_AUTO_OAUTH_ENCRYPTION_KEY": "test-fernet-key"}, clear=True), patch("content_engine.trend_publishers.OAuthTokenVault") as vault_type:
            vault_type.return_value.get.return_value = {
                "access_token": "tiktok-token", "account_id": "open-id-1",
                "granted_scopes": "user.info.basic",
            }
            with self.assertRaisesRegex(PermanentPublishError, "공개 범위"):
                publish("tiktok", {"video_path": str(video), "title": "문안"}, "tt-key")
            with self.assertRaisesRegex(PermanentPublishError, "Direct Post 게시 권한"):
                publish("tiktok", {"video_path": str(video), "title": "문안",
                                   "privacy_level": "SELF_ONLY"}, "tt-key")

    def test_tiktok_adapter_uses_encrypted_token_and_marks_ambiguous_api_failure(self):
        video = self.data_dir / "approved-tiktok.mp4"
        video.write_bytes(b"mp4-test-data")
        with patch.dict("os.environ", {"TAK_AUTO_DATA_DIR": str(self.data_dir),
                                      "TAK_AUTO_OAUTH_ENCRYPTION_KEY": "test-fernet-key"}, clear=True), patch("content_engine.trend_publishers.OAuthTokenVault") as vault_type, patch("content_engine.trend_publishers.TikTokClient") as client_type:
            vault_type.return_value.get.return_value = {
                "access_token": "private-tiktok-token", "account_id": "open-id-1",
                "granted_scopes": "user.info.basic,video.publish",
                "expires_at": "2099-01-01T00:00:00+00:00",
            }
            client_type.return_value.publish_video.side_effect = TikTokAPIError("connection lost")
            with self.assertRaises(PublishUncertainError):
                publish("tiktok", {"video_path": str(video), "title": "승인된 문안",
                                   "privacy_level": "SELF_ONLY", "is_aigc": True}, "tt-key")
        client_type.assert_called_once_with(access_token="private-tiktok-token", open_id="open-id-1")
        client_type.return_value.publish_video.assert_called_once_with(
            video_path=video, title="승인된 문안", privacy_level="SELF_ONLY",
            disable_comment=False, disable_duet=False, disable_stitch=False, is_aigc=True,
        )


if __name__ == "__main__":
    unittest.main()
