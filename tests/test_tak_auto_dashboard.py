import unittest

from tak_scout.dashboard import render_dashboard, render_dashboard_markdown


class TakAutoDashboardTests(unittest.TestCase):
    def test_dashboard_renders_metrics_sources_and_disclosures(self):
        report = {
            "generated_on": "2026-11-17",
            "top_keywords": [{"keyword": "ai", "candidate_count": 3, "source_count": 2}],
            "rising_keywords": [{"keyword": "스마트 안경", "previous_count": 1,
                                 "current_count": 3, "change": 2}],
            "content_opportunities": [{
                "keyword": "ai", "score": 70, "candidate_count": 3, "source_count": 2,
                "candidate_ids": ["s1"], "reasons": ["복수 출처"],
            }],
            "limitations": ["검색량 미확인"],
            "naver_datalab": {"status": "not_configured"},
        }
        candidates = [{
            "scout_id": "s1", "title": "AI 신제품 공개", "summary": "요약",
            "source_url": "https://example.com/story", "source_name": "Example",
            "published_at": "2026-11-17",
        }]
        html = render_dashboard(report, candidates)
        self.assertIn("TAK AUTO", html)
        self.assertIn("스마트 안경", html)
        self.assertIn("AI 신제품 공개", html)
        self.assertIn("https://example.com/story", html)
        self.assertIn("검색량 미확인", html)
        self.assertIn("not_configured", html)

    def test_markdown_dashboard_contains_clickable_source_and_limits(self):
        report = {
            "generated_on": "2026-11-17",
            "top_keywords": [{"keyword": "ai", "candidate_count": 2, "source_count": 2,
                              "candidate_ids": ["s1"]}],
            "rising_keywords": [],
            "content_opportunities": [{"keyword": "ai", "score": 60,
                                       "candidate_count": 2, "source_count": 2,
                                       "reasons": ["복수 출처"]}],
            "limitations": ["검색량 미확인"],
            "naver_datalab": {"status": "not_configured"},
        }
        candidates = [{"scout_id": "s1", "title": "AI 공개", "source_url": "https://example.com",
                       "source_name": "Example"}]
        markdown = render_dashboard_markdown(report, candidates)
        self.assertIn("[AI 공개](https://example.com)", markdown)
        self.assertIn("검색량 미확인", markdown)
        self.assertIn("콘텐츠 기회 TOP 5", markdown)

    def test_dashboard_escapes_untrusted_html(self):
        report = {"generated_on": "today", "top_keywords": [
            {"keyword": "<script>alert(1)</script>", "candidate_count": 2, "source_count": 1}
        ], "rising_keywords": [], "content_opportunities": [], "limitations": []}
        html = render_dashboard(report, [])
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)


if __name__ == "__main__":
    unittest.main()
