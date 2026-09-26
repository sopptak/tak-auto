#!/usr/bin/env python3
"""Shorts V3(6-52, 6-53): V3 문서 / 기존 ShortsScript / approved Shorts -> MP4 + 품질 게이트 리포트(배치).

LOCAL PREVIEW ONLY. YouTube/Threads/Naver/LLM API를 호출하지 않는다. ``data/``는 읽기만 한다 -
실행 전후 Production Archive와 ShortsScript의 sha256이 같은지 확인하고 다르면 실패한다.

사용 예:
    # 사람이 고친 V3 문서(여러 개 가능)
    py scripts/render_shorts_v3.py --document a.json --document b.json --out artifacts/x --ffmpeg <ffmpeg>
    # 기존 ShortsScript -> adapter -> V3 문서(<out>/<id>.document.json 저장) -> MP4
    py scripts/render_shorts_v3.py --shorts-script data/shorts_scripts/<id>.json --generation-id <gen> --out artifacts/x --ffmpeg <ffmpeg>
    # Production Archive의 approved Shorts 전부(읽기 전용). --validate-only면 렌더 없이 검증만
    py scripts/render_shorts_v3.py --approved --validate-only --out artifacts/x
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_engine.shorts_v3_pipeline import (  # noqa: E402
    approved_items, item_from_document, item_from_shorts_script, render_batch,
)
from scripts.render_production_shorts_preview import data_fingerprint  # noqa: E402

DATA = ROOT / "data"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--document", type=Path, action="append", default=[], help="V3 문서 JSON(반복 가능)")
    parser.add_argument("--shorts-script", type=Path, action="append", default=[], help="기존 ShortsScript JSON(반복 가능)")
    parser.add_argument("--generation-id", action="append", default=[],
                        help="lineage용 generation_id - --shorts-script와 같은 순서·같은 개수로(반복 가능)")
    parser.add_argument("--approved", action="store_true", help="Production Archive의 approved Shorts 전부(읽기 전용)")
    parser.add_argument("--archive", type=Path, default=DATA / "tak_media_archive.json")
    parser.add_argument("--scripts-dir", type=Path, default=DATA / "shorts_scripts")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--validate-only", action="store_true", help="렌더 없이 문서/레이아웃/lineage 검증만")
    parser.add_argument("--force", action="store_true", help="render key가 같아도 다시 렌더")
    args = parser.parse_args(argv)
    if args.generation_id and len(args.generation_id) != len(args.shorts_script):
        parser.error("--generation-id는 --shorts-script와 같은 개수여야 합니다(순서대로 짝지음).")

    items = [item_from_document(p) for p in args.document]
    for k, p in enumerate(args.shorts_script):
        gen = args.generation_id[k] if args.generation_id else None
        item = item_from_shorts_script(p, generation_id=gen or None)
        if item.document is not None:  # 사람이 고쳐서 --document로 다시 렌더할 수 있게 저장
            args.out.mkdir(parents=True, exist_ok=True)
            path = args.out / f"{item.name}.document.json"
            path.write_text(json.dumps(item.document, ensure_ascii=False, indent=2), encoding="utf-8")
            item = item_from_document(path, name=item.name)
        items.append(item)
    if args.approved:
        items += approved_items(args.archive, args.scripts_dir)
    if not items:
        parser.error("--document / --shorts-script / --approved 중 하나는 필요합니다.")

    before = data_fingerprint()
    summary = render_batch(items, args.out, ffmpeg=args.ffmpeg, validate_only=args.validate_only, force=args.force)
    unchanged = before == data_fingerprint()
    for r in summary["results"]:
        print(json.dumps({k: r.get(k) for k in ("name", "content_id", "status", "reasons", "output_path")}, ensure_ascii=False))
    print(json.dumps({"total": summary["total"], "success": summary["success"], "failed": summary["failed"], "counts": summary["counts"],
                      "performance": summary["performance"], "production_data_unchanged": unchanged}, ensure_ascii=False))
    if not unchanged:
        print("ERROR: data/ 가 바뀌었습니다", file=sys.stderr)
        return 2
    return 0 if all(r["status"] in ("success", "skipped", "validated") for r in summary["results"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
