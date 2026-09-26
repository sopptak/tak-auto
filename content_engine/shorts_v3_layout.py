"""Shorts V3 레이아웃 엔진(6-53) - V3RenderDocument + 템플릿 -> 장면별 배치(글자 블록, 이미지, bbox).

프레임(템플릿 frames):
    TITLE   : 워터마크 줄 + 제목(자동 줄바꿈/축소, 정렬)
    CONTENT : layout_type -> 템플릿 layouts의 영역(image/text 비율). 영역 종류마다 handler가 배치한다
              (새 layout_type = 템플릿에 영역 추가. 새 영역 종류 = REGION_HANDLERS에 handler 추가)
    FOOTER  : 자막 + 출처(+ 진행 표시 줄). 비면 CONTENT가 내려와 채운다

텍스트 엔진(넘칠 때 순서): 1) 폰트 size_max -> size_min  2) 줄 간격 line_gap -> line_gap_min
3) 영역 확장(헤드라인 최소화, 템플릿 layouts.<type>.fallback 기하, 빈 footer)  4) 그래도 안 되면
오류 코드(TITLE/HEADLINE/BODY/SUBTITLE_OVERFLOW)로 BLOCK. 문장을 자르거나 요약하지 않는다
(출처 한 줄만 말줄임 + SOURCE_TRUNCATED 경고).

엔진은 예외 대신 ``issues``(코드/심각도/장면/메시지)를 모은다 - 품질 게이트가 그대로 보고한다.
6-41 V2의 layout_text(어절 줄바꿈/강조)와 Look 팔레트를 재사용한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from content_engine.shorts_renderer import ShortsRenderError
from content_engine.shorts_v2_renderer import LOOKS, Look, TextBlock, _font, _gradient, layout_text
from content_engine.shorts_v3_document import TimedV3Scene, V3RenderDocument, V3Scene, build_v3_timeline
from content_engine.shorts_v3_template import V3Error

Rect = tuple[int, int, int, int]
BLOCKING_LAYOUT_CODES = ("TITLE_OVERFLOW", "HEADLINE_OVERFLOW", "BODY_OVERFLOW", "SUBTITLE_OVERFLOW", "SOURCE_OVERFLOW")


class V3LayoutError(V3Error, ShortsRenderError):
    """배치가 불가능한 문서(넘치는 텍스트). code는 첫 번째 차단 코드."""

    def __init__(self, code: str, message: str) -> None:
        V3Error.__init__(self, code, message)


def sub_rect(frame: Rect, frac) -> Rect:
    x0, y0, x1, y1 = frame
    return (round(x0 + (x1 - x0) * frac[0]), round(y0 + (y1 - y0) * frac[1]),
            round(x0 + (x1 - x0) * frac[2]), round(y0 + (y1 - y0) * frac[3]))


def inside(box: Rect, rect: Rect) -> bool:
    return box[0] >= rect[0] and box[1] >= rect[1] and box[2] <= rect[2] and box[3] <= rect[3]


def text_look(base: Look, spec: dict, line_gap: float | None = None) -> Look:
    return Look(**{**base.__dict__, "weight": spec.get("weight", base.weight),
                   "text": tuple(spec.get("color", base.text)), "line_gap": line_gap or base.line_gap})


def shift_block(block: TextBlock, dy: int) -> TextBlock:
    for w in block.words:
        w.y += dy
    for m in block.marks:
        m.rect = (m.rect[0], m.rect[1] + dy, m.rect[2], m.rect[3] + dy)
    block.bbox = (block.bbox[0], block.bbox[1] + dy, block.bbox[2], block.bbox[3] + dy)
    return block


def blocks_height(blocks: list[TextBlock]) -> int:
    return blocks[-1].bbox[3] - blocks[0].bbox[1] if blocks else 0


def fit_paragraphs(text: str, base: Look, rect: Rect, spec: dict, *, max_size: int | None = None,
                   align: str = "center") -> list[TextBlock] | None:
    """rect 안에 들어가는 가장 큰 폰트/줄 간격으로 문단들을 쌓는다. 못 넣으면 None(자르지 않는다)."""
    x0, y0, x1, y1 = rect
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    pgap = int(spec.get("paragraph_gap", 0))
    gaps = [base.line_gap] + ([float(spec["line_gap_min"])] if float(spec.get("line_gap_min", base.line_gap)) < base.line_gap else [])
    for line_gap in gaps:
        look = text_look(base, spec, line_gap)
        for size in range(int(max_size or spec["size_max"]), int(spec["size_min"]) - 1, -2):
            blocks: list[TextBlock] = []
            try:
                for p in paragraphs:
                    blocks.append(layout_text(p, look, (y0 + y1) // 2, size=size, max_lines=int(spec["max_lines"]),
                                              max_width=x1 - x0, center_x=(x0 + x1) // 2))
            except ShortsRenderError:
                continue
            total = sum(b.bbox[3] - b.bbox[1] for b in blocks) + pgap * (len(blocks) - 1)
            if sum(b.lines for b in blocks) > int(spec["max_lines"]) or total > y1 - y0:
                continue
            if any(b.bbox[0] < x0 or b.bbox[2] > x1 for b in blocks):
                continue
            top = {"top": y0, "bottom": y1 - total}.get(align, y0 + (y1 - y0 - total) // 2)
            for b in blocks:
                shift_block(b, top - b.bbox[1])
                top = b.bbox[3] + pgap
            return blocks
    return None


@dataclass
class SceneLayout:
    timed: TimedV3Scene
    content: Rect = (0, 0, 0, 0)
    variant: str = "primary"  # primary | fallback(템플릿 대체 기하를 썼음)
    image_rect: Rect | None = None
    image: Image.Image | None = None  # RGB, Ken Burns용으로 image_rect보다 약간 크게 준비
    image_status: str = "none"  # none / loaded / fallback:empty / fallback:missing / fallback:unreadable
    scrim: bool = False
    credit: Image.Image | None = None
    credit_position: str = "bottom_right"  # 이미지 출처 표시 위치(템플릿/레이아웃 값)
    headline: list[TextBlock] = field(default_factory=list)
    body: list[TextBlock] = field(default_factory=list)
    subtitle: list[TextBlock] = field(default_factory=list)
    source: list[TextBlock] = field(default_factory=list)
    boxes: list = field(default_factory=list)  # (이름, bbox, 들어가야 할 프레임)
    issues: list = field(default_factory=list)


def _issue(code: str, severity: str, scene, message: str) -> dict:
    return {"code": code, "severity": severity, "scene": scene, "message": message}


# ---- 영역 handler: 템플릿 layouts의 영역 종류 하나를 배치한다 ----------------------------------

def _image_region(engine: "LayoutEngine", scene: V3Scene, rect: Rect, lay: SceneLayout, variant: dict) -> bool:
    lay.image_rect = rect
    lay.scrim = bool(variant.get("scrim"))
    lay.credit_position = variant.get("credit_position", engine.tpl["image"].get("credit_position", "bottom_right"))
    engine.prepare_image(scene, lay)
    lay.boxes.append(("image", rect, lay.content))
    return True


def _text_region(engine: "LayoutEngine", scene: V3Scene, rect: Rect, lay: SceneLayout, variant: dict) -> bool:
    if not (scene.headline or scene.body):
        return True
    return engine.text_group(scene, rect, lay)


REGION_HANDLERS = {"image": _image_region, "text": _text_region}


class LayoutEngine:
    def __init__(self, doc: V3RenderDocument) -> None:
        self.doc, self.tpl = doc, doc.template
        self.look = LOOKS[self.tpl["look"]]
        self.frames = {k: tuple(v) for k, v in self.tpl["frames"].items()}
        self.safe = tuple(self.tpl["safe_area"])
        self.timeline = build_v3_timeline(doc)
        self.issues: list[dict] = []
        self._title_layout()
        self.layouts = [self._scene_layout(ts) for ts in self.timeline]
        for lay in self.layouts:
            self.issues += lay.issues
        self._check_boxes()

    # ---- 제목 프레임 ----
    def progress_row(self) -> Rect | None:
        p = self.doc.progress
        if not p.get("enabled", True) or p.get("position", "footer") != "footer":
            return None
        x0, _, x1, y1 = self.frames["footer"]
        return (x0, y1 - int(self.tpl["footer_rows"]["progress"]), x1, y1)

    def _title_layout(self) -> None:
        x0, y0, x1, y1 = self.frames["title"]
        brand, progress = self.doc.brand, self.doc.progress
        spec = self.tpl["text"]["title"]
        top_row = brand.get("watermark", True) or (progress.get("enabled", True) and progress.get("position") == "top")
        self.title_rect = (x0, y0 + (int(spec.get("top_row", 0)) if top_row else 0), x1, y1)
        self.title_look = text_look(self.look, spec)
        self.title = fit_paragraphs(self.doc.title, self.look, self.title_rect, spec, align=spec.get("align", "center")) or []
        self.title_boxes = [("title", b.bbox, self.frames["title"]) for b in self.title]
        if not self.title:
            self.issues.append(_issue("TITLE_OVERFLOW", "error", None,
                                      f"제목이 TITLE 프레임에 안 들어갑니다(최소 {spec['size_min']}px, {spec['max_lines']}줄): {self.doc.title[:40]!r}"))
        self.watermark = None
        if brand.get("watermark", True) and brand.get("text"):
            wspec = self.tpl["text"]["watermark"]
            font = _font(self.look.font, int(wspec["size"]), int(wspec["weight"]))
            text = brand["text"]
            img = Image.new("RGBA", (int(font.getlength(text)) + 60, 60), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            d.ellipse((6, 22, 22, 38), fill=self.look.accent + (255,))
            d.text((34, 12), text, font=font, fill=(255, 255, 255, 200))
            wy = y0 + (22 if progress.get("position") == "top" else 6)
            self.watermark = (img, x0, wy)
            self.title_boxes.append(("watermark", (x0, wy, x0 + img.width, wy + img.height), self.frames["title"]))

    # ---- 장면 ----
    def _scene_layout(self, ts: TimedV3Scene) -> SceneLayout:
        lay = SceneLayout(ts)
        scene = ts.scene
        if scene is None:  # 엔드카드: 브랜드 + CTA
            return lay
        spec = self.tpl["text"]
        fx0, fy0, fx1, fy1 = self.frames["footer"]
        row = self.progress_row()
        rows = self.tpl["footer_rows"]
        bottom = row[1] - int(rows["gap"]) if row else fy1
        cursor = bottom  # FOOTER: 아래에서 위로(출처 -> 자막). 비어 있으면 CONTENT가 그만큼 내려온다
        if scene.source:
            rect = (fx0, cursor - int(rows["source"]), fx1, cursor)
            lay.source = self._fit_source(scene.source.display(self.tpl), rect, lay)
            lay.boxes += [("source", b.bbox, self.frames["footer"]) for b in lay.source]
            cursor = rect[1] - int(rows["gap"])
        if scene.subtitle:
            rect = (fx0, max(fy0, cursor - int(rows["subtitle"])), fx1, cursor)
            lay.subtitle = fit_paragraphs(scene.marked(scene.subtitle), self.look, rect, spec["subtitle"]) or []
            if not lay.subtitle:
                lay.issues.append(_issue("SUBTITLE_OVERFLOW", "error", ts.index, f"자막이 한 줄에 안 들어갑니다: {scene.subtitle[:30]!r}"))
            lay.boxes += [("subtitle", b.bbox, self.frames["footer"]) for b in lay.subtitle]
        cx0, cy0, cx1, cy1 = self.frames["content"]
        lay.content = (cx0, cy0, cx1, cy1 if (scene.source or scene.subtitle) else max(cy1, bottom - int(rows["content_gap"])))
        geometry = self.tpl["layouts"][scene.layout]
        variants = [("primary", geometry)] + ([("fallback", geometry["fallback"])] if geometry.get("fallback") else [])
        base_boxes, base_issues = list(lay.boxes), list(lay.issues)
        for name, variant in variants:
            lay.boxes, lay.issues, lay.headline, lay.body, lay.variant = list(base_boxes), list(base_issues), [], [], name
            ok = all(REGION_HANDLERS[kind](self, scene, sub_rect(lay.content, variant[kind]), lay, variant)
                     for kind in REGION_HANDLERS if kind in variant)
            if ok:
                break
        return lay

    def _fit_source(self, text: str, rect: Rect, lay: SceneLayout) -> list[TextBlock]:
        spec = self.tpl["text"]["source"]
        text = text.replace("*", "")
        while True:
            blocks = fit_paragraphs(text, self.look, rect, spec)
            if blocks:
                return blocks
            if len(text) <= 8:
                lay.issues.append(_issue("SOURCE_OVERFLOW", "error", lay.timed.index, "출처를 한 줄에 넣을 수 없습니다."))
                return []
            text = (text[:-2] if not text.endswith("…") else text[:-3]).rstrip() + "…"
            if not any(i["code"] == "SOURCE_TRUNCATED" for i in lay.issues):  # 원문 출처는 문서/lineage에 그대로 있다
                lay.issues.append(_issue("SOURCE_TRUNCATED", "warning", lay.timed.index, "출처가 길어 말줄임했습니다."))

    def text_group(self, scene: V3Scene, rect: Rect, lay: SceneLayout) -> bool:
        """헤드라인 + 본문 묶음. 본문이 안 들어가면 헤드라인을 최소 크기로 줄여 영역을 넓혀 본다."""
        spec, gap = self.tpl["text"], int(self.tpl["text"]["gap"])
        x0, y0, x1, y1 = rect
        attempts = [None, int(spec["headline"]["size_min"])] if scene.headline and scene.body else [None]
        for head_size in attempts:
            head: list[TextBlock] = []
            if scene.headline:
                share = float(spec["headline"].get("share", 0.45)) if scene.body else 1.0  # 본문이 있을 때 헤드라인 몫
                head_rect = (x0, y0, x1, y0 + int((y1 - y0) * share))
                head = fit_paragraphs(scene.marked(scene.headline), self.look, head_rect, spec["headline"], max_size=head_size) or []
                if not head:
                    continue
            body: list[TextBlock] = []
            if scene.body:
                top = y0 + (blocks_height(head) + gap if head else 0)
                body = fit_paragraphs(scene.marked(scene.body), self.look, (x0, top, x1, y1), spec["body"]) or []
                if not body:
                    continue
            total = blocks_height(head) + blocks_height(body) + (gap if head and body else 0)
            top = y0 + (y1 - y0 - total) // 2  # 묶음을 영역 가운데에 세운다
            if head:
                dy = top - head[0].bbox[1]
                for b in head:
                    shift_block(b, dy)
                top = head[-1].bbox[3] + gap
            if body:
                dy = top - body[0].bbox[1]
                for b in body:
                    shift_block(b, dy)
            lay.headline, lay.body = head, body
            lay.boxes += [("headline", b.bbox, rect) for b in head] + [("body", b.bbox, rect) for b in body]
            return True
        code = "HEADLINE_OVERFLOW" if scene.headline and not scene.body else "BODY_OVERFLOW"
        lay.issues.append(_issue(code, "error", lay.timed.index,
                                 f"{scene.layout} 텍스트 영역 {rect}에 안 들어갑니다(최소 폰트·줄 간격·대체 기하까지 시도) - 장면을 나누세요."))
        return False

    # ---- 이미지 슬롯 ----
    def prepare_image(self, scene: V3Scene, lay: SceneLayout) -> None:
        x0, y0, x1, y1 = lay.image_rect
        kb = 1 + float(self.tpl["image"].get("ken_burns", 0))
        w, h = int((x1 - x0) * kb), int((y1 - y0) * kb)
        path = self.doc.image_path(scene)
        img = None
        if path is None:
            lay.image_status = "fallback:empty"
            lay.issues.append(_issue("IMAGE_SLOT_EMPTY", "warning", lay.timed.index, "이미지 경로가 없어 placeholder를 씁니다."))
        else:
            try:
                with Image.open(path) as src:
                    img = ImageOps.exif_transpose(src).convert("RGB")
                lay.image_status = "loaded"
            except FileNotFoundError:
                lay.image_status = "fallback:missing"
                lay.issues.append(_issue("IMAGE_MISSING", "error", lay.timed.index, f"이미지 파일이 없습니다: {scene.image.path}"))
            except (OSError, ValueError):
                lay.image_status = "fallback:unreadable" if path.exists() else "fallback:missing"
                code = "IMAGE_DECODE_FAILED" if path.exists() else "IMAGE_MISSING"
                lay.issues.append(_issue(code, "error", lay.timed.index, f"이미지를 읽을 수 없습니다: {scene.image.path}"))
        if img is None:
            lay.image = self.placeholder((w, h))
        elif (scene.image.fit or self.tpl["image"].get("fit", "cover")) == "contain":
            lay.image = self._contain(img, (w, h), scene.image)
        else:
            lay.image = self._cover(img, (w, h), scene.image)
        if scene.image and scene.image.source:
            lay.credit = self._credit(scene.image.source, x1 - x0)

    @staticmethod
    def _cover(img: Image.Image, size, media) -> Image.Image:
        """슬롯 비율로 자른다: 기준점(position) 주위를 scale만큼 확대."""
        w, h = size
        iw, ih = img.size
        aspect = w / h
        cw, ch = (ih * aspect, ih) if iw / ih > aspect else (iw, iw / aspect)
        cw, ch = cw / media.scale, ch / media.scale
        fx, fy = media.position
        cx = min(max(fx * iw, cw / 2), iw - cw / 2)
        cy = min(max(fy * ih, ch / 2), ih - ch / 2)
        return img.crop((int(cx - cw / 2), int(cy - ch / 2), int(cx + cw / 2), int(cy + ch / 2))).resize((w, h), Image.LANCZOS)

    def _contain(self, img: Image.Image, size, media) -> Image.Image:
        """이미지 전체를 보여준다: 흐리게 한 cover 배경 위에 원본 비율 그대로."""
        w, h = size
        bg = self._cover(img, size, media).filter(ImageFilter.GaussianBlur(28))
        bg = Image.blend(bg, Image.new("RGB", size, self.look.bg_top), 0.45)
        iw, ih = img.size
        s = min(w / iw, h / ih) * media.scale
        fg = img.resize((max(1, int(iw * s)), max(1, int(ih * s))), Image.LANCZOS)
        fx, fy = media.position
        px, py = int((w - fg.width) * fx), int((h - fg.height) * fy)
        bg.paste(fg, (px, py))
        return bg

    def placeholder(self, size) -> Image.Image:
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

    # ---- 검사 ----
    def _check_boxes(self) -> None:
        for name, box, frame in self.title_boxes:
            if not inside(box, frame) or not inside(box, self.safe):
                self.issues.append(_issue("SAFE_AREA_VIOLATION", "error", None, f"{name} {box}가 {frame}/안전영역 밖"))
        for lay in self.layouts:
            for name, box, frame in lay.boxes:
                if not inside(box, self.safe):
                    self.issues.append(_issue("SAFE_AREA_VIOLATION", "error", lay.timed.index, f"{name} {box}가 안전영역 {self.safe} 밖"))
                elif not inside(box, frame):
                    self.issues.append(_issue("FRAME_VIOLATION", "error", lay.timed.index, f"{name} {box}가 프레임 {frame} 밖"))

    @property
    def blocking(self) -> list[dict]:
        return [i for i in self.issues if i["code"] in BLOCKING_LAYOUT_CODES]

    def report(self) -> dict:
        """모든 텍스트/이미지 bbox + 문제 목록 - 품질 게이트 입력."""
        scenes = []
        for lay in self.layouts:
            ts = lay.timed
            scenes.append({
                "index": ts.index, "end_card": ts.scene is None, "layout": ts.scene.layout if ts.scene else "end_card",
                "variant": lay.variant, "start": round(ts.start, 3), "duration": round(ts.duration, 3), "beats": ts.beats,
                "image": lay.image_status,
                "warnings": [i["code"].lower() for i in lay.issues if i["severity"] == "warning"],
                "boxes": [{"name": n, "bbox": list(b), "frame": list(f)} for n, b, f in lay.boxes],
            })
        overflow = [i["message"] for i in self.issues if i["code"] in BLOCKING_LAYOUT_CODES + ("SAFE_AREA_VIOLATION", "FRAME_VIOLATION")]
        title_box = [min(b.bbox[0] for b in self.title), self.title[0].bbox[1], max(b.bbox[2] for b in self.title), self.title[-1].bbox[3]] if self.title else []
        return {"title": {"bbox": title_box, "lines": sum(b.lines for b in self.title)}, "scenes": scenes,
                "total": round(self.timeline[-1].end, 3), "overflow": overflow, "issues": list(self.issues)}
