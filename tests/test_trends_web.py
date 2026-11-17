import unittest
from types import SimpleNamespace

from scripts.trends_web import render_trends_page


class TrendWebTests(unittest.TestCase):
    def test_renders_trend_sections_and_existing_research_links(self):
        report = {
            "generated_on": "2026-11-17",
            "top_keywords": [{"keyword": "생성형 AI", "candidate_count": 4, "source_count": 3}],
            "rising_keywords": [{"keyword": "스마트 안경", "previous_count": 1,
                                 "current_count": 3, "change": 2}],
            "content_opportunities": [{"keyword": "생성형 AI", "score": 70,
                                       "candidate_count": 4, "source_count": 3,
                                       "candidate_ids": ["scout-1"], "reasons": ["복수 출처"]}],
        }
        html = render_trends_page(report, [SimpleNamespace(scout_id="scout-1")])
        self.assertIn("반복 키워드 TOP 20", html)
        self.assertIn("급상승 후보 TOP 10", html)
        self.assertIn("생성형 AI", html)
        self.assertIn("/research/scout-1", html)
        self.assertIn("근거 기사 심층 조사", html)
        self.assertIn('action="/candidate/scout-1/research"', html)
        self.assertIn("전체 검색량이나 SNS 인기도가 아닙니다", html)

    def test_escapes_untrusted_keyword_html(self):
        html = render_trends_page({"top_keywords": [{"keyword": "<script>bad</script>"}]})
        self.assertNotIn("<script>bad</script>", html)
        self.assertIn("&lt;script&gt;", html)


if __name__ == "__main__":
    unittest.main()
