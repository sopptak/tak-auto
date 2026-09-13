"""안전한 콘텐츠 초안을 검증 가능한 AI 재작성 인터페이스로 연결한다."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import re

from tak_brain.models import KnowledgeRecord

from .models import ContentDraft


_NUMBER_PATTERN = re.compile(r"\d+(?:[.,]\d+)?")
_TOKEN_PATTERN = re.compile(r"[A-Za-z가-힣]{2,}")
_SENTENCE_PATTERN = re.compile(r"[^.!?\n]+")
_ENTITY_PATTERN = re.compile(r"[A-Za-z가-힣]{2,}(?:은행|증권|보험|카드|법률|법|규정|령|고시|님|씨|앱|서비스|상품|프로젝트)")
_FINANCE_BOUNDARY_PATTERN = re.compile(r"금융기관의\s+공식\s+심사\s+기준으로\s+해석하지\s+않(?:습니다|는다|으며|고|아)")
_THIRD_PERSON_SUMMARY_PATTERNS = (
    re.compile(r"(?:작성자|저자|글쓴이)(?:는|의|가|도)"),
    re.compile(r"원문(?:은|에서는|의|에 따르면)"),
    re.compile(r"이 글은\s+.*(?:다룹니다|설명합니다|전합니다|소개합니다)"),
    re.compile(r"경험을\s+(?:남겼습니다|공유합니다|전달합니다)"),
)
_SAFE_REWRITE_WORDS = frozenset(
    {
        "이", "글", "콘텐츠", "초안", "핵심", "내용", "설명", "정리", "관점",
        "독자", "문장", "제목", "훅", "원문", "작성자", "따라서", "그리고",
    }
)
_FACT_RISK_TERMS = frozenset(
    {
        "경험", "성과", "수익", "매출", "고객", "출시", "수상", "계약", "투자",
        "창업", "근무", "기관", "은행", "상품", "서비스", "프로젝트", "법률",
        "규정", "조례", "시행령", "법적", "기준",
    }
)


@dataclass(frozen=True)
class RewriteRequest:
    """외부 AI provider가 받게 될 재작성 입력 계약."""

    knowledge: KnowledgeRecord
    draft: ContentDraft
    source_url: str
    evidence: tuple[str, ...]
    article_type: str | None
    knowledge_type: str | None


@dataclass(frozen=True)
class RewriteValidation:
    status: str
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class RewriteResult:
    """원본 보존과 재작성 검증 결과를 함께 반환한다."""

    original_draft: ContentDraft
    rewritten_draft: ContentDraft
    rewrite_status: str
    validation_status: str
    validation_errors: tuple[str, ...] = ()


class RewriteProvider(ABC):
    """향후 외부 AI provider가 구현할 네트워크 경계."""

    @abstractmethod
    def rewrite(self, request: RewriteRequest) -> ContentDraft:
        raise NotImplementedError


@dataclass(frozen=True)
class MockRewriteProvider(RewriteProvider):
    """테스트용 provider. 네트워크 호출 없이 지정한 초안을 돌려준다."""

    rewritten_draft: ContentDraft | None = None

    def rewrite(self, request: RewriteRequest) -> ContentDraft:
        return self.rewritten_draft or request.draft


class RewriteValidator:
    """재작성 초안이 승인 KNOWLEDGE와 원본 Draft의 안전 경계를 지키는지 검사한다."""

    def validate(
        self,
        request: RewriteRequest,
        rewritten_draft: ContentDraft,
    ) -> RewriteValidation:
        errors = []
        if type(rewritten_draft) is not type(request.draft):
            errors.append("재작성 초안의 콘텐츠 유형이 원본과 다릅니다.")
        if rewritten_draft.source_url != request.source_url:
            errors.append("source_url이 원본 Draft와 다릅니다.")
        if rewritten_draft.evidence != request.evidence:
            errors.append("evidence가 원본 Draft와 다릅니다.")
        if rewritten_draft.evidence_unit_ids != request.draft.evidence_unit_ids:
            errors.append("근거 단위 추적 정보가 원본 Draft와 다릅니다.")

        source_text = self._source_text(request)
        errors.extend(self._new_number_errors(source_text, rewritten_draft, request.source_url))
        errors.extend(self._fact_scope_errors(source_text, rewritten_draft))
        errors.extend(self._finance_errors(request, rewritten_draft))
        errors.extend(self._style_errors(request, rewritten_draft))
        return RewriteValidation("valid" if not errors else "invalid", tuple(errors))

    @staticmethod
    def _source_text(request: RewriteRequest) -> str:
        knowledge_text = " ".join(
            value
            for value in (
                request.knowledge.title,
                request.knowledge.experience,
                request.knowledge.problem,
                request.knowledge.action,
                request.knowledge.result,
                request.knowledge.lesson,
                request.knowledge.reusable_principle,
                request.knowledge.derived_insight,
            )
            if value
        )
        return " ".join((request.draft.title, request.draft.body, knowledge_text, *request.evidence))

    @staticmethod
    def _new_number_errors(
        source_text: str,
        rewritten_draft: ContentDraft,
        source_url: str = "",
    ) -> tuple[str, ...]:
        allowed_numbers = set(_NUMBER_PATTERN.findall(source_text))
        url_numbers = set(_NUMBER_PATTERN.findall(source_url)) if source_url else set()
        rewritten_numbers = set(_NUMBER_PATTERN.findall(f"{rewritten_draft.title} {rewritten_draft.body}"))
        new_numbers = sorted(rewritten_numbers - allowed_numbers - url_numbers)
        return tuple(f"원문 근거에 없는 숫자가 추가되었습니다: {number}" for number in new_numbers)

    @staticmethod
    def _fact_scope_errors(source_text: str, rewritten_draft: ContentDraft) -> tuple[str, ...]:
        rewritten_text = f"{rewritten_draft.title} {rewritten_draft.body}"
        errors = []
        new_entities = sorted(
            entity
            for entity in set(_ENTITY_PATTERN.findall(rewritten_text))
            if entity not in source_text
        )
        if new_entities:
            errors.append(f"원문 근거에 없는 사람·기관·상품명이 추가되었습니다: {', '.join(new_entities)}")

        new_risk_terms = sorted(
            term
            for term in _FACT_RISK_TERMS
            if term in rewritten_text and term not in source_text
        )
        if new_risk_terms:
            errors.append(f"사실 범위를 넓히는 표현이 추가되었습니다: {', '.join(new_risk_terms)}")

        return tuple(errors)

    @staticmethod
    def _finance_errors(request: RewriteRequest, rewritten_draft: ContentDraft) -> tuple[str, ...]:
        if request.article_type != "finance":
            return ()
        rewritten_text = f"{rewritten_draft.title} {rewritten_draft.body}"
        if _FINANCE_BOUNDARY_PATTERN.search(request.draft.body) and not _FINANCE_BOUNDARY_PATTERN.search(rewritten_text):
            return ("금융 콘텐츠의 공식 기준 비해석 경계가 유지되지 않았습니다.",)
        official_claim = any(
            "공식 심사 기준" in sentence and not _FINANCE_BOUNDARY_PATTERN.search(sentence)
            for sentence in _SENTENCE_PATTERN.findall(rewritten_text)
        )
        if official_claim:
            return ("금융기관의 공식 심사 기준으로 오해될 표현이 추가되었습니다.",)
        return ()

    @staticmethod
    def _style_errors(request: RewriteRequest, rewritten_draft: ContentDraft) -> tuple[str, ...]:
        is_experience = request.knowledge_type == "경험" or request.article_type in {"experience", "ai_business"}
        if not is_experience:
            return ()
        rewritten_text = f"{rewritten_draft.title} {rewritten_draft.body}"
        for pattern in _THIRD_PERSON_SUMMARY_PATTERNS:
            if match := pattern.search(rewritten_text):
                # 원본 draft 본문 자체에 이미 포함되어 있던 템플릿 인용구 제외하고, 새로 작성된 텍스트에서 검출된 경우만 체크
                if match.group() not in request.draft.body and match.group() not in request.draft.title:
                    return (f"경험형 콘텐츠 스타일 위반: 3인칭 요약체 또는 메타 표현이 포함되었습니다 ({match.group().strip()}).",)
        return ()


class RewriteService:
    """승인 KNOWLEDGE의 안전한 Draft만 provider에 전달하고 결과를 검증한다."""

    def __init__(self, provider: RewriteProvider, validator: RewriteValidator | None = None) -> None:
        self.provider = provider
        self.validator = validator or RewriteValidator()

    def rewrite(self, knowledge: KnowledgeRecord, draft: ContentDraft) -> RewriteResult:
        if knowledge.knowledge_review_status != "approved":
            raise ValueError("승인된 KNOWLEDGE만 재작성할 수 있습니다.")
        request = RewriteRequest(
            knowledge=knowledge,
            draft=draft,
            source_url=draft.source_url,
            evidence=draft.evidence,
            article_type=knowledge.article_type,
            knowledge_type=knowledge.knowledge_type,
        )
        rewritten_draft = self.provider.rewrite(request)
        validation = self.validator.validate(request, rewritten_draft)
        return RewriteResult(
            original_draft=draft,
            rewritten_draft=rewritten_draft,
            rewrite_status="rewritten" if validation.status == "valid" else "rejected",
            validation_status=validation.status,
            validation_errors=validation.errors,
        )
