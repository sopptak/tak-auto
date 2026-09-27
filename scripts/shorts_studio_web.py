"""Shorts Studio 화면(6-55, 6-56) - scripts/run_scout_dashboard.py가 /shorts-studio 요청을 여기로 넘긴다.

운영자는 개발자가 아니라는 전제: JSON/경로/ID를 입력하지 않고 고르고 누른다. ID·해시·경로는 접힌 "고급 정보"에만.
원본(Production Archive + ShortsScript)은 읽기만 하고, 고친 내용은 content_engine.shorts_studio.DraftStore에만 저장한다.
승인은 Draft 저장소 안의 기록이다 - Production review_status를 바꾸거나 게시하지 않는다.

    handle(config, method, path, query, body, content_type) -> ("html", status, bytes) | ("redirect", url) | ("file", type, bytes)
"""

from __future__ import annotations

import email
import email.policy
import json
import re
from datetime import datetime
from html import escape
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote

from content_engine import shorts_studio as studio
from content_engine.shorts_v3_contract import editable_fields

ROOT = Path(__file__).resolve().parents[1]

LAYOUT_LABELS = {"text_focus": "글자 중심", "image_top": "이미지 위 · 글 아래", "split": "좌우 나눔(이미지 | 글)",
                 "image_full": "이미지 전체 · 글 겹침"}
TRANSITION_LABELS = {"": "기본(톡)", "punch": "톡", "dissolve": "스르륵", "fade": "스르륵(fade)", "slide": "밀기", "cut": "바로 전환"}
FIT_LABELS = {"": "기본(꽉 채우기)", "cover": "꽉 채우기(가장자리 잘림)", "contain": "전체 보이기(여백 흐림)", "crop": "꽉 채우기(crop)"}
MUSIC_LABELS = {"": "기본", "ai": "테크(ai)", "finance": "차분(finance)", "human": "따뜻(human)"}
STATE_LABELS = {"NO_DRAFT": ("Draft 없음", "#eee", "#555"), "DRAFT": ("Draft", "#eef0f7", "#33415c"),
                "EDITED": ("Edited", "#fff4de", "#6b4a00"), "PREVIEW_READY": ("Preview Ready", "#e3eefc", "#1d4f91"),
                "RENDERED": ("Rendered", "#dff3e3", "#1a5c3a"), "APPROVED": ("Approved", "#1a5c3a", "#fff"),
                "BLOCKED": ("Blocked", "#f9e0e0", "#7a2626"), "LOCKED": ("Superseded(잠김)", "#ddd", "#555")}
VERDICT_COLORS = {"PASS": ("#dff3e3", "#1a5c3a"), "WARNING": ("#fff4de", "#6b4a00"), "BLOCKED": ("#f9e0e0", "#7a2626")}
GRID = [("0,0", "↖"), ("0.5,0", "↑"), ("1,0", "↗"), ("0,0.5", "←"), ("0.5,0.5", "●"), ("1,0.5", "→"), ("0,1", "↙"), ("0.5,1", "↓"), ("1,1", "↘")]
NAMED_POSITIONS = {"center": (0.5, 0.5), "top": (0.5, 0.0), "bottom": (0.5, 1.0), "left": (0.0, 0.5), "right": (1.0, 0.5)}
MAX_BODY_BYTES = studio.MAX_UPLOAD_BYTES * 4 + 1_000_000  # 장면 여러 개에 한 번에 올리는 경우까지

