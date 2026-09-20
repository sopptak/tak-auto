"""TAK SCOUT 후보 + TAK INTERVIEW 답변을 TAK BRAIN KNOWLEDGE(pending)로 연결한다.

외부 자료의 사실과 티몽의 의견을 명확하게 구분한다.

    SOURCE FACT             - 외부 자료에서 확인한 사실(요약/제목)
    SOURCE URL              - 원문 주소
    USER ANGLE              - 티몽이 A/B/C 중 선택한 의견
    USER ORIGINAL THOUGHT   - D를 선택했을 때 직접 입력한 생각

이 네 가지는 evidence에 라벨을 붙여 그대로 남긴다. 외부 블로그/기사 문장을 그대로
복사하거나 재작성하지 않으며, 답변하지 않은 후보는 KNOWLEDGE로 만들지 않는다.

기존 TAK BRAIN 구조를 재사용한다: KnowledgeRecord 스키마와
``tak_brain.knowledge.validate_knowledge``를 그대로 쓰고, 생성 직후 상태는 항상
pending이다(``review_knowledge.py``로 사람이 승인해야 TAK MEDIA 대상이 된다).
"""

from __future__ import annotations

from pathlib import Path
import hashlib
import json
import tempfile

from blog_importer.models import utc_now
from tak_brain.models import CATEGORIES, KnowledgeRecord
from tak_brain.knowledge import validate_knowledge

from .answers import InterviewAnswer, load_answers
from .collector import load_daily_pack
from .models import ScoutCandidate, subject_label


# data/scout_sources.json의 category는 영문(예: "finance")도 쓸 수 있으므로,
# tak_brain.models.CATEGORIES(한글)에 대응하는 것만 최소로 번역한다.
_CATEGORY_ALIASES = {"finance": "금융"}

_OPTION_ANGLE_TEMPLATES = {
    "A": "{subject}를 긍정적으로 본다.",
    "B": "{subject}를 부정적으로 본다.",
    "C": "상황을 더 지켜봐야 한다고 본다.",
}


def _angle_text(candidate: ScoutCandidate, answer: InterviewAnswer) -> str:
    if answer.selected_option == "D":
        return answer.custom_answer
    template = _OPTION_ANGLE_TEMPLATES[answer.selected_option]
    return template.format(subject=subject_label(candidate))


def _knowledge_id(answer: InterviewAnswer) -> str:
    payload = f"{answer.scout_id}:{answer.selected_option}:{answer.custom_answer}"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"knowledge-scout-{digest}"


def _map_category(raw_category: str) -> str:
    if raw_category in CATEGORIES:
        return raw_category
    return _CATEGORY_ALIASES.get(raw_category, "기타")


