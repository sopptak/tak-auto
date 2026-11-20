import base64
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import json
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
import re
import tempfile
import threading
from types import SimpleNamespace
import unittest
from urllib.error import HTTPError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
from unittest.mock import patch

from content_engine.publishing_queue import PublishUncertainError, PublishingQueue
from scripts import run_trend_content_mvp as app


class MediaAssetRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.data_dir = Path(self.temp_dir.name)
        self.environment = patch.dict("os.environ", {
            "TAK_WEB_USERNAME": "operator",
            "TAK_WEB_PASSWORD": "strong-test-password",
            "TAK_AUTO_MEDIA_SIGNING_KEY": "test-signing-key-that-is-at-least-32-chars",
            "TAK_AUTO_PUBLIC_URL": "https://tak-auto.example.test",
        }, clear=False)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.data_dir_patch = patch.object(app, "DATA_DIR", self.data_dir)
        self.data_dir_patch.start()
        self.addCleanup(self.data_dir_patch.stop)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), app.create_handler())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._stop_server)
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.auth = "Basic " + base64.b64encode(b"operator:strong-test-password").decode("ascii")

    def _stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def _upload(self, *, authorization=True, origin="https://tak-auto.example.test",
                content_type="video/mp4", body=None):
        payload = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 128 if body is None else body
        headers = {
            "Content-Type": content_type,
            "Content-Length": str(len(payload)),
            "Origin": origin,
            "X-Asset-Filename": "approved.mp4",
        }
        if authorization:
            headers["Authorization"] = self.auth
        request = Request(self.base_url + "/media/assets/upload", data=payload, headers=headers, method="POST")
        return payload, request

    def test_closing_unpublished_requires_auth_same_origin_and_confirmation(self):
        path = self.data_dir / "queue.json"
        queue = PublishingQueue(path)
        now = datetime.now(timezone.utc)
        item = queue.enqueue_approved(
            content_id="review-job", platform="threads", payload={"body": "문안"},
            scheduled_at=now + timedelta(seconds=10), approved_by="operator", now=now,
        )

        def uncertain(*_args):
            raise PublishUncertainError("response lost")

        queue.run_due(uncertain, enabled=True, now=now + timedelta(seconds=11))

        def post(confirmed="yes", *, auth=self.auth, origin="https://tak-auto.example.test"):
            headers = {"Origin": origin, "Content-Type": "application/x-www-form-urlencoded"}
            if auth:
                headers["Authorization"] = auth
            data = urlencode({"item_id": item["id"], "confirmed_unpublished": confirmed}).encode()
            request = Request(self.base_url + "/queue/close-unpublished", data=data, headers=headers)
            with urlopen(request, timeout=5) as response:
                return response.status

        with patch.object(app, "QUEUE_PATH", path), patch.object(app, "TREND_PATH", self.data_dir / "trends.json"), \
                patch.object(app, "PREVIEW_PATH", self.data_dir / "previews.json"):
            for expected, kwargs in ((401, {"auth": ""}), (403, {"origin": "https://wrong.example.test"}),
                                     (400, {"confirmed": ""})):
                with self.subTest(expected=expected), self.assertRaises(HTTPError) as caught:
                    post(**kwargs)
                self.assertEqual(caught.exception.code, expected)
                caught.exception.close()
                self.assertEqual(queue.snapshot()["items"][0]["status"], "needs_review")
            self.assertEqual(post(), 200)

        saved = queue.snapshot()["items"][0]
        self.assertEqual(saved["status"], "rejected")
        self.assertEqual(saved["last_review"]["reviewed_by"], "operator")

    def test_authenticated_upload_and_signed_public_get_work_end_to_end(self):
        payload, request = self._upload()
        with urlopen(request, timeout=5) as response:
            result = json.loads(response.read().decode("utf-8"))
            self.assertEqual(response.status, 200)
        self.assertEqual(result["filename"], "approved.mp4")
        self.assertEqual(result["size_bytes"], len(payload))
        signed_url = app._media_asset_store().signed_url(result["asset_id"])
        parsed = urlparse(signed_url)
        public_request = Request(self.base_url + parsed.path + "?" + parsed.query)
        with urlopen(public_request, timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers.get("Content-Type"), "video/mp4")
            self.assertEqual(response.read(), payload)

    def test_dashboard_uses_a_nonce_scoped_script_policy(self):
        request = Request(self.base_url + "/", headers={"Authorization": self.auth})
        with urlopen(request, timeout=5) as response:
            policy = response.headers.get("Content-Security-Policy", "")
            permissions_policy = response.headers.get("Permissions-Policy", "")
            body = response.read().decode("utf-8")
        nonce_match = re.search(r"script-src 'nonce-([^']+)'", policy)
        self.assertIsNotNone(nonce_match)
        self.assertIn(f'<script nonce="{nonce_match.group(1)}">', body)
        self.assertIn("object-src 'none'", policy)
        self.assertIn("base-uri 'none'", policy)
        self.assertNotIn("script-src 'unsafe-inline'", policy)
        self.assertEqual(permissions_policy, "camera=(), geolocation=(), microphone=()")
        second_request = Request(self.base_url + "/", headers={"Authorization": self.auth})
        with urlopen(second_request, timeout=5) as response:
            second_policy = response.headers.get("Content-Security-Policy", "")
        second_nonce_match = re.search(r"script-src 'nonce-([^']+)'", second_policy)
        self.assertIsNotNone(second_nonce_match)
        self.assertNotEqual(nonce_match.group(1), second_nonce_match.group(1))

    def test_concurrent_ai_action_is_rejected_before_a_second_provider_call(self):
        provider_started = threading.Event()
        release_provider = threading.Event()
        provider_calls = []

        def discover(provider):
            provider_calls.append(provider)
            provider_started.set()
            if not release_provider.wait(timeout=5):
                raise TimeoutError("test provider release timed out")
            return SimpleNamespace(to_dict=lambda: {"trends": []})

        with ExitStack() as stack:
            stack.enter_context(patch.object(app, "TREND_PATH", self.data_dir / "trends.json"))
            stack.enter_context(patch.object(app, "PREVIEW_PATH", self.data_dir / "previews.json"))
            stack.enter_context(patch.object(app, "QUEUE_PATH", self.data_dir / "queue.json"))
            stack.enter_context(patch.object(app.PerplexityResearchProvider, "from_environment", return_value=object()))
            stack.enter_context(patch.object(app, "discover_trends", side_effect=discover))
            stack.enter_context(patch.object(app, "_page", side_effect=lambda report, previews, error="", *args, **kwargs: error or "ok"))

            def post_discover():
                connection = HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=5)
                connection.request("POST", "/discover", body=b"", headers={
                    "Authorization": self.auth,
                    "Origin": "https://tak-auto.example.test",
                    "Host": f"127.0.0.1:{self.server.server_address[1]}",
                    "X-Forwarded-Proto": "http",
                    "Content-Type": "application/x-www-form-urlencoded",
                })
                response = connection.getresponse()
                result = response.status, response.read().decode("utf-8")
                connection.close()
                return result

            first_result = []
            first_request = threading.Thread(target=lambda: first_result.append(post_discover()), daemon=True)
            first_request.start()
            try:
                self.assertTrue(provider_started.wait(timeout=3))
                duplicate_status, duplicate_body = post_discover()
                self.assertEqual(duplicate_status, 429)
                self.assertIn("다른 AI 요청이 진행 중입니다", duplicate_body)
            finally:
                release_provider.set()
                first_request.join(timeout=5)
            self.assertFalse(first_request.is_alive())
            self.assertEqual(first_result[0][0], 200)
            self.assertEqual(len(provider_calls), 1)
            retry_status, _ = post_discover()
            self.assertEqual(retry_status, 200)
            self.assertEqual(len(provider_calls), 2)

    def test_signed_public_media_supports_http_range_requests(self):
        _, request = self._upload()
        with urlopen(request, timeout=5) as response:
            asset_id = json.loads(response.read().decode("utf-8"))["asset_id"]
        parsed = urlparse(app._media_asset_store().signed_url(asset_id))
        ranged = Request(
            self.base_url + parsed.path + "?" + parsed.query,
            headers={"Range": "bytes=0-7"},
        )
        with urlopen(ranged, timeout=5) as response:
            self.assertEqual(response.status, 206)
            self.assertEqual(response.headers.get("Content-Range").split(" ")[0], "bytes")
            self.assertEqual(len(response.read()), 8)

    def test_upload_requires_basic_auth_and_same_origin(self):
        # Keep rejected requests bodyless because the server intentionally closes
        # the connection before reading an unauthorized upload body.
        _, unauthorized = self._upload(authorization=False, body=b"")
        with self.assertRaises(HTTPError) as auth_error:
            urlopen(unauthorized, timeout=5)
        self.assertEqual(auth_error.exception.code, 401)
        _, cross_origin = self._upload(origin="https://attacker.example", body=b"")
        with self.assertRaises(HTTPError) as origin_error:
            urlopen(cross_origin, timeout=5)
        self.assertEqual(origin_error.exception.code, 403)

    def test_upload_rejects_wrong_content_type(self):
        # This route rejects the content type before reading the body. Keep this
        # negative request bodyless so Windows does not reset the loopback socket
        # while the server closes a connection with unread upload bytes.
        _, request = self._upload(content_type="application/octet-stream", body=b"")
        with self.assertRaises(HTTPError) as error:
            urlopen(request, timeout=5)
        self.assertEqual(error.exception.code, 415)

    def test_public_media_url_rejects_tampered_signature(self):
        _, request = self._upload()
        with urlopen(request, timeout=5) as response:
            asset_id = json.loads(response.read().decode("utf-8"))["asset_id"]
        parsed = urlparse(app._media_asset_store().signed_url(asset_id))
        tampered_query = parsed.query.replace("signature=", "signature=0")
        tampered = Request(self.base_url + parsed.path + "?" + tampered_query)
        with self.assertRaises(HTTPError) as error:
            urlopen(tampered, timeout=5)
        self.assertEqual(error.exception.code, 403)


if __name__ == "__main__":
    unittest.main()
