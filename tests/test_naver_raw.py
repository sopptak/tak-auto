import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from blog_importer.naver_post import PublicPostExtraction, NaverPostError
from blog_importer.naver_raw import collect_naver_rss, select_published_at


RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<item><title>HTML 글</title><link>https://blog.naver.com/tmong2/1</link><guid>post-1</guid>
<description>RSS 요약 1</description><pubDate>Thu, 10 Sep 2026 15:02:52 +0900</pubDate><category>기록</category></item>
<item><title>Fallback 글</title><link>https://blog.naver.com/tmong2/2</link><guid>post-2</guid>
<description>RSS fallback 본문</description><pubDate>Wed, 09 Sep 2026 12:00:00 +0900</pubDate></item>
</channel></rss>"""


class NaverRawTests(unittest.TestCase):
    def test_rss_date_wins_over_absolute_or_relative_html_date(self):
        self.assertEqual(
            select_published_at("2026-09-10T15:02:52+09:00", "2026. 09. 11."),
            "2026-09-10T15:02:52+09:00",
        )
        self.assertEqual(select_published_at("", "1시간 전"), "")
        self.assertEqual(select_published_at("", "2026. 09. 11."), "2026. 09. 11.")

    def test_html_body_and_rss_fallback_are_stored_with_status(self):
        def fetcher(url: str, timeout: float) -> PublicPostExtraction:
            if url.endswith("/2"):
                raise NaverPostError("공개 본문 접근 실패")
            return PublicPostExtraction("HTML 보조 제목", "1시간 전", "정제된 HTML 본문", None, 200, None)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "raw.json"
            with patch("blog_importer.naver_raw.fetch_rss", return_value=RSS_XML):
                report = collect_naver_rss("https://rss.example.test/tmong2.xml", str(output), post_fetcher=fetcher)

            records = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual((report.total, report.new, report.full, report.partial, report.failed), (2, 2, 1, 1, 0))
            self.assertEqual(records[0]["raw"]["title"], "HTML 글")
            self.assertEqual(records[0]["raw"]["body"], "정제된 HTML 본문")
            self.assertEqual(records[0]["raw"]["extraction_status"], "full")
            self.assertEqual(records[0]["raw"]["published_at"], "2026-09-10T15:02:52+09:00")
            self.assertEqual(records[1]["raw"]["body"], "RSS fallback 본문")
            self.assertEqual(records[1]["raw"]["extraction_method"], "naver_rss_description")
            self.assertEqual(records[1]["raw"]["extraction_status"], "partial")

    def test_hash_and_source_url_both_prevent_reimport(self):
        calls = 0

        def fetcher(url: str, timeout: float) -> PublicPostExtraction:
            nonlocal calls
            calls += 1
            body = "본문 첫 수집" if calls <= 2 else "본문 변경 수집"
            return PublicPostExtraction("제목", None, body, None, 200, None)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "raw.json"
            with patch("blog_importer.naver_raw.fetch_rss", return_value=RSS_XML):
                first = collect_naver_rss("https://rss.example.test/tmong2.xml", str(output), post_fetcher=fetcher)
                second = collect_naver_rss("https://rss.example.test/tmong2.xml", str(output), post_fetcher=fetcher)

            self.assertEqual(first.new, 2)
            self.assertEqual(second.duplicate, 2)
            self.assertEqual(len(json.loads(output.read_text(encoding="utf-8"))), 2)

    def test_risk_flag_is_preserved_in_raw_metadata(self):
        risk_xml = RSS_XML.replace("RSS 요약 1", "계좌번호 123-456-789와 특정 고객 정보")

        def fetcher(url: str, timeout: float) -> PublicPostExtraction:
            body = "계좌번호 123-456-789와 특정 고객 정보" if url.endswith("/1") else "일반 본문"
            return PublicPostExtraction("제목", None, body, None, 200, None)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "raw.json"
            with patch("blog_importer.naver_raw.fetch_rss", return_value=risk_xml):
                report = collect_naver_rss("https://rss.example.test/tmong2.xml", str(output), post_fetcher=fetcher)

            records = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report.risk_flags, 1)
            self.assertTrue(records[0]["metadata"]["risk_flag"])
            self.assertIn("privacy_or_financial", records[0]["metadata"]["risk_flags"])


if __name__ == "__main__":
    unittest.main()
