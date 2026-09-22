"""Production Archive에서 superseded된 콘텐츠가 downstream(Blog/Shorts/Threads)에서
다시 발행 후보로 살아나는 것을 막기 위한 공통 판정 헬퍼(6-19,
docs/6-19-superseded-downstream-safeguards.md).

배경: Blog(``content_engine.blog_publish_pack.select_approved_blog_candidates_from_archive``)와
Shorts(``scripts/generate_approved_shorts_script.py``)는 이미 candidate 선정 시점에
``review_status == "approved"``만 통과시키므로, supersede로 review_status가
"superseded"로 바뀐 레코드는 그 필터에서 자동으로 제외된다(6-19 조사 결과, 이 두
경로는 이미 안전하다 - docs 3장/6장/7장 참고). 반면 Threads
(``scripts/publish_approved_threads.py``)와 YouTube 업로드
(``scripts/upload_youtube_short.py``)는 downstream artifact(pending draft,
ShortsScript+렌더링된 MP4)가 만들어진 시점의 승인 상태만 신뢰하고, 실제 발행
직전에 Production Archive의 "지금" 상태를 다시 확인하지 않는다 - 이 모듈은 그
구멍만 메운다.

이 모듈이 판정하는 것은 정확히 하나, "이 content_id가 supersede 때문에 지금
차단되어야 하는가"뿐이다. 다음은 이 모듈의 책임이 아니고, 각 플랫폼의 기존 로직이
계속 그대로 담당한다(6-19 지시 5장: "승인 여부"와 "현재 발행 가능한지"를 같은
개념으로 취급하지 않는다):
    - review_status가 approved인지("승인 여부") - 각 CLI/adapter의 기존 승인 게이트.
    - ALREADY_PUBLISHED(이미 실제로 게시됨) - 각 채널의 PublishHistory/
      YouTubeUploadHistory가 계속 담당한다. 이 판정보다 항상 먼저 확인해야 한다
      (6-19 지시 9장, 15장 - "이미 나간 사실"이 더 긴급하다).
    - ORPHAN(Production Archive에 해당 content_id 레코드 자체가 없음) - 이 모듈은
      레코드가 없으면 차단하지 않는다(호출부의 기존 ORPHAN 정책을 그대로 둔다).
    - unreviewed/dismissed 레코드 - 차단하지 않는다(supersede와 무관한 상태).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .media_archive import MediaArchiveRecord


@dataclass(frozen=True)
class SupersedeCheck:
    """content_id 1건에 대한 supersede 차단 판정 결과."""

    blocked: bool
    reason: str | None = None
    superseded_by: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {"blocked": self.blocked, "reason": self.reason, "superseded_by": self.superseded_by}


_NOT_BLOCKED = SupersedeCheck(blocked=False)


def find_production_record(
    records: Sequence[MediaArchiveRecord], content_id: str
) -> MediaArchiveRecord | None:
    """Production Archive 레코드 목록에서 ``content_id``와 정확히 일치하는 1건을 찾는다.

    정상 운영이라면(``upsert_archive()``가 content_id 단독 키로 upsert하므로) 이
    호출은 항상 0건 또는 1건을 반환한다. 여러 건이 있어도(``ERROR``/duplicate
    상황) 이 함수는 판단하지 않고 그냥 처음 찾은 것을 반환한다 - 구조적 이상 탐지는
    ``content_engine.publish_audit``의 책임이다.
    """
    for record in records:
        if record.content_id == content_id:
            return record
    return None


def check_supersede_block(record: MediaArchiveRecord | None) -> SupersedeCheck:
    """이미 조회한 Production Archive 레코드 1건(또는 없음)을 보고 supersede
    차단 여부만 판정한다. 파일을 읽지 않는 순수 함수다.
    """
    if record is None:
        return _NOT_BLOCKED
    if record.review_status != "superseded":
        return _NOT_BLOCKED
    return SupersedeCheck(
        blocked=True,
        reason=(
            f"production archive record가 superseded 상태입니다"
            f"(superseded_by={record.superseded_by}) - 더 이상 활성 게시 후보가 아닙니다."
        ),
        superseded_by=record.superseded_by,
    )


def check_content_supersede(
    records: Sequence[MediaArchiveRecord], content_id: str
) -> SupersedeCheck:
    """``records``에서 ``content_id``를 조회해 곧바로 supersede 차단 여부를 판정하는
    편의 함수(``find_production_record()`` + ``check_supersede_block()``)."""
    return check_supersede_block(find_production_record(records, content_id))


def format_block_message(content_id: str, check: SupersedeCheck) -> str:
    """CLI가 사람이 읽을 수 있는 한 줄 차단 메시지를 만든다(6-19 지시 16장).

    ``check.blocked``가 False일 때 호출하면 안 된다(호출부가 이미 분기 처리한다).
    """
    return (
        f"차단: content_id={content_id} status=SUPERSEDED "
        f"superseded_by={check.superseded_by} result=BLOCKED reason={check.reason}"
    )
