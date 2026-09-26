#!/usr/bin/env python3
"""이미 업로드된 YouTube 영상의 처리 상태를 다시 조회해 publish log에 기록한다(6-43 lifecycle).

videos.list(part=snippet,status,processingDetails) **조회만** 한다 - 업로드/공개 상태 변경/삭제를
하지 않는다. 지정한 video_id만 조회한다(대량 호출 없음). 식별 필드는 바꾸지 않고
privacy_status/upload_status/processing_status/processing_failure_reason/last_checked_at만 갱신한다.

사용 예:
    py scripts/refresh_youtube_status.py --video-id RAZ3E4UBj6E
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_engine.youtube_publisher import (  # noqa: E402
    STATUS_UNKNOWN,
    YouTubeAPIError,
    YouTubeClient,
    YouTubeConfigurationError,
)
from content_engine.youtube_upload_history import (  # noqa: E402
    YouTubeUploadHistory,
    YouTubeUploadHistoryError,
    lifecycle_state,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="YouTube 처리 상태 재확인(조회 전용)")
    parser.add_argument("--video-id", action="append", required=True, help="조회할 video_id(여러 번 지정 가능)")
    parser.add_argument("--history", type=Path, default=ROOT / "data" / "youtube_publish_log.json")
    args = parser.parse_args(argv)

    history = YouTubeUploadHistory(args.history)
    known = {r.get("video_id") for r in history.load()}
    unknown = [v for v in args.video_id if v not in known]
    if unknown:  # 이력에 없는 영상은 조회하지 않는다(이 저장소가 올린 영상만 추적)
        print(f"오류: publish log에 없는 video_id입니다: {unknown}", file=sys.stderr)
        return 1
    try:
        client = YouTubeClient.from_environment()
    except YouTubeConfigurationError as error:
        print(f"설정 오류: {error}", file=sys.stderr)
        return 1

    exit_code = 0
    for video_id in args.video_id:
        checked_at = datetime.now(timezone.utc).isoformat()
        try:
            status = client.get_video_status(video_id)
        except YouTubeAPIError as error:
            print(f"{video_id}: 조회 실패 - {error}", file=sys.stderr)
            exit_code = 1
            continue
        if not status.found:
            fields = {"processing_failure_reason": "videos.list에서 찾을 수 없음(삭제/권한 없음 가능)", "last_checked_at": checked_at}
            exit_code = 1
        else:
            fields = {
                "privacy_status": status.privacy_status,
                "upload_status": status.upload_status,
                "processing_status": status.processing_status or STATUS_UNKNOWN,
                "processing_failure_reason": status.failure_reason,
                "last_checked_at": checked_at,
            }
        try:
            record = history.update_record(video_id, fields)
        except YouTubeUploadHistoryError as error:
            print(f"{video_id}: 기록 실패 - {error}", file=sys.stderr)
            return 1
        print(f"{video_id}: found={status.found} privacy={record.get('privacy_status')} upload={record.get('upload_status')} "
              f"processing={record.get('processing_status')} lifecycle={lifecycle_state(record)}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
