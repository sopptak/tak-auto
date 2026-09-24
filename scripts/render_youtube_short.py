#!/usr/bin/env python3
"""ShortsScript JSON 파일을 실제 MP4로 렌더링하는 CLI(6-40).

docs/6-30이 CASE C(Git 이력 어디에도 존재한 적 없음, EXTERNAL_MACHINE_REQUIRED)로
판정한 렌더러를 최소 사양으로 새로 구현했다(content_engine/shorts_renderer.py).
이 스크립트는 ``data/`` 아래 어떤 파일도 읽거나 쓰지 않는다 - ``--input``/
``--output``을 사람이 직접 지정해야 한다(운영 Production Archive와 분리된
로컬 QA 렌더링 경로).

사용 예:
    python scripts/render_youtube_short.py \\
        --input artifacts/6-40-content-preview/shorts_scripts/shorts_01_finance.json \\
        --output artifacts/6-40-shorts-preview/shorts_01_finance.mp4 \\
        --ffmpeg "C:/Program Files (x86)/clipdown/ffmpeg.exe" \\
        --accent 2E5B8A
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_engine.shorts_renderer import RenderStyle, render_shorts_video
from content_engine.shorts_script import ShortsScript, ShortsScriptError


def _parse_hex_color(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    if len(value) != 6:
        raise argparse.ArgumentTypeError("--accent는 RRGGBB 형식의 6자리 16진수여야 합니다(예: 2E5B8A).")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ShortsScript JSON을 실제 MP4로 렌더링한다(로컬 QA 전용).")
    parser.add_argument("--input", type=Path, required=True, help="ShortsScript JSON 파일 경로")
    parser.add_argument("--output", type=Path, required=True, help="생성할 MP4 파일 경로")
    parser.add_argument("--ffmpeg", default="ffmpeg", help="ffmpeg 실행 파일 경로(기본값: PATH의 ffmpeg)")
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--accent", type=_parse_hex_color, default=None, help="강조색(RRGGBB), 생략 시 기본 팔레트")
    args = parser.parse_args(argv)

    try:
        data = json.loads(args.input.read_text(encoding="utf-8"))
        script = ShortsScript.from_dict(data)
    except (OSError, json.JSONDecodeError, ShortsScriptError) as error:
        print(f"오류: 대본을 읽을 수 없습니다: {error}", file=sys.stderr)
        return 1

    style = RenderStyle(accent=args.accent) if args.accent else RenderStyle()

    try:
        result = render_shorts_video(script, args.output, style=style, ffmpeg_path=args.ffmpeg, fps=args.fps)
    except Exception as error:  # noqa: BLE001 - CLI 경계에서 사람이 읽을 오류로 변환
        print(f"오류: 렌더링 실패: {error}", file=sys.stderr)
        return 1

    print(f"해상도: {result.width}x{result.height}")
    print(f"화면 수: {result.scene_count}")
    print(f"예상 길이: {result.planned_duration_seconds:.2f}초")
    print(f"저장 완료: {result.output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