STYLE = """<style>
  .studio-wrap { max-width: 1280px; }
  .studio-grid { display: grid; grid-template-columns: 400px minmax(0, 1fr); gap: 16px; align-items: start; }
  .sticky { position: sticky; top: 8px; max-height: calc(100vh - 16px); overflow-y: auto; }
  @media (max-width: 900px) { .studio-grid { grid-template-columns: minmax(0, 1fr); } .sticky { position: static; } }
  .studio label.f { display: block; font-size: 0.8rem; color: #555; margin: 10px 0 3px; font-weight: 600; }
  .studio input[type=text], .studio input[type=number], .studio select, .studio textarea {
    width: 100%; padding: 8px 10px; border-radius: 8px; border: 1px solid #ccc; font-size: 0.95rem; font-family: inherit; }
  .studio textarea { min-height: 70px; max-width: none; }
  .row { display: flex; gap: 10px; flex-wrap: wrap; }
  .row > div { flex: 1 1 170px; min-width: 0; }
  .code { font-family: ui-monospace, Consolas, monospace; font-size: 0.78rem; background: #f1f1ef; padding: 1px 6px; border-radius: 4px; word-break: break-all; }
  .badge { display: inline-block; font-size: 0.78rem; padding: 2px 10px; border-radius: 999px; font-weight: 700; }
  .item { padding: 6px 10px; border-radius: 8px; margin: 5px 0; font-size: 0.86rem; }
  .item.BLOCKED { background: #f9e0e0; color: #7a2626; } .item.WARNING { background: #fff4de; color: #6b4a00; }
  .frames { display: flex; gap: 6px; overflow-x: auto; padding-bottom: 4px; }
  .frames a { flex: 0 0 auto; text-align: center; font-size: 0.72rem; color: #555; text-decoration: none; }
  .frames img { width: 84px; border-radius: 6px; border: 1px solid #ddd; display: block; }
  video { width: auto; max-width: 100%; height: 52vh; aspect-ratio: 9 / 16; border-radius: 10px; background: #000; display: block; }
  button[disabled] { opacity: 0.45; cursor: not-allowed; }
  .section-title { font-size: 0.8rem; font-weight: 800; color: #1a5c3a; letter-spacing: 0.04em; margin: 14px 0 2px; }
  .scene-head { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
  .scene-head b { font-size: 1.02rem; margin-right: auto; }
  .mini { padding: 4px 9px; font-size: 0.8rem; }
  .gallery { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 6px; }
  .gallery label { cursor: pointer; font-size: 0.7rem; text-align: center; width: 92px; word-break: break-all; }
  .gallery img { width: 92px; height: 92px; object-fit: cover; border-radius: 6px; border: 2px solid #ddd; display: block; }
  .gallery input { display: none; }
  .gallery input:checked + img { border-color: #1a5c3a; box-shadow: 0 0 0 2px #1a5c3a55; }
  .gallery .none { width: 92px; height: 92px; border-radius: 6px; border: 2px dashed #bbb; display: flex; align-items: center; justify-content: center; color: #777; }
  .gallery input:checked + .none { border-color: #1a5c3a; color: #1a5c3a; }
  .current-img { display: flex; gap: 10px; align-items: center; }
  .current-img img { width: 120px; max-height: 160px; object-fit: contain; border-radius: 6px; border: 1px solid #ddd; background: #222; }
  .pgrid { display: inline-grid; grid-template-columns: repeat(3, 34px); gap: 3px; }
  .pgrid label { cursor: pointer; }
  .pgrid input { display: none; }
  .pgrid span { display: block; width: 34px; height: 30px; line-height: 30px; text-align: center; border: 1px solid #ccc; border-radius: 6px; background: #fff; }
  .pgrid input:checked + span { background: #1a5c3a; color: #fff; border-color: #1a5c3a; }
  .radios label { display: inline-block; margin: 2px 10px 2px 0; font-size: 0.88rem; }
  .list-table { border-collapse: collapse; font-size: 0.88rem; background: #fff; width: 100%; }
  .list-table th, .list-table td { border-bottom: 1px solid #eee; padding: 8px; text-align: left; vertical-align: middle; }
  .linkbtn { background: none; border: 0; padding: 0; color: #1a4fa0; cursor: pointer; font: inherit; text-align: left; font-weight: 600; }
  details.adv { margin-top: 10px; } details.adv summary { cursor: pointer; color: #555; font-size: 0.85rem; }
  .kv { font-size: 0.8rem; border-collapse: collapse; } .kv td { padding: 2px 10px 2px 0; vertical-align: top; }
  #busy { display: none; position: fixed; inset: 0; background: #0008; color: #fff; z-index: 9; align-items: center; justify-content: center; font-size: 1.1rem; text-align: center; }
  .hint { font-size: 0.78rem; color: #777; margin-top: 2px; }
</style>"""

BUSY_SCRIPT = """<div id="busy"><div>영상을 만드는 중입니다…<br><small>보통 20~60초 걸립니다. 창을 닫지 마세요.</small></div></div>
<script>
document.addEventListener('submit', function (e) {
  var b = e.submitter;
  if (b && (b.value === 'preview' || b.value === 'final')) { document.getElementById('busy').style.display = 'flex'; }
});
</script>"""


def _page(title: str, body: str) -> bytes:
    from scripts.run_scout_dashboard import _page as dashboard_page  # 기존 Dashboard 공통 틀/CSS 재사용

    return dashboard_page(title, STYLE + body)


def _sources(config) -> list[dict]:
    sources = [(config.media_archive_path, config.shorts_scripts_path), *config.shorts_studio_extra_sources]
    return studio.list_sources(sources, studio.load_fact_checks(config.fact_check_manifest_path))


def _entry(config, content_id: str) -> dict | None:
    return next((e for e in _sources(config) if e["content_id"] == content_id), None)


def _store(config) -> studio.DraftStore:
    return studio.DraftStore(config.shorts_drafts_path, ROOT)


def _rel(path: Path) -> str:
    path = Path(path).resolve()
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _assets(config, limit: int = 60) -> list[str]:
    """고를 수 있는 로컬 이미지(asset 폴더, 최신 순). 인터넷에서 가져오지 않는다."""
    files = [p for d in config.shorts_asset_dirs if Path(d).exists() for p in Path(d).rglob("*")
             if p.is_file() and p.suffix.lower() in studio.IMAGE_SUFFIXES]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [_rel(p) for p in files[:limit]]


def _asset_url(path: str) -> str:
    return "/shorts-studio/asset?path=" + quote(path)


def _local(ts: str | None) -> str:
    """저장은 UTC, 화면은 이 PC 시간."""
    try:
        return datetime.fromisoformat(ts).astimezone().strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return ts or "-"


def _badge(state: str) -> str:
    label, bg, fg = STATE_LABELS.get(state, (state, "#eee", "#333"))
    return f'<span class="badge" style="background:{bg};color:{fg}">{escape(label)}</span>'


def _verdict_badge(verdict: str) -> str:
    bg, fg = VERDICT_COLORS.get(verdict, ("#eee", "#333"))
    return f'<span class="badge" style="background:{bg};color:{fg}">{escape(verdict)}</span>'


def _options(values, current) -> str:
    return "".join(f'<option value="{escape(str(v))}"{" selected" if str(v) == str(current or "") else ""}>{escape(str(label))}</option>'
                   for v, label in values)


def _latest_video(previews: list[dict], version: int) -> dict | None:
    """현재 버전의 최종 > 현재 버전 미리보기 > 이전 버전 영상 순."""
    usable = [p for p in previews if p.get("output_path") and Path(p["output_path"]).exists() and p["status"] in ("success", "skipped")]
    for pick in (lambda p: p["draft_version"] == version and p.get("mode") == "final", lambda p: p["draft_version"] == version, lambda p: True):
        found = [p for p in usable if pick(p)]
        if found:
            return found[-1]
    return None


