# 5-10 Phase 2 — TAK SCOUT 멀티턴 인터뷰 Dashboard UX 구현

`docs/5-10_interview_2_design.md`(설계)와 `docs/5-10_phase1_session.md`(세션
데이터 계층)를 기반으로, 기존 1회성 Dashboard 인터뷰를 **최대 3턴 고정
템플릿 멀티턴 인터뷰**로 연결했다. **LLM은 코드 어디에도 호출하지
않았다.** git commit/push는 하지 않았다.

## 1. 구현 파일

이번 단계에서 완전히 새로 만든 파일은 없다 — Phase 1에서 만든
`tak_scout/interview_session.py`를 그대로 가져다 썼고, 나머지는 5-9에서
이미 존재하던 두 파일을 Phase 2 요구사항에 맞게 확장했다(2번 참고).

## 2. 변경 파일

| 파일 | 종류 | 설명 |
|---|---|---|
| `scripts/run_scout_dashboard.py` | 수정(5-9 → 5-10 Phase 2) | 단일 질문 화면을 멀티턴 세션 기반으로 교체, `/review`·`/finalize`·`/restart` route 추가 |
| `tests/test_scout_dashboard.py` | 수정(5-9 → 5-10 Phase 2) | 옛 1회성 답변 테스트를 멀티턴 흐름 테스트로 교체 + 신규 테스트 추가 |
| `docs/5-10_phase2_dashboard_multiturn.md` | 신규 | 이 보고서 |

**이번 단계에서 건드리지 않은 파일**(요청받은 금지 목록 그대로 확인):
`content_engine/*`, TAK MEDIA, Threads publisher, Naver 관련 코드,
`tak_scout/scoring.py`, `scripts/run_scout.py`, `tak_scout/answers.py`,
`tak_scout/knowledge_bridge.py`, `tak_scout/interview.py`,
`tak_scout/interview_session.py`, GitHub Actions, 기존 실제 데이터 파일
전부. `git status`로 확인했다(9번 참고).

## 3. route 변경 내용

5-9의 route 5개 중 3개는 그대로 두고, `/candidate/{id}`와
`/candidate/{id}/answer`의 **내부 동작만** 세션 기반으로 바꿨다. 신규
route 2개를 추가했다.

| Route | 5-9(이전) | 5-10 Phase 2(이후) |
|---|---|---|
| `GET /` | 소재 목록 | **변경 없음** |
| `POST /candidate/{id}/skip` | 관심 없음 표시 | **변경 없음** |
| `GET /candidate/{id}` | `build_interview_question()`로 고정 질문 1개 표시 | 세션이 없으면 turn 1 생성, 있으면 마지막(미답변) turn 표시. `status=="completed"`면 `/review`로 303 리다이렉트 |
| `POST /candidate/{id}/answer` | `InterviewAnswer` 1건 즉시 저장 + 즉시 `append_scout_knowledge` 호출 | 세션의 현재 turn에 답 기록 → 3턴 미만이면 다음 turn 생성 후 `?saved=1`로 302, 3턴째면 `status="completed"`로 만들고 `/review`로 303 (여기서는 아직 KNOWLEDGE를 건드리지 않는다) |
| `GET /candidate/{id}/review` | 없음 | **신규.** 세션이 없거나 미완료면 `/candidate/{id}`로 안내, 완료됐으면 STEP 8 화면 표시 |
| `POST /candidate/{id}/finalize` | 없음 | **신규.** 완료된 세션 → `InterviewAnswer` 합성 → `upsert_answer` → `append_scout_knowledge`(pending) |
| `POST /candidate/{id}/restart` | 없음 | **신규.** 세션을 삭제하지 않고 turn 1부터 다시 시작하도록 초기화 |

기존 route를 삭제하지 않았고(`/`, `/skip`은 완전히 그대로), 요청받은 대로
"현재 구조를 최대한 유지하면서" 확장했다.

## 4. Session 데이터 흐름

