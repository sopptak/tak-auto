"""scripts/youtube_oauth_setup.py 검증(6-26).

이 스크립트는 실제 OAuth 인증을 수행하지 않는다 - 이 테스트도 실제
Google 인증/네트워크를 절대 시도하지 않는다. ``environ`` 딕셔너리를 직접
주입해 실제 ``os.environ``/실제 네트워크와 완전히 격리한다.
"""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout

import scripts.youtube_oauth_setup as oauth_setup


class CheckEnvironmentTests(unittest.TestCase):
    def test_all_missing_reports_false_for_each(self) -> None:
        presence = oauth_setup.check_environment({})
        self.assertEqual(
            presence,
            {"YOUTUBE_CLIENT_ID": False, "YOUTUBE_CLIENT_SECRET": False, "YOUTUBE_REFRESH_TOKEN": False},
        )

    def test_all_present_reports_true_for_each(self) -> None:
        presence = oauth_setup.check_environment(
            {
                "YOUTUBE_CLIENT_ID": "fake-client-id",
                "YOUTUBE_CLIENT_SECRET": "fake-secret",
                "YOUTUBE_REFRESH_TOKEN": "fake-refresh-token",
            }
        )
        self.assertTrue(all(presence.values()))

    def test_whitespace_only_value_counts_as_missing(self) -> None:
        presence = oauth_setup.check_environment(
            {"YOUTUBE_CLIENT_ID": "   ", "YOUTUBE_CLIENT_SECRET": "x", "YOUTUBE_REFRESH_TOKEN": "y"}
        )
        self.assertFalse(presence["YOUTUBE_CLIENT_ID"])

    def test_partial_presence_is_reported_accurately(self) -> None:
        presence = oauth_setup.check_environment(
            {"YOUTUBE_CLIENT_ID": "id-only"}
        )
        self.assertTrue(presence["YOUTUBE_CLIENT_ID"])
        self.assertFalse(presence["YOUTUBE_CLIENT_SECRET"])
        self.assertFalse(presence["YOUTUBE_REFRESH_TOKEN"])


class RunCheckTests(unittest.TestCase):
    def test_missing_all_returns_exit_1_and_never_prints_values(self) -> None:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = oauth_setup.run_check({})
        output = buffer.getvalue()

        self.assertEqual(exit_code, 1)
        self.assertIn("MISSING", output)
        self.assertNotIn("SET", output.replace("MISSING", ""))  # SET이 등장하면 안 됨(전부 MISSING)

    def test_present_credentials_return_exit_0_and_client_initializes(self) -> None:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = oauth_setup.run_check(
                {
                    "YOUTUBE_CLIENT_ID": "fake-client-id",
                    "YOUTUBE_CLIENT_SECRET": "fake-secret",
                    "YOUTUBE_REFRESH_TOKEN": "fake-refresh-token",
                }
            )
        output = buffer.getvalue()

        self.assertEqual(exit_code, 0)
        self.assertIn("SET", output)
        self.assertIn("API client 초기화 가능: YES", output)

    def test_fake_credential_values_never_appear_in_output(self) -> None:
        """--check는 값 존재 여부만 보여줘야 한다 - 실제 값(여기서는 가짜 값이지만
        같은 원칙 검증)이 출력에 그대로 노출되면 안 된다."""
        buffer = io.StringIO()
        secret_value = "super-secret-value-should-not-leak"
        with redirect_stdout(buffer):
            oauth_setup.run_check(
                {
                    "YOUTUBE_CLIENT_ID": secret_value,
                    "YOUTUBE_CLIENT_SECRET": secret_value,
                    "YOUTUBE_REFRESH_TOKEN": secret_value,
                }
            )
        self.assertNotIn(secret_value, buffer.getvalue())

    def test_partial_missing_reports_exit_1_with_missing_names(self) -> None:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = oauth_setup.run_check({"YOUTUBE_CLIENT_ID": "id-only"})
        output = buffer.getvalue()

        self.assertEqual(exit_code, 1)
        self.assertIn("YOUTUBE_CLIENT_SECRET", output)
        self.assertIn("YOUTUBE_REFRESH_TOKEN", output)


class MainCliTests(unittest.TestCase):
    def test_no_args_prints_setup_guide_and_does_not_touch_real_environment(self) -> None:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = oauth_setup.main([])
        output = buffer.getvalue()

        self.assertEqual(exit_code, 0)
        self.assertIn("YouTube OAuth 최초 설정 절차", output)
        self.assertIn("OAuth 2.0 Playground", output)

    def test_check_flag_never_performs_network_or_browser_flow(self) -> None:
        """--check 코드 경로 어디에도 브라우저 실행/urlopen 호출이 없는지 소스
        레벨로 확인한다(실제 네트워크 호출 금지 요구사항의 회귀 보증)."""
        import scripts.youtube_oauth_setup as module
        from pathlib import Path

        source = Path(module.__file__).read_text(encoding="utf-8")
        self.assertNotIn("urlopen", source)
        self.assertNotIn("webbrowser", source)
        self.assertNotIn("input(", source)  # 대화형 프롬프트도 없어야 한다(스크립트 자동화 가능해야 함)


if __name__ == "__main__":
    unittest.main()
