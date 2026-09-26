"""Shorts V3 템플릿 해석기(6-53) - 템플릿 파일 로드 + 문서 덮어쓰기 병합 + 검증 + 해시.

템플릿 = 화면 틀(캔버스, 안전영역, 프레임, 글자 스타일, 레이아웃 영역, 이미지/전환/진행 표시/
오디오/브랜드/타이밍 기본값). 콘텐츠(제목/장면/이미지/출처)는 넣지 않는다.
검증에 실패하면 ``V3Error(code="INVALID_TEMPLATE")``. 표준 라이브러리만 사용한다.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path

TEMPLATE_DIR = Path(__file__).resolve().parent / "shorts_v3_templates"
CANVAS = (1080, 1920)
AUDIO_BACKGROUNDS = ("finance", "human", "ai")  # 6-41 합성 음악 스타일
LOOK_NAMES = ("finance", "human", "ai")  # 6-41 팔레트(shorts_v2_renderer.LOOKS)
TEXT_ROLES = ("title", "headline", "body", "subtitle", "source")
REQUIRED = ("canvas", "safe_area", "look", "frames", "footer_rows", "text", "layouts", "image", "transition",
            "animation", "progress", "audio", "brand", "timing")


class V3Error(ValueError):
    """V3 파이프라인 오류. ``code``는 품질 게이트/배치 결과에 그대로 기록되는 오류 코드다."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message


def deep_merge(base: Mapping, override: Mapping | None) -> dict:
    out = copy.deepcopy(dict(base))
    for key, value in (override or {}).items():
        out[key] = deep_merge(out[key], value) if isinstance(value, Mapping) and isinstance(out.get(key), Mapping) else value
    return out