```
GET /candidate/{id} (최초 방문)
    │  find_session() → 없음
    ▼
get_or_start_session()
    │  InterviewSession(status="in_progress", turns=(turn1,))
    │  turn1 = 고정 템플릿, generated_by="template", selected_option=None
    ▼
upsert_session(sessions_path, session)   ← data/tak_interview_sessions.json에 저장
    │
    ▼
[화면: Turn 1 표시] → 사용자가 A/B/C/D 선택
    │
    ▼
POST /candidate/{id}/answer
    │  handle_turn_answer_submission(session, form, sessions_path)
    │  - 현재(마지막) turn에 selected_option/custom_answer/answered_at 기록
    │  - len(turns) < 3 → 다음 turn(고정 템플릿) 추가, status 그대로 in_progress
    │  - len(turns) == 3 → status="completed", completed_at 기록
    ▼
upsert_session(...) 로 매번 즉시 저장(다음 턴 생성 시점에도, 완료 시점에도)
    │
    ▼
(반복: turn 2, turn 3)
    │
    ▼
GET /candidate/{id}/review  (status=="completed"일 때만 정상 표시)
    │
    ▼
POST /candidate/{id}/finalize
    │  handle_finalize(candidate, session, config)
    │  - 세션의 turns를 "Q1./A1." 형식으로 합쳐 하나의 텍스트로 만든다
    │  - InterviewAnswer.create(scout_id, "D", combined_text)  (기존 함수 그대로)
    │  - upsert_answer(answers_path, answer)                  (기존 함수 그대로)
    │  - append_scout_knowledge(daily_pack, answers, knowledge) (기존 함수 그대로)
    ▼
data/tak_interview_answers.json (합성된 답변 1건)
data/tak_brain_knowledge.json (pending KNOWLEDGE 1건, 자동 승인 없음)
```

**세션(원본)과 답변(호환 결과)의 관계**가 설계 문서 11번 원칙 그대로
구현됐다: `InterviewSession`은 finalize 이후에도 그대로 남아 있고(삭제하지
않음), 사용자가 실제로 타이핑한 D 직접입력 문장은 세션에도, 합성된
`InterviewAnswer.custom_answer`에도 **한 글자도 바뀌지 않고** 들어 있다
(9번 실제 테스트로 확인).

## 5. A/B/C/D 처리 방식

`handle_turn_answer_submission()`에서 처리한다.

- **A/B/C**: `selected_option`을 그 글자로 저장하고 `custom_answer`는
  **항상 빈 문자열로 강제**한다(폼에 다른 값이 딸려 와도 무시 - 요청받은
  "빈 문자열을 자동으로 임의의 답변으로 바꾸지 않는다"를 반대 방향에서도
  지킨 것: A/B/C 선택에 엉뚱한 텍스트가 섞여 들어가지 않게 함).
- **D**: `custom_answer`를 폼에서 받은 문자열을 **앞뒤 공백만 제거하고
  그대로** 저장한다. 재작성·요약·정제를 하는 코드 경로 자체가 없다(LLM
  호출이 아예 없으므로 구조적으로 불가능하다). 비어 있으면 저장하지 않고
  오류를 반환한다(`"D(직접 입력)를 선택하면 답변 내용이 필요합니다."`).
- **유효하지 않은 선택지**(`A/B/C/D`가 아닌 값)는 `tak_scout.VALID_OPTIONS`를
  그대로 재사용해 검증하고, HTTP 400과 함께 같은 턴 화면을 다시 보여준다
  (세션 상태는 바뀌지 않음 - 실제 테스트로 확인, 9번 참고).
- **중복 제출 방지**: 이미 답이 채워진 턴에 다시 답이 오면(새로고침 후
  재제출 등) 조용히 현재 세션을 그대로 반환하고 다음 턴을 또 만들지
  않는다(멱등적 처리).

## 6. 3턴 완료 처리

`len(turns) == MAX_TURNS(3)`이 되는 순간 `handle_turn_answer_submission()`
안에서:

```python
status = "completed"
completed_at = now  # ISO timestamp
```

로 세션을 갱신하고 **4번째 turn은 만들지 않는다.** 이후 같은 세션에
`POST .../answer`가 다시 오면(`status == "completed"`) 답을 받지 않고 바로
`/review`로 303 리다이렉트한다(라우팅 단계에서부터 차단 - `do_POST`의
`/answer` 처리 맨 앞에서 `session.status == "completed"` 체크). 실제
테스트(`test_full_three_turn_flow_a_then_d_then_b`)에서 3턴 완료 직후
`len(session.turns) == 3`임을 직접 확인했다.

