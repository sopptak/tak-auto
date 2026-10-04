# 5-10 Phase 3-4 — 실제 다건 LLM 인터뷰 검증 보고서

## 1. 테스트 목적

Phase 3-3에서 실제 LLM 인터뷰 1건이 "1턴 만에 sufficient=true"로 끝난 것이
우연인지, 구조적인 경향인지를 서로 다른 성격의 소재 3건으로 재현 검증한다.
코드는 전혀 수정하지 않았다.

## 2. 실제 LLM 실행 여부

**실행함.** 3건 모두 실제 `InterviewLLMProvider.from_environment()`(Fake
Provider 아님)로 실제 OpenAI Chat Completions API를 호출했다. 소재별로
독립된 임시 디렉터리 + 독립된 포트(8801/8802/8803)에서 Dashboard를 실행하고,
실제 소켓을 여는 HTTP 요청(curl)으로 `GET /candidate/...` →
`POST .../answer` → `GET .../review` → `POST .../finalize` 전 라우트를
그대로 호출했다(이 환경에는 GUI 브라우저가 없어 Phase 3-3과 동일하게 실제
HTTP 요청으로 대체 - 서버 로직·LLM 호출은 브라우저를 거치는 것과 동일하다).

## 3. 환경 설정

| 환경변수 | 상태 |
|---|---|
| `TAK_MEDIA_LLM_API_KEY` | 설정되어 있던 값을 그대로 사용 |
| `TAK_MEDIA_LLM_ENDPOINT` | 이 환경에 없어 테스트 프로세스 안에서만 `https://api.openai.com/v1/chat/completions`로 설정(`os.environ.setdefault`, 영구 설정 아님) |
| `TAK_MEDIA_LLM_MODEL` | 이 환경에 없어 테스트 프로세스 안에서만 `gpt-4o-mini`로 설정(동일) |

값 자체, Authorization 헤더는 이 문서 어디에도 기록하지 않았다.

## 4. 테스트 소재 3건

운영 `data/tak_scout_daily.json`(읽기 전용) 10건을
`tak_scout.scoring.rank_candidates()`로 채점한 뒤, 이미 Phase 3-3에서 실제
테스트한 `scout-4a25c9bcac4e`(부동산/임대료)는 제외하고 성격이 다른 3건을
선정했다. daily pack의 `category` 필드는 10건 전부 `finance`로 저장돼
있지만(수집 스크립트의 카테고리 라벨링 관례), **소재 내용 자체**는 아래처럼
뚜렷이 다른 성격이다.

| # | scout_id | 제목 | 소재 성격(내용 기준) | daily pack category | SCOUT score |
|---|---|---|---|---|---|
| A | `scout-e630ed0ba090` | Amazon pauses work with cargo firm after fatal crash | 물류/기업 안전 책임(경제·기업) | finance | 39 |
| B | `scout-66639b297fc0` | Committee calls for bill to address AI threat to human rights | AI/기술 규제·인권 | finance | 38 |
| C | `scout-87f2284ff52b` | How to protect your laptop, phone and bike from thieves at uni | 대학생 도난 예방(생활/안전) | finance | 22 |

각 소재는 운영 `data/tak_interview_answers.json`에 이미 A(단순 선택)로
답변되어 있었으므로, 지시 4번 절차대로 **소재별 독립 임시 디렉터리에 복사한
답변 파일에서만** 해당 1건씩을 제거해 "미답변" 상태로 되돌린 뒤 테스트했다
(운영 답변 파일은 세 번 모두 손대지 않음 - 9번 항목에서 해시로 재확인).

## 5. 소재별 인터뷰 결과

### Case A — Amazon pauses work with cargo firm after fatal crash

- Turn 1 질문: **"이러한 사고가 발생했을 때, 운송업체와 대형 기업의 책임에
  대해 어떻게 생각하세요?"** (A: 운송업체가 모든 책임 / B: 대형 기업도 일정
  부분 책임 / C: 사고는 불가피, 누구도 책임 없음)