# ---- 목록 -------------------------------------------------------------------------------------

FILTERS = [("", "전체"), ("DRAFT", "Draft"), ("EDITED", "Edited"), ("PREVIEW_READY", "Preview Ready"), ("RENDERED", "Rendered"),
           ("APPROVED", "Approved"), ("BLOCKED", "Blocked"), ("NO_DRAFT", "Draft 없음"), ("LOCKED", "Superseded")]


def list_rows(config) -> list[dict]:
    store = _store(config)
    drafts = {d["draft_id"]: d for d in store.list()}
    rows = []
    for e in _sources(config):
        draft = drafts.get(f"draft-{e['content_id']}")
        previews = store.previews(draft["draft_id"]) if draft else []
        state = "LOCKED" if studio.is_superseded(e) else studio.draft_state(draft, previews, store.approvals(draft["draft_id"]) if draft else [])
        video = _latest_video(previews, draft["draft_version"]) if draft else None
        rows.append({"entry": e, "draft": draft, "state": state, "video": video,
                     "title": (draft or {}).get("document", {}).get("title") or e["title"],
                     "category": ((draft or {}).get("meta") or {}).get("category", ""),
                     "updated": (draft or {}).get("updated_at", "")})
    return rows


def render_list_html(rows: list[dict], state: str = "", q: str = "", category: str = "") -> str:
    counts = {k: sum(r["state"] == k for r in rows) for k, _ in FILTERS if k}
    shown = [r for r in rows if (not state or r["state"] == state)
             and (not q or q.lower() in (r["title"] + " " + r["entry"]["content_id"]).lower())
             and (not category or r["category"] == category)]
    links = "".join(
        f'<a class="filter-link{" active" if k == state else ""}" href="/shorts-studio?state={k}&q={quote(q)}&category={quote(category)}">'
        f'{escape(label)} {len(rows) if not k else counts.get(k, 0)}</a>' for k, label in FILTERS)
    cats = sorted({r["category"] for r in rows if r["category"]} | set(studio.CATEGORIES))
    body_rows = []
    for r in shown:
        e, d = r["entry"], r["draft"]
        locked = r["state"] == "LOCKED"
        open_btn = ("" if locked else
                    f'<form method="post" action="/shorts-studio/open"><input type="hidden" name="content_id" value="{escape(e["content_id"])}">'
                    f'<button class="linkbtn" type="submit">{escape(r["title"])}</button></form>')
        title_html = open_btn or f'<span style="color:#888">{escape(r["title"])}</span>'
        video = "▶ 있음" if r["video"] else "-"
        body_rows.append(f"""<tr><td>{title_html}<div class="hint">{escape(e['content_id'])}</div></td>
<td>{escape(r['category'] or '-')}</td><td>{_badge(r['state'])}</td>
<td>{f"v{d['draft_version']}" if d else '-'}</td><td>{escape(_local(r['updated']))}</td>
<td>{video}</td><td>{escape(e.get('review_status') or '-')}{' · 대체됨' if locked else ''}</td>
<td>{escape(e.get('fact_check') or '-')}</td><td class="hint">{escape((e.get('generation_id') or '-')[-12:])}</td></tr>""")
    return f"""<div class="studio-wrap studio">
<a class="back" href="/">&larr; Dashboard</a>
<h1>🎬 SHORTS STUDIO</h1>
<div class="sub">콘텐츠를 누르면 편집 화면이 열립니다. 원본(Production)은 바뀌지 않고, 고친 내용은 Draft로 따로 저장됩니다.</div>
<div class="filters"><div class="filter-row">{links}</div>
<form method="get" action="/shorts-studio" class="row" style="max-width:640px">
<input type="hidden" name="state" value="{escape(state)}">
<div><input type="text" name="q" value="{escape(q)}" placeholder="제목 검색"></div>
<div><select name="category">{_options([("", "모든 분야")] + [(c, c) for c in cats], category)}</select></div>
<div style="flex:0 0 auto"><button class="btn" type="submit">검색</button></div></form></div>
<table class="list-table"><tr><th>제목</th><th>분야</th><th>상태</th><th>버전</th><th>마지막 수정</th><th>영상</th><th>원본 상태</th><th>fact-check</th><th>generation</th></tr>
{"".join(body_rows) if body_rows else '<tr><td colspan="9">조건에 맞는 콘텐츠가 없습니다.</td></tr>'}
</table></div>"""


# ---- 편집 화면 ------------------------------------------------------------------------------------

def _xy(position) -> tuple[float, float]:
    if isinstance(position, str):
        return NAMED_POSITIONS.get(position, (0.5, 0.5))
    if isinstance(position, dict):
        position = (position.get("x", 0.5), position.get("y", 0.5))
    try:
        return float(position[0]), float(position[1])
    except (TypeError, ValueError, IndexError):
        return 0.5, 0.5


