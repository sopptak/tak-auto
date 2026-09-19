"""tak_scout/interview_llm.py의 InterviewLLMProvider 테스트(5-10 Phase 3-1).

실제 네트워크는 어떤 테스트에서도 호출하지 않는다:
    - 대부분의 테스트는 transport를 fake 함수로 주입해 HTTP 계층 자체를 우회한다.
    - _http_transport(기본 production transport)만 검증하는 테스트는
      urllib.request.urlopen을 unittest.mock으로 패치해 소켓을 열지 않는다.
"""

from __future__ import annotations

from collections.abc import Mapping
from unittest import mock
import io
import json
import unittest
from urllib.error import HTTPError, URLError

from content_engine import LLMConfigurationError

from tak_scout.interview_llm import (
    FollowUpDecision,
    InterviewLLMProvider,
    _http_transport,
)
from tak_scout.interview_session import InterviewTurnRecord
from tak_scout.models import ScoutCandidate


def _make_candidate(**overrides) -> ScoutCandidate:
    defaults = dict(
        scout_id="scout-llm-test-1",
        title="AI 개발 속도를 늦춰야 한다는 주장이 나왔다",
        summary="AI 모델이 전 세계에 심각한 피해를 줄 수 있다는 우려가 커지고 있다.",
        source_url="https://example.invalid/news/ai-slowdown",
        published_at="2026-09-12T21:16:47+00:00",
        source_name="BBC Business",
        category="finance",
    )
    defaults.update(overrides)
    return ScoutCandidate(**defaults)


def _chat_response(content: dict) -> dict:
    return {"choices": [{"message": {"content": json.dumps(content, ensure_ascii=False)}}]}


def _fake_transport(*, response: Mapping | None = None, error: Exception | None = None, calls: list | None = None):
    def transport(endpoint, headers, payload, timeout_seconds):
        if calls is not None:
            calls.append(
                {
                    "endpoint": endpoint,
                    "headers": dict(headers),
                    "payload": payload,
                    "timeout_seconds": timeout_seconds,
                }
            )
        if error is not None:
            raise error
        return response

    return transport


VALID_TURN1_CONTENT = {
    "question": "AI를 직접 활용해보면서 느낀 점이 있나요?",
    "option_a": "있다, 업무에 직접 활용해봤다",
    "option_b": "아직 써본 적은 없다",
    "option_c": "간접적으로만 접해봤다",
    "option_d": "직접 입력",
}


class InterviewLLMProviderEnvironmentTests(unittest.TestCase):
    def test_from_environment_success(self):
        environ = {
            "TAK_MEDIA_LLM_API_KEY": "TEST_SECRET_KEY_123",
            "TAK_MEDIA_LLM_ENDPOINT": "https://example.invalid/v1/chat/completions",
            "TAK_MEDIA_LLM_MODEL": "test-model",
        }
        provider = InterviewLLMProvider.from_environment(environ=environ, transport=_fake_transport())

        self.assertEqual(provider.api_key, "TEST_SECRET_KEY_123")
        self.assertEqual(provider.endpoint, "https://example.invalid/v1/chat/completions")
        self.assertEqual(provider.model, "test-model")

    def test_from_environment_missing_api_key(self):
        environ = {
            "TAK_MEDIA_LLM_ENDPOINT": "https://example.invalid/v1/chat/completions",
            "TAK_MEDIA_LLM_MODEL": "test-model",
        }
        with self.assertRaises(LLMConfigurationError):
            InterviewLLMProvider.from_environment(environ=environ)

    def test_from_environment_missing_endpoint(self):
        environ = {
            "TAK_MEDIA_LLM_API_KEY": "TEST_SECRET_KEY_123",
            "TAK_MEDIA_LLM_MODEL": "test-model",
        }
        with self.assertRaises(LLMConfigurationError):
            InterviewLLMProvider.from_environment(environ=environ)

    def test_from_environment_missing_model(self):
        environ = {
            "TAK_MEDIA_LLM_API_KEY": "TEST_SECRET_KEY_123",
            "TAK_MEDIA_LLM_ENDPOINT": "https://example.invalid/v1/chat/completions",
        }
        with self.assertRaises(LLMConfigurationError):
            InterviewLLMProvider.from_environment(environ=environ)


