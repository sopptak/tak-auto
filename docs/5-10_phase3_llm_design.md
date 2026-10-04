# 5-10 Phase 3 — TAK SCOUT LLM Interview 설계

**이번 단계는 설계 전용이다. 코드는 한 줄도 수정하지 않았다.** 아래 모든
파일/함수 이름은 "다음 구현 단계에서 이렇게 하겠다"는 제안이며, 실제로는
만들어지거나 바뀌지 않았다. 실제 LLM도 호출하지 않았다. 지시받은 파일
전부를 읽고 분석한 뒤 작성했다.

## 1. 현재 구조 분석

| 파일 | Phase 3와의 관계 |
|---|---|
| `tak_scout/interview.py` | `build_interview_question()` — 소재 1건당 고정 질문 1개. **Turn 1의 안전한 fallback**으로 이미 Phase 2에서도 쓰이지 않게 됐고(Phase 2는 `_build_template_turn`을 새로 씀), Phase 3에서도 건드리지 않는다. |
| `tak_scout/interview_session.py` | `InterviewSession`/`InterviewTurnRecord` + load/save/upsert(Phase 1). 필드가 이미 `generated_by`("template"/"llm")를 갖고 있어 **Phase 3를 위해 만들어 둔 구조**다. 스키마 변경이 전혀 필요 없다. |
| `tak_scout/answers.py` | `InterviewAnswer`(scout_id당 1개, 스키마 불변). Phase 3도 finalize 시점에 이 스키마 그대로 합성한다(11번 참고). |
| `tak_scout/knowledge_bridge.py` | `build_knowledge_from_interview()` — `InterviewAnswer` 1개만 받는다. Phase 3에서도 이 함수의 입력 계약을 바꾸지 않는다(11번). |
| `scripts/run_scout_dashboard.py` | Phase 2에서 만든 `_build_template_turn(turn_number)`, `handle_turn_answer_submission()`, `handle_finalize()`, `_build_combined_answer_text()`, `MAX_TURNS=3`. **이 함수들의 "끼워 넣을 지점"을 14번에서 정확히 짚는다** — 이번 단계에서는 손대지 않는다. |
| `content_engine/llm_provider.py`, `rewrite.py`, `models.py` | TAK MEDIA용 `RewriteProvider`/`OpenAICompatibleRewriteProvider`. **재사용 불가 판정**(2번, 5-10 최초 설계 문서의 결론을 이번에 다시 코드로 재확인). |
| `tests/test_scout_dashboard.py`, `test_scout_interview.py`, `test_interview_session.py` | Phase 2/1의 테스트 패턴(실제 소켓을 여는 HTTP 통합 테스트, fake/mock provider를 생성자 인자로 주입하는 `test_media_batch.py`의 `PartiallyFailingProvider`/`CrashingProvider` 패턴)을 13번 테스트 설계에서 그대로 계승한다. |

## 2. LLM 모듈 구조 제안

### 2-1. `RewriteProvider`를 재사용할 수 있는가 — **재사용 불가(재확인)**

`content_engine/rewrite.py`의 `RewriteProvider`는 추상 메서드
`rewrite(self, request: RewriteRequest) -> ContentDraft` 하나뿐이다.
`OpenAICompatibleRewriteProvider.rewrite()`를 다시 읽어 확인한 결과:

- 입력이 `RewriteRequest`(`ContentDraft` + `KnowledgeRecord`)로 고정되어
  있다. 인터뷰 질문 생성 시점에는 `ContentDraft`/`KnowledgeRecord`가 아직
  존재하지 않는다(인터뷰가 끝나야 KNOWLEDGE가 생긴다 - 순서가 반대).
- system prompt가 "한국어 콘텐츠를 사실 경계 안에서 재작성하라"로
  하드코딩되어 있다(`_system_prompt()`). 질문을 만들라는 지시가 아니다.
- 응답 파싱(`_draft_from_response`)이 `{title, body}`를 받아
  `dataclasses.replace(원본_draft, title=..., body=...)`로 **원본
  `ContentDraft` 객체에 이어붙이는 구조**다. 인터뷰 질문+선택지+충분성
  판단은 이 형태로 표현할 수 없다.

**결론**: 클래스/인터페이스 자체는 재사용할 수 없다. "그대로 복붙해서
엉뚱한 provider를 만드는 것도 피한다"(15번 지시)는 원칙에 따라, 완전히
새로 만들되 **작게** 만든다.

### 2-2. 무엇을 재사용하는가

