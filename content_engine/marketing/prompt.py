"""콘텐츠 생성용 Prompt contract. 승인된 MarketingBrief를 8단계 사고 순서로 직렬화한다.

LLM을 호출하지 않는다 - 생성 단계가 그대로 쓸 수 있는 구조화된 프롬프트(dict)만 만든다.
"""

from __future__ import annotations

from .briefs import readiness_blockers
from .models import DIMENSIONS, MarketingBrief, MarketingError
from .platforms import STRATEGIES

THINKING_STEPS: tuple[tuple[str, str], ...] = (
    ("market_problem", "시장에 어떤 문제가 있는가?"),
    ("who", "누가 그 문제를 가지고 있는가?"),
    ("why_care", "그 사람이 왜 관심을 가져야 하는가?"),
    ("first_line", "첫 문장에서 무엇을 보여줄 것인가?"),
    ("story", "어떤 이야기를 통해 끝까지 읽게 할 것인가?"),
    ("proof", "어떤 증거로 신뢰를 만들 것인가?"),
    ("action", "무엇을 행동하게 만들 것인가?"),
    ("distribution", "어느 채널에서 어떻게 유통할 것인가?"),
)

CONSTRAINTS: tuple[str, ...] = (
    "evidence에 없는 사실, 수치, 후기를 만들어 내지 않는다.",
    "evidence는 검증 전 근거다. 단정하지 말고 출처를 구분해 표현한다.",
    "과장/허위 긴급성/근거 없는 효과 보장을 쓰지 않는다.",
    "결과는 초안이며 사람이 검토하기 전에는 발행하지 않는다.",
)


# 플랫폼별 생성 계약: 결과물이 반드시 갖춰야 할 구성 요소.
PLATFORM_CONTRACTS: dict[str, tuple[str, ...]] = {
    "blog": ("검색 의도에 맞는 제목/도입", "고객 문제의 해결 절차", "evidence 기반 근거", "신뢰 요소(출처 구분)", "CTA"),
    "threads": ("강한 주장", "반전", "공감", "논쟁 포인트", "답글 유도"),
    "shorts": ("1~2초 안에 끝나는 hook", "한 가지 핵심 메시지", "장면 변화 지시", "짧은 CTA"),
    "youtube": ("hook", "problem", "tension", "insight", "transformation", "proof", "CTA"),
}


def build_content_prompt(brief: MarketingBrief, allow_draft: bool = False) -> dict:
    """approved 브리프로 프롬프트 계약을 만든다. 게이트를 통과하지 못하면 MarketingError."""
    if not allow_draft:
        blockers = readiness_blockers(brief)
        if blockers:
            raise MarketingError("콘텐츠 생성 준비가 안 된 브리프: " + " / ".join(blockers))
    platform = brief.platform or brief.distribution.target_platform
    strategy = STRATEGIES.get(platform)
    return {
        "brief_id": brief.brief_id,
        "platform": platform,
        "thinking_steps": [{"id": key, "question": question} for key, question in THINKING_STEPS],
        "brief": {
            "topic": brief.topic, "target_audience": brief.target_audience,
            "customer_problem": brief.customer_problem, "desired_action": brief.desired_action,
            **{name: brief.dimension(name).filled() for name in DIMENSIONS},
        },
        "platform_strategy": None if strategy is None else {
            "angle": strategy.angle, "primary_axis": strategy.primary_axis, "emphasis": list(strategy.emphasis),
            "format_notes": strategy.format_notes,
        },
        "generation_contract": list(PLATFORM_CONTRACTS.get(platform, ())),
        "evidence": [item.to_dict() for item in brief.evidence],
        "constraints": list(CONSTRAINTS),
        "open_questions": brief.missing_fields(),
        "is_draft_brief": brief.status != "approved",
        "requires_human_review": True,
    }


def render_prompt_text(contract: dict) -> str:
    """계약 dict를 LLM에 그대로 넘길 수 있는 텍스트로 만든다."""
    lines = [f"[플랫폼] {contract['platform'] or '공통'}", "[생각 순서]"]
    lines += [f"{index}. {step['question']}" for index, step in enumerate(contract["thinking_steps"], 1)]
    brief = contract["brief"]
    lines += ["[브리프]", f"주제: {brief['topic']}", f"대상: {brief['target_audience']}",
              f"고객 문제: {brief['customer_problem']}", f"유도할 행동: {brief['desired_action']}"]
    for name in DIMENSIONS:
        for element, value in brief[name].items():
            lines.append(f"{name}.{element}: {value}")
    if contract["platform_strategy"]:
        strategy = contract["platform_strategy"]
        lines += [f"[채널 전략] {strategy['angle']} - {strategy['format_notes']}"]
    if contract.get("generation_contract"):
        lines.append("[생성 계약] " + " / ".join(contract["generation_contract"]))
    lines.append("[근거(검증 전)]")
    lines += [f"- ({item['kind']}) {item['title']}: {item['snippet']} {item['url']}".rstrip() for item in contract["evidence"]]
    lines.append("[제약]")
    lines += [f"- {rule}" for rule in contract["constraints"]]
    return "\n".join(lines)
