import base64
import json
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from scripts import run_trend_content_mvp as app


class PublishingQueueAuditRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "queue.json"
        for context in (
            patch.object(app, "QUEUE_PATH", self.path),
            patch.dict("os.environ", {"TAK_WEB_USERNAME": "operator", "TAK_WEB_PASSWORD": "test-password"}),
        ):
            context.start()
            self.addCleanup(context.stop)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), app.create_handler())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)
        self.auth = "Basic " + base64.b64encode(b"operator:test-password").decode("ascii")

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def get(self, path, *, authenticated=True):
        connection = HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=5)
        try:
            connection.request("GET", path, headers={"Authorization": self.auth} if authenticated else {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read().decode("utf-8")
        finally:
            connection.close()

    def test_both_diagnostic_routes_require_auth_before_reading_queue(self):
        with patch.object(app, "audit_queue_file") as audit:
            for path in ("/queue/diagnostics", "/queue/diagnostics.json"):
                with self.subTest(path=path):
                    status, headers, _ = self.get(path, authenticated=False)
                    self.assertEqual(status, 401)
                    self.assertEqual(headers["Cache-Control"], "no-store")
            audit.assert_not_called()

    def test_corrupt_queue_still_has_a_safe_read_only_diagnostic_page(self):
        original = b'{"private-token":"secret-sentinel",'
        self.path.write_bytes(original)
        before = set(self.path.parent.iterdir())
        with patch.object(app, "_read_json", side_effect=AssertionError("unrelated state must not be loaded")):
            status, headers, body = self.get("/queue/diagnostics")
        self.assertEqual(status, 200)
        self.assertIn("문제 해결 필요", body)
        self.assertIn("JSON 형식", body)
        self.assertNotIn("secret-sentinel", body)
        self.assertNotIn(str(self.path), body)
        self.assertNotIn("<script", body)
        self.assertIn("script-src 'none'", headers["Content-Security-Policy"])
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(set(self.path.parent.iterdir()), before)

    def test_json_report_works_without_creating_missing_queue(self):
        status, headers, body = self.get("/queue/diagnostics.json")
        self.assertEqual(status, 200)
        self.assertIn("application/json", headers["Content-Type"])
        report = json.loads(body)
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["findings"][0]["code"], "queue_missing")
        self.assertEqual(list(self.path.parent.iterdir()), [])

    def test_empty_valid_queue_renders_success_and_navigation(self):
        self.path.write_text(json.dumps({"version": 1, "items": [], "history": []}), encoding="utf-8")
        status, _, body = self.get("/queue/diagnostics")
        self.assertEqual(status, 200)
        self.assertIn("검사 통과", body)
        self.assertIn('href="/"', body)
        self.assertIn('href="/queue/diagnostics.json"', body)
        self.assertIn("별도로 확인", body)

    def test_unicode_login_returns_success_or_401_without_breaking_connection(self):
        self.auth = "Basic " + base64.b64encode("운영자:비밀번호🔒".encode("utf-8")).decode("ascii")
        status, _, _ = self.get("/queue/diagnostics")
        self.assertEqual(status, 401)
        with patch.dict("os.environ", {"TAK_WEB_USERNAME": "운영자", "TAK_WEB_PASSWORD": "비밀번호🔒"}):
            status, _, body = self.get("/queue/diagnostics")
        self.assertEqual(status, 200)
        self.assertIn("대기열 파일이 없습니다", body)

    def test_dashboard_recovers_with_diagnostics_when_queue_is_corrupt(self):
        for original in (b'{"secret-sentinel":', b"\xff", b'{"version":1,"items":[null],"history":[]}'):
            with self.subTest(original=original):
                self.path.write_bytes(original)
                with patch.object(app, "_read_json", side_effect=[{}, []]):
                    status, _, body = self.get("/")
                self.assertEqual(status, 503)
                self.assertIn("문제 해결 필요", body)
                self.assertIn('href="/queue/diagnostics"', body)
                self.assertNotIn("secret-sentinel", body)
                self.assertEqual(self.path.read_bytes(), original)

    def test_dashboard_blocks_malformed_items_before_rendering_actions(self):
        self.path.write_text(json.dumps({"version": 1, "items": [{"status": "scheduled", "scheduled_at": []}], "history": []}), encoding="utf-8")
        with patch.object(app, "_read_json", side_effect=[{}, []]), patch.object(app, "_page") as dashboard:
            status, _, body = self.get("/")
        self.assertEqual(status, 503)
        self.assertIn("명시적인 사람의 승인", body)
        dashboard.assert_not_called()


if __name__ == "__main__":
    unittest.main()
