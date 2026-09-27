"""Shorts Content Studio(6-55) - 사람이 고치는 Draft 저장소 + 미리보기.

    Production Content(ShortsScript + archive 레코드)  -- 읽기만 한다
        -> open_draft(): adapter로 V3 문서를 만들어 Draft로 복제(data/shorts_drafts/<draft_id>/)
        -> apply_form() / save(): 사람이 고친 값 -> 검증 -> 버전 스냅샷(v0001.json, v0002.json, ...)
        -> check(): 렌더 없는 검사(6-54 check_document 재사용)
        -> preview(): 6-54 render_item(레이아웃 -> 렌더 -> 품질 게이트 -> manifest) -> MP4

Draft 문서는 V3 Render Document(shorts_v3_document/1) 그대로다 - 편집기용 별도 스키마를 만들지 않는다.
이 모듈이 쓰는 곳은 DraftStore.root와 preview out_dir 두 곳뿐이다. Production Archive, ShortsScript,
review_status/approved/superseded는 읽기만 하고, 쓰는 함수를 import하지도 않는다.
네트워크/외부 API/LLM을 쓰지 않는다. 문장을 요약하거나 바꾸지 않는다(사람이 입력한 값 그대로 저장).
"""

from __future__ import annotations

import copy
import json
import re
import traceback
from datetime import datetime, timezone
from pathlib import Path

from content_engine.shorts_v3_adapter import document_from_shorts_script
from content_engine.shorts_v3_assets import AssetResolver
from content_engine.shorts_v3_contract import check_document
from content_engine.shorts_v3_pipeline import ContentItem, render_item, sha256_file
from content_engine.shorts_v3_template import V3Error, load_template

DRAFT_SCHEMA = "shorts_draft/1"
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,120}$")  # content_id - 경로 조작(../) 차단
# draft_id는 항상 "draft-"로 시작한다 - 저장소 root를 잘못 지정해도(예: data/) draft-* 폴더 밖은 가리킬 수 없다.
_DRAFT_ID = re.compile(r"^draft-[A-Za-z0-9][A-Za-z0-9_-]{0,120}$")
MAX_FIELD_CHARS = 4000  # 저장 자체를 막는 상한(렌더 가능 여부는 품질 게이트가 따로 판정)
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")

