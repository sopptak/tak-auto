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

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Any


DEFAULT_HISTORY_FILENAME = "youtube_publish_log.json"

# 6-43: upload_mode - 이 업로드가 어떤 경로로 들어왔는가.
#   production      : --content-id(Production Archive 승인 콘텐츠)로 올린 정식 업로드
#   test            : --test-upload로 명시한 content_id 없는 테스트 업로드(항상 private)
#   legacy_unlinked : 6-43 이전 기록 중 content_id도, 테스트라는 근거도 없는 기록(추측해서 채우지 않음)
UPLOAD_MODES = ("production", "test", "legacy_unlinked")

# 6-43: publish lifecycle. 기록은 업로드 성공 후에만 생기므로 UPLOAD_PENDING은 "승인됐지만
# 아직 기록이 없는 콘텐츠"를 뜻하는 파생 상태다(publish_audit의 READY와 같은 의미).
UPLOAD_PENDING = "UPLOAD_PENDING"
UPLOADED = "UPLOADED"
PROCESSING = "PROCESSING"
SUCCEEDED = "SUCCEEDED"
FAILED = "FAILED"
LIFECYCLE_STATES = (UPLOAD_PENDING, UPLOADED, PROCESSING, SUCCEEDED, FAILED)

_FAILED_PROCESSING = {"failed", "terminated"}
_FAILED_UPLOAD = {"rejected", "failed", "deleted"}


def lifecycle_state(record: Mapping[str, Any]) -> str:
    """history 레코드 1건의 lifecycle 상태. YouTube 원본 값(processing_status/upload_status)을
    그대로 보존하고, 이 함수는 그 값을 해석만 한다(별도 필드에 중복 저장하지 않는다)."""
    processing = str(record.get("processing_status") or "")
    upload = str(record.get("upload_status") or "")
    if processing in _FAILED_PROCESSING or upload in _FAILED_UPLOAD:
        return FAILED
    if processing == "succeeded" or upload == "processed":
        return SUCCEEDED
    if processing in ("processing", "WAITING_PROCESSING"):
        return PROCESSING
    return UPLOADED


