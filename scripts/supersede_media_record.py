#!/usr/bin/env python3
"""이미 승인된(approved) Production Archive 레코드를 정정본으로 **안전하게 대체**
표시하는 CLI (6-17, docs/6-17_superseded_lifecycle_design.md 구현).

배경(6-16이 확인한 문제): 정정본은 보통 원본과 다른 content_id를 받는다
(``compute_content_id()``가 original_title/body를 지문에 포함하기 때문). 그
결과 기존 ``promote_media_generation.py``로 정정본을 승격해도 옛 승인
레코드는 그대로 남고 새 레코드가 옆에 "추가"될 뿐이다 - "대체"가 되지 않는다.

이 스크립트가 하는 일은 정확히 하나뿐이다:

    옛 레코드(``--old-content-id``)의 ``review_status``를 ``"superseded"``로
    바꾸고 ``superseded_by``에 새 레코드(``--new-content-id``)의 content_id를
    적어 저장한다.

이 스크립트가 절대 하지 않는 것:
    - 새 레코드를 production archive에 추가하는 것 (그건 기존
      ``promote_media_generation.py``의 일이다 - 이 스크립트를 실행하기 전에
      먼저 새 레코드가 이미 production archive에 approved+valid 상태로
      존재해야 한다)
    - 옛 레코드의 content_id/title/body/created_at/knowledge_id/source_url/
      evidence 등 어떤 필드도 변경 (review_status/superseded_by 두 필드만
      바뀐다 - 나머지는 전부 그대로 보존된다)
    - downstream artifact(ShortsScript 파일, Threads pending draft, publish
      history) 삭제 또는 수정 (전혀 건드리지 않는다 - docs/6-17 13장 정책)
    - review_status를 approved로 만드는 것 (새 레코드는 이미 다른 도구로
      승인된 상태여야 한다 - 이 스크립트는 승인 기능이 없다)
    - 외부 게시(Naver/Threads/YouTube), LLM 호출

Supersede 조건(모두 만족해야 실행 가능, docs/6-17 5장·9장):
    1. old_content_id가 production archive에 존재한다.
    2. new_content_id가 production archive에 존재한다(= 이미 promotion 완료).
    3. old.content_id != new.content_id (같은 슬롯을 자기 자신으로 대체할 수 없음).
    4. old.review_status == "approved" (이미 superseded된 것을 다시 superseded
       하거나, 아직 approved도 안 된 것을 superseded할 수 없음).
    5. new.generation_status == "valid".
    6. new.review_status == "approved".
    7. old.knowledge_id == new.knowledge_id.
    8. old.platform == new.platform.
    9. old.source_url == new.source_url (정책: "정정"은 같은 원문의 교정만
       인정한다 - 다른 원문으로 바꾸는 것은 이 워크플로우의 대상이 아니다,
       docs/6-17 10장 CASE 7 정책 결정).

기본 동작은 dry-run이다(파일을 쓰지 않고 계획만 출력) - ``--execute``를
명시해야 실제로 production archive를 갱신한다(``promote_media_generation.py``와
동일한 안전 관례). ``--production-archive``는 항상 명시적으로 지정해야 한다
(기본값 없음) - approved 레코드를 되돌릴 수 없는 상태로 바꾸는, 이 저장소에서
가장 민감한 쓰기 동작이므로 6-09의 batch promotion보다도 더 보수적인 안전
장치를 둔다.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_engine.media_archive import MediaArchiveRecord, load_archive, upsert_archive


class SupersedeError(ValueError):
    """Supersede 조건을 만족하지 못했을 때 발생한다. 파일은 아무것도 쓰지 않는다."""


@dataclass(frozen=True)
class SupersedePlan:
    """검증을 통과한 supersede 계획. ``updated_old_record``만 실제로 저장된다."""

    old_record: MediaArchiveRecord
    new_record: MediaArchiveRecord
    updated_old_record: MediaArchiveRecord


def _find(records: list[MediaArchiveRecord], content_id: str) -> MediaArchiveRecord | None:
    for record in records:
        if record.content_id == content_id:
            return record
    return None


def plan_supersede(
    production_archive_path: Path, old_content_id: str, new_content_id: str
) -> SupersedePlan:
    """Supersede 대상을 검증하고 계획을 반환한다. 파일을 쓰지 않는 순수 함수다.

    조건을 하나라도 만족하지 못하면 ``SupersedeError``를 던진다 - 이 경우 옛
    레코드는 호출부가 무엇을 하든 안전하게 원래 상태 그대로 남는다(이 함수가
    파일에 아무것도 쓰지 않으므로).
    """
    records = load_archive(production_archive_path)

    old = _find(records, old_content_id)
    if old is None:
        raise SupersedeError(
            f"old_content_id를 production archive에서 찾을 수 없습니다: {old_content_id!r} "
            f"(경로: {production_archive_path})"
        )

    new = _find(records, new_content_id)
    if new is None:
        raise SupersedeError(
            f"new_content_id를 production archive에서 찾을 수 없습니다: {new_content_id!r}. "
            "supersede는 정정본이 이미 promote_media_generation.py로 production archive에 "
            "승격된 뒤에만 실행할 수 있습니다."
        )

    if old.content_id == new.content_id:
        raise SupersedeError(
            "old_content_id와 new_content_id가 같습니다 - supersede는 서로 다른 두 "
            "content_id 사이에서만 의미가 있습니다(같은 content_id의 재생성은 "
            "generation pool + promote_media_generation.py가 이미 다루는 별개의 경로입니다)."
        )

    if old.review_status == "superseded":
        raise SupersedeError(
            f"old record가 이미 superseded 상태입니다(현재 대체본: {old.superseded_by!r}) - "
            "이중 supersede는 허용하지 않습니다."
        )
    if old.review_status != "approved":
        raise SupersedeError(
            f"old record가 approved 상태가 아닙니다: review_status={old.review_status!r} - "
            "supersede는 이미 approved된 레코드에만 적용합니다."
        )

    if new.generation_status != "valid":
        raise SupersedeError(
            f"new record의 generation_status가 valid가 아닙니다: {new.generation_status!r}"
        )
    if new.review_status != "approved":
        raise SupersedeError(
            f"new record가 아직 approved되지 않았습니다: review_status={new.review_status!r} - "
            "먼저 Dashboard 등에서 승인하세요(이 스크립트는 승인 기능이 없습니다)."
        )

    if old.knowledge_id != new.knowledge_id:
        raise SupersedeError(
            f"old/new의 knowledge_id가 다릅니다: {old.knowledge_id!r} != {new.knowledge_id!r} - "
            "서로 다른 KNOWLEDGE에서 나온 콘텐츠는 supersede 관계로 연결할 수 없습니다."
        )
    if old.platform != new.platform:
        raise SupersedeError(
            f"old/new의 platform이 다릅니다: {old.platform!r} != {new.platform!r}"
        )
    if old.source_url != new.source_url:
        raise SupersedeError(
            f"old/new의 source_url이 다릅니다: {old.source_url!r} != {new.source_url!r} - "
            "이 워크플로우는 같은 원문(source_url)의 정정본만 supersede로 인정합니다. "
            "다른 원문으로 교체하는 것은 '정정'이 아니라 별개의 신규 콘텐츠이므로 이 "
            "스크립트로 처리하지 않습니다(docs/6-17_superseded_lifecycle_design.md 10장)."
        )

    updated_old = replace(old, review_status="superseded", superseded_by=new.content_id)
    return SupersedePlan(old_record=old, new_record=new, updated_old_record=updated_old)


def execute_supersede(production_archive_path: Path, plan: SupersedePlan) -> MediaArchiveRecord:
    """계획을 실제로 저장한다. ``updated_old_record`` 1건만 upsert한다 - 새
    레코드는 이미 production archive에 있으므로 다시 쓰지 않는다(원자성:
    이 호출 하나가 바꾸는 파일 상태는 옛 레코드 1건뿐이다 - save_archive()가
    쓰는 tempfile+Path.replace() 덕분에 저장 도중 실패해도 원본 파일은
    그대로 남는다, docs/6-17 9장 CASE 9)."""
    upsert_archive(production_archive_path, [plan.updated_old_record])
    return plan.updated_old_record


def _print_plan(plan: SupersedePlan) -> None:
    print(f"old content_id:  {plan.old_record.content_id}")
    print(f"  title:         {plan.old_record.final_title}")
    print(f"  review_status: {plan.old_record.review_status} -> superseded")
    print(f"new content_id:  {plan.new_record.content_id}")
    print(f"  title:         {plan.new_record.final_title}")
    print(f"  review_status: {plan.new_record.review_status} (변경 없음)")
    print(f"knowledge_id:    {plan.old_record.knowledge_id} (동일)")
    print(f"platform:        {plan.old_record.platform} (동일)")
    print(f"source_url:      {plan.old_record.source_url} (동일)")
    print()
    print("이 작업 후:")
    print(f"  - {plan.old_record.content_id}: review_status=superseded, superseded_by={plan.new_record.content_id}")
    print(f"  - {plan.new_record.content_id}: 변경 없음(이미 production archive에 approved 상태로 존재)")
    print("  - downstream artifact(ShortsScript/Threads pending/publish history)는 전혀 삭제/수정하지 않음")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "이미 approved된 production archive 레코드를, 이미 승격된 정정본으로 "
            "안전하게 superseded 표시한다. 옛 레코드는 삭제되지 않고 review_status만 "
            "'superseded'로 바뀌며 superseded_by에 정정본 content_id가 기록된다. "
            "기본은 dry-run(파일 변경 없음)이며, --execute를 줘야 실제로 쓴다."
        )
    )
    parser.add_argument(
        "--production-archive",
        type=Path,
        required=True,
        help="production archive 경로. 이 스크립트는 기본값을 두지 않는다(안전장치).",
    )
    parser.add_argument("--old-content-id", type=str, required=True, help="superseded로 표시할 옛 레코드의 content_id")
    parser.add_argument("--new-content-id", type=str, required=True, help="이미 승격된 정정본 레코드의 content_id")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="실제로 production archive를 갱신합니다. 생략하면 dry-run(계획만 출력, 파일 변경 없음).",
    )
    args = parser.parse_args(argv)

    mode = "EXECUTE" if args.execute else "DRY-RUN (파일 변경 없음)"

    try:
        plan = plan_supersede(args.production_archive, args.old_content_id, args.new_content_id)
    except SupersedeError as error:
        print(f"오류: {error}", file=sys.stderr)
        return 1

    print(f"=== MEDIA Record Supersede [{mode}] ===")
    _print_plan(plan)

    if not args.execute:
        print("\ndry-run 완료. 실제로 반영하려면 --execute를 추가하세요.")
        return 0

    execute_supersede(args.production_archive, plan)
    print(f"\nsupersede 완료: {args.production_archive}에 반영했습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