- Turn 1 답변(D 직접 입력): "아마존처럼 물류를 대량으로 위탁하는 대기업은
  협력업체의 안전 관리 수준까지 책임지고 점검할 의무가 있다고 본다. 예전에
  택배 물량이 몰리는 시즌에 배송기사들이 무리한 일정으로 사고 위험에
  노출된다는 뉴스를 본 적이 있는데, 결국 최종 발주처인 대기업이 하청업체의
  안전 기준을 관리하지 않으면 이런 사고는 반복될 수밖에 없다고 생각한다.
  사고 직후 계약을 끊는 대응보다, 애초에 협력업체를 고를 때 안전 이력을 더
  꼼꼼히 따지는 게 우선이라고 본다."
- Turn 2 질문/답변: **없음 — sufficient=true로 조기 종료**
- Turn 3 질문/답변: **없음**
- sufficient: `true` (Turn 1 답변 직후 1회 판단)
- 실제 종료 턴: **Turn 1**
- perspective_summary: "사용자는 대기업이 협력업체의 안전 관리를 책임지고
  점검해야 한다고 생각하며, 사고 발생 시 계약 종료보다 협력업체 선택 시
  안전 이력을 철저히 확인하는 것이 중요하다고 강조했다."
- LLM 호출 횟수: **2회**(Turn 1 생성 1 + follow-up 판단 1)

### Case B — Committee calls for bill to address AI threat to human rights

- Turn 1 질문: **"AI의 발전이 인권에 미치는 위협에 대해 어떻게
  생각하시나요?"** (A: 현재 법으로 충분 / B: 법 보완·규제 시급 / C: 인권보다
  기술 발전이 더 중요)
- Turn 1 답변(D 직접 입력): "AI가 채용 심사나 신용 평가처럼 사람의 기회를
  좌우하는 영역에 이미 쓰이고 있는데, 그 판단 과정이 불투명해서 문제가
  생겨도 왜 그런 결과가 나왔는지 당사자가 알기 어렵다는 점이 제일
  걱정된다. 기존 개인정보보호법이나 차별금지법만으로는 AI가 만드는 새로운
  형태의 피해, 예를 들어 알고리즘이 은연중에 특정 집단을 불리하게 판단하는
  경우를 다루기 어렵다고 본다. 기술 발전 자체를 막자는 게 아니라,
  자동화된 결정에 대해 설명을 요구하고 이의를 제기할 수 있는 절차적 권리를
  법으로 명확히 만들어야 한다는 게 내 생각이다."
- Turn 2 질문/답변: **없음 — sufficient=true로 조기 종료**
- Turn 3 질문/답변: **없음**
- sufficient: `true`
- 실제 종료 턴: **Turn 1**
- perspective_summary: "AI가 사람의 기회를 좌우하는 영역에 쓰여지고 있는
  점이 걱정된다. 판단 과정의 불투명성이 문제이며, 기존 법으로는 AI로 인한
  새로운 형태의 피해를 다루기 어렵다고 본다. 기술 발전을 막지 말고,
  자동화된 결정에 대한 설명 요구와 이의 제기 절차를 법제화해야 한다고
  생각한다."
- LLM 호출 횟수: **2회**

### Case C — How to protect your laptop, phone and bike from thieves at uni

- Turn 1 질문: **"대학생으로서 소중한 물건을 보호하기 위한 방법에 대해
  어떻게 생각하시나요?"** (A: 예방 조치가 가장 중요 / B: 보험 가입이 더
  중요 / C: 안전한 곳에 보관하는 것이 우선)
- Turn 1 답변(D 직접 입력): "나는 예방이 우선이라고 생각한다. 예전에
  자전거를 잠깐 세워두고 편의점에 들어갔다가 자물쇠를 제대로 안 채운
  사이에 잃어버린 적이 있는데, 그 이후로는 아무리 짧은 시간이라도 U자형
  자물쇠로 프레임과 바퀴까지 같이 고정하는 습관이 생겼다. 보험은 이미
  잃어버린 뒤의 대책이라 마음은 편해질 수 있어도 물건 자체나 그 안의
  자료는 돌아오지 않으니, 학생들에게는 보험보다 애초에 도난을 막는 습관을
  먼저 들이라고 말해주고 싶다."
