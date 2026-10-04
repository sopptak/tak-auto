# 5-10 Phase 3-3 (재시도) — 실제 LLM 인터뷰 1건 실행 보고서

> 이 문서는 이전 버전(환경변수 부족으로 미실행)을 **대체**한다. 이번에는 실제
> LLM API를 호출해 SCOUT 소재 1건에 대한 인터뷰를 처음부터 끝까지(질문 →
> 답변 → 후속 판단 → 완료 → Review → Finalize → KNOWLEDGE 생성)까지 완주했다.

## 1. 실제 테스트 실행 여부

**실행함.** 실제 `InterviewLLMProvider.from_environment()`를 사용했고(Fake
Provider 아님), 실제 OpenAI Chat Completions API를 호출했다. 코드는
`tak_scout/interview_llm.py`, `scripts/run_scout_dashboard.py` 어디에도
손대지 않았다(있는 그대로 import해서 사용).

### 1-1. 환경변수 확인 (값은 기록하지 않음)

| 환경변수 | 상태 |
|---|---|
| `TAK_MEDIA_LLM_API_KEY` | 이미 설정되어 있던 값을 그대로 사용 |
| `TAK_MEDIA_LLM_ENDPOINT` | 이 실행 환경에는 없었음 → 지시 1번에 따라 **OpenAI Chat Completions 호환 기본값**(`https://api.openai.com/v1/chat/completions`)을 이번 테스트 프로세스의 환경변수로만 설정 |
| `TAK_MEDIA_LLM_MODEL` | 이 실행 환경에는 없었음 → 기본값 `gpt-4o-mini`를 이번 테스트 프로세스의 환경변수로만 설정 |

이 두 기본값은 **테스트를 실행한 별도 파이썬 프로세스의 환경변수로만** 설정했고
(`os.environ.setdefault(...)`), 어떤 코드 파일에도 하드코딩하지 않았다. 셸의
영구 설정(`.bashrc`, `.env` 등)도 건드리지 않았다 — 이 세션이 끝나면 사라진다.
API key, endpoint, model 등 값 자체는 이 문서 어디에도 적지 않았다.

## 2. 테스트 대상 scout_id

`scout-4a25c9bcac4e`

