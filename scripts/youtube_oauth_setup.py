#!/usr/bin/env python3
"""YouTube Data API v3 최초 1회 OAuth 2.0 인증(Refresh Token 발급) 도구.

OAuth 2.0 Device Authorization Grant(기기 흐름)를 사용한다. 이 방식을 선택한 이유:
    - Codespaces/서버 등 헤드리스(브라우저 없는) 환경에서도 동작한다.
    - 로컬 리다이렉트(redirect_uri) HTTP 서버를 띄울 필요가 없다.
    - 사용자가 아무 기기(휴대폰 등)에서 URL을 열고 코드만 입력하면 된다.

Google Cloud Console에서 OAuth 클라이언트 유형을 "TVs and Limited Input devices"로
만들어야 이 흐름을 사용할 수 있다 (docs/5-13_youtube_shorts_upload.md 참고).

발급된 refresh_token은 터미널/표준출력에 절대 출력하지 않는다(세션 로그에 값이
남는 것을 막기 위함). 대신 저장소 로컬(git 추적 제외) 파일에 값만 기록하고,
사용자가 VS Code 등으로 그 파일을 직접 열어 확인한 뒤 GitHub Codespaces Secrets
웹 화면에 수동으로 옮기는 흐름을 전제로 한다. 표준 라이브러리(urllib)만 사용한다.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEVICE_CODE_URL = "https://oauth2.googleapis.com/device/code"
TOKEN_URL = "https://oauth2.googleapis.com/token"

# refresh_token을 담는 로컬 전용 파일의 기본 경로. secrets/ 디렉터리 전체가
# .gitignore 대상이므로 git에는 절대 올라가지 않는다.
DEFAULT_OUTPUT_PATH = "secrets/youtube_refresh_token.txt"

# Device Authorization Grant(TVs and Limited Input devices)는 Google이 문서화한
# 허용 scope 목록에 youtube.upload를 포함하지 않는다 - 허용되는 것은
# https://www.googleapis.com/auth/youtube 와 .../youtube.readonly 뿐이다.
# videos.insert(업로드)는 이 전체(youtube) scope로도 정상 동작하므로, upload 전용
# scope 대신 이 값을 사용한다.
DEFAULT_SCOPE = "https://www.googleapis.com/auth/youtube"


def _post_form(url: str, fields: dict[str, str], timeout_seconds: float = 30.0) -> dict:
    data = urlencode(fields).encode("utf-8")
    request = Request(
        url,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = {"error": "http_error", "error_description": body}
        parsed["_http_status"] = error.code
        return parsed


def request_device_code(client_id: str, scope: str) -> dict:
    return _post_form(DEVICE_CODE_URL, {"client_id": client_id, "scope": scope})


def poll_for_token(client_id: str, client_secret: str, device_code: str, interval: int, expires_in: int) -> dict:
    deadline = time.monotonic() + expires_in
    while time.monotonic() < deadline:
        time.sleep(interval)
        result = _post_form(
            TOKEN_URL,
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
        )
        error = result.get("error")
        if error is None and result.get("refresh_token"):
            return result
        if error == "authorization_pending":
            print("대기 중... 아직 인증이 완료되지 않았습니다.", file=sys.stderr)
            continue
        if error == "slow_down":
            interval += 5
            continue
        if error in ("access_denied", "expired_token"):
            raise RuntimeError(f"OAuth 인증 실패: {error}")
        raise RuntimeError(f"OAuth 인증 중 알 수 없는 오류: {result}")
    raise RuntimeError("OAuth 인증 대기 시간이 초과되었습니다. 다시 시도해주세요.")


def write_refresh_token_file(refresh_token: str, output_path: str) -> str:
    """refresh_token을 소유자만 읽을 수 있는 로컬 파일에 저장하고 절대경로를 반환한다.

    파일/디렉터리를 생성과 동시에 0600/0700 권한으로 만들어, 값이 잠시라도
    다른 사용자에게 읽힐 수 있는 창구(생성 후 chmod하는 방식의 race condition)를
    없앤다.
    """
    directory = os.path.dirname(output_path) or "."
    os.makedirs(directory, exist_ok=True)
    os.chmod(directory, stat.S_IRWXU)  # 0700: 소유자만 접근 가능

    fd = os.open(output_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(fd, "w") as handle:
        handle.write(refresh_token.strip() + "\n")

    return os.path.abspath(output_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "YouTube Data API v3 최초 1회 OAuth 인증 도구 (Device Authorization Grant). "
            "발급된 refresh_token은 화면/로그에 출력하지 않고 로컬 파일(기본: "
            f"{DEFAULT_OUTPUT_PATH})에만 저장합니다."
        )
    )
    parser.add_argument(
        "--client-id",
        type=str,
        default=os.environ.get("YOUTUBE_CLIENT_ID", ""),
        help="Google Cloud Console에서 발급한 OAuth Client ID (기본값: YOUTUBE_CLIENT_ID 환경변수)",
    )
    parser.add_argument(
        "--client-secret",
        type=str,
        default=os.environ.get("YOUTUBE_CLIENT_SECRET", ""),
        help="Google Cloud Console에서 발급한 OAuth Client Secret (기본값: YOUTUBE_CLIENT_SECRET 환경변수)",
    )
    parser.add_argument("--scope", type=str, default=DEFAULT_SCOPE, help="요청할 OAuth 스코프")
    parser.add_argument(
        "--output",
        type=str,
        default=DEFAULT_OUTPUT_PATH,
        help=f"refresh_token을 저장할 로컬 파일 경로 (기본값: {DEFAULT_OUTPUT_PATH})",
    )
    args = parser.parse_args(argv)

    if not args.client_id or not args.client_secret:
        print(
            "오류: --client-id/--client-secret 또는 YOUTUBE_CLIENT_ID/YOUTUBE_CLIENT_SECRET "
            "환경변수가 필요합니다.",
            file=sys.stderr,
        )
        return 1

    device_response = request_device_code(args.client_id, args.scope)
    if device_response.get("error"):
        print(f"오류: 기기 코드 요청 실패: {device_response}", file=sys.stderr)
        return 1

    verification_url = device_response.get("verification_url") or device_response.get("verification_uri")
    user_code = device_response.get("user_code")
    device_code = device_response.get("device_code")
    interval = int(device_response.get("interval", 5))
    expires_in = int(device_response.get("expires_in", 1800))

    if not verification_url or not user_code or not device_code:
        print(f"오류: 기기 코드 응답이 올바르지 않습니다: {device_response}", file=sys.stderr)
        return 1

    print("=== YouTube OAuth 최초 인증 (Device Authorization Grant) ===")
    print(f"1) 아무 브라우저에서 다음 URL을 여세요: {verification_url}")
    print(f"2) 다음 코드를 입력하세요: {user_code}")
    print(f"3) Google 계정으로 업로드 권한({args.scope})을 승인하세요.")
    print(f"(코드는 {expires_in // 60}분 안에 만료됩니다. 승인 후 자동으로 진행됩니다...)")
    print("-" * 60)

    try:
        token_response = poll_for_token(args.client_id, args.client_secret, device_code, interval, expires_in)
    except RuntimeError as err:
        print(f"오류: {err}", file=sys.stderr)
        return 1

    refresh_token = token_response.get("refresh_token")
    if not refresh_token:
        print(
            "오류: 응답에 refresh_token이 없습니다. 이미 이 계정/클라이언트로 인증한 적이 있다면 "
            "Google 계정 권한 페이지(myaccount.google.com/permissions)에서 기존 앱 접근을 해제한 뒤 "
            "다시 시도하세요.",
            file=sys.stderr,
        )
        return 1

    saved_path = write_refresh_token_file(refresh_token, args.output)

    print("-" * 60)
    print("성공: 인증이 완료되었습니다.")
    print(f"refresh_token을 다음 로컬 파일에 저장했습니다 (권한: 소유자 전용 읽기/쓰기): {saved_path}")
    print("이 파일은 .gitignore 대상이므로 git에는 올라가지 않습니다.")
    print("-" * 60)
    print("다음 단계:")
    print(f"1) VS Code 탐색기 또는 `code {args.output}` 등으로 위 파일을 열어 값을 확인하세요.")
    print("2) GitHub 저장소 Settings → Secrets and variables → Codespaces 화면에서")
    print("   YOUTUBE_REFRESH_TOKEN Secret 값으로 그 값을 직접 붙여넣으세요.")
    print("3) 값을 옮긴 뒤에는 로컬 사본을 남겨두지 않도록 이 파일을 삭제하는 것을 권장합니다.")
    print("-" * 60)
    print("절대 이 값을 커밋하거나 공개 채널/채팅에 붙여넣지 마세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