- Turn 2 질문/답변: **없음 — sufficient=true로 조기 종료**
- Turn 3 질문/답변: **없음**
- sufficient: `true`
- 실제 종료 턴: **Turn 1**
- perspective_summary: "사용자는 예방이 중요하다고 생각하며, 자전거를
  잃어버린 경험을 통해 도난 방지를 위한 습관을 강조한다. 보험은 잃은 후의
  대책일 뿐이며, 도난을 막는 습관을 먼저 들이기를 원한다."
- LLM 호출 횟수: **2회**

## 6. KNOWLEDGE 결과

| case | knowledge_id | status | SOURCE FACT | USER ORIGINAL THOUGHT |
|---|---|---|---|---|
| A | `knowledge-scout-33eddc578cb6` | pending | "The 21 Air-operated jet overshot a runway at Miami International Airport and hit several vehicles." | "Q1. 이러한 사고가 발생했을 때... / A1. 아마존처럼 물류를 대량으로 위탁하는 대기업은..." (Turn 1 원문 그대로) |
| B | `knowledge-scout-0e13c6c3b8b6` | pending | "A cross-party group of MPs and peers identifies human rights risks that existing laws appear not to cover." | "Q1. AI의 발전이 인권에 미치는 위협에... / A1. AI가 채용 심사나 신용 평가처럼..." (Turn 1 원문 그대로) |
| C | `knowledge-scout-bc04eb528d93` | pending | "What should new students consider to keep your belongings safe and covered by insurance?" | "Q1. 대학생으로서 소중한 물건을 보호하기 위한... / A1. 나는 예방이 우선이라고 생각한다..." (Turn 1 원문 그대로) |

세 건 모두 `SOURCE FACT`는 기사 원문 요약(`candidate.summary`) 그대로이고,
`USER ORIGINAL THOUGHT`는 티몽이 실제로 입력한 문장을 `Q1./A1.` 형식으로만
감싼 원문이다. **`perspective_summary`(5번 항목의 AI 요약 문장)는 세 건의
evidence 어디에도 등장하지 않는다** — `handle_finalize()`가
`session.turns`만 읽고 `session.perspective_summary`는 읽지 않는 기존
구조(Phase 3-2에서 이미 확인, 이번에도 직접 대조로 재확인) 그대로라서, 구조적으로
섞일 수 없다. **SOURCE FACT ↔ USER ORIGINAL THOUGHT 구분: 정상.**

참고: Case A의 `scout-e630ed0ba090`에는 이전 대량-답변(단순 A 선택)으로
생성된 `rejected` 상태의 옛 KNOWLEDGE 레코드가 이미 있었으나(운영 파일을
그대로 복사했으므로 임시본에도 그대로 있었다), 이번에 만든 새 레코드와
`id`가 달라 중복 없이 별개로 추가됐다 - `append_scout_knowledge()`의 기존
중복 방지 로직이 정상 동작함을 재확인했다.

## 7. A~F 품질 평가

