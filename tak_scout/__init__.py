"""TAK SCOUT: 공개 RSS에서 소재를 찾고, TAK INTERVIEW로 티몽의 의견을 받아
TAK BRAIN KNOWLEDGE로 연결하는 최소 파이프라인.

이 패키지는 로그인, 브라우저 크롤링, 접근 제한 우회를 하지 않는다. 공개 RSS만 읽고,
원문 전체가 아니라 제목/짧은 요약/URL 중심으로만 소재를 저장한다.
"""

from .models import ScoutCandidate, compute_scout_id, subject_label
from .rss import ScoutRssError, fetch_rss, parse_rss_items
from .collector import (
    DEFAULT_MAX_CANDIDATES,
    SourceCollectionResult,
    build_daily_pack,
    collect_all,
    dedupe_candidates,
    load_daily_pack,
    load_sources,
    render_daily_pack_markdown,
    save_daily_pack_json,
    save_daily_pack_markdown,
    select_candidates,
)
from .interview import (
    InterviewQuestion,
    build_interview_question,
    build_interview_questions,
    load_questions,
    render_questions_markdown,
    save_questions_json,
    save_questions_markdown,
)
from .answers import (
    VALID_OPTIONS,
    InterviewAnswer,
    InterviewAnswerError,
    load_answers,
    save_answers,
    upsert_answer,
)
from .knowledge_bridge import append_scout_knowledge, build_knowledge_from_interview
from .scoring import ScoutScore, rank_candidates, score_candidate, top_candidates

__all__ = [
    "ScoutCandidate",
    "compute_scout_id",
    "subject_label",
    "ScoutRssError",
    "fetch_rss",
    "parse_rss_items",
    "DEFAULT_MAX_CANDIDATES",
    "SourceCollectionResult",
    "build_daily_pack",
    "collect_all",
    "dedupe_candidates",
    "load_daily_pack",
    "load_sources",
    "render_daily_pack_markdown",
    "save_daily_pack_json",
    "save_daily_pack_markdown",
    "select_candidates",
    "InterviewQuestion",
    "build_interview_question",
    "build_interview_questions",
    "load_questions",
    "render_questions_markdown",
    "save_questions_json",
    "save_questions_markdown",
    "VALID_OPTIONS",
    "InterviewAnswer",
    "InterviewAnswerError",
    "load_answers",
    "save_answers",
    "upsert_answer",
    "append_scout_knowledge",
    "build_knowledge_from_interview",
    "ScoutScore",
    "rank_candidates",
    "score_candidate",
    "top_candidates",
]