class GenerateFirstQuestionTests(unittest.TestCase):
    def _provider(self, **transport_kwargs) -> tuple[InterviewLLMProvider, list]:
        calls: list = []
        transport = _fake_transport(calls=calls, **transport_kwargs)
        provider = InterviewLLMProvider(
            endpoint="https://example.invalid/v1/chat/completions",
            api_key="TEST_SECRET_KEY_123",
            model="test-model",
            transport=transport,
        )
        return provider, calls

    def test_success_returns_turn_one(self):
        provider, calls = self._provider(response=_chat_response(VALID_TURN1_CONTENT))
        candidate = _make_candidate()

        turn = provider.generate_first_question(candidate, "AI 모델이 전 세계에 심각한 피해를 줄 수 있다는 우려가 커지고 있다.")

        self.assertIsInstance(turn, InterviewTurnRecord)
        self.assertEqual(turn.turn, 1)
        self.assertEqual(turn.question, VALID_TURN1_CONTENT["question"])
        self.assertEqual(turn.option_a, VALID_TURN1_CONTENT["option_a"])
        self.assertEqual(len(calls), 1)  # 정확히 1회만 호출(재시도 없음)

    def test_generated_by_is_llm(self):
        provider, _ = self._provider(response=_chat_response(VALID_TURN1_CONTENT))
        turn = provider.generate_first_question(_make_candidate(), "source fact")
        self.assertEqual(turn.generated_by, "llm")

    def test_option_d_is_always_forced_to_direct_input(self):
        tampered = {**VALID_TURN1_CONTENT, "option_d": "그만 물어봐"}
        provider, _ = self._provider(response=_chat_response(tampered))
        turn = provider.generate_first_question(_make_candidate(), "source fact")
        self.assertEqual(turn.option_d, "직접 입력")

    def test_malformed_json_returns_none(self):
        response = {"choices": [{"message": {"content": "이것은 JSON이 아닙니다"}}]}
        provider, _ = self._provider(response=response)
        self.assertIsNone(provider.generate_first_question(_make_candidate(), "source fact"))

    def test_missing_required_field_returns_none(self):
        broken = {k: v for k, v in VALID_TURN1_CONTENT.items() if k != "option_b"}
        provider, _ = self._provider(response=_chat_response(broken))
        self.assertIsNone(provider.generate_first_question(_make_candidate(), "source fact"))

    def test_empty_question_returns_none(self):
        broken = {**VALID_TURN1_CONTENT, "question": "   "}
        provider, _ = self._provider(response=_chat_response(broken))
        self.assertIsNone(provider.generate_first_question(_make_candidate(), "source fact"))

    def test_duplicate_options_returns_none(self):
        broken = {**VALID_TURN1_CONTENT, "option_b": VALID_TURN1_CONTENT["option_a"]}
        provider, _ = self._provider(response=_chat_response(broken))
        self.assertIsNone(provider.generate_first_question(_make_candidate(), "source fact"))

    def test_question_too_long_returns_none(self):
        broken = {**VALID_TURN1_CONTENT, "question": "가" * 201}
        provider, _ = self._provider(response=_chat_response(broken))
        self.assertIsNone(provider.generate_first_question(_make_candidate(), "source fact"))

    def test_option_too_long_returns_none(self):
        broken = {**VALID_TURN1_CONTENT, "option_a": "가" * 81}
        provider, _ = self._provider(response=_chat_response(broken))
        self.assertIsNone(provider.generate_first_question(_make_candidate(), "source fact"))

    def test_http_error_returns_none(self):
        provider, calls = self._provider(error=RuntimeError("HTTP 500 Internal Server Error"))
        self.assertIsNone(provider.generate_first_question(_make_candidate(), "source fact"))
        self.assertEqual(len(calls), 1)

    def test_timeout_returns_none(self):
        provider, _ = self._provider(error=TimeoutError("timed out"))
        self.assertIsNone(provider.generate_first_question(_make_candidate(), "source fact"))

    def test_source_fact_and_user_answers_are_separated_in_request(self):
        provider, calls = self._provider(response=_chat_response(VALID_TURN1_CONTENT))
        candidate = _make_candidate()
        source_fact = "AI 모델이 전 세계에 심각한 피해를 줄 수 있다는 우려가 커지고 있다."

        provider.generate_first_question(candidate, source_fact)

        sent_body = json.loads(calls[0]["payload"]["messages"][1]["content"])
        self.assertEqual(sent_body["scout"]["source_fact"], source_fact)
        self.assertEqual(sent_body["scout"]["title"], candidate.title)
        self.assertEqual(sent_body["previous_turns"], [])
        self.assertEqual(sent_body["current_turn_number"], 1)
        self.assertEqual(sent_body["contract_version"], "tak-interview-v1")

    def test_request_uses_chat_completions_shape(self):
        provider, calls = self._provider(response=_chat_response(VALID_TURN1_CONTENT))
        provider.generate_first_question(_make_candidate(), "source fact")

        payload = calls[0]["payload"]
        self.assertEqual(payload["model"], "test-model")
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertEqual(payload["messages"][0]["role"], "system")
        self.assertEqual(payload["messages"][1]["role"], "user")
        self.assertEqual(calls[0]["headers"]["Authorization"], "Bearer TEST_SECRET_KEY_123")


