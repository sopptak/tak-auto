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
        evidence = self._evidence(
            raw,
            "매출만으로 대출 가능성을 판단해서는 안 된다는 설명을 확인했다." if "매출만으로" in raw.body else "",
            f"본문에서 다음 재무 항목을 확인했다: {', '.join(found)}." if found else "",
            "기존에 빌린 돈도 함께 본다는 설명을 확인했다." if "기존에 빌린 돈" in raw.body else "",
        )
        return self._record(
            raw,
            classification,
            domain="금융",
            knowledge_type="판단기준",
            problem="매출 규모가 있어도 대출이 기대보다 나오지 않을 수 있는 상황을 제시한다." if "대출" in raw.title else None,
            lesson="원문은 매출뿐 아니라 이익과 기존 부채 등 여러 조건을 함께 살펴야 한다고 설명한다." if found else None,
            reusable_principle="대출 가능성을 매출 하나로 단정하지 말고, 원문에 제시된 재무지표와 기존 부채를 함께 확인한다." if found else None,
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
        experience = None
        problem = None
        action = None
        decision = None
        result = None
        if "거절을 잘하는" in raw.title and "저도" in body:
            lesson = "업무상 거절 방식과 직장 내 신뢰의 관계를 설명한다."
            principle = "거절이 필요한 상황에서는 관계와 업무 맥락을 함께 고려한다."
            experience = "작성자가 부탁을 쉽게 거절하지 못했던 직장생활 경험을 설명한다."
            problem = "부탁을 계속 받아주면 업무를 제때 처리하지 못해 신뢰도가 떨어질 수 있었다."
            action = "부탁을 모두 받아주기보다 업무 상황을 고려해 거절하는 방식을 제시한다."
            decision = "좋은 사람으로 보이기 위해 무조건 수락하기보다 필요한 경우 거절하기로 판단한다."
            result = "적절한 거절이 오히려 직장 내 신뢰로 이어질 수 있다고 설명한다."
        elif "일 잘하는데도" in raw.title or "인정받지 못" in raw.title:
            problem = "일을 잘해도 직장에서 인정받지 못하는 차이가 생기는 상황을 다룬다."
            lesson = "업무 능력만으로 인정이 결정되는 것은 아니며 문제 대응과 협업 태도도 영향을 줄 수 있다."
            principle = "직장에서는 업무 수행 능력과 함께 문제 대응 방식과 협업 태도를 함께 본다."
        elif "신뢰받는 사람들은" in raw.title:
            lesson = "업무 범위를 설명하는 말과 책임을 피하는 말이 신뢰 판단에 영향을 줄 수 있다고 설명한다."
            principle = "업무 경계를 설명할 때 책임 회피로 들리는 표현과 협업 의사를 구분한다."
        elif "무시당하는 사람들이" in raw.title:
            lesson = "모르는 것을 모른다고 말하는 것과 자신을 반복적으로 낮추는 표현은 구분해야 한다고 설명한다."
            principle = "직장 커뮤니케이션에서는 내용뿐 아니라 자신을 표현하는 습관과 그 영향을 함께 점검한다."
        elif "거절" in raw.title and "신뢰" in body:
            lesson = "업무상 거절 방식과 직장 내 신뢰의 관계를 설명한다."
            principle = "거절이 필요한 상황에서는 관계와 업무 맥락을 함께 고려한다."
        elif ("작은 약속" in body or "약속을 지키" in body) and "신뢰" in body:
            lesson = "작은 약속을 지키는 행동과 직장 내 신뢰의 관계를 설명한다."
            principle = "직장 내 신뢰를 판단할 때 큰 성과뿐 아니라 약속을 지키는 행동을 함께 본다."
        return self._record(
            raw,
            classification,
            domain="직장·인간관계",
            knowledge_type="판단기준",
            experience=experience,
            problem=problem,
            action=action,
            decision=decision,
            result=result,
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
            problem="일하지 않는 시간에도 작동하는 수익 구조를 만들고 싶었다." if "일하지 않는 시간" in body else None,
            action="AI를 이용한 프로젝트 HARU를 시작했다." if "HARU" in body else None,
            decision="처음부터 큰 금액이 아니라 첫 목표를 월 1만원으로 설정했다." if "월 1만원" in body else None,
            result="수익 결과가 원문에 확인된다." if has_result else None,
            evidence=self._evidence(raw, "본문에서 AI 수익 시도와 HARU 프로젝트를 확인했다." if "AI" in body and "HARU" in body else ""),
            derived_insight="AI를 활용한 수익 시도는 실제 결과와 기대를 구분해 기록해야 한다." if "AI" in body else None,
        )


class BookPhilosophyKnowledgeTransformer(BaseKnowledgeTransformer):
    def transform(self, raw: RawContent, classification: ArticleClassification) -> KnowledgeRecord:
        book = next((name for name in ("장자", "손자병법") if name in raw.body or name in raw.title), None)
        evidence_items = [f"본문에서 {book}의 핵심 메시지와 해석을 확인했다." if book else ""]
        if book == "장자":
            evidence_items.extend(
                [
                    "비교가 불안과 조급함을 만든다는 해석을 확인했다.",
                    "SNS 사용 시간 줄이기와 감사한 일 기록이라는 실천 제안을 확인했다.",
                ]
            )
        if book == "손자병법":
            evidence_items.extend(
                [
                    "준비 없이 싸우는 것은 무모하다는 설명을 확인했다.",
                    "싸우기 전에 승리를 준비하고 감정으로 싸우지 말라는 원칙을 확인했다.",
                ]
            )
            if "지점장의 현장 인사이트" in raw.body and "대출 심사를 하다 보면" in raw.body:
                evidence_items.append("본문의 별도 인사이트 구간에서 대출 심사와 기업 위험 관리에 관한 작성자의 주장·관찰을 확인했다.")
        return self._record(
            raw,
            classification,
            domain="독서·철학",
            knowledge_type="정보" if book else None,
            experience=None,
            problem=("비교가 불안과 조급함을 만들 수 있다는 문제의식을 제시한다." if book == "장자" else "준비 없이 싸움을 시작하거나 감정으로 판단하는 문제를 다룬다." if book == "손자병법" else None),
            action=("SNS 사용 시간을 줄이고 감사한 일을 기록하는 실천을 제안한다." if book == "장자" else None),
            lesson=("비교에서 벗어나 타인의 시선보다 자신의 삶을 살아가는 방향을 제시한다." if book == "장자" else "손자병법의 핵심 주장을 정리하고, 대출 심사·위험 관리 내용은 작성자의 금융 관련 주장·관찰로 구분한다." if book == "손자병법" else None),
            reusable_principle=("비교로 인한 불안을 줄이기 위해 타인의 시선보다 자신의 삶과 현재 행동을 점검한다." if book == "장자" else "손자병법의 판단 기준과 작성자의 금융 관련 주장·관찰을 구분한 뒤 원문 맥락을 함께 확인한다." if book == "손자병법" else None),
            evidence=self._evidence(raw, *evidence_items),
            derived_insight=("비교를 줄이는 원칙을 SNS 사용과 감사 기록이라는 행동으로 연결한 정리다." if book == "장자" else "손자병법의 준비와 위험 점검 원칙을 일반 의사결정에 적용한 정리다." if book == "손자병법" else None),
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