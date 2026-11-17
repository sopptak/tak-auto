import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from tak_scout.perplexity_research import ResearchResult
from tak_scout.trend_discovery import build_trend_query, parse_trend_result


class TrendDiscoveryTests(unittest.TestCase):
    def _answer(self):
        rows = []
        for index in range(1, 7):
            rows.append({
                "rank": index,
                "keyword": f"트렌드 키워드 {index}",
                "category": "AI·테크" if index % 2 else "생활",
                "summary": "최근 공개된 발표와 자료에서 확인된 변화에 관한 설명입니다.",
                "why_now": "최근 7일 안에 공식 발표가 공개되어 관심이 모이고 있습니다.",
                "audience_question": "이 변화가 내 생활에 어떤 영향을 줄까요?",
                "content_angle": "초보자 관점에서 실제 영향과 확인 방법을 비교합니다.",
                "blog_title": f"트렌드 키워드 {index} 변화와 실제 영향 정리",
                "shorts_hook": "이 변화, 그냥 지나치면 놓칠 수 있습니다.",
                "key_points": [
                    "공식 발표에서 확인된 첫 번째 주요 내용입니다.",
                    "관련 자료에서 확인된 두 번째 주요 내용입니다.",
                    "이용자가 확인해야 할 실제 영향과 조건입니다.",
                ],
                "source_urls": ["https://example.com/source"],
            })
        import json
        return json.dumps({"trends": rows}, ensure_ascii=False)

    def test_query_requests_broad_recent_korean_trends_and_json(self):
        query = build_trend_query(datetime(2026, 11, 17, 9, 0, tzinfo=ZoneInfo("Asia/Seoul")))
        self.assertIn("최근 7일", query)
        self.assertIn("AI·테크", query)
        self.assertIn("여행·레저", query)
        self.assertIn('"trends"', query)

    def test_parse_preserves_only_cited_urls_and_limits_to_twenty(self):
        answer = self._answer()
        result = ResearchResult("query", answer, ("https://example.com/source",), "sonar-pro")
        parsed = parse_trend_result(result, researched_at="2026-11-17T09:00:00+09:00")
        self.assertEqual(len(parsed.trends), 6)
        self.assertEqual(parsed.trends[0].rank, 1)
        self.assertEqual(parsed.trends[0].source_urls, ("https://example.com/source",))
        self.assertEqual(parsed.trends[0].key_points[0], "공식 발표에서 확인된 첫 번째 주요 내용입니다.")

    def test_rejects_insufficient_or_uncited_payload(self):
        import json
        payload = {"trends": [{"keyword": "one"}]}
        result = ResearchResult("query", json.dumps(payload), (), "sonar-pro")
        with self.assertRaises(ValueError):
            parse_trend_result(result)

    def test_duplicate_keywords_are_removed(self):
        import json
        rows = []
        base = {
            "keyword": "중복 키워드", "category": "기타",
            "summary": "최근 발표와 자료에서 확인된 구체적인 변화입니다.",
            "why_now": "최근 7일 안에 새로운 발표가 나왔습니다.",
            "audience_question": "무엇이 달라졌나요?",
            "content_angle": "실제 이용자 관점에서 설명합니다.",
            "blog_title": "중복 키워드 정리", "shorts_hook": "이 변화가 시작됐습니다.",
            "key_points": ["첫 번째 확인된 핵심 사실에 대한 설명입니다.", "두 번째 확인된 핵심 사실에 대한 설명입니다.", "세 번째 확인된 핵심 사실에 대한 설명입니다."],
            "source_urls": ["https://example.com/source"],
        }
        rows = [dict(base) for _ in range(6)]
        result = ResearchResult("query", json.dumps({"trends": rows}, ensure_ascii=False), ("https://example.com/source",), "sonar-pro")
        with self.assertRaises(ValueError):
            parse_trend_result(result)


if __
