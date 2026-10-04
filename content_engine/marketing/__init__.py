"""AI Marketing Intelligence Layer (docs/6-79-ai-marketing-intelligence.md)."""

from .briefs import (
    MIN_IDEA_SCORE, brief_confidence, brief_from_idea, market_evidence, readiness_blockers, with_status,
)
from .insight import (
    MarketingInsight, attribute_lift, collect_marketing_insights, marketing_attributes, split_metrics,
)
from .models import (
    BRIEF_STATUSES, DIMENSIONS, PLATFORMS, Design, Distribution, EvidenceItem, MarketingBrief, MarketingError,
    Psychology, Sales, Storytelling, compute_brief_id,
)
from .platforms import STRATEGIES, PlatformStrategy, derive_all_platform_briefs, derive_platform_brief
from .prompt import THINKING_STEPS, build_content_prompt, render_prompt_text
from .research_tasks import (
    ASPECT_QUERIES, ResearchBundle, build_queries, research_idea, run_research_tasks,
)
from .scoring import MarketingScore, score_brief
from .store import append_briefs, link_content, load_briefs, set_brief_status