def _image_html(i: int, image: dict, assets: list[str], layout: str) -> str:
    p = f"s{i}_"
    path = image.get("path", "")
    resolved = (Path(path) if Path(path).is_absolute() else ROOT / path) if path else None
    if not path:
        current = '<div class="hint">이미지 없음' + (" — 이 레이아웃은 이미지 칸이 비어 보입니다." if layout != "text_focus" else "") + "</div>"
    elif resolved.is_file():
        current = f'<div class="current-img"><img alt="현재 이미지" src="{_asset_url(path)}"><div class="hint">{escape(Path(path).name)}</div></div>'
    else:
        current = f'<div class="item BLOCKED">ASSET_MISSING — {escape(studio.describe("ASSET_MISSING"))}<br><span class="code">{escape(path)}</span></div>'
    choices = list(dict.fromkeys(([path] if path and resolved.is_file() else []) + assets))
    gallery = [f'<label><input type="radio" name="{p}image_path" value=""{" checked" if not path else ""}><span class="none">이미지 없음</span></label>']
    gallery += [f'<label><input type="radio" name="{p}image_path" value="{escape(a)}"{" checked" if a == path else ""}>'
                f'<img loading="lazy" alt="" src="{_asset_url(a)}">{escape(Path(a).name[:24])}</label>' for a in choices]
    if path and not resolved.is_file():  # 없는 파일도 선택 상태를 유지해 저장 시 조용히 사라지지 않게
        gallery.append(f'<label><input type="radio" name="{p}image_path" value="{escape(path)}" checked><span class="none">없는 파일</span></label>')
    x, y = _xy(image.get("position", "center"))
    grid = "".join(f'<label title="{v}"><input type="radio" name="{p}image_position" value="{v}"'
                   f'{" checked" if (abs(float(v.split(",")[0]) - x) < 0.01 and abs(float(v.split(",")[1]) - y) < 0.01) else ""}><span>{a}</span></label>'
                   for v, a in GRID)
    fits = "".join(f'<label><input type="radio" name="{p}image_fit" value="{v}"{" checked" if (image.get("fit", "") == v) else ""}> {escape(t)}</label>'
                   for v, t in FIT_LABELS.items() if v != "crop")
    return f"""<label class="f">이미지</label>{current}
<details{" open" if (path and not resolved.is_file()) else ""}><summary class="btn mini" style="display:inline-block;margin-top:6px">이미지 바꾸기 / 빼기</summary>
<div class="gallery">{"".join(gallery)}</div>
<label class="f">내 컴퓨터에서 새 이미지 올리기</label><input type="file" name="{p}image_upload" accept="image/png,image/jpeg,image/webp">
<div class="hint">PNG/JPEG/WEBP, 320px 이상. 저장하면 이 장면에 들어갑니다.</div></details>
<div class="row"><div><label class="f">맞춤</label><div class="radios">{fits}</div></div>
<div style="flex:0 0 auto"><label class="f">보여줄 부분(기준점)</label><div class="pgrid">{grid}</div></div></div>
<details class="adv"><summary>고급: 이미지 경로 직접 입력</summary><input type="text" name="{p}image_custom" value="" placeholder="{escape(path or 'data/shorts_assets/…png')}"></details>"""


def _scene_html(i: int, n: int, scene: dict, timing: dict | None, frame: dict | None, assets: list[str], layouts: list[str],
                transitions: list[str], issues: list[dict]) -> str:
    p = f"s{i}_"
    image = scene.get("image") if "image" in scene else scene.get("media")
    image = {"path": image} if isinstance(image, str) else (image or {})
    source = scene.get("source")
    source_label, source_value = (source.get("label", ""), source.get("value", "")) if isinstance(source, dict) else ("", source or "")
    role = "Hook" if i == 0 else ("마무리" if i == n - 1 and n > 1 else "내용")
    auto = f"자동 ({timing['duration']}초)" if timing else "자동"
    duration = scene.get("duration")
    layout = scene.get("layout", "text_focus")
    layout_opts = "".join(f'<label><input type="radio" name="{p}layout" value="{escape(l)}"{" checked" if l == layout else ""}> {escape(LAYOUT_LABELS.get(l, l))}</label>'
                          for l in layouts)
    thumb = f'<img src="/shorts-studio/{{draft}}/frame/{escape(frame["file"])}" style="width:72px;border-radius:6px;border:1px solid #ddd">' if frame else ""
    ops = "".join(f'<button class="btn mini{" ghost" if op == "delete" else ""}" type="submit" name="scene_op" value="{op}:{i}"{dis}>{label}</button>'
                  for op, label, dis in (("up", "↑ 위로", " disabled" if i == 0 else ""), ("down", "↓ 아래로", " disabled" if i == n - 1 else ""),
                                         ("duplicate", "복제", ""), ("delete", "삭제", " disabled" if n == 1 else "")))
    headline_label = "Hook 문구(헤드라인) — 첫 화면에서 시선을 잡는 한 줄" if i == 0 else "헤드라인"
    problems = "".join(f'<div class="item {escape(it["level"])}">{escape(it["text"])}</div>' for it in issues)
    return f"""<div class="card" id="scene-{i}"><div class="scene-head">{thumb}<b>Frame {i + 1} · {role}</b>{ops}</div>
{problems}
<div class="section-title">내용</div>
<label class="f">{headline_label}</label><input type="text" name="{p}headline" value="{escape(scene.get('headline', ''))}">
<label class="f">본문 (빈 줄 = 문단 나눔)</label><textarea name="{p}body" rows="4">{escape(scene.get('body', ''))}</textarea>
<div class="row">
 <div><label class="f">강조 문구 (한 줄에 하나, 본문/헤드라인 안의 말)</label><textarea name="{p}emphasis" rows="2">{escape(chr(10).join(scene.get('emphasis') or []))}</textarea></div>
 <div><label class="f">하단 자막 (한 줄)</label><input type="text" name="{p}subtitle" value="{escape(scene.get('subtitle', ''))}"></div>
</div>
<div class="row">
 <div style="flex:0 1 140px"><label class="f">출처 머리말</label><input type="text" name="{p}source_label" value="{escape(source_label)}" placeholder="출처"></div>
 <div><label class="f">출처 (BBC, Reuters, 책 제목, 링크 …)</label><input type="text" name="{p}source_value" value="{escape(source_value)}" placeholder="없으면 비워 두세요"></div>
</div>
<div class="section-title">디자인</div>
<label class="f">레이아웃</label><div class="radios">{layout_opts}</div>
{_image_html(i, image, assets, layout)}
<div class="section-title">타이밍</div>
<div class="row">
 <div><label class="f">장면 길이(초)</label><input type="text" inputmode="decimal" name="{p}duration" value="{escape('' if duration is None else f'{duration:g}' if isinstance(duration, (int, float)) else str(duration))}" placeholder="{escape(auto)}">
 <div class="hint">비우면 글 길이에 맞춰 자동. 지금: {escape(str(timing['start']) + '초부터 ' + str(timing['duration']) + '초') if timing else '-'}</div></div>
 <div><label class="f">들어오는 전환</label><select name="{p}transition">{_options([(t, TRANSITION_LABELS.get(t, t)) for t in [""] + transitions], scene.get('transition', ''))}</select></div>
</div></div>"""


