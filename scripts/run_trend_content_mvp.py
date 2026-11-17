#!/usr/bin/env python3
"""Local web MVP: discover current trends with Perplexity and preview traffic content."""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
from dataclasses import asdict
from datetime import datetime
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import tempfile
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from blog_importer.models import utc_now
from content_engine.generator import generate_content_bundle
from content_engine.publishing_queue import PublishingQueue, queue_dashboard
from scripts.run_publishing_queue import start_scheduler
from tak_brain.models import KnowledgeRecord
from tak_scout.perplexity_research import PerplexityResearchProvider
from tak_scout.trend_discovery import TrendDiscovery, TrendItem, discover_trends

KST = ZoneInfo("Asia/Seoul")
def _resolve_writable_data_dir(configured: Path) -> tuple[Path, bool]:
    """Use the configured data directory when writable; otherwise use ephemeral /tmp."""
    candidates = [(configured, False)]
    fallback = Path(tempfile.gettempdir()) / "tak-auto-data"
    if fallback != configured:
        candidates.append((fallback, True))
    for candidate, is_fallback in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(prefix=".tak-auto-write-test-", dir=candidate, delete=True):
                pass
            return candidate, is_fallback
        except OSError:
            continue
    # Preserve the original configured path so the first write returns a clear error.
    return configured, False


CONFIGURED_DATA_DIR = Path(os.getenv("TAK_AUTO_DATA_DIR", str(ROOT / "data"))).expanduser()
DATA_DIR, USING_EPHEMERAL_STORAGE = _resolve_writable_data_dir(CONFIGURED_DATA_DIR)
TREND_PATH = DATA_DIR / "tak_auto_live_trends.json"
PREVIEW_PATH = DATA_DIR / "tak_auto_content_previews.json"
QUEUE_PATH = DATA_DIR / "tak_auto_publishing_queue.json"


