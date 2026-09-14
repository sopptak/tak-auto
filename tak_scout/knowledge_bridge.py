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


_FINANCE_CATEGORIES = ("금융", "대출", "경매", "부동산")

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
    article_type = "finance" if category in _FINANCE_CATEGORIES else None

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
