# 6-63 TAK GAME FACTORY — 후보 전략 + 학습형 게임 아키텍처

> 상태: **후보(CANDIDATE)**. 설계·데이터 구조·운영 원칙만 정한다. 게임 코드, 배포, 광고·결제는 이번 작업에 없다.
> MONEY 실제 수익 루프(6-57~6-62, `REAL_REVENUE_PENDING`, 첫 목표 실제 10,000원)가 계속 최우선이다.

## 1. Executive Summary

- **TAK GAME FACTORY** = AI로 3~5분짜리 초소형 웹게임을 빠르게 만들고, 실제 플레이 데이터로 살아남는 게임만 키우는 수익화 실험.
- 가장 유망한 갈래는 **LEARNING GAME ENGINE**: "상황 → 판단 → 결과 → 해설 → 다음 상황". TAK BRAIN KNOWLEDGE에는 이미
  `problem / decision / result / lesson / judgment_rule` 필드가 있다(`tak_brain/models.py` `KnowledgeRecord`). 그래서
  **새 지식 구조 없이** 시나리오 원료를 얻을 수 있다.
- 사용자는 개발자가 아니라 **Game Director / Playtest Director**다. AI가 만들고, 사용자가 재미를 판정한다.
- 착수 조건(15장)이 채워지기 전에는 대규모 개발을 하지 않는다. 첫 게임은 "대박"이 아니라 **수익화 가능성 검증 실험**이다.

## 2. Why Game Fits TAK AUTO

| TAK AUTO가 이미 가진 것 | 게임에서 쓰는 곳 |
|---|---|
| KNOWLEDGE(경험·사례·판단기준) — `tak_brain/models.py` | 시나리오·선택지·해설의 원료 |
| 소재군 재활용 전략 — `docs/6-62-first-real-money-run.md` 13~15장 | 게임을 Shorts/Threads/Blog 옆의 **네 번째 형식**으로 |
| Performance snapshot·측정 window — `content_engine/performance/`, `docs/6-34-performance-loop-and-monetization-measurement.md` | 게임 지표(start/completion/play_time/retry)를 같은 방식으로 |
| 고위험 주제 사람 검토 — `content_engine/media_strategy.py` `HIGH_RISK_KEYWORDS` | 금융·법률·세금 학습게임의 검토 게이트 |
| 출처 추적 — Shorts Studio `SOURCE_MISSING` 경고(`content_engine/shorts_studio.py`) | 학습게임 문항의 `source`/`source_date`/`version` |
| "측정 → 유지/개선/폐기" 루프 — 6-59 MONEY Performance Loop | KEEP / IMPROVE / KILL 판정 |

게임은 **콘텐츠 형식**이다. 새 사업을 따로 세우는 게 아니다. 같은 KNOWLEDGE에서 한 갈래가 더 생기는 것이다.

## 3. User Game Director Expertise

**Game Director Domain Expertise** (사용자 제공 정보):
- XT 시절부터 플레이: 페르시아의 왕자, 미래전쟁, 원숭이섬의 비밀, 킹스퀘스트 시리즈.
- 콘솔 세대 전체: SFC, PS1~PS5, Wii, Nintendo 3DS, Nintendo Switch.
- 특히 **Koei 전략·경영 계열, 삼국지 2~13**: 같은 장르의 시스템이 30년 동안 어떻게 늘고 줄었는지 직접 겪었다.

AI가 게임을 만드는 시대에 이 경험이 맡는 일:

| AI | 사용자 (Game / Playtest Director) |
|---|---|
| 아이디어 확장, 변형 20개 만들기 | 그중 재미있는 핵심 하나를 고르기 |
| 규칙·HTML/CSS/JS 구현 | 규칙이 재미있는지 판정 |
| 그래픽·효과음 보조 | 플레이 흐름(첫 선택까지의 속도, 긴장 곡선) 판정 |
| 밸런스 후보 수치 생성·시뮬레이션 | 밸런스 판정(삼국지식 "내정 vs 군비" 긴장이 살아 있는가) |
| 자동 테스트·빌드 | 불필요한 시스템 삭제(Koei 후기작의 과잉 시스템 경험) |
| 플레이 데이터 분석 | 핵심 재미 정의, **최종 출시 여부 결정** |

