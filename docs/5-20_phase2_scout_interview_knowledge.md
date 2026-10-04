# TAK AUTO Phase 2 — SCOUT TOP 5 → 인터뷰 → KNOWLEDGE 연결

## 0. 핵심 발견

코드 조사 결과, Phase 2가 요구한 흐름(SCOUT TOP 5 → 후보 선택 → InterviewSession →
AI 질문 → 답변 → 충분성 판단 → 최대 3턴 → KNOWLEDGE draft → 승인 대기)은
**이미 미커밋 상태로 거의 완전히 구현되어 있었다** (`docs/5-10_interview_2_design.md`,
`docs/5-10_phase2_dashboard_multiturn.md`, `docs/5-19_daily_pipeline_investigation.md`에
설계·구현 기록이 남아 있음). 이번 작업은 "새로 만드는 것"이 아니라 **"이미 있는
것을 검증하고, 작은 빈틈 하나를 메우고, 실제 SCOUT 데이터로 연결해 커밋하는 것"**이었다.

## 1. 기존 구현에서 재사용한 부분 (수정 없음)

| 모듈/함수 | 역할 |
|---|---|
| `tak_scout.collector.load_daily_pack` | `data/tak_scout_daily.json`(SCOUT TOP 5) 읽기 |
| `tak_scout.scoring.rank_candidates` | SCOUT SCORE 기준 정렬 |
| `tak_scout.interview_session.InterviewSession/InterviewTurnRecord` + load/save/upsert | 멀티턴 세션 저장 계층 (scout_id당 세션 1개) |
| `tak_scout.interview_llm.InterviewLLMProvider` | LLM 첫 질문 생성 + 후속 질문/충분성 판단(`decide_next_turn`), 최대 3턴 하드 제한, `option_d` 서버 강제 고정 |
| `tak_scout.answers.InterviewAnswer/upsert_answer` | 최종 합성 답변 저장 (스키마 변경 없음) |
| `tak_scout.knowledge_bridge.build_knowledge_from_interview` / `append_scout_knowledge` | KNOWLEDGE 생성(항상 `pending`) |
| `content_engine.LLMConfigurationError/LLMResponseError` | 예외 클래스만 재사용(이미 커밋된 `content_engine/llm_provider.py`) |
| `content_engine.threads_review.*` | 기존 Threads 검수 라우트(이번 작업과 무관, 손대지 않음) |

**새로 만들지 않은 이유**: 위 모든 모듈이 이미 5-10/5-11 단계에서 설계·구현되어 있었고,
`tak_scout/knowledge_bridge.py`, `tak_scout/answers.py`, `tak_scout/interview.py`는
**이번 세션에서도 단 한 줄도 수정하지 않았다**.

## 2. 새로 만든 파일

없음. 아래 "수정한 파일" 표의 파일들은 전부 이전 세션에서 이미 작성되어 있었고,
이번 세션에서는 그중 `scripts/run_scout_dashboard.py`에 작은 기능 하나(카드에 요약
표시)만 추가했다.

## 3. 이번 세션에서 수정/커밋한 파일

| 파일 | 상태 | 이번 세션에서 한 일 |
|---|---|---|
| `tak_scout/interview_session.py` | 커밋(신규) | 검증만 함, 코드 변경 없음 |
| `tak_scout/interview_llm.py` | 커밋(신규) | 검증만 함, 코드 변경 없음 |
| `tak_scout/dashboard_state.py` | 커밋(신규) | 검증만 함, 코드 변경 없음 |
| `tak_scout/__init__.py` | 커밋(수정) | `scoring` export 1줄(이미 있던 미커밋 diff를 그대로 커밋에 포함 — `run_scout_dashboard.py`가 `ScoutScore`/`rank_candidates`를 쓰므로 필수) |
| `scripts/run_scout_dashboard.py` | 커밋(신규) | **후보 카드에 `candidate.summary`("짧은 요약") 표시 추가** — 사용자가 명시한 카드 스펙(순위/제목/source/SCOUT SCORE/짧은 요약/URL/선택 버튼) 중 요약만 누락되어 있던 유일한 빈틈이었다. CSS 규칙 1개도 함께 추가. |
| `tests/test_interview_session.py` | 커밋(신규) | 검증만 함 |
| `tests/test_interview_llm.py` | 커밋(신규) | 검증만 함 |
| `tests/test_scout_dashboard.py` | 커밋(수정) | 요약 표시를 검증하는 테스트 1개(`test_list_shows_short_summary_for_each_candidate`) 추가 |