def file_sha256(path: Path | str) -> str:
    """MP4 등 로컬 산출물의 sha256(중복 업로드 판정 키, 6-43)."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
    # 6-43: lineage/lifecycle/중복 방지 필드(전부 선택, 과거 기록은 migration으로만 채운다).
    generation_id: str = ""
    upload_mode: str = ""
    artifact_sha256: str = ""
    source_ref: str = ""  # content_id가 없는 업로드의 출처(예: 장면 설계 파일 경로) - 사실만 기록
    upload_status: str = ""
    processing_failure_reason: str = ""
    last_checked_at: str = ""

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
            "generation_id": self.generation_id,
            "upload_mode": self.upload_mode,
            "artifact_sha256": self.artifact_sha256,
            "source_ref": self.source_ref,
            "upload_status": self.upload_status,
            "processing_failure_reason": self.processing_failure_reason,
            "last_checked_at": self.last_checked_at,
        }


_NEW_FIELDS_6_43 = (
    "processing_status", "generation_id", "upload_mode", "artifact_sha256", "source_ref",
    "upload_status", "processing_failure_reason", "last_checked_at",
)
_IDENTITY_FIELDS = ("video_id", "uploaded_at", "title", "url", "content_id", "knowledge_id", "video_path", "tags")


@dataclass(frozen=True)
class TestUploadAnnotation:
    """migration 시 "이 video_id는 테스트 업로드였다"는 **문서화된 근거가 있을 때만** 주는 주석.
    artifact_sha256은 실제 파일에서 계산한 값만 넣는다(추측 금지)."""

    video_id: str
    artifact_sha256: str
    source_ref: str


def migrate_history_records(
    records: list[dict[str, Any]], annotations: tuple[TestUploadAnnotation, ...] = ()
) -> list[dict[str, Any]]:
    """6-43 스키마로 옮긴 새 목록을 돌려준다(입력은 바꾸지 않음, 여러 번 실행해도 결과 동일).

    - 없는 6-43 필드는 ""로 채운다.
    - upload_mode: content_id가 있으면 production, 주석이 있으면 test, 둘 다 없으면 legacy_unlinked.
    - 식별 필드(video_id/uploaded_at/title/url/content_id/knowledge_id/video_path/tags)는 절대 바꾸지 않는다.
    - 이미 다른 값이 들어 있는 artifact_sha256/upload_mode를 덮어써야 하면 실패한다(조용한 덮어쓰기 금지).
    """
    by_video = {a.video_id: a for a in annotations}
    known = {r.get("video_id") for r in records}
    missing = sorted(set(by_video) - known)
    if missing:
        raise YouTubeUploadHistoryError(f"주석 대상 video_id가 이력에 없습니다: {missing}")
    migrated = []
    for original in records:
        record = dict(original)
        for name in _NEW_FIELDS_6_43:
            record.setdefault(name, "")
        note = by_video.get(record.get("video_id"))
        if record.get("content_id"):
            wanted_mode = "production"
        elif note is not None:
            wanted_mode = "test"
        else:
            wanted_mode = "legacy_unlinked"
        if record["upload_mode"] not in ("", wanted_mode):
            raise YouTubeUploadHistoryError(
                f"video_id={record.get('video_id')}: upload_mode가 이미 {record['upload_mode']!r}입니다({wanted_mode!r}로 바꾸지 않음)."
            )
        record["upload_mode"] = wanted_mode
        if note is not None:
            if record["artifact_sha256"] not in ("", note.artifact_sha256):
                raise YouTubeUploadHistoryError(f"video_id={note.video_id}: 기존 artifact_sha256과 다릅니다.")
            record["artifact_sha256"] = note.artifact_sha256
            record["source_ref"] = record["source_ref"] or note.source_ref
        migrated.append(record)
    validate_migration(records, migrated)
    return migrated


def validate_migration(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> None:
    """migration 후 검증: 건수/순서/식별 필드 불변, upload_mode 유효."""
    if len(before) != len(after):
        raise YouTubeUploadHistoryError(f"레코드 수가 바뀌었습니다: {len(before)} -> {len(after)}")
    for old, new in zip(before, after):
        for name in _IDENTITY_FIELDS:
            if old.get(name) != new.get(name):
                raise YouTubeUploadHistoryError(f"video_id={old.get('video_id')}: 식별 필드 {name}가 바뀌었습니다.")
        if new.get("upload_mode") not in UPLOAD_MODES:
            raise YouTubeUploadHistoryError(f"video_id={new.get('video_id')}: upload_mode가 올바르지 않습니다.")


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
        self.write_records(records)

    def find_by_content_id(self, content_id: str) -> dict[str, Any] | None:
        return next((r for r in self.load() if content_id and r.get("content_id") == content_id), None)

    def find_by_artifact(self, sha256: str) -> dict[str, Any] | None:
        """같은 MP4(sha256)가 이미 올라간 기록(6-43 - 다른 content_id로 우회 등록 방지)."""
        return next((r for r in self.load() if sha256 and r.get("artifact_sha256") == sha256), None)

    def performance_targets(self) -> list[dict[str, str]]:
        """향후 성과 수집 대상: content_id가 있는 production 업로드 중 처리 성공한 것만(6-43).
        테스트/legacy 업로드는 성과 데이터와 연결하지 않는다."""
        return [
            {key: str(r.get(key) or "") for key in ("content_id", "knowledge_id", "video_id", "uploaded_at")}
            for r in self.load()
            if r.get("content_id") and r.get("upload_mode") == "production" and lifecycle_state(r) == SUCCEEDED
        ]

    def update_record(self, video_id: str, fields: Mapping[str, Any]) -> dict[str, Any]:
        """video_id가 같은 레코드 1건의 필드만 갱신한다(6-43 상태 재확인/migration용).
        식별 필드(video_id/content_id/knowledge_id/uploaded_at/url)는 바꾸지 못한다."""
        protected = {"video_id", "content_id", "knowledge_id", "uploaded_at", "url"}
        if protected & set(fields):
            raise YouTubeUploadHistoryError(f"식별 필드는 갱신할 수 없습니다: {sorted(protected & set(fields))}")
        records = self.load()
        matches = [r for r in records if r.get("video_id") == video_id]
        if len(matches) != 1:
            raise YouTubeUploadHistoryError(f"video_id={video_id} 레코드가 {len(matches)}건입니다(정확히 1건이어야 함).")
        matches[0].update(fields)
        self.write_records(records)
        return matches[0]

    def write_records(self, records: list[dict[str, Any]]) -> None:
        """전체 목록을 원자적으로 저장한다(append/update_record/migration 공용)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=self.path.parent, delete=False
        ) as handle:
            json.dump(records, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            temp_path = Path(handle.name)
        temp_path.replace(self.path)
