"""Shorts MP4 공용 검사(6-53) - 6-41 ffprobe 요약과 6-51 품질검사를 한 곳에 모았다.

6-41 ``scripts/render_shorts_v2.py``, 6-51 ``scripts/render_production_shorts_preview.py``,
6-52/6-53 V3 파이프라인이 모두 이 모듈을 쓴다(같은 검사를 여러 군데 두지 않는다).
로컬 ffmpeg/ffprobe만 실행한다.
"""

from __future__ import annotations

import json
import math
import subprocess
from array import array
from pathlib import Path

from PIL import Image, ImageStat

BLANK_STDDEV = 6.0  # 프레임 밝기 표준편차가 이보다 낮으면 빈 화면으로 본다


def ffprobe_for(ffmpeg: str) -> str:
    path = Path(ffmpeg)
    return str(path.with_name(path.name.replace("ffmpeg", "ffprobe")))


def probe(ffprobe: str, path: Path) -> dict:
    out = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries",
         "format=duration,size:stream=codec_type,codec_name,width,height,r_frame_rate,duration,sample_rate,channels,nb_frames",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    data = json.loads(out)
    video = next(s for s in data["streams"] if s["codec_type"] == "video")
    audio = next((s for s in data["streams"] if s["codec_type"] == "audio"), None)
    return {
        "file": str(path.resolve()),
        "size_bytes": int(data["format"]["size"]),
        "duration": float(data["format"]["duration"]),
        "width": video["width"], "height": video["height"], "fps": video["r_frame_rate"],
        "video_codec": video["codec_name"], "video_duration": float(video.get("duration", 0)),
        "audio_codec": audio["codec_name"] if audio else None,
        "audio_duration": float(audio.get("duration", 0)) if audio else None,
        "audio_channels": audio.get("channels") if audio else None,
        "nb_frames": int(video["nb_frames"]) if str(video.get("nb_frames", "")).isdigit() else None,
    }



def media_checks(ffmpeg: str, video: Path, info: dict, expected: float, scene_times: list[tuple[int, float]],
                 frames_dir: Path, expect_audio: bool = True) -> tuple[dict, list[int], str]:
    """렌더 결과 MP4 자체 검사(6-51, 6-52 V3 공용): 파일/디코드/길이/해상도/코덱/빈 화면.
    ``scene_times``는 (장면 번호, 그 장면 가운데 시각) 목록 - 실제 MP4에서 프레임을 뽑아 본다."""
    decode = subprocess.run([ffmpeg, "-v", "error", "-i", str(video), "-f", "null", "-"],
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    blank = []
    frames_dir.mkdir(parents=True, exist_ok=True)
    for index, t in scene_times:
        png = frames_dir / f"scene{index:02d}.png"
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-ss", f"{t:.3f}",
                        "-i", str(video), "-frames:v", "1", str(png)], check=True)
        if ImageStat.Stat(Image.open(png).convert("L")).stddev[0] < BLANK_STDDEV:
            blank.append(index)
    audio_ok = info["audio_codec"] == "aac" if expect_audio else info["audio_codec"] is None
    checks = {
        "file_exists_nonempty": video.exists() and info["size_bytes"] > 0,
        "decode_clean": decode.returncode == 0 and not decode.stderr.strip(),
        "duration_matches_spec": abs(info["duration"] - expected) < 0.2 and info["duration"] > 0,
        "resolution_1080x1920": (info["width"], info["height"]) == (1080, 1920),
        "codec_h264_aac": info["video_codec"] == "h264" and audio_ok,
        "no_blank_scene": not blank,
    }
    return checks, blank, decode.stderr.strip()[:500]


def audio_levels(ffmpeg: str, video: Path, *, rate: int = 8000, window: float = 0.1) -> dict | None:
    """MP4 오디오를 모노 PCM으로 디코드해 구간별 RMS(0~1)를 잰다(6-54). 오디오가 없으면 None.
    반환: peak(가장 큰 구간), middle(가운데 절반 구간의 중앙값), tail(마지막 0.3초), windows(구간 수)."""
    proc = subprocess.run([ffmpeg, "-v", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", str(rate), "-f", "s16le", "-"],
                          capture_output=True)
    if proc.returncode != 0 or not proc.stdout:
        return None
    pcm = array("h")
    pcm.frombytes(proc.stdout[: len(proc.stdout) // 2 * 2])
    step = max(1, int(rate * window))
    rms = [math.sqrt(sum(v * v for v in pcm[i:i + step]) / len(pcm[i:i + step])) / 32768 for i in range(0, len(pcm) - step + 1, step)]
    if not rms:
        return None
    n = len(rms)
    middle = sorted(rms[n // 4: max(n // 4 + 1, 3 * n // 4)])
    tail = rms[-max(1, int(0.3 / window)):]
    return {"peak": round(max(rms), 4), "middle": round(middle[len(middle) // 2], 4),
            "tail": round(sum(tail) / len(tail), 4), "windows": n}