class DecideNextTurnTests(unittest.TestCase):
    def _provider(self, **transport_kwargs) -> tuple[InterviewLLMProvider, list]:
        calls: list = []
        transport = _fake_transport(calls=calls, **transport_kwargs)
        provider = InterviewLLMProvider(
            endpoint="https://example.invalid/v1/chat/completions",
            api_key="TEST_SECRET_KEY_123",
            model="test-model",
            transport=transport,
        )
        return provider, calls

    def _turn1_answered(self, custom_answer: str = "신기술은 두려워 말고 부딪혀서 느껴봐야 한다.") -> InterviewTurnRecord:
        return InterviewTurnRecord(
            turn=1,
            question="이 소재에 대해 어떻게 생각하시나요?",
            option_a="긍정적으로 본다",
            option_b="부정적으로 본다",
            option_c="아직 판단하기 어렵다",
            option_d="직접 입력",
            generated_by="template",
            selected_option="D",
            custom_answer=custom_answer,
            answered_at="2026-09-15T00:00:00+00:00",
        )

    def test_sufficient_false_returns_next_turn(self):
        content = {
            "sufficient": False,
            "question": "실제로 AI를 사용하면서 비슷하게 느낀 경험이 있나요?",
            "option_a": "있다, 직접 활용해봤다",
            "option_b": "아직 없다",
            "option_c": "간접적으로만 접했다",
            "option_d": "직접 입력",
            "perspective_summary": "신기술을 두려워하지 않고 직접 경험해야 한다는 입장",
        }
        provider, _ = self._provider(response=_chat_response(content))
        decision = provider.decide_next_turn(_make_candidate(), "source fact", (self._turn1_answered(),))

        self.assertIsInstance(decision, FollowUpDecision)
        self.assertFalse(decision.sufficient)
        self.assertIsNotNone(decision.next_turn)
        self.assertEqual(decision.next_turn.turn, 2)
        self.assertEqual(decision.next_turn.generated_by, "llm")
        self.assertEqual(decision.next_turn.question, content["question"])
        self.assertEqual(decision.perspective_summary, content["perspective_summary"])

    def test_sufficient_true_returns_no_next_turn(self):
        content = {"sufficient": True, "perspective_summary": "신기술을 직접 경험해야 한다는 입장"}
        provider, _ = self._provider(response=_chat_response(content))
        decision = provider.decide_next_turn(_make_candidate(), "source fact", (self._turn1_answered(),))

        self.assertTrue(decision.sufficient)
        self.assertIsNone(decision.next_turn)
        self.assertEqual(decision.perspective_summary, content["perspective_summary"])

    def test_option_d_is_always_forced_even_when_tampered(self):
        content = {
            "sufficient": False,
            "question": "질문",
            "option_a": "가",
            "option_b": "나",
            "option_c": "다",
            "option_d": "그만 물어봐",
            "perspective_summary": "요약",
        }
        provider, _ = self._provider(response=_chat_response(content))
        decision = provider.decide_next_turn(_make_candidate(), "source fact", (self._turn1_answered(),))
        self.assertEqual(decision.next_turn.option_d, "직접 입력")

    def test_malformed_json_returns_none(self):
        response = {"choices": [{"message": {"content": "not json"}}]}
        provider, _ = self._provider(response=response)
        self.assertIsNone(provider.decide_next_turn(_make_candidate(), "source fact", (self._turn1_answered(),)))

    def test_sufficient_wrong_type_returns_none(self):
        content = {"sufficient": "true", "perspective_summary": "요약"}
        provider, _ = self._provider(response=_chat_response(content))
        self.assertIsNone(provider.decide_next_turn(_make_candidate(), "source fact", (self._turn1_answered(),)))

    def test_missing_perspective_summary_returns_none(self):
        content = {"sufficient": True}
        provider, _ = self._provider(response=_chat_response(content))
        self.assertIsNone(provider.decide_next_turn(_make_candidate(), "source fact", (self._turn1_answered(),)))

    def test_missing_question_field_when_insufficient_returns_none(self):
        content = {
            "sufficient": False,
            "option_a": "가",
            "option_b": "나",
            "option_c": "다",
            "perspective_summary": "요약",
        }
        provider, _ = self._provider(response=_chat_response(content))
        self.assertIsNone(provider.decide_next_turn(_make_candidate(), "source fact", (self._turn1_answered(),)))

    def test_duplicate_options_returns_none(self):
        content = {
            "sufficient": False,
            "question": "질문",
            "option_a": "같음",
            "option_b": "같음",
            "option_c": "다름",
            "perspective_summary": "요약",
        }
        provider, _ = self._provider(response=_chat_response(content))
        self.assertIsNone(provider.decide_next_turn(_make_candidate(), "source fact", (self._turn1_answered(),)))

    def test_question_too_long_returns_none(self):
        content = {
            "sufficient": False,
            "question": "가" * 201,
            "option_a": "가",
            "option_b": "나",
            "option_c": "다",
            "perspective_summary": "요약",
        }
        provider, _ = self._provider(response=_chat_response(content))
        self.assertIsNone(provider.decide_next_turn(_make_candidate(), "source fact", (self._turn1_answered(),)))

    def test_http_error_returns_none(self):
        provider, _ = self._provider(error=RuntimeError("HTTP 500 Internal Server Error"))
        self.assertIsNone(provider.decide_next_turn(_make_candidate(), "source fact", (self._turn1_answered(),)))

    def test_timeout_returns_none(self):
        provider, _ = self._provider(error=TimeoutError("timed out"))
        self.assertIsNone(provider.decide_next_turn(_make_candidate(), "source fact", (self._turn1_answered(),)))

    def test_custom_answer_original_text_passed_through_unchanged(self):
        custom_answer = "특수문자 테스트!! \n두 번째 줄\t탭 포함 — 그대로 보존되어야 한다."
        content = {"sufficient": True, "perspective_summary": "요약"}
        provider, calls = self._provider(response=_chat_response(content))

        provider.decide_next_turn(_make_candidate(), "source fact", (self._turn1_answered(custom_answer),))

        sent_body = json.loads(calls[0]["payload"]["messages"][1]["content"])
        self.assertEqual(sent_body["previous_turns"][0]["user_answer_text"], custom_answer)
        self.assertEqual(sent_body["previous_turns"][0]["selected_option"], "D")

    def test_source_fact_kept_separate_from_previous_turn_answers(self):
        content = {"sufficient": True, "perspective_summary": "요약"}
        provider, calls = self._provider(response=_chat_response(content))
        source_fact = "이것은 기사에서 확인된 사실입니다."

        provider.decide_next_turn(_make_candidate(), source_fact, (self._turn1_answered(),))

        sent_body = json.loads(calls[0]["payload"]["messages"][1]["content"])
        self.assertEqual(sent_body["scout"]["source_fact"], source_fact)
        # previous_turns 안에는 source_fact 텍스트가 섞여 들어가지 않는다.
        self.assertNotIn(source_fact, sent_body["previous_turns"][0]["user_answer_text"])

    def test_current_turn_number_reflects_answered_turn_count(self):
        content = {"sufficient": True, "perspective_summary": "요약"}
        provider, calls = self._provider(response=_chat_response(content))

        provider.decide_next_turn(_make_candidate(), "source fact", (self._turn1_answered(),))

        sent_body = json.loads(calls[0]["payload"]["messages"][1]["content"])
        self.assertEqual(sent_body["current_turn_number"], 2)
        self.assertEqual(sent_body["max_turns"], 3)

    def test_exactly_one_http_call_no_retry(self):
        content = {"sufficient": True, "perspective_summary": "요약"}
        provider, calls = self._provider(response=_chat_response(content))
        provider.decide_next_turn(_make_candidate(), "source fact", (self._turn1_answered(),))
        self.assertEqual(len(calls), 1)