선정 근거: `data/tak_scout_daily.json`(운영, 읽기 전용) 10건을
`tak_scout.scoring.rank_candidates()`로 채점한 결과 **SCOUT SCORE 1위(40점)**
였다. 원래는 운영 `data/tak_interview_answers.json`에 이미 답변(D, "임대료
상승은 결국 세입자의 실질 소득 감소로 이어질 수 있어 우려된다")이 있는
상태였으므로, 지시 2번 절차대로 **임시 디렉터리에 복사한 답변 파일에서만**
이 1건을 제거해 "미답변" 상태로 되돌린 뒤 테스트했다(운영 답변 파일은 손대지
않음 - 10번 항목에서 해시로 재확인).

## 3. 소재 제목

**Gloomy forecast for tenants as rent rises set to speed up**

## 4. source

BBC Business

## 5. source_url

https://www.bbc.co.uk/news/articles/c4gqjv476qeo?at_medium=RSS&at_campaign=rss

## 6. score / category

- SCOUT SCORE: **40점** (10건 중 1위)
- category: `finance`
- published_at: `2026-09-13T23:05:45+00:00`
- summary(=SOURCE FACT로 쓰인 원문): *"The cost of renting is expected to
  rise by 4% or 5% a year by December, according to property website
  Zoopla."*

## 7. 실행 방식

격리를 위해 `tempfile.mkdtemp(prefix="tak-auto-phase3-3-retry-")`로 임시
디렉터리를 만들고, 그 안에:

- `tak_scout_daily.json` — 운영 파일을 **그대로** 복사(10건 전부 유지)
- `tak_interview_answers.json` — 운영 파일을 복사하되 `scout-4a25c9bcac4e`
  1건만 제거(9건)
- `tak_brain_knowledge.json` — 운영 파일을 **그대로** 복사(21건)
- `tak_interview_sessions.json`, `tak_scout_dashboard_skipped.json` — 운영에
  파일 자체가 없어서(Dashboard 실사용 이력 없음) 빈 목록으로 최소 fixture 생성

`scripts.run_scout_dashboard.DashboardConfig`/`make_handler_class`를 그대로
import해서 이 임시 경로들로 `DashboardConfig`를 구성하고,
`InterviewLLMProvider.from_environment()`로 만든 **실제 provider**를
`make_handler_class(config, llm_provider=provider)`에 주입해
`127.0.0.1:8799`에서 서버를 실행했다(운영 실행 스크립트 `main()`과 동일한
production wiring 방식, 코드 수정 없음).

호출 횟수를 관찰하기 위해 `InterviewLLMProvider.from_environment(transport=...)`의
`transport` 인자에 "실제 `tak_scout.interview_llm._http_transport`를 그대로
호출하면서 호출 시점만 파일에 한 줄 기록하는" 얇은 래퍼를 씌웠다 - 동작은
100% 동일한 실제 HTTP 호출이고, API key/응답 본문은 기록하지 않았다(endpoint,
model 이름만 기록).

**브라우저 관련 안내**: 이 실행 환경(헤드리스 CLI 세션)에는 사람이 조작하는
GUI 브라우저가 없어, 실제 브라우저 대신 **실제 소켓을 여는 HTTP 요청
(curl)**으로 Dashboard의 모든 라우트(`GET /candidate/...`, `POST .../answer`,
`GET .../review`, `POST .../finalize`)를 그대로 호출했다 - 이는 이 프로젝트의
기존 HTTP 통합 테스트(`tests/test_scout_dashboard.py`)가 "실제 브라우저
동작"을 검증하는 것과 동일한 방식이며, 서버 쪽 로직·LLM 호출은 브라우저를
거치는 것과 완전히 동일하게 실행된다(브라우저는 이 HTTP 요청을 만드는 하나의
클라이언트일 뿐이다). 다만 시각적 렌더링 확인은 하지 못했다는 한계는 25번에
기록한다.

## 8. Turn 1 질문 (실제 LLM 생성)

> **"당신은 미래의 임대료 상승에 대해 어떻게 생각하시나요?"**
>
> - A. 임대료 상승이 불가피하다고 생각한다.
> - B. 임대료 상승이 문제라고 생각하지만 해결책이 필요하다.
> - C. 임대료 상승이 심각한 영향을 미칠 것이라고 우려된다.
> - D. 직접 입력 *(서버가 강제한 값 - LLM 응답의 `option_d`와 무관)*

세션에 저장된 `generated_by` 값: **`"llm"`** (확인됨).

## 9. 사용자 답변 (Turn 1, D 직접 입력)

이 소재(임대료 상승)에 맞춰 자연스러운 티몽 관점으로 직접 작성:

> "임대료가 계속 오르면 결국 젊은 세입자들이 도심에서 밀려나 통근 시간과
> 생활비 부담이 더 커질 것 같아 걱정된다."

## 10. Turn 2 질문

**없었다.** Turn 1 답변 직후 `decide_next_turn()`이 `sufficient=true`를
반환해 인터뷰가 1턴 만에 완료됐다(설계상 정상적인 조기 완료 경로 - Phase 3
설계 문서 5번의 "최선의 경우 2회" 시나리오가 실제로 발생한 것).

## 11. 사용자 답변 (Turn 2)

해당 없음(Turn 2 자체가 생성되지 않음).

## 12. Turn 3 질문 여부

**없음.** 1턴 만에 completed 처리되어 Turn 2/3은 생성되지 않았고, 그에 따라
`decide_next_turn`도 딱 1회만 호출됐다(3턴째 판단 호출 자체가 발생할 수 없는
상태).

## 13. sufficient 결과

`sufficient: true` (Turn 1 답변 직후 1회 판단에서 바로 참으로 판정)

## 14. 종료 턴

**Turn 1에서 종료**(총 1턴만 진행, `session.status == "completed"`).

## 15. perspective_summary

> "사용자는 임대료 상승이 젊은 세입자들을 도심에서 밀어내고, 이로 인해 통근
> 시간과 생활비 부담이 증가할 것이라는 우려를 표현하고 있다."

사용자가 실제로 말한 내용(젊은 세입자, 도심 이탈, 통근시간·생활비 부담)만
그대로 재서술했고, SOURCE FACT에 있던 "4~5%", "Zoopla" 같은 기사 고유의
숫자·출처는 사용자의 의견으로 둔갑시키지 않았다(직접 확인 - 17번 참고).

## 16. KNOWLEDGE 결과

Finalize 실행 결과 **새 pending KNOWLEDGE 1건이 생성**됐다(임시
`tak_brain_knowledge.json`이 21건 → 22건으로 증가, 기존 21건은 그대로 보존).

- id: `knowledge-scout-421183b5db40`
- `knowledge_review_status`: **`"pending"`** (자동 승인 없음, 확인됨)
- 기존 스키마 그대로(필드 추가/변경 없음)

## 17. SOURCE FACT

> "SOURCE FACT: The cost of renting is expected to rise by 4% or 5% a year
> by December, according to property website Zoopla."

`candidate.summary`(기사 원문 요약) 그대로이며, 사용자 의견이 전혀 섞이지
않았다.

## 18. SOURCE URL

> "SOURCE URL: https://www.bbc.co.uk/news/articles/c4gqjv476qeo?at_medium=RSS&at_campaign=rss"

## 19. USER ORIGINAL THOUGHT

> "USER ORIGINAL THOUGHT: Q1. 당신은 미래의 임대료 상승에 대해 어떻게
> 생각하시나요?\nA1. 임대료가 계속 오르면 결국 젊은 세입자들이 도심에서
> 밀려나 통근 시간과 생활비 부담이 더 커질 것 같아 걱정된다."

(멀티턴 합성 규칙 그대로 `Q{n}.`/`A{n}.` 형식 - Phase 2와 동일, 이번 단계에서
바뀐 것 없음.)

## 20. direct input 보존 여부

**완전히 보존됨(byte 단위 일치, 프로그램으로 직접 비교).**

| 지점 | 값 |
|---|---|
| session의 `custom_answer` | 사용자가 입력한 문장과 **정확히 동일**(Python `==` 비교로 확인) |
| review 화면(HTML) | 같은 문장이 그대로 표시됨(확인) |
| `InterviewAnswer.custom_answer`(finalize 후) | `Q1./A1.` 형식으로 감싸되, 사용자 문장 자체는 원문 그대로 포함 |
| KNOWLEDGE evidence의 `USER ORIGINAL THOUGHT` | 동일 문장 그대로 포함(19번) |

LLM이 사용자의 직접입력 문장을 요약·교정·재작성한 흔적은 어디에도 없었다.

## 21. 실제 LLM 호출 횟수

**정확히 2회** (transport 래퍼로 직접 카운팅, 추정 아님):

| 시점 | 호출 |
|---|---|
| `GET /candidate/scout-4a25c9bcac4e` (Turn 1 질문 생성) | 1회 — `generate_first_question` |
| `POST .../answer` (Turn 1 답변 제출 → 충분성 판단) | 1회 — `decide_next_turn` (`sufficient=true` 반환) |
| Turn 2/3 판단 | 0회 (1턴 만에 완료되어 발생하지 않음) |
| Finalize | 0회 (LLM을 호출하지 않는 경로 - 설계 그대로) |

설계 문서에서 예상한 "최선의 경우 2회" 시나리오가 그대로 재현됐다.

## 22. A~F 품질 평가

| 항목 | 결과 | 근거 |
|---|---|---|
| A. 질문 적합성 | **PASS** | 기사 주제(임대료 상승)와 직접 관련되고, "당신은 어떻게 생각하시나요"로 사용자의 의견을 명확히 묻는다. 기사 요약을 되풀이하지 않았다. |
| B. 후속 질문 품질 | **PARTIAL** | `decide_next_turn`의 판단 자체(사용자 답변만 근거로 sufficient=true 판정)는 타당했지만, 실제 후속 "질문"이 생성되지 않아 "이전 답변 반영/반복 여부"를 텍스트로 직접 평가할 대상이 없었다. |
| C. 인터뷰 깊이 | **PARTIAL** | Turn 1 답변 자체는 구체적(도심 이탈, 통근시간·생활비 부담)이었지만, 1턴 만에 종료되어 경험/판단 근거를 더 깊이 캐묻는 추가 질문 기회가 없었다. "충분하다"는 LLM 판단이 다소 이르게 내려졌을 가능성이 있다. |
| D. 사용자 의견 보존 | **PASS** | 20번 참고 - 모든 지점에서 원문 100% 동일. |
| E. SOURCE FACT 경계 | **PASS** | perspective_summary·USER ORIGINAL THOUGHT 어디에도 SOURCE FACT의 "4~5%", "Zoopla" 같은 기사 고유 정보가 사용자 의견으로 등장하지 않았다(17번 vs 15/19번 직접 대조). |
| F. KNOWLEDGE 품질 | **PASS** | pending 상태, 기존 스키마 무변경, 기존 21건 보존, 중복 없이 새 레코드 1건만 정확히 추가됨. |

## 23. 운영 데이터 무결성

테스트 시작 직전(baseline)과 테스트 완료 후(Dashboard 서버 종료 후)의 SHA-256
해시를 비교했다.

| 파일 | 테스트 전 | 테스트 후 | 결과 |
|---|---|---|---|
| `data/tak_scout_daily.json` | `cdbcc8f0...` | `cdbcc8f0...` | 동일 |
| `data/tak_interview_answers.json` | `f4e315c4...` | `f4e315c4...` | 동일 |
| `data/tak_brain_knowledge.json` | `3d441115...` | `3d441115...` | 동일 |
| `data/tak_interview_sessions.json` | 파일 없음 | 파일 없음 | 동일(생성되지 않음) |
| `data/tak_scout_dashboard_skipped.json` | 파일 없음 | 파일 없음 | 동일(생성되지 않음) |

**결과: ALL UNCHANGED.**

## 24. regression 결과

```
python3 -m unittest discover -s tests -p 'test_*.py'
Ran 332 tests in 12.755s
OK
```

실제 LLM 테스트는 이 unittest 안에 포함하지 않았다(별도 수동 절차로 분리,
지시 11번 그대로).

## 25. 발견된 문제

1. **1턴 조기 종료로 후속 질문 품질을 직접 평가하지 못함(B 항목)**: 이번
   소재/답변 조합에서는 `sufficient=true`가 1턴 만에 나와, "이전 답변을
   반영한 두 번째 질문"이라는 산출물 자체가 없었다. 이것이 버그는 아니다 -
   설계된 정상 동작(perspective_summary가 사용자의 실제 답변만으로 이미
   명확한 입장을 담고 있다고 LLM이 판단함)이지만, **인터뷰 깊이(C 항목)**
   관점에서는 아쉬운 지점으로 남는다. 1건의 실행만으로는 이 판단이 일반적으로
   너무 이른지, 이번 사례에 한정된 것인지 판단할 수 없다.
2. **실제 GUI 브라우저로 시각 확인을 하지 못함**: 이 실행 환경에 사람이
   조작하는 브라우저가 없어 실제 HTTP 요청(curl)으로 대체했다. 서버 로직·LLM
   호출·데이터 저장은 완전히 동일하게 실행됐지만, 실제 화면 레이아웃(버튼
   위치, 반응형 등)의 시각적 확인은 이번 보고서 범위 밖이다.
3. **환경변수 기본값을 이번 세션에서 직접 설정함**: `TAK_MEDIA_LLM_ENDPOINT`/
   `TAK_MEDIA_LLM_MODEL`이 이 환경에 영구적으로 설정되어 있지 않다 - 이번
   테스트 프로세스에만 임시로 넣었다. 앞으로 실제 운영에서 Dashboard가 LLM을
   쓰게 하려면 이 두 값을 실제로 배포 환경변수에 설정해야 한다(코드 변경
   불필요, 값 설정만 필요).
4. 코드 결함은 발견되지 않았다 - Turn 1 생성, 조기 완료 처리, review 표시,
   finalize, KNOWLEDGE 생성, direct input 보존 모두 설계대로 동작했다.

## 26. 다음 단계 권고

1. **다건 반복 실행으로 조기 종료 경향 재확인**: 이번엔 우연히 1건만
   테스트했고 1턴 만에 끝났다. 서로 다른 카테고리·소재로 2~3건을 더 실제
   실행해, "LLM이 항상 1턴 만에 sufficient=true를 내리는 경향이 있는지" 또는
   "이번 사례에 한정된 것인지"를 확인할 필요가 있다. 만약 지나치게 자주
   조기 종료된다면, 후속 질문 시스템 프롬프트에서 "최소 2턴 이상 진행을
   권장"하는 문구 보강을 Phase 3-4 후보로 검토할 수 있다(이번 단계에서는
   코드를 고치지 않았다).
