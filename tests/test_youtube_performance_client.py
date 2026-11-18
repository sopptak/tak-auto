"""content_engine.youtube_publisher.YouTubeClient.get_video_statistics() 검증(6-01).

별도 파일로 분리한 이유: tests/test_youtube_publisher.py는 이번 작업 시작 시점에
이미 이전 세션에서 만들어진 채 커밋되지 않은 상태였다(5-13/5-14 YouTube 업로드
기능, 이번 6-01 작업과 무관) - 그 파일에 이어 쓰면 이번 커밋에 무관한 이전
세션의 미커밋 내용까지 함께 섞여 들어간다("기존 미커밋 변경과 절대 섞지 않는다"는
지시 위반). 이 파일은 이번 세션에서 새로 만든 것이므로 git add 시 이 파일
하나만 정확히 추가된다.

업로드(upload_short)와 동일한 transport 주입 패턴이라 실제 네트워크를 전혀
호출하지 않고 검증한다.
"""

from __future__ import annotations

import json
from unittest import mock
import unittest

from content_engine.youtube_publisher import (
    YouTubeAPIError, YouTubeClient, YouTubeChannelProfile,
    _default_channel_transport, _default_stats_transport,
)


class YouTubeOAuthClientResolutionTests(unittest.TestCase):
    def test_encrypted_oauth_connection_builds_client_with_required_scope(self):
        environ = {
            "TAK_AUTO_OAUTH_ENCRYPTION_KEY": "vault-key",
            "TAK_AUTO_DATA_DIR": "/tmp/tak-auto-test",
            "YOUTUBE_OAUTH_CLIENT_ID": "web-client-id",
            "YOUTUBE_OAUTH_CLIENT_SECRET": "web-client-secret",
        }
        with mock.patch.dict("os.environ", environ, clear=True):
            with mock.patch("content_engine.social_oauth.OAuthTokenVault") as vault_type:
                vault_type.return_value.get.return_value = {
                    "refresh_token": "vault-refresh-token",
                    "granted_scopes": "https://www.googleapis.com/auth/youtube.readonly https://www.googleapis.com/auth/youtube.upload",
                }
                client = YouTubeClient.from_environment_or_oauth(
                    required_scope="https://www.googleapis.com/auth/youtube.upload",
                )
        self.assertEqual(client.client_id, "web-client-id")
        self.assertEqual(client.client_secret, "web-client-secret")
        self.assertEqual(client.refresh_token, "vault-refresh-token")
        vault_type.return_value.get.assert_called_once_with("youtube_shorts")

    def test_encrypted_oauth_connection_rejects_missing_required_scope(self):
        with mock.patch.dict("os.environ", {
            "TAK_AUTO_OAUTH_ENCRYPTION_KEY": "vault-key",
            "YOUTUBE_OAUTH_CLIENT_ID": "web-client-id",
            "YOUTUBE_OAUTH_CLIENT_SECRET": "web-client-secret",
        }, clear=True):
            with mock.patch("content_engine.social_oauth.OAuthTokenVault") as vault_type:
                vault_type.return_value.get.return_value = {
                    "refresh_token": "vault-refresh-token",
                    "granted_scopes": "https://www.googleapis.com/auth/youtube.readonly",
                }
                with self.assertRaisesRegex(ValueError, "youtube.upload"):
                    YouTubeClient.from_environment_or_oauth(
                        required_scope="https://www.googleapis.com/auth/youtube.upload",
                    )
