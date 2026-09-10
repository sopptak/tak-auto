#!/usr/bin/env python3
"""공개 네이버 게시물의 본문 영역만 점검합니다. 원문은 출력하지 않습니다."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from blog_importer.naver_post import NaverPostError, fetch_public_post


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="네이버 공개 게시물 본문 영역 점검")
    parser.add_argument("--url", required=True, help="공개 네이버 게시물 URL")
    parser.add_argument("--timeout", type=float, default=20.0, help="HTTP timeout(초)")
    args = parser.parse_args(argv)
    try:
        result = fetch_public_post(args.url, timeout=args.timeout)
    except NaverPostError as error:
        print(f"게시물 오류: {error}", file=sys.stderr)
        return 1

    print(f"게시물 접근: 성공")
    print(f"페이지 HTTP 상태: {result.page_status}")
    print(f"iframe HTTP 상태: {result.frame_status or '없음'}")
    print(f"HTML 본문 영역: {'확인' if result.body else '없음'}")
    print(f"제목 확보: {'가능' if result.title else '불가'}")
    print(f"게시일 표지: {result.published_at or '없음'}")
    print(f"본문 텍스트 길이: {len(result.body)}자")
    print(f"본문 출력: 생략")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())