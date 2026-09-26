""""티몽의 지혜" 브랜드 카드뉴스 스타일 YouTube Shorts 렌더링 엔진.

content_engine.shorts_script.ShortsScript(표지/본문 카드/마무리로 이미 나뉜 대본)를
받아 1080x1920 무음 MP4를 생성한다.

- 이미지 합성: Pillow (그라데이션 배경, 반투명 카드 패널, 한국어 줄바꿈/자동 폰트 크기)
- 영상 인코딩: 시스템에 설치된 ffmpeg를 subprocess로 호출 (H.264, 오디오 트랙 없음)

디자인 원칙(요청 사항 요약):
    - 화면 자체는 거의 정지된 카드뉴스 + 화면 간 짧은 크로스페이드만 사용한다.
    - 줌/팬/흔들림/화려한 전환은 사용하지 않는다.
    - 렌더러는 "문장 배치"만 담당하고 대본 문장을 새로 만들거나 요약하지 않는다.
    - 브랜드명은 모든 화면 하단에 일관되게 표시한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import random
import subprocess
import tempfile
from typing import Sequence

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from .shorts_script import ScreenPlan, ShortsScript, build_screen_plan


class ShortsRenderError(RuntimeError):
    """Shorts 영상 렌더링(이미지 합성/ffmpeg 인코딩/검증)이 실패했을 때 발생한다."""


CANVAS_SIZE = (1080, 1920)
CANVAS_W, CANVAS_H = CANVAS_SIZE
FPS = 30
FADE_SECONDS = 0.4

MARGIN_X = 90
CONTENT_WIDTH = CANVAS_W - 2 * MARGIN_X
PANEL_PAD_X = 70
PANEL_PAD_Y = 76
TEXT_MAX_WIDTH = CONTENT_WIDTH - 2 * PANEL_PAD_X

TOP_SAFE = 230
BOTTOM_SAFE = CANVAS_H - 250
SAFE_HEIGHT = BOTTOM_SAFE - TOP_SAFE
PANEL_RADIUS = 46

BRAND_Y_CENTER = CANVAS_H - 130

LINE_SPACING = 1.34
TITLE_SIZES = (108, 96, 86, 78, 70, 62)
SUBTITLE_SIZE = 42
CARD_SIZES = (72, 64, 58, 52, 46, 40, 36)
TAKEAWAY_SIZES = (92, 82, 74, 66, 58)
BADGE_SIZE = 44
BRAND_SIZE = 32

TITLE_TEXT_COLOR = (52, 36, 26, 255)
SUBTITLE_TEXT_COLOR = (108, 86, 64, 255)
BODY_TEXT_COLOR = (46, 38, 32, 255)
TAKEAWAY_TEXT_COLOR = (44, 30, 22, 255)
BADGE_COLOR = (178, 96, 60, 255)
BRAND_TEXT_COLOR = (94, 68, 47, 255)
GOLD_RULE_COLOR = (178, 143, 86, 220)

PANEL_FILL = (250, 244, 231, 235)
PANEL_SHADOW_FILL = (30, 20, 14, 110)


# ---------------------------------------------------------------------------
# 폰트 (Codespace에 설치된 나눔글꼴을 사용한다: 제목/마무리는 명조 계열로 "고전/책"
# 느낌을, 본문은 고딕 계열로 모바일 가독성을 확보한다)
# ---------------------------------------------------------------------------

_FONT_SEARCH_DIRS: tuple[Path, ...] = (
    Path("/usr/share/fonts/truetype/nanum"),
    Path("/usr/share/fonts"),
)

_FONT_CANDIDATES: dict[str, tuple[str, ...]] = {
    "title_serif_bold": ("NanumMyeongjoBold.ttf",),
    "title_serif": ("NanumMyeongjo.ttf",),
    "body_sans": ("NanumBarunGothic.ttf", "NanumGothic.ttf"),
    "body_sans_bold": ("NanumBarunGothicBold.ttf", "NanumGothicBold.ttf"),
}


def _resolve_font_path(candidates: tuple[str, ...]) -> str:
    for name in candidates:
        for directory in _FONT_SEARCH_DIRS:
            path = directory / name
            if path.exists():
                return str(path)
    for directory in _FONT_SEARCH_DIRS:
        if not directory.exists():
            continue
        for name in candidates:
            matches = list(directory.rglob(name))
            if matches:
                return str(matches[0])
    raise ShortsRenderError(
        "필요한 한국어 폰트를 찾을 수 없습니다: "
        + ", ".join(candidates)
        + " (예: `sudo apt-get install fonts-nanum`으로 설치할 수 있습니다.)"
    )


@lru_cache(maxsize=None)
def _font_path(font_key: str) -> str:
    return _resolve_font_path(_FONT_CANDIDATES[font_key])


@lru_cache(maxsize=None)
def _load_font(font_key: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(_font_path(font_key), size=size)


# ---------------------------------------------------------------------------
# 한국어 줄바꿈: 의미를 바꾸지 않고 "배치"만 담당한다 - 내용을 자르거나 요약하지 않는다.
# ---------------------------------------------------------------------------


def wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    text = text.strip()
    if not text:
        return []
    lines: list[str] = []
    for paragraph in text.split("\n"):
        current = ""
        for word in paragraph.split(" "):
            if not word:
                continue
            candidate = f"{current} {word}" if current else word
            if font.getlength(candidate) <= max_width:
                current = candidate
                continue
            if not current:
                lines.extend(_break_long_word(word, font, max_width))
                current = ""
                continue
            lines.append(current)
            if font.getlength(word) <= max_width:
                current = word
            else:
                broken = _break_long_word(word, font, max_width)
                if broken:
                    lines.extend(broken[:-1])
                    current = broken[-1]
                else:
                    current = ""
        if current:
            lines.append(current)
    return lines


def _break_long_word(word: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for ch in word:
        candidate = current + ch
        if font.getlength(candidate) <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = ch
    if current:
        lines.append(current)
    return lines


def _fit_lines(
    text: str,
    font_key: str,
    sizes: Sequence[int],
    max_width: int,
    max_height: float,
) -> tuple[ImageFont.FreeTypeFont, list[str], float]:
    fallback: tuple[ImageFont.FreeTypeFont, list[str], float] | None = None
    for size in sizes:
        font = _load_font(font_key, size)
        lines = wrap_text(text, font, max_width)
        line_height = size * LINE_SPACING
        block_height = line_height * max(len(lines), 1)
        if fallback is None:
            fallback = (font, lines, line_height)
        if block_height <= max_height:
            return font, lines, line_height
    assert fallback is not None
    return fallback


def _draw_text_block(
    draw: ImageDraw.ImageDraw,
    lines: Sequence[str],
    font: ImageFont.FreeTypeFont,
    line_height: float,
    center_x: float,
    top_y: float,
    fill: tuple[int, int, int, int],
) -> float:
    y = top_y + line_height / 2
    for line in lines:
        draw.text((center_x, y), line, font=font, fill=fill, anchor="mm")
        y += line_height
    return top_y + line_height * len(lines)


# ---------------------------------------------------------------------------
# 카드 패널(반투명 아이보리) + 그림자
# ---------------------------------------------------------------------------


def _draw_shadowed_panel(
    canvas_rgba: Image.Image,
    box: tuple[float, float, float, float],
    radius: float = PANEL_RADIUS,
    fill: tuple[int, int, int, int] = PANEL_FILL,
) -> None:
    x0, y0, x1, y1 = box
    shadow_layer = Image.new("RGBA", canvas_rgba.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow_layer)
    offset = 14
    shadow_draw.rounded_rectangle(
        [x0 + offset, y0 + offset, x1 + offset, y1 + offset],
        radius=radius,
        fill=PANEL_SHADOW_FILL,
    )
    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(22))
    canvas_rgba.alpha_composite(shadow_layer)

    panel_layer = Image.new("RGBA", canvas_rgba.size, (0, 0, 0, 0))
    ImageDraw.Draw(panel_layer).rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=fill)
    canvas_rgba.alpha_composite(panel_layer)


def _draw_brand_footer(canvas_rgba: Image.Image, brand: str) -> None:
    font = _load_font("body_sans_bold", BRAND_SIZE)
    label = f"—  {brand}  —"
    pill_width = min(CONTENT_WIDTH, int(font.getlength(label)) + 90)
    pill_height = 74
    cx = CANVAS_W // 2
    cy = BRAND_Y_CENTER
    box = (cx - pill_width / 2, cy - pill_height / 2, cx + pill_width / 2, cy + pill_height / 2)
    _draw_shadowed_panel(canvas_rgba, box, radius=pill_height / 2, fill=(250, 244, 231, 214))
    draw = ImageDraw.Draw(canvas_rgba)
    draw.text((cx, cy), label, font=font, fill=BRAND_TEXT_COLOR, anchor="mm")


# ---------------------------------------------------------------------------
# 화면 종류별 렌더링 (표지 / 본문 카드 / 마무리)
# ---------------------------------------------------------------------------


def _render_cover(canvas_rgba: Image.Image, script: ShortsScript, plan: ScreenPlan) -> None:
    title_font, title_lines, title_lh = _fit_lines(
        script.title, "title_serif_bold", TITLE_SIZES, TEXT_MAX_WIDTH, SAFE_HEIGHT * 0.55
    )
    subtitle_lines: list[str] = []
    subtitle_font = None
    subtitle_lh = 0.0
    if script.subtitle:
        subtitle_font = _load_font("body_sans", SUBTITLE_SIZE)
        subtitle_lines = wrap_text(script.subtitle, subtitle_font, TEXT_MAX_WIDTH)
        subtitle_lh = SUBTITLE_SIZE * LINE_SPACING

    gap = 46 if subtitle_lines else 0
    content_h = title_lh * len(title_lines) + gap + subtitle_lh * len(subtitle_lines)
    panel_h = min(content_h + PANEL_PAD_Y * 2, SAFE_HEIGHT)
    panel_top_y = TOP_SAFE + (SAFE_HEIGHT - panel_h) / 2
    box = (MARGIN_X, panel_top_y, MARGIN_X + CONTENT_WIDTH, panel_top_y + panel_h)
    _draw_shadowed_panel(canvas_rgba, box)

    draw = ImageDraw.Draw(canvas_rgba)
    cx = CANVAS_W / 2
    y_cursor = panel_top_y + (panel_h - content_h) / 2
    y_cursor = _draw_text_block(draw, title_lines, title_font, title_lh, cx, y_cursor, TITLE_TEXT_COLOR)
    if subtitle_lines:
        y_cursor += gap
        _draw_text_block(draw, subtitle_lines, subtitle_font, subtitle_lh, cx, y_cursor, SUBTITLE_TEXT_COLOR)


def _render_card(canvas_rgba: Image.Image, script: ShortsScript, plan: ScreenPlan) -> None:
    body_font, body_lines, body_lh = _fit_lines(
        plan.text, "body_sans", CARD_SIZES, TEXT_MAX_WIDTH, SAFE_HEIGHT * 0.6
    )
    badge_font = _load_font("title_serif_bold", BADGE_SIZE)
    badge_lh = BADGE_SIZE * LINE_SPACING
    badge_gap = 28

    content_h = badge_lh + badge_gap + body_lh * len(body_lines)
    panel_h = min(content_h + PANEL_PAD_Y * 2, SAFE_HEIGHT)
    panel_top_y = TOP_SAFE + (SAFE_HEIGHT - panel_h) / 2
    box = (MARGIN_X, panel_top_y, MARGIN_X + CONTENT_WIDTH, panel_top_y + panel_h)
    _draw_shadowed_panel(canvas_rgba, box)

    draw = ImageDraw.Draw(canvas_rgba)
    cx = CANVAS_W / 2
    text_top = panel_top_y + (panel_h - content_h) / 2

    badge_text = f"{plan.card_index:02d}" if plan.card_index else ""
    badge_x = MARGIN_X + PANEL_PAD_X
    draw.text((badge_x, text_top + badge_lh / 2), badge_text, font=badge_font, fill=BADGE_COLOR, anchor="lm")

    y_cursor = text_top + badge_lh + badge_gap
    _draw_text_block(draw, body_lines, body_font, body_lh, cx, y_cursor, BODY_TEXT_COLOR)


def _render_takeaway(canvas_rgba: Image.Image, script: ShortsScript, plan: ScreenPlan) -> None:
    font, lines, line_h = _fit_lines(
        plan.text, "title_serif_bold", TAKEAWAY_SIZES, TEXT_MAX_WIDTH, SAFE_HEIGHT * 0.5
    )
    rule_gap = 40
    content_h = line_h * len(lines)
    panel_h = min(content_h + PANEL_PAD_Y * 2 + rule_gap * 2, SAFE_HEIGHT)
    panel_top_y = TOP_SAFE + (SAFE_HEIGHT - panel_h) / 2
    box = (MARGIN_X, panel_top_y, MARGIN_X + CONTENT_WIDTH, panel_top_y + panel_h)
    _draw_shadowed_panel(canvas_rgba, box)

    draw = ImageDraw.Draw(canvas_rgba)
    cx = CANVAS_W / 2
    text_top = panel_top_y + (panel_h - content_h) / 2
    rule_width = CONTENT_WIDTH * 0.32
    draw.line(
        [(cx - rule_width / 2, text_top - rule_gap / 2), (cx + rule_width / 2, text_top - rule_gap / 2)],
        fill=GOLD_RULE_COLOR,
        width=3,
    )
    bottom_y = _draw_text_block(draw, lines, font, line_h, cx, text_top, TAKEAWAY_TEXT_COLOR)
    draw.line(
        [(cx - rule_width / 2, bottom_y + rule_gap / 2), (cx + rule_width / 2, bottom_y + rule_gap / 2)],
        fill=GOLD_RULE_COLOR,
        width=3,
    )


# ---------------------------------------------------------------------------
# 배경: 저작권 문제가 없도록 전부 프로그램으로 생성한다(그라데이션/도형/질감).
# 영상 1개당 한 가지 스타일을 고정 사용하고, 화면 순서에 따라 밝기만 미세하게
# 흔들어("약간씩 변화") 완전히 동일한 배경 반복을 피한다.
# ---------------------------------------------------------------------------


def _vertical_gradient(
    size: tuple[int, int], top: tuple[int, int, int], bottom: tuple[int, int, int]
) -> Image.Image:
    width, height = size
    column = Image.new("RGB", (1, height))
    pixels = column.load()
    for y in range(height):
        t = y / max(height - 1, 1)
        pixels[0, y] = (
            round(top[0] + (bottom[0] - top[0]) * t),
            round(top[1] + (bottom[1] - top[1]) * t),
            round(top[2] + (bottom[2] - top[2]) * t),
        )
    return column.resize((width, height))


def _apply_jitter(img: Image.Image, jitter: float) -> Image.Image:
    if jitter == 0:
        return img
    factor = max(0.85, min(1.15, 1.0 + jitter))
    return ImageEnhance.Brightness(img).enhance(factor)


def _draw_book_silhouette(
    layer: Image.Image, color: tuple[int, int, int, int], box: tuple[float, float, float, float]
) -> None:
    x0, y0, x1, y1 = box
    draw = ImageDraw.Draw(layer)
    draw.rounded_rectangle([x0, y0, x1, y1], radius=18, fill=color)
    cx = (x0 + x1) / 2
    draw.line([(cx, y0 + 10), (cx, y1 - 10)], fill=(255, 255, 255, 40), width=4)
    for i in range(1, 4):
        yy = y0 + i * (y1 - y0) / 5
        draw.line([(x0 + 14, yy), (x1 - 14, yy)], fill=(255, 255, 255, 26), width=2)


def _draw_wavy_line(
    draw: ImageDraw.ImageDraw,
    start: tuple[float, float],
    end: tuple[float, float],
    color: tuple[int, int, int, int],
    segments: int = 6,
    width: int = 3,
) -> None:
    x0, y0 = start
    x1, y1 = end
    points = []
    for i in range(segments + 1):
        t = i / segments
        x = x0 + (x1 - x0) * t + math.sin(t * math.pi * 2) * 8
        y = y0 + (y1 - y0) * t
        points.append((x, y))
    draw.line(points, fill=color, width=width, joint="curve")


def _draw_cup_silhouette(
    layer: Image.Image, color: tuple[int, int, int, int], center: tuple[float, float], radius: float
) -> None:
    draw = ImageDraw.Draw(layer)
    cx, cy = center
    draw.ellipse([cx - radius, cy - radius * 0.6, cx + radius, cy + radius * 0.6], fill=color)
    draw.arc(
        [cx + radius * 0.55, cy - radius * 0.5, cx + radius * 1.55, cy + radius * 0.5],
        start=-90,
        end=90,
        fill=color[:3],
        width=10,
    )
    for dx in (-radius * 0.3, 0, radius * 0.3):
        _draw_wavy_line(
            draw,
            (cx + dx, cy - radius * 0.7),
            (cx + dx * 0.6, cy - radius * 1.7),
            color=(255, 255, 255, 60),
        )


def _draw_silhouette_bust(
    layer: Image.Image, color: tuple[int, int, int, int], box: tuple[float, float, float, float]
) -> None:
    x0, y0, x1, y1 = box
    draw = ImageDraw.Draw(layer)
    width = x1 - x0
    head_r = width * 0.24
    head_cx = x0 + width * 0.5
    head_cy = y0 + head_r + 10
    draw.ellipse([head_cx - head_r, head_cy - head_r, head_cx + head_r, head_cy + head_r], fill=color)
    draw.polygon(
        [
            (x0 + width * 0.08, y1),
            (x0 + width * 0.5, y0 + head_r * 1.7),
            (x0 + width * 0.92, y1),
        ],
        fill=color,
    )


def _draw_gold_frame(layer: Image.Image, color: tuple[int, int, int, int], margin: float) -> None:
    draw = ImageDraw.Draw(layer)
    width, height = layer.size
    draw.rectangle([margin, margin, width - margin, height - margin], outline=color, width=3)
    draw.rectangle(
        [margin + 16, margin + 16, width - margin - 16, height - margin - 16], outline=color, width=1
    )


def _draw_hanji_grain(layer: Image.Image, rng: random.Random, density: int = 1800, alpha: int = 18) -> None:
    draw = ImageDraw.Draw(layer)
    width, height = layer.size
    for _ in range(density):
        x = rng.randint(0, width - 1)
        y = rng.randint(0, height - 1)
        shade = rng.choice([255, 255, 255, 0, 0])
        draw.point((x, y), fill=(shade, shade, shade, alpha))
    for _ in range(14):
        x0 = rng.randint(0, width)
        y0 = rng.randint(0, height)
        length = rng.randint(80, 220)
        angle = rng.uniform(0, math.pi)
        x1 = x0 + length * math.cos(angle)
        y1 = y0 + length * math.sin(angle)
        draw.line([(x0, y0), (x1, y1)], fill=(255, 255, 255, 20), width=1)


def _bg_book_desk(jitter: float) -> Image.Image:
    img = _vertical_gradient(CANVAS_SIZE, (120, 86, 58), (48, 32, 22))
    rgba = img.convert("RGBA")
    glow = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse(
        [CANVAS_W * 0.5 - 260, 120, CANVAS_W * 0.5 + 260, 120 + 420], fill=(255, 224, 170, 70)
    )
    glow = glow.filter(ImageFilter.GaussianBlur(90))
    rgba.alpha_composite(glow)
    book_layer = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
    _draw_book_silhouette(
        book_layer, (34, 22, 15, 150), (CANVAS_W * 0.18, CANVAS_H * 0.72, CANVAS_W * 0.82, CANVAS_H * 0.86)
    )
    rgba.alpha_composite(book_layer)
    return _apply_jitter(rgba.convert("RGB"), jitter)


def _bg_tea_book(jitter: float) -> Image.Image:
    img = _vertical_gradient(CANVAS_SIZE, (247, 240, 224), (222, 202, 172))
    rgba = img.convert("RGBA")
    cup_layer = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
    _draw_cup_silhouette(cup_layer, (150, 108, 72, 140), (CANVAS_W * 0.78, CANVAS_H * 0.80), 90)
    rgba.alpha_composite(cup_layer)
    book_layer = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
    _draw_book_silhouette(
        book_layer, (150, 108, 72, 90), (CANVAS_W * 0.10, CANVAS_H * 0.84, CANVAS_W * 0.55, CANVAS_H * 0.93)
    )
    rgba.alpha_composite(book_layer)
    return _apply_jitter(rgba.convert("RGB"), jitter)


def _bg_sunset_book(jitter: float) -> Image.Image:
    top, mid, bottom = (214, 122, 74), (176, 102, 110), (46, 34, 44)
    half = CANVAS_H // 2
    upper = _vertical_gradient((CANVAS_W, half), top, mid)
    lower = _vertical_gradient((CANVAS_W, CANVAS_H - half), mid, bottom)
    img = Image.new("RGB", CANVAS_SIZE)
    img.paste(upper, (0, 0))
    img.paste(lower, (0, half))
    rgba = img.convert("RGBA")
    draw = ImageDraw.Draw(rgba)
    horizon_y = int(CANVAS_H * 0.66)
    draw.line([(0, horizon_y), (CANVAS_W, horizon_y)], fill=(255, 214, 180, 90), width=3)
    book_layer = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
    _draw_book_silhouette(
        book_layer,
        (30, 20, 20, 170),
        (CANVAS_W * 0.5 - 140, horizon_y - 46, CANVAS_W * 0.5 + 140, horizon_y + 10),
    )
    rgba.alpha_composite(book_layer)
    return _apply_jitter(rgba.convert("RGB"), jitter)


def _bg_hanji_paper(jitter: float) -> Image.Image:
    img = Image.new("RGB", CANVAS_SIZE, (240, 231, 212))
    rgba = img.convert("RGBA")
    rng = random.Random("tak-shorts-hanji-grain")
    _draw_hanji_grain(rgba, rng)
    return _apply_jitter(rgba.convert("RGB"), jitter)


def _bg_classic_cover(jitter: float) -> Image.Image:
    img = _vertical_gradient(CANVAS_SIZE, (58, 40, 28), (26, 18, 13))
    rgba = img.convert("RGBA")
    _draw_gold_frame(rgba, (178, 143, 86, 150), 54)
    return _apply_jitter(rgba.convert("RGB"), jitter)


def _bg_silhouette_warm(jitter: float) -> Image.Image:
    img = _vertical_gradient(CANVAS_SIZE, (222, 158, 120), (246, 236, 220))
    rgba = img.convert("RGBA")
    sil_layer = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
    _draw_silhouette_bust(
        sil_layer, (90, 64, 48, 90), (CANVAS_W * 0.55, CANVAS_H * 0.55, CANVAS_W * 1.05, CANVAS_H * 0.95)
    )
    sil_layer = sil_layer.filter(ImageFilter.GaussianBlur(2))
    rgba.alpha_composite(sil_layer)
    return _apply_jitter(rgba.convert("RGB"), jitter)


BACKGROUND_VARIANTS = {
    "book_desk": _bg_book_desk,
    "tea_book": _bg_tea_book,
    "sunset_book": _bg_sunset_book,
    "hanji_paper": _bg_hanji_paper,
    "classic_cover": _bg_classic_cover,
    "silhouette_warm": _bg_silhouette_warm,
}


def pick_background_variant(script: ShortsScript, override: str | None = None) -> str:
    """영상 1개당 배경 스타일 1개를 고정 선택한다(대본 내용 기반 결정적 선택)."""
    if override:
        if override not in BACKGROUND_VARIANTS:
            raise ShortsRenderError(
                f"알 수 없는 배경 스타일입니다: {override} "
                f"(선택 가능: {', '.join(BACKGROUND_VARIANTS)})"
            )
        return override
    digest = hashlib.sha256(f"{script.title}|{script.brand}".encode("utf-8")).hexdigest()
    order = tuple(BACKGROUND_VARIANTS)
    return order[int(digest[:8], 16) % len(order)]


def _jitter_for_index(index: int, total: int) -> float:
    if total <= 1:
        return 0.0
    t = index / (total - 1)
    return (t - 0.5) * 0.16


def build_screen_image(
    script: ShortsScript, plan: ScreenPlan, variant: str, screen_index: int, total_screens: int
) -> Image.Image:
    """대본 화면 1개(표지/본문 카드/마무리)를 1080x1920 RGB 프레임으로 렌더링한다."""
    jitter = _jitter_for_index(screen_index, total_screens)
    background = BACKGROUND_VARIANTS[variant](jitter)
    canvas = background.convert("RGBA")

    if plan.kind == "cover":
        _render_cover(canvas, script, plan)
    elif plan.kind == "card":
        _render_card(canvas, script, plan)
    elif plan.kind == "takeaway":
        _render_takeaway(canvas, script, plan)
    else:  # pragma: no cover - ScreenPlan.kind는 shorts_script에서만 생성됨
        raise ShortsRenderError(f"알 수 없는 화면 종류입니다: {plan.kind}")

    _draw_brand_footer(canvas, script.brand)
    return canvas.convert("RGB")


# ---------------------------------------------------------------------------
# ffmpeg 인코딩 (정지 이미지 시퀀스 + 짧은 크로스페이드, 오디오 트랙 없음)
# ---------------------------------------------------------------------------


def _build_filter_complex(durations: Sequence[float], fade: float) -> tuple[str, str]:
    n = len(durations)
    if n == 1:
        return "", "0:v"
    parts: list[str] = []
    prev_label = "0:v"
    offset = max(durations[0] - fade, 0.0)
    for i in range(1, n):
        out_label = f"v{i}" if i < n - 1 else "vout"
        parts.append(
            f"[{prev_label}][{i}:v]xfade=transition=fade:duration={fade:.3f}:offset={offset:.3f}[{out_label}]"
        )
        prev_label = out_label
        if i < n - 1:
            offset = offset + durations[i] - fade
    return ";".join(parts), prev_label


def _encode_with_ffmpeg(
    image_paths: Sequence[Path],
    durations: Sequence[float],
    fps: int,
    fade: float,
    output_path: Path,
) -> None:
    args = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    for path, duration in zip(image_paths, durations):
        args += ["-loop", "1", "-framerate", str(fps), "-t", f"{duration:.3f}", "-i", str(path)]

    filter_complex, out_label = _build_filter_complex(durations, fade)
    if filter_complex:
        args += ["-filter_complex", filter_complex, "-map", f"[{out_label}]"]
    else:
        args += ["-map", "0:v"]

    args += [
        "-r",
        str(fps),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-an",
        "-movflags",
        "+faststart",
        str(output_path),
    ]

    try:
        result = subprocess.run(args, capture_output=True, text=True)
    except FileNotFoundError as error:
        raise ShortsRenderError("ffmpeg 실행 파일을 찾을 수 없습니다 (시스템에 ffmpeg가 설치되어 있어야 합니다).") from error

    if result.returncode != 0:
        tail = "\n".join(result.stderr.strip().splitlines()[-15:])
        raise ShortsRenderError(f"ffmpeg 인코딩에 실패했습니다 (exit={result.returncode}):\n{tail}")


@dataclass(frozen=True)
class VideoProbe:
    width: int
    height: int
    duration_seconds: float
    has_audio: bool


def probe_video(path: Path | str) -> VideoProbe:
    """ffprobe로 실제 생성된 mp4의 해상도/길이/오디오 트랙 유무를 검증한다."""
    args = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_streams",
        "-show_format",
        str(path),
    ]
    try:
        result = subprocess.run(args, capture_output=True, text=True)
    except FileNotFoundError as error:
        raise ShortsRenderError("ffprobe 실행 파일을 찾을 수 없습니다 (ffmpeg 패키지에 포함되어 있어야 합니다).") from error

    if result.returncode != 0:
        raise ShortsRenderError(f"ffprobe 실행에 실패했습니다: {result.stderr.strip()}")

    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
    if not video_streams:
        raise ShortsRenderError("생성된 파일에서 비디오 스트림을 찾을 수 없습니다.")

    video = video_streams[0]
    duration_raw = data.get("format", {}).get("duration") or video.get("duration") or "0"
    return VideoProbe(
        width=int(video["width"]),
        height=int(video["height"]),
        duration_seconds=float(duration_raw),
        has_audio=bool(audio_streams),
    )


@dataclass(frozen=True)
class ShortsRenderResult:
    output_path: Path
    width: int
    height: int
    duration_seconds: float
    screen_count: int
    background_variant: str
    has_audio: bool


def render_shorts_video(
    script: ShortsScript,
    output_path: Path | str,
    *,
    background_variant: str | None = None,
    fps: int = FPS,
    fade_seconds: float = FADE_SECONDS,
) -> ShortsRenderResult:
    """ShortsScript -> 1080x1920 무음 MP4 (실제 ffmpeg 인코딩 + 사후 검증까지 수행)."""
    output_path = Path(output_path)
    variant = pick_background_variant(script, background_variant)
    plans = build_screen_plan(script)
    total_screens = len(plans)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="tak_shorts_render_") as tmp:
        tmp_dir = Path(tmp)
        image_paths: list[Path] = []
        for index, plan in enumerate(plans):
            frame = build_screen_image(script, plan, variant, index, total_screens)
            frame_path = tmp_dir / f"screen_{index:02d}.png"
            frame.save(frame_path, format="PNG")
            image_paths.append(frame_path)

        _encode_with_ffmpeg(
            image_paths,
            [plan.duration_seconds for plan in plans],
            fps,
            fade_seconds,
            output_path,
        )

    if not output_path.exists():
        raise ShortsRenderError(f"영상 파일 생성에 실패했습니다: {output_path}")

    probe = probe_video(output_path)
    if (probe.width, probe.height) != CANVAS_SIZE:
        raise ShortsRenderError(
            f"출력 해상도가 올바르지 않습니다: {probe.width}x{probe.height} "
            f"(기대값: {CANVAS_SIZE[0]}x{CANVAS_SIZE[1]})"
        )
    if probe.has_audio:
        raise ShortsRenderError("출력 영상에 오디오 트랙이 포함되어 있습니다 (기본값은 오디오 없음입니다).")

    return ShortsRenderResult(
        output_path=output_path,
        width=probe.width,
        height=probe.height,
        duration_seconds=probe.duration_seconds,
        screen_count=total_screens,
        background_variant=variant,
        has_audio=probe.has_audio,
    )
