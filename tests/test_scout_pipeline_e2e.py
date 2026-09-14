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
from tak_scout.knowledge_bridge import append_scout_knowledge


FEED_XML = """<rss version="2.0"><channel>
<item>
  <title>중앙은행, 기준금리 동결 발표</title>
  <link>https://example.test/news/rate-hold</link>
  <description>중앙은행이 이번 회의에서 기준금리를 동결하기로 결정했다.</description>
  <pubDate>Thu, 10 Sep 2026 09:00:00 +0900</pubDate>
</item>
</channel></rss>"""


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
