"""TAK SCOUT -> TAK INTERVIEW -> TAK BRAIN -> TAK MEDIA 전체 흐름 1건 검증.

실제 RSS 네트워크나 실제 LLM/Threads API는 호출하지 않는다. RSS 응답은 fetch_rss를
patch해 대체하고, TAK MEDIA 재작성은 기존 MockRewriteProvider를 사용한다. 이 테스트는
Threads 실제 게시를 수행하지 않는다(run_media_batch까지만 검증).
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from content_engine.generator import generate_content_bundle
from content_engine.pipeline import run_media_batch
from content_engine.rewrite import MockRewriteProvider
from tak_brain.knowledge import load_knowledge_records, select_approved, set_review_status
from tak_scout.answers import InterviewAnswer
from tak_scout.collector import build_daily_pack, save_daily_pack_json
from tak_scout.interview import build_interview_question
from tak_scout.knowledge_bridge import append_scout_knowledge, build_knowledge_from_interview
from tak_scout.models import ScoutCandidate


FEED_XML = """<rss version="2.0"><channel>
<item>
  <title>중앙은행, 기준금리 동결 발표</title>
  <link>https://example.test/news/rate-hold</link>
  <description>중앙은행이 이번 회의에서 기준금리를 동결하기로 결정했다.</description>
  <pubDate>Thu, 10 Sep 2026 09:00:00 +0900</pubDate>