원칙: **재미 판정은 사람만 한다.** AI가 "재미있다"고 스스로 판정해 출시하지 않는다(MONEY의 "실제 참여는 사람" 원칙과 같다).

## 4. TAK GAME FACTORY Definition

- 목적: 작은 웹게임을 여러 개 실험해, 데이터로 살아남는 게임을 찾는다.
- 철학: "대작 하나를 만드는 것이 아니라, 작은 게임을 여러 개 실험하고 데이터로 살아남는 게임을 찾는다."
- 설계 기준(초소형 웹게임):
  - 브라우저에서 바로 실행, 설치 없음, **모바일 우선**(세로 390px에서 가로 스크롤 없음 — 기존 대시보드 검증 기준과 같음)
  - 한 판 3~5분, 규칙 설명 30초 이내, 첫 선택까지 최대한 빠르게
  - 핵심 재미는 하나
  - 초기에는 로그인·서버·광고·결제 **없음**(정적 파일 하나로 동작)
  - 먼저 검증: 재미와 반복 플레이 데이터
- 기본 단위: 3분 선택형 전략 / 5분 경영·타이쿤 / 선택형 학습 / 자격증·시험 대비 / 상식·퀴즈 / 직업·업무 시뮬레이션 / 인간관계 선택 / 금융 의사결정 / 고전·전략 사고.
- 장기 목표: **하나의 엔진 + 템플릿 5개(13장)로 여러 게임을 생산**. 게임마다 코드를 새로 쓰지 않고 데이터(JSON)만 바꾼다.

## 5. 3-Min Choice Strategy (TEMPLATE_A)

- 상황 한 줄: "당신은 작은 세력의 지도자다."
- 턴마다 선택 4개(예: 군비 확장 / 외교 강화 / 경제 투자 / 인재 영입). 변수 4~5개(자원·신뢰도·국력·관계·위험도)가 움직인다.
- 루프: 선택 → 결과(변수 변화 + 한 줄 사건) → 다음 선택 → 8~10턴 뒤 최종 결과(엔딩 3~5종).
- **랜덤 게임이 되지 않게**:
  - 모든 선택에는 이득과 대가가 함께 있다(예: 군비 +국력 −자원 +위험도).
  - 같은 선택을 연속하면 효율이 떨어진다.
  - 사건은 현재 변수 상태로 정해지고, 무작위는 작은 흔들림으로만 쓴다.
- 설계 검증(구현 시): AI가 무작위 전략·탐욕 전략·균형 전략으로 1,000판을 시뮬레이션한다. "한 가지 선택만 반복해 이기는 전략"이 없음을 자동 테스트로 확인한다.

## 6. 5-Min Tycoon (TEMPLATE_B)

- 무대: 작은 가게·카페·작은 회사·수협 지점·게임회사·농장·미디어 회사 중 하나.
- 제한 자원(돈·시간·직원·평판)으로 5분 동안(= 게임 속 12개월, 한 달에 1결정) 채용·가격·마케팅·투자·비용 절감·위험 관리를 정한다.
- 달마다 결과 보고서(매출·비용·평판) 한 장 → 12개월 뒤 점수 = 최종 순자산 + 평판 보너스.
- 긴장: "지금 투자(나중 수익) vs 지금 현금(위기 대비)". 월별 무작위 사건(원가 상승·경쟁점 개점)에 대비했는지가 차이를 만든다.

## 7. Learning Game (TEMPLATE_C) — LEARNING GAME ENGINE

```
SOURCE → KNOWLEDGE → 학습 소재 → 상황/문제 → 선택지 → 결과 → 해설 → 점수 → 약점 분석 → 재도전
```

예:
- [상황] 고객 A: 소득·담보·기존 부채·상환능력·목적이 주어진다.
- [선택] ① 즉시 승인 ② 추가 자료 요청 ③ 조건부 승인 ④ 거절
- [결과] 선택에 따른 결과를 보여 준다(연체·수익·고객 이탈 등).
- [학습] 왜 적절하거나 부적절한지 해설하고, 근거(`source`)를 표시한다.
- [다음 상황] 난이도가 오른다.

