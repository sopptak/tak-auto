"""Shorts Content Studio(6-55, 6-56) - 사람이 고치는 Draft 저장소 + 미리보기 + 최종 렌더 + 사람 승인.

    Production Content(ShortsScript + archive 레코드)  -- 읽기만 한다
        -> open_draft(): adapter로 V3 문서를 만들어 Draft로 복제(data/shorts_drafts/<draft_id>/)
        -> apply_form() / apply_meta() / save(): 사람이 고친 값 -> 검증 -> 버전 스냅샷(v0001.json, v0002.json, ...)
        -> check(): 렌더 없는 검사(6-54 check_document + 편집기 경고) -> PASS / WARNING / BLOCKED
        -> scene_frames(): 같은 렌더러의 장면별 정지 화면(즉시 확인용 PNG)
        -> preview(mode="preview"): 같은 문서·렌더러·게이트, 빠른 인코더 설정 -> 미리보기 MP4
        -> preview(mode="final"):   템플릿 인코더 설정 그대로 -> 최종 MP4
        -> approve(): 최종 MP4(PASS)가 있는 현재 버전을 사람이 승인 - Draft 저장소 안에만 기록

Draft 문서는 V3 Render Document(shorts_v3_document/1) 그대로다(콘텐츠 + 장면별 디자인 선택).
화면 틀(글꼴 크기·영역·색·전환 시간·음악)은 템플릿(content_engine/shorts_v3_templates/)이 가진다.
분야/주제/언어 같은 분류 정보는 렌더 결과에 영향이 없으므로 문서가 아니라 Draft meta에 둔다(render key 불변).

이 모듈이 쓰는 곳: DraftStore.root(draft-* 폴더), preview out_dir, asset 폴더(업로드한 이미지) 세 곳뿐이다.
Production Archive, ShortsScript, review_status/approved/superseded는 읽기만 하고, 쓰는 함수를 import하지도 않는다.
여기서의 "승인"은 Draft 저장소의 기록이다 - Production review_status를 바꾸지 않고 게시하지 않는다.
네트워크/외부 API/LLM을 쓰지 않는다. 문장을 요약하거나 바꾸지 않는다(사람이 입력한 값 그대로 저장).
"""

from __future__ import annotations

import copy
import getpass
import hashlib
import io
import json
import re
import traceback
from datetime import datetime, timezone
from pathlib import Path

from content_engine.shorts_v3_adapter import document_from_shorts_script
from content_engine.shorts_v3_assets import AssetResolver
from content_engine.shorts_v3_contract import check_document
from content_engine.shorts_v3_pipeline import ContentItem, render_item, sha256_file
from content_engine.shorts_v3_template import V3Error, canonical_sha256, deep_merge, load_template

DRAFT_SCHEMA = "shorts_draft/1"
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,120}$")  # content_id - 경로 조작(../) 차단
# draft_id는 항상 "draft-"로 시작한다 - 저장소 root를 잘못 지정해도(예: data/) draft-* 폴더 밖은 가리킬 수 없다.
_DRAFT_ID = re.compile(r"^draft-[A-Za-z0-9][A-Za-z0-9_-]{0,120}$")
MAX_FIELD_CHARS = 4000  # 저장 자체를 막는 상한(렌더 가능 여부는 품질 게이트가 따로 판정)
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
# 미리보기는 최종과 같은 문서·렌더러·레이아웃·게이트를 쓰고 인코더 설정만 빠르게 한다(픽셀 배치는 같고 압축만 다르다).
PREVIEW_ENCODER = {"preset": "ultrafast", "crf": 28}
IMAGE_CROP_WARN = 0.45  # cover로 채울 때 원본 이미지의 45% 넘게 잘리면 경고
META_FIELDS = ("category", "topic", "language", "locale", "master_content_id")
CATEGORIES = ("지식/상식", "AI/테크", "금융/재테크", "부동산", "공인중개사", "공무원 시험", "건강", "역사", "인간관계/심리",
              "게임", "영화", "음악", "어린이", "스토리")
LANGUAGES = {"ko": "한국어", "en": "English", "ja": "日本語", "zh": "中文", "es": "Español", "ar": "العربية"}

