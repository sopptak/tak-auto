import tempfile
from pathlib import Path
import unittest

from blog_importer.naver_post import NaverPostError, find_frame_url, parse_public_post, parse_public_post_file


OUTER_HTML = """
<html><head><title>블로그 프레임셋</title></head>
<body><iframe id="mainFrame" src="/PostView.naver?blogId=tmong2&amp;logNo=1"></iframe></body></html>
"""

FRAME_HTML = """
<html><head><title>테스트 게시물 : 네이버 블로그</title></head>
<body><div class="se-view"><span class="se_publishdate pcol2">2026. 09. 10.</span>
<div class="se-main-container"><p>본문 첫 문장</p><p>본문 둘째 문장</p></div></div></body></html>
"""


class NaverPostTests(unittest.TestCase):
    def test_parse_public_post_extracts_title_date_and_body(self):
        result = parse_public_post(FRAME_HTML, "https://blog.naver.com/PostView.naver")

        self.assertEqual(result.title, "테스트 게시물 : 네이버 블로그")
        self.assertEqual(result.published_at, "2026. 09. 10.")
        self.assertEqual(result.body, "본문 첫 문장 본문 둘째 문장")
        self.assertIsNone(result.frame_url)

    def test_public_frame_url_is_identified_without_fetching(self):
        frame_url = find_frame_url(OUTER_HTML, "https://blog.naver.com/tmong2/1")

        self.assertEqual(frame_url, "https://blog.naver.com/PostView.naver?blogId=tmong2&logNo=1")

    def test_missing_body_is_reported(self):
        with self.assertRaises(NaverPostError):
            parse_public_post("<title>제목</title>", "https://blog.naver.com/1")

    def test_file_parser_does_not_require_network(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "post.html"
            path.write_text(FRAME_HTML, encoding="utf-8")

            result = parse_public_post_file(path, "https://blog.naver.com/PostView.naver")

            self.assertEqual(len(result.body), 16)


if __name__ == "__main__":
    unittest.main()