class TranslateTitlesTests(unittest.TestCase):
    """5-20: InterviewLLMProvider.translate_titles() - SCOUT 후보 제목의 한국어
    표시용 번역(Dashboard 표시 전용, SCOUT SCORE/후보 선정 로직과는 무관)."""

    JP_MORGAN_TITLE = (
        "We simply don't know - JP Morgan struggling to forecast oil prices due to Trump's war with Iran"
    )
    JP_MORGAN_TITLE_KO = "정말 알 수 없다 — JP모건, 이란 전쟁으로 유가 전망에 어려움"

    def _provider(self, **transport_kwargs) -> tuple[InterviewLLMProvider, list]:
        calls: list = []
        transport = _fake_transport(calls=calls, **transport_kwargs)
        provider = InterviewLLMProvider(
            endpoint="https://example.invalid/v1/chat/completions",
            api_key="TEST_SECRET_KEY_123",
            model="test-model",
            transport=transport,
        )
        return provider, calls

    def test_success_translates_real_sample_title(self):
        content = {"translations": {"scout-jpmorgan-1": self.JP_MORGAN_TITLE_KO}}
        provider, _ = self._provider(response=_chat_response(content))

        result = provider.translate_titles((("scout-jpmorgan-1", self.JP_MORGAN_TITLE),))

        self.assertEqual(result, {"scout-jpmorgan-1": self.JP_MORGAN_TITLE_KO})

    def test_empty_titles_returns_empty_dict_without_calling_llm(self):
        provider, calls = self._provider(response={})
        result = provider.translate_titles(())
        self.assertEqual(result, {})
        self.assertEqual(calls, [])

    def test_batch_of_multiple_titles_in_one_call(self):
        content = {
            "translations": {
                "scout-a": "한국어 제목 A",
                "scout-b": "한국어 제목 B",
            }
        }
        provider, calls = self._provider(response=_chat_response(content))

        result = provider.translate_titles((("scout-a", "Title A"), ("scout-b", "Title B")))

        self.assertEqual(result, {"scout-a": "한국어 제목 A", "scout-b": "한국어 제목 B"})
        self.assertEqual(len(calls), 1)  # 후보 2건이어도 HTTP 호출은 1번뿐.

    def test_missing_scout_id_in_response_is_simply_absent(self):
        """일부 scout_id의 번역이 응답에 없으면 그 항목만 결과에서 빠진다(부분 실패)."""
        content = {"translations": {"scout-a": "한국어 제목 A"}}
        provider, _ = self._provider(response=_chat_response(content))

        result = provider.translate_titles((("scout-a", "Title A"), ("scout-b", "Title B")))

        self.assertEqual(result, {"scout-a": "한국어 제목 A"})
        self.assertNotIn("scout-b", result)

    def test_unrequested_scout_id_in_response_is_ignored(self):
        content = {"translations": {"scout-a": "한국어 제목 A", "scout-not-requested": "엉뚱한 항목"}}
        provider, _ = self._provider(response=_chat_response(content))

        result = provider.translate_titles((("scout-a", "Title A"),))

        self.assertEqual(result, {"scout-a": "한국어 제목 A"})

    def test_empty_translation_value_is_skipped(self):
        content = {"translations": {"scout-a": "   "}}
        provider, _ = self._provider(response=_chat_response(content))
        result = provider.translate_titles((("scout-a", "Title A"),))
        self.assertEqual(result, {})

    def test_translation_too_long_is_skipped(self):
        content = {"translations": {"scout-a": "가" * 121}}
        provider, _ = self._provider(response=_chat_response(content))
        result = provider.translate_titles((("scout-a", "Title A"),))
        self.assertEqual(result, {})

    def test_malformed_json_returns_none(self):
        response = {"choices": [{"message": {"content": "not json"}}]}
        provider, _ = self._provider(response=response)
        self.assertIsNone(provider.translate_titles((("scout-a", "Title A"),)))

    def test_translations_wrong_type_returns_none(self):
        content = {"translations": "not a dict"}
        provider, _ = self._provider(response=_chat_response(content))
        self.assertIsNone(provider.translate_titles((("scout-a", "Title A"),)))

    def test_http_error_returns_none(self):
        provider, _ = self._provider(error=RuntimeError("HTTP 500 Internal Server Error"))
        self.assertIsNone(provider.translate_titles((("scout-a", "Title A"),)))

    def test_timeout_returns_none(self):
        provider, _ = self._provider(error=TimeoutError("timed out"))
        self.assertIsNone(provider.translate_titles((("scout-a", "Title A"),)))

    def test_source_titles_sent_unmodified_in_request(self):
        content = {"translations": {"scout-jpmorgan-1": self.JP_MORGAN_TITLE_KO}}
        provider, calls = self._provider(response=_chat_response(content))

        provider.translate_titles((("scout-jpmorgan-1", self.JP_MORGAN_TITLE),))

        sent_body = json.loads(calls[0]["payload"]["messages"][1]["content"])
        self.assertEqual(sent_body["titles"], [{"scout_id": "scout-jpmorgan-1", "title": self.JP_MORGAN_TITLE}])

    def test_exactly_one_http_call_no_retry(self):
        content = {"translations": {"scout-a": "한국어 제목"}}
        provider, calls = self._provider(response=_chat_response(content))
        provider.translate_titles((("scout-a", "Title A"),))
        self.assertEqual(len(calls), 1)


