from __future__ import annotations

import unittest
from urllib.parse import parse_qs, urlsplit

from content_engine.performance.tiktok import collect_tiktok_performance, normalize_tiktok_video
from content_engine.tiktok_publisher import TikTokAPIError, TikTokClient


class TikTokPerformanceTests(unittest.TestCase):
    def test_normalizes_only_nonnegative_integer_video_counts(self):
        self.assertEqual(normalize_tiktok_video({
            "view_count": "100", "like_count": 4, "comment_count": 2, "share_count": 1,
            "favorite_count": 7, "bad": "x", "negative": -1, "boolean": True,
        }), {"views": 100, "likes": 4, "comments": 2, "shares": 1})

    def test_client_uses_video_query_fields_and_exact_requested_id(self):
        requests = []

        def transport(method, url, **kwargs):
            requests.append((method, url, kwargs))
            return {"data": {"videos": [{"id": "123456", "view_count": 21, "like_count": 3}]},
                    "error": {"code": "ok"}}

        client = TikTokClient(access_token="secret", open_id="open-id", json_transport=transport)
        record = collect_tiktok_performance(
            client, video_id="123456", content_id="content-tt", knowledge_id="knowledge-tt",
            published_at="2026-11-01T00:00:00+00:00", metric_collected_at="2026-11-02T00:00:00+00:00",
        )
        method, url, kwargs = requests[0]
        self.assertEqual(method, "POST")
        self.assertEqual(urlsplit(url).hostname, "open.tiktokapis.com")
        self.assertEqual(urlsplit(url).path, "/v2/video/query/")
        self.assertEqual(parse_qs(urlsplit(url).query)["fields"], ["id,view_count,like_count,comment_count,share_count"])
        self.assertEqual(kwargs["body"], {"filters": {"video_ids": ["123456"]}})
        self.assertEqual(kwargs["access_token"], "secret")
        self.assertNotIn("secret", url)
        self.assertEqual(record.metrics, {"views": 21, "likes": 3})
        self.assertEqual(record.unavailable_metrics, ("comments", "shares"))
        self.assertEqual(record.source, "tiktok_api")

    def test_rejects_invalid_or_mismatched_video_id(self):
        requests = []
        client = TikTokClient(access_token="secret", open_id="open-id",
                              json_transport=lambda *a, **k: requests.append(a) or {})
        with self.assertRaises(ValueError):
            client.get_video_statistics("../x")
        self.assertEqual(requests, [])
        mismatch = TikTokClient(access_token="secret", open_id="open-id",
                                json_transport=lambda *a, **k: {"data": {"videos": [{"id": "654321"}]},
                                                               "error": {"code": "ok"}})
        with self.assertRaises(TikTokAPIError):
            mismatch.get_video_statistics("123456")


if __name__ == "__main__":
    unittest.main()
