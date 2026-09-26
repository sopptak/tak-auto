"""Shorts V3(6-52) 레이아웃 엔진 + 렌더러 - 콘텐츠와 무관한 화면 틀.

화면(1080x1920)은 템플릿이 정한 세 프레임으로 나뉜다:

    TITLE   : 워터마크(브랜드) + 제목만. 긴 제목은 줄바꿈 + 폰트 자동 축소(템플릿 범위 안)
    CONTENT : layout_type(템플릿 "layouts")에 따라 IMAGE 슬롯 + HEADLINE/BODY
    FOOTER  : 자막(subtitle) + 출처(source) + 진행 표시(bar/counter). 비면 CONTENT가 내려와 채운다

6-41 V2에서 재사용: layout_text(어절 줄바꿈/강조), draw_text_block(kinetic text),
Look 팔레트, 비네트/그레인, encode_frames(ffmpeg 파이프), 합성 사운드트랙.
넘치는 텍스트는 템플릿의 최소 폰트까지 줄여 보고, 그래도 안 되면 조용히 자르지 않고
V3LayoutError로 실패한다(출처 한 줄만 예외: 말줄임 + 경고). 이미지가 없거나 못 읽으면
그라디언트 placeholder로 대체하고 경고만 남긴다(전체 렌더를 실패시키지 않는다).

``data/``를 읽거나 쓰지 않는다. 외부 API를 호출하지 않는다(로컬 ffmpeg만).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

from content_engine.shorts_renderer import ShortsRenderError
from content_engine.shorts_v2_audio import synthesize_soundtrack
from content_engine.shorts_v2_renderer import (
    LOOKS, LOUDNORM, Look, TextBlock, _blit, _clamp, _font, _gradient, _radial_mask, draw_text_block,
    ease_in_out, ease_out_cubic, encode_frames, layout_text,
)
from content_engine.shorts_v2_scene import HEIGHT, WIDTH, Scene, ShortSpec
from content_engine.shorts_v3_document import ShortsV3Document, TimedV3Scene, build_v3_timeline

Rect = tuple[int, int, int, int]
PLATE_SCALE = 1.08


class V3LayoutError(ShortsRenderError):
    """텍스트가 템플릿 최소 폰트로도 프레임에 들어가지 않을 때(overflow)."""


def _sub(frame: Rect, frac) -> Rect:
    x0, y0, x1, y1 = frame
    return (round(x0 + (x1 - x0) * frac[0]), round(y0 + (y1 - y0) * frac[1]),
            round(x0 + (x1 - x0) * frac[2]), round(y0 + (y1 - y0) * frac[3]))


def _inside(box: Rect, rect: Rect) -> bool:
    return box[0] >= rect[0] and box[1] >= rect[1] and box[2] <= rect[2] and box[3] <= rect[3]


def text_look(base: Look, spec: dict) -> Look:
    return Look(**{**base.__dict__, "weight": spec.get("weight", base.weight),
                   "text": tuple(spec.get("color", base.text))})


def fit_text(text: str, look: Look, rect: Rect, spec: dict) -> TextBlock:
    """rect 안에 들어가는 가장 큰 폰트(size_max -> size_min)로 배치한다. 못 넣으면 V3LayoutError."""
    x0, y0, x1, y1 = rect
    for size in range(int(spec["size_max"]), int(spec["size_min"]) - 1, -2):
        try:
            block = layout_text(text, look, (y0 + y1) // 2, size=size, max_lines=int(spec["max_lines"]),
                                max_width=x1 - x0, center_x=(x0 + x1) // 2)
        except ShortsRenderError:
            continue
        if block.bbox[3] - block.bbox[1] <= y1 - y0 and block.bbox[0] >= x0 and block.bbox[2] <= x1:
            return block
    raise V3LayoutError(
        f"텍스트가 프레임 {rect}에 들어가지 않습니다(최소 {spec['size_min']}px, 최대 {spec['max_lines']}줄): "
        f"{text[:40]!r} - 문장을 나누거나 장면을 늘리세요."
    )


def shift_block(block: TextBlock, dy: int) -> TextBlock:
    for w in block.words:
        w.y += dy
    for m in block.marks:
        m.rect = (m.rect[0], m.rect[1] + dy, m.rect[2], m.rect[3] + dy)
    block.bbox = (block.bbox[0], block.bbox[1] + dy, block.bbox[2], block.bbox[3] + dy)
    return block


def _height(block: TextBlock | None) -> int:
    return block.bbox[3] - block.bbox[1] if block else 0


@dataclass
class SceneLayout:
    timed: TimedV3Scene
    content: Rect = (0, 0, 0, 0)
    image_rect: Rect | None = None
    image: Image.Image | None = None  # RGB, Ken Burns용으로 image_rect보다 약간 크게 준비
    image_status: str = "none"  # none / loaded / fallback:missing / fallback:unreadable
    scrim: bool = False
    credit: Image.Image | None = None
    headline: TextBlock | None = None
    body: TextBlock | None = None
    subtitle: TextBlock | None = None
    source: TextBlock | None = None
    boxes: list = field(default_factory=list)  # (이름, bbox, 들어가야 할 프레임)
    warnings: list = field(default_factory=list)


class ShortsV3Renderer:
    def __init__(self, doc: ShortsV3Document, fps: int | None = None) -> None:
        tpl = doc.template
        if (tpl["canvas"]["width"], tpl["canvas"]["height"]) != (WIDTH, HEIGHT):
            raise ShortsRenderError(f"V3는 {WIDTH}x{HEIGHT}만 지원합니다: {tpl['canvas']}")
        self.doc, self.tpl = doc, tpl
        self.fps = int(fps or tpl["canvas"]["fps"])
        self.look = LOOKS[tpl["look"]]
        self.frames = {k: tuple(v) for k, v in tpl["frames"].items()}
        self.safe = tuple(tpl["safe_area"])
        self.timeline = build_v3_timeline(doc)
        self.total = self.timeline[-1].end
        self.content_total = sum(ts.duration for ts in self.timeline if ts.scene is not None)
        self.rng = random.Random(f"{doc.id}-6-52")
        self._title_layout()
        self.layouts = [self._scene_layout(ts) for ts in self.timeline]
        self.plate = self._plate()
        self.vignette = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
        self.vignette.putalpha(_radial_mask((WIDTH, HEIGHT), 0.35, 1.0, 150))
        self.grain = []
        for _ in range(4):
            noise = Image.effect_noise((WIDTH // 2, HEIGHT // 2), 60).resize((WIDTH, HEIGHT), Image.NEAREST)
            self.grain.append(Image.merge("RGBA", (noise, noise, noise, Image.new("L", (WIDTH, HEIGHT), self.look.grain))))

    # ---- 레이아웃 ----
    def _progress_row(self) -> Rect | None:
        p = self.doc.progress
        if not p.get("enabled", True) or p.get("position", "footer") != "footer":
            return None
        x0, _, x1, y1 = self.frames["footer"]
        return (x0, y1 - 40, x1, y1)

    def _title_layout(self) -> None:
        x0, y0, x1, y1 = self.frames["title"]
        brand, progress = self.doc.brand, self.doc.progress
        top_row = brand.get("watermark", True) or (progress.get("enabled", True) and progress.get("position") == "top")
        self.title_rect = (x0, y0 + (64 if top_row else 0), x1, y1)
        self.title_look = text_look(self.look, self.tpl["text"]["title"])
        self.title = fit_text(self.doc.title, self.title_look, self.title_rect, self.tpl["text"]["title"])
        self.title_boxes = [("title", self.title.bbox, self.frames["title"])]
        self.watermark = None
        if brand.get("watermark", True) and brand.get("text"):
            spec = self.tpl["text"]["watermark"]
            font = _font(self.look.font, int(spec["size"]), int(spec["weight"]))
            text = brand["text"]
            img = Image.new("RGBA", (int(font.getlength(text)) + 60, 60), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            d.ellipse((6, 22, 22, 38), fill=self.look.accent + (255,))
            d.text((34, 12), text, font=font, fill=(255, 255, 255, 200))
            self.watermark = (img, x0, y0 + (22 if progress.get("position") == "top" else 6))
            self.title_boxes.append(("watermark", (x0, self.watermark[2], x0 + img.width, self.watermark[2] + img.height), self.frames["title"]))

    def _scene_layout(self, ts: TimedV3Scene) -> SceneLayout:
        lay = SceneLayout(ts)
        scene = ts.scene
        if scene is None:  # 엔드카드: 브랜드 + CTA
            return lay
        text_spec = self.tpl["text"]
        fx0, fy0, fx1, fy1 = self.frames["footer"]
        progress_row = self._progress_row()
        bottom = progress_row[1] - 8 if progress_row else fy1
        # FOOTER: 아래에서 위로 쌓는다(출처 -> 자막). 비어 있으면 CONTENT가 그만큼 내려온다.
        cursor = bottom
        if scene.source:
            rect = (fx0, cursor - 40, fx1, cursor)
            lay.source = self._fit_source(scene.source, rect, lay)
            lay.boxes.append(("source", lay.source.bbox, self.frames["footer"]))
            cursor = rect[1] - 6
        if scene.subtitle:
            rect = (fx0, max(fy0, cursor - 64), fx1, cursor)
            lay.subtitle = fit_text(scene.marked(scene.subtitle), text_look(self.look, text_spec["subtitle"]), rect, text_spec["subtitle"])
            lay.boxes.append(("subtitle", lay.subtitle.bbox, self.frames["footer"]))
            cursor = rect[1]
        cx0, cy0, cx1, cy1 = self.frames["content"]
        content = (cx0, cy0, cx1, cy1 if (scene.source or scene.subtitle) else max(cy1, bottom - 16))
        lay.content = content
        geometry = self.tpl["layouts"][scene.layout]
        if "image" in geometry:
            lay.image_rect = _sub(content, geometry["image"])
            lay.scrim = bool(geometry.get("scrim"))
            self._prepare_image(scene, lay)
            lay.boxes.append(("image", lay.image_rect, content))
        if "text" in geometry and (scene.headline or scene.body):
            self._text_group(scene, _sub(content, geometry["text"]), lay)
        return lay

    def _fit_source(self, source: str, rect: Rect, lay: SceneLayout) -> TextBlock:
        spec = self.tpl["text"]["source"]
        look = text_look(self.look, spec)
        text = f"{spec.get('prefix', '')}{source}"
        while True:
            try:
                return fit_text(text.replace("*", ""), look, rect, spec)
            except V3LayoutError:
                if len(text) <= 8:
                    raise
                text = text[:-2].rstrip() + "…" if not text.endswith("…") else text[:-3].rstrip() + "…"
                if "source_truncated" not in lay.warnings:
                    lay.warnings.append("source_truncated")  # 원문 출처는 문서/lineage에 그대로 있다

    def _text_group(self, scene, rect: Rect, lay: SceneLayout) -> None:
        spec, gap = self.tpl["text"], int(self.tpl["text"]["gap"])
        x0, y0, x1, y1 = rect
        if scene.headline:
            head_rect = (x0, y0, x1, y0 + (y1 - y0) * (45 if scene.body else 100) // 100)
            lay.headline = fit_text(scene.marked(scene.headline), text_look(self.look, spec["headline"]), head_rect, spec["headline"])
        if scene.body:
            top = y0 + (_height(lay.headline) + gap if lay.headline else 0)
            lay.body = fit_text(scene.marked(scene.body), text_look(self.look, spec["body"]), (x0, top, x1, y1), spec["body"])
        # 헤드라인 + 본문 묶음을 영역 가운데에 세운다
        total = _height(lay.headline) + _height(lay.body) + (gap if lay.headline and lay.body else 0)
        top = y0 + (y1 - y0 - total) // 2
        if lay.headline:
            shift_block(lay.headline, top - lay.headline.bbox[1])
            lay.boxes.append(("headline", lay.headline.bbox, rect))
            top = lay.headline.bbox[3] + gap
        if lay.body:
            shift_block(lay.body, top - lay.body.bbox[1])
            lay.boxes.append(("body", lay.body.bbox, rect))

    def _prepare_image(self, scene, lay: SceneLayout) -> None:
        x0, y0, x1, y1 = lay.image_rect
        kb = 1 + float(self.tpl["image"].get("ken_burns", 0))
        w, h = int((x1 - x0) * kb), int((y1 - y0) * kb)
        path = self.doc.image_path(scene)
        img = None
        if path is not None:
            try:
                with Image.open(path) as src:
                    img = ImageOps.exif_transpose(src).convert("RGB")
                lay.image_status = "loaded"
            except (OSError, ValueError):
                lay.image_status = "fallback:missing" if not path.exists() else "fallback:unreadable"
                lay.warnings.append(f"image {lay.image_status}: {scene.image.path}")
        else:
            lay.image_status = "fallback:missing"
        if img is None:
            lay.image = self._placeholder((w, h))
        else:  # cover 크롭: 기준점(image_position) 주위를 image_scale만큼 확대해 영역 비율로 자른다
            iw, ih = img.size
            aspect = w / h
            cw, ch = (ih * aspect, ih) if iw / ih > aspect else (iw, iw / aspect)
            cw, ch = cw / scene.image_scale, ch / scene.image_scale
            fx, fy = scene.image_position
            cx = min(max(fx * iw, cw / 2), iw - cw / 2)
            cy = min(max(fy * ih, ch / 2), ih - ch / 2)
            lay.image = img.crop((int(cx - cw / 2), int(cy - ch / 2), int(cx + cw / 2), int(cy + ch / 2))).resize((w, h), Image.LANCZOS)
        if scene.image and scene.image.source:
            lay.credit = self._credit(scene.image.source, x1 - x0)

    def _placeholder(self, size) -> Image.Image:
        look = self.look
        img = _gradient(size, tuple(min(255, c + 22) for c in look.bg_bottom), look.bg_top)
        d = ImageDraw.Draw(img, "RGBA")
        w, h = size
        for y in range(18, h, 36):
            for x in range(18, w, 36):
                d.ellipse((x - 2, y - 2, x + 2, y + 2), fill=look.accent2 + (60,))
        cx, cy, r = w // 2, h // 2, min(w, h) // 7  # 이미지 자리 표시(산 + 해)
        d.polygon([(cx - 2 * r, cy + r), (cx - r // 2, cy - r // 2), (cx + r // 2, cy + r // 3), (cx + r, cy - r // 6), (cx + 2 * r, cy + r)], fill=look.accent2 + (90,))
        d.ellipse((cx + r // 2, cy - 2 * r, cx + r + r // 2, cy - r), fill=look.accent + (140,))
        return img

    def _credit(self, text: str, max_w: int) -> Image.Image:
        font = _font(self.look.font, int(self.tpl["image"].get("credit_size", 22)), 500)
        while font.getlength(text) > max_w - 60 and len(text) > 4:
            text = text[:-2].rstrip("…") + "…"
        tw = int(font.getlength(text))
        img = Image.new("RGBA", (tw + 28, 40), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((0, 0, img.width - 1, 39), radius=12, fill=(0, 0, 0, 150))
        d.text((14, 7), text, font=font, fill=(235, 235, 235, 230))
        return img

    def _plate(self) -> Image.Image:
        look = self.look
        size = (int(WIDTH * PLATE_SCALE), int(HEIGHT * PLATE_SCALE))
        img = _gradient(size, look.bg_top, look.bg_bottom)
        d = ImageDraw.Draw(img, "RGBA")
        for y in range(27, size[1], 54):
            for x in range(27, size[0], 54):
                d.ellipse((x - 3, y - 3, x + 3, y + 3), fill=(80, 90, 110, 120))
        return img

    # ---- 프레임 합성 ----
    def scene_at(self, t: float) -> int:
        for i, ts in enumerate(self.timeline):
            if t < ts.end:
                return i
        return len(self.timeline) - 1

    def _background(self, t: float) -> Image.Image:
        z = 1 + 0.04 * ease_in_out(_clamp(t / max(self.total, 0.01)))
        pw, ph = self.plate.size
        cw, ch = pw / (PLATE_SCALE * z), ph / (PLATE_SCALE * z)
        return self.plate.crop((int((pw - cw) / 2), int((ph - ch) / 2), int((pw + cw) / 2), int((ph + ch) / 2))).resize((WIDTH, HEIGHT), Image.BILINEAR)

    def frame(self, t: float) -> Image.Image:
        i = self.scene_at(t)
        ts = self.timeline[i]
        local = t - ts.start
        img = self._background(t)
        self._draw_scene(img, i, local)
        scene = ts.scene
        transition = scene.transition if scene is not None else "punch"
        region = (0, self.frames["content"][1] - 20, WIDTH, self.frames["footer"][3] + 10)
        if transition == "dissolve" and i > 0 and local < 0.5:
            prev = self._background(t)
            self._draw_scene(prev, i - 1, self.timeline[i - 1].duration - 0.001)
            mixed = Image.blend(prev.crop(region), img.crop(region), ease_in_out(local / 0.5))
            img.paste(mixed, region[:2])
        elif transition == "punch" and i > 0 and local < 0.3:  # 박자 위 짧은 줌 펀치(콘텐츠 영역만 - 제목은 고정)
            z = 1 + 0.045 * (1 - ease_out_cubic(local / 0.3))
            part = img.crop(region)
            rw, rh = part.size
            cw, ch = rw / z, rh / z
            part = part.crop((int((rw - cw) / 2), int((rh - ch) / 2), int((rw + cw) / 2), int((rh + ch) / 2))).resize((rw, rh), Image.BILINEAR)
            img.paste(part, region[:2])
        img.paste(self.vignette, (0, 0), self.vignette)
        grain = self.grain[int(t * 12) % len(self.grain)]
        img.paste(grain, (0, 0), grain)
        if scene is not None:
            self._overlay(img, t, i)
        return img

    def _exit(self, ts: TimedV3Scene, local: float) -> float:
        if ts.index == len(self.timeline) - 1:
            return 0.0
        exit_s = float(self.tpl["timing"]["exit_seconds"])
        return _clamp((local - (ts.duration - exit_s)) / exit_s)

    def _draw_scene(self, img: Image.Image, i: int, local: float) -> None:
        lay = self.layouts[i]
        ts = lay.timed
        if ts.scene is None:
            self._end_card(img, local)
            return
        exit_p = self._exit(ts, local)
        if i == 0:
            local += float(self.tpl["timing"]["hook_headstart"])
        if lay.image is not None:
            self._draw_image(img, lay, local, exit_p)
        text_spec = self.tpl["text"]
        if lay.headline:
            draw_text_block(img, lay.headline, text_look(self.look, text_spec["headline"]), local, exit_p)
        if lay.body:
            draw_text_block(img, lay.body, text_look(self.look, text_spec["body"]), local - (0.2 if lay.headline else 0.0), exit_p)
        if lay.subtitle:
            draw_text_block(img, lay.subtitle, text_look(self.look, text_spec["subtitle"]), local - 0.3, exit_p, simple=True)
        if lay.source:
            draw_text_block(img, lay.source, text_look(self.look, text_spec["source"]), local - 0.5, exit_p, simple=True)

    def _draw_image(self, img: Image.Image, lay: SceneLayout, local: float, exit_p: float) -> None:
        x0, y0, x1, y1 = lay.image_rect
        w, h = x1 - x0, y1 - y0
        p = _clamp(local / lay.timed.duration)
        src = lay.image
        z = src.width / w - (src.width / w - 1) * ease_in_out(p)  # 준비한 여유분만큼 천천히 줌 인
        cw, ch = w * z, h * z
        ox, oy = (src.width - cw) / 2, (src.height - ch) / 2
        part = src.crop((int(ox), int(oy), int(ox + cw), int(oy + ch))).resize((w, h), Image.BILINEAR).convert("RGBA")
        if lay.scrim:  # 전체 이미지 위 글자 가독성: 아래쪽을 어둡게
            shade = Image.new("L", (1, 256))
            for k in range(256):
                shade.putpixel((0, k), int(210 * _clamp((k / 255 - 0.35) / 0.65)))
            dark = Image.new("RGBA", (w, h), (0, 0, 0, 255))
            dark.putalpha(shade.resize((w, h)))
            part = Image.alpha_composite(part, dark)
        if lay.credit is not None:
            part.alpha_composite(lay.credit, (w - lay.credit.width - 14, h - lay.credit.height - 14))
        radius = int(self.tpl["image"].get("radius", 0))
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=255)
        part.putalpha(mask)
        q = ease_out_cubic(_clamp(local / 0.35))
        _blit(img, part, x0, y0 + 24 * (1 - q), q * (1 - exit_p))

    def _overlay(self, img: Image.Image, t: float, i: int) -> None:
        """영상 전체에 고정된 요소: 제목, 워터마크, 진행 표시."""
        draw_text_block(img, self.title, self.title_look, t + float(self.tpl["timing"]["hook_headstart"]), 0.0)
        if self.watermark is not None:
            wm, x, y = self.watermark
            _blit(img, wm, x, y, 0.9)
        p = self.doc.progress
        if not p.get("enabled", True):
            return
        h = int(p.get("height", 6))
        if p.get("position", "footer") == "top":
            x0, y0, x1, _ = self.frames["title"]
            bar = (x0, y0, x1, y0 + h)
        else:
            x0, _, x1, y1 = self._progress_row()
            bar = (x0, y1 - h, x1, y1)
        d = ImageDraw.Draw(img, "RGBA")
        d.rounded_rectangle(bar, radius=h // 2, fill=(255, 255, 255, 40))
        frac = _clamp(t / max(self.content_total, 0.01))
        d.rounded_rectangle((bar[0], bar[1], bar[0] + max(h, int((bar[2] - bar[0]) * frac)), bar[3]), radius=h // 2, fill=self.look.accent + (255,))
        if p.get("counter", True):
            spec = self.tpl["text"]["counter"]
            font = _font(self.look.font, int(spec["size"]), int(spec["weight"]))
            n = sum(1 for ts in self.timeline if ts.scene is not None)
            label = f"{i + 1:02d} / {n:02d}"
            d.text((bar[2] - font.getlength(label), bar[1] - int(spec["size"]) - 10), label, font=font, fill=(255, 255, 255, 190))

    def _end_card(self, img: Image.Image, local: float) -> None:
        look, brand = self.look, self.doc.brand
        cx, cy = (self.safe[0] + self.safe[2]) // 2, 860
        d = ImageDraw.Draw(img, "RGBA")
        text = brand.get("text", "")
        if text:
            font = _font(look.font, 104, 900)
            tw = font.getlength(text)
            w = (tw + 60) * ease_out_cubic(_clamp(local / 0.35))
            d.rounded_rectangle((cx - w / 2, cy - 90, cx + w / 2, cy + 70), radius=24, fill=look.accent + (255,))
            if local > 0.2:
                d.text((cx - tw / 2, cy - 78), text, font=font, fill=(8, 10, 14, int(255 * _clamp((local - 0.2) / 0.2))))
        cta = brand.get("cta", "")
        if cta:
            sub = _font(look.font, 40, 500)
            d.text((cx - sub.getlength(cta) / 2, cy + 120), cta, font=sub, fill=(255, 255, 255, int(170 * _clamp((local - 0.6) / 0.5))))

    # ---- 검사용 ----
    def layout_report(self) -> dict:
        """모든 텍스트/이미지 bbox와 그것이 들어가야 할 프레임 - overflow/안전영역 검사 입력."""
        scenes = []
        for lay in self.layouts:
            ts = lay.timed
            scenes.append({
                "index": ts.index, "end_card": ts.scene is None, "layout": ts.scene.layout if ts.scene else "end_card",
                "start": round(ts.start, 3), "duration": round(ts.duration, 3), "beats": ts.beats,
                "image": lay.image_status, "warnings": list(lay.warnings),
                "boxes": [{"name": n, "bbox": list(b), "frame": list(f)} for n, b, f in lay.boxes],
            })
        overflow = [f"title: {n} {b} not in {f}" for n, b, f in self.title_boxes if not (_inside(b, f) and _inside(b, self.safe))]
        for s in scenes:
            for box in s["boxes"]:
                if not (_inside(box["bbox"], box["frame"]) and _inside(box["bbox"], self.safe)):
                    overflow.append(f"scene {s['index']}: {box['name']} {box['bbox']} not in {box['frame']}")
        return {"title": {"bbox": list(self.title.bbox), "lines": self.title.lines}, "scenes": scenes,
                "total": round(self.total, 3), "overflow": overflow}


def soundtrack_spec(doc: ShortsV3Document, timeline: tuple[TimedV3Scene, ...]) -> ShortSpec:
    """V3 타임라인을 6-41 합성기가 읽는 장면 목록으로 옮긴다(박자 수 그대로 - 음악은 새로 만들지 않는다)."""
    scenes = tuple(
        Scene(role="BRAND", text="", layout="brand", audio=("chime",), beats=ts.beats) if ts.scene is None
        else Scene(role="HOOK" if ts.index == 0 else "INFO", text="", audio=tuple(ts.scene.audio), beats=ts.beats)
        for ts in timeline
    )
    return ShortSpec(id=doc.id or "v3", style=doc.audio["background"], bpm=float(doc.audio["bpm"]), idea="", scenes=scenes)


@dataclass(frozen=True)
class RenderResultV3:
    output_path: Path
    duration: float
    frames: int
    scenes: int
    audio: bool
    layout: dict


def render_short_v3(doc: ShortsV3Document, output_path: Path | str, *, ffmpeg_path: str = "ffmpeg",
                    max_seconds: float | None = None) -> RenderResultV3:
    renderer = ShortsV3Renderer(doc)
    total = renderer.total if max_seconds is None else min(renderer.total, max_seconds)
    audio = doc.audio
    soundtrack, audio_filter = None, LOUDNORM
    if audio.get("enabled", True):
        soundtrack = lambda wav: synthesize_soundtrack(soundtrack_spec(doc, renderer.timeline), wav)  # noqa: E731
        fade_out = float(audio.get("fade_out", 0))
        audio_filter += f",volume={float(audio.get('volume', 1.0))}"
        if float(audio.get("fade_in", 0)) > 0:
            audio_filter += f",afade=t=in:d={float(audio['fade_in'])}"
        if fade_out > 0:
            audio_filter += f",afade=t=out:st={max(0.0, total - fade_out):.3f}:d={fade_out}"
    frames = encode_frames(renderer.frame, total, Path(output_path), ffmpeg_path=ffmpeg_path, fps=renderer.fps,
                           soundtrack=soundtrack, audio_filter=audio_filter)
    return RenderResultV3(Path(output_path), frames / renderer.fps, frames, len(renderer.timeline),
                          soundtrack is not None, renderer.layout_report())
