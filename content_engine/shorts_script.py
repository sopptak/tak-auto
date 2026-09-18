""""티몽의 지혜" Shorts 렌더러가 받는 대본 입력 모델과 화면별 노출 시간 계산.

TAK MEDIA의 ShortDraft(title + 단일 body 문자열)와는 별도로, 렌더러는 이미
"화면 단위로 나뉜" 대본만 입력으로 받는다 - 렌더링 엔진은 문장을 새로 나누거나
요약하지 않고, 주어진 cards를 그대로 화면에 배치하는 역할만 담당한다(문장 분할·
요약은 상위 콘텐츠 생성 단계의 책임).

이 모듈은 표준 라이브러리만 사용한다 - Pillow/ffmpeg에 의존하는 실제 이미지·영상
렌더링은 content_engine.shorts_renderer가 담당한다.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field


DEFAULT_BRAND = "티몽의 지혜"

MIN_CARDS = 1
MAX_CARDS = 8

COVER_MIN_SECONDS = 2.0
COVER_MAX_SECONDS = 3.0
CARD_MIN_SECONDS = 3.0
CARD_MAX_SECONDS = 5.0
TAKEAWAY_MIN_SECONDS = 3.0
TAKEAWAY_MAX_SECONDS = 4.0

# 한국어 숏폼 카드뉴스 기준 체감 읽기 속도(공백 제외 글자 수 / 초). 경험적 근사치.
_CHARS_PER_SECOND = 11.0


class ShortsScriptError(ValueError):
    """Shorts 대본 입력이 렌더러 스키마와 맞지 않을 때 발생한다."""


@dataclass(frozen=True)
class ShortsScript:
    """티몽의 지혜 Shorts 카드뉴스 대본.

    표지(title/subtitle) -> 본문 카드(cards, 3~5개 권장) -> 마무리(takeaway) 순으로
    화면이 구성된다. brand는 모든 화면 하단에 일관되게 표시된다.
    """

    title: str
    subtitle: str
    cards: tuple[str, ...]
    takeaway: str
    brand: str = DEFAULT_BRAND

    def __post_init__(self) -> None:
        if isinstance(self.cards, list):
            object.__setattr__(self, "cards", tuple(self.cards))
        _validate(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "ShortsScript":
        if not isinstance(data, Mapping):
            raise ShortsScriptError("대본 입력은 JSON 객체(dict)여야 합니다.")

        cards_raw = data.get("cards")
        if not isinstance(cards_raw, Sequence) or isinstance(cards_raw, (str, bytes)):
            raise ShortsScriptError("cards 필드는 문자열 배열이어야 합니다.")

        brand_raw = data.get("brand")
        brand = str(brand_raw).strip() if brand_raw else ""

        return cls(
            title=str(data.get("title") or "").strip(),
            subtitle=str(data.get("subtitle") or "").strip(),
            cards=tuple(str(card).strip() for card in cards_raw),
            takeaway=str(data.get("takeaway") or "").strip(),
            brand=brand or DEFAULT_BRAND,
        )

    @property
    def screen_texts(self) -> tuple[str, ...]:
        """cover, card1..cardN, takeaway 순서의 전체 화면 텍스트."""
        return (self.title, *self.cards, self.takeaway)


def _validate(script: ShortsScript) -> None:
    if not script.title:
        raise ShortsScriptError("title이 비어 있습니다.")
    if not script.takeaway:
        raise ShortsScriptError("takeaway가 비어 있습니다.")
    if not script.brand:
        raise ShortsScriptError("brand가 비어 있습니다.")
    if not script.cards:
        raise ShortsScriptError(f"cards가 비어 있습니다. 최소 {MIN_CARDS}개 이상 필요합니다.")
    if len(script.cards) > MAX_CARDS:
        raise ShortsScriptError(
            f"cards는 최대 {MAX_CARDS}개까지 지원합니다 (입력: {len(script.cards)}개)."
        )
    for index, card in enumerate(script.cards, start=1):
        if not card.strip():
            raise ShortsScriptError(f"cards[{index}]가 비어 있습니다.")


@dataclass(frozen=True)
class ScreenPlan:
    """렌더링 대상 화면 1개(표지/본문 카드/마무리)와 노출 시간(초)."""

    kind: str  # "cover" | "card" | "takeaway"
    text: str
    duration_seconds: float
    card_index: int | None = None  # 본문 카드의 1-base 순번 (표지/마무리는 None)
    card_total: int | None = None  # 본문 카드 총 개수 (표지/마무리는 None)


def _reading_seconds(text: str, minimum: float, maximum: float) -> float:
    length = len(text.replace("\n", "").replace(" ", ""))
    if length == 0:
        return minimum
    seconds = length / _CHARS_PER_SECOND
    return max(minimum, min(maximum, seconds))


def build_screen_plan(script: ShortsScript) -> tuple[ScreenPlan, ...]:
    """대본을 표지 -> 본문 카드 -> 마무리 화면 순서의 노출 계획으로 변환한다."""
    plans: list[ScreenPlan] = [
        ScreenPlan(
            kind="cover",
            text=script.title,
            duration_seconds=_reading_seconds(
                script.title + script.subtitle, COVER_MIN_SECONDS, COVER_MAX_SECONDS
            ),
        )
    ]
    card_total = len(script.cards)
    for position, card in enumerate(script.cards, start=1):
        plans.append(
            ScreenPlan(
                kind="card",
                text=card,
                duration_seconds=_reading_seconds(card, CARD_MIN_SECONDS, CARD_MAX_SECONDS),
                card_index=position,
                card_total=card_total,
            )
        )
    plans.append(
        ScreenPlan(
            kind="takeaway",
            text=script.takeaway,
            duration_seconds=_reading_seconds(
                script.takeaway, TAKEAWAY_MIN_SECONDS, TAKEAWAY_MAX_SECONDS
            ),
        )
    )
    return tuple(plans)


def total_duration_seconds(plans: Sequence[ScreenPlan], fade_seconds: float) -> float:
    """크로스페이드 전환(화면 사이 fade_seconds초 겹침)을 반영한 전체 영상 길이."""
    total = sum(plan.duration_seconds for plan in plans)
    if len(plans) > 1:
        total -= fade_seconds * (len(plans) - 1)
    return max(total, 0.0)
