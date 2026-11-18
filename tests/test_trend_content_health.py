import unittest
from unittest.mock import patch

from scripts.run_trend_content_mvp import _health_payload


class TrendContentHealthTests(unittest.TestCase):
    def test_readiness_requires_persistent_storage(self):
        environ = {
            "TAK_SCOUT_PERPLEXITY_API_KEY": "configured",
            "TAK_WEB_USERNAME": "operator",
            "TAK_WEB_PASSWORD": "configured",
            "TAK_AUTO_PUBLISHING_ENABLED": "false",
        }
        with patch("scripts.run_trend_content_mvp.USING_EPHEMERAL_STORAGE", True):
            payload = _health_payload(environ)
        self.assertEqual(payload["status"], "ok")
        self.assertFalse(payload["storage_persistent"])
        self.assertEqual(payload["storage_mode"], "ephemeral_fallback")
        self.assertFalse(payload["ready"])

    def test_readiness_requires_publisher_adapter_when_publishing_is_enabled(self):
        environ = {
            "TAK_SCOUT_PERPLEXITY_API_KEY": "configured",
            "TAK_WEB_USERNAME": "operator",
            "TAK_WEB_PASSWORD": "configured",
            "TAK_AUTO_PUBLISHING_ENABLED": "true",
        }
        with patch("scripts.run_trend_content_mvp.USING_EPHEMERAL_STORAGE", False):
            without_adapter = _health_payload(environ)
            with_adapter = _health_payload({**environ, "TAK_AUTO_PUBLISHER": "content_engine.trend_publishers:publish"})
        self.assertTrue(without_adapter["storage_persistent"])
        self.assertFalse(without_adapter["publisher_adapter_configured"])
        self.assertFalse(without_adapter["ready"])
        self.assertTrue(with_adapter["publisher_adapter_configured"])
        self.assertTrue(with_adapter["ready"])

    def test_disabled_publishing_does_not_require_publisher_adapter(self):
        environ = {
            "TAK_SCOUT_PERPLEXITY_API_KEY": "configured",
            "TAK_WEB_USERNAME": "operator",
            "TAK_WEB_PASSWORD": "configured",
            "TAK_AUTO_PUBLISHING_ENABLED": "false",
        }
        with patch("scripts.run_trend_content_mvp.USING_EPHEMERAL_STORAGE", False):
            payload = _health_payload(environ)
        self.assertTrue(payload["storage_persistent"])
        self.assertFalse(payload["publisher_adapter_configured"])
        self.assertTrue(payload["ready"])


if __name__ == "__main__":
    unittest.main()
