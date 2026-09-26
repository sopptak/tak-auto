#!/usr/bin/env python3
"""사람이 실제로 네이버 블로그에 게시(예약 발행 포함)를 완료한 뒤 실행하는 CLI.

TAK AUTO는 네이버 블로그에 자동 게시하지 않으므로, Threads처럼 API 응답을 받아 자동으로
게시 이력을 기록할 방법이 없다. 이 스크립트는 사람이 실제 게시를 확인한 뒤 content_id를
Blog 게시 이력(기본값: data/blog_publish_log.json)에 직접 기록하는 최소한의 수단이다.

이 스크립트를 실행하지 않으면 같은 content_id가 다음 Blog Publishing Pack 생성에서
계속 후보로 다시 나타난다(자동으로 소진되지 않는다). 이는 의도된 동작이다: 사람이
채택하지 않은 콘텐츠까지 자동으로 "게시 완료" 처리되는 것을 막기 위함이다.

네이버 계정 로그인 정보, 비밀번호, 쿠키, access token 등은 이 스크립트에서 요구하거나
저장하지 않는다.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_engine.publish_history import PublishHistory, PublishHistoryError, PublishRecord


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="네이버 블로그에 실제 게시를 완료한 Blog 콘텐츠를 게시 이력에 기록"
    )
    parser.add_argument(
        "--content-id",
        required=True,
        help="Blog Publishing Pack에 표시된 content_id (예: content-abcd1234...)",
    )
    parser.add_argument("--knowledge-id", default="", help="원본 KNOWLEDGE ID(선택)")
    parser.add_argument("--source-url", default="", help="원본 source_url(선택)")
    parser.add_argument(
        "--post-url",
        default="",
        help="사람이 실제로 게시한 네이버 블로그 포스트 URL(선택, 기록용)",
    )
    parser.add_argument(
        "--history",
        type=Path,
        default=ROOT / "data" / "blog_publish_log.json",
        help="Blog 게시 이력 JSON 경로 (기본값: data/blog_publish_log.json)",
    )
    args = parser.parse_args(argv)

    history = PublishHistory(args.history)

    try:
        if history.is_published(args.content_id):
            print(f"안내: content_id={args.content_id}는 이미 게시 이력에 기록되어 있습니다.")
            return 0

        history.append(
            PublishRecord(
                content_id=args.content_id,
                published_at=datetime.now(timezone.utc).isoformat(),
                threads_post_id=args.post_url or "manual",
                knowledge_id=args.knowledge_id,
                platform="blog",
                source_url=args.source_url,
            )
        )
    except (PublishHistoryError, OSError) as err:
        print(f"오류: 게시 이력 기록에 실패했습니다: {err}", file=sys.stderr)
        return 1

    print(f"성공: content_id={args.content_id}를 Blog 게시 이력에 기록했습니다.")
    print(f"이력 파일: {args.history}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