# 화면에 보여줄 설명(traceback 대신). 코드는 6-53/6-54 엔진 코드를 그대로 쓴다.
ERROR_TEXT = {
    "TITLE_EMPTY": "제목이 비어 있습니다.",
    "FIELD_TOO_LONG": f"한 칸에 {MAX_FIELD_CHARS}자를 넘게 저장할 수 없습니다.",
    "TITLE_OVERFLOW": "제목이 제목 영역(최대 3줄)에 들어가지 않습니다. 제목을 줄여 주세요.",
    "HEADLINE_OVERFLOW": "헤드라인이 2줄을 넘습니다.",
    "BODY_OVERFLOW": "본문이 화면에 들어가지 않습니다. 본문을 줄이거나 장면을 나누거나 text_focus 레이아웃을 써 보세요.",
    "SUBTITLE_OVERFLOW": "자막이 한 줄을 넘습니다.",
    "SOURCE_OVERFLOW": "출처가 한 줄에 들어가지 않습니다.",
    "SOURCE_TRUNCATED": "출처가 길어 화면에서 말줄임(…) 처리됩니다.",
    "ASSET_MISSING": "이미지 파일이 없습니다(IMAGE_MISSING). 경로를 확인해 주세요.",
    "ASSET_UNSUPPORTED_FORMAT": "지원하지 않는 이미지 형식입니다(PNG/JPEG/WEBP만).",
    "ASSET_DECODE_FAILED": "이미지 파일이 손상돼 읽을 수 없습니다.",
    "ASSET_TOO_SMALL": "이미지가 너무 작습니다(최소 320x320).",
    "ASSET_REQUIRED": "이 레이아웃은 이미지가 필요합니다.",
    "IMAGE_SLOT_EMPTY": "이미지 칸이 비어 있어 placeholder로 그립니다.",
    "INVALID_DURATION": "장면 길이가 잘못됐습니다(0보다 크고, 글을 읽을 수 있는 길이여야 합니다).",
    "INVALID_LAYOUT": "템플릿에 없는 레이아웃입니다.",
    "INVALID_TEMPLATE": "템플릿/설정 값이 잘못됐습니다(예: 음량, 진행 표시 위치).",
    "INVALID_IMAGE_SPEC": "이미지 fit/position/scale 값이 잘못됐습니다.",
    "INVALID_TRANSITION": "지원하지 않는 전환입니다.",
    "INVALID_DOCUMENT": "문서 형식이 잘못됐습니다.",
    "EMPTY_SCENE": "장면에 이미지/헤드라인/본문 중 하나는 있어야 합니다.",
    "SAFE_AREA_VIOLATION": "글자나 이미지가 안전영역 밖으로 나갑니다.",
    "FRAME_VIOLATION": "요소가 프레임 밖으로 나갑니다.",
    "PROGRESS_OVERLAP": "진행 표시가 다른 요소와 겹칩니다.",
    "SCENE_TIMING_INVALID": "장면 타이밍이 맞지 않습니다.",
    "LINEAGE_MISSING": "content_id(lineage)가 없습니다.",
    "RENDER_FAILED": "렌더 중 오류가 났습니다(ffmpeg 경로/폰트를 확인해 주세요).",
    "QUALITY_GATE_FAILED": "영상은 만들어졌지만 품질 게이트를 통과하지 못했습니다.",
    "DRAFT_NOT_FOUND": "Draft를 찾을 수 없습니다.",
    "DRAFT_CONFLICT": "다른 곳에서 먼저 저장했습니다. 새로고침 후 다시 고쳐 주세요.",
    "SOURCE_NOT_FOUND": "원본 콘텐츠(ShortsScript)를 찾을 수 없습니다.",
    "BASE_CHANGED": "Draft를 만든 뒤 원본 ShortsScript가 바뀌었습니다. 원본으로 초기화하거나 차이를 확인해 주세요.",
}


def describe(code: str) -> str:
    return ERROR_TEXT.get(code, code)


class DraftError(Exception):
    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or describe(code))
        self.code = code
        self.message = message or describe(code)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


# ---- 원본 콘텐츠(읽기 전용) ------------------------------------------------------------------

def list_sources(sources: list[tuple[Path, Path]], fact_checks: dict[str, str] | None = None) -> list[dict]:
    """(archive 경로, ShortsScript 폴더) 목록 -> ShortsScript가 있는 Shorts 레코드. 앞 source가 우선(중복 content_id 제외)."""
    from content_engine.media_archive import load_archive

    fact_checks = fact_checks or {}
    seen, entries = set(), []
    for archive_path, scripts_dir in sources:
        if not Path(archive_path).exists():
            continue
        for record in load_archive(archive_path):
            script = Path(scripts_dir) / f"{record.content_id}.json"
            if record.platform != "shorts" or record.content_id in seen or not script.exists():
                continue
            seen.add(record.content_id)
            raw = json.loads(script.read_text(encoding="utf-8"))
            entries.append({
                "content_id": record.content_id, "title": raw.get("title", ""), "generation_id": record.generation_id,
                "knowledge_id": record.knowledge_id, "platform": record.platform, "review_status": record.review_status,
                "superseded_by": record.superseded_by, "fact_check": fact_checks.get(record.content_id),
                "script_path": str(script), "archive_path": str(archive_path),
            })
    return entries


def load_fact_checks(manifest_path: Path | None) -> dict[str, str]:
    """6-51 preview manifest(videos[].fact_check)에 기록된 fact-check 상태. 없으면 빈 dict."""
    try:
        data = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        return {v["content_id"]: v["fact_check"] for v in data.get("videos", []) if v.get("fact_check")}
    except (TypeError, OSError, ValueError, KeyError):
        return {}