def _gate_html(report: dict) -> str:
    # 엔진의 원문 메시지(좌표 등)는 마우스를 올렸을 때만 - 화면에는 사람 말만
    items = "".join(f'<div class="item {escape(it["level"])}" title="{escape(it.get("detail") or "")}"><b>{escape(it["level"])}</b> {escape(it["text"])}</div>'
                    for it in report.get("items", []))
    return f'<div class="card"><b>품질 검사</b> {_verdict_badge(report.get("verdict", "BLOCKED"))}{items or "<div class=hint>문제 없음</div>"}</div>'


def _video_html(record: dict | None, draft: dict) -> str:
    if not record:
        return '<div class="hint">아직 영상이 없습니다. 아래 "미리보기 렌더"를 누르세요.</div>'
    name = Path(record["output_path"]).name
    which = "최종본" if record.get("mode") == "final" else "미리보기"
    old = "" if record["draft_version"] == draft["draft_version"] else f' <span class="badge" style="background:#fff4de;color:#6b4a00">v{record["draft_version"]} 영상 — 지금 버전과 다름</span>'
    media = record.get("media") or {}
    return (f'<video controls preload="metadata" src="/shorts-studio/{escape(draft["draft_id"])}/file/{escape(name)}"></video>'
            f'<div class="hint">{which} v{record["draft_version"]} · {record.get("duration")}초 · {media.get("width")}x{media.get("height")} · '
            f'{media.get("video_codec")}/{media.get("audio_codec")} · 게이트 {escape(str(record.get("quality") or record["status"]))}{old}</div>')


