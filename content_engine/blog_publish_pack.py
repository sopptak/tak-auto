"""승인 KNOWLEDGE의 Blog Draft를 "네이버 블로그 게시 후보(Blog Publishing Pack)"로 변환한다.

TAK AUTO는 네이버 블로그에 자동 로그인/자동 게시를 하지 않는다(정책·보안상 구현하지 않음).
대신 이 모듈은 하루 최대 N개의 Blog 콘텐츠 후보를 사람이 네이버 블로그에 복사/붙여넣기하고
직접 예약 발행하기 좋은 Markdown 문서로 만드는 책임만 가진다.

기존 구조를 그대로 재사용한다:

- ``content_engine.pipeline.run_media_batch``/``MediaBatchReport`` (Blog Draft 생성/검증 자체는
  변경하지 않는다)
- ``content_engine.publish_history.PublishHistory``/``compute_content_id`` (Blog 전용 이력 파일에
  그대로 재사용한다. Threads와 동일한 지문 계산 방식을 쓰되, 저장 파일만 분리한다)

Blog는 Threads와 달리 API 게시 성공 응답으로 이력을 자동 기록할 수 없다. 따라서 이 모듈은
"게시 완료"를 자동으로 판단하지 않으며, 사람이 실제로 네이버에 게시를 마친 뒤
``scripts/mark_blog_published.py``로 명시적으로 기록해야만 다음 Pack 생성에서 같은 콘텐츠가
후보에서 제외된다.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any

from tak_brain.models import KnowledgeRecord

from .media_archive import MediaArchiveRecord
from .pipeline import MediaBatchReport
from .publish_history import PublishHistory, compute_content_id


DEFAULT_MAX_CANDIDATES = 5

# KNOWLEDGE의 category/domain/article_type 중 하나라도 여기 해당하면 review_required=True.
# tak_brain.models.CATEGORIES에 정의된 지원 category 중 사실관계 오류가 실제 금전적·법적
# 피해로 이어질 수 있는 항목만 추린다.
FINANCE_REVIEW_KEYWORDS = ("금융", "대출", "경매", "부동산")

_KEYWORD_TOKEN_PATTERN = re.compile(r"[A-Za-z가-힣]{2,}")

_GENERIC_IMAGE_IDEAS = (
    "대표 이미지: 제목의 핵심 주제를 상징적으로 보여주는 이미지 1장",
    "본문 이미지 1: 글에서 다루는 상황·문제를 보여주는 이미지",
    "본문 이미지 2: 결과·교훈·판단기준을 정리한 이미지 또는 간단한 인포그래픽",
)


@dataclass(frozen=True)
class BlogPublishItem:
    """사람이 네이버 블로그에 옮길 Blog 게시 후보 1건."""

    sequence: int
    title: str
    body: str
    category: str
    keywords: tuple[str, ...]
    hashtags: tuple[str, ...]
    image_ideas: tuple[str, ...]
    knowledge_id: str
    source_url: str
    review_required: bool
    content_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "title": self.title,
            "body": self.body,
            "category": self.category,
            "keywords": list(self.keywords),
            "hashtags": list(self.hashtags),
            "image_ideas": list(self.image_ideas),
            "knowledge_id": self.knowledge_id,
            "source_url": self.source_url,
            "review_required": self.review_required,
            "content_id": self.content_id,
        }


def is_review_required(knowledge: KnowledgeRecord | None) -> bool:
    """금융·대출·경매·부동산 관련 KNOWLEDGE는 사람의 최종 확인이 필요하다.

    knowledge를 찾을 수 없는 예외적인 경우에는 안전한 쪽(True)으로 기본값을 둔다.
    면책 문구(예: "공식 심사 기준으로 해석하지 않습니다")는 이 판단을 대체하지 않는다.
    """
    if knowledge is None:
        return True
    if knowledge.article_type == "finance":
        return True
    if knowledge.category and knowledge.category in FINANCE_REVIEW_KEYWORDS:
        return True
    if knowledge.domain and any(keyword in knowledge.domain for keyword in FINANCE_REVIEW_KEYWORDS):
        return True
    return False


def suggest_category(knowledge: KnowledgeRecord | None) -> str:
    """네이버 블로그 카테고리 추천(참고용). 검색 노출을 보장하지 않는다."""
    if knowledge is None:
        return "기타"
    if is_review_required(knowledge):
        return "금융/재테크"
    if knowledge.article_type == "book_philosophy":
        return "독서/책리뷰"
    if knowledge.article_type == "workplace":
        return "직장생활/인간관계"
    if knowledge.article_type in {"experience", "ai_business"}:
        return "일상/자기계발"
    return "기타"


def suggest_keywords(title: str, knowledge: KnowledgeRecord | None, limit: int = 5) -> tuple[str, ...]:
    """제목/도메인/카테고리에서 이미 검증된 텍스트만 추출한다(새 사실을 추가하지 않음)."""
    candidates: list[str] = []
    if knowledge is not None:
        if knowledge.category:
            candidates.append(knowledge.category)
        if knowledge.domain:
            candidates.extend(part.strip() for part in re.split(r"[·,/]", knowledge.domain) if part.strip())
    candidates.extend(_KEYWORD_TOKEN_PATTERN.findall(title))

    seen: list[str] = []
    for candidate in candidates:
        if candidate not in seen:
            seen.append(candidate)
        if len(seen) >= limit:
            break
    return tuple(seen)


def suggest_hashtags(keywords: Sequence[str]) -> tuple[str, ...]:
    return tuple(f"#{keyword.replace(' ', '')}" for keyword in keywords if keyword.strip())


def suggest_image_ideas() -> tuple[str, ...]:
    """콘텐츠별 사실을 포함하지 않는 범용 이미지 아이디어(사람이 직접 선택해야 함)."""
    return _GENERIC_IMAGE_IDEAS


def select_blog_publish_candidates(
    blog_items: Sequence[Mapping[str, Any]],
    history: PublishHistory,
    max_count: int = DEFAULT_MAX_CANDIDATES,
) -> list[tuple[Mapping[str, Any], str]]:
    """valid Blog 항목 중 아직 게시 이력에 없는 것만, 서로 다른 KNOWLEDGE를 우선해 최대 max_count개 고른다.

    - platform == "blog", status == "valid"만 대상으로 한다.
    - history(PublishHistory)에 이미 기록된 content_id는 제외한다.
    - 1차로 KNOWLEDGE별 처음 등장한 항목(서로 다른 KNOWLEDGE)을 우선 채우고,
      슬롯이 남으면 2차로 나머지(동일 KNOWLEDGE의 추가 항목)로 채운다.
    """
    published_ids = history.published_content_ids()

    candidates: list[tuple[Mapping[str, Any], str]] = []
    for item in blog_items:
        if item.get("platform") != "blog" or item.get("status") != "valid":
            continue
        content_id = compute_content_id(item)
        if content_id in published_ids:
            continue
        candidates.append((item, content_id))

    seen_knowledge: set[Any] = set()
    first_pass: list[tuple[Mapping[str, Any], str]] = []
    remaining: list[tuple[Mapping[str, Any], str]] = []
    for item, content_id in candidates:
        knowledge_id = item.get("knowledge_id")
        if knowledge_id not in seen_knowledge:
            seen_knowledge.add(knowledge_id)
            first_pass.append((item, content_id))
        else:
            remaining.append((item, content_id))

    ordered = first_pass + remaining
    return ordered[:max_count]


def build_blog_publish_pack(
    report: MediaBatchReport,
    records: Iterable[KnowledgeRecord],
    history: PublishHistory,
    max_count: int = DEFAULT_MAX_CANDIDATES,
) -> tuple[BlogPublishItem, ...]:
    """MediaBatchReport와 원본 KNOWLEDGE 목록에서 오늘의 Blog Publishing Pack을 만든다."""
    knowledge_by_id = {record.id: record for record in records}
    blog_items = [
        item.to_dict() for item in report.items if item.platform == "blog" and item.status == "valid"
    ]
    selection = select_blog_publish_candidates(blog_items, history, max_count=max_count)

    results: list[BlogPublishItem] = []
    for index, (item, content_id) in enumerate(selection, start=1):
        knowledge = knowledge_by_id.get(item.get("knowledge_id"))
        title = str(item.get("rewritten_title") or item.get("original_title") or "")
        body = str(item.get("rewritten_body") or item.get("original_body") or "")
        keywords = suggest_keywords(title, knowledge)

        results.append(
            BlogPublishItem(
                sequence=index,
                title=title,
                body=body,
                category=suggest_category(knowledge),
                keywords=keywords,
                hashtags=suggest_hashtags(keywords),
                image_ideas=suggest_image_ideas(),
                knowledge_id=str(item.get("knowledge_id") or ""),
                source_url=str(item.get("source_url") or ""),
                review_required=is_review_required(knowledge),
                content_id=content_id,
            )
        )
    return tuple(results)


# --- MEDIA archive(5-27/5-29) 기반 Blog downstream 연결 -----------------------
#
# build_blog_publish_pack()/select_blog_publish_candidates()는 위에서 전혀
# 수정하지 않는다 - "방금 실행한 MediaBatchReport에서 valid Blog를 바로 Pack에
# 담는" 기존 흐름은 그대로 둔다. 아래 두 함수는 그 대신 "사람이 MEDIA
# Dashboard에서 이미 승인(review_status == approved)한 것만 후보로 쓴다"는
# 별도의 입력 소스를 추가할 뿐이며, 선정 규칙(서로 다른 KNOWLEDGE 우선,
# PublishHistory 중복 제외, max_count)과 BlogPublishItem 변환 로직(카테고리/
# 키워드/해시태그/이미지 제안, review_required 판정)은 위 함수들과 동일하게
# 재사용한다.


def select_approved_blog_candidates_from_archive(
    records: Sequence[MediaArchiveRecord],
    history: PublishHistory,
    max_count: int = DEFAULT_MAX_CANDIDATES,
) -> list[MediaArchiveRecord]:
    """MEDIA archive에서 platform=="blog", generation_status=="valid",
    review_status=="approved"이고 아직 게시 이력에 없는 항목만, 서로 다른
    KNOWLEDGE를 우선해 최대 max_count개 고른다.

    select_blog_publish_candidates()와 동일한 2단계 선정 규칙(1차: 서로 다른
    KNOWLEDGE 우선, 2차: 나머지)을 그대로 따르되, content_id를
    compute_content_id()로 다시 계산하지 않는다 - MediaArchiveRecord는 이미
    자신의 content_id를 갖고 있다(그 값도 결국 compute_content_id()로 계산된
    것이므로 Threads/Blog 게시 이력과 동일한 지문 체계를 그대로 공유한다).
    """
    published_ids = history.published_content_ids()
    candidates = [
        record
        for record in records
        if record.platform == "blog"
        and record.generation_status == "valid"
        and record.review_status == "approved"
        and record.content_id not in published_ids
    ]

    seen_knowledge: set[str] = set()
    first_pass: list[MediaArchiveRecord] = []
    remaining: list[MediaArchiveRecord] = []
    for record in candidates:
        if record.knowledge_id not in seen_knowledge:
            seen_knowledge.add(record.knowledge_id)
            first_pass.append(record)
        else:
            remaining.append(record)

    return (first_pass + remaining)[:max_count]


def build_blog_publish_pack_from_archive(
    records: Sequence[MediaArchiveRecord],
    knowledge_records: Iterable[KnowledgeRecord],
    history: PublishHistory,
    max_count: int = DEFAULT_MAX_CANDIDATES,
) -> tuple[BlogPublishItem, ...]:
    """MEDIA archive에서 사람이 이미 승인한 Blog 항목만으로 오늘의 Blog Publishing
    Pack을 만든다. build_blog_publish_pack()의 입력을 "방금 생성한 MediaBatchReport"
    대신 "사람이 검수를 마친 archive"로 바꾼 버전일 뿐, BlogPublishItem으로
    변환하는 로직(카테고리/키워드/해시태그/이미지 제안, review_required 판정)은
    완전히 동일하게 재사용한다.

    각 후보의 제목/본문은 ``record.final_title``/``record.final_body``를 쓴다 -
    사람이 MEDIA Dashboard에서 수정했다면(edited_title/edited_body) 그 수정본이,
    수정하지 않았다면 AI 생성 결과(rewritten_title/rewritten_body)가 그대로
    쓰인다(5-29 설계: "edited가 있으면 edited, 없으면 generated").
    """
    knowledge_by_id = {record.id: record for record in knowledge_records}
    selection = select_approved_blog_candidates_from_archive(records, history, max_count=max_count)

    results: list[BlogPublishItem] = []
    for index, record in enumerate(selection, start=1):
        knowledge = knowledge_by_id.get(record.knowledge_id)
        title = record.final_title
        body = record.final_body
        keywords = suggest_keywords(title, knowledge)

        results.append(
            BlogPublishItem(
                sequence=index,
                title=title,
                body=body,
                category=suggest_category(knowledge),
                keywords=keywords,
                hashtags=suggest_hashtags(keywords),
                image_ideas=suggest_image_ideas(),
                knowledge_id=record.knowledge_id,
                source_url=record.source_url,
                review_required=is_review_required(knowledge),
                content_id=record.content_id,
            )
        )
    return tuple(results)


def _render_item(item: BlogPublishItem) -> str:
    divider = "━" * 20
    general_box = "☑" if not item.review_required else "□"
    finance_box = "☑" if item.review_required else "□"
    lines = [
        divider,
        f"[{item.sequence}번 글]",
        f"카테고리: {item.category}",
        f"제목: {item.title}",
        "",
        "본문:",
        item.body,
        "",
        "핵심 키워드:",
        ", ".join(item.keywords) if item.keywords else "(제안 없음)",
        "",
        "해시태그:",
        " ".join(item.hashtags) if item.hashtags else "(제안 없음)",
        "",
        "이미지 권장:",
        *[f"- {idea}" for idea in item.image_ideas],
        "",
        "검토:",
        f"{general_box} 일반 콘텐츠",
        f"{finance_box} 금융/부동산/대출 → 사람 확인 필요",
        "",
        "원본:",
        item.knowledge_id,
        f"source_url: {item.source_url}",
        divider,
    ]
    return "\n".join(lines)


def render_markdown(items: Sequence[BlogPublishItem], generated_at: str | None = None) -> str:
    """사람이 그대로 읽고 복사할 수 있는 Markdown 문서를 만든다."""
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    review_count = sum(1 for item in items if item.review_required)
    header = [
        "# TAK AUTO 네이버 블로그 게시 후보 (Blog Publishing Pack)",
        "",
        f"생성 시각(UTC): {generated_at}",
        f"오늘의 후보: {len(items)}건 (최대 {DEFAULT_MAX_CANDIDATES}건, 이 중 사람 확인 필요 {review_count}건)",
        "",
        "⚠️ 이 문서는 네이버 블로그에 자동으로 게시되지 않습니다. 아래 내용을 검토한 뒤 사람이 직접",
        "네이버 블로그에 복사/붙여넣기하고 카테고리를 확인한 다음 예약 발행해야 합니다.",
        "⚠️ '금융/부동산/대출 → 사람 확인 필요'로 표시된 글은 게시 전 반드시 원문 근거·확정적 표현·",
        "현재 규정/금리/세금 의존 여부를 사람이 직접 확인해야 합니다.",
        "⚠️ 카테고리·키워드·해시태그·이미지 아이디어는 참고용 제안이며, 검색 순위나 조회수를",
        "보장하지 않습니다.",
        "",
    ]

    if not items:
        body = ["오늘 생성할 새로운 Blog 게시 후보가 없습니다. (승인 KNOWLEDGE 소진 또는 전부 게시 완료)"]
    else:
        body = [_render_item(item) for item in items]

    return "\n".join(header) + "\n\n" + "\n\n".join(body) + "\n"


def save_markdown(
    items: Sequence[BlogPublishItem],
    path: Path | str,
    generated_at: str | None = None,
) -> None:
    """Blog Publishing Pack을 Markdown 파일로 저장한다(매 실행마다 새로 덮어쓰는 휘발성 파일)."""
    target_path = Path(path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(render_markdown(items, generated_at=generated_at), encoding="utf-8")
