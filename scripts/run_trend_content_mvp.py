#!/usr/bin/env python3
"""Local web MVP: discover current trends with Perplexity and preview traffic content."""
from __future__ import annotations

import argparse
import hashlib
from dataclasses import asdict
from datetime import datetime
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from blog_importer.models import utc_now
from content_engine.generator import generate_content_bundle
from tak_brain.models import KnowledgeRecord
from tak_scout.perplexity_research import PerplexityResearchProvider
from tak_scout.trend_discovery import TrendDiscovery, TrendItem, discover_trends

KST = ZoneInfo("Asia/Seoul")
TREND_PATH = ROOT / "data" / "tak_auto_live_trends.json"
PREVIEW_PATH = ROOT / "data" / "tak_auto_content_previews.json"


def _read_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _make_preview(item: dict, trend_report: dict) -> dict:
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


def _page(report: dict | None, previews: list[dict], error: str = "") -> str:
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
    for preview in previews:
        blog = preview.get("blog") or {}
        shorts = preview.get("shorts") or []
        threads = preview.get("threads") or []
        preview_cards.append(f"""
<section class="preview">
  <h2>{escape(str(preview.get('keyword', '')))} 콘텐츠 미리보기</h2>
  <p class="warning">{escape(str(preview.get('warning', '')))}</p>
  <h3>블로그 · {escape(str(blog.get('title', '')))}</h3><pre>{escape(str(blog.get('body', '')))}</pre>
  <h3>유튜브 쇼츠 · {len(shorts)}편</h3>
  {"".join(f'<div class="draft"><b>{escape(str(row.get("title", "")))}</b><pre>{escape(str(row.get("body", "")))}</pre></div>' for row in shorts)}
  <h3>Threads · {len(threads)}편</h3>
  {"".join(f'<div class="draft"><b>{escape(str(row.get("title", "")))}</b><pre>{escape(str(row.get("body", "")))}</pre></div>' for row in threads)}
  <p class="meta">{" ".join(f'<a href="{escape(url, quote=True)}" target="_blank" rel="noopener">원문 출처</a>' for url in preview.get("source_urls", []))}</p>
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
@media(max-width:560px){{h1{{font-size:22px}}.grid{{display:block}}}}
</style></head><body><main>
<header><h1>TAK AUTO · TREND CONTENT FACTORY</h1>
<p>최신 트렌드 발견 → Perplexity 조사 → 블로그·쇼츠·Threads 제작 → 트래픽 유도</p>
<div>마지막 조사: {generated} · 모델: {escape(str(report.get('model', '미연결')))}</div></header>
{error_html}
<section class="toolbar"><h2>최신 트렌드 조사</h2>
<p>Perplexity가 최근 7일 공개 웹 자료를 바탕으로 여러 분야의 키워드 최대 20개를 발굴합니다.</p>
<form method="post" action="/discover"><button type="submit">Perplexity 최신 트렌드 TOP 20 조사</button></form>
<p class="meta">검색량 순위가 아니라 최신 근거·한국 독자 관련성·콘텐츠 설명 가치에 따른 편집 후보입니다.</p></section>
<h2>발굴된 트렌드 {len(trends)}개</h2><div class="grid">{''.join(cards) or '<p>아직 조사 결과가 없습니다. 위 버튼으로 첫 조사를 실행하세요.</p>'}</div>
<h2>생성한 콘텐츠 패키지 {len(previews)}개</h2>{''.join(preview_cards) or '<p>트렌드를 선택해 콘텐츠 패키지를 생성하세요.</p>'}
</main></body></html>"""


def create_handler():
    class Handler(BaseHTTPRequestHandler):
        def _respond(self, body: str, status: int = 200):
            encoded = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self):
            report = _read_json(TREND_PATH, {})
            previews = _read_json(PREVIEW_PATH, [])
            self._respond(_page(report, previews))

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            if length > 16_384:
                self._respond(_page(_read_json(TREND_PATH, {}), [], "요청이 너무 큽니다."), 413)
                return
            form = parse_qs(self.rfile.read(length).decode("utf-8"))
            report = _read_json(TREND_PATH, {})
            previews = _read_json(PREVIEW_PATH, [])
            try:
                if self.path == "/discover":
                    provider = PerplexityResearchProvider.from_environment()
                    discovered = discover_trends(provider)
                    report = discovered.to_dict()
                    _write_json(TREND_PATH, report)
                    self._respond(_page(report, previews))
                    return
                if self.path == "/generate":
                    if not report.get("trends"):
                        raise ValueError("먼저 최신 트렌드를 조사하세요.")
                    index = int(form.get("index", ["-1"])[0])
                    if index < 0 or index >= len(report["trends"]):
                        raise ValueError("선택한 트렌드가 없습니다.")
                    preview = _make_preview(report["trends"][index], report)
                    previews = [row for row in previews if row.get("keyword") != preview["keyword"]]
                    previews.insert(0, preview)
                    _write_json(PREVIEW_PATH, previews[:10])
                    self._respond(_page(report, previews[:10]))
                    return
                self._respond(_page(report, previews, "지원하지 않는 요청입니다."), 404)
            except Exception as error:
                # Never print request credentials or full exception payloads into the page.
                message = str(error) if isinstance(error, (ValueError, RuntimeError)) else type(error).__name__
                self._respond(_page(report, previews, message), 400)

        def log_message(self, _format, *_args):
            return

    return Handler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", help="MVP 기본값은 이 PC에서만 접속")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    if args.host not in {"127.0.0.1", "localhost"}:
        parser.error("초기 MVP는 로컬 접속만 허용합니다. 외부 배포는 인증 기능 추가 후 진행하세요.")
    if not 1 <= args.port <= 65535:
        parser.error("--port는 1~65535 범위여야 합니다.")
    print("TAK AUTO Trend Content Factory")
    print(f"열기: http://{args.host}:{args.port}")
    print("Perplexity API 키: 설정됨" if os.getenv("TAK_SCOUT_PERPLEXITY_API_KEY") else "Perplexity API 키: 미설정")
    print("종료: Ctrl+C")
    server = ThreadingHTTPServer((args.host, args.port), create_handler())
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n종료합니다.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