- **환경변수 이름**: `TAK_MEDIA_LLM_API_KEY`/`TAK_MEDIA_LLM_ENDPOINT`/
  `TAK_MEDIA_LLM_MODEL` 그대로(새 시크릿 없음).
- **예외 클래스**: `content_engine.LLMConfigurationError`,
  `content_engine.LLMResponseError`를 **import해서 그대로 재사용**한다
  (클래스 정의만 가져다 쓰는 것이라 `content_engine`을 전혀 수정하지
  않고도 같은 실패 상황을 같은 이름으로 표현할 수 있다).
- **HTTP 호출 패턴**: `_http_transport`(urllib 기반 단순 POST)와 같은
  *모양*만 새로 작성한다. 이 함수는 `content_engine/llm_provider.py`의
  모듈 비공개 함수라 직접 import해서 공유할 수 없고, 공유 가능하게
  만들려면 그 파일을 수정해야 한다(금지 사항 위반). "공용 HTTP 계층을
  뽑아낼지 vs 새 파일에 따로 만들지"를 저울질한 결과, **이번 규모(약
  20~30줄짜리 POST 호출 1개)에서는 공용 계층을 새로 만드는 것이 오히려
  과도한 추상화**라고 판단했다(15번 지시 그대로). 중복은 작고, 두 provider가
  서로 다른 계약(재작성 vs 질문 생성)을 갖고 있어 억지로 공유하면 나중에
  한쪽을 바꿀 때 다른 쪽이 깨질 위험이 더 크다.

### 2-3. 새 모듈: `tak_scout/interview_llm.py` (제안, 아직 없음)

```python
@dataclass(frozen=True)
class FollowUpDecision:
    sufficient: bool
    next_turn: InterviewTurnRecord | None   # sufficient=False일 때만
    perspective_summary: str                 # 항상 채움(10번)


class InterviewLLMProvider:
    # RewriteProvider를 상속하지 않는다 - 계약이 다르다(2-1).

    @classmethod
    def from_environment(cls) -> "InterviewLLMProvider":
        ...  # 없으면 LLMConfigurationError(content_engine에서 import)

    def generate_first_question(
        self, candidate: ScoutCandidate, source_fact: str
    ) -> InterviewTurnRecord | None:
        """성공하면 turn=1 InterviewTurnRecord(generated_by="llm"), 실패하면 None."""

    def decide_next_turn(
        self,
        candidate: ScoutCandidate,
        source_fact: str,
        turns_so_far: tuple[InterviewTurnRecord, ...],
    ) -> FollowUpDecision | None:
        """성공하면 FollowUpDecision, 실패하면 None(호출부가 fallback 처리)."""
```

**두 메서드 모두 절대 예외를 밖으로 던지지 않는다** — 내부에서 모든 실패를
잡아 `None`을 반환한다(6, 7, 8, 12번). 호출부(Dashboard)는 `None`이면
기존 템플릿으로 대체하기만 하면 되므로, 실패 처리 로직이 Dashboard 쪽에
전혀 새로 생기지 않는다 — "가장 단순하고 안전한 방법"(15번)에 부합한다.

## 3. 입력 JSON

LLM에 보내는 사용자 메시지(JSON)는 SOURCE FACT와 사용자의 실제 답변을
**필드 이름 수준에서부터 명확히 구분**한다.

```json
{
  "contract_version": "tak-interview-v1",
  "scout": {
    "title": "Anthropic boss Dario Amodei calls for AI development to slow down",
    "source_name": "BBC Business",
    "source_url": "https://www.bbc.co.uk/news/articles/...",
    "category": "finance",
    "published_at": "2026-09-12T21:16:47+00:00",
    "source_fact": "The call comes amid growing concerns that AI models may become able to inflict serious damage worldwide."
  },
  "current_turn_number": 2,
  "max_turns": 3,
  "previous_turns": [
    {
      "turn": 1,
      "question": "이 소재에 대해 어떻게 생각하시나요?",
      "selected_option": "D",
      "user_answer_text": "신기술은 두려워 말고 부딪혀서 느껴봐야 한다."
    }
  ]
}
```

- `scout.source_fact`는 원문 요약(`candidate.summary`)이며, 시스템
  프롬프트에서 **"이것은 기사에서 확인된 사실이며 사용자의 의견이 아니다"**
  라고 명시적으로 라벨링한다.
- `previous_turns[].user_answer_text`는 A/B/C면 선택한 문구, D면 사용자가
  입력한 **원문 그대로**다(5번 스키마의 `_turn_answer_text()`와 동일한
  해석 규칙 - Phase 2에 이미 있는 함수를 그대로 재사용).