def canonical_sha256(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def load_template(name_or_path: str | Path) -> dict:
    path = Path(name_or_path)
    if not path.suffix:
        path = TEMPLATE_DIR / f"{name_or_path}.json"
    if not path.exists():
        raise V3Error("INVALID_TEMPLATE", f"템플릿이 없습니다: {path}")
    try:
        template = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise V3Error("INVALID_TEMPLATE", f"템플릿 JSON 오류: {path}: {error}") from error
    validate_template(template)
    return template


def resolve_template(name_or_path: str | Path | Mapping, overrides: Mapping | None = None) -> dict:
    """템플릿(이름/경로/이미 읽은 dict) + 문서 덮어쓰기 -> 검증된 최종 템플릿."""
    base = dict(name_or_path) if isinstance(name_or_path, Mapping) else load_template(name_or_path)
    resolved = deep_merge(base, overrides)
    validate_template(resolved)
    return resolved


def _rect(value, name: str) -> tuple[int, int, int, int]:
    if not (isinstance(value, (list, tuple)) and len(value) == 4 and all(isinstance(v, (int, float)) for v in value)):
        raise V3Error("INVALID_TEMPLATE", f"{name}은 [x0, y0, x1, y1]이어야 합니다: {value!r}")
    x0, y0, x1, y1 = value
    if not (x0 < x1 and y0 < y1):
        raise V3Error("INVALID_TEMPLATE", f"{name}의 크기가 0 이하입니다: {value!r}")
    return tuple(value)


def _inside(inner, outer) -> bool:
    return inner[0] >= outer[0] and inner[1] >= outer[1] and inner[2] <= outer[2] and inner[3] <= outer[3]


def validate_template(t: Mapping) -> None:
    missing = [k for k in REQUIRED if k not in t]
    if missing:
        raise V3Error("INVALID_TEMPLATE", f"템플릿에 없는 항목: {missing}")
    canvas = t["canvas"]
    if (canvas.get("width"), canvas.get("height")) != CANVAS or not 1 <= int(canvas.get("fps", 0)) <= 60:
        raise V3Error("INVALID_TEMPLATE", f"canvas는 {CANVAS[0]}x{CANVAS[1]}, fps 1~60이어야 합니다: {canvas}")
    safe = _rect(t["safe_area"], "safe_area")
    if not _inside(safe, (0, 0, *CANVAS)):
        raise V3Error("INVALID_TEMPLATE", f"safe_area가 화면 밖입니다: {safe}")
    if t["look"] not in LOOK_NAMES:
        raise V3Error("INVALID_TEMPLATE", f"look은 {LOOK_NAMES} 중 하나여야 합니다: {t['look']!r}")
    frames = t["frames"]
    for name in ("title", "content", "footer"):
        if name not in frames:
            raise V3Error("INVALID_TEMPLATE", f"frames.{name}이 없습니다.")
        if not _inside(_rect(frames[name], f"frames.{name}"), safe):
            raise V3Error("INVALID_TEMPLATE", f"frames.{name}이 safe_area 밖입니다: {frames[name]}")
    if not frames["title"][3] <= frames["content"][1] <= frames["content"][3] <= frames["footer"][1]:
        raise V3Error("INVALID_TEMPLATE", "frames는 위에서부터 title -> content -> footer 순서로 겹치지 않아야 합니다.")
    for role in TEXT_ROLES:
        spec = t["text"].get(role)
        if not isinstance(spec, Mapping):
            raise V3Error("INVALID_TEMPLATE", f"text.{role}이 없습니다.")
        if not (8 <= int(spec.get("size_min", 0)) <= int(spec.get("size_max", 0)) <= 200 and int(spec.get("max_lines", 0)) >= 1):
            raise V3Error("INVALID_TEMPLATE", f"text.{role}의 size_min/size_max/max_lines가 잘못됐습니다: {spec}")
    layouts = t["layouts"]
    if not isinstance(layouts, Mapping) or not layouts:
        raise V3Error("INVALID_TEMPLATE", "layouts가 비어 있습니다.")
    for name, geometry in layouts.items():
        for variant in (geometry, geometry.get("fallback") or {}):
            regions = {k: v for k, v in variant.items() if k in ("image", "text")}
            if variant is geometry and not regions:
                raise V3Error("INVALID_TEMPLATE", f"layouts.{name}에 image/text 영역이 없습니다.")
            for k, v in regions.items():
                r = _rect(v, f"layouts.{name}.{k}")
                if not _inside(r, (0, 0, 1, 1)):
                    raise V3Error("INVALID_TEMPLATE", f"layouts.{name}.{k}는 CONTENT 기준 0~1 비율이어야 합니다: {v}")
    rows = t["footer_rows"]
    if any(int(rows.get(k, -1)) < 0 for k in ("progress", "source", "subtitle", "gap", "content_gap")):
        raise V3Error("INVALID_TEMPLATE", f"footer_rows(progress/source/subtitle/gap/content_gap)는 0 이상이어야 합니다: {rows}")
    if rows["progress"] + rows["source"] + 2 * rows["gap"] > frames["footer"][3] - frames["footer"][1]:  # 자막 줄은 남는 높이로 줄어든다
        raise V3Error("INVALID_TEMPLATE", "footer_rows(progress + source + gap)가 FOOTER 프레임 높이보다 큽니다.")
    if any(float(t["animation"].get(k, -1)) < 0 for k in ("body_delay", "paragraph_delay", "subtitle_delay", "source_delay", "image_in")):
        raise V3Error("INVALID_TEMPLATE", f"animation 지연 값은 0 이상이어야 합니다: {t['animation']}")
    if t["audio"].get("background") not in AUDIO_BACKGROUNDS or not 50 <= float(t["audio"].get("bpm", 0)) <= 180:
        raise V3Error("INVALID_TEMPLATE", f"audio.background는 {AUDIO_BACKGROUNDS}, bpm 50~180이어야 합니다.")
    if t["progress"].get("position", "footer") not in ("footer", "top") or t["progress"].get("mode", "time") not in ("time", "scene"):
        raise V3Error("INVALID_TEMPLATE", "progress.position은 footer|top, mode는 time|scene이어야 합니다.")
    if float(t["timing"].get("min_scene_seconds", 0)) <= 0:
        raise V3Error("INVALID_TEMPLATE", "timing.min_scene_seconds는 0보다 커야 합니다.")
