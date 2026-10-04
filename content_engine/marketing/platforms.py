"""플랫폼별 전략 프로필과 브리프 파생. 같은 소재라도 채널마다 다른 distribution angle을 만든다.

프로필은 '무엇을 강조할지'의 가이드이며 문장을 생성하지 않는다(생성은 프롬프트 계약 이후 단계).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .models import PLATFORMS, MarketingBrief, MarketingError, compute_brief_id


@dataclass(frozen=True)
class PlatformStrategy:
    platform: str
    angle: str
    primary_axis: str  # attention | engagement | conversion
    emphasis: tuple[str, ...]  # 우선 채워야 할 요소 (dimension.element)
    format_notes: str


STRATEGIES: dict[str, PlatformStrategy] = {
    "blog": PlatformStrategy(
        "blog", "검색 의도 + 문제 해결", "conversion",
        ("distribution.search_intent", "distribution.discovery_keyword", "sales.customer_problem", "sales.proof",
         "sales.call_to_action"),
        "검색어에 직접 답하는 구조, 근거/출처, 다음 행동으로 이어지는 CTA",
    ),
    "threads": PlatformStrategy(
        "threads", "의견 + 반전 + 논쟁", "engagement",
        ("psychology.identification", "storytelling.tension", "storytelling.insight", "psychology.curiosity"),
        "짧은 단언, 통념을 뒤집는 반전, 답글을 부르는 질문",
    ),
    "shorts": PlatformStrategy(
        "shorts", "강한 hook + 시각적 변화", "attention",
        ("storytelling.hook", "design.visual_hook", "psychology.attention", "design.visual_clarity"),
        "첫 1~2초 안의 hook, 장면 전환, 한 가지 메시지",
    ),
    "youtube": PlatformStrategy(
        "youtube", "스토리 + 신뢰 + 깊이", "conversion",
        ("storytelling.transformation", "psychology.trust", "sales.proof", "design.thumbnail_concept"),
        "문제-긴장-통찰-변화의 서사, 출처와 사례, 썸네일/제목 콘셉트",
    ),
}
assert set(STRATEGIES) == set(PLATFORMS)


def derive_platform_brief(brief: MarketingBrief, platform: str) -> MarketingBrief:
    """공통 브리프에서 플랫폼용 브리프를 만든다. 내용은 복사하지 않고 distribution만 채운다.

    다른 요소(psychology 등)는 그대로 승계하되 status는 draft/검토 필요로 초기화한다.
    이미 사람이 distribution_angle을 적어 두었다면 덮어쓰지 않는다.
    """
    if platform not in STRATEGIES:
        raise MarketingError(f"알 수 없는 platform: {platform!r}")
    strategy = STRATEGIES[platform]
    others = [p for p in PLATFORMS if p != platform]
    distribution = replace(
        brief.distribution,
        target_platform=platform,
        distribution_angle=brief.distribution.distribution_angle if brief.platform == platform and brief.distribution.distribution_angle
        else strategy.angle,
        repurpose_targets=", ".join(others),
    )
    return replace(
        brief, brief_id=compute_brief_id(brief.topic, platform, brief.idea_id), platform=platform,
        distribution=distribution, status="draft", requires_human_review=True, content_ids=(),
    )


def derive_all_platform_briefs(brief: MarketingBrief) -> dict[str, MarketingBrief]:
    return {platform: derive_platform_brief(brief, platform) for platform in PLATFORMS}