def _basic_auth_valid(header: str, username: str, password: str) -> bool:
    """Constant-time Basic Auth check; never logs credentials."""
    if not username or not password or not header.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(header[6:], validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return False
    supplied_user, separator, supplied_password = decoded.partition(":")
    return bool(separator) and hmac.compare_digest(supplied_user, username) and hmac.compare_digest(supplied_password, password)


def _same_origin(origin: str, host: str, forwarded_proto: str) -> bool:
    """Reject cross-origin form submissions, including behind HTTPS proxies."""
    if not origin or not host:
        return False
    parsed = urlparse(origin)
    expected_scheme = (forwarded_proto or "https").split(",")[0].strip().lower()
    return parsed.scheme.lower() == expected_scheme and parsed.netloc.lower() == host.lower()


def _read_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _build_content_prompt(item: dict, trend_report: dict) -> str:
    sources = item.get("source_urls") or trend_report.get("citations") or []
    facts = {
        "keyword": item.get("keyword"),
        "category": item.get("category"),
        "summary": item.get("summary"),
        "why_now": item.get("why_now"),
        "audience_question": item.get("audience_question"),
        "content_angle": item.get("content_angle"),
        "key_points": item.get("key_points", []),
        "verified_source_urls": sources,
        "research_date": trend_report.get("researched_at"),
    }
    return f"""당신은 한국어 검색 유입과 영상 시청 지속시간을 설계하는 전문 콘텐츠 에디터입니다.
아래 Perplexity 트렌드 조사 자료만 사실의 출발점으로 삼아 게시 직전 검토가 가능한 콘텐츠 패키지를 작성하세요.

자료:
{json.dumps(facts, ensure_ascii=False, indent=2)}

작성 원칙:
- 독자의 검색 의도에 직접 답하고, 제목은 구체적이며 과장하지 마세요.
- 확인된 사실, 해석, 전망을 분리하고 불확실한 내용은 단정하지 마세요.
- 자료에 없는 숫자·통계·인용·사례·발언·URL을 만들지 마세요.
- 원문 출처 URL은 위 verified_source_urls만 사용하세요.
- 블로그는 검색 의도에 답하는 충분한 본문(한국어 1,200자 이상 목표), 소제목, 체크포인트, 요약, 자연스러운 다음 행동 CTA를 포함하세요.
- 쇼츠는 약 60초 분량으로 6~8개 장면을 구성하세요. 각 장면은 time, visual, caption, narration을 포함하고 첫 3초 후킹과 마지막 행동 유도를 포함하세요. 세로 9:16(1080x1920) 기준으로 화면 중앙 안전영역에 핵심 피사체와 자막을 배치하고, 자막은 한 화면 최대 2줄·짧은 문장으로 작성하며 화면 가장자리 잘림을 피하도록 visual에 구도를 구체적으로 지시하세요.
- Threads는 각각 독립적으로 읽혀도 되는 후킹 중심 글 2개를 만들고 각 본문은 500자 이내로 하세요.
- 같은 내용을 세 번 반복하지 말고 플랫폼별 문법에 맞게 재구성하세요.
- 결과는 아래 JSON 객체 하나로만 출력하세요. 코드펜스나 설명은 붙이지 마세요.
{{
  "blog": {{"title":"검색형 제목","meta_description":"검색 결과 설명","focus_keyword":"핵심 키워드","body":"Markdown 본문"}},
  "shorts": {{"title":"쇼츠 제목","duration_seconds":60,"hook":"첫 3초 후킹","scenes":[{{"time":"00-05초","visual":"9:16 화면 구도와 안전영역을 포함한 화면 구성","caption":"짧은 자막","narration":"내레이션"}}],"closing_cta":"마지막 행동 유도","youtube_description":"유튜브 설명란 문안","instagram_caption":"인스타그램 릴스 설명문","tiktok_caption":"틱톡 설명문","hashtags":["해시태그1","해시태그2"]}},
  "threads": [{{"title":"후킹 제목","body":"Threads 본문"}},{{"title":"후킹 제목","body":"Threads 본문"}}]
}}"""


def _parse_content_package(answer: str) -> dict:
    text = answer.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3].strip()
    start = text.find("{")
    if start < 0:
        raise ValueError("콘텐츠 응답에서 JSON 객체를 찾지 못했습니다.")
    try:
        package, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError as error:
        raise ValueError("콘텐츠 응답의 JSON 형식이 올바르지 않습니다.") from error
    if not isinstance(package, dict):
        raise ValueError("콘텐츠 패키지는 JSON 객체여야 합니다.")
    blog = package.get("blog")
    shorts = package.get("shorts")
    threads = package.get("threads")
    if not isinstance(blog, dict) or len(str(blog.get("body", "")).strip()) < 500:
        raise ValueError("블로그 본문이 없거나 500자 미만입니다. 다시 생성하세요.")
    if not isinstance(shorts, dict) or not isinstance(shorts.get("scenes"), list) or len(shorts["scenes"]) < 5:
        raise ValueError("쇼츠 장면 구성이 부족합니다. 최소 5개 장면이 필요합니다.")
    if not isinstance(threads, list) or len(threads) != 2:
        raise ValueError("Threads 초안은 정확히 2개가 필요합니다.")
    for post in threads:
        if not isinstance(post, dict) or not str(post.get("body", "")).strip() or len(str(post["body"])) > 500:
            raise ValueError("Threads 본문은 비어 있지 않고 500자 이하여야 합니다.")
    return package


