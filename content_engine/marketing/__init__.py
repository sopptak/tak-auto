"""AI Marketing Intelligence Layer (docs/6-79-ai-marketing-intelligence.md)."""

from .briefs import (
    CORE_ELEMENTS, MIN_IDEA_SCORE, approval_blockers, brief_confidence, brief_from_idea, market_evidence, readiness_blockers, with_status,
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
from .editing import set_element
from .generation import (
    CONTENTS_FILE, MEDIA_PLATFORMS, STATUS_REVIEW_REQUIRED, GenerationResult, generate_candidates, generation_blockers,
    media_content_id, media_platform, save_candidates,
)
from .store import (
    append_briefs, append_suggestions, link_content, load_briefs, load_suggestions, resolve_suggestion,
    set_brief_status, update_element,
)
from .suggestions import Suggestion, apply_suggestion, suggest_elements