# 화면에 보여줄 설명(traceback 대신). 코드는 6-53/6-54 엔진 코드를 그대로 쓴다.
ERROR_TEXT = {
    "TITLE_EMPTY": "제목이 비어 있습니다.",
    "FIELD_TOO_LONG": f"한 칸에 {MAX_FIELD_CHARS}자를 넘게 저장할 수 없습니다.",
    "TITLE_OVERFLOW": "제목이 제목 영역(최대 3줄)에 들어가지 않습니다. 제목을 줄여 주세요.",
    "HEADLINE_OVERFLOW": "헤드라인이 2줄을 넘습니다. 헤드라인을 줄여 주세요.",
    "BODY_OVERFLOW": "본문이 화면에 들어가지 않습니다. 본문을 줄이거나, 장면을 복제해 나눠 쓰거나, '글자 중심' 레이아웃을 써 보세요.",
    "SUBTITLE_OVERFLOW": "자막이 한 줄을 넘습니다.",
    "SOURCE_OVERFLOW": "출처가 한 줄에 들어가지 않습니다.",
    "SOURCE_TRUNCATED": "출처가 길어 화면에서 말줄임(…) 처리됩니다.",
    "ASSET_MISSING": "이미지 파일이 없습니다(IMAGE_MISSING). 이미지를 다시 선택해 주세요.",
    "ASSET_UNSUPPORTED_FORMAT": "지원하지 않는 이미지 형식입니다(PNG/JPEG/WEBP만).",
    "ASSET_DECODE_FAILED": "이미지 파일이 손상돼 읽을 수 없습니다.",
    "ASSET_TOO_SMALL": "이미지가 너무 작습니다(최소 320x320).",
    "ASSET_REQUIRED": "이 레이아웃은 이미지가 필요합니다.",
    "IMAGE_SLOT_EMPTY": "이미지 칸이 비어 있어 빈 틀로 그립니다. 이미지를 고르거나 '글자 중심' 레이아웃을 쓰세요.",
    "IMAGE_RATIO_CROP": "이미지 비율이 칸과 많이 달라 크게 잘립니다. '전체 보이기'나 다른 레이아웃을 고려하세요.",
    "INVALID_DURATION": "장면 길이가 잘못됐습니다(0보다 크고, 글을 읽을 수 있는 길이여야 합니다).",
    "INVALID_LAYOUT": "템플릿에 없는 레이아웃입니다.",
    "INVALID_TEMPLATE": "설정 값이 잘못됐습니다(예: 음량 0~2, 진행 표시 위치).",
    "INVALID_IMAGE_SPEC": "이미지 맞춤/위치/확대 값이 잘못됐습니다.",
    "INVALID_TRANSITION": "지원하지 않는 전환입니다.",
    "INVALID_DOCUMENT": "문서 형식이 잘못됐습니다.",
    "EMPTY_SCENE": "장면에 이미지/헤드라인/본문 중 하나는 있어야 합니다.",
    "SAFE_AREA_VIOLATION": "글자나 이미지가 화면 안전영역 밖으로 나갑니다.",
    "FRAME_VIOLATION": "요소가 정해진 영역 밖으로 나갑니다.",
    "PROGRESS_OVERLAP": "진행 표시가 다른 요소와 겹칩니다.",
    "SCENE_TIMING_INVALID": "장면 타이밍이 맞지 않습니다.",
    "LINEAGE_MISSING": "content_id(lineage)가 없습니다.",
    "SOURCE_MISSING": "출처가 한 곳도 없습니다. 사실을 다루는 콘텐츠라면 출처를 넣어 주세요.",
    "BODY_MISSING": "본문이 있는 장면이 하나도 없습니다.",
    "EMPHASIS_NOT_FOUND": "강조 문구가 헤드라인/본문 안에 없어 강조되지 않습니다.",
    "FONT_GLYPH_MISSING": "현재 글꼴에 없는 문자가 있어 네모(□)로 보입니다(예: 아랍어/이모지).",
    "RENDER_FAILED": "렌더 중 오류가 났습니다(ffmpeg 경로/폰트를 확인해 주세요).",
    "QUALITY_GATE_FAILED": "영상은 만들어졌지만 품질 게이트를 통과하지 못했습니다.",
    "FILE_MISSING": "영상 파일이 만들어지지 않았습니다.", "DECODE_ERROR": "영상 파일이 깨졌습니다.",
    "DURATION_MISMATCH": "영상 길이가 계획과 다릅니다.", "RESOLUTION_MISMATCH": "해상도가 1080x1920이 아닙니다.",
    "CODEC_MISMATCH": "코덱이 h264/aac가 아닙니다.", "BLANK_FRAME": "빈(검은) 화면이 있습니다.",
    "FRAME_COUNT_MISMATCH": "프레임 수가 계획과 다릅니다.", "AUDIO_MISSING": "소리가 없습니다.",
    "AUDIO_SILENT": "소리가 사실상 들리지 않습니다.", "AUDIO_FADE_MISSING": "끝부분 소리가 줄어들지 않습니다.",
    "AUDIO_MISMATCH": "소리 길이/채널이 영상과 맞지 않습니다.",
    "DRAFT_NOT_FOUND": "Draft를 찾을 수 없습니다.",
    "DRAFT_CONFLICT": "다른 곳에서 먼저 저장했습니다. 새로고침 후 다시 고쳐 주세요.",
    "SOURCE_NOT_FOUND": "원본 콘텐츠(ShortsScript)를 찾을 수 없습니다.",
    "BASE_CHANGED": "Draft를 만든 뒤 원본 ShortsScript가 바뀌었습니다. 원본으로 초기화하거나 차이를 확인해 주세요.",
    "SUPERSEDED": "이 콘텐츠는 새 버전으로 대체(superseded)됐습니다. 편집/렌더/승인할 수 없습니다.",
    "GENERATION_MISMATCH": "같은 content_id의 다른 generation으로 만든 Draft가 이미 있습니다. 섞이지 않도록 막았습니다.",
    "APPROVAL_NOT_READY": "지금 버전의 최종 렌더(품질 검사 PASS)가 아직 없습니다. '최종 렌더'를 먼저 누르세요.",
    "UPLOAD_INVALID": "이미지 파일로 읽을 수 없습니다(PNG/JPEG/WEBP, 최소 320x320, 20MB 이하).",
}
# 게이트 결과를 사람이 읽는 3단계로
PASS, WARNING, BLOCKED = "PASS", "WARNING", "BLOCKED"


