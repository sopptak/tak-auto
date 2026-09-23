#!/usr/bin/env python3
"""YouTube Data API v3 OAuth 2.0 최초 설정 준비/검증 CLI(6-26).

이 스크립트는 실제 OAuth 인증을 수행하지 않는다 - 브라우저를 열지 않고,
Google 계정에 로그인하지 않고, 새 refresh token을 발급받지 않는다. 이
CLI가 하는 일은 정확히 두 가지뿐이다:

    1. ``--check``: 이미 설정된(또는 아직 설정되지 않은) 환경변수
       (``YOUTUBE_CLIENT_ID``/``YOUTUBE_CLIENT_SECRET``/``YOUTUBE_REFRESH_TOKEN``)의
       **존재 여부만** 확인하고, 값 자체는 절대 출력하지 않는다. 셋 다
       있으면 ``content_engine.youtube_publisher.YouTubeClient.from_environment()``로
       클라이언트를 실제로 만들어본다(이 생성 자체는 네트워크를 쓰지
       않는다 - access_token 발급은 실제 업로드/조회를 시도할 때만
       일어난다).
    2. 인자 없이 실행: refresh token을 처음 발급받는 절차를 사람이 Google
       Cloud Console에서 수동으로 진행할 수 있도록 순서를 안내한다(문서
       역할 - 이 스크립트가 그 과정을 대신 실행하지 않는다).

6-24 Production Readiness Audit(P1)에서 이 스크립트가 여러 문서(5-18,
5-31, 6-01~6-03)에 언급만 되고 실제로 구현된 적이 없다는 사실이 발견됐다 -
이번에 최초로 구현한다.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_engine.youtube_publisher import YouTubeClient, YouTubeConfigurationError

REQUIRED_ENV_VARS = ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN")

REQUIRED_SCOPE = "https://www.googleapis.com/auth/youtube.upload"

_SETUP_GUIDE = f"""\
=== YouTube OAuth 최초 설정 절차(안내 전용 - 이 스크립트가 대신 실행하지 않습니다) ===

이 저장소의 업로드 코드(content_engine/youtube_publisher.py)는 OAuth 2.0
"refresh_token" 방식만 지원합니다 - 매 실행마다 브라우저 로그인을 요구하지
않고, 발급받은 refresh_token 하나로 access_token을 계속 갱신합니다.

1. https://console.cloud.google.com 에서 프로젝트를 만들고
   "YouTube Data API v3"를 사용 설정합니다.
2. "OAuth 동의 화면"을 구성합니다(범위: {REQUIRED_SCOPE}).
3. "사용자 인증 정보 > OAuth 클라이언트 ID"를 만듭니다
   (애플리케이션 유형: "데스크톱 앱"을 권장합니다 - redirect URI 설정이
   가장 단순합니다).
4. 발급된 클라이언트 ID/보안 비밀을 각각 YOUTUBE_CLIENT_ID/
   YOUTUBE_CLIENT_SECRET로 로컬 환경에 저장합니다(.env 등 - 절대 git에
   커밋하지 마세요, .gitignore에 .env가 이미 포함되어 있습니다, 6-24/6-25).
5. 최초 1회, 사람이 직접(이 CLI가 아니라) 다음 중 하나로 refresh_token을
   발급받습니다:
     - Google이 제공하는 OAuth 2.0 Playground(https://developers.google.com/oauthplayground)
       에서 위 클라이언트 ID/보안 비밀을 등록하고 범위 {REQUIRED_SCOPE}로
       인증한 뒤 "Exchange authorization code for tokens"로 refresh_token을
       받습니다.
     - 또는 Google이 제공하는 공식 OAuth 라이브러리로 로컬 1회성 인증
       스크립트를 직접 실행합니다(이 저장소는 그런 라이브러리를 의존성으로
       추가하지 않았습니다 - content_engine/youtube_publisher.py가 표준
       라이브러리만 쓰는 원칙을 지키고 있기 때문입니다).
6. 발급받은 refresh_token을 YOUTUBE_REFRESH_TOKEN으로 저장합니다.
7. 환경변수 3개를 전부 설정한 뒤 다음을 실행해 확인합니다:
       python scripts/youtube_oauth_setup.py --check
8. 확인이 끝나면 dry-run으로 업로드 경로를 먼저 점검합니다:
       python scripts/upload_youtube_short.py --video <mp4> --title <제목> --dry-run

이 스크립트(youtube_oauth_setup.py)는 3~6단계를 대신 수행하지 않습니다 -
Google 계정 로그인이 필요한 단계는 항상 사람이 직접 진행해야 합니다.
"""


def check_environment(environ: dict | None = None) -> dict[str, bool]:
    """각 환경변수의 존재 여부(값이 비어있지 않은지)만 반환한다. 값 자체는
    절대 반환/출력하지 않는다."""
    values = os.environ if environ is None else environ
    return {name: bool(values.get(name, "").strip()) for name in REQUIRED_ENV_VARS}


def run_check(environ: dict | None = None) -> int:
    """--check: 환경변수 존재 여부 + (전부 있으면) 클라이언트 초기화 가능
    여부를 확인한다. 실제 네트워크 호출은 하지 않는다."""
    presence = check_environment(environ)

    print("=== YouTube OAuth 환경 점검(--check, 실제 API 호출 없음) ===")
    for name in REQUIRED_ENV_VARS:
        status = "SET" if presence[name] else "MISSING"
        print(f"  {name}: {status}")

    missing = [name for name, present in presence.items() if not present]
    if missing:
        print()
        print(f"부족한 환경변수: {', '.join(missing)}")
        print("값 자체는 이 스크립트가 출력하지 않습니다 - 위 안내(인자 없이 실행)를 참고해 발급하세요.")
        return 1

    print()
    try:
        YouTubeClient.from_environment(environ=environ)
    except YouTubeConfigurationError as error:
        # from_environment()는 값이 비어 있을 때만 이 예외를 던지므로(위에서
        # 이미 비어있지 않음을 확인했다) 여기 도달하는 것은 사실상
        # 일어나지 않아야 정상이다 - 그래도 방어적으로 처리한다.
        print(f"오류: API client를 초기화할 수 없습니다: {error}", file=sys.stderr)
        return 1

    print("API client 초기화 가능: YES (실제 업로드/조회는 시도하지 않았습니다)")
    print()
    print("다음 단계: python scripts/upload_youtube_short.py --video <mp4> --title <제목> --dry-run")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "YouTube OAuth 최초 설정 준비/검증 CLI. 실제 OAuth 인증은 수행하지 않는다 - "
            "환경변수 존재 여부 확인(--check)과 설정 절차 안내만 한다."
        )
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="환경변수 존재 여부와 API client 초기화 가능 여부만 확인한다(값은 출력하지 않음, 네트워크 호출 없음).",
    )
    args = parser.parse_args(argv)

    if args.check:
        return run_check()

    print(_SETUP_GUIDE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
