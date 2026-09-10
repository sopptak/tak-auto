import unittest

from blog_importer.naver_rss import NaverRssError, parse_rss
from tak_brain import BrainRepository


RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>테스트 블로그</title>
    <item>
      <title><![CDATA[첫 번째 글]]></title>
      <link>https://blog.naver.com/tmong2/1001</link>
      <guid>https://blog.naver.com/tmong2/1001</guid>
      <description><![CDATA[전체로 보이는 공개 요약]]></description>
      <pubDate>Thu, 10 Sep 2026 15:02:52 +0900</pubDate>
      <category><![CDATA[기록]]></category>
      <tag><![CDATA[테스트,원본]]></tag>
    </item>
    <item>
      <title>두 번째 글</title>
      <link>https://blog.naver.com/tmong2/1002</link>
      <guid>https://blog.naver.com/tmong2/1002</guid>
      <description>잘린 요약.......</description>
      <pubDate>Wed, 09 Sep 2026 12:00:00 +0900</pubDate>
    </item>
  </channel>
</rss>
"""


class NaverRssTests(unittest.TestCase):
    def test_parses_title_date_url_and_summary_scope(self):
        records = parse_rss(RSS_XML, limit=1)

        self.assertEqual(len(records), 1)
        post = records[0].post
        self.assertEqual(post.title, "첫 번째 글")
        self.assertEqual(post.source_url, "https://blog.naver.com/tmong2/1001")
        self.assertEqual(post.published_at, "2026-09-10T15:02:52+09:00")
        self.assertEqual(post.body, "전체로 보이는 공개 요약")
        self.assertEqual(post.tags, ("기록", "테스트", "원본"))
        self.assertTrue(records[0].body_is_complete)

    def test_limit_and_truncated_body_detection(self):
        records = parse_rss(RSS_XML, limit=2)

        self.assertEqual(len(records), 2)
        self.assertFalse(records[1].body_is_complete)
        self.assertEqual(len(parse_rss(RSS_XML, limit=1)), 1)

    def test_duplicate_posts_use_existing_content_hash(self):
        records = parse_rss(RSS_XML.replace("</channel>", RSS_XML.split("<item>", 2)[1].split("</item>", 1)[0].join(["<item>", "</item>"]) + "</channel>"), limit=3)
        repository = BrainRepository()

        self.assertEqual(repository.add_many([record.post for record in records]), 2)

    def test_invalid_xml_and_limit_are_reported(self):
        with self.assertRaises(NaverRssError):
            parse_rss("<rss>", limit=10)
        with self.assertRaises(ValueError):
            parse_rss(RSS_XML, limit=0)


if __name__ == "__main__":
    unittest.main()