**이번 커밋에 포함하지 않은 것**: `content_engine/*`, `docs/*`(이 보고서 제외), 기타
YouTube/Blog/Firebase 관련 미커밋 파일 전부 — Phase 2 범위(SCOUT→인터뷰→KNOWLEDGE)와
무관하므로 그대로 미커밋 상태로 남겨뒀다. `content_engine/__init__.py`는 이미 커밋된
버전에 `LLMConfigurationError`/`LLMResponseError`가 이미 export되어 있어 이번 기능이
그 파일을 전혀 필요로 하지 않음을 확인했다(4번 참고).

## 4. 전체 흐름 (구현/검증된 그대로)

```
GET  /                              SCOUT TOP N 카드 목록 (순위·SCORE·요약·출처·URL·선택/관심없음)
  │  사용자가 "이 소재로 답변하기" 클릭
  ▼
GET  /candidate/{scout_id}          세션 없으면 turn 1 생성(LLM 우선 시도, 실패 시 고정 템플릿)
  │  A/B/C 버튼 또는 D(직접 입력) 텍스트 제출
  ▼
POST /candidate/{scout_id}/answer   현재 턴 답 기록
  │  turn < 3 → LLM decide_next_turn 시도(충분/불충분 판단 + 다음 질문)
  │             실패/없음 → 고정 템플릿 fallback
  │  turn == 3 → LLM 호출 없이 무조건 종료(비용 상한 강제)
  ▼
(반복, 최대 3턴)
  ▼
GET  /candidate/{scout_id}/review   Q1~Q3/답변 전문 표시 + [KNOWLEDGE 만들기]/[다시 답변하기]
  ▼
POST /candidate/{scout_id}/finalize 세션 → InterviewAnswer(D, 합성텍스트) → upsert_answer
                                     → append_scout_knowledge → KNOWLEDGE(pending) 1건 생성
  ▼
review_knowledge.py --approve       (이번 범위 밖, 사람이 별도로 실행)
```

LLM이 없거나 모든 호출이 실패해도 시스템 전체가 100% 동작한다(고정 템플릿 3종으로
자동 대체). API 키는 서버 프로세스 안에서만 쓰이고 브라우저에 노출되지 않는다.

## 5. 테스트 결과

```
$ python3 -m pytest -q
570 passed, 68 subtests passed
```

사용자가 요구한 13개 최소 테스트 항목 전부 기존 테스트 스위트에 이미 존재함을
확인했다(이번 세션에서 1개 추가로 14번째 항목 보강):

| # | 요구 항목 | 커버하는 테스트 |
|---|---|---|
| 1 | TOP 5 표시 | `test_list_reads_daily_pack_and_sorts_by_score` |
| 2 | 후보 선택 | `test_first_visit_creates_session_with_template_turn_one` 등 |
| 3 | scout_id로 InterviewSession 생성 | 〃 |
| 4 | 첫 질문 생성 | `test_llm_first_question_success_sets_generated_by_llm`, `test_success_returns_turn_one` |
| 5 | 답변 저장 | `test_full_three_turn_flow_a_then_d_then_b` |
| 6 | sufficient=true 종료 | `test_sufficient_true_completes_immediately_and_shows_review`, `test_sufficient_true_returns_no_next_turn` |
| 7 | sufficient=false 추가 질문 | `test_sufficient_false_shows_and_stores_next_turn`, `test_sufficient_false_returns_next_turn` |
| 8 | 최대 3턴 제한 | `test_turn_three_never_calls_decide_next_turn_and_completes` |
| 9 | KNOWLEDGE draft 생성 | `test_finalize_after_llm_driven_session_keeps_existing_knowledge_structure` |
| 10 | 원문 답변 보존 | `test_direct_input_preserved_through_llm_flow`, `test_custom_answer_original_text_passed_through_unchanged` |
| 11 | 승인 전 approved 안됨 | `append_scout_knowledge`가 항상 `pending` 생성(구조적 보장) + 실제 E2E로 재확인(7번) |
| 12 | 존재하지 않는 scout_id | `test_unknown_scout_id_returns_404_on_new_routes` + 실제 E2E로 재확인 |
| 13 | 잘못된/빈 답변 처리 | `test_invalid_option_does_not_crash_or_advance_turn`, `test_option_d_without_custom_answer_is_rejected` |
| (신규) | 카드에 짧은 요약 표시 | `test_list_shows_short_summary_for_each_candidate` |

