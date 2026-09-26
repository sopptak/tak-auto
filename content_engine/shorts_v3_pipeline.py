"""Shorts V3 생산 파이프라인(6-53) - lineage, render key(캐시), 품질 게이트(오류 코드), 배치 렌더.

    입력(V3 문서 JSON / 기존 ShortsScript / Production Archive의 approved Shorts)
      -> BatchItem(문서 dict + 기준 폴더 + 출처 정보)
      -> V3RenderDocument(검증) -> LayoutEngine(배치 검사) -> [render key가 같으면 캐시 재사용]
      -> render_short_v3(MP4) -> ffprobe/디코드/빈 화면 검사 -> 품질 게이트(PASS/BLOCK) -> 리포트

- render key = sha256(렌더러 버전, 문서 해시, 템플릿 해시, 이미지 파일 해시, fps). 콘텐츠/템플릿/이미지
  중 하나라도 바뀌면 key가 바뀌어 새 렌더가 된다. 같은 key + 같은 MP4 해시 + PASS 리포트면 다시 렌더하지 않는다.
- 배치: 항목 하나의 실패(검증 오류/레이아웃 차단/예외)는 그 항목 결과에만 기록되고 나머지는 계속된다.
- Production Archive는 ``approved_items()``에서 **읽기만** 한다(렌더러는 archive를 모른다).
  출력은 ``out_dir`` 아래에만 쓴다. 외부 API를 호출하지 않는다.
"""

from __future__ import annotations

import hashlib
import json
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from content_engine.shorts_qa import ffprobe_for, media_checks, probe
from content_engine.shorts_v3_adapter import document_from_shorts_script
from content_engine.shorts_v3_document import V3RenderDocument, build_v3_timeline
from content_engine.shorts_v3_layout import BLOCKING_LAYOUT_CODES, LayoutEngine
from content_engine.shorts_v3_renderer import render_short_v3
from content_engine.shorts_v3_template import V3Error, canonical_sha256

# 렌더 결과(픽셀/소리)가 바뀌는 renderer 변경이 있으면 올린다 - render key가 바뀌어 캐시가 무효화된다.
RENDERER_VERSION = "shorts_v3/6-53.3"

