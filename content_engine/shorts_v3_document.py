"""Shorts V3 Render Document(6-52, 6-53) - 렌더러가 읽는 유일한 콘텐츠 입력(정규화된 내부 표현).

    Shorts 콘텐츠 데이터(V3 문서 JSON / 기존 ShortsScript -> adapter)
        -> V3RenderDocument(이 모듈: 검증 + 템플릿 해석 + 박자 타임라인)
        -> shorts_v3_layout(레이아웃 엔진) -> shorts_v3_renderer(프레임 합성) -> MP4

렌더러는 Production Archive나 ShortsScript를 직접 읽지 않는다 - 이 문서만 읽는다.
콘텐츠(제목/장면/이미지/출처/CTA)와 템플릿(화면 틀)은 분리돼 있고, 문서는 템플릿의 일부
기본값(brand/cta/progress/audio)만 덮어쓸 수 있다.

검증 실패는 ``V3Error``(code: INVALID_DOCUMENT / INVALID_DURATION / INVALID_LAYOUT /
INVALID_TRANSITION / INVALID_IMAGE_SPEC / EMPTY_SCENE / TIMING_MISMATCH / INVALID_TEMPLATE).
표준 라이브러리만 사용한다. ``data/``를 읽거나 쓰지 않는다.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from urllib.parse import urlsplit
from dataclasses import dataclass, field
from pathlib import Path

from content_engine.shorts_v2_scene import ENTRANCE_SECONDS
from content_engine.shorts_v3_template import (  # noqa: F401 - 6-52 호환 재노출
    TEMPLATE_DIR, V3Error, canonical_sha256, deep_merge, load_template, resolve_template,
)

SCHEMA = "shorts_v3_document/1"
TRANSITIONS = ("cut", "punch", "dissolve", "fade", "slide")  # fade = dissolve 별칭
IMAGE_FITS = ("cover", "contain", "crop")  # crop = cover 별칭
_POSITIONS = {"center": (0.5, 0.5), "top": (0.5, 0.0), "bottom": (0.5, 1.0), "left": (0.0, 0.5), "right": (1.0, 0.5)}
_LATIN = re.compile(r"[A-Za-z0-9]")
# 6-52 호환: 예전 이름. 이제 모든 문서 오류는 V3Error(code)다.
V3DocumentError = V3Error


@dataclass(frozen=True)
class Media:
    path: str = ""
    alt: str = ""
    source: str = ""
    fit: str = ""  # cover | contain, 비우면 템플릿 image.fit
    position: tuple[float, float] = (0.5, 0.5)  # 기준점(focal point, 0~1)
    scale: float = 1.0  # 기준점 주위 확대(1.0~4.0)


@dataclass(frozen=True)
class Source:
    value: str
    label: str = ""  # 비우면 템플릿 text.source.label("출처")

    def display(self, template: Mapping) -> str:
        spec = template["text"]["source"]
        label = self.label or spec.get("label", "")
        value = readable_source(self.value, template)
        return f"{label}{spec.get('separator', ' · ')}{value}" if label else value


def readable_source(value: str, template: Mapping) -> str:
    """URL이면 화면에는 사람이 읽는 이름만: 템플릿 source_labels(도메인 -> 매체 이름), 없으면 도메인.
    원문 URL은 문서에 그대로 남는다."""
    if not re.match(r"https?://", value):
        return value
    host = urlsplit(value).netloc.lower().removeprefix("www.")
    labels = template.get("source_labels", {})
    for domain, name in labels.items():
        if host == domain or host.endswith("." + domain):
            return name
    return host or value


@dataclass(frozen=True)
class V3Scene:
    layout: str = "text_focus"
    image: Media | None = None
    headline: str = ""
    body: str = ""  # 빈 줄("\n\n")로 문단을 나눌 수 있다
    subtitle: str = ""  # 하단 자막 한 줄
    source: Source | None = None  # footer 출처(본문에 넣지 않는다)
    duration: float | None = None  # 생략하면 글자 수로 자동(박자 단위로 올림)
    transition: str = ""  # 비우면 템플릿 transition.default
    emphasis: tuple[str, ...] = ()  # 강조할 구절(본문/헤드라인 안에서 찾아 *구절*로 표시)
    audio: tuple[str, ...] = ("whoosh",)  # 장면 시작 효과음 cue(6-41 합성기)

    # 6-52 호환 속성
    @property
    def image_position(self) -> tuple[float, float]:
        return self.image.position if self.image else (0.5, 0.5)

    @property
    def image_scale(self) -> float:
        return self.image.scale if self.image else 1.0

    def marked(self, text: str) -> str:
        for phrase in self.emphasis:
            if phrase and phrase in text and f"*{phrase}*" not in text:
                text = text.replace(phrase, f"*{phrase}*", 1)
        return text

    @property
    def visible_text(self) -> str:
        return re.sub(r"[\s*]", "", self.headline + self.body + self.subtitle)


@dataclass(frozen=True)
class V3RenderDocument:
    id: str
    title: str
    scenes: tuple[V3Scene, ...]
    template: dict  # 해석·검증이 끝난 최종 템플릿(문서 덮어쓰기 포함)
    lineage: dict = field(default_factory=dict)
    base_dir: Path = Path(".")  # 이미지 상대 경로 기준(문서 파일 위치)
    content: dict = field(default_factory=dict, compare=False)  # 원본 문서 dict(해시/lineage용)

    @property
    def content_id(self) -> str:
        return str(self.lineage.get("content_id") or "")

    @property
    def generation_id(self) -> str | None:
        return self.lineage.get("generation_id")

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

    def transition_of(self, scene: V3Scene) -> str:
        name = scene.transition or self.template["transition"].get("default", "punch")
        return "dissolve" if name == "fade" else name

    def image_path(self, scene: V3Scene) -> Path | None:
        if scene.image is None or not scene.image.path:
            return None
        p = Path(scene.image.path)
        return p if p.is_absolute() else self.base_dir / p

    def document_sha256(self) -> str:
        return canonical_sha256(self.content)

    def template_sha256(self) -> str:
        return canonical_sha256(self.template)

    # ---- 읽기 ----
    @classmethod
    def from_dict(cls, data: Mapping, base_dir: Path | str = ".", template: dict | None = None) -> "V3RenderDocument":
        if not isinstance(data, Mapping):
            raise V3Error("INVALID_DOCUMENT", "문서는 JSON 객체여야 합니다.")
        if data.get("schema", SCHEMA) != SCHEMA:
            raise V3Error("INVALID_DOCUMENT", f"지원하지 않는 schema: {data.get('schema')!r}")
        overrides: dict = {k: data[k] for k in ("brand", "progress", "audio") if isinstance(data.get(k), Mapping)}
        if isinstance(data.get("brand"), str):
            overrides["brand"] = {"text": data["brand"]}
        if isinstance(data.get("cta"), str):
            overrides.setdefault("brand", {})["cta"] = data["cta"]
        if isinstance(data.get("progress"), bool):
            overrides["progress"] = {"enabled": data["progress"]}
        tpl = resolve_template(template if template is not None else data.get("template", "default"), overrides)
        raw_scenes = data.get("scenes")
        if not isinstance(raw_scenes, list) or not raw_scenes:
            raise V3Error("INVALID_DOCUMENT", "scenes는 비어 있지 않은 배열이어야 합니다.")
        lineage = data.get("lineage") or {}
        if not isinstance(lineage, Mapping):
            raise V3Error("INVALID_DOCUMENT", "lineage는 객체여야 합니다.")
        doc = cls(
            id=str(data.get("id", "")),
            title=str(data.get("title", "")).strip(),
            scenes=tuple(_scene(raw, i) for i, raw in enumerate(raw_scenes)),
            template=tpl,
            lineage=dict(lineage),
            base_dir=Path(base_dir),
            content=json.loads(json.dumps(dict(data), ensure_ascii=False)),
        )
        validate_document(doc, data.get("expected_duration"))
        return doc

    @classmethod
    def load(cls, path: Path | str, template: dict | None = None) -> "V3RenderDocument":
        path = Path(path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise V3Error("INVALID_DOCUMENT", f"문서를 읽을 수 없습니다: {path}: {error}") from error
        return cls.from_dict(data, base_dir=path.parent, template=template)


ShortsV3Document = V3RenderDocument  # 6-52 이름


def _position(raw, index: int) -> tuple[float, float]:
    if raw is None:
        return (0.5, 0.5)
    if isinstance(raw, str):
        if raw not in _POSITIONS:
            raise V3Error("INVALID_IMAGE_SPEC", f"scene {index}: position은 {tuple(_POSITIONS)} 또는 [x, y]여야 합니다: {raw!r}")
        return _POSITIONS[raw]
    if isinstance(raw, Mapping):  # {"x": 0.5, "y": 0.3} - 사람이 읽기 쉬운 형태
        raw = (raw.get("x", 0.5), raw.get("y", 0.5))
    if not (isinstance(raw, (list, tuple)) and len(raw) == 2):
        raise V3Error("INVALID_IMAGE_SPEC", f"scene {index}: position [x, y]가 잘못됐습니다: {raw!r}")
    try:
        x, y = float(raw[0]), float(raw[1])
    except (TypeError, ValueError) as error:
        raise V3Error("INVALID_IMAGE_SPEC", f"scene {index}: position 값은 숫자여야 합니다: {raw!r}") from error
    return (min(1.0, max(0.0, x)), min(1.0, max(0.0, y)))


def _media(raw, scene: Mapping, index: int) -> Media | None:
    if raw in (None, ""):
        return None
    if isinstance(raw, str):
        raw = {"path": raw}
    if not isinstance(raw, Mapping):
        raise V3Error("INVALID_IMAGE_SPEC", f"scene {index}: image는 경로 문자열이나 객체여야 합니다: {raw!r}")
    fit = str(raw.get("fit", scene.get("image_fit", "")))
    if fit and fit not in IMAGE_FITS:
        raise V3Error("INVALID_IMAGE_SPEC", f"scene {index}: image fit은 {IMAGE_FITS} 중 하나여야 합니다: {fit!r}")
    try:
        scale = float(raw.get("scale", scene.get("image_scale", 1.0)))
    except (TypeError, ValueError) as error:
        raise V3Error("INVALID_IMAGE_SPEC", f"scene {index}: image scale은 숫자여야 합니다.") from error
    if not 1.0 <= scale <= 4.0:
        raise V3Error("INVALID_IMAGE_SPEC", f"scene {index}: image scale은 1.0~4.0이어야 합니다: {scale}")
    return Media(path=str(raw.get("path", "")), alt=str(raw.get("alt", "")), source=str(raw.get("source", "")),
                 fit="cover" if fit == "crop" else fit, position=_position(raw.get("position", scene.get("image_position")), index), scale=scale)


def _source(raw, index: int) -> Source | None:
    if raw in (None, ""):
        return None
    if isinstance(raw, str):
        return Source(value=raw.strip())
    if isinstance(raw, Mapping) and str(raw.get("value", "")).strip():
        return Source(value=str(raw["value"]).strip(), label=str(raw.get("label", "")).strip())
    raise V3Error("INVALID_DOCUMENT", f"scene {index}: source는 문자열이나 {{label, value}} 객체여야 합니다: {raw!r}")


def _scene(raw, index: int) -> V3Scene:
    if not isinstance(raw, Mapping):
        raise V3Error("INVALID_DOCUMENT", f"scene {index}는 객체여야 합니다.")
    image = _media(raw.get("image") if "image" in raw else raw.get("media"), raw, index)
    duration = raw.get("duration")
    if duration is not None:
        try:
            duration = float(duration)
        except (TypeError, ValueError) as error:
            raise V3Error("INVALID_DURATION", f"scene {index}: duration이 숫자가 아닙니다: {duration!r}") from error
    audio = raw.get("audio", ("whoosh",))
    if isinstance(audio, str) or not all(isinstance(a, str) for a in audio):
        raise V3Error("INVALID_DOCUMENT", f"scene {index}: audio는 효과음 이름 배열이어야 합니다: {audio!r}")
    return V3Scene(
        layout=str(raw.get("layout", "image_top" if image else "text_focus")),
        image=image,
        headline=str(raw.get("headline", "")).strip(),
        body=str(raw.get("body", "")).strip(),
        subtitle=str(raw.get("subtitle", "")).strip(),
        source=_source(raw.get("source"), index),
        duration=duration,
        transition=str(raw.get("transition", "")),
        emphasis=tuple(str(e) for e in raw.get("emphasis", ())),
        audio=tuple(audio),
    )


def validate_document(doc: V3RenderDocument, expected_duration=None) -> None:
    tpl = doc.template
    if not doc.title:
        raise V3Error("INVALID_DOCUMENT", "title이 비어 있습니다.")
    timing = tpl["timing"]
    min_scene, max_scene = float(timing["min_scene_seconds"]), float(timing.get("max_scene_seconds", 60))
    for i, s in enumerate(doc.scenes):
        if s.layout not in tpl["layouts"]:
            raise V3Error("INVALID_LAYOUT", f"scene {i}: layout {s.layout!r}이 템플릿에 없습니다({tuple(tpl['layouts'])}).")
        if s.transition and s.transition not in TRANSITIONS:
            raise V3Error("INVALID_TRANSITION", f"scene {i}: transition은 {TRANSITIONS} 중 하나여야 합니다: {s.transition!r}")
        if not (s.image or s.headline or s.body):
            raise V3Error("EMPTY_SCENE", f"scene {i}: image/headline/body 중 하나는 있어야 합니다.")
        if s.duration is not None:
            if not math.isfinite(s.duration) or s.duration <= 0:
                raise V3Error("INVALID_DURATION", f"scene {i}: duration은 0보다 커야 합니다: {s.duration}")
            if not min_scene <= s.duration <= max_scene:
                raise V3Error("INVALID_DURATION", f"scene {i}: duration {s.duration}초 - {min_scene}~{max_scene}초 범위여야 합니다.")
            need = min_read_seconds(s, tpl)
            if s.duration < need:
                raise V3Error("INVALID_DURATION", f"scene {i}: {s.duration}초로는 글을 다 읽을 수 없습니다(최소 {need:.1f}초).")
    if expected_duration is not None:  # 문서가 전체 길이를 선언했다면 장면 합계와 맞아야 한다
        total = build_v3_timeline(doc)[-1].end
        if abs(float(expected_duration) - total) > doc.beat_seconds:
            raise V3Error("TIMING_MISMATCH", f"expected_duration {expected_duration}초 != 장면 합계 {total:.2f}초")


def min_read_seconds(scene: V3Scene, template: Mapping) -> float:
    """읽기 시간: 한글 9자/초, 라틴 문자는 더 빠르게(템플릿 timing) + 진입 애니메이션."""
    timing = template["timing"]
    text = scene.visible_text
    if not text:
        return float(timing["image_only_seconds"])
    latin = len(_LATIN.findall(text))
    seconds = ENTRANCE_SECONDS + (len(text) - latin) / float(timing.get("chars_per_second", 9.0)) \
        + latin / float(timing.get("latin_chars_per_second", 15.0))
    return min(float(timing.get("max_scene_seconds", 60)), max(float(timing["min_scene_seconds"]), seconds))


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


def build_v3_timeline(doc: V3RenderDocument) -> tuple[TimedV3Scene, ...]:
    """장면 길이를 박자 단위로 올린다 - 전환이 음악 박자 위에서 일어난다(6-41 원칙 유지)."""
    beat = doc.beat_seconds
    min_scene = float(doc.template["timing"]["min_scene_seconds"])
    out, t = [], 0.0
    for i, s in enumerate(doc.scenes):
        seconds = s.duration if s.duration is not None else min_read_seconds(s, doc.template)
        beats = max(1, math.ceil(seconds / beat - 1e-9))
        out.append(TimedV3Scene(s, i, t, beats * beat, beats))
        t += beats * beat
    if doc.brand.get("end_card", True):
        seconds = max(min_scene, float(doc.brand.get("end_card_seconds", 2.0)))
        beats = max(1, math.ceil(seconds / beat - 1e-9))
        out.append(TimedV3Scene(None, len(out), t, beats * beat, beats))
    return tuple(out)
