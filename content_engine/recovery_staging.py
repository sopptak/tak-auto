"""Recovery Staging / Reconciliation - 외부(예: 다른 PC) 운영 데이터를 실제
Production Archive에 반영하기 전에 먼저 비교·검증·보고만 하는 읽기 전용
계층(6-22, docs/6-22-recovery-staging-and-reconciliation.md).

설계 원칙(6-22 지시 3장):

    SOURCE -> STAGING -> VALIDATION -> RECONCILIATION -> REPORT
    -> HUMAN APPROVAL -> EXPLICIT APPLY

이 모듈은 REPORT까지만 구현한다. HUMAN APPROVAL/EXPLICIT APPLY는 이 저장소
어디에도 구현하지 않았다(6-22 지시 0장/10장 - "실제 Production Archive를
복구하거나 GitHub에 운영 데이터를 추가하지 않는다") - 향후 설계만
docs/6-22-recovery-staging-and-reconciliation.md 9장에 문서화한다.

이 모듈의 모든 함수는 순수 함수이거나 읽기 전용이다 - 어떤 파일도 쓰지
않는다. ``data/`` 아래 실제 운영 파일을 기본 대상으로 삼지 않는다 - 항상
호출부가 명시한 ``source_dir``만 검사한다(6-22 지시 4장 "사용자가 명시한
source path를 받아 검사하는 구조를 우선하라").

상태 판정(NOT_PRESENT/EMPTY/VALID/CORRUPTED)은 6-21에서 정의되고 6-22가
``content_engine/data_state.py``로 공유 모듈화한 것을 그대로 재사용한다 -
이 모듈에서 새로 정의하지 않는다.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .data_state import CORRUPTED, EMPTY, NOT_PRESENT, VALID, dir_status, format_mtime, json_file_status
from .media_archive import (
    ArchiveConflictError,
    MediaArchiveError,
    MediaArchiveRecord,
    check_promotion_conflict,
)
from .threads_review import ThreadsPendingError, load_pending

# --- Source 레이아웃(6-22 지시 4장) ------------------------------------------
#
# 실제 data/ 운영 디렉터리와 같은 파일명 규칙을 그대로 쓴다 - 다른 PC에서
# 그 디렉터리를 통째로 복사해 온 것을 그대로 --source로 가리킬 수 있게
# 하기 위함이다. 새 규칙을 만들지 않는다.
ARCHIVE_FILENAME = "tak_media_archive.json"
THREADS_PENDING_FILENAME = "tak_threads_pending.json"
KNOWLEDGE_FILENAME = "tak_brain_knowledge.json"
GENERATION_POOL_GLOB = "tak_media_generation_*.json"
SHORTS_SCRIPTS_DIRNAME = "shorts_scripts"
# blog_drafts/는 이 코드베이스 어떤 스크립트도 생성하지 않는 디렉터리다
# (6-21 조사 결과, docs/6-21-data-sync-and-recovery-architecture.md 14장).
# 존재하지 않는 개념에 대해 스키마를 새로 만들지 않고, 파일 수준 상태만
# 확인한다(아래 ``inspect_blog_drafts()`` 참고).
BLOG_DRAFTS_DIRNAME = "blog_drafts"


def sha256_of(path: Path | str) -> str | None:
    """파일 내용의 SHA256 hex digest를 반환한다. 파일이 없으면 ``None``.

    내용을 통째로 메모리에 올리지만(현재 운영 데이터 규모 - 수십~수백KB -
    에서는 문제없다), 절대 그 내용을 반환하거나 출력하지 않는다 - 해시값만
    돌려준다(6-22 지시 11장 "원본 확인용 metadata만 관리").
    """
    target = Path(path)
    if not target.exists() or not target.is_file():
        return None
    digest = hashlib.sha256()
    digest.update(target.read_bytes())
    return digest.hexdigest()


# --- 5장: Source 파일 수준 검사 ----------------------------------------------


@dataclass(frozen=True)
class SourceFileInfo:
    """source 디렉터리 안의 파일 1건에 대한 읽기 전용 메타데이터(6-22 지시 5장).

    파일 내용은 어디에도 보존하지 않는다 - ``sha256``/``record_count``만으로
    "같은 파일인가/다른 내용인가"를 식별한다.
    """

    name: str
    path: Path
    status: str  # NOT_PRESENT / EMPTY / VALID / CORRUPTED
    size_bytes: int | None
    sha256: str | None
    record_count: int | None
    top_level_type: str | None  # "list" / "dict" / None
    mtime: str

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "path": str(self.path),
            "status": self.status,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "record_count": self.record_count,
            "top_level_type": self.top_level_type,
            "mtime": self.mtime,
        }


def inspect_source_file(path: Path, name: str) -> SourceFileInfo:
    status, record_count = json_file_status(path)
    top_level_type: str | None = None
    if status == VALID:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = None
        if isinstance(data, list):
            top_level_type = "list"
        elif isinstance(data, dict):
            top_level_type = "dict"
    return SourceFileInfo(
        name=name,
        path=path,
        status=status,
        size_bytes=path.stat().st_size if path.exists() else None,
        sha256=sha256_of(path),
        record_count=record_count,
        top_level_type=top_level_type,
        mtime=format_mtime(path),
    )


@dataclass(frozen=True)
class SourceDirInfo:
    """source 디렉터리 안의 디렉터리형 산출물(shorts_scripts/, blog_drafts/) 상태."""

    name: str
    path: Path
    status: str  # NOT_PRESENT / EMPTY / VALID / CORRUPTED
    file_count: int | None
    mtime: str

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "path": str(self.path),
            "status": self.status,
            "file_count": self.file_count,
            "mtime": self.mtime,
        }


def inspect_source_dir(path: Path, name: str, glob: str = "*.json") -> SourceDirInfo:
    status, count = dir_status(path, glob)
    return SourceDirInfo(name=name, path=path, status=status, file_count=count, mtime=format_mtime(path))


@dataclass(frozen=True)
class SourceInventory:
    """source 디렉터리 1건의 전체 파일 목록 스냅샷(6-22 지시 4장)."""

    source_dir: Path
    archive: SourceFileInfo
    knowledge: SourceFileInfo
    threads_pending: SourceFileInfo
    generation_pool_files: tuple[SourceFileInfo, ...]
    shorts_scripts: SourceDirInfo
    blog_drafts: SourceDirInfo


def discover_source(source_dir: Path | str) -> SourceInventory:
    """``source_dir`` 하나를 대상으로 알려진 6개 운영 데이터 위치를 읽기 전용으로
    조사한다. ``data/`` 운영 디렉터리를 기본값으로 쓰지 않는다 - 호출부가 항상
    명시적으로 넘겨야 한다."""
    root = Path(source_dir)
    generation_pool_files = tuple(
        inspect_source_file(p, p.name) for p in sorted(root.glob(GENERATION_POOL_GLOB))
    )
    return SourceInventory(
        source_dir=root,
        archive=inspect_source_file(root / ARCHIVE_FILENAME, ARCHIVE_FILENAME),
        knowledge=inspect_source_file(root / KNOWLEDGE_FILENAME, KNOWLEDGE_FILENAME),
        threads_pending=inspect_source_file(root / THREADS_PENDING_FILENAME, THREADS_PENDING_FILENAME),
        generation_pool_files=generation_pool_files,
        shorts_scripts=inspect_source_dir(root / SHORTS_SCRIPTS_DIRNAME, SHORTS_SCRIPTS_DIRNAME),
        blog_drafts=inspect_source_dir(root / BLOG_DRAFTS_DIRNAME, BLOG_DRAFTS_DIRNAME),
    )


# --- 6장: Production Archive 심층 검증 ---------------------------------------
#
# A~M 오류 코드(6-22 지시 6장). B/C/D/F/필수필드(content_id/knowledge_id)는
# MediaArchiveRecord.__post_init__(content_engine/media_archive.py)가 이미
# 검증하므로 그 예외 메시지를 그대로 분류해서 재사용한다(새 규칙을 만들지
# 않는다) - A/E/G/J만 이 모듈이 새로 검사한다(archive 전체를 놓고 보는 교차
# 레코드 검사이거나, 기존 어디에도 없던 검사이기 때문).

_SCHEMA_ERROR_CLASSIFIERS: tuple[tuple[str, str], ...] = (
    ("content_id가 필요합니다", "MISSING_CONTENT_ID"),
    ("knowledge_id가 필요합니다", "MISSING_KNOWLEDGE_ID"),
    ("generation_status는", "C_INVALID_GENERATION_STATUS"),
    ("review_status는", "B_INVALID_REVIEW_STATUS"),
    ("superseded_by(대체한 새 content_id)가 반드시 있어야", "D_SUPERSEDED_WITHOUT_TARGET"),
    ("superseded_by가 설정된 레코드는 review_status가", "D_INCONSISTENT_SUPERSEDE_FLAG"),
    ("자기 자신의 content_id일 수 없습니다", "F_SELF_SUPERSEDE"),
)


def _classify_schema_error(message: str) -> str:
    for needle, code in _SCHEMA_ERROR_CLASSIFIERS:
        if needle in message:
            return code
    return "UNKNOWN_SCHEMA_ERROR"


@dataclass(frozen=True)
class ArchiveIssue:
    """Production Archive(또는 generation pool) 레코드 1건 또는 archive 전체
    수준의 검증 실패 1건."""

    index: int  # 레코드의 원본 배열 인덱스. 레코드 단위가 아니면 -1.
    content_id: str | None
    code: str  # 6-22 지시 6장의 A~M(+세부 코드) 중 하나
    message: str

    def to_dict(self) -> dict[str, object]:
        return {"index": self.index, "content_id": self.content_id, "code": self.code, "message": self.message}


@dataclass(frozen=True)
class ArchiveValidationReport:
    """Production Archive 1건에 대한 전체 검증 결과."""

    path: Path
    status: str  # NOT_PRESENT(M) / EMPTY(L) / VALID / CORRUPTED(K)
    record_count: int | None
    issues: tuple[ArchiveIssue, ...]
    records: tuple[MediaArchiveRecord, ...]  # 구조적으로 유효한 레코드만

    def to_dict(self) -> dict[str, object]:
        return {
            "path": str(self.path),
            "status": self.status,
            "record_count": self.record_count,
            "issues": [issue.to_dict() for issue in self.issues],
        }


def validate_production_archive(path: Path | str) -> ArchiveValidationReport:
    """Production Archive 파일 1건을 A~M 오류 체계에 따라 검증한다.

    파일 자체가 없거나(M)/비어있거나(L)/손상됐으면(K) 그 상태만 보고하고
    레코드 단위 검사는 하지 않는다 - 검사할 레코드가 없기 때문이다.
    """
    target = Path(path)
    status, count = json_file_status(target)
    if status != VALID:
        return ArchiveValidationReport(path=target, status=status, record_count=count, issues=(), records=())

    raw = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        issue = ArchiveIssue(
            index=-1,
            content_id=None,
            code="INVALID_CONTAINER_TYPE",
            message="production archive는 JSON 배열(list)이어야 합니다.",
        )
        return ArchiveValidationReport(path=target, status=CORRUPTED, record_count=count, issues=(issue,), records=())

    issues: list[ArchiveIssue] = []
    parsed: list[MediaArchiveRecord] = []
    for index, item in enumerate(raw):
        item_content_id = item.get("content_id") if isinstance(item, dict) else None
        try:
            record = MediaArchiveRecord.from_dict(item)
        except MediaArchiveError as error:
            issues.append(
                ArchiveIssue(
                    index=index,
                    content_id=item_content_id,
                    code=_classify_schema_error(str(error)),
                    message=str(error),
                )
            )
            continue
        parsed.append(record)

    # A: duplicate content_id
    counts: dict[str, int] = {}
    for record in parsed:
        counts[record.content_id] = counts.get(record.content_id, 0) + 1
    for content_id, occurrences in counts.items():
        if occurrences > 1:
            issues.append(
                ArchiveIssue(
                    index=-1,
                    content_id=content_id,
                    code="A_DUPLICATE_CONTENT_ID",
                    message=f"content_id={content_id!r}가 archive에 {occurrences}번 나타납니다.",
                )
            )

    # 마지막 레코드 기준 lookup(중복은 위에서 이미 A로 별도 보고했으므로,
    # 여기서는 E/G/J 검사를 위한 "대표 레코드 1건" 조회 용도로만 쓴다).
    by_content_id = {record.content_id: record for record in parsed}

    for index, record in enumerate(parsed):
        # E: superseded_by가 존재하지 않는 대상을 가리킴 / J: 대상과 필드 불일치
        if record.superseded_by:
            target_record = by_content_id.get(record.superseded_by)
            if target_record is None:
                issues.append(
                    ArchiveIssue(
                        index=index,
                        content_id=record.content_id,
                        code="E_DANGLING_SUPERSEDED_BY",
                        message=(
                            f"superseded_by={record.superseded_by!r}가 archive에 존재하지 않습니다."
                        ),
                    )
                )
            else:
                mismatched = [
                    field_name
                    for field_name, a, b in (
                        ("knowledge_id", record.knowledge_id, target_record.knowledge_id),
                        ("platform", record.platform, target_record.platform),
                        ("source_url", record.source_url, target_record.source_url),
                    )
                    if a != b
                ]
                if mismatched:
                    issues.append(
                        ArchiveIssue(
                            index=index,
                            content_id=record.content_id,
                            code="J_SUPERSEDE_PAIR_MISMATCH",
                            message=(
                                f"superseded_by={record.superseded_by!r} 레코드와 "
                                f"{'/'.join(mismatched)}가 다릅니다(6-17 supersede 정책 위반)."
                            ),
                        )
                    )

        # G: approved인데 필수 필드(제목/본문/source_url) 없음
        if record.review_status == "approved":
            missing = [
                label
                for label, value in (
                    ("title", record.final_title),
                    ("body", record.final_body),
                    ("source_url", record.source_url),
                )
                if not (value or "").strip()
            ]
            if missing:
                issues.append(
                    ArchiveIssue(
                        index=index,
                        content_id=record.content_id,
                        code="G_APPROVED_MISSING_REQUIRED_FIELD",
                        message=f"review_status=approved인데 다음 필드가 비어 있습니다: {', '.join(missing)}",
                    )
                )

    return ArchiveValidationReport(path=target, status=VALID, record_count=count, issues=tuple(issues), records=tuple(parsed))


# --- 7장: Generation Pool 검증 ------------------------------------------------


@dataclass(frozen=True)
class GenerationPoolItem:
    """generation pool 레코드 1건을 production archive와 비교한 결과."""

    file: Path
    content_id: str
    generation_id: str | None
    record: MediaArchiveRecord
    comparison: str  # PRODUCTION_MATCH / GENERATION_ONLY / CONTENT_ID_CONFLICT / SOURCE_URL_MISMATCH
    detail: str

    def to_dict(self) -> dict[str, object]:
        return {
            "file": str(self.file),
            "content_id": self.content_id,
            "generation_id": self.generation_id,
            "comparison": self.comparison,
            "detail": self.detail,
        }


def validate_generation_pool_file(
    path: Path | str, archive_records: Sequence[MediaArchiveRecord]
) -> tuple[list[GenerationPoolItem], list[ArchiveIssue]]:
    """generation pool 파일 1건을 production archive 레코드들과 대조한다.

    - I(동일 content_id + 동일 generation 중복): 정상 pool 파일은
      ``(content_id, generation_id)`` 복합 키로 upsert되므로 원래는 발생할 수
      없지만(``upsert_generation_archive()``), 외부에서 수기 편집/손상된 파일을
      recovery source로 가져올 가능성이 있으므로 원본 JSON 배열 단계에서
      직접 중복을 센다.
    - H(동일 content_id + 다른 generation 충돌): 기존 6-18
      ``check_promotion_conflict()``를 그대로 호출해서 판정한다(새 정책을
      만들지 않는다) - production에 이미 다른 generation_id로 존재하면
      ``ArchiveConflictError``가 발생하고, 이를 ``CONTENT_ID_CONFLICT``로
      기록한다.
    """
    target = Path(path)
    status, _ = json_file_status(target)
    if status != VALID:
        return [], []

    raw = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        return [], [
            ArchiveIssue(
                index=-1,
                content_id=None,
                code="INVALID_CONTAINER_TYPE",
                message=f"generation pool 파일은 JSON 배열(list)이어야 합니다: {target}",
            )
        ]

    pair_counts: dict[tuple[str, str | None], int] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        key = (str(item.get("content_id") or ""), item.get("generation_id"))
        pair_counts[key] = pair_counts.get(key, 0) + 1

    file_issues: list[ArchiveIssue] = []
    for (content_id, generation_id), occurrences in pair_counts.items():
        if occurrences > 1:
            file_issues.append(
                ArchiveIssue(
                    index=-1,
                    content_id=content_id or None,
                    code="I_DUPLICATE_CONTENT_GENERATION_PAIR",
                    message=(
                        f"(content_id={content_id!r}, generation_id={generation_id!r})가 "
                        f"이 generation pool 파일에 {occurrences}번 나타납니다."
                    ),
                )
            )

    parsed: list[MediaArchiveRecord] = []
    for item in raw:
        try:
            parsed.append(MediaArchiveRecord.from_dict(item))
        except MediaArchiveError as error:
            file_issues.append(
                ArchiveIssue(
                    index=-1,
                    content_id=item.get("content_id") if isinstance(item, dict) else None,
                    code=_classify_schema_error(str(error)),
                    message=str(error),
                )
            )

    archive_by_content_id = {record.content_id: record for record in archive_records}

    items: list[GenerationPoolItem] = []
    for record in parsed:
        existing = archive_by_content_id.get(record.content_id)
        try:
            check_promotion_conflict(existing, record)
        except ArchiveConflictError as error:
            items.append(
                GenerationPoolItem(
                    file=target,
                    content_id=record.content_id,
                    generation_id=record.generation_id,
                    record=record,
                    comparison="CONTENT_ID_CONFLICT",
                    detail=str(error),
                )
            )
            continue

        if existing is None:
            items.append(
                GenerationPoolItem(
                    file=target,
                    content_id=record.content_id,
                    generation_id=record.generation_id,
                    record=record,
                    comparison="GENERATION_ONLY",
                    detail="production archive에 이 content_id가 아직 없습니다(신규 후보).",
                )
            )
            continue

        # existing.generation_id == record.generation_id (check_promotion_conflict가
        # 예외를 던지지 않았으므로 여기 도달했다는 것 자체가 그 뜻이다) - 이미
        # 승격된 것과 동일한 generation. 그래도 source_url이 달라 보이면(정상
        # 운영에서는 content_id 계산 방식상 있을 수 없지만, 손상된 recovery
        # source를 가정한 방어적 검사) 별도로 경고한다.
        if existing.source_url != record.source_url:
            items.append(
                GenerationPoolItem(
                    file=target,
                    content_id=record.content_id,
                    generation_id=record.generation_id,
                    record=record,
                    comparison="SOURCE_URL_MISMATCH",
                    detail=(
                        f"동일 content_id/generation_id인데 source_url이 다릅니다: "
                        f"production={existing.source_url!r} vs pool={record.source_url!r}"
                    ),
                )
            )
            continue

        items.append(
            GenerationPoolItem(
                file=target,
                content_id=record.content_id,
                generation_id=record.generation_id,
                record=record,
                comparison="PRODUCTION_MATCH",
                detail="이미 production archive에 동일 generation으로 승격되어 있습니다(변경 없음).",
            )
        )

    return items, file_issues


# --- 8장: Downstream reconciliation ------------------------------------------
#
# 상태 이름은 6-22 지시 8장이 그대로 명시한 8개를 쓴다: MATCH/MISSING_PRODUCTION/
# SUPERSEDED/APPROVED/UNREVIEWED/DISMISSED/CONTENT_ID_CONFLICT/INVALID.
#
# 이 중 SUPERSEDED/APPROVED/UNREVIEWED/DISMISSED는 production archive에서
# 찾은 레코드의 review_status를 그대로 반영한 "1차 상태"다(REVIEW_STATUSES,
# content_engine.media_archive와 정확히 동일한 4개 값이라 이 네 개만으로
# review_status가 있는 모든 경우를 남김없이 덮는다). MATCH는 review_status
# 축과는 별개로, downstream artifact가 자체적으로 들고 있는 필드(source_url
# 등)가 production 레코드와 실제로 일치하는지를 나타내는 **부가 정보**
# (``field_consistency``)로 둔다 - review_status 네 가지와 겹치지 않는
# 다섯 번째 "정상" 카테고리를 억지로 만들지 않기 위한 설계 결정이다(자세한
# 근거는 docs/6-22-recovery-staging-and-reconciliation.md 7장 참고).
MISSING_PRODUCTION = "MISSING_PRODUCTION"
SUPERSEDED = "SUPERSEDED"
APPROVED = "APPROVED"
UNREVIEWED = "UNREVIEWED"
DISMISSED = "DISMISSED"
CONTENT_ID_CONFLICT = "CONTENT_ID_CONFLICT"
INVALID = "INVALID"
MATCH = "MATCH"
MISMATCH = "MISMATCH"

_REVIEW_STATUS_TO_RECONCILIATION_STATUS = {
    "superseded": SUPERSEDED,
    "approved": APPROVED,
    "unreviewed": UNREVIEWED,
    "dismissed": DISMISSED,
}

DOWNSTREAM_STATUSES = (
    MATCH,
    MISSING_PRODUCTION,
    SUPERSEDED,
    APPROVED,
    UNREVIEWED,
    DISMISSED,
    CONTENT_ID_CONFLICT,
    INVALID,
)


@dataclass(frozen=True)
class DownstreamReconciliationItem:
    artifact_type: str  # "threads" | "shorts"
    artifact_path: str
    content_id: str | None
    status: str
    field_consistency: str | None  # MATCH / MISMATCH / None(해당 없음)
    reasons: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        return {
            "artifact_type": self.artifact_type,
            "artifact_path": self.artifact_path,
            "content_id": self.content_id,
            "status": self.status,
            "field_consistency": self.field_consistency,
            "reasons": list(self.reasons),
        }


def _duplicate_content_ids(records: Sequence[MediaArchiveRecord]) -> frozenset[str]:
    counts: dict[str, int] = {}
    for record in records:
        counts[record.content_id] = counts.get(record.content_id, 0) + 1
    return frozenset(cid for cid, n in counts.items() if n > 1)


def reconcile_threads_pending(
    path: Path | str, archive_records: Sequence[MediaArchiveRecord]
) -> list[DownstreamReconciliationItem]:
    """Threads pending draft 각각이 가리키는 content_id를 Production Archive와
    대조한다. ``content_engine.threads_review.load_pending()``을 그대로
    재사용한다(새 파서를 만들지 않는다)."""
    status, _ = json_file_status(path)
    if status != VALID:
        return []

    try:
        drafts = list(load_pending(path))
    except ThreadsPendingError as error:
        return [
            DownstreamReconciliationItem(
                artifact_type="threads",
                artifact_path=str(path),
                content_id=None,
                status=INVALID,
                field_consistency=None,
                reasons=(f"threads pending 파일을 파싱할 수 없습니다: {error}",),
            )
        ]

    duplicate_ids = _duplicate_content_ids(archive_records)
    by_content_id = {record.content_id: record for record in archive_records}

    items: list[DownstreamReconciliationItem] = []
    for draft in drafts:
        if not draft.content_id:
            items.append(
                DownstreamReconciliationItem(
                    artifact_type="threads",
                    artifact_path=str(path),
                    content_id=None,
                    status=INVALID,
                    field_consistency=None,
                    reasons=("content_id가 비어 있습니다.",),
                )
            )
            continue
        if draft.content_id in duplicate_ids:
            items.append(
                DownstreamReconciliationItem(
                    artifact_type="threads",
                    artifact_path=str(path),
                    content_id=draft.content_id,
                    status=CONTENT_ID_CONFLICT,
                    field_consistency=None,
                    reasons=("production archive에 이 content_id가 중복 존재합니다(A).",),
                )
            )
            continue
        record = by_content_id.get(draft.content_id)
        if record is None:
            items.append(
                DownstreamReconciliationItem(
                    artifact_type="threads",
                    artifact_path=str(path),
                    content_id=draft.content_id,
                    status=MISSING_PRODUCTION,
                    field_consistency=None,
                    reasons=(
                        "production archive에 이 content_id 레코드가 없습니다(orphan - "
                        "기존 정책상 차단 대상 아님, content_engine.publish_eligibility 참고).",
                    ),
                )
            )
            continue
        consistency = MATCH if record.source_url == draft.source_url else MISMATCH
        reasons = () if consistency == MATCH else ("source_url이 production archive 레코드와 다릅니다.",)
        items.append(
            DownstreamReconciliationItem(
                artifact_type="threads",
                artifact_path=str(path),
                content_id=draft.content_id,
                status=_REVIEW_STATUS_TO_RECONCILIATION_STATUS[record.review_status],
                field_consistency=consistency,
                reasons=reasons,
            )
        )
    return items


def reconcile_shorts_scripts(
    dir_path: Path | str, archive_records: Sequence[MediaArchiveRecord]
) -> list[DownstreamReconciliationItem]:
    """``shorts_scripts/<content_id>.json`` 각 파일이 가리키는 content_id를
    Production Archive와 대조한다(6-22 지시 8장). 파일명(``<content_id>.json``,
    ``content_engine.shorts_adapter.shorts_script_output_path()``의 관례)과
    파일 내부 ``content_id`` 필드가 일치하는지도 함께 확인한다."""
    status, _ = dir_status(dir_path, "*.json")
    if status not in (VALID,):
        return []

    duplicate_ids = _duplicate_content_ids(archive_records)
    by_content_id = {record.content_id: record for record in archive_records}

    items: list[DownstreamReconciliationItem] = []
    for file_path in sorted(Path(dir_path).glob("*.json")):
        stem = file_path.stem
        try:
            raw = json.loads(file_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            items.append(
                DownstreamReconciliationItem(
                    artifact_type="shorts",
                    artifact_path=str(file_path),
                    content_id=None,
                    status=INVALID,
                    field_consistency=None,
                    reasons=("JSON을 파싱할 수 없습니다.",),
                )
            )
            continue

        internal_content_id = raw.get("content_id") if isinstance(raw, dict) else None
        if not internal_content_id or internal_content_id != stem:
            items.append(
                DownstreamReconciliationItem(
                    artifact_type="shorts",
                    artifact_path=str(file_path),
                    content_id=internal_content_id,
                    status=INVALID,
                    field_consistency=None,
                    reasons=(
                        f"파일명({stem})과 내부 content_id({internal_content_id!r})가 일치하지 않습니다.",
                    ),
                )
            )
            continue

        content_id = stem
        if content_id in duplicate_ids:
            items.append(
                DownstreamReconciliationItem(
                    artifact_type="shorts",
                    artifact_path=str(file_path),
                    content_id=content_id,
                    status=CONTENT_ID_CONFLICT,
                    field_consistency=None,
                    reasons=("production archive에 이 content_id가 중복 존재합니다(A).",),
                )
            )
            continue

        record = by_content_id.get(content_id)
        if record is None:
            items.append(
                DownstreamReconciliationItem(
                    artifact_type="shorts",
                    artifact_path=str(file_path),
                    content_id=content_id,
                    status=MISSING_PRODUCTION,
                    field_consistency=None,
                    reasons=("production archive에 이 content_id 레코드가 없습니다(orphan).",),
                )
            )
            continue

        consistency = MATCH if record.platform == "shorts" else MISMATCH
        reasons = () if consistency == MATCH else (f"production archive의 platform이 shorts가 아닙니다: {record.platform!r}",)
        items.append(
            DownstreamReconciliationItem(
                artifact_type="shorts",
                artifact_path=str(file_path),
                content_id=content_id,
                status=_REVIEW_STATUS_TO_RECONCILIATION_STATUS[record.review_status],
                field_consistency=consistency,
                reasons=reasons,
            )
        )
    return items


# --- 9장: Reconciliation Report ----------------------------------------------


@dataclass(frozen=True)
class RecoveryReconciliationReport:
    source_dir: Path
    inventory: SourceInventory
    archive_report: ArchiveValidationReport
    generation_items: tuple[GenerationPoolItem, ...]
    generation_issues: tuple[ArchiveIssue, ...]
    threads_items: tuple[DownstreamReconciliationItem, ...]
    shorts_items: tuple[DownstreamReconciliationItem, ...]
    conflicts: int
    warnings: int
    action: str  # NO_SOURCE_ARCHIVE / BLOCKED / REVIEW_REQUIRED / OK

    def to_dict(self) -> dict[str, object]:
        return {
            "source_dir": str(self.source_dir),
            "archive": self.archive_report.to_dict(),
            "generation_pool": {
                "items": [item.to_dict() for item in self.generation_items],
                "issues": [issue.to_dict() for issue in self.generation_issues],
            },
            "threads": [item.to_dict() for item in self.threads_items],
            "shorts": [item.to_dict() for item in self.shorts_items],
            "conflicts": self.conflicts,
            "warnings": self.warnings,
            "action": self.action,
        }


_CONFLICT_CODES = frozenset(
    {
        "A_DUPLICATE_CONTENT_ID",
        "E_DANGLING_SUPERSEDED_BY",
        "F_SELF_SUPERSEDE",
        "J_SUPERSEDE_PAIR_MISMATCH",
        "I_DUPLICATE_CONTENT_GENERATION_PAIR",
        "INVALID_CONTAINER_TYPE",
        "MISSING_CONTENT_ID",
        "MISSING_KNOWLEDGE_ID",
        "B_INVALID_REVIEW_STATUS",
        "C_INVALID_GENERATION_STATUS",
        "D_SUPERSEDED_WITHOUT_TARGET",
        "D_INCONSISTENT_SUPERSEDE_FLAG",
        "UNKNOWN_SCHEMA_ERROR",
    }
)
# G(approved인데 필수 필드 없음)는 데이터 무결성 문제이지 구조적 충돌이
# 아니므로 conflict가 아니라 warning으로 집계한다.


def build_reconciliation_report(source_dir: Path | str) -> RecoveryReconciliationReport:
    """``source_dir`` 하나에 대해 DISCOVER -> VALIDATE -> COMPARE 전체를 수행해
    보고서를 만든다. 이 함수는 어떤 파일도 쓰지 않는다."""
    root = Path(source_dir)
    inventory = discover_source(root)
    archive_report = validate_production_archive(inventory.archive.path)

    generation_items: list[GenerationPoolItem] = []
    generation_issues: list[ArchiveIssue] = []
    for gen_file in inventory.generation_pool_files:
        items, issues = validate_generation_pool_file(gen_file.path, archive_report.records)
        generation_items.extend(items)
        generation_issues.extend(issues)

    threads_items = tuple(reconcile_threads_pending(inventory.threads_pending.path, archive_report.records))
    shorts_items = tuple(reconcile_shorts_scripts(inventory.shorts_scripts.path, archive_report.records))

    conflicts = sum(1 for issue in archive_report.issues if issue.code in _CONFLICT_CODES)
    conflicts += sum(1 for issue in generation_issues if issue.code in _CONFLICT_CODES)
    conflicts += sum(1 for item in generation_items if item.comparison == "CONTENT_ID_CONFLICT")
    conflicts += sum(1 for item in threads_items if item.status == CONTENT_ID_CONFLICT)
    conflicts += sum(1 for item in shorts_items if item.status == CONTENT_ID_CONFLICT)

    warnings = sum(1 for issue in archive_report.issues if issue.code == "G_APPROVED_MISSING_REQUIRED_FIELD")
    warnings += sum(1 for item in generation_items if item.comparison == "SOURCE_URL_MISMATCH")
    warnings += sum(1 for item in threads_items if item.status == INVALID or item.field_consistency == MISMATCH)
    warnings += sum(1 for item in shorts_items if item.status == INVALID or item.field_consistency == MISMATCH)

    if archive_report.status == NOT_PRESENT:
        action = "NO_SOURCE_ARCHIVE"
    elif archive_report.status == CORRUPTED:
        action = "BLOCKED"
    elif conflicts > 0:
        action = "REVIEW_REQUIRED"
    elif warnings > 0:
        action = "REVIEW_REQUIRED"
    else:
        action = "OK"

    return RecoveryReconciliationReport(
        source_dir=root,
        inventory=inventory,
        archive_report=archive_report,
        generation_items=tuple(generation_items),
        generation_issues=tuple(generation_issues),
        threads_items=threads_items,
        shorts_items=shorts_items,
        conflicts=conflicts,
        warnings=warnings,
        action=action,
    )


def render_report_text(report: RecoveryReconciliationReport) -> str:
    """6-22 지시 9장 예시 형식과 같은 사람이 읽는 요약을 만든다. 이 함수는 파일을
    쓰지 않는다 - CLI가 필요하면 stdout에 print만 한다."""
    lines = [
        "RECOVERY RECONCILIATION",
        "",
        "Source:",
        str(report.source_dir),
        "",
        "Archive:",
        report.archive_report.status,
    ]
    if report.archive_report.record_count is not None:
        lines.append(f"{report.archive_report.record_count} records")
    lines += [
        "",
        "Generation pool files:",
        str(len(report.inventory.generation_pool_files)),
        "Generation pool records reconciled:",
        str(len(report.generation_items)),
        "",
        "Threads:",
        str(len(report.threads_items)),
        "",
        "Shorts:",
        str(len(report.shorts_items)),
        "",
        "Blog drafts:",
        report.inventory.blog_drafts.status
        + " (이 코드베이스는 blog_drafts/를 생성하지 않음 - 파일 수준만 확인)",
        "",
        "Conflicts:",
        str(report.conflicts),
        "",
        "Warnings:",
        str(report.warnings),
        "",
        "Action:",
        report.action,
    ]
    return "\n".join(lines)
