#!/usr/bin/env python3
"""사람이 네이버 블로그에 실제로 게시를 마친 뒤, 그 사실을 로컬 이력에 기록하는 CLI.

TAK AUTO는 네이버 블로그에 자동으로 게시하지 않는다(scripts/generate_blog_publish_pack.py
참고). 사람이 Publishing Pack의 콘텐츠를 직접 복사/붙여넣기해서 네이버에 게시를 마친 뒤
이 스크립트로 content_id를 명시적으로 기록해야, 다음 scripts/generate_blog_publish_pack.py
실행에서 같은 콘텐츠가 후보에서 제외된다. content_engine.publish_history.PublishHistory/
PublishRecord를 그대로 재사용하되, Threads 이력(data/threads_publish_log.json)과는
별도 파일(기본값 data/blog_publish_log.json)에 저장한다. 실제 네이버 게시 자체는
수행하지 않는다.

6-27(docs/6-27-blog-publish-readiness.md)에서 Production Archive 기반 안전장치를
추가했다. 이전에는 이 스크립트가 ``--content-id``로 받은 값을 전혀 검증하지 않고
그대로 이력에 기록했다 - 오타나 잘못된 값을 입력해도(또는 순서를 착각해 아직
게시하지 않은 콘텐츠를 먼저 기록해도) 아무 경고 없이 성공했고, 그 content_id는
이후 영구히 "이미 게시됨"으로 취급되어 다음 Blog Publishing Pack에서 조용히
제외됐다. 이제 content_id가 Production Archive에 존재하고 review_status==approved인
경우에만 기록을 허용한다(--content-id는 이미 필수 인자라 자유 입력을 지원할
이유가 없다 - scripts/upload_youtube_short.py의 --content-id와 달리 선택 필드가
아니다).

**이 스크립트가 여전히 할 수 없는 것**: 실제로 네이버 블로그에 게시가 됐는지는
API로 확인할 방법이 자체적으로 없다(Naver 공식 글쓰기 API 자체가 없다는 프로젝트
정책, docs/6-27-blog-publish-readiness.md 1장) - 이 스크립트는 "이 content_id가
기록해도 되는 정당한 대상인가"만 검증할 뿐, "사람이 정말로 게시를 마쳤는가"는
여전히 전적으로 사람의 신고를 신뢰한다.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from blog_importer.models import utc_now
from content_engine.media_archive import load_archive
from content_engine.publish_eligibility import find_production_record
from content_engine.publish_history import PublishHistory, PublishRecord


def check_blog_publish_confirmation_eligibility(content_id, production_records) -> str | None:
    """이 content_id를 "게시 완료"로 기록해도 되는지 판정한다(6-27). 문제 없으면
    ``None``, 있으면 차단 사유 문자열을 반환한다. 새 판정 로직이 아니라 기존
    ``content_engine.publish_eligibility.find_production_record()``(6-19)를
    재사용해 존재/승인 여부만 확인한다 - "실제 게시됐는가"는 판단하지 않는다
    (위 모듈 docstring 참고).
    """
    record = find_production_record(production_records, content_id)
    if record is None:
        return (
            f"content_id={content_id}: production archive에 이 레코드가 없습니다(ORPHAN) - "
            "게시 완료로 기록하지 않습니다."
        )
    if record.review_status != "approved":
        return (
            f"content_id={content_id}: production archive review_status가 approved가 "
            f"아닙니다({record.review_status!r}) - 게시 완료로 기록하지 않습니다."
        )
    return None


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
    parser.add_argument(
        "--production-archive",
        type=Path,
        default=ROOT / "data" / "tak_media_archive.json",
        help=(
            "Production Archive 경로 (기본값: data/tak_media_archive.json). content_id가 "
            "이 archive에 존재하고 review_status==approved인 경우에만 게시 완료로 "
            "기록한다(6-27). 읽기 전용 - 이 스크립트는 이 파일을 쓰지 않는다."
        ),
    )
    args = parser.parse_args(argv)

    history = PublishHistory(args.history)
    if history.is_published(args.content_id):
        print(
            f"안내: content_id={args.content_id}는 이미 게시 이력에 있습니다. "
            "다시 기록하지 않습니다."
        )
        return 0

    production_records = load_archive(args.production_archive)
    block_reason = check_blog_publish_confirmation_eligibility(args.content_id, production_records)
    if block_reason:
        print(f"차단: {block_reason}", file=sys.stderr)
        return 1

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
