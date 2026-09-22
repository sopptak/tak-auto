#!/usr/bin/env python3
"""사람이 네이버 블로그에 실제로 게시를 마친 뒤, 그 사실을 로컬 이력에 기록하는 CLI.

TAK AUTO는 네이버 블로그에 자동으로 게시하지 않는다(scripts/generate_blog_publish_pack.py
참고). 사람이 Publishing Pack의 콘텐츠를 직접 복사/붙여넣기해서 네이버에 게시를 마친 뒤
이 스크립트로 content_id를 명시적으로 기록해야, 다음 scripts/generate_blog_publish_pack.py
실행에서 같은 콘텐츠가 후보에서 제외된다. content_engine.publish_history.PublishHistory/
PublishRecord를 그대로 재사용하되, Threads 이력(data/threads_publish_log.json)과는
별도 파일(기본값 data/blog_publish_log.json)에 저장한다. 실제 네이버 게시 자체는
수행하지 않는다.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from blog_importer.models import utc_now
from content_engine.publish_history import PublishHistory, PublishRecord


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="네이버 블로그에 실제로 게시를 마친 content_id를 이력에 기록"
    )
    parser.add_argument("--content-id", required=True, help="게시를 마친 content_id")
    parser.add_argument("--knowledge-id", default="", help="원본 KNOWLEDGE ID (선택)")
    parser.add_argument("--source-url", default="", help="원본 source_url (선택)")
    parser.add_argument(
        "--history",
        type=Path,
        default=ROOT / "data" / "blog_publish_log.json",
        help="Blog 게시 이력 JSON 경로 (기본값: data/blog_publish_log.json)",
    )
    args = parser.parse_args(argv)

    history = PublishHistory(args.history)
    if history.is_published(args.content_id):
        print(
            f"안내: content_id={args.content_id}는 이미 게시 이력에 있습니다. "
            "다시 기록하지 않습니다."
        )
        return 0

    try:
        history.append(
            PublishRecord(
                content_id=args.content_id,
                published_at=utc_now(),
                threads_post_id="",
                knowledge_id=args.knowledge_id,
                platform="blog",
                source_url=args.source_url,
            )
        )
    except OSError as err:
        print(f"오류: 게시 이력 저장에 실패했습니다: {err}", file=sys.stderr)
        return 1

    print(f"기록 완료: content_id={args.content_id}는 이제 Blog 게시 후보에서 제외됩니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
