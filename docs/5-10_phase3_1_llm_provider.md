# 5-10 Phase 3-1 — TAK SCOUT Interview LLM Provider 구현 보고서

docs/5-10_phase3_llm_design.md의 설계를 그대로 구현했다. 이번 단계는 "LLM
인터뷰 provider 자체"만 완성했고, Dashboard(scripts/run_scout_dashboard.py)는
전혀 건드리지 않았다.

## 1. 구현 파일

- `tak_scout/interview_llm.py` (신규) — `InterviewLLMProvider`, `FollowUpDecision`
- `tests/test_interview_llm.py` (신규) — 36개 테스트, fake transport / mock urlopen만 사용
- `docs/5-10_phase3_1_llm_provider.md` (신규, 이 문서)

기존 파일은 한 줄도 수정하지 않았다(18번 금지 목록 전부 확인 - 8번 참고).

## 2. InterviewLLMProvider 구조

```python
@dataclass(frozen=True)
class FollowUpDecision:
    sufficient: bool
    next_turn: InterviewTurnRecord | None   # sufficient=False일 때만 채움
    perspective_summary: str                 # 항상 채움


@dataclass(frozen=True)
class InterviewLLMProvider:
    endpoint: str
    api_key: str
    model: str
    timeout_seconds: float = 20.0
    transport: InterviewLLMTransport = _http_transport

    @classmethod
    def from_environment(cls, environ=None, transport=_http_transport) -> "InterviewLLMProvider": ...

    def generate_first_question(self, candidate, source_fact) -> InterviewTurnRecord | None: ...

    def decide_next_turn(self, candidate, source_fact, turns_so_far) -> FollowUpDecision | None: ...
```

- `RewriteProvider`/`OpenAICompatibleRewriteProvider`를 상속하지 않는다(설계
  문서 2-1번에서 재확인한 대로 계약 자체가 다르다 - 인터뷰 질문 생성 시점에는
  `ContentDraft`/`KnowledgeRecord`가 아직 없다).
- `content_engine/llm_provider.py`의 HTTP 호출 코드는 import도, 복붙도 하지
  않았다. `interview_llm.py` 안에 독립적인 `_http_transport`(약 25줄)를 새로
  작성했다.
- 인스턴스 생성만으로는 네트워크를 호출하지 않는다. `generate_first_question`/
  `decide_next_turn`을 호출할 때만 HTTP 요청 1회가 발생한다(재시도 없음).

## 3. 환경변수

기존 이름을 그대로 재사용했다(새 시크릿 없음).

- `TAK_MEDIA_LLM_API_KEY`
- `TAK_MEDIA_LLM_ENDPOINT`
- `TAK_MEDIA_LLM_MODEL`

셋 중 하나라도 없으면 `content_engine.LLMConfigurationError`(import해서 그대로
재사용, `content_engine` 파일은 수정하지 않음)를 raise한다 - 이것만 예외로
호출부까지 전파되고, 나머지 모든 실패는 provider 내부에서 흡수한다.

## 4. HTTP 호출 방식

- `POST {TAK_MEDIA_LLM_ENDPOINT}`
- 헤더: `Authorization: Bearer {api_key}`, `Content-Type: application/json`
- 바디: `model`, `response_format={"type": "json_object"}`, `messages`(system +
  user) — `temperature` 등 불필요한 파라미터는 추가하지 않았다.
- production 기본 transport(`_http_transport`)는 `urllib.request` 기반이며,
  생성자/`from_environment`가 `transport` 인자를 받아 테스트에서 fake 함수로
  교체할 수 있다(`content_engine.OpenAICompatibleRewriteProvider`와 동일한
  주입 패턴).

## 5. Turn 1 출력 구조

```json
{"question": "...", "option_a": "...", "option_b": "...", "option_c": "...", "option_d": "직접 입력"}
```

- 성공 시 `InterviewTurnRecord(turn=1, generated_by="llm", option_d="직접 입력", selected_option=None, custom_answer="", answered_at=None)`를 반환.
- `option_d`는 LLM 응답 값을 절대 쓰지 않고 서버가 항상 리터럴 `"직접 입력"`으로 덮어쓴다(변조 테스트로 확인).
- 실패하면 `None`.

## 6. 후속 질문 출력 구조

```json
{
  "sufficient": false,
  "question": "...", "option_a": "...", "option_b": "...", "option_c": "...", "option_d": "직접 입력",
  "perspective_summary": "..."
}
```

- `sufficient=true`이면 `question`/`option_*`는 무시하고
  `FollowUpDecision(sufficient=True, next_turn=None, perspective_summary=...)`.
