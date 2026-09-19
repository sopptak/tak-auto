"""TAK SCOUT 멀티턴 인터뷰의 선택적 LLM provider(5-10 Phase 3-1).

이 모듈은 오직 "LLM 인터뷰 provider 자체"만 담당한다. Dashboard
(scripts/run_scout_dashboard.py)는 이 단계에서 이 모듈을 아직 참조하지 않는다 -
연결은 Phase 3-2에서 한다(docs/5-10_phase3_llm_design.md 15번 구현 순서).

content_engine.OpenAICompatibleRewriteProvider와의 관계(재확인 - 설계 문서 2번):
    - RewriteProvider도, OpenAICompatibleRewriteProvider도 상속하지 않는다.
      RewriteProvider의 계약은 ContentDraft + KnowledgeRecord -> ContentDraft이고,
      인터뷰 질문 생성 시점에는 이 두 값이 아직 존재하지 않는다(순서가 반대).
    - content_engine/llm_provider.py의 HTTP 호출 코드를 import하거나 그대로
      복사하지 않는다. 이 파일 안에 독립적인 최소 HTTP 호출 코드를 새로 쓴다
      (약 20~30줄 규모의 POST 호출 1개를 위해 공용 계층을 뽑아내는 것은 이번
      규모에서 과도한 추상화라고 판단했다 - 설계 문서 2-2번).
    - 재사용하는 것은 딱 세 가지뿐이다: 환경변수 이름(TAK_MEDIA_LLM_*)과
      content_engine.LLMConfigurationError/LLMResponseError 예외 클래스.
      content_engine 파일은 한 줄도 수정하지 않는다.

두 공개 메서드(generate_first_question, decide_next_turn)는 절대 예외를 밖으로
던지지 않는다. 내부에서 모든 실패(설정 오류 제외, HTTP 오류, timeout, JSON 파싱
오류, 응답 구조 오류, 필수 필드 누락, 길이 초과, 중복 선택지 등)를 잡아 None을
반환한다 - 호출부는 기존 템플릿 fallback으로 대체하기만 하면 된다.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from content_engine import LLMConfigurationError, LLMResponseError

from .interview_session import InterviewTurnRecord
from .models import ScoutCandidate


CONTRACT_VERSION = "tak-interview-v1"
MAX_TURNS = 3

# option_d는 LLM이 무엇을 응답하든 서버가 항상 이 값으로 덮어쓴다(설계 문서 6, 8번).
# 사용자의 직접 입력 경로를 LLM이 절대 변조할 수 없게 하는 안전장치다.
FORCED_OPTION_D = "직접 입력"

MAX_QUESTION_LENGTH = 200
MAX_OPTION_LENGTH = 80

# Dashboard 표시용 한국어 제목 번역(5-20)에 쓰는 상한. 카드 제목이 너무 길어지지
# 않도록 인터뷰 질문/선택지와 비슷한 수준으로 제한한다.
MAX_TITLE_LENGTH = 120

InterviewLLMTransport = Callable[[str, Mapping[str, str], Mapping[str, object], float], Mapping[str, object]]


@dataclass(frozen=True)
class FollowUpDecision:
    """decide_next_turn()의 결과. sufficient=False일 때만 next_turn을 채운다."""

    sufficient: bool
    next_turn: InterviewTurnRecord | None
    perspective_summary: str


def _safe_http_error_message(error: HTTPError) -> str:
    """HTTP 오류 본문에서 허용된 OpenAI 오류 필드만 노출한다(API key는 절대 포함하지 않는다).

    content_engine/llm_provider.py의 같은 이름 함수와 동일한 관례를 따르되, 이
    파일은 content_engine을 import하지 않으므로 독립적으로 다시 작성했다.
    """
    details = []
    try:
        payload = json.loads(error.read().decode("utf-8"))
        error_data = payload.get("error", {}) if isinstance(payload, dict) else {}
        if isinstance(error_data, dict):
            for field_name in ("message", "type", "code", "param"):
                value = error_data.get(field_name)
                if isinstance(value, str) and value:
                    details.append(f"{field_name}={value}")
    except (UnicodeDecodeError, json.JSONDecodeError, OSError):
        pass
    detail_text = "; ".join(details) if details else "OpenAI 오류 필드를 읽을 수 없습니다."
    return f"LLM HTTP {error.code}: {detail_text}"


def _http_transport(
    endpoint: str,
    headers: Mapping[str, str],
    payload: Mapping[str, object],
    timeout_seconds: float,
) -> Mapping[str, object]:
    """urllib 기반 최소 POST 호출. 실제 production에서 쓰는 기본 transport."""
    request = Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=dict(headers),
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            raw_text = response.read().decode("utf-8")
    except HTTPError as error:
        raise LLMResponseError(_safe_http_error_message(error)) from None
    except URLError as error:
        raise LLMResponseError(f"LLM 연결 실패: {error.reason}") from None
    except TimeoutError:
        raise LLMResponseError("LLM 요청이 시간 초과되었습니다.") from None

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as error:
        raise LLMResponseError("LLM 응답이 유효한 JSON이 아닙니다.") from error
    if not isinstance(data, dict):
        raise LLMResponseError("LLM 응답은 JSON 객체여야 합니다.")
    return data


def _turn_answer_text(turn: InterviewTurnRecord) -> str:
    """턴의 답을 텍스트로 바꾼다. D는 사용자가 입력한 원문 그대로(재생성하지 않음).

    scripts/run_scout_dashboard.py의 동명 함수와 의도적으로 동일한 규칙을 쓴다
    (설계 문서 10번). 이 모듈은 그 파일을 import하지 않는 독립 계층이므로, 이
    작은 순수 함수를 여기에도 똑같이 둔다.
    """
    if turn.selected_option == "D":
        return turn.custom_answer
    option_texts = {"A": turn.option_a, "B": turn.option_b, "C": turn.option_c}
    return option_texts.get(turn.selected_option or "", "")


def _scout_payload(candidate: ScoutCandidate, source_fact: str) -> dict[str, str]:
    return {
        "title": candidate.title,
        "source_name": candidate.source_name,
        "source_url": candidate.source_url,
        "category": candidate.category,
        "published_at": candidate.published_at,
        "source_fact": source_fact,
    }


def _validate_question_block(data: Mapping[str, object]) -> tuple[str, str, str, str]:
    """question/option_a/b/c를 방어적으로 검증한다. 실패하면 LLMResponseError."""
    values: dict[str, str] = {}
    for name in ("question", "option_a", "option_b", "option_c"):
        value = data.get(name)
        if not isinstance(value, str) or not value.strip():
            raise LLMResponseError(f"{name}이(가) 비어 있거나 없습니다.")
        values[name] = value

    if len(values["question"]) > MAX_QUESTION_LENGTH:
        raise LLMResponseError(f"question이 {MAX_QUESTION_LENGTH}자를 초과했습니다.")
    for name in ("option_a", "option_b", "option_c"):
        if len(values[name]) > MAX_OPTION_LENGTH:
            raise LLMResponseError(f"{name}이(가) {MAX_OPTION_LENGTH}자를 초과했습니다.")

    if len({values["option_a"], values["option_b"], values["option_c"]}) < 3:
        raise LLMResponseError("option_a/b/c 중 서로 동일한 선택지가 있습니다.")

    return values["question"], values["option_a"], values["option_b"], values["option_c"]


def _parse_json_content(response: Mapping[str, object]) -> dict[str, object]:
    """OpenAI Chat Completions 응답에서 content(JSON 문자열)를 꺼내 파싱한다."""
    try:
        choices = response["choices"]
        content = choices[0]["message"]["content"]  # type: ignore[index]
    except (KeyError, IndexError, TypeError) as error:
        raise LLMResponseError("LLM 응답에 choices[0].message.content가 필요합니다.") from error
    if not isinstance(content, str):
        raise LLMResponseError("LLM 응답 content는 문자열이어야 합니다.")
    try:
        data = json.loads(content)
    except json.JSONDecodeError as error:
        raise LLMResponseError("LLM 응답 content는 유효한 JSON이어야 합니다.") from error
    if not isinstance(data, dict):
        raise LLMResponseError("LLM 응답 JSON은 객체여야 합니다.")
    return data


def _log_error(context: str, error: Exception) -> None:
    """짧은 오류만 stderr에 남긴다. API key는 절대 로그에 남기지 않는다.

    LLMConfigurationError/LLMResponseError는 이 모듈이 스스로 만든, 이미
    안전하게 정제된 메시지만 담고 있으므로 그대로 출력해도 안전하다. 그 외의
    예상치 못한 예외는 타입 이름만 남기고 str(error)는 출력하지 않는다 - 어떤
    경로로도 시크릿이 로그에 섞여 들어갈 여지를 원천 차단한다.
    """
    if isinstance(error, (LLMConfigurationError, LLMResponseError)):
        message = str(error)
    else:
        message = type(error).__name__
    sys.stderr.write(f"[interview_llm] {context} 실패: {message}\n")


@dataclass(frozen=True)
class InterviewLLMProvider:
    """OpenAI 호환 Chat Completions API로 인터뷰 질문/충분성 판단을 생성한다.

    인스턴스 생성만으로는 네트워크를 호출하지 않는다. generate_first_question
    또는 decide_next_turn을 호출할 때만 HTTP 요청이 발생하고, 각 호출은 정확히
    1회의 HTTP 요청만 만든다(재시도 없음).
    """

    endpoint: str
    api_key: str
    model: str
    timeout_seconds: float = 20.0
    transport: InterviewLLMTransport = _http_transport

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
        transport: InterviewLLMTransport = _http_transport,
    ) -> "InterviewLLMProvider":
        values = os.environ if environ is None else environ
        api_key = values.get("TAK_MEDIA_LLM_API_KEY", "")
        endpoint = values.get("TAK_MEDIA_LLM_ENDPOINT", "")
        model = values.get("TAK_MEDIA_LLM_MODEL", "")
        if not api_key:
            raise LLMConfigurationError("TAK_MEDIA_LLM_API_KEY 환경변수가 필요합니다.")
        if not endpoint:
            raise LLMConfigurationError("TAK_MEDIA_LLM_ENDPOINT 환경변수가 필요합니다.")
        if not model:
            raise LLMConfigurationError("TAK_MEDIA_LLM_MODEL 환경변수가 필요합니다.")
        return cls(endpoint=endpoint, api_key=api_key, model=model, transport=transport)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _request_payload(self, system_prompt: str, user_message: str) -> dict[str, object]:
        return {
            "model": self.model,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        }

    def _call(self, system_prompt: str, user_message: str) -> dict[str, object]:
        response = self.transport(
            self.endpoint,
            self._headers(),
            self._request_payload(system_prompt, user_message),
            self.timeout_seconds,
        )
        return _parse_json_content(response)

    # --- Turn 1 ---------------------------------------------------------

    @staticmethod
    def _first_question_system_prompt() -> str:
        return (
            "당신은 TAK SCOUT 인터뷰 진행자입니다. 목표는 뉴스 기사를 요약하는 것이 "
            "아니라 사용자(티몽)의 생각을 끌어내는 것입니다.\n\n"
            "scout.source_fact는 기사에서 확인된 사실이며, 사용자의 의견이 아닙니다. "
            "source_fact로부터 사용자의 생각을 추측하지 마세요.\n\n"
            "사용자가 자신의 경험, 생각, 판단을 직접 말할 수 있는 질문 1개와 A/B/C "
            "선택지를 만드세요. 세 선택지는 서로 뚜렷하게 다른 입장이어야 합니다.\n\n"
            "다음 JSON 형식으로만 응답하세요. 다른 텍스트는 포함하지 마세요:\n"
            '{"question": "...", "option_a": "...", "option_b": "...", '
            '"option_c": "...", "option_d": "직접 입력"}\n\n'
            "question은 200자 이내, option_a/b/c는 각각 80자 이내여야 합니다. "
            "option_d 값은 서버가 항상 \"직접 입력\"으로 대체하므로 어떤 값을 넣어도 "
            "무시됩니다."
        )

    def _first_question_user_message(self, candidate: ScoutCandidate, source_fact: str) -> str:
        payload = {
            "contract_version": CONTRACT_VERSION,
            "scout": _scout_payload(candidate, source_fact),
            "current_turn_number": 1,
            "max_turns": MAX_TURNS,
            "previous_turns": [],
        }
        return json.dumps(payload, ensure_ascii=False)

    def generate_first_question(
        self, candidate: ScoutCandidate, source_fact: str
    ) -> InterviewTurnRecord | None:
        """성공하면 turn=1의 InterviewTurnRecord(generated_by="llm"), 실패하면 None."""
        try:
            data = self._call(
                self._first_question_system_prompt(),
                self._first_question_user_message(candidate, source_fact),
            )
            question, option_a, option_b, option_c = _validate_question_block(data)
        except Exception as error:  # noqa: BLE001 - 의도적으로 모든 실패를 None으로 흡수한다.
            _log_error("generate_first_question", error)
            return None

        return InterviewTurnRecord(
            turn=1,
            question=question,
            option_a=option_a,
            option_b=option_b,
            option_c=option_c,
            option_d=FORCED_OPTION_D,
            generated_by="llm",
            selected_option=None,
            custom_answer="",
            answered_at=None,
        )

    # --- 후속 질문 ---------------------------------------------------------

    @staticmethod
    def _follow_up_system_prompt() -> str:
        return (
            "당신은 TAK SCOUT 인터뷰 진행자입니다. previous_turns[].user_answer_text에 "
            "있는 사용자의 실제 답변만 보고, 사용자의 독자적인 관점을 충분히 "
            "파악했는지 판단하세요.\n\n"
            "scout.source_fact는 기사에서 확인된 사실이며 사용자의 의견이 아닙니다. "
            "사용자의 실제 생각은 previous_turns[].user_answer_text에만 있습니다. "
            "source_fact의 내용을 사용자가 말한 것처럼 다루지 마세요.\n\n"
            "perspective_summary must summarize only the user's actual answers. "
            "Do not add facts, numbers, experiences, claims, or opinions that the "
            "user did not express. The source_fact is article context, not the "
            "user's opinion. (perspective_summary는 previous_turns[].user_answer_text에 "
            "있는 내용만 요약해야 합니다. 사용자가 말하지 않은 경험, 숫자, 사실, "
            "주장, 감정을 새로 추가하지 마세요.)\n\n"
            "충분히 파악했다면 sufficient=true와 perspective_summary만 반환하세요. "
            "충분하지 않다면 sufficient=false와 함께 다음 질문(question, option_a, "
            "option_b, option_c)과 perspective_summary(지금까지 파악한 내용)를 "
            "반환하세요.\n\n"
            "다음 JSON 형식으로만 응답하세요. 다른 텍스트는 포함하지 마세요:\n"
            '{"sufficient": false, "question": "...", "option_a": "...", '
            '"option_b": "...", "option_c": "...", "option_d": "직접 입력", '
            '"perspective_summary": "..."}\n\n'
            "sufficient=true일 때는 question/option_a/b/c를 생략해도 됩니다. "
            "question은 200자 이내, option_a/b/c는 각각 80자 이내여야 합니다. "
            "option_d 값은 서버가 항상 \"직접 입력\"으로 대체하므로 어떤 값을 넣어도 "
            "무시됩니다."
        )

    def _follow_up_user_message(
        self,
        candidate: ScoutCandidate,
        source_fact: str,
        turns_so_far: tuple[InterviewTurnRecord, ...],
    ) -> str:
        previous_turns = [
            {
                "turn": turn.turn,
                "question": turn.question,
                "selected_option": turn.selected_option,
                "user_answer_text": _turn_answer_text(turn),
            }
            for turn in turns_so_far
        ]
        payload = {
            "contract_version": CONTRACT_VERSION,
            "scout": _scout_payload(candidate, source_fact),
            "current_turn_number": len(turns_so_far) + 1,
            "max_turns": MAX_TURNS,
            "previous_turns": previous_turns,
        }
        return json.dumps(payload, ensure_ascii=False)

    def decide_next_turn(
        self,
        candidate: ScoutCandidate,
        source_fact: str,
        turns_so_far: tuple[InterviewTurnRecord, ...],
    ) -> FollowUpDecision | None:
        """성공하면 FollowUpDecision, 실패하면 None(호출부가 fallback 처리)."""
        try:
            data = self._call(
                self._follow_up_system_prompt(),
                self._follow_up_user_message(candidate, source_fact, turns_so_far),
            )

            sufficient = data.get("sufficient")
            if not isinstance(sufficient, bool):
                raise LLMResponseError("sufficient는 boolean이어야 합니다.")

            perspective_summary = data.get("perspective_summary")
            if not isinstance(perspective_summary, str) or not perspective_summary.strip():
                raise LLMResponseError("perspective_summary가 비어 있거나 없습니다.")

            if sufficient:
                return FollowUpDecision(
                    sufficient=True, next_turn=None, perspective_summary=perspective_summary
                )

            question, option_a, option_b, option_c = _validate_question_block(data)
            next_turn = InterviewTurnRecord(
                turn=len(turns_so_far) + 1,
                question=question,
                option_a=option_a,
                option_b=option_b,
                option_c=option_c,
                option_d=FORCED_OPTION_D,
                generated_by="llm",
                selected_option=None,
                custom_answer="",
                answered_at=None,
            )
            return FollowUpDecision(
                sufficient=False, next_turn=next_turn, perspective_summary=perspective_summary
            )
        except Exception as error:  # noqa: BLE001 - 의도적으로 모든 실패를 None으로 흡수한다.
            _log_error("decide_next_turn", error)
            return None

    # --- Dashboard 표시용 한국어 제목 번역(5-20) --------------------------------

    @staticmethod
    def _title_translation_system_prompt() -> str:
        return (
            "당신은 뉴스 제목을 한국어로 옮기는 번역가입니다. 아래 titles 배열의 영어(또는 "
            "다른 외국어) 제목들을 자연스러운 한국어 제목으로 번역하세요. 원문의 의미를 "
            "바꾸거나 새로운 사실을 추가하지 마세요. 이미 한국어인 제목은 그대로 반환하세요. "
            "각 번역은 120자 이내로 간결하게 작성하세요.\n\n"
            "다음 JSON 형식으로만 응답하세요. 다른 텍스트는 포함하지 마세요:\n"
            '{"translations": {"<scout_id>": "<한국어 제목>", ...}}\n\n'
            "요청받은 모든 scout_id에 대해 번역을 반환하세요."
        )

    @staticmethod
    def _title_translation_user_message(titles: tuple[tuple[str, str], ...]) -> str:
        payload = {
            "contract_version": CONTRACT_VERSION,
            "titles": [{"scout_id": scout_id, "title": title} for scout_id, title in titles],
        }
        return json.dumps(payload, ensure_ascii=False)

    def translate_titles(self, titles: tuple[tuple[str, str], ...]) -> dict[str, str] | None:
        """(scout_id, 원문 제목) 목록을 한 번의 LLM 호출로 한국어 제목으로 번역한다.

        여러 후보를 개별 호출이 아니라 배치 1회로 처리해 비용/응답 시간을 아낀다
        (5-20 지시 8번). 호출 자체가 실패하면(설정 오류, 네트워크, JSON 파싱 등)
        None을 반환한다 - 호출부는 모든 후보에 원문 제목을 fallback으로 쓰면 된다.

        호출은 성공했지만 일부 scout_id의 번역만 비어있거나 형식이 잘못된 경우에는
        그 항목만 결과 dict에서 빠진다(부분 실패를 전체 실패로 취급하지 않는다) -
        호출부는 dict에 없는 scout_id에 대해서만 원문 제목으로 fallback하면 된다.
        """
        if not titles:
            return {}
        try:
            data = self._call(
                self._title_translation_system_prompt(),
                self._title_translation_user_message(titles),
            )
            translations = data.get("translations")
            if not isinstance(translations, dict):
                raise LLMResponseError("translations는 객체여야 합니다.")
        except Exception as error:  # noqa: BLE001 - 의도적으로 모든 실패를 None으로 흡수한다.
            _log_error("translate_titles", error)
            return None

        result: dict[str, str] = {}
        requested_ids = {scout_id for scout_id, _title in titles}
        for scout_id, display_title in translations.items():
            if scout_id not in requested_ids:
                continue
            if not isinstance(display_title, str) or not display_title.strip():
                continue
            if len(display_title) > MAX_TITLE_LENGTH:
                continue
            result[scout_id] = display_title.strip()
        return result
