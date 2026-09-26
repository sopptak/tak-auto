"""안전한 콘텐츠 초안을 검증 가능한 AI 재작성 인터페이스로 연결한다."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import re

from tak_brain.models import KnowledgeRecord

from .models import ContentDraft, ThreadDraft


_NUMBER_PATTERN = re.compile(r"\d+(?:[.,]\d+)?")
_TOKEN_PATTERN = re.compile(r"[A-Za-z가-힣]{2,}")
_SENTENCE_PATTERN = re.compile(r"[^.!?\n]+")
_ENTITY_PATTERN = re.compile(r"[A-Za-z가-힣]{2,}(?:은행|증권|보험|카드|법률|법|규정|령|고시|님|씨|앱|서비스|상품|프로젝트)")
_FINANCE_BOUNDARY_PATTERN = re.compile(
    r"(?:금융기관의|은행의)?\s*(?:공식\s+)?(?:심사\s+)?기준(?:으로|으로의|이라)?\s*(?:해석|확대|확대해석)하지\s*(?:않|말)|"
    r"은행의\s+공식\s+(?:심사\s+)?기준(?:이라|이라고|으로)?\s*단정하는\s*(?:내용|것|말|글)?(?:이|은)?\s*아니"
)
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


def find_finance_boundary_sentence(text: str) -> str | None:
    """금융 안전 경계 문구가 포함된 문장을 text에서 찾아 원문 그대로 반환한다.

    RewriteValidator._finance_errors가 재작성 결과를 검사할 때 쓰는 것과
    완전히 동일한 패턴(_FINANCE_BOUNDARY_PATTERN)을 사용한다 - LLM에게
    "반드시 그대로 보존하라"고 전달하는 문장과, 실제로 검증하는 문장이
    항상 같은 기준(단일 source of truth)을 공유하도록 하기 위함이다
    (5-10 Phase 4-3). 일치하는 문장이 없으면 None을 반환한다.
    """
    for sentence in _SENTENCE_PATTERN.findall(text):
        if _FINANCE_BOUNDARY_PATTERN.search(sentence):
            return sentence.strip()
    return None


_FACT_RISK_TERMS = frozenset(
    {
        "경험", "성과", "수익", "매출", "고객", "출시", "수상", "계약", "투자",
        "창업", "근무", "기관", "은행", "상품", "서비스", "프로젝트", "법률",
        "규정", "조례", "시행령", "법적", "기준",
    }
)

# SOURCE FACT의 영문 월 이름이 재작성 과정에서 한국어 "N월"로 자연스럽게 번역되면
# _new_number_errors가 "원문에 없는 새 숫자"로 오탐한다(예: "by December" ->
# "12월" 에서 12를 새 숫자로 오인 - 5-10 Phase 4-1에서 실제로 재현됨). 이 표를
# source_text에 실제로 등장한 월 이름과 정확히 대응하는 "N월" 표기만 숫자 비교
# 대상에서 제외하는 데 쓴다 - "12"라는 숫자 자체를 광범위하게 허용하지 않는다
# (예: "12억원"처럼 월 표기가 아닌 숫자는 이 예외의 영향을 받지 않는다).
_MONTH_NAME_TO_NUMBER = {
    "January": "1", "February": "2", "March": "3", "April": "4",
    "May": "5", "June": "6", "July": "7", "August": "8",
    "September": "9", "October": "10", "November": "11", "December": "12",
}
_MONTH_NAME_PATTERN = re.compile(r"\b(" + "|".join(_MONTH_NAME_TO_NUMBER) + r")\b")


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
        errors.extend(self._fact_scope_errors(source_text, rewritten_draft, request.article_type))
        errors.extend(self._finance_errors(request, rewritten_draft))
        errors.extend(self._style_errors(request, rewritten_draft))
        errors.extend(self._threads_length_errors(request, rewritten_draft))
        return RewriteValidation("valid" if not errors else "invalid", tuple(errors))

    @staticmethod
    def _source_text(request: RewriteRequest) -> str:
        knowledge_text = " ".join(
            value
            for value in (
                request.knowledge.title,
                request.knowledge.knowledge_type,
                request.knowledge.experience,
                request.knowledge.problem,
                request.knowledge.action,
                request.knowledge.result,
                request.knowledge.lesson,
                request.knowledge.reusable_principle,
                request.knowledge.derived_insight,
                request.knowledge.judgment_rule,
            )
            if value
        )
        return " ".join((request.draft.title, request.draft.body, knowledge_text, *request.evidence))

    @staticmethod
    def _strip_translated_month_references(source_text: str, rewritten_text: str) -> str:
        """source_text에 실제로 등장한 영문 월 이름과 대응하는 "N월" 표기만
        rewritten_text에서 제거해, 날짜의 영→한 표기 변환이 새 숫자로 오탐되지
        않게 한다. 그 외 숫자(예: "12억원", "30%")는 그대로 남아 기존 검증을
        받는다 - "N월" 형태로 정확히 등장할 때만 제외한다.
        """
        months_in_source = set(_MONTH_NAME_PATTERN.findall(source_text))
        if not months_in_source:
            return rewritten_text
        result = rewritten_text
        for month_name in months_in_source:
            number = _MONTH_NAME_TO_NUMBER[month_name]
            result = re.sub(rf"(?<!\d){number}월", "", result)
        return result

    @staticmethod
    def _new_number_errors(
        source_text: str,
        rewritten_draft: ContentDraft,
        source_url: str = "",
    ) -> tuple[str, ...]:
        allowed_numbers = set(_NUMBER_PATTERN.findall(source_text))
        url_numbers = set(_NUMBER_PATTERN.findall(source_url)) if source_url else set()
        rewritten_text = RewriteValidator._strip_translated_month_references(
            source_text, f"{rewritten_draft.title} {rewritten_draft.body}"
        )
        rewritten_numbers = set(_NUMBER_PATTERN.findall(rewritten_text))
        new_numbers = sorted(rewritten_numbers - allowed_numbers - url_numbers)
        return tuple(f"원문 근거에 없는 숫자가 추가되었습니다: {number}" for number in new_numbers)

    @staticmethod
    def _fact_scope_errors(
        source_text: str,
        rewritten_draft: ContentDraft,
        article_type: str | None = None,
    ) -> tuple[str, ...]:
        rewritten_text = f"{rewritten_draft.title} {rewritten_draft.body}"
        errors = []
        new_entities = sorted(
            entity
            for entity in set(_ENTITY_PATTERN.findall(rewritten_text))
            if entity not in source_text
        )
        if new_entities:
            errors.append(f"원문 근거에 없는 사람·기관·상품명이 추가되었습니다: {', '.join(new_entities)}")

        risk_sentences = []
        for sentence in _SENTENCE_PATTERN.findall(rewritten_text):
            if article_type == "finance" and _FINANCE_BOUNDARY_PATTERN.search(sentence):
                continue
            risk_sentences.append(sentence)

        text_to_check = " ".join(risk_sentences)
        new_risk_terms = sorted(
            term
            for term in _FACT_RISK_TERMS
            if term in text_to_check and term not in source_text
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
            ("공식 심사 기준" in sentence or "공식 기준" in sentence or "심사 기준" in sentence)
            and not _FINANCE_BOUNDARY_PATTERN.search(sentence)
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

    @staticmethod
    def _threads_length_errors(request: RewriteRequest, rewritten_draft: ContentDraft) -> tuple[str, ...]:
        is_threads = isinstance(rewritten_draft, ThreadDraft) or isinstance(request.draft, ThreadDraft)
        if not is_threads:
            return ()
        clean_body = rewritten_draft.body.strip()
        if len(clean_body) > 500:
            return (f"Threads text exceeds 500 characters: {len(clean_body)}",)
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
