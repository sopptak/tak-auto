#!/usr/bin/env python3
"""YouTube OAuth 2.0 최초 1회 로컬 인증(6-42) - Desktop OAuth client JSON -> refresh_token.

``scripts/youtube_oauth_setup.py``(6-26)는 의도적으로 안내/점검만 하고 네트워크를 쓰지 않는다
(그 보장을 깨지 않기 위해 실제 인증 흐름은 이 별도 스크립트에 둔다).

흐름(Google "installed app" 공식 방식, 표준 라이브러리만 사용):
    1. Google Cloud에서 받은 Desktop client JSON(``{"installed": {...}}``)을 읽는다.
    2. 127.0.0.1 임의 포트에 1회용 로컬 서버를 띄우고, PKCE(S256) + state로 인증 URL을 만든다.
    3. 기본 브라우저를 연다 - **사람이 직접** Google 계정 로그인과 YouTube 권한 승인을 한다.
    4. 브라우저가 로컬 서버로 돌아오면 code를 token으로 교환한다(refresh_token 필수).
    5. YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET / YOUTUBE_REFRESH_TOKEN을 Windows 사용자
       환경변수(HKCU\\Environment)에 저장한다 - 기존 ``YouTubeClient.from_environment()``가 그대로 읽는다.

client_id/client_secret/refresh_token/access_token 값은 어디에도 출력하지 않는다(SET/NOT_SET만).
저장소 파일이나 git에는 아무것도 쓰지 않는다.

사용 예:
    py scripts/youtube_oauth_authorize.py --client-secrets "%USERPROFILE%\\Downloads\\client_secret_....json"
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import secrets
import sys
import time
import webbrowser
from collections.abc import Callable, Mapping
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_engine.youtube_publisher import YouTubeAPIError, _safe_http_error_message  # noqa: E402

# youtube.upload: videos.insert / youtube.readonly: 업로드 후 videos.list 상태 확인(6-42 9장 위험 해소)
SCOPES = ("https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly")
AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"
ENV_NAMES = ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN")


class OAuthAuthorizeError(RuntimeError):
    """인증 흐름 실패(값을 포함하지 않는 메시지만 담는다)."""


def load_installed_client(path: Path) -> tuple[str, str]:
    """Desktop(installed) client JSON에서 (client_id, client_secret)을 읽는다."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise OAuthAuthorizeError(f"client JSON을 읽을 수 없습니다: {type(error).__name__}") from None
    inner = data.get("installed") if isinstance(data, dict) else None
    if not isinstance(inner, dict):
        raise OAuthAuthorizeError("Desktop 앱(installed) 유형 OAuth client JSON이 아닙니다.")
    client_id, client_secret = str(inner.get("client_id", "")), str(inner.get("client_secret", ""))
    if not client_id or not client_secret:
        raise OAuthAuthorizeError("client JSON에 client_id/client_secret이 없습니다.")
    return client_id, client_secret


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def build_auth_url(client_id: str, redirect_uri: str, state: str, challenge: str) -> str:
    return AUTH_URI + "?" + urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",  # refresh_token을 확실히 받기 위해
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
    })


def parse_callback(path: str, expected_state: str) -> str:
    """로컬 서버로 돌아온 요청 경로에서 code를 꺼낸다. state 불일치/거부는 실패."""
    query = parse_qs(urlparse(path).query)
    if query.get("state", [""])[0] != expected_state:
        raise OAuthAuthorizeError("state 불일치 - 이 인증 요청에서 온 응답이 아닙니다.")
    if "error" in query:
        raise OAuthAuthorizeError(f"사용자 또는 Google이 인증을 거부했습니다: {query['error'][0]}")
    code = query.get("code", [""])[0]
    if not code:
        raise OAuthAuthorizeError("응답에 authorization code가 없습니다.")
    return code


