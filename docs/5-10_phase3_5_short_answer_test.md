# 5-10 Phase 3-5 — 짧은 답변 sufficient 압박 테스트

## 1. 테스트 목적

Phase 3-3(1건)·Phase 3-4(3건)에서 실제 LLM 인터뷰가 4/4건 모두 Turn 1에서
`sufficient=true`로 조기 종료됐지만, 4건 모두 첫 답변이 판단+이유+경험/메시지를
갖춘 비교적 구체적인 문장이었다. 이번에는 **의도적으로 짧고 근거 없는 답변**
(판단만 있고 이유가 없는 답변)을 줘서, `decide_next_turn`이 실제로 답변의
구체성/깊이를 보고 후속 질문을 만드는지 검증한다. 코드는 전혀 수정하지 않았다.

## 2. 테스트 소재

| 항목 | 값 |
|---|---|
| scout_id | `scout-ba089403ed6d` |
| 제목 | AI staff 'genuinely frightened' for humanity's future, ex-Anthropic researcher tells BBC |
| source | BBC Business |
| category(daily pack 필드) | finance (내용 성격: AI/기술) |
| SCOUT score | 35 |
| source_fact(summary) | *"It comes as the AI firm's boss has called for the technology's development to be slowed down, citing "serious" risks."* |

Phase 3-3(부동산)·Phase 3-4(물류/AI인권/생활안전)에서 이미 실제 테스트한
4건과 겹치지 않는, 아직 테스트하지 않은 AI 소재 중 SCOUT score가 가장 높은
것을 선택했다(동점 35점 3건 중 이 소재를 선택). 운영
`data/tak_interview_answers.json`에 이미 A(단순 선택)로 답변되어 있었으므로,
**임시 디렉터리에 복사한 답변 파일에서만** 이 1건을 제거해 미답변 상태로
되돌린 뒤 테스트했다(운영 답변 파일은 손대지 않음 - 14번에서 해시로 재확인).

## 3. 실제 LLM 실행 여부

**실행함.** 실제 `InterviewLLMProvider.from_environment()`(Fake Provider
아님)로 실제 OpenAI Chat Completions API를 호출했다.

| 환경변수 | 상태 |
|---|---|
| `TAK_MEDIA_LLM_API_KEY` | 설정되어 있던 값을 그대로 사용 |
| `TAK_MEDIA_LLM_ENDPOINT` | 이 환경에 없어 테스트 프로세스 안에서만 `https://api.openai.com/v1/chat/completions`로 설정(영구 설정 아님) |
| `TAK_MEDIA_LLM_MODEL` | 이 환경에 없어 테스트 프로세스 안에서만 `gpt-4o-mini`로 설정(동일) |

값 자체, Authorization 헤더는 이 문서 어디에도 기록하지 않았다. 임시
디렉터리(`tempfile.mkdtemp()`) + 독립 포트(8811)에서 Dashboard를
`DashboardConfig` + `make_handler_class(config, llm_provider=provider)`로
실행하고, 실제 소켓을 여는 HTTP 요청(curl)으로 라우트를 그대로 호출했다(GUI
브라우저가 없는 환경이라 Phase 3-3/3-4와 동일한 방식으로 대체 - 서버 로직·LLM
호출은 완전히 동일하다).

## 4. Turn 1

- 실제 LLM 질문: **"AI 기술의 발전 속도를 조절해야 한다는 주장에 대해 어떻게
  생각하시나요?"**
  - A. AI의 빠른 발전은 인류에 많은 긍정적 기회를 가져올 것이라고 생각합니다.
  - B. AI 기술 발전의 속도를 조절하는 것이 필요하다고 느낍니다.
  - C. AI 기술에 대한 두려움을 덜어내고 더 많은 발전을 지지합니다.
  - D. 직접 입력
- 사용자의 짧은 D 답변(의도적으로 근거·경험 없이 판단만):
  > **"규제는 어느 정도 필요하다고 봅니다."**

## 5. sufficient 판단 (Turn 1 답변 직후)

- 결과: **`false`**
- 실제 LLM 호출 결과: 짧은 답변만으로는 충분하지 않다고 판단하고, 실제로
  후속 질문(6번)을 생성해 돌려줬다.

## 6. Turn 2

- 생성 여부: **생성됨**
- 질문: **"AI 기술 발전에 대한 규제의 필요성에 대해 더 말씀해 주시겠어요?"**
  - A. 어떤 구체적인 규제가 필요하다고 생각하시나요?
  - B. 규제의 필요성에 대한 예를 들어 주실 수 있나요?
  - C. 규제가 어떤 긍정적인 영향을 미칠 것이라고 보시나요?
  - D. 직접 입력
