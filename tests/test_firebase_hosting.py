"""Firebase Hosting 정적 홈페이지/개인정보처리방침 페이지 검증.

이 테스트는 Google OAuth 동의 화면에 쓸 "애플리케이션 홈페이지"와
"개인정보처리방침" 두 URL이 실제로 열리는지 로컬에서 확인한다. 실제 Firebase
배포나 네트워크 호출은 하지 않는다 - public/ 디렉터리를 로컬 HTTP 서버로 직접
서빙해 firebase.json의 cleanUrls 규칙(확장자 없는 경로 -> 같은 이름의 .html 파일)을
그대로 재현해서 검증한다 (tests/test_scout_dashboard.py의
ThreadingHTTPServer + 실제 소켓 패턴을 따른다).
"""

from __future__ import annotations

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import unittest
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DIR = ROOT / "public"
INDEX_HTML = PUBLIC_DIR / "index.html"
PRIVACY_HTML = PUBLIC_DIR / "privacy.html"
FIREBASE_JSON = ROOT / "firebase.json"
FIREBASERC = ROOT / ".firebaserc"


class CleanUrlHandler(SimpleHTTPRequestHandler):
    """firebase.json의 cleanUrls: true 규칙(경로에 확장자가 없으면 .html을 찾는다)을
    로컬에서 재현하는 최소한의 핸들러. 테스트 전용이며 배포 코드가 아니다."""

    def do_GET(self):  # noqa: N802 (http.server 관례)
        path_only = self.path.split("?", 1)[0]
        if path_only != "/" and "." not in path_only.rsplit("/", 1)[-1]:
            candidate = Path(self.directory) / (path_only.lstrip("/") + ".html")
            if candidate.is_file():
                self.path = path_only + ".html"
        return super().do_GET()

    def log_message(self, format, *args):  # noqa: A002 (http.server 시그니처)
        pass


class FileExistenceTests(unittest.TestCase):
    def test_index_html_exists(self):
        self.assertTrue(INDEX_HTML.is_file(), f"홈페이지 파일이 없습니다: {INDEX_HTML}")

    def test_privacy_html_exists(self):
        self.assertTrue(PRIVACY_HTML.is_file(), f"개인정보처리방침 파일이 없습니다: {PRIVACY_HTML}")

    def test_firebase_config_files_exist(self):
        self.assertTrue(FIREBASE_JSON.is_file())
        self.assertTrue(FIREBASERC.is_file())


class FirebaseConfigTests(unittest.TestCase):
    def test_firebase_json_points_to_public_directory_with_clean_urls(self):
        config = json.loads(FIREBASE_JSON.read_text(encoding="utf-8"))
        hosting = config.get("hosting", {})
        self.assertEqual(hosting.get("public"), "public")
        self.assertTrue(hosting.get("cleanUrls"))

    def test_firebaserc_points_to_expected_project(self):
        config = json.loads(FIREBASERC.read_text(encoding="utf-8"))
        self.assertEqual(config.get("projects", {}).get("default"), "tmong-golf-diary")


class IndexPageContentTests(unittest.TestCase):
    def setUp(self):
        self.html = INDEX_HTML.read_text(encoding="utf-8")

    def test_has_mobile_viewport_meta(self):
        self.assertIn('name="viewport"', self.html)

    def test_has_doctype_and_title(self):
        self.assertIn("<!DOCTYPE html>", self.html)
        self.assertIn("<title>티몽의 지혜</title>", self.html)

    def test_has_brand_and_description(self):
        self.assertIn("티몽의 지혜", self.html)
        self.assertIn(
            "AI를 활용해 콘텐츠를 만들고 관리하는 개인 콘텐츠 자동화 프로젝트입니다.", self.html
        )

    def test_has_required_bullet_points(self):
        for item in ["콘텐츠 기획", "정보 및 지식 정리", "YouTube Shorts 콘텐츠 제작", "콘텐츠 자동 게시 및 관리"]:
            self.assertIn(item, self.html)

    def test_links_to_privacy_page(self):
        self.assertIn('href="/privacy"', self.html)


class PrivacyPageContentTests(unittest.TestCase):
    def setUp(self):
        self.html = PRIVACY_HTML.read_text(encoding="utf-8")

    def test_has_mobile_viewport_meta(self):
        self.assertIn('name="viewport"', self.html)

    def test_covers_oauth_usage(self):
        self.assertIn("Google OAuth 2.0", self.html)

    def test_covers_upload_permission_scope(self):
        self.assertIn("업로드", self.html)
        self.assertIn("권한", self.html)

    def test_covers_secure_credential_handling(self):
        self.assertIn("안전하게 관리", self.html)

    def test_covers_no_public_repo_storage_of_tokens(self):
        self.assertIn("Access Token", self.html)
        self.assertIn("Refresh Token", self.html)
        self.assertIn("공개 저장소", self.html)

    def test_covers_revocation_instructions(self):
        self.assertIn("철회", self.html)
        self.assertIn("myaccount.google.com/permissions", self.html)

    def test_covers_youtube_api_usage(self):
        self.assertIn("YouTube Data API", self.html)

    def test_does_not_falsely_claim_unrelated_data_collection(self):
        # 실제로 하지 않는 것(로그인/회원가입/광고추적/분석쿠키)을 한다고 거짓 기재하지 않는다.
        self.assertIn("운영하지 않으며", self.html)

    def test_has_contact_email(self):
        self.assertIn("mygolfdiary01@gmail.com", self.html)
        self.assertIn("mailto:mygolfdiary01@gmail.com", self.html)


class LocalServerAccessTests(unittest.TestCase):
    """firebase.json의 cleanUrls 규칙을 재현한 로컬 서버로 두 URL이 실제로 열리는지 확인한다."""

    def setUp(self):
        handler_class = partial(CleanUrlHandler, directory=str(PUBLIC_DIR))
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler_class)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._shutdown)

    def _shutdown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _get(self, path: str) -> tuple[int, str]:
        url = f"http://127.0.0.1:{self.port}{path}"
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status, response.read().decode("utf-8")

    def test_homepage_opens_at_root(self):
        status, body = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn("티몽의 지혜", body)

    def test_privacy_page_opens_at_clean_url(self):
        status, body = self._get("/privacy")
        self.assertEqual(status, 200)
        self.assertIn("개인정보처리방침", body)


if __name__ == "__main__":
    unittest.main()
