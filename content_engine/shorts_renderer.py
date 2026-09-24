"""ShortsScript(content_engine.shorts_script)를 실제 MP4로 렌더링하는
엔진(6-40, "6-30 EXTERNAL_MACHINE_REQUIRED -> REBUILD_REQUIRED" 판정에 따른
최소 구현).

docs/5-17/5-18이 기술한 렌더러 코드 자체는 git 이력 어디에도 존재한 적이
없다(docs/6-30 4장, CASE C로 확정) - 이 모듈은 그 코드를 "복구"한 것이
아니라 **처음부터 새로 작성**했다. 다만 화면 구성/장면 순서/텍스트
분량-노출시간 계산은 이미 존재하는 ``content_engine.shorts_script``
(``ShortsScript``/``build_screen_plan()``, 무수정)를 그대로 재사용한다 -
이 모듈은 오직 "그 계획을 실제 픽셀/영상으로 그리는" 책임만 진다.

파이프라인:

    ShortsScript -> build_screen_plan()(재사용, 무수정)
                 -> 화면별 PNG 프레임(Pillow)
                 -> ffmpeg concat demuxer(하드 컷, 오디오 없음)
                 -> MP4(H.264, yuv420p, 지정한 fps)

이 모듈은 어떤 운영 데이터(``data/``)도 읽거나 쓰지 않는다 - 호출부가
``ShortsScript``와 출력 경로를 직접 넘긴다. 외부 API를 호출하지 않는다 -
로컬 ffmpeg/ffprobe 실행(subprocess)과 로컬 폰트 파일 읽기만 한다.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from content_engine.shorts_script import ScreenPlan, ShortsScript, build_screen_plan

WIDTH = 1080
HEIGHT = 1920
DEFAULT_FPS = 30

# --- 폰트 --------------------------------------------------------------------
# 5-18 문서가 기록한 기존 스타일(명조체 제목/마무리, 고딕체 본문)을 그대로
# 따른다. Windows 표준 한글 폰트만 쓴다 - 별도 폰트 파일을 저장소에 추가하지
# 않는다(라이선스 확인 없이 폰트 자산을 커밋하지 않기 위함).
_WINDOWS_FONTS = Path("C:/Windows/Fonts")
SERIF_FONT_CANDIDATES = (_WINDOWS_FONTS / "HANBatangB.ttf", _WINDOWS_FONTS / "batang.ttc")
SANS_FONT_CANDIDATES = (_WINDOWS_FONTS / "malgunbd.ttf", _WINDOWS_FONTS / "malgun.ttf")
SANS_REGULAR_FONT_CANDIDATES = (_WINDOWS_FONTS / "malgun.ttf",)


class ShortsRenderError(RuntimeError):
    """렌더링(프레임 생성 또는 ffmpeg 인코딩)이 실패했을 때 발생한다."""


@dataclass(frozen=True)
class RenderStyle:
    """화면별 색상 팔레트. 주제마다 강조색만 다르게 줘서(브랜드 시스템은
    동일하게 유지하면서) 세 영상이 서로 완전히 똑같아 보이지 않게 한다
    (6-40 지시 8장 14번 항목)."""

    background: tuple[int, int, int] = (0xF6, 0xF1, 0xE4)  # 아이보리
    ink: tuple[int, int, int] = (0x2A, 0x24, 0x1C)  # 짙은 세피아 잉크색
    accent: tuple[int, int, int] = (0xB8, 0x8A, 0x2E)  # 기본 금색
    card_fill: tuple[int, int, int] = (0xFF, 0xFC, 0xF6)


STYLE_FINANCE = RenderStyle(accent=(0x2E, 0x5B, 0x8A))  # 신뢰감 있는 남색 계열
STYLE_RELATIONS = RenderStyle(accent=(0xB0, 0x5A, 0x3A))  # 따뜻한 테라코타 계열
STYLE_AI = RenderStyle(accent=(0x35, 0x7A, 0x6E))  # 차분한 청록 계열


@dataclass(frozen=True)
class RenderResult:
    output_path: Path
    width: int
    height: int
    fps: int
    scene_count: int
    planned_duration_seconds: float


def _find_font(candidates: tuple[Path, ...], size: int) -> ImageFont.FreeTypeFont:
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    raise ShortsRenderError(
        f"사용 가능한 한글 폰트를 찾지 못했습니다(후보: {[str(c) for c in candidates]}). "
        "Windows 한글 폰트(맑은 고딕/함초롱바탕)가 설치된 환경에서 실행하세요."
    )


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def _split_long_word(draw: ImageDraw.ImageDraw, word: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """어절 하나만으로도 폭을 넘는 극단적인 경우에만 글자 단위로 쪼갠다(안전망)."""
    pieces: list[str] = []
    current = ""
    for ch in word:
        trial = current + ch
        if _text_width(draw, trial, font) > max_width and current:
            pieces.append(current)
            current = ch
        else:
            current = trial
    if current:
        pieces.append(current)
    return pieces


def _wrap_by_pixel_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """명시적 개행(``\\n``)은 대본 작성자가 의도한 구(句) 경계이므로 그대로
    존중한다. 그 줄이 폭을 넘으면 **어절(공백) 단위로** 다시 감싼다 - 이전
    버전은 글자 단위로 강제 개행해 "생각보다 큰 힘을 발휘하더라\\n고요."처럼
    단어 중간이 잘리는 문제가 있었다(6-40 1차 렌더링 육안 검사에서 발견,
    2차 렌더링에서 수정). 한 어절 자체가 폭을 넘는 극단적인 경우에만
    ``_split_long_word()``로 글자 단위 안전망을 적용한다."""
    lines: list[str] = []
    for raw_line in text.split("\n"):
        if not raw_line:
            lines.append("")
            continue
        current = ""
        for word in raw_line.split(" "):
            trial = f"{current} {word}".strip()
            if _text_width(draw, trial, font) <= max_width:
                current = trial
                continue
            if current:
                lines.append(current)
            if _text_width(draw, word, font) > max_width:
                pieces = _split_long_word(draw, word, font, max_width)
                lines.extend(pieces[:-1])
                current = pieces[-1] if pieces else ""
            else:
                current = word
        if current:
            lines.append(current)
    return lines


def _draw_multiline_centered(
    draw: ImageDraw.ImageDraw, lines: list[str], font: ImageFont.FreeTypeFont,
    center_x: int, center_y: int, fill: tuple[int, int, int], line_spacing: int = 18,
) -> None:
    heights = []
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        heights.append(bbox[3] - bbox[1])
    total_height = sum(heights) + line_spacing * (len(lines) - 1 if lines else 0)
    y = center_y - total_height // 2
    for line, height in zip(lines, heights):
        bbox = draw.textbbox((0, 0), line, font=font)
        width = bbox[2] - bbox[0]
        draw.text((center_x - width // 2, y - bbox[1]), line, font=font, fill=fill)
        y += height + line_spacing


def _draw_brand_badge(draw: ImageDraw.ImageDraw, script: ShortsScript, style: RenderStyle, font: ImageFont.FreeTypeFont) -> None:
    text = f"— {script.brand} —"
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad_x, pad_y = 34, 16
    box_w, box_h = text_w + pad_x * 2, text_h + pad_y * 2
    x0 = (WIDTH - box_w) // 2
    y0 = HEIGHT - 130 - box_h
    draw.rounded_rectangle((x0, y0, x0 + box_w, y0 + box_h), radius=box_h // 2, fill=style.accent)
    draw.text((x0 + pad_x - bbox[0], y0 + pad_y - bbox[1]), text, font=font, fill=(255, 255, 255))


def _render_frame(plan: ScreenPlan, script: ShortsScript, style: RenderStyle) -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), color=style.background)
    draw = ImageDraw.Draw(image)

    border = 28
    draw.rectangle((border, border, WIDTH - border, HEIGHT - border), outline=style.accent, width=6)

    badge_font = _find_font(SANS_REGULAR_FONT_CANDIDATES, 32)
    _draw_brand_badge(draw, script, style, badge_font)

    if plan.kind == "cover":
        title_font = _find_font(SERIF_FONT_CANDIDATES, 96)
        title_lines = _wrap_by_pixel_width(draw, plan.text, title_font, WIDTH - 220)
        _draw_multiline_centered(draw, title_lines, title_font, WIDTH // 2, HEIGHT // 2 - 120, style.ink, line_spacing=20)
        if script.subtitle:
            sub_font = _find_font(SANS_REGULAR_FONT_CANDIDATES, 46)
            sub_lines = _wrap_by_pixel_width(draw, script.subtitle, sub_font, WIDTH - 260)
            _draw_multiline_centered(draw, sub_lines, sub_font, WIDTH // 2, HEIGHT // 2 + 140, style.accent, line_spacing=14)
        rule_y = HEIGHT // 2 + 230
        draw.line((WIDTH // 2 - 90, rule_y, WIDTH // 2 + 90, rule_y), fill=style.accent, width=4)

    elif plan.kind == "card":
        panel_margin = 90
        panel_top, panel_bottom = 420, HEIGHT - 420
        draw.rounded_rectangle(
            (panel_margin, panel_top, WIDTH - panel_margin, panel_bottom),
            radius=36, fill=style.card_fill, outline=style.accent, width=3,
        )
        page_font = _find_font(SANS_FONT_CANDIDATES, 40)
        page_text = f"{plan.card_index:02d} / {plan.card_total:02d}"
        draw.text((panel_margin + 40, panel_top + 34), page_text, font=page_font, fill=style.accent)

        body_font = _find_font(SANS_REGULAR_FONT_CANDIDATES, 58)
        body_lines = _wrap_by_pixel_width(draw, plan.text, body_font, WIDTH - panel_margin * 2 - 100)
        _draw_multiline_centered(draw, body_lines, body_font, WIDTH // 2, (panel_top + panel_bottom) // 2 + 20, style.ink, line_spacing=24)

    else:  # takeaway
        rule_y_top = HEIGHT // 2 - 300
        draw.line((WIDTH // 2 - 140, rule_y_top, WIDTH // 2 + 140, rule_y_top), fill=style.accent, width=4)
        label_font = _find_font(SANS_FONT_CANDIDATES, 38)
        label_bbox = draw.textbbox((0, 0), "TAKEAWAY", font=label_font)
        draw.text((WIDTH // 2 - (label_bbox[2] - label_bbox[0]) // 2, rule_y_top + 24), "TAKEAWAY", font=label_font, fill=style.accent)

        takeaway_font = _find_font(SERIF_FONT_CANDIDATES, 62)
        lines = _wrap_by_pixel_width(draw, plan.text, takeaway_font, WIDTH - 140)
        _draw_multiline_centered(draw, lines, takeaway_font, WIDTH // 2, HEIGHT // 2 + 40, style.ink, line_spacing=22)

        rule_y_bottom = HEIGHT // 2 + 300
        draw.line((WIDTH // 2 - 140, rule_y_bottom, WIDTH // 2 + 140, rule_y_bottom), fill=style.accent, width=4)

    return image


def render_shorts_video(
    script: ShortsScript,
    output_path: Path | str,
    *,
    style: RenderStyle = RenderStyle(),
    ffmpeg_path: str = "ffmpeg",
    fps: int = DEFAULT_FPS,
    work_dir: Path | str | None = None,
) -> RenderResult:
    """``script``를 실제 MP4(``output_path``)로 렌더링한다.

    ``work_dir``를 주지 않으면 임시 디렉터리를 만들어 프레임 PNG를 그 안에
    쓰고 렌더링이 끝나면 정리한다(``output_path`` 파일 하나만 남는다) - 이
    함수는 ``data/`` 아래 어떤 파일도 만들지 않는다."""
    if shutil.which(ffmpeg_path) is None and not Path(ffmpeg_path).exists():
        raise ShortsRenderError(
            f"ffmpeg 실행 파일을 찾을 수 없습니다: {ffmpeg_path!r}. --ffmpeg로 전체 경로를 지정하세요."
        )

    plans = build_screen_plan(script)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    def _do_render(frame_dir: Path) -> RenderResult:
        frame_paths: list[Path] = []
        for index, plan in enumerate(plans):
            frame = _render_frame(plan, script, style)
            frame_path = frame_dir / f"frame_{index:03d}.png"
            frame.save(frame_path)
            frame_paths.append(frame_path)

        concat_path = frame_dir / "concat.txt"
        with concat_path.open("w", encoding="utf-8") as handle:
            for frame_path, plan in zip(frame_paths, plans):
                handle.write(f"file '{frame_path.as_posix()}'\n")
                handle.write(f"duration {plan.duration_seconds:.6f}\n")
            # ffmpeg concat demuxer 관례: 마지막 파일의 duration은 무시되므로
            # 마지막 프레임을 한 번 더 적어야 실제로 그 길이만큼 노출된다.
            handle.write(f"file '{frame_paths[-1].as_posix()}'\n")

        cmd = [
            ffmpeg_path, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_path),
            "-vf", f"fps={fps},format=yuv420p",
            "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", "-an", str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise ShortsRenderError(f"ffmpeg 인코딩 실패(exit={result.returncode}):\n{result.stderr[-2000:]}")

        planned_duration = sum(plan.duration_seconds for plan in plans)
        return RenderResult(
            output_path=output_path, width=WIDTH, height=HEIGHT, fps=fps,
            scene_count=len(plans), planned_duration_seconds=planned_duration,
        )

    if work_dir is not None:
        frame_dir = Path(work_dir)
        frame_dir.mkdir(parents=True, exist_ok=True)
        return _do_render(frame_dir)

    with tempfile.TemporaryDirectory(prefix="tak_shorts_render_") as tmp:
        return _do_render(Path(tmp))