class DefaultHttpTransportTests(unittest.TestCase):
    """production 기본 transport(_http_transport) 자체를 검증한다.

    urllib.request.urlopen을 mock으로 패치하므로 실제 네트워크는 열리지 않는다.
    """

    def test_posts_json_body_with_expected_headers(self):
        fake_response = mock.MagicMock()
        fake_response.read.return_value = json.dumps(_chat_response(VALID_TURN1_CONTENT)).encode("utf-8")
        fake_response.__enter__.return_value = fake_response
        fake_response.__exit__.return_value = False

        with mock.patch("tak_scout.interview_llm.urlopen", return_value=fake_response) as mock_urlopen:
            result = _http_transport(
                "https://example.invalid/v1/chat/completions",
                {"Authorization": "Bearer TEST_SECRET_KEY_123", "Content-Type": "application/json"},
                {"model": "test-model", "messages": []},
                20.0,
            )

        self.assertEqual(result, _chat_response(VALID_TURN1_CONTENT))
        sent_request = mock_urlopen.call_args.args[0]
        self.assertEqual(sent_request.get_method(), "POST")
        self.assertEqual(sent_request.get_header("Authorization"), "Bearer TEST_SECRET_KEY_123")
        sent_payload = json.loads(sent_request.data.decode("utf-8"))
        self.assertEqual(sent_payload["model"], "test-model")

    def test_http_error_message_never_leaks_api_key(self):
        error_body = json.dumps(
            {
                "error": {
                    "message": "Rate limited",
                    "type": "rate_limit_error",
                    # message/type/code/param 외의 필드는 절대 노출되지 않아야 한다.
                    "debug_request_headers": "Authorization: Bearer TEST_SECRET_KEY_123",
                }
            }
        ).encode("utf-8")
        http_error = HTTPError(
            url="https://example.invalid/v1/chat/completions",
            code=429,
            msg="Too Many Requests",
            hdrs=None,
            fp=io.BytesIO(error_body),
        )

        with mock.patch("tak_scout.interview_llm.urlopen", side_effect=http_error):
            with self.assertRaises(Exception) as ctx:
                _http_transport(
                    "https://example.invalid/v1/chat/completions",
                    {"Authorization": "Bearer TEST_SECRET_KEY_123"},
                    {"model": "test-model", "messages": []},
                    20.0,
                )

        message = str(ctx.exception)
        self.assertNotIn("TEST_SECRET_KEY_123", message)
        self.assertIn("Rate limited", message)

    def test_connection_failure_returns_safe_message(self):
        with mock.patch("tak_scout.interview_llm.urlopen", side_effect=URLError("Connection refused")):
            with self.assertRaises(Exception) as ctx:
                _http_transport(
                    "https://example.invalid/v1/chat/completions",
                    {"Authorization": "Bearer TEST_SECRET_KEY_123"},
                    {"model": "test-model", "messages": []},
                    20.0,
                )
        self.assertNotIn("TEST_SECRET_KEY_123", str(ctx.exception))

    def test_timeout_returns_safe_message(self):
        with mock.patch("tak_scout.interview_llm.urlopen", side_effect=TimeoutError("timed out")):
            with self.assertRaises(Exception) as ctx:
                _http_transport(
                    "https://example.invalid/v1/chat/completions",
                    {"Authorization": "Bearer TEST_SECRET_KEY_123"},
                    {"model": "test-model", "messages": []},
                    20.0,
                )
        self.assertNotIn("TEST_SECRET_KEY_123", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
