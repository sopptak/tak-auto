#!/usr/bin/env python3
"""TAK SCOUT Dashboard: 웹 브라우저에서 오늘의 SCOUT 소재를 보고, 최대 3턴짜리
멀티턴 인터뷰에 답하는 화면(5-9 MVP + 5-10 Phase 2 멀티턴 확장 + Phase 3-2 LLM 연결).

Python 표준 라이브러리 http.server만 사용한다(Flask/React/Next.js 등 새 의존성을
추가하지 않는다). 프론트엔드 빌드 시스템도 없다 - HTML은 이 파일 안에서 문자열로
직접 만든다.

Phase 2(5-10)에서 추가된 것: 소재 1건당 질문을 1개가 아니라 최대 3개(고정
템플릿, LLM 없음)까지 순서대로 묻고, 3턴이 끝나면 review 화면에서 사람이 확인한
뒤에만 KNOWLEDGE로 연결한다. 멀티턴 원본은 tak_scout.interview_session에 별도로
저장하고, 최종 확정된 답변만 기존 tak_scout.answers/knowledge_bridge 경로로
합성해 넘긴다(기존 스키마 변경 없음).

Phase 3-2(5-10)에서 추가된 것: tak_scout.interview_llm.InterviewLLMProvider를
선택적으로 연결한다. Turn 1 질문과 Turn 2/3 후속 질문·조기 완료 판단을 LLM이
우선 시도하고, provider가 없거나 LLM 호출이 어떤 이유로든 실패(None 반환)하면
Phase 2의 고정 템플릿으로 그대로 fallback한다 - LLM 실패가 Dashboard 오류가 되지
않는다. `make_handler_class(config, llm_provider=...)`로 주입하며, 인자를 생략하면
(기존 호출부·기존 테스트와 동일) LLM을 전혀 쓰지 않는 Phase 2 동작 그대로다 -
content_engine의 MockRewriteProvider 관례와 동일하게, "인자 없음 = 네트워크 없는
안전한 기본값"을 따른다. 실제 운영에서 LLM을 쓰려면 main()이 하는 것처럼 호출부가
`InterviewLLMProvider.from_environment()`로 만든 provider를 명시적으로 넘겨야
한다(scripts/run_media_batch.py 등 기존 스크립트들이 OpenAICompatibleRewriteProvider를
넘기는 방식과 동일한 관례).

Phase 2(5-11)에서 추가된 것: SCOUT/INTERVIEW 흐름과 완전히 별개인 "Threads 초안
검수" 화면(`/threads`, `/threads/{content_id}`)을 같은 Dashboard에 추가한다.
`content_engine.threads_review`(5-11 Phase 1, 수정 없음)가 만든
`data/tak_threads_pending.json`의 `status == "pending"` 초안을 보여주고, 티몽이
그대로 승인하거나 제목/본문을 직접 고쳐 승인할 수 있게 한다. 이 화면은
`ThreadsClient`를 import하지 않고, 실제 Threads 게시나 `PublishHistory` 갱신을
전혀 수행하지 않는다 - 상태를 `pending -> approved`로 바꿔 저장하는 것까지만
한다(발행은 다음 Phase의 책임). SCOUT 인터뷰 라우트(`/`, `/candidate/...`)는 이
Phase에서 한 줄도 수정하지 않았다.

이 스크립트는 새 비즈니스 로직을 만들지 않는다. 각 단계는 이미 구현되고 테스트된
기존 함수를 그대로 호출한다:

    tak_scout.load_daily_pack            TAK SCOUT 오늘의 소재 읽기(읽기 전용)
    tak_scout.rank_candidates            SCOUT SCORE 계산 + 정렬(5-8, 수정 없음)
    tak_scout.interview_session.*        멀티턴 세션 저장/로드(5-10 Phase 1, 수정 없음)
    tak_scout.interview_llm.InterviewLLMProvider  선택적 LLM 질문 생성(5-10 Phase 3-1, 수정 없음)
    tak_scout.InterviewAnswer/upsert_answer  최종 합성 답변 저장(기존 스키마 그대로)
    tak_scout.load_answers               "이미 답변함" 판단(5-7과 동일 개념)
    tak_scout.append_scout_knowledge     TAK BRAIN KNOWLEDGE 생성(pending) -
                                          apply_interview.py가 호출하는 것과
                                          똑같은 함수를 그대로 호출한다.
    tak_scout.dashboard_state            "관심 없음" 상태(5-9, 수정 없음)
    content_engine.threads_review.*      Threads pending draft 저장/상태 전이
                                          (5-11 Phase 1, 수정 없음)

이 스크립트가 절대 하지 않는 것:
    - KNOWLEDGE 자동 승인 (pending까지만 - 승인은 review_knowledge.py로 사람이)
    - TAK MEDIA 실행
    - Threads/Naver 게시 (Threads 검수 화면도 승인까지만 - 실제 API 호출은 하지 않음)
    - 외부 네트워크에 노출(기본적으로 127.0.0.1에만 바인딩)
    - LLM 실패를 사용자에게 노출(항상 조용히 템플릿으로 fallback)
    - Threads 사용자 수정 문장을 LLM으로 다시 보내 재작성하는 것(5-11 Phase 2)
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
from datetime import datetime
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from blog_importer.models import utc_now

from tak_scout import (
    VALID_OPTIONS,
    InterviewAnswer,
    InterviewAnswerError,
    ScoutCandidate,
    ScoutScore,
    append_scout_knowledge,
    load_answers,
    load_daily_pack,
    rank_candidates,
    upsert_answer,
)
from tak_scout.dashboard_state import mark_skipped, skipped_scout_ids
from tak_scout.interview_llm import FORCED_OPTION_D, FollowUpDecision, InterviewLLMProvider
from tak_scout.interview_session import (
    InterviewSession,
    InterviewTurnRecord,
    load_sessions,
    upsert_session,
)
from tak_scout.title_translation import TitleTranslation, translations_by_scout_id, upsert_translation
from tak_brain import KnowledgeRecord, load_knowledge_records
from content_engine import LLMConfigurationError
from content_engine.media_archive import (
    MediaArchiveRecord,
    find_generation_record,
    load_archive,
    upsert_archive,
    upsert_generation_archive,
)
from content_engine.performance import (
    ContentPerformanceSummary,
    load_snapshots as load_performance_snapshots,
    pick_headline_metric,
    render_text_trend,
    summarize_content_history,
)
from content_engine.publish_history import PublishHistory
from content_engine.shorts_adapter import (
    ShortsAdapterError,
    save_approved_shorts_script,
    shorts_script_output_path,
)
from content_engine.threads_review import (
    UNRESOLVED_STATUSES,
    ThreadsPendingDraft,
    ThreadsPendingError,
    load_pending,
    mark_approved,
    upsert_pending,
)
from content_engine.youtube_upload_history import YouTubeUploadHistory


_BREAKDOWN_LABELS: tuple[tuple[str, str, int], ...] = (
    ("content_interest", "콘텐츠 관심도", 25),
    ("expertise_relevance", "티몽 전문성", 25),
    ("opinion_potential", "의견 가능성", 20),
    ("monetization_relevance", "수익화 관련성", 15),
    ("recency", "최신성", 15),
)

# Phase 2 고정 질문 템플릿(5-10 Phase 2 지시사항 그대로). LLM을 쓰지 않는다.
# 선택지 텍스트에는 "A. " 같은 문자 접두어를 담지 않는다(렌더링 시에만 붙인다) -
# InterviewTurnRecord.option_a 등에는 순수 문구만 저장한다.
MAX_TURNS = 3
_TURN_TEMPLATES: tuple[dict[str, str], ...] = (
    {
        "question": "이 소재에 대해 어떻게 생각하시나요?",
        "option_a": "긍정적으로 본다",
        "option_b": "부정적으로 본다",
        "option_c": "아직 판단하기 어렵다",
        "option_d": "직접 입력",
    },
    {
        "question": "그렇게 생각하게 된 이유나 경험이 있나요?",
        "option_a": "직접 경험한 적이 있다",
        "option_b": "주변에서 비슷한 사례를 봤다",
        "option_c": "특별한 경험은 없지만 그렇게 생각한다",
        "option_d": "직접 입력",
    },
    {
        "question": "이 주제에 대해 다른 사람에게 가장 전하고 싶은 생각은 무엇인가요?",
        "option_a": "직접 해보는 것이 중요하다",
        "option_b": "신중하게 접근해야 한다",
        "option_c": "아직 더 지켜봐야 한다",
        "option_d": "직접 입력",
    },
)


@dataclass(frozen=True)
class DashboardConfig:
    daily_pack_path: Path
    answers_path: Path
    knowledge_path: Path
    skipped_path: Path
    sessions_path: Path
    # 5-11 Phase 2 - 기본값을 둬서 기존 호출부(테스트 포함)가 이 필드를 넘기지
    # 않아도 그대로 동작한다(SCOUT 관련 기존 테스트는 이 경로를 전혀 쓰지 않는다).
    pending_path: Path = ROOT / "data" / "tak_threads_pending.json"
    # 5-20 - 한국어 표시용 제목 번역 캐시. 기본값을 둬서 기존 호출부(테스트 포함)가
    # 이 필드를 넘기지 않아도 그대로 동작한다.
    title_translations_path: Path = ROOT / "data" / "tak_scout_title_translations.json"
    # 5-27 - TAK MEDIA 배치 결과 전체(valid/rejected/error) 아카이브. 기본값을 둬서
    # 기존 호출부(테스트 포함)가 이 필드를 넘기지 않아도 그대로 동작한다. 이 Dashboard는
    # 이 경로를 읽기만 한다 - 승인/발행 액션은 이번 작업 범위에 포함하지 않는다.
    media_archive_path: Path = ROOT / "data" / "tak_media_archive.json"
    # 5-29 - 승인된 Shorts를 저장하는 ShortsScript JSON 디렉터리. MEDIA 승인 시
    # 자동으로 이 경로에 생성된다(content_engine.shorts_adapter.
    # save_approved_shorts_script). 기본값을 둬서 기존 호출부가 이 필드를
    # 넘기지 않아도 그대로 동작한다.
    shorts_scripts_path: Path = ROOT / "data" / "shorts_scripts"
    # 5-29 - Blog 게시 이력(PublishHistory). Dashboard는 이 경로를 읽기만 해서
    # "게시 기록됨" downstream 상태를 판정한다 - 새로 쓰지 않는다(실제 게시
    # 기록은 여전히 사람이 scripts/mark_blog_published.py로 한다).
    blog_history_path: Path = ROOT / "data" / "blog_publish_log.json"
    # 6-01 - 성과(Performance) 스냅샷 저장소. 이 Dashboard는 /performance에서
    # 읽기만 한다 - 실제 수집(API 호출/수동 입력 저장)은 scripts/collect_performance.py의
    # 책임이다(MEDIA archive를 이 Dashboard가 승인만 하고 발행은 다른 스크립트가
    # 하는 것과 동일한 책임 분리).
    performance_path: Path = ROOT / "data" / "tak_performance.json"
    # 6-07 - MEDIA generation pool(6-06 설계) 파일 목록. 6-07에서는 읽기 전용
    # 조회만 가능했고, 6-08에서 승인/보류(review_status 변경) 액션이 추가됐다.
    # production archive(media_archive_path)와 달리 generation pool은 고정된
    # 경로 하나가 아니라 "이번에 재생성한 KNOWLEDGE 1건"마다 별도 파일로 생긴다
    # (docs/6-07_second_knowledge_regeneration.md 참고) - 기본값은 빈 튜플이라
    # 이 인자를 넘기지 않는 기존 호출부(테스트 포함)는 /media/generations가
    # "설정된 generation pool 없음"으로 안전하게 동작한다. 이 화면의 승인/보류
    # 액션은 generation pool 파일만 갱신하고 production archive는 절대 건드리지
    # 않는다(docs/6-08_generation_review_and_promotion.md 참고).
    generation_archive_paths: tuple[Path, ...] = ()
    # 6-13 - YouTube 업로드 이력(YouTubeUploadHistory, content_engine.youtube_upload_history).
    # Dashboard는 이 경로를 읽기만 해서 Shorts의 downstream 상태가 "MP4 생성됨"에서
    # 더 나아가 "YouTube 업로드됨"까지 표시되도록 한다 - 실제 업로드는 여전히 사람이
    # scripts/upload_youtube_short.py로 한다(blog_history_path와 동일한 책임 분리).
    # 기본값을 둬서 기존 호출부(테스트 포함)가 이 필드를 넘기지 않아도 그대로 동작한다.
    youtube_history_path: Path = ROOT / "data" / "youtube_publish_log.json"


# Threads 500자 제한은 새로 만드는 규칙이 아니다 - ThreadsClient.publish_text
# (content_engine/threads_publisher.py)와 RewriteValidator._threads_length_errors
# (content_engine/rewrite.py)가 이미 각각 하드코딩해 둔 것과 정확히 같은 값을
# Dashboard 승인 단계에서도 그대로 적용한다(기존 정책 재사용, 신규 규칙 아님).
MAX_THREADS_BODY_LENGTH = 500

_THREADS_STATUS_LABELS: dict[str, str] = {
    "pending": "검수 대기",
    "approved": "승인됨 (발행 대기)",
    "published": "발행됨",
    "failed": "발행 실패",
}


# --- 공용 HTML 뼈대 (프레임워크 없이 순수 문자열) ------------------------------

_PAGE_STYLE = """
<style>
  :root { color-scheme: light; }
  * { box-sizing: border-box; }
  body {
    font-family: -apple-system, "Apple SD Gothic Neo", "Malgun Gothic", sans-serif;
    margin: 0; padding: 16px; background: #f5f5f4; color: #1c1c1c; line-height: 1.5;
  }
  h1 { font-size: 1.3rem; margin: 0 0 4px; }
  .sub { color: #6b6b6b; font-size: 0.85rem; margin-bottom: 16px; }
  .card {
    background: #fff; border: 1px solid #e2e2e0; border-radius: 10px;
    padding: 14px 16px; margin-bottom: 12px; max-width: 760px;
  }
  .card-top { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
  .rank { font-weight: 700; color: #8a8a86; }
  .score { font-weight: 700; font-size: 1.1rem; color: #1a5c3a; }
  .status { font-size: 0.78rem; padding: 2px 8px; border-radius: 999px; background: #eee; }
  .status.answered { background: #dff3e3; color: #1a5c3a; }
  .status.skipped { background: #f1e6e6; color: #8a3b3b; }
  .status.unanswered { background: #eef0f7; color: #33415c; }
  .title { font-size: 1.05rem; font-weight: 600; margin: 6px 0 4px; }
  .title-ko { font-size: 1.05rem; font-weight: 600; margin: 6px 0 2px; }
  .title-en { font-size: 0.78rem; color: #8a8a86; margin-bottom: 4px; }
  .meta { font-size: 0.82rem; color: #6b6b6b; margin-bottom: 6px; }
  .breakdown { font-size: 0.78rem; color: #555; margin-bottom: 6px; }
  .summary { font-size: 0.88rem; color: #333; margin-bottom: 6px; }
  .reason { font-size: 0.88rem; margin-bottom: 10px; }
  .actions { display: flex; gap: 8px; flex-wrap: wrap; }
  .btn {
    display: inline-block; padding: 8px 14px; border-radius: 8px; border: 1px solid #ccc;
    background: #fff; color: #1c1c1c; text-decoration: none; font-size: 0.88rem; cursor: pointer;
  }
  .btn.primary { background: #1a5c3a; color: #fff; border-color: #1a5c3a; }
  .btn.ghost { background: #fff; color: #8a3b3b; border-color: #e0c9c9; }
  form { display: inline; margin: 0; }
  .options { display: flex; flex-direction: column; gap: 10px; max-width: 560px; }
  .options button {
    text-align: left; padding: 12px 14px; border-radius: 8px; border: 1px solid #ccc;
    background: #fff; font-size: 0.95rem; cursor: pointer;
  }
  .options button:hover { border-color: #1a5c3a; }
  textarea {
    width: 100%; max-width: 560px; min-height: 90px; padding: 10px; border-radius: 8px;
    border: 1px solid #ccc; font-size: 0.95rem; font-family: inherit;
  }
  .banner { background: #dff3e3; border: 1px solid #b6e0c1; color: #1a5c3a;
    padding: 10px 14px; border-radius: 8px; margin-bottom: 14px; max-width: 700px; }
  .error { background: #f9e0e0; border: 1px solid #e5b8b8; color: #7a2626;
    padding: 10px 14px; border-radius: 8px; margin-bottom: 14px; max-width: 700px; }
  .back { display: inline-block; margin-bottom: 12px; font-size: 0.85rem; }
  .progress { font-size: 0.82rem; color: #6b6b6b; margin-bottom: 10px; }
  .qa-block { max-width: 700px; margin-bottom: 14px; padding-bottom: 10px; border-bottom: 1px solid #eee; }
  .qa-question { font-weight: 600; margin-bottom: 4px; }
  .qa-answer { color: #1a5c3a; }
  .qa-answer.direct { white-space: pre-wrap; }
  .nav-links { font-size: 0.82rem; margin-bottom: 10px; }
  .nav-links a { margin-right: 10px; }
  h2 { font-size: 1rem; margin: 18px 0 6px; }
  .body-block { white-space: pre-wrap; font-size: 0.92rem; max-width: 700px; }
  .body-preview { font-size: 0.88rem; color: #444; margin: 4px 0 8px; white-space: pre-wrap; }
  .group-header { font-weight: 700; margin: 18px 0 6px; font-size: 0.95rem; color: #33415c; }
  .filters { margin-bottom: 14px; display: flex; flex-direction: column; gap: 6px; }
  .filter-row { display: flex; gap: 6px; flex-wrap: wrap; }
  .filter-link {
    font-size: 0.78rem; padding: 4px 10px; border-radius: 999px; background: #eee;
    color: #333; text-decoration: none; white-space: nowrap;
  }
  .filter-link.active { background: #1a5c3a; color: #fff; }
  @media (max-width: 480px) {
    body { padding: 10px; }
    .card { padding: 12px; }
  }
</style>
"""


def _page(title: str, body: str) -> bytes:
    html = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
{_PAGE_STYLE}
</head>
<body>
{body}
</body>
</html>
"""
    return html.encode("utf-8")


def _format_published_at(published_at: str) -> str:
    try:
        parsed = datetime.fromisoformat(published_at)
    except ValueError:
        return published_at or "알 수 없음"
    return parsed.strftime("%Y-%m-%d %H:%M")


def _status_for(scout_id: str, answered_ids: frozenset[str], skipped_ids: frozenset[str]) -> tuple[str, str]:
    """(css class, 표시 라벨)을 반환한다."""
    if scout_id in answered_ids:
        return "answered", "이미 답변함"
    if scout_id in skipped_ids:
        return "skipped", "관심 없음"
    return "unanswered", "아직 답변하지 않음"


def render_candidate_list_html(
    ranked: list[tuple[ScoutCandidate, ScoutScore]],
    answered_ids: frozenset[str],
    skipped_ids: frozenset[str],
    display_titles: dict[str, str] | None = None,
) -> str:
    """오늘의 소재 화면(화면 1) - 점수 내림차순 카드 목록.

    5-20: 카드에는 한국어 표시용 제목(display_titles)을 가장 크게 보여주고, 영어
    원문 제목은 그 아래 작게 보조 표시한다. display_titles를 안 넘기면(기존
    호출부 호환) 원문 제목만 표시했던 이전 동작과 같아진다 - 번역이 없는 scout_id는
    원문을 그대로 쓴다.
    """
    display_titles = display_titles or {}
    cards: list[str] = []
    for index, (candidate, score) in enumerate(ranked, start=1):
        status_class, status_label = _status_for(candidate.scout_id, answered_ids, skipped_ids)
        breakdown_text = " · ".join(
            f"{label} {score.breakdown[key]}" for key, label, _max in _BREAKDOWN_LABELS
        )
        candidate_url = f"/candidate/{escape(candidate.scout_id)}"
        display_title = display_titles.get(candidate.scout_id, candidate.title)
        title_block = f'<div class="title-ko">{escape(display_title)}</div>'
        if display_title != candidate.title:
            title_block += f'<div class="title-en">원문: {escape(candidate.title)}</div>'
        cards.append(
            f"""
<div class="card">
  <div class="card-top">
    <span class="rank">#{index}</span>
    <span class="score">{score.total}점</span>
    <span class="status {status_class}">{escape(status_label)}</span>
  </div>
  {title_block}
  <div class="meta">
    출처: {escape(candidate.source_name or "알 수 없음")} ·
    발행: {escape(_format_published_at(candidate.published_at))} ·
    category: {escape(candidate.category)}
  </div>
  <div class="breakdown">{escape(breakdown_text)}</div>
  <div class="summary">{escape(candidate.summary or "(요약 없음)")}</div>
  <div class="reason">추천 이유: {escape(score.recommendation_reason)}</div>
  <div class="actions">
    <a class="btn primary" href="{candidate_url}">이 소재로 답변하기</a>
    <a class="btn" href="{escape(candidate.source_url)}" target="_blank" rel="noopener">원문 보기</a>
    <form method="post" action="{candidate_url}/skip">
      <button class="btn ghost" type="submit">관심 없음</button>
    </form>
  </div>
</div>
"""
        )

    body = f"""
<h1>TAK SCOUT Dashboard</h1>
<div class="nav-links"><a href="/threads">Threads 검수</a><a href="/media">📱 TAK MEDIA</a><a href="/performance">📈 Performance</a></div>
<div class="sub">오늘의 소재 {len(ranked)}건 · 점수 내림차순 (SCOUT SCORE MVP, LLM 미사용)</div>
{"".join(cards) if cards else "<p>오늘 표시할 소재가 없습니다.</p>"}
"""
    return body


def _option_label(letter: str, text: str) -> str:
    return f"{letter}. {text}"


def render_turn_html(
    candidate: ScoutCandidate,
    session: InterviewSession,
    turn: InterviewTurnRecord,
    saved: bool = False,
    error: str | None = None,
    display_title: str | None = None,
) -> str:
    """멀티턴 인터뷰 중 현재 턴의 질문 화면(화면 2, Phase 2).

    5-20: display_title(한국어 표시용 제목)을 먼저 보여주고, 원문(candidate.title)은
    작은 글씨로 함께 보여준다. display_title을 안 넘기면(기존 호출부 호환) 원문만
    표시한다.
    """
    banner = ""
    if saved:
        banner = '<div class="banner">저장되었습니다. 다음 질문으로 이동합니다.</div>'
    if error:
        banner += f'<div class="error">오류: {escape(error)}</div>'

    action = f"/candidate/{escape(candidate.scout_id)}/answer"

    heading = escape(display_title or candidate.title)
    original_line = ""
    if display_title and display_title != candidate.title:
        original_line = f'<div class="title-en">원문: {escape(candidate.title)}</div>'

    body = f"""
<a class="back" href="/">&larr; 오늘의 소재로 돌아가기</a>
<h1>{heading}</h1>
{original_line}
<div class="meta">출처: {escape(candidate.source_name or "알 수 없음")} ({escape(candidate.source_url)})</div>
<div class="progress">질문 {turn.turn} / {MAX_TURNS}</div>
{banner}
<p><strong>{escape(turn.question)}</strong></p>
<form method="post" action="{action}" id="answer-form">
  <div class="options">
    <button type="submit" name="option" value="A">{escape(_option_label("A", turn.option_a))}</button>
    <button type="submit" name="option" value="B">{escape(_option_label("B", turn.option_b))}</button>
    <button type="submit" name="option" value="C">{escape(_option_label("C", turn.option_c))}</button>
    <button type="button" id="option-d-btn">{escape(_option_label("D", turn.option_d))}</button>
  </div>
  <div id="custom-box" style="display:none; margin-top:12px;">
    <p>내 생각을 직접 입력하세요</p>
    <textarea name="custom_answer" placeholder="예: 신기술은 두려워 말고 부딪혀서 느껴봐야 한다."></textarea>
    <div style="margin-top:8px;">
      <button type="submit" class="btn primary" name="option" value="D">다음</button>
    </div>
  </div>
</form>
<script>
  document.getElementById('option-d-btn').addEventListener('click', function () {{
    document.getElementById('custom-box').style.display = 'block';
  }});
</script>
"""
    return body


def _turn_answer_text(turn: InterviewTurnRecord) -> str:
    """턴의 답을 사람이 읽는 텍스트로 바꾼다. D는 사용자가 입력한 원문 그대로."""
    if turn.selected_option == "D":
        return turn.custom_answer
    option_texts = {"A": turn.option_a, "B": turn.option_b, "C": turn.option_c}
    return option_texts.get(turn.selected_option or "", "")


def render_review_html(
    candidate: ScoutCandidate,
    session: InterviewSession,
    saved: bool = False,
    error: str | None = None,
    display_title: str | None = None,
) -> str:
    """STEP 8: 인터뷰 결과 확인 화면(화면, Phase 2 + Phase 3-2 perspective_summary 표시).

    5-20: display_title(한국어 표시용 제목)을 먼저 보여주고, 원문(candidate.title)은
    작은 글씨로 함께 보여준다.
    """
    banner = ""
    if saved:
        banner = '<div class="banner">저장되었습니다. TAK BRAIN KNOWLEDGE(pending)로 연결했습니다.</div>'
    if error:
        banner += f'<div class="error">오류: {escape(error)}</div>'

    # LLM이 3턴을 다 채우기 전에 sufficient=True로 판단해 조기 완료된 경우에만
    # 안내 문구를 보여준다(5-10 Phase 3-2 6번) - 항상 정확히 3턴이었던 Phase 2와
    # 달리, 사용자가 "왜 벌써 끝났지"라고 혼란스럽지 않도록 이유를 명시한다.
    early_completion_notice = ""
    if len(session.turns) < MAX_TURNS:
        early_completion_notice = (
            '<div class="banner">AI가 충분하다고 판단해 인터뷰를 마쳤습니다.</div>'
        )

    qa_blocks: list[str] = []
    for turn in session.turns:
        answer_text = _turn_answer_text(turn)
        is_direct = turn.selected_option == "D"
        qa_blocks.append(
            f"""
<div class="qa-block">
  <div class="qa-question">Q{turn.turn}. {escape(turn.question)}</div>
  <div class="qa-answer{' direct' if is_direct else ''}">{escape(answer_text)}</div>
</div>
"""
        )

    # perspective_summary는 LLM이 사용자의 실제 답변만 요약한 참고용 정보다(설계
    # 문서 6, 9번). fallback/실패로 비어 있으면 이 영역 자체를 생략한다 - KNOWLEDGE
    # 생성(finalize)에는 전혀 쓰이지 않는, review 화면 전용 보조 정보다.
    perspective_block = ""
    if session.perspective_summary.strip():
        perspective_block = f"""
<div class="qa-block">
  <div class="qa-question">티몽의 관점 요약</div>
  <div class="qa-answer">{escape(session.perspective_summary)}</div>
</div>
"""

    scout_id = escape(candidate.scout_id)
    heading = escape(display_title or candidate.title)
    original_line = ""
    if display_title and display_title != candidate.title:
        original_line = f'<div class="title-en">원문: {escape(candidate.title)}</div>'
    body = f"""
<a class="back" href="/">&larr; 오늘의 소재로 돌아가기</a>
<h1>{heading}</h1>
{original_line}
<div class="meta">
  출처: {escape(candidate.source_name or "알 수 없음")} ·
  <a href="{escape(candidate.source_url)}" target="_blank" rel="noopener">원문 보기</a>
</div>
{banner}
{early_completion_notice}
<h2 style="font-size:1rem;">인터뷰 결과</h2>
{"".join(qa_blocks)}
{perspective_block}
<div class="actions">
  <form method="post" action="/candidate/{scout_id}/finalize">
    <button class="btn primary" type="submit">이 내용으로 KNOWLEDGE 만들기</button>
  </form>
  <form method="post" action="/candidate/{scout_id}/restart">
    <button class="btn" type="submit">다시 답변하기</button>
  </form>
</div>
"""
    return body


def render_not_found_html(scout_id: str) -> str:
    return f"""
<a class="back" href="/">&larr; 오늘의 소재로 돌아가기</a>
<div class="error">소재를 찾을 수 없습니다: {escape(scout_id)}</div>
"""


# --- Threads 검수 화면 (5-11 Phase 2) ----------------------------------------


def render_threads_list_html(drafts: list[ThreadsPendingDraft]) -> str:
    """GET /threads - 미해결(pending/approved) Threads 초안 목록.

    Phase 1의 idempotency 설계상 미해결 draft는 보통 0~1개다. 정상적으로는 1개일
    때 do_GET에서 바로 상세 화면으로 리다이렉트하므로, 이 목록 화면은 "0개"이거나
    (드문 경우) "2개 이상"일 때만 실제로 보여진다.
    """
    if not drafts:
        body = """
<h1>Threads 검수</h1>
<div class="sub">검수할 초안이 없습니다.</div>
<p>매일 자동 생성되는 초안이 여기 나타납니다.</p>
"""
        return body

    cards = []
    for draft in drafts:
        label = _THREADS_STATUS_LABELS.get(draft.status, draft.status)
        title = draft.ai_rewritten_title or draft.original_title
        cards.append(
            f"""
<div class="card">
  <div class="card-top">
    <span class="status">{escape(label)}</span>
  </div>
  <div class="title">{escape(title)}</div>
  <div class="actions">
    <a class="btn primary" href="/threads/{escape(draft.content_id)}">검수하기</a>
  </div>
</div>
"""
        )

    body = f"""
<h1>Threads 검수</h1>
<div class="sub">검수 대기 중인 초안 {len(drafts)}건</div>
{"".join(cards)}
"""
    return body


# --- TAK MEDIA Human Review Dashboard (5-28) ---------------------------------
#
# KNOWLEDGE -> TAK MEDIA 9개 생성 -> ARCHIVE(5-27, data/tak_media_archive.json)
# 까지는 이미 구현되어 있다. 이 화면은 그 archive를 사람이 휴대폰에서 확인하고
# VALID 콘텐츠만 승인(review_status: unreviewed -> approved)할 수 있게 한다.
#
# 이 화면이 절대 하지 않는 것:
#   - 실제 Threads/YouTube/Naver 발행 (ThreadsClient/YouTubeClient/Naver 게시
#     코드를 이 화면에서 전혀 import/호출하지 않는다)
#   - Threads 이외 채널의 새 "발행 대기열" 파일 생성 (Blog/Shorts는 archive의
#     review_status만 approved로 바꾸는 것으로 끝난다 - 기존에 Blog/Shorts
#     전용 pending 저장소 자체가 없으므로 새로 만들지 않는다)
#   - Shorts MP4 렌더링 실행 (content_engine.shorts_renderer를 호출하지 않는다)
#
# platform == "threads"이면서 승인된 경우에만, 기존
# content_engine.threads_review.upsert_pending()을 그대로 재사용해 (새 저장
# 구조를 만들지 않고) status="pending"인 ThreadsPendingDraft를
# data/tak_threads_pending.json에 추가한다 - 이미 그 파일에 같은 content_id가
# 있으면(예: generate_threads_draft.py의 rotation이 먼저 만들었거나 이미
# 승인/발행까지 진행된 경우) 절대 덮어쓰지 않는다("기존 승인 상태를 임의로
# 바꾸지 않는다"). 이렇게 넘어간 draft는 기존 "/threads" 검수 화면에서 사람이
# 다시 한번 확인 후 최종 승인해야 실제 발행 후보(approved)가 된다 - 이 MEDIA
# 화면의 승인 버튼이 Threads 발행 승인을 대신하지 않는다.

_MEDIA_PLATFORM_LABELS: dict[str, str] = {"blog": "BLOG", "shorts": "SHORTS", "threads": "THREADS"}
_MEDIA_GENERATION_STATUS_LABELS: dict[str, str] = {
    "valid": "VALID",
    "rejected": "REJECTED",
    "error": "ERROR",
}
_MEDIA_REVIEW_STATUS_LABELS: dict[str, str] = {
    "unreviewed": "검수대기",
    "approved": "승인",
    "dismissed": "보류",
}

_MEDIA_PLATFORM_OPTIONS: tuple[tuple[str, str], ...] = (
    ("all", "전체"), ("blog", "Blog"), ("shorts", "Shorts"), ("threads", "Threads"),
)
_MEDIA_GENERATION_STATUS_OPTIONS: tuple[tuple[str, str], ...] = (
    ("all", "전체"), ("valid", "Valid"), ("rejected", "Rejected"), ("error", "Error"),
)
_MEDIA_REVIEW_STATUS_OPTIONS: tuple[tuple[str, str], ...] = (
    ("all", "전체"), ("unreviewed", "검수대기"), ("approved", "승인"), ("dismissed", "보류"),
)

_MEDIA_BODY_PREVIEW_LENGTH = 120


def filter_media_archive_records(
    records: list[MediaArchiveRecord],
    platform: str = "all",
    generation_status: str = "all",
    review_status: str = "all",
) -> list[MediaArchiveRecord]:
    """세 필터(platform/generation_status/review_status)를 모두 만족하는 항목만 남긴다.
    각 값이 "all"이면 그 축은 걸러내지 않는다. 기능은 단순한 AND 필터 하나뿐이다."""
    result = records
    if platform != "all":
        result = [record for record in result if record.platform == platform]
    if generation_status != "all":
        result = [record for record in result if record.generation_status == generation_status]
    if review_status != "all":
        result = [record for record in result if record.review_status == review_status]
    return result


def group_media_archive_records_by_knowledge(
    records: list[MediaArchiveRecord],
) -> list[tuple[str, list[MediaArchiveRecord]]]:
    """created_at 내림차순으로 정렬한 뒤 knowledge_id별로 묶는다.

    "KNOWLEDGE 1건당 9개 Draft가 한꺼번에 생성됐다"는 사실이 한눈에 보이도록 하기
    위한 그룹핑일 뿐, 정렬 기준 자체를 바꾸지 않는다 - 그룹의 순서는 그 그룹에서
    가장 최근인 항목(정렬 후 그룹의 첫 항목) 기준을 그대로 따른다.
    """
    ordered = sorted(records, key=lambda record: record.created_at, reverse=True)
    groups: dict[str, list[MediaArchiveRecord]] = {}
    order: list[str] = []
    for record in ordered:
        if record.knowledge_id not in groups:
            groups[record.knowledge_id] = []
            order.append(record.knowledge_id)
        groups[record.knowledge_id].append(record)
    return [(knowledge_id, groups[knowledge_id]) for knowledge_id in order]


def find_media_archive_record(archive_path: Path, content_id: str) -> MediaArchiveRecord | None:
    for record in load_archive(archive_path):
        if record.content_id == content_id:
            return record
    return None


# --- Downstream 상태 표시 (5-29) ----------------------------------------------
#
# 새 저장소를 만들지 않는다(docs/5-29_media_operational_pipeline.md 2장 C).
# 셋 다 기존 파일을 "읽기"만 해서 상태를 계산한다:
#   - Threads: data/tak_threads_pending.json의 ThreadsPendingDraft.status
#   - Blog:    data/blog_publish_log.json(PublishHistory)에 기록됐는지 여부
#   - Shorts:  data/shorts_scripts/<content_id>.json 파일 존재 여부(+ 참고용으로
#              data/shorts/<content_id>.mp4 존재 여부도 함께 읽는다 - 이 파일이
#              생기게 만드는 렌더링은 이 Dashboard가 절대 실행하지 않는다)

_MEDIA_NEXT_STEP_HINTS: dict[str, str] = {
    "blog": "Blog Publishing Pack을 생성할 수 있습니다 (scripts/generate_blog_publish_pack.py --from-archive).",
    "shorts": "ShortsScript가 자동 생성되었습니다. 실제 MP4 렌더링 여부는 사람이 별도로 결정합니다.",
    "threads": "Threads 검수 대기열로 이동되었습니다. /threads 화면에서 최종 승인해야 실제 발행 후보가 됩니다.",
}


def compute_media_downstream_status(record: MediaArchiveRecord, config: DashboardConfig) -> str:
    """승인 이후 이 레코드가 각 채널에서 실제로 어디까지 진행됐는지 읽기 전용으로
    계산한다. 이 함수는 어떤 파일도 쓰지 않는다."""
    if record.review_status != "approved":
        return "승인 전"

    if record.platform == "threads":
        draft = find_pending_draft(config.pending_path, record.content_id)
        if draft is None:
            return "승인됨 (대기열 생성 예정)"
        return _THREADS_STATUS_LABELS.get(draft.status, draft.status)

    if record.platform == "blog":
        history = PublishHistory(config.blog_history_path)
        if history.is_published(record.content_id):
            return "게시 기록됨"
        return "승인됨 (Pack 생성 가능)"

    if record.platform == "shorts":
        script_path = shorts_script_output_path(config.shorts_scripts_path, record.content_id)
        if not script_path.exists():
            return "승인됨 (Script 생성 가능)"
        # 6-13: YouTube 업로드는 이 상태 체인의 종결 상태다 - review_status=="approved"가
        # 곧 "게시됨"을 뜻하지 않는다는 원칙(6-13 지시 5장)을 그대로 따라, 실제
        # 업로드 이력(YouTubeUploadHistory, content_id로 연결)이 있을 때만 "YouTube
        # 업로드됨"을 보여준다 - MP4가 로컬에 렌더링됐다는 사실만으로는 게시됐다고
        # 표시하지 않는다.
        youtube_history = YouTubeUploadHistory(config.youtube_history_path)
        if youtube_history.is_published(record.content_id):
            return "YouTube 업로드됨"
        mp4_path = ROOT / "data" / "shorts" / f"{record.content_id}.mp4"
        if mp4_path.exists():
            return "Script 생성됨 (MP4 생성됨)"
        return "Script 생성됨 (MP4 미생성)"

    return ""


def handle_media_approve_submission(
    archive_path: Path,
    knowledge_path: Path,
    threads_pending_path: Path,
    content_id: str,
    shorts_scripts_path: Path | None = None,
) -> tuple[MediaArchiveRecord | None, str | None]:
    """POST /media/{content_id}/approve 처리(순수 로직, 서버 없이 테스트 가능).

    (갱신된 레코드 또는 None, 오류 메시지 또는 None)을 반환한다. 레코드가 아예
    없으면 (None, None)을 반환해 호출부가 404로 처리하게 한다.

    이미 approved인 레코드를 다시 승인 요청하면 그 레코드를 그대로(수정 없이)
    반환한다 - 에러도 아니고 중복 저장도 하지 않는 idempotent 동작이다("이미
    approved인 콘텐츠에는 중복 승인 버튼을 보여주지 않는다"는 UI 규칙의 방어적
    백업).

    5-29: platform=="threads"뿐 아니라 platform=="shorts"도 승인 시점에
    자동으로 downstream 파일(ShortsScript JSON)을 만든다 - 둘 다 "레코드
    1건 -> 파생 파일 1건"의 순수하고 멱등한 변환이라 승인 POST 안에서
    안전하게 실행할 수 있다(docs/5-29_media_operational_pipeline.md 4장
    "결정 1" 참고). Blog는 여러 레코드를 모아 매번 다시 선정하는 배치
    결과물이라 성격이 달라 이 함수에서 자동 연결하지 않는다 - 별도
    CLI(scripts/generate_blog_publish_pack.py --from-archive)로 남겨둔다.
    ``shorts_scripts_path``를 생략하면(``None``) Shorts 자동 생성 자체를
    건너뛴다 - 기존 호출부(있다면)와의 하위 호환을 위한 안전한 기본값이다.
    """
    record = find_media_archive_record(archive_path, content_id)
    if record is None:
        return None, None

    if record.review_status == "approved":
        return record, None

    if record.generation_status != "valid":
        return None, "VALID 상태의 콘텐츠만 승인할 수 있습니다."

    updated = replace(record, review_status="approved")
    upsert_archive(archive_path, [updated])

    if updated.platform == "threads" and find_pending_draft(threads_pending_path, content_id) is None:
        # 이미 같은 content_id의 pending/approved/published/failed draft가 있으면
        # (예: generate_threads_draft.py의 rotation이 먼저 만든 경우) 절대
        # 건드리지 않는다 - upsert_pending()은 무조건 덮어쓰므로, 새로 만들
        # 때만 호출한다.
        knowledge_by_id = {record.id: record for record in load_knowledge_records(knowledge_path)}
        knowledge = knowledge_by_id.get(updated.knowledge_id)
        new_draft = ThreadsPendingDraft(
            content_id=updated.content_id,
            knowledge_id=updated.knowledge_id,
            source_url=updated.source_url,
            evidence_unit_ids=updated.evidence_unit_ids,
            article_type=knowledge.article_type if knowledge else None,
            knowledge_type=knowledge.knowledge_type if knowledge else None,
            original_title=updated.original_title,
            original_body=updated.original_body,
            ai_rewritten_title=updated.final_title,
            ai_rewritten_body=updated.final_body,
            status="pending",
            created_at=utc_now(),
        )
        upsert_pending(threads_pending_path, new_draft)

    if updated.platform == "shorts" and shorts_scripts_path is not None:
        try:
            save_approved_shorts_script(updated, shorts_scripts_path)
        except ShortsAdapterError:
            # 조건(valid+approved)은 이미 위에서 확인했으므로 정상 경로에서는
            # 발생하지 않는다 - 혹시 모를 방어적 처리로, 승인 자체(review_status
            # 갱신)는 이미 저장이 끝났으므로 여기서 실패해도 승인을 되돌리지
            # 않는다(Script 생성은 사람이 CLI로 나중에 다시 시도할 수 있다).
            pass

    return updated, None


def _can_review_media_record(record: MediaArchiveRecord) -> bool:
    """수정/승인/보류가 모두 가능한 상태인지: generation_status가 VALID여야 하고
    (REJECTED/ERROR는 애초에 검증을 통과하지 못했으므로 사람이 텍스트만 고쳐서
    검증을 우회하게 두지 않는다), 아직 approved가 아니어야 한다(승인은 이
    화면에서 되돌릴 수 없는 종결 상태 - 승인 이후에는 이미 downstream으로
    넘어갔을 수 있으므로 그 뒤의 수정은 이 archive 레코드에 반영해도 의미가
    없다). dismissed는 unreviewed와 동일하게 "다시 검토 가능"으로 취급한다."""
    return record.generation_status == "valid" and record.review_status != "approved"


def handle_media_edit_submission(
    archive_path: Path, content_id: str, title: str, body: str
) -> tuple[MediaArchiveRecord | None, str | None]:
    """POST /media/{content_id}/edit 처리(순수 로직, 서버 없이 테스트 가능).

    original_title/original_body(생성 전 원본), rewritten_title/rewritten_body
    (AI 생성 결과)는 이 함수가 절대 건드리지 않는다 - edited_title/edited_body만
    갱신한다. 저장 후에는 review_status를 항상 "unreviewed"로 되돌려, 수정된
    내용이 다시 검토·승인 대상이 되게 한다(수정만으로 승인되지 않는다).
    """
    record = find_media_archive_record(archive_path, content_id)
    if record is None:
        return None, None

    if not _can_review_media_record(record):
        if record.review_status == "approved":
            return None, "이미 승인된 콘텐츠는 수정할 수 없습니다."
        return None, "VALID 상태의 콘텐츠만 수정할 수 있습니다."

    if not title.strip():
        return None, "제목을 입력해주세요."
    if not body.strip():
        return None, "본문을 입력해주세요."

    updated = replace(record, edited_title=title, edited_body=body, review_status="unreviewed")
    upsert_archive(archive_path, [updated])
    return updated, None


def handle_media_dismiss_submission(
    archive_path: Path, content_id: str
) -> tuple[MediaArchiveRecord | None, str | None]:
    """POST /media/{content_id}/dismiss 처리(순수 로직, 서버 없이 테스트 가능).

    데이터를 삭제하지 않는다 - review_status만 "dismissed"로 바꿔 저장한다.
    dismissed 상태에서도 _can_review_media_record()가 True를 반환하므로,
    나중에 다시 수정하거나 승인할 수 있다(완전히 되돌릴 수 있는 상태).
    """
    record = find_media_archive_record(archive_path, content_id)
    if record is None:
        return None, None

    if record.review_status == "approved":
        return None, "이미 승인된 콘텐츠는 보류할 수 없습니다."
    if record.generation_status != "valid":
        return None, "VALID 상태의 콘텐츠만 보류할 수 있습니다."

    updated = replace(record, review_status="dismissed")
    upsert_archive(archive_path, [updated])
    return updated, None


def _media_filter_query(overrides: dict[str, str]) -> str:
    return "&".join(f"{key}={value}" for key, value in overrides.items())


def _media_filter_row(
    param_name: str,
    options: tuple[tuple[str, str], ...],
    current: str,
    other_params: dict[str, str],
) -> str:
    links = []
    for value, label in options:
        params = {**other_params, param_name: value}
        active = " active" if value == current else ""
        links.append(
            f'<a class="filter-link{active}" href="/media?{_media_filter_query(params)}">{escape(label)}</a>'
        )
    return f'<div class="filter-row">{"".join(links)}</div>'


def render_media_filters_html(platform: str, generation_status: str, review_status: str) -> str:
    platform_row = _media_filter_row(
        "platform", _MEDIA_PLATFORM_OPTIONS, platform,
        {"generation_status": generation_status, "review_status": review_status},
    )
    generation_row = _media_filter_row(
        "generation_status", _MEDIA_GENERATION_STATUS_OPTIONS, generation_status,
        {"platform": platform, "review_status": review_status},
    )
    review_row = _media_filter_row(
        "review_status", _MEDIA_REVIEW_STATUS_OPTIONS, review_status,
        {"platform": platform, "generation_status": generation_status},
    )
    return f'<div class="filters">{platform_row}{generation_row}{review_row}</div>'


def _generation_label(record: MediaArchiveRecord) -> str:
    """6-06: production archive(콘텐츠 슬롯당 활성 레코드 1개)에 표시된 레코드는
    정의상 그 content_id의 "현재 활성/승격된" generation이다. generation_id가
    없으면(5-27 시절 레코드) legacy generation으로 표시한다 - KeyError 없이
    항상 문자열을 반환한다."""
    if record.generation_id:
        return f"세대 {record.generation_id} (활성)"
    return "레거시 생성 (generation_id 없음)"


def _media_card_html(record: MediaArchiveRecord, config: DashboardConfig) -> str:
    platform_label = _MEDIA_PLATFORM_LABELS.get(record.platform, record.platform.upper())
    generation_label = _MEDIA_GENERATION_STATUS_LABELS.get(record.generation_status, record.generation_status.upper())
    review_label = _MEDIA_REVIEW_STATUS_LABELS.get(record.review_status, record.review_status)
    downstream_label = compute_media_downstream_status(record, config)
    title = record.rewritten_title or record.original_title
    body_text = record.rewritten_body or record.original_body or ""
    preview = body_text[:_MEDIA_BODY_PREVIEW_LENGTH]
    if len(body_text) > _MEDIA_BODY_PREVIEW_LENGTH:
        preview += "…"

    return f"""
<div class="card">
  <div class="card-top">
    <span class="status">{escape(platform_label)}</span>
    <span class="status">{escape(generation_label)}</span>
    <span class="status">{escape(review_label)}</span>
  </div>
  <div class="sub">{escape(downstream_label)}</div>
  <div class="sub">{escape(_generation_label(record))}</div>
  <div class="title">{escape(title)}</div>
  <p class="body-preview">{escape(preview)}</p>
  <div class="actions">
    <a class="btn primary" href="/media/{escape(record.content_id)}">상세보기</a>
  </div>
</div>
"""


def render_media_list_html(
    records: list[MediaArchiveRecord],
    config: DashboardConfig,
    platform: str = "all",
    generation_status: str = "all",
    review_status: str = "all",
    approved: bool = False,
) -> str:
    """GET /media - TAK MEDIA archive 전체를 KNOWLEDGE별로 묶어 카드로 보여준다."""
    banner = '<div class="banner">승인되었습니다.</div>' if approved else ""
    filters_html = render_media_filters_html(platform, generation_status, review_status)

    if not records:
        return f"""
<h1>TAK MEDIA</h1>
{banner}
{filters_html}
<div class="sub">조건에 맞는 Draft가 없습니다.</div>
"""

    groups = group_media_archive_records_by_knowledge(records)
    groups_html = []
    for knowledge_id, group_records in groups:
        cards = "".join(_media_card_html(record, config) for record in group_records)
        groups_html.append(
            f"""
<div class="group-header">KNOWLEDGE: {escape(knowledge_id)} <span class="sub">({len(group_records)}건)</span></div>
{cards}
"""
        )

    body = f"""
<h1>TAK MEDIA</h1>
<div class="sub">총 {len(records)}건 · KNOWLEDGE {len(groups)}건</div>
{banner}
{filters_html}
{"".join(groups_html)}
"""
    return body


# --- MEDIA Generation Pool 검수 (6-07 읽기 전용 조회 -> 6-08 승인 기능 추가) ---
#
# 6-06이 만든 generation pool(같은 content_id의 여러 generation을 동시에 보존하는
# 별도 archive 파일)을 사람이 실제로 검수(승인/보류)할 수 있게 하는 화면이다.
# production archive(`/media`)와는 여전히 완전히 분리돼 있다:
#   - 이 화면의 승인/보류 액션은 generation pool 파일(record가 들어있는 그
#     파일)만 upsert_generation_archive()로 갱신한다 - production archive
#     경로를 아예 인자로 받지 않는 함수만 쓰므로 구조적으로 production archive를
#     건드릴 수 없다.
#   - promotion을 실행하는 버튼/링크는 여전히 없다
#     (scripts/promote_media_generation.py는 CLI 전용으로 남긴다 - 10장/6-08
#     보고서 참고. "승인"과 "production 반영"을 같은 클릭으로 묶지 않는다).
# 역할 구분(6-08 13장): `/media`는 이미 production archive에 들어온 MEDIA의
# 최종 검수, `/media/generations`는 production에 들어가기 전 generation
# 후보 검수. Generation Pool -> (사람 승인) -> Promotion(CLI) -> Production
# Archive -> 기존 `/media`라는 순서는 그대로 유지한다.


_GENERATION_POOL_GLOB = "tak_media_generation_*.json"


def discover_generation_pool_paths(data_dir: Path) -> tuple[Path, ...]:
    """``data_dir``에서 ``tak_media_generation_*.json`` 이름 규칙(6-05/6-06/6-07이
    이미 만든 관례, 12장)을 따르는 파일을 전부 찾아 정렬해 반환한다(6-08 11장:
    Dashboard를 실행할 때마다 --generation-archive를 일일이 지정하지 않아도
    되게 하기 위한 auto-discovery).

    production archive(``data/tak_media_archive.json``)는 이 패턴에 절대
    맞지 않는다 - 파일명이 ``tak_media_archive``로 시작하고 ``tak_media_generation``으로
    시작하지 않기 때문에 glob 패턴 자체가 구조적으로 그 파일을 제외한다(이
    함수는 그 사실에 의존할 뿐, 별도로 production archive 경로를 하드코딩해
    걸러내지 않는다 - 이름 규칙만 지키면 자동으로 안전하다).

    ``data_dir``가 없으면 빈 튜플을 반환한다(오류를 던지지 않는다 - Dashboard
    최초 실행 시 아직 어떤 generation도 만들어지지 않았을 수 있다).
    """
    if not data_dir.exists():
        return ()
    return tuple(sorted(data_dir.glob(_GENERATION_POOL_GLOB)))


def resolve_generation_archive_paths(
    explicit_paths: tuple[Path, ...], data_dir: Path
) -> tuple[Path, ...]:
    """CLI가 실제 사용할 generation pool 경로 목록을 결정한다.

    ``--generation-archive``를 하나 이상 명시했다면(``explicit_paths``가
    비어 있지 않으면) 그 목록을 그대로 쓴다(6-05 회귀 테스트 픽스처처럼 이름
    규칙을 따르지 않는 legacy 파일도 사람이 명시하면 볼 수 있어야 하므로).
    아무것도 지정하지 않았다면 ``discover_generation_pool_paths()``로 자동
    탐색한 결과를 쓴다. ``DashboardConfig``를 직접 생성하는 기존 테스트/호출부는
    이 함수를 거치지 않으므로(CLI 진입점인 main()에서만 호출) 전혀 영향받지
    않는다.
    """
    if explicit_paths:
        return explicit_paths
    return discover_generation_pool_paths(data_dir)


def load_generation_pool_records(paths: tuple[Path, ...]) -> list[MediaArchiveRecord]:
    """설정된 generation pool 파일들(config.generation_archive_paths)을 전부 읽어
    하나의 목록으로 합친다. 파일이 없거나 목록이 비어 있으면 빈 목록을 반환한다
    (load_archive() 자체가 이미 "파일 없으면 빈 목록"이므로 이 함수는 그 위에
    여러 경로를 합치는 역할만 한다)."""
    records: list[MediaArchiveRecord] = []
    for path in paths:
        records.extend(load_archive(path))
    return records


def group_generation_records_by_content_id(
    records: list[MediaArchiveRecord],
) -> list[tuple[str, list[MediaArchiveRecord]]]:
    """같은 content_id의 여러 generation을 나란히 비교할 수 있도록 content_id로
    묶는다(created_at 오름차순 - 오래된 generation부터 최신 순으로 보여준다)."""
    ordered = sorted(records, key=lambda record: record.created_at)
    groups: dict[str, list[MediaArchiveRecord]] = {}
    order: list[str] = []
    for record in ordered:
        if record.content_id not in groups:
            groups[record.content_id] = []
            order.append(record.content_id)
        groups[record.content_id].append(record)
    return [(content_id, groups[content_id]) for content_id in order]


_LEGACY_GENERATION_LABEL = "legacy"


def _generation_url_segment(generation_id: str | None) -> str:
    """URL 경로에 쓸 generation_id 세그먼트. generation_id가 없는(5-27/6-05
    시절) legacy 레코드는 "legacy"라는 고정 문자열로 표현한다 - 빈 문자열은
    URL 경로 세그먼트로 쓸 수 없기 때문이다. 실제 매칭은
    _generation_id_from_url_segment()가 다시 None으로 되돌려 수행한다."""
    return generation_id or _LEGACY_GENERATION_LABEL


def _generation_id_from_url_segment(segment: str) -> str | None:
    return None if segment == _LEGACY_GENERATION_LABEL else segment


def group_generation_records_by_knowledge_and_generation(
    records: list[MediaArchiveRecord],
) -> list[tuple[tuple[str, str | None], list[MediaArchiveRecord]]]:
    """(knowledge_id, generation_id) 쌍으로 묶는다 - "이 KNOWLEDGE의 이번 생성
    시도"가 검수·전체 승인의 기준 단위가 되도록 하기 위함이다(6-08 7장 "generation
    단위 전체 승인"). 서로 다른 generation은 이 키가 다르므로 절대 섞이지 않는다
    (같은 knowledge_id라도 generation_id가 다르면 별도 그룹)."""
    ordered = sorted(records, key=lambda record: record.created_at)
    groups: dict[tuple[str, str | None], list[MediaArchiveRecord]] = {}
    order: list[tuple[str, str | None]] = []
    for record in ordered:
        key = (record.knowledge_id, record.generation_id)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(record)
    return [(key, groups[key]) for key in order]


_GENERATION_PLATFORM_ORDER = ("blog", "shorts", "threads")


def group_records_by_platform(records: list[MediaArchiveRecord]) -> list[tuple[str, list[MediaArchiveRecord]]]:
    """platform별로 접어서 볼 수 있도록 묶는다(6-08 4장). blog/shorts/threads
    순서를 우선하고, 그 외 platform 값이 있다면 알파벳 순으로 뒤에 붙인다."""
    by_platform: dict[str, list[MediaArchiveRecord]] = {}
    for record in records:
        by_platform.setdefault(record.platform, []).append(record)
    ordered_platforms = [p for p in _GENERATION_PLATFORM_ORDER if p in by_platform]
    ordered_platforms += sorted(p for p in by_platform if p not in _GENERATION_PLATFORM_ORDER)
    return [(platform, by_platform[platform]) for platform in ordered_platforms]


def _can_review_generation_record(record: MediaArchiveRecord) -> bool:
    """generation pool 레코드가 승인/보류 대상인지 - production `/media`의
    ``_can_review_media_record()``와 정확히 같은 기준(REJECTED/ERROR는 애초에
    검증 실패이므로 승인 대상이 아니고, 이미 approved인 것은 다시 누를 필요가
    없다). 새 상태값을 만들지 않고 기존 review_status enum
    (unreviewed/approved/dismissed)만 그대로 재사용한다(6-08 14장)."""
    return record.generation_status == "valid" and record.review_status != "approved"


def _generation_pool_card_html(record: MediaArchiveRecord) -> str:
    platform_label = _MEDIA_PLATFORM_LABELS.get(record.platform, record.platform.upper())
    generation_label = _MEDIA_GENERATION_STATUS_LABELS.get(record.generation_status, record.generation_status.upper())
    review_label = _MEDIA_REVIEW_STATUS_LABELS.get(record.review_status, record.review_status)
    title = record.rewritten_title or record.original_title
    body_text = record.rewritten_body or record.original_body or ""
    generation_segment = _generation_url_segment(record.generation_id)

    validation_html = ""
    if record.validation_errors:
        items = "".join(f"<li>{escape(reason)}</li>" for reason in record.validation_errors)
        validation_html = f'<div class="sub">validation_errors:</div><ul class="sub">{items}</ul>'

    actions_html = ""
    if _can_review_generation_record(record):
        actions_html = f"""
  <div class="actions">
    <a class="btn" href="/media/generations/record/{escape(record.content_id)}/{escape(generation_segment)}/edit">수정</a>
    <form method="post" action="/media/generations/record/{escape(record.content_id)}/{escape(generation_segment)}/approve" style="display:inline;">
      <button class="btn primary" type="submit">승인</button>
    </form>
    <form method="post" action="/media/generations/record/{escape(record.content_id)}/{escape(generation_segment)}/dismiss" style="display:inline;">
      <button class="btn ghost" type="submit">보류</button>
    </form>
  </div>
"""

    return f"""
<div class="card">
  <div class="card-top">
    <span class="status">{escape(platform_label)}</span>
    <span class="status">{escape(generation_label)}</span>
    <span class="status">{escape(review_label)}</span>
  </div>
  <div class="sub">content_id: {escape(record.content_id)}</div>
  <div class="sub">generation_id: {escape(record.generation_id or "(legacy, 없음)")}</div>
  <div class="sub">created_at: {escape(record.created_at)}</div>
  <div class="sub">출처: <a href="{escape(record.source_url)}" target="_blank" rel="noopener">{escape(record.source_url)}</a></div>
  <div class="title">{escape(title)}</div>
  <p class="body-block">{escape(body_text)}</p>
  {validation_html}
  {actions_html}
</div>
"""


def summarize_generation_reviews(records: list[MediaArchiveRecord]) -> dict[str, int]:
    """generation 1건(또는 그룹)의 검수 현황 요약(6-09 14장) - production
    archive는 전혀 읽지 않는다. 이 generation pool 레코드만 센다."""
    return {
        "total": len(records),
        "valid": sum(1 for record in records if record.generation_status == "valid"),
        "rejected": sum(1 for record in records if record.generation_status == "rejected"),
        "error": sum(1 for record in records if record.generation_status == "error"),
        "approved": sum(1 for record in records if record.review_status == "approved"),
        "unreviewed": sum(1 for record in records if record.review_status == "unreviewed"),
        "dismissed": sum(1 for record in records if record.review_status == "dismissed"),
    }


def summarize_platform_approval(records: list[MediaArchiveRecord]) -> list[tuple[str, int, int]]:
    """platform별 (platform, approved_count, total_count) 목록(6-09 15장)."""
    return [
        (platform, sum(1 for record in platform_records if record.review_status == "approved"), len(platform_records))
        for platform, platform_records in group_records_by_platform(records)
    ]


def _generation_summary_html(records: list[MediaArchiveRecord]) -> str:
    summary = summarize_generation_reviews(records)
    platform_line = " · ".join(
        f"{escape(_MEDIA_PLATFORM_LABELS.get(platform, platform.upper()))} {approved}/{total}"
        for platform, approved, total in summarize_platform_approval(records)
    )
    error_segment = ""
    if summary["rejected"] or summary["error"]:
        error_segment = f" · Rejected {summary['rejected']} · Error {summary['error']}"
    return f"""
  <div class="sub">총 {summary['total']} · Valid {summary['valid']} · Approved {summary['approved']} · Unreviewed {summary['unreviewed']} · Dismissed {summary['dismissed']}{error_segment}</div>
  <div class="sub">{platform_line}</div>
"""


def load_knowledge_titles(knowledge_path: Path) -> dict[str, str]:
    """generation pool 화면(6-11 8장)에서 "이 MEDIA가 어떤 KNOWLEDGE에서
    나왔는가"를 사람이 바로 알 수 있게, knowledge_id -> title 매핑만 읽기
    전용으로 만든다. ``data/tak_brain_knowledge.json``을 이 함수가 쓰지
    않는다 - ``load_knowledge_records()``(기존 함수, 5-28부터 이미
    render_media_detail_html이 같은 목적으로 써왔다)를 그대로 재사용한다."""
    return {record.id: record.title for record in load_knowledge_records(knowledge_path)}


def _generation_group_header_label(knowledge_id: str, knowledge_titles: dict[str, str] | None) -> str:
    """generation 그룹 헤더에 보여줄 "KNOWLEDGE: ..." 라벨(6-11 8장).

    사람이 이 MEDIA가 어떤 KNOWLEDGE에서 생성됐는지 knowledge_id만 보고는
    바로 알기 어렵다는 문제를 최소한으로 보완한다 - ``knowledge_titles``
    (knowledge_id -> title 매핑)에 제목이 있으면 "제목 (knowledge_id)" 형태로,
    없으면(캐시를 안 넘겼거나 그 KNOWLEDGE를 찾지 못했으면) 기존처럼
    knowledge_id만 그대로 보여준다 - 이 함수를 호출하지 않는 기존 코드/테스트와
    100% 하위 호환.
    """
    title = (knowledge_titles or {}).get(knowledge_id)
    if title:
        return f"{title} ({knowledge_id})"
    return knowledge_id


def _generation_group_html(
    knowledge_id: str,
    generation_id: str | None,
    group_records: list[MediaArchiveRecord],
    knowledge_titles: dict[str, str] | None = None,
) -> str:
    generation_segment = _generation_url_segment(generation_id)
    reviewable_count = sum(1 for record in group_records if _can_review_generation_record(record))
    summary_html = _generation_summary_html(group_records)
    knowledge_label = _generation_group_header_label(knowledge_id, knowledge_titles)

    approve_all_html = ""
    if reviewable_count > 0:
        approve_all_html = f"""
  <form method="post" action="/media/generations/generation/{escape(generation_segment)}/approve-all" style="margin-top:8px;">
    <button class="btn primary" type="submit">이 generation 전체 승인 ({reviewable_count}건)</button>
  </form>
"""

    platform_sections = []
    for platform, platform_records in group_records_by_platform(group_records):
        platform_label = _MEDIA_PLATFORM_LABELS.get(platform, platform.upper())
        cards = "".join(_generation_pool_card_html(record) for record in platform_records)
        platform_sections.append(
            f"""
<details open>
  <summary>{escape(platform_label)} ({len(platform_records)}건)</summary>
  {cards}
</details>
"""
        )

    return f"""
<div class="group-header">KNOWLEDGE: {escape(knowledge_label)}
  <span class="sub">generation: {escape(generation_id or "(legacy, generation_id 없음)")} ({len(group_records)}건)</span>
  {summary_html}
  {approve_all_html}
</div>
{"".join(platform_sections)}
"""


def render_generation_pool_html(
    records: list[MediaArchiveRecord],
    knowledge_id_filter: str | None = None,
    notice: str | None = None,
    knowledge_titles: dict[str, str] | None = None,
) -> str:
    """GET /media/generations 또는 /media/generations/<knowledge_id> 본문.

    Production archive는 이 화면 어디에서도 읽거나 쓰지 않는다 - 승인/보류
    액션은 이 레코드가 들어있는 generation pool 파일만 갱신한다. promotion
    버튼/링크는 여기 없다 - scripts/promote_media_generation.py를 CLI로
    직접 실행해야 한다.

    ``knowledge_titles``(6-11 8장, knowledge_id -> title 매핑)를 넘기면 각
    그룹 헤더에 "KNOWLEDGE: <제목> (<knowledge_id>)"를 보여준다 - 넘기지
    않으면(기존 호출부/테스트 호환) 이전처럼 knowledge_id만 보여준다. 이
    매핑은 읽기 전용으로만 쓰인다 - data/tak_brain_knowledge.json을 이 함수가
    직접 쓰지 않는다(호출부가 이미 읽어서 넘겨준 dict일 뿐이다).
    """
    if knowledge_id_filter:
        records = [record for record in records if record.knowledge_id == knowledge_id_filter]

    heading = "TAK MEDIA Generation Pool"
    if knowledge_id_filter:
        heading += f" — {knowledge_id_filter}"

    notice_html = ""
    if notice == "approved":
        notice_html = '<div class="banner">승인되었습니다(generation pool에만 반영 - production archive는 변경되지 않았습니다).</div>'
    elif notice == "dismissed":
        notice_html = '<div class="banner">보류되었습니다.</div>'
    elif notice == "approved-all":
        notice_html = '<div class="banner">generation 전체를 승인했습니다(generation pool에만 반영 - production archive는 변경되지 않았습니다).</div>'
    elif notice == "saved":
        notice_html = (
            '<div class="banner">수정 내용이 저장되었습니다 - 검토 상태가 "검토대기(unreviewed)"로 '
            "돌아갔습니다. production archive는 변경되지 않았습니다.</div>"
        )

    disclaimer = (
        '<div class="sub">승인/보류는 이 generation pool 파일에만 반영됩니다 - production archive'
        "(data/tak_media_archive.json)는 이 화면에서 절대 바뀌지 않습니다. Production 반영은 "
        "scripts/promote_media_generation.py를 사람이 CLI로 직접 실행해야 합니다.</div>"
    )

    if not records:
        return f"""
<a class="back" href="/media">&larr; TAK MEDIA로</a>
<h1>{escape(heading)}</h1>
{notice_html}
{disclaimer}
<div class="sub">표시할 generation이 없습니다(설정된 generation pool 파일이 없거나 비어 있음).</div>
"""

    generation_groups = group_generation_records_by_knowledge_and_generation(records)
    groups_html = "".join(
        _generation_group_html(knowledge_id, generation_id, group_records, knowledge_titles)
        for (knowledge_id, generation_id), group_records in generation_groups
    )

    return f"""
<a class="back" href="/media">&larr; TAK MEDIA로</a>
<h1>{escape(heading)}</h1>
{notice_html}
{disclaimer}
<div class="sub">총 generation record {len(records)}건 · KNOWLEDGE×generation 조합 {len(generation_groups)}개</div>
{groups_html}
"""


def find_generation_pool_record(
    paths: tuple[Path, ...], content_id: str, generation_id: str | None
) -> tuple[MediaArchiveRecord | None, Path | None]:
    """설정된 generation pool 파일들 중, 이 (content_id, generation_id) 쌍과
    정확히 일치하는 레코드를 찾는다. 찾으면 (레코드, 그 레코드가 들어있던 파일
    경로)를 반환한다 - 승인/보류 액션이 갱신을 정확히 그 파일에만 쓰기 위함이다.
    """
    for path in paths:
        record = find_generation_record(path, content_id, generation_id)
        if record is not None:
            return record, path
    return None, None


def render_generation_edit_html(record: MediaArchiveRecord, error: str | None = None) -> str:
    """GET /media/generations/record/{content_id}/{generation_id}/edit - 제목/본문
    수정 화면(6-10).

    production ``/media`` 상세 화면의 편집 폼(render_media_detail_html의 ⑥ 사람
    검수 상태 섹션)과 정확히 같은 값 우선순위(edited -> rewritten -> original)와
    같은 가시성 규칙(``_can_review_generation_record`` - VALID이고 아직 approved가
    아닐 때만 폼을 보여준다)을 그대로 재사용한다. 다만 이 화면은 generation pool
    레코드 1건의 편집 폼만 보여준다 - production ``/media`` 상세의 나머지 섹션
    (①~⑤/⑦)은 이미 ``/media/generations`` 목록 카드에 표시되므로 새로 만들지
    않는다(11장: 대규모 UI 개편 금지).
    """
    error_banner = f'<div class="error">{escape(error)}</div>' if error else ""
    generation_segment = _generation_url_segment(record.generation_id)
    platform_label = _MEDIA_PLATFORM_LABELS.get(record.platform, record.platform.upper())
    review_label = _MEDIA_REVIEW_STATUS_LABELS.get(record.review_status, record.review_status)

    if _can_review_generation_record(record):
        title_value = record.edited_title if record.edited_title is not None else (record.rewritten_title or record.original_title)
        body_value = record.edited_body if record.edited_body is not None else (record.rewritten_body or record.original_body or "")
        action = f"/media/generations/record/{escape(record.content_id)}/{escape(generation_segment)}/edit"
        form_html = f"""
<form method="post" action="{action}">
  <p><strong>제목 수정</strong></p>
  <input type="text" name="title" value="{escape(title_value)}"
    style="width:100%; max-width:560px; padding:10px; border-radius:8px; border:1px solid #ccc; font-size:0.95rem;">
  <p style="margin-top:12px;"><strong>본문 수정</strong></p>
  <textarea name="body" style="min-height:220px;">{escape(body_value)}</textarea>
  <div class="actions" style="margin-top:14px;">
    <button class="btn primary" type="submit">저장</button>
  </div>
</form>
<p class="sub" style="margin-top:10px;">저장하면 검토 상태가 "검토대기(unreviewed)"로 돌아갑니다 - production archive는 변경되지 않습니다.</p>
"""
    elif record.review_status == "approved":
        form_html = "<p>이미 승인된 generation은 이 화면에서 더 이상 수정할 수 없습니다.</p>"
    else:
        form_html = "<p>VALID 상태의 generation만 수정할 수 있습니다.</p>"

    return f"""
<a class="back" href="/media/generations">&larr; 목록으로</a>
<h1>Generation 수정</h1>
<div class="card-top">
  <span class="status">{escape(platform_label)}</span>
  <span class="status">{escape(review_label)}</span>
</div>
<div class="sub">content_id: {escape(record.content_id)}</div>
<div class="sub">generation_id: {escape(record.generation_id or "(legacy, 없음)")}</div>
{error_banner}
{form_html}
"""


def handle_generation_review_submission(
    paths: tuple[Path, ...], content_id: str, generation_id: str | None, new_review_status: str
) -> tuple[MediaArchiveRecord | None, str | None]:
    """POST /media/generations/record/{content_id}/{generation_id}/approve|dismiss 처리.

    review_status만 바꾼다. 이 함수는 production archive 경로를 인자로 받지
    않으므로 구조적으로 production archive를 건드릴 수 없다 - 오직 이 레코드가
    들어있던 그 generation pool 파일만 upsert_generation_archive()로 갱신한다.
    """
    record, path = find_generation_pool_record(paths, content_id, generation_id)
    if record is None or path is None:
        return None, None

    if record.generation_status != "valid":
        return None, "VALID 상태의 generation만 검토할 수 있습니다."
    if record.review_status == "approved":
        return record, None  # 이미 승인됨 - idempotent, 에러 아님(기존 /media 승인과 동일한 관례)

    updated = replace(record, review_status=new_review_status)
    upsert_generation_archive(path, [updated])
    return updated, None


def handle_generation_edit_submission(
    paths: tuple[Path, ...], content_id: str, generation_id: str | None, title: str, body: str
) -> tuple[MediaArchiveRecord | None, str | None]:
    """POST /media/generations/record/{content_id}/{generation_id}/edit 처리(6-10,
    순수 로직, 서버 없이 테스트 가능).

    production ``/media``의 ``handle_media_edit_submission()``과 정확히 같은 정책을
    ``(content_id, generation_id)`` 복합 키 위에서 적용한다(4장: "기존 /media의 편집
    의미를 그대로 따른다"): original_*/rewritten_*는 절대 건드리지 않고
    edited_title/edited_body만 갱신하며, 저장 후에는 review_status를 항상
    "unreviewed"로 되돌린다 - 사람이 승인했거나(approved) 보류했던(dismissed)
    콘텐츠를 수정하면 다시 검토 대상이 되어야 하기 때문이다.

    ``_can_review_generation_record()``를 그대로 재사용하므로(10장: "기존 정책과
    다르면 임의로 바꾸지 않는다"), 이미 approved인 레코드는 - production ``/media``와
    동일하게 - 수정이 아예 차단된다(승인은 이 화면에서 되돌릴 수 없는 종결 상태).
    REJECTED/ERROR도 검증을 통과하지 못했으므로 텍스트만 고쳐 승인을 우회할 수 없다.

    이 함수는 production archive 경로를 아예 인자로 받지 않으므로 구조적으로
    production archive를 건드릴 수 없다 - 오직 이 (content_id, generation_id)가
    들어있던 그 generation pool 파일만 ``upsert_generation_archive()``로 갱신한다.
    """
    record, path = find_generation_pool_record(paths, content_id, generation_id)
    if record is None or path is None:
        return None, None

    if not _can_review_generation_record(record):
        if record.review_status == "approved":
            return None, "이미 승인된 콘텐츠는 수정할 수 없습니다."
        return None, "VALID 상태의 콘텐츠만 수정할 수 있습니다."

    if not title.strip():
        return None, "제목을 입력해주세요."
    if not body.strip():
        return None, "본문을 입력해주세요."

    updated = replace(record, edited_title=title, edited_body=body, review_status="unreviewed")
    upsert_generation_archive(path, [updated])
    return updated, None


def handle_generation_approve_all_submission(
    paths: tuple[Path, ...], generation_id: str | None
) -> tuple[list[MediaArchiveRecord], str | None]:
    """POST /media/generations/generation/{generation_id}/approve-all 처리.

    이 generation_id를 가진 모든 레코드 중 ``_can_review_generation_record()``가
    True인 것(VALID 상태이고 아직 approved가 아닌 것)만 approved로 바꾼다.
    REJECTED/ERROR 레코드는 "전체 승인"을 눌러도 승인되지 않는다 - 애초에
    승인이 promotion 가능성과 무관한 무의미한 상태 전이이기 때문이다(REJECTED는
    scripts/promote_media_generation.py가 어차피 다시 막는다).

    generation_id가 여러 파일에 걸쳐 있어도(이론상으로만 가능 - 실제로는
    archive_generation_report() 한 번의 실행이 만든 모든 레코드가 항상 같은
    파일에 저장된다) 전부 처리한다. 이 함수도 production archive 경로를
    전혀 받지 않는다.
    """
    updated_records: list[MediaArchiveRecord] = []
    found_any = False
    for path in paths:
        records = load_archive(path)
        matching = [record for record in records if record.generation_id == generation_id]
        if not matching:
            continue
        found_any = True
        to_write = [
            replace(record, review_status="approved") for record in matching if _can_review_generation_record(record)
        ]
        updated_records.extend(to_write)
        if to_write:
            upsert_generation_archive(path, to_write)

    if not found_any:
        return [], "generation_id를 찾을 수 없습니다."
    return updated_records, None


_MEDIA_NOTICE_MESSAGES: dict[str, str] = {
    "approved": "승인되었습니다.",
    "saved": "수정 내용이 저장되었습니다.",
    "dismissed": "보류되었습니다.",
}


def render_media_detail_html(
    record: MediaArchiveRecord,
    knowledge: KnowledgeRecord | None,
    config: DashboardConfig,
    notice: str | None = None,
) -> str:
    """GET /media/{content_id} - Draft 1건의 전체 정보.

    VALID이고 아직 approved가 아닌 동안(``_can_review_media_record``)에만 제목/본문
    수정 폼과 [승인]/[보류] 버튼을 보여준다 - REJECTED/ERROR는 애초에 검증을 통과하지
    못했으므로 텍스트만 고쳐서 승인으로 우회할 수 없고, 이미 approved인 것은
    downstream으로 넘어간 종결 상태라 더 이상 이 화면에서 바꿀 수 없다.
    """
    platform_label = _MEDIA_PLATFORM_LABELS.get(record.platform, record.platform.upper())
    generation_label = _MEDIA_GENERATION_STATUS_LABELS.get(record.generation_status, record.generation_status.upper())
    review_label = _MEDIA_REVIEW_STATUS_LABELS.get(record.review_status, record.review_status)

    message = _MEDIA_NOTICE_MESSAGES.get(notice or "")
    banner = f'<div class="banner">{escape(message)}</div>' if message else ""

    can_review = _can_review_media_record(record)

    if record.validation_errors:
        validation_html = "<ul>" + "".join(f"<li>{escape(reason)}</li>" for reason in record.validation_errors) + "</ul>"
    elif record.error_message:
        validation_html = f"<p>{escape(record.error_message)}</p>"
    else:
        validation_html = "<p>(없음)</p>"

    source_title = knowledge.title if knowledge is not None else "(KNOWLEDGE를 찾을 수 없습니다)"
    source_url = knowledge.source_url if knowledge is not None else record.source_url

    edited_notice = ""
    if record.edited_title is not None or record.edited_body is not None:
        edited_notice = (
            '<div class="banner">사람이 수정한 내용이 있습니다. '
            "승인 시 아래 ⑥ 수정 영역의 내용이 최종 콘텐츠로 사용됩니다.</div>"
        )

    review_section = ""
    if can_review:
        title_value = record.edited_title if record.edited_title is not None else (record.rewritten_title or "")
        body_value = record.edited_body if record.edited_body is not None else (record.rewritten_body or "")
        review_section = f"""
<form method="post" action="/media/{escape(record.content_id)}/edit">
  <p><strong>제목 수정</strong></p>
  <input type="text" name="title" value="{escape(title_value)}"
    style="width:100%; max-width:560px; padding:10px; border-radius:8px; border:1px solid #ccc; font-size:0.95rem;">
  <p style="margin-top:12px;"><strong>본문 수정</strong></p>
  <textarea name="body" style="min-height:220px;">{escape(body_value)}</textarea>
  <div class="actions" style="margin-top:14px;">
    <button class="btn primary" type="submit">저장</button>
  </div>
</form>
<div class="actions" style="margin-top:14px;">
  <form method="post" action="/media/{escape(record.content_id)}/approve">
    <button class="btn primary" type="submit">승인</button>
  </form>
  <form method="post" action="/media/{escape(record.content_id)}/dismiss">
    <button class="btn ghost" type="submit">보류</button>
  </form>
</div>
"""
    elif record.review_status == "approved":
        review_section = (
            "<p>이미 승인되어 다음 단계로 이동했습니다 - 이 화면에서는 더 이상 수정할 수 없습니다.</p>"
            f'<p class="body-block">최종 확정 제목: {escape(record.final_title)}</p>'
            f'<p class="body-block">최종 확정 본문: {escape(record.final_body)}</p>'
        )

    body = f"""
<a class="back" href="/media">&larr; 목록으로</a>
<h1>TAK MEDIA 상세</h1>
<div class="card-top">
  <span class="status">{escape(platform_label)}</span>
  <span class="status">{escape(generation_label)}</span>
  <span class="status">{escape(review_label)}</span>
</div>
{banner}

<h2>① KNOWLEDGE</h2>
<div class="meta">knowledge_id: {escape(record.knowledge_id)}</div>
<div class="meta">source title: {escape(source_title)}</div>
<div class="meta">source URL: <a href="{escape(source_url)}" target="_blank" rel="noopener">{escape(source_url)}</a></div>

<h2>② 원본 Draft</h2>
<div class="title">{escape(record.original_title)}</div>
<p class="body-block">{escape(record.original_body)}</p>

<h2>③ AI 생성 결과</h2>
<div class="title">{escape(record.rewritten_title or "(없음)")}</div>
<p class="body-block">{escape(record.rewritten_body or "(없음)")}</p>
{edited_notice}

<h2>④ 검증 결과</h2>
<div class="meta">generation_status: {escape(generation_label)}</div>
{validation_html}

<h2>⑤ 생성 정보</h2>
<div class="meta">created_at: {escape(record.created_at)}</div>
<div class="meta">platform: {escape(platform_label)}</div>
<div class="meta">content_id: {escape(record.content_id)}</div>
<div class="meta">generation: {escape(_generation_label(record))}</div>

<h2>⑥ 사람 검수 상태</h2>
<div class="meta">review_status: {escape(review_label)}</div>
{review_section}

<h2>⑦ Downstream 상태</h2>
<div class="meta">현재 상태: {escape(compute_media_downstream_status(record, config))}</div>
{f'<div class="sub">다음 단계: {escape(_MEDIA_NEXT_STEP_HINTS.get(record.platform, ""))}</div>' if record.review_status == "approved" and record.platform in _MEDIA_NEXT_STEP_HINTS else ""}
"""
    return body


# --- Performance Dashboard (6-01 MVP + 6-02 시계열 추이) -----------------------
#
# /media가 승인/수정 액션을 갖는 것과 달리 이 화면은 순수 읽기 전용이다 - 어떤
# POST 라우트도 없고, 이 함수는 어떤 파일도 쓰지 않는다. 실제 성과 수집(API
# 호출/수동 입력 저장)은 scripts/collect_performance.py가 별도로 담당한다.
#
# 6-02: content_id별 "가장 최근 스냅샷"만 보여주던 6-01 MVP에, 이미 저장소에
# 쌓여 있던 시계열 데이터를 활용한 추이를 추가했다. 대형 차트 라이브러리나 새
# JS 프레임워크는 추가하지 않는다 - content_engine.performance.summary가 만든
# 순수 텍스트(sparkline 형태 문자열 + 변화량 dict)를 그대로 HTML에 얹을 뿐이다.


def _metrics_text(metrics: dict[str, int]) -> str:
    return " · ".join(f"{name} {value:,}" for name, value in sorted(metrics.items())) or "(수집된 지표 없음)"


def _delta_text(delta: dict[str, int]) -> str:
    if not delta:
        return "(비교할 이전 값 없음)"
    return " · ".join(f"{name} {value:+,}" for name, value in delta.items())


def _performance_row_html(
    summary: ContentPerformanceSummary, archive_by_content_id: dict[str, MediaArchiveRecord]
) -> str:
    latest = summary.latest
    archived = archive_by_content_id.get(summary.content_id)
    title = latest.title or (archived.final_title if archived is not None else "") or "(제목 없음)"

    baseline_warning = ""
    if summary.baseline_is_migration:
        baseline_warning = (
            '<div class="sub">⚠️ 최초 값이 실제 성과가 아니라 기존 발행 이력에서 옮긴 baseline'
            "(source=migration_baseline)입니다 - 아래 변화량을 실제 성과 비교의 기준점으로"
            " 오해하지 마세요.</div>"
        )

    trend_html = ""
    if summary.snapshot_count >= 2:
        headline_metric = pick_headline_metric(summary.history)
        if headline_metric:
            trend_text = render_text_trend(list(summary.history), headline_metric)
            if trend_text:
                trend_html = f'<div class="meta">{escape(headline_metric)} 추이: {escape(trend_text)}</div>'

    return f"""
<div class="card">
  <div class="card-top">
    <span class="status">{escape(summary.platform)}</span>
    <span class="sub">source: {escape(latest.source)}</span>
    <span class="sub">snapshot {summary.snapshot_count}건</span>
  </div>
  <div class="title">{escape(title)}</div>
  <div class="meta">content_id: {escape(summary.content_id)} · knowledge_id: {escape(latest.knowledge_id)}</div>
  <div class="meta">발행: {escape(_format_published_at(latest.published_at))} · 최근 수집: {escape(_format_published_at(latest.metric_collected_at))}</div>
  <div class="body-preview">최근 metrics: {escape(_metrics_text(latest.metrics))}</div>
  {f'<div class="body-preview">이전 metrics: {escape(_metrics_text(summary.previous.metrics))}</div>' if summary.previous is not None else ''}
  {trend_html}
  <div class="meta">최초 대비 변화량: {escape(_delta_text(summary.metric_delta()))}</div>
  {baseline_warning}
</div>
"""


def render_performance_list_html(
    summaries: list[ContentPerformanceSummary],
    archive_by_content_id: dict[str, MediaArchiveRecord],
) -> str:
    """GET /performance - content_id별 성과 시계열 요약을 읽기 전용으로 보여준다."""
    if not summaries:
        return """
<h1>Performance</h1>
<div class="sub">아직 수집된 성과 데이터가 없습니다. scripts/collect_performance.py로 수집해야 여기에 표시됩니다.</div>
"""

    ordered = sorted(summaries, key=lambda s: s.latest.metric_collected_at, reverse=True)
    rows = "".join(_performance_row_html(summary, archive_by_content_id) for summary in ordered)
    return f"""
<h1>Performance</h1>
<div class="sub">총 {len(ordered)}건 (content_id별 시계열 요약 - 최근 수집 순)</div>
{rows}
"""


def render_threads_review_html(
    draft: ThreadsPendingDraft,
    error: str | None = None,
    submitted_title: str | None = None,
    submitted_body: str | None = None,
) -> str:
    """GET /threads/{content_id} - status == "pending"일 때만 보여주는 검수/편집 화면.

    최소 UX 10항목을 전부 화면에 표시한다: 상태, AI 제목, AI 본문, 원본 제목,
    source_url, KNOWLEDGE ID, 버튼 2개, 제목/본문 입력창. 그 외 내부 정보
    (원본 본문, evidence_unit_ids 등)는 <details>로 접어 기본 화면을 단순하게
    유지한다.
    """
    error_banner = f'<div class="error">{escape(error)}</div>' if error else ""

    # 유효성 검사 실패로 다시 렌더링할 때는 사용자가 방금 입력한 값을 그대로
    # 입력창에 남겨서 다시 타이핑하지 않게 한다.
    title_value = submitted_title if submitted_title is not None else draft.ai_rewritten_title
    body_value = submitted_body if submitted_body is not None else draft.ai_rewritten_body

    finance_notice = ""
    if draft.article_type == "finance":
        finance_notice = (
            '<div class="banner">⚠ 금융 관련 콘텐츠입니다. '
            "원문의 공식 심사 기준 관련 안내 문구를 임의로 지우지 않도록 확인해주세요.</div>"
        )

    action = f"/threads/{escape(draft.content_id)}/approve"
    label = _THREADS_STATUS_LABELS.get(draft.status, draft.status)

    body = f"""
<a class="back" href="/threads">&larr; 목록으로</a>
<h1>Threads 초안 검수</h1>
<div class="meta">상태: <span class="status">{escape(label)}</span></div>
{error_banner}
{finance_notice}
<form method="post" action="{action}">
  <p><strong>제목</strong></p>
  <input type="text" name="title" value="{escape(title_value)}" style="width:100%; max-width:560px; padding:10px; border-radius:8px; border:1px solid #ccc; font-size:0.95rem;">
  <p style="margin-top:12px;"><strong>본문</strong> (Threads 실제 게시 내용, {MAX_THREADS_BODY_LENGTH}자 이내)</p>
  <textarea name="body" style="min-height:180px;">{escape(body_value)}</textarea>
  <div class="actions" style="margin-top:14px;">
    <button class="btn primary" type="submit" name="mode" value="ai_original">AI 초안 그대로 승인</button>
    <button class="btn" type="submit" name="mode" value="edited">수정하여 승인</button>
  </div>
</form>
<details style="margin-top:18px;">
  <summary>자세히 보기 (원본 KNOWLEDGE 정보)</summary>
  <div class="meta" style="margin-top:8px;">원본 제목: {escape(draft.original_title)}</div>
  <div class="meta">KNOWLEDGE ID: {escape(draft.knowledge_id)}</div>
  <div class="meta">출처: <a href="{escape(draft.source_url)}" target="_blank" rel="noopener">{escape(draft.source_url)}</a></div>
  <div class="meta">content_id: {escape(draft.content_id)}</div>
</details>
"""
    return body


def render_threads_resolved_html(draft: ThreadsPendingDraft) -> str:
    """approved/published/failed 상태의 draft를 GET으로 다시 열었을 때 보여주는
    읽기 전용 화면. 편집/승인 폼은 아예 렌더링하지 않는다 - 이미 처리된 초안을
    다시 승인할 수 있는 경로 자체를 UI에서 없애는 것이 가장 단순한 idempotency
    보장 방법이다.
    """
    label = _THREADS_STATUS_LABELS.get(draft.status, draft.status)
    final_title = draft.final_title if draft.final_title is not None else draft.ai_rewritten_title
    final_body = draft.final_body if draft.final_body is not None else draft.ai_rewritten_body

    extra = ""
    if draft.status == "failed" and draft.failure_reason:
        extra = f'<div class="error">발행 실패 사유: {escape(draft.failure_reason)}</div>'
    if draft.status == "published" and draft.threads_post_id:
        extra = f'<div class="banner">Threads Post ID: {escape(draft.threads_post_id)}</div>'

    body = f"""
<a class="back" href="/threads">&larr; 목록으로</a>
<h1>Threads 초안 (이미 처리됨)</h1>
<div class="meta">상태: <span class="status">{escape(label)}</span></div>
{extra}
<div class="title">{escape(final_title)}</div>
<p>{escape(final_body)}</p>
<div class="meta">KNOWLEDGE ID: {escape(draft.knowledge_id)}</div>
"""
    return body


# --- HTTP 요청과 분리된 순수 처리 로직(테스트에서 서버 없이 직접 호출 가능) -----


def find_candidate(candidates: list[ScoutCandidate], scout_id: str) -> ScoutCandidate | None:
    for candidate in candidates:
        if candidate.scout_id == scout_id:
            return candidate
    return None


def _build_template_turn(turn_number: int) -> InterviewTurnRecord:
    template = _TURN_TEMPLATES[turn_number - 1]
    return InterviewTurnRecord(
        turn=turn_number,
        question=template["question"],
        option_a=template["option_a"],
        option_b=template["option_b"],
        option_c=template["option_c"],
        option_d=template["option_d"],
        generated_by="template",
        selected_option=None,
        custom_answer="",
        answered_at=None,
    )


def _source_fact_for(candidate: ScoutCandidate) -> str:
    """tak_scout/knowledge_bridge.py의 SOURCE FACT 계약과 동일한 값을 만든다.

    knowledge_bridge.py:71의 `source_fact = candidate.summary.strip() or
    candidate.title`과 의도적으로 똑같은 규칙이다(5-10 Phase 3-2 4번 지시). 그
    파일을 이번 단계에서 수정하지 않으므로, 이 한 줄짜리 규칙만 여기 그대로
    복제해 둔다 - "SOURCE FACT는 기사에서 확인된 사실이며 사용자의 의견이
    아니다"라는 경계를 KNOWLEDGE 생성 시점과 인터뷰 질문 생성 시점 모두에서
    동일하게 유지한다.
    """
    return candidate.summary.strip() or candidate.title


def _log_unexpected_llm_error(context: str, error: Exception) -> None:
    """InterviewLLMProvider는 예외를 던지지 않는 계약이지만(5-10 Phase 3-1), 방어적으로
    한 번 더 잡는다 - 어떤 이유로도 LLM 실패가 Dashboard 500 오류로 번지지 않게 한다
    (5-10 Phase 3-2 4, 11번). 예외 메시지 대신 타입 이름만 남겨 시크릿 노출 위험을
    피한다(tak_scout/interview_llm.py의 _log_error와 동일한 원칙).
    """
    sys.stderr.write(f"[dashboard] {context}에서 예상치 못한 LLM 오류: {type(error).__name__}\n")


def get_display_titles(
    candidates: list[ScoutCandidate],
    llm_provider: InterviewLLMProvider | None,
    translations_path: Path,
) -> dict[str, str]:
    """소재 목록의 scout_id -> 한국어 표시용 제목 매핑을 만든다(5-20).

    원문 title(candidate.title)은 이 함수가 절대 바꾸지 않는다 - 반환하는 dict는
    화면 렌더링에서만 쓰는 별도 값이다.

    1) 이미 캐시(tak_scout_title_translations.json)에 있는 scout_id는 LLM을 다시
       부르지 않고 캐시된 번역을 그대로 쓴다(같은 후보를 새로고침해도 반복 호출
       없음 - 5-20 지시 7번).
    2) 캐시에 없는 후보만 모아 InterviewLLMProvider.translate_titles()를 "한 번의
       배치 호출"로 처리한다(후보마다 개별 호출하지 않음 - 5-20 지시 8번, 비용/응답
       속도 억제).
    3) provider가 없거나 호출이 실패(None)했거나, 일부 scout_id만 번역되지 않은
       경우 - 그 scout_id는 원문 title을 그대로 fallback으로 쓴다(5-20 지시 6번).
       실패한 항목은 캐시에 저장하지 않는다 - 다음에 LLM이 복구되면 다시 시도할 수
       있게 한다(기존 interview_llm.py의 "실패는 영구 상태로 남기지 않는다" 철학과
       동일).
    """
    cached = translations_by_scout_id(translations_path)
    display_titles: dict[str, str] = {}
    uncached: list[tuple[str, str]] = []

    for candidate in candidates:
        cached_entry = cached.get(candidate.scout_id)
        if cached_entry is not None:
            display_titles[candidate.scout_id] = cached_entry.display_title
        else:
            uncached.append((candidate.scout_id, candidate.title))

    if uncached and llm_provider is not None:
        try:
            translated = llm_provider.translate_titles(tuple(uncached))
        except Exception as error:  # noqa: BLE001 - LLM 실패를 절대 Dashboard 오류로 노출하지 않는다.
            _log_unexpected_llm_error("translate_titles", error)
            translated = None

        if translated:
            now = utc_now()
            candidates_by_id = {candidate.scout_id: candidate for candidate in candidates}
            for scout_id, display_title in translated.items():
                candidate = candidates_by_id.get(scout_id)
                if candidate is None:
                    continue
                upsert_translation(
                    translations_path,
                    TitleTranslation(
                        scout_id=scout_id,
                        source_title=candidate.title,
                        display_title=display_title,
                        translated_at=now,
                    ),
                )
                display_titles[scout_id] = display_title

    for scout_id, title in uncached:
        display_titles.setdefault(scout_id, title)

    return display_titles


def _build_turn_one(candidate: ScoutCandidate, llm_provider: InterviewLLMProvider | None) -> InterviewTurnRecord:
    """LLM을 우선 시도하고, provider가 없거나 실패(None)하면 템플릿으로 대체한다."""
    if llm_provider is not None:
        try:
            llm_turn = llm_provider.generate_first_question(candidate, _source_fact_for(candidate))
        except Exception as error:  # noqa: BLE001 - LLM 실패를 절대 Dashboard 오류로 노출하지 않는다.
            _log_unexpected_llm_error("generate_first_question", error)
            llm_turn = None
        if llm_turn is not None:
            # option_d는 사용자의 직접입력 경로다 - provider가 이미 강제하지만(Phase
            # 3-1), Dashboard에서도 한 번 더 덮어써 이중으로 보호한다(5-10 Phase 3-2
            # 테스트 3번: "LLM이 반환한 option_d가 이상한 값이어도 최종 D는 '직접 입력'").
            return replace(llm_turn, option_d=FORCED_OPTION_D)
    return _build_template_turn(1)


def find_session(scout_id: str, sessions_path: Path) -> InterviewSession | None:
    return next((s for s in load_sessions(sessions_path) if s.scout_id == scout_id), None)


def get_or_start_session(
    candidate: ScoutCandidate,
    sessions_path: Path,
    llm_provider: InterviewLLMProvider | None,
) -> InterviewSession:
    """세션이 있으면 그대로 반환하고, 없으면 turn 1을 만들어 새로 시작한다.

    이미 저장된 세션이 있으면 새로 만들지 않는다(새로고침해도 같은 세션이 유지되어야
    한다는 요구사항 - 5-10 Phase 2 4번). 저장된 세션을 그대로 반환하는 이 경로는
    LLM을 전혀 호출하지 않는다 - LLM은 세션이 처음 생성되는 순간에만 시도한다
    (5-10 Phase 3-2 9번).
    """
    existing = find_session(candidate.scout_id, sessions_path)
    if existing is not None:
        return existing
    now = utc_now()
    session = InterviewSession(
        scout_id=candidate.scout_id,
        status="in_progress",
        turns=(_build_turn_one(candidate, llm_provider),),
        perspective_summary="",
        created_at=now,
        updated_at=now,
        completed_at=None,
    )
    upsert_session(sessions_path, session)
    return session


def handle_turn_answer_submission(
    candidate: ScoutCandidate,
    session: InterviewSession,
    form: dict[str, list[str]],
    sessions_path: Path,
    llm_provider: InterviewLLMProvider | None,
) -> tuple[InterviewSession | None, str | None]:
    """현재 턴에 답을 기록하고, 필요하면 다음 턴을 만들거나 세션을 완료 처리한다.

    (갱신된 세션 또는 None, 오류 메시지 또는 None)을 반환한다. 사용자가 입력한
    직접입력 문자열은 앞뒤 공백만 제거할 뿐 절대 요약·수정하지 않는다.

    3턴 미만이면 LLM(decide_next_turn)에게 "충분한지"와 "다음 질문"을 함께
    묻는다. LLM이 없거나 실패(None)하면 기존 고정 템플릿으로 fallback한다(5-10
    Phase 3-2 5번). 이미 3턴에 도달했으면 LLM을 아예 호출하지 않고 무조건
    완료 처리한다(5-10 설계 문서 5, 12번 - 비용 상한을 코드 구조로 강제).
    """
    if session.status == "completed" or not session.turns:
        return session, None

    current_turn = session.turns[-1]
    if current_turn.selected_option is not None:
        # 이미 답변된 턴에 대한 중복 제출(새로고침/두 번 클릭 등) - 그대로 무시하고
        # 현재 세션을 반환한다(다시 저장하거나 다음 턴을 또 만들지 않는다, LLM도
        # 다시 호출하지 않는다).
        return session, None

    option = (form.get("option", [""])[0] or "").strip().upper()
    if option not in VALID_OPTIONS:
        return None, f"선택지는 {'/'.join(VALID_OPTIONS)} 중 하나여야 합니다: {option!r}"

    if option == "D":
        custom_answer = (form.get("custom_answer", [""])[0] or "").strip()
        if not custom_answer:
            return None, "D(직접 입력)를 선택하면 답변 내용이 필요합니다."
    else:
        custom_answer = ""

    now = utc_now()
    answered_turn = replace(current_turn, selected_option=option, custom_answer=custom_answer, answered_at=now)
    turns = session.turns[:-1] + (answered_turn,)
    perspective_summary = session.perspective_summary

    if len(turns) >= MAX_TURNS:
        # 3턴째가 방금 답변됨 - LLM을 호출하지 않는다(기존 동작 그대로 유지).
        status = "completed"
        completed_at = now
    else:
        decision: FollowUpDecision | None = None
        if llm_provider is not None:
            try:
                decision = llm_provider.decide_next_turn(candidate, _source_fact_for(candidate), turns)
            except Exception as error:  # noqa: BLE001 - LLM 실패를 절대 Dashboard 오류로 노출하지 않는다.
                _log_unexpected_llm_error("decide_next_turn", error)
                decision = None

        if decision is not None:
            # perspective_summary는 LLM이 사용자의 실제 답변만 요약한 결과다(설계
            # 문서 6번) - review 화면 표시용일 뿐, SOURCE FACT/URL/USER ORIGINAL
            # THOUGHT 등 KNOWLEDGE 구조에는 전혀 섞이지 않는다(handle_finalize는
            # session.turns만 읽는다).
            perspective_summary = decision.perspective_summary
            if decision.sufficient:
                status = "completed"
                completed_at = now
            else:
                # option_d 이중 보호(_build_turn_one과 동일한 이유).
                turns = turns + (replace(decision.next_turn, option_d=FORCED_OPTION_D),)
                status = "in_progress"
                completed_at = None
        else:
            # llm_provider가 없거나 decide_next_turn이 실패(None)했다 - 기존 Phase 2
            # 고정 템플릿으로 조용히 fallback한다. Dashboard는 이 실패를 절대 사용자
            # 오류로 노출하지 않는다.
            turns = turns + (_build_template_turn(len(turns) + 1),)
            status = "in_progress"
            completed_at = None

    updated = replace(
        session,
        turns=turns,
        status=status,
        updated_at=now,
        completed_at=completed_at,
        perspective_summary=perspective_summary,
    )
    upsert_session(sessions_path, updated)
    return updated, None


def _build_combined_answer_text(session: InterviewSession) -> str:
    """세션의 턴들을 "Q1./A1." 형식으로 이어붙인다. 사용자가 쓴 문장은 그대로 보존한다."""
    blocks = []
    for turn in session.turns:
        if turn.selected_option is None:
            continue
        blocks.append(f"Q{turn.turn}. {turn.question}\nA{turn.turn}. {_turn_answer_text(turn)}")
    return "\n\n".join(blocks)


def handle_finalize(
    candidate: ScoutCandidate, session: InterviewSession, config: DashboardConfig
) -> tuple[InterviewAnswer | None, tuple[int, int, int] | None, str | None]:
    """완료된 세션을 기존 InterviewAnswer로 합성해 저장하고, 기존
    append_scout_knowledge를 그대로 호출해 pending KNOWLEDGE로 연결한다.

    기존 tak_scout/answers.py, tak_scout/knowledge_bridge.py는 전혀 수정하지
    않는다 - 이 함수가 세션 -> InterviewAnswer 변환만 담당하는 작은 어댑터다.
    (합성된 답변, append_scout_knowledge의 (created, skipped, duplicates), 오류)
    를 반환한다.
    """
    if session.status != "completed":
        return None, None, "아직 모든 질문에 답하지 않았습니다."

    combined_text = _build_combined_answer_text(session)
    if not combined_text.strip():
        return None, None, "저장할 답변 내용이 없습니다."

    try:
        # 멀티턴 합성 결과는 항상 D(직접 입력)로 저장한다 - 여러 턴을 합친 결과는
        # 단순 A/B/C로 표현할 수 없는 내용이기 때문이다(5-10 설계 문서 5번).
        answer = InterviewAnswer.create(candidate.scout_id, "D", combined_text)
    except InterviewAnswerError as error:
        return None, None, str(error)

    upsert_answer(config.answers_path, answer)
    counts = append_scout_knowledge(config.daily_pack_path, config.answers_path, config.knowledge_path)
    return answer, counts, None


def handle_restart(
    candidate: ScoutCandidate, sessions_path: Path, llm_provider: InterviewLLMProvider | None
) -> InterviewSession:
    """[다시 답변하기]: 세션을 삭제하지 않고 turn 1부터 다시 시작하도록 초기화한다.

    가장 단순한 방식을 택했다: 세션을 지우지 않고 upsert로 덮어써서 turn 1개
    (미답변)로 되돌린다. 세션이 처음 만들어진 시각(created_at)만 보존하고, 이전
    턴의 질문/답변 텍스트 자체는 새 턴으로 교체된다(복잡한 버전 관리는 만들지
    않는다 - 5-10 Phase 2 9번). 이미 확정되어 data/tak_interview_answers.json과
    KNOWLEDGE에 저장된 이전 결과는 restart만으로는 전혀 건드리지 않는다 - 그
    데이터는 다시 [KNOWLEDGE 만들기]를 눌러야만 갱신된다.

    restart로 새로 만드는 turn 1은 get_or_start_session()과 동일하게 LLM을
    다시 시도한다(5-10 Phase 3-2 10번) - 이미 저장된 진행 중 turn을 단순히 다시
    읽는 것과는 다른 경로이므로 LLM 재호출이 허용된다. perspective_summary도
    새로 시작하므로 빈 문자열로 초기화한다.
    """
    existing = find_session(candidate.scout_id, sessions_path)
    now = utc_now()
    created_at = existing.created_at if existing is not None else now
    fresh = InterviewSession(
        scout_id=candidate.scout_id,
        status="in_progress",
        turns=(_build_turn_one(candidate, llm_provider),),
        perspective_summary="",
        created_at=created_at,
        updated_at=now,
        completed_at=None,
    )
    upsert_session(sessions_path, fresh)
    return fresh


def handle_skip_submission(candidate: ScoutCandidate, config: DashboardConfig) -> None:
    mark_skipped(config.skipped_path, candidate.scout_id)


# --- Threads 검수 순수 로직 (5-11 Phase 2, 서버 없이 테스트 가능) ---------------


def find_pending_draft(pending_path: Path, content_id: str) -> ThreadsPendingDraft | None:
    for draft in load_pending(pending_path):
        if draft.content_id == content_id:
            return draft
    return None


def list_unresolved_threads_drafts(pending_path: Path) -> list[ThreadsPendingDraft]:
    """pending/approved 상태만 반환한다 - published/failed는 검수 목록에서 제외한다."""
    return [draft for draft in load_pending(pending_path) if draft.status in UNRESOLVED_STATUSES]


def handle_threads_approve_submission(
    pending_path: Path, content_id: str, form: dict[str, list[str]]
) -> tuple[ThreadsPendingDraft | None, str | None]:
    """POST /threads/{content_id}/approve 처리.

    (갱신된 draft 또는 None, 오류 메시지 또는 None)을 반환한다. draft가 아예
    없으면 (None, None)을 반환해 호출부가 404로 처리하게 한다.

    mode == "ai_original"이면 사용자가 입력창에 무엇을 남겼든 무시하고
    ai_rewritten_title/body를 그대로 final_*로 확정한다(요구사항 A를 문자열
    비교가 아니라 명시적으로 보장하기 위함). 그 외(mode == "edited" 또는 알 수
    없는 값)에는 사용자가 제출한 값을 한 글자도 바꾸지 않고 그대로 final_*로
    쓴다 - 공백 trim도, LLM 재작성도 하지 않는다(요구사항: "사용자 수정 문장은
    어떤 LLM에도 다시 보내지 않는다").
    """
    draft = find_pending_draft(pending_path, content_id)
    if draft is None:
        return None, None

    # Phase 2는 pending -> approved만 Dashboard로 수행한다(approved/failed에서의
    # 재승인·재시도는 다음 Phase의 책임) - 이미 처리된 draft는 여기서 명시적으로
    # 막아 이중 승인을 방지한다(idempotent: 같은 draft를 두 번 승인해도 두 번째는
    # 아무 것도 바꾸지 않고 오류만 반환한다).
    if draft.status != "pending":
        return None, "이미 처리된 초안입니다."

    mode = (form.get("mode", [""])[0] or "").strip()
    if mode == "ai_original":
        final_title = draft.ai_rewritten_title
        final_body = draft.ai_rewritten_body
    else:
        final_title = form.get("title", [""])[0] or ""
        final_body = form.get("body", [""])[0] or ""

    if not final_title.strip():
        return None, "제목을 입력해주세요."
    if not final_body.strip():
        return None, "본문을 입력해주세요."
    if len(final_body) > MAX_THREADS_BODY_LENGTH:
        return None, f"본문이 Threads 제한({MAX_THREADS_BODY_LENGTH}자)을 넘었습니다. 현재 {len(final_body)}자입니다."

    try:
        approved = mark_approved(draft, final_title=final_title, final_body=final_body, approved_at=utc_now())
    except ThreadsPendingError as error:
        return None, str(error)

    upsert_pending(pending_path, approved)
    return approved, None


# --- HTTP 서버 --------------------------------------------------------------


def make_handler_class(
    config: DashboardConfig, llm_provider: InterviewLLMProvider | None = None
) -> type[BaseHTTPRequestHandler]:
    """`llm_provider`를 생략하면(기본값 None) LLM을 전혀 쓰지 않는다 - Phase 2와
    완전히 동일한 템플릿 전용 동작이다. content_engine의 MockRewriteProvider나
    tak_scout.interview_llm의 여러 provider와 마찬가지로, "인자를 넘기지 않으면
    네트워크 호출이 없는 안전한 기본값"이라는 이 프로젝트의 기존 관례를 그대로
    따른다.

    production에서 실제로 LLM을 쓰려면 main()이 하는 것처럼 호출부가
    `InterviewLLMProvider.from_environment()`로 만든 provider를 명시적으로
    넘겨야 한다(scripts/run_media_batch.py 등이 OpenAICompatibleRewriteProvider를
    넘기는 방식과 동일) - 이렇게 해야 기존 테스트를 포함한 모든 테스트가 환경변수
    상태와 무관하게 항상 결정적으로 동작한다(5-10 Phase 3-2 15번: "테스트가 실제
    환경변수/API에 의존하면 안 된다").
    """

    class DashboardRequestHandler(BaseHTTPRequestHandler):
        server_version = "TAKScoutDashboard/0.2"

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            sys.stderr.write("[dashboard] " + (format % args) + "\n")

        def _send_html(self, body: bytes, status: int = 200) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _redirect(self, location: str) -> None:
            self.send_response(303)
            self.send_header("Location", location)
            self.end_headers()

        def _load_candidate_or_404(self, scout_id: str) -> ScoutCandidate | None:
            candidates = load_daily_pack(config.daily_pack_path)
            candidate = find_candidate(candidates, scout_id)
            if candidate is None:
                self._send_html(_page("소재 없음", render_not_found_html(scout_id)), status=404)
            return candidate

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            query = parse_qs(parsed.query)
            saved = query.get("saved", ["0"])[0] == "1"

            if path == "/":
                candidates = load_daily_pack(config.daily_pack_path)
                ranked = rank_candidates(candidates)
                answered_ids = frozenset(a.scout_id for a in load_answers(config.answers_path))
                skipped_ids = skipped_scout_ids(config.skipped_path)
                display_titles = get_display_titles(candidates, llm_provider, config.title_translations_path)
                body = render_candidate_list_html(ranked, answered_ids, skipped_ids, display_titles)
                self._send_html(_page("TAK SCOUT Dashboard", body))
                return

            if path.startswith("/candidate/") and path.endswith("/review"):
                scout_id = unquote(path[len("/candidate/") : -len("/review")])
                candidate = self._load_candidate_or_404(scout_id)
                if candidate is None:
                    return
                session = find_session(scout_id, config.sessions_path)
                if session is None or session.status != "completed":
                    # 아직 다 답하지 않았으면 review 대신 다시 인터뷰 화면으로.
                    self._redirect(f"/candidate/{scout_id}")
                    return
                display_title = get_display_titles([candidate], llm_provider, config.title_translations_path)[scout_id]
                body = render_review_html(candidate, session, saved=saved, display_title=display_title)
                self._send_html(_page(candidate.title, body))
                return

            if path.startswith("/candidate/"):
                scout_id = unquote(path[len("/candidate/") :])
                candidate = self._load_candidate_or_404(scout_id)
                if candidate is None:
                    return
                session = get_or_start_session(candidate, config.sessions_path, llm_provider)
                if session.status == "completed":
                    self._redirect(f"/candidate/{scout_id}/review")
                    return
                current_turn = session.turns[-1]
                display_title = get_display_titles([candidate], llm_provider, config.title_translations_path)[scout_id]
                body = render_turn_html(candidate, session, current_turn, saved=saved, display_title=display_title)
                self._send_html(_page(candidate.title, body))
                return

            # --- Threads 검수 (5-11 Phase 2) ---------------------------------

            if path == "/threads":
                drafts = list_unresolved_threads_drafts(config.pending_path)
                if len(drafts) == 1:
                    # 초안이 정확히 1개면 목록을 보여줄 필요 없이 바로 검수 화면으로.
                    self._redirect(f"/threads/{drafts[0].content_id}")
                    return
                body = render_threads_list_html(drafts)
                self._send_html(_page("Threads 검수", body))
                return

            if path.startswith("/threads/"):
                content_id = unquote(path[len("/threads/") :])
                draft = find_pending_draft(config.pending_path, content_id)
                if draft is None:
                    body = (
                        '<a class="back" href="/threads">&larr; 목록으로</a>'
                        f'<div class="error">초안을 찾을 수 없습니다: {escape(content_id)}</div>'
                    )
                    self._send_html(_page("초안 없음", body), status=404)
                    return
                if draft.status == "pending":
                    body = render_threads_review_html(draft)
                else:
                    # approved/published/failed - 편집/승인 폼 없는 읽기 전용 화면
                    # (이미 처리된 초안을 다시 승인할 수 있는 경로 자체가 없다).
                    body = render_threads_resolved_html(draft)
                self._send_html(_page("Threads 초안 검수", body))
                return

            # --- TAK MEDIA Human Review Dashboard (5-28) ---------------------

            if path == "/media":
                platform = query.get("platform", ["all"])[0]
                generation_status = query.get("generation_status", ["all"])[0]
                review_status = query.get("review_status", ["all"])[0]
                approved_flag = query.get("approved", ["0"])[0] == "1"

                records = load_archive(config.media_archive_path)
                filtered = filter_media_archive_records(records, platform, generation_status, review_status)
                body = render_media_list_html(
                    filtered,
                    config,
                    platform=platform,
                    generation_status=generation_status,
                    review_status=review_status,
                    approved=approved_flag,
                )
                self._send_html(_page("TAK MEDIA", body))
                return

            # 6-07: generation pool 조회 (6-08: 승인/보류 액션 추가) - "/media/{content_id}"
            # 상세 라우트보다 먼저 검사해야 "/media/generations"가 content_id로
            # 잘못 해석되지 않는다.
            if path == "/media/generations":
                notice = query.get("notice", [None])[0]
                records = load_generation_pool_records(config.generation_archive_paths)
                knowledge_titles = load_knowledge_titles(config.knowledge_path)
                body = render_generation_pool_html(records, notice=notice, knowledge_titles=knowledge_titles)
                self._send_html(_page("TAK MEDIA Generation Pool", body))
                return

            # 6-10: generation pool 레코드 1건의 수정 화면 - "/media/generations/"로
            # 시작하는 knowledge_id 필터 라우트보다 반드시 먼저 검사해야
            # "/media/generations/record/.../edit"가 knowledge_id로 잘못 해석되지
            # 않는다("/media/generations/record/.../approve|dismiss" POST 라우트가
            # 이미 같은 이유로 일반 knowledge_id 필터보다 먼저 검사되는 것과 동일한
            # 순서 원칙, 6-08 주석 참고).
            if path.startswith("/media/generations/record/") and path.endswith("/edit"):
                segment = path[len("/media/generations/record/") : -len("/edit")]
                content_id, _, generation_segment = segment.rpartition("/")
                content_id = unquote(content_id)
                generation_id = _generation_id_from_url_segment(unquote(generation_segment))
                record, _pool_path = find_generation_pool_record(
                    config.generation_archive_paths, content_id, generation_id
                )
                if record is None:
                    body = (
                        '<a class="back" href="/media/generations">&larr; 목록으로</a>'
                        f'<div class="error">generation을 찾을 수 없습니다: {escape(content_id)}</div>'
                    )
                    self._send_html(_page("Generation 없음", body), status=404)
                    return
                body = render_generation_edit_html(record)
                self._send_html(_page("Generation 수정", body))
                return

            if path.startswith("/media/generations/"):
                knowledge_id = unquote(path[len("/media/generations/") :])
                notice = query.get("notice", [None])[0]
                records = load_generation_pool_records(config.generation_archive_paths)
                knowledge_titles = load_knowledge_titles(config.knowledge_path)
                body = render_generation_pool_html(
                    records, knowledge_id_filter=knowledge_id, notice=notice, knowledge_titles=knowledge_titles
                )
                self._send_html(_page("TAK MEDIA Generation Pool", body))
                return

            if path.startswith("/media/"):
                content_id = unquote(path[len("/media/") :])
                record = find_media_archive_record(config.media_archive_path, content_id)
                if record is None:
                    body = (
                        '<a class="back" href="/media">&larr; 목록으로</a>'
                        f'<div class="error">Draft를 찾을 수 없습니다: {escape(content_id)}</div>'
                    )
                    self._send_html(_page("MEDIA Draft 없음", body), status=404)
                    return

                knowledge_by_id = {
                    knowledge.id: knowledge for knowledge in load_knowledge_records(config.knowledge_path)
                }
                knowledge = knowledge_by_id.get(record.knowledge_id)
                notice = query.get("notice", [None])[0]
                body = render_media_detail_html(record, knowledge, config, notice=notice)
                self._send_html(_page("TAK MEDIA 상세", body))
                return

            # --- Performance Dashboard (6-01 MVP + 6-02 시계열 추이, 읽기 전용) ---

            if path == "/performance":
                snapshots_by_content: dict[str, list] = {}
                for snapshot in load_performance_snapshots(config.performance_path):
                    snapshots_by_content.setdefault(snapshot.content_id, []).append(snapshot)
                summaries = [
                    summary
                    for summary in (
                        summarize_content_history(records) for records in snapshots_by_content.values()
                    )
                    if summary is not None
                ]
                archive_by_content_id = {
                    record.content_id: record for record in load_archive(config.media_archive_path)
                }
                body = render_performance_list_html(summaries, archive_by_content_id)
                self._send_html(_page("Performance", body))
                return

            self._send_html(_page("페이지 없음", "<p>페이지를 찾을 수 없습니다.</p>"), status=404)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            length = int(self.headers.get("Content-Length") or 0)
            raw_body = self.rfile.read(length) if length else b""
            form = parse_qs(raw_body.decode("utf-8"))

            if path.startswith("/candidate/") and path.endswith("/answer"):
                scout_id = unquote(path[len("/candidate/") : -len("/answer")])
                candidate = self._load_candidate_or_404(scout_id)
                if candidate is None:
                    return
                session = get_or_start_session(candidate, config.sessions_path, llm_provider)
                if session.status == "completed":
                    self._redirect(f"/candidate/{scout_id}/review")
                    return
                updated_session, error = handle_turn_answer_submission(
                    candidate, session, form, config.sessions_path, llm_provider
                )
                if error:
                    current_turn = session.turns[-1]
                    display_title = get_display_titles(
                        [candidate], llm_provider, config.title_translations_path
                    )[scout_id]
                    body = render_turn_html(
                        candidate, session, current_turn, error=error, display_title=display_title
                    )
                    self._send_html(_page(candidate.title, body), status=400)
                    return
                if updated_session.status == "completed":
                    self._redirect(f"/candidate/{scout_id}/review")
                else:
                    self._redirect(f"/candidate/{scout_id}?saved=1")
                return

            if path.startswith("/candidate/") and path.endswith("/finalize"):
                scout_id = unquote(path[len("/candidate/") : -len("/finalize")])
                candidate = self._load_candidate_or_404(scout_id)
                if candidate is None:
                    return
                session = find_session(scout_id, config.sessions_path)
                if session is None:
                    self._redirect(f"/candidate/{scout_id}")
                    return
                _answer, _counts, error = handle_finalize(candidate, session, config)
                if error:
                    display_title = get_display_titles(
                        [candidate], llm_provider, config.title_translations_path
                    )[scout_id]
                    body = render_review_html(candidate, session, error=error, display_title=display_title)
                    self._send_html(_page(candidate.title, body), status=400)
                    return
                self._redirect(f"/candidate/{scout_id}/review?saved=1")
                return

            if path.startswith("/candidate/") and path.endswith("/restart"):
                scout_id = unquote(path[len("/candidate/") : -len("/restart")])
                candidate = self._load_candidate_or_404(scout_id)
                if candidate is None:
                    return
                handle_restart(candidate, config.sessions_path, llm_provider)
                self._redirect(f"/candidate/{scout_id}")
                return

            if path.startswith("/candidate/") and path.endswith("/skip"):
                scout_id = unquote(path[len("/candidate/") : -len("/skip")])
                candidate = self._load_candidate_or_404(scout_id)
                if candidate is None:
                    return
                handle_skip_submission(candidate, config)
                self._redirect("/")
                return

            # --- Threads 검수 승인 (5-11 Phase 2) ----------------------------

            if path.startswith("/threads/") and path.endswith("/approve"):
                content_id = unquote(path[len("/threads/") : -len("/approve")])
                approved, error = handle_threads_approve_submission(config.pending_path, content_id, form)

                if approved is None and error is None:
                    body = (
                        '<a class="back" href="/threads">&larr; 목록으로</a>'
                        f'<div class="error">초안을 찾을 수 없습니다: {escape(content_id)}</div>'
                    )
                    self._send_html(_page("초안 없음", body), status=404)
                    return

                if error:
                    draft = find_pending_draft(config.pending_path, content_id)
                    if draft is None:
                        body = (
                            '<a class="back" href="/threads">&larr; 목록으로</a>'
                            f'<div class="error">초안을 찾을 수 없습니다: {escape(content_id)}</div>'
                        )
                        self._send_html(_page("초안 없음", body), status=404)
                        return
                    if draft.status != "pending":
                        # 이미 처리된 초안(이중 제출 등) - 폼을 다시 보여주지 않고
                        # 현재 실제 상태 화면으로 안전하게 돌려보낸다(idempotent).
                        self._redirect(f"/threads/{content_id}")
                        return
                    body = render_threads_review_html(
                        draft,
                        error=error,
                        submitted_title=form.get("title", [None])[0],
                        submitted_body=form.get("body", [None])[0],
                    )
                    self._send_html(_page("Threads 초안 검수", body), status=400)
                    return

                self._redirect(f"/threads/{content_id}")
                return

            # --- MEDIA Generation Pool 승인/보류 (6-08) -------------------------
            #
            # production archive 경로를 인자로 받지 않는 handle_generation_*
            # 함수만 호출한다 - 구조적으로 production archive를 쓸 수 없다.
            # "/media/"로 시작하는 일반 승인/보류 라우트보다 반드시 먼저 검사해야
            # "/media/generations/record/.../approve"가 그 일반 라우트에
            # content_id="generations/record/.../approve"처럼 잘못 먹히지 않는다.

            if path.startswith("/media/generations/record/") and path.endswith("/approve"):
                segment = path[len("/media/generations/record/") : -len("/approve")]
                content_id, _, generation_segment = segment.rpartition("/")
                content_id = unquote(content_id)
                generation_id = _generation_id_from_url_segment(unquote(generation_segment))
                updated, error = handle_generation_review_submission(
                    config.generation_archive_paths, content_id, generation_id, "approved"
                )
                if updated is None and error is None:
                    self._send_html(
                        _page(
                            "Generation 없음",
                            '<a class="back" href="/media/generations">&larr; 목록으로</a>'
                            f'<div class="error">generation을 찾을 수 없습니다: {escape(content_id)}</div>',
                        ),
                        status=404,
                    )
                    return
                if error:
                    self._send_html(
                        _page(
                            "승인 실패",
                            '<a class="back" href="/media/generations">&larr; 목록으로</a>'
                            f'<div class="error">{escape(error)}</div>',
                        ),
                        status=400,
                    )
                    return
                self._redirect("/media/generations?notice=approved")
                return

            if path.startswith("/media/generations/record/") and path.endswith("/dismiss"):
                segment = path[len("/media/generations/record/") : -len("/dismiss")]
                content_id, _, generation_segment = segment.rpartition("/")
                content_id = unquote(content_id)
                generation_id = _generation_id_from_url_segment(unquote(generation_segment))
                updated, error = handle_generation_review_submission(
                    config.generation_archive_paths, content_id, generation_id, "dismissed"
                )
                if updated is None and error is None:
                    self._send_html(
                        _page(
                            "Generation 없음",
                            '<a class="back" href="/media/generations">&larr; 목록으로</a>'
                            f'<div class="error">generation을 찾을 수 없습니다: {escape(content_id)}</div>',
                        ),
                        status=404,
                    )
                    return
                if error:
                    self._send_html(
                        _page(
                            "보류 실패",
                            '<a class="back" href="/media/generations">&larr; 목록으로</a>'
                            f'<div class="error">{escape(error)}</div>',
                        ),
                        status=400,
                    )
                    return
                self._redirect("/media/generations?notice=dismissed")
                return

            # 6-10: generation pool 레코드 1건의 제목/본문 수정. 다른 generation
            # 승인/보류 라우트와 동일한 이유로 "/media/"로 시작하는 일반 수정
            # 라우트보다 반드시 먼저 검사한다. production archive 경로를 인자로
            # 받지 않는 handle_generation_edit_submission()만 호출하므로 구조적으로
            # production archive를 쓸 수 없다.

            if path.startswith("/media/generations/record/") and path.endswith("/edit"):
                segment = path[len("/media/generations/record/") : -len("/edit")]
                content_id, _, generation_segment = segment.rpartition("/")
                content_id = unquote(content_id)
                generation_id = _generation_id_from_url_segment(unquote(generation_segment))
                title = form.get("title", [""])[0] or ""
                body_text = form.get("body", [""])[0] or ""
                updated, error = handle_generation_edit_submission(
                    config.generation_archive_paths, content_id, generation_id, title, body_text
                )
                if updated is None and error is None:
                    self._send_html(
                        _page(
                            "Generation 없음",
                            '<a class="back" href="/media/generations">&larr; 목록으로</a>'
                            f'<div class="error">generation을 찾을 수 없습니다: {escape(content_id)}</div>',
                        ),
                        status=404,
                    )
                    return
                if error:
                    self._send_html(
                        _page(
                            "수정 실패",
                            '<a class="back" href="/media/generations">&larr; 목록으로</a>'
                            f'<div class="error">{escape(error)}</div>',
                        ),
                        status=400,
                    )
                    return
                self._redirect("/media/generations?notice=saved")
                return

            if path.startswith("/media/generations/generation/") and path.endswith("/approve-all"):
                generation_segment = unquote(
                    path[len("/media/generations/generation/") : -len("/approve-all")]
                )
                generation_id = _generation_id_from_url_segment(generation_segment)
                _updated_records, error = handle_generation_approve_all_submission(
                    config.generation_archive_paths, generation_id
                )
                if error:
                    self._send_html(
                        _page(
                            "전체 승인 실패",
                            '<a class="back" href="/media/generations">&larr; 목록으로</a>'
                            f'<div class="error">{escape(error)}</div>',
                        ),
                        status=400,
                    )
                    return
                self._redirect("/media/generations?notice=approved-all")
                return

            # --- TAK MEDIA 승인 (5-28) ----------------------------------------
            #
            # 이 핸들러는 review_status만 바꾸고(+ platform=="threads"일 때만
            # 기존 threads_review.upsert_pending()으로 pending draft 하나를 새로
            # 만드는 것까지만 한다). ThreadsClient/YouTubeClient/Naver 게시
            # 코드는 이 파일 어디에서도 import하지 않는다 - 실제 발행은 이
            # 핸들러가 절대 할 수 없다.

            if path.startswith("/media/") and path.endswith("/approve"):
                content_id = unquote(path[len("/media/") : -len("/approve")])
                updated, error = handle_media_approve_submission(
                    config.media_archive_path,
                    config.knowledge_path,
                    config.pending_path,
                    content_id,
                    shorts_scripts_path=config.shorts_scripts_path,
                )

                if updated is None and error is None:
                    body = (
                        '<a class="back" href="/media">&larr; 목록으로</a>'
                        f'<div class="error">Draft를 찾을 수 없습니다: {escape(content_id)}</div>'
                    )
                    self._send_html(_page("MEDIA Draft 없음", body), status=404)
                    return

                if error:
                    self._send_html(
                        _page(
                            "승인 실패",
                            '<a class="back" href="/media">&larr; 목록으로</a>'
                            f'<div class="error">{escape(error)}</div>',
                        ),
                        status=400,
                    )
                    return

                self._redirect(f"/media/{content_id}?notice=approved")
                return

            # --- TAK MEDIA 수정 (5-29) -----------------------------------------
            #
            # original_title/original_body(원본), rewritten_title/rewritten_body
            # (AI 생성 결과)는 그대로 두고 edited_title/edited_body만 바꾼다.
            # 저장해도 승인되지 않는다 - review_status는 항상 "unreviewed"로
            # 되돌아가 사람이 다시 [승인]을 눌러야 한다.

            if path.startswith("/media/") and path.endswith("/edit"):
                content_id = unquote(path[len("/media/") : -len("/edit")])
                title = form.get("title", [""])[0] or ""
                body_text = form.get("body", [""])[0] or ""
                updated, error = handle_media_edit_submission(config.media_archive_path, content_id, title, body_text)

                if updated is None and error is None:
                    body = (
                        '<a class="back" href="/media">&larr; 목록으로</a>'
                        f'<div class="error">Draft를 찾을 수 없습니다: {escape(content_id)}</div>'
                    )
                    self._send_html(_page("MEDIA Draft 없음", body), status=404)
                    return

                if error:
                    self._send_html(
                        _page(
                            "수정 실패",
                            '<a class="back" href="/media">&larr; 목록으로</a>'
                            f'<div class="error">{escape(error)}</div>',
                        ),
                        status=400,
                    )
                    return

                self._redirect(f"/media/{content_id}?notice=saved")
                return

            # --- TAK MEDIA 보류 (5-29) -------------------------------------------
            #
            # 데이터를 삭제하지 않는다 - review_status를 "dismissed"로 바꿔
            # 저장할 뿐이며, dismissed 상태에서도 나중에 다시 수정/승인할 수 있다.

            if path.startswith("/media/") and path.endswith("/dismiss"):
                content_id = unquote(path[len("/media/") : -len("/dismiss")])
                updated, error = handle_media_dismiss_submission(config.media_archive_path, content_id)

                if updated is None and error is None:
                    body = (
                        '<a class="back" href="/media">&larr; 목록으로</a>'
                        f'<div class="error">Draft를 찾을 수 없습니다: {escape(content_id)}</div>'
                    )
                    self._send_html(_page("MEDIA Draft 없음", body), status=404)
                    return

                if error:
                    self._send_html(
                        _page(
                            "보류 실패",
                            '<a class="back" href="/media">&larr; 목록으로</a>'
                            f'<div class="error">{escape(error)}</div>',
                        ),
                        status=400,
                    )
                    return

                self._redirect(f"/media/{content_id}?notice=dismissed")
                return

            self._send_html(_page("페이지 없음", "<p>페이지를 찾을 수 없습니다.</p>"), status=404)

    return DashboardRequestHandler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="TAK SCOUT Dashboard: 웹 브라우저에서 오늘의 소재를 보고 최대 3턴 답하는 MVP"
    )
    parser.add_argument("--host", default="127.0.0.1", help="바인딩 host (기본값: 127.0.0.1, 로컬 전용)")
    parser.add_argument("--port", type=int, default=8000, help="포트 (기본값: 8000)")
    parser.add_argument(
        "--daily-pack", type=Path, default=ROOT / "data" / "tak_scout_daily.json",
        help="읽기 전용 TAK SCOUT 결과 경로 (기본값: data/tak_scout_daily.json)",
    )
    parser.add_argument(
        "--answers", type=Path, default=ROOT / "data" / "tak_interview_answers.json",
        help="TAK INTERVIEW 답변 저장 경로 (기본값: data/tak_interview_answers.json)",
    )
    parser.add_argument(
        "--knowledge", type=Path, default=ROOT / "data" / "tak_brain_knowledge.json",
        help="KNOWLEDGE 누적 저장 경로 (기본값: data/tak_brain_knowledge.json)",
    )
    parser.add_argument(
        "--skipped", type=Path, default=ROOT / "data" / "tak_scout_dashboard_skipped.json",
        help="관심 없음 표시 저장 경로 (기본값: data/tak_scout_dashboard_skipped.json)",
    )
    parser.add_argument(
        "--sessions", type=Path, default=ROOT / "data" / "tak_interview_sessions.json",
        help="멀티턴 인터뷰 세션 저장 경로 (기본값: data/tak_interview_sessions.json)",
    )
    parser.add_argument(
        "--pending", type=Path, default=ROOT / "data" / "tak_threads_pending.json",
        help="Threads 검수 대기 draft 경로 (기본값: data/tak_threads_pending.json, 5-11 Phase 2)",
    )
    parser.add_argument(
        "--title-translations", type=Path, default=ROOT / "data" / "tak_scout_title_translations.json",
        help="한국어 표시용 제목 번역 캐시 경로 (기본값: data/tak_scout_title_translations.json, 5-20)",
    )
    parser.add_argument(
        "--media-archive", type=Path, default=ROOT / "data" / "tak_media_archive.json",
        help="TAK MEDIA 배치 결과 아카이브 경로, 읽기 전용 (기본값: data/tak_media_archive.json, 5-27)",
    )
    parser.add_argument(
        "--shorts-scripts", type=Path, default=ROOT / "data" / "shorts_scripts",
        help="승인된 Shorts ShortsScript JSON 저장 디렉터리 (기본값: data/shorts_scripts, 5-29)",
    )
    parser.add_argument(
        "--blog-history", type=Path, default=ROOT / "data" / "blog_publish_log.json",
        help="Blog 게시 이력 경로, 읽기 전용(downstream 상태 표시용) (기본값: data/blog_publish_log.json, 5-29)",
    )
    parser.add_argument(
        "--performance", type=Path, default=ROOT / "data" / "tak_performance.json",
        help="성과 스냅샷 저장소 경로, 읽기 전용(/performance 화면용) (기본값: data/tak_performance.json, 6-01)",
    )
    parser.add_argument(
        "--generation-archive", type=Path, action="append", default=[],
        help=(
            "MEDIA generation pool 경로(/media/generations 검수 화면용, 6-07/6-08). "
            "여러 번 줄 수 있다(예: --generation-archive a.json --generation-archive b.json). "
            "생략하면 data/tak_media_generation_*.json 이름 규칙에 맞는 파일을 자동으로 찾는다 "
            "(6-08 auto-discovery). 하나 이상 명시하면 자동 탐색 대신 명시한 파일만 정확히 쓴다 - "
            "이름 규칙을 따르지 않는 예전 파일(예: 6-05의 "
            "tak_media_archive_6-05_..._regeneration.json)을 보고 싶을 때 이 옵션으로 직접 지정한다. "
            "production archive(--media-archive)와는 완전히 별개다."
        ),
    )
    args = parser.parse_args(argv)

    if not args.daily_pack.exists():
        print(
            f"오류: {args.daily_pack}가 없습니다. 먼저 python3 scripts/run_scout.py를 실행하세요.",
            file=sys.stderr,
        )
        return 1

    generation_archive_paths = resolve_generation_archive_paths(
        tuple(args.generation_archive), args.media_archive.parent
    )
    if args.generation_archive:
        print(f"TAK MEDIA Generation Pool: 명시된 파일 {len(generation_archive_paths)}개 사용")
    elif generation_archive_paths:
        names = ", ".join(path.name for path in generation_archive_paths)
        print(f"TAK MEDIA Generation Pool: 자동 탐색됨 ({len(generation_archive_paths)}개) - {names}")
    else:
        print("TAK MEDIA Generation Pool: 발견된 파일 없음 (data/tak_media_generation_*.json)")

    config = DashboardConfig(
        daily_pack_path=args.daily_pack,
        answers_path=args.answers,
        knowledge_path=args.knowledge,
        skipped_path=args.skipped,
        sessions_path=args.sessions,
        pending_path=args.pending,
        title_translations_path=args.title_translations,
        media_archive_path=args.media_archive,
        shorts_scripts_path=args.shorts_scripts,
        blog_history_path=args.blog_history,
        performance_path=args.performance,
        generation_archive_paths=generation_archive_paths,
    )

    # scripts/run_media_batch.py, scripts/run_daily.py, scripts/tak_auto.py와 동일한
    # 관례: 실제 provider 생성은 CLI 진입점(main)에서만 하고, 하위 함수에는 명시적으로
    # 넘긴다. 환경변수가 없으면 조용히 템플릿 전용(llm_provider=None)으로 진행한다 -
    # LLM 미설정이 Dashboard 실행 자체를 막지 않는다.
    try:
        llm_provider: InterviewLLMProvider | None = InterviewLLMProvider.from_environment()
        print("TAK SCOUT Dashboard: LLM 인터뷰 provider 연결됨 (실패 시 템플릿으로 자동 대체)")
    except LLMConfigurationError:
        llm_provider = None
        print("TAK SCOUT Dashboard: LLM 환경변수 미설정 - 템플릿 질문만 사용합니다.")

    handler_class = make_handler_class(config, llm_provider=llm_provider)
    server = ThreadingHTTPServer((args.host, args.port), handler_class)
    print(f"TAK SCOUT Dashboard 실행 중: http://{args.host}:{args.port}")
    print("Ctrl+C로 종료하세요.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nTAK SCOUT Dashboard 종료")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
