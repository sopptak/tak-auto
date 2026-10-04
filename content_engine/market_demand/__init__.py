"""시장 수요 데이터 -> 기회 점수 -> 사업 아이디어 후보(docs/6-78-market-demand-research.md)."""

from .models import (
    IDEA_ACCEPTED, IDEA_CANDIDATE, IDEA_REJECTED, IDEA_STATUSES, IdeaCandidate, MarketDemand, MarketDemandError,
    OpportunityScore, compute_demand_id,
)
from .provider import (
    KNOWN_SOURCES, ManualMarketDemandProvider, MarketDemandProvider, MockMarketDemandProvider,
    available_market_providers, get_market_demand_provider, load_rows, normalize_row, register_provider,
)
from .scoring import score_demand
from .store import (
    append_demands, append_ideas, build_idea_candidates, load_demands, load_ideas, set_idea_status,
)