**KNOWLEDGE → 시나리오 매핑** (기존 `KnowledgeRecord` 필드 그대로, 새 필드 없음):

| 시나리오 요소 | KnowledgeRecord 필드 |
|---|---|
| 상황 | `experience`, `problem`, `case` |
| 정답 판단 | `decision`, `action` |
| 결과 | `result` |
| 해설 | `judgment_rule`, `lesson`, `reusable_principle` |
| 근거 | `evidence`, `source_url`, `source_raw_id` |
| 주제 | `category`, `domain`, `knowledge_type`(`판단기준`·`사례`가 가장 적합) |

- 원칙은 `media_strategy.suggest_content_angles`와 같다: **이미 채워진 필드만 쓴다.** KNOWLEDGE에 없는 판단을 AI가 지어내 "정답"으로 만들지 않는다.
- 오답 선택지는 AI가 만들 수 있다. 다만 **정답·해설은 KNOWLEDGE 근거가 있는 것만** 쓰고, `knowledge_review_status=approved`인 것만 원료로 쓴다.
- `derived_insight`(규칙 기반 도출)는 해설 보조로만 쓴다. 정답의 근거로는 쓰지 않는다.

## 8. Certification / Exam Learning Model

대상 후보: 공인중개사, 신용관리사, 자산관리사, 금융규정, 수협 업무. **지금은 문제은행을 만들지 않는다.**
미래 데이터 구조(설계만, 파일·코드 없음):

| 필드 | 뜻 |
|---|---|
| `subject` | 과목(예: 공인중개사/민법) |
| `topic` | 세부 주제 |
| `difficulty` | 1~5 |
| `scenario` | 상황 설명 |
| `question` | 묻는 것 |
| `choices` | 선택지 목록(id, 글) |
| `correct_answer` | 정답 choice id |
| `explanation` | 해설 |
| `source` | 근거(법령명·조문·기관 자료·KNOWLEDGE id) — **필수** |
| `source_date` | 근거 기준일(법령 시행일·자료 발표일) — **필수** |
| `version` | 문항 버전(근거가 바뀌면 올린다) |
| `score` | 배점 |
| `mistake_type` | 오답 유형(개념 혼동·예외 누락·계산 실수·최신 개정 미반영) |

추가 원칙:
- 법규·시험 기준은 바뀐다. `source_date`가 기준일보다 오래되면 문항을 **자동으로 숨기고** 사람이 재검토한다(stale 처리).
- 실제 기출문제 원문은 저작권 문제가 있어 그대로 쓰지 않는다. 개념을 새 상황으로 다시 쓴다.
- 금융·법률·세금·투자 주제는 `HIGH_RISK_KEYWORDS`(media_strategy)처럼 **사람 검토 필수**. 교육용 표시를 붙인다("실제 심사·법률 자문 아님").

## 9. Content Reuse

하나의 KNOWLEDGE → Blog / Shorts / Threads / **Game**:

| KNOWLEDGE | Blog | Shorts | Threads | Game |
|---|---|---|---|---|
| 사람을 설득하는 방법 | 설득의 구조 | 30초 설득 팁 | 한 줄 질문 | "당신이라면 어떻게 설득하겠는가?"(TEMPLATE_E) |
| 대출 심사 판단기준 | 대출 심사에서 보는 핵심 | 대출 심사 30초 | 대출 담당자가 보는 것 | "당신이 대출 심사역이라면?"(TEMPLATE_C) |
| 삼국지 인재 이야기 | 인재 등용의 원칙 | 조조의 인재관 30초 | 한 줄 인용 | 인재등용 게임(TEMPLATE_A) |

장기 구조:
```
TAK BRAIN → 소재군 → 콘텐츠 ─┬ Blog
                             ├ Shorts
                             ├ Threads
                             └ Game
                    → 반응 측정 → 상위 소재 → 확장
```

**혼동 방지 — 축 세 개를 분리한다:**