def describe(code: str) -> str:
    return ERROR_TEXT.get(code, code)


class DraftError(Exception):
    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or describe(code))
        self.code = code
        self.message = message or describe(code)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _operator() -> str:
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001 - 사용자 이름을 못 읽어도 저장은 된다
        return "local"


def _write_json(path: Path, data) -> None:
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


def is_superseded(entry: dict | None) -> bool:
    return bool(entry) and (bool(entry.get("superseded_by")) or entry.get("review_status") == "superseded")


def document_from_source(entry: dict) -> tuple[dict, str]:
    """원본 ShortsScript -> V3 문서(adapter). (문서, 원본 sha256)."""
    path = Path(entry["script_path"])
    if not path.exists():
        raise DraftError("SOURCE_NOT_FOUND", f"ShortsScript 없음: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    doc = document_from_shorts_script(raw, generation_id=entry.get("generation_id"),
                                      source_script=str(path).replace("\\", "/"))
    return doc, sha256_file(path)


def base_drift(draft: dict, entry: dict | None) -> str | None:
    """Draft를 만든 뒤 원본 ShortsScript가 바뀌었으면 사유 코드(승인 전 사람이 알아야 한다). 원본은 읽기만."""
    if entry is None or not Path(entry["script_path"]).exists():
        return "SOURCE_NOT_FOUND"
    return None if sha256_file(Path(entry["script_path"])) == draft["base_content_sha256"] else "BASE_CHANGED"


def guard(draft: dict, entry: dict | None) -> list[str]:
    """이 Draft로 렌더/승인하면 안 되는 이유(없으면 빈 목록). BASE_CHANGED는 승인만 막는다(approve에서 따로 본다)."""
    if entry is None:
        return ["SOURCE_NOT_FOUND"]
    if is_superseded(entry):
        return ["SUPERSEDED"]
    if (entry.get("generation_id") or None) != (draft.get("generation_id") or None):
        return ["GENERATION_MISMATCH"]
    return []


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
            for k, e in enumerate(s.get("emphasis") or []):
                yield f"scene {i + 1} emphasis {k + 1}", e


_GLYPH_CACHE: dict = {}


def missing_glyphs(text: str, font_path: Path | str) -> list[str]:
    """글꼴에 없는(= .notdef 네모로 그려질) 문자. 다국어 확장 때 조용히 깨지지 않게 경고용."""
    from PIL import ImageFont

    key = str(font_path)
    if key not in _GLYPH_CACHE:
        font = ImageFont.truetype(key, 40)
        _GLYPH_CACHE[key] = (font, bytes(font.getmask("\U000F0000")), {})  # 15번 평면 사용자 영역 = 어떤 글꼴에도 없음
    font, notdef, seen = _GLYPH_CACHE[key]
    missing = []
    for ch in dict.fromkeys(text):
        if ch.isspace() or ch in "*":
            continue
        if ch not in seen:
            seen[ch] = bytes(font.getmask(ch)) == notdef
        if seen[ch]:
            missing.append(ch)
    return missing


