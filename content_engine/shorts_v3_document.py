"""Shorts V3(6-52) 문서 모델 - 콘텐츠 데이터(ShortsV3Document)와 화면 틀(template)을 분리한다.

    CONTENT DATA(문서 JSON)  +  TEMPLATE(content_engine/shorts_v3_templates/<name>.json)
                 -> 타임라인(박자 단위) -> shorts_v3_renderer(레이아웃 엔진) -> MP4

- 문서: 제목, 장면(이미지/헤드라인/본문/자막/출처/길이/전환/강조), 브랜드·CTA·진행 표시·오디오
  덮어쓰기, lineage. 사람이 JSON으로 직접 고친다.
- 템플릿: 화면 크기, 프레임 위치, 폰트 크기 범위, 레이아웃 기하(layout_type -> 영역 비율),
  진행 표시·오디오·브랜드 기본값. 렌더러 코드에 이 값들을 하드코딩하지 않는다.

표준 라이브러리만 사용한다. ``data/``를 읽거나 쓰지 않는다.
"""

from __future__ import annotations

import copy
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from content_engine.shorts_v2_scene import CHARS_PER_SECOND, ENTRANCE_SECONDS, STYLES, TRANSITIONS

SCHEMA = "shorts_v3_document/1"
TEMPLATE_DIR = Path(__file__).resolve().parent / "shorts_v3_templates"
_POSITIONS = {"center": (0.5, 0.5), "top": (0.5, 0.0), "bottom": (0.5, 1.0), "left": (0.0, 0.5), "right": (1.0, 0.5)}


class V3DocumentError(ValueError):
    """문서/템플릿이 스키마 규칙을 어길 때 발생한다."""


def deep_merge(base: Mapping, override: Mapping | None) -> dict:
    out = copy.deepcopy(dict(base))
    for key, value in (override or {}).items():
        out[key] = deep_merge(out[key], value) if isinstance(value, Mapping) and isinstance(out.get(key), Mapping) else value
    return out


def load_template(name_or_path: str | Path) -> dict:
    path = Path(name_or_path)
    if not path.suffix:
        path = TEMPLATE_DIR / f"{name_or_path}.json"
    if not path.exists():
        raise V3DocumentError(f"템플릿이 없습니다: {path}")
    template = json.loads(path.read_text(encoding="utf-8"))
    for key in ("canvas", "frames", "text", "layouts", "progress", "audio", "brand", "timing", "look"):
        if key not in template:
            raise V3DocumentError(f"템플릿에 '{key}'가 없습니다: {path}")
    if template["audio"].get("background") not in STYLES:
        raise V3DocumentError(f"audio.background는 {STYLES} 중 하나여야 합니다.")
    return template


@dataclass(frozen=True)
class Media:
    path: str = ""
    alt: str = ""
    source: str = ""


@dataclass(frozen=True)
class V3Scene:
    layout: str = "text_focus"
    image: Media | None = None
    image_position: tuple[float, float] = (0.5, 0.5)  # 이미지에서 잘라낼 때 기준점(0~1)
    image_scale: float = 1.0  # 1 이상이면 기준점 주위를 확대
    headline: str = ""
    body: str = ""
    subtitle: str = ""  # 하단 자막 한 줄
    source: str = ""  # 하단 footer 출처(본문에 넣지 않는다)
    duration: float | None = None  # 생략하면 글자 수로 자동(박자 단위로 올림)
    transition: str = "punch"
    emphasis: tuple[str, ...] = ()  # 강조할 구절(본문/헤드라인 안에서 찾아 *구절*로 표시)
    audio: tuple[str, ...] = ("whoosh",)  # 장면 시작 효과음 cue(6-41 합성기)

    def marked(self, text: str) -> str:
        for phrase in self.emphasis:
            if phrase and phrase in text and f"*{phrase}*" not in text:
                text = text.replace(phrase, f"*{phrase}*", 1)
        return text

    @property
    def readable_chars(self) -> int:
        return len(re.sub(r"[\s*]", "", self.headline + self.body + self.subtitle))


@dataclass(frozen=True)
class ShortsV3Document:
    id: str
    title: str
    scenes: tuple[V3Scene, ...]
    template: dict
    lineage: dict = field(default_factory=dict)
    base_dir: Path = Path(".")  # 이미지 상대 경로 기준(문서 파일 위치)

    @property
    def brand(self) -> dict:
        return self.template["brand"]

    @property
    def progress(self) -> dict:
        return self.template["progress"]

    @property
    def audio(self) -> dict:
        return self.template["audio"]

    @property
    def beat_seconds(self) -> float:
        return 60.0 / float(self.audio["bpm"])

    def image_path(self, scene: V3Scene) -> Path | None:
        if scene.image is None or not scene.image.path:
            return None
        p = Path(scene.image.path)
        return p if p.is_absolute() else self.base_dir / p

    # ---- 읽기 ----
    @classmethod
    def from_dict(cls, data: Mapping, base_dir: Path | str = ".", template: dict | None = None) -> "ShortsV3Document":
        if not isinstance(data, Mapping):
            raise V3DocumentError("문서는 JSON 객체여야 합니다.")
        if data.get("schema", SCHEMA) != SCHEMA:
            raise V3DocumentError(f"지원하지 않는 schema: {data.get('schema')!r}")
        base = template or load_template(data.get("template", "default"))
        # 문서가 템플릿 기본값 일부(브랜드/CTA/진행 표시/오디오)를 덮어쓸 수 있다
        overrides = {k: data[k] for k in ("brand", "progress", "audio") if isinstance(data.get(k), Mapping)}
        if isinstance(data.get("brand"), str):
            overrides["brand"] = {"text": data["brand"]}
        if isinstance(data.get("cta"), str):
            overrides.setdefault("brand", {})["cta"] = data["cta"]
        if isinstance(data.get("progress"), bool):
            overrides["progress"] = {"enabled": data["progress"]}
        tpl = deep_merge(base, overrides)
        raw_scenes = data.get("scenes")
        if not isinstance(raw_scenes, list) or not raw_scenes:
            raise V3DocumentError("scenes는 비어 있지 않은 배열이어야 합니다.")
        doc = cls(
            id=str(data.get("id", "")),
            title=str(data.get("title", "")).strip(),
            scenes=tuple(_scene(raw, i) for i, raw in enumerate(raw_scenes)),
            template=tpl,
            lineage=dict(data.get("lineage") or {}),
            base_dir=Path(base_dir),
        )
        validate_document(doc)
        return doc

    @classmethod
    def load(cls, path: Path | str, template: dict | None = None) -> "ShortsV3Document":
        path = Path(path)
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")), base_dir=path.parent, template=template)


