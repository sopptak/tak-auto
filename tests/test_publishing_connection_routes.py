import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from scripts import run_trend_content_mvp as app


class PublishingConnectionRouteTests(unittest.TestCase):
    now = datetime(2026, 11, 17, 0, 0, tzinfo=timezone.utc)

    def test_verified_profile_is_cached_without_storing_access_token(self):
        environ = {"THREADS_ACCESS_TOKEN": "test-token", "THREADS_USERNAME": "configured_name"}
        with patch.object(app, "verify_publishing_connection", return_value={
            "account_id": "thread-id", "account_name": "verified_name",
        }) as verify:
            cache, message = app._run_connection_verification("threads", {}, environ=environ, now=self.now)

        verify.assert_called_once_with("threads", environ)
        self.assertEqual(cache["threads"]["status"], "verified")
        self.assertEqual(cache["threads"]["account_name"], "verified_name")
        self.assertIn("verified_name", message)
        self.assertNotIn("test-token", json.dumps(cache))

    def test_api_failure_is_cached_as_unverified_safe_message(self):
        environ = {"THREADS_ACCESS_TOKEN": "test-token", "THREADS_USERNAME": "configured_name"}
        with patch.object(app, "verify_publishing_connection", side_effect=ValueError("safe API summary")):
            cache, message = app._run_connection_verification("threads", {}, environ=environ, now=self.now)

        self.assertEqual(cache["threads"]["status"], "failed")
        self.assertEqual(cache["threads"]["account_name"], "configured_name")
        self.assertIn("safe API summary", cache["threads"]["message"])
        self.assertIn("확인 실패", message)
        self.assertNotIn("test-token", json.dumps(cache))

    def test_oauth_connected_account_can_be_verified_without_legacy_env_tokens(self):
        environ = {"TAK_AUTO_OAUTH_ENCRYPTION_KEY": "vault-key"}
        linked = {"threads": {"account_id": "thread-id", "account_name": "oauth_user"}}
        with patch.object(app, "verify_publishing_connection", return_value={
            "account_id": "thread-id", "account_name": "oauth_user",
        }) as verify:
            cache, message = app._run_connection_verification(
                "threads", {}, environ=environ, now=self.now, oauth_connections=linked,
            )
        verify.assert_called_once_with("threads", environ)
        self.assertEqual(cache["threads"]["status"], "verified")
        self.assertIn("oauth_user", message)

    def test_oauth_storage_error_stops_verification_before_api_call(self):
        with patch.object(app, "_read_oauth_connections", return_value=({}, "storage error")) as read:
            with patch.object(app, "verify_publishing_connection") as verify:
                with self.assertRaisesRegex(ValueError, "암호화 저장소"):
                    app._run_connection_verification("threads", {}, environ={"TAK_AUTO_OAUTH_ENCRYPTION_KEY": "key"})
        verify.assert_not_called()

    def test_missing_or_unsupported_account_never_calls_external_verifier(self):
        with patch.object(app, "verify_publishing_connection") as verify:
            with self.assertRaisesRegex(ValueError, "인증 환경변수"):
                app._run_connection_verification("threads", {}, environ={})
            with self.assertRaisesRegex(ValueError, "지원하지 않는 플랫폼"):
                app._run_connection_verification("tiktok", {}, environ={})
        verify.assert_not_called()


if __name__ == "__main__":
    unittest.main()