def _editor_warnings(document: dict, base_dir: Path | str) -> list[dict]:
    """게이트가 막지는 않지만 사람이 알아야 하는 것(출처 없음, 강조 문구 없음, 글꼴에 없는 문자, 이미지 크게 잘림)."""
    from content_engine.shorts_v2_renderer import LOOKS
    from content_engine.shorts_v3_document import V3RenderDocument
    from content_engine.shorts_v3_layout import LayoutEngine

    out = []
    scenes = [s for s in document.get("scenes") or [] if isinstance(s, dict)]
    if scenes and not any(s.get("source") for s in scenes):
        out.append({"code": "SOURCE_MISSING", "severity": "warning", "scene": None})
    if scenes and not any(str(s.get("body", "")).strip() for s in scenes):
        out.append({"code": "BODY_MISSING", "severity": "warning", "scene": None})
    for i, s in enumerate(scenes):
        text = f"{s.get('headline', '')} {s.get('body', '')}"
        if any(e and e not in text for e in s.get("emphasis") or []):
            out.append({"code": "EMPHASIS_NOT_FOUND", "severity": "warning", "scene": i})
    doc = V3RenderDocument.from_dict(document, base_dir=base_dir)
    font = LOOKS[doc.template["look"]].font
    all_text = " ".join(str(v) for _, v in _texts(document) if isinstance(v, str) and not _.endswith("image"))
    if missing := missing_glyphs(all_text, font):
        out.append({"code": "FONT_GLYPH_MISSING", "severity": "warning", "scene": None,
                    "message": " ".join(f"U+{ord(c):04X}" for c in missing[:8])})
    engine = LayoutEngine(doc)
    report = engine.report()
    for i, scene in enumerate(doc.scenes):
        asset = engine.assets.get(i)
        box = next((b["bbox"] for b in report["scenes"][i]["boxes"] if b["name"] == "image"), None)
        if not (asset and asset.ok and box and scene.image) or (scene.image.fit or doc.template["image"]["fit"]) != "cover":
            continue
        slot, img = (box[2] - box[0]) / max(1, box[3] - box[1]), asset.width / max(1, asset.height)
        if 1 - min(slot / img, img / slot) > IMAGE_CROP_WARN:
            out.append({"code": "IMAGE_RATIO_CROP", "severity": "warning", "scene": i})
    return out


def _item(issue: dict, level: str) -> dict:
    scene = issue.get("scene")
    where = f"장면 {scene + 1}: " if isinstance(scene, int) else ""
    return {"level": level, "code": issue["code"], "scene": scene, "text": where + describe(issue["code"]),
            "detail": issue.get("message", "")}


def check(document: dict, base_dir: Path | str) -> dict:
    """저장/미리보기 전 검사. hard=True면 저장할 수 없는 값(빈 제목, 잘못된 길이/레이아웃 등 문서 오류),
    hard=False인 codes는 저장은 되지만 품질 게이트가 렌더를 막는 문제(overflow, 이미지 없음 등).
    verdict: PASS / WARNING(렌더 가능, 확인 권장) / BLOCKED. items: 사람이 읽는 문장 목록."""
    def hard(code: str, detail: str = "") -> dict:
        return {"ok": False, "hard": True, "codes": [code], "errors": [detail or describe(code)], "warnings": [], "scenes": [],
                "total": None, "verdict": BLOCKED, "items": [{"level": BLOCKED, "code": code, "scene": None, "text": describe(code), "detail": detail}]}

    if not str(document.get("title", "")).strip():
        return hard("TITLE_EMPTY")
    for name, value in _texts(document):
        if isinstance(value, str) and len(value) > MAX_FIELD_CHARS:
            return hard("FIELD_TOO_LONG", f"{name}: {len(value)}자")
    report = check_document(document, base_dir)
    if report["total"] is None:  # 문서 자체를 읽을 수 없음(V3Error)
        return hard(report["codes"][0], "; ".join(report["errors"]))
    report["hard"] = False
    extra = _editor_warnings(document, base_dir)
    report["warnings"] = report["warnings"] + [w["code"] for w in extra]
    items = [_item(i, BLOCKED if i["severity"] == "error" else WARNING) for i in report.get("issues", [])]
    items += [_item(w, WARNING) for w in extra]
    report["items"] = sorted(items, key=lambda x: (x["level"] != BLOCKED, x["scene"] if x["scene"] is not None else -1))
    report["verdict"] = BLOCKED if report["codes"] else WARNING if items else PASS
    return report


# ---- 편집 폼 -> 문서 ---------------------------------------------------------------------------

def _set(target: dict, key: str, value) -> None:
    if value in (None, "", []):
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


def _getter(form):
    def get(key: str):
        value = form.get(key)
        if isinstance(value, list):
            value = value[0] if value else ""
        return None if value is None else str(value).replace("\r\n", "\n")
    return get


