"""Explicit Apply Guard + 원자적 apply(6-23 지시 6장·7장,
docs/6-23-recovery-review-and-approval-gate.md).

이 모듈이 실제로 production archive에 쓰는 **유일한** 경로다. 절대 원칙:

    - approval은 여기서 만들지 않는다 - 호출부(CLI)가 사람이 명시한
      ``--approve <content_id>`` 목록을 그대로 전달해야 한다(5장: "자동
      approval 금지"). 이 모듈은 그 목록을 신뢰하지 않고 매번 다시
      검증한다(가드 조건 5/6/7/8/11/12).
    - downstream artifact(Threads pending, Shorts scripts, Blog drafts)는
      이 모듈이 **전혀 건드리지 않는다** - production archive 1개 파일만
      쓴다. "자동 삭제 금지, 자동 publish 금지"(6-23 지시 12장) 원칙을
      아예 그 파일들을 import/참조하지 않는 방식으로 구조적으로 지킨다.
    - 실제 쓰기는 ``content_engine.media_archive.upsert_archive()``(6-06)를
      그대로 재사용한다 - 새 쓰기 메커니즘(원자성 포함)을 만들지 않는다.
      이 모듈이 새로 추가하는 것은 "쓰기 전 가드"와 "쓰기 후 검증+롤백"
      뿐이다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
import tempfile

from .data_state import CORRUPTED, VALID
from .media_archive import MediaArchiveRecord, upsert_archive
from .recovery_decision import ALREADY_PRESENT, BLOCKED, CONFLICT, INVALID, RecoveryReport, SAFE_TO_REVIEW
from .recovery_staging import validate_production_archive


@dataclass(frozen=True)
class ApplyGuardFailure:
    check: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"check": self.check, "message": self.message}


@dataclass(frozen=True)
class ApplyGuardResult:
    passed: bool
    failures: tuple[ApplyGuardFailure, ...]
    approved_records: tuple[MediaArchiveRecord, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "failures": [f.to_dict() for f in self.failures],
            "approved_content_ids": [r.content_id for r in self.approved_records],
        }


def evaluate_apply_guard(
    report: RecoveryReport,
    approved_content_ids: Sequence[str],
    *,
    expected_source_sha256: dict[str, str | None] | None = None,
) -> ApplyGuardResult:
    """6-23 지시 6장의 12개 조건을 전부 검사한다. 하나라도 실패하면
    ``passed=False``와 함께 전부(중단하지 않고) 모아서 반환한다 - 사람이
    한 번에 무엇을 고쳐야 하는지 볼 수 있도록.

    이 함수는 파일을 읽거나 쓰지 않는다(``report``에 이미 로드된 정보만
    쓴다) - 순수 함수다.
    """
    failures: list[ApplyGuardFailure] = []

    # 1. source validation PASS
    if report.source_archive.status != VALID:
        failures.append(
            ApplyGuardFailure("source_validation", f"source archive 상태가 VALID가 아닙니다: {report.source_archive.status}")
        )
    if report.source_archive.issues:
        failures.append(
            ApplyGuardFailure(
                "source_validation", f"source archive에 {len(report.source_archive.issues)}건의 검증 오류가 있습니다."
            )
        )

    # 2. reconciliation 완료 - report 객체가 전달됐다는 것 자체가 완료를 뜻한다(추가 검사 불필요).

    # 3. conflict 0 (report 전체)
    conflict_candidates = [c for c in report.candidates if c.status == CONFLICT]
    if conflict_candidates:
        failures.append(
            ApplyGuardFailure("conflict_zero", f"CONFLICT 상태 후보가 {len(conflict_candidates)}건 있습니다 - 전부 해결해야 합니다.")
        )

    # 4. invalid 0
    invalid_candidates = [c for c in report.candidates if c.status == INVALID]
    if invalid_candidates:
        failures.append(
            ApplyGuardFailure("invalid_zero", f"INVALID 상태 후보가 {len(invalid_candidates)}건 있습니다 - 전부 해결해야 합니다.")
        )

    # 5. human approval 명시 / 11. apply 대상 명시
    approved_set = list(dict.fromkeys(approved_content_ids))  # 순서 보존 중복 제거
    if not approved_set:
        failures.append(ApplyGuardFailure("explicit_approval", "승인된 content_id가 하나도 없습니다(--approve 필요)."))

    candidates_by_content_id: dict[str, list] = {}
    for candidate in report.candidates:
        candidates_by_content_id.setdefault(candidate.content_id, []).append(candidate)

    approved_records: list[MediaArchiveRecord] = []
    for content_id in approved_set:
        matches = candidates_by_content_id.get(content_id, [])
        if not matches:
            failures.append(
                ApplyGuardFailure(
                    "explicit_approval", f"승인된 content_id={content_id!r}가 이번 reconciliation 후보 목록에 없습니다."
                )
            )
            continue
        if len(matches) > 1:
            failures.append(
                ApplyGuardFailure(
                    "unambiguous_target",
                    f"content_id={content_id!r}에 대해 서로 다른 generation 후보가 {len(matches)}건 있어 "
                    "무엇을 적용할지 모호합니다 - 사람이 먼저 하나로 정리해야 합니다.",
                )
            )
            continue

        decision = matches[0]

        # 6. 기존 production overwrite 없음 / 7. same content_id conflict 없음
        if decision.status != SAFE_TO_REVIEW:
            failures.append(
                ApplyGuardFailure(
                    "safe_status_only",
                    f"content_id={content_id!r}의 상태가 SAFE_TO_REVIEW가 아닙니다: {decision.status} - "
                    "이 도구는 신규 추가(ADD)만 적용하며, 기존 production 레코드를 덮어쓰지 않습니다.",
                )
            )
            # 8. superseded resurrection 없음(BLOCKED로 이미 위에서 걸리지만, 사유를 명확히 별도로도 남긴다)
            if decision.status == BLOCKED:
                failures.append(
                    ApplyGuardFailure(
                        "no_resurrection", f"content_id={content_id!r}는 BLOCKED 상태(superseded resurrection 위험)입니다."
                    )
                )
            continue

        if decision.record is None:
            failures.append(
                ApplyGuardFailure("record_missing", f"content_id={content_id!r}의 후보 레코드를 찾을 수 없습니다.")
            )
            continue

        approved_records.append(decision.record)

    # 9. source SHA256 확인(검토 시점 스냅샷과 지금 다시 계산한 값이 같은지)
    if expected_source_sha256 is not None:
        for name, expected_hash in expected_source_sha256.items():
            actual = report.source_sha256.get(name)
            if actual != expected_hash:
                failures.append(
                    ApplyGuardFailure(
                        "sha256_drift",
                        f"{name}의 SHA256이 검토 시점과 다릅니다(source가 그 사이 바뀌었을 수 있습니다) - "
                        "다시 검토해야 합니다.",
                    )
                )

    # 10. 대상 Production Archive 존재 여부/무결성 확인
    if report.target_archive.status == CORRUPTED:
        failures.append(
            ApplyGuardFailure("target_archive_integrity", "target production archive가 CORRUPTED 상태입니다 - 자동으로 덮어쓰지 않습니다.")
        )

    # 12. dry-run 결과와 apply 대상 동일성 확인은 apply_recovery() 호출 직전에
    # 별도로 report를 다시 만들어 비교하는 방식으로 수행한다(아래
    # reevaluate_before_apply() 참고) - 여기서는 스냅샷 검증(9번)까지만.

    return ApplyGuardResult(passed=not failures, failures=tuple(failures), approved_records=tuple(approved_records))


def reevaluate_before_apply(
    build_report_fn,
    source_dir: Path,
    target_archive_path: Path,
    previously_approved_content_ids: Sequence[str],
) -> ApplyGuardFailure | None:
    """12번 조건("dry-run 결과와 apply 대상 동일성 확인") 전용 - apply 직전에
    ``build_report_fn(source_dir, target_archive_path)``으로 보고서를 다시
    만들어, 승인했던 content_id들이 여전히 ``SAFE_TO_REVIEW``인지 재확인한다.
    문제가 없으면 ``None``, 있으면 실패 사유를 반환한다.
    """
    fresh_report = build_report_fn(source_dir, target_archive_path)
    fresh_by_content_id = {c.content_id: c for c in fresh_report.candidates}
    for content_id in previously_approved_content_ids:
        fresh_decision = fresh_by_content_id.get(content_id)
        if fresh_decision is None or fresh_decision.status != SAFE_TO_REVIEW:
            return ApplyGuardFailure(
                "reconciliation_drift",
                f"content_id={content_id!r}의 재검증 결과가 검토 시점과 다릅니다"
                f"(지금 상태: {fresh_decision.status if fresh_decision else '후보 목록에서 사라짐'}) - "
                "apply 직전에 다시 REPORT를 확인하세요.",
            )
    return None


@dataclass(frozen=True)
class MediaArchiveApplyResult:
    success: bool
    written_content_ids: tuple[str, ...]
    rolled_back: bool
    message: str

    def to_dict(self) -> dict[str, object]:
        return {
            "success": self.success,
            "written_content_ids": list(self.written_content_ids),
            "rolled_back": self.rolled_back,
            "message": self.message,
        }


def _atomic_write_bytes(target: Path, content: bytes) -> None:
    """``content_engine.media_archive.save_archive()``와 동일한 tempfile +
    ``Path.replace()`` 관례로 원시 bytes를 원자적으로 쓴다(롤백 복원 전용 -
    새 쓰기 메커니즘이 아니라 같은 패턴을 재사용한다)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", dir=target.parent, delete=False) as handle:
        handle.write(content)
        temp_path = Path(handle.name)
    temp_path.replace(target)