| 항목 | 결과 | 근거 |
|---|---|---|
| A. 질문 적합성 | **PASS** | 3건 모두 기사 내용을 단순 요약하지 않고, 소재의 핵심 쟁점(기업 책임, AI 규제, 도난 예방)에 대한 티몽 본인의 입장을 직접 묻는 질문이었다. |
| B. 후속 질문 품질 | **PARTIAL** | 3건 모두 후속 질문 자체가 생성되지 않아(1턴 조기 종료) "이전 답변 반영/반복 여부"를 텍스트로 평가할 대상이 없었다. `decide_next_turn`의 판단(사용자 답변만 근거로 sufficient 여부 결정)은 매번 타당해 보였지만, "질문 품질"을 직접 관찰하지 못했다. |
| C. 인터뷰 깊이 | **PARTIAL** | 3건 모두 Turn 1 하나로 끝났다. 다만 이번 답변들은 지시 6번에 따라 판단+이유+경험/사례+핵심 메시지를 의도적으로 담아 작성했고, `perspective_summary`가 이 요소들을 실제로 반영한 것으로 보아 "답변이 이미 충분히 깊었기 때문에 조기 종료된" 것일 가능성이 높다 - 다만 설계 의도(최대 3턴까지 파고드는 인터뷰)가 실제로 거의 발동되지 않는다는 사실 자체는 그대로 남는다. |
| D. 사용자 의견 보존 | **PASS** | 3건 모두 session/`InterviewAnswer`/KNOWLEDGE `USER ORIGINAL THOUGHT`에서 Python 문자열 `==` 비교로 원문과 100% 일치 확인. |
| E. SOURCE FACT 경계 | **PASS** | 3건 모두 SOURCE FACT(기사 요약)와 perspective_summary/USER ORIGINAL THOUGHT가 뒤섞이지 않았다 - 기사 고유의 숫자·기관명(Miami International Airport, MPs and peers, Zoopla류 출처 등)이 사용자 의견으로 등장하지 않았다. |
| F. KNOWLEDGE 품질 | **PASS** | 3건 모두 `pending`, 자동 승인 없음, 기존 스키마 무변경, 기존 레코드와 중복 없이 정확히 1건씩만 추가. "기사 사실 + 티몽의 독자적 관점" 구조(SOURCE FACT + USER ORIGINAL THOUGHT 분리)가 유지됨. |

## 8. 조기 종료 통계

- 1턴 종료: **3건**
- 2턴 종료: 0건
- 3턴 종료: 0건

**해석: ① "3건 모두 1턴 종료 → 조기 종료 경향이 강한 것으로 판단."**

Phase 3-3의 실제 인터뷰 1건(부동산/임대료 소재)까지 합치면, 지금까지 실제
LLM으로 진행한 **4건의 실제 인터뷰가 전부 1턴 만에 `sufficient=true`로
종료**됐다. 소재 성격(경제/AI규제/생활안전/부동산)과 답변 스타일(판단만 /
판단+경험+메시지)을 다양하게 바꿔도 결과가 바뀌지 않았다는 점에서, 이는
"이번 3건의 우연"이 아니라 **현재 후속 질문 판단 프롬프트가 "사용자가 이유
있는 의견 한 마디를 남기면 대체로 충분하다고 판단하는" 구조적 경향**임을
시사한다. 다만 4건 모두 답변자가 (나 자신이) 판단+이유를 포함한 비교적
완성도 높은 문장을 D로 직접 입력했다는 공통점이 있어, "짧고 단순한 답변"이나
"애매한 답변"을 줬을 때도 동일하게 조기 종료되는지는 이번 검증 범위 밖이다.

## 9. 운영 데이터 무결성

테스트 시작 직전(baseline, Phase 3-3 종료 시점과 동일)과 3건의 실제 인터뷰
+ finalize를 전부 마친 뒤(서버 3개 모두 종료 후)의 SHA-256 해시를 비교했다.

| 파일 | 테스트 전 | 테스트 후 | 결과 |
|---|---|---|---|
| `data/tak_scout_daily.json` | `cdbcc8f0...` | `cdbcc8f0...` | 동일 |
| `data/tak_interview_answers.json` | `f4e315c4...` | `f4e315c4...` | 동일 |
| `data/tak_brain_knowledge.json` | `3d441115...` | `3d441115...` | 동일 |
| `data/tak_interview_sessions.json` | 파일 없음 | 파일 없음 | 동일(생성되지 않음) |
| `data/tak_scout_dashboard_skipped.json` | 파일 없음 | 파일 없음 | 동일(생성되지 않음) |

**결과: ALL UNCHANGED.**

## 10. Regression

```
python3 -m unittest discover -s tests -p 'test_*.py'
Ran 332 tests in 12.859s
OK
```

332/332 PASS(코드 변경이 없으므로 예상대로). 실제 LLM 테스트는 이 unittest
안에 포함하지 않았다(수동 절차로 분리).