- 시스템 프롬프트(설계 초안, 아직 코드 아님)에 반드시 넣을 문장:
  > "scout.source_fact는 기사에서 확인된 사실이며 사용자의 의견이 아니다.
  > 사용자의 실제 생각은 previous_turns[].user_answer_text에만 있다.
  > source_fact의 내용을 사용자가 말한 것처럼 다루지 마라."

## 4. 출력 JSON

요청받은 최소 구조를 그대로 채택한다.

```json
{
  "sufficient": false,
  "question": "실제로 AI를 사용하면서 비슷하게 느낀 경험이 있나요?",
  "option_a": "있다, 직접 활용해봤다",
  "option_b": "아직 없다",
  "option_c": "간접적으로만 접했다",
  "option_d": "직접 입력",
  "perspective_summary": "신기술을 두려워하지 않고 직접 경험해야 한다는 입장"
}
```

`sufficient: true`일 때는 `question`/`option_*`를 생략해도 되게 만든다
(있어도 무시). **필수 필드는 `sufficient`와 `perspective_summary` 둘뿐**
이고, `sufficient: false`일 때만 `question`/`option_a/b/c`가 추가로
필수가 된다(6번 필수 필드 누락 검증에서 이 규칙을 그대로 쓴다).

**추가 필드 제안**: `reasoning`(선택, 내부용) — "왜 sufficient로
판단했는지" 한 줄. **제안 이유**: 나중에 프롬프트를 튜닝할 때 사람이
로그를 보고 판단 근거를 확인할 수 있으면 디버깅이 쉬워진다. **단, Phase 3
1차 구현에서는 채택하지 않는 것을 권장한다** — 이 필드는 세션/KNOWLEDGE
어디에도 저장하지 않아야 한다(AI의 "판단 이유"가 사용자의 말인 것처럼
섞여 들어갈 위험을 원천 차단). 필요해지면 그때 "로그에만 출력하고 저장은
안 함"이라는 조건으로 별도 검토한다.

## 5. sufficient 판단 구조

"충분한가?"와 "다음 질문은 무엇인가?"를 **한 번의 LLM 호출**로 함께
받는다(비용 절감, 13번). Turn 1은 판단할 이전 답변이 없으므로 별도
메서드(`generate_first_question`)로 분리한다 — "충분한가?"라는 질문 자체가
Turn 1에는 성립하지 않기 때문에, 하나의 메서드에 억지로 합치면 응답
스키마에 무의미한 `sufficient` 필드를 항상 채워야 해서 오히려 복잡해진다.

```
Turn 1 답변 완료
    │  turns 개수 1개, MAX_TURNS(3) 미만
    ▼
decide_next_turn(candidate, source_fact, turns_so_far=(turn1,))
    │
    ├─ sufficient=true  → 완료(perspective_summary 저장, turns=1개인 채로 종료)
    └─ sufficient=false → turn 2 생성(생성된 question/option_a~c + 강제 option_d)

Turn 2 답변 완료 (turn 2가 있었다면)
    │  turns 개수 2개, MAX_TURNS(3) 미만
    ▼
decide_next_turn(..., turns_so_far=(turn1, turn2))
    │
    ├─ sufficient=true  → 완료(turns=2개)
    └─ sufficient=false → turn 3 생성

Turn 3 답변 완료
    │  turns 개수 3개 == MAX_TURNS
    ▼
decide_next_turn을 아예 호출하지 않는다 - 무조건 완료(8번)
```

## 6. 질문 생성 구조

**Turn 1**:

```
provider = InterviewLLMProvider.from_environment()  # 실패하면 LLMConfigurationError -> None 취급
turn = provider.generate_first_question(candidate, source_fact) if provider else None
if turn is None:
    turn = _build_template_turn(1)   # 기존 Phase 2 함수, 그대로 fallback
```

`_build_template_turn(1)`은 반드시 fallback으로 남는다(요청 원칙 그대로).
Phase 2 코드를 1바이트도 바꾸지 않고 그대로 재사용 가능하다는 것을 이미
확인했다(Phase 2 코드를 다시 읽고 확인 - `_build_template_turn`은
`turn_number`만 받는 순수 함수라 Phase 3에서 조건부 호출만 추가하면 된다).

**Turn 2, 3(후속)**: 5번 구조 그대로. `sufficient=false`일 때 LLM이 만든
`question`/`option_a/b/c`로 `InterviewTurnRecord`를 만들되, **option_d는
LLM 응답 값을 무시하고 서버 코드가 항상 리터럴 문자열 `"직접 입력"`으로
덮어쓴다**:

```python
next_turn = InterviewTurnRecord(
    turn=next_number,
    question=response["question"],
    option_a=response["option_a"],
    option_b=response["option_b"],
    option_c=response["option_c"],
    option_d="직접 입력",   # 항상 고정 - response["option_d"]를 쓰지 않는다
    generated_by="llm",
    selected_option=None,
    custom_answer="",
    answered_at=None,
)
```

## 7. fallback 정책

12번의 실패 유형 10가지를 전부 표로 정리한다. **모든 실패는
`InterviewLLMProvider` 안에서 잡히고 호출부에는 `None`만 전달된다.**

| # | 실패 유형 | 처리 |
|---|---|---|
| 1 | API key 없음 | `from_environment()`에서 `LLMConfigurationError`(재사용) - Dashboard가 세션 시작 시점에 **한 번만** 확인하고, 실패하면 이번 인터뷰 전체를 템플릿 전용으로 진행(매 턴마다 다시 시도하지 않음 - 13번 비용 절감과 직결) |
| 2 | endpoint 오류(연결 실패) | 전송 함수에서 예외 포착 → `None` 반환, 재시도 없음(무한 루프 방지, 8번) |
| 3 | timeout | 고정 timeout(예: 20~30초, `OpenAICompatibleRewriteProvider`와 같은 관례) 설정 → 초과 시 `None` |
| 4 | HTTP 4xx/5xx | 응답 바디에서 안전한 필드만 뽑아 로그(API key가 로그에 남지 않게 함, 11번) → `None` |
| 5 | JSON parsing 실패 | `json.loads` 예외 포착 → `None` |
| 6 | 필수 필드 누락 | `sufficient`/`perspective_summary`(항상 필수), `sufficient=false`일 때 `question`/`option_a/b/c`(추가 필수) 중 하나라도 없으면 `None` |
| 7 | 이상한 option 생성(빈 문자열, 중복) | 빈 문자열이거나 A/B/C가 서로 완전히 같으면 `None` |
| 8 | sufficient 값 이상(불리언 아님) | `isinstance(value, bool)`이 아니면 `None` |
| 9 | 너무 긴 질문 | `question` 200자 초과 또는 `option_a/b/c` 각 80자 초과면 `None`(정상적인 4지선다 UI를 벗어나는 응답을 걸러냄) |
| 10 | D option 변조 | **fallback이 아니다** - 실패로 취급하지 않고 응답 자체는 유효하다고 보되, `option_d`만 6번처럼 서버가 항상 `"직접 입력"`으로 고쳐 쓴다 |

**decide_next_turn 실패 시 fallback을 "완료" vs "템플릿으로 계속" 중
무엇으로 할지**는 두 가지 방법이 다 있다(요청서에도 두 옵션이 모두
제시됨). 이번 설계에서는 **"템플�이트으로 계속 진행"을 권장**한다:

- 이유: turn 1이 LLM으로 성공했는데 turn 2 판단만 실패했다고 해서
  인터뷰를 1턴 만에 끝내면, 사용자가 겨우 한 번 답했는데 바로 끝나
  당황스러울 수 있다. "일단 약속한 3턴까지는 진행한다"는 쪽이 더
  예측 가능한 경험이다.
- 대안(완료로 fallback)도 코드상 똑같이 간단하므로, 실제 구현 확정
  직전에 다시 한 번 결정해도 된다 - 이 설계 문서는 "권장안 + 대안"을
  모두 기록해 둔다.

## 8. 직접입력 보호

**구조적으로 이미 안전하다** — Phase 2 코드를 다시 확인한 결과:

```python
# scripts/run_scout_dashboard.py, handle_turn_answer_submission() (Phase 2, 기존)
if option == "D":
    custom_answer = (form.get("custom_answer", [""])[0] or "").strip()
    ...
```

`custom_answer`는 **폼 제출 시점에 딱 한 번, 동기적으로** 세션에
기록된다. 그 다음 턴을 위한 LLM 호출(`decide_next_turn`)은 이 값을
**입력으로만** 사용하고(3번 `previous_turns[].user_answer_text`), 그
호출의 응답 스키마(4번) 어디에도 "기존 턴의 custom_answer를 다시 써서
돌려주는" 필드 자체가 없다. 즉 **LLM이 사용자의 직접입력 원문을 고쳐서
돌려줄 수 있는 코드 경로가 애초에 존재하지 않는다** - 설계 자체가
차단한다.

