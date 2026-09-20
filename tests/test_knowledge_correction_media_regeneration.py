"""6-05 회귀 테스트: knowledge-scout-b28b782b2a33의 article_type 정정과
그 뒤에 이어지는 MEDIA 재생성이 안전한지 확인한다.

docs/6-05_knowledge_correction_and_media_regeneration.md 참고. 6-04에서 이미
tests/test_scout_knowledge_bridge.py(SCOUT source category가 article_type을
결정하지 않음)와 tests/test_scout_pipeline_e2e.py(합성 fixture로 finance
템플릿 미적용을 검증)를 추가했으므로, 이 파일은 그 둘이 다루지 않는
"실제 production KNOWLEDGE 레코드 정정" + "기존 archive 재실행 시 데이터 보존"
범위만 다루고 중복 테스트는 만들지 않는다.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from content_engine.blog_publish_pack import is_review_required
from content_engine.generator import generate_content_bundle
from content_engine.media_archive import MediaArchiveRecord, archive_report, load_archive
from content_engine.pipeline import run_media_batch
from content_engine.publish_history import compute_content_id
from tak_brain import load_knowledge_records

KNOWLEDGE_PATH = Path(__file__).parents[1] / "data" / "tak_brain_knowledge.json"
TARGET_KNOWLEDGE_ID = "knowledge-scout-b28b782b2a33"

_FINANCE_TEMPLATE_MARKERS = (
    "재무 판단에서 함께 볼 기준",
    "재무 판단의 출발점",
    "금융기관의 공식 심사 기준",
    "심사 기준",
)


def _load_target():
    records = load_knowledge_records(KNOWLEDGE_PATH)
    return next(r for r in records if r.id == TARGET_KNOWLEDGE_ID)


class CorrectedProductionKnowledgeTests(unittest.TestCase):
    """정정된 실제 production KNOWLEDGE 레코드(합성 fixture가 아님) 자체를 검증한다."""

    def setUp(self) -> None:
        self.knowledge = _load_target()

    def test_article_type_was_corrected_to_none(self):
        self.assertIsNone(self.knowledge.article_type)

    def test_corrected_knowledge_produces_no_finance_template_leakage(self):
        bundle = generate_content_bundle(self.knowledge)
        all_text = bundle.blog.title + " " + bundle.blog.body
        for short in bundle.shorts:
            all_text += " " + short.title + " " + short.body
        for thread in bundle.threads:
            all_text += " " + thread.title + " " + thread.body

        for marker in _FINANCE_TEMPLATE_MARKERS:
            self.assertNotIn(marker, all_text)

    def test_corrected_knowledge_keeps_source_facts_and_opinion(self):
        bundle = generate_content_bundle(self.knowledge)
        all_text = bundle.blog.title + " " + bundle.blog.body
        for short in bundle.shorts:
            all_text += " " + short.title + " " + short.body
        for thread in bundle.threads:
            all_text += " " + thread.title + " " + thread.body

        self.assertIn("신기술은 두려워 말고 부딪혀서 느껴봐야 한다", all_text)
        self.assertIn(
            "The call comes amid growing concerns that AI models may become able to "
            "inflict serious damage worldwide",
            all_text,
        )

    def test_corrected_knowledge_still_requires_human_review(self):
        """article_type을 null로 정정해도 category/domain="금융" 안전장치가
        살아있으므로 is_review_required()는 계속 True를 반환해야 한다
        (6-05 보고서 4장: article_type 정정이 finance 안전장치를 약화하지 않음)."""
        self.assertEqual(self.knowledge.category, "금융")
        self.assertTrue(is_review_required(self.knowledge))


class RegenerationPreservesExistingArchiveTests(unittest.TestCase):
    """같은 knowledge_id를 article_type 정정 후 재실행해도 기존 archive 레코드가
    사라지거나 조용히 덮어써지지 않아야 한다(6-05 보고서 5/7장)."""

    def setUp(self) -> None:
        self.knowledge = _load_target()
        finance_knowledge = replace(self.knowledge, article_type="finance")
        self.old_report = run_media_batch([finance_knowledge])

        tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        tmp.close()
        self.archive_path = Path(tmp.name)
        self.addCleanup(self.archive_path.unlink, missing_ok=True)

        archive_report(self.old_report, self.archive_path)
        self.old_content_ids = {record.content_id for record in load_archive(self.archive_path)}

    def test_old_finance_profile_ids_survive_regeneration_under_corrected_type(self):
        new_report = run_media_batch([self.knowledge])
        archive_report(new_report, self.archive_path)

        archived = load_archive(self.archive_path)
        archived_ids = {record.content_id for record in archived}

        # 정정 전 9건 중 일부는 article_type과 무관한 템플릿 문구를 써서
        # content_id가 동일하게 재계산된다(예: threads 5건). 그 항목들은 upsert로
        # "덮어써지는" 것이 아니라 여전히 존재해야 하고(사라지지 않음), 나머지는
        # 새 content_id로 추가되어야 한다.
        self.assertTrue(self.old_content_ids.issubset(archived_ids))
        self.assertGreater(len(archived_ids), len(self.old_content_ids))

    def test_regenerated_items_default_to_unreviewed(self):
        new_report = run_media_batch([self.knowledge])
        archived = archive_report(new_report, self.archive_path)
        for record in archived:
            self.assertEqual(record.review_status, "unreviewed")


class ContentIdReflectsArticleTypeCorrectionTests(unittest.TestCase):
    """blog draft의 content_id가 article_type 정정 전/후로 달라지는지 확인한다
    (동일 KNOWLEDGE에 대한 서로 다른 generation을 구분하는 근거, 6-05 보고서 8장)."""

    def test_blog_content_id_differs_between_finance_and_corrected_profile(self):
        knowledge = _load_target()
        finance_knowledge = replace(knowledge, article_type="finance")

        finance_bundle = generate_content_bundle(finance_knowledge)
        corrected_bundle = generate_content_bundle(knowledge)

        def blog_content_id(bundle, source_knowledge):
            return compute_content_id(
                {
                    "knowledge_id": source_knowledge.id,
                    "platform": "blog",
                    "source_url": bundle.blog.source_url,
                    "evidence_unit_ids": list(bundle.blog.evidence_unit_ids),
                    "original_title": bundle.blog.title,
                    "original_body": bundle.blog.body,
                }
            )

        finance_id = blog_content_id(finance_bundle, finance_knowledge)
        corrected_id = blog_content_id(corrected_bundle, knowledge)

        self.assertNotEqual(finance_id, corrected_id)
        self.assertNotEqual(finance_bundle.blog.title, corrected_bundle.blog.title)


if __name__ == "__main__":
    unittest.main()