## 7. Review 화면

`GET /candidate/{scout_id}/review`가 `render_review_html()`로 렌더링한다.
요청받은 항목을 전부 포함한다: 소재 제목, 출처, source URL(링크), "인터뷰
결과" 아래 Turn 1~3의 질문 + 선택한 답(A/B/C는 해당 선택지 문구, D는
사용자가 입력한 원문을 `white-space: pre-wrap`으로 그대로 표시), 그리고
`[이 내용으로 KNOWLEDGE 만들기]` / `[다시 답변하기]` 버튼. `perspective_summary`는
Phase 2 지시대로 빈 문자열로 두고 화면에 별도로 노출하지 않았다("AI 관점
요약"은 Phase 3 이후 과제).

세션이 아직 `in_progress`인 상태로 `/review`에 접근하면(직접 URL 입력 등)
`/candidate/{scout_id}`로 안내해 계속 답하게 한다(빈 review 화면을 보여주지
않음 - 실제 테스트로 확인).

## 8. KNOWLEDGE bridge 연결 방식

요청받은 원칙("기존 answers.py 스키마를 깨지 않는다", "새로운 schema를
함부로 뜯어고치지 않는다")을 그대로 지켰다. `handle_finalize()`가 작은
**어댑터** 역할만 한다:

1. `_build_combined_answer_text(session)`: 답변된 turn들을 `Qn./An.` 형식
   문자열로 이어 붙인다(설계 문서 5번 형식 그대로). A/B/C는 선택지 문구,
   D는 사용자 원문을 그대로 쓴다 - 여기서도 텍스트를 요약·재작성하지
   않는다.
2. `InterviewAnswer.create(scout_id, "D", combined_text)` — **기존 함수를
   그대로 호출.** 멀티턴 합성 결과는 항상 `D`(직접 입력)로 저장한다(여러
   턴을 합친 결과는 단순 A/B/C로 표현할 수 없다는 5-10 설계 문서의 결정을
   그대로 따름).
3. `upsert_answer(answers_path, answer)` — **기존 함수 그대로.**
4. `append_scout_knowledge(daily_pack_path, answers_path, knowledge_path)` —
   **기존 함수 그대로**(apply_interview.py가 호출하는 것과 100% 동일한
   함수).

`tak_scout/answers.py`, `tak_scout/knowledge_bridge.py`는 이 과정에서 한
줄도 수정하지 않았다. 결과적으로 생성되는 KNOWLEDGE의 evidence는 기존과
똑같이 `SOURCE FACT`/`SOURCE URL`/`USER ORIGINAL THOUGHT` 3줄 구조이며(9번
실제 테스트로 확인), `USER ORIGINAL THOUGHT`에 3턴 전체 내용이 들어간다.
KNOWLEDGE는 항상 `knowledge_review_status="pending"`으로 생성되고, 이번
단계는 그 무엇도 자동 승인하지 않는다.

## 9. 테스트 결과

`tests/test_scout_dashboard.py`를 개편했다: 5-9의 `DashboardLogicTests`
7건 중 4건(목록 정렬, 소재 검색, "이미 답변함" 표시, "관심 없음")은
그대로 유지하되 "이미 답변함" 테스트만 `upsert_answer`로 직접 상태를
만드는 방식으로 단순화했다(리스트 렌더링 로직만 검증하도록 범위를
좁힘 - 인터뷰 흐름 자체와는 무관한 테스트이기 때문). 5-9의 옛 1회성
`POST /answer` 테스트 3건과 HTTP 통합 테스트 2건은 **Phase 2 6번 지시
("POST /answer를 멀티턴 세션 기반으로 변경한다")에 따라 동작 자체가
바뀌었으므로, 같은 검증 목적(B/D 저장, 원문 보존, 잘못된 입력 처리)을
새 멀티턴 흐름에 맞게 다시 작성했다** — 이 부분은 "테스트를 깨뜨린 것"이
아니라 "의도적으로 바뀐 동작에 맞춰 테스트를 갱신한 것"임을 명확히
기록해 둔다.

`DashboardMultiTurnHttpTests`(신규, 실제 소켓을 여는 HTTP 통합 테스트
10건)에서 요청받은 12번 섹션의 18개 항목을 아래처럼 커버했다.

| # | 요청 항목 | 확인 테스트 |
|---|---|---|
| 1 | 첫 접속 시 session 생성 | `test_first_visit_creates_session_with_template_turn_one` |
| 2 | 첫 질문 generated_by == "template" | 〃 |
| 3, 4, 5, 6 | A/B/C/D 답변 저장 | `test_full_three_turn_flow_a_then_d_then_b` (A→D→B로 3턴 전부 실사용) |
| 7 | custom_answer 원문 보존 | 〃 (D 턴 텍스트를 세션/합성답변/KNOWLEDGE 3곳 모두에서 원문 일치 확인) |
| 8, 9 | 2턴째/3턴째 질문 생성 | 〃 |
| 10, 11 | 3턴 완료 후 status=="completed", completed_at | 〃 |
| 12 | 4턴이 생성되지 않음 | 〃 (`len(turns) == 3` 확인) |
| 13 | 새로고침 후 세션 복원 | `test_revisiting_before_answering_does_not_recreate_session` + 3턴 흐름 테스트 안에서도 재확인 |
| 14 | 프로세스 경계를 넘어 session 복원 | `test_session_survives_server_restart`(서버 인스턴스를 완전히 종료 후 재기동) |
| 15 | review 화면 정상 표시 | `test_full_three_turn_flow_a_then_d_then_b` 안에서 확인 |
| 16 | KNOWLEDGE 생성 버튼이 기존 bridge와 연결됨 | 〃 (finalize 후 answers/KNOWLEDGE 파일 직접 검사) |
| 17 | 기존 "관심 없음" 유지 | `test_skip_marks_not_interested`(로직) + `test_skip_over_http_still_works`(HTTP) |
| 18 | 기존 "이미 답변함" 유지 | `test_answered_candidate_shown_in_list`(로직) + 3턴 흐름 테스트 마지막 단계(HTTP) |

추가로 요청 항목 밖이지만 안전을 위해 포함한 테스트: 잘못된 선택지 처리
(`test_invalid_option_does_not_crash_or_advance_turn`), D인데 내용이 빈
경우 거부(`test_option_d_without_custom_answer_is_rejected`), 미완료
상태에서 review 접근 시 안내(`test_review_before_completion_redirects_back_to_interview`),
"다시 답변하기"가 기존 확정 답변을 지우지 않는지
(`test_restart_resets_session_but_keeps_finalized_answer`), 존재하지 않는
scout_id로 새 route 호출 시 404(`test_unknown_scout_id_returns_404_on_new_routes`).

```
$ python3 -m unittest tests.test_scout_dashboard -v
Ran 14 tests in 5.655s
OK
```

## 10. 실제 Dashboard HTTP 테스트 결과

오늘 실제 SCOUT 데이터(`data/tak_scout_daily.json`, 10건)를 세션 임시
디렉터리로 **복사**하고, 답변/KNOWLEDGE/skipped/session 파일은 전부 빈
상태(`[]`)로 서버를 백그라운드로 띄워(`--port 8124`, 운영 포트 8000과
겹치지 않음) `curl`로 요청받은 검증 흐름을 그대로 수행했다.

```
GET  /candidate/scout-0db222f63dd1              → "질문 1 / 3" 표시
POST .../answer option=A                        → "질문 2 / 3" 표시
POST .../answer option=D, custom_answer="신기술은 두려워 말고 부딪혀서 느껴봐야 한다."
                                                  → "질문 3 / 3" 표시
POST .../answer option=B                        → 303 → /review
GET  /candidate/.../review                       → "인터뷰 결과", "긍정적으로 본다",
                                                    "신기술은 두려워 말고 부딪혀서 느껴봐야 한다.",
                                                    "신중하게 접근해야 한다" 전부 표시됨
POST .../finalize                                → 303 → "저장되었습니다. TAK BRAIN
                                                    KNOWLEDGE(pending)로 연결했습니다."
```

finalize 이후 실제 파일 확인:

- `tak_interview_answers.json`: 1건, `selected_option: "D"`, `custom_answer`에
  `Q1./A1./Q2./A2./Q3./A3.` 형식으로 3턴 전체가 합쳐져 들어감(원문 그대로).
- `tak_brain_knowledge.json`: 1건, `knowledge_review_status: "pending"`,
  evidence에 `SOURCE FACT`/`SOURCE URL`/`USER ORIGINAL THOUGHT` 3줄, D 턴
  원문이 그대로 포함됨.
- `GET /` 목록: 해당 소재 카드에 "이미 답변함" 배지가 정상 표시됨.

**프로세스 재시작 검증**: 다른 소재(`scout-4a25c9bcac4e`)로 turn 1을
`option=C`로 답한 뒤, 서버 프로세스를 완전히 `kill`하고(PID 종료 확인)
**다른 PID로 새 서버 프로세스를 처음부터 다시 실행**해 같은 소재를 다시
`GET`했다 — "질문 2 / 3"과 turn 2 질문 문구가 정확히 복원됨을 확인했다
(진짜 프로세스 경계를 넘는 지속성 확인, 테스트 스위트 안의
`test_session_survives_server_restart`는 같은 스레드 안에서 서버 인스턴스만
새로 만드는 방식이라, 이번 curl 검증은 그보다 더 엄격하게 실제 OS
프로세스 재시작으로 확인한 것이다).

테스트 종료 후 서버 프로세스들을 전부 종료했고(`ps aux`로 확인), 실제
운영 데이터 3개 파일(`data/tak_scout_daily.json`,
`data/tak_interview_answers.json`, `data/tak_brain_knowledge.json`)이
실행 전후로 **완전히 동일함**을 diff/직접 비교로 확인했다(승인 5 / 대기 7
/ 거절 9, 답변 10건 그대로). `data/tak_interview_sessions.json`은 실제
데이터 디렉터리에 생성되지 않았다(모든 검증이 격리된 임시 디렉터리에서만
이루어졌기 때문).

## 11. 기존 기능 회귀 여부

| 기능 | 상태 |
|---|---|
| 소재 목록(점수순) | 회귀 없음(로직 무변경) |
| 점수 표시/breakdown | 회귀 없음 |
| 소재 상세(제목/출처/source URL) | 회귀 없음(구조 유지, turn 화면에서도 동일하게 표시) |
| "이미 답변함" | 회귀 없음 — 다만 **의미가 정확해졌다**: 이제는 "최종 확정된 답변(finalize 완료)"을 뜻한다. 인터뷰를 시작만 하고 끝내지 않은 상태는 "아직 답변하지 않음"으로 계속 표시된다(의도된 동작 - 8번 KNOWLEDGE 원칙과 일관됨). |
| "관심 없음" | 회귀 없음(코드 전혀 안 건드림, HTTP로 재확인) |
| 기존 데이터 파일 구조 | 회귀 없음(`tak_scout_daily.json`/`tak_interview_answers.json`/`tak_brain_knowledge.json`/`tak_scout_dashboard_skipped.json` 스키마 전부 그대로) |
| KNOWLEDGE 생성 시 pending 유지(자동 승인 없음) | 회귀 없음(finalize도 동일하게 pending만 생성) |
| `POST /candidate/{id}/answer`의 예전(1회성) 동작 | **의도적으로 변경됨**(6번 지시에 따름) — 예전에는 1번 제출로 답변+KNOWLEDGE가 즉시 만들어졌지만, 이제는 3턴을 다 채우고 사람이 review에서 `[KNOWLEDGE 만들기]`를 눌러야 KNOWLEDGE가 만들어진다. 관련 옛 테스트는 새 동작에 맞춰 갱신했다(9번). |

## 12. 발견된 문제

1. **목록 화면에 "인터뷰 진행 중"이라는 중간 상태가 없다** — 3턴 중 일부만
   답한 소재는 목록에서 여전히 "아직 답변하지 않음"으로 보인다(세션이
   `in_progress`인지 파일로는 알 수 있지만 목록 렌더링에는 반영하지
   않음). Phase 2 요구사항(A~I)에는 이 표시가 없어 이번 단계에서는 추가
   하지 않았다 — 필요하면 Phase 3 이후 검토 대상으로 남긴다.
2. **"다시 답변하기"는 이전 turn의 질문/답변 텍스트를 세션 안에 별도
   이력으로 남기지 않는다** — turn 1부터 다시 시작하며 이전 턴 내용은
   덮어써진다(5-10 설계 문서 및 이번 지시 둘 다 "복잡한 branching/
   versioning을 만들지 않는다"고 명시했으므로 의도된 단순화다). 대신
   **이미 finalize된 `InterviewAnswer`/KNOWLEDGE는 restart만으로는 전혀
   건드리지 않는다**(9번 실제 테스트로 확인) — "기존 답변 데이터가
   유실되지 않도록" 요구는 이 지점에서 지켜졌다.
3. **직접 실행한 curl 검증 중 커브(curl)의 `-X POST -L` 조합이 303
   리다이렉트에서 자동으로 GET으로 전환되지 않는 특이 동작**을 발견했다
   (표준 브라우저나 `urllib.request`는 정상적으로 GET으로 전환한다 - 실제
   자동화 테스트 14건은 전부 `urllib.request`로 검증했으므로 영향이
   없다). 이는 curl 사용법 이슈일 뿐 Dashboard 서버 코드의 문제가
   아니다 - 10번에서 수동 curl 검증을 다시 할 때는 리다이렉트를 별도
   GET으로 나눠 처리해 우회했다.
4. Phase 2 지시사항 A~I에는 없었지만 5-10 설계 문서에 있던 "완료하기(조기
   종료)" 버튼은 이번 단계에서 구현하지 않았다 — 이번 지시가 "최대 3턴
   진행"을 명시했고 조기 종료 기능은 언급하지 않아 범위를 좁게 유지했다.

## 13. 다음 Phase 3 준비 상태

**Phase 2는 완료되어 Phase 3(LLM 기반 질문 생성)로 진행할 준비가 되어
있다.**

- 고정 템플릿을 만드는 지점이 `_build_template_turn(turn_number)` 한
  함수로 명확히 분리되어 있어, Phase 3에서 "LLM 성공 시 LLM 결과 사용,
  실패 시 이 함수로 fallback"하는 구조를 끼워 넣기 쉽다.
- `handle_turn_answer_submission()`은 "다음 턴을 어떻게 만들지"와 "언제
  완료로 볼지"를 분리해 두지 않고 지금은 "턴 수 < 3이면 무조건 다음
  템플릿 턴 추가"로 단순화되어 있다 — Phase 3에서는 여기에 "AI 충분성
  판단" 분기가 추가되어야 한다(5-10 설계 문서 7번 참고). 이번 구조를
  바꾸지 않고 이 함수 내부에 분기만 추가하면 될 것으로 보인다.
- `InterviewSession.perspective_summary`는 이미 필드로 존재하지만 계속
  빈 문자열이었다 — Phase 3에서 AI가 채워 넣을 자리가 이미 마련되어
  있다.
- `handle_finalize()`의 KNOWLEDGE 합성 로직은 세션의 turns만 보고
  동작하므로, Phase 3에서 질문이 LLM으로 바뀌어도(질문 텍스트만 다를 뿐
  구조는 같음) 이 함수는 수정할 필요가 없어 보인다.

---

## 최종 요약

- **전체 테스트 수 / 통과 수**: 284개 / 284개 통과(`python3 -m unittest
  discover -s tests -p 'test_*.py'`). Phase 1 종료 시점 279개에서 이번
  단계로 순증 5개(`test_scout_dashboard.py`가 9개 → 14개로 재구성).
- **실제 운영 데이터 변경 여부**: 변경 없음. `data/tak_scout_daily.json`,
  `data/tak_interview_answers.json`, `data/tak_brain_knowledge.json`을
  실행 전후로 직접 비교해 완전히 동일함을 확인했다. 모든 검증(자동
  테스트 + 수동 curl 검증)은 세션 임시 디렉터리의 복사본에서만
  수행했다.
- **LLM 호출 여부**: 없음. 코드 전체(`scripts/run_scout_dashboard.py`,
  `tests/test_scout_dashboard.py`)에 네트워크 호출이나 LLM 관련 import가
  전혀 없다. 질문은 3개의 고정 한국어 템플릿만 사용했다.
- **git commit/push 여부**: 하지 않았다. `git status`로 변경 파일 목록만
  확인했다(2번 표 참고) — 어떤 커밋도 만들지 않았다.
