from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit

from content_engine.instagram_publisher import InstagramAPIError, InstagramClient
from content_engine.performance.instagram import collect_instagram_performance, normalize_instagram_media


class InstagramPerformanceNormalizationTests(unittest.TestCase):
    def test_normalizes_only_nonnegative_integer_media_counts(self):
        self.assertEqual(
            normalize_instagram_media({
                "like_count": "12", "comments_count": 4, "views": 100,
                "saved_count": 2, "not_count": "bad", "boolean_count": True,
                "negative_count": -1,
            }),
            {"likes": 12, "comments": 4},
        )

    def test_collect_records_missing_metrics_without_fabricating_zeroes(self):
        client = InstagramClient(
            access_token="fake-token", instagram_user_id="17840000000000000",
            transport=lambda *args, **kwargs: {"id": "17890000000000001", "like_count": 0},
        )
        record = collect_instagram_performance(
            client, media_id="17890000000000001", content_id="content-ig-1",
            knowledge_id="knowledge-ig-1", published_at="2026-11-01T00:00:00+00:00",
            metric_collected_at="2026-11-02T00:00:00+00:00",
        )
        self.assertEqual(record.metrics, {"likes": 0})
        self.assertEqual(record.unavailable_metrics, ("comments",))
        self.assertEqual(record.source, "instagram_api")

    def test_client_requests_documented_fields_and_rejects_wrong_response_id(self):
        requests = []
        client = InstagramClient(
            access_token="fake-token", instagram_user_id="17840000000000000",
            transport=lambda method, url, **kwargs: requests.append((method, url, kwargs)) or {
                "id": "17890000000000001", "like_count": 1, "comments_count": 2,
            },
        )
        result = client.get_media_performance("17890000000000001")
        self.assertEqual(result["like_count"], 1)
        self.assertEqual(requests[0][0], "GET")
        self.assertEqual(requests[0][2]["fields"], {"fields": "id,media_type,like_count,comments_count"})
        with self.assertRaisesRegex(ValueError, "숫자"):
            client.get_media_performance("../not-a-media")
        mismatch = InstagramClient(
            access_token="fake-token", instagram_user_id="17840000000000000",
            transport=lambda *args, **kwargs: {"id": "17890000000000002"},
        )
        with self.assertRaises(InstagramAPIError):
            mismatch.get_media_performance("17890000000000001")
        missing_id = InstagramClient(
            access_token="fake-token", instagram_user_id="17840000000000000",
            transport=lambda *args, **kwargs: {"like_count": 3},
        )
        with self.assertRaises(InstagramAPIError):
            missing_id.get_media_performance("17890000000000001")

    def test_does_not_truncate_fractional_metrics(self):
        self.assertEqual(
            normalize_instagram_media({"like_count": 2.7, "comments_count": "3.5"}),
            {},
        )

    def test_default_transport_keeps_token_out_of_url(self):
        from content_engine.instagram_publisher import _request_json

        response = MagicMock()
        response.read.return_value = json.dumps({"id": "17890000000000001"}).encode("utf-8")
        response.__enter__.return_value = response
        with patch("content_engine.instagram_publisher.urlopen", return_value=response) as opener:
            _request_json(
                "GET", "https://graph.instagram.com/v27.0/17890000000000001",
                access_token="private-access-token",
                fields={"fields": "id,like_count,comments_count"},
            )
        request = opener.call_args.args[0]
        self.assertEqual(parse_qs(urlsplit(request.full_url).query)["fields"], ["id,like_count,comments_count"])
        self.assertNotIn("private-access-token", request.full_url)
        self.assertEqual(request.get_header("Authorization"), "Bearer private-access-token")

    def test_oauth_factory_requires_basic_scope_and_uses_encrypted_connection(self):
        connection = {
            "access_token": "encrypted-vault-value", "account_id": "17840000000000000",
            "granted_scopes": "instagram_business_basic,instagram_business_content_publish",
            "expires_at": "2099-01-01T00:00:00+00:00",
        }
        with patch("content_engine.social_oauth.OAuthTokenVault") as vault_type:
            vault_type.return_value.get.return_value = connection
            client = InstagramClient.from_environment_or_oauth({
                "TAK_AUTO_OAUTH_ENCRYPTION_KEY": "test-key",
                "TAK_AUTO_DATA_DIR": "/tmp/tak-auto-instagram-test",
            })
        self.assertEqual(client.access_token, "encrypted-vault-value")
        self.assertEqual(client.instagram_user_id, "17840000000000000")
        vault_type.return_value.get.assert_called_once_with("instagram_reels")

        with patch("content_engine.social_oauth.OAuthTokenVault") as vault_type:
            vault_type.return_value.get.return_value = {
                **connection, "granted_scopes": "instagram_business_content_publish",
            }
            with self.assertRaisesRegex(ValueError, "instagram_business_basic"):
                InstagramClient.from_environment_or_oauth({
                    "TAK_AUTO_OAUTH_ENCRYPTION_KEY": "test-key",
                    "TAK_AUTO_DATA_DIR": "/tmp/tak-auto-instagram-test",
                })


if __name__ == "__main__":
    unittest.main()