- `sufficient=false`이면 `next_turn`(turn 번호 = `len(turns_so_far) + 1`,
  `generated_by="llm"`, `option_d` 강제 고정)을 만든 `FollowUpDecision`.
- 두 경우 모두 `perspective_summary`는 필수(빈 문자열이면 실패 → `None`).

## 7. JSON validation

공통(두 메서드 모두):
- 응답이 JSON object인지 (`choices[0].message.content`를 다시 `json.loads`)
- `decide_next_turn`에서만: `sufficient`가 `bool`인지, `perspective_summary`가
  비어 있지 않은 문자열인지

`sufficient=false`(또는 turn 1)일 때 추가로:
- `question`/`option_a`/`option_b`/`option_c` 각각 존재 + 비어 있지 않음
- `question` ≤ 200자, `option_a/b/c` 각 ≤ 80자
- `option_a`/`option_b`/`option_c` 세 값이 서로 달라야 함(중복 금지)

`option_d`는 검증하지 않는다 - 서버가 항상 대체하기 때문이다(설계 문서 12번
그대로).

## 8. 오류 처리

다음은 모두 provider 내부(`generate_first_question`/`decide_next_turn`의
`try/except Exception`)에서 잡아 `None`으로 흡수한다: HTTP 연결 실패,
timeout, HTTP 4xx/5xx, JSON parsing 실패, 응답 구조 오류(`choices` 없음 등),
content 없음/문자열 아님, malformed JSON, 필수 필드 누락, `sufficient` 타입
오류, 빈 질문, 중복 option, 길이 초과. 예외는 Dashboard까지 전파되지 않는다.
`from_environment()`의 환경변수 누락만 `LLMConfigurationError`를 그대로
raise한다(설계 문서 13번 그대로).

## 9. 보안

- API key는 `os.environ`에서만 읽는다(`from_environment`).
- `_safe_http_error_message`가 OpenAI 오류 응답 중 `message`/`type`/`code`/
  `param` 필드만 로그에 남기고, 그 외 필드(예: 오류 본문에 실수로 섞여 들어간
  인증 헤더 같은 값)는 절대 노출하지 않는다.
- `_log_error()`는 `LLMConfigurationError`/`LLMResponseError`처럼 이미
  안전하게 정제된 메시지만 그대로 stderr에 남기고, 그 외의 예상치 못한
  예외는 타입 이름만 기록한다(`str(error)`를 절대 출력하지 않음) - 시크릿이
  로그에 섞여 들어갈 경로를 원천 차단했다.
- 보안 테스트: 가짜 시크릿 문자열 `"TEST_SECRET_KEY_123"`을 헤더/오류 본문에
  넣고, `_http_transport`가 raise하는 예외 메시지에 그 문자열이 전혀 나타나지
  않음을 확인했다(`test_http_error_message_never_leaks_api_key`,
  `test_connection_failure_returns_safe_message`,
  `test_timeout_returns_safe_message`). 실제 secret은 테스트에 전혀 쓰지
  않았다.

## 10. source_fact 처리 확인 결과

`candidate.summary`의 실제 의미를 코드로 추적했다(`tak_scout/rss.py`,
`tak_scout/knowledge_bridge.py`):

- `tak_scout/rss.py`의 `parse_rss_items()`가 RSS `<description>`(또는
  `<summary>`) 태그 원문에서 HTML 태그를 제거하고 200자로 자른 것이
  `ScoutCandidate.summary`다. **AI가 생성한 문장이 아니고, 사용자 의견도
  섞여 있지 않다** — 공개 RSS 피드(BBC Business, Hacker News 등)가 제공하는
  기사 자체의 요약 원문이다.
- 이미 `tak_scout/knowledge_bridge.py:71`에 `source_fact =
  candidate.summary.strip() or candidate.title`라는 동일한 계약이 존재한다
  (KNOWLEDGE의 `SOURCE FACT` evidence 줄을 만들 때 쓰는 것과 완전히 같은
  값·같은 의미). 이번 Phase 3-1의 `source_fact` 파라미터는 이 기존 계약을
  그대로 이어받는다 - 새 의미를 만들지 않았다.
- 이 단계에서는 새 evidence schema를 만들지 않았다(15번 지시 그대로). 실제로
  `generate_first_question(candidate, source_fact)`처럼 `source_fact`를
  `candidate`와 분리된 별도 인자로 받게 설계해, "이것은 기사 사실이며 사용자
  의견이 아니다"라는 경계가 함수 시그니처 수준에서부터 명확하다.

