#!/usr/bin/env python3
"""승인된 MEDIA generation을 production archive로 승격(promote)하는 CLI (6-06, 6-09 batch 확장).

docs/6-06_media_versioning_and_safe_promotion.md 5~10장 설계를 구현한다.
docs/6-09_batch_promotion_and_production_readiness.md에서 여러 record를 한 번에
다루는 batch 모드를 추가했다.

이 스크립트가 하는 일은 두 가지뿐이다:

1. (기존, 6-06) ``--content-id``를 명시하면 그 record 1건만 다룬다: generation
   pool에서 사람이 이미 ``review_status="approved"``로 승인한 그 1건을 찾아
   production archive에 upsert한다.
2. (신규, 6-09) ``--content-id``를 생략하고 ``--generation-id``만 주면, 그
   generation_id를 가진 **모든** record를 조회해 조건을 만족하는 record만 한
   번에 promotion한다("batch promotion"). 조건을 만족하지 못하는 record는
   promotion하지 않고 이유와 함께 건너뛴다(skip) - 부분 승인된 generation도
   안전하게 처리할 수 있다.

이 스크립트가 절대 하지 않는 것:
    - 실제 Threads/YouTube/Naver 게시 (ThreadsClient/YouTubeClient/Naver 게시
      코드를 전혀 import하지 않는다)
    - LLM 호출 (generation pool에 이미 저장된 결과만 읽는다)
    - review_status를 approved로 바꾸는 것 (사람이 Dashboard/다른 도구로 이미
      approved로 만든 generation만 대상으로 한다 - 이 스크립트는 승인 기능이
      없다). batch 모드도 마찬가지로, unreviewed/dismissed record를 approved로
      바꾸지 않고 그냥 건너뛴다.

Promotion 조건(단건/batch 공통, 모두 만족해야 promotion 대상):
    1. generation pool에 (content_id, generation_id)가 정확히 일치하는 레코드가 있다.
    2. 그 레코드의 generation_status == "valid" (rejected/error는 promotion 불가).
    3. 그 레코드의 review_status == "approved" (unreviewed/dismissed는 promotion 불가).

기본 동작은 dry-run이다(파일을 쓰지 않고 계획만 출력) - ``--execute``를 명시해야
실제로 production archive를 갱신한다(``scripts/run_media_batch.py --execute``와
동일한 안전 관례).

이미 그 content_id의 production 활성 레코드가 같은 generation_id라면
(이미 승격된 상태) 아무것도 다시 쓰지 않고 idempotent하게 끝난다(단건/batch 공통).

6-09 안전 원칙: batch 모드는 ``--production-archive``를 **명시적으로** 받아야만
동작한다(dry-run 포함) - "기본값으로 실제 production archive에 쓴다"는 사고를
구조적으로 막기 위함이다. 단건 모드는 6-06 때부터의 기존 기본값
(``data/tak_media_archive.json``) 동작을 그대로 유지한다(하위 호환).
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_engine.media_archive import (
    ArchiveConflictError,
    MediaArchiveRecord,
    check_promotion_conflict,
    find_generation_record,
    load_archive,
    upsert_archive,
)


DEFAULT_PRODUCTION_ARCHIVE_PATH = ROOT / "data" / "tak_media_archive.json"

# review_status/generation_status가 promotion 조건을 만족하지 못할 때 보여줄
# 사람이 읽을 수 있는 skip 사유. 새 상태값을 만들지 않고 기존
# content_engine.media_archive.REVIEW_STATUSES/GENERATION_STATUSES 값만 그대로 쓴다.
_SKIP_REASON_LABELS = {
    "unreviewed": "review_status=unreviewed (아직 검토 전)",
    "dismissed": "review_status=dismissed (사람이 보류함)",
    "rejected": "generation_status=rejected (검증 실패)",
    "error": "generation_status=error (생성 오류)",
}


class PromotionError(ValueError):
    """Promotion 조건을 만족하지 못했을 때 발생한다."""


class PromotionConflictError(PromotionError):
    """6-18: production archive에 이미 존재하는 content_id를 다른 generation_id를
    가진 candidate로 promotion하려고 할 때 발생한다(``PromotionError``의
    하위 클래스라 기존 ``except PromotionError`` 호출부는 그대로 잡아낸다).

    이 예외가 발생했다는 것은 곧 production archive가 전혀 바뀌지 않았다는
    뜻이다 - ``check_promotion_conflict()``가 파일을 쓰기 전에 검사하는
    순수 함수이기 때문이다(``content_engine.media_archive.ArchiveConflictError``
    참고). 이 상황을 해결하려면 명시적인
    ``scripts/supersede_media_record.py``를 사용해야 한다 - 이 스크립트는
    자동으로 supersede하지 않는다(6-18 정책 D).
    """


def find_active_record(production_archive_path: Path, content_id: str) -> MediaArchiveRecord | None:
    """production archive에서 이 content_id의 현재 활성 레코드를 찾는다(없으면 None)."""
    for record in load_archive(production_archive_path):
        if record.content_id == content_id:
            return record
    return None


def plan_promotion(
    generation_archive_path: Path,
    production_archive_path: Path,
    content_id: str,
    generation_id: str,
) -> tuple[MediaArchiveRecord, MediaArchiveRecord | None]:
    """Promotion 대상을 검증하고 (candidate, current_active) 쌍을 반환한다.

    조건을 만족하지 못하면 ``PromotionError``를 던진다(파일은 아무것도 건드리지
    않는다 - 이 함수는 순수 조회/검증만 한다).
    """
    candidate = find_generation_record(generation_archive_path, content_id, generation_id)
    if candidate is None:
        raise PromotionError(
            f"generation pool에서 찾을 수 없습니다: content_id={content_id!r}, "
            f"generation_id={generation_id!r} (경로: {generation_archive_path})"
        )
    if candidate.generation_status != "valid":
        raise PromotionError(
            f"generation_status가 'valid'가 아니면 promotion할 수 없습니다: "
            f"{candidate.generation_status!r} (content_id={content_id!r}, generation_id={generation_id!r})"
        )
    if candidate.review_status != "approved":
        raise PromotionError(
            f"review_status가 'approved'가 아니면 promotion할 수 없습니다: "
            f"{candidate.review_status!r} (content_id={content_id!r}, generation_id={generation_id!r}). "
            "이 스크립트는 승인 기능이 없습니다 - Dashboard 등에서 먼저 승인하세요."
        )

    current_active = find_active_record(production_archive_path, content_id)
    # 6-18: 같은 content_id + 다른 generation_id인 기존 production 레코드가
    # 있으면 여기서 즉시 차단한다 - 이 함수는 순수 조회/검증만 하므로(파일에
    # 아무것도 쓰지 않는다), 이 시점에 예외가 발생해도 production archive는
    # 호출 전 상태 그대로 보존된다.
    try:
        check_promotion_conflict(current_active, candidate)
    except ArchiveConflictError as error:
        raise PromotionConflictError(str(error)) from error
    return candidate, current_active


# --- 6-09: Batch promotion (여러 record를 한 번에) --------------------------


@dataclass(frozen=True)
class BatchPromotionItem:
    """batch 계획에서 record 1건의 상태."""

    record: MediaArchiveRecord
    # "promote": 지금 promotion하면 production archive가 바뀐다.
    # "already_promoted": approved+valid이지만 production이 이미 같은
    #   generation_id로 승격돼 있어 다시 쓸 필요가 없다(idempotent skip).
    # "skip": generation_status/review_status 조건을 만족하지 못해 애초에
    #   promotion 대상이 아니다.
    # "conflict"(6-18): approved+valid이지만 production에 이미 다른
    #   generation_id의 활성 레코드가 있어 자동 overwrite가 금지된 경우.
    #   "skip"과 구분하는 이유: skip은 이 candidate 자체가 아직 promotion
    #   조건(승인/유효성)을 만족하지 못한 정상적인 대기 상태이지만, conflict는
    #   candidate는 조건을 만족하는데도 데이터 무결성 보호 때문에 사람의
    #   추가 결정(supersede)이 필요한 상태이기 때문이다.
    action: str
    reason: str
    # 6-18: action=="conflict"일 때만 채워진다 - 기존 production 활성
    # 레코드의 generation_id(사람이 CLI 출력에서 old/new를 한눈에 비교할 수
    # 있도록). 그 외 action에서는 None이다(의미가 없으므로).
    old_generation_id: str | None = None


def plan_batch_promotion(
    generation_archive_path: Path,
    production_archive_path: Path,
    generation_id: str | None,
) -> list[BatchPromotionItem]:
    """``generation_id``를 가진 generation pool의 모든 record에 대한 batch 계획을 세운다.

    조건을 만족하는 record(approved+valid)만 "promote"(또는 이미 승격됐다면
    "already_promoted")로 분류하고, 나머지는 정확한 사유와 함께 "skip"으로
    분류한다 - 어떤 record도 파일에 쓰지 않는다(순수 조회/검증만).

    이 generation_id를 가진 record가 generation pool에 하나도 없으면
    ``PromotionError``를 던진다("존재하지 않는 generation").
    """
    all_records = load_archive(generation_archive_path)
    matching = [record for record in all_records if record.generation_id == generation_id]
    if not matching:
        raise PromotionError(
            f"generation pool에서 generation_id={generation_id!r}를 찾을 수 없습니다 "
            f"(경로: {generation_archive_path})"
        )

    items: list[BatchPromotionItem] = []
    for record in matching:
        if record.generation_status != "valid":
            items.append(
                BatchPromotionItem(
                    record=record,
                    action="skip",
                    reason=_SKIP_REASON_LABELS.get(
                        record.generation_status, f"generation_status={record.generation_status}"
                    ),
                )
            )
            continue
        if record.review_status != "approved":
            items.append(
                BatchPromotionItem(
                    record=record,
                    action="skip",
                    reason=_SKIP_REASON_LABELS.get(
                        record.review_status, f"review_status={record.review_status}"
                    ),
                )
            )
            continue

        current_active = find_active_record(production_archive_path, record.content_id)
        if current_active is not None and current_active.generation_id == generation_id:
            items.append(
                BatchPromotionItem(record=record, action="already_promoted", reason="이미 승격됨(변경 없음)")
            )
            continue
        if current_active is not None:
            # 6-18: content_id는 같지만 generation_id가 다른 기존 production
            # 활성 레코드가 있다 - 이 record만 conflict로 보고하고 건너뛴다.
            # 같은 batch의 다른 record(신규 content_id 등)는 이 conflict와
            # 무관하게 정상적으로 "promote"/"already_promoted"/"skip"으로
            # 계속 분류된다(11장: 하나의 충돌이 다른 정상 record를 막지 않는다).
            items.append(
                BatchPromotionItem(
                    record=record,
                    action="conflict",
                    reason=(
                        f"기존 production 활성 레코드와 충돌(old_generation_id="
                        f"{current_active.generation_id!r}, new_generation_id={generation_id!r}) - "
                        "자동 overwrite 금지, supersede_media_record.py로 명시적 처리 필요"
                    ),
                    old_generation_id=current_active.generation_id,
                )
            )
            continue
        items.append(BatchPromotionItem(record=record, action="promote", reason="approved+valid"))

    return items


def _print_batch_plan(generation_id: str, items: list[BatchPromotionItem]) -> None:
    total = len(items)
    approved = sum(1 for item in items if item.record.review_status == "approved")
    unreviewed = sum(1 for item in items if item.record.review_status == "unreviewed")
    dismissed = sum(1 for item in items if item.record.review_status == "dismissed")
    rejected = sum(1 for item in items if item.record.generation_status == "rejected")
    error = sum(1 for item in items if item.record.generation_status == "error")
    valid = sum(1 for item in items if item.record.generation_status == "valid")
    to_promote = [item for item in items if item.action == "promote"]
    already_promoted = [item for item in items if item.action == "already_promoted"]
    to_skip = [item for item in items if item.action == "skip"]
    to_conflict = [item for item in items if item.action == "conflict"]

    knowledge_ids = {item.record.knowledge_id for item in items}

    print(f"generation_id:   {generation_id}")
    print(f"knowledge_id:    {', '.join(sorted(knowledge_ids))}")
    print(f"총 record:       {total}")
    print(f"  valid:         {valid}")
    print(f"  rejected:      {rejected}")
    print(f"  error:         {error}")
    print(f"  approved:      {approved}")
    print(f"  unreviewed:    {unreviewed}")
    print(f"  dismissed:     {dismissed}")
    print(f"promotion 예정:  {len(to_promote)}건")
    print(f"이미 승격됨:      {len(already_promoted)}건 (변경 없음, idempotent)")
    print(f"skip:            {len(to_skip)}건")
    print(f"conflict:        {len(to_conflict)}건 (기존 production record와 충돌 - 자동 차단, 6-18)")
    print()
    for item in items:
        action_label = {
            "promote": "PROMOTE",
            "already_promoted": "ALREADY PROMOTED (변경 없음)",
            "skip": f"SKIP ({item.reason})",
            "conflict": f"CONFLICT ({item.reason})",
        }[item.action]
        print(
            f"  {item.record.content_id}  [{item.record.platform}]  "
            f"generation_status={item.record.generation_status} review_status={item.record.review_status}  "
            f"-> {action_label}"
        )
    if to_conflict:
        print()
        print("=== CONFLICT 상세 (사람의 결정 필요) ===")
        for item in to_conflict:
            print(f"  content_id       = {item.record.content_id}")
            print(f"  old_generation_id = {item.old_generation_id}")
            print(f"  new_generation_id = {generation_id}")
            print("  result           = CONFLICT")
            print("  reason           = 기존 production 활성 레코드와 다른 generation_id로 충돌 - 자동 overwrite 금지")
            print()


def _print_plan(candidate: MediaArchiveRecord, current_active: MediaArchiveRecord | None) -> None:
    print(f"content_id:      {candidate.content_id}")
    print(f"knowledge_id:    {candidate.knowledge_id}")
    print(f"platform:        {candidate.platform}")
    print(f"generation_id:   {candidate.generation_id}")
    print(f"generation_status: {candidate.generation_status}")
    print(f"review_status:     {candidate.review_status}")
    print(f"새 title:        {candidate.final_title}")
    print()
    # 6-18: current_active가 있으면서 generation_id가 다른 경우는 이제 이
    # 함수가 호출되기 전에 plan_promotion()이 PromotionConflictError를 던져
    # 걸러낸다 - 여기 도달했다는 것 자체가 "없음" 또는 "이미 이 generation"
    # 둘 중 하나만 가능하다는 뜻이다(자동 overwrite가 조용히 진행되는 것처럼
    # 보이던 기존 문구는 더 이상 나올 수 없으므로 제거했다).
    if current_active is None:
        print("기존 production 활성 레코드: 없음 (이 content_id는 production archive에 처음 추가됨)")
    else:
        print("기존 production 활성 레코드가 이미 이 generation입니다 (변경 없음, idempotent).")
        print(f"  현재 title: {current_active.final_title}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "generation pool에서 승인된(approved) + 유효한(valid) MEDIA generation을 "
            "production archive로 승격한다. 기본은 dry-run(파일 변경 없음)이며, "
            "--execute를 줘야 실제로 쓴다. --content-id를 주면 record 1건만(6-06), "
            "생략하면 --generation-id 전체를 대상으로 batch promotion한다(6-09) - "
            "이 경우 조건을 만족하지 못하는 record는 promotion하지 않고 skip한다."
        )
    )
    parser.add_argument(
        "--archive",
        type=Path,
        required=True,
        help="generation pool 아카이브 경로 (예: archive_generation_report()가 만든 파일)",
    )
    parser.add_argument(
        "--production-archive",
        type=Path,
        default=None,
        help=(
            "production archive 경로. --content-id로 단건 promotion할 때는 생략하면 "
            "data/tak_media_archive.json을 쓴다(6-06 기존 기본값, 하위 호환). "
            "--content-id 없이 batch promotion할 때는 실수로 실제 production archive를 "
            "건드리는 것을 막기 위해 반드시 명시해야 한다(6-09 안전 원칙, 기본값 없음)."
        ),
    )
    parser.add_argument(
        "--content-id",
        type=str,
        default=None,
        help="승격할 콘텐츠 슬롯의 content_id. 생략하면 --generation-id 전체를 batch promotion한다.",
    )
    parser.add_argument("--generation-id", type=str, required=True, help="승격할 generation_id")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="실제로 production archive를 갱신합니다. 생략하면 dry-run(계획만 출력, 파일 변경 없음).",
    )
    args = parser.parse_args(argv)

    mode = "EXECUTE" if args.execute else "DRY-RUN (파일 변경 없음)"

    if args.content_id is not None:
        # --- 단건 promotion (6-06, 기존 동작 그대로) ---
        production_archive_path = args.production_archive or DEFAULT_PRODUCTION_ARCHIVE_PATH
        try:
            candidate, current_active = plan_promotion(
                args.archive, production_archive_path, args.content_id, args.generation_id
            )
        except PromotionError as error:
            print(f"오류: {error}", file=sys.stderr)
            return 1

        print(f"=== MEDIA Generation Promotion [{mode}] ===")
        _print_plan(candidate, current_active)

        if not args.execute:
            print("\ndry-run 완료. 실제로 반영하려면 --execute를 추가하세요.")
            return 0

        if current_active is not None and current_active.generation_id == candidate.generation_id:
            print("\n이미 승격된 generation입니다. 아무것도 쓰지 않았습니다.")
            return 0

        upsert_archive(production_archive_path, [candidate])
        print(f"\n승격 완료: {production_archive_path}에 반영했습니다.")
        return 0

    # --- batch promotion (6-09, --content-id 생략) ---
    if args.production_archive is None:
        print(
            "오류: batch promotion(--content-id 생략)은 --production-archive를 "
            "명시적으로 지정해야 합니다 - 실수로 실제 production archive를 건드리는 것을 "
            "막기 위한 안전장치입니다(docs/6-09_batch_promotion_and_production_readiness.md 참고).",
            file=sys.stderr,
        )
        return 1

    try:
        items = plan_batch_promotion(args.archive, args.production_archive, args.generation_id)
    except PromotionError as error:
        print(f"오류: {error}", file=sys.stderr)
        return 1

    print(f"=== MEDIA Generation Batch Promotion [{mode}] ===")
    _print_batch_plan(args.generation_id, items)

    to_promote = [item.record for item in items if item.action == "promote"]

    if not args.execute:
        print("\ndry-run 완료. 실제로 반영하려면 --execute를 추가하세요.")
        return 0

    if not to_promote:
        print("\npromotion 대상이 없습니다(전부 이미 승격됐거나 skip/conflict 대상). 아무것도 쓰지 않았습니다.")
        return 0

    upsert_archive(args.production_archive, to_promote)
    print(f"\n승격 완료: {len(to_promote)}건을 {args.production_archive}에 반영했습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
