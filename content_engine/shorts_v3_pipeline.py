"""Shorts V3 자동 생산 파이프라인(6-53, 6-54).

단계(각각 독립 함수 - 한 거대 함수가 모든 일을 하지 않는다):

    resolve_content()        입력(V3 문서 JSON / 기존 ShortsScript / 사람이 만든 fixture / archive approved) -> ContentItem
    build_render_document()  ContentItem -> V3RenderDocument(스키마·템플릿 검증)
    resolve_assets()         문서의 이미지 요청 -> ResolvedAsset(존재/형식/디코드/크기/비율/sha256)
    validate()               레이아웃 엔진 + 구조 검사 -> issues(오류 코드)
    render()                 MP4(6-41 음악 포함)
    inspect_media()          ffprobe/디코드/빈 화면/전환 프레임/프레임 수/오디오 레벨
    quality_gate()           issues -> PASS/BLOCK
    write_manifest()         <name>.manifest.json(lineage, asset, output, 검사 결과, publish contract)
    render_item()            위 단계를 순서대로 + render key 기반 idempotency(SKIP / 손상 시 재렌더)
    render_batch()           여러 항목, 실패 격리, batch_manifest.json + batch_report.md

렌더러는 Production Archive를 모른다 - ``approved_items()``만 archive를 **읽는다**.
출력은 ``out_dir`` 아래에만 쓴다. 네트워크/외부 API를 쓰지 않는다.
"""

from __future__ import annotations

import hashlib
import json
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from content_engine.shorts_qa import audio_levels, ffprobe_for, media_checks, probe
from content_engine.shorts_v3_adapter import document_from_shorts_script
from content_engine.shorts_v3_assets import AssetResolver, ResolvedAsset
from content_engine.shorts_v3_assets import resolve_assets as _resolve_assets
from content_engine.shorts_v3_document import V3RenderDocument, build_v3_timeline
from content_engine.shorts_v3_layout import LayoutEngine
from content_engine.shorts_v3_renderer import RenderResultV3, render_short_v3
from content_engine.shorts_v3_template import V3Error, canonical_sha256

# 렌더 결과(픽셀/소리)가 바뀌는 renderer 변경이 있으면 올린다 - render key가 바뀌어 기존 결과를 다시 쓰지 않는다.
RENDERER_VERSION = "shorts_v3/6-54.3"
MANIFEST_SCHEMA = "shorts_v3_manifest/1"
BATCH_SCHEMA = "shorts_v3_batch/1"

MEDIA_CODES = {
    "file_exists_nonempty": "FILE_MISSING", "decode_clean": "DECODE_ERROR", "duration_matches_spec": "DURATION_MISMATCH",
    "resolution_1080x1920": "RESOLUTION_MISMATCH", "codec_h264_aac": "CODEC_MISMATCH", "no_blank_scene": "BLANK_FRAME",
}
AUDIO_SILENT_RMS = 0.005  # 가장 큰 0.1초 구간 RMS가 이보다 작으면 사실상 무음
FADE_TAIL_RATIO = 0.5  # fade_out이 있으면 마지막 0.3초 RMS가 가운데의 절반보다 작아야 한다


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _issue(code: str, severity: str, scene, message: str) -> dict:
    return {"code": code, "severity": severity, "scene": scene, "message": message}


# ---- 1. 입력 --------------------------------------------------------------------------------

@dataclass
class ContentItem:
    """정규화 전 입력 한 건. 어떤 입력이든 document(V3 문서 dict)로 바뀐다."""
    name: str
    document: dict | None
    base_dir: Path = Path(".")
    origin: dict = field(default_factory=dict)  # 어디서 왔는지(문서 파일 / ShortsScript / archive 레코드)
    error: V3Error | None = None  # 문서를 만들기도 전에 실패한 경우(예: ShortsScript 없음)


BatchItem = ContentItem  # 6-53 이름


def item_from_document(path: Path | str, name: str | None = None) -> ContentItem:
    """B/C. V3 문서 JSON(사람이 만든 fixture 포함)."""
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return ContentItem(name or path.stem, None, path.parent, {"kind": "document", "path": str(path)}, V3Error("INVALID_DOCUMENT", str(error)))
    return ContentItem(name or str(data.get("id") or path.stem), data, path.parent,
                       {"kind": "document", "path": str(path), "sha256": sha256_file(path)})


