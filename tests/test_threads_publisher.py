from io import BytesIO
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from urllib.error import HTTPError

from content_engine.threads_publisher import (
    DEFAULT_INSIGHTS_METRICS,
    ThreadsAPIError,
    ThreadsClient,
    ThreadsConfigurationError,
    ThreadsProfile,
    ThreadsPublishResult,
    _default_http_transport,
)


class ThreadsPublisherTests(unittest.TestCase):
    def test_empty_token_raises_configuration_error(self):
        with self.assertRaises(ThreadsConfigurationError):
            ThreadsClient.from_environment({"THREADS_ACCESS_TOKEN": ""})

        with self.assertRaises(ThreadsConfigurationError):
            ThreadsClient.from_environment({})

    def test_client_created_from_environment(self):
        client = ThreadsClient.from_environment(
            {
                "THREADS_ACCESS_TOKEN": "test-secret-token",
                "THREADS_API_BASE": "https://graph.threads.net/v1.0",
            }
        )

        self.assertEqual(client.access_token, "test-secret-token")
        self.assertEqual(client.api_base, "https://graph.threads.net/v1.0")

    def test_get_profile_sends_correct_request(self):
        captured = []

        def transport(method, url, headers, payload, timeout):
            captured.append((method, url, headers, payload, timeout))
            return {
                "id": "1234567890",
                "username": "tmong_wisdom",
                "name": "티몽의 지혜",
            }

        client = ThreadsClient(access_token="test-token", transport=transport)
        profile = client.get_profile()

        self.assertIsInstance(profile, ThreadsProfile)
        self.assertEqual(profile.id, "1234567890")
        self.assertEqual(profile.username, "tmong_wisdom")
        self.assertEqual(profile.name, "티몽의 지혜")

        self.assertEqual(len(captured), 1)
        method, url, headers, payload, timeout = captured[0]
        self.assertEqual(method, "GET")
        self.assertIn("/me?", url)
        self.assertIn("fields=id%2Cusername%2Cname", url)
        self.assertEqual(headers["Authorization"], "Bearer test-token")
        self.assertIsNone(payload)

    def test_publish_text_sends_correct_payload(self):
        captured = []

        def transport(method, url, headers, payload, timeout):
            captured.append((method, url, headers, payload, timeout))
            return {"id": "th_post_99999"}

        client = ThreadsClient(access_token="test-token", transport=transport)
        result = client.publish_text(
            "코딩을 몰라도 일단 시작하라. 만들면서 배우면 된다.",
            reply_control="everyone",
            topic_tag="자기계발",
        )

        self.assertIsInstance(result, ThreadsPublishResult)
        self.assertEqual(result.id, "th_post_99999")

        self.assertEqual(len(captured), 1)
        method, url, headers, payload, timeout = captured[0]
        self.assertEqual(method, "POST")
        self.assertEqual(url, "https://graph.threads.net/me/threads")
        self.assertEqual(headers["Authorization"], "Bearer test-token")
        self.assertIsNotNone(payload)
        self.assertEqual(payload["media_type"], "TEXT")
        self.assertEqual(payload["auto_publish_text"], "true")
        self.assertEqual(payload["text"], "코딩을 몰라도 일단 시작하라. 만들면서 배우면 된다.")
        self.assertEqual(payload["reply_control"], "everyone")
        self.assertEqual(payload["topic_tag"], "자기계발")

    def test_empty_or_whitespace_text_raises_value_error(self):
        client = ThreadsClient(access_token="test-token")

        with self.assertRaises(ValueError):
            client.publish_text("")

        with self.assertRaises(ValueError):
            client.publish_text("   \n\t  ")

    def test_publish_text_exceeding_500_chars_raises_value_error(self):
        client = ThreadsClient(access_token="test-token")
        long_text = "가" * 501

        with self.assertRaises(ValueError) as ctx:
            client.publish_text(long_text)

        self.assertIn("Threads text exceeds 500 characters: 501", str(ctx.exception))

    def test_token_is_not_exposed_in_api_error_messages(self):
        token = "SECRET_SUPER_SENSITIVE_TOKEN_12345"
        error_body = BytesIO(
            json.dumps(
                {
                    "error": {
                        "message": "Invalid OAuth access token",
                        "type": "OAuthException",
                        "code": 190,
                        "error_subcode": 463,
                        "fbtrace_id": "AbCdEf123456",
                    }
                }
            ).encode("utf-8")
        )

        with mock.patch(
            "content_engine.threads_publisher.urlopen",
            side_effect=HTTPError("https://graph.threads.net/me", 401, "Unauthorized", {}, error_body),
        ):
            with self.assertRaises(ThreadsAPIError) as raised:
                _default_http_transport(
                    "GET",
                    "https://graph.threads.net/me?fields=id,username",
                    {"Authorization": f"Bearer {token}"},
                    None,
                    30.0,
                )

        error_msg = str(raised.exception)
        self.assertIn("Threads HTTP 401", error_msg)
        self.assertIn("Invalid OAuth access token", error_msg)
        self.assertIn("OAuthException", error_msg)
        self.assertIn("code=190", error_msg)
        self.assertNotIn(token, error_msg)

    def test_missing_id_in_publish_response_raises_api_error(self):
        def transport(method, url, headers, payload, timeout):
            return {"status": "ok"}  # 'id' missing

        client = ThreadsClient(access_token="test-token", transport=transport)
        with self.assertRaises(ThreadsAPIError) as raised:
            client.publish_text("테스트 본문")
        self.assertIn("게시물 id가 누락", str(raised.exception))

    def test_cli_dry_run_executes_without_network_or_token(self):
        sample_batch_data = {
            "all_items": [
                {
                    "platform": "blog",
                    "status": "valid",
                    "rewritten_body": "블로그 본문",
                },
                {
                    "knowledge_id": "k-001",
                    "platform": "threads",
                    "status": "valid",
                    "source_url": "https://example.test/source",
                    "original_title": "원본 스레드 제목",
                    "original_body": "원본 스레드 본문",
                    "rewritten_title": "재작성 스레드 제목",
                    "rewritten_body": "스레드 1인칭 본문 내용입니다.",
                },
            ]
        }

        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as tmp_file:
            json.dump(sample_batch_data, tmp_file, ensure_ascii=False)
            tmp_path = tmp_file.name

        script = Path(__file__).parents[1] / "scripts" / "publish_threads.py"

        try:
            result = subprocess.run(
                [sys.executable, str(script), "--input", tmp_path, "--index", "1", "--dry-run"],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertIn("TAK MEDIA Threads Publish (Dry-run)", result.stdout)
            self.assertIn("선택 항목: [1/1]", result.stdout)
            self.assertIn("스레드 1인칭 본문 내용입니다.", result.stdout)
            self.assertIn("네트워크 호출 없음", result.stdout)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_cli_rejects_out_of_range_index(self):
        sample_batch_data = {
            "all_items": [
                {
                    "knowledge_id": "k-001",
                    "platform": "threads",
                    "status": "valid",
                    "rewritten_body": "스레드 본문",
                }
            ]
        }
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as tmp_file:
            json.dump(sample_batch_data, tmp_file, ensure_ascii=False)
            tmp_path = tmp_file.name

        script = Path(__file__).parents[1] / "scripts" / "publish_threads.py"

        try:
            result = subprocess.run(
                [sys.executable, str(script), "--input", tmp_path, "--index", "5", "--dry-run"],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("유효하지 않은 index", result.stderr)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_cli_rejects_threads_text_exceeding_500_chars(self):
        sample_batch_data = {
            "all_items": [
                {
                    "knowledge_id": "k-001",
                    "platform": "threads",
                    "status": "valid",
                    "rewritten_body": "가" * 501,
                }
            ]
        }
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as tmp_file:
            json.dump(sample_batch_data, tmp_file, ensure_ascii=False)
            tmp_path = tmp_file.name

        script = Path(__file__).parents[1] / "scripts" / "publish_threads.py"

        try:
            result = subprocess.run(
                [sys.executable, str(script), "--input", tmp_path, "--index", "1", "--dry-run"],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Threads text exceeds 500 characters: 501", result.stderr)
        finally:
            Path(tmp_path).unlink(missing_ok=True)


class ThreadsMediaInsightsTests(unittest.TestCase):
    """6-01: ThreadsClient.get_media_insights() - 성과 수집용 신규 메서드.
    기존 publish_text()/get_profile()과 동일한 transport 주입 패턴이라 실제
    네트워크를 전혀 호출하지 않고 검증한다."""

    def test_get_media_insights_sends_correct_request(self):
        captured = []

        def transport(method, url, headers, payload, timeout):
            captured.append((method, url, headers, payload, timeout))
            return {
                "data": [
                    {"name": "views", "values": [{"value": 120}]},
                    {"name": "likes", "values": [{"value": 8}]},
                ]
            }

        client = ThreadsClient(access_token="test-token", transport=transport)
        response = client.get_media_insights("media-123")

        self.assertEqual(len(captured), 1)
        method, url, headers, payload, _timeout = captured[0]
        self.assertEqual(method, "GET")
        self.assertIn("media-123/insights", url)
        self.assertIn("metric=" + "%2C".join(DEFAULT_INSIGHTS_METRICS), url)
        self.assertIsNone(payload)
        self.assertEqual(headers["Authorization"], "Bearer test-token")
        self.assertEqual(response["data"][0]["name"], "views")

    def test_get_media_insights_accepts_custom_metrics(self):
        captured = []

        def transport(method, url, headers, payload, timeout):
            captured.append(url)
            return {"data": []}

        client = ThreadsClient(access_token="test-token", transport=transport)
        client.get_media_insights("media-123", metrics=("views", "likes"))

        self.assertIn("metric=views%2Clikes", captured[0])

    def test_get_media_insights_requires_media_id(self):
        client = ThreadsClient(access_token="test-token", transport=lambda *a: {"data": []})
        with self.assertRaises(ValueError):
            client.get_media_insights("")


if __name__ == "__main__":
    unittest.main()