- 요약/교정/재작성/번역/정제 전부 하지 않는다: 어떤 Phase 3 코드도
  `custom_answer` 필드에 값을 "생성"해서 대입하지 않는다. 유일하게
  값을 쓰는 곳은 `handle_turn_answer_submission()`의 `.strip()` 한 줄뿐
  이다(Phase 2와 동일).
- **whitespace 처리**: Phase 2와 완전히 동일하게 앞뒤 공백만 제거한다
  (`.strip()`). Phase 3에서 이 동작을 바꿀 이유가 없으므로 그대로 둔다 -
  "Phase 2 현재 구현과의 호환성"을 기준으로 검토한 결과 변경 불필요.

## 9. perspective_summary 정책

**원칙: SUMMARY = USER ANSWERS ONLY.** SOURCE FACT는 맥락으로만 쓰고,
사용자의 생각으로 둔갑시키지 않는다.

- 시스템 프롬프트(설계 초안)에 명시할 문장:
  > "perspective_summary는 previous_turns[].user_answer_text에 있는
  > 내용만 요약해야 한다. scout.source_fact의 사실·숫자·주장을
  > 사용자가 말한 것처럼 쓰지 마라. 사용자가 언급하지 않은 경험, 숫자,
  > 사실, 주장을 추가하지 마라."
- **자동 검증(선택, 1차 구현에는 넣지 않는 것을 권장)**: `content_engine
  /rewrite.py`의 `RewriteValidator._new_number_errors`와 비슷한 방식으로
  `perspective_summary`에 사용자 답변 텍스트에 없는 숫자가 새로 등장하면
  거부하는 검사를 추가할 수 있다(문자 그대로 재사용은 안 됨 -
  `ContentDraft`에 강결합된 코드라 8-1처럼 재사용 불가, **패턴만** 참고).
  다만 **1차 구현에서는 넣지 않는 것을 권장**한다: 어차피 review
  화면에서 사람이 finalize 전에 반드시 확인하므로(이미 존재하는 안전
  장치), 자동 검사까지 추가하는 것은 이번 규모에서 과도한 방어 로직일
  수 있다. 실사용 중 문제가 관찰되면 그때 추가한다.

## 10. KNOWLEDGE 연결 방식

`perspective_summary`를 KNOWLEDGE에 넣을지 세 가지 방식을 비교했다.

| 방식 | 설명 | 장점 | 단점 |
|---|---|---|---|
| (a) `USER ORIGINAL THOUGHT`에 합쳐 넣기 | `_build_combined_answer_text()`의 텍스트 끝에 "관점 요약: ..." 추가 | 스키마 변경 없음 | 사용자의 원문(raw Q&A)과 AI가 쓴 요약이 같은 필드 안에 섞여, "USER ORIGINAL THOUGHT"라는 이름의 정직성이 흐려짐 |
| (b) 새 evidence 줄로 분리(`answers.py`/`knowledge_bridge.py` 확장) | 최초 5-10 설계 문서의 "Option 2"(`follow_up` 필드)처럼 새 라벨(`AI PERSPECTIVE SUMMARY:` 등)로 명확히 구분 | 사실/사용자원문/AI요약이 evidence 안에서도 라벨로 분리됨 | 스키마 변경 필요(이번 단계 금지 대상은 아니지만 범위가 커짐), "AI가 쓴 문장"이 KNOWLEDGE에 들어가는 것 자체가 부담 |
| (c) KNOWLEDGE에는 아예 넣지 않고 review 화면 UI에만 표시 | finalize는 Phase 2의 `_build_combined_answer_text()`를 **그대로** 사용, `perspective_summary`는 사람이 finalize 여부를 결정할 때 참고하는 화면 보조 정보로만 사용 | KNOWLEDGE에는 여전히 "사람이 실제로 답한 원문"만 들어감(이번 프로젝트 전체를 관통하는 원칙: "USER ORIGINAL THOUGHT는 절대 축약·대체되지 않는다"와 완전히 일치) | perspective_summary가 나중에 콘텐츠 작성 시 참고 자료로 남지 않음 |

**권장: (c).** `handle_finalize()`/`_build_combined_answer_text()`는
**전혀 수정하지 않는다** — KNOWLEDGE의 `USER ORIGINAL THOUGHT`에는
지금처럼 사용자가 실제로 고른/입력한 답변만 들어간다.
`perspective_summary`는 `InterviewSession`(이미 Phase 1부터 필드로
존재)에 저장되고, review 화면에만 표시되는 "AI가 지금까지 파악한 요약,
참고용"으로 취급한다. 나중에 (b)가 필요하다고 판단되면 그때 별도 단계로
`answers.py`/`knowledge_bridge.py`를 검토한다 - 지금 스키마를 키우지
않는다(11번 지시 그대로).

