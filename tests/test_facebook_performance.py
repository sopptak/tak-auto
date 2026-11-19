from __future__ import annotations

import unittest
from urllib.parse import parse_qs, urlsplit

from content_engine.facebook_publisher import FacebookClient
from content_engine.performance.facebook import collect_facebook_performance, normalize_facebook_insights


class FacebookPerformanceTests(unittest.TestCase):
    def test_normalizes_documented_page_post_metrics_without_guessing(self):
        self.assertEqual(normalize_facebook_insights({"data": [
            {"name": "post_media_view", "values": [{"value": "50"}]},
            {"name": "post_reactions_by_type_total", "values": [{"value": {"like": 4, "love": 2}}]},
            {"name": "unknown", "values": [{"value": 100}]},
        ]}), {"views": 50, "reactions": 6})
        self.assertEqual(normalize_facebook_insights({"data": [
            {"name": "post_media_view", "values": [{"value": True}]},
            {"name": "post_reactions_by_type_total", "values": [{"value": {"like": -2}}]},
        ]}), {})
        self.assertEqual(normalize_facebook_insights({"data": "bad"}), {})

    def test_client_requests_insights_with_page_bearer_and_current_metrics(self):
        requests = []

        def transport(method, url, **kwargs):
            requests.append((method, url, kwargs))
            return {"data": [{"name": "post_media_view", "values": [{"value": 5}]}]}

        client = FacebookClient(access_token="secret", page_id="123", transport=transport)
        record = collect_facebook_performance(
            client, post_id="123_456", content_id="content-fb", knowledge_id="knowledge-fb",
            published_at="2026-11-01T00:00:00+00:00", metric_collected_at="2026-11-02T00:00:00+00:00",
        )
        method, url, kwargs = requests[0]
        self.assertEqual(method, "GET")
        self.assertEqual(urlsplit(url).hostname, "graph.facebook.com")
        self.assertEqual(parse_qs(urlsplit(url).query)["metric"], ["post_media_view,post_reactions_by_type_total"])
        self.assertEqual(kwargs["access_token"], "secret")
        self.assertNotIn("secret", url)
        self.assertEqual(record.metrics, {"views": 5})
        self.assertEqual(record.unavailable_metrics, ("reactions",))
        self.assertEqual(record.source, "facebook_api")

    def test_rejects_malformed_or_other_page_post_ids_before_transport(self):
        requests = []
        client = FacebookClient(access_token="secret", page_id="123", transport=lambda *a, **k: requests.append(a))
        for post_id in ("../x", "123_456_789", "999_456"):
            with self.subTest(post_id=post_id), self.assertRaises(ValueError):
                client.get_post_insights(post_id)
        self.assertEqual(requests, [])


if __name__ == "__main__":
    unittest.main()
