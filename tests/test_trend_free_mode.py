import unittest
from unittest.mock import patch
from scripts import run_trend_content_mvp as app
from scripts.check_trend_factory_deployment import validate_health


class FreeModeTests(unittest.TestCase):
    def test_free_mode_blocks_paid_provider_even_with_key(self):
        with patch.dict("os.environ", {"TAK_AUTO_FREE_MODE": "true", "TAK_SCOUT_PERPLEXITY_API_KEY": "unused"}), patch.object(app.PerplexityResearchProvider, "from_environment") as provider:
            with self.assertRaises(ValueError):
                app._paid_research_provider()
            provider.assert_not_called()

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

    def test_free_http_flow_and_paid_route_guards(self):
        import tempfile
        import threading
        from pathlib import Path
        from datetime import datetime, timedelta
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
                    provider.assert_not_called()
                    self.assertFalse(app._health_payload()["publishing_enabled"])
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=2)
