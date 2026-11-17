"""Read-only trend view embedded in the existing TAK SCOUT Dashboard."""
from __future__ import annotations

from html import escape
from typing import Any


def render_trends_page(report: dict[str, Any], research_records: list[Any] | None = None) -> str:
    research_by_id = {getattr(item, "scout_id", ""): item for item in (research_records or [])}
    top = report.get("top_keywords", [])
    rising = report.get("rising_keywords", [])
    opportunities = report.get("content_opportunities", [])
    lines = [
        '<h1>TAK AUTO · 오늘의 트렌드</h1>',
        '<div class="nav-links"><a href="/">← 기존 SCOUT 홈</a> <a href="/research">심층 조사 결과</a></div>',
        '<div class="sub">기준일: ' + escape(str(report.get("generated_on", "미수집"))) +
        ' · 측정 범위: 등록된 공개 RSS 피드</div>',
        '<section class="card"><h2>반복 키워드 TOP 20</h2>',
        '<table><thead><tr><th>키워드</th><th>피드 언급</th><th>출처</th></tr></thead><tbody>',
    ]
    for row in top:
        lines.append('<tr><td><strong>' + escape(str(row.get("keyword", ""))) +
                     '</strong></td><td>' + escape(str(row.get("candidate_count", 0))) +
                     '</td><td>' + escape(str(row.get("source_count", 0))) + '</td></tr>')
    if not top:
        lines.append('<tr><td colspan="3">트렌드 자료가 없습니다. 먼저 일일 수집을 실행하세요.</td></tr>')
    lines.extend(['</tbody></table></section>', '<section class="card"><h2>급상승 후보 TOP 10</h2>',
                  '<table><thead><tr><th>키워드</th><th>이전 → 오늘</th><th>증가</th></tr></thead><tbody>'])
    for row in rising:
        lines.append('<tr><td>' + escape(str(row.get("keyword", ""))) + '</td><td>' +
                     escape(str(row.get("previous_count", 0))) + ' → ' +
                     escape(str(row.get("current_count", 0))) + '</td><td>+' +
                     escape(str(row.get("change", 0))) + '</td></tr>')
    if not rising:
        lines.append('<tr><td colspan="3">비교 가능한 과거 관측 데이터가 부족하거나 증가 후보가 없습니다.</td></tr>')
    lines.extend(['</tbody></table></section>', '<h2>콘텐츠 기회 TOP 5</h2>'])
    for row in opportunities:
        ids = row.get("candidate_ids", [])
        evidence_links = []
        for candidate_id in ids:
            record = research_by_id.get(str(candidate_id))
            if record:
                evidence_links.append('<a class="btn" href="/research/' +
                                      escape(str(candidate_id)) + '">조사 결과 보기</a>')
            else:
                safe_id = escape(str(candidate_id), quote=True)
                evidence_links.append(
                    '<form method="post" action="/candidate/' + safe_id +
                    '/research"><button class="btn primary" type="submit">근거 기사 심층 조사</button></form>'
                )
        keyword = str(row.get("keyword", ""))
        lines.append(
            '<section class="card"><div class="card-top"><strong class="title">' +
            escape(keyword) + '</strong><span class="score">' +
            escape(str(row.get("score", 0))) + '점</span></div><p>' +
            escape(" · ".join(str(x) for x in row.get("reasons", []))) +
            '</p><div class="meta">RSS 언급 ' +
            escape(str(row.get("candidate_count", 0))) + '건 · 출처 ' +
            escape(str(row.get("source_count", 0))) + '곳</div>' +
            (''.join(evidence_links) if evidence_links else
             '<p class="meta">근거 기사별 Perplexity 조사를 실행할 수 있습니다.</p>') +
            '</section>'
        )
    if not opportunities:
        lines.append('<p>콘텐츠 기회 후보가 없습니다.</p>')
    lines.extend([
        '<section class="card"><h2>지표 해석 주의</h2><ul>',
        '<li>RSS 언급 건수는 전체 검색량이나 SNS 인기도가 아닙니다.</li>',
        '<li>급상승은 직전 저장 관측일 대비 등록 피드 내 언급 증가만 의미합니다.</li>',
        '<li>기회 점수는 편집 우선순위 참고용 휴리스틱이며 검색 경쟁도·수요 점수가 아닙니다.</li>',
        '</ul></section>',
    ])
    return '\n'.join(lines)