## 11. 발견된 문제

**코드 결함: 없음.** Turn 1 생성, LLM 호출 횟수 제한(정확히 2회씩, 재시도
없음), finalize, KNOWLEDGE 생성, direct input 보존, SOURCE FACT 경계는 3건
모두 설계대로 정확히 동작했다.

**품질/설계 개선 후보(코드 결함 아님, 이번 단계에서 수정하지 않음)**:

1. **1턴 조기 종료가 재현 가능한 경향으로 확인됨**(8번). 실제 인터뷰 4/4건이
   1턴에 끝났다 - "최대 3턴까지 진행할 수 있다"는 설계가 실제로는 거의
   발동되지 않고 있다. 이것이 제품 의도에 부합하는지(짧고 명확한 의견은
   1턴으로 충분하다는 철학이라면 OK) 아니면 후속 질문 판단 프롬프트를
   보수적으로(예: "최소 2턴은 진행을 권장" 문구 추가) 조정해야 하는지는
   별도의 제품 판단이 필요하다.
2. **"애매하거나 짧은 답변"에 대한 동작은 검증하지 못함**: 이번 4건은 모두
   비교적 완성도 높은 답변이었다. "잘 모르겠다"처럼 짧고 모호한 답변에도
   sufficient=true가 나오는지는 아직 확인하지 않았다 - 만약 그렇다면 더 큰
   품질 문제로 이어질 수 있다.

## 12. 결론

**PARTIAL — 추가 검증 필요.**

핵심 파이프라인(실제 LLM Turn 1 생성 → 사용자 답변 → 실제 후속 판단 →
Review → Finalize → pending KNOWLEDGE, direct input 보존, SOURCE FACT 경계)은
서로 다른 성격의 소재 3건 모두에서 **코드 결함 없이** 정확하게 동작했다
(PASS 요소들). 그러나 "1턴 조기 종료"가 이제 4/4건으로 재현되어, 지시 9번의
해석 기준 ①에 명확히 해당한다 - 단순한 우연이 아니라 구조적 경향으로
판단된다. 이는 Phase 3-5로 그대로 넘어가도 되는 수준의 완성도라기보다,
"이 동작이 의도된 것인지"를 사람이 먼저 판단해야 하는 지점이라 **PARTIAL**로
평가한다. **코드 결함으로 인한 FAIL은 아니다** - 지금 상태로도 실제 KNOWLEDGE
생성까지는 안전하게 완주된다.

## 13. 다음 단계 제안

**이번 단계에서는 코드 수정하지 않음.**

1. (제품 판단) "짧은 의견도 1턴이면 충분하다"는 현재 동작을 그대로 받아들일지,
   아니면 후속 질문 프롬프트에 "최소 2턴 진행 권장" 같은 조정을 Phase 3-5
   후보로 검토할지 결정이 필요하다 - 이번 보고서는 판단 근거(4/4 조기 종료
   데이터)만 제공한다.
2. 다음 실제 검증 라운드에서는 일부러 짧고 모호한 답변("잘 모르겠어요" 등)을
   1건 포함해, sufficient 판단이 답변의 구체성에 따라 실제로 달라지는지
   확인해 볼 가치가 있다.
3. 코드 수정이 결정되면 별도 Phase에서, 이번 문서에 기록된 재현 가능한 4건의
   실제 사례를 회귀 기준선으로 활용할 수 있다.

---

## 최종 확인

- **실제 인터뷰**: 3건
- **실제 LLM 호출**: 총 6회 (건당 2회 × 3건)
- **1턴/2턴/3턴 종료**: 3 / 0 / 0
- **KNOWLEDGE 생성**: 3건, 모두 `pending`
- **운영 데이터**: ALL UNCHANGED
- **regression**: 332/332 PASS
- **코드 수정**: 없음
- **git commit/push**: 없음(`git status`만 확인, 이전과 동일한 44줄 - 커밋 여부는 사용자 검토 후 결정)
- **보고서 경로**: `docs/5-10_phase3_4_multi_interview_test.md`
