import base64
import json
from http.server import ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from unittest.mock import patch

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
                content_type="video/mp4"):
        payload = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 128
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
        _, unauthorized = self._upload(authorization=False)
        with self.assertRaises(HTTPError) as auth_error:
            urlopen(unauthorized, timeout=5)
        self.assertEqual(auth_error.exception.code, 401)
        _, cross_origin = self._upload(origin="https://attacker.example")
        with self.assertRaises(HTTPError) as origin_error:
            urlopen(cross_origin, timeout=5)
        self.assertEqual(origin_error.exception.code, 403)

    def test_upload_rejects_wrong_content_type(self):
        _, request = self._upload(content_type="application/octet-stream")
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
