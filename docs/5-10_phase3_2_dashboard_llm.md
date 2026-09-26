# 5-10 Phase 3-2 — TAK SCOUT Dashboard ↔ Interview LLM 연결 보고서

Phase 3-1에서 만든 `tak_scout/interview_llm.py`의 `InterviewLLMProvider`를
`scripts/run_scout_dashboard.py`에 연결했다. 전체 흐름을 우선 완성하는 것이
목표였으므로 과도한 리팩터링은 하지 않았고, 기존 데이터 포맷·기존 KNOWLEDGE
생성 구조를 그대로 유지했다.

## 1. 변경 파일

- `scripts/run_scout_dashboard.py` (수정) — LLM 연결
- `tests/test_scout_dashboard.py` (수정) — `FakeInterviewLLMProvider` + 신규
  테스트 12개 추가(기존 테스트는 한 줄도 바꾸지 않음)
- `docs/5-10_phase3_2_dashboard_llm.md` (신규, 이 문서)

`tak_scout/interview_llm.py`, `tak_scout/interview_session.py`,
`tak_scout/interview.py`, `tak_scout/answers.py`,
`tak_scout/knowledge_bridge.py`, `content_engine/*`, `tak_scout/scoring.py`,
`scripts/run_scout.py`는 이번 단계에서 전혀 수정하지 않았다(13번 금지 목록
전부 확인).

## 2. Dashboard LLM 연결 구조

```python
def make_handler_class(
    config: DashboardConfig, llm_provider: InterviewLLMProvider | None = None
) -> type[BaseHTTPRequestHandler]:
    ...
```

- `llm_provider`를 생략하면(기본값 `None`) **LLM을 전혀 쓰지 않는다** - Phase 2와
  완전히 동일한 템플릿 전용 동작이다.
- 이 기본값은 `content_engine.pipeline.run_media_batch(records, provider=None)`가
  `None`일 때 네트워크 없는 `MockRewriteProvider()`로 대체하는 것과 같은,
  이 프로젝트의 기존 관례를 그대로 따른 것이다. 실제 production에서 LLM을 쓰려면
  `scripts/run_media_batch.py`/`scripts/run_daily.py`/`scripts/tak_auto.py`가
  `OpenAICompatibleRewriteProvider.from_environment()`를 CLI `main()`에서 만들어
  명시적으로 넘기는 것과 똑같이, `run_scout_dashboard.py`의 `main()`도
  `InterviewLLMProvider.from_environment()`를 시도하고 실패(`LLMConfigurationError`)
  하면 `None`으로 조용히 넘어간 뒤 `make_handler_class(config, llm_provider=...)`에
  명시적으로 넘긴다.
- **이렇게 설계한 이유(지시받은 "make_handler_class(config, llm_provider=None)"
  예시와 다르게 구현한 부분에 대한 설명)**: 지시문 3번은 "production에서는
  llm_provider가 없으면 InterviewLLMProvider.from_environment()를 사용한다"를
  요구했는데, 이를 `make_handler_class` 내부에서 처리하면 `llm_provider`를
  넘기지 않고 호출하는 모든 테스트(기존 Phase 2 테스트 14개 포함)가 **테스트
  실행 시점의 환경변수 상태에 따라 동작이 달라지는 위험**을 갖게 된다(지시문
  15번: "환경변수에 실제 API key가 있더라도 테스트가 실제 API를 호출하지
  않도록 한다"와 직접 충돌할 수 있다 - 실제로 이 실행 환경에는
  `TAK_MEDIA_LLM_API_KEY`가 이미 설정되어 있었다). 그래서 env 해석은 CLI
  진입점인 `main()`에서만 하고, `make_handler_class`는 인자 없음을 "명시적으로
  LLM 없음"으로 취급하도록 만들었다 - 기존 테스트를 단 한 줄도 고치지 않고도
  안전성이 코드 구조로 보장된다.
