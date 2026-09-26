#!/usr/bin/env python3
"""YouTube publish log를 6-43 lineage 스키마로 옮기는 migration CLI.

순서: before snapshot(백업 + 바이트 비교) -> migration(순수 함수) -> after validation -> 원자적 저장.
어느 단계에서든 실패하면 원본 파일을 쓰지 않는다(백업은 남긴다). 여러 번 실행해도 결과가 같다.

content_id를 추측해서 채우지 않는다. content_id가 없는 기록은 문서화된 근거가 있을 때만
``--test-video`` 주석으로 test 업로드로 표시하고, 그 외에는 legacy_unlinked로 둔다.
네트워크를 쓰지 않는다.

사용 예(6-42 실제 테스트 업로드 연결):
    py scripts/migrate_youtube_publish_log.py --test-video RAZ3E4UBj6E \\
        --artifact artifacts/6-41-shorts-v2/shorts_v2_finance.mp4 \\
        --source-ref "content_engine/shorts_v2_specs/finance.json (6-41 QA 장면 설계, content_id 없음)"
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_engine.youtube_upload_history import (  # noqa: E402
    TestUploadAnnotation,
    YouTubeUploadHistory,
    YouTubeUploadHistoryError,
    file_sha256,
    migrate_history_records,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="YouTube publish log 6-43 migration(네트워크 없음)")
    parser.add_argument("--history", type=Path, default=ROOT / "data" / "youtube_publish_log.json")
    parser.add_argument("--test-video", default="", help="테스트 업로드였다는 근거가 있는 video_id(선택)")
    parser.add_argument("--artifact", type=Path, default=None, help="--test-video의 실제 업로드 MP4(sha256 계산용)")
    parser.add_argument("--source-ref", default="", help="--test-video의 출처(사실만)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    history = YouTubeUploadHistory(args.history)
    try:
        before = history.load()
        annotations: tuple[TestUploadAnnotation, ...] = ()
        if args.test_video:
            if args.artifact is None or not args.artifact.exists():
                raise YouTubeUploadHistoryError("--test-video에는 실제 존재하는 --artifact가 필요합니다.")
            annotations = (TestUploadAnnotation(args.test_video, file_sha256(args.artifact), args.source_ref.strip()),)
        after = migrate_history_records(before, annotations)
    except (OSError, YouTubeUploadHistoryError) as error:
        print(f"중단(파일 변경 없음): {error}", file=sys.stderr)
        return 1

    changed = [a.get("video_id") for b, a in zip(before, after) if a != b]
    print(f"레코드 {len(before)}건, 변경 대상 {len(changed)}건: {changed}")
    for record in after:
        print(f"  {record.get('video_id')}: upload_mode={record['upload_mode']} "
              f"content_id={record.get('content_id') or '(없음)'} artifact={'SET' if record['artifact_sha256'] else '-'}")
    if not changed:
        print("변경 없음(이미 migration 완료) - 파일을 쓰지 않습니다.")
        return 0
    if args.dry_run:
        print("dry-run: 파일을 쓰지 않았습니다.")
        return 0

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = args.history.with_name(f"{args.history.stem}.backup-6-43-{stamp}.json")
    shutil.copy2(args.history, backup)
    if backup.read_bytes() != args.history.read_bytes():
        print("중단(파일 변경 없음): 백업이 원본과 다릅니다.", file=sys.stderr)
        return 1
    history.write_records(after)
    if json.loads(args.history.read_text(encoding="utf-8")) != after:
        shutil.copy2(backup, args.history)
        print("실패: 저장 후 검증 불일치 - 백업으로 되돌렸습니다.", file=sys.stderr)
        return 1
    print(f"완료. before snapshot: {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