| 축 | 값 | 어디 있나 |
|---|---|---|
| **category** (KNOWLEDGE 분류) | 금융·대출·경매·부동산·인간관계·심리·자기계발·독서·건강·가족·골프·기타 | `tak_brain/models.py` `CATEGORIES` (코드) |
| **소재군** (콘텐츠 묶음) | 금융/대출 · 부동산 · 인간관계 · 고전/전략 · AI · 직장생활 | 6-62 문서 (전략, 코드 없음) |
| **형식** (어떻게 내보내나) | Blog · Shorts · Threads · **Game**(후보) | `media_strategy.PLATFORMS`=threads/blog/shorts (Game은 아직 없음) |

- "게임", "학습", "자격증"은 **소재군이 아니다.** "게임"은 형식이다. "학습/자격증"은 게임화할 수 있는 소재 성격(learning 모드)이다.
- **발견한 충돌**: 소재군 `고전/전략`·`AI`·`직장생활`에 맞는 `CATEGORIES` 값이 없다. 지금은 `독서`·`자기계발`·`기타`로 흩어진다.
  소재군 → category 매핑(전략 문서 수준): 금융/대출 → 금융·대출 · 부동산 → 부동산·경매 · 인간관계 → 인간관계·심리·가족 ·
  고전/전략 → 독서(+태그) · AI → 기타(+태그) · 직장생활 → 자기계발(+태그).
  `CATEGORIES` 변경은 KNOWLEDGE 스키마 변경이라 이번에 하지 않는다. 소재군별 성과 측정이 실제로 시작될 때 태그 방식과 함께 결정한다.

## 10. Game Monetization Candidates (후보만, 구현 없음)

| # | 수익원 | 초기 적합도 | 비고 |
|---|---|---|---|
| 1 | 광고(배너/전면) | 낮음 | 플레이 데이터 전에는 붙이지 않는다 |
| 2 | 보상형 광고(재도전·힌트) | 중간 | "재도전" 루프와 자연스럽게 맞음 |
| 3 | 게임 내 추가 콘텐츠(시나리오 팩) | 중간 | 학습게임과 맞음 |
| 4 | 프리미엄(유료) 게임 | 낮음 | 검증 전에는 아님 |
| 5 | 학습 콘텐츠 유료화 | 높음(장기) | 출처·버전 관리가 선행돼야 한다 |
| 6 | 자격증 시나리오 패키지 | 높음(장기) | 8장 구조가 전제 |
| 7 | 교육기관·기업용 라이선스 | 장기 | 금융 직무교육 등 |
| 8 | 게임 → Shorts/Blog/Threads 트래픽 | 즉시 가능(측정만) | 결과 화면 공유 |
| 9 | 게임을 콘텐츠 유입 장치로 | 즉시 가능(측정만) | Blog 글 속 "직접 판단해 보기" |

- 초기 순서: **플레이 → 반복 → 데이터**. 수익은 그다음이다.
- 게임 수익은 MONEY(`money_tasks`, 노가다형 작업)에 넣지 않는다. 콘텐츠 수익처럼 Performance 쪽에서 추적한다(17장).

## 11. Game Performance Metrics

- 조회수 하나로 판단하지 않는다.
- 최소 세트(초기): `game_start`, `completion`, `play_time`, `retry`.
- 전체 후보: `game_start`, `first_choice`, `completion`, `completion_rate`, `play_time`, `retry`, `replay_rate`, `score`, `share`, `return_play`, `ad_view`(향후), `purchase`(향후).

기존 구조 재사용안(설계, 구현 안 함):
- `PerformanceRecord.metrics`는 이미 `dict[str, int]`다. 그래서 `{"game_start": n, "completion": n, "play_time_sec": n, "retry": n}`로 **스키마 변경 없이** 담긴다.
  비율(`completion_rate` 등)은 저장하지 않고 계산한다(6-34 "필요 없는 필드 추가 금지"와 같은 원칙).
- 추가해야 할 것은 딱 두 가지다: `PLATFORMS`에 `"game"`, `SOURCES`에 게임 이벤트 집계 출처 하나. 둘 다 첫 게임이 실제로 측정될 때 추가한다.
- 측정 window는 `classify_measurement_window`(24h/72h/7d/30d)를 그대로 쓴다. 저장은 snapshot 방식(6-34 7장)이다.
- 초기 판정 기준(첫 실험용 가설, 데이터로 조정):
  - 완주율 ≥ 40%
  - 재도전률 ≥ 20%
  - 평균 플레이 시간이 설계 시간의 70~130%

