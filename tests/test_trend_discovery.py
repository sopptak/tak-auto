import json
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from tak_scout.perplexity_research import ResearchResult
from tak_scout.trend_discovery import build_trend_query, parse_trend_result
from scripts.run_trend_content_mvp import _make_preview, _parse_content_package


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
        return json.dumps({"trends": rows}, ensure_ascii=False)

    def test_query_requests_broad_recent_korean_trends_and_json(self):
        query = build_trend_query(datetime(2026, 11, 17, 9, 0, tzinfo=ZoneInfo("Asia/Seoul")))
        self.assertIn("최근 7일", query)
        self.assertIn("AI·테크", query)
        self.assertIn("여행·레저", query)
        self.assertIn('"trends"', query)

    def test_parse_preserves_only_cited_urls(self):
        result = ResearchResult("query", self._answer(),
                                ("https://example.com/source",), "sonar-pro")
        parsed = parse_trend_result(result, researched_at="2026-11-17T09:00:00+09:00")
        self.assertEqual(len(parsed.trends), 6)
        self.assertEqual(parsed.trends[0].rank, 1)
        self.assertEqual(parsed.trends[0].source_urls, ("https://example.com/source",))
        self.assertEqual(parsed.trends[0].key_points[0],
                         "공식 발표에서 확인된 첫 번째 주요 내용입니다.")

    def test_rejects_insufficient_payload(self):
        result = ResearchResult("query", json.dumps({"trends": [{"keyword": "one"}]}),
                                (), "sonar-pro")
        with self.assertRaises(ValueError):
            parse_trend_result(result)

    def test_duplicate_keywords_are_removed(self):
        payload = json.loads(self._answer())
        payload["trends"] = [payload["trends"][0]] * 6
        result = ResearchResult("query", json.dumps(payload, ensure_ascii=False),
                                ("https://example.com/source",), "sonar-pro")
        with self.assertRaises(ValueError):
            parse_trend_result(result)

    def test_selected_trend_generates_preview_bundle_without_publishing(self):
        report = {
            "citations": ["https://example.com/source"],
            "trends": [{
                "rank": 1, "keyword": "생성형 AI 활용",
                "category": "AI·테크",
                "summary": "기업과 개인의 생성형 AI 활용 방식이 최근 공개 자료에서 구체화되고 있습니다.",
                "why_now": "최근 7일 동안 주요 서비스의 기능 발표와 이용 사례가 이어졌습니다.",
                "audience_question": "일반 이용자는 어떤 기능부터 써보면 좋을까요?",
                "content_angle": "무료·유료 기능 차이와 실제 활용 시 주의점을 비교합니다.",
                "blog_title": "생성형 AI 활용법과 무료·유료 기능 차이",
                "shorts_hook": "AI를 쓰는데 아직 이 기능을 모른다고요?",
                "key_points": [
                    "새 기능 발표에서 확인된 주요 사용 사례를 정리합니다.",
                    "무료와 유료 이용 조건은 서비스별로 다릅니다.",
                    "개인정보와 결과 검증을 고려해 사용해야 합니다.",
                ],
                "source_urls": ["https://example.com/source"],
            }],
        }
        preview = _make_preview(report["trends"][0], report)
        self.assertEqual(preview["status"], "preview_only_not_approved")
        self.assertIsNotNone(preview["blog"])
        self.assertEqual(len(preview["shorts"]), 3)
        self.assertEqual(len(preview["threads"]), 5)
        self.assertTrue(preview["source_urls"])
        self.assertIn("미리보기", preview["warning"])


if __name__ == "__main__":
    unittest.main()
