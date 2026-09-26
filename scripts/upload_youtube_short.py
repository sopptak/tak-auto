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

6-26(docs/6-26-youtube-publish-readiness.md)에서 --content-id가 주어졌을 때의
검증을 강화했다. 이전에는 supersede 여부만 다시 확인했는데(6-19), 그것만으로는
review_status가 "unreviewed"/"dismissed"인 콘텐츠나 ShortsScript가 아예 없는
콘텐츠도 업로드를 막지 못했다. --content-id를 생략한 호출(레거시/자유
업로드)은 이 검증을 전혀 거치지 않는다 - 애초에 TAK MEDIA 파이프라인과 무관한
영상을 올리는 것이 정당한 사용법이기 때문이다(docstring 상단 예시 참고).
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_engine.media_archive import MediaArchiveRecord, load_archive
from content_engine.publish_eligibility import check_content_supersede, find_production_record, format_block_message
from content_engine.shorts_adapter import shorts_script_output_path
from content_engine.youtube_publisher import (
    STATUS_UNKNOWN,
    VALID_PRIVACY_STATUSES,
    YouTubeAPIError,
    YouTubeClient,
    YouTubeConfigurationError,
    YouTubeVideoStatus,
)
from content_engine.youtube_upload_history import YouTubeUploadHistory, YouTubeUploadRecord, file_sha256


def parse_tags(raw_tags: str) -> list[str]:
    if not raw_tags:
        return []
    return [tag.strip() for tag in raw_tags.split(",") if tag.strip()]