## 12. Game Factory Pipeline

```
GAME IDEA → GAME DESIGN SPEC → TEMPLATE 선택 → AI GENERATION → AUTOMATED TEST → PLAYABLE BUILD
→ USER PLAYTEST → FEEDBACK → REVISION → PUBLISH CANDIDATE → PERFORMANCE → KEEP / IMPROVE / KILL
```

| 단계 | 누가 | 산출물 / 기준 |
|---|---|---|
| DESIGN SPEC | AI 초안 → 사용자 확정 | 1페이지: 핵심 재미 1줄, 템플릿, 변수, 턴 수, 엔딩 |
| AI GENERATION | AI | 템플릿 + 게임 데이터 JSON(엔진 코드는 재사용) |
| AUTOMATED TEST | AI | 데이터 검증, 자동 플레이 시뮬레이션(지배 전략 없음, 모든 엔딩 도달 가능), 390px 레이아웃 |
| USER PLAYTEST | **사용자** | 3판 플레이 → 재미 1~5, "지운다/남긴다" 목록 |
| PUBLISH CANDIDATE | **사용자 결정** | 출시 여부(자동 출시 없음) |
| KEEP/IMPROVE/KILL | 데이터 + 사용자 | 11장 기준 미달이면 KILL(버려도 되는 구조) |

- 게임 한 개에 몇 주를 쓰지 않는다. 목표: 아이디어에서 플레이 가능한 빌드까지 **하루 이내**.
- Shorts 파이프라인과 같은 형태다: 초안 → 자동 검사 → 사람 검토 → 출시. Shorts Studio의 "사람이 최종 확인" 원칙을 따른다.

## 13. Game Templates

| 템플릿 | 핵심 루프 | 대표 게임 |
|---|---|---|
| TEMPLATE_A Choice Strategy | 턴 선택 → 변수 변화 → 엔딩 | 3분 전략가, 인재등용, 역사 전략 |
| TEMPLATE_B Mini Tycoon | 월별 결정 → 보고서 → 12개월 점수 | 5분 타이쿤, 수협 지점장, AI 회사 |
| TEMPLATE_C Learning Scenario | 상황 → 판단 → 결과 → 해설 | 대출 심사, 자격증 판단 |
| TEMPLATE_D Quiz + Decision | 퀴즈 정답 → 보상으로 결정권 | 상식 + 자원 배분 |
| TEMPLATE_E Relationship Choice | 대화 선택 → 관계 수치 → 결말 | 인간관계, 직장 생존 |

**공통 인터페이스**(개념, 코드 없음):

| 이름 | 역할 |
|---|---|
| `GameConfig` | id, template, title, 목표 플레이 시간, 턴 수, 변수 정의(이름·초기값·범위), 엔딩 규칙, 모드(`play` / `learning`) |
| `GameState` | 현재 턴, 변수 값, 선택 기록, 시작 시각 |
| `Choice` | id, 글, 조건(보이는 조건), effects(변수 변화) |
| `Outcome` | 선택 결과: 변화량, 사건 글, (learning) 정답 여부·해설 |
| `Score` | 최종 점수 계산식 + 세부 항목 |
| `Ending` | 조건, 제목, 설명, 공유 문구 |
| `Source` | knowledge_id, source_url, source_date, version (learning 모드 필수) |
| `AnalyticsEvent` | event(`game_start`/`first_choice`/`completion`/`retry`…), game_id, game_version, 시각, 턴, (개인정보 없음) |

기존 구조 재사용:
- `Source` → KnowledgeRecord의 `id` / `source_url` / `evidence` 연결을 그대로 쓴다(새 출처 체계 없음).
- `AnalyticsEvent` 집계 → `PerformanceRecord.metrics`(11장).
- 공유 결과 문구·짧은 해설 → Shorts/Threads 초안의 소재로 쓴다(`media_strategy.build_generation_handoff`와 같은 handoff 방식).
- 게임 데이터 파일은 **스키마 검증 + 자동 시뮬레이션** 테스트로 보호한다(Shorts v3 contract가 문서를 검증하는 방식과 같음).

