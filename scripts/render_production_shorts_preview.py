#!/usr/bin/env python3
"""6-51: 실제 운영 ShortsScript -> Shorts V2(6-41) MP4 로컬 미리보기 + lineage + 품질검사.

LOCAL PREVIEW ONLY. YouTube/Threads/Naver/LLM API를 호출하지 않는다.
``data/``는 읽기만 한다 - 실행 전후 Production Archive와 ShortsScript의 sha256이
같은지 확인하고, 다르면 실패한다.

카드 문장은 한 글자도 바꾸지 않는다. 6-41 렌더러의 3줄/안전영역 규칙에 맞도록
문장 경계 -> 어절 경계로만 장면을 나눈다(나눈 조각을 이어 붙이면 원문과 같아야 한다).

사용 예:
    py scripts/render_production_shorts_preview.py --ffmpeg "C:/Program Files (x86)/clipdown/ffmpeg.exe" \\
        --out artifacts/6-51-shorts-preview
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from content_engine.shorts_renderer import ShortsRenderError  # noqa: E402
from content_engine.shorts_script import ShortsScript  # noqa: E402
from content_engine.shorts_v2_renderer import LOOKS, ShortsV2Renderer, layout_text, render_short_v2  # noqa: E402
from content_engine.shorts_v2_scene import (  # noqa: E402
    MAX_HOOK_SECONDS, MIN_TOTAL_SECONDS, Scene, ShortSpec, build_timeline, scene_beats, validate_spec,
)
from content_engine.shorts_qa import BLANK_STDDEV, media_checks  # noqa: E402,F401 - 6-53: 공용 모듈로 이동
from scripts.render_shorts_v2 import extract_previews, probe  # noqa: E402

PRODUCTION_ARCHIVE = ROOT / "data" / "tak_media_archive.json"
PRODUCTION_SCRIPTS = ROOT / "data" / "shorts_scripts"
STAGING = ROOT / "artifacts" / "6-48-recovery-staging" / "data"
STYLE, BPM = "ai", 120  # 5개 모두 AI/신기술 주제 - 6-41 STYLE C 그대로

# (순서, content_id, fact-check 상태) - 6-50 결과. FACT_CHECK_FAILED는 없음.
CANDIDATES = (
    ("01", "content-e787c9201b94a948", "NOT_REQUIRED(6-50 applied)"),
    ("02", "content-3ae2d78568210164", "NOT_REQUIRED(6-50 applied)"),
    ("03", "content-ec0c38b9a20c424c", "FACT_CHECK_PASSED"),
    ("04", "content-e3b8d986ea6db98e", "FACT_CHECK_PASSED"),
    ("05", "content-91869ed8be17f3f3", "FACT_CHECK_PARTIAL"),
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def data_fingerprint() -> dict[str, str]:
    files = [PRODUCTION_ARCHIVE, *sorted(PRODUCTION_SCRIPTS.glob("*.json"))]
    return {str(p.relative_to(ROOT)).replace("\\", "/"): sha256(p) for p in files if p.exists()}


def find_record(content_id: str) -> tuple[dict, str]:
    for path in (PRODUCTION_ARCHIVE, STAGING / "tak_media_archive.json"):
        if path.exists():
            for rec in json.loads(path.read_text(encoding="utf-8")):
                if rec.get("content_id") == content_id:
                    return rec, str(path.relative_to(ROOT)).replace("\\", "/")
    raise SystemExit(f"archive 레코드 없음: {content_id}")


def find_script(content_id: str) -> Path:
    for d in (PRODUCTION_SCRIPTS, STAGING / "shorts_scripts"):
        if (d / f"{content_id}.json").exists():
            return d / f"{content_id}.json"
    raise SystemExit(f"ShortsScript 없음: {content_id}")


def fits(text: str, size: int | None = None, max_lines: int = 3) -> bool:
    try:
        layout_text(text, LOOKS[STYLE], 900, size=size, max_lines=max_lines)
        return True
    except ShortsRenderError:
        return False


def _break_word(word: str) -> str:
    """안전영역 폭보다 긴 어절 하나(예: 'conscious"입니다.')는 글자 경계에 줄바꿈("\\n")만 넣는다 -
    공백을 끼워 넣지 않는다. 닫는 따옴표 뒤를 우선."""
    if fits(word):
        return word
    quote = max(word.rfind('"'), word.rfind("”"))
    if 0 < quote < len(word) - 1 and fits(word[:quote + 1]):
        cut = quote + 1
    else:
        cut = max(i for i in range(1, len(word)) if fits(word[:i]))
    return word[:cut] + "\n" + _break_word(word[cut:])


def _balanced(words: list[str], n: int) -> list[str]:
    target = sum(len(w) for w in words) / n
    groups: list[list[str]] = [[]]
    for w in words:
        if groups[-1] and len(groups) < n and sum(len(x) for x in groups[-1]) + len(w) / 2 > target:
            groups.append([])
        groups[-1].append(w)
    return [" ".join(g) for g in groups]


def split_card(card: str) -> list[str]:
    """문장 경계, 그다음 어절 경계에서만 나눈다(장면 길이가 고르게). 원문 글자는 바꾸지 않는다."""
    chunks: list[str] = []
    for sentence in re.split(r"(?<=[.?!])\s+", card.strip()):
        words = [_break_word(w) for w in sentence.split()]
        n = 1
        while not all(fits(c) for c in _balanced(words, n)):
            n += 1
        chunks += _balanced(words, n)
    return chunks


def same_chars(a: str, b: str) -> bool:
    return re.sub(r"\s", "", a) == re.sub(r"\s", "", b)


def source_note(takeaway: str) -> str:
    """takeaway("출처: URL")를 작은 보조 문구로. 추적 query만 떼고, 그래도 넘치면 도메인만 표시."""
    url = takeaway.split(":", 1)[1].strip() if takeaway.startswith("출처:") else takeaway
    parts = urlsplit(url)
    for shown in (f"{parts.netloc}{parts.path}", parts.netloc):
        note = f"출처: {shown.removeprefix('www.')}"
        if fits(note, size=40, max_lines=2):
            return note
    raise ShortsRenderError(f"출처 표시가 안전영역에 안 들어갑니다: {takeaway!r}")


def build_spec(script: ShortsScript, content_id: str) -> tuple[ShortSpec, list[list[str]]]:
    beat = 60.0 / BPM
    split = [split_card(card) for card in script.cards]
    scenes = [Scene(role="HOOK", text=script.title, audio=("impact",))]
    for chunks in split:
        for chunk in chunks:
            scenes.append(Scene(role="INFO", text=chunk, transition="punch", audio=("whoosh",)))
    last = scenes[-1]
    scenes[-1] = Scene(**{**last.__dict__, "note": source_note(script.takeaway)})
    beats = [scene_beats(s, beat) for s in scenes]
    if beats[0] * beat > MAX_HOOK_SECONDS:
        raise ShortsRenderError(f"제목이 HOOK 3초에 안 들어갑니다: {script.title!r}")
    # 글이 적으면 25초 하한에 못 미친다 - 새 문장을 만들지 않고 본문 장면을 박자 단위로 더 오래 보여준다.
    brand_beats = 4
    k = 0
    while (sum(beats) + brand_beats) * beat < MIN_TOTAL_SECONDS:
        beats[1 + k % (len(beats) - 1)] += 1
        k += 1
    scenes = [Scene(**{**s.__dict__, "beats": b}) for s, b in zip(scenes, beats)]
    scenes.append(Scene(role="BRAND", text="", layout="brand", audio=("chime",), beats=brand_beats))
    spec = ShortSpec(id=content_id, style=STYLE, bpm=BPM, idea=f"6-51 preview of {content_id}",
                     scenes=tuple(scenes), brand=script.brand)
    validate_spec(spec)
    ShortsV2Renderer(spec, 30)  # 모든 장면의 3줄/안전영역 검사(넘치면 ShortsRenderError)
    return spec, split


def spec_to_dict(spec: ShortSpec) -> dict:
    return {"id": spec.id, "style": spec.style, "bpm": spec.bpm, "idea": spec.idea, "brand": spec.brand,
            "scenes": [{k: (list(v) if isinstance(v, tuple) else v) for k, v in s.__dict__.items()} for s in spec.scenes]}


def quality(ffmpeg: str, video: Path, info: dict, spec: ShortSpec, script: ShortsScript, split: list[list[str]],
            frames_dir: Path) -> dict:
    timeline = build_timeline(spec)
    expected = timeline[-1].end
    checks, blank, stderr = media_checks(ffmpeg, video, info, expected,
                                         [(ts.index, ts.start + ts.duration / 2) for ts in timeline], frames_dir)
    checks |= {
        "text_verbatim": len(split) == len(script.cards) and all(same_chars("".join(c), card) for c, card in zip(split, script.cards)),
        "layout_and_safe_area_guard": True,  # build_spec의 ShortsV2Renderer 생성이 통과해야 여기까지 온다
    }
    return {"passed": all(checks.values()), "checks": checks, "expected_duration": expected, "blank_scenes": blank,
            "decode_stderr": stderr}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts" / "6-51-shorts-preview")
    parser.add_argument("--only", nargs="*", help="content_id 일부만")
    args = parser.parse_args(argv)
    ffmpeg_path = Path(args.ffmpeg)
    ffprobe = str(ffmpeg_path.with_name(ffmpeg_path.name.replace("ffmpeg", "ffprobe")))

    before = data_fingerprint()
    manifest = {"data_sha256_before": before, "videos": []}
    for order, content_id, fact_check in CANDIDATES:
        if args.only and content_id not in args.only:
            continue
        record, archive_path = find_record(content_id)
        script_path = find_script(content_id)
        raw = json.loads(script_path.read_text(encoding="utf-8"))
        # lineage: 파일 이름만 믿지 않고 ShortsScript 안의 content_id/knowledge_id가 archive 레코드와 같은지 본다
        if (raw.get("content_id"), raw.get("knowledge_id")) != (content_id, record.get("knowledge_id")):
            raise SystemExit(f"lineage 불일치: {script_path} {raw.get('content_id')} {raw.get('knowledge_id')}")
        script = ShortsScript.from_dict(raw)
        spec, split = build_spec(script, content_id)
        video = args.out / f"{order}_{content_id}.mp4"
        render_short_v2(spec, video, ffmpeg_path=args.ffmpeg)
        info = probe(ffprobe, video)
        name = f"{order}_{content_id}"
        info["previews"] = [str(p.relative_to(args.out)) for p in
                            extract_previews(args.ffmpeg, video, info["duration"], args.out / "preview", name, True)]
        (args.out / "specs").mkdir(parents=True, exist_ok=True)
        spec_path = args.out / "specs" / f"{name}.spec.json"
        spec_path.write_text(json.dumps(spec_to_dict(spec), ensure_ascii=False, indent=2), encoding="utf-8")
        entry = {
            "order": order, "file": video.name, "content_id": content_id,
            "generation_id": record.get("generation_id"), "knowledge_id": record.get("knowledge_id"),
            "title": script.title, "platform": record.get("platform"),
            "review_status": record.get("review_status"), "generation_status": record.get("generation_status"),
            "superseded_by": record.get("superseded_by"), "fact_check": fact_check,
            "archive_source": archive_path,
            "shorts_script": str(script_path.relative_to(ROOT)).replace("\\", "/"),
            "shorts_script_sha256": sha256(script_path), "spec_sha256": sha256(spec_path),
            "mp4_sha256": sha256(video), "scenes": len(spec.scenes), "probe": info,
            "quality": quality(args.ffmpeg, video, info, spec, script, split, args.out / "frames" / name),
        }
        manifest["videos"].append(entry)
        print(json.dumps({k: entry[k] for k in ("file", "content_id", "mp4_sha256")} | {"quality": entry["quality"]["passed"]},
                         ensure_ascii=False))
    after = data_fingerprint()
    manifest["data_sha256_after"] = after
    manifest["production_data_unchanged"] = before == after
    (args.out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    if before != after:
        print("ERROR: data/ 가 바뀌었습니다", file=sys.stderr)
        return 2
    return 0 if all(v["quality"]["passed"] for v in manifest["videos"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