def item_from_shorts_script(path: Path | str, *, generation_id: str | None = None, name: str | None = None,
                            source_label: str | None = None) -> ContentItem:
    """A. 기존 ShortsScript -> adapter -> V3 문서(원본은 읽기만)."""
    path = Path(path)
    label = source_label or str(path).replace("\\", "/")
    origin = {"kind": "shorts_script", "path": label}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        doc = document_from_shorts_script(raw, generation_id=generation_id, source_script=label)
    except FileNotFoundError:
        return ContentItem(name or path.stem, None, path.parent, origin, V3Error("SHORTS_SCRIPT_MISSING", f"ShortsScript 파일이 없습니다: {label}"))
    except (json.JSONDecodeError, ValueError) as error:
        code = error.code if isinstance(error, V3Error) else "INVALID_SHORTS_SCRIPT"
        return ContentItem(name or path.stem, None, path.parent, origin, V3Error(code, str(error)))
    doc["lineage"]["source_script_sha256"] = sha256_file(path)
    return ContentItem(name or doc["id"] or path.stem, doc, path.parent, {**origin, "sha256": doc["lineage"]["source_script_sha256"]})


def approved_items(archive_path: Path | str, scripts_dir: Path | str) -> list[ContentItem]:
    """Production Archive의 approved + 대체되지 않은 Shorts -> 입력 항목(읽기 전용).
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
        item = item_from_shorts_script(shorts_script_output_path(scripts_dir, record.content_id),
                                       generation_id=record.generation_id, name=record.content_id)
        item.origin["archive"] = str(archive_path)
        items.append(item)
    return items


def resolve_content(source) -> ContentItem:
    """입력 한 건을 ContentItem으로: ContentItem 그대로 / dict(V3 문서) / 경로(.json: ShortsScript면 adapter, 아니면 문서)."""
    if isinstance(source, ContentItem):
        return source
    if isinstance(source, dict):
        return ContentItem(str(source.get("id") or "document"), source, Path("."), {"kind": "inline"})
    path = Path(source)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return item_from_document(path)  # 오류 코드가 담긴 항목이 된다
    if isinstance(data, dict) and "cards" in data and "scenes" not in data:
        return item_from_shorts_script(path)
    return item_from_document(path)


# ---- 2~4. 문서 / asset / 검증 --------------------------------------------------------------------

def build_render_document(item: ContentItem) -> V3RenderDocument:
    if item.error is not None:
        raise item.error
    return V3RenderDocument.from_dict(item.document, base_dir=item.base_dir)


def resolve_assets(doc: V3RenderDocument, resolver: AssetResolver) -> dict[int, ResolvedAsset]:
    return _resolve_assets(doc, resolver)


def render_key(doc: V3RenderDocument, assets: dict[int, ResolvedAsset] | None = None) -> str:
    """hash(content_id, generation_id, 문서, 템플릿, asset 내용, renderer 버전, fps)."""
    assets = assets if assets is not None else _resolve_assets(doc)
    return canonical_sha256({"renderer": RENDERER_VERSION, "content_id": doc.content_id, "generation_id": doc.generation_id,
                             "document": doc.document_sha256(), "template": doc.template_sha256(),
                             "assets": {str(i): (a.sha256 or a.status) for i, a in sorted(assets.items())},
                             "fps": doc.template["canvas"]["fps"]})


def lineage(doc: V3RenderDocument, assets: dict[int, ResolvedAsset] | None = None) -> dict:
    assets = assets if assets is not None else _resolve_assets(doc)
    return {**doc.lineage, "document_sha256": doc.document_sha256(), "template_id": doc.template.get("id"),
            "template_sha256": doc.template_sha256(),
            "asset_sha256": {a.path: a.sha256 or None for a in assets.values()},
            "renderer_version": RENDERER_VERSION, "render_key": render_key(doc, assets)}


def structure_issues(doc: V3RenderDocument, layout: dict) -> list[dict]:
    """렌더 전에 알 수 있는 문제: 레이아웃(overflow/안전영역/겹침/asset) + 장면 타이밍 + lineage."""
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


def validate(doc: V3RenderDocument, assets: dict[int, ResolvedAsset], resolver: AssetResolver) -> tuple[LayoutEngine, dict, list[dict]]:
    engine = LayoutEngine(doc, assets=assets, resolver=resolver)
    layout = engine.report()
    return engine, layout, structure_issues(doc, layout)


def quality_gate(issues: list[dict]) -> dict:
    errors = [i for i in issues if i["severity"] == "error"]
    return {"status": "BLOCK" if errors else "PASS", "errors": errors,
            "warnings": [i for i in issues if i["severity"] != "error"],
            "codes": sorted({i["code"] for i in errors})}


gate = quality_gate  # 6-53 이름


# ---- 5~6. 렌더 / 미디어 검사 ---------------------------------------------------------------------

def render(doc: V3RenderDocument, engine: LayoutEngine, video: Path, ffmpeg: str) -> RenderResultV3:
    return render_short_v3(doc, video, ffmpeg_path=ffmpeg, engine=engine)


def inspect_media(ffmpeg: str, video: Path, info: dict, doc: V3RenderDocument, layout: dict, frames_dir: Path) -> tuple[list[dict], dict, dict | None]:
    """렌더 결과 검사: 규격/디코드/길이 + 장면 가운데·전환 직후 프레임 빈 화면 + 프레임 수 + 오디오 레벨/fade."""
    expect_audio = bool(doc.audio.get("enabled", True))
    timeline = build_v3_timeline(doc)
    tcfg = doc.template["transition"]
    times = [(ts.index, ts.start + ts.duration * 0.6) for ts in timeline]
    for ts in timeline[1:]:  # 전환 구간(0.05초, 전환 중간) - 검은/빈 프레임이 끼지 않았는지
        name = doc.transition_of(ts.scene) if ts.scene is not None else "punch"
        span = {"dissolve": tcfg["dissolve_seconds"], "slide": tcfg["slide_seconds"], "punch": tcfg["punch_seconds"]}.get(name, 0.1)
        times += [(100 + ts.index, ts.start + 0.05), (200 + ts.index, ts.start + float(span) / 2)]
    checks, blank, stderr = media_checks(ffmpeg, video, info, layout["total"], times, frames_dir, expect_audio=expect_audio)
    issues = []
    for key, ok in checks.items():
        if not ok:
            code = "AUDIO_MISSING" if key == "codec_h264_aac" and expect_audio and info["audio_codec"] is None else MEDIA_CODES[key]
            issues.append(_issue(code, "error", blank if key == "no_blank_scene" else None, f"{key} 실패 {stderr[:200]}".strip()))
    fps = doc.template["canvas"]["fps"]
    if info.get("nb_frames") is not None and info["nb_frames"] != round(layout["total"] * fps):  # 한 프레임도 빠지면 안 된다
        issues.append(_issue("FRAME_COUNT_MISMATCH", "error", None, f"프레임 {info['nb_frames']}개 / 기대 {round(layout['total'] * fps)}개"))
    levels = None
    if expect_audio and info["audio_codec"]:
        if info["audio_channels"] != 2 or abs((info["audio_duration"] or 0) - info["duration"]) > 0.2:
            issues.append(_issue("AUDIO_MISMATCH", "error", None, f"오디오 {info['audio_channels']}ch {info['audio_duration']}초 / 영상 {info['duration']}초"))
        levels = audio_levels(ffmpeg, video)
        if levels is None or levels["peak"] < AUDIO_SILENT_RMS:
            issues.append(_issue("AUDIO_SILENT", "error", None, f"오디오가 사실상 무음입니다: {levels}"))
        elif float(doc.audio.get("fade_out", 0)) > 0 and levels["tail"] > levels["middle"] * FADE_TAIL_RATIO:
            issues.append(_issue("AUDIO_FADE_MISSING", "error", None, f"fade_out이 있는데 끝부분이 줄지 않았습니다: {levels}"))
    return issues, checks, levels


# ---- 7. manifest ---------------------------------------------------------------------------------

def visual_review(doc: V3RenderDocument, layout: dict, assets: dict[int, ResolvedAsset], info: dict | None) -> dict:
    """사람이 preview를 검토할 때 볼 요약: 제목, 장면 수, 레이아웃, 이미지 종류, 출처, 길이, 오디오."""
    def image_type(i: int, scene) -> str | None:
        if i in assets and assets[i].ok:
            return assets[i].orientation
        return "placeholder" if "image" in doc.template["layouts"][scene.layout] else None

    return {
        "title": doc.title, "scene_count": len(doc.scenes),
        "layouts": [s.layout for s in doc.scenes],
        "image_types": [image_type(i, s) for i, s in enumerate(doc.scenes)],
        "sources": [s.source.display(doc.template) if s.source else None for s in doc.scenes],
        "duration": info["duration"] if info else layout["total"],
        "audio": bool(info and info.get("audio_codec")),
        "transitions": [doc.transition_of(s) for s in doc.scenes],
    }


def write_manifest(path: Path, manifest: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _result(item: ContentItem, status: str, **extra) -> dict:
    doc = item.document or {}
    lin = doc.get("lineage") or {}
    reasons = extra.pop("reasons", [])
    return {"name": item.name, "content_id": lin.get("content_id"), "generation_id": lin.get("generation_id"),
            "status": status, "error_code": reasons[0] if reasons and status not in ("skipped",) else None,
            "reasons": reasons, "origin": item.origin, **extra}


def _already_rendered(manifest_path: Path, video: Path, key: str) -> tuple[bool, str | None]:
    """같은 render key로 성공한 결과가 있고 MP4가 그대로면 True. 파일이 없거나 바뀌었으면 재렌더 사유."""
    if not manifest_path.exists():
        return False, None
    try:
        old = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False, "MANIFEST_UNREADABLE"
    if old.get("render_key") != key or old.get("quality", {}).get("status") != "PASS":
        return False, None
    if not video.exists():
        return False, "ARTIFACT_MISSING"
    if sha256_file(video) != old.get("output", {}).get("sha256"):
        return False, "ARTIFACT_CHANGED"  # 손상/수정된 파일은 다시 만든다
    return True, None


def render_item(item: ContentItem, out_dir: Path, *, ffmpeg: str = "ffmpeg", validate_only: bool = False,
                force: bool = False, resolver: AssetResolver | None = None) -> dict:
    """한 항목: 문서 -> asset -> 검증 -> (idempotency) -> 렌더 -> 미디어 검사 -> 게이트 -> manifest.
    status: validated / blocked / skipped / success / failed."""
    started = time.perf_counter()
    doc = build_render_document(item)
    resolver = resolver or AssetResolver.for_template(doc.template)
    assets = resolve_assets(doc, resolver)
    engine, layout, pre = validate(doc, assets, resolver)
    lin = lineage(doc, assets)
    key = lin["render_key"]
    common = {"render_key": key, "template": doc.template.get("id"), "layouts": [s.layout for s in doc.scenes],
              "assets": [a.to_dict() for a in assets.values()]}
    pre_gate = quality_gate(pre)
    if pre_gate["status"] == "BLOCK" or validate_only:
        return _result(item, "blocked" if pre_gate["status"] == "BLOCK" else "validated", reasons=pre_gate["codes"],
                       errors=[e["message"] for e in pre_gate["errors"]], warnings=[w["code"] for w in pre_gate["warnings"]],
                       lineage=lin, seconds=round(time.perf_counter() - started, 2), **common)
    video, manifest_path = out_dir / f"{item.name}.mp4", out_dir / f"{item.name}.manifest.json"
    done, rerender_reason = (False, None) if force else _already_rendered(manifest_path, video, key)
    if done:
        old = json.loads(manifest_path.read_text(encoding="utf-8"))
        return _result(item, "skipped", reasons=["ALREADY_RENDERED"], output_path=str(video), manifest_path=str(manifest_path),
                       lineage=old.get("lineage"), duration=old["output"]["duration"], sha256=old["output"]["sha256"],
                       bytes=old["output"]["bytes"],
                       seconds=round(time.perf_counter() - started, 2), **common)
    render_started = time.perf_counter()
    render(doc, engine, video, ffmpeg)
    render_seconds = time.perf_counter() - render_started
    info = probe(ffprobe_for(ffmpeg), video)
    post, checks, levels = inspect_media(ffmpeg, video, info, doc, layout, out_dir / "frames" / item.name)
    verdict = quality_gate(pre + post)
    mp4_sha = sha256_file(video)
    lin["mp4_sha256"] = mp4_sha
    manifest = {
        "schema": MANIFEST_SCHEMA, "name": item.name, "render_key": key, "renderer_version": RENDERER_VERSION,
        "lineage": lin, "origin": item.origin,
        "assets": {str(i): a.to_dict() for i, a in sorted(assets.items())},
        "output": {"path": str(video), "sha256": mp4_sha, "bytes": info["size_bytes"], "duration": info["duration"],
                   "width": info["width"], "height": info["height"], "fps": info["fps"], "frames": info.get("nb_frames"),
                   "video_codec": info["video_codec"], "audio_codec": info["audio_codec"], "audio_channels": info["audio_channels"]},
        "visual_review": visual_review(doc, layout, assets, info),
        "quality": verdict, "media_checks": checks, "audio_levels": levels, "layout": layout,
        "timing": {"render_seconds": round(render_seconds, 2), "total_seconds": round(time.perf_counter() - started, 2)},
        "rerender_reason": rerender_reason,
        # 업로드 CLI(scripts/upload_youtube_short.py)가 요구하는 값들 - 이 파일만으로 업로드 입력을 만들 수 있다.
        # 실제 업로드 가능 여부(Production Archive approved 등)는 업로드 CLI의 기존 가드가 판정한다.
        "publish_contract": {"video": str(video), "artifact_sha256": mp4_sha, "content_id": doc.content_id,
                             "knowledge_id": doc.lineage.get("knowledge_id"), "generation_id": doc.generation_id,
                             "title": doc.title, "duration": info["duration"], "quality_status": verdict["status"],
                             "source_url": doc.lineage.get("source_url")},
    }
    write_manifest(manifest_path, manifest)
    return _result(item, "success" if verdict["status"] == "PASS" else "failed", reasons=verdict["codes"],
                   warnings=[w["code"] for w in verdict["warnings"]], output_path=str(video), manifest_path=str(manifest_path),
                   lineage=lin, duration=info["duration"], sha256=mp4_sha, bytes=info["size_bytes"],
                   render_seconds=round(render_seconds, 2), seconds=round(time.perf_counter() - started, 2),
                   rerender_reason=rerender_reason, **common)


# ---- 8. 배치 ------------------------------------------------------------------------------------

def render_batch(sources: list, out_dir: Path | str, *, ffmpeg: str = "ffmpeg", validate_only: bool = False,
                 force: bool = False) -> dict:
    """여러 입력을 차례로 처리한다. 한 항목의 실패는 그 결과에만 남고 다음 항목은 계속된다.
    같은 배치 안에서는 asset resolver(해시/디코드 캐시)를 공유한다(asset 정책은 기본 템플릿 기준)."""
    out_dir = Path(out_dir)
    started = time.perf_counter()
    resolver: AssetResolver | None = None
    results = []
    for source in sources:
        item = resolve_content(source)
        try:
            doc = build_render_document(item)
            resolver = resolver or AssetResolver.for_template(doc.template)
            results.append(render_item(item, out_dir, ffmpeg=ffmpeg, validate_only=validate_only, force=force, resolver=resolver))
        except V3Error as error:  # 입력/문서/템플릿 검증 오류, 레이아웃 차단
            results.append(_result(item, "blocked", reasons=[error.code], errors=[error.message]))
        except Exception as error:  # noqa: BLE001 - 배치 격리: 예상 못 한 예외도 이 항목만 실패
            results.append(_result(item, "failed", reasons=["RENDER_EXCEPTION"], errors=[f"{type(error).__name__}: {error}"],
                                   traceback=traceback.format_exc(limit=5)))
    counts: dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    rendered = [r for r in results if r.get("render_seconds") is not None]
    summary = {
        "schema": BATCH_SCHEMA, "renderer_version": RENDERER_VERSION, "validate_only": validate_only,
        "total": len(results), "success": counts.get("success", 0) + counts.get("skipped", 0) + counts.get("validated", 0),
        "failed": counts.get("failed", 0) + counts.get("blocked", 0), "counts": counts,
        "performance": {"total_seconds": round(time.perf_counter() - started, 2),
                        "rendered": len(rendered),
                        "avg_render_seconds": round(sum(r["render_seconds"] for r in rendered) / len(rendered), 2) if rendered else None,
                        "output_bytes": sum(r.get("bytes") or 0 for r in results),
                        "asset_hash_computations": resolver.hash_computations if resolver else 0,
                        "asset_decodes": resolver.decodes if resolver else 0},
        "results": results,
    }
    if not validate_only:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "batch_manifest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        (out_dir / "batch_report.md").write_text(batch_report_markdown(summary), encoding="utf-8")
    return summary


def batch_report_markdown(summary: dict) -> str:
    """사람이 읽는 배치 보고서(batch_manifest.json과 같은 내용의 요약)."""
    p = summary["performance"]
    lines = [
        "# Shorts V3 batch report", "",
        f"- renderer: `{summary['renderer_version']}`",
        f"- total {summary['total']} / success {summary['success']} / failed {summary['failed']} — {summary['counts']}",
        f"- time {p['total_seconds']}s, rendered {p['rendered']}, avg render {p['avg_render_seconds']}s, output {p['output_bytes']:,} bytes", "",
        "| name | content_id | generation_id | template | layouts | status | output | duration | sha256 | error |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in summary["results"]:
        layouts = ",".join(sorted(set(r.get("layouts") or []))) or "-"
        out = Path(r["output_path"]).name if r.get("output_path") else "-"
        sha = (r.get("sha256") or "")[:16] or "-"
        err = ", ".join(r.get("reasons") or []) or "-"
        lines.append(f"| {r['name']} | {r.get('content_id') or '-'} | {r.get('generation_id') or '-'} | {r.get('template') or '-'} | "
                     f"{layouts} | {r['status']} | {out} | {r.get('duration') or '-'} | {sha} | {err} |")
    return "\n".join(lines) + "\n"