def document_from_source(entry: dict) -> tuple[dict, str]:
    """원본 ShortsScript -> V3 문서(adapter). (문서, 원본 sha256)."""
    path = Path(entry["script_path"])
    if not path.exists():
        raise DraftError("SOURCE_NOT_FOUND", f"ShortsScript 없음: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    doc = document_from_shorts_script(raw, generation_id=entry.get("generation_id"),
                                      source_script=str(path).replace("\\", "/"))
    return doc, sha256_file(path)


# ---- 검증 -----------------------------------------------------------------------------------

def _texts(document: dict):
    yield "title", document.get("title")
    yield "brand", document.get("brand")
    yield "cta", document.get("cta")
    for i, s in enumerate(document.get("scenes") or []):
        if isinstance(s, dict):
            src = s.get("source")
            for key, value in (("headline", s.get("headline")), ("body", s.get("body")), ("subtitle", s.get("subtitle")),
                               ("source", src.get("value") if isinstance(src, dict) else src),
                               ("image", (s.get("image") or {}).get("path") if isinstance(s.get("image"), dict) else s.get("image"))):
                yield f"scene {i + 1} {key}", value


def check(document: dict, base_dir: Path | str) -> dict:
    """저장/미리보기 전 검사. hard=True면 저장할 수 없는 값(빈 제목, 잘못된 길이/레이아웃 등 문서 오류),
    hard=False인 codes는 저장은 되지만 품질 게이트가 렌더를 막는 문제(overflow, 이미지 없음 등)."""
    if not str(document.get("title", "")).strip():
        return {"ok": False, "hard": True, "codes": ["TITLE_EMPTY"], "errors": [describe("TITLE_EMPTY")], "warnings": [], "scenes": [], "total": None}
    for name, value in _texts(document):
        if isinstance(value, str) and len(value) > MAX_FIELD_CHARS:
            return {"ok": False, "hard": True, "codes": ["FIELD_TOO_LONG"], "errors": [f"{name}: {len(value)}자"],
                    "warnings": [], "scenes": [], "total": None}
    report = check_document(document, base_dir)
    report["hard"] = report["total"] is None  # 문서 자체를 읽을 수 없음(V3Error)
    return report


# ---- 편집 폼 -> 문서 ---------------------------------------------------------------------------

def _set(target: dict, key: str, value) -> None:
    if value in (None, ""):
        target.pop(key, None)
    else:
        target[key] = value


def _number(text: str):
    """숫자로 읽히면 숫자, 아니면 입력 그대로(검증이 INVALID_* 코드로 알려준다 - 조용히 버리지 않는다)."""
    try:
        return float(text) if text.strip() else None
    except ValueError:
        return text


def _position(text: str):
    text = text.strip()
    if "," in text:
        x, _, y = text.partition(",")
        return {"x": _number(x), "y": _number(y)}
    return text or None


