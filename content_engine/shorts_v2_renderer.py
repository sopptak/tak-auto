"""Shorts 2.0(6-41) 모던 스타일 렌더러.

6-40 ``shorts_renderer``(정적 PNG 카드 -> concat 하드컷, 무음)를 폐기하지 않고
그 위에 "Modern Style Layer"를 얹는다:

    6-40 Base Layer   : ShortsScript, 1080x1920/H.264 규격, 한글 폰트/줄바꿈 원칙,
                        ShortsRenderError, 로컬 ffmpeg 인코딩
    6-41 Style Layer  : 장면 설계(shorts_v2_scene) -> 매 프레임 합성
                        (움직이는 배경, 카메라 무빙, kinetic typography, 강조 단어,
                        장면 전환, 진행 표시, 모션 그래픽) + 합성 사운드트랙
                        (shorts_v2_audio) -> ffmpeg rawvideo 파이프 인코딩

원칙: "움직여야 할 이유가 있는 요소만 움직인다." 배경은 느리게, 텍스트는
등장/퇴장 순간에만, 강조 단어는 한 번만 튄다. 흔들림/회전/번쩍임은 쓰지 않는다.

``data/``를 읽거나 쓰지 않는다. 외부 API를 호출하지 않는다(로컬 ffmpeg만).
"""

from __future__ import annotations

import math
import random
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from content_engine.shorts_renderer import ShortsRenderError
from content_engine.shorts_script import ShortsScript
from content_engine.shorts_v2_audio import synthesize_soundtrack
from content_engine.shorts_v2_scene import (
    HEIGHT, SAFE_BOTTOM, SAFE_LEFT, SAFE_RIGHT, SAFE_TOP, WIDTH, Scene, ShortSpec, TimedScene,
    build_timeline, item_reveal_times, validate_spec,
)

DEFAULT_FPS = 30
_FONTS = Path("C:/Windows/Fonts")
SANS_VF = _FONTS / "NotoSansKR-VF.ttf"
SERIF_VF = _FONTS / "NotoSerifKR-VF.ttf"
MONO = _FONTS / "consola.ttf"

RGB = tuple[int, int, int]


# --- 스타일 정의 ------------------------------------------------------------------

@dataclass(frozen=True)
class Look:
    font: Path
    weight: int
    size: int
    text: RGB
    accent: RGB
    accent2: RGB
    bg_top: RGB
    bg_bottom: RGB
    emphasis: str  # "color_underline" | "box" | "color"
    motion: str  # "rise" | "pop" | "blur"
    grain: int  # 필름 그레인 강도(알파 0~255)
    camera: float  # 장면당 줌 증가량
    watermark: bool
    line_gap: float = 1.32


LOOKS = {
    # 금융: 짙은 남색 + 금색 강조 + 청록 보조. 신뢰감, 정돈된 정보 그래픽.
    "finance": Look(SANS_VF, 800, 84, (248, 250, 252), (245, 196, 81), (45, 212, 191),
                    (8, 18, 36), (16, 42, 67), "color_underline", "rise", 7, 0.05, True),
    # 인간관계: 명조 + 따뜻한 호박색 강조, 시네마틱(보케/비/노을), 느린 블러 인.
    "human": Look(SERIF_VF, 700, 82, (255, 248, 240), (255, 201, 139), (255, 170, 120),
                  (18, 12, 10), (40, 24, 20), "color", "blur", 16, 0.07, False, line_gap=1.45),
    # AI: 검정 + 라임/시안, 굵은 고딕, 단어 단위 팝, 빠른 컷.
    "ai": Look(SANS_VF, 900, 90, (255, 255, 255), (200, 255, 46), (56, 225, 255),
               (5, 6, 10), (12, 14, 22), "box", "pop", 8, 0.04, True),
}

TEXT_BLOCK_CENTER_Y = 900
SAFE_CX = (SAFE_LEFT + SAFE_RIGHT) // 2  # 우측 버튼 열을 피해 화면 중심보다 약간 왼쪽
SAFE_PAD = 10
HOOK_HEADSTART = {"rise": 0.35, "pop": 0.45, "blur": 0.9}


@lru_cache(maxsize=64)
def _font(path: Path, size: int, weight: int | None = None) -> ImageFont.FreeTypeFont:
    if not path.exists():
        raise ShortsRenderError(f"폰트가 없습니다: {path} (Windows Noto Sans/Serif KR 필요)")
    font = ImageFont.truetype(str(path), size=size)
    if weight is not None:
        font.set_variation_by_axes([weight])
    return font


# --- easing / 합성 헬퍼 ----------------------------------------------------------

def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def ease_out_cubic(x: float) -> float:
    x = _clamp(x)
    return 1 - (1 - x) ** 3


def ease_out_back(x: float, s: float = 1.6) -> float:
    x = _clamp(x) - 1
    return 1 + (s + 1) * x ** 3 + s * x ** 2


def ease_in_out(x: float) -> float:
    x = _clamp(x)
    return x * x * (3 - 2 * x)


def _with_alpha(img: Image.Image, alpha: float) -> Image.Image:
    if alpha >= 0.999:
        return img
    a = img.getchannel("A").point(lambda v: int(v * alpha))
    out = img.copy()
    out.putalpha(a)
    return out


def _blit(frame: Image.Image, sprite: Image.Image, x: float, y: float, alpha: float = 1.0) -> None:
    """RGB 프레임 위에 RGBA 스프라이트를 알파 블렌딩한다(화면 밖으로 일부가 나가도 된다).

    프레임은 항상 RGB로 유지한다 - RGBA 프레임에 ImageDraw로 반투명 도형을
    그리면 블렌딩되지 않고 알파값이 픽셀에 그대로 덮어써져, 최종 RGB 변환 시
    반투명 요소가 불투명하게 나오는 문제가 있었다(6-41 1차 미리보기에서 발견)."""
    if alpha <= 0.01:
        return
    x, y = int(round(x)), int(round(y))
    sx0, sy0 = max(0, -x), max(0, -y)
    sx1, sy1 = min(sprite.width, frame.width - x), min(sprite.height, frame.height - y)
    if sx0 >= sx1 or sy0 >= sy1:
        return
    part = sprite if (sx0, sy0, sx1, sy1) == (0, 0, sprite.width, sprite.height) else sprite.crop((sx0, sy0, sx1, sy1))
    part = _with_alpha(part, alpha)
    frame.paste(part, (x + sx0, y + sy0), part)


def _gradient(size: tuple[int, int], top: RGB, bottom: RGB) -> Image.Image:
    col = Image.new("RGB", (1, 256))
    for i in range(256):
        f = i / 255
        col.putpixel((0, i), tuple(int(top[c] + (bottom[c] - top[c]) * f) for c in range(3)))
    return col.resize(size, Image.BICUBIC)


