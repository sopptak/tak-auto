# 5-10 TAK SCOUT Interview 2.0 — 설계 단계

**이번 단계는 설계 전용이다. 코드는 한 줄도 수정하지 않았다.** 아래 모든
파일/함수 이름은 "다음 구현 단계에서 이렇게 하겠다"는 제안이며, 실제로
만들어지거나 바뀌지 않았다(`git status`로 확인 가능 — 이번 문서 추가
외에는 diff가 없다).

핵심 원칙(이번 설계 전체를 관통하는 기준): **"뉴스를 AI가 요약하는
시스템"이 아니라 "AI가 티몽을 인터뷰해서 티몽만의 관점을 뽑아내는
시스템"**이다. 그래서 이번 설계는 처음부터 끝까지 "LLM이 사실을 생성하지
않는다 / USER ORIGINAL THOUGHT는 절대 축약·대체되지 않는다"는 원칙을
지키는 방향으로만 확장 지점을 골랐다.

---

## 1. 현재 구조 분석

지시된 파일을 전부 읽었다. 핵심만 정리한다.

| 파일 | 역할 | 이번 설계와의 관계 |
|---|---|---|
| `tak_scout/models.py` | `ScoutCandidate` (scout_id, title, summary, source_url, published_at, source_name, category) | 그대로 재사용. 변경 불필요. |
| `tak_scout/interview.py` | `InterviewQuestion`(question, option_a~d) + `build_interview_question()` — **소재 1건당 고정 템플릿 질문 1개만** 만든다. 선택지는 항상 "긍정/부정/지켜본다/직접입력"으로 고정. | 1차 질문의 **안전한 fallback**으로 그대로 유지. 후속 질문은 이 모듈이 아니라 새 모듈에서 만든다(아래 4번). |
| `tak_scout/answers.py` | `InterviewAnswer`(scout_id, selected_option, custom_answer, answered_at) + `upsert_answer` — **scout_id 1개당 답변 1개**만 존재하는 구조(덮어쓰기). | **이 스키마와 함수는 손대지 않는다.** 멀티턴 결과를 "최종 합성된 답변 1개"로 만들어 여기 그대로 넣는다(5번 참고 — 가장 중요한 설계 결정). |
| `tak_scout/knowledge_bridge.py` | `build_knowledge_from_interview(candidate, answer)` — **`InterviewAnswer` 1개**를 받아 KNOWLEDGE 1건을 만든다. evidence에 `SOURCE FACT`/`SOURCE URL`/`USER ANGLE` 또는 `USER ORIGINAL THOUGHT`(D일 때) 3줄만 넣는다. | 이번 단계에서 인터페이스를 바꾸지 않는다. 9번에서 "지금 당장 안 바꿔도 되는 이유"와 "나중에 바꾸면 좋은 지점"을 둘 다 제시한다. |
| `tak_scout/scoring.py` | SCOUT SCORE(5-8). 인터뷰와 무관, 그대로 재사용. | 변경 없음. |
| `tak_scout/dashboard_state.py` | "관심 없음"만 저장하는 별도 파일(5-9). | 변경 없음. 인터뷰 세션과 독립적으로 공존한다(17번 참고). |
| `scripts/run_interview.py` | 터미널 CLI. `input()`으로 한 소재씩 A/B/C/D를 묻는다. | 이번 확장과 무관하게 계속 작동해야 하며, 건드릴 필요가 없다(질문 스키마 자체는 안 바꾸므로). |
| `scripts/apply_interview.py` | `append_scout_knowledge()`를 호출하는 얇은 CLI. | 그대로 재사용(9번). |
| `scripts/run_scout_dashboard.py` | 5-9에서 만든 Python 표준 라이브러리 `http.server` 기반 웹 서버. `render_question_html`, `handle_answer_submission` 등. | **다음 구현 단계에서 라우트를 추가**해야 한다(10번, 14번). 이번 설계 문서에서는 수정하지 않는다. |
| `tests/test_scout_interview.py`, `test_scout_answers.py`, `test_scout_knowledge_bridge.py`, `test_scout_dashboard.py` | 각각 258개 전체 테스트의 일부. 전부 위 스키마가 "소재 1개 = 질문 1개 = 답변 1개"라고 가정하고 짜여 있다. | 이 가정을 깨지 않는 것이 이번 설계의 최우선 제약이다. |
| 실제 `data/tak_interview_answers.json` | 현재 10건, 전부 `{scout_id, selected_option, custom_answer, answered_at}` 스키마. | 5번에서 이 스키마를 그대로 유지하는 이유를 설명한다. |
| 실제 `data/tak_brain_knowledge.json` | 21건(승인 5/대기 7/거절 9). scout 연동 11건 전부 evidence 3줄(SOURCE FACT/SOURCE URL/USER ANGLE 또는 ORIGINAL THOUGHT) 구조. | 9번에서 이 구조를 유지할지/확장할지 논의한다. |
| `content_engine/rewrite.py`, `llm_provider.py` | TAK MEDIA의 `RewriteProvider` 추상클래스(`rewrite(request: RewriteRequest) -> ContentDraft`, 메서드 1개뿐) + `OpenAICompatibleRewriteProvider`. | 8번에서 상세히 분석 — **재사용 불가 판정**. |
| 5-7 (`docs/5-7_operator_usability.md`), 5-9 (`docs/5-9_tak_scout_dashboard_mvp.md`) | "[이미 답변함]" 개념, Dashboard 라우팅/렌더링 패턴 | 그대로 계승(10번, 11번). |

