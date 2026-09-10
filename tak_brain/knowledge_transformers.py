"""글 유형별 근거 기반 KNOWLEDGE 변환기."""

from __future__ import annotations

from abc import ABC, abstractmethod
import re

from blog_importer.models import utc_now

from .article_types import ArticleClassification
from .models import KnowledgeRecord, RawContent


class KnowledgeTransformer(ABC):
    @abstractmethod
    def transform(self, raw: RawContent, classification: ArticleClassification) -> KnowledgeRecord:
        raise NotImplementedError


class BaseKnowledgeTransformer(KnowledgeTransformer):
    def _record(self, raw: RawContent, classification: ArticleClassification, **values: object) -> KnowledgeRecord:
        return KnowledgeRecord(
            id=f"knowledge-{raw.content_hash[:12]}",
            source_raw_id=raw.id,
            source_url=raw.source_url,
            title=raw.title,
            article_type=classification.article_type,
            domain=values.pop("domain", None),
            knowledge_type=values.pop("knowledge_type", None),
            evidence=tuple(values.pop("evidence", ())),
            derived_insight=values.pop("derived_insight", None),
            inference_method="rule_based_template",
            confidence=None,
            created_at=utc_now(),
            knowledge_review_status="pending",
            verification_required=True,
            current_validity=values.pop("current_validity", None),
            **values,
        )

    @staticmethod
    def _evidence(raw: RawContent, *items: str) -> tuple[str, ...]:
        return (f"제목: {raw.title}",) + tuple(item for item in items if item)


class ExperienceKnowledgeTransformer(BaseKnowledgeTransformer):
    _TESTER_PATTERN = re.compile(r"테스터\s*(\d+)명")

    def transform(self, raw: RawContent, classification: ArticleClassification) -> KnowledgeRecord:
        body = raw.body
        tester_match = self._TESTER_PATTERN.search(body)
        evidence = list(self._evidence(raw))
        if "ChatGPT" in body and "클로드코드" in body:
            evidence.append("본문에서 ChatGPT의 기획 정리와 클로드코드의 결과물 생성을 확인했다.")
        if "문제가 생기면" in body and "테스트" in body:
            evidence.append("본문에서 문제 발생 후 질문·수정·테스트를 반복한 내용을 확인했다.")
        if "비공개 테스트" in body:
            tester = f"테스터 {tester_match.group(1)}명 참여와 " if tester_match else ""
            evidence.append(f"본문에서 {tester}비공개 테스트를 확인했다.")
        app_experience = "앱" in body and ("개발" in body or "코딩" in body)
        return self._record(
            raw,
            classification,
            domain="자기계발" if app_experience else None,
            knowledge_type="경험",
            experience="개발자가 아니고 코딩을 몰랐던 작성자가 AI 도구로 앱 제작을 진행한 경험이다." if app_experience else None,
            problem="코딩을 모르는 상태에서 앱을 직접 구현하고 문제를 수정해야 했다." if app_experience else None,
            action="AI로 기획과 명령어를 정리하고 결과물을 만든 뒤 질문·수정·테스트를 반복했다." if app_experience else None,
            decision="개발자에게만 맡기지 않고 AI와 대화하며 직접 앱 제작에 도전했다." if "도전" in body else None,
            result=(f"첫 앱을 비공개 테스트했고 테스터 {tester_match.group(1)}명이 참여했다." if tester_match else None),
            lesson="코딩을 몰라도 만들면서 배우고 문제가 생기면 수정할 수 있다는 교훈이다." if "만들면서 배우" in body else None,
            reusable_principle="AI로 첫 결과물을 만든 뒤 문제마다 수정·테스트하며 실제 사용자 검증까지 진행한다." if app_experience and "테스트" in body else None,
            evidence=tuple(evidence),
            derived_insight="앱을 만들며 문제마다 수정·테스트를 반복하면 결과물을 검증할 수 있다는 정리다." if app_experience and "테스트" in body else None,
        )


class FinanceKnowledgeTransformer(BaseKnowledgeTransformer):
    _ITEMS = ("매출", "영업이익", "당기순이익", "매출 증가 추이", "이익률")

    def transform(self, raw: RawContent, classification: ArticleClassification) -> KnowledgeRecord:
        found = tuple(item for item in self._ITEMS if item in raw.body)
        evidence = self._evidence(raw, f"본문에서 다음 재무 항목을 확인했다: {', '.join(found)}." if found else "")
        return self._record(
            raw,
            classification,
            domain="금융",
            knowledge_type="판단기준",
            problem="대출 판단에서 매출만으로 충분한지 질문하는 글이다." if "대출" in raw.title else None,
            lesson="원문은 매출뿐 아니라 함께 확인할 재무 항목을 제시한다." if found else None,
            reusable_principle="금융 판단에서는 원문에 제시된 여러 재무 지표를 함께 확인한다." if found else None,
            evidence=evidence,
            current_validity="확인 필요",
        )