def _media(raw) -> Media | None:
    if raw in (None, ""):
        return None
    if isinstance(raw, str):
        return Media(path=raw)
    if isinstance(raw, Mapping):
        return Media(path=str(raw.get("path", "")), alt=str(raw.get("alt", "")), source=str(raw.get("source", "")))
    raise V3DocumentError(f"image는 경로 문자열이나 객체여야 합니다: {raw!r}")


def _position(raw) -> tuple[float, float]:
    if raw is None:
        return (0.5, 0.5)
    if isinstance(raw, str):
        if raw not in _POSITIONS:
            raise V3DocumentError(f"image_position은 {tuple(_POSITIONS)} 또는 [x, y]여야 합니다: {raw!r}")
        return _POSITIONS[raw]
    x, y = raw
    return (min(1.0, max(0.0, float(x))), min(1.0, max(0.0, float(y))))


def _scene(raw, index: int) -> V3Scene:
    if not isinstance(raw, Mapping):
        raise V3DocumentError(f"scene {index}는 객체여야 합니다.")
    image = _media(raw.get("image") if "image" in raw else raw.get("media"))
    duration = raw.get("duration")
    return V3Scene(
        layout=str(raw.get("layout", "image_top" if image else "text_focus")),
        image=image,
        image_position=_position(raw.get("image_position")),
        image_scale=float(raw.get("image_scale", 1.0)),
        headline=str(raw.get("headline", "")).strip(),
        body=str(raw.get("body", "")).strip(),
        subtitle=str(raw.get("subtitle", "")).strip(),
        source=str(raw.get("source", "")).strip(),
        duration=None if duration is None else float(duration),
        transition=str(raw.get("transition", "punch")),
        emphasis=tuple(str(e) for e in raw.get("emphasis", ())),
        audio=tuple(raw.get("audio", ("whoosh",))),
    )


def validate_document(doc: ShortsV3Document) -> None:
    tpl = doc.template
    if not doc.title:
        raise V3DocumentError("title이 비어 있습니다.")
    min_scene = float(tpl["timing"]["min_scene_seconds"])
    for i, s in enumerate(doc.scenes):
        if s.layout not in tpl["layouts"]:
            raise V3DocumentError(f"scene {i}: layout {s.layout!r}이 템플릿에 없습니다({tuple(tpl['layouts'])}).")
        if s.transition not in TRANSITIONS:
            raise V3DocumentError(f"scene {i}: transition은 {TRANSITIONS} 중 하나여야 합니다: {s.transition!r}")
        if not (s.image or s.headline or s.body):
            raise V3DocumentError(f"scene {i}: image/headline/body 중 하나는 있어야 합니다.")
        if not 1.0 <= s.image_scale <= 4.0:
            raise V3DocumentError(f"scene {i}: image_scale은 1.0~4.0이어야 합니다: {s.image_scale}")
        if s.duration is not None and s.duration < min_scene:
            raise V3DocumentError(f"scene {i}: duration {s.duration}초 - 최소 {min_scene}초.")
        if s.duration is not None and s.duration < min_read_seconds(s, tpl):
            raise V3DocumentError(f"scene {i}: {s.duration}초로는 글을 다 읽을 수 없습니다(최소 {min_read_seconds(s, tpl):.1f}초).")


def min_read_seconds(scene: V3Scene, template: Mapping) -> float:
    timing = template["timing"]
    if not scene.readable_chars:
        return float(timing["image_only_seconds"])
    return max(float(timing["min_scene_seconds"]), ENTRANCE_SECONDS + scene.readable_chars / CHARS_PER_SECOND)


@dataclass(frozen=True)
class TimedV3Scene:
    scene: V3Scene | None  # None = 브랜드 엔드카드
    index: int
    start: float
    duration: float
    beats: int

    @property
    def end(self) -> float:
        return self.start + self.duration


def build_v3_timeline(doc: ShortsV3Document) -> tuple[TimedV3Scene, ...]:
    """장면 길이를 박자 단위로 올린다 - 전환이 음악 박자 위에서 일어난다(6-41 원칙 유지)."""
    beat = doc.beat_seconds
    out, t = [], 0.0
    for i, s in enumerate(doc.scenes):
        seconds = s.duration if s.duration is not None else min_read_seconds(s, doc.template)
        beats = max(1, math.ceil(seconds / beat - 1e-9))
        out.append(TimedV3Scene(s, i, t, beats * beat, beats))
        t += beats * beat
    if doc.brand.get("end_card", True):
        beats = max(1, math.ceil(float(doc.brand.get("end_card_seconds", 2.0)) / beat - 1e-9))
        out.append(TimedV3Scene(None, len(out), t, beats * beat, beats))
    return tuple(out)
