"""tak_scout.rss 검증. 실제 네트워크를 사용하지 않고 RSS XML 텍스트만으로 검증한다."""

from __future__ import annotations

import unittest

from tak_scout.models import compute_scout_id
from tak_scout.rss import ScoutRssError, parse_rss_items


RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>테스트 피드</title>
    <item>
      <title>첫 번째 기사</title>
      <link>https://example.test/articles/1</link>
      <description><![CDATA[<p>첫 번째 기사의 <b>짧은</b> 요약입니다.</p>]]></description>
      <pubDate>Thu, 10 Sep 2026 15:02:52 +0900</pubDate>
    </item>
    <item>
      <title>두 번째 기사</title>
      <link>https://example.test/articles/2</link>
      <description>두 번째 기사 요약</description>
      <pubDate>Wed, 09 Sep 2026 12:00:00 +0900</pubDate>
    </item>
  </channel>
</rss>
"""


class ParseRssItemsTests(unittest.TestCase):
    def test_parses_title_summary_url_published_at(self):
        candidates = parse_rss_items(RSS_XML, source_name="테스트 소스", category="finance")

        self.assertEqual(len(candidates), 2)
        first = candidates[0]
        self.assertEqual(first.title, "첫 번째 기사")
        self.assertEqual(first.source_url, "https://example.test/articles/1")
        self.assertEqual(first.summary, "첫 번째 기사의 짧은 요약입니다.")
        self.assertEqual(first.published_at, "2026-09-10T15:02:52+09:00")
        self.assertEqual(first.source_name, "테스트 소스")
        self.assertEqual(first.category, "finance")

    def test_scout_id_is_deterministic_and_matches_helper(self):
        candidates = parse_rss_items(RSS_XML, source_name="테스트 소스", category="finance")

        expected = compute_scout_id("첫 번째 기사", "https://example.test/articles/1")
        self.assertEqual(candidates[0].scout_id, expected)

        # 같은 XML을 다시 파싱해도 scout_id가 바뀌지 않는다.
        again = parse_rss_items(RSS_XML, source_name="테스트 소스", category="finance")
        self.assertEqual(candidates[0].scout_id, again[0].scout_id)

    def test_items_missing_title_or_link_are_skipped(self):
        xml_text = """<rss version="2.0"><channel>
        <item><title>제목만 있음</title><description>요약</description></item>
        <item><link>https://example.test/only-link</link><description>요약</description></item>
        <item><title>정상 기사</title><link>https://example.test/ok</link><description>요약</description></item>
        </channel></rss>"""

        candidates = parse_rss_items(xml_text, source_name="소스", category="기타")

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].title, "정상 기사")

    def test_invalid_xml_raises_scout_rss_error(self):
        with self.assertRaises(ScoutRssError):
            parse_rss_items("<rss>", source_name="소스", category="기타")

    def test_summary_strips_html_and_truncates_long_text(self):
        long_text = "가" * 300
        xml_text = f"""<rss version="2.0"><channel>
        <item><title>긴 요약</title><link>https://example.test/long</link>
        <description>{long_text}</description></item>
        </channel></rss>"""

        candidates = parse_rss_items(xml_text, source_name="소스", category="기타")

        self.assertLessEqual(len(candidates[0].summary), 201)  # 200자 + 말줄임표
        self.assertTrue(candidates[0].summary.endswith("…"))


if __name__ == "__main__":
    unittest.main()
