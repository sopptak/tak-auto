from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from urllib.error import HTTPError

from content_engine.youtube_publisher import (
    YouTubeAPIError,
    YouTubeClient,
    YouTubeConfigurationError,
    YouTubeUploadResult,
    _default_token_transport,
    _default_upload_transport,
)


def _make_temp_mp4() -> Path:
    handle = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    handle.write(b"fake-mp4-bytes")
    handle.close()
    return Path(handle.name)


class YouTubeClientConfigurationTests(unittest.TestCase):
    def test_missing_env_vars_raise_configuration_error(self):
        with self.assertRaises(YouTubeConfigurationError):
            YouTubeClient.from_environment({})

        with self.assertRaises(YouTubeConfigurationError) as ctx:
            YouTubeClient.from_environment({"YOUTUBE_CLIENT_ID": "cid"})
        self.assertIn("YOUTUBE_CLIENT_SECRET", str(ctx.exception))
        self.assertIn("YOUTUBE_REFRESH_TOKEN", str(ctx.exception))

    def test_client_created_from_environment(self):
        client = YouTubeClient.from_environment(
            {
                "YOUTUBE_CLIENT_ID": "test-client-id",
                "YOUTUBE_CLIENT_SECRET": "test-client-secret",
                "YOUTUBE_REFRESH_TOKEN": "test-refresh-token",
            }
        )
        self.assertEqual(client.client_id, "test-client-id")
        self.assertEqual(client.client_secret, "test-client-secret")
        self.assertEqual(client.refresh_token, "test-refresh-token")


