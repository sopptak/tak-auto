"""Render a self-contained, read-only HTML dashboard from daily TAK AUTO data."""
from __future__ import annotations

from html import escape
from typing import Any


def _cell(value: object) -> str:
    return escape(str(value if value is not None else ""))


def render_dashboard(report: dict[str, Any], candidates: list[dict[str, Any]]) -> str:
    by_id = {str(row.get("scout_id", "")): row for row in candidates}
    generated = _cell(report.get("generated_on", ""))
    top = report.get("top_keywords", [])
    rising = report.get("rising_keywords", [])
    opportunities = report.get("content_opportunities", [])

    keyword_rows = "".join(
        f"<tr><td>{_cell(i)}</td><td><strong>{_cell(row.get('keyword'))}</strong></td>"
        f"<td>{_cell(row.get('candidate_count'))}</td><td>{_cell(row.get('source_count'))}</td></tr>"
        for i, row in enumerate(top, 1)
    ) or '<tr><td colspan="4">반복 키워드가 없습니다.</td></tr>'
    rising_rows = "".join(
        f"<tr><td>{_cell(row.get('keyword'))}</td><td>{_cell(row.get('previous_count'))} → "
        f"{_cell(row.get('current_count'))}</td><td>+{_cell(row.get('change'))}</td></tr>"
        for row in rising
    ) or '<tr><td colspan="3">비교 가능한 증가 키워드가 없습니다.</td></tr>'
    opportunity_cards = []
    for row in opportunities:
        linked = []
        for candidate_id in row.get("candidate_ids", []):
            candidate = by_id.get(str(candidate_id))
            if candidate:
                linked.append(candidate)
        # Older report schema may not include candidate IDs; display its evidence text instead.
        sources = "".join(
            f'<li><a href="{_cell(item.get("source_url"))}" target="_blank" rel="noopener">'
            f'{_cell(item.get("title"))}</a> · {_cell(item.get("source_name"))}</li>'
            for item in linked[:3]
        )
        reasons = " · ".join(_cell(x) for x in row.get("reasons", []))
        opportunity_cards.append(
            f'<article class="opportunity"><div class="score">{_cell(row.get("score"))}점</div>'
            f'<h3>{_cell(row.get("keyword"))}</h3><p>{reasons}</p>'
            f'<p class="muted">피드 언급 { _cell(row.get("candidate_count")) }건 · '
            f'출처 { _cell(row.get("source_count")) }곳</p><ul>{sources}</ul></article>'
        )
    cards = "".join(opportunity_cards) or '<p>콘텐츠 기회 후보가 없습니다.</p>'

    candidate_rows = "".join(
        f'<article class="story"><h3><a href="{_cell(row.get("source_url"))}" target="_blank" '
        f'rel="noopener">{_cell(row.get("title"))}</a></h3><p>{_cell(row.get("summary"))}</p>'
        f'<small>{_cell(row.get("source_name"))} · {_cell(row.get("published_at"))}</small></article>'
        for row in candidates
    ) or "<p>오늘 수집된 후보가 없습니다.</p>"

    datalab = report.get("naver_datalab", {})
    datalab_status = _cell(datalab.get("status", "미연결") if isinstance(datalab, dict) else "미연결")
    limitations = "".join(f"<li>{_cell(item)}</li>" for item in report.get("limitations", []))
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TAK AUTO · {generated}</title><style>
:root{{--bg:#f4f6fa;--ink:#172033;--muted:#65718a;--line:#e1e6ef;--accent:#3659d9}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 system-ui,-apple-system,"Malgun Gothic",sans-serif}}
main{{max-width:1100px;margin:auto;padding:28px 18px 60px}}header{{background:#17233e;color:white;padding:28px;border-radius:18px}}
header p{{color:#c8d2e7;margin:6px 0}}h1{{margin:0;font-size:28px}}h2{{margin:30px 0 12px;font-size:21px}}
.metrics{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:16px 0}}
.metric,.panel,.opportunity,.story{{background:white;border:1px solid var(--line);border-radius:14px;padding:16px}}
.metric b{{display:block;font-size:30px}}.muted,small{{color:var(--muted)}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}}
.score{{color:var(--accent);font-weight:800}}table{{width:100%;border-collapse:collapse;background:white;border-radius:12px;overflow:hidden}}
th,td{{text-align:left;padding:11px 13px;border-bottom:1px solid var(--line)}}th{{background:#edf1f8}}
a{{color:#244bc2;text-decoration:none}}a:hover{{text-decoration:underline}}ul{{padding-left:18px}}
.notice{{background:#fff8e8;border:1px solid #f0dfb2;padding:13px;border-radius:12px;color:#70551a}}
@media(max-width:560px){{.metrics{{grid-template-columns:1fr}}h1{{font-size:23px}}}}
</style></head><body><main>
<header><h1>TAK AUTO</h1><p>Trend Discovery & Content Factory</p><p>기준일: {generated} · 데이터랩: {datalab_status}</p></header>
<section class="metrics"><div class="metric"><span class="muted">반복 키워드</span><b>{len(top)}</b><small>등록 RSS 내부 신호</small></div>
<div class="metric"><span class="muted">급상승 후보</span><b>{len(rising)}</b><small>직전 관측일 대비</small></div>
<div class="metric"><span class="muted">콘텐츠 기회</span><b>{len(opportunities)}</b><small>편집 우선순위 후보</small></div></section>
<h2>오늘의 반복 키워드 TOP 20</h2><table><thead><tr><th>#</th><th>키워드</th><th>언급</th><th>출처</th></tr></thead><tbody>{keyword_rows}</tbody></table>
<h2>급상승 키워드 TOP 10</h2><table><thead><tr><th>키워드</th><th>이전 → 오늘</th><th>증가</th></tr></thead><tbody>{rising_rows}</tbody></table>
<h2>콘텐츠 기회 TOP 5</h2><div class="grid">{cards}</div>
<h2>오늘의 소재</h2><div class="grid">{candidate_rows}</div>
<h2>측정 한계</h2><div class="notice"><ul>{limitations}</ul>
<p>RSS 반복은 전체 검색량·SNS 인기도·키워드 경쟁도를 뜻하지 않습니다. 데이터랩 값은 상대 검색 관심도이며 절대 검색량이 아닙니다.</p></div>
<footer><p class="muted">TAK AUTO · 사람이 검토하고 승인하기 전 외부 게시를 하지 않습니다.</p></footer>
</main></body></html>
"""