## 14. First 10 Game Candidates (설계만)

**1. 3분 전략가** (A)
- 루프: 작은 세력, 8턴, 선택 4개(군비·외교·경제·인재)
- 시간: 3분
- 승패: 엔딩 4종(천하통일·동맹 맹주·멸망·은둔). 점수 = 국력 + 신뢰
- 재플레이: 매 판 시작 조건(이웃 세력 성향)이 다르다
- 학습: 트레이드오프 사고
- 콘텐츠: "3분 만에 천하통일한 선택" Shorts

**2. 5분 카페 타이쿤** (B)
- 루프: 12개월 × 결정 1(가격·원두·알바·홍보)
- 시간: 5분
- 점수: 순자산 + 평판
- 재플레이: 매 판 사건 순서가 다르고 최고 점수에 도전
- 학습: 원가·마진·고정비 감각
- 콘텐츠: "카페 망하는 3가지 선택" Blog

**3. 인간관계 선택게임** (E)
- 루프: 갈등 장면 6개(친구·가족·동료)마다 대화 선택 3개
- 관계 수치: 신뢰·거리감
- 시간: 3분
- 엔딩: 관계 유형 5종 + 짧은 해설
- 재플레이: 다른 엔딩 수집
- 학습: 소통 원칙(KNOWLEDGE 인간관계·심리 category)
- 콘텐츠: Threads 질문 "당신이라면?"

**4. 대출 심사 게임** (C)
- 루프: 고객 카드 8장(소득·담보·부채·목적)마다 승인·조건부·추가서류·거절 중 선택
- 판정: 결과 = 연체·수익·고객 만족
- 시간: 4분
- 점수: 정확도 + 수익
- 재플레이: 틀린 유형만 다시(약점 분석)
- 학습: 높음(판단기준 KNOWLEDGE)
- 가드레일: 고위험 주제 → 사람 검토, "교육용" 표시
- 콘텐츠: Shorts "대출 심사 30초"

**5. 수협 지점장 게임** (B)
- 루프: 12개월 지점 운영(예금 유치·대출 한도·인력·지역 행사)
- 긴장: 연체율과 실적 사이
- 시간: 5분
- 점수: 실적 + 건전성
- 재플레이: 지역(어촌·도시) 조건이 달라진다
- 학습: 금융기관 운영 감각(일반화된 내용만, 내부정보 금지 — `_INTERNAL_PATTERN` 원칙)
- 콘텐츠: 직장생활 소재군

**6. 삼국지식 인재등용** (A)
- 루프: 인재 카드 10장(능력치 4 + 성향)마다 등용·보류·거절
- 제약: 한정된 봉록
- 시간: 3분
- 점수: 최종 전투·내정 결과
- 재플레이: 인재 풀이 매번 다르다
- 학습: 사람 보는 기준(고전/전략 소재군)
- 핵심 재미 정의는 Game Director의 Koei 경험을 가장 직접적으로 쓴다
- 콘텐츠: "조조라면 누구를 뽑았을까" Shorts

**7. 직장 생존게임** (E)
- 루프: 입사 1년, 사건 10개(보고·회식·갈등·야근 요청)
- 수치: 평판·체력·성과
- 시간: 4분
- 엔딩: 승진·번아웃·이직 등
- 재플레이: 엔딩 수집
- 학습: 직장 커뮤니케이션
- 콘텐츠: 직장생활 소재군 Threads

**8. AI 회사 경영** (B)
- 루프: 12분기(모델 개발·데이터·인력·마케팅·규제 대응)
- 시간: 5분
- 점수: 기업가치
- 재플레이: 기술 트렌드 사건이 무작위로 바뀐다
- 학습: AI 산업 구조(AI 소재군)
- 콘텐츠: Blog "AI 스타트업이 망하는 선택"

**9. 자격증 판단게임** (C/D)
- 루프: 과목 하나(예: 공인중개사 민법 중 한 주제), 상황형 10문항
- 즉시 해설, 오답 유형(`mistake_type`) 분석
- 시간: 5분
- 점수: 정답률 + 연속 정답
- 재플레이: 약점 유형만 다시
- 학습: 최고
- 전제: 8장의 source·version·stale 관리가 먼저(없으면 착수 금지)
- 콘텐츠: Shorts "헷갈리는 조항 30초"

