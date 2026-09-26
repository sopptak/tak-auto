"""scripts/youtube_oauth_setup.py의 OAuth scope 검증 및 refresh_token 로컬 저장 검증.

Device Authorization Grant(TVs and Limited Input devices)는 Google이 문서화한 허용
scope 목록에 https://www.googleapis.com/auth/youtube.upload를 포함하지 않는다.
허용되는 것은 https://www.googleapis.com/auth/youtube 와 .../youtube.readonly뿐이다.
이 테스트는 실제로 요청되는 scope가 (upload 전용이 아니라) 전체 youtube scope인지
검증한다. 실제 네트워크 호출은 하지 않는다.

또한 refresh_token이 화면(stdout/stderr)에 절대 출력되지 않고, 소유자 전용 권한의
로컬 파일에만 저장되는지 검증한다(세션/CI 로그에 값이 남는 것을 막기 위함).
"""

from __future__ import annotations

import contextlib
from io import BytesIO, StringIO
import json
import os
import stat
import sys
import tempfile
from unittest import mock
from urllib.parse import parse_qs
import unittest

from scripts.youtube_oauth_setup import (
    DEFAULT_OUTPUT_PATH,
    DEFAULT_SCOPE,
    main,
    request_device_code,
    write_refresh_token_file,
)


class DefaultScopeTests(unittest.TestCase):
    def test_default_scope_is_full_youtube_scope(self):
        self.assertEqual(DEFAULT_SCOPE, "https://www.googleapis.com/auth/youtube")

    def test_default_scope_does_not_request_upload_only_scope(self):
        # Device Authorization Grant의 허용 scope 목록에 youtube.upload가 없으므로,
        # 우회 없이 전체 youtube scope 하나만 사용해야 한다.
        self.assertNotIn("youtube.upload", DEFAULT_SCOPE)


class FakeResponse:
    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class RequestDeviceCodeScopeTests(unittest.TestCase):
    def test_request_device_code_sends_default_scope_in_request_body(self):
        captured_requests = []

        def fake_urlopen(request, timeout=None):
            captured_requests.append(request)
            return FakeResponse(
                {
                    "device_code": "ddd",
                    "user_code": "ABCD-EFGH",
                    "verification_url": "https://www.google.com/device",
                    "expires_in": 1800,
                    "interval": 5,
                }
            )

        with mock.patch("scripts.youtube_oauth_setup.urlopen", side_effect=fake_urlopen):
            request_device_code("test-client-id", DEFAULT_SCOPE)

        self.assertEqual(len(captured_requests), 1)
        sent_body = captured_requests[0].data.decode("utf-8")
        sent_fields = parse_qs(sent_body)
        self.assertEqual(sent_fields["scope"], ["https://www.googleapis.com/auth/youtube"])
        self.assertEqual(sent_fields["client_id"], ["test-client-id"])

    def test_request_device_code_never_sends_upload_only_scope(self):
        captured_requests = []

        def fake_urlopen(request, timeout=None):
            captured_requests.append(request)
            return FakeResponse({"device_code": "d", "user_code": "u", "verification_url": "v"})

        with mock.patch("scripts.youtube_oauth_setup.urlopen", side_effect=fake_urlopen):
            request_device_code("test-client-id", DEFAULT_SCOPE)

        sent_body = captured_requests[0].data.decode("utf-8")
        self.assertNotIn("youtube.upload", sent_body)


class MainUsesDefaultScopeTests(unittest.TestCase):
    def test_main_requests_default_scope_when_not_overridden(self):
        captured_scopes = []

        def fake_request_device_code(client_id, scope):
            captured_scopes.append(scope)
            return {
                "device_code": "ddd",
                "user_code": "ABCD-EFGH",
                "verification_url": "https://www.google.com/device",
                "expires_in": 1800,
                "interval": 5,
            }

        def fake_poll_for_token(client_id, client_secret, device_code, interval, expires_in):
            return {"refresh_token": "fake-refresh-token", "access_token": "fake-access-token"}

        with mock.patch(
            "scripts.youtube_oauth_setup.request_device_code", side_effect=fake_request_device_code
        ), mock.patch("scripts.youtube_oauth_setup.poll_for_token", side_effect=fake_poll_for_token), tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "youtube_refresh_token.txt")
            exit_code = main(
                ["--client-id", "cid", "--client-secret", "secret", "--output", output_path]
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(captured_scopes, ["https://www.googleapis.com/auth/youtube"])


class DefaultOutputPathTests(unittest.TestCase):
    def test_default_output_path_lives_under_secrets_directory(self):
        self.assertEqual(DEFAULT_OUTPUT_PATH, "secrets/youtube_refresh_token.txt")

    def test_secrets_directory_is_gitignored(self):
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(repo_root, ".gitignore"), "r", encoding="utf-8") as handle:
            gitignore_contents = handle.read()
        self.assertIn("secrets/", gitignore_contents)


class WriteRefreshTokenFileTests(unittest.TestCase):
    def test_writes_token_to_file_with_owner_only_permissions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "nested", "youtube_refresh_token.txt")

            saved_path = write_refresh_token_file("fake-refresh-token-value", output_path)

            with open(saved_path, "r", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "fake-refresh-token-value\n")

            file_mode = stat.S_IMODE(os.stat(saved_path).st_mode)
            self.assertEqual(file_mode, stat.S_IRUSR | stat.S_IWUSR)

    def test_overwrites_existing_file_instead_of_appending(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "youtube_refresh_token.txt")
            write_refresh_token_file("old-token", output_path)

            write_refresh_token_file("new-token", output_path)

            with open(output_path, "r", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "new-token\n")


class MainNeverPrintsRefreshTokenTests(unittest.TestCase):
    def test_successful_run_does_not_print_refresh_token_to_stdout_or_stderr(self):
        secret_token_value = "super-secret-refresh-token-xyz"

        def fake_request_device_code(client_id, scope):
            return {
                "device_code": "ddd",
                "user_code": "ABCD-EFGH",
                "verification_url": "https://www.google.com/device",
                "expires_in": 1800,
                "interval": 5,
            }

        def fake_poll_for_token(client_id, client_secret, device_code, interval, expires_in):
            return {"refresh_token": secret_token_value, "access_token": "fake-access-token"}

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "youtube_refresh_token.txt")
            captured_stdout = StringIO()
            captured_stderr = StringIO()

            with mock.patch(
                "scripts.youtube_oauth_setup.request_device_code", side_effect=fake_request_device_code
            ), mock.patch(
                "scripts.youtube_oauth_setup.poll_for_token", side_effect=fake_poll_for_token
            ), contextlib.redirect_stdout(captured_stdout), contextlib.redirect_stderr(captured_stderr):
                exit_code = main(
                    ["--client-id", "cid", "--client-secret", "secret", "--output", output_path]
                )

            self.assertEqual(exit_code, 0)
            self.assertNotIn(secret_token_value, captured_stdout.getvalue())
            self.assertNotIn(secret_token_value, captured_stderr.getvalue())

            with open(output_path, "r", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), secret_token_value + "\n")


if __name__ == "__main__":
    unittest.main()