def apply_recovery(
    target_archive_path: Path | str, approved_records: Sequence[MediaArchiveRecord]
) -> MediaArchiveApplyResult:
    """가드를 통과한 후보만 실제로 ``target_archive_path``에 반영한다.

    호출부는 반드시 먼저 ``evaluate_apply_guard()``(및 필요하면
    ``reevaluate_before_apply()``)를 통과시킨 뒤에만 이 함수를 불러야 한다 -
    이 함수 자체는 가드를 다시 검사하지 않는다(단일 책임: "이미 승인된
    것만 쓰기").

    안전장치:
        - 쓰기 전: target의 현재 원시 bytes를 메모리에 백업한다(파일이
          없으면 ``None``).
        - 쓰기: ``upsert_archive()``(6-06, tempfile+``Path.replace()``로
          이미 원자적)를 그대로 재사용한다. 이 호출이 예외를 던지면 target은
          호출 전 상태 그대로다(원자적 쓰기가 실패하면 애초에 교체가
          일어나지 않으므로 복원할 필요조차 없다) - 6-23 시나리오 M.
        - 쓰기 후: ``validate_production_archive()``로 결과를 다시 검증한다.
          문제가 있으면 즉시 쓰기 전 bytes로 복원한다(같은 원자적 패턴) -
          6-23 시나리오 N.
    """
    target = Path(target_archive_path)
    backup_bytes = target.read_bytes() if target.exists() else None

    try:
        upsert_archive(target, list(approved_records))
    except Exception as error:  # noqa: BLE001 - 어떤 예외든 target 불변을 보장하고 사유를 보고한다
        return MediaArchiveApplyResult(
            success=False,
            written_content_ids=(),
            rolled_back=False,
            message=f"쓰기 실패, target은 변경되지 않았습니다(upsert_archive의 원자적 쓰기 보장): {error}",
        )

    post_report = validate_production_archive(target)
    if post_report.status != VALID or post_report.issues:
        if backup_bytes is not None:
            _atomic_write_bytes(target, backup_bytes)
        else:
            target.unlink(missing_ok=True)
        return MediaArchiveApplyResult(
            success=False,
            written_content_ids=(),
            rolled_back=True,
            message=(
                f"쓰기 후 검증 실패(status={post_report.status}, {len(post_report.issues)}건 이슈) - "
                "원래 상태로 복원했습니다."
            ),
        )

    return MediaArchiveApplyResult(
        success=True,
        written_content_ids=tuple(record.content_id for record in approved_records),
        rolled_back=False,
        message=f"{len(approved_records)}건을 {target}에 반영했습니다.",
    )
