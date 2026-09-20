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

from content_engine.youtube_publisher import YouTubeClient, _default_stats_transport


class YouTubeVideoStatisticsTests(unittest.TestCase):
    def _client(self, token_transport=None, stats_transport=None):
        kwargs = {}
        if token_transport is not None:
            kwargs["token_transport"] = token_transport
        if stats_transport is not None:
            kwargs["stats_transport"] = stats_transport
        return YouTubeClient(client_id="cid", client_secret="secret", refresh_token="rtoken", **kwargs)

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


if __name__ == "__main__":
    unittest.main()
