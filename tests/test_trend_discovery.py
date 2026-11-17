import json
from pathlib import Path
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from tak_scout.perplexity_research import ResearchResult
from tak_scout.trend_discovery import build_trend_query, parse_trend_result
from scripts.run_trend_content_mvp import (
    _basic_auth_valid, _make_preview, _page, _parse_content_package, _same_origin,
    _resolve_writable_data_dir,
)


class TrendDiscoveryTests(unittest.TestCase):
    def _answer(self):
        rows = []
        for index in range(1, 7):
            rows.append({
                "rank": index,
                "keyword": f"분야{index} 트렌드 키워드 {index}",
                "category": "AI·테크" if index % 2 else "생활",
                "summary": "최근 공개된 발표와 자료에서 확인된 변화에 관한 설명입니다.",
                "why_now": "최근 7일 안에 공식 발표가 공개되어 관심이 모이고 있습니다.",
                "audience_question": "이 변화가 내 생활에 어떤 영향을 줄까요?",
                "content_angle": "초보자 관점에서 실제 영향과 확인 방법을 비교합니다.",
                "blog_title": f"분야{index} 고유이슈{index}번의 핵심 영향",
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


    def test_near_duplicate_topics_are_removed_and_editorial_score_is_exposed(self):
        payload = json.loads(self._answer())
        payload["trends"][1]["keyword"] = "트렌드 키워드 1 최신 정보"
        payload["trends"][1]["blog_title"] = payload["trends"][0]["blog_title"]
        result = ResearchResult("query", json.dumps(payload, ensure_ascii=False),
                                ("https://example.com/source",), "sonar-pro")
        parsed = parse_trend_result(result)
        self.assertEqual(len(parsed.trends), 5)
        self.assertTrue(all(0 <= item.content_score <= 100 for item in parsed.trends))
        self.assertEqual([item.rank for item in parsed.trends], list(range(1, 6)))

    def test_category_concentration_is_limited_and_uncited_items_are_excluded(self):
        payload = json.loads(self._answer())
        for index, row in enumerate(payload["trends"]):
            row["keyword"] = f"독립적인 주제 {index}번"
            row["blog_title"] = f"주제분야 {index}번만의 새 이슈"
            row["category"] = "경제·금융" if index < 5 else "건강"
        payload["trends"][0]["source_urls"] = ["https://unverified.example/nope"]
        result = ResearchResult("query", json.dumps(payload, ensure_ascii=False),
                                ("https://example.com/source",), "sonar-pro")
        parsed = parse_trend_result(result)
        counts = {}
        for item in parsed.trends:
            counts[item.category] = counts.get(item.category, 0) + 1
        self.assertLessEqual(counts.get("경제·금융", 0), 4)
        self.assertNotIn("독립적인 주제 0번", [item.keyword for item in parsed.trends])

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


    def test_preview_page_has_copy_controls_for_each_platform(self):
        preview = {
            "keyword": "테스트 주제",
            "warning": "검토용 초안",
            "blog": {"title": "블로그 제목", "body": "블로그 본문"},
            "shorts": [{"title": "쇼츠 제목", "body": "쇼츠 대본"}],
            "threads": [{"title": "Threads 제목", "body": "Threads 본문"}],
            "source_urls": ["https://example.com/source"],
        }
        html = _page({"trends": []}, [preview])
        self.assertIn("블로그 원고 복사", html)
        self.assertIn("쇼츠 대본 복사", html)
        self.assertIn("Threads 글 복사", html)
        self.assertIn("navigator.clipboard.writeText", html)
        self.assertIn("YouTube 설명란", html)
        self.assertIn("Instagram 릴스 문안", html)
        self.assertIn("TikTok 설명문", html)
        self.assertIn("게시 계정 연결 현황", html)
        self.assertIn("네이버 블로그", html)

    def test_dashboard_exposes_approval_schedule_and_disabled_publishing_status(self):
        preview = {
            "keyword": "예약 테스트", "blog": {"title": "제목", "body": "본문"},
            "shorts": [{"title": "쇼츠", "body": "대본"}],
            "threads": [{"title": "Threads", "body": "글"}],
        }
        html = _page({"trends": []}, [preview], queue_snapshot={"items": [], "history": []})
        self.assertIn('action="/queue/approve"', html)
        self.assertIn('name="scheduled_at"', html)
        self.assertIn("승인 후에도 실제 게시 기능은 기본 비활성 상태입니다.", html)
        self.assertIn("비활성화 (기본값)", html)
        self.assertIn("pending approval: 1", html)
        self.assertIn("계정명 확인 필요", html)

    def test_parses_perplexity_content_package(self):
        blog_body = "# 검색 유입형 제목\\n\\n" + ("독자가 궁금해하는 핵심 내용을 근거와 함께 설명합니다. " * 30)
        package = {
            "blog": {"title": "검색형 제목", "meta_description": "검색 설명",
                     "focus_keyword": "트렌드", "body": blog_body},
            "shorts": {"title": "60초 쇼츠", "duration_seconds": 60,
                       "hook": "첫 3초 후킹",
                       "scenes": [{"time": f"{i*8:02d}-{i*8+8:02d}초",
                                   "visual": "관련 화면", "caption": "핵심 자막",
                                   "narration": "근거에 기반한 내레이션"} for i in range(6)],
                       "closing_cta": "댓글로 의견을 남겨주세요.", "youtube_description": "유튜브 설명", "instagram_caption": "인스타 문안", "tiktok_caption": "틱톡 문안", "hashtags": ["정보"]},
            "threads": [{"title": "후킹 1", "body": "첫 번째 독립적인 Threads 글입니다."},
                        {"title": "후킹 2", "body": "두 번째 독립적인 Threads 글입니다."}],
        }
        parsed = _parse_content_package(json.dumps(package, ensure_ascii=False))
        self.assertEqual(len(parsed["shorts"]["scenes"]), 6)
        self.assertEqual(len(parsed["threads"]), 2)
        package["shorts"]["scenes"][0] = {"time": "00-08초"}
        with self.assertRaisesRegex(ValueError, "화면 구성"):
            _parse_content_package(json.dumps(package, ensure_ascii=False))

    def test_rejects_too_short_blog(self):
        invalid = {
            "blog": {"title": "짧음", "body": "짧은 본문"},
            "shorts": {"scenes": [{"time": "x"}] * 5},
            "threads": [{"body": "a"}, {"body": "b"}],
        }
        with self.assertRaises(ValueError):
            _parse_content_package(json.dumps(invalid))

    def test_llm_preview_uses_perplexity_and_returns_one_shorts_script(self):
        class FakeProvider:
            def __init__(self):
                self.query = ""
                self.recency = None

            def search(self, query, **kwargs):
                self.query = query
                self.recency = kwargs.get("search_recency_filter")
                body = "# 제목\\n\\n" + ("확인된 사실과 독자에게 미치는 영향을 설명합니다. " * 30)
                package = {
                    "blog": {"title": "검색형 블로그 제목", "meta_description": "설명",
                             "focus_keyword": "생성형 AI", "body": body},
                    "shorts": {"title": "60초 쇼츠", "duration_seconds": 60,
                               "hook": "첫 3초 후킹",
                               "scenes": [{"time": f"{i*8:02d}-{i*8+8:02d}초",
                                           "visual": "화면", "caption": "자막",
                                           "narration": "내레이션"} for i in range(6)],
                               "closing_cta": "댓글을 남겨주세요.",
                               "youtube_description": "YouTube 설명",
                               "instagram_caption": "Instagram 문안",
                               "tiktok_caption": "TikTok 문안",
                               "hashtags": ["생성형AI"]},
                    "threads": [{"title": "글1", "body": "첫 번째 Threads 글입니다."},
                                {"title": "글2", "body": "두 번째 Threads 글입니다."}],
                }
                return ResearchResult(query, json.dumps(package, ensure_ascii=False),
                                       ("https://example.com/extra",), "sonar-pro")

        report = {
            "researched_at": "2026-11-17T09:00:00+09:00",
            "citations": ["https://example.com/source"],
            "trends": [],
        }
        item = {
            "rank": 1, "keyword": "생성형 AI", "category": "AI·테크",
            "summary": "최근 공개 자료에서 확인된 생성형 AI의 변화입니다.",
            "why_now": "최근 7일 안에 주요 서비스의 신규 기능이 발표됐습니다.",
            "audience_question": "어떤 기능을 먼저 써야 할까요?",
            "content_angle": "실제 이용자 관점에서 기능과 주의점을 비교합니다.",
            "blog_title": "생성형 AI 최신 기능 정리",
            "key_points": ["첫 번째 사실을 설명하는 근거 문장입니다.",
                           "두 번째 사실을 설명하는 근거 문장입니다.",
                           "세 번째 사실을 설명하는 근거 문장입니다."],
            "source_urls": ["https://example.com/source"],
        }
        provider = FakeProvider()
        preview = _make_preview(item, report, provider=provider)
        self.assertEqual(provider.recency, "week")
        self.assertIn("verified_source_urls", provider.query)
        self.assertEqual(preview["status"], "preview_only_not_approved")
        self.assertEqual(len(preview["shorts"]), 1)
        self.assertEqual(len(preview["shorts"][0]["scenes"]), 6)
        self.assertIn("youtube_description", preview["shorts"][0])
        self.assertIn("instagram_caption", preview["shorts"][0])
        self.assertIn("tiktok_caption", preview["shorts"][0])
        self.assertEqual(len(preview["threads"]), 2)
        self.assertIn("https://example.com/extra", preview["source_urls"])


    def test_unwritable_configured_data_dir_falls_back_to_tmp(self):
        with tempfile.TemporaryDirectory() as directory:
            configured = Path(directory) / "blocked"
            original_mkdir = Path.mkdir

            def deny_configured_directory(path, *args, **kwargs):
                if path == configured:
                    raise PermissionError("simulated unwritable directory")
                return original_mkdir(path, *args, **kwargs)

            with patch.object(Path, "mkdir", deny_configured_directory):
                selected, is_fallback = _resolve_writable_data_dir(configured)
        self.assertTrue(is_fallback)
        self.assertTrue(selected.is_dir())
        self.assertIn("tak-auto-data", str(selected))


if __name__ == "__main__":
    unittest.main()


class CloudWebSecurityTests(unittest.TestCase):
    def test_basic_auth_accepts_only_matching_credentials(self):
        import base64
        token = base64.b64encode("owner:strong-password".encode()).decode()
        self.assertTrue(_basic_auth_valid("Basic " + token, "owner", "strong-password"))
        self.assertFalse(_basic_auth_valid("Basic " + token, "owner", "wrong-password"))
        self.assertFalse(_basic_auth_valid("", "owner", "strong-password"))
        self.assertFalse(_basic_auth_valid("Basic !!!", "owner", "strong-password"))

    def test_same_origin_allows_render_https_proxy_and_rejects_cross_origin(self):
        self.assertTrue(_same_origin("https://tak.example.com", "tak.example.com", "https"))
        self.assertFalse(_same_origin("https://evil.example", "tak.example.com", "https"))
        self.assertFalse(_same_origin("http://tak.example.com", "tak.example.com", "https"))
        self.assertFalse(_same_origin("", "tak.example.com", "https"))
        self.assertTrue(_same_origin("http://127.0.0.1:8765", "127.0.0.1:8765", "https"))
        self.assertFalse(_same_origin("https://127.0.0.1:8765", "127.0.0.1:8765", "https"))
