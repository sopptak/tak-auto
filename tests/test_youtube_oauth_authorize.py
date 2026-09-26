"""scripts/youtube_oauth_authorize.py(6-42) 검증 - 실제 Google 인증/네트워크 없음.

로컬 콜백 서버만 127.0.0.1에서 실제로 띄워 브라우저 리다이렉트를 흉내 낸다.
토큰 교환/환경변수 저장/브라우저는 전부 가짜로 대체한다.
"""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlparse
from urllib.error import HTTPError
from urllib.request import urlopen

import scripts.youtube_oauth_authorize as auth

FAKE_ID, FAKE_SECRET, FAKE_REFRESH = "fake-client-id-123", "fake-secret-456", "fake-refresh-789"


def _client_json(tmp: Path, kind: str = "installed") -> Path:
    path = tmp / "client.json"
    path.write_text(json.dumps({kind: {"client_id": FAKE_ID, "client_secret": FAKE_SECRET}}), encoding="utf-8")
    return path


class PieceTests(unittest.TestCase):
    def test_auth_url_requests_offline_upload_and_readonly_with_pkce(self) -> None:
        query = parse_qs(urlparse(auth.build_auth_url("cid", "http://127.0.0.1:5", "st", "ch")).query)
        self.assertEqual(query["access_type"], ["offline"])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertIn("youtube.upload", query["scope"][0])
        self.assertIn("youtube.readonly", query["scope"][0])

    def test_callback_rejects_wrong_state_and_denial(self) -> None:
        with self.assertRaises(auth.OAuthAuthorizeError):
            auth.parse_callback("/?code=c&state=other", "st")
        with self.assertRaises(auth.OAuthAuthorizeError):
            auth.parse_callback("/?error=access_denied&state=st", "st")
        self.assertEqual(auth.parse_callback("/?code=c1&state=st", "st"), "c1")

    def test_exchange_requires_refresh_token(self) -> None:
        with self.assertRaises(auth.OAuthAuthorizeError):
            auth.exchange_code("i", "s", "c", "r", "v", post=lambda p: {"access_token": "a"})
        token, _ = auth.exchange_code("i", "s", "c", "r", "v", post=lambda p: {"refresh_token": "rt", "scope": "x"})
        self.assertEqual(token, "rt")

    def test_web_client_json_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(auth.OAuthAuthorizeError):
                auth.load_installed_client(_client_json(Path(tmp), kind="web"))


class FullFlowTests(unittest.TestCase):
    def test_flow_stores_three_values_and_never_prints_them(self) -> None:
        stored: dict = {}

        def browser_redirect(redirect_uri: str, callback: str) -> None:
            with contextlib.suppress(HTTPError):  # 관계없는 요청(favicon)은 404로 무시돼야 한다
                urlopen(redirect_uri + "/favicon.ico").close()
            urlopen(callback).read()

        def fake_open(url: str) -> bool:
            query = parse_qs(urlparse(url).query)
            redirect_uri = query["redirect_uri"][0]
            callback = f"{redirect_uri}/?code=abc&state={query['state'][0]}"
            threading.Thread(target=browser_redirect, args=(redirect_uri, callback)).start()
            return True

        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp,                 mock.patch.object(auth.webbrowser, "open", side_effect=fake_open),                 mock.patch.object(auth, "exchange_code", return_value=(FAKE_REFRESH, " ".join(auth.SCOPES))) as exchange,                 mock.patch.object(auth, "store_user_environment", side_effect=stored.update),                 contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = auth.main(["--client-secrets", str(_client_json(Path(tmp))), "--timeout", "20"])
        self.assertEqual(exchange.call_args.args[2], "abc")  # 콜백으로 받은 code로 교환
        self.assertEqual(code, 0, out.getvalue())
        self.assertEqual(stored, {"YOUTUBE_CLIENT_ID": FAKE_ID, "YOUTUBE_CLIENT_SECRET": FAKE_SECRET, "YOUTUBE_REFRESH_TOKEN": FAKE_REFRESH})
        for value in (FAKE_ID, FAKE_SECRET, FAKE_REFRESH):
            self.assertNotIn(value, out.getvalue())
        self.assertIn("youtube.readonly", out.getvalue())

    def test_timeout_without_approval_fails_and_stores_nothing(self) -> None:
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(auth.webbrowser, "open", return_value=True), \
                mock.patch.object(auth, "store_user_environment") as store, \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = auth.main(["--client-secrets", str(_client_json(Path(tmp))), "--timeout", "0.5"])
        self.assertEqual(code, 1)
        store.assert_not_called()


if __name__ == "__main__":
    unittest.main()