- 답변(D 직접 입력, 이번엔 의도적으로 구체적으로):
  > "채용이나 대출 심사처럼 사람의 인생을 좌우하는 결정에 AI가 관여할
  > 때는, 왜 그런 결론을 냈는지 설명할 수 있어야 하고 사람이 최종 검토할
  > 수 있는 장치가 있어야 한다고 생각합니다. 그런 최소한의 안전장치도 없이
  > 속도만 내는 건 위험하다고 봅니다."
- sufficient(Turn 2 답변 직후): **`true`**

## 7. Turn 3

- 생성 여부: **생성되지 않음**(Turn 2 답변 직후 `sufficient=true`가 나와
  3턴째로 넘어가지 않고 바로 completed 처리됨)
- 질문/답변: 해당 없음

## 8. 최종 종료 턴

**Turn 2에서 종료**(`session.status == "completed"`, `len(turns) == 2`).

## 9. perspective_summary

> "사용자는 AI 기술 발전에 대해 규제가 필요하다고 생각하며, 특히 사람의
> 인생에 영향을 미치는 결정에 AI가 관여할 경우 설명 가능성 및 최종 검토
> 장치가 필요하다고 강조했습니다. 이러한 안전장치 없이 AI 기술의 빠른
> 발전은 위험하다고 언급했습니다."

Turn 1의 짧은 판단("규제는 어느 정도 필요")과 Turn 2의 구체화(채용/대출,
설명 가능성, 사람의 최종 검토)가 모두 정확히 반영됐고, 기사 SOURCE FACT의
"Anthropic 연구원", "development to be slowed down" 같은 문구를 사용자
의견으로 둔갑시키지 않았다.

## 10. KNOWLEDGE 결과

- `knowledge_id`: `knowledge-scout-22d1fef9c033`
- `knowledge_review_status`: **`pending`**(자동 승인 없음, 확인됨)
- 기존 21건은 그대로 보존, 이 1건만 새로 추가(중복 없음)

## 11. SOURCE FACT / USER ORIGINAL THOUGHT 경계

```
SOURCE FACT: It comes as the AI firm's boss has called for the technology's
development to be slowed down, citing "serious" risks.
SOURCE URL: https://www.bbc.co.uk/news/articles/c1kx0gyje9wo?at_medium=RSS&at_campaign=rss
USER ORIGINAL THOUGHT: Q1. AI 기술의 발전 속도를 조절해야 한다는 주장에 대해
어떻게 생각하시나요?
A1. 규제는 어느 정도 필요하다고 봅니다.

Q2. AI 기술 발전에 대한 규제의 필요성에 대해 더 말씀해 주시겠어요?
A2. 채용이나 대출 심사처럼 사람의 인생을 좌우하는 결정에 AI가 관여할 때는,
왜 그런 결론을 냈는지 설명할 수 있어야 하고 사람이 최종 검토할 수 있는
장치가 있어야 한다고 생각합니다. 그런 최소한의 안전장치도 없이 속도만
내는 건 위험하다고 봅니다.
```

- **direct input 보존**: Turn 1·Turn 2 두 답변 모두 Python 문자열 `==`
  비교로 session → KNOWLEDGE `USER ORIGINAL THOUGHT`까지 **원문과 100%
  일치**함을 확인했다.
- **perspective_summary는 evidence에 포함되지 않음**: `summary in
  evidence_text` 비교 결과 `False` — perspective_summary 문장이 evidence
  어디에도 섞이지 않았다(`handle_finalize`가 `session.turns`만 읽는 기존
  구조 그대로).

## 12. A~G 품질 평가

| 항목 | 결과 | 근거 |
|---|---|---|
| A. 짧은 답변 감지 | **PASS** | "규제는 어느 정도 필요하다고 봅니다."라는, 이유·경험 없이 판단만 있는 짧은 답변에 대해 `sufficient=false`로 정확히 판정했다. |
| B. 후속 질문 생성 | **PASS** | Turn 1 답변 직후 실제로 새 질문(Turn 2)이 생성됐다. |
| C. 후속 질문 적합성 | **PASS** | "AI 기술 발전에 대한 규제의 필요성에 대해 더 말씀해 주시겠어요?" + 선택지("어떤 구체적인 규제가 필요한지", "예를 들어 줄 수 있는지", "긍정적 영향은 무엇인지")는 원래 질문을 반복하지 않고, Turn 1의 "규제는 필요하다"는 판단을 구체화하도록 정확히 유도했다. |
| D. 충분성 판단 | **PASS** | Turn 2에서 채용/대출 심사라는 구체적 영역, 설명가능성·사람의 최종 검토라는 구체적 요구, "안전장치 없이 속도만 내는 건 위험"이라는 근거까지 제시하자 `sufficient=true`로 바뀌었다 - 답변의 구체성에 실제로 반응하는 판단임을 확인했다. |
| E. 사용자 의견 보존 | **PASS** | Turn 1·2 답변 모두 원문 100% 일치(11번). |
| F. SOURCE FACT 경계 | **PASS** | SOURCE FACT(기사 요약)와 사용자 의견이 섞이지 않음(11번). |
| G. KNOWLEDGE 품질 | **PASS** | pending, 자동 승인 없음, 기존 스키마 무변경, 중복 없이 신규 1건만 추가. |

