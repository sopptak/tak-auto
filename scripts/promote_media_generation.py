#!/usr/bin/env python3
"""승인된 MEDIA generation 1건을 production archive로 승격(promote)하는 CLI (6-06).

docs/6-06_media_versioning_and_safe_promotion.md 5~10장 설계를 구현한다.

이 스크립트가 하는 일은 딱 하나다: generation pool(``content_engine.media_archive``의
``archive_generation_report()``/``upsert_generation_archive()``가 만든, 같은
content_id의 여러 generation을 모두 보존하는 별도 아카이브 파일)에서 사람이 이미
``review_status="approved"``로 승인한 generation 1건을 찾아, production
archive(``content_id`` 단독 키 - 콘텐츠 슬롯당 활성 레코드가 정확히 하나인 기존
``data/tak_media_archive.json`` 구조)에 그 레코드를 upsert한다. 그 이상은 하지
않는다.

이 스크립트가 절대 하지 않는 것:
    - 실제 Threads/YouTube/Naver 게시 (ThreadsClient/YouTubeClient/Naver 게시
      코드를 전혀 import하지 않는다)
    - LLM 호출 (generation pool에 이미 저장된 결과만 읽는다)
    - review_status를 approved로 바꾸는 것 (사람이 Dashboard/다른 도구로 이미
      approved로 만든 generation만 대상으로 한다 - 이 스크립트는 승인 기능이
      없다)

Promotion 조건(모두 만족해야 함):
    1. generation pool에 (content_id, generation_id)가 정확히 일치하는 레코드가 있다.
    2. 그 레코드의 generation_status == "valid" (rejected/error는 promotion 불가).
    3. 그 레코드의 review_status == "approved" (unreviewed/dismissed는 promotion 불가).

기본 동작은 dry-run이다(파일을 쓰지 않고 계획만 출력) - ``--execute``를 명시해야
실제로 production archive를 갱신한다(``scripts/run_media_batch.py --execute``와
동일한 안전 관례).

이미 그 content_id의 production 활성 레코드가 같은 generation_id라면
(이미 승격된 상태) 아무것도 다시 쓰지 않고 idempotent하게 끝난다.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_engine.media_archive import (
    MediaArchiveRecord,
    find_generation_record,
    load_archive,
    upsert_archive,
)


class PromotionError(ValueError):
    """Promotion 조건을 만족하지 못했을 때 발생한다."""


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
    return candidate, current_active


def _print_plan(candidate: MediaArchiveRecord, current_active: MediaArchiveRecord | None) -> None:
    print(f"content_id:      {candidate.content_id}")
    print(f"knowledge_id:    {candidate.knowledge_id}")
    print(f"platform:        {candidate.platform}")
    print(f"generation_id:   {candidate.generation_id}")
    print(f"generation_status: {candidate.generation_status}")
    print(f"review_status:     {candidate.review_status}")
    print(f"새 title:        {candidate.final_title}")
    print()
    if current_active is None:
        print("기존 production 활성 레코드: 없음 (이 content_id는 production archive에 처음 추가됨)")
    elif current_active.generation_id == candidate.generation_id:
        print("기존 production 활성 레코드가 이미 이 generation입니다 (변경 없음, idempotent).")
        print(f"  현재 title: {current_active.final_title}")
    else:
        print("기존 production 활성 레코드가 이 promotion으로 교체됩니다:")
        print(f"  기존 generation_id: {current_active.generation_id!r} (legacy면 None)")
        print(f"  기존 title:        {current_active.final_title}")
        print(f"  기존 review_status: {current_active.review_status}")
        print("  (review_status/edited_title/edited_body는 candidate 레코드의 값을 그대로 씁니다 -")
        print("   candidate가 이미 승인된 generation이므로, 승격 이후에는 candidate의 값이 곧 production 상태입니다.)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "generation pool에서 승인된(approved) + 유효한(valid) generation 1건을 "
            "production archive로 승격한다. 기본은 dry-run(파일 변경 없음)이며, "
            "--execute를 줘야 실제로 쓴다."
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
        default=ROOT / "data" / "tak_media_archive.json",
        help="production archive 경로 (기본값: data/tak_media_archive.json)",
    )
    parser.add_argument("--content-id", type=str, required=True, help="승격할 콘텐츠 슬롯의 content_id")
    parser.add_argument("--generation-id", type=str, required=True, help="승격할 generation_id")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="실제로 production archive를 갱신합니다. 생략하면 dry-run(계획만 출력, 파일 변경 없음).",
    )
    args = parser.parse_args(argv)

    try:
        candidate, current_active = plan_promotion(
            args.archive, args.production_archive, args.content_id, args.generation_id
        )
    except PromotionError as error:
        print(f"오류: {error}", file=sys.stderr)
        return 1

    mode = "EXECUTE" if args.execute else "DRY-RUN (파일 변경 없음)"
    print(f"=== MEDIA Generation Promotion [{mode}] ===")
    _print_plan(candidate, current_active)

    if not args.execute:
        print("\ndry-run 완료. 실제로 반영하려면 --execute를 추가하세요.")
        return 0

    if current_active is not None and current_active.generation_id == candidate.generation_id:
        print("\n이미 승격된 generation입니다. 아무것도 쓰지 않았습니다.")
        return 0

    upsert_archive(args.production_archive, [candidate])
    print(f"\n승격 완료: {args.production_archive}에 반영했습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
