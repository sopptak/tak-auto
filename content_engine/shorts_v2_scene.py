"""Shorts 2.0(6-41) 장면 설계 모델 - "영상에 글을 넣는 시스템"이 아니라
"영상 자체를 설계하는 시스템"의 입력 스키마.

6-40의 ``ShortsScript``(title/cards/takeaway)는 카드뉴스 구조를 전제한다.
6-41은 그 위에 새 레이어를 얹는다: 대본을 장면(scene) 목록으로 설계하고,
장면마다 duration/text/emphasis/visual/transition/audio cue를 정의한다.

    CONTENT IDEA -> HOOK -> BEAT SHEET -> SCENE PLAN(이 모듈)
                 -> ON-SCREEN TEXT / VISUAL / TIMING -> RENDER(shorts_v2_renderer)

타이밍 원칙:
- 모든 장면 길이는 음악 BPM의 박자(beat) 단위로 맞춘다 - 장면 전환이
  항상 박자 위에서 일어난다(beat sync).
- ``beats``를 생략하면 텍스트 길이로 최소 읽기 시간을 계산한 뒤 박자
  단위로 올림한다(문장 길이에 따른 표시시간 자동 조정).
- ``beats``를 직접 줘도 읽기 시간보다 짧으면 거부한다 - 글자를 못 읽는
  장면을 만들지 않는다.

표준 라이브러리만 사용한다(Pillow/ffmpeg 무관). ``data/``를 읽거나 쓰지 않는다.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from content_engine.shorts_script import DEFAULT_BRAND

WIDTH = 1080
HEIGHT = 1920

# YouTube Shorts 앱 UI(상단 검색/카메라, 하단 채널명·설명·음악 표시, 우측
# 좋아요/댓글/공유 버튼 열)가 덮는 영역을 피한 중요 요소 배치 영역.
# YouTube 편집기의 visual guide(https://support.google.com/youtube/answer/16215842)
# 가 경고하는 영역과 같은 목적 - 수치는 1080x1920 기준 보수적 근사치다.
SAFE_LEFT = 90
SAFE_TOP = 260
SAFE_RIGHT = WIDTH - 170  # 우측 액션 버튼 열
SAFE_BOTTOM = HEIGHT - 560  # 하단 채널명/설명/음악 영역
SAFE_BOX = (SAFE_LEFT, SAFE_TOP, SAFE_RIGHT, SAFE_BOTTOM)

MIN_TOTAL_SECONDS = 25.0
MAX_TOTAL_SECONDS = 45.0

# 한국어 숏폼 기준 체감 읽기 속도(공백 제외 글자 수/초). 6-40의 11자/초보다
# 조금 보수적으로 잡고, 장면 진입 애니메이션 시간(약 0.4초)을 더한다.
CHARS_PER_SECOND = 9.0
ENTRANCE_SECONDS = 0.4
MIN_SCENE_SECONDS = 1.2
MAX_HOOK_SECONDS = 3.0

STYLES = ("finance", "human", "ai")
LAYOUTS = ("center", "big", "list", "brand")
TRANSITIONS = ("cut", "punch", "dissolve")

_EMPHASIS = re.compile(r"\*([^*]+)\*")


class SceneSpecError(ValueError):
    """장면 설계 입력이 스키마/타이밍/분량 규칙을 어길 때 발생한다."""


@dataclass(frozen=True)
class Scene:
    role: str  # HOOK / PROBLEM / CONTEXT / INFO / INSIGHT / TAKEAWAY / BRAND
    text: str  # 화면 텍스트. "*단어*"는 강조, "\n"은 의도된 줄바꿈
    layout: str = "center"
    visual: str = ""  # 배경/그래픽 종류(렌더러가 스타일별로 해석)
    transition: str = "cut"  # 이 장면으로 "들어오는" 전환
    audio: tuple[str, ...] = ()  # 이 장면 시작 시 효과음 cue
    beats: int | None = None
    big: str = ""  # layout=big: 거대 숫자/단어, layout=list: 목록 제목 아래 항목은 items
    label: str = ""  # 칩 라벨(예: "01 상환능력")
    items: tuple[str, ...] = ()
    note: str = ""  # 작은 보조 문구(출처/주의 문구)
    music: str = ""  # "break" = 이 장면 동안 드럼 제거(호흡)
    voiceover: str = ""  # VERSION B(선택적 내레이션) 대본 - 이번 렌더에서는 미사용

    @property
    def plain_text(self) -> str:
        return _EMPHASIS.sub(r"\1", self.text)

    @property
    def emphasis(self) -> tuple[str, ...]:
        return tuple(_EMPHASIS.findall(self.text))

    @property
    def readable_chars(self) -> int:
        visible = self.plain_text + self.big + self.label + "".join(self.items)
        return len(re.sub(r"\s", "", visible))


@dataclass(frozen=True)
class TimedScene:
    scene: Scene
    index: int
    start: float
    duration: float

    @property
    def end(self) -> float:
        return self.start + self.duration


@dataclass(frozen=True)
class ShortSpec:
    id: str
    style: str
    bpm: float
    idea: str
    scenes: tuple[Scene, ...]
    brand: str = DEFAULT_BRAND

    @property
    def beat_seconds(self) -> float:
        return 60.0 / self.bpm

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "ShortSpec":
        scenes_raw = data.get("scenes")
        if not isinstance(scenes_raw, list) or not scenes_raw:
            raise SceneSpecError("scenes는 비어 있지 않은 배열이어야 합니다.")
        scenes = []
        for raw in scenes_raw:
            if not isinstance(raw, Mapping):
                raise SceneSpecError("scene은 객체여야 합니다.")
            scenes.append(Scene(
                role=str(raw.get("role", "")),
                text=str(raw.get("text", "")),
                layout=str(raw.get("layout", "center")),
                visual=str(raw.get("visual", "")),
                transition=str(raw.get("transition", "cut")),
                audio=tuple(raw.get("audio", ())),
                beats=raw.get("beats"),
                big=str(raw.get("big", "")),
                label=str(raw.get("label", "")),
                items=tuple(raw.get("items", ())),
                note=str(raw.get("note", "")),
                music=str(raw.get("music", "")),
                voiceover=str(raw.get("voiceover", "")),
            ))
        spec = cls(
            id=str(data.get("id", "")),
            style=str(data.get("style", "")),
            bpm=float(data.get("bpm", 0) or 0),
            idea=str(data.get("idea", "")),
            scenes=tuple(scenes),
            brand=str(data.get("brand") or DEFAULT_BRAND),
        )
        validate_spec(spec)
        return spec

    @classmethod
    def load(cls, path: Path | str) -> "ShortSpec":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def min_read_seconds(scene: Scene) -> float:
    """장면을 읽는 데 필요한 최소 시간(진입 애니메이션 + 글자 수 / 읽기 속도)."""
    seconds = ENTRANCE_SECONDS + scene.readable_chars / CHARS_PER_SECOND
    return max(MIN_SCENE_SECONDS, seconds)


def item_reveal_times(timed: "TimedScene", beat_seconds: float) -> tuple[float, ...]:
    """list 레이아웃 항목이 하나씩 등장하는 시각 - 박자마다 1개(렌더러/효과음 공용)."""
    return tuple(timed.start + beat_seconds * (k + 1) for k in range(len(timed.scene.items)))


def scene_beats(scene: Scene, beat_seconds: float) -> int:
    seconds = min_read_seconds(scene)
    if scene.items:  # 마지막 항목이 등장한 뒤에도 1초는 머물러야 읽힌다
        seconds = max(seconds, beat_seconds * (len(scene.items) + 1) + 1.0)
    needed = math.ceil(seconds / beat_seconds - 1e-9)
    if scene.beats is None:
        return max(1, needed)
    if scene.beats < needed:
        raise SceneSpecError(
            f"{scene.role} 장면 '{scene.plain_text[:20]}'은 {scene.beats}박({scene.beats * beat_seconds:.2f}초)인데 "
            f"읽는 데 최소 {needed}박이 필요합니다 - 문장을 줄이거나 박자를 늘리세요."
        )
    return scene.beats


def build_timeline(spec: ShortSpec) -> tuple[TimedScene, ...]:
    timed = []
    t = 0.0
    for index, scene in enumerate(spec.scenes):
        duration = scene_beats(scene, spec.beat_seconds) * spec.beat_seconds
        timed.append(TimedScene(scene=scene, index=index, start=t, duration=duration))
        t += duration
    return tuple(timed)


def total_seconds(spec: ShortSpec) -> float:
    timeline = build_timeline(spec)
    return timeline[-1].end


def validate_spec(spec: ShortSpec) -> None:
    if spec.style not in STYLES:
        raise SceneSpecError(f"style은 {STYLES} 중 하나여야 합니다: {spec.style!r}")
    if not 50 <= spec.bpm <= 180:
        raise SceneSpecError(f"bpm이 비정상입니다: {spec.bpm}")
    for scene in spec.scenes:
        if scene.layout not in LAYOUTS:
            raise SceneSpecError(f"layout은 {LAYOUTS} 중 하나여야 합니다: {scene.layout!r}")
        if scene.transition not in TRANSITIONS:
            raise SceneSpecError(f"transition은 {TRANSITIONS} 중 하나여야 합니다: {scene.transition!r}")
        if scene.layout != "brand" and not (scene.text or scene.big or scene.items):
            raise SceneSpecError(f"{scene.role} 장면에 화면 텍스트가 없습니다.")
        lines = [line for line in scene.plain_text.split("\n") if line.strip()]
        if len(lines) > 3:
            raise SceneSpecError(f"{scene.role} 장면 텍스트가 {len(lines)}줄입니다 - 한 화면 최대 3줄.")
    if spec.scenes[0].role != "HOOK":
        raise SceneSpecError("첫 장면은 HOOK이어야 합니다.")
    hook = build_timeline(spec)[0]
    if hook.duration > MAX_HOOK_SECONDS:
        raise SceneSpecError(f"HOOK이 {hook.duration:.2f}초 - 첫 장면은 {MAX_HOOK_SECONDS}초 안에 끝나야 합니다.")
    total = total_seconds(spec)
    if not MIN_TOTAL_SECONDS <= total <= MAX_TOTAL_SECONDS:
        raise SceneSpecError(f"전체 길이 {total:.1f}초 - {MIN_TOTAL_SECONDS:.0f}~{MAX_TOTAL_SECONDS:.0f}초 범위여야 합니다.")
