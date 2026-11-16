"""Deterministic research quality checks; no network calls."""
import unittest

from tak_scout.research import ResearchRecord
from tak_scout.research_quality import assess_research_quality


def make_record(**changes):
    values = dict(
        scout_id="scout-quality", candidate_title="품질 점검", 
        candidate_url="https://news.example/item", source_name="News",
        candidate_published_at="2026-11-15", researched_at="2026-11-16T10:00:00Z",
        query="조사", answer="조사 응답", 
        citations=("https://a.example/1", "https://b.example/2", "https://a.example/3"),
        model="sonar-pro", status="completed", error="",
    )
    values.update(changes)
    return ResearchRecord(**values)


class ResearchQualityTests(unittest.TestCase):
    def test_complete_provenance_is_completeness_good_not_fact_verified(self):
        result = assess_research_quality(make_record())
        self.assertEqual(result.level, "completeness_good")
        self.assertEqual(result.score, 100)
        self.assertFalse(result.requires_human_review)

    def test_missing_citations_requires_human_review(self):
        result = assess_research_quality(make_record(citations=()))
        self.assertEqual(result.level, "review_required")
        self.assertTrue(any("인용 URL" in warning for warning in result.warnings))

    def test_one_domain_is_not_cross_source_confirmation(self):
        result = assess_research_quality(make_record(
            citations=("https://a.example/1", "https://a.example/2", "https://a.example/3")
        ))
        self.assertTrue(any("교차 확인" in warning for warning in result.warnings))

    def test_invalid_citation_urls_are_not_counted(self):
        result = assess_research_quality(make_record(
            citations=("javascript:alert(1)", "not-a-url")
        ))
        self.assertEqual(result.citation_count, 0)
        self.assertEqual(result.unique_hosts, 0)

    def test_missing_publication_date_is_flagged(self):
        result = assess_research_quality(make_record(candidate_published_at=""))
        self.assertTrue(any("발행일" in warning for warning in result.warnings))


if __name__ == "__main__":
    unittest.main()
