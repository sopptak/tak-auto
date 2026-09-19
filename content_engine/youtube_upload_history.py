"""YouTube Shorts 업로드 이력 저장소.

content_engine.publish_history의 원자적(atomic) JSON append 패턴을 그대로 따르되,
Threads 전용 필드(content_id, knowledge_id 등)에 의존하지 않는 독립 모듈이다.
기존 publish_history.py/threads_publish_log.json은 전혀 수정하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import tempfile
from typing import Any


DEFAULT_HISTORY_FILENAME = "youtube_publish_log.json"


class YouTubeUploadHistoryError(ValueError):
    """업로드 이력 파일이 없거나 예상한 JSON 구조와 다를 때 발생한다."""


@dataclass(frozen=True)
class YouTubeUploadRecord:
    """업로드 이력 한 건. 실제 업로드 성공 후에만 생성되어야 한다."""

    video_id: str
    uploaded_at: str
    title: str
    privacy_status: str
    video_path: str = ""
    tags: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "video_id": self.video_id,
            "uploaded_at": self.uploaded_at,
            "title": self.title,
            "privacy_status": self.privacy_status,
            "video_path": self.video_path,
            "tags": list(self.tags),
            "url": f"https://youtu.be/{self.video_id}",
        }


class YouTubeUploadHistory:
    """``data/youtube_publish_log.json``에 업로드 이력을 저장하고 조회하는 저장소."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def load(self) -> list[dict[str, Any]]:
        """이력 파일을 읽는다. 파일이 없거나 비어 있으면 빈 목록을 반환한다."""
        if not self.path.exists():
            return []
        raw_text = self.path.read_text(encoding="utf-8").strip()
        if not raw_text:
            return []
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError as error:
            raise YouTubeUploadHistoryError(
                f"업로드 이력 파일이 올바른 JSON이 아닙니다: {self.path}"
            ) from error
        if not isinstance(data, list) or not all(isinstance(record, dict) for record in data):
            raise YouTubeUploadHistoryError(
                f"업로드 이력 파일은 객체 목록(list) 구조여야 합니다: {self.path}"
            )
        return data

    def append(self, record: YouTubeUploadRecord) -> None:
        """이력을 한 건 추가하고 파일에 원자적으로(atomic) 저장한다."""
        records = self.load()
        records.append(record.to_dict())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=self.path.parent, delete=False
        ) as handle:
            json.dump(records, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            temp_path = Path(handle.name)
        temp_path.replace(self.path)