def _glow(radius: int, color: RGB, alpha: int, blur: float | None = None) -> Image.Image:
    size = radius * 2 + int((blur or radius * 0.6) * 3)
    img = Image.new("RGBA", (size, size), color + (0,))
    mask = Image.new("L", (size, size), 0)
    c = size // 2
    ImageDraw.Draw(mask).ellipse((c - radius, c - radius, c + radius, c + radius), fill=alpha)
    img.putalpha(mask.filter(ImageFilter.GaussianBlur(blur if blur is not None else radius * 0.6)))
    return img


def _radial_mask(size: tuple[int, int], inner: float, outer: float, strength: int) -> Image.Image:
    """중앙은 투명, 가장자리로 갈수록 어두워지는 비네트 마스크."""
    w, h = 108, 192
    small = Image.new("L", (w, h))
    for yy in range(h):
        for xx in range(w):
            d = math.hypot((xx - w / 2) / (w / 2), (yy - h / 2) / (h / 2)) / math.sqrt(2)
            f = _clamp((d - inner) / (outer - inner))
            small.putpixel((xx, yy), int(strength * f * f))
    return small.resize(size, Image.BICUBIC)


# --- 텍스트 레이아웃 ---------------------------------------------------------------

@dataclass
class Word:
    image: Image.Image  # 그림자 포함 RGBA
    x: int  # 화면 좌표(이미지 좌상단)
    y: int
    line: int
    order: int


@dataclass
class Mark:
    """강조 구간 하나(여러 어절에 걸칠 수 있음). box 스타일은 글자 뒤 박스, 그 외는 밑줄."""
    rect: tuple[int, int, int, int]
    line: int
    order: int  # 이 구간의 첫 어절 순번(등장 타이밍 기준)


@dataclass
class TextBlock:
    words: list[Word]
    lines: int
    bbox: tuple[int, int, int, int]
    marks: list[Mark] = field(default_factory=list)


_MARGIN = 28  # 그림자용 여백
_BOX_PAD = 10


def _tokens(line: str) -> list[list[tuple[str, bool]]]:
    """'이미 *갚고 있는* 대출' -> 어절 목록, 어절은 (조각, 강조여부) 목록."""
    words: list[list[tuple[str, bool]]] = [[]]
    emph = False
    for ch in line:
        if ch == "*":
            emph = not emph
        elif ch == " ":
            if words[-1]:
                words.append([])
        elif words[-1] and words[-1][-1][1] == emph:
            words[-1][-1] = (words[-1][-1][0] + ch, emph)
        else:
            words[-1].append((ch, emph))
    return [w for w in words if w]


def _word_image(parts: list[tuple[str, bool]], font: ImageFont.FreeTypeFont, look: Look) -> tuple[Image.Image, int, list[tuple[int, int]]]:
    """어절 하나를 그림자 포함 RGBA로 그린다. 반환: (이미지, 글자 폭, 강조 조각의 x범위들(이미지 기준))."""
    text = "".join(p for p, _ in parts)
    width = int(font.getlength(text))
    ascent, descent = font.getmetrics()
    img = Image.new("RGBA", (width + _MARGIN * 2, ascent + descent + _MARGIN * 2), (0, 0, 0, 0))
    mask = Image.new("L", img.size, 0)
    mdraw = ImageDraw.Draw(mask)
    spans = []
    x = _MARGIN
    for part, emph in parts:
        w = font.getlength(part)
        if emph:
            spans.append((int(x), int(x + w)))
        if not (emph and look.emphasis == "box"):  # 박스 위 검은 글자에는 그림자를 주지 않는다
            mdraw.text((x, _MARGIN + 4), part, font=font, fill=190)
        x += w
    img.putalpha(mask.filter(ImageFilter.GaussianBlur(10)))  # 검은 부드러운 그림자
    draw = ImageDraw.Draw(img)
    x = _MARGIN
    for part, emph in parts:
        if emph and look.emphasis == "box":
            color = (8, 10, 14)
        elif emph:
            color = look.accent
        else:
            color = look.text
        draw.text((x, _MARGIN), part, font=font, fill=color)
        x += font.getlength(part)
    return img, width, spans


def layout_text(text: str, look: Look, center_y: int, *, size: int | None = None, max_lines: int = 3,
                color_override: RGB | None = None, max_width: int | None = None,
                center_x: int = SAFE_CX) -> TextBlock:
    """텍스트를 안전영역 폭 안에서 어절 단위로 배치한다. 3줄을 넘으면 폰트를 줄이지 않고 실패한다.
    6-52: ``max_width``/``center_x``로 V3 프레임(좁은 열 등) 안에 배치할 수 있다(기본값 = V2 동작)."""
    font = _font(look.font, size or look.size, look.weight)
    boxed = look.emphasis == "box"
    if max_width is None:
        max_width = SAFE_RIGHT - SAFE_LEFT - SAFE_PAD * 2
    max_width -= _BOX_PAD * 2 if boxed else 0
    space = font.getlength(" ")
    lines: list[list[list[tuple[str, bool]]]] = []
    for raw in text.split("\n"):
        current: list[list[tuple[str, bool]]] = []
        current_w = 0.0
        for tok in _tokens(raw):
            w = font.getlength("".join(p for p, _ in tok))
            if w > max_width:
                raise ShortsRenderError(f"어절 하나가 안전영역 폭을 넘습니다: {''.join(p for p, _ in tok)!r} - 문장을 바꾸세요.")
            add = w + (space if current else 0)
            if current and current_w + add > max_width:
                lines.append(current)
                current, current_w = [tok], w
            else:
                current.append(tok)
                current_w += add
        if current:
            lines.append(current)
    if len(lines) > max_lines:
        raise ShortsRenderError(
            f"텍스트가 {len(lines)}줄로 넘칩니다(최대 {max_lines}줄, {size or look.size}px): {text!r} - "
            "폰트를 줄이지 말고 문장을 줄이세요."
        )
    ascent, descent = font.getmetrics()
    glyph = font.getbbox("가")
    line_h = int((ascent + descent) * look.line_gap)
    top = center_y - (line_h * len(lines) - int((ascent + descent) * (look.line_gap - 1))) // 2
    words: list[Word] = []
    marks: list[Mark] = []
    order = 0
    x_min, x_max = WIDTH, 0
    this_look = look if color_override is None else Look(**{**look.__dict__, "text": color_override})
    for li, line in enumerate(lines):
        rendered = [_word_image(tok, font, this_look) for tok in line]
        line_w = sum(w for _, w, _ in rendered) + space * (len(rendered) - 1)
        x = center_x - line_w / 2
        y = top + li * line_h
        run: list | None = None  # 연속된 강조 어절을 하나의 구간으로 합친다
        for img, w, spans in rendered:
            ix = int(x) - _MARGIN
            for s0, s1 in spans:
                a, b = ix + s0, ix + s1
                if run is not None and a - run[1] <= space + 2:
                    run[1] = b
                else:
                    if run is not None:
                        marks.append(Mark((run[0], run[2], run[1], run[3]), li, run[4]))
                    run = [a, b, y, y, order]
            if not spans or spans[-1][1] < w + _MARGIN - 1:
                if run is not None:
                    marks.append(Mark((run[0], run[2], run[1], run[3]), li, run[4]))
                run = None
            words.append(Word(img, ix, y - _MARGIN, li, order))
            order += 1
            x += w + space
        if run is not None:
            marks.append(Mark((run[0], run[2], run[1], run[3]), li, run[4]))
        x_min = min(x_min, int(center_x - line_w / 2))
        x_max = max(x_max, int(center_x + line_w / 2))
    for m in marks:  # 구간 좌표를 실제 도형 좌표로 확정
        x0, ly, x1, _ = m.rect
        if boxed:
            m.rect = (x0 - _BOX_PAD, ly + glyph[1] - 14, x1 + _BOX_PAD, ly + glyph[3] + 16)
            x_min, x_max = min(x_min, m.rect[0]), max(x_max, m.rect[2])
        else:
            m.rect = (x0, ly + glyph[3] + 12, x1, ly + glyph[3] + 20)
    bbox = (x_min, top, x_max, top + line_h * (len(lines) - 1) + ascent + descent)
    return TextBlock(words, len(lines), bbox, marks)