def render_editor_html(draft: dict, document: dict, meta: dict, report: dict, *, previews: list[dict], versions: list[dict],
                       approvals: list[dict], assets: list[str], frames: dict, state: str, problems: list[str],
                       approve_blockers: list[str], notice: str | None = None, error: str | None = None) -> str:
    draft_id = draft["draft_id"]
    fields = editable_fields(document.get("template") if isinstance(document.get("template"), str) else "default")
    layouts, transitions = fields["scene"]["layout"], fields["scene"]["transition"]
    progress = document.get("progress")
    progress = {"enabled": progress} if isinstance(progress, bool) else (progress or {})
    audio = document.get("audio") or {}
    on_off = [("on", "켜기"), ("off", "끄기")]
    timings = {s["index"]: s for s in report.get("scenes", [])}
    frame_by_index = {f["index"]: f for f in frames.get("frames", [])}
    scenes = [s for s in document.get("scenes") or [] if isinstance(s, dict)]
    scene_cards = "".join(_scene_html(i, len(scenes), s, timings.get(i), frame_by_index.get(i), assets, layouts, transitions,
                                      [it for it in report.get("items", []) if it["scene"] == i])
                          for i, s in enumerate(scenes)).replace("{draft}", escape(draft_id))
    strip = "".join(f'<a href="#scene-{f["index"]}"><img src="/shorts-studio/{escape(draft_id)}/frame/{escape(f["file"])}" alt="">'
                    f'{"엔딩" if f["end_card"] else f"Frame {f["index"] + 1}"} · {f["duration"]}초</a>'
                    for f in frames.get("frames", []))
    if frames.get("error"):
        strip = f'<div class="item BLOCKED">화면을 그릴 수 없습니다: {escape(studio.describe(frames["error"]))}</div>'
    video = _latest_video(previews, draft["draft_version"])
    locked = bool(problems) or report.get("verdict") == "BLOCKED"
    disabled = " disabled" if locked else ""
    why_locked = ('<div class="item BLOCKED">품질 검사 BLOCKED 항목을 먼저 고쳐야 렌더할 수 있습니다(아래 빨간 항목).</div>'
                  if report.get("verdict") == "BLOCKED" and not problems else "")
    approved = [a for a in approvals if a.get("draft_version") == draft["draft_version"] and not a.get("revoked")]
    approve_html = (
        f'<div class="item" style="background:#dff3e3;color:#1a5c3a">✔ v{draft["draft_version"]} 승인됨 ({escape(_local(approved[-1]["approved_at"]))}, {escape(approved[-1]["approved_by"])})</div>'
        f'<form method="post" action="/shorts-studio/{escape(draft_id)}/revoke"><button class="btn ghost mini" type="submit">승인 취소</button></form>'
        if approved else
        f'<form method="post" action="/shorts-studio/{escape(draft_id)}/approve"><button class="btn primary" type="submit"{" disabled" if approve_blockers else ""}>이 최종 영상 승인</button></form>'
        + (f'<div class="hint">승인 조건: {escape(" / ".join(studio.describe(c) for c in approve_blockers))}</div>' if approve_blockers else ""))
    banners = (f'<div class="banner">{escape(notice)}</div>' if notice else "") + (f'<div class="error">{escape(error)}</div>' if error else "")
    banners += "".join(f'<div class="error">{escape(studio.describe(c))}</div>' for c in problems)
    version_rows = "".join(
        f"""<tr><td>v{v['draft_version']}</td><td>{escape(_local(v.get('updated_at')))}</td><td>{escape(v.get('note') or '')}</td><td>{escape((v.get('title') or '')[:30])}</td>
<td>{'지금' if v['draft_version'] == draft['draft_version'] else f'<form method="post" action="/shorts-studio/{escape(draft_id)}/reset"><input type="hidden" name="target" value="v{v["draft_version"]}"><button class="btn mini" type="submit">이 버전으로 되돌리기</button></form>'}</td></tr>"""
        for v in reversed(versions))
    lin = (video or {}).get("lineage") or {}
    adv_rows = [("draft_id", draft_id), ("content_id", draft["content_id"]), ("generation_id", draft.get("generation_id")),
                ("draft version / parent", f"v{draft['draft_version']} / {draft.get('parent_version')}"),
                ("원본 ShortsScript", draft["base"].get("script_path")), ("원본 sha256", draft["base_content_sha256"]),
                ("문서 sha256", draft.get("document_sha256")), ("원본 review_status", draft["base"].get("review_status")),
                ("영상 render key", (video or {}).get("render_key")), ("영상 sha256", (video or {}).get("sha256")),
                ("template sha256", lin.get("template_sha256")), ("asset sha256", json.dumps(lin.get("asset_sha256") or {}, ensure_ascii=False)),
                ("영상 파일", (video or {}).get("output_path"))]
    cats = list(dict.fromkeys(([meta.get("category")] if meta.get("category") else []) + list(studio.CATEGORIES)))
    return f"""<div class="studio-wrap studio">
<a class="back" href="/shorts-studio">&larr; SHORTS STUDIO 목록</a>
<h1>{escape(document.get('title', '').replace(chr(10), ' '))} {_badge(state)} <span class="badge" style="background:#eee">v{draft['draft_version']}</span></h1>
<div class="sub">원본(Production)은 바뀌지 않습니다. 저장할 때마다 새 버전이 쌓이고 언제든 되돌릴 수 있습니다.</div>
{banners}
<div class="studio-grid">
<div class="sticky">
 <div class="card"><b>동작</b>
  <div class="actions" style="margin:8px 0">
   <button class="btn" type="submit" form="editor" name="action" value="save">저장 (Save Draft)</button>
   <button class="btn" type="submit" form="editor" name="action" value="preview"{disabled}>미리보기 렌더 (Render Preview)</button>
   <button class="btn primary" type="submit" form="editor" name="action" value="final"{disabled}>최종 렌더</button>
  </div>
  {why_locked}<div class="hint">미리보기 = 빠른 압축, 최종 = 게시용 화질. 두 영상은 같은 화면 배치/소리/검사 규칙을 씁니다.</div>
  <div style="margin-top:8px">{approve_html}</div>
 </div>
 {_gate_html(report)}
 <div class="card"><b>영상</b>{_video_html(video, draft)}</div>
 <div class="card"><b>장면 화면</b> <span class="hint">(최종 영상과 같은 렌더러로 그린 정지 화면 · 전체 {frames.get('total', report.get('total'))}초)</span><div class="frames">{strip}</div></div>
</div>
<div>
<form id="editor" method="post" action="/shorts-studio/{escape(draft_id)}/save" enctype="multipart/form-data" style="display:block">
<input type="hidden" name="expected_version" value="{draft['draft_version']}">
<div class="card"><b>기본 정보</b>
<label class="f">제목 (영상 내내 위에 보입니다. 줄바꿈 가능)</label><textarea name="title" rows="2">{escape(document.get('title', ''))}</textarea>
<div class="row">
 <div><label class="f">분야</label><select name="meta_category">{_options([("", "(선택 안 함)")] + [(c, c) for c in cats], meta.get('category', ''))}</select></div>
 <div><label class="f">주제(자유)</label><input type="text" name="meta_topic" value="{escape(meta.get('topic', ''))}"></div>
 <div><label class="f">언어</label><select name="meta_language">{_options(list(studio.LANGUAGES.items()), meta.get('language', 'ko'))}</select></div>
</div>
<div class="hint">content {escape(draft['content_id'])} · generation {escape(draft.get('generation_id') or '-')} · v{draft['draft_version']}</div>
</div>
{scene_cards}
<div class="card"><b>엔딩 화면 (자동으로 마지막에 붙습니다)</b>
<div class="row">
 <div><label class="f">마지막 CTA 문구</label><input type="text" name="cta" value="{escape(document.get('cta') or '')}" placeholder="기본: 다음 편에서 또 만나요"></div>
 <div><label class="f">채널 이름</label><input type="text" name="brand" value="{escape(document.get('brand') if isinstance(document.get('brand'), str) else '')}" placeholder="기본: 티몽의 지혜"></div>
</div></div>
<div class="card"><b>영상 설정</b>
<div class="row">
 <div><label class="f">진행 표시(Progress)</label><select name="progress_enabled">{_options(on_off, 'off' if progress.get('enabled') is False else 'on')}</select></div>
 <div><label class="f">진행 표시 위치</label><select name="progress_position">{_options([('', '기본(아래)'), ('footer', '아래'), ('top', '위')], progress.get('position', ''))}</select></div>
</div>
<div class="row">
 <div><label class="f">배경음악</label><select name="audio_enabled">{_options(on_off, 'off' if audio.get('enabled') is False else 'on')}</select></div>
 <div><label class="f">음악 분위기</label><select name="audio_background">{_options(list(MUSIC_LABELS.items()), audio.get('background', ''))}</select></div>
 <div><label class="f">음량 (0~2, 비우면 기본 1)</label><input type="text" inputmode="decimal" name="audio_volume" value="{escape('' if audio.get('volume') is None else f"{audio.get('volume'):g}" if isinstance(audio.get('volume'), (int, float)) else str(audio.get('volume')))}"></div>
</div></div>
<div class="actions"><button class="btn" type="submit" name="action" value="save">저장 (Save Draft)</button>
<button class="btn" type="submit" name="action" value="preview"{disabled}>미리보기 렌더 (Render Preview)</button></div>
</form>
<div class="card" style="margin-top:12px"><b>되돌리기 / 버전</b>
<div class="actions" style="margin:8px 0">
<form method="post" action="/shorts-studio/{escape(draft_id)}/reset"><input type="hidden" name="target" value="base"><button class="btn ghost" type="submit">원본 Production Content로 초기화</button></form>
<a class="btn" href="/shorts-studio/{escape(draft_id)}">저장 안 한 입력 버리기</a>
</div>
<table class="list-table">{version_rows}</table>
<div class="hint">초기화/되돌리기도 새 버전으로 쌓입니다. 이전 버전은 지워지지 않습니다.</div>
<details class="adv"><summary>고급 정보 (개발/점검용)</summary><table class="kv">
{"".join(f'<tr><td>{escape(k)}</td><td><span class="code">{escape(str(v))}</span></td></tr>' for k, v in adv_rows if v not in (None, "", "{}"))}
</table></details>
</div>
</div></div></div>{BUSY_SCRIPT}"""


# ---- 요청 처리 ------------------------------------------------------------------------------------

def parse_body(body: bytes, content_type: str) -> tuple[dict, dict]:
    """urlencoded 또는 multipart -> (form: {name: [str]}, files: {name: (filename, bytes)}). 빈 칸도 유지한다."""
    if content_type.startswith("multipart/form-data"):
        msg = email.message_from_bytes(b"Content-Type: " + content_type.encode("latin-1") + b"\r\n\r\n" + body, policy=email.policy.HTTP)
        form, files = {}, {}
        for part in msg.iter_parts():
            name = part.get_param("name", header="content-disposition")
            data = part.get_payload(decode=True) or b""
            if part.get_filename() is not None:
                if data:
                    files[name] = (part.get_filename(), data)
            else:
                form.setdefault(name, []).append(data.decode("utf-8"))
        return form, files
    return parse_qs(body.decode("utf-8"), keep_blank_values=True), {}


NOTICES = {"saved": "저장했습니다(새 버전).", "unchanged": "바뀐 내용이 없어 새 버전을 만들지 않았습니다.",
           "preview": "미리보기 영상을 만들었습니다.", "final": "최종 영상을 만들었습니다.", "reset": "되돌렸습니다(새 버전).",
           "approved": "승인했습니다(Draft 기록 - 원본/게시에는 아직 반영되지 않습니다).", "revoked": "승인을 취소했습니다."}


def handle(config, method: str, path: str, query: dict, body: bytes = b"", content_type: str = ""):
    store = _store(config)
    if method == "GET" and path == "/shorts-studio":
        get = lambda k: (query.get(k) or [""])[0]  # noqa: E731
        return "html", 200, _page("Shorts Studio", render_list_html(list_rows(config), get("state"), get("q"), get("category")))

    if method == "GET" and path == "/shorts-studio/asset":
        raw = (query.get("path") or [""])[0]
        target = (Path(raw) if Path(raw).is_absolute() else ROOT / raw).resolve()
        roots = [ROOT.resolve(), *(Path(d).resolve() for d in config.shorts_asset_dirs)]
        if target.suffix.lower() in studio.IMAGE_SUFFIXES and target.is_file() and any(target.is_relative_to(r) for r in roots):
            kind = {".png": "image/png", ".webp": "image/webp"}.get(target.suffix.lower(), "image/jpeg")
            return "file", kind, target.read_bytes()
        return "html", 404, _page("없음", "<p>이미지를 찾을 수 없습니다.</p>")

    form, files = parse_body(body, content_type) if method == "POST" else ({}, {})
    if method == "POST" and path == "/shorts-studio/open":
        content_id = (form.get("content_id") or [""])[0]
        entry = _entry(config, content_id)
        try:
            if entry is None:
                raise studio.DraftError("SOURCE_NOT_FOUND", content_id)
            return "redirect", f"/shorts-studio/{store.open_draft(entry)['draft_id']}"
        except studio.DraftError as error:
            return "html", 409, _page("열 수 없음", f'<a class="back" href="/shorts-studio">&larr; 목록</a><div class="error">[{escape(error.code)}] {escape(studio.describe(error.code))}</div>')

    parts = path[len("/shorts-studio/"):].split("/")
    draft_id = unquote(parts[0])
    try:
        draft = store.load(draft_id)
    except studio.DraftError as error:
        return "html", 404, _page("Draft 없음", f'<a class="back" href="/shorts-studio">&larr; 목록</a><div class="error">{escape(error.message)}</div>')
    entry = _entry(config, draft["content_id"])

    def problems() -> list[str]:
        return studio.guard(draft, entry)

    def editor(status: int = 200, document: dict | None = None, meta: dict | None = None, notice: str | None = None, error: str | None = None):
        unsaved = document is not None
        document = draft["document"] if document is None else document
        report = studio.check(document, store.base_dir)
        previews, approvals = store.previews(draft_id), store.approvals(draft_id)
        frames = {"frames": []} if unsaved else studio.scene_frames(store, draft_id)
        warn = [c for c in [studio.base_drift(draft, entry)] if c and c != "SOURCE_NOT_FOUND"]
        body_html = render_editor_html(
            draft, document, draft.get("meta", {}) if meta is None else meta, report, previews=previews, versions=store.versions(draft_id),
            approvals=approvals, assets=_assets(config), frames=frames,
            state=studio.draft_state(draft, previews, approvals), problems=problems() + warn,
            approve_blockers=studio.approval_blockers(store, draft_id, entry), notice=notice, error=error)
        return "html", status, _page("Shorts Studio", body_html)

    if method == "GET" and len(parts) == 1:
        return editor(notice=NOTICES.get((query.get("notice") or [""])[0]))

    if method == "GET" and len(parts) == 3 and parts[1] == "file":
        name = unquote(parts[2])
        target = config.shorts_studio_out_path / draft_id / name
        if re.fullmatch(r"[A-Za-z0-9._-]+\.mp4", name) and target.is_file():
            return "file", "video/mp4", target.read_bytes()
        return "html", 404, _page("없음", "<p>파일을 찾을 수 없습니다.</p>")

    if method == "GET" and len(parts) == 4 and parts[1] == "frame":
        key, name = unquote(parts[2]), unquote(parts[3])
        target = config.shorts_drafts_path / draft_id / "frames" / key / name
        if re.fullmatch(r"[0-9a-f]{16}", key) and re.fullmatch(r"scene\d{2}\.png", name) and target.is_file():
            return "file", "image/png", target.read_bytes()
        return "html", 404, _page("없음", "<p>화면을 찾을 수 없습니다.</p>")

    if method == "POST" and len(parts) == 2 and parts[1] == "save":
        try:
            for key, (filename, data) in files.items():  # 새 이미지 업로드 -> asset 폴더 -> 그 장면의 이미지로
                m = re.fullmatch(r"s(\d+)_image_upload", key or "")
                if m:
                    saved = studio.store_asset(data, filename, config.shorts_asset_dirs[0])
                    form[f"s{m.group(1)}_image_custom"] = [_rel(saved)]
        except studio.DraftError as error:
            return editor(400, error=f"이미지를 올리지 못했습니다 [{error.code}] {studio.describe(error.code)} — {error.message}")
        document = studio.apply_form(draft["document"], form)
        meta = studio.apply_meta(draft.get("meta", {}), form)
        try:
            expected = int((form.get("expected_version") or [""])[0])
        except ValueError:
            expected = None
        try:
            _, _, saved_new = store.save(draft_id, document, expected_version=expected, meta=meta)
        except studio.DraftError as error:
            # 입력한 값을 잃지 않도록 저장 안 된 문서를 그대로 다시 보여준다.
            return editor(400, document, meta, error=f"저장하지 않았습니다 [{error.code}] {studio.describe(error.code)} — {error.message}")
        action = (form.get("action") or ["save"])[0]
        if action in ("preview", "final"):
            studio.preview(store, draft_id, config.shorts_studio_out_path, ffmpeg=config.ffmpeg, mode=action, entry=entry)
            return "redirect", f"/shorts-studio/{draft_id}?notice={action}"
        anchor = ""
        op, _, index = (form.get("scene_op") or [""])[0].partition(":")
        if index.isdigit():  # 복제/이동한 프레임으로 바로 이동
            anchor = f"#scene-{max(0, int(index) + {'duplicate': 1, 'down': 1, 'up': -1, 'delete': -1}.get(op, 0))}"
        return "redirect", f"/shorts-studio/{draft_id}?notice={'saved' if saved_new else 'unchanged'}{anchor}"

    if method == "POST" and len(parts) == 2 and parts[1] == "reset":
        target = (form.get("target") or [""])[0]
        try:
            if target == "base":
                if entry is None:
                    raise studio.DraftError("SOURCE_NOT_FOUND")
                store.reset_to_base(draft_id, entry)
            elif re.fullmatch(r"v\d+", target):
                store.revert(draft_id, int(target[1:]))
            else:
                raise studio.DraftError("DRAFT_NOT_FOUND", f"잘못된 대상: {target!r}")
        except studio.DraftError as error:
            return editor(400, error=f"[{error.code}] {error.message}")
        return "redirect", f"/shorts-studio/{draft_id}?notice=reset"

    if method == "POST" and len(parts) == 2 and parts[1] == "approve":
        try:
            studio.approve(store, draft_id, entry)
        except studio.DraftError as error:
            return editor(400, error=f"승인하지 않았습니다 [{error.code}] {studio.describe(error.code)} — {error.message}")
        return "redirect", f"/shorts-studio/{draft_id}?notice=approved"

    if method == "POST" and len(parts) == 2 and parts[1] == "revoke":
        studio.revoke_approval(store, draft_id)
        return "redirect", f"/shorts-studio/{draft_id}?notice=revoked"

    return "html", 404, _page("페이지 없음", "<p>페이지를 찾을 수 없습니다.</p>")
