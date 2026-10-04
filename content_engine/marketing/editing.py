"""브리프 요소의 사람 편집. 순수 함수.

규칙: rejected 브리프는 편집할 수 없고, approved 브리프를 편집하면 내용이 달라졌으므로 draft로 되돌아간다
(승인은 현재 내용에 대한 것이어야 한다).
"""

from __future__ import annotations

from dataclasses import replace

from .models import STATUS_APPROVED, STATUS_DRAFT, STATUS_REJECTED, MarketingBrief, MarketingError
from .suggestions import split_key


def set_element(brief: MarketingBrief, key: str, value: str) -> MarketingBrief:
    if brief.status == STATUS_REJECTED:
        raise MarketingError("rejected 브리프는 편집할 수 없습니다.")
    value = (value or "").strip()
    dimension, element = split_key(key)
    status = STATUS_DRAFT if brief.status == STATUS_APPROVED else brief.status
    if dimension == "brief":
        return replace(brief, status=status, **{element: value})
    updated = replace(brief.dimension(dimension), **{element: value})
    return replace(brief, status=status, **{dimension: updated})
