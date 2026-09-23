#!/usr/bin/env python3
"""TAK MEDIA 검증 완료된 Threads 콘텐츠를 Threads 공식 API로 단건 게시하는 CLI.

6-25(docs/6-25-threads-publish-path-consolidation.md)에서 Production Archive
기반 eligibility 게이트를 추가했다. 이전에는 이 스크립트(및 이를 호출하는
``scripts/run_daily.py``)가 ``generation_status == "valid"``만 확인하고
사람의 승인(``review_status``) 여부를 전혀 확인하지 않았다 - 이제
``scripts/publish_approved_threads.py``와 같은 계약(``content_engine.publish_eligibility``)을
재사용해, Production Archive에서 해당 content_id가 ``review_status == "approved"``이고
superseded가 아닌 경우에만 게시 후보로 고려한다. 새 eligibility 로직을
따로 만들지 않았다 - 기존 5-11/6-19 코드를 그대로 호출한다.
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

from content_engine import (
    ThreadsAPIError,
    ThreadsClient,
    ThreadsConfigurationError,
)
from content_engine.media_archive import MediaArchiveRecord, load_archive
from content_engine.publish_eligibility import (
    check_content_supersede,
    find_production_record,
    format_block_message,
)
from content_engine.publish_history import (
    PublishHistory,
    PublishHistoryError,
    PublishRecord,
    compute_content_id,
    select_unpublished_threads_item,
)


def check_threads_item_eligibility(
    item: dict, production_records: list[MediaArchiveRecord]
) -> tuple[bool, str | None, str | None]:
    """이 배치 항목이 지금 발행해도 되는지 판정한다(5장 Eligibility Contract).

    반환값: ``(eligible, content_id 또는 None, 차단/오류 사유 또는 None)``.
    ``content_id`` 계산 자체가 실패하면 ``eligible=False``, ``content_id=None``.

    이 함수는 파일을 읽지 않는다(``production_records``를 호출부가 한 번만
    읽어 넘긴다 - ``scripts/publish_approved_threads.py``와 동일한 관례,
    6-19 주석 참고: "모든 draft가 같은 스냅샷을 기준으로 판정받도록").
    """
    try:
        content_id = compute_content_id(item)
    except PublishHistoryError as err:
        return False, None, str(err)

    record = find_production_record(production_records, content_id)
    if record is None:
        return (
            False,
            content_id,
            f"content_id={content_id}: production archive에 이 레코드가 없습니다 - "
            "승인 여부를 확인할 수 없어 발행하지 않습니다.",
        )
    if record.review_status != "approved":
        return (
            False,
            content_id,
            f"content_id={content_id}: production archive review_status가 "
            f"approved가 아닙니다({record.review_status!r}) - 발행하지 않습니다.",
        )

    supersede_check = check_content_supersede(production_records, content_id)
    if supersede_check.blocked:
        return False, content_id, format_block_message(content_id, supersede_check)

    return True, content_id, None


def load_valid_threads_items(input_path: Path | str) -> list[dict]:
    path = Path(input_path)
    if not path.exists():
        raise FileNotFoundError(f"입력 파일을 찾을 수 없습니다: {path}")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        raise ValueError(f"유효하지 않은 JSON 파일입니다: {err}") from err

    all_items = data.get("all_items", [])
    valid_threads = [
        item for item in all_items
        if item.get("platform") == "threads" and item.get("status") == "valid"
    ]
    return valid_threads


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TAK MEDIA Threads Publisher (단건 게시)")
    parser.add_argument(
        "--input",
        type=Path,
        default=ROOT / "data" / "tak_media_batch_e2e_test.json",
        help="배치 결과 JSON 경로 (기본값: data/tak_media_batch_e2e_test.json)",
    )
    parser.add_argument(
        "--index",
        type=int,
        default=1,
        help="게시할 Threads 콘텐츠 번호 (1-based, 기본값: 1). --auto와 함께 사용하면 무시됩니다.",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="검증 통과(valid)했지만 아직 게시하지 않은 Threads 콘텐츠 1건을 자동으로 선택합니다. --index보다 우선합니다.",
    )
    parser.add_argument(
        "--history",
        type=Path,
        default=ROOT / "data" / "threads_publish_log.json",
        help="게시 이력 JSON 경로 (기본값: data/threads_publish_log.json)",
    )
    parser.add_argument(
        "--production-archive",
        type=Path,
        default=ROOT / "data" / "tak_media_archive.json",
        help=(
            "Production Archive 경로 (기본값: data/tak_media_archive.json). 6-25: "
            "여기서 review_status == 'approved'이고 superseded가 아닌 content_id만 "
            "게시 후보로 고려합니다(scripts/publish_approved_threads.py와 동일한 계약). "
            "읽기 전용 - 이 스크립트는 이 파일을 쓰지 않습니다."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="실제 API 호출 없이 게시 예정 내용을 확인합니다.",
    )
    args = parser.parse_args(argv)

    try:
        valid_items = load_valid_threads_items(args.input)
    except (FileNotFoundError, ValueError) as err:
        print(f"오류: {err}", file=sys.stderr)
        return 1

    if not valid_items:
        print(f"알림: '{args.input}' 파일에 valid 상태의 Threads 콘텐츠가 없습니다.", file=sys.stderr)
        return 1

    history = PublishHistory(args.history)
    # 6-25: production archive는 한 번만 읽는다 - 이 실행 안의 모든 후보가 같은
    # 스냅샷을 기준으로 판정받는다(scripts/publish_approved_threads.py 6-19와 동일한 이유).
    production_records = load_archive(args.production_archive)

    if args.auto:
        eligible_items = []
        for item in valid_items:
            eligible, _content_id, reason = check_threads_item_eligibility(item, production_records)
            if eligible:
                eligible_items.append(item)
            elif reason:
                print(f"안내: 후보에서 제외 - {reason}")

        try:
            selection = select_unpublished_threads_item(eligible_items, history)
        except PublishHistoryError as err:
            print(f"오류: {err}", file=sys.stderr)
            return 1

        if selection is None:
            print(
                "게시할 콘텐츠 없음: 검증 통과(valid)하고, production archive에서 "
                "승인(approved)되고 superseded되지 않은 채, 아직 게시하지 않은 "
                "Threads 콘텐츠가 없습니다."
            )
            return 0

        target_item, content_id = selection
        selection_label = f"자동 선택 (게시 이력에 없는 첫 valid+approved 항목, content_id={content_id})"
    else:
        if args.index < 1 or args.index > len(valid_items):
            print(
                f"오류: 유효하지 않은 index입니다. (입력: {args.index}, 선택 가능 범위: 1 ~ {len(valid_items)})",
                file=sys.stderr,
            )
            return 1

        target_item = valid_items[args.index - 1]
        eligible, content_id, reason = check_threads_item_eligibility(target_item, production_records)
        if content_id is None:
            print(f"오류: {reason}", file=sys.stderr)
            return 1
        if not eligible:
            print(f"오류: {reason}", file=sys.stderr)
            return 1
        selection_label = f"[{args.index}/{len(valid_items)}] (수동 지정)"

    publish_text = (target_item.get("rewritten_body") or target_item.get("original_body") or "").strip()

    if not publish_text:
        print("오류: 게시할 텍스트 본문이 비어 있습니다.", file=sys.stderr)
        return 1

    if len(publish_text) > 500:
        print(f"오류: Threads text exceeds 500 characters: {len(publish_text)}", file=sys.stderr)
        return 1

    knowledge_id = target_item.get("knowledge_id", "unknown")
    source_url = target_item.get("source_url", "unknown")

    if args.dry_run:
        print("=== TAK MEDIA Threads Publish (Dry-run) ===")
        print(f"대상 파일: {args.input}")
        if args.auto:
            print(f"선택 항목: {selection_label} (KNOWLEDGE: {knowledge_id})")
        else:
            print(f"선택 항목: [{args.index}/{len(valid_items)}] (KNOWLEDGE: {knowledge_id})")
        print(f"출처 URL: {source_url}")
        print("-" * 50)
        print("게시 예정 내용:")
        print(publish_text)
        print("-" * 50)
        print("네트워크 호출 없음. 실제 게시에는 --dry-run 없이 THREADS_ACCESS_TOKEN 환경변수가 필요합니다.")
        print("Dry-run에서는 게시 이력을 기록하지 않습니다.")
        return 0

    try:
        client = ThreadsClient.from_environment()
        profile = client.get_profile()
        print(f"Threads 계정 확인 완료: @{profile.username} (ID: {profile.id})")
        print(f"게시 중: {selection_label} KNOWLEDGE={knowledge_id}...")

        result = client.publish_text(publish_text)
        print(f"성공: Threads 게시 완료! (Post ID: {result.id})")

        try:
            history.append(
                PublishRecord(
                    content_id=content_id,
                    published_at=datetime.now(timezone.utc).isoformat(),
                    threads_post_id=result.id,
                    knowledge_id=str(knowledge_id),
                    platform="threads",
                    source_url=str(source_url),
                )
            )
        except (PublishHistoryError, OSError) as history_err:
            print(
                f"경고: 게시는 성공했지만 게시 이력 저장에 실패했습니다: {history_err}",
                file=sys.stderr,
            )

        return 0
    except ThreadsConfigurationError as err:
        print(f"설정 오류: {err}", file=sys.stderr)
        return 1
    except ThreadsAPIError as err:
        print(f"Threads API 오류: {err}", file=sys.stderr)
        return 1
    except ValueError as err:
        print(f"오류: {err}", file=sys.stderr)
        return 1
    except Exception as err:
        print(f"게시 실패: {type(err).__name__}: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
