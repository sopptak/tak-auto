#!/usr/bin/env python3
"""Shorts 2.0(6-41) 장면 설계 JSON -> 실제 MP4 + 미리보기 프레임 + ffprobe 리포트(로컬 QA 전용).

``data/``를 읽거나 쓰지 않는다. 외부 API를 호출하지 않는다 - 로컬 ffmpeg/ffprobe만 실행한다.

사용 예:
    py scripts/render_shorts_v2.py --ffmpeg "C:/Program Files (x86)/clipdown/ffmpeg.exe" \\
        --out artifacts/6-41-shorts-v2 finance human ai
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_engine.shorts_v2_renderer import render_short_v2  # noqa: E402
from content_engine.shorts_qa import probe  # noqa: E402,F401 - 6-53: 공용 모듈로 이동
from content_engine.shorts_v2_scene import SAFE_BOX, ShortSpec  # noqa: E402

SPEC_DIR = ROOT / "content_engine" / "shorts_v2_specs"
# 미리보기 추출 지점: 첫 프레임, 15%, 50%, 80%, 마지막 프레임
PREVIEW_POINTS = (("01", 0.0), ("15", 0.15), ("mid", 0.5), ("80", 0.8), ("last", None))


def extract_previews(ffmpeg: str, video: Path, duration: float, preview_dir: Path, name: str, guides: bool) -> list[Path]:
    """MP4에서 실제로 인코딩된 프레임을 뽑는다(렌더러 내부 이미지가 아니라 결과물 검증)."""
    preview_dir.mkdir(parents=True, exist_ok=True)
    x0, y0, x1, y1 = SAFE_BOX
    paths = []
    for tag, frac in PREVIEW_POINTS:
        t = max(0.0, duration - 0.25) if frac is None else duration * frac
        out = preview_dir / f"{name}_{tag}.png"
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1", str(out)], check=True)
        paths.append(out)
        if guides:  # YouTube UI가 덮는 영역을 빨간 반투명으로 표시한 검증용 사본
            guide = preview_dir / "guides" / f"{name}_{tag}_safe.png"
            guide.parent.mkdir(exist_ok=True)
            vf = (f"drawbox=x=0:y=0:w=iw:h={y0}:color=red@0.25:t=fill,"
                  f"drawbox=x=0:y={y1}:w=iw:h=ih-{y1}:color=red@0.25:t=fill,"
                  f"drawbox=x={x1}:y={y0}:w=iw-{x1}:h={y1 - y0}:color=red@0.25:t=fill,"
                  f"drawbox=x=0:y={y0}:w={x0}:h={y1 - y0}:color=red@0.25:t=fill")
            subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(out), "-vf", vf, str(guide)], check=True)
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("names", nargs="+", help="content_engine/shorts_v2_specs/<name>.json")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default=None, help="기본값: ffmpeg와 같은 폴더의 ffprobe")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--no-audio", action="store_true")
    parser.add_argument("--no-guides", action="store_true")
    args = parser.parse_args(argv)
    ffmpeg_path = Path(args.ffmpeg)
    ffprobe = args.ffprobe or str(ffmpeg_path.with_name(ffmpeg_path.name.replace("ffmpeg", "ffprobe")))

    report = {}
    for name in args.names:
        spec = ShortSpec.load(SPEC_DIR / f"{name}.json")
        video = args.out / f"shorts_v2_{name}.mp4"
        started = time.time()
        render_short_v2(spec, video, ffmpeg_path=args.ffmpeg, audio=not args.no_audio)
        info = probe(ffprobe, video)
        info["render_seconds"] = round(time.time() - started, 1)
        info["previews"] = [str(p.resolve()) for p in extract_previews(args.ffmpeg, video, info["duration"], args.out / "preview", name, not args.no_guides)]
        report[name] = info
        print(json.dumps(info, ensure_ascii=False, indent=2))
    (args.out / "ffprobe_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