def check_shorts_upload_eligibility(
    content_id: str,
    production_records: list[MediaArchiveRecord],
    shorts_scripts_dir: Path | str,
) -> str | None:
    """--content-id가 주어졌을 때 지금 업로드해도 되는지 판정한다(6-26 4장
    Eligibility Contract). 문제가 없으면 ``None``, 있으면 차단 사유 문자열을
    반환한다. 새 판정 로직을 만들지 않고 기존 6-19
    ``content_engine.publish_eligibility``(``find_production_record()``,
    ``check_content_supersede()``)를 그대로 재사용한다 - 이 함수는 그 결과를
    조합만 한다.

    파일을 쓰지 않는다(읽기 전용) - ``production_records``는 호출부가 한 번만
    읽어 넘긴다(다른 publish CLI들과 동일한 "스냅샷 1회 읽기" 관례).
    """
    record = find_production_record(production_records, content_id)
    if record is None:
        return f"content_id={content_id}: production archive에 이 레코드가 없습니다(ORPHAN) - 업로드하지 않습니다."
    if record.review_status != "approved":
        return (
            f"content_id={content_id}: production archive review_status가 "
            f"approved가 아닙니다({record.review_status!r}) - 업로드하지 않습니다."
        )
    if record.platform != "shorts" or record.generation_status != "valid":
        # 6-43: 검증을 통과하지 못한(invalid) 생성본이나 Shorts가 아닌 레코드는 올리지 않는다.
        return (
            f"content_id={content_id}: Shorts 업로드 대상이 아닙니다(platform={record.platform!r}, "
            f"generation_status={record.generation_status!r}) - 업로드하지 않습니다."
        )

    supersede_check = check_content_supersede(production_records, content_id)
    if supersede_check.blocked:
        return format_block_message(content_id, supersede_check)

    script_path = shorts_script_output_path(shorts_scripts_dir, content_id)
    if not script_path.exists():
        return f"content_id={content_id}: ShortsScript 파일이 없습니다({script_path}) - 업로드하지 않습니다."
    try:
        script_data = json.loads(script_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return f"content_id={content_id}: ShortsScript 파일을 읽을 수 없습니다: {error}"
    script_content_id = script_data.get("content_id") if isinstance(script_data, dict) else None
    if script_content_id != content_id:
        return (
            f"content_id={content_id}: ShortsScript 내부 content_id({script_content_id!r})가 "
            "일치하지 않습니다(CONFLICT)."
        )

    return None


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
        "--confirm-public",
        action="store_true",
        help=(
            "6-42: --privacy public은 이 플래그를 함께 줄 때만 허용한다(실수로 공개 게시되는 "
            "경로 차단). 기본값 private은 그대로다."
        ),
    )
    parser.add_argument(
        "--test-upload",
        action="store_true",
        help=(
            "6-43: content_id 없는 테스트 업로드를 명시적으로 허용한다(private 전용, upload_mode=test로 기록, "
            "성과 데이터와 연결하지 않음). 일반 운영 업로드는 --content-id/--knowledge-id가 필수다."
        ),
    )
    parser.add_argument(
        "--source-ref",
        type=str,
        default="",
        help="6-43: 테스트 업로드의 출처(예: 장면 설계 파일 경로). 사실만 적는다.",
    )
    parser.add_argument(
        "--skip-status-check",
        action="store_true",
        help="6-42: 업로드 후 processingStatus 조회(videos.list)를 건너뛴다.",
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
            "주어졌을 때만 이 파일에서 review_status==approved 여부와 superseded 여부를 "
            "다시 확인한다(6-19/6-26). 읽기 전용 - 이 스크립트는 이 파일을 쓰지 않는다."
        ),
    )
    parser.add_argument(
        "--shorts-scripts-dir",
        type=Path,
        default=ROOT / "data" / "shorts_scripts",
        help=(
            "ShortsScript JSON 디렉터리 (기본값: data/shorts_scripts). --content-id가 "
            "주어졌을 때만, 이 디렉터리에 <content_id>.json이 존재하고 내부 content_id가 "
            "일치하는지 확인한다(6-26). 읽기 전용."
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
    if args.privacy == "public" and not args.confirm_public:
        print(
            "차단: --privacy public은 --confirm-public을 함께 지정해야 합니다(6-42 공개 게시 보호).",
            file=sys.stderr,
        )
        return 1

    if bool(content_id) != bool(knowledge_id):
        print(
            "오류: --content-id와 --knowledge-id는 둘 다 지정하거나 둘 다 생략해야 합니다.",
            file=sys.stderr,
        )
        return 1

    # 6-43: 운영 업로드는 content_id로 추적 가능해야 한다. content_id 없는 업로드는
    # --test-upload(private 전용)로 명시했을 때만 허용한다. dry-run은 아무것도 올리지 않으므로 안내만 한다.
    if content_id and args.test_upload:
        print("오류: --test-upload는 content_id 없는 테스트 업로드 전용입니다(--content-id와 함께 쓸 수 없음).", file=sys.stderr)
        return 1
    if args.test_upload and args.privacy != "private":
        print("차단: --test-upload는 --privacy private에서만 허용됩니다.", file=sys.stderr)
        return 1
    if not content_id and not args.test_upload and not args.dry_run:
        print(
            "차단: content_id 없는 운영 업로드는 허용하지 않습니다(6-43). --content-id/--knowledge-id를 지정하거나, "
            "테스트라면 --test-upload를 명시하세요.",
            file=sys.stderr,
        )
        return 1
    upload_mode = "production" if content_id else "test"

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
    production_records = load_archive(args.production_archive) if content_id else []
    current_generation = ""
    if content_id:
        production_record = find_production_record(production_records, content_id)
        current_generation = (production_record.generation_id or "") if production_record else ""
    if content_id and history.is_published(content_id):
        existing = history.find_by_content_id(content_id) or {}
        print(f"안내: content_id={content_id}는 이미 YouTube 업로드 이력에 있습니다. 다시 업로드하지 않습니다.")
        print(f"기존 video_id: {existing.get('video_id', '')}")
        print(f"기존 URL: {existing.get('url', '')}")
        uploaded_generation = str(existing.get("generation_id") or "")
        if uploaded_generation and current_generation and uploaded_generation != current_generation:
            # 6-43: 같은 content_id의 다른 생성본 - 자동 재업로드/덮어쓰기 금지. 정정본은 기존
            # supersede 절차(새 content_id로 승격 후 옛 레코드 superseded)로만 올린다.
            print(
                f"차단: 업로드된 generation_id={uploaded_generation}와 현재 Production generation_id="
                f"{current_generation}가 다릅니다. 같은 content_id로 다시 올리지 않습니다 - 정정본은 "
                "supersede 절차로 새 content_id를 만들어 올리세요."
            )
            return 1
        return 0

    # 6-43: 같은 MP4(sha256)가 이미 올라갔다면 content_id가 달라도(또는 없어도) 다시 올리지 않는다.
    artifact_sha256 = file_sha256(video_path)
    same_artifact = history.find_by_artifact(artifact_sha256)
    if same_artifact is not None:
        print(
            f"차단: 같은 MP4가 이미 업로드되어 있습니다(video_id={same_artifact.get('video_id', '')}, "
            f"content_id={same_artifact.get('content_id') or '(없음)'}). 다른 content_id로 다시 올리지 않습니다."
        )
        return 1

    # 6-19/6-26: --content-id가 주어졌을 때만 Production Archive/ShortsScript를
    # 다시 확인한다("ShortsScript/MP4가 이미 만들어져 있으니 지금도 유효하다"는
    # 가정을 하지 않는다) - approved 여부, superseded 여부, ShortsScript
    # 존재/일치까지 전부 확인한다(6-26 Eligibility Contract). --content-id를
    # 생략한 기존 호출(레거시/자유 업로드)은 판단 근거가 없으므로 이 검사를
    # 건너뛰고 기존과 동일하게 동작한다.
    if content_id:
        block_reason = check_shorts_upload_eligibility(content_id, production_records, args.shorts_scripts_dir)
        if block_reason:
            print(f"차단: {block_reason}")
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
        live_note = "" if content_id or args.test_upload else " (live 실행은 --content-id 또는 --test-upload가 필요 - 지금 설정으로는 차단됨)"
        print(f"upload_mode: {upload_mode}{live_note}")
        print(f"generation_id: {current_generation or '(없음)'}")
        print(f"artifact_sha256: {artifact_sha256[:16]}...")
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

    # 6-42: 업로드 직후 제한된 횟수만 processingStatus를 확인한다. 조회 실패(예: OAuth
    # 범위가 youtube.upload뿐이라 videos.list가 거부됨)는 업로드 성공을 되돌리지 않는다 -
    # UNKNOWN으로 기록하고 이력 저장은 계속한다.
    processing_status = ""
    upload_status = ""
    failure_reason = ""
    last_checked_at = ""
    # 상태 조회는 best-effort다 - 조회 기능이 없는 클라이언트(테스트용 대역 등)는 건너뛴다.
    wait_for_processing = getattr(client, "wait_for_processing", None)
    if not args.skip_status_check and wait_for_processing is not None:
        try:
            status = wait_for_processing(result.video_id)
            if not isinstance(status, YouTubeVideoStatus):
                raise ValueError(f"상태 조회 결과 형식이 올바르지 않습니다: {type(status).__name__}")
            processing_status = status.processing_status or STATUS_UNKNOWN
            upload_status = status.upload_status
            failure_reason = status.failure_reason
            last_checked_at = datetime.now(timezone.utc).isoformat()
            print(f"확인: found={status.found} privacy={status.privacy_status} "
                  f"upload={status.upload_status} processing={processing_status}")
            if status.found and status.title != clean_title:
                print(f"경고: YouTube에 저장된 제목이 요청과 다릅니다: {status.title!r}", file=sys.stderr)
            if status.found and status.privacy_status != args.privacy:
                print(f"경고: 요청한 공개 상태({args.privacy})와 실제({status.privacy_status})가 다릅니다.", file=sys.stderr)
        except (YouTubeAPIError, ValueError) as status_err:
            processing_status = STATUS_UNKNOWN
            print(f"경고: 업로드는 성공했지만 처리 상태 조회에 실패했습니다: {status_err}", file=sys.stderr)

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
                processing_status=processing_status,
                generation_id=current_generation,
                upload_mode=upload_mode,
                artifact_sha256=artifact_sha256,
                source_ref=args.source_ref.strip(),
                upload_status=upload_status,
                processing_failure_reason=failure_reason,
                last_checked_at=last_checked_at,
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