def apply_form(document: dict, form: dict[str, list[str]] | dict[str, str]) -> dict:
    """편집 화면 값 -> 새 문서(원본 dict는 바꾸지 않는다). 폼에 없는 키는 그대로 둔다. 빈 값 = 키 제거(템플릿 기본값/자동)."""
    get = _getter(form)
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
        if (v := get(p + "emphasis")) is not None:  # 강조 문구: 한 줄에 하나
            _set(scene, "emphasis", [line.strip() for line in v.split("\n") if line.strip()])
        if (v := get(p + "duration")) is not None:
            _set(scene, "duration", _number(v))
        if (v := get(p + "source_value")) is not None:
            label = (get(p + "source_label") or "").strip()
            _set(scene, "source", ({"label": label, "value": v.strip()} if label else v.strip()) if v.strip() else None)
        path = get(p + "image_custom")  # Advanced: 경로 직접 입력이 있으면 그 값이 우선
        if not (path or "").strip():
            path = get(p + "image_path")
        if path is not None:
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
    # 장면(프레임) 편집: 복제/삭제/위·아래 이동. 새 빈 장면은 EMPTY_SCENE이라 만들지 않는다(복제 후 고친다).
    op, _, index = (get("scene_op") or "").partition(":")
    if index.isdigit() and int(index) < len(scenes):
        i = int(index)
        if op == "duplicate":
            scenes.insert(i + 1, copy.deepcopy(scenes[i]))
        elif op == "delete" and len(scenes) > 1:
            del scenes[i]
        elif op == "up" and i > 0:
            scenes[i - 1], scenes[i] = scenes[i], scenes[i - 1]
        elif op == "down" and i + 1 < len(scenes):
            scenes[i + 1], scenes[i] = scenes[i], scenes[i + 1]
    return doc


def apply_meta(meta: dict, form) -> dict:
    """분야/주제/언어 등 분류 정보(렌더 결과와 무관 - 문서가 아니라 Draft meta)."""
    get = _getter(form)
    meta = dict(meta or {})
    for key in META_FIELDS:
        if (v := get(f"meta_{key}")) is not None:
            _set(meta, key, v.strip())
    return meta


# ---- 이미지 asset(업로드) ------------------------------------------------------------------------

def store_asset(data: bytes, filename: str, asset_dir: Path | str) -> Path:
    """업로드한 이미지를 검사해 asset 폴더에 저장한다(같은 내용이면 같은 파일). 6-54 asset resolver와 같은 기준."""
    from PIL import Image

    if not data or len(data) > MAX_UPLOAD_BYTES:
        raise DraftError("UPLOAD_INVALID", f"{len(data or b'')} bytes")
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.verify()
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            fmt, size = img.format, img.size
    except Exception as error:  # noqa: BLE001 - 무엇이든 이미지로 못 읽으면 같은 코드
        raise DraftError("UPLOAD_INVALID", f"{type(error).__name__}") from error
    if fmt not in ("PNG", "JPEG", "WEBP") or min(size) < 320:
        raise DraftError("UPLOAD_INVALID", f"{fmt} {size[0]}x{size[1]}")
    stem = re.sub(r"[^A-Za-z0-9가-힣_-]+", "_", Path(filename or "image").stem)[:40].strip("_") or "image"
    ext = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}[fmt]
    target = Path(asset_dir) / "uploads" / f"{hashlib.sha256(data).hexdigest()[:12]}-{stem}{ext}"
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return target


# ---- Draft 저장소 ------------------------------------------------------------------------------