---

## 2. 문제 정의

현재 인터뷰는 "소재 1건 → 질문 1개(항상 같은 4지선다 틀) → 답변 1개"로
끝난다. 이 구조의 한계:

1. 모든 소재가 "긍정적으로 본다 / 부정적으로 본다 / 지켜본다 / 직접입력"이라는
   **똑같은 4지선다**를 받는다 — 소재 내용과 무관하다.
2. 답변이 짧은 의견 한 줄로 끝나면 **"왜" 그렇게 생각하는지, 실제 경험이
   있는지**를 물어볼 방법이 없다 — 그래서 KNOWLEDGE의 `reusable_principle`이
   "이 경제 이슈를 긍정적으로 본다." 같은 얕은 문장에 그치는 사례가 실제
   운영 데이터에도 다수 있다(1번 표의 실제 예시 참고).
3. "티몽만의 관점과 경험"을 추출한다는 이 시스템의 존재 이유에 비해, 지금은
   사실상 "찬/반/중립 투표"에 가깝다.

이번 설계의 목표는 이 구조를 "1차 질문 → 답변 → (필요하면) 후속 질문 →
답변 → 충분성 판단 → 종료"로 확장하되, **기존 스키마/파이프라인을 깨지
않는** 방법을 찾는 것이다.

---

## 3. 목표 인터뷰 흐름

사용자가 제시한 STEP 1~8을 그대로 채택한다.

```
소재 선택 → 1차 질문(주제 맞춤형 A/B/C/D) → 답변
    → [AI가 충분성 판단]
        충분함 → STEP 8(최종 확인)로
        부족함 → 후속 질문(최대 2회 더, 총 3턴) → 답변 → 다시 판단
    → STEP 8: 소재/원문/답변들/AI가 파악한 핵심 관점/KNOWLEDGE 초안 표시
    → [이 내용으로 KNOWLEDGE 만들기] (사람이 눌러야 함, 자동 아님)
    → append_scout_knowledge (pending) → 사람 검토 → approved → TAK MEDIA
```

**최대 질문 수는 3개로 확정한다**(1차 + 후속 최대 2개). 근거:

- 사용자가 예시로 "최대 3개 정도"를 직접 제시했다.
- 후속 질문마다 LLM 호출이 1회 필요하므로(8번), 턴 수를 늘릴수록 비용과
  대기 시간이 늘어난다.
- "귀찮게 만들지 않는다"는 원칙과 직접 상충하는 요소라 상한을 낮게 잡는
  것이 안전하다.

---

## 4. 질문/선택지 설계

### 4-1. 1차 질문

**기존 `tak_scout.interview.build_interview_question()`을 기본 fallback으로
유지**하되, LLM이 사용 가능하면 소재별 맞춤 질문+선택지를 생성한다.

새 스키마(기존 `InterviewQuestion`과 필드명을 맞춰 호환성을 최대화):

```python
@dataclass(frozen=True)
class InterviewTurn:
    scout_id: str
    turn: int                    # 1, 2, 3
    question: str
    option_a: str
    option_b: str
    option_c: str
    option_d: str                 # 항상 "D. 직접 입력" 계열 고정 문구
    generated_by: str             # "template" | "llm"
```