MEDIA_CODES = {
    "file_exists_nonempty": "FILE_MISSING", "decode_clean": "DECODE_ERROR", "duration_matches_spec": "DURATION_MISMATCH",
    "resolution_1080x1920": "RESOLUTION_MISMATCH", "codec_h264_aac": "CODEC_MISMATCH", "no_blank_scene": "BLANK_FRAME",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def asset_hashes(doc: V3RenderDocument) -> dict[str, str | None]:
    """문서가 참조하는 이미지 파일 해시(없으면 None) - 이미지만 바꿔도 render key가 바뀐다."""
    out: dict[str, str | None] = {}
    for scene in doc.scenes:
        path = doc.image_path(scene)
        if path is not None:
            out[scene.image.path] = sha256_file(path) if path.is_file() else None
    return out


def render_key(doc: V3RenderDocument) -> str:
    return canonical_sha256({"renderer": RENDERER_VERSION, "document": doc.document_sha256(),
                             "template": doc.template_sha256(), "assets": asset_hashes(doc),
                             "fps": doc.template["canvas"]["fps"]})


def lineage(doc: V3RenderDocument) -> dict:
    return {**doc.lineage, "document_sha256": doc.document_sha256(), "template_id": doc.template.get("id"),
            "template_sha256": doc.template_sha256(), "assets": asset_hashes(doc),
            "renderer_version": RENDERER_VERSION, "render_key": render_key(doc)}


def _issue(code: str, severity: str, scene, message: str) -> dict:
    return {"code": code, "severity": severity, "scene": scene, "message": message}


def structure_issues(doc: V3RenderDocument, layout: dict) -> list[dict]:
    """렌더 전에 알 수 있는 문제: 레이아웃(overflow/안전영역/이미지) + 장면 타이밍 + lineage."""
    issues = list(layout["issues"])
    beat = doc.beat_seconds
    min_scene = float(doc.template["timing"]["min_scene_seconds"])
    for s in layout["scenes"]:
        if s["duration"] < min_scene - 1e-6 or abs(s["duration"] / beat - s["beats"]) > 1e-6:
            issues.append(_issue("SCENE_TIMING_INVALID", "error", s["index"], f"장면 길이 {s['duration']}초가 박자/최소 길이 규칙에 맞지 않습니다."))
    if abs(sum(s["duration"] for s in layout["scenes"]) - layout["total"]) > 1e-3:
        issues.append(_issue("SCENE_TIMING_INVALID", "error", None, "장면 길이 합계가 전체 길이와 다릅니다."))
    if not doc.content_id:
        issues.append(_issue("LINEAGE_MISSING", "error", None, "lineage.content_id가 없습니다."))
    return issues


def media_issues(ffmpeg: str, video: Path, info: dict, doc: V3RenderDocument, layout: dict, frames_dir: Path) -> tuple[list[dict], dict]:
    expect_audio = bool(doc.audio.get("enabled", True))
    timeline = build_v3_timeline(doc)
    checks, blank, stderr = media_checks(ffmpeg, video, info, layout["total"],
                                         [(ts.index, ts.start + ts.duration * 0.6) for ts in timeline],
                                         frames_dir, expect_audio=expect_audio)
    issues = []
    for key, ok in checks.items():
        if not ok:
            code = "AUDIO_MISSING" if key == "codec_h264_aac" and expect_audio and info["audio_codec"] is None else MEDIA_CODES[key]
            issues.append(_issue(code, "error", blank if key == "no_blank_scene" else None, f"{key} 실패 {stderr[:200]}".strip()))
    if expect_audio and info["audio_codec"] and (info["audio_channels"] != 2 or abs((info["audio_duration"] or 0) - info["duration"]) > 0.2):
        issues.append(_issue("AUDIO_MISMATCH", "error", None, f"오디오 {info['audio_channels']}ch {info['audio_duration']}초 / 영상 {info['duration']}초"))
    return issues, checks


def gate(issues: list[dict]) -> dict:
    errors = [i for i in issues if i["severity"] == "error"]
    return {"status": "BLOCK" if errors else "PASS", "errors": errors,
            "warnings": [i for i in issues if i["severity"] != "error"],
            "codes": sorted({i["code"] for i in errors})}


@dataclass
class BatchItem:
    name: str
    document: dict | None
    base_dir: Path = Path(".")
    origin: dict = field(default_factory=dict)  # 어디서 왔는지(문서 파일 / ShortsScript / archive 레코드)
    error: V3Error | None = None  # 문서를 만들기도 전에 실패한 경우(예: ShortsScript 없음)


def item_from_document(path: Path | str, name: str | None = None) -> BatchItem:
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return BatchItem(name or path.stem, None, path.parent, {"document": str(path)}, V3Error("INVALID_DOCUMENT", str(error)))
    return BatchItem(name or str(data.get("id") or path.stem), data, path.parent, {"document": str(path)})


def item_from_shorts_script(path: Path | str, *, generation_id: str | None = None, name: str | None = None,
                            source_label: str | None = None) -> BatchItem:
    path = Path(path)
    label = source_label or str(path).replace("\\", "/")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        doc = document_from_shorts_script(raw, generation_id=generation_id, source_script=label)
    except FileNotFoundError:
        return BatchItem(name or path.stem, None, path.parent, {"shorts_script": label},
                         V3Error("SHORTS_SCRIPT_MISSING", f"ShortsScript 파일이 없습니다: {label}"))
    except (json.JSONDecodeError, ValueError) as error:
        code = error.code if isinstance(error, V3Error) else "INVALID_SHORTS_SCRIPT"
        return BatchItem(name or path.stem, None, path.parent, {"shorts_script": label}, V3Error(code, str(error)))
    doc["lineage"]["source_script_sha256"] = sha256_file(path)
    return BatchItem(name or doc["id"] or path.stem, doc, path.parent, {"shorts_script": label})


def approved_items(archive_path: Path | str, scripts_dir: Path | str) -> list[BatchItem]:
    """Production Archive의 approved + 대체되지 않은 Shorts -> 배치 항목(읽기 전용).
    publish readiness와 같은 기준(6-19 publish_eligibility)을 재사용한다."""
    from content_engine.media_archive import load_archive
    from content_engine.publish_eligibility import check_content_supersede
    from content_engine.shorts_adapter import shorts_script_output_path

    records = load_archive(archive_path)
    items = []
    for record in records:
        if record.platform != "shorts" or record.review_status != "approved":
            continue
        if check_content_supersede(records, record.content_id).blocked:
            continue
        path = shorts_script_output_path(scripts_dir, record.content_id)
        items.append(item_from_shorts_script(path, generation_id=record.generation_id, name=record.content_id))
    return items


def _result(item: BatchItem, status: str, **extra) -> dict:
    doc = item.document or {}
    lin = doc.get("lineage") or {}
    return {"name": item.name, "content_id": lin.get("content_id"), "generation_id": lin.get("generation_id"),
            "status": status, "origin": item.origin, **extra}


def render_item(item: BatchItem, out_dir: Path, *, ffmpeg: str = "ffmpeg", validate_only: bool = False,
                force: bool = False) -> dict:
    """항목 하나: 검증 -> 배치 검사 -> (캐시 확인) -> 렌더 -> 품질 게이트 -> 리포트.
    status: validated / blocked / cached / success / failed."""
    if item.error is not None:
        return _result(item, "blocked", reasons=[item.error.code], errors=[item.error.message])
    doc = V3RenderDocument.from_dict(item.document, base_dir=item.base_dir)
    engine = LayoutEngine(doc)
    layout = engine.report()
    pre = structure_issues(doc, layout)
    lin = lineage(doc)
    pre_gate = gate(pre)
    if pre_gate["status"] == "BLOCK" or validate_only:
        status = "blocked" if pre_gate["status"] == "BLOCK" else "validated"
        return _result(item, status, reasons=pre_gate["codes"], errors=[e["message"] for e in pre_gate["errors"]],
                       warnings=[w["code"] for w in pre_gate["warnings"]], render_key=lin["render_key"], lineage=lin)
    out_dir.mkdir(parents=True, exist_ok=True)
    video, report_path = out_dir / f"{item.name}.mp4", out_dir / f"{item.name}.report.json"
    if not force and video.exists() and report_path.exists():
        old = json.loads(report_path.read_text(encoding="utf-8"))
        if old.get("render_key") == lin["render_key"] and old.get("quality", {}).get("status") == "PASS" \
                and old.get("mp4_sha256") == sha256_file(video):
            return _result(item, "cached", output=str(video), report=str(report_path), render_key=lin["render_key"],
                           lineage=old.get("lineage"), reasons=[])
    result = render_short_v3(doc, video, ffmpeg_path=ffmpeg)
    info = probe(ffprobe_for(ffmpeg), video)
    post, checks = media_issues(ffmpeg, video, info, doc, result.layout, out_dir / "frames" / item.name)
    quality = gate(pre + post)
    lin["mp4_sha256"] = sha256_file(video)
    report = {"file": video.name, "render_key": lin["render_key"], "mp4_sha256": lin["mp4_sha256"], "lineage": lin,
              "probe": info, "media_checks": checks, "layout": result.layout, "quality": quality, "origin": item.origin}
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return _result(item, "success" if quality["status"] == "PASS" else "failed", output=str(video), report=str(report_path),
                   render_key=lin["render_key"], lineage=lin, reasons=quality["codes"],
                   warnings=[w["code"] for w in quality["warnings"]])


def render_batch(items: list[BatchItem], out_dir: Path | str, *, ffmpeg: str = "ffmpeg", validate_only: bool = False,
                 force: bool = False) -> dict:
    """여러 항목을 차례로 처리한다. 한 항목의 실패는 그 결과에만 남고 다음 항목은 계속된다."""
    out_dir = Path(out_dir)
    results = []
    for item in items:
        try:
            results.append(render_item(item, out_dir, ffmpeg=ffmpeg, validate_only=validate_only, force=force))
        except V3Error as error:  # 문서/템플릿 검증 오류, 레이아웃 차단
            results.append(_result(item, "blocked", reasons=[error.code], errors=[error.message]))
        except Exception as error:  # noqa: BLE001 - 배치 격리: 예상 못 한 예외도 이 항목만 실패
            results.append(_result(item, "failed", reasons=["RENDER_EXCEPTION"], errors=[f"{type(error).__name__}: {error}"],
                                   traceback=traceback.format_exc(limit=5)))
    counts: dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    summary = {"renderer_version": RENDERER_VERSION, "validate_only": validate_only, "counts": counts, "results": results}
    if not validate_only:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "batch_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary
