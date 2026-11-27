import hashlib
import json
import unittest
from unittest.mock import patch
from scripts import run_trend_content_mvp as app
from scripts.check_trend_factory_deployment import validate_health


class FreeModeTests(unittest.TestCase):
    def test_scout_selection_keeps_topic_diversity(self):
        from datetime import datetime, timezone
        from tak_scout.models import ScoutCandidate
        now = datetime.now(timezone.utc).isoformat()
        finance = [ScoutCandidate(f"finance-{i}", f"금융 변화 발표 {i}", "금융 소식 요약", f"https://example.com/f/{i}", now, "금융 피드", "finance") for i in range(12)]
        tech = ScoutCandidate("tech-1", "새 기술 소식", "기술 소식 요약", "https://example.com/t/1", now, "기술 피드", "tech")
        selected = app._select_diverse_scout_candidates(finance + [tech])
        self.assertEqual(len(selected), 10)
        self.assertIn(tech, selected)

    def test_scout_category_leader_prefers_publisher_link(self):
        from datetime import datetime, timezone
        from tak_scout.models import ScoutCandidate
        now = datetime.now(timezone.utc).isoformat()
        relay = ScoutCandidate("relay", "충격 발표 최초 공개", "변화와 영향", "https://news.google.com/rss/articles/1", now, "Google News", "tech")
        publisher = ScoutCandidate("publisher", "기술 소식", "새로운 기술", "https://www.bbc.com/news/technology-1", now, "BBC Technology", "tech")
        selected = app._select_diverse_scout_candidates([relay, publisher], limit=1)
        self.assertEqual(selected, [publisher])

    def test_google_news_relay_is_marked_as_unverified_original(self):
        from types import SimpleNamespace
        item = {"summary": "피드에 나온 짧은 요약입니다.", "source_urls": ["https://news.google.com/rss/articles/example"],
                "source_name": "Google News", "published_at": "2026-11-27T00:00:00+00:00", "origin": "tak-scout"}
        preview = app._make_scout_preview(item, {}, SimpleNamespace(title="기사 제목", id="knowledge-1"))
        self.assertIn("중계 링크", preview["warning"])
        self.assertEqual(preview["status"], "preview_only_not_approved")

    def test_free_perplexity_prompt_uses_https_scout_lead(self):
        item = {"keyword": "오늘 수집한 주제", "source_urls": ["https://example.com/news"]}
        prompt = app._free_perplexity_prompt(item)
        self.assertIn("https://example.com/news", prompt)
        self.assertIn("공식 원문을 확인할 수 없으면", prompt)
        self.assertIn("## 블로그 원고", prompt)
        self.assertIn("## 60초 쇼츠 대본", prompt)
        self.assertEqual(app._free_perplexity_prompt({**item, "source_urls": ["javascript:alert(1)"]}), "")

    def test_combined_perplexity_answer_requires_two_ordered_sections(self):
        blog, shorts = app._split_pasted_draft("안내\n## 블로그 원고\n기사 본문\n## 60초 쇼츠 대본\n장면 대본")
        self.assertEqual((blog, shorts), ("기사 본문", "장면 대본"))
        for invalid in ("블로그 원고\n기사만", "쇼츠 대본\n장면\n블로그 원고\n기사", "블로그 원고\n기사\n쇼츠 대본\n장면\n쇼츠 대본\n다른 장면"):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, "순서대로"):
                app._split_pasted_draft(invalid)

    def test_free_mode_blocks_paid_provider_even_with_key(self):
        with patch.dict("os.environ", {"TAK_AUTO_FREE_MODE": "true", "TAK_SCOUT_PERPLEXITY_API_KEY": "unused"}), patch.object(app.PerplexityResearchProvider, "from_environment") as provider:
            with self.assertRaises(ValueError):
                app._paid_research_provider()
            provider.assert_not_called()

    def test_refresh_keeps_recent_articles_and_preserves_previous_on_stale_feeds(self):
        from datetime import datetime, timedelta, timezone
        from tak_scout.models import ScoutCandidate
        now = datetime(2026, 11, 26, tzinfo=timezone.utc)
        def candidate(name, age):
            return ScoutCandidate(name, name, "충분한 길이의 출처 요약입니다.", f"https://example.com/{name}",
                                  (now - age).isoformat(), "검증 피드", "general")
        previous = {"trends": [{"keyword": "기존 후보", "origin": "manual"}]}
        with patch.object(app, "load_sources", return_value=[{"url": "https://example.com/rss"}]), \
                patch.object(app, "collect_all", return_value=([candidate("today", timedelta(days=1)),
                    candidate("old", timedelta(days=8))], [])):
            report = app._refresh_scout_trends(previous, now=now)
        self.assertEqual([row["keyword"] for row in report["trends"]], ["today", "기존 후보"])
        with patch.object(app, "load_sources", return_value=[]), \
                patch.object(app, "collect_all", return_value=([candidate("old", timedelta(days=8))], [])):
            with self.assertRaisesRegex(ValueError, "최근 7일"):
                app._refresh_scout_trends(previous, now=now)
        self.assertEqual(previous["trends"][0]["keyword"], "기존 후보")

    def test_refresh_selects_usable_article_before_ranking(self):
        from datetime import datetime, timezone
        from tak_scout.models import ScoutCandidate
        now = datetime.now(timezone.utc)
        empty = ScoutCandidate("empty", "충격 발표", "", "https://example.com/empty", now.isoformat(), "빈 피드", "tech")
        usable = ScoutCandidate("usable", "기술 기사", "원문을 설명하는 충분한 길이의 요약입니다.", "https://example.com/usable", now.isoformat(), "기술 피드", "tech")
        with patch.object(app, "load_sources", return_value=[]), patch.object(app, "collect_all", return_value=([empty, usable], [])):
            report = app._refresh_scout_trends({}, now=now)
        self.assertEqual([row["keyword"] for row in report["trends"]], ["기술 기사"])

    def test_imported_scout_age_warning_uses_publication_time(self):
        from datetime import datetime, timedelta, timezone

        now = datetime(2026, 11, 27, tzinfo=timezone.utc)
        item = {"origin": "tak-scout", "published_at": (now - timedelta(days=8)).isoformat()}
        self.assertIn("7일", app._scout_age_warning(item, now=now))
        item["published_at"] = (now - timedelta(days=1)).isoformat()
        self.assertEqual(app._scout_age_warning(item, now=now), "")
        item["published_at"] = ""
        self.assertIn("확인할 수 없습니다", app._scout_age_warning(item, now=now))

    def test_manual_input_to_template_and_queue_payload(self):
        item = app._manual_trend({"keyword": ["생활 정보"], "source_url": ["https://example.com/source"], "facts": ["첫 번째 확인한 근거 자료입니다.\n두 번째 확인한 근거 자료입니다.\n세 번째 확인한 근거 자료입니다."]})
        with patch.object(app.PerplexityResearchProvider, "from_environment") as provider:
            preview = app._make_preview(item, {"citations": item["source_urls"]})
            provider.assert_not_called()
        self.assertEqual(preview["status"], "preview_only_not_approved")
        self.assertTrue(app._queue_payload_for_platform(preview, "threads"))

    def test_manual_input_rejects_unsafe_source_and_insufficient_evidence(self):
        for source, facts in [("javascript:alert(1)", "a"), ("https://example.com", "a")]:
            with self.assertRaises(ValueError):
                app._manual_trend({"keyword": ["topic"], "source_url": [source], "facts": [facts]})

    def test_free_readiness_needs_storage_and_auth_but_no_paid_key(self):
        env = {"TAK_AUTO_FREE_MODE": "true", "TAK_WEB_USERNAME": "operator", "TAK_WEB_PASSWORD": "password"}
        with patch.object(app, "USING_EPHEMERAL_STORAGE", False):
            health = app._health_payload(env)
        self.assertTrue(health["ready"])
        self.assertFalse(health["perplexity_configured"])
        self.assertEqual(validate_health(health), [])
        with patch.object(app, "USING_EPHEMERAL_STORAGE", True):
            self.assertFalse(app._health_payload(env)["ready"])

    def test_many_scout_drafts_keep_edited_copy_and_same_title_sources(self):
        import tempfile
        import threading
        from datetime import datetime, timezone
        from http.server import ThreadingHTTPServer
        from pathlib import Path
        from urllib.parse import urlencode
        from urllib.request import Request, urlopen

        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {
            "TAK_AUTO_FREE_MODE": "true", "TAK_AUTO_PUBLISHING_ENABLED": "false",
            "TAK_WEB_USERNAME": "", "TAK_WEB_PASSWORD": "", "TAK_AUTO_PUBLIC_URL": "",
        }), patch.object(app.PerplexityResearchProvider, "from_environment") as provider:
            root = Path(directory)
            with patch.multiple(app, DATA_DIR=root, TREND_PATH=root / "trends.json", PREVIEW_PATH=root / "previews.json", QUEUE_PATH=root / "queue.json"):
                server = ThreadingHTTPServer(("127.0.0.1", 0), app.create_handler())
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                origin = f"http://127.0.0.1:{server.server_port}"
                def post(path, data):
                    request = Request(origin + path, data=urlencode(data).encode(), headers={"Origin": origin})
                    with urlopen(request, timeout=5) as response:
                        return response.read()
                try:
                    candidates = [{
                        "title": "공통 제목" if index < 2 else f"주제 {index}",
                        "summary": f"출처 {index}에서 확인한 충분한 길이의 원본 요약입니다.",
                        "source_url": f"https://example.com/article/{index}",
                        "source_name": "검증 피드",
                        "published_at": datetime.now(timezone.utc).isoformat(),
                    } for index in range(11)]
                    app._write_json(app.TREND_PATH, app._scout_trends(json.dumps({"candidates": candidates}), {}))
                    post("/generate", {"index": "0"})
                    original = app._read_json(app.PREVIEW_PATH, [])[0]["blog"]["body"]
                    edited = "원문 확인 뒤 수정한 원고"
                    post("/scout/edit", {"preview_index": "0", "target": "blog.body",
                         "base_hash": hashlib.sha256(original.encode()).hexdigest(), "body": edited})
                    for index in range(1, len(candidates)):
                        post("/generate", {"index": str(index)})
                    previews = app._read_json(app.PREVIEW_PATH, [])
                    self.assertEqual(len(previews), 11)
                    self.assertEqual(previews[-1]["blog"]["body"], edited)
                    self.assertEqual(len([row for row in previews if row["keyword"] == "공통 제목"]), 2)
                    self.assertEqual(len({row["source_urls"][0] for row in previews}), 11)
                    provider.assert_not_called()
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=2)

    def test_free_http_flow_and_paid_route_guards(self):
        import tempfile
        import threading
        from pathlib import Path
        from datetime import datetime, timedelta, timezone
        from http.server import ThreadingHTTPServer
        from urllib.parse import urlencode
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError
        from content_engine.publishing_queue import PublishingQueue
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {
            "TAK_AUTO_FREE_MODE": "true", "TAK_AUTO_PUBLISHING_ENABLED": "false",
            "TAK_WEB_USERNAME": "", "TAK_WEB_PASSWORD": "", "TAK_AUTO_PUBLIC_URL": "",
        }), patch.object(app.PerplexityResearchProvider, "from_environment") as provider:
            root = Path(directory)
            with patch.multiple(app, DATA_DIR=root, TREND_PATH=root / "trends.json", PREVIEW_PATH=root / "previews.json", QUEUE_PATH=root / "queue.json"):
                server = ThreadingHTTPServer(("127.0.0.1", 0), app.create_handler())
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                origin = f"http://127.0.0.1:{server.server_port}"
                def post(path, data):
                    request = Request(origin + path, data=urlencode(data).encode(), headers={"Origin": origin})
                    with urlopen(request, timeout=5) as response:
                        return response.read().decode()
                try:
                    post("/manual", {"keyword": "생활 정보", "source_url": "https://example.com/source", "facts": "첫 번째 확인한 근거 자료입니다.\n두 번째 확인한 근거 자료입니다.\n세 번째 확인한 근거 자료입니다."})
                    post("/generate", {"index": "0"})
                    preview = app._read_json(app.PREVIEW_PATH, [])[0]
                    self.assertEqual(PublishingQueue(app.QUEUE_PATH).snapshot()["items"], [])
                    post("/queue/approve", {"preview_index": "0", "platform": "threads", "scheduled_at": (datetime.now(app.KST) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")})
                    self.assertEqual(len(PublishingQueue(app.QUEUE_PATH).snapshot()["items"]), len(preview["threads"]))
                    with self.assertRaises(HTTPError) as error:
                        post("/discover", {})
                    self.assertEqual(error.exception.code, 400)
                    error.exception.close()
                    from tak_scout.models import ScoutCandidate
                    fresh = ScoutCandidate("scout-fresh", "오늘 수집한 주제", "오늘 확인할 수 있는 원본 요약입니다.", "https://example.com/fresh", datetime.now(timezone.utc).isoformat(), "검증 피드", "general")
                    with patch.object(app, "collect_all", return_value=([fresh], [])):
                        post("/scout/refresh", {})
                    self.assertIn("오늘 수집한 주제", app._read_json(app.TREND_PATH, {})["trends"][0]["keyword"])
                    scout_pack = {"generated_at": "2026-11-26T00:00:00Z", "candidates": [
                        {"title": "탁스카우트 검증 주제", "summary": "수집 피드에 포함된 원본 요약입니다.",
                         "source_url": "https://example.com/scout", "source_name": "검증 피드",
                         "published_at": datetime.now(timezone.utc).isoformat()},
                        {"title": "지난 주 소식", "summary": "날짜 확인을 요구할 충분한 길이의 원본 요약입니다.",
                         "source_url": "https://example.com/old", "source_name": "검증 피드",
                         "published_at": (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()},
                        {"title": "잘못된 주소", "summary": "선택지에 나타나지 않아야 하는 후보입니다.",
                         "source_url": "javascript:alert(1)"},
                    ]}
                    scout_path = root / "tak_scout_daily.json"
                    scout_path.write_text(json.dumps(scout_pack), encoding="utf-8")
                    with patch.dict("os.environ", {"TAK_SCOUT_DAILY_PACK": str(scout_path)}):
                        html = post("/scout/import", {})
                    self.assertIn('<body class="free-mode">', html)
                    self.assertIn('.free-mode .stage-two{display:none}', html)
                    self.assertIn('href="#free-import"', html)
                    self.assertIn('id="saved-drafts"', html)
                    self.assertIn("탁스카우트 검증 주제", html)
                    self.assertIn("요청문 복사", html)
                    self.assertIn("공식 원문을 확인할 수 없으면", html)
                    self.assertNotIn("잘못된 주소", html)
                    upload = Request(origin + "/scout/import", data=json.dumps(scout_pack).encode(), headers={
                        "Origin": origin, "Content-Type": "application/json",
                    })
                    with urlopen(upload, timeout=5) as reply:
                        self.assertEqual(json.load(reply), {"ok": True})
                    html = post("/generate", {"index": "0"})
                    self.assertIn("블로그 원고 복사", html)
                    self.assertIn("쇼츠 대본 복사", html)
                    scout_draft = app._read_json(app.PREVIEW_PATH, [])[0]
                    self.assertEqual(scout_draft["source_urls"], ["https://example.com/scout"])
                    self.assertIn("원본 요약", scout_draft["blog"]["body"])
                    self.assertIn("원본 요약", scout_draft["shorts"][0]["body"])
                    self.assertEqual(scout_draft["status"], "preview_only_not_approved")
                    original = scout_draft["blog"]["body"]
                    edit = {"preview_index": "0", "target": "blog.body",
                            "base_hash": hashlib.sha256(original.encode()).hexdigest(),
                            "body": "원문 확인 후 직접 고친 블로그 원고"}
                    post("/scout/edit", edit)
                    updated = app._read_json(app.PREVIEW_PATH, [])[0]
                    self.assertEqual(updated["blog"]["body"], edit["body"])
                    self.assertEqual(updated["editorial_history"][0]["before"], original)
                    with self.assertRaises(HTTPError) as regenerate:
                        post("/generate", {"index": "0"})
                    self.assertEqual(regenerate.exception.code, 400)
                    regenerate.exception.close()
                    self.assertEqual(app._read_json(app.PREVIEW_PATH, [])[0]["blog"]["body"], edit["body"])
                    with self.assertRaises(HTTPError) as stale:
                        post("/scout/edit", edit)
                    self.assertEqual(stale.exception.code, 400)
                    stale.exception.close()
                    post("/editorial/revert", {"preview_index": "0", "revision_id": updated["editorial_history"][0]["revision_id"]})
                    self.assertEqual(app._read_json(app.PREVIEW_PATH, [])[0]["blog"]["body"], original)
                    with self.assertRaises(HTTPError) as stale_source:
                        post("/generate", {"index": "1"})
                    self.assertEqual(stale_source.exception.code, 400)
                    stale_source.exception.close()
                    post("/generate", {"index": "1", "confirm_source_age": "yes"})
                    self.assertIn("7일", app._read_json(app.PREVIEW_PATH, [])[0]["warning"])
                    self.assertEqual(len(PublishingQueue(app.QUEUE_PATH).snapshot()["items"]), len(preview["threads"]))
                    provider.assert_not_called()
                    self.assertFalse(app._health_payload()["publishing_enabled"])
                    pasted_blog = "# 실제 원문을 대조한 블로그 원고\n\n" + ("공식 자료에서 확인한 내용을 정리합니다. " * 20)
                    pasted_shorts = "0~10초 | 화면: 공식 발표문 | 자막: 오늘의 발표 | 내레이션: 공식 발표 내용을 확인합니다."
                    html = post("/perplexity/import", {"title": "무료 Perplexity 원고", "source_url": "https://example.com/official",
                                                     "blog_body": pasted_blog, "shorts_body": pasted_shorts})
                    pasted = app._read_json(app.PREVIEW_PATH, [])[0]
                    self.assertEqual(pasted["blog"]["body"], pasted_blog.strip())
                    self.assertEqual(pasted["shorts"][0]["body"], pasted_shorts)
                    self.assertEqual(pasted["content_model"], "perplexity-free-paste")
                    self.assertEqual(pasted["status"], "preview_only_not_approved")
                    self.assertIn("블로그 원고 복사", html)
                    with self.assertRaises(HTTPError) as unsafe_source:
                        post("/perplexity/import", {"title": "잘못된 출처", "source_url": "http://example.com",
                                                    "blog_body": pasted_blog, "shorts_body": pasted_shorts})
                    self.assertEqual(unsafe_source.exception.code, 400)
                    unsafe_source.exception.close()
                    combined = "사실 확인 안내\n## 블로그 원고\n" + pasted_blog + "\n## 60초 쇼츠 대본\n" + pasted_shorts
                    post("/perplexity/import", {"title": "무료 Perplexity 원고", "source_url": "https://example.com/official",
                                                "combined_body": combined})
                    combined_draft = app._read_json(app.PREVIEW_PATH, [])[0]
                    self.assertEqual(combined_draft["blog"]["body"], pasted_blog.strip())
                    self.assertEqual(combined_draft["shorts"][0]["body"], pasted_shorts)
                    with self.assertRaises(HTTPError) as mixed_input:
                        post("/perplexity/import", {"title": "무료 Perplexity 원고", "source_url": "https://example.com/official",
                                                    "combined_body": combined, "blog_body": pasted_blog})
                    self.assertEqual(mixed_input.exception.code, 400)
                    mixed_input.exception.close()
                    post("/scout/edit", {"preview_index": "0", "target": "blog.body",
                                         "base_hash": hashlib.sha256(pasted_blog.strip().encode()).hexdigest(),
                                         "body": "원문 확인 후 수정한 블로그 원고"})
                    self.assertEqual(app._read_json(app.PREVIEW_PATH, [])[0]["blog"]["body"], "원문 확인 후 수정한 블로그 원고")
                    provider.assert_not_called()
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=2)