## 11. 보안

- API key는 **환경변수**(`TAK_MEDIA_LLM_API_KEY`)에서 **서버 프로세스
  안에서만** 읽는다(`InterviewLLMProvider.from_environment()`) - 기존
  `OpenAICompatibleRewriteProvider.from_environment()`와 동일한 방식.
- Dashboard는 `http.server` 기반이라 브라우저에 전달되는 것은 HTML/JS
  뿐이고, 이 안에 API key가 들어갈 코드 경로 자체가 없다(브라우저 쪽
  JS는 폼 제출만 한다 - Phase 2와 동일 구조를 그대로 유지).
- **에러 페이지 노출 방지**: `LLMResponseError`/`LLMConfigurationError`
  메시지를 그대로 사용자 화면에 보여주지 않는다. `InterviewLLMProvider`
  내부에서 실패를 잡아 `None`을 반환하므로, 애초에 이 예외 메시지가
  Dashboard의 HTTP 응답까지 도달하지 않는다(구조적으로 차단 - 사람이
  실수로 `except` 블록을 지워도 최소한 서버 로그(`stderr`)에만 남고
  HTTP 응답 바디에는 안 나가도록, "예외를 잡아 로그만 남기고 None 반환"
  하는 경계를 provider 클래스 경계 자체로 강제한다).
- `_safe_http_error_message`처럼 OpenAI 오류 응답 중 허용된 필드
  (`message`/`type`/`code`/`param`)만 로그에 남기는 방식을 그대로 따라
  구현한다(같은 관례, 코드는 새로 작성 - 2-2 참고).

## 12. 비용/호출 횟수

| 시점 | 호출 여부 | 누적 |
|---|---|---|
| Turn 1 생성 | `generate_first_question` 1회(provider 설정된 경우만) | 최대 1 |
| Turn 1 답변 후 판단 | `decide_next_turn` 1회 | 최대 2 |
| Turn 2 답변 후 판단(Turn 2가 있었을 때만) | `decide_next_turn` 1회 | 최대 3 |
| Turn 3 답변 후 | **호출 안 함**(무조건 완료, 8번) | 최대 3 유지 |

**인터뷰 1건당 최대 3회, 최선의 경우(1턴만에 충분) 2회.** 요청받은
"최대 3회 이내"를 정확히 만족한다.

**중복 호출 방지**: `decide_next_turn`은 `handle_turn_answer_submission()`
안에서, 턴이 "미답변 → 답변됨"으로 바뀌는 **그 순간에만** 호출된다(Phase
2에 이미 있는 멱등성 가드 재사용: `if current_turn.selected_option is not
None: return session, None`이 먼저 실행되므로, 새로고침/중복 클릭으로
같은 턴에 또 POST가 와도 그 턴을 다시 처리하지 않고, 당연히
`decide_next_turn`도 다시 부르지 않는다). GET 요청(페이지 조회)은
어떤 경우에도 LLM을 호출하지 않는다 - Phase 2와 동일 원칙.

## 13. 테스트 전략

**실제 API를 호출하는 테스트는 만들지 않는다.** `content_engine`의
`OpenAICompatibleRewriteProvider.transport`처럼, `InterviewLLMProvider`도
`transport: Callable`을 주입받게 설계해 테스트에서 가짜 응답을 만드는
함수로 교체한다(이미 이 프로젝트의 검증된 패턴 - `_http_transport`를
대체하는 방식).

