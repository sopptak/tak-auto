#!/usr/bin/env python3
"""승인된(review_status=='approved') Shorts archive 레코드를 실제 렌더링 가능한
ShortsScript JSON 파일로 저장하는 CLI(5-29).

흐름: MEDIA archive(data/tak_media_archive.json) -> platform=="shorts" &&
generation_status=="valid" && review_status=="approved" 레코드 선택 ->
content_engine.shorts_adapter.save_approved_shorts_script()로
data/shorts_scripts/<content_id>.json 저장.

이 스크립트가 절대 하지 않는 것:
    - MP4 렌더링 (content_engine.shorts_renderer, scripts/render_youtube_short.py는
      import하지 않는다)
    - YouTube 업로드 (scripts/upload_youtube_short.py는 import하지 않는다)
    - LLM 호출 (content_engine.llm_provider는 import하지 않는다 - archive에
      이미 저장된 결과를 읽기만 한다)
    - archive/knowledge 데이터 수정 (읽기 전용)

--content-id를 생략하면 archive에서 조건을 만족하는 Shorts 전체를 처리한다
(scripts/run_media_batch.py --id의 "생략하면 전체" 관례와 동일). --content-id를
주면 그 1건에 한해 조건 미충족 시 명확한 오류(exit 1)를 반환한다.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_engine.media_archive import MediaArchiveRecord, load_archive
from content_engine.shorts_adapter import (
    ShortsAdapterError,
    save_approved_shorts_script,
    shorts_script_output_path,
)


def _is_eligible(record: MediaArchiveRecord) -> bool:
    return record.generation_status == "valid" and record.review_status == "approved"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="승인된 Shorts archive 레코드를 ShortsScript JSON 파일로 저장하는 CLI"
    )
    parser.add_argument(
        "--archive",
        type=Path,
        default=ROOT / "data" / "tak_media_archive.json",
        help="읽기 전용 MEDIA archive JSON 경로 (기본값: data/tak_media_archive.json)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "data" / "shorts_scripts",
        help="ShortsScript JSON 저장 디렉터리 (기본값: data/shorts_scripts)",
    )
    parser.add_argument(
        "--content-id",
        type=str,
        default=None,
        help="특정 content_id 1건만 대상으로 실행(선택, 기본값: 승인된 전체 Shorts)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="파일을 실제로 쓰지 않고 대상 목록과 이미 존재 여부만 보여준다.",
    )
    args = parser.parse_args(argv)

    records = load_archive(args.archive)
    shorts_records = [record for record in records if record.platform == "shorts"]

    if args.content_id:
        matches = [record for record in shorts_records if record.content_id == args.content_id]
        if not matches:
            print(
                f"오류: content_id를 찾을 수 없습니다(platform=shorts 기준): {args.content_id}",
                file=sys.stderr,
            )
            return 1
        record = matches[0]
        if record.generation_status != "valid":
            print(
                f"오류: generation_status가 'valid'가 아닙니다: {record.generation_status!r}",
                file=sys.stderr,
            )
            return 1
        if record.review_status != "approved":
            print(
                f"오류: review_status가 'approved'가 아닙니다: {record.review_status!r}",
                file=sys.stderr,
            )
            return 1
        eligible = [record]
    else:
        eligible = [record for record in shorts_records if _is_eligible(record)]
        if not eligible:
            print(
                "생성할 승인된 Shorts가 없습니다 "
                "(조건: platform=shorts, generation_status=valid, review_status=approved)."
            )
            return 0

    print(f"대상: {len(eligible)}건")

    if args.dry_run:
        for record in eligible:
            existing = shorts_script_output_path(args.output_dir, record.content_id).exists()
            print(f"[dry-run] {record.content_id} ({'이미 존재 - 건너뜀' if existing else '생성 예정'})")
        return 0

    created = 0
    skipped_existing = 0
    for record in eligible:
        output_path = shorts_script_output_path(args.output_dir, record.content_id)
        already_existed = output_path.exists()
        try:
            saved_path = save_approved_shorts_script(record, args.output_dir)
        except ShortsAdapterError as err:
            print(f"오류: {record.content_id} 변환에 실패했습니다: {err}", file=sys.stderr)
            continue

        if already_existed:
            skipped_existing += 1
            print(f"건너뜀(이미 존재): {saved_path}")
        else:
            created += 1
            print(f"저장 완료: {saved_path}")

    print(f"완료: 신규 저장 {created}건, 이미 존재해 건너뜀 {skipped_existing}건 (경로: {args.output_dir})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