def apply_form(document: dict, form: dict[str, list[str]] | dict[str, str]) -> dict:
    """편집 화면 값 -> 새 문서(원본 dict는 바꾸지 않는다). 폼에 없는 키는 그대로 둔다. 빈 값 = 키 제거(템플릿 기본값/자동)."""
    def get(key: str):
        value = form.get(key)
        if isinstance(value, list):
            value = value[0] if value else ""
        return None if value is None else str(value).replace("\r\n", "\n")

    doc = copy.deepcopy(document)
    if (v := get("title")) is not None:
        doc["title"] = v.strip()
    for key in ("brand", "cta"):
        if (v := get(key)) is not None:
            _set(doc, key, v.strip())
    for group, fields in (("progress", ("enabled", "position")), ("audio", ("enabled", "volume", "background"))):
        section = dict(doc.get(group) or {}) if not isinstance(doc.get(group), bool) else {"enabled": doc[group]}
        for field in fields:
            v = get(f"{group}_{field}")
            if v is None:
                continue
            if field == "enabled":
                v = {"on": True, "off": False}.get(v, None)
            elif field == "volume":
                v = _number(v)
            _set(section, field, v)
        _set(doc, group, section or None)
    scenes = doc.get("scenes") or []
    for i, scene in enumerate(scenes):
        p = f"s{i}_"
        for key in ("layout", "headline", "body", "subtitle", "transition"):
            if (v := get(p + key)) is not None:
                _set(scene, key, v.strip())
        if (v := get(p + "duration")) is not None:
            _set(scene, "duration", _number(v))
        if (v := get(p + "source_value")) is not None:
            label = (get(p + "source_label") or "").strip()
            _set(scene, "source", ({"label": label, "value": v.strip()} if label else v.strip()) if v.strip() else None)
        if (path := get(p + "image_path")) is not None:
            if not path.strip():
                scene.pop("image", None)
                scene.pop("media", None)
            else:
                image = scene.get("image") if isinstance(scene.get("image"), dict) else {}
                image = {**image, "path": path.strip()}
                if (fit := get(p + "image_fit")) is not None:
                    _set(image, "fit", fit.strip())
                if (pos := get(p + "image_position")) is not None:
                    _set(image, "position", _position(pos))
                scene["image"] = image
    # 장면 복제/삭제(본문이 넘치면 장면을 복제해 두 장면에 나눠 쓴다). 새 빈 장면은 EMPTY_SCENE이라 만들지 않는다.
    op, _, index = (get("scene_op") or "").partition(":")
    if op in ("duplicate", "delete") and index.isdigit() and int(index) < len(scenes):
        i = int(index)
        if op == "duplicate":
            scenes.insert(i + 1, copy.deepcopy(scenes[i]))
        elif len(scenes) > 1:
            del scenes[i]
    return doc


def base_drift(draft: dict, entry: dict | None) -> str | None:
    """Draft를 만든 뒤 원본 ShortsScript가 바뀌었으면 사유 문자열(승인 연결 전 사람이 알아야 한다). 원본은 읽기만."""
    if entry is None or not Path(entry["script_path"]).exists():
        return "SOURCE_NOT_FOUND"
    return None if sha256_file(Path(entry["script_path"])) == draft["base_content_sha256"] else "BASE_CHANGED"


# ---- Draft 저장소 ------------------------------------------------------------------------------