`option_a/b/c`는 LLM이 소재 내용에 맞게 만든다(사용자 예시처럼 "AI 발전
속도를 어떻게 보십니까?"라면 "적극적으로 받아들여야 한다 / 규제가 필요하다 /
아직 판단하기 어렵다"처럼). **`option_d`는 절대 LLM이 만들지 않는다** — 코드가
항상 고정 문구("D. 직접 입력")를 강제로 덮어쓴다(4-3 참고).

### 4-2. 후속 질문

같은 `InterviewTurn` 스키마를 `turn=2, 3`에 재사용한다. 질문 생성 방식만
다르다(AI가 직전 답변을 보고 만든다 — 8번 참고).

### 4-3. D = 직접 입력 불변 규칙

세 가지를 코드 레벨 불변식으로 강제한다(설계 시점에 명시, 구현 시 반드시
지켜야 함):

1. `option_d` 텍스트는 질문 생성 함수(LLM이든 템플릿이든)의 출력값을
   그대로 쓰지 않는다. 생성된 결과에서 `option_d` 필드는 항상 무시하고,
   코드가 상수 `"D. 직접 입력"`으로 **덮어쓴다.**
2. `selected_option == "D"`일 때 `custom_answer`는 **LLM에 절대 통과시키지
   않는다** — 기존 `InterviewAnswer.create()`가 이미 이렇게 동작한다(요약/
   재작성 없이 원문 그대로 저장). 이 계약을 유지한다.
3. 최종 KNOWLEDGE의 `USER ORIGINAL THOUGHT`(또는 `FOLLOW-UP ANSWER`)에는
   사용자가 실제로 타이핑한 문자열이 **한 글자도 바뀌지 않고** 들어가야
   한다 — 5-3~5-6 단계에서 이미 여러 번 검증한 원칙을 그대로 유지한다.

---

## 5. 답변 schema

**가장 중요한 결정: `data/tak_interview_answers.json`의 스키마를 바꾸지
않는다.**

이유:

- `InterviewAnswer`는 `tak_scout.answers`, `tak_scout.knowledge_bridge`,
  `scripts/run_interview.py`, `scripts/apply_interview.py`,
  `scripts/tak_auto.py`(5-6), `scripts/run_scout_dashboard.py`(5-9) 전부가
  "scout_id 1개 = 답변 1개"라고 가정하고 만들어져 있다. 여기를 바꾸면
  거의 모든 기존 모듈에 손을 대야 한다 — "TAK BRAIN 구조를 임의로 변경하지
  말 것"이라는 이번 단계 제약과 정면으로 충돌한다.
- 대신 **멀티턴 원본 데이터는 새 파일(6번)에 그대로 보관**하고, 인터뷰가
  "충분하다"고 끝나는 시점에만 **합성된 답변 1개**를 만들어 기존
  `InterviewAnswer.create(scout_id, "D", combined_text)` + `upsert_answer()`를
  **그대로** 호출한다.
- `selected_option`은 항상 `"D"`로 합성한다 — 멀티턴 결과는 태생적으로
  "직접 입력"에 가깝다(1차 답변이 A/B/C였더라도, 후속 답변까지 합치면 단순
  4지선다로 표현할 수 없는 내용이 되기 때문). `custom_answer`에는 턴별
  질문/답변을 사람이 읽기 좋은 형태로 이어붙인 텍스트를 넣는다. 예:

  ```
  Q1. 이 이슈에 대해 어떻게 생각하시나요?
  A1. 신기술은 두려워 말고 부딪혀서 느껴봐야 한다.

  Q2. 실제로 AI를 사용하면서 비슷하게 느낀 경험이 있나요?
  A2. AI를 직접 사용해보지 않으면 실제 위험과 가능성을 알기 어렵다.
  ```

  (정확한 포맷은 구현 단계에서 확정. 핵심은 **사용자가 실제로 쓴 문장을
  한 글자도 바꾸지 않고 그대로 잇는 것** — LLM 재작성/요약 없음.)
- 결과적으로 `tak_interview_answers.json`을 읽는 기존 코드(`load_answers`,
  `apply_interview.py`, 5-6/5-7/5-9의 모든 로직)는 **한 줄도 안 바꿔도
  된다.** 이것이 "기존 answers.py와의 호환 방법"에 대한 최종 답이다.

**대안 검토(기각)**: `InterviewAnswer`에 `follow_up_answers: tuple[str, ...] = ()`
같은 필드를 바로 추가하는 방법도 검토했다. 기존 JSON에 이 필드가 없어도
`from_dict`가 기본값(`()`)을 쓰면 하위 호환은 유지된다. 하지만 이러면
`build_knowledge_from_interview`도 함께 손대야 KNOWLEDGE에 반영되므로,
"이번 단계에서 코드 수정 금지"라는 제약과 "TAK BRAIN 구조를 임의로 바꾸지
말 것"이라는 제약을 모두 지키려면 **이번 설계에서는 채택하지 않는다.**
9번에서 "나중에 하면 좋은 확장"으로 별도로 기록한다.

---

## 6. Session schema

멀티턴 원본을 보관할 **새 파일**이 필요하다: `data/tak_interview_sessions.json`
(요청에서 예시로 든 이름 그대로 채택).

```python
@dataclass(frozen=True)
class InterviewSession:
    scout_id: str
    status: str                      # "in_progress" | "completed"
    turns: tuple[InterviewTurnRecord, ...]
    perspective_summary: str         # AI가 파악한 티몽의 핵심 관점 (없으면 "")
    created_at: str
    updated_at: str
    completed_at: str | None

@dataclass(frozen=True)
class InterviewTurnRecord:
    turn: int
    question: str
    option_a: str
    option_b: str
    option_c: str
    option_d: str
    generated_by: str                # "template" | "llm"
    selected_option: str | None      # 아직 답 안 했으면 None
    custom_answer: str
    answered_at: str | None
```

`tak_scout.answers`와 완전히 같은 패턴(`load_sessions`/`save_sessions`/
`upsert_session`, 원자적 쓰기)으로 새 모듈 `tak_scout/interview_session.py`에
만든다. **scout_id 1개당 세션 1개**(같은 upsert 원칙), 리스트를 JSON 배열로
저장 — 기존 `tak_interview_answers.json`/`tak_scout_dashboard_skipped.json`과
동일한 파일 형태이므로 사람이 봐도 구조가 낯설지 않다.

이 파일은 `tak_interview_answers.json`을 대체하지 않는다 — **원본(세션)과
최종 산출물(답변)을 분리**하는 것이 이번 설계의 핵심이다.

---

## 7. 후속 질문 로직

### 7-1. 충분성 판단 기준(사용자가 제시한 기준을 그대로 채택)

다음 중 하나라도 해당하면 후속 질문을 권장한다:

- 의견만 있고 이유가 없음
- 일반적인 말뿐임(예: "긍정적으로 본다"에서 멈춤)
- 실제 경험이 없음(경험/사례 언급 없음)
- 구체적인 사례가 없음
- 원문 내용과 사용자 의견의 연결이 약함

다음이면 종료한다:

1. 최대 질문 수(3) 도달 — **LLM 판단과 무관하게 코드가 강제 종료**한다.
2. AI가 "충분하다"고 판단
3. 사용자가 명시적으로 "완료하기"를 선택(항상 노출되는 탈출구, 1차 답변
   직후부터 가능 — 사용자를 인터뷰에 가두지 않는다)
4. (드묾) 추가 질문의 가치가 낮다고 AI가 판단

### 7-2. 판단 + 다음 질문 생성을 한 번의 LLM 호출로 묶는다

비용/지연을 줄이기 위해, "충분한가?"와 "다음 질문은 무엇인가?"를 별도
호출 2번이 아니라 **JSON 응답 1개**로 함께 받는다:

```json
{
  "sufficient": false,
  "perspective_summary": "지금까지 파악한 티몽의 핵심 관점 한 줄",
  "next_question": {
    "question": "실제로 AI를 사용하면서 비슷하게 느낀 경험이 있나요?",
    "option_a": "있다, 직접 활용해봤다",
    "option_b": "아직 없다",
    "option_c": "간접적으로만 접했다"
  }
}
```

`sufficient: true`면 `next_question`은 없어도 된다(있어도 무시).

### 7-3. 결정적 보호장치(코드 레벨, LLM을 신뢰하지 않는 부분)

- turn == 3에 도달하면 **LLM을 아예 호출하지 않고** 강제로 `sufficient=true`
  처리한다(호출 자체를 생략 — 비용도 아낀다).
- LLM 응답이 스키마와 안 맞거나(JSON 파싱 실패, 필수 키 없음), 호출 자체가
  실패하면(`LLMConfigurationError`/`LLMResponseError`/네트워크 오류)
  **즉시 `sufficient=true`로 처리하고 이미 받은 답변만으로 STEP 8로
  넘어간다.** 사용자가 이미 입력한 내용은 그대로 세션에 남아 있으므로
  아무것도 잃지 않는다.
- 같은 턴에 대해 이미 질문이 생성되어 세션에 저장되어 있으면(페이지
  새로고침, 중복 클릭 등) **다시 LLM을 호출하지 않고** 저장된 질문을 그대로
  보여준다(9-3, 12번 참고).

---

## 8. LLM 사용 전략

### 8-1. 기존 `content_engine`의 `RewriteProvider`를 재사용할 수 있는가? — **아니오, 그대로는 불가능하다**

`content_engine/rewrite.py`의 `RewriteProvider`는 추상 메서드가
`rewrite(self, request: RewriteRequest) -> ContentDraft` **하나뿐**이다.
`OpenAICompatibleRewriteProvider.rewrite()`를 직접 읽어 확인한 결과:

- 입력이 `RewriteRequest`(이미 만들어진 `ContentDraft` + `KnowledgeRecord`)로
  **고정**되어 있다. 인터뷰 질문 생성에는 애초에 `ContentDraft`/`KnowledgeRecord`가
  존재하지 않는다(인터뷰가 끝나야 KNOWLEDGE가 생기므로 순서가 거�로다).
- system prompt가 "한국어 콘텐츠를 사실 경계 안에서 재작성하라"는 내용으로
  **하드코딩**되어 있다 — 질문을 만들라는 지시가 전혀 아니다.
  (`_system_prompt()`, `_user_prompt()` 참고)
- 응답 파싱(`_draft_from_response`)이 `{title, body}` 형태를 받아
  `dataclasses.replace(original_draft, title=..., body=...)`로 **원본 Draft
  객체에 이어붙이는 구조**다. 인터뷰 질문은 `ContentDraft`가 아니므로 이
  경로 자체가 성립하지 않는다.

**결론**: `RewriteProvider`/`OpenAICompatibleRewriteProvider` 클래스 자체는
재사용할 수 없다. 이 사실을 명확히 기록해 둔다(요청사항 A번).

### 8-2. 무엇을 재사용할 수 있는가

- **환경변수 이름과 관례**: `TAK_MEDIA_LLM_API_KEY`/`TAK_MEDIA_LLM_ENDPOINT`/
  `TAK_MEDIA_LLM_MODEL`을 그대로 쓴다. 새 시크릿을 추가하지 않는다(운영
  편의).
- **예외 타입**: `content_engine.LLMConfigurationError`,
  `content_engine.LLMResponseError`를 그대로 **import해서 재사용**한다(같은
  실패 상황을 같은 이름으로 표현 — 클래스 정의만 가져다 쓰는 것이라
  `content_engine`을 수정하지 않고도 안전하게 재사용 가능).
- **HTTP 호출 패턴**: `urllib.request` 기반의 단순 POST 호출(`_http_transport`와
  같은 모양)은 **패턴만** 그대로 따라 새로 작성한다. `content_engine`의
  `_http_transport`는 모듈 비공개 함수라 import해서 공유할 수 없고, 억지로
  공유 가능하게 만들려면 `content_engine/llm_provider.py`를 수정해야 하는데
  이는 "기존 TAK MEDIA 코드 수정 금지"에 위배된다. 그래서 이번 설계는
  **새 파일에 짧은(약 20~30줄) HTTP 호출 함수를 하나 더 만드는 쪽**을
  권장한다(중복이지만, TAK MEDIA를 건드리지 않는 것이 이번 제약상 더 안전).

### 8-3. 새 모듈 제안: `tak_scout/interview_llm.py`

```python
class InterviewLLMProvider:  # RewriteProvider를 상속하지 않는다(계약이 다름)
    @classmethod
    def from_environment(cls) -> "InterviewLLMProvider": ...
    def generate_first_question(self, candidate: ScoutCandidate) -> InterviewTurn: ...
    def decide_next_turn(
        self, candidate: ScoutCandidate, turns_so_far: tuple[InterviewTurnRecord, ...]
    ) -> "FollowUpDecision":  # sufficient, perspective_summary, next_question(optional)
        ...
```

이 provider가 없거나(`LLMConfigurationError`) 실패하면, 호출부는 다음으로
대체한다:

- `generate_first_question` 실패 → 기존 `tak_scout.interview.build_interview_question()`
  그대로 사용(완전한 fallback, 지금 운영 중인 동작과 100% 동일).
- `decide_next_turn` 실패 → `sufficient=true`로 간주(7-3 참고).

즉 **LLM 없이도 전체 시스템이 100% 작동한다**(1차 질문은 기존 템플릿,
후속 질문은 아예 없이 1턴으로 끝남 — 지금의 동작과 동일). LLM은 "있으면
더 좋아지는" 계층으로 설계한다.

### 8-4. 비용/중복 호출 방지

- 소재 1건당 **최대 2회**의 LLM 호출만 발생한다(1차 질문 생성 1회 + 2턴째
  진입 시 판단 1회. 3턴째는 무조건 마지막이라 판단 호출 자체가 없음 — 즉
  "1차 질문 + 최대 2번의 판단"이 아니라 "1차 질문 1회 + 판단 최대 1회"이며,
  요청서의 "최대 3회 정도" 기준보다도 더 보수적이다).
- 세션에 이미 해당 턴이 기록되어 있으면 다시 호출하지 않는다(멱등성 —
  9번 항목의 "중복 호출 방지" 요구를 세션 상태 확인으로 만족시킨다).
- API 키는 **브라우저에 절대 노출되지 않는다** — 애초에 5-9 Dashboard
  구조상 모든 LLM 호출은 Python 서버 프로세스 안에서만 일어나고, 브라우저는
  폼 제출(HTML/JS)만 한다. 이 구조를 그대로 유지하면 별도 조치 없이
  자동으로 만족된다.

---

## 9. KNOWLEDGE 연결

### 9-1. 이번 단계(변경 없음, Option 1)로도 되는 이유

5번에서 설명한 것처럼, 멀티턴 결과를 합성한 텍스트 1개를 기존
`InterviewAnswer(selected_option="D", custom_answer=합성텍스트)`로 만들면,
`tak_scout.knowledge_bridge.build_knowledge_from_interview()`는 **지금
코드 그대로** 다음을 만든다:

```
SOURCE FACT: <원문 요약, 변경 없음>
SOURCE URL: <원문 URL, 변경 없음>
USER ORIGINAL THOUGHT: <Q1/A1, Q2/A2, Q3/A3를 이어붙인 텍스트>
```

`knowledge_bridge.py`를 단 한 줄도 안 바꿔도 pending KNOWLEDGE가 그대로
만들어진다. **가장 안전한 경로**이며, 이번 설계가 1차로 권장하는 방식이다.

### 9-2. 더 정확한 구조(Option 2, 다음다음 단계 제안)

사용자가 4번 섹션에서 보여준 예시처럼 `FOLLOW-UP ANSWER:` 줄을 evidence에
개별적으로 남기고 싶다면, 아래처럼 **작고 하위 호환되는** 확장이 필요하다
(이번 단계에서 구현하지 않음, 설계만 기록):

```python
# tak_scout/answers.py — 새 필드 추가(기본값 있어 하위 호환 유지)
@dataclass(frozen=True)
class InterviewAnswer:
    scout_id: str
    selected_option: str
    custom_answer: str
    answered_at: str
    follow_up: tuple[tuple[str, str], ...] = ()  # [(질문, 답변), ...]

    @classmethod
    def from_dict(cls, data):
        ...
        follow_up = tuple(tuple(pair) for pair in data.get("follow_up", []))  # 없으면 빈 튜플
        ...
```

기존 `tak_interview_answers.json`의 10건에는 `follow_up` 키가 없지만,
`.get("follow_up", [])`로 읽으므로 **에러 없이 빈 튜플로 로드된다** —
완전한 하위 호환. 이 필드가 채워져 있으면 `knowledge_bridge.py`의
`build_knowledge_from_interview`가 evidence에 다음을 추가로 넣는다:

```
FOLLOW-UP Q: 실제로 AI를 사용하면서 비슷하게 느낀 경험이 있나요?
FOLLOW-UP ANSWER: AI를 직접 사용해보지 않으면 실제 위험과 가능성을 알기 어렵다.
```

**이번 단계 권고**: 먼저 9-1(변경 없음) 방식으로 구현하고 실제로 며칠
써 본 뒤, KNOWLEDGE의 "합쳐진 텍스트"가 읽기 불편하거나 TAK MEDIA 재작성
품질에 문제가 생기면 그때 9-2를 별도 단계로 진행한다. 지금 두 가지를
한꺼번에 설계·구현하면 위험이 커진다.

### 9-3. 승인 원칙 불변

두 방식 모두 KNOWLEDGE는 항상 `knowledge_review_status="pending"`으로
생성된다. **자동 승인은 어떤 경우에도 하지 않는다** — `review_knowledge.py
--approve`는 계속 사람이 누른다.

---

## 10. Dashboard UX

5-9의 라우트 구조를 그대로 확장한다(교체 아님).

```
GET  /                              오늘의 소재 목록(5-9, 변경 없음)
GET  /candidate/{scout_id}          세션이 없으면 turn 1 생성 후 표시.
                                     세션이 IN_PROGRESS면 "아직 답 안 한 턴"을
                                     표시. COMPLETED면 결과 화면으로 안내.
POST /candidate/{scout_id}/answer   현재 턴 답변 저장 → 세션 갱신
                                     → (turn<3 and not sufficient) 다음 턴 생성
                                       후 같은 화면 계속
                                     → 아니면 review 화면으로 303 리다이렉트
GET  /candidate/{scout_id}/review   STEP 8 최종 확인 화면
POST /candidate/{scout_id}/finalize [KNOWLEDGE 만들기] 처리(9-1의 합성 로직
                                     + append_scout_knowledge 호출)
POST /candidate/{scout_id}/skip     관심 없음(5-9, 변경 없음)
```

**"완료하기" 탈출구**: 질문 화면에 매 턴 `[완료하고 결과 보기]` 버튼을
항상 함께 노출한다(사용자가 3턴을 다 채우지 않아도 STEP 8로 바로 이동
가능). 이는 7-1의 종료 조건 3번을 만족한다.

**review 화면(STEP 8)** 구성(요청 그대로):

```
소재: <제목>
원문: <link>
Q1/A1, Q2/A2, Q3/A3 (있는 만큼만)
AI가 파악한 티몽의 핵심 관점: <perspective_summary>
생성될 KNOWLEDGE 미리보기:
  SOURCE FACT: ...
  USER ORIGINAL THOUGHT: ...(합성 텍스트 미리보기)

[이 내용으로 KNOWLEDGE 만들기]   [다시 답변하기]
```

`[다시 답변하기]`는 세션을 `turn=1`부터 다시 시작하게 한다(기존
`upsert_answer`/`upsert_session` 모두 덮어쓰기 방식이라 자연스럽게
지원됨 — 5-7에서 이미 검증한 "다시 답변" 패턴과 동일한 사용자 경험).

---

## 11. 상태 관리

요청된 상태 모델(`NOT_STARTED/QUESTIONING/WAITING_ANSWER/COMPLETED`)을
검토한 결과, 5-9 Dashboard가 **요청마다 파일을 새로 읽는 무상태(stateless)
서버**라는 점을 고려해 다음처럼 단순화할 것을 제안한다:

| 상태 | 저장 여부 | 판단 방법 |
|---|---|---|
| `NOT_STARTED` | 저장 안 함(암묵적) | 세션 파일에 해당 scout_id 항목이 없음 |
| `IN_PROGRESS` | 저장함 | 세션은 있지만 `status="in_progress"` |
| `COMPLETED` | 저장함 | `status="completed"`, `completed_at` 있음 |

"QUESTIONING"과 "WAITING_ANSWER"를 따로 두지 않는 이유: 서버가 상태를
메모리에 들고 있지 않고 **매 요청마다 세션 파일을 다시 읽어 "마지막 턴에
답이 있는가?"만 보고 판단**하기 때문에, 그 중간 상태를 명시적으로 저장할
필요가 없다 — 오히려 상태가 2개 더 있으면 파일과 실제 화면이 어긋날
위험(상태 불일치 버그)만 늘어난다.

**새로고침 안전성**: 매 턴의 답변을 저장한 직후 세션 파일에 바로
반영되므로(POST 처리 안에서 동기적으로 저장), `GET /candidate/{scout_id}`를
아무 때나 다시 호출해도 세션 파일을 다시 읽어 정확히 "지금까지 어디까지
진행됐는지"를 재구성할 수 있다. 서버가 재시작되어도 세션이 파일에 남아
있으므로 인터뷰가 끊기지 않는다(DB 없이도 이 요구를 만족한다).

---

## 12. 보안/비용

요청된 체크리스트를 하나씩 확인한다.

| 요구 | 설계에서 어떻게 만족하는가 |
|---|---|
| API key를 브라우저에 노출하지 않는다 | LLM 호출은 전부 `tak_scout/interview_llm.py`(서버 프로세스) 안에서만 일어난다. 브라우저는 HTML 폼 제출만 한다(5-9와 동일 구조). |
| LLM 호출은 Python 서버에서만 | 위와 동일. Dashboard가 `http.server` 기반이라 애초에 클라이언트 사이드 실행 환경이 없다. |
| 한 소재당 최대 3회 제한 | 7-3에서 코드 레벨로 강제(turn==3이면 LLM 호출 자체를 생략). 실제로는 최대 2회(1차 질문 1회 + 판단 1회)로 더 보수적이다(8-4). |
| 중복 호출 방지 | 세션에 해당 턴이 이미 있으면 재호출하지 않는다(7-3, 8-4). |
| LLM 실패 시 인터뷰를 잃지 않음 | 실패 즉시 `sufficient=true`로 처리해 이미 받은 답변까지만으로 STEP 8로 진행(7-3). 1차 질문 생성 실패는 기존 템플릿으로 완전히 대체(8-3). |
| 기존 answer 보존 | `tak_interview_answers.json`은 STEP 8에서 "완료"로 확정될 때만 갱신된다 — 진행 중인 세션이 기존 답변을 건드리지 않는다. |

---

## 13. 기존 코드 호환성

| 구분 | 상태 |
|---|---|
| `tak_scout/models.py` | 변경 없음 |
| `tak_scout/interview.py` | 변경 없음(1차 질문의 fallback으로 그대로 사용) |
| `tak_scout/answers.py` | 변경 없음(9-1 채택 시 영구히 없어도 됨. 9-2는 하위 호환 추가) |
| `tak_scout/knowledge_bridge.py` | 변경 없음(9-1 채택 시) |
| `tak_scout/scoring.py`, `dashboard_state.py` | 변경 없음 |
| `scripts/run_interview.py`, `apply_interview.py`, `run_scout.py`, `run_scout_score.py` | 변경 없음 |
| `content_engine/*`(TAK MEDIA 전체) | 변경 없음(8-1에서 재사용 불가 판정, 8-2에서 예외 클래스만 import) |
| `.github/workflows/*` | 변경 없음(이번 기능과 무관) |
| 기존 258개 테스트 | 전부 영향받지 않아야 한다(새 모듈만 추가하므로 이론상 회귀 위험 없음 — 15번에서 검증 계획) |

---

## 14. 변경 예정 파일 (다음 구현 단계에서, 이번 단계 아님)

**신규 파일**

- `tak_scout/interview_session.py` — `InterviewSession`/`InterviewTurnRecord` +
  load/save/upsert (6번)
- `tak_scout/interview_llm.py` — `InterviewLLMProvider`, fallback 로직 (8번)
- `data/tak_interview_sessions.json` — 런타임에 생성되는 데이터 파일
  (`.gitignore`의 `data/*.json`에 이미 포함되어 추가 설정 불필요)
- `tests/test_interview_session.py` — 세션 모듈 단위 테스트
- `tests/test_interview_llm.py` — fallback/파싱 실패 처리 테스트(실제
  네트워크 호출 없이 transport를 patch)

**수정 파일**

- `scripts/run_scout_dashboard.py` — 라우트 확장(10번). 5-9에서 우리가
  만든 파일이므로 "기존 TAK BRAIN/MEDIA 코드"에 해당하지 않는다.
- `tests/test_scout_dashboard.py` — 새 라우트에 대한 테스트 추가.

**조건부(9-2를 별도로 승인받을 때만)**

- `tak_scout/answers.py` (하위 호환 필드 추가)
- `tak_scout/knowledge_bridge.py` (evidence 렌더링 확장)
- 관련 테스트(`test_scout_answers.py`, `test_scout_knowledge_bridge.py`)

**절대 건드리지 않음**

- `content_engine/*` 전체
- `tak_brain/*` 전체(9-1 채택 시 `knowledge_bridge.py`도 포함해 전부 무변경)
- `.github/workflows/*`

---

## 15. 테스트 계획 (구현 단계에서 작성할 것, 이번엔 미작성)

1. `InterviewSession` round-trip(save→load), upsert가 scout_id 기준으로
   덮어쓰는지.
2. 세션 파일이 없을 때 `GET /candidate/{id}`가 turn 1을 생성하고
   `status="in_progress"`로 새 세션을 만드는지.
3. LLM 미설정(`LLMConfigurationError`) 상태에서 1차 질문이 기존
   `build_interview_question()` 결과와 **동일하게** 나오는지(진짜
   fallback 검증).
4. turn==3에서는 LLM `decide_next_turn`이 아예 호출되지 않는지(mock으로
   호출 횟수 0 확인).
5. LLM이 이상한 JSON을 반환해도 서버가 500을 내지 않고 `sufficient=true`로
   안전하게 처리하는지.
6. 완료(finalize) 후 `data/tak_interview_answers.json`에 정확히 1건만
   생기고, `selected_option="D"`이며, `custom_answer`에 모든 턴의 질문/답변
   원문이 한 글자도 안 바뀌고 들어있는지.
7. finalize가 기존 `append_scout_knowledge()`를 그대로 호출해 pending
   KNOWLEDGE가 생기는지(자동 승인 없는지 함께 확인).
8. "다시 답변하기"로 같은 소재를 재시작해도 세션/답변이 깨지지 않는지
   (upsert 재확인).
9. "완료하기" 버튼으로 turn 1만 답하고 바로 끝내도 정상적으로 review
   화면과 KNOWLEDGE 생성까지 이어지는지.
10. 회귀: 기존 258개 테스트 전부 재실행 — 특히 `test_scout_interview.py`,
    `test_scout_answers.py`, `test_scout_knowledge_bridge.py`,
    `test_scout_dashboard.py`가 그대로 통과하는지(모두 새 모듈을 참조하지
    않으므로 이론상 영향 없어야 함 — 실제로 확인 필요).

---

## 16. 구현 순서 (제안)

**Phase 1 — 세션 데이터 계층만** (LLM/Dashboard 변경 없음, 가장 안전)
`tak_scout/interview_session.py` + 테스트만 추가. 기존 어떤 기능도 바뀌지
않으므로 회귀 위험이 사실상 0이다.

**Phase 2 — LLM 없이 멀티턴 UX부터 증명**
Dashboard에 라우트를 추가하되, 후속 질문은 **결정론적 고정 템플릿**
1개("그렇게 생각하시는 이유가 무엇인가요? A.경험 때문에 B.정보/뉴스 때문에
C.직감적으로 D.직접입력" 같은 범용 질문)만 붙여서 "1차 질문 → 후속 질문 →
완료" 흐름 자체가 실제로 동작하는지 먼저 검증한다. LLM 비용/실패 위험
없이 UX를 먼저 확정할 수 있다.

**Phase 3 — LLM 기반 질문 생성 도입**
`tak_scout/interview_llm.py` 추가, Phase 2의 고정 템플릿을 LLM 결과로
교체하되 항상 fallback 유지. 여기서부터 실제 LLM 비용이 발생한다.

**Phase 4(선택, 별도 승인 필요) — KNOWLEDGE evidence 구조 확장**
9-2의 `follow_up` 필드 추가. Phase 1~3이 실사용으로 검증된 뒤에만 진행.

각 Phase 종료 시점마다 전체 테스트(`python3 -m unittest discover -s tests
-p 'test*.py'`)를 실행해 회귀가 없는지 확인하고 나서 다음 Phase로 넘어가는
것을 권장한다.

---

## 17. 발견된 위험/문제

1. **`RewriteProvider` 재사용 불가**(8-1) — 처음에 "기존 provider를 그대로
   쓸 수 있을 것"이라 가정했다면 잘못된 가정이었다. 새 provider를 별도로
   만들어야 하며, HTTP 호출 코드가 `content_engine`과 일부 중복된다(8-2).
   장기적으로는 `content_engine`에 공용 저수준 HTTP transport를 뽑아
   `tak_scout`와 공유하는 리팩터링을 고려할 수 있지만, 이는 "기존 TAK
   MEDIA 코드 수정"에 해당해 이번 범위 밖이다.
2. **멀티턴을 단일 `InterviewAnswer`로 우겨넣으면 정보가 손실될 수 있음** —
   9-1(변경 없음) 방식은 안전하지만, 턴 구분이 사라지고 하나의 텍스트
   블록이 된다. 사람이 나중에 KNOWLEDGE를 검토할 때 "어디까지가 1차 답변이고
   어디부터가 후속 답변인지" 구분하기 불편할 수 있다 — 9-2로 완화 가능하나
   이번 단계에서는 채택하지 않는다.
3. **LLM이 만드는 A/B/C 선택지 품질을 사람이 매번 확인할 수 없음** — 자동
   승인은 안 하지만, "선택지 자체가 소재와 안 맞게 나온" 경우를 걸러낼
   장치가 이번 설계에는 없다(KNOWLEDGE 승인 단계에서는 질문/선택지 자체가
   아니라 최종 텍스트만 보임). 구현 단계에서 세션 원문도 review 화면에
   같이 노출하므로(10번), 최소한 사람이 "이상한 질문에 답한 결과"임을
   확인할 기회는 있다.
4. **세션이 영원히 `in_progress`로 남는 경우** — 사용자가 답변 도중
   이탈하면 세션이 미완료 상태로 남는다. 문제라기보다는 정상 동작이다
   (다음에 같은 소재를 다시 열면 이어서 진행하면 됨) — 별도 정리(TTL,
   자동 만료 등)는 이번 설계에서 불필요하다고 판단했다.
5. **5-9의 "관심 없음"과 인터뷰 세션의 공존** — 이미 "관심 없음"으로
   표시한 소재를 나중에 다시 선택해 인터뷰를 시작하는 것은 5-9 설계상
   이미 허용되어 있다(다시 선택 가능). 충돌 없음, 별도 처리 불필요.

---

## 18. 최종 권고

1. **9-1(답변 스키마 변경 없음)을 채택**해 `tak_interview_answers.json`,
   `tak_scout/answers.py`, `tak_scout/knowledge_bridge.py`를 이번 확장에서
   전혀 건드리지 않는다. `follow_up` 필드 확장(9-2)은 실사용 후 필요성이
   확인되면 별도 단계로 진행한다.
2. **16번의 Phase 1부터 순서대로 구현**할 것을 권한다 — 특히 Phase 2(LLM
   없이 고정 템플릿 후속 질문)로 UX 자체를 먼저 검증하고 나서 Phase 3(LLM
   질문 생성)으로 넘어가면, "질문 스키마/세션 스키마가 잘못됐다"는 문제와
   "LLM이 이상한 질문을 만든다"는 문제를 분리해서 디버깅할 수 있다.
3. **`content_engine.RewriteProvider`는 재사용하지 말고**, 예외 클래스만
   import해서 `tak_scout/interview_llm.py`에 독립된 소형 provider를
   새로 만든다(8-1, 8-2).
4. 이번 설계는 코드/데이터/git 상태를 전혀 바꾸지 않았다. 다음 단계로
   진행하려면 Phase 1(`tak_scout/interview_session.py`)부터 구현 승인을
   받는 것을 제안한다.