| 요청 항목 | 테스트 방법(제안) |
|---|---|
| LLM 성공 | fake transport가 유효한 JSON 반환 → `generate_first_question`/`decide_next_turn`이 올바른 객체 반환 |
| LLM 실패 fallback | fake transport가 예외 발생 → `None` 반환 → Dashboard 쪽에서 `_build_template_turn` 사용 확인(HTTP 통합 테스트) |
| malformed JSON | fake transport가 `"not json"` 반환 → `None` |
| sufficient=true | fake transport가 `{"sufficient": true, "perspective_summary": "..."}` 반환 → 세션이 3턴 미만에서 `status="completed"`로 바뀌는지(HTTP 통합 테스트) |
| sufficient=false | 다음 질문 필드가 채워진 응답 → 다음 turn이 정확히 그 내용으로 생성되는지 |
| D 강제 | fake transport가 `"option_d": "그만 물어봐"` 같은 변조값 반환 → 실제 저장된 turn의 `option_d`는 항상 `"직접 입력"`인지 |
| 3턴 제한 | turn 3 답변 후 `decide_next_turn`이 **호출되는지 여부**를 fake transport 호출 횟수 카운터로 확인(0회여야 함) |
| 직접입력 원문 보존 | D로 특수문자/긴 문장을 입력 → 세션의 `custom_answer`가 100% 동일한지(LLM 응답과 무관하게) |
| API key 미설정 | 환경변수 없이 `from_environment()` 호출 → `LLMConfigurationError` → 호출부는 `None` 취급하고 fallback |
| API error | fake transport가 HTTP 500류 예외 발생 → `None` |
| 기존 session 복원 | Phase 2 테스트(`test_session_survives_server_restart`)와 동일 패턴을 LLM 경로에도 적용 - 세션 파일에 `generated_by="llm"`인 turn이 저장된 채로 서버를 재기동해도 그대로 복원되는지 |
| LLM 중복 호출 방지 | fake transport에 호출 횟수 카운터를 두고, 같은 턴에 대해 두 번 POST(중복 제출)해도 카운터가 1 이상 늘지 않는지 |

Dashboard HTTP 통합 테스트(Phase 2의 `DashboardMultiTurnHttpTests`
패턴)에서 가짜 provider를 주입하려면, `make_handler_class(config)`가
provider도 함께 받을 수 있어야 한다 — 예:
`make_handler_class(config, llm_provider=FakeInterviewLLMProvider(...))`
처럼 선택적 인자를 추가하는 것을 제안한다(Phase 3 구현 시 결정, 이번
설계에서는 필요성만 짚어 둔다 - `test_media_batch.py`가 이미
`run_media_batch(records, provider=CustomProvider())`로 이 패턴을
쓰고 있어 낯설지 않다).

## 14. 예상 변경 파일 (다음 구현 단계에서, 이번 단계 아님)

**신규**

- `tak_scout/interview_llm.py` — `InterviewLLMProvider`, `FollowUpDecision`
- `tests/test_interview_llm.py` — 12개 시나리오(13번), fake transport만 사용

**수정 예정**

- `scripts/run_scout_dashboard.py`:
  - `get_or_start_session()`: turn 1 생성 시 LLM 우선 시도, 실패 시
    `_build_template_turn(1)`
  - `handle_turn_answer_submission()`: 턴 완료 후 `decide_next_turn` 호출
    지점 추가. **여기서 Phase 2와의 실질적 동작 차이가 생긴다** — Phase
    2는 항상 정확히 3턴이었지만, Phase 3는 LLM이 `sufficient=true`라고
    판단하면 1~2턴 만에도 완료될 수 있다(2번 목표 구조 자체가 그렇다).
    이 변경은 사용자 경험상 "완료 조건이 유동적으로 바뀐다"는 의미라,
    review 화면에 "AI가 충분하다고 판단해 인터뷰를 마쳤습니다" 같은 안내
    문구를 추가하는 것을 함께 고려해야 한다(16번 위험요소).
  - `render_review_html()`: `perspective_summary`가 있으면 화면에 표시
    (KNOWLEDGE에는 안 들어감, 10번)
  - `make_handler_class()`: 테스트용 provider 주입 지점 추가(13번)
- `tests/test_scout_dashboard.py`: LLM 경로에 대한 HTTP 통합 테스트 추가
  (fake provider 주입)

**변경 없음**(이번 단계 금지 목록 + 실제로도 변경이 불필요함을 확인)

- `tak_scout/interview.py`, `tak_scout/answers.py`,
  `tak_scout/knowledge_bridge.py`, `tak_scout/interview_session.py`
- `content_engine/*` 전체
- 실제 데이터 파일 전부
- `.github/workflows/*`

## 15. 구현 순서 (제안)

1. **`tak_scout/interview_llm.py` + 테스트만 먼저.** Dashboard를 전혀
   건드리지 않으므로 회귀 위험이 0에 가깝다. fake transport로 12개
   시나리오를 전부 검증한 뒤 다음 단계로.
2. **Turn 1만 LLM 연결.** `get_or_start_session()`에만 LLM 시도를
   추가하고, Turn 2/3은 계속 Phase 2 고정 템플릿으로 둔다. 가장 작은
   변경으로 "AI가 첫 질문을 만든다"는 가치를 먼저 검증한다.
