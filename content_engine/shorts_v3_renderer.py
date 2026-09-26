"""Shorts V3 렌더러(6-52, 6-53) - 레이아웃 엔진 결과를 매 프레임 합성해 MP4로 만든다.

    V3RenderDocument -> LayoutEngine(shorts_v3_layout) -> ShortsV3Renderer.frame(t) -> encode_frames -> MP4

이 모듈은 배치를 계산하지 않는다(레이아웃 엔진 몫). 여기서 하는 일:
배경(느린 카메라) + 이미지(Ken Burns/scrim/출처) + kinetic text(6-41 draw_text_block) + 전환
(템플릿 transition: cut/punch/dissolve(fade)/slide, CONTENT+FOOTER 영역만 - 제목은 고정) +
비네트/그레인 + 고정 요소(제목/워터마크/진행 표시) + 엔드카드(브랜드/CTA) + 6-41 합성 음악.

제목·브랜드·좌표·폰트 크기·레이아웃 비율은 전부 템플릿/문서 값이다.
``data/``를 읽거나 쓰지 않는다. 외부 API를 호출하지 않는다(로컬 ffmpeg만).
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

from content_engine.shorts_v2_audio import synthesize_soundtrack
from content_engine.shorts_v2_renderer import (
    LOUDNORM, _blit, _clamp, _font, _gradient, _radial_mask, draw_text_block, ease_in_out, ease_out_cubic,
    encode_frames,
)
from content_engine.shorts_v2_scene import HEIGHT, WIDTH, Scene, ShortSpec
from content_engine.shorts_v3_document import TimedV3Scene, V3RenderDocument
from content_engine.shorts_v3_layout import (  # noqa: F401 - 6-52 호환 재노출
    LayoutEngine, SceneLayout, V3LayoutError, fit_paragraphs, shift_block, text_look,
)

PLATE_SCALE = 1.08


class ShortsV3Renderer:
    def __init__(self, doc: V3RenderDocument, fps: int | None = None) -> None:
        self.doc, self.tpl = doc, doc.template
        self.fps = int(fps or self.tpl["canvas"]["fps"])
        self.engine = LayoutEngine(doc)
        if self.engine.blocking:  # 넘치는 텍스트는 그릴 수 없다 - 이상한 MP4 대신 명확한 오류
            first = self.engine.blocking[0]
            raise V3LayoutError(first["code"], first["message"])
        e = self.engine
        self.look, self.frames, self.safe = e.look, e.frames, e.safe
        self.timeline, self.layouts = e.timeline, e.layouts
        self.title, self.title_look, self.watermark = e.title, e.title_look, e.watermark
        self.total = self.timeline[-1].end
        self.content_total = sum(ts.duration for ts in self.timeline if ts.scene is not None)
        self.scene_count = sum(1 for ts in self.timeline if ts.scene is not None)
        self.region = (0, self.frames["content"][1] - 20, WIDTH, self.frames["footer"][3] + 10)
        self.plate = self._plate()
        self.vignette = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
        self.vignette.putalpha(_radial_mask((WIDTH, HEIGHT), 0.35, 1.0, 150))
        # 그레인은 문서 id로 시드를 고정한다 - 같은 입력이면 같은 MP4(바이트 동일)가 나와야 렌더 결과를 비교/재현할 수 있다
        rng = random.Random(f"{doc.id}-6-53-grain")
        self.grain = []
        for _ in range(4):
            noise = Image.frombytes("L", (WIDTH // 2, HEIGHT // 2), rng.randbytes(WIDTH // 2 * HEIGHT // 2))
            noise = noise.point(lambda v: 128 + (v - 128) // 2).resize((WIDTH, HEIGHT), Image.NEAREST)
            self.grain.append(Image.merge("RGBA", (noise, noise, noise, Image.new("L", (WIDTH, HEIGHT), self.look.grain))))

    def layout_report(self) -> dict:
        return self.engine.report()

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

    def _previous(self, t: float, i: int) -> Image.Image:
        prev = self._background(t)
        self._draw_scene(prev, i - 1, self.timeline[i - 1].duration - 0.001)
        return prev

    def frame(self, t: float) -> Image.Image:
        i = self.scene_at(t)
        ts = self.timeline[i]
        local = t - ts.start
        img = self._background(t)
        self._draw_scene(img, i, local)
        self._transition(img, t, i, local)
        img.paste(self.vignette, (0, 0), self.vignette)
        grain = self.grain[int(t * 12) % len(self.grain)]
        img.paste(grain, (0, 0), grain)
        if ts.scene is not None:
            self._overlay(img, t, i)
        return img

    def _transition(self, img: Image.Image, t: float, i: int, local: float) -> None:
        """장면 진입 전환 - CONTENT+FOOTER 영역에만(제목/진행 표시는 흔들리지 않는다)."""
        if i == 0:
            return
        ts, cfg, region = self.timeline[i], self.tpl["transition"], self.region
        name = self.doc.transition_of(ts.scene) if ts.scene is not None else "punch"
        if name == "dissolve" and local < float(cfg["dissolve_seconds"]):
            mixed = Image.blend(self._previous(t, i).crop(region), img.crop(region), ease_in_out(local / float(cfg["dissolve_seconds"])))
            img.paste(mixed, region[:2])
        elif name == "slide" and local < float(cfg["slide_seconds"]):
            e = ease_out_cubic(local / float(cfg["slide_seconds"]))
            prev, cur = self._previous(t, i).crop(region), img.crop(region)
            dx = int(float(cfg["slide_distance"]) * (1 - e))
            out = prev.copy()  # 새 장면이 오른쪽에서 밀려 들어오며 이전 장면 위로 겹친다
            out.paste(cur, (dx, 0))
            img.paste(Image.blend(prev, out, e), region[:2])
        elif name == "punch" and local < float(cfg["punch_seconds"]):  # 박자 위 짧은 줌 펀치(6-41)
            z = 1 + float(cfg["punch_zoom"]) * (1 - ease_out_cubic(local / float(cfg["punch_seconds"])))
            part = img.crop(region)
            rw, rh = part.size
            cw, ch = rw / z, rh / z
            part = part.crop((int((rw - cw) / 2), int((rh - ch) / 2), int((rw + cw) / 2), int((rh + ch) / 2))).resize((rw, rh), Image.BILINEAR)
            img.paste(part, region[:2])

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
        spec, anim = self.tpl["text"], self.tpl["animation"]
        for b in lay.headline:
            draw_text_block(img, b, text_look(self.look, spec["headline"]), local, exit_p)
        delay = float(anim["body_delay"]) if lay.headline else 0.0
        for k, b in enumerate(lay.body):
            draw_text_block(img, b, text_look(self.look, spec["body"]), local - delay - float(anim["paragraph_delay"]) * k, exit_p)
        for b in lay.subtitle:
            draw_text_block(img, b, text_look(self.look, spec["subtitle"]), local - float(anim["subtitle_delay"]), exit_p, simple=True)
        for b in lay.source:
            draw_text_block(img, b, text_look(self.look, spec["source"]), local - float(anim["source_delay"]), exit_p, simple=True)

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
            top = lay.credit_position.startswith("top")  # 글자를 이미지 위에 올리는 레이아웃은 위쪽에 둔다
            part.alpha_composite(lay.credit, (w - lay.credit.width - 14, 14 if top else h - lay.credit.height - 14))
        radius = int(self.tpl["image"].get("radius", 0))
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=255)
        part.putalpha(mask)
        q = ease_out_cubic(_clamp(local / float(self.tpl["animation"]["image_in"])))
        _blit(img, part, x0, y0 + 24 * (1 - q), q * (1 - exit_p))

    def _overlay(self, img: Image.Image, t: float, i: int) -> None:
        """영상 전체에 고정된 요소: 제목, 워터마크, 진행 표시."""
        for b in self.title:
            draw_text_block(img, b, self.title_look, t + float(self.tpl["timing"]["hook_headstart"]), 0.0)
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
            x0, _, x1, y1 = self.engine.progress_row()
            bar = (x0, y1 - h, x1, y1)
        d = ImageDraw.Draw(img, "RGBA")
        if p.get("bar", True):
            if p.get("mode", "time") == "scene":  # 장면 단위로 한 칸씩
                frac = (i + _clamp((t - self.timeline[i].start) / self.timeline[i].duration)) / self.scene_count
            else:  # 시간 기준(6-41 AI 스타일 진행 바)
                frac = _clamp(t / max(self.content_total, 0.01))
            d.rounded_rectangle(bar, radius=h // 2, fill=(255, 255, 255, 40))
            d.rounded_rectangle((bar[0], bar[1], bar[0] + max(h, int((bar[2] - bar[0]) * frac)), bar[3]), radius=h // 2, fill=self.look.accent + (255,))
        if p.get("counter", True):
            spec = self.tpl["text"]["counter"]
            font = _font(self.look.font, int(spec["size"]), int(spec["weight"]))
            label = f"{i + 1:02d} / {self.scene_count:02d}"
            d.text((bar[2] - font.getlength(label), bar[1] - int(spec["size"]) - 10), label, font=font, fill=(255, 255, 255, 190))

    def _end_card(self, img: Image.Image, local: float) -> None:
        look, brand = self.look, self.doc.brand
        cx, cy = (self.safe[0] + self.safe[2]) // 2, (self.frames["content"][1] + self.frames["content"][3]) // 2
        d = ImageDraw.Draw(img, "RGBA")
        text = brand.get("text", "")
        if text:
            font = _font(look.font, int(brand.get("end_card_size", 104)), 900)
            tw = min(font.getlength(text), self.safe[2] - self.safe[0] - 60)
            w = (tw + 60) * ease_out_cubic(_clamp(local / 0.35))
            d.rounded_rectangle((cx - w / 2, cy - 90, cx + w / 2, cy + 70), radius=24, fill=look.accent + (255,))
            if local > 0.2:
                d.text((cx - font.getlength(text) / 2, cy - 78), text, font=font, fill=(8, 10, 14, int(255 * _clamp((local - 0.2) / 0.2))))
        cta = brand.get("cta", "")
        if cta:
            sub = _font(look.font, int(brand.get("cta_size", 40)), 500)
            d.text((cx - sub.getlength(cta) / 2, cy + 120), cta, font=sub, fill=(255, 255, 255, int(170 * _clamp((local - 0.6) / 0.5))))


def soundtrack_spec(doc: V3RenderDocument, timeline: tuple[TimedV3Scene, ...]) -> ShortSpec:
    """V3 타임라인을 6-41 합성기가 읽는 장면 목록으로 옮긴다(박자 수 그대로 - 음악은 새로 만들지 않는다)."""
    scenes = tuple(
        Scene(role="BRAND", text="", layout="brand", audio=("chime",), beats=ts.beats) if ts.scene is None
        else Scene(role="HOOK" if ts.index == 0 else "INFO", text="", audio=tuple(ts.scene.audio), beats=ts.beats)
        for ts in timeline
    )
    return ShortSpec(id=doc.id or "v3", style=doc.audio["background"], bpm=float(doc.audio["bpm"]), idea="", scenes=scenes)


def audio_filter(audio: dict, total: float) -> str:
    """템플릿/문서 audio -> ffmpeg 필터(loudnorm 뒤 volume/fade). loop/ducking은 예약 필드:
    합성 음악은 항상 영상 길이와 같고(loop 불필요), 내레이션 트랙이 없어 ducking 대상이 없다."""
    chain = LOUDNORM + f",volume={float(audio.get('volume', 1.0))}"
    if float(audio.get("fade_in", 0)) > 0:
        chain += f",afade=t=in:d={float(audio['fade_in'])}"
    fade_out = float(audio.get("fade_out", 0))
    if fade_out > 0:
        chain += f",afade=t=out:st={max(0.0, total - fade_out):.3f}:d={fade_out}"
    return chain


@dataclass(frozen=True)
class RenderResultV3:
    output_path: Path
    duration: float
    frames: int
    scenes: int
    audio: bool
    layout: dict


def render_short_v3(doc: V3RenderDocument, output_path: Path | str, *, ffmpeg_path: str = "ffmpeg",
                    max_seconds: float | None = None) -> RenderResultV3:
    renderer = ShortsV3Renderer(doc)
    total = renderer.total if max_seconds is None else min(renderer.total, max_seconds)
    soundtrack = None
    if doc.audio.get("enabled", True):
        soundtrack = lambda wav: synthesize_soundtrack(soundtrack_spec(doc, renderer.timeline), wav)  # noqa: E731
    frames = encode_frames(renderer.frame, total, Path(output_path), ffmpeg_path=ffmpeg_path, fps=renderer.fps,
                           soundtrack=soundtrack, audio_filter=audio_filter(doc.audio, total))
    return RenderResultV3(Path(output_path), frames / renderer.fps, frames, len(renderer.timeline),
                          soundtrack is not None, renderer.layout_report())