class YouTubeVideoStatisticsTests(unittest.TestCase):
    def _client(self, token_transport=None, stats_transport=None, channel_transport=None):
        kwargs = {}
        if token_transport is not None:
            kwargs["token_transport"] = token_transport
        if stats_transport is not None:
            kwargs["stats_transport"] = stats_transport
        if channel_transport is not None:
            kwargs["channel_transport"] = channel_transport
        return YouTubeClient(client_id="cid", client_secret="secret", refresh_token="rtoken", **kwargs)

    def test_get_channel_profile_refreshes_token_and_returns_authenticated_identity(self):
        token_calls = []
        channel_calls = []

        def token_transport(client_id, client_secret, refresh_token, timeout):
            token_calls.append((client_id, client_secret, refresh_token))
            return {"access_token": "fresh-access-token"}

        def channel_transport(access_token, timeout):
            channel_calls.append((access_token, timeout))
            return {"items": [{"id": "channel-123", "snippet": {"title": "TAK AUTO"}}]}

        profile = self._client(token_transport=token_transport, channel_transport=channel_transport).get_channel_profile()
        self.assertEqual(profile, YouTubeChannelProfile(channel_id="channel-123", title="TAK AUTO"))
        self.assertEqual(token_calls, [("cid", "secret", "rtoken")])
        self.assertEqual(channel_calls[0][0], "fresh-access-token")

    def test_get_channel_profile_fails_when_authorized_account_has_no_channel(self):
        client = self._client(
            token_transport=lambda *a: {"access_token": "t"},
            channel_transport=lambda *a: {"items": []},
        )
        with self.assertRaisesRegex(YouTubeAPIError, "인증된 YouTube 채널을 찾을 수 없습니다"):
            client.get_channel_profile()

    def test_get_video_statistics_refreshes_token_and_calls_stats_transport(self):
        token_calls = []
        stats_calls = []

        def token_transport(client_id, client_secret, refresh_token, timeout):
            token_calls.append((client_id, client_secret, refresh_token))
            return {"access_token": "fresh-access-token"}

        def stats_transport(access_token, video_ids, timeout):
            stats_calls.append((access_token, video_ids, timeout))
            return {
                "items": [
                    {"id": "vid1", "statistics": {"viewCount": "100", "likeCount": "5", "commentCount": "1"}}
                ]
            }

        client = self._client(token_transport=token_transport, stats_transport=stats_transport)
        response = client.get_video_statistics(["vid1"])

        self.assertEqual(len(token_calls), 1)
        self.assertEqual(len(stats_calls), 1)
        access_token, video_ids, _timeout = stats_calls[0]
        self.assertEqual(access_token, "fresh-access-token")
        self.assertEqual(video_ids, ["vid1"])
        self.assertEqual(response["items"][0]["statistics"]["viewCount"], "100")

    def test_get_video_statistics_rejects_empty_list(self):
        client = self._client(
            token_transport=lambda *a: {"access_token": "t"}, stats_transport=lambda *a: {"items": []}
        )
        with self.assertRaises(ValueError):
            client.get_video_statistics([])

    def test_get_video_statistics_rejects_more_than_50_ids(self):
        client = self._client(
            token_transport=lambda *a: {"access_token": "t"}, stats_transport=lambda *a: {"items": []}
        )
        with self.assertRaises(ValueError):
            client.get_video_statistics([f"vid{i}" for i in range(51)])

    def test_default_stats_transport_sends_correct_request(self):
        response_body = json.dumps({"items": [{"id": "vid1", "statistics": {"viewCount": "42"}}]}).encode("utf-8")

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return response_body

        captured_requests = []

        def fake_urlopen(request, timeout):
            captured_requests.append(request)
            return FakeResponse()

        with mock.patch("content_engine.youtube_publisher.urlopen", side_effect=fake_urlopen):
            data = _default_stats_transport("access-token", ["vid1"], 30.0)

        self.assertEqual(data["items"][0]["statistics"]["viewCount"], "42")
        self.assertEqual(len(captured_requests), 1)
        request = captured_requests[0]
        self.assertIn("videos?", request.full_url)
        self.assertIn("part=statistics", request.full_url)
        self.assertIn("id=vid1", request.full_url)
        self.assertEqual(request.headers["Authorization"], "Bearer access-token")

    def test_default_channel_transport_sends_authenticated_mine_query(self):
        response_body = json.dumps({"items": [{"id": "channel-123", "snippet": {"title": "TAK AUTO"}}]}).encode("utf-8")

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return response_body

        captured_requests = []

        def fake_urlopen(request, timeout):
            captured_requests.append(request)
            return FakeResponse()

        with mock.patch("content_engine.youtube_publisher.urlopen", side_effect=fake_urlopen):
            data = _default_channel_transport("access-token", 30.0)

        self.assertEqual(data["items"][0]["id"], "channel-123")
        request = captured_requests[0]
        self.assertIn("channels?", request.full_url)
        self.assertIn("part=snippet", request.full_url)
        self.assertIn("mine=true", request.full_url)
        self.assertEqual(request.headers["Authorization"], "Bearer access-token")


if __name__ == "__main__":
    unittest.main()