class DraftStore:
    """data/shorts_drafts/<draft_id>/current.json + versions/vNNNN.json(바뀌지 않는 스냅샷) + previews.json
    + approvals.json + frames/(장면 정지 화면 캐시)."""

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
        return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(self.root.glob("draft-*/current.json"))]

    def _commit(self, draft: dict, report: dict | None = None) -> dict:
        d = self._dir(draft["draft_id"])
        snapshot = d / "versions" / f"v{draft['draft_version']:04d}.json"
        if snapshot.exists():  # 스냅샷은 덮어쓰지 않는다
            raise DraftError("DRAFT_CONFLICT", f"이미 있는 버전: v{draft['draft_version']}")
        draft = {**draft, "document_sha256": canonical_sha256(draft["document"]),
                 "check": _check_summary(draft["document"], self.base_dir, report)}
        _write_json(snapshot, draft)
        _write_json(d / "current.json", draft)
        return draft

    def open_draft(self, entry: dict) -> dict:
        """원본 콘텐츠 -> Draft(이미 있으면 그대로 연다 - 사람이 고친 내용을 덮어쓰지 않는다).
        대체된 콘텐츠는 열지 않고, 같은 content_id의 다른 generation Draft와 섞지 않는다."""
        if not _ID.match(entry.get("content_id") or ""):
            raise DraftError("SOURCE_NOT_FOUND", f"잘못된 content_id: {entry.get('content_id')!r}")
        if is_superseded(entry):
            raise DraftError("SUPERSEDED", f"{entry['content_id']} → {entry.get('superseded_by')}")
        draft_id = f"draft-{entry['content_id']}"
        if self.exists(draft_id):
            draft = self.load(draft_id)
            if guard(draft, entry):
                raise DraftError(guard(draft, entry)[0], f"Draft generation {draft.get('generation_id')} / 원본 {entry.get('generation_id')}")
            return draft
        document, base_sha = document_from_source(entry)
        now = _now()
        return self._commit({
            "schema": DRAFT_SCHEMA, "draft_id": draft_id, "draft_version": 1, "parent_version": None, "status": "draft",
            "content_id": entry["content_id"], "generation_id": entry.get("generation_id"),
            "base_content_sha256": base_sha,
            "base": {"kind": "shorts_script", "script_path": entry["script_path"].replace("\\", "/"),
                     "archive_path": entry.get("archive_path", "").replace("\\", "/"),
                     "review_status": entry.get("review_status"), "knowledge_id": entry.get("knowledge_id")},
            "meta": {"language": "ko", "locale": "ko-KR", "master_content_id": entry["content_id"]},
            "created_at": now, "updated_at": now, "modified_by": _operator(), "note": "원본에서 복제", "document": document,
        })

    def save(self, draft_id: str, document: dict, *, expected_version: int | None = None, note: str = "",
             meta: dict | None = None) -> tuple[dict, dict, bool]:
        """검증 -> 새 버전 저장. (draft, check 결과, 저장했는지). 내용(문서+meta)이 같으면 버전을 올리지 않는다.
        저장할 수 없는 값이면 DraftError(code)."""
        draft = self.load(draft_id)
        if expected_version is not None and expected_version != draft["draft_version"]:
            raise DraftError("DRAFT_CONFLICT", f"편집 시작 v{expected_version}, 현재 v{draft['draft_version']}")
        report = check(document, self.base_dir)
        if report["hard"]:
            raise DraftError(report["codes"][0], "; ".join(report["errors"]) or describe(report["codes"][0]))
        meta = draft.get("meta", {}) if meta is None else meta
        if document == draft["document"] and meta == draft.get("meta", {}):
            return draft, report, False
        new = {**draft, "document": copy.deepcopy(document), "meta": dict(meta), "draft_version": draft["draft_version"] + 1,
               "parent_version": draft["draft_version"], "updated_at": _now(), "modified_by": _operator(), "note": note or "편집"}
        return self._commit(new, report), report, True

    def versions(self, draft_id: str) -> list[dict]:
        return [{k: v.get(k) for k in ("draft_version", "parent_version", "updated_at", "modified_by", "note", "document_sha256")}
                | {"title": v["document"].get("title")}
                for v in (json.loads(p.read_text(encoding="utf-8")) for p in sorted((self._dir(draft_id) / "versions").glob("v*.json")))]

    def load_version(self, draft_id: str, version: int) -> dict:
        path = self._dir(draft_id) / "versions" / f"v{int(version):04d}.json"
        if not path.exists():
            raise DraftError("DRAFT_NOT_FOUND", f"{draft_id} v{version} 없음")
        return json.loads(path.read_text(encoding="utf-8"))

    def revert(self, draft_id: str, version: int) -> dict:
        """이전 버전 내용으로 되돌린다 - 기록을 지우지 않고 새 버전으로 쌓는다."""
        old = self.load_version(draft_id, version)
        draft, _, _ = self.save(draft_id, old["document"], meta=old.get("meta", {}), note=f"v{version}로 되돌림")
        return draft

    def reset_to_base(self, draft_id: str, entry: dict) -> dict:
        """원본 Production Content로 되돌린다(새 버전). 원본 파일은 읽기만 한다. 분류 meta는 유지한다."""
        draft = self.load(draft_id)
        if problems := guard(draft, entry):
            raise DraftError(problems[0])
        document, base_sha = document_from_source(entry)
        if document == draft["document"] and base_sha == draft["base_content_sha256"]:
            return draft
        new = {**draft, "document": document, "draft_version": draft["draft_version"] + 1, "parent_version": draft["draft_version"],
               "updated_at": _now(), "modified_by": _operator(), "base_content_sha256": base_sha, "note": "원본으로 초기화"}
        return self._commit(new)

    def previews(self, draft_id: str) -> list[dict]:
        path = self._dir(draft_id) / "previews.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []

    def _record_preview(self, draft_id: str, result: dict) -> None:
        _write_json(self._dir(draft_id) / "previews.json", [*self.previews(draft_id), result])

    def approvals(self, draft_id: str) -> list[dict]:
        path = self._dir(draft_id) / "approvals.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def _check_summary(document: dict, base_dir: Path, report: dict | None = None) -> dict:
    try:
        r = report or check(document, base_dir)
        return {"verdict": r["verdict"], "codes": r["codes"], "warnings": r["warnings"]}
    except Exception as error:  # noqa: BLE001 - 요약 실패가 저장을 막지 않는다
        return {"verdict": BLOCKED, "codes": [type(error).__name__], "warnings": []}


