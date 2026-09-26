#!/usr/bin/env python3
"""Shorts V3(6-52): V3 문서 JSON(또는 기존 ShortsScript) -> MP4 + 미리보기 + 품질 게이트 리포트.

LOCAL PREVIEW ONLY. YouTube/Threads/Naver/LLM API를 호출하지 않는다. ``data/``는 읽기만 한다 -
렌더 전후 Production Archive와 ShortsScript의 sha256이 같은지 확인하고 다르면 실패한다.

사용 예:
    # 사람이 고친 V3 문서로 렌더
    py scripts/render_shorts_v3.py --document my_short.json --out artifacts/6-52-shorts-v3-preview --ffmpeg <ffmpeg>
    # 기존 ShortsScript -> adapter -> V3 문서(<name>.document.json으로 저장, 이후 사람이 고쳐 재렌더) -> MP4
    py scripts/render_shorts_v3.py --shorts-script data/shorts_scripts/<content_id>.json --generation-id <gen> \\
        --out artifacts/6-52-shorts-v3-preview --ffmpeg <ffmpeg>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_engine.shorts_v3_adapter import document_from_shorts_script  # noqa: E402
from content_engine.shorts_v3_document import ShortsV3Document, build_v3_timeline  # noqa: E402
from content_engine.shorts_v3_renderer import render_short_v3  # noqa: E402
from scripts.render_production_shorts_preview import data_fingerprint, media_checks, sha256  # noqa: E402
from scripts.render_shorts_v2 import extract_previews, probe  # noqa: E402


def structure_checks(doc: ShortsV3Document, layout: dict) -> dict:
    """렌더 전에 알 수 있는 검사: overflow/프레임/이미지 영역/장면 길이/lineage."""
    beat = doc.beat_seconds
    min_scene = float(doc.template["timing"]["min_scene_seconds"])
    scenes = layout["scenes"]
    return {
        "no_overflow": not layout["overflow"],  # 제목/헤드라인/본문/자막/출처/이미지 bbox가 제 프레임 + 안전영역 안
        "image_region_ok": all(s["image"] in ("none", "loaded") or s["image"].startswith("fallback:")
                               for s in scenes) and all(b["bbox"][2] > b["bbox"][0] and b["bbox"][3] > b["bbox"][1]
                                                        for s in scenes for b in s["boxes"] if b["name"] == "image"),
        "scene_durations_ok": all(s["duration"] >= min_scene - 1e-6 and abs(s["duration"] / beat - s["beats"]) < 1e-6
                                  for s in scenes) and abs(sum(s["duration"] for s in scenes) - layout["total"]) < 1e-3,
        "lineage_present": bool((doc.lineage or {}).get("content_id")),
    }


def quality_gate(ffmpeg: str, video: Path, info: dict, doc: ShortsV3Document, layout: dict, frames_dir: Path) -> dict:
    timeline = build_v3_timeline(doc)
    expect_audio = bool(doc.audio.get("enabled", True))
    checks, blank, stderr = media_checks(ffmpeg, video, info, layout["total"],
                                         [(ts.index, ts.start + ts.duration * 0.6) for ts in timeline],
                                         frames_dir, expect_audio=expect_audio)
    checks |= structure_checks(doc, layout)
    checks["audio_ok"] = (not expect_audio) or (info["audio_channels"] == 2 and abs((info["audio_duration"] or 0) - info["duration"]) < 0.2)
    return {"passed": all(checks.values()), "checks": checks, "blank_scenes": blank, "decode_stderr": stderr,
            "warnings": [f"scene {s['index']}: {w}" for s in layout["scenes"] for w in s["warnings"]]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--document", type=Path, help="V3 문서 JSON")
    src.add_argument("--shorts-script", type=Path, help="기존 ShortsScript JSON(adapter로 변환)")
    parser.add_argument("--generation-id", default=None, help="--shorts-script lineage용 generation_id")
    parser.add_argument("--name", default=None, help="출력 파일 이름(기본: 문서 id)")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    args = parser.parse_args(argv)
    ffmpeg_path = Path(args.ffmpeg)
    ffprobe = str(ffmpeg_path.with_name(ffmpeg_path.name.replace("ffmpeg", "ffprobe")))
    args.out.mkdir(parents=True, exist_ok=True)

    before = data_fingerprint()
    if args.shorts_script:
        raw = json.loads(args.shorts_script.read_text(encoding="utf-8"))
        rel = args.shorts_script.resolve()
        rel = str(rel.relative_to(ROOT) if rel.is_relative_to(ROOT) else rel).replace("\\", "/")
        document = document_from_shorts_script(raw, generation_id=args.generation_id, source_script=rel)
        document["lineage"]["source_script_sha256"] = sha256(args.shorts_script)
        name = args.name or document["id"]
        doc_path = args.out / f"{name}.document.json"  # 사람이 고쳐서 --document로 다시 렌더할 수 있다
        doc_path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        doc_path = args.document
    doc = ShortsV3Document.load(doc_path)
    name = args.name or doc.id or doc_path.stem
    video = args.out / f"{name}.mp4"
    result = render_short_v3(doc, video, ffmpeg_path=args.ffmpeg)
    info = probe(ffprobe, video)
    info["previews"] = [str(p.relative_to(args.out)) for p in
                        extract_previews(args.ffmpeg, video, info["duration"], args.out / "preview", name, True)]
    report = {
        "file": video.name, "document": str(doc_path), "document_sha256": sha256(doc_path),
        "template": doc.template.get("id"), "template_sha256": hashlib.sha256(
            json.dumps(doc.template, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest(),
        "lineage": doc.lineage, "mp4_sha256": sha256(video), "probe": info, "layout": result.layout,
        "quality": quality_gate(args.ffmpeg, video, info, doc, result.layout, args.out / "frames" / name),
    }
    after = data_fingerprint()
    report["production_data_unchanged"] = before == after
    (args.out / f"{name}.report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"file": video.name, "mp4_sha256": report["mp4_sha256"], "quality": report["quality"]["passed"],
                      "checks": report["quality"]["checks"], "warnings": report["quality"]["warnings"],
                      "production_data_unchanged": before == after}, ensure_ascii=False, indent=2))
    if before != after:
        print("ERROR: data/ 가 바뀌었습니다", file=sys.stderr)
        return 2
    return 0 if report["quality"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
