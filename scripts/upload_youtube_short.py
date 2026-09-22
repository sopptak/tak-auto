#!/usr/bin/env python3
"""완성된 9:16 MP4 Shorts 영상을 YouTube Data API v3로 업로드하는 CLI.

흐름: 완성된 MP4 -> 제목 -> 설명 -> 해시태그 -> YouTube Shorts 업로드 -> 업로드 결과 기록.

이 스크립트는 "YouTube 자동 업로드"만 책임진다. 영상 생성(TAK MEDIA), TAK BRAIN,
Threads 게시 로직은 전혀 import하거나 수정하지 않는다.

사용 예:
    python scripts/upload_youtube_short.py \\
        --video data/shorts/short_001.mp4 \\
        --title "60대 이후에도 꼭 곁에 두어야 할 진짜 인연 5가지" \\
        --description "티몽의 지혜..." \\
        --tags "인간관계,인생,명언,채근담,티몽의지혜" \\
        --privacy private

--content-id/--knowledge-id(6-02, 선택)를 함께 주면 이 업로드가 나중에 성과
데이터(content_engine/performance/)와 원본 KNOWLEDGE로 연결된다. 생략하면 기존과
완전히 동일하게 동작한다(legacy 업로드 이력은 이 값 없이 저장되며, 이후에도
억지로 채워지지 않는다).

최초 1회 OAuth 인증은 scripts/youtube_oauth_setup.py로 진행한다 (docs 참고).
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_engine.media_archive import load_archive
from content_engine.publish_eligibility import check_content_supersede, format_block_message
from content_engine.youtube_publisher import (
    VALID_PRIVACY_STATUSES,
    YouTubeAPIError,
    YouTubeClient,
    YouTubeConfigurationError,
)
from content_engine.youtube_upload_history import YouTubeUploadHistory, YouTubeUploadRecord


def parse_tags(raw_tags: str) -> list[str]:
    if not raw_tags:
        return []
    return [tag.strip() for tag in raw_tags.split(",") if tag.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="YouTube Shorts 업로드 CLI (YouTube Data API v3, OAuth 2.0)"
    )
    parser.add_argument("--video", type=Path, required=True, help="업로드할 9:16 MP4 파일 경로")
    parser.add_argument("--title", type=str, required=True, help="영상 제목 (최대 100자)")
    parser.add_argument("--description", type=str, default="", help="영상 설명")
    parser.add_argument(
        "--tags",
        type=str,
        default="",
        help="쉼표(,)로 구분한 해시태그/키워드 목록 (예: \"인간관계,인생,명언\")",
    )
    parser.add_argument(
        "--privacy",
        type=str,
        choices=VALID_PRIVACY_STATUSES,
        default="private",
        help="공개 상태 (기본값: private)",
    )
    parser.add_argument(
        "--category-id",
        type=str,
        default="22",
        help="YouTube 카테고리 ID (기본값: 22 = People & Blogs)",
    )
    parser.add_argument(
        "--history",
        type=Path,
        default=ROOT / "data" / "youtube_publish_log.json",
        help="업로드 이력 JSON 경로 (기본값: data/youtube_publish_log.json)",
    )
    parser.add_argument(
        "--content-id",
        type=str,
        default="",
        help="MEDIA archive/성과 데이터와 연결할 content_id (6-02, 선택 - --knowledge-id와 함께 지정해야 함)",
    )
    parser.add_argument(
        "--knowledge-id",
        type=str,
        default="",
        help="원본 KNOWLEDGE ID (6-02, 선택 - --content-id와 함께 지정해야 함)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="실제 YouTube API를 호출하지 않고 업로드 예정 내용만 확인합니다.",
    )
    parser.add_argument(
        "--production-archive",
        type=Path,
        default=ROOT / "data" / "tak_media_archive.json",
        help=(
            "Production Archive 경로 (기본값: data/tak_media_archive.json). --content-id가 "
            "주어졌을 때만 이 파일에서 현재 review_status를 다시 확인해, superseded된 "
            "레코드는 업로드를 차단한다(6-19). 읽기 전용 - 이 스크립트는 이 파일을 쓰지 않는다."
        ),
    )
    args = parser.parse_args(argv)

    tags = parse_tags(args.tags)
    video_path = args.video
    content_id = args.content_id.strip()
    knowledge_id = args.knowledge_id.strip()

    # 6-02: 둘 중 하나만 주면 이후 성과 데이터가 절반만 연결된 채로 저장되어(예:
    # content_id는 있는데 knowledge_id가 없어 어느 KNOWLEDGE에서 나왔는지 못 찾음)
    # 조용히 잘못된 데이터가 쌓인다 - 이걸 막기 위해 "둘 다 주거나 둘 다 생략"만
    # 허용한다(PerformanceRecord가 둘 다 필수로 요구하는 것과 동일한 규칙).
    # 둘 다 생략하면(기존 사용자의 기존 명령) 이전과 완전히 동일하게 동작한다 -
    # backward compatibility가 깨지지 않는다.
    if bool(content_id) != bool(knowledge_id):
        print(
            "오류: --content-id와 --knowledge-id는 둘 다 지정하거나 둘 다 생략해야 합니다.",
            file=sys.stderr,
        )
        return 1

    if not video_path.exists():
        print(f"오류: 영상 파일을 찾을 수 없습니다: {video_path}", file=sys.stderr)
        return 1
    if video_path.suffix.lower() != ".mp4":
        print(f"오류: 영상 파일은 .mp4여야 합니다: {video_path}", file=sys.stderr)
        return 1

    clean_title = args.title.strip()
    if not clean_title:
        print("오류: --title이 비어 있습니다.", file=sys.stderr)
        return 1
    if len(clean_title) > 100:
        print(f"오류: YouTube title exceeds 100 characters: {len(clean_title)}", file=sys.stderr)
        return 1

    # 6-13: content_id가 주어졌고 이미 업로드 이력에 있으면 dry-run/live 모두
    # 여기서 끝낸다 - Threads(publish_approved_threads.py)/Blog(mark_blog_published.py)와
    # 동일한 idempotency 원칙(이미 게시된 content_id는 다시 게시하지 않는다).
    # content_id를 생략한 호출(기존 사용자의 기존 명령)은 판단 근거가 없으므로
    # 이 검사를 건너뛰고 완전히 기존과 동일하게 동작한다.
    history = YouTubeUploadHistory(args.history)
    if content_id and history.is_published(content_id):
        existing = next(
            (record for record in history.load() if record.get("content_id") == content_id),
            {},
        )
        print(f"안내: content_id={content_id}는 이미 YouTube 업로드 이력에 있습니다. 다시 업로드하지 않습니다.")
        print(f"기존 video_id: {existing.get('video_id', '')}")
        print(f"기존 URL: {existing.get('url', '')}")
        return 0

    # 6-19: --content-id가 주어졌을 때만 Production Archive에서 지금 superseded
    # 상태인지 다시 확인한다("ShortsScript/MP4가 이미 만들어져 있으니 지금도
    # 유효하다"는 가정을 하지 않는다). --content-id를 생략한 기존 호출(레거시
    # 업로드)은 판단 근거가 없으므로 이 검사를 건너뛰고 기존과 동일하게 동작한다.
    if content_id:
        production_records = load_archive(args.production_archive)
        supersede_check = check_content_supersede(production_records, content_id)
        if supersede_check.blocked:
            print(format_block_message(content_id, supersede_check))
            return 1

    if args.dry_run:
        print("=== YouTube Shorts Upload (Dry-run) ===")
        print(f"영상 파일: {video_path}")
        print(f"제목: {clean_title}")
        print(f"설명: {args.description}")
        print(f"태그: {tags}")
        print(f"공개 상태: {args.privacy}")
        print(f"카테고리 ID: {args.category_id}")
        print(f"content_id: {content_id or '(없음 - 성과 데이터와 연결되지 않음)'}")
        print(f"knowledge_id: {knowledge_id or '(없음 - 성과 데이터와 연결되지 않음)'}")
        print("-" * 50)
        print("네트워크 호출 없음. 실제 업로드에는 --dry-run 없이 "
              "YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET / YOUTUBE_REFRESH_TOKEN 환경변수가 필요합니다.")
        print("Dry-run에서는 업로드 이력을 기록하지 않습니다.")
        return 0

    try:
        client = YouTubeClient.from_environment()
    except YouTubeConfigurationError as err:
        print(f"설정 오류: {err}", file=sys.stderr)
        return 1

    print(f"업로드 중: {video_path.name} (공개 상태: {args.privacy})...")
    try:
        result = client.upload_short(
            video_path=video_path,
            title=clean_title,
            description=args.description,
            tags=tags,
            privacy_status=args.privacy,
            category_id=args.category_id,
        )
    except YouTubeConfigurationError as err:
        print(f"설정 오류: {err}", file=sys.stderr)
        return 1
    except YouTubeAPIError as err:
        print(f"YouTube API 오류: {err}", file=sys.stderr)
        return 1
    except ValueError as err:
        print(f"오류: {err}", file=sys.stderr)
        return 1
    except Exception as err:
        print(f"업로드 실패: {type(err).__name__}: {err}", file=sys.stderr)
        return 1

    print(f"성공: YouTube Shorts 업로드 완료! (Video ID: {result.video_id})")
    print(f"URL: {result.url}")

    try:
        history.append(
            YouTubeUploadRecord(
                video_id=result.video_id,
                uploaded_at=datetime.now(timezone.utc).isoformat(),
                title=clean_title,
                privacy_status=args.privacy,
                video_path=str(video_path),
                tags=tuple(tags),
                content_id=content_id,
                knowledge_id=knowledge_id,
            )
        )
    except (OSError, ValueError) as history_err:
        print(
            f"경고: 업로드는 성공했지만 업로드 이력 저장에 실패했습니다: {history_err}",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