# ---- 상태 ------------------------------------------------------------------------------------

def draft_state(draft: dict | None, previews: list[dict], approvals: list[dict] | None = None) -> str:
    """목록 필터용 상태(저장하지 않고 기록에서 계산한다 - 따로 관리하는 상태값이 어긋날 일이 없다).
    NO_DRAFT / DRAFT(원본 그대로) / EDITED / PREVIEW_READY / RENDERED / APPROVED / BLOCKED"""
    if draft is None:
        return "NO_DRAFT"
    v = draft["draft_version"]
    if any(a.get("draft_version") == v and not a.get("revoked") for a in approvals or []):
        return "APPROVED"
    current = [p for p in previews if p.get("draft_version") == v]
    if current and current[-1]["status"] in ("blocked", "failed"):
        return "BLOCKED"
    if (draft.get("check") or {}).get("verdict") == BLOCKED:
        return "BLOCKED"
    ok = [p for p in current if p["status"] in ("success", "skipped")]
    if any(p.get("mode") == "final" for p in ok):
        return "RENDERED"
    if ok:
        return "PREVIEW_READY"
    return "DRAFT" if v == 1 or draft.get("note") == "원본으로 초기화" else "EDITED"


# ---- 미리보기 / 최종 렌더 ------------------------------------------------------------------------

def _render_document(document: dict, mode: str) -> dict:
    if mode == "final":
        return document
    name = document.get("template", "default")
    base = load_template(name) if isinstance(name, str) else dict(name)
    return {**document, "template": deep_merge(base, {"encoder": PREVIEW_ENCODER})}


def preview(store: DraftStore, draft_id: str, out_root: Path | str, *, ffmpeg: str = "ffmpeg", force: bool = False,
            resolver: AssetResolver | None = None, mode: str = "preview", entry: dict | None = None) -> dict:
    """현재 Draft 버전 -> V3 문서 -> 6-54 render_item(레이아웃 -> 렌더 -> 품질 게이트 -> manifest) -> MP4.
    mode="preview": 빠른 인코더(같은 픽셀 배치), mode="final": 템플릿 인코더 그대로(최종본).
    entry를 주면 대체(superseded)/generation 불일치 콘텐츠는 렌더하지 않는다.
    반환: status(success/skipped/blocked/failed), error_code, reasons, messages, output_path, lineage(draft 포함)."""
    if mode not in ("preview", "final"):
        raise ValueError(mode)
    draft = store.load(draft_id)
    version = draft["draft_version"]
    draft_lineage = {"draft_id": draft_id, "draft_version": version, "base_content_id": draft["content_id"],
                     "generation_id": draft.get("generation_id"), "base_content_sha256": draft["base_content_sha256"],
                     "draft_document_sha256": canonical_sha256(draft["document"])}
    blocked = guard(draft, entry) if entry is not None else []
    item = ContentItem(f"{draft_id}-v{version:04d}-{mode}", _render_document(draft["document"], mode), store.base_dir,
                       {"kind": "shorts_draft", "mode": mode, **draft_lineage, "base": draft.get("base")})
    try:
        if blocked:
            raise V3Error(blocked[0], describe(blocked[0]))
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
        "draft_id": draft_id, "draft_version": version, "mode": mode, "at": _now(), "status": status, "error_code": error_code,
        "reasons": result.get("reasons", []), "messages": [describe(c) for c in result.get("reasons", [])],
        "errors": result.get("errors", []), "warnings": result.get("warnings", []),
        "output_path": result.get("output_path"), "manifest_path": result.get("manifest_path"),
        "duration": result.get("duration"), "sha256": result.get("sha256"), "render_key": result.get("render_key"),
        "layouts": result.get("layouts"), "seconds": result.get("seconds"), "lineage": lineage,
    }
    if record["manifest_path"] and Path(record["manifest_path"]).exists():
        m = json.loads(Path(record["manifest_path"]).read_text(encoding="utf-8"))
        record["media"] = {k: m["output"].get(k) for k in ("width", "height", "fps", "frames", "video_codec", "audio_codec", "audio_channels", "bytes")}
        record["quality"] = m["quality"]["status"]
        record["publish_contract"] = m.get("publish_contract")
    store._record_preview(draft_id, record)
    return record


