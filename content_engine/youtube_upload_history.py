"""YouTube Shorts 업로드 이력 저장소.

content_engine.publish_history의 원자적(atomic) JSON append 패턴을 그대로 따르되,
Threads 전용 로직(compute_content_id 계산, PublishHistory 클래스 등)에 의존하지
않는 독립 모듈이다. 기존 publish_history.py/threads_publish_log.json은 전혀
수정하지 않는다.

6-02: content_id/knowledge_id 필드를 추가했다(둘 다 기본값 ""로 optional -
과거 기록은 이 두 필드 없이 저장되어 있고, 이 모듈은 그 legacy 기록을 그대로
"연결 정보가 없는 레코드"로 취급한다. 값을 추측해서 채우지 않는다). 이 두 값은
MediaArchiveRecord/PerformanceRecord와 동일하게, 이미 compute_content_id()로
계산되어 있는 값을 호출부(scripts/upload_youtube_short.py)가 그대로 넘겨줄
뿐이다 - 이 모듈은 content_id를 스스로 계산하지 않는다.
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
    # 6-02: KNOWLEDGE/MEDIA archive와 연결하기 위한 선택적 필드. 둘 다 비어있으면
    # (기본값) "이 업로드가 어느 KNOWLEDGE에서 나왔는지 알 수 없는 legacy 기록"이라는
    # 뜻이다 - 이 값을 나중에 억지로 채우지 않는다(6-02 보고서 3장 참고).
    content_id: str = ""
    knowledge_id: str = ""
    # 6-42: 업로드 직후 videos.list로 확인한 processingDetails.processingStatus
    # (succeeded/failed/WAITING_PROCESSING/UNKNOWN 등). 과거 기록에는 없다 - 채우지 않는다.
    processing_status: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "video_id": self.video_id,
            "uploaded_at": self.uploaded_at,
            "title": self.title,
            "privacy_status": self.privacy_status,
            "video_path": self.video_path,
            "tags": list(self.tags),
            "url": f"https://youtu.be/{self.video_id}",
            "content_id": self.content_id,
            "knowledge_id": self.knowledge_id,
            "processing_status": self.processing_status,
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

    def published_content_ids(self) -> set[str]:
        """content_id가 기록된(비어있지 않은) 업로드 이력의 content_id 집합.

        content_id 없이 저장된 legacy 기록(6-02 이전, 또는 --content-id를
        생략한 업로드)은 여기 포함되지 않는다 - 그런 레코드는 애초에 어떤
        content_id와도 연결할 근거가 없으므로 중복 판정에 쓸 수 없다
        (``content_engine.publish_history.PublishHistory.published_content_ids()``
        와 동일한 관례).
        """
        return {
            record["content_id"]
            for record in self.load()
            if isinstance(record.get("content_id"), str) and record["content_id"]
        }

    def is_published(self, content_id: str) -> bool:
        """이 content_id가 이미 업로드 이력에 있는지(=이미 게시됨) 여부.

        빈 문자열/None은 항상 False다 - content_id를 지정하지 않은 업로드는
        (6-02 이전 관례대로) 중복 판정 대상이 아니다."""
        if not content_id:
            return False
        return content_id in self.published_content_ids()

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