class YouTubeClientUploadTests(unittest.TestCase):
    def setUp(self):
        self.video_path = _make_temp_mp4()
        self.addCleanup(self.video_path.unlink, missing_ok=True)

    def _client(self, token_transport=None, upload_transport=None):
        kwargs = {}
        if token_transport is not None:
            kwargs["token_transport"] = token_transport
        if upload_transport is not None:
            kwargs["upload_transport"] = upload_transport
        return YouTubeClient(
            client_id="cid",
            client_secret="secret",
            refresh_token="rtoken",
            **kwargs,
        )

    def test_upload_short_success_sends_correct_metadata_and_token(self):
        token_calls = []
        upload_calls = []

        def token_transport(client_id, client_secret, refresh_token, timeout):
            token_calls.append((client_id, client_secret, refresh_token, timeout))
            return {"access_token": "fresh-access-token", "expires_in": 3600}

        def upload_transport(access_token, metadata, video_path, timeout):
            upload_calls.append((access_token, metadata, video_path, timeout))
            return {"id": "yt_video_123"}

        client = self._client(token_transport=token_transport, upload_transport=upload_transport)
        result = client.upload_short(
            video_path=self.video_path,
            title="테스트 제목",
            description="테스트 설명",
            tags=["태그1", "태그2"],
            privacy_status="private",
        )

        self.assertIsInstance(result, YouTubeUploadResult)
        self.assertEqual(result.video_id, "yt_video_123")
        self.assertEqual(result.url, "https://youtu.be/yt_video_123")

        self.assertEqual(len(token_calls), 1)
        self.assertEqual(token_calls[0][:3], ("cid", "secret", "rtoken"))

        self.assertEqual(len(upload_calls), 1)
        access_token, metadata, video_path, _timeout = upload_calls[0]
        self.assertEqual(access_token, "fresh-access-token")
        self.assertEqual(video_path, self.video_path)
        self.assertEqual(metadata["snippet"]["title"], "테스트 제목")
        self.assertEqual(metadata["snippet"]["description"], "테스트 설명")
        self.assertEqual(metadata["snippet"]["tags"], ["태그1", "태그2"])
        self.assertEqual(metadata["status"]["privacyStatus"], "private")
        self.assertEqual(metadata["status"]["selfDeclaredMadeForKids"], False)

    def test_upload_short_missing_file_raises_value_error(self):
        client = self._client(
            token_transport=lambda *a: {"access_token": "t"},
            upload_transport=lambda *a: {"id": "x"},
        )
        with self.assertRaises(ValueError):
            client.upload_short(
                video_path=Path("/nonexistent/short.mp4"),
                title="제목",
            )

    def test_upload_short_rejects_non_mp4_extension(self):
        with tempfile.NamedTemporaryFile(suffix=".mov", delete=False) as tmp:
            tmp.write(b"data")
            bad_path = Path(tmp.name)
        self.addCleanup(bad_path.unlink, missing_ok=True)

        client = self._client(
            token_transport=lambda *a: {"access_token": "t"},
            upload_transport=lambda *a: {"id": "x"},
        )
        with self.assertRaises(ValueError):
            client.upload_short(video_path=bad_path, title="제목")

    def test_upload_short_empty_title_raises_value_error(self):
        client = self._client(
            token_transport=lambda *a: {"access_token": "t"},
            upload_transport=lambda *a: {"id": "x"},
        )
        with self.assertRaises(ValueError):
            client.upload_short(video_path=self.video_path, title="   ")

    def test_upload_short_title_exceeding_100_chars_raises_value_error(self):
        client = self._client(
            token_transport=lambda *a: {"access_token": "t"},
            upload_transport=lambda *a: {"id": "x"},
        )
        with self.assertRaises(ValueError) as ctx:
            client.upload_short(video_path=self.video_path, title="가" * 101)
        self.assertIn("YouTube title exceeds 100 characters: 101", str(ctx.exception))

    def test_upload_short_invalid_privacy_status_raises_value_error(self):
        client = self._client(
            token_transport=lambda *a: {"access_token": "t"},
            upload_transport=lambda *a: {"id": "x"},
        )
        with self.assertRaises(ValueError):
            client.upload_short(video_path=self.video_path, title="제목", privacy_status="everyone")

    def test_upload_short_supports_all_privacy_statuses(self):
        for privacy in ("private", "unlisted", "public"):
            client = self._client(
                token_transport=lambda *a: {"access_token": "t"},
                upload_transport=lambda access_token, metadata, video_path, timeout: {"id": "vid"},
            )
            result = client.upload_short(video_path=self.video_path, title="제목", privacy_status=privacy)
            self.assertEqual(result.video_id, "vid")

    def test_missing_video_id_in_response_raises_api_error(self):
        client = self._client(
            token_transport=lambda *a: {"access_token": "t"},
            upload_transport=lambda *a: {"status": "ok"},
        )
        with self.assertRaises(YouTubeAPIError):
            client.upload_short(video_path=self.video_path, title="제목")

    def test_token_transport_failure_propagates_as_api_error(self):
        def failing_token_transport(*args):
            raise YouTubeAPIError("YouTube OAuth Token HTTP 400: message=invalid_grant")

        client = self._client(
            token_transport=failing_token_transport,
            upload_transport=lambda *a: {"id": "vid"},
        )
        with self.assertRaises(YouTubeAPIError):
            client.upload_short(video_path=self.video_path, title="제목")


class YouTubeDefaultTransportTests(unittest.TestCase):
    def test_token_is_not_exposed_in_api_error_messages(self):
        secret = "SECRET_SUPER_SENSITIVE_REFRESH_TOKEN"
        error_body = BytesIO(
            json.dumps({"error": "invalid_grant", "error_description": "Token has been expired or revoked."}).encode(
                "utf-8"
            )
        )
        with mock.patch(
            "content_engine.youtube_publisher.urlopen",
            side_effect=HTTPError("https://oauth2.googleapis.com/token", 400, "Bad Request", {}, error_body),
        ):
            with self.assertRaises(YouTubeAPIError) as raised:
                _default_token_transport("cid", "secret", secret, 30.0)

        error_msg = str(raised.exception)
        self.assertIn("YouTube OAuth Token HTTP 400", error_msg)
        self.assertIn("Token has been expired or revoked", error_msg)
        self.assertNotIn(secret, error_msg)

    def test_upload_init_missing_location_header_raises_api_error(self):
        class FakeResponse:
            def __init__(self):
                self.headers = {}

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        video_path = _make_temp_mp4()
        try:
            with mock.patch(
                "content_engine.youtube_publisher.urlopen",
                return_value=FakeResponse(),
            ):
                with self.assertRaises(YouTubeAPIError) as raised:
                    _default_upload_transport("access-token", {"snippet": {}}, video_path, 30.0)
            self.assertIn("Location", str(raised.exception))
        finally:
            video_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