def render_drafts(store: DraftStore, draft_ids: list[str], out_root: Path | str, *, ffmpeg: str = "ffmpeg", force: bool = False,
                  mode: str = "preview") -> dict:
    """여러 Draft 미리보기(배치). 한 Draft 실패는 그 결과에만 남는다. asset 해시/디코드 캐시를 공유한다."""
    resolver = None
    results = []
    for draft_id in draft_ids:
        try:
            doc = store.load(draft_id)["document"]
            resolver = resolver or AssetResolver.for_template(load_template(doc.get("template", "default")))
            results.append(preview(store, draft_id, out_root, ffmpeg=ffmpeg, force=force, resolver=resolver, mode=mode))
        except (DraftError, V3Error) as error:
            results.append({"draft_id": draft_id, "status": "blocked", "error_code": error.code, "reasons": [error.code],
                            "messages": [describe(error.code)], "errors": [str(error)]})
    ok = sum(r["status"] in ("success", "skipped") for r in results)
    return {"total": len(results), "success": ok, "failed": len(results) - ok, "results": results}


def scene_frames(store: DraftStore, draft_id: str, *, width: int = 360) -> dict:
    """현재 버전 각 장면(+엔드카드)의 정지 화면 - 최종 MP4와 같은 렌더러(ShortsV3Renderer.frame)로 그린다.
    MP4 검사와 같은 시점(장면 길이의 60%). 문서 해시로 캐시. 레이아웃이 막히면 {"error": code}."""
    from content_engine.shorts_v3_document import V3RenderDocument
    from content_engine.shorts_v3_renderer import ShortsV3Renderer

    draft = store.load(draft_id)
    key = canonical_sha256(draft["document"])[:16]
    folder = store._dir(draft_id) / "frames" / key
    done = folder / "frames.json"
    if done.exists():
        return json.loads(done.read_text(encoding="utf-8"))
    try:
        doc = V3RenderDocument.from_dict(draft["document"], base_dir=store.base_dir)
        renderer = ShortsV3Renderer(doc)
    except V3Error as error:
        return {"key": key, "error": error.code, "message": error.message, "frames": []}
    folder.mkdir(parents=True, exist_ok=True)
    frames = []
    for i, ts in enumerate(renderer.timeline):
        img = renderer.frame(ts.start + ts.duration * 0.6).convert("RGB")
        img = img.resize((width, round(width * img.height / img.width)))
        name = f"scene{i + 1:02d}.png"
        img.save(folder / name)
        frames.append({"index": i, "file": f"{key}/{name}", "start": round(ts.start, 2), "duration": round(ts.duration, 2),
                       "end_card": ts.scene is None})
    result = {"key": key, "error": None, "frames": frames, "total": round(renderer.total, 2)}
    _write_json(done, result)
    return result


# ---- 사람 승인(Draft 저장소 안) ------------------------------------------------------------------

def approval_blockers(store: DraftStore, draft_id: str, entry: dict | None) -> list[str]:
    """승인 조건(6-55 37장 C 계약): 현재 버전의 최종 렌더 PASS + MP4 sha256 일치 + 원본 변경/대체/generation 불일치 없음."""
    draft = store.load(draft_id)
    problems = guard(draft, entry)
    if (drift := base_drift(draft, entry)) and drift not in problems:
        problems.append(drift)
    final = [p for p in store.previews(draft_id) if p.get("draft_version") == draft["draft_version"] and p.get("mode") == "final"
             and p["status"] in ("success", "skipped") and p.get("quality", "PASS") == "PASS"]
    if not final or not final[-1].get("output_path") or not Path(final[-1]["output_path"]).exists() \
            or sha256_file(Path(final[-1]["output_path"])) != final[-1].get("sha256"):
        problems.append("APPROVAL_NOT_READY")
    return problems


def approve(store: DraftStore, draft_id: str, entry: dict | None, *, note: str = "") -> dict:
    """사람이 누른 승인만 기록한다(자동 승인 없음). Production review_status는 바꾸지 않는다 - 게시 파이프라인에 넘길 계약만 남긴다."""
    if problems := approval_blockers(store, draft_id, entry):
        raise DraftError(problems[0], ", ".join(problems))
    draft = store.load(draft_id)
    final = [p for p in store.previews(draft_id) if p.get("draft_version") == draft["draft_version"] and p.get("mode") == "final"
             and p["status"] in ("success", "skipped")][-1]
    record = {"draft_id": draft_id, "draft_version": draft["draft_version"], "content_id": draft["content_id"],
              "generation_id": draft.get("generation_id"), "base_content_sha256": draft["base_content_sha256"],
              "render_key": final["render_key"], "mp4_sha256": final["sha256"], "video": final["output_path"],
              "approved_by": _operator(), "approved_at": _now(), "note": note, "revoked": False,
              "publish_contract": final.get("publish_contract")}
    _write_json(store._dir(draft_id) / "approvals.json", [*store.approvals(draft_id), record])
    return record


def revoke_approval(store: DraftStore, draft_id: str) -> None:
    items = store.approvals(draft_id)
    for a in items:
        if not a.get("revoked"):
            a.update(revoked=True, revoked_at=_now(), revoked_by=_operator())
    _write_json(store._dir(draft_id) / "approvals.json", items)