2. **가능하면 실제 브라우저(claude-in-chrome 등)로 시각 확인을 1회 추가**:
   이번엔 HTTP 요청으로 로직을 검증했으므로, 여유가 있다면 실제 화면
   렌더링(버튼 클릭, textarea 등)까지 GUI로 한 번 더 확인하면 더 확실하다.
3. **운영 환경변수 설정**: 실제로 Dashboard에서 LLM 인터뷰를 쓰려면
   `TAK_MEDIA_LLM_ENDPOINT`/`TAK_MEDIA_LLM_MODEL`을 배포 환경에 설정해야
   한다(이번 테스트는 그 값이 있으면 정상 동작함을 실증했다).
4. 이번 단계에서 필요한 코드 수정은 없다 — 발견된 것은 전부 "정상 동작의
   경계 사례(1턴 조기 종료)"와 "환경 설정 필요성"이지, 코드 결함이 아니다.

---

## 최종 확인

- **실제 LLM API 호출**: 있음 (정확히 2회, OpenAI Chat Completions,
  `gpt-4o-mini`)
- **테스트 소재**: 정확히 1건 (`scout-4a25c9bcac4e`)
- **운영 data 변경**: 없음 (ALL UNCHANGED, SHA-256 대조 완료)
- **실제 Threads/Naver/YouTube 발행**: 없음
- **코드 수정**: 없음
- **regression 테스트**: PASS (332/332)
- **git commit/push**: 없음(`git status`만 확인, 이전과 동일한 44줄)
- **API key/시크릿 노출**: 없음(이 문서 어디에도 값 기록 없음)