## 13. LLM 호출 횟수

**정확히 3회**(transport 래퍼로 직접 카운팅):

| # | 시점 | 호출 |
|---|---|---|
| 1 | `GET /candidate/scout-ba089403ed6d` | `generate_first_question` (Turn 1 질문 생성) |
| 2 | `POST .../answer` (Turn 1 답변 제출) | `decide_next_turn` → `sufficient=false`, Turn 2 생성 |
| 3 | `POST .../answer` (Turn 2 답변 제출) | `decide_next_turn` → `sufficient=true`, 완료 |

Finalize는 LLM을 호출하지 않았다(호출 로그가 finalize 전후로 3회에서 변하지
않음, 직접 확인).

## 14. 운영 데이터 무결성

| 파일 | 테스트 전 | 테스트 후 | 결과 |
|---|---|---|---|
| `data/tak_scout_daily.json` | `cdbcc8f0...` | `cdbcc8f0...` | 동일 |
| `data/tak_interview_answers.json` | `f4e315c4...` | `f4e315c4...` | 동일 |
| `data/tak_brain_knowledge.json` | `3d441115...` | `3d441115...` | 동일 |
| `data/tak_interview_sessions.json` | 파일 없음 | 파일 없음 | 동일(생성되지 않음) |
| `data/tak_scout_dashboard_skipped.json` | 파일 없음 | 파일 없음 | 동일(생성되지 않음) |

**결과: ALL UNCHANGED.**

## 15. Regression

```
python3 -m unittest discover -s tests -p 'test_*.py'
Ran 332 tests in 13.382s
OK
```

332/332 PASS(코드 변경 없음).

## 16. 발견된 문제

**없음.** 이번 테스트에서는 코드 결함은 물론, Phase 3-4에서 우려했던
"짧은 답변에도 관대하게 sufficient=true를 주는" 경향도 재현되지 않았다 -
오히려 정확히 반대로, 근거 없는 짧은 답변에는 `false`, 구체화된 답변에는
`true`로 답변의 실질적 깊이를 보고 판단하는 모습을 확인했다.

## 17. 제품 판단

**CASE 1 — "현재 인터뷰 엔진의 충분성 판단은 기본적으로 정상 작동한다."**

> 짧은 답변 → `sufficient=false` → 후속 질문 생성 → 구체적인 답변 후
> `sufficient=true`

이번 1건에서 지시 13번의 CASE 1 시나리오가 정확히 재현됐다. Phase 3-4까지의
"4/4건 1턴 조기 종료"는 **판단 로직이 관대해서가 아니라, 사람이 처음부터
근거를 담은 답변을 줬기 때문에 조기 종료가 정당했던 것**이라는 해석에
무게가 실린다. 다만 표본이 1건뿐이므로 이 결론을 확정적으로 일반화하지는
않는다(18번 참고). 추가적인 "최소 2턴 강제"는 이번 단계에서 제안하지 않는다.

## 18. 결론

**PASS — 현재 sufficient 판단을 유지.**

이번 1건은 Phase 3-4에서 남겨둔 의문("혹시 짧은 답변에도 무조건
관대하게 통과시키는 것 아닌가?")에 대해 명확히 **아니다**라는 실제 증거를
제공했다: 근거 없는 짧은 답변은 후속 질문으로 이어졌고, 구체화된 답변에만
충분하다고 판단했다. Phase 3-4의 4/4 조기 종료 경향과 이번 CASE 1 결과를
종합하면, 현재 후속 판단 로직은 "질문의 개수"가 아니라 "답변의 실질적
깊이"를 실제로 보고 있는 것으로 보인다. 코드 수정은 필요하지 않다. (표본이
누적 5건으로 아직 많지 않으므로, 이 결론은 향후 실사용 데이터가 쌓이면
재검토할 수 있는 잠정적 결론으로 남긴다.)

---

## 최종 확인

- **실제 인터뷰**: 1건
- **실제 LLM 호출**: 3회
- **Turn 1 sufficient**: `false`
- **후속 질문**: 생성됨(Turn 2)
- **Turn 2 sufficient**: `true`
- **최종 종료 턴**: Turn 2
- **KNOWLEDGE**: 생성됨, `pending`
- **운영 데이터**: ALL UNCHANGED
- **regression**: 332/332 PASS
- **코드 수정**: 없음
- **git commit/push**: 없음(`git status`만 확인)
- **보고서 경로**: `docs/5-10_phase3_5_short_answer_test.md`