## 11. 테스트 목록 (tests/test_interview_llm.py, 36개)

**환경변수 (4)**: 정상 생성, API key/endpoint/model 각각 없음 → `LLMConfigurationError`

**generate_first_question (13)**: 정상 응답, `generated_by=="llm"`,
`option_d` 강제 변조 확인, malformed JSON, 필수 필드 누락, 빈 질문, 중복
option, question 길이 초과, option 길이 초과, HTTP 오류, timeout, source_fact/
`previous_turns` 분리 확인, Chat Completions 요청 형태(model/response_format/
messages/Authorization 헤더) 확인

**decide_next_turn (16)**: `sufficient=false` 다음 턴 생성, `sufficient=true`
완료, `option_d` 강제 변조 확인, malformed JSON, `sufficient` 타입 오류,
`perspective_summary` 누락, `question` 누락(불충분 시), 중복 option, 길이
초과, HTTP 오류, timeout, 사용자 직접입력 원문 그대로 전달(특수문자/줄바꿈
포함), source_fact와 user_answer_text 분리 확인, `current_turn_number`/
`max_turns` 값 확인, 호출 1회만 발생(재시도 없음)

**기본 production transport `_http_transport` (4, `urllib.request.urlopen`을
mock으로 패치 — 실제 네트워크 없음)**: POST JSON 바디/헤더 형태 확인, HTTP
오류 메시지에 API key 미노출, 연결 실패 시 안전한 메시지, timeout 시 안전한
메시지

## 12. 테스트 결과

```
python3 -m unittest tests.test_interview_llm -v
Ran 36 tests in 0.006s
OK
```

```
python3 -m unittest discover -s tests -p 'test_*.py'
Ran 320 tests in 7.122s
OK
```

기존 테스트는 전부 그대로 통과했다(전체 320개, 신규 36개 포함 — 기존 284개는
그대로 무손상).

## 13. 실제 네트워크 호출 여부

**없음.** 모든 테스트가 fake transport 함수 주입 또는
`unittest.mock.patch("tak_scout.interview_llm.urlopen", ...)`로 HTTP 계층을
대체했다. 소켓을 여는 코드 경로는 어떤 테스트에서도 실행되지 않았다. 이번
단계 전체에서 실제 LLM API를 1회도 호출하지 않았다.

## 14. 기존 코드 변경 여부

**없음.** `git status --short` 결과, 이번 대화에서 새로 생긴 파일은
`tak_scout/interview_llm.py`, `tests/test_interview_llm.py`,
`docs/5-10_phase3_1_llm_provider.md` 셋뿐이다. 18번 금지 목록
(`scripts/run_scout_dashboard.py`, `tak_scout/interview.py`,
`tak_scout/interview_session.py`, `tak_scout/answers.py`,
`tak_scout/knowledge_bridge.py`, `content_engine/*`, `scoring.py`,
`run_scout.py`) 중 어느 것도 수정하지 않았다.

## 15. 운영 데이터 변경 여부

**없음.** `data/` 아래 어떤 파일도 읽거나 쓰지 않았다(이 provider는 파일
I/O를 전혀 하지 않고, 테스트도 실제 `data/tak_brain_knowledge.json` 등을
참조하지 않는다).

## 16. git commit/push 여부

**없음.** `git commit`/`git push`를 하지 않았다. `git status`만 확인했다
(11번 결과 참고).

## 17. Phase 3-2 준비 상태

- `InterviewLLMProvider.from_environment()` / `generate_first_question()` /
  `decide_next_turn()` 세 진입점이 모두 완성되어 있고, 실패 시 항상 `None`을
  반환하므로 Dashboard 쪽은 "LLM 우선 시도 → `None`이면 기존
  `_build_template_turn`으로 fallback"이라는 한 줄짜리 분기만 추가하면 된다
  (설계 문서 6번 의사코드 그대로 적용 가능).
- 테스트용 provider 주입 지점(`make_handler_class(config, llm_provider=...)`
  같은 선택적 인자)은 아직 Dashboard에 없다 - 설계 문서 13/16-3번에서 짚은
  대로 Phase 3-2에서 추가해야 한다.
- `perspective_summary`를 review 화면에 표시하는 로직, "AI가 충분하다고
  판단해 인터뷰를 마쳤습니다" 안내 문구 추가는 모두 Phase 3-2 범위다(설계
  문서 14/16번).
- 이번 단계는 Dashboard를 전혀 건드리지 않았으므로 회귀 위험이 0에 가깝다 -
  설계 문서 15번의 권장 구현 순서 1단계를 그대로 완료한 상태다.