- 서버(핸들러 클래스) 생성 시점에는 어떤 경우에도 LLM API를 호출하지 않는다.
  `InterviewLLMProvider.from_environment()`도, `make_handler_class()`도 환경변수
  읽기/객체 생성만 할 뿐 HTTP 요청을 만들지 않는다. 실제 HTTP 호출은
  `generate_first_question()`/`decide_next_turn()`을 실제로 호출할 때만
  발생한다(Phase 3-1 계약 그대로).

## 3. Turn 1 fallback

`get_or_start_session(candidate, sessions_path, llm_provider)` → 세션이 없을
때만 `_build_turn_one(candidate, llm_provider)` 호출:

```python
def _build_turn_one(candidate, llm_provider):
    if llm_provider is not None:
        try:
            llm_turn = llm_provider.generate_first_question(candidate, _source_fact_for(candidate))
        except Exception as error:
            _log_unexpected_llm_error("generate_first_question", error)
            llm_turn = None
        if llm_turn is not None:
            return replace(llm_turn, option_d=FORCED_OPTION_D)
    return _build_template_turn(1)
```

- `source_fact`는 지시받은 대로 `candidate.summary.strip() or candidate.title`
  (`_source_fact_for()`) — `tak_scout/knowledge_bridge.py:71`과 **완전히 같은
  규칙**이다. 그 파일을 수정하지 않으므로 이 한 줄짜리 규칙만 Dashboard에
  복제했다(주석에 근거 명시).
- 성공하면 `generated_by="llm"`인 `InterviewTurnRecord`를 turn 1로 저장, 실패
  (`None`)하면 기존 `_build_template_turn(1)`(`generated_by="template"`)을
  그대로 사용한다.
- **이중 방어**: `InterviewLLMProvider`는 이미 예외를 던지지 않는 계약이지만
  (Phase 3-1), Dashboard에서도 `try/except Exception`으로 한 번 더 감쌌다.
  Fake provider가 실제로 예외를 던지는 테스트로 "혹시 계약이 깨지더라도 500
  오류가 되지 않는다"를 확인했다(11번 테스트).
- `option_d`도 이중 방어: provider가 이미 `"직접 입력"`으로 강제하지만,
  Dashboard도 `replace(llm_turn, option_d=FORCED_OPTION_D)`로 한 번 더
  덮어쓴다(`FORCED_OPTION_D`는 `tak_scout/interview_llm.py`에 이미 정의된
  상수를 그대로 import해 재사용 - 같은 문자열을 두 곳에 따로 하드코딩하지
  않는다).

## 4. Turn 2/3 follow-up

`handle_turn_answer_submission(candidate, session, form, sessions_path, llm_provider)`:

```
turns = (현재 턴 답변 반영)

if len(turns) >= MAX_TURNS(3):
    status = "completed"          # LLM을 호출하지 않는다
else:
    decision = llm_provider.decide_next_turn(candidate, source_fact, turns)  (try/except로 보호)
    if decision is not None:
        perspective_summary = decision.perspective_summary
        if decision.sufficient:
            status = "completed"
        else:
            turns += (decision.next_turn,)   # option_d 이중 강제
            status = "in_progress"
    else:
        turns += (_build_template_turn(len(turns) + 1),)   # 기존 template fallback
        status = "in_progress"
```

- `turns`(방금 답변까지 포함한, 지금까지 답변된 턴 전체)를 `turns_so_far`로
  그대로 넘긴다 - Phase 3-1의 `decide_next_turn(candidate, source_fact,
  turns_so_far)` 계약과 일치.
- 3턴째가 방금 답변된 경우 `decide_next_turn`을 아예 호출하지 않는다(호출
  횟수 카운터로 테스트에서 직접 확인 - 8, 9번 테스트).

## 5. sufficient=True 조기 완료

- `sufficient=True`면 다음 턴을 만들지 않고 그 자리에서 `status="completed"`,
  `completed_at` 기록, `perspective_summary` 저장 후 review로 리다이렉트한다.
  Phase 2는 항상 정확히 3턴이었지만 Phase 3-2부터는 1~2턴 만에 끝날 수 있다.