3. **후속 질문 + 조기 완료 로직 연결.** `decide_next_turn`을
   `handle_turn_answer_submission()`에 연결한다. 여기서부터 "3턴이 아닐
   수도 있다"는 UX 변화가 생기므로, 리뷰 화면 안내 문구도 함께 추가한다.
4. **review 화면에 perspective_summary 표시**(UI 전용, KNOWLEDGE 무관).
5. (선택, 별도 승인 필요) perspective_summary를 KNOWLEDGE evidence에
   포함할지(10번의 (b) 방식)는 실사용 후 재검토.

각 단계마다 `python3 -m unittest discover -s tests -p 'test_*.py'`로
전체 테스트가 통과하는지 확인하고 다음 단계로 넘어가는 것을 권장한다
(Phase 1/2에서 이미 해 온 방식 그대로).

## 16. 위험요소

1. **완료 조건이 유동적으로 바뀜**(14번) — Phase 2는 "항상 3턴", Phase 3는
   "AI가 충분하다면 더 일찍 끝날 수 있음". UI 안내 없이 배포하면 사용자가
   "왜 1턴만에 끝났지?"라고 혼란스러울 수 있다 — review 화면에 이유를
   명시해야 한다.
2. **LLM이 만든 선택지 품질을 자동으로 검증할 수 없음** — 이상한 질문이
   나와도(문법은 맞지만 소재와 안 맞는 등) 9번 길이 체크 정도만 걸러낼
   수 있고, 내용 적합성은 사람이 review 화면에서 확인해야 한다(기존에도
   있는 안전장치 - finalize 전 사람 확인).
3. **테스트에서 fake provider를 주입할 지점이 필요**(13번) — 이 DI
   지점을 설계 단계에서 미리 정하지 않으면, 나중에 실제 구현 시 테스트
   코드가 네트워크를 진짜로 호출하거나 monkeypatch에 의존하게 될 위험이
   있다. `make_handler_class(config, llm_provider=...)` 같은 선택적
   인자를 처음부터 넣는 것을 권장.
4. **"다시 답변하기"를 반복하면 LLM 호출이 누적될 수 있음** — 매 restart는
   최대 3회의 새 호출을 유발할 수 있다. 사용자가 의도적으로 누르는
   행동이라 자동 발생은 아니지만, 비용 관점에서 인지하고 있어야 한다.
5. **소재 제목/요약에 담긴 텍스트가 프롬프트에 그대로 들어감** — 공개
   RSS(BBC Business, Hacker News)에서 온 것이라 위험도는 낮지만, 이론상
   이상한 문구가 섞인 기사 제목이 질문 생성에 영향을 줄 가능성은
   있다 - 다만 모든 단계(턴 선택, review 확인)에 사람이 개입하므로
   심각도는 낮다고 판단한다.

## 17. Phase 3 구현 완료 조건 (제안)

실제 구현 단계가 끝났다고 볼 수 있는 기준을 미리 정해 둔다.

1. 기존 284개 테스트가 전부 그대로 통과한다(Phase 2 템플릿 전용 경로가
   여전히 유효한 fallback으로 남아 있어야 함).
2. `tests/test_interview_llm.py`가 13번의 12개 시나리오를 전부
   커버하고, **실제 네트워크 호출이 전혀 없이** 통과한다.
3. `data/tak_brain_knowledge.json`/`data/tak_interview_answers.json`의
   스키마가 Phase 2와 동일하다(`answers.py`/`knowledge_bridge.py` 무변경
   확인).
4. API key가 어떤 HTTP 응답 바디나 에러 페이지에도 나타나지 않는다(수동
   확인 또는 테스트로 검증).
5. 운영 데이터를 건드리지 않는 격리된 환경에서, `--execute`류 플래그로
   실제 LLM을 1회 이상 호출해 본 뒤(5-5/5-6에서 해 온 방식과 동일하게)
   결과를 별도 보고서로 남긴다 - 이는 자동화 테스트가 아니라 수동 검증
   단계다.

---

## 최종 확인

- **코드 변경 없음**: 이번 단계에서 `.py` 파일을 하나도 만들거나 수정하지
  않았다. 새로 생긴 파일은 이 보고서(`docs/5-10_phase3_llm_design.md`)
  하나뿐이다.
- **실제 LLM 호출 없음**: 이번 단계 전체에서 네트워크 호출을 하지
  않았다.
- **운영 데이터 변경 없음**: `data/` 아래 어떤 파일도 읽거나 쓰지
  않았다.
- **git commit/push 없음**: `git status`만 확인했고 커밋하지 않았다.
