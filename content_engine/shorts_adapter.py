"""TAK MEDIA의 ShortDraft(title + 단일 body 문자열)를 Shorts 렌더러가 받는
ShortsScript(title/subtitle/cards/takeaway/brand)로 변환하는 어댑터(5-19).

content_engine/shorts_script.py 자체가 스스로 명시하듯, 렌더러는 "화면 단위로
나뉜 대본"만 입력으로 받고 문장을 새로 나누거나 요약하지 않는다(그건 상위
콘텐츠 생성 단계의 책임). 이 모듈이 바로 그 "상위 단계"에 해당하며, 하는 일은
오직 구조 변환뿐이다 - 새로운 문장을 만들거나 원문 내용을 수정하지 않는다.

규칙(5-19 설계 문서 그대로):
    - title      -> ShortsScript.title (그대로)
    - body       -> "\\n\\n"로 나눈 문단이 cards가 된다(생성기 content_engine/
                    generator.py의 _body()가 원래 이 구분자로 문단을 합치므로,
                    별도 파싱 없이 그 관례를 그대로 재사용한다).
    - 마지막 문단 -> takeaway (문단이 여러 개면 마지막 문단은 cards에서 빠진다).
    - 문단이 1개뿐이면 그 문단을 cards와 takeaway 양쪽에 그대로 재사용한다
      (새 문장을 만들지 않기 위한 안전한 fallback - 아래 함수 docstring 참고).
    - subtitle은 ShortDraft에 대응하는 필드가 없으므로 빈 문자열로 둔다(없는
      내용을 새로 만들지 않는다). ShortsScript는 subtitle을 필수로 요구하지
      않는다(content_engine/shorts_script.py의 _validate 참고).
    - brand 기본값은 ShortsScript와 동일하게 "티몽의 지혜".

이 모듈은 content_engine/shorts_script.py, content_engine/shorts_renderer.py,
content_engine/generator.py를 전혀 수정하지 않는다. Finance/사실성/원문 검증
로직도 새로 만들지 않는다 - 그런 검증은 이미 content_engine/rewrite.py의
책임이며 이 어댑터가 받는 ShortDraft는 이미 그 검증을 통과한 콘텐츠다.

5-29: ``save_approved_shorts_script()``가 승인된 Shorts를 실제 JSON 파일로
저장한다(MP4 렌더링은 여전히 하지 않는다 - content_engine/shorts_renderer는
이 모듈이 전혀 import하지 않는다). 저장 스키마는 ``ShortsScript.from_dict()``가
읽는 5개 키(title/subtitle/cards/takeaway/brand)를 그대로 포함하므로,
``scripts/render_youtube_short.py --input``에 이 파일을 바로 넘길 수 있다.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile

from blog_importer.models import utc_now

from .media_archive import MediaArchiveRecord
from .models import ShortDraft
from .shorts_script import DEFAULT_BRAND, MAX_CARDS, ShortsScript, ShortsScriptError


class ShortsAdapterError(ValueError):
    """ShortDraft를 ShortsScript로 안전하게 변환할 수 없을 때 발생한다."""


def short_draft_to_shorts_script(
    draft: ShortDraft, brand: str = DEFAULT_BRAND
) -> ShortsScript:
    """ShortDraft를 ShortsScript로 변환한다.

    body가 빈 문단만 가지고 있으면(예: body가 빈 문자열) 변환할 내용이 없으므로
    ShortsAdapterError를 던진다.

    문단이 9개 이상이라 마지막 문단을 takeaway로 뺀 뒤에도 cards가
    MAX_CARDS(8)개를 초과하면, 일부 문단을 임의로 잘라 의미를 훼손하는 대신
    명시적으로 실패시킨다(ShortsAdapterError) - 어떤 문단을 버릴지 이 어댑터가
    임의로 판단하지 않는다는 원칙(콘텐츠를 새로 창작/편집하지 않는다)에 따른
    선택이다.
    """
    paragraphs = [paragraph.strip() for paragraph in draft.body.split("\n\n") if paragraph.strip()]
    if not paragraphs:
        raise ShortsAdapterError("ShortDraft.body에 변환할 문단이 없습니다(빈 본문).")

    if len(paragraphs) == 1:
        # 문단이 1개뿐이면 카드와 마무리 문구를 나눌 재료가 없다. 없는 내용을
        # 새로 지어내는 대신, 있는 문단을 그대로 양쪽에 재사용한다.
        cards = tuple(paragraphs)
        takeaway = paragraphs[0]
    else:
        cards = tuple(paragraphs[:-1])
        takeaway = paragraphs[-1]

    if len(cards) > MAX_CARDS:
        raise ShortsAdapterError(
            f"본문 카드로 쓸 문단이 {len(cards)}개로 ShortsScript의 최대 {MAX_CARDS}개를 "
            "초과합니다. 일부 문단을 임의로 생략하지 않고 변환을 중단합니다."
        )

    try:
        return ShortsScript(
            title=draft.title,
            subtitle="",
            cards=cards,
            takeaway=takeaway,
            brand=brand or DEFAULT_BRAND,
        )
    except ShortsScriptError as error:
        raise ShortsAdapterError(str(error)) from error


# --- MEDIA archive(5-27/5-29) 기반 Shorts downstream 연결 ---------------------


def approved_media_archive_record_to_shorts_script(
    record: MediaArchiveRecord, brand: str = DEFAULT_BRAND
) -> ShortsScript:
    """MEDIA Dashboard에서 승인된 Shorts archive 레코드를 ShortsScript로 변환한다.

    이 함수 자체는 새 변환 로직을 만들지 않는다 - record를 ``ShortDraft``로 감싼
    뒤 기존 ``short_draft_to_shorts_script()``를 그대로 호출할 뿐이다. 실제
    MP4 렌더링(content_engine.shorts_renderer)은 이 함수가 전혀 호출하지 않는다 -
    변환까지만 한다.

    조건(platform=="shorts", generation_status=="valid", review_status=="approved")을
    만족하지 않으면 ShortsAdapterError를 던진다 - 검증을 통과하지 못했거나 아직
    사람이 승인하지 않은 콘텐츠가 실수로 Shorts 대본으로 변환되는 것을 막는다.

    제목/본문은 ``record.final_title``/``record.final_body``를 쓴다 - 사람이
    MEDIA Dashboard에서 수정했다면(edited_title/edited_body) 그 수정본이,
    수정하지 않았다면 AI 생성 결과가 그대로 쓰인다(5-29 설계).
    """
    if record.platform != "shorts":
        raise ShortsAdapterError(f"platform이 'shorts'가 아닙니다: {record.platform!r}")
    if record.generation_status != "valid":
        raise ShortsAdapterError(f"generation_status가 'valid'가 아닙니다: {record.generation_status!r}")
    if record.review_status != "approved":
        raise ShortsAdapterError(f"review_status가 'approved'가 아닙니다: {record.review_status!r}")

    draft = ShortDraft(
        title=record.final_title,
        body=record.final_body,
        source_url=record.source_url,
        evidence=record.evidence,
        evidence_unit_ids=record.evidence_unit_ids,
    )
    return short_draft_to_shorts_script(draft, brand=brand)


def shorts_script_output_path(output_dir: Path | str, content_id: str) -> Path:
    """content_id로부터 결정적인 저장 경로를 계산한다(파일 존재 여부 확인,
    승인 POST의 자동 연결, CLI가 전부 이 함수 하나로 같은 경로 계산 규칙을
    공유한다)."""
    return Path(output_dir) / f"{content_id}.json"


def save_approved_shorts_script(
    record: MediaArchiveRecord,
    output_dir: Path | str,
    brand: str = DEFAULT_BRAND,
    created_at: str | None = None,
) -> Path:
    """승인된 Shorts archive 레코드를 ``<output_dir>/<content_id>.json``으로
    원자적으로(tempfile + replace) 저장한다.

    이미 같은 content_id 파일이 있으면 다시 쓰지 않고 그 경로만 반환한다
    (5-29 설계: "이미 생성된 경우에는 중복 생성하지 않는다" - 한 번 저장된
    Script는 스냅샷으로 고정되며, 다시 만들려면 사람이 파일을 직접 지워야
    한다. Blog의 "게시 완료는 사람이 명시적으로 기록해야 한다"는 원칙과
    같은 성격이다).

    저장 스키마는 ``ShortsScript.from_dict()``가 읽는 5개 키(title/subtitle/
    cards/takeaway/brand)를 그대로 포함하고, content_id/knowledge_id/
    platform/created_at은 추적용으로 추가한 필드다 - ``ShortsScript.from_dict()``
    는 이 추가 필드를 그냥 무시하므로 ``scripts/render_youtube_short.py
    --input``에 이 파일을 그대로 넘길 수 있다(스키마 호환 유지).

    변환 자체가 실패하면(``approved_media_archive_record_to_shorts_script()``가
    던지는 ``ShortsAdapterError``) 파일을 쓰지 않고 그대로 예외를 전파한다.
    """
    output_path = shorts_script_output_path(output_dir, record.content_id)
    if output_path.exists():
        return output_path

    script = approved_media_archive_record_to_shorts_script(record, brand=brand)

    payload = {
        "content_id": record.content_id,
        "knowledge_id": record.knowledge_id,
        "platform": record.platform,
        "title": script.title,
        "subtitle": script.subtitle,
        "cards": list(script.cards),
        "takeaway": script.takeaway,
        "brand": script.brand,
        "created_at": created_at or utc_now(),
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=output_path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temp_path = Path(handle.name)
    temp_path.replace(output_path)
    return output_path