- review 화면에는 `len(session.turns) < MAX_TURNS`일 때만
  `"AI가 충분하다고 판단해 인터뷰를 마쳤습니다."` 배너를 보여준다(정확히 3턴을
  다 채우고 끝난 경우에는 표시하지 않는다 - 설계 문서 16번 위험요소에 대한
  대응).

## 6. perspective_summary 처리

- `InterviewSession.perspective_summary`(Phase 1부터 이미 존재하는 필드,
  스키마 변경 없음)에 LLM이 반환한 요약을 그대로 저장한다.
- review 화면(`render_review_html`)에 `"티몽의 관점 요약"` 블록으로 표시한다.
  `perspective_summary`가 빈 문자열(템플릿 fallback만 쓰인 세션 등)이면 그
  블록 자체를 렌더링하지 않는다(자연스러운 생략).
- **KNOWLEDGE에는 전혀 들어가지 않는다** — `handle_finalize()`/
  `_build_combined_answer_text()`를 한 글자도 수정하지 않았고, 이 두 함수는
  `session.turns`만 읽는다(`session.perspective_summary`를 읽지 않음). 테스트
  (`test_finalize_after_llm_driven_session_keeps_existing_knowledge_structure`)로
  KNOWLEDGE evidence 안에 perspective_summary 텍스트("최종 요약", "1턴 후
  요약")가 전혀 나타나지 않음을 직접 확인했다.

## 7. direct input 보호

- D를 선택했을 때 `custom_answer`는 기존 Phase 2와 동일하게 `.strip()`만
  적용해 원문 그대로 저장한다 - LLM 경로가 추가돼도 이 처리는 전혀 바뀌지
  않았다(`handle_turn_answer_submission`의 해당 코드 블록 무변경).
- `decide_next_turn`에 넘어가는 `previous_turns[].user_answer_text`도 D일 때
  이 원문 그대로다(Phase 3-1에서 이미 보장, Dashboard는 그 값을 다시 가공하지
  않고 `turns` 튜플 그대로 전달).
- 특수문자·줄바꿈·탭이 섞인 직접입력을 LLM 흐름(turn 1 LLM 성공 → D 직접입력
  → sufficient=True 조기 완료 → finalize)까지 통째로 흘려서 `session`,
  `review` 화면, `InterviewAnswer.custom_answer`, KNOWLEDGE evidence 네 지점
  모두에서 원문이 100% 동일함을 테스트로 확인했다.

## 8. Fake Provider 구조

```python
@dataclass
class FakeInterviewLLMProvider:
    first_question_results: list = field(default_factory=list)
    decide_results: list = field(default_factory=list)
    first_question_calls: list = field(default_factory=list)
    decide_calls: list = field(default_factory=list)

    def generate_first_question(self, candidate, source_fact):
        self.first_question_calls.append((candidate, source_fact))
        ...  # 큐에서 하나 꺼내 반환, 예외 클래스면 raise, 큐가 비면 None

    def decide_next_turn(self, candidate, source_fact, turns_so_far):
        self.decide_calls.append((candidate, source_fact, turns_so_far))
        ...  # 동일 패턴
```

- `InterviewLLMProvider`를 상속하지 않는 순수 duck-typing fake다(Phase 3-1
  provider와 메서드 시그니처만 동일).
- 결과를 리스트에 미리 채워 두고 순서대로 하나씩 소비한다. `None`을 넣으면
  "LLM 실패"를, 예외 클래스(`RuntimeError` 등)를 넣으면 "LLM이 예외를 던짐"을
  시뮬레이션한다.
- 모든 호출의 인자를 그대로 기록해 두어(`first_question_calls`,
  `decide_calls`) "몇 번 호출됐는지", "무엇이 전달됐는지"(candidate,
  source_fact, turns_so_far)를 테스트에서 직접 검증할 수 있다 - 실제
  `InterviewLLMProvider`나 환경변수는 어디에서도 참조하지 않는다.

## 9. 테스트 목록(신규 12개, `DashboardLLMIntegrationTests`)

| # | 테스트 | 확인 내용 |
|---|---|---|
| 1 | `test_llm_first_question_success_sets_generated_by_llm` | LLM 성공 → `generated_by=="llm"`, 화면에 LLM 질문 표시 |
| 2 | `test_llm_first_question_failure_falls_back_to_template` | `None` → 기존 template 질문/문구 그대로 |
| 3 | `test_llm_first_question_option_d_is_forced_to_direct_input` | LLM이 이상한 `option_d`를 반환해도 저장된 값은 `"직접 입력"` |
| 4 | `test_sufficient_false_shows_and_stores_next_turn` | `sufficient=False` → 다음 질문 표시 + session 저장 + `turns_so_far` 전달 값 확인 |
| 5 | `test_sufficient_true_completes_immediately_and_shows_review` | `sufficient=True` → 즉시 completed, review 이동, 조기완료 배너 + perspective_summary 표시 |
| 6 | `test_turn_three_never_calls_decide_next_turn_and_completes` | turn 3 답변 시 `decide_next_turn` 호출 횟수가 늘지 않음(정확히 2회 유지), status completed |
| 7 | `test_decide_next_turn_none_falls_back_to_template` | `decide_next_turn() is None` → 기존 template follow-up |
| 8 | `test_llm_exception_does_not_crash_dashboard` | Fake provider가 실제로 예외를 던져도 200 응답 + template fallback (500 없음) |
| 9 | `test_resuming_in_progress_session_does_not_call_llm_again` | 같은 in_progress 세션을 3번 GET해도 `generate_first_question` 호출은 1회 |
| 10 | `test_resuming_completed_session_redirects_to_review` | completed 세션 재진입 → review로 리다이렉트 |
| 11 | `test_direct_input_preserved_through_llm_flow` | 특수문자/줄바꿈 포함 D 직접입력이 session/`decide_next_turn` 입력/review 화면에서 원문 그대로 |
| 12 | `test_finalize_after_llm_driven_session_keeps_existing_knowledge_structure` | LLM 기반 세션도 기존 finalize/KNOWLEDGE(pending, SOURCE FACT/URL/USER ORIGINAL THOUGHT) 구조 유지, perspective_summary는 evidence에 섞이지 않음 |

기존 `DashboardLogicTests`(4개), `DashboardMultiTurnHttpTests`(10개)는 **한 줄도
수정하지 않았다** - `llm_provider`를 넘기지 않는 기존 호출부가 그대로
`llm_provider=None`(LLM 없음) 기본값을 타므로 Phase 2와 동일하게 통과한다.

## 10. 테스트 결과

```
python3 -m unittest tests.test_scout_dashboard -v
Ran 26 tests in 11.719s
OK
```

```
python3 -m unittest discover -s tests -p 'test_*.py'
Ran 332 tests in 13.411s
OK
```

(Phase 3-1 종료 시점 320개 + 이번 신규 12개 = 332개, 전부 통과. 기존 320개는
무손상.)

## 11. 실제 API 호출 여부

**없음.** `tests/test_scout_dashboard.py`의 새 테스트는 전부
`FakeInterviewLLMProvider`만 주입하며, `tak_scout.interview_llm.InterviewLLMProvider`
클래스 자체를 인스턴스화하지 않는다. 기존 테스트도 `llm_provider`를 넘기지
않아 LLM 경로 자체가 비활성화된다. 이 실행 환경에 실제
`TAK_MEDIA_LLM_API_KEY`가 설정되어 있었지만(2번 항목에서 설명한 대로),
`make_handler_class`가 인자 없음을 "LLM 없음"으로 처리하도록 설계했기
때문에 이 값과 무관하게 테스트는 항상 결정적으로 네트워크 없이 동작한다.

## 12. 운영 데이터 변경 여부

**없음.** 모든 테스트가 `tempfile.TemporaryDirectory()`로 만든 임시 경로만
사용한다(`DashboardLLMIntegrationTests.setUp`도 기존 테스트 클래스들과 동일한
패턴). `git status --short` 결과 `data/tak_brain_knowledge.json`의 변경은
이번 대화 시작 이전부터 있던 것(이 세션에서 건드리지 않음)이고, 이번 단계가
새로 변경한 `data/` 파일은 없다.

## 13. 기존 기능 회귀 여부

**없음.** 기존 `DashboardLogicTests`, `DashboardMultiTurnHttpTests`(Phase 2
템플릿 전용 흐름 - 3턴 고정, "이미 답변함", "관심 없음", session 복원,
restart, invalid option 등) 24개 테스트가 코드 수정 없이 전부 그대로
통과했다. `handle_finalize`, `tak_scout/answers.py`,
`tak_scout/knowledge_bridge.py`는 이번 단계에서 전혀 손대지 않았다.

## 14. Phase 3-3 준비 상태

- Dashboard가 이제 Turn 1/2/3 전 구간에서 LLM을 우선 시도하고 실패 시 항상
  안전하게 template으로 fallback하는 구조를 완성했다. `main()`이 production
  wiring(`InterviewLLMProvider.from_environment()`)을 담당하므로, 실제로
  `TAK_MEDIA_LLM_ENDPOINT`/`TAK_MEDIA_LLM_MODEL`을 설정하면 바로 실제 LLM
  인터뷰가 동작한다(수동 검증은 별도 격리 환경에서 진행 필요 - 설계 문서
  17번 항목과 동일한 성격).
- review 화면에 조기완료 배너/`perspective_summary` 표시까지 완료되어
  사용자에게 "왜 3턴이 아니었는지"가 항상 설명된다.
- 다음 단계가 있다면(예: 실제 운영 검증, UI/문구 다듬기, perspective_summary를
  KNOWLEDGE evidence에 포함할지 여부 재검토 등) 이번 구조 위에 얹으면 되고,
  이번 단계에서 새로 도입한 회귀 위험은 없다(모든 신규 분기는 `llm_provider is
  None`일 때 기존 코드 경로와 100% 동일하게 동작).

## 15. 알려진 제한사항

- `_build_turn_one`/`decide_next_turn` 호출부의 `try/except Exception`은
  Phase 3-1 계약(예외를 절대 던지지 않음)에 대한 **이중 방어**일 뿐, Phase
  3-1의 실제 오류 로깅(안전하게 정제된 메시지)을 대체하지 않는다 - Dashboard
  쪽 로그는 예외 타입 이름만 남긴다(시크릿 노출 방지 원칙 동일 적용, 다만
  Phase 3-1의 로그보다 더 적은 정보만 남는다).
- LLM이 만든 질문/선택지의 "내용 적합성"(문법은 맞지만 소재와 안 맞는 등)은
  자동으로 검증하지 않는다 - 기존 review 화면에서 사람이 finalize 전에
  확인하는 안전장치에 계속 의존한다(설계 문서 16번 그대로, 이번 단계에서
  새로 추가한 자동 검증 없음).
- `perspective_summary`를 KNOWLEDGE evidence에 포함할지(설계 문서 10번의
  (b) 방식)는 이번 단계에서 다루지 않았다 - 여전히 review 화면 전용 정보다.
- "다시 답변하기(restart)"를 반복하면 매번 최대 3회의 새 LLM 호출이 발생할
  수 있다(설계 문서 16번 위험요소 4와 동일, 이번 단계에서 별도 제한을 추가하지
  않았다 - 사용자가 의도적으로 누르는 동작이라는 전제 유지).

---

## 최종 확인

- **실제 LLM API 호출**: 없음
- **운영 data 변경**: 없음
- **git commit/push**: 없음(`git status`만 확인)