# --- 장면 에셋 -------------------------------------------------------------------

@dataclass
class SceneAssets:
    timed: TimedScene
    plate: Image.Image  # 카메라 무빙용 확대 배경(RGB)
    sprites: list = field(default_factory=list)  # (sprite, x0, y0, vx, vy, phase, amp)
    text: TextBlock | None = None
    big_center_y: int = 0
    items: list = field(default_factory=list)  # (image, x, y)
    chip: tuple | None = None  # (image, x, y)
    note: TextBlock | None = None
    boxes: list = field(default_factory=list)  # 안전영역 검사 대상 bbox


PLATE_SCALE = 1.14


class ShortsV2Renderer:
    def __init__(self, spec: ShortSpec, fps: int = DEFAULT_FPS) -> None:
        self.spec = spec
        self.look = LOOKS[spec.style]
        self.fps = fps
        self.timeline = build_timeline(spec)
        self.total = self.timeline[-1].end
        self.rng = random.Random(f"{spec.id}-6-41")
        self.assets = [self._build_assets(ts) for ts in self.timeline]
        self.vignette = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
        self.vignette.putalpha(_radial_mask((WIDTH, HEIGHT), 0.35, 1.0, 200 if spec.style == "human" else 150))
        self.grain = []
        for k in range(4):
            noise = Image.effect_noise((WIDTH // 2, HEIGHT // 2), 60).resize((WIDTH, HEIGHT), Image.NEAREST)
            layer = Image.merge("RGBA", (noise, noise, noise, Image.new("L", (WIDTH, HEIGHT), self.look.grain)))
            self.grain.append(layer)
        self.watermark = self._watermark() if self.look.watermark else None

    # ---- 에셋 준비 ----
    def _build_assets(self, ts: TimedScene) -> SceneAssets:
        scene, look = ts.scene, self.look
        pw, ph = int(WIDTH * PLATE_SCALE), int(HEIGHT * PLATE_SCALE)
        assets = SceneAssets(ts, self._plate(scene, (pw, ph)))
        assets.sprites = self._sprites(scene)
        if scene.layout == "brand":
            return assets
        if scene.layout == "big":
            text_y, assets.big_center_y = (620, 1010)
        elif scene.layout == "list":
            text_y = 560
        else:
            text_y = TEXT_BLOCK_CENTER_Y + (40 if scene.label else 0) + (60 if scene.visual in ("notify",) else 0)
            if scene.visual in ("bars", "stack", "timeline", "compare"):
                text_y = 700
        if scene.text:
            # HOOK은 첫 1~2초에 한눈에 읽혀야 하므로 한 단계 크게 쓴다
            hook_size = int(look.size * 1.12) if scene.role == "HOOK" and scene.layout != "big" and look.motion != "blur" else None
            assets.text = layout_text(scene.text, look, text_y, size=hook_size)
            assets.boxes.append(assets.text.bbox)
        if scene.label:
            assets.chip = self._chip(scene.label, (assets.text.bbox[1] if assets.text else text_y) - 60)
            img, x, y = assets.chip
            assets.boxes.append((x + 10, y + 10, x + img.width - 10, y + img.height - 10))
        if scene.layout == "big" and scene.big:
            font = _font(SANS_VF, self._big_size(scene.big), 900)
            b = font.getbbox(scene.big)
            w, h = b[2] - b[0], b[3] - b[1]
            assets.boxes.append((SAFE_CX - w // 2, assets.big_center_y - h // 2, SAFE_CX + w // 2, assets.big_center_y + h // 2))
        if scene.items:
            assets.items = self._list_items(scene)
            for img, x, y in assets.items:
                assets.boxes.append((x + 20, y + 20, x + img.width - 20, y + img.height - 20))
        if scene.note:
            note_look = Look(**{**look.__dict__, "emphasis": "color", "line_gap": 1.3})
            note_y = 1290 if scene.layout == "big" else min(SAFE_BOTTOM - 40, (assets.text.bbox[3] if assets.text else 1000) + 90)
            assets.note = layout_text(scene.note, note_look, note_y, size=40, max_lines=2, color_override=(200, 210, 222))
            assets.boxes.append(assets.note.bbox)
        for box in assets.boxes:
            if box[0] < SAFE_LEFT or box[1] < SAFE_TOP or box[2] > SAFE_RIGHT or box[3] > SAFE_BOTTOM:
                raise ShortsRenderError(f"{scene.role} 장면 요소가 안전영역을 벗어났습니다: {box} (안전영역 {SAFE_LEFT},{SAFE_TOP},{SAFE_RIGHT},{SAFE_BOTTOM})")
        return assets

    @staticmethod
    def _big_size(big: str) -> int:
        return 300 if len(big) <= 2 else (210 if len(big) <= 3 else 170)

    def _chip(self, label: str, bottom_y: int):
        look = self.look
        num, _, name = label.partition(" ")
        font_num = _font(SANS_VF, 44, 900)
        font_name = _font(look.font, 44, 700)
        name = name.strip()
        w_num, w_name = int(font_num.getlength(num)), int(font_name.getlength(name))
        h = 84
        img = Image.new("RGBA", (w_num + w_name + 36 * 2 + 30 + 20, h + 20), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((10, 10, img.width - 10, 10 + h), radius=h // 2, fill=(255, 255, 255, 26), outline=look.accent + (200,), width=3)
        d.rounded_rectangle((10, 10, 10 + w_num + 56, 10 + h), radius=h // 2, fill=look.accent + (255,))
        d.text((10 + 28, 10 + 12), num, font=font_num, fill=look.bg_top)
        d.text((10 + w_num + 56 + 22, 10 + 12), name, font=font_name, fill=look.text)
        x = SAFE_CX - img.width // 2
        return img, x, bottom_y - img.height - 20

    def _list_items(self, scene: Scene):
        look = self.look
        human_side = scene.visual == "list_human"
        font = _font(SANS_VF, 76, 900)
        out = []
        cols, cell_w, cell_h, gap = 2, 360, 170, 30
        grid_w = cols * cell_w + gap
        x0 = SAFE_CX - grid_w // 2
        y0 = 740
        for k, item in enumerate(scene.items):
            img = Image.new("RGBA", (cell_w + 40, cell_h + 40), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            if human_side:
                d.rounded_rectangle((20, 20, 20 + cell_w, 20 + cell_h), radius=34, fill=look.accent + (255,))
                color = (8, 10, 14)
            else:
                d.rounded_rectangle((20, 20, 20 + cell_w, 20 + cell_h), radius=34, fill=(255, 255, 255, 18), outline=look.accent2 + (230,), width=4)
                color = look.text
            b = font.getbbox(item)
            d.text((20 + (cell_w - (b[2] - b[0])) // 2 - b[0], 20 + (cell_h - (b[3] - b[1])) // 2 - b[1]), item, font=font, fill=color)
            col, row = k % cols, k // cols
            out.append((img, x0 + col * (cell_w + gap) - 20, y0 + row * (cell_h + gap) - 20))
        return out

    def _watermark(self) -> Image.Image:
        font = _font(self.look.font, 30, 700)
        text = self.spec.brand
        img = Image.new("RGBA", (int(font.getlength(text)) + 60, 60), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.ellipse((4, 20, 20, 36), fill=self.look.accent + (255,))
        d.text((32, 10), text, font=font, fill=(255, 255, 255, 170))
        return img

    # ---- 배경 plate(정적, 카메라가 그 위를 천천히 움직인다) ----
    def _plate(self, scene: Scene, size: tuple[int, int]) -> Image.Image:
        style, look, v = self.spec.style, self.look, scene.visual
        w, h = size
        rng = random.Random(f"{self.spec.id}-{scene.role}-{v}-{scene.text}")
        if style == "finance":
            img = _gradient(size, look.bg_top, look.bg_bottom)
            d = ImageDraw.Draw(img, "RGBA")
            step = 90
            for x in range(0, w, step):
                d.line((x, 0, x, h), fill=(255, 255, 255, 12), width=2)
            for y in range(0, h, step):
                d.line((0, y, w, y), fill=(255, 255, 255, 12), width=2)
            # 흐릿한 상승 차트 선(배경 텍스처, 정보 아님)
            pts, y = [], h * 0.78
            for x in range(-40, w + 80, 80):
                y += rng.uniform(-70, 40)
                pts.append((x, y))
            d.line(pts, fill=look.accent2 + (40,), width=6, joint="curve")
            return img
        if style == "ai":
            img = _gradient(size, look.bg_top, look.bg_bottom)
            d = ImageDraw.Draw(img, "RGBA")
            step = 54
            for y in range(step // 2, h, step):
                for x in range(step // 2, w, step):
                    d.ellipse((x - 3, y - 3, x + 3, y + 3), fill=(80, 90, 110, 120))
            return img
        # human: 장면마다 다른 "영화 같은" 배경
        palettes = {
            "bokeh_warm": ((22, 12, 10), (58, 30, 20)),
            "street": ((10, 14, 24), (30, 28, 40)),
            "rain": ((12, 18, 26), (28, 36, 46)),
            "dusk": ((30, 22, 48), (190, 96, 70)),
            "two_lights": ((10, 10, 14), (24, 20, 22)),
            "dawn": ((40, 44, 70), (214, 150, 120)),
            "brand": ((16, 12, 12), (36, 24, 22)),
        }
        top, bottom = palettes.get(v, palettes["bokeh_warm"])
        img = _gradient(size, top, bottom)
        if v == "dusk":  # 도시 실루엣 + 켜진 창문
            d = ImageDraw.Draw(img, "RGBA")
            x = 0
            while x < w:
                bw, bh = rng.randint(70, 170), rng.randint(260, 700)
                d.rectangle((x, h - bh, x + bw, h), fill=(14, 10, 20, 255))
                for wy in range(h - bh + 30, h - 20, 46):
                    for wx in range(x + 14, x + bw - 20, 32):
                        if rng.random() < 0.18:
                            d.rectangle((wx, wy, wx + 12, wy + 18), fill=(255, 200, 120, 200))
                x += bw + rng.randint(0, 10)
        if v in ("bokeh_warm", "street", "rain", "dusk"):  # 멀리 있는 흐린 불빛(정적 레이어)
            for _ in range(22):
                color = rng.choice([(255, 170, 80), (255, 120, 60), (255, 220, 160), (120, 170, 255)] if v != "rain" else [(150, 190, 255), (255, 190, 120)])
                g = _glow(rng.randint(30, 80), color, rng.randint(40, 110))
                img.paste(g, (rng.randint(0, w - g.width), rng.randint(0, h - g.height)), g)
        if v == "dawn":
            sun = _glow(420, (255, 214, 170), 150, 260)
            img.paste(sun, (w // 2 - sun.width // 2, int(h * 0.55)), sun)
        return img

    def _sprites(self, scene: Scene) -> list:
        """plate 위에서 독립적으로 움직이는 요소들 - 배경을 '살아있게' 만드는 최소한의 motion."""
        style, look, v = self.spec.style, self.look, scene.visual
        rng = random.Random(f"{self.spec.id}-{scene.role}-sprites")
        sprites = []
        if style == "finance":
            sprites.append((_glow(360, (31, 111, 235), 90), -200, 200, 18, 6, 0.0, 60))
            sprites.append((_glow(300, look.accent2, 60), 500, 1100, -14, -10, 1.3, 50))
        elif style == "ai":
            sprites.append((_glow(320, look.accent2, 45), 480, 300, -10, 12, 0.0, 40))
            if scene.visual == "list_human":
                sprites.append((_glow(360, look.accent, 50), 100, 900, 12, -8, 2.0, 40))
        else:
            if v in ("bokeh_warm", "street", "rain", "dusk", "dawn", "brand"):
                n = 16 if v != "dawn" else 26
                for _ in range(n):
                    if v == "dawn":  # 떠오르는 먼지 입자
                        g = _glow(rng.randint(3, 7), (255, 240, 220), rng.randint(120, 200), 3)
                        sprites.append((g, rng.randint(0, WIDTH), rng.randint(0, HEIGHT), rng.uniform(-6, 6), rng.uniform(-40, -15), rng.random() * 6, 20))
                    else:  # 가까운 큰 보케(느린 시차 이동)
                        color = rng.choice([(255, 180, 90), (255, 140, 80), (255, 225, 170)] if v != "rain" else [(160, 200, 255), (255, 200, 140)])
                        g = _glow(rng.randint(40, 110), color, rng.randint(50, 120), rng.randint(10, 26))
                        sprites.append((g, rng.randint(-100, WIDTH), rng.randint(-100, HEIGHT), rng.uniform(-14, 14), rng.uniform(-10, 10), rng.random() * 6, 15))
        return sprites

    # ---- 프레임 합성 ----
    def scene_at(self, t: float) -> int:
        for i, ts in enumerate(self.timeline):
            if t < ts.end:
                return i
        return len(self.timeline) - 1

    def frame(self, t: float) -> Image.Image:
        i = self.scene_at(t)
        ts = self.timeline[i]
        local = t - ts.start
        img = self._scene_frame(i, local)
        dissolve = 0.7
        if ts.scene.transition == "dissolve" and i > 0 and local < dissolve:
            prev = self._scene_frame(i - 1, self.timeline[i - 1].duration + local)
            img = Image.blend(prev, img, ease_in_out(local / dissolve))
        if ts.scene.transition == "punch" and local < 0.3:  # 박자에 맞춘 짧은 줌 펀치
            z = 1 + 0.045 * (1 - ease_out_cubic(local / 0.3))
            cw, ch = WIDTH / z, HEIGHT / z
            img = img.crop((int((WIDTH - cw) / 2), int((HEIGHT - ch) / 2), int((WIDTH + cw) / 2), int((HEIGHT + ch) / 2))).resize((WIDTH, HEIGHT), Image.BILINEAR)
        img.paste(self.vignette, (0, 0), self.vignette)
        grain = self.grain[int(t * 12) % len(self.grain)]  # 초당 12회만 바꾼다(필름 질감 + 인코딩 용량 절감)
        img.paste(grain, (0, 0), grain)
        self._overlay(img, t, i)
        return img

    def _overlay(self, img: Image.Image, t: float, i: int) -> None:
        """영상 전체에 걸친 요소: 진행 표시, 워터마크."""
        if self.spec.scenes[i].layout == "brand":
            return
        if self.spec.style == "ai":  # 얇은 전체 진행 바
            d = ImageDraw.Draw(img, "RGBA")
            y = SAFE_TOP
            d.rounded_rectangle((SAFE_LEFT, y, SAFE_RIGHT, y + 6), radius=3, fill=(255, 255, 255, 40))
            d.rounded_rectangle((SAFE_LEFT, y, SAFE_LEFT + int((SAFE_RIGHT - SAFE_LEFT) * t / self.total), y + 6), radius=3, fill=self.look.accent + (255,))
        if self.watermark is not None and i > 0:  # HOOK 화면은 워터마크 없이 깨끗하게
            _blit(img, self.watermark, SAFE_LEFT, SAFE_TOP + 18, 0.9)

    def _scene_frame(self, i: int, local: float) -> Image.Image:
        a = self.assets[i]
        ts, scene, look = a.timed, a.timed.scene, self.look
        p = local / ts.duration
        # 카메라: 장면 동안 아주 느린 줌 + 약간의 수평 이동(정적인 카드뉴스 느낌 제거)
        z = 1 + look.camera * ease_in_out(p) if self.spec.style != "human" else 1 + look.camera * p
        pw, ph = a.plate.size
        cw, ch = pw / (PLATE_SCALE * z) , ph / (PLATE_SCALE * z)
        drift = (i % 2 * 2 - 1) * 30 * p
        cx, cy = pw / 2 + drift, ph / 2
        frame = a.plate.crop((int(cx - cw / 2), int(cy - ch / 2), int(cx + cw / 2), int(cy + ch / 2))).resize((WIDTH, HEIGHT), Image.BILINEAR)
        for sprite, x0, y0, vx, vy, phase, amp in a.sprites:
            x = x0 + vx * local + amp * math.sin(local * 0.6 + phase)
            y = y0 + vy * local + amp * math.cos(local * 0.5 + phase)
            _blit(frame, sprite, x, y)
        exit_p = _clamp((local - (ts.duration - 0.2)) / 0.2)
        if look.motion == "blur":
            # 디졸브 전환에서는 배경만 겹치고 글자는 겹치지 않게 한다: 이전 장면 글자는 컷 0.3초
            # 전부터 사라지고(컷 이후 연장 구간에서는 완전히 투명), 새 글자는 디졸브 중반 이후 떠오른다.
            # (2차 렌더링 프레임 검사에서 두 장면 문장이 겹쳐 보이는 문제 발견 후 수정)
            exit_p = _clamp((local - (ts.duration - 0.3)) / 0.3)
        # HOOK은 등장 애니메이션을 앞당겨 첫 프레임부터 글자가 보이게 한다(스크롤을 멈추게 하는
        # 첫 0.1초에 빈 화면이 나오던 1차 렌더링 결함 수정). 움직임 자체는 남겨 둔다.
        if i == 0:
            local += HOOK_HEADSTART[look.motion]
        self._graphic(frame, a, local)
        if scene.layout == "brand":
            self._brand(frame, local)
            return frame
        if a.chip:
            img, x, y = a.chip
            _blit(frame, img, x - 60 * (1 - ease_out_cubic(local / 0.4)), y, _clamp(local / 0.25) * (1 - exit_p))
            if scene.label[:2].isdigit():  # 3단계 진행 표시(01/02/03)
                d = ImageDraw.Draw(frame, "RGBA")
                idx = int(scene.label[:2])
                seg_w, gap = 70, 12
                sx = SAFE_CX - (3 * seg_w + 2 * gap) // 2
                sy = y - 24
                for k in range(3):
                    fill = look.accent + (255,) if k < idx - 1 else (255, 255, 255, 50)
                    d.rounded_rectangle((sx + k * (seg_w + gap), sy, sx + k * (seg_w + gap) + seg_w, sy + 8), radius=4, fill=fill)
                    if k == idx - 1:
                        grow = ease_out_cubic((local - 0.2) / 0.5)
                        d.rounded_rectangle((sx + k * (seg_w + gap), sy, sx + k * (seg_w + gap) + int(seg_w * grow), sy + 8), radius=4, fill=look.accent + (255,))
        text_delay = 0.25 if a.chip else 0.0
        if look.motion == "blur":
            text_delay = 0.4 if scene.transition == "dissolve" else 0.15
        if a.text:
            self._draw_text(frame, a.text, local - text_delay, exit_p)
        if scene.layout == "big" and scene.big:
            self._big(frame, a, local, exit_p)
        for k, (img, x, y) in enumerate(a.items):
            t0 = item_reveal_times(ts, self.spec.beat_seconds)[k] - ts.start
            q = (local - t0) / 0.3
            if q <= 0:
                continue
            s = ease_out_back(q)
            if abs(s - 1) > 0.01:
                sized = img.resize((max(1, int(img.width * s)), max(1, int(img.height * s))), Image.BILINEAR)
                _blit(frame, sized, x + (img.width - sized.width) / 2, y + (img.height - sized.height) / 2, _clamp(q * 2) * (1 - exit_p))
            else:
                _blit(frame, img, x, y, 1 - exit_p)
        if a.note:
            self._draw_text(frame, a.note, local - 0.8, exit_p, simple=True)
        return frame

    def _draw_text(self, frame: Image.Image, block: TextBlock, local: float, exit_p: float, simple: bool = False) -> None:
        draw_text_block(frame, block, self.look, local, exit_p, simple)

    def _big(self, frame: Image.Image, a: SceneAssets, local: float, exit_p: float) -> None:
        scene, look = a.timed.scene, self.look
        q = (local - 0.35) / 0.45
        if q <= 0:
            return
        text = scene.big
        m = re.match(r"(\d+)(.*)", text)
        if m and "count" in scene.visual:  # 숫자가 올라가며 멈춘다
            target = int(m.group(1))
            text = f"{max(1, round(target * ease_out_cubic(q * 1.3)))}{m.group(2)}"
        font = _font(SANS_VF, self._big_size(scene.big), 900)
        color = look.accent if scene.visual.startswith("big_accent") or "accent" in scene.visual else look.text
        b = font.getbbox(text)
        img = Image.new("RGBA", (b[2] - b[0] + 80, b[3] - b[1] + 80), (0, 0, 0, 0))
        dd = ImageDraw.Draw(img)
        dd.text((40 - b[0], 40 - b[1]), text, font=font, fill=color)
        glow = img.getchannel("A").filter(ImageFilter.GaussianBlur(24))
        halo = Image.new("RGBA", img.size, color + (0,))
        halo.putalpha(glow.point(lambda v: int(v * 0.45)))
        img = Image.alpha_composite(halo, img)
        s = 1 + 0.35 * (1 - ease_out_back(q, 1.4))
        s *= 1 - 0.08 * exit_p
        sized = img.resize((max(1, int(img.width * s)), max(1, int(img.height * s))), Image.BILINEAR)
        cx = SAFE_CX
        _blit(frame, sized, cx - sized.width / 2, a.big_center_y - sized.height / 2, _clamp(q * 2.5) * (1 - exit_p))
        if "strike" in scene.visual and self.timeline[a.timed.index - 1].scene.big:  # 이전 장면 숫자에 취소선
            prev = self.timeline[a.timed.index - 1].scene.big
            f2 = _font(SANS_VF, 110, 900)
            pw = f2.getlength(prev)
            px, py = cx - pw / 2, a.big_center_y - 270
            dd2 = ImageDraw.Draw(frame, "RGBA")
            dd2.text((px, py), prev, font=f2, fill=(255, 255, 255, 110))
            sw = ease_out_cubic((local - 0.1) / 0.3)
            dd2.line((px - 10, py + 80, px - 10 + (pw + 20) * sw, py + 80), fill=(255, 80, 80, 230), width=10)

    def _brand(self, frame: Image.Image, local: float) -> None:
        look = self.look
        cx, cy = SAFE_CX, 860
        font = _font(look.font, 104, 900 if look.font == SANS_VF else 700)
        text = self.spec.brand
        tw = font.getlength(text)
        q = ease_out_cubic(local / 0.6)
        d = ImageDraw.Draw(frame, "RGBA")
        if self.spec.style == "ai":
            pad = 30
            w = (tw + pad * 2) * ease_out_cubic(local / 0.35)
            d.rounded_rectangle((cx - w / 2, cy - 90, cx + w / 2, cy + 70), radius=24, fill=look.accent + (255,))
            if local > 0.2:
                d.text((cx - tw / 2, cy - 78), text, font=font, fill=(8, 10, 14, int(255 * _clamp((local - 0.2) / 0.2))))
        else:
            d.text((cx - tw / 2, cy - 78 + 30 * (1 - q)), text, font=font, fill=look.text + (int(255 * q),))
            lw = 220 * ease_out_cubic((local - 0.3) / 0.6)
            d.line((cx - lw, cy + 80, cx + lw, cy + 80), fill=look.accent + (230,), width=4)
        sub = _font(look.font, 40, 500)
        tag = "다음 편에서 또 만나요"
        sw = sub.getlength(tag)
        d.text((cx - sw / 2, cy + 120), tag, font=sub, fill=(255, 255, 255, int(170 * _clamp((local - 0.6) / 0.5))))

    # ---- 장면별 모션 그래픽(정보를 그림으로 보여주는 레이어) ----
    def _graphic(self, frame: Image.Image, a: SceneAssets, local: float) -> None:
        v, look = a.timed.scene.visual, self.look
        d = ImageDraw.Draw(frame, "RGBA")
        cx = SAFE_CX
        small = _font(SANS_VF, 40, 700)
        exit_p = _clamp((local - (a.timed.duration - 0.2)) / 0.2)
        fade = int(255 * (1 - exit_p))
        if v == "notify":  # 심사 결과 알림이 위에서 떨어진다
            q = ease_out_back(local / 0.45, 1.2)
            y = SAFE_TOP + 40 - 260 * (1 - q)
            x0, x1 = SAFE_LEFT + 10, SAFE_RIGHT - 10
            d.rounded_rectangle((x0, y, x1, y + 190), radius=34, fill=(240, 244, 250, int(235 * _clamp(local / 0.2)) * fade // 255))
            d.ellipse((x0 + 34, y + 38, x0 + 104, y + 108), fill=(220, 60, 60, fade))
            d.text((x0 + 58, y + 42), "!", font=_font(SANS_VF, 52, 900), fill=(255, 255, 255, fade))
            d.text((x0 + 130, y + 36), "대출 심사 결과 안내", font=_font(SANS_VF, 40, 800), fill=(20, 24, 32, fade))
            d.text((x0 + 130, y + 100), "요청하신 대출이 승인되지 않았습니다", font=_font(SANS_VF, 32, 500), fill=(90, 96, 110, fade))
        elif v == "bars":  # 월 소득 vs 월 상환액 막대
            rows = (("월 소득", 1.0, look.accent2), ("월 상환액", 0.62, look.accent))
            for k, (label, ratio, color) in enumerate(rows):
                y = 1000 + k * 150
                grow = ease_out_cubic((local - 0.6 - k * 0.3) / 0.8)
                d.text((SAFE_LEFT + 20, y), label, font=small, fill=(255, 255, 255, int(200 * _clamp((local - 0.5) / 0.3)) * fade // 255))
                d.rounded_rectangle((SAFE_LEFT + 20, y + 60, SAFE_RIGHT - 20, y + 100), radius=20, fill=(255, 255, 255, 25 * fade // 255))
                if grow > 0:
                    d.rounded_rectangle((SAFE_LEFT + 20, y + 60, SAFE_LEFT + 20 + (SAFE_RIGHT - SAFE_LEFT - 40) * ratio * grow, y + 100), radius=20, fill=color + (fade,))
        elif v == "stack":  # 기존 빚이 하나씩 쌓인다
            for k, label in enumerate(("주택담보대출", "카드론", "자동차 할부")):
                q = ease_out_cubic((local - 0.7 - k * 0.35) / 0.4)
                if q <= 0:
                    continue
                bw, bh = 520 - k * 60, 92
                y = 1250 - (k + 1) * (bh + 14) - 200 * (1 - q)
                d.rounded_rectangle((cx - bw / 2, y, cx + bw / 2, y + bh), radius=18, fill=(look.accent if k == 1 else look.accent2) + (int(230 * q) * fade // 255,))
                tw = small.getlength(label)
                d.text((cx - tw / 2, y + 20), label, font=small, fill=look.bg_top + (fade,))
        elif v == "timeline":  # 거래 기록이 시간 순서로 쌓인다
            y = 1130
            x0, x1 = SAFE_LEFT + 40, SAFE_RIGHT - 40
            grow = ease_out_cubic((local - 0.6) / 1.2)
            d.line((x0, y, x0 + (x1 - x0) * grow, y), fill=(255, 255, 255, 120 * fade // 255), width=5)
            for k in range(6):
                px = x0 + (x1 - x0) * k / 5
                if grow * 5 + 0.01 >= k:
                    d.ellipse((px - 16, y - 16, px + 16, y + 16), fill=look.accent2 + (fade,))
                    d.line((px - 7, y, px - 1, y + 7, px + 9, y - 7), fill=look.bg_top + (fade,), width=5)
            d.text((x0 - 10, y + 40), "처음 거래", font=_font(SANS_VF, 34, 600), fill=(255, 255, 255, 150 * fade // 255))
            lbl = "지금"
            d.text((x1 - _font(SANS_VF, 34, 600).getlength(lbl) + 10, y + 40), lbl, font=_font(SANS_VF, 34, 600), fill=(255, 255, 255, 150 * fade // 255))
        elif v == "compare":  # 연봉이 같은 두 사람, 기존 부채만 다르다
            for k, (name, debt) in enumerate((("A", 0.2), ("B", 0.8))):
                q = ease_out_cubic((local - 0.6 - k * 0.25) / 0.5)
                if q <= 0:
                    continue
                w = 340
                x = cx - w - 20 + k * (w + 40)
                y = 1000 + 60 * (1 - q)
                al = int(255 * q) * fade // 255
                d.rounded_rectangle((x, y, x + w, y + 300), radius=30, fill=(255, 255, 255, 22 * al // 255), outline=(255, 255, 255, 70 * al // 255), width=3)
                d.text((x + 30, y + 26), f"{name}", font=_font(SANS_VF, 56, 900), fill=look.text + (al,))
                d.text((x + 30, y + 110), "연봉  같음", font=_font(SANS_VF, 34, 600), fill=(255, 255, 255, 190 * al // 255))
                d.text((x + 30, y + 170), "기존 부채", font=_font(SANS_VF, 34, 600), fill=(255, 255, 255, 190 * al // 255))
                g = ease_out_cubic((local - 1.0 - k * 0.25) / 0.7)
                d.rounded_rectangle((x + 30, y + 230, x + w - 30, y + 256), radius=13, fill=(255, 255, 255, 30 * al // 255))
                col = look.accent2 if k == 0 else (255, 107, 107)
                d.rounded_rectangle((x + 30, y + 230, x + 30 + (w - 60) * debt * max(g, 0.02), y + 256), radius=13, fill=col + (al,))
        elif v == "terminal":  # AI가 요약을 끝내는 과정(타이핑)
            mono = _font(MONO, 42)
            lines = ("> summarize(reports[1:10])", "  reading ########## 10/10", "  done.")
            y0 = 1080
            box = (SAFE_LEFT + 10, y0 - 34, SAFE_RIGHT - 10, y0 + 210)
            d.rounded_rectangle(box, radius=22, fill=(255, 255, 255, 14), outline=look.accent2 + (120,), width=2)
            chars = int((local - 0.4) * 38)
            for k, line in enumerate(lines):
                shown = line[: max(0, chars)]
                chars -= len(line)
                d.text((box[0] + 30, y0 + k * 56), shown, font=mono, fill=(look.accent if "done" in line else (200, 230, 240)) + (230,))
        elif v == "scan":  # 위에서 아래로 훑는 스캔 라인
            y = SAFE_TOP + (SAFE_BOTTOM - SAFE_TOP) * ((local * 0.5) % 1)
            d.line((0, y, WIDTH, y), fill=look.accent2 + (90,), width=3)
        elif v == "two_lights":  # 두 개의 불빛이 천천히 멀어진다
            p = ease_in_out(local / a.timed.duration)
            gap = 60 + 380 * p
            for sign in (-1, 1):
                g = _glow_cached(70, (255, 196, 130), 230)
                _blit(frame, g, WIDTH // 2 + sign * gap - g.width / 2, 1250 - g.height / 2)
                g2 = _glow_cached(16, (255, 245, 225), 255)
                _blit(frame, g2, WIDTH // 2 + sign * gap - g2.width / 2, 1250 - g2.height / 2)
        elif v == "rain":  # 유리창을 타고 내리는 빗줄기
            rng = random.Random(7)
            for _ in range(70):
                x = rng.randint(0, WIDTH)
                speed = rng.uniform(500, 1100)
                y = (rng.randint(0, HEIGHT) + local * speed) % (HEIGHT + 200) - 100
                d.line((x, y, x - 6, y + 60), fill=(200, 220, 255, rng.randint(30, 80)), width=2)


def draw_text_block(frame: Image.Image, block: TextBlock, look: Look, local: float, exit_p: float, simple: bool = False) -> None:
    """kinetic text(rise/pop/blur) + 강조 마크. V2 장면과 6-52 V3 프레임이 같이 쓴다."""
    motion = "rise" if simple else look.motion
    d = ImageDraw.Draw(frame, "RGBA")
    fade = 1 - exit_p
    exit_dy = -40 * ease_out_cubic(exit_p) if motion == "rise" else 0.0
    if not simple and look.emphasis in ("box", "color_underline"):  # 강조 구간은 글자보다 먼저(뒤에) 그린다
        for m in block.marks:
            if look.emphasis == "box":  # 형광펜처럼 왼쪽에서 오른쪽으로 칠해진다
                u = ease_out_cubic((local - m.order * 0.06) / 0.22)
            else:  # 줄이 올라온 뒤 밑줄이 그어진다
                u = ease_out_cubic((local - m.line * 0.12 - 0.35) / 0.3)
            if u <= 0:
                continue
            x0, y0, x1, y1 = m.rect
            dy = exit_dy
            radius = 14 if look.emphasis == "box" else 4
            d.rounded_rectangle((x0, y0 + dy, x0 + max(2 * radius, (x1 - x0) * u), y1 + dy), radius=radius, fill=look.accent + (int(255 * fade),))
    for w in block.words:
        if motion == "rise":  # 줄 단위로 아래에서 올라오며 등장
            q = (local - w.line * 0.12) / 0.38
            if q <= 0:
                continue
            e = ease_out_cubic(q)
            _blit(frame, w.image, w.x, w.y + 46 * (1 - e) + exit_dy, e * fade)
        elif motion == "pop":  # 어절 단위 팝(살짝 크게 -> 제자리)
            q = (local - w.order * 0.06) / 0.28
            if q <= 0:
                continue
            s = 1 + 0.22 * (1 - ease_out_back(q, 2.2)) if q < 1 else 1.0
            s *= 1 - 0.1 * exit_p
            img = w.image
            if abs(s - 1) > 0.01:
                img = img.resize((max(1, int(img.width * s)), max(1, int(img.height * s))), Image.BILINEAR)
            _blit(frame, img, w.x + (w.image.width - img.width) / 2, w.y + (w.image.height - img.height) / 2, _clamp(q * 3) * fade)
        else:  # blur: 흐릿하게 떠올라 선명해진다(시네마틱)
            q = (local - w.line * 0.35) / 0.8
            if q <= 0:
                continue
            e = ease_out_cubic(q)
            img = w.image
            radius = 9 * (1 - e)
            if radius > 0.6:
                img = _blurred(img, round(radius))
            _blit(frame, img, w.x, w.y + 18 * (1 - e), e * fade)


@lru_cache(maxsize=32)
def _glow_cached(radius: int, color: RGB, alpha: int) -> Image.Image:
    return _glow(radius, color, alpha)


_BLUR_CACHE: dict = {}


def _blurred(img: Image.Image, radius: int) -> Image.Image:
    key = (id(img), radius)
    if key not in _BLUR_CACHE:
        if len(_BLUR_CACHE) > 400:
            _BLUR_CACHE.clear()
        _BLUR_CACHE[key] = (img, img.filter(ImageFilter.GaussianBlur(radius)))
    return _BLUR_CACHE[key][1]


# --- 인코딩 ----------------------------------------------------------------------

@dataclass(frozen=True)
class RenderResultV2:
    output_path: Path
    duration_seconds: float
    frames: int
    scenes: int
    has_audio: bool


def render_short_v2(spec: ShortSpec, output_path: Path | str, *, ffmpeg_path: str = "ffmpeg",
                    fps: int = DEFAULT_FPS, audio: bool = True, max_seconds: float | None = None) -> RenderResultV2:
    """spec을 MP4로 렌더링한다. 프레임은 rawvideo로 ffmpeg stdin에 흘려보낸다
    (중간 PNG 수천 장을 디스크에 쓰지 않는다). ``max_seconds``는 테스트용 부분 렌더."""
    renderer = ShortsV2Renderer(spec, fps)
    total = renderer.total if max_seconds is None else min(renderer.total, max_seconds)
    frames = encode_frames(renderer.frame, total, Path(output_path), ffmpeg_path=ffmpeg_path, fps=fps,
                           soundtrack=(lambda wav: synthesize_soundtrack(spec, wav)) if audio else None)
    return RenderResultV2(Path(output_path), frames / fps, frames, len(renderer.timeline), audio)


LOUDNORM = "loudnorm=I=-14:TP=-1.5:LRA=11"


def encode_frames(frame_at, total: float, output_path: Path, *, ffmpeg_path: str = "ffmpeg", fps: int = DEFAULT_FPS,
                  soundtrack=None, audio_filter: str = LOUDNORM) -> int:
    """``frame_at(t)`` 프레임을 rawvideo로 ffmpeg stdin에 흘려 H.264(+AAC) MP4를 만든다.
    ``soundtrack(wav_path)``가 있으면 그 WAV를 오디오로 붙인다. 반환값은 프레임 수. (V2/V3 공용)"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frames = int(round(total * fps))
    with tempfile.TemporaryDirectory(prefix="tak_shorts_") as tmp:
        cmd = [ffmpeg_path, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
               "-s", f"{WIDTH}x{HEIGHT}", "-r", str(fps), "-i", "-"]
        if soundtrack is not None:
            wav = Path(tmp) / "soundtrack.wav"
            soundtrack(wav)
            cmd += ["-i", str(wav), "-map", "0:v", "-map", "1:a",
                    "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
                    "-af", audio_filter, "-shortest"]
        cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-profile:v", "high",
                "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output_path)]
        log_path = Path(tmp) / "ffmpeg.log"
        with log_path.open("wb") as log:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=log)
            try:
                for n in range(frames):
                    proc.stdin.write(frame_at(n / fps).convert("RGB").tobytes())
                proc.stdin.close()
            except BrokenPipeError:
                pass
            code = proc.wait()
        if code != 0:
            raise ShortsRenderError(f"ffmpeg 인코딩 실패(exit={code}): {log_path.read_text(errors='replace')[-1500:]}")
    return frames


def spec_from_shorts_script(script: ShortsScript, style: str = "finance", bpm: float = 100) -> ShortSpec:
    """6-40 ShortsScript(카드뉴스 대본)를 6-41 장면 설계로 옮기는 호환 경로.
    카드 문장은 그대로 쓰므로 길이 규칙(3줄)에 걸리면 SceneSpecError/ShortsRenderError로
    드러난다 - 카드뉴스 문장을 그대로 영상에 붓지 말라는 신호다."""
    scenes = [Scene(role="HOOK", text=script.title, transition="cut", audio=("impact",))]
    for k, card in enumerate(script.cards):
        scenes.append(Scene(role="INFO", text=card, transition="punch", audio=("whoosh",)))
    scenes.append(Scene(role="TAKEAWAY", text=script.takeaway, transition="punch", audio=("pop",)))
    scenes.append(Scene(role="BRAND", text="", layout="brand", audio=("chime",), beats=4))
    spec = ShortSpec(id="from-6-40", style=style, bpm=bpm, idea=script.subtitle, scenes=tuple(scenes), brand=script.brand)
    validate_spec(spec)
    return spec