</item>
</channel></rss>"""

# 6-04: 실제 production에서 재현된 문제(knowledge-scout-b28b782b2a33,
# docs/6-04_media_generation_quality_investigation.md)를 그대로 반영한 fixture다 -
# data/scout_sources.json의 "BBC Business" 소스는 category="finance"로 등록되어
# 있지만, 실제 기사 내용은 AI 개발 속도에 대한 것이라 금융과 무관하다.
_AI_NEWS_FROM_FINANCE_TAGGED_SOURCE = ScoutCandidate(
    scout_id="scout-ai-news-1",
    title="Anthropic boss Dario Amodei calls for AI development to slow down",
    summary=(
        "The call comes amid growing concerns that AI models may become able to "
        "inflict serious damage worldwide."
    ),
    source_url="https://www.bbc.co.uk/news/articles/c14dpgm0rg4o",
    published_at="2026-09-14T00:00:00+00:00",
    source_name="BBC Business",
    category="finance",
)

_FINANCE_TEMPLATE_MARKERS = ("재무 판단", "금융기관", "심사 기준")


class ScoutSourcedFinanceTemplateLeakageTests(unittest.TestCase):
    """6-04 회귀 테스트: category(=RSS 소스의 블랭킷 카테고리)만으로 article_type을
    "finance"로 단정하면, 실제로 금융과 무관한 SCOUT 기사에도
    content_engine/generator.py의 finance 전용 템플릿(제목/공식 기준 비해석
    문구)이 잘못 적용된다. 이 클래스는 knowledge_bridge -> generator 전체 사슬을
    실제로 통과시켜 그 문제가 재발하지 않는지 확인한다."""

    def test_finance_tagged_source_with_ai_content_does_not_get_finance_template(self):
        answer = InterviewAnswer.create(
            _AI_NEWS_FROM_FINANCE_TAGGED_SOURCE.scout_id, "D", "신기술은 두려워 말고 부딪혀서 느껴봐야 한다"
        )
        knowledge = build_knowledge_from_interview(_AI_NEWS_FROM_FINANCE_TAGGED_SOURCE, answer)

        # category/domain은 소스 태그를 그대로 참고 정보로 보존한다(안전 검토 트리거용).
        self.assertEqual(knowledge.domain, "금융")
        # 하지만 article_type은 실제 본문을 분석한 결과가 아니므로 "finance"로 단정하지 않는다.
        self.assertIsNone(knowledge.article_type)

        approved = set_review_status(knowledge, "approved")
        bundle = generate_content_bundle(approved)

        all_text = bundle.blog.title + " " + bundle.blog.body
        for short in bundle.shorts:
            all_text += " " + short.title + " " + short.body
        for thread in bundle.threads:
            all_text += " " + thread.title + " " + thread.body

        for marker in _FINANCE_TEMPLATE_MARKERS:
            self.assertNotIn(
                marker, all_text,
                f"금융과 무관한 SCOUT 콘텐츠에 finance 전용 템플릿 문구({marker!r})가 포함되었습니다.",
            )

    def test_finance_tagged_source_ai_content_keeps_core_facts(self):
        """AI development slowdown이라는 원문 핵심 사실(evidence)이 Blog Draft에
        그대로 유지되는지 확인한다 - finance 템플릿으로 잘못 치환되어 핵심 내용이
        사라지면 안 된다."""
        answer = InterviewAnswer.create(
            _AI_NEWS_FROM_FINANCE_TAGGED_SOURCE.scout_id, "D", "신기술은 두려워 말고 부딪혀서 느껴봐야 한다"
        )
        knowledge = build_knowledge_from_interview(_AI_NEWS_FROM_FINANCE_TAGGED_SOURCE, answer)
        approved = set_review_status(knowledge, "approved")
        bundle = generate_content_bundle(approved)

        self.assertIn("AI models may become able to inflict serious damage worldwide", bundle.blog.body)
        self.assertIn("신기술은 두려워 말고 부딪혀서 느껴봐야 한다", bundle.blog.body)

    def test_workplace_tagged_source_does_not_get_finance_template(self):
        """워크플레이스 성격 소재도 finance 템플릿과 무관해야 한다(회귀 확인,
        구조적으로 원래도 영향이 없었지만 명시적으로 고정한다)."""
        candidate = ScoutCandidate(
            scout_id="scout-workplace-1",
            title="상사에게 신뢰받는 신입사원의 습관",
            summary="직장에서 상사와 동료에게 인정받는 사람들의 공통된 습관을 정리했다.",
            source_url="https://example.test/news/workplace-1",
            published_at="2026-09-14T00:00:00+00:00",
            source_name="테스트 매거진",
            category="workplace",
        )
        answer = InterviewAnswer.create(candidate.scout_id, "A")
        knowledge = build_knowledge_from_interview(candidate, answer)
        self.assertIsNone(knowledge.article_type)

        approved = set_review_status(knowledge, "approved")
        bundle = generate_content_bundle(approved)
        self.assertNotIn(_FINANCE_TEMPLATE_MARKERS[0], bundle.blog.title)
        self.assertNotIn(_FINANCE_TEMPLATE_MARKERS[1], bundle.blog.body)


class ScoutToMediaPipelineTests(unittest.TestCase):
    def test_one_candidate_flows_from_rss_to_media_bundle(self):
        sources = [{"name": "테스트 경제 뉴스", "url": "https://example.test/rss.xml", "category": "finance"}]

        # 1) TAK SCOUT: RSS -> 후보
        with patch("tak_scout.collector.fetch_rss", return_value=FEED_XML):
            candidates, _ = build_daily_pack(sources, max_count=10)
        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]

        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            daily_pack_path = directory / "tak_scout_daily.json"
            save_daily_pack_json(candidates, daily_pack_path)

            # 2) TAK INTERVIEW: 4지선다 질문 생성 + 직접 입력(D)으로 답변
            question = build_interview_question(candidate)
            self.assertIn("직접 입력", question.option_d)

            answer = InterviewAnswer.create(
                candidate.scout_id, "D", "이번 동결은 물가보다 성장을 더 우선한 결정으로 보인다"
            )
            answers_path = directory / "tak_interview_answers.json"
            answers_path.write_text(json.dumps([answer.to_dict()], ensure_ascii=False), encoding="utf-8")

            # 3) TAK BRAIN: 답변 -> KNOWLEDGE(pending)
            knowledge_path = directory / "tak_brain_knowledge.json"
            created, skipped_unanswered, duplicates = append_scout_knowledge(
                daily_pack_path, answers_path, knowledge_path
            )
            self.assertEqual((created, skipped_unanswered, duplicates), (1, 0, 0))

            records = load_knowledge_records(knowledge_path)
            self.assertEqual(len(records), 1)
            pending = records[0]
            self.assertEqual(pending.knowledge_review_status, "pending")

            # pending 상태로는 TAK MEDIA 대상이 아니다.
            self.assertEqual(select_approved(records), ())

            # 사람이 승인(review_knowledge.py --approve와 동일한 동작)
            approved = set_review_status(pending, "approved")

        # 4) TAK MEDIA: 승인 KNOWLEDGE -> Blog/Shorts/Threads Draft
        bundle = generate_content_bundle(approved)
        self.assertEqual(bundle.status, "complete")
        self.assertIsNotNone(bundle.blog)
        self.assertEqual(len(bundle.shorts), 3)
        self.assertEqual(len(bundle.threads), 5)
        for draft in (bundle.blog, *bundle.shorts, *bundle.threads):
            self.assertEqual(draft.source_url, candidate.source_url)

        report = run_media_batch([approved], provider=MockRewriteProvider())
        self.assertEqual(report.approved_knowledge_count, 1)
        self.assertGreater(report.valid_count, 0)
        self.assertEqual(report.error_count, 0)

        # 원문 사실과 티몽의 의견이 evidence에 구분되어 남아 있는지 최종 확인
        evidence_text = " ".join(approved.evidence)
        self.assertIn("SOURCE FACT:", evidence_text)
        self.assertIn("SOURCE URL:", evidence_text)
        self.assertIn("USER ORIGINAL THOUGHT:", evidence_text)


if __name__ == "__main__":
    unittest.main()
