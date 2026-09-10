#!/usr/bin/env python3
"""네이버 RSS와 공개 게시물 본문을 TAK BRAIN RAW에 저장합니다."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from blog_importer.naver_raw import collect_naver_rss
from blog_importer.naver_rss import NaverRssError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="네이버 RSS 기반 TAK BRAIN RAW 수집")
    parser.add_argument("--url", default="https://rss.blog.naver.com/tmong2.xml", help="네이버 RSS URL")
    parser.add_argument("--limit", type=int, default=10, help="가져올 최대 게시물 수")
    parser.add_argument("--timeout", type=float, default=20.0, help="HTTP timeout(초)")
    parser.add_argument("--output", default=str(ROOT / "data" / "tak_brain_raw.json"), help="로컬 RAW 출력 파일")
    args = parser.parse_args(argv)
    if args.limit < 1:
        parser.error("--limit은 1 이상이어야 합니다.")

    try:
        report = collect_naver_rss(args.url, args.output, args.limit, args.timeout)
    except (NaverRssError, OSError, ValueError) as error:
        print(f"수집 오류: {error}", file=sys.stderr)
        return 1

    print(f"전체: {report.total}")
    print(f"신규: {report.new}")
    print(f"중복: {report.duplicate}")
    print(f"본문 full: {report.full}")
    print(f"본문 partial: {report.partial}")
    print(f"본문 실패: {report.failed}")
    print(f"위험 flag: {report.risk_flags}")
    print(f"오류: {report.errors}")
    print(f"RAW 저장: {args.output}")
    if report.sample_titles:
        print("제목 샘플(최대 3개):")
        for title in report.sample_titles:
            print(f"- {title}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