class WorkplaceKnowledgeTransformer(BaseKnowledgeTransformer):
    def transform(self, raw: RawContent, classification: ArticleClassification) -> KnowledgeRecord:
        body = raw.body
        evidence_items = []
        if "23년차" in body or "23년차" in raw.title:
            evidence_items.append("본문에서 23년차 직장생활을 바탕으로 한 관찰임을 확인했다.")
        for term in ("약속", "신뢰", "거절", "말"):
            if term in body:
                evidence_items.append(f"본문에서 '{term}'과 직장 내 관계를 다룬 내용을 확인했다.")
        lesson = None
        principle = None
        if "약속" in body and "신뢰" in body:
            lesson = "작은 약속을 지키는 행동과 직장 내 신뢰의 관계를 설명한다."
            principle = "직장 내 신뢰를 판단할 때 큰 성과뿐 아니라 약속을 지키는 행동을 함께 본다."
        elif "거절" in body and "신뢰" in body:
            lesson = "업무상 거절 방식과 직장 내 신뢰의 관계를 설명한다."
            principle = "거절이 필요한 상황에서는 관계와 업무 맥락을 함께 고려한다."
        return self._record(
            raw,
            classification,
            domain="직장·인간관계",
            knowledge_type="판단기준",
            experience="작성자가 23년 직장생활을 바탕으로 관찰을 제시했다." if "23년차" in body else None,
            lesson=lesson,
            reusable_principle=principle,
            evidence=self._evidence(raw, *evidence_items),
        )


class AIBusinessKnowledgeTransformer(BaseKnowledgeTransformer):
    def transform(self, raw: RawContent, classification: ArticleClassification) -> KnowledgeRecord:
        body = raw.body
        has_result = bool(re.search(r"수익|벌었|입금|만원을 벌", body)) and "기다린다" not in raw.title
        return self._record(
            raw,
            classification,
            domain="자기계발·AI",
            knowledge_type="경험",
            experience="작성자가 AI를 이용해 수익을 시도한 경험이다." if "AI" in body else None,
            action="AI를 이용한 프로젝트 HARU를 시작했다." if "HARU" in body else None,
            result="수익 결과가 원문에 확인된다." if has_result else None,
            evidence=self._evidence(raw, "본문에서 AI 수익 시도와 HARU 프로젝트를 확인했다." if "AI" in body and "HARU" in body else ""),
            derived_insight="AI를 활용한 수익 시도는 실제 결과와 기대를 구분해 기록해야 한다." if "AI" in body else None,
        )


class BookPhilosophyKnowledgeTransformer(BaseKnowledgeTransformer):
    def transform(self, raw: RawContent, classification: ArticleClassification) -> KnowledgeRecord:
        book = next((name for name in ("장자", "손자병법") if name in raw.body or name in raw.title), None)
        evidence = self._evidence(raw, f"본문에서 {book}의 핵심 메시지와 해석을 확인했다." if book else "")
        return self._record(
            raw,
            classification,
            domain="독서·철학",
            knowledge_type="정보" if book else None,
            experience=None,
            lesson="책의 주장을 작성자의 해석과 함께 정리한 글이다." if book else None,
            reusable_principle="책에서 제시한 판단기준을 다른 상황에 적용하려면 원문 맥락을 함께 확인한다." if book else None,
            evidence=evidence,
        )


class GeneralKnowledgeTransformer(BaseKnowledgeTransformer):
    def transform(self, raw: RawContent, classification: ArticleClassification) -> KnowledgeRecord:
        return self._record(raw, classification, evidence=self._evidence(raw))


TRANSFORMERS = {
    "experience": ExperienceKnowledgeTransformer,
    "finance": FinanceKnowledgeTransformer,
    "workplace": WorkplaceKnowledgeTransformer,
    "ai_business": AIBusinessKnowledgeTransformer,
    "book_philosophy": BookPhilosophyKnowledgeTransformer,
    "general": GeneralKnowledgeTransformer,
}