**실제 LLM API 테스트와 단위 테스트 분리**: `tests/test_interview_llm.py`,
`tests/test_scout_dashboard.py`의 LLM 관련 테스트는 전부 `unittest.mock.patch` 또는
`FakeInterviewLLMProvider`로 HTTP transport를 대체한다. `grep`으로 저장소 전체
테스트를 확인한 결과 실제 네트워크를 호출하는 자동화 테스트는 하나도 없다(가짜
API 키 `"TEST_SECRET_KEY_123"`만 환경변수 검증용으로 사용).

## 6. 실제 E2E 테스트 결과 (실제 SCOUT JSON, 격리된 임시 디렉터리)

`data/tak_scout_daily.json`(오늘 실제 수집된 TOP 5)을 임시 디렉터리로 복사하고,
`--daily-pack/--answers/--knowledge/--skipped/--sessions`를 전부 그 임시 디렉터리로
지정해 실제 Dashboard 서버(`scripts/run_scout_dashboard.py`, 포트 8199)를 백그라운드로
띄워 실제 HTTP 요청으로 검증했다. `TAK_MEDIA_LLM_API_KEY` 등은 의도적으로 비워
템플릿 fallback 경로로 진행했다(실제 LLM 과금/외부 호출 없음). 외부 SNS 발행은
전혀 수행하지 않았다.

```
GET  /                                    → 200, TOP 5 카드 5개, "이 소재로 답변하기" 5개,
                                             신규 추가한 요약 텍스트("Central banks around
                                             the world...") 정상 표시
GET  /candidate/scout-a39f6e89baf9        → "질문 1 / 3"
POST .../answer option=A                  → 303 → "질문 2 / 3"
POST .../answer option=D,
     custom_answer="대출 고객들의 이자 부담이 바로 커지고 신규 대출 심사도
                     더 보수적으로 변할 가능성이 있다고 봅니다."
                                           → 303 → "질문 3 / 3"
POST .../answer option=B                  → 303 → /review
GET  .../review                           → Q1/Q2/Q3 + D 턴 원문 그대로 표시
POST .../finalize                         → 303 → "저장되었습니다. TAK BRAIN
                                             KNOWLEDGE(pending)로 연결했습니다."
GET  /                                    → 해당 카드 "이미 답변함"으로 표시
GET  /candidate/scout-does-not-exist      → 404 (존재하지 않는 scout_id)
```

테스트 후 서버 프로세스를 종료했고, 실제 운영 데이터
(`data/tak_scout_daily.json`, `data/tak_interview_answers.json`,
`data/tak_brain_knowledge.json`)는 이 E2E 테스트로 전혀 변경되지 않았음을 `git status`로
확인했다(`data/tak_brain_knowledge.json`의 기존 `M` 표시는 이번 세션 이전부터 있던
별개의 미커밋 변경이며 이번 E2E와 무관).

## 7. KNOWLEDGE 생성 결과 (E2E 테스트, 격리된 파일에 생성됨)

