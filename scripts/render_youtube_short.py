#!/usr/bin/env python3
"""대본 JSON을 "티몽의 지혜" 브랜드 카드뉴스 스타일 YouTube Shorts MP4로 렌더링하는 CLI.

흐름: 대본 JSON -> 화면 분할(표지/본문 카드/마무리) -> Pillow 이미지 합성 -> ffmpeg 인코딩
       -> 1080x1920 무음 MP4.

이 스크립트는 "완성된 대본을 영상으로 렌더링"만 책임진다. TAK BRAIN/TAK MEDIA의
콘텐츠 생성 로직이나 YouTube 업로드(scripts/upload_youtube_short.py)는 전혀
import하거나 수정하지 않는다.

대본 JSON 스키마:
    {
      "title": "좋은 사람이 만만한 사람이 되지 않으려면",
      "subtitle": "사람에게 잘하되 내 중심까지 내주지는 마세요.",
      "cards": ["...", "...", "..."],
      "takeaway": "좋은 사람이 되는 것과 만만한 사람이 되는 것은 다릅니다.",
      "brand": "티몽의 지혜"
    }

사용 예:
    python scripts/render_youtube_short.py \\
        --input data/shorts_scripts/example.json \\
        --output data/shorts/example.mp4
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_engine.shorts_script import (
    ShortsScript,
    ShortsScriptError,
    build_screen_plan,
    total_duration_seconds,
)


def _load_script(input_path: Path) -> ShortsScript:
    try:
        raw_text = input_path.read_text(encoding="utf-8")
    except OSError as error:
        raise ShortsScriptError(f"입력 파일을 읽을 수 없습니다: {input_path} ({error})") from error
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as error:
        raise ShortsScriptError(f"입력 파일이 올바른 JSON이 아닙니다: {input_path} ({error})") from error
    return ShortsScript.from_dict(data)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description='"티몽의 지혜" Shorts 카드뉴스 렌더링 CLI (대본 JSON -> MP4)'
    )
    parser.add_argument("--input", type=Path, required=True, help="대본 JSON 파일 경로")
    parser.add_argument("--output", type=Path, required=True, help="생성할 MP4 파일 경로")
    parser.add_argument(
        "--background",
        type=str,
        default=None,
        help="배경 스타일 강제 지정(생략 시 대본 내용 기반으로 자동 선택)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="실제 렌더링 없이 대본 검증과 화면 구성/예상 길이만 미리 확인합니다.",
    )
    args = parser.parse_args(argv)

    if not args.input.exists():
        print(f"오류: 입력 파일을 찾을 수 없습니다: {args.input}", file=sys.stderr)
        return 1

    try:
        script = _load_script(args.input)
    except ShortsScriptError as error:
        print(f"오류: {error}", file=sys.stderr)
        return 1

    plans = build_screen_plan(script)

    if args.dry_run:
        from content_engine.shorts_renderer import FADE_SECONDS, pick_background_variant

        try:
            variant = pick_background_variant(script, args.background)
        except Exception as error:  # noqa: BLE001 - 배경 이름 오류를 그대로 사용자에게 보여준다
            print(f"오류: {error}", file=sys.stderr)
            return 1

        estimated_total = total_duration_seconds(plans, FADE_SECONDS)
        print("=== TAK Shorts Render (Dry-run) ===")
        print(f"입력 파일: {args.input}")
        print(f"출력 파일(예정): {args.output}")
        print(f"브랜드: {script.brand}")
        print(f"제목: {script.title}")
        print(f"부제: {script.subtitle}")
        print(f"카드 수: {len(script.cards)}")
        print(f"배경 스타일: {variant}")
        print("화면 구성:")
        for index, plan in enumerate(plans, start=1):
            label = plan.kind if plan.card_index is None else f"card {plan.card_index}/{plan.card_total}"
            print(f"  {index}. [{label}] {plan.duration_seconds:.1f}s - {plan.text}")
        print(f"예상 전체 길이: 약 {estimated_total:.1f}초 (해상도 1080x1920, 오디오 없음)")
        print("네트워크/렌더링 호출 없음. 실제 렌더링에는 --dry-run 없이 실행하세요.")
        return 0

    from content_engine.shorts_renderer import ShortsRenderError, render_shorts_video

    print(f"렌더링 중: {args.input.name} -> {args.output} ...")
    try:
        result = render_shorts_video(script, args.output, background_variant=args.background)
    except ShortsRenderError as error:
        print(f"렌더링 오류: {error}", file=sys.stderr)
        return 1
    except Exception as error:  # noqa: BLE001 - 예기치 못한 실패도 명확하게 알린다
        print(f"렌더링 실패: {type(error).__name__}: {error}", file=sys.stderr)
        return 1

    print("성공: Shorts 영상 생성 완료!")
    print(f"파일: {result.output_path}")
    print(f"해상도: {result.width}x{result.height}")
    print(f"길이: {result.duration_seconds:.2f}초")
    print(f"화면 수: {result.screen_count}")
    print(f"배경 스타일: {result.background_variant}")
    print(f"오디오 트랙: {'있음' if result.has_audio else '없음'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