**10. 역사 전략 선택게임** (A)
- 루프: 실제 역사 분기점 5개마다 선택 3개
- 결과: 가상 역사 전개 + "실제로는 이렇게 됐다" 해설
- 시간: 4분
- 재플레이: 다른 결말
- 학습: 역사(출처 필수)
- 콘텐츠: Shorts "만약 그때 다른 선택을 했다면"

## 15. Launch Criteria (실제 개발 착수 조건)

아래가 **모두** 채워지기 전에는 대규모 GAME FACTORY 개발을 하지 않는다.

- [ ] MONEY 실제 수익 데이터가 일부 쌓임(현재 `REAL_REVENUE_PENDING`, 0원 → **미충족**)
- [ ] 콘텐츠 성과 데이터 축적(소재군별 반응 — 6-62 14장 → **미충족**)
- [ ] 기존 TAK AUTO 핵심 루프 안정(MONEY·Shorts·Performance)
- [ ] 첫 게임의 목적이 한 줄로 정의됨(예: "학습형 게임의 완주율·재도전률 검증")
- [ ] 범위 3~5분, 서버·로그인 없이 동작
- [ ] 개발 기간 상한(예: 첫 플레이 빌드까지 1일, 전체 1주)
- [ ] 실패하면 버릴 수 있는 구조(기존 코드와 분리된 정적 파일)

첫 게임 추천 순서(착수 시): **4 대출 심사**(학습 가설, KNOWLEDGE 원료 있음) 또는 **6 인재등용**(Director 전문성, 출처 부담 적음).
9 자격증은 8장 구조가 갖춰진 뒤에 한다.

## 16. Risks / Guardrails

| 위험 | 가드레일 |
|---|---|
| MONEY 우선순위가 흐려짐 | 착수 조건 1번(실제 수익 데이터). 이 문서는 MONEY 코드·데이터를 건드리지 않는다 |
| 틀린 금융·법률 정보를 "정답"으로 가르침 | 정답은 승인된 KNOWLEDGE 근거만, `source_date`·`version`·stale 숨김, 고위험 주제 사람 검토, 교육용 표시 |
| 기출문제 저작권 | 원문을 쓰지 않고 개념을 새 상황으로 재구성 |
| 내부정보 유출(수협 등) | `tak_brain` 개인정보/금융/내부정보 패턴 원칙과 같음 — 일반화된 내용만 |
| 랜덤 게임(재미 없음) | 자동 시뮬레이션으로 지배 전략·무의미한 선택 검출 + 사람 플레이테스트 |
| 범위 폭주(대작화) | 3~5분·템플릿 5개 고정, 새 시스템은 Director 승인 |
| 가짜 지표 | 플레이 데이터는 실제 이벤트만, 시뮬레이션 결과를 성과로 섞지 않음(MONEY "예상 vs 실제" 분리와 같은 원칙) |
| 개인정보 | 분석 이벤트에 개인정보 없음, 초기 로그인 없음 |
| 광고·결제 | 데이터 검증 전에는 연결 안 함 |

## 17. Relationship to MONEY

- MONEY(6-57~6-62)는 "이미 있는 온라인 노가다 기회를 찾아 사람이 수행 → 실제 원·분 기록"이다. 게임은 **만드는 자산**이라 성격이 다르다.
- 그래서 게임은 `money_tasks.json`의 플랫폼이 아니다. 나중에 게임 수익이 생기면 콘텐츠 수익처럼 Performance(`metrics`)로 추적한다.
  MONEY의 "실제 수익" 합계와 섞지 않는다.
- 공유하는 원칙: 예상과 실제 분리, 실제 데이터로만 판정, 표본이 적으면 강하게 학습하지 않음(6-59 최소 표본), 사람이 최종 판단.
- 현재 MONEY 상태(변경 없음): 실제 기회 2건, 실제 수익 0원, `REAL_REVENUE_PENDING`, 첫 목표 실제 10,000원.

## 18. Relationship to TAK BRAIN / MEDIA

