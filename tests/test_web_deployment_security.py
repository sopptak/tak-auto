"""Hosted web MVP deployment safety checks."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class HostedDashboardSecurityTests(unittest.TestCase):
    def test_get_and_post_require_authentication(self):
        source = (ROOT / "scripts" / "run_scout_dashboard.py").read_text(encoding="utf-8")
        self.assertIn('def _require_web_auth(self)', source)
        self.assertIn('if not self._require_web_auth():', source)
        self.assertEqual(source.count('if not self._require_web_auth():'), 2)

    def test_external_bind_without_credentials_fails_closed(self):
        source = (ROOT / "scripts" / "run_scout_dashboard.py").read_text(encoding="utf-8")
        self.assertIn('TAK_WEB_USERNAME', source)
        self.assertIn('TAK_WEB_PASSWORD', source)
        self.assertIn('Web authentication is not configured.', source)
        self.assertIn('WWW-Authenticate', source)

    def test_post_actions_reject_missing_or_cross_origin_origin_header(self):
        source = (ROOT / "scripts" / "run_scout_dashboard.py").read_text(encoding="utf-8")
        post = source.index("def do_POST")
        section = source[post:post + 1800]
        self.assertIn('origin = self.headers.get("Origin", "")', section)
        self.assertIn('request_host = self.headers.get("Host", "")', section)
        self.assertIn('if not origin or urlparse(origin).netloc.lower() != request_host.lower():', section)
        self.assertIn('self.send_response(403)', section)

    def test_health_endpoint_is_public_and_minimal(self):
        source = (ROOT / "scripts" / "run_scout_dashboard.py").read_text(encoding="utf-8")
        health = source.index('if parsed.path == "/health":')
        auth = source.index('if not self._require_web_auth():', health)
        self.assertLess(health, auth)
        self.assertIn('self.wfile.write(b"ok")', source[health:auth])

    def test_hosted_root_redirects_to_trends(self):
        config = (ROOT / "render.yaml").read_text(encoding="utf-8")
        source = (ROOT / "scripts" / "run_scout_dashboard.py").read_text(encoding="utf-8")
        self.assertIn("TAK_WEB_LANDING_PATH", config)
        self.assertIn('os.environ.get("TAK_WEB_LANDING_PATH"', source)
        self.assertIn('self._redirect("/trends")', source)

    def test_hosted_service_disables_local_browser_agent(self):
        config = (ROOT / "render.yaml").read_text(encoding="utf-8")
        source = (ROOT / "scripts" / "run_scout_dashboard.py").read_text(encoding="utf-8")
        self.assertIn("TAK_DISABLE_MONEY_SCOUT_AGENT", config)
        self.assertIn('os.environ.get("TAK_DISABLE_MONEY_SCOUT_AGENT"', source)

    def test_render_reuses_persisted_scout_data_after_restart(self):
        config = (ROOT / "render.yaml").read_text(encoding="utf-8")
        self.assertIn("if [ -s data/tak_auto_trend_daily.json ]; then", config)
        self.assertIn("--skip-collect --host 0.0.0.0", config)
        self.assertIn("else", config)

    def test_render_blueprint_uses_persistent_disk_and_secrets(self):
        config = (ROOT / "render.yaml").read_text(encoding="utf-8")
        for required in ("mountPath: /var/data", "sizeGB: 1", "TAK_WEB_USERNAME", "TAK_WEB_PASSWORD", "healthCheckPath: /health"):
            self.assertIn(required, config)
        self.assertIn("ln -sfn /var/data data", config)


if __name__ == "__main__":
    unittest.main()