```json
{
  "id": "knowledge-scout-ba40d3d0eec3",
  "source_raw_id": "scout-a39f6e89baf9",
  "source_url": "https://www.bbc.co.uk/news/articles/cqn74jeek06no?...",
  "title": "Japan raises interest rate to new 31-year high to curb rising prices",
  "knowledge_review_status": "pending",
  "evidence": [
    "SOURCE FACT: Central banks around the world have hiked rates as high energy prices are pushing up inflation.",
    "SOURCE URL: https://www.bbc.co.uk/news/articles/cqn74jeek06no?...",
    "USER ORIGINAL THOUGHT: Q1. 이 소재에 대해 어떻게 생각하시나요?\nA1. 긍정적으로 본다\n\nQ2. 그렇게 생각하게 된 이유나 경험이 있나요?\nA2. 대출 고객들의 이자 부담이 바로 커지고 신규 대출 심사도 더 보수적으로 변할 가능성이 있다고 봅니다.\n\nQ3. 이 주제에 대해 다른 사람에게 가장 전하고 싶은 생각은 무엇인가요?\nA3. 신중하게 접근해야 한다"
  ]
}
```

- 상태: `pending` (자동 승인 없음) — 확인됨
- 사용자가 turn 2에서 실제로 입력한 문장이 한 글자도 바뀌지 않고 그대로 포함됨 — 확인됨
- `source_raw_id`로 scout_id 연결 유지 — 확인됨

## 8. commit hash

- `3640847` — `feat: connect SCOUT TOP N to multi-turn LLM interview and KNOWLEDGE draft`
  (8개 파일: `scripts/run_scout_dashboard.py`, `tak_scout/dashboard_state.py`,
  `tak_scout/interview_llm.py`, `tak_scout/interview_session.py`, `tak_scout/__init__.py`,
  `tests/test_interview_llm.py`, `tests/test_interview_session.py`, `tests/test_scout_dashboard.py`)
- `cf9ff6e` — 그 사이 워크플로우가 자동 생성한 SCOUT 결과 갱신 커밋과의 병합(force push 없음)

## 9. push 성공 여부

성공. `fea6e01..cf9ff6e main -> main`, local main == origin/main(`cf9ff6e`) 확인됨.
기존 미커밋 변경사항(`content_engine/*`, `.gitignore`의 다른 pending 라인,
`data/tak_brain_knowledge.json` 등)은 전부 그대로 보존됨.

## 10. 다음 Phase에서 필요한 작업

1. **Codespace가 켜져 있을 때만 Dashboard 접속 가능** — 매일 아침 실제로 쓰려면
   Codespace를 그 시점에 켜두거나(5-19 문서에서 이미 지적된 제약), 항상-켜진
   호스팅을 별도로 검토해야 한다. 이번 범위 밖.
2. **"인터뷰 진행 중" 중간 상태가 목록에 안 보임** — 3턴 중 일부만 답한 소재가
   목록에서 "아직 답변하지 않음"으로만 보인다(5-10 Phase 2 문서에서 이미 기록된
   기존 한계). 필요하면 다음 단계에서 배지 추가 검토.
3. **`follow_up` 필드로 evidence를 턴별로 분리하는 안(9-2, 5-10 설계 문서)** —
   지금은 3턴을 하나의 텍스트 블록으로 합쳐 저장한다. 실사용 후 KNOWLEDGE 검토가
   불편하면 하위호환 필드 추가를 검토.
4. **KNOWLEDGE 승인 이후 TAK MEDIA 연결(Blog/Shorts/Threads 초안 생성)** —
   `review_knowledge.py --approve` 이후 단계는 이미 존재하는 별도 파이프라인
   (`run_media_batch.py` 등)과 연결하는 것이 다음 Phase.
5. **Threads 자동 게시 cron 충돌 처리** — 5-19 문서 3-a에서 이미 지적된 대로,
   `daily-threads-post.yml`이 여전히 사람 승인 없이 자동 게시 중이다. 이번 Phase와
   직접 관련은 없지만, "자동 공개하지 않는다"는 원칙을 전체 파이프라인에 일관되게
   적용하려면 별도 결정이 필요하다(코드 문제가 아니라 운영 결정).