| 연결 | 기존 위치 | 게임에서의 역할 |
|---|---|---|
| RAW → KNOWLEDGE | `tak_brain/models.py`, `docs/knowledge_extraction_design.md` | 학습 시나리오 원료(7장 매핑) |
| category | `tak_brain/models.py` `CATEGORIES` | 게임 주제 분류(소재군과 분리, 9장) |
| Media Strategy | `content_engine/media_strategy.py` | 형식 판정 방식을 Game에 확장할 후보(PLATFORMS에 아직 없음) |
| 고위험 검토 | `media_strategy.HIGH_RISK_KEYWORDS` | 금융·법률 학습게임 게이트 |
| Shorts Studio | `content_engine/shorts_studio.py`, `docs/6-55-shorts-content-studio.md` | 게임 결과 → Shorts 소재, "사람이 최종 확인" 원칙 |
| Performance | `content_engine/performance/`, `docs/6-34-…`, `docs/performance_operations.md` | 게임 지표 저장·window |
| MONEY | `content_engine/money.py`, `docs/6-62-first-real-money-run.md` | 분리(17장) |
| 소재군 전략 | `docs/6-62-first-real-money-run.md` 13~15장 | Game = 네 번째 형식 |

## 19. Future Roadmap

| 단계 | 조건 | 할 일 |
|---|---|---|
| G0 (지금) | — | 이 문서: 후보 전략·템플릿·데이터 구조 |
| G1 | 착수 조건 충족 (예외: 6-64에서 사용자 지시로 **선택100 금융 G1 프로토타입**을 먼저 만듦 — 로컬 전용, 배포·광고·결제 없음, `docs/6-64-choice100-finance-g1.md`) | 첫 게임 1개(4 또는 6): 정적 HTML 1개 + 게임 데이터 JSON + 자동 시뮬레이션 테스트, 로컬 플레이테스트만 |
| G2 | G1 플레이테스트 통과 | 공개 없이 지인 테스트 → 이벤트 4개 수동 집계 → Performance 기록(`platform="game"` 추가) |
| G3 | 완주율·재도전 기준 충족 | 공개 후보(사람 결정), 콘텐츠 연결(Shorts/Blog 유입 측정) |
| G4 | 게임 2~3개 데이터 | 엔진·템플릿 공통화, 학습 문항 구조(8장) 구현 |
| G5 | 반복 성과 확인 | 수익화 후보(보상형 광고·시나리오 팩) 검토 |

## 20. Explicitly NOT IMPLEMENTED

이번 작업에서 **하지 않은 것**:
- 게임 코드·HTML·엔진·템플릿 구현, 게임 데이터 파일
- 게임 배포, 외부 게임 플랫폼 계정, 새 GitHub 저장소
- 광고·보상형 광고·IAP·결제 연동
- 자격증 문제은행, 기출문제 수집
- `PerformanceRecord.PLATFORMS`에 `game` 추가, `media_strategy.PLATFORMS` 변경, `CATEGORIES` 변경
- MONEY 코드·데이터 변경, 실제 수익 기록 생성, 가짜 플레이·수익 데이터
- PanelNow 접근·클릭·응답, 로그인/OTP/CAPTCHA 자동화
- Production Archive·ShortsScript·YouTube·Threads·KNOWLEDGE·SCOUT 데이터 변경
- 새 dependency

## 연결된 기존 문서

- `docs/6-62-first-real-money-run.md` — 소재군 재활용·반응 측정·채널 분리 후보(13~15장). 이 문서 9장이 형식 축(Game)과 category 매핑으로 확장한다.
- `docs/6-61-money-real-revenue-loop.md`, `docs/6-59-money-performance-loop.md`, `docs/6-58-money-opportunity-operations.md` — MONEY 원칙(예상 vs 실제, 최소 표본).
- `docs/6-34-performance-loop-and-monetization-measurement.md` — snapshot·window·monetization 원칙(11장 재사용).
- `docs/6-37-media-strategy-quality-gate.md` — 형식별 적합성 판정·고위험 검토.
- `docs/6-55-shorts-content-studio.md` — 사람 최종 확인 원칙.
- `docs/knowledge_extraction_design.md` — KNOWLEDGE 필드(7장 매핑).