def _default_token_post(payload: Mapping[str, str]) -> Mapping[str, object]:
    request = Request(TOKEN_URI, data=urlencode(payload).encode(), headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    try:
        with urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise YouTubeAPIError(_safe_http_error_message("YouTube OAuth Code Exchange", error)) from None


def exchange_code(client_id: str, client_secret: str, code: str, redirect_uri: str, verifier: str,
                  post: Callable[[Mapping[str, str]], Mapping[str, object]] = _default_token_post) -> tuple[str, str]:
    """code -> (refresh_token, 승인된 scope 문자열)."""
    data = post({
        "code": code, "client_id": client_id, "client_secret": client_secret,
        "redirect_uri": redirect_uri, "grant_type": "authorization_code", "code_verifier": verifier,
    })
    refresh_token = str(data.get("refresh_token", "")) if isinstance(data, Mapping) else ""
    if not refresh_token:
        raise OAuthAuthorizeError("토큰 응답에 refresh_token이 없습니다(prompt=consent로 다시 시도하세요).")
    return refresh_token, str(data.get("scope", ""))


def store_user_environment(values: Mapping[str, str]) -> None:
    """Windows 사용자 환경변수(HKCU\\Environment)에 저장하고 새 프로세스가 보도록 알린다.
    명령줄 인자로 값을 넘기지 않는다(프로세스 목록 노출 방지)."""
    import ctypes
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as key:
        for name, value in values.items():
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
    HWND_BROADCAST, WM_SETTINGCHANGE, SMTO_ABORTIFHUNG = 0xFFFF, 0x001A, 0x0002
    ctypes.windll.user32.SendMessageTimeoutW(HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment", SMTO_ABORTIFHUNG, 5000, None)


def wait_for_callback(server: HTTPServer, state: str, timeout_seconds: float) -> str:
    result: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if "state=" not in self.path:  # favicon 등 관계없는 요청은 무시
                self.send_response(404)
                self.end_headers()
                return
            try:
                result["code"] = parse_callback(self.path, state)
                body, status = "TAK AUTO: YouTube 인증 완료. 이 창을 닫고 터미널로 돌아가세요.", 200
            except OAuthAuthorizeError as error:
                result["error"] = str(error)
                body, status = f"TAK AUTO: 인증 실패 - {error}", 400
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(body.encode("utf-8"))

        def log_message(self, *args) -> None:  # code가 담긴 요청 줄을 로그로 남기지 않는다
            pass

    server.RequestHandlerClass = Handler
    deadline = time.monotonic() + timeout_seconds
    while not result:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise OAuthAuthorizeError(f"{timeout_seconds:.0f}초 안에 브라우저 승인이 완료되지 않았습니다.")
        server.timeout = remaining
        server.handle_request()
    if "error" in result:
        raise OAuthAuthorizeError(result["error"])
    return result["code"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="YouTube OAuth 최초 1회 로컬 인증(Desktop client JSON)")
    parser.add_argument("--client-secrets", type=Path, required=True, help="Google Cloud에서 받은 Desktop OAuth client JSON")
    parser.add_argument("--timeout", type=float, default=900, help="브라우저 승인 대기 시간(초)")
    parser.add_argument("--no-browser", action="store_true", help="브라우저를 자동으로 열지 않는다(URL은 출력)")
    args = parser.parse_args(argv)

    try:
        client_id, client_secret = load_installed_client(args.client_secrets)
        server = HTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
        redirect_uri = f"http://127.0.0.1:{server.server_address[1]}"
        state = secrets.token_urlsafe(24)
        verifier, challenge = pkce_pair()
        url = build_auth_url(client_id, redirect_uri, state, challenge)

        print("=== YouTube OAuth 로컬 인증 ===")
        print(f"요청 권한: {', '.join(s.rsplit('/', 1)[-1] for s in SCOPES)}")
        print(f"로컬 콜백 대기: {redirect_uri} (최대 {args.timeout:.0f}초)")
        opened = False if args.no_browser else webbrowser.open(url)
        # 인증 URL에는 client_id(비밀 아님)가 들어 있다 - 브라우저가 안 열릴 때만 사람이 직접 연다.
        print("브라우저를 열었습니다. Google 계정 로그인과 YouTube 권한 승인을 진행하세요." if opened
              else f"브라우저에서 다음 URL을 여세요:\n{url}", flush=True)

        with server:
            code = wait_for_callback(server, state, args.timeout)
        refresh_token, scope = exchange_code(client_id, client_secret, code, redirect_uri, verifier)
        store_user_environment({"YOUTUBE_CLIENT_ID": client_id, "YOUTUBE_CLIENT_SECRET": client_secret, "YOUTUBE_REFRESH_TOKEN": refresh_token})
    except (OAuthAuthorizeError, YouTubeAPIError, OSError) as error:
        print(f"오류: {error}", file=sys.stderr)
        return 1

    granted = {s.rsplit("/", 1)[-1] for s in scope.split()}
    print("인증 성공.")
    print(f"승인된 권한: {', '.join(sorted(granted)) or '(응답에 없음)'}")
    for name in ENV_NAMES:
        print(f"  {name}: SET (Windows 사용자 환경변수)")
    print("값은 출력하지 않았습니다. 새로 연 터미널부터 적용됩니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
