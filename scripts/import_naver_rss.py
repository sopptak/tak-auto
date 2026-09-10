#!/usr/bin/env python3
"""네이버 RSS에서 확인 가능한 공개 메타데이터를 점검합니다."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from blog_importer.naver_rss import NaverRssError, fetch_rss, parse_rss
from tak_brain.models import build_metadata


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="네이버 RSS 공개 정보 점검")
    parser.add_argument("--url", required=True, help="네이버 RSS URL")
    parser.add_argument("--limit", type=int, default=10, help="가져올 최대 게시물 수")
    parser.add_argument("--timeout", type=float, default=20.0, help="HTTP timeout(초)")
    args = parser.parse_args(argv)
    if args.limit < 1:
        parser.error("--limit은 1 이상이어야 합니다.")

    try:
        records = parse_rss(fetch_rss(args.url, timeout=args.timeout), limit=args.limit)
    except NaverRssError as error:
        print(f"RSS 오류: {error}", file=sys.stderr)
        return 1

    complete_count = sum(record.body_is_complete for record in records)
    privacy_count = sum(build_metadata(record.post)["privacy_risk"] for record in records)
    internal_count = sum(build_metadata(record.post)["internal_information_risk"] for record in records)
    print(f"RSS 접근 성공: 예")
    print(f"발견한 게시물 수: {len(records)}")
    print(f"RSS 본문 전체 확보: {complete_count}/{len(records)}")
    print(f"개인정보 위험 수: {privacy_count}")
    print(f"내부정보 위험 수: {internal_count}")
    for index, record in enumerate(records, 1):
        post = record.post
        scope = "전체 여부 확인 필요" if not record.body_is_complete else "RSS description"
        print(f"{index:02d}. {post.title} | {post.published_at} | {post.source_url} | {scope}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())