def _make_preview(item: dict, trend_report: dict, provider=None) -> dict:
    urls = item.get("source_urls") or trend_report.get("citations") or []
    if not urls:
        raise ValueError("이 트렌드는 연결된 출처 URL이 없어 콘텐츠 초안을 만들 수 없습니다.")
    keyword = str(item.get("keyword") or "").strip()
    if not keyword:
        raise ValueError("키워드가 비어 있습니다.")
    points = [str(value).strip() for value in item.get("key_points", []) if str(value).strip()]
    points.extend([
        str(item.get("why_now") or ""),
        str(item.get("audience_question") or ""),
        str(item.get("content_angle") or ""),
    ])
    points = list(dict.fromkeys(value for value in points if len(value) >= 12))
    if len(points) < 3:
        raise ValueError("콘텐츠 생성에 필요한 독립 근거가 3개 미만입니다.")
    facts = "\n".join([
        f"트렌드 키워드: {keyword}",
        f"요약: {item.get('summary', '')}",
        f"지금 주목하는 이유: {item.get('why_now', '')}",
        f"독자 질문: {item.get('audience_question', '')}",
        f"콘텐츠 관점: {item.get('content_angle', '')}",
        *[f"확인할 핵심 사실: {point}" for point in points],
    ])
    knowledge = KnowledgeRecord(
        id="trend-preview-" + hashlib.sha256(keyword.encode("utf-8")).hexdigest()[:16],
        source_raw_id="trend-preview:" + keyword,
        source_url=urls[0],
        title=str(item.get("blog_title") or keyword),
        domain=str(item.get("category") or "기타"),
        knowledge_type="정보",
        lesson=facts,
        evidence=tuple(f"SOURCE: {url}" for url in urls),
        created_at=utc_now(),
        knowledge_review_status="approved",
        summary=str(item.get("summary") or facts)[:500],
        key_points=tuple(points),
        factual_information=facts,
        current_validity="Perplexity 조사 시점 기준. 발행 전 원문과 최신성 재검증 필요.",
        verification_required=True,
    )
    if provider is not None:
        result = provider.search(
            _build_content_prompt(item, trend_report),
            search_recency_filter="week",
        )
        package = _parse_content_package(result.answer)
        return {
            "keyword": keyword,
            "created_at": utc_now(),
            "status": "preview_only_not_approved",
            "warning": "Perplexity가 작성한 검토용 초안입니다. 원문 사실 확인과 사람의 승인을 거쳐야 게시할 수 있습니다.",
            "blog": package["blog"],
            "shorts": [{
                "title": package["shorts"].get("title", ""),
                "body": "\\n".join(
                    f"{scene.get('time', '')} | 화면: {scene.get('visual', '')} | "
                    f"자막: {scene.get('caption', '')} | 내레이션: {scene.get('narration', '')}"
                    for scene in package["shorts"]["scenes"]
                ) + "\\n마무리 CTA: " + str(package["shorts"].get("closing_cta", "")),
                "duration_seconds": package["shorts"].get("duration_seconds", 60),
                "hook": package["shorts"].get("hook", ""),
                "scenes": package["shorts"]["scenes"],
                "youtube_description": package["shorts"].get("youtube_description", ""),
                "instagram_caption": package["shorts"].get("instagram_caption", ""),
                "tiktok_caption": package["shorts"].get("tiktok_caption", ""),
                "hashtags": package["shorts"].get("hashtags", []),
            }],
            "threads": package["threads"],
            "source_urls": list(dict.fromkeys(urls + list(result.citations))),
            "content_model": result.model,
        }

    # Offline fallback is retained for deterministic tests and local template preview only.
    bundle = generate_content_bundle(knowledge)
    return {
        "keyword": keyword,
        "created_at": utc_now(),
        "status": "preview_only_not_approved",
        "warning": "검토용 미승인 미리보기입니다. 사실·인용 원문 확인과 사람의 승인을 거쳐야 게시할 수 있습니다.",
        "blog": asdict(bundle.blog) if bundle.blog else None,
        "shorts": [asdict(row) for row in bundle.shorts],
        "threads": [asdict(row) for row in bundle.threads],
        "source_urls": urls,
    }


def _page(report: dict | None, previews: list[dict], error: str = "", queue_snapshot: dict | None = None) -> str:
    error_html = f'<div class="error">{escape(error)}</div>' if error else ""
    if not report:
        report = {}
    trends = report.get("trends", [])
    cards = []
    for index, item in enumerate(trends):
        sources = " ".join(
            f'<a href="{escape(url, quote=True)}" target="_blank" rel="noopener">출처 {i}</a>'
            for i, url in enumerate(item.get("source_urls", []), 1)
        )
        cards.append(f"""
<article class="trend">
  <div class="meta">#{index + 1} · {escape(str(item.get('category', '기타')))}</div>
  <h3>{escape(str(item.get('keyword', '')))}</h3>
  <p>{escape(str(item.get('summary', '')))}</p>
  <p><b>왜 지금?</b> {escape(str(item.get('why_now', '')))}</p>
  <p><b>독자 질문</b> {escape(str(item.get('audience_question', '')))}</p>
  <p><b>콘텐츠 관점</b> {escape(str(item.get('content_angle', '')))}</p>
  <p class="hook">쇼츠 후킹: {escape(str(item.get('shorts_hook', '')))}</p>
  <p class="meta">{sources}</p>
  <form method="post" action="/generate"><input type="hidden" name="index" value="{index}">
    <button type="submit">이 키워드로 콘텐츠 패키지 생성</button></form>
</article>""")
    preview_cards = []
    for preview_index, preview in enumerate(previews):
        blog = preview.get("blog") or {}
        shorts = preview.get("shorts") or []
        threads = preview.get("threads") or []
        preview_cards.append(f"""
<section class="preview">
  <h2>{escape(str(preview.get('keyword', '')))} 콘텐츠 미리보기</h2>
  <p class="warning">{escape(str(preview.get('warning', '')))}</p>
  <h3>네이버 블로그 · {escape(str(blog.get('title', '')))}</h3>
  <button type="button" class="secondary copy" data-copy="blog-{len(preview_cards)}">블로그 원고 복사</button>
  <pre id="blog-{len(preview_cards)}">{escape(str(blog.get('body', '')))}</pre>
  <h3>유튜브 쇼츠 · {len(shorts)}편</h3>
  {"".join(f'<div class="draft"><b>{escape(str(row.get("title", "")))}</b><button type="button" class="secondary copy" data-copy="short-{len(preview_cards)}-{i}">쇼츠 대본 복사</button><pre id="short-{len(preview_cards)}-{i}">{escape(str(row.get("body", "")))}</pre></div>' for i, row in enumerate(shorts))}
  {"".join(f'<div class="draft"><b>{label}</b><button type="button" class="secondary copy" data-copy="caption-{len(preview_cards)}-{i}">문안 복사</button><pre id="caption-{len(preview_cards)}-{i}">{escape(str(shorts[i].get(field, "")))}</pre></div>' for i in range(len(shorts)) for label, field in [("YouTube 설명란", "youtube_description"), ("Instagram 릴스 문안", "instagram_caption"), ("TikTok 설명문", "tiktok_caption")])}
  {"".join(f'<p class="meta">해시태그: {escape(" ".join("#" + str(tag).lstrip("#") for tag in shorts[i].get("hashtags", [])))}</p>' for i in range(len(shorts)))}
  <h3>Threads · {len(threads)}편</h3>
  {"".join(f'<div class="draft"><b>{escape(str(row.get("title", "")))}</b><button type="button" class="secondary copy" data-copy="thread-{len(preview_cards)}-{i}">Threads 글 복사</button><pre id="thread-{len(preview_cards)}-{i}">{escape(str(row.get("body", "")))}</pre></div>' for i, row in enumerate(threads))}
  <p class="meta">{" ".join(f'<a href="{escape(url, quote=True)}" target="_blank" rel="noopener">원문 출처</a>' for url in preview.get("source_urls", []))}</p>
  <details><summary>플랫폼 게시 예약 및 승인</summary>
    <p class="warning">승인 후에도 실제 게시 기능은 기본 비활성 상태입니다.</p>
    <form method="post" action="/queue/approve" class="queue-form">
      <input type="hidden" name="preview_index" value="{preview_index}">
      <label>플랫폼 <select name="platform">{"".join(f'<option value="{platform}">{label}</option>' for platform, label in [("blog", "네이버 블로그"), ("youtube_shorts", "YouTube Shorts"), ("threads", "Threads"), ("instagram_reels", "Instagram Reels"), ("tiktok", "TikTok")])}</select></label>
      <label>예약 시각 (한국시간) <input type="datetime-local" name="scheduled_at" required></label>
      <button type="submit">승인하고 예약</button>
    </form>
  </details>
</section>""")
    generated = escape(str(report.get("researched_at", "아직 조사 전")))
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>TAK AUTO Trend Factory</title>
<style>
:root{{--bg:#f3f5f9;--ink:#182235;--muted:#65728a;--line:#dfe5ee;--accent:#3157c8}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.65 system-ui,"Malgun Gothic",sans-serif}}
main{{max-width:1100px;margin:auto;padding:24px 16px 60px}}header{{background:#182744;color:white;border-radius:18px;padding:26px}}
h1{{margin:0;font-size:28px}}header p{{color:#d4def0}}h2{{margin-top:30px}}
.toolbar,.trend,.preview{{background:white;border:1px solid var(--line);border-radius:14px;padding:18px;margin:14px 0}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}}
.trend h3{{font-size:20px;margin:6px 0}}.meta{{color:var(--muted);font-size:13px}}.hook{{font-weight:700;color:#9a4b13}}
button{{border:0;border-radius:9px;padding:11px 15px;background:var(--accent);color:white;font-weight:700;cursor:pointer}}
button.secondary{{background:#475569}}.error{{background:#fee;border:1px solid #d88;padding:12px;border-radius:10px}}
.warning{{background:#fff4d9;padding:12px;border-radius:9px}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.7 inherit;background:#f7f8fb;padding:14px;border-radius:9px}}
a{{color:#3157c8}}.draft{{border-top:1px solid var(--line);padding:10px 0}}
.copy{{margin:6px 0}}.copy.done{{background:#16794b}}
table{{width:100%;border-collapse:collapse;background:white}}th,td{{padding:8px;border-bottom:1px solid var(--line);text-align:left;overflow-wrap:anywhere}}.queue-form{{display:flex;flex-wrap:wrap;gap:12px;align-items:end}}label{{display:grid;gap:4px}}
@media(max-width:560px){{h1{{font-size:22px}}.grid{{display:block}}}}
</style></head><body><main>
<header><h1>TAK AUTO · TREND CONTENT FACTORY</h1>
<p>최신 트렌드 발견 → Perplexity 조사 → 블로그·쇼츠·Threads 제작 → 트래픽 유도</p>
<div>마지막 조사: {generated} · 모델: {escape(str(report.get('model', '미연결')))}</div>
{"<p>임시 저장소 사용 중: Render 무료 인스턴스에서는 재시작·재배포 시 조사 결과가 초기화될 수 있습니다.</p>" if USING_EPHEMERAL_STORAGE else ""}</header>
{error_html}
<section class="toolbar"><h2>최신 트렌드 조사</h2>
<p>Perplexity가 최근 7일 공개 웹 자료를 바탕으로 여러 분야의 키워드 최대 20개를 발굴합니다. 선택 키워드 콘텐츠 생성에도 Perplexity API를 한 번 더 사용합니다.</p>
<form method="post" action="/discover"><button type="submit">Perplexity 최신 트렌드 TOP 20 조사</button></form>
<p class="meta">검색량 순위가 아니라 최신 근거·한국 독자 관련성·콘텐츠 설명 가치에 따른 편집 후보입니다.</p></section>
<h2>발굴된 트렌드 {len(trends)}개</h2><div class="grid">{''.join(cards) or '<p>아직 조사 결과가 없습니다. 위 버튼으로 첫 조사를 실행하세요.</p>'}</div>
<h2>생성한 콘텐츠 패키지 {len(previews)}개</h2>{''.join(preview_cards) or '<p>트렌드를 선택해 콘텐츠 패키지를 생성하세요.</p>'}
{queue_dashboard(queue_snapshot or {"items": [], "history": []}, publishing_enabled=os.getenv("TAK_AUTO_PUBLISHING_ENABLED", "").strip().lower() == "true", pending_approvals=len(previews))}
</main><script>
document.addEventListener("click", async (event) => {{
  const button = event.target.closest("button.copy");
  if (!button) return;
  const target = document.getElementById(button.dataset.copy);
  if (!target) return;
  const text = target.innerText;
  try {{
    await navigator.clipboard.writeText(text);
    button.textContent = "복사 완료";
    button.classList.add("done");
  }} catch (_) {{
    const area = document.createElement("textarea");
    area.value = text;
    document.body.appendChild(area);
    area.select();
    const copied = document.execCommand("copy");
    area.remove();
    button.textContent = copied ? "복사 완료" : "텍스트를 직접 선택하세요";
  }}
}});
</script></body></html>"""


def create_handler():
    class Handler(BaseHTTPRequestHandler):
        def _respond(self, body: str, status: int = 200, content_type: str = "text/html; charset=utf-8"):
            encoded = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
            self.end_headers()
            self.wfile.write(encoded)

        def _require_auth(self):
            username = os.getenv("TAK_WEB_USERNAME", "").strip()
            password = os.getenv("TAK_WEB_PASSWORD", "")
            if not username and not password and self.server.server_address[0] in {"127.0.0.1", "localhost"}:
                return True
            if _basic_auth_valid(self.headers.get("Authorization", ""), username, password):
                return True
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="TAK AUTO", charset="UTF-8"')
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return False

        def do_GET(self):
            if self.path == "/health":
                perplexity_ready = bool(os.getenv("TAK_SCOUT_PERPLEXITY_API_KEY"))
                auth_ready = bool(os.getenv("TAK_WEB_USERNAME") and os.getenv("TAK_WEB_PASSWORD"))
                publishing_enabled = os.getenv("TAK_AUTO_PUBLISHING_ENABLED", "").strip().lower() == "true"
                publisher_configured = bool(os.getenv("TAK_AUTO_PUBLISHER", "").strip())
                payload = {
                    "status": "ok", "perplexity_configured": perplexity_ready,
                    "web_auth_configured": auth_ready, "publishing_enabled": publishing_enabled,
                    "publisher_adapter_configured": publisher_configured,
                    "ready": perplexity_ready and auth_ready,
                }
                self._respond(json.dumps(payload), content_type="application/json; charset=utf-8")
                return
            if not self._require_auth():
                return
            report = _read_json(TREND_PATH, {})
            previews = _read_json(PREVIEW_PATH, [])
            queue_snapshot = PublishingQueue(QUEUE_PATH).snapshot()
            self._respond(_page(report, previews, queue_snapshot=queue_snapshot))

        def do_POST(self):
            if not self._require_auth():
                return
            host = self.headers.get("Host", "")
            origin = self.headers.get("Origin", "")
            forwarded_proto = self.headers.get("X-Forwarded-Proto", "http")
            if not _same_origin(origin, host, forwarded_proto):
                self._respond(_page(_read_json(TREND_PATH, {}), [], "허용되지 않은 출처의 요청입니다."), 403)
                return
            length = int(self.headers.get("Content-Length", "0"))
            if length > 16_384:
                self._respond(_page(_read_json(TREND_PATH, {}), [], "요청이 너무 큽니다."), 413)
                return
            form = parse_qs(self.rfile.read(length).decode("utf-8"))
            report = _read_json(TREND_PATH, {})
            previews = _read_json(PREVIEW_PATH, [])
            queue = PublishingQueue(QUEUE_PATH)
            try:
                if self.path == "/discover":
                    provider = PerplexityResearchProvider.from_environment()
                    discovered = discover_trends(provider)
                    report = discovered.to_dict()
                    _write_json(TREND_PATH, report)
                    self._respond(_page(report, previews, queue_snapshot=queue.snapshot()))
                    return
                if self.path == "/generate":
                    if not report.get("trends"):
                        raise ValueError("먼저 최신 트렌드를 조사하세요.")
                    index = int(form.get("index", ["-1"])[0])
                    if index < 0 or index >= len(report["trends"]):
                        raise ValueError("선택한 트렌드가 없습니다.")
                    provider = PerplexityResearchProvider.from_environment()
                    preview = _make_preview(report["trends"][index], report, provider=provider)
                    previews = [row for row in previews if row.get("keyword") != preview["keyword"]]
                    previews.insert(0, preview)
                    _write_json(PREVIEW_PATH, previews[:10])
                    self._respond(_page(report, previews[:10], queue_snapshot=queue.snapshot()))
                    return
                if self.path == "/queue/approve":
                    index = int(form.get("preview_index", ["-1"])[0])
                    if index < 0 or index >= len(previews):
                        raise ValueError("승인할 콘텐츠 초안을 찾을 수 없습니다.")
                    platform = form.get("platform", [""])[0]
                    local_time = datetime.strptime(form.get("scheduled_at", [""])[0], "%Y-%m-%dT%H:%M")
                    scheduled_at = local_time.replace(tzinfo=KST)
                    preview = previews[index]
                    preview_key = json.dumps(preview, ensure_ascii=False, sort_keys=True)
                    content_id = "trend-" + hashlib.sha256(preview_key.encode("utf-8")).hexdigest()[:20]
                    if platform == "blog":
                        payloads = [preview.get("blog") or {}]
                    elif platform == "threads":
                        payloads = preview.get("threads") or []
                    else:
                        shorts = preview.get("shorts") or []
                        if not shorts:
                            raise ValueError("이 콘텐츠에는 쇼츠 원고가 없습니다.")
                        payloads = [shorts[0]]
                    approver = os.getenv("TAK_WEB_USERNAME", "local-user").strip() or "local-user"
                    enqueued = [queue.enqueue_approved(
                        content_id=content_id, platform=platform, payload=payload,
                        scheduled_at=scheduled_at, approved_by=approver,
                    ) for payload in payloads]
                    self._respond(_page(report, previews, f"{len(enqueued)}개 작업을 승인하고 예약했습니다.", queue.snapshot()))
                    return
                self._respond(_page(report, previews, "지원하지 않는 요청입니다."), 404)
            except Exception as error:
                # Never print request credentials or full exception payloads into the page.
                message = str(error) if isinstance(error, (ValueError, RuntimeError)) else type(error).__name__
                self._respond(_page(report, previews, message, queue.snapshot()), 400)

        def log_message(self, _format, *_args):
            return

    return Handler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.getenv("TAK_AUTO_HOST", "127.0.0.1"), help="바인딩 주소 (클라우드: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8765")))
    args = parser.parse_args(argv)
    if args.host not in {"127.0.0.1", "localhost"} and not (
        os.getenv("TAK_WEB_USERNAME", "").strip() and os.getenv("TAK_WEB_PASSWORD", "")
    ):
        parser.error("외부 공개 서버는 TAK_WEB_USERNAME과 TAK_WEB_PASSWORD 인증 설정이 필수입니다.")
    if not 1 <= args.port <= 65535:
        parser.error("--port는 1~65535 범위여야 합니다.")
    print("TAK AUTO Trend Content Factory")
    print(f"바인딩: {args.host}:{args.port}")
    print(f"데이터 디렉터리: {DATA_DIR}")
    if USING_EPHEMERAL_STORAGE:
        print("주의: 설정된 저장 경로를 쓸 수 없어 임시 저장소(/tmp)를 사용합니다. 무료 인스턴스 재시작 시 데이터가 사라질 수 있습니다.")
    print("웹 인증: 설정됨" if os.getenv("TAK_WEB_USERNAME") and os.getenv("TAK_WEB_PASSWORD") else "웹 인증: 로컬 개발 모드")
    print("Perplexity API 키: 설정됨" if os.getenv("TAK_SCOUT_PERPLEXITY_API_KEY") else "Perplexity API 키: 미설정")
    print("종료: Ctrl+C")
    server = ThreadingHTTPServer((args.host, args.port), create_handler())
    scheduler_thread, scheduler_stop = start_scheduler(QUEUE_PATH)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n종료합니다.")
    finally:
        scheduler_stop.set()
        scheduler_thread.join(timeout=2)
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