class DraftStore:
    """data/shorts_drafts/<draft_id>/current.json + versions/vNNNN.json(바뀌지 않는 스냅샷) + previews.json."""

    def __init__(self, root: Path | str, base_dir: Path | str) -> None:
        self.root = Path(root)
        self.base_dir = Path(base_dir)  # 문서 image.path 상대 경로 기준(저장소 루트)

    def _dir(self, draft_id: str) -> Path:
        if not isinstance(draft_id, str) or not _DRAFT_ID.match(draft_id):
            raise DraftError("DRAFT_NOT_FOUND", f"잘못된 draft_id: {draft_id!r}")
        return self.root / draft_id

    def exists(self, draft_id: str) -> bool:
        return (self._dir(draft_id) / "current.json").exists()

    def load(self, draft_id: str) -> dict:
        path = self._dir(draft_id) / "current.json"
        if not path.exists():
            raise DraftError("DRAFT_NOT_FOUND", f"Draft 없음: {draft_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def list(self) -> list[dict]:
        if not self.root.exists():
            return []
        return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(self.root.glob("*/current.json"))]

    def _commit(self, draft: dict) -> dict:
        d = self._dir(draft["draft_id"])
        snapshot = d / "versions" / f"v{draft['draft_version']:04d}.json"
        if snapshot.exists():  # 스냅샷은 덮어쓰지 않는다
            raise DraftError("DRAFT_CONFLICT", f"이미 있는 버전: v{draft['draft_version']}")
        _write_json(snapshot, draft)
        _write_json(d / "current.json", draft)
        return draft

    def open_draft(self, entry: dict) -> dict:
        """원본 콘텐츠 -> Draft(이미 있으면 그대로 연다 - 사람이 고친 내용을 덮어쓰지 않는다)."""
        if not _ID.match(entry.get("content_id") or ""):
            raise DraftError("SOURCE_NOT_FOUND", f"잘못된 content_id: {entry.get('content_id')!r}")
        draft_id = f"draft-{entry['content_id']}"
        if self.exists(draft_id):
            return self.load(draft_id)
        document, base_sha = document_from_source(entry)
        now = _now()
        return self._commit({
            "schema": DRAFT_SCHEMA, "draft_id": draft_id, "draft_version": 1, "status": "draft",
            "content_id": entry["content_id"], "generation_id": entry.get("generation_id"),
            "base_content_sha256": base_sha,
            "base": {"kind": "shorts_script", "script_path": entry["script_path"].replace("\\", "/"),
                     "archive_path": entry.get("archive_path", "").replace("\\", "/"),
                     "review_status": entry.get("review_status"), "knowledge_id": entry.get("knowledge_id")},
            "created_at": now, "updated_at": now, "note": "원본에서 복제", "document": document,
        })

    def save(self, draft_id: str, document: dict, *, expected_version: int | None = None, note: str = "") -> tuple[dict, dict, bool]:
        """검증 -> 새 버전 저장. (draft, check 결과, 저장했는지). 내용이 같으면 버전을 올리지 않는다.
        저장할 수 없는 값이면 DraftError(code)."""
        draft = self.load(draft_id)
        if expected_version is not None and expected_version != draft["draft_version"]:
            raise DraftError("DRAFT_CONFLICT", f"편집 시작 v{expected_version}, 현재 v{draft['draft_version']}")
        report = check(document, self.base_dir)
        if report["hard"]:
            raise DraftError(report["codes"][0], "; ".join(report["errors"]) or describe(report["codes"][0]))
        if document == draft["document"]:
            return draft, report, False
        new = {**draft, "document": copy.deepcopy(document), "draft_version": draft["draft_version"] + 1,
               "updated_at": _now(), "note": note or "편집"}
        return self._commit(new), report, True

    def versions(self, draft_id: str) -> list[dict]:
        return [{k: v.get(k) for k in ("draft_version", "updated_at", "note")} | {"title": v["document"].get("title")}
                for v in (json.loads(p.read_text(encoding="utf-8")) for p in sorted((self._dir(draft_id) / "versions").glob("v*.json")))]

    def load_version(self, draft_id: str, version: int) -> dict:
        path = self._dir(draft_id) / "versions" / f"v{int(version):04d}.json"
        if not path.exists():
            raise DraftError("DRAFT_NOT_FOUND", f"{draft_id} v{version} 없음")
        return json.loads(path.read_text(encoding="utf-8"))

    def revert(self, draft_id: str, version: int) -> dict:
        """이전 버전 내용으로 되돌린다 - 기록을 지우지 않고 새 버전으로 쌓는다."""
        old = self.load_version(draft_id, version)
        draft, _, _ = self.save(draft_id, old["document"], note=f"v{version}로 되돌림")
        return draft

    def reset_to_base(self, draft_id: str, entry: dict) -> dict:
        """원본 Production Content로 되돌린다(새 버전). 원본 파일은 읽기만 한다."""
        draft = self.load(draft_id)
        document, base_sha = document_from_source(entry)
        if document == draft["document"]:
            return draft
        new = {**draft, "document": document, "draft_version": draft["draft_version"] + 1, "updated_at": _now(),
               "base_content_sha256": base_sha, "note": "원본으로 초기화"}
        return self._commit(new)

    def previews(self, draft_id: str) -> list[dict]:
        path = self._dir(draft_id) / "previews.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []

    def _record_preview(self, draft_id: str, result: dict) -> None:
        path = self._dir(draft_id) / "previews.json"
        path.write_text(json.dumps([*self.previews(draft_id), result], ensure_ascii=False, indent=2), encoding="utf-8")