def build_knowledge_from_interview(candidate: ScoutCandidate, answer: InterviewAnswer) -> KnowledgeRecord:
    """소재 1건 + 답변 1건을 pending 상태의 KNOWLEDGE 초안으로 만든다."""
    if candidate.scout_id != answer.scout_id:
        raise ValueError("candidate와 answer의 scout_id가 일치하지 않습니다.")

    source_fact = candidate.summary.strip() or candidate.title
    angle = _angle_text(candidate, answer)

    evidence = [f"SOURCE FACT: {source_fact}", f"SOURCE URL: {candidate.source_url}"]
    if answer.selected_option == "D":
        evidence.append(f"USER ORIGINAL THOUGHT: {angle}")
    else:
        evidence.append(f"USER ANGLE: {angle}")

    category = _map_category(candidate.category)
    # 6-04: article_type은 category(=candidate.category, data/scout_sources.json에 등록된
    # RSS 소스의 블랭킷 카테고리, 예: "BBC Business" -> "finance")에서 유추하지 않는다.
    # category/domain은 "이 소재가 대략 어떤 성격의 출처에서 왔는가"를 나타낼 뿐 이 후보
    # 기사 하나의 실제 내용을 분석한 결과가 아니다 - 예를 들어 BBC Business RSS에 실린
    # AI 안전성 기사(Anthropic CEO의 AI 개발 속도 완화 촉구)도 "finance" 카테고리로
    # 통째로 태깅된다(실제 재현: knowledge-scout-b28b782b2a33,
    # docs/6-04_media_generation_quality_investigation.md). article_type == "finance"는
    # content_engine/generator.py의 _profile()과 content_engine/rewrite.py의
    # _finance_errors()가 "이 콘텐츠는 실제로 대출/금융기관 심사 기준을 다룬다"고 신뢰하는
    # 신호라서, 무관한 콘텐츠에 잘못 붙으면 "재무 판단..." 제목과 "금융기관의 공식 심사
    # 기준으로 해석하지 않습니다" 문구가 엉뚱하게 삽입된다. 실제 본문을 분석해 분류하는
    # tak_brain.article_types.ArticleTypeClassifier(블로그 RAW 임포트 경로가 쓰는 것과
    # 동일한 분류기)가 SCOUT 후보에는 적용되지 않으므로, 이 경로에는 신뢰할 수 있는
    # content-based 분류 신호가 아예 없다 - 없는 신호를 있는 것처럼 만들지 않고 None으로
    # 둔다. category/domain(예: "금융")은 그대로 유지한다 -
    # content_engine/blog_publish_pack.py의 is_review_required()가 이 값만으로 이미
    # "사람 확인 필요" 안전장치를 독립적으로 보장하므로(article_type과 무관), 이 변경으로
    # 안전성이 약화되지 않는다.
    article_type = None

    knowledge = KnowledgeRecord(
        id=_knowledge_id(answer),
        source_raw_id=candidate.scout_id,
        source_url=candidate.source_url,
        title=candidate.title,
        article_type=article_type,
        domain=category,
        category=category,
        knowledge_type="의견",
        # TAK MEDIA(content_engine)가 실제로 참조하는 필드: 원문 사실은 lesson에,
        # 티몽의 의견은 reusable_principle에 담아 둘 다 콘텐츠 생성 근거로 쓰인다.
        lesson=source_fact,
        reusable_principle=angle,
        evidence=tuple(evidence),
        inference_method="rule_based_template",
        confidence=None,
        created_at=utc_now(),
        knowledge_review_status="pending",
        # 사람이 리뷰할 때 사실/의견을 한눈에 구분할 수 있도록 별도 필드에도 남긴다.
        factual_information=source_fact,
        opinion=angle,
        current_validity="확인 필요",
        verification_required=True,
    )
    validate_knowledge(knowledge)
    return knowledge


def append_scout_knowledge(
    daily_pack_path: Path | str,
    answers_path: Path | str,
    knowledge_path: Path | str,
) -> tuple[int, int, int]:
    """답변이 있는 TAK SCOUT 후보만 KNOWLEDGE 파일에 누적한다.

    답변하지 않은 후보는 건너뛰고, 이미 같은 답변으로 만들어진 KNOWLEDGE는 중복
    추가하지 않는다(같은 scout_id+답변이면 KNOWLEDGE id가 결정적으로 같아진다).
    기존 KNOWLEDGE(예: 블로그 RAW에서 만든 것)는 그대로 보존한다.

    반환값: (created, skipped_unanswered, duplicates)
    """
    candidates = {candidate.scout_id: candidate for candidate in load_daily_pack(daily_pack_path)}
    answers = {answer.scout_id: answer for answer in load_answers(answers_path)}

    output_path = Path(knowledge_path)
    if output_path.exists():
        raw_text = output_path.read_text(encoding="utf-8").strip()
        data = json.loads(raw_text) if raw_text else []
        if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
            raise ValueError("KNOWLEDGE 파일은 객체 목록이어야 합니다.")
    else:
        data = []

    existing_ids = {item.get("id") for item in data}

    created = 0
    duplicates = 0
    skipped_unanswered = 0
    for scout_id, candidate in candidates.items():
        answer = answers.get(scout_id)
        if answer is None:
            skipped_unanswered += 1
            continue
        knowledge = build_knowledge_from_interview(candidate, answer)
        if knowledge.id in existing_ids:
            duplicates += 1
            continue
        data.append(knowledge.to_dict())
        existing_ids.add(knowledge.id)
        created += 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=output_path.parent, delete=False) as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temp_path = Path(handle.name)
    temp_path.replace(output_path)
    return created, skipped_unanswered, duplicates