# ---- 미리보기 ----------------------------------------------------------------------------------

def preview(store: DraftStore, draft_id: str, out_root: Path | str, *, ffmpeg: str = "ffmpeg", force: bool = False,
            resolver: AssetResolver | None = None) -> dict:
    """현재 Draft 버전 -> V3 문서 -> 6-54 render_item(레이아웃 -> 렌더 -> 품질 게이트 -> manifest) -> MP4.
    반환: status(success/skipped/blocked/failed), error_code, reasons, messages, output_path, lineage(draft 포함)."""
    draft = store.load(draft_id)
    version = draft["draft_version"]
    draft_lineage = {"draft_id": draft_id, "draft_version": version, "base_content_id": draft["content_id"],
                     "generation_id": draft.get("generation_id"), "base_content_sha256": draft["base_content_sha256"]}
    item = ContentItem(f"{draft_id}-v{version:04d}", draft["document"], store.base_dir,
                       {"kind": "shorts_draft", **draft_lineage, "base": draft.get("base")})
    try:
        result = render_item(item, Path(out_root) / draft_id, ffmpeg=ffmpeg, force=force, resolver=resolver)
    except V3Error as error:
        result = {"status": "blocked", "reasons": [error.code], "errors": [error.message]}
    except Exception as error:  # noqa: BLE001 - 화면에는 코드와 한 줄 설명만, traceback은 기록에만
        result = {"status": "failed", "reasons": ["RENDER_FAILED"], "errors": [f"{type(error).__name__}: {error}"],
                  "traceback": traceback.format_exc(limit=5)}
    status = result["status"]
    if status == "failed" and result.get("output_path"):  # 렌더는 됐지만 게이트 BLOCK
        error_code = "QUALITY_GATE_FAILED"
    else:
        error_code = (result.get("reasons") or [None])[0] if status in ("blocked", "failed") else None
    lineage = {**(result.get("lineage") or {}), **draft_lineage}
    record = {
        "draft_id": draft_id, "draft_version": version, "at": _now(), "status": status, "error_code": error_code,
        "reasons": result.get("reasons", []), "messages": [describe(c) for c in result.get("reasons", [])],
        "errors": result.get("errors", []), "warnings": result.get("warnings", []),
        "output_path": result.get("output_path"), "manifest_path": result.get("manifest_path"),
        "duration": result.get("duration"), "sha256": result.get("sha256"), "render_key": result.get("render_key"),
        "layouts": result.get("layouts"), "lineage": lineage,
    }
    if record["manifest_path"] and Path(record["manifest_path"]).exists():
        m = json.loads(Path(record["manifest_path"]).read_text(encoding="utf-8"))
        record["media"] = {k: m["output"].get(k) for k in ("width", "height", "fps", "frames", "video_codec", "audio_codec", "audio_channels", "bytes")}
        record["quality"] = m["quality"]["status"]
    store._record_preview(draft_id, record)
    return record


def render_drafts(store: DraftStore, draft_ids: list[str], out_root: Path | str, *, ffmpeg: str = "ffmpeg", force: bool = False) -> dict:
    """여러 Draft 미리보기(배치). 한 Draft 실패는 그 결과에만 남는다. asset 해시/디코드 캐시를 공유한다."""
    resolver = None
    results = []
    for draft_id in draft_ids:
        try:
            doc = store.load(draft_id)["document"]
            resolver = resolver or AssetResolver.for_template(load_template(doc.get("template", "default")))
            results.append(preview(store, draft_id, out_root, ffmpeg=ffmpeg, force=force, resolver=resolver))
        except (DraftError, V3Error) as error:
            results.append({"draft_id": draft_id, "status": "blocked", "error_code": error.code, "reasons": [error.code],
                            "messages": [describe(error.code)], "errors": [str(error)]})
    ok = sum(r["status"] in ("success", "skipped") for r in results)
    return {"total": len(results), "success": ok, "failed": len(results) - ok, "results": results}
