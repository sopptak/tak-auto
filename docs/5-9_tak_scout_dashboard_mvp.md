# 5-9 TAK SCOUT Dashboard MVP

TAK SCOUT의 질의응답을 터미널(`run_interview.py`)에서 웹 브라우저로 옮기는
MVP. 기존 TAK INTERVIEW/TAK BRAIN 스키마와 로직은 그대로 재사용하고, 웹
서버·화면만 새로 추가했다. **git commit/push는 하지 않았다.**

## 1. 구현한 파일

| 파일 | 설명 |
|---|---|
| `scripts/run_scout_dashboard.py` | Dashboard 웹 서버 본체(신규) |
| `tak_scout/dashboard_state.py` | "관심 없음" 상태 저장 전용 모듈(신규) |
| `tests/test_scout_dashboard.py` | Dashboard 테스트 9건(신규) |
| `docs/5-9_tak_scout_dashboard_mvp.md` | 이 보고서 |

## 2. 수정한 파일

**없음.** 이번 단계에서 기존 파일은 한 줄도 수정하지 않았다(`git status`로
확인: `scripts/run_scout.py`, `scripts/run_scout_score.py`,
`scripts/run_interview.py`, `scripts/apply_interview.py`, `tak_scout/answers.py`,
`tak_scout/interview.py`, `tak_scout/collector.py`, `tak_scout/knowledge_bridge.py`,
`tak_scout/scoring.py`, `tak_scout/__init__.py`, `tak_brain/*` 전부 변경 없음).
Dashboard는 이 파일들이 이미 제공하는 함수를 그대로 가져다 썼다.

작업 전에 다음을 전부 읽고 시작했다: `tak_scout/`(models, collector, rss,
interview, answers, knowledge_bridge, scoring, __init__), `tak_brain/knowledge.py`,
`scripts/run_scout.py`, `run_scout_score.py`, `run_interview.py`,
`apply_interview.py`, `tests/test_scout_*.py`, 실제
`data/tak_scout_daily.json`/`tak_interview_answers.json` 구조.

## 3. Dashboard 실행 방법

```
python3 scripts/run_scout_dashboard.py
```

기본 경로: `--daily-pack data/tak_scout_daily.json`,
`--answers data/tak_interview_answers.json`,
`--knowledge data/tak_brain_knowledge.json`,
`--skipped data/tak_scout_dashboard_skipped.json` (마지막 것만 신규 파일).
`--port`(기본 8000), `--host`(기본 `127.0.0.1` - 로컬 전용, 외부에 노출하지
않음)로 조정 가능. 먼저 `python3 scripts/run_scout.py`로 오늘의 소재를
수집해 둔 상태여야 한다(daily pack이 없으면 안내 메시지 후 종료).

기술 선택: **Python 표준 라이브러리 `http.server`(ThreadingHTTPServer)만
사용**했다. Flask/React/Next.js/별도 빌드 시스템 전부 도입하지 않았다 -
저장소 의존성이 하나도 늘지 않았다(`import` 구문을 봐도 표준 라이브러리와
기존 `tak_scout`/`tak_brain` 모듈뿐이다). HTML은 이 스크립트 안에서 문자열로
직접 만든다(`tak_scout.interview.render_questions_markdown`과 같은 기존
접근 방식).

## 4. 브라우저 접속 주소

```
http://localhost:8000
```

(포트를 바꾸면 그 포트로). 저장소 안에 이 포트를 쓰는 다른 서버가 없음을
먼저 확인했다(`grep`으로 `8000`/`HTTPServer`/`socketserver` 등 검색 결과
기존 사용처 없음).

## 5. 화면 구성

**화면 1. 오늘의 소재 (`GET /`)**: SCOUT SCORE(5-8) 내림차순 카드 목록.
카드마다 순위, 점수, 상태 배지(아직 답변하지 않음 / 이미 답변함 / 관심 없음),
제목, 출처·발행시간·category, 점수 breakdown 5개 항목, 추천 이유, 원문 링크,
[이 소재로 답변하기] / [관심 없음] 버튼을 표시한다.

**화면 2. 질문 (`GET /candidate/{scout_id}`)**: `tak_scout.build_interview_question`
그대로 만든 질문과 A/B/C/D 선택지를 버튼으로 보여준다. A/B/C는 클릭하면 바로
제출되고, D를 클릭하면 직접 입력 텍스트 상자가 나타난다(순수 JS 몇 줄, 별도
프레임워크 없음). 이미 답변이 있는 소재면 기존 답변 내용을 안내 배너로
보여준다(5-7의 "이미 답변함" 개념을 웹으로 그대로 옮김).

저장 후에는 같은 질문 화면에 "저장되었습니다" 배너와 함께 다시 표시된다
(POST 후 303 리다이렉트 → GET, 새로고침해도 중복 제출되지 않는 구조).

## 6. 데이터 흐름

```
scripts/run_scout.py            (기존, 수정 없음)
        │  data/tak_scout_daily.json 생성
        ▼
scripts/run_scout_dashboard.py  (신규)
        │  tak_scout.load_daily_pack (읽기 전용)
        │  tak_scout.rank_candidates (5-8 scoring, 수정 없음, 매 요청마다 실시간 계산)
        ▼
  [브라우저: 오늘의 소재 목록 표시]
        │
  [사용자: 소재 선택 → 질문 화면]
        │  tak_scout.build_interview_question (수정 없음)
        ▼
  [사용자: A/B/C/D 클릭, D면 직접 입력]
        │  tak_scout.InterviewAnswer.create + upsert_answer (수정 없음)
        ▼
data/tak_interview_answers.json  (기존 스키마 그대로 갱신)
        │  tak_scout.append_scout_knowledge (수정 없음 - apply_interview.py가
        │  내부에서 호출하는 것과 정확히 같은 함수)
        ▼
data/tak_brain_knowledge.json  (신규 KNOWLEDGE, pending으로 추가 - 자동 승인 없음)
        │
  [브라우저: "저장되었습니다" 확인 화면]
```

[관심 없음]을 누르면 별도로 `data/tak_scout_dashboard_skipped.json`(신규
파일)에만 `scout_id`가 기록되고, 그 외 어떤 기존 파일도 건드리지 않는다.

## 7. 답변 저장 구조

웹에서 저장한 답변은 `data/tak_interview_answers.json`에 **기존과 완전히
같은 스키마**로 들어간다(추가 필드 없음):

```json
{
  "scout_id": "scout-4a25c9bcac4e",
  "selected_option": "D",
  "custom_answer": "신기술은 두려워 말고 부딪혀서 느껴봐야 한다.",
  "answered_at": "2026-09-14T05:52:40.754793+00:00"
}
```

이는 `tak_scout.answers.InterviewAnswer.create()` + `upsert_answer()`를
그대로 호출한 결과이며, `scripts/apply_interview.py`가 그대로 읽을 수 있다
(같은 함수를 쓰기 때문에 당연히 호환됨 - 실제로 Dashboard 자체가 저장 직후
`append_scout_knowledge`를 바로 호출해 확인했다, 8번 참고). 같은 소재를
다시 답하면 `upsert_answer`가 그대로 덮어쓴다(5-7과 동일 동작).

## 8. Knowledge Bridge 연결 방식

답변 저장 직후, Dashboard는 `tak_scout.append_scout_knowledge(daily_pack,
answers, knowledge)`를 **그대로** 호출한다 — 이는 `scripts/apply_interview.py`
의 `main()`이 내부에서 호출하는 것과 100% 동일한 함수다(별도 로직을 새로
만들지 않았다). 그 결과:

- 새 KNOWLEDGE는 항상 `knowledge_review_status: "pending"`으로 생성된다.
- **자동 승인은 절대 하지 않는다.** 승인은 여전히 사람이
  `python3 scripts/review_knowledge.py --pending` → `--id <ID> --approve`로
  별도 진행해야 한다.
- 같은 답을 중복 제출해도 결정적 id 덕분에 KNOWLEDGE가 중복 생성되지
  않는다(기존 dedup 로직 그대로, 5-7에서 이미 검증된 동작과 동일).

즉 "답변 → pending KNOWLEDGE → 사람 검토 → approved"라는 기존 원칙이
그대로 유지된다.

## 9. 테스트 결과

`tests/test_scout_dashboard.py`에 9개 테스트를 추가했다(13번에서 요구한
1~8번 항목 + 유효성 검사 1건):

| # | 테스트 | 확인 내용 |
|---|---|---|
| 1, 2 | `test_list_reads_daily_pack_and_sorts_by_score` | daily pack을 읽고, 점수 높은 소재가 목록에서 더 먼저 나오는지 |
| 3 | `test_find_candidate_returns_exact_match_or_none` | 소재 선택(조회) 정상 작동 |
| 4 | `test_option_b_answer_is_saved_and_compatible_with_existing_schema` | B 선택 저장 + JSON 스키마가 기존과 정확히 일치(`scout_id/selected_option/custom_answer/answered_at`) |
| 5 | `test_option_d_with_custom_text_is_saved` | D 직접 입력 저장 + KNOWLEDGE evidence에 `USER ORIGINAL THOUGHT`로 정확히 반영 |
| 6 | (4, 5에 포함) | 저장된 JSON을 `tak_scout.answers.load_answers`(기존 함수)로 다시 읽어 호환 확인 |
| 7 | `test_answered_candidate_shown_in_list` | 답변한 소재 카드에만 "이미 답변함" 표시 |
| 8 | `test_skip_marks_not_interested` | "관심 없음" 저장 + 목록에 "관심 없음" 표시 + 여전히 선택 가능 |
| - | `test_invalid_option_returns_error_without_crash` | 잘못된 선택지를 보내도 서버가 죽지 않고 에러만 반환 |
| - | `DashboardHttpIntegrationTests` (2건) | 실제 소켓을 열어 GET/POST 라우팅 전체가 실제로 동작하는지(11번과 별개로, 자동화된 통합 테스트) |

```
$ python3 -m unittest tests.test_scout_dashboard -v
Ran 9 tests in ~1.0s
OK
```

**9. 기존 SCOUT 테스트 / 10. 기존 Knowledge Bridge 테스트**가 깨지지
않는지 함께 확인:

```
$ python3 -m unittest tests.test_scout_collector tests.test_scout_interview \
    tests.test_scout_answers tests.test_scout_knowledge_bridge \
    tests.test_scout_pipeline_e2e tests.test_scout_rss tests.test_scout_scoring \
    tests.test_scout_dashboard -v
Ran 58 tests in 1.096s
OK
```

## 10. 전체 테스트 결과

```
$ python3 -m unittest discover -s tests -p 'test*.py'
Ran 258 tests in 2.716s
OK
```

**258/258 전체 통과**(5-8 단계 249건 + 이번에 추가한 신규 9건). 기존 파일을
전혀 수정하지 않았으므로 회귀 위험이 구조적으로 낮았고, 실제로도 실패 없이
통과했다.

## 11. 실제 Dashboard 테스트 결과

실제 운영 데이터(`data/tak_scout_daily.json`, 10건)를 **세션 임시
디렉터리로 복사**하고, 답변/KNOWLEDGE/skipped 파일은 전부 빈 상태(`[]`)로
새로 시작해 서버를 백그라운드로 띄우고(`--port 8123`, 운영 포트 8000과
겹치지 않게) `curl`로 실제 HTTP 요청을 보내 확인했다.

1. `GET /` → HTTP 200, 카드 10개 모두 점수 내림차순으로 렌더링됨. 1위는
   5-8과 동일하게 "Gloomy forecast for tenants..." 44점, 2위 "Amazon
   pauses work..." 42점 등 — 5-8의 점수화 로직이 그대로 재사용됐음을
   실제로 확인.
2. `GET /candidate/scout-4a25c9bcac4e` → HTTP 200, 질문 문구와 D 옵션의
   "직접 입력" 텍스트 상자 스크립트가 정확히 렌더링됨.
3. `POST /candidate/scout-4a25c9bcac4e/answer` (option=D,
   custom_answer="신기술은 두려워 말고 부딪혀서 느껴봐야 한다.") → HTTP 303
   → 리다이렉트 따라가면 "저장되었습니다. TAK BRAIN KNOWLEDGE(pending)로
   연결했습니다." 배너 확인. 실제 파일 확인 결과:
   - `tak_interview_answers.json`에 정확히 그 답변 1건 저장됨.
   - `tak_brain_knowledge.json`에 KNOWLEDGE 1건이 `pending` 상태로 생성됐고,
     evidence에 `USER ORIGINAL THOUGHT: 신기술은 두려워 말고 부딪혀서
     느껴봐야 한다.`가 정확히 들어감.
4. 같은 소재를 다시 `GET`하니 "이 소재에는 이미 답변이 있습니다 (현재
   답변: D - "...")" 안내 배너가 정상 표시됨.
5. `POST /candidate/scout-87f2284ff52b/skip` → HTTP 303 →
   `tak_scout_dashboard_skipped.json`에 해당 scout_id가 기록되고, 다시
   `GET /`한 목록에서 그 소재 카드에 "관심 없음" 배지가 표시됨.
6. 테스트 종료 후 서버 프로세스를 종료했고(`kill`, `ps aux`로 완전히
   죽었음을 확인), 실제 운영 데이터 3개 파일
   (`data/tak_scout_daily.json`, `data/tak_interview_answers.json`,
   `data/tak_brain_knowledge.json`)이 실행 전후로 **완전히 동일함**을
   직접 diff/비교로 확인했다(승인 5 / 대기 7 / 거절 9, 답변 10건 그대로).
   `data/tak_scout_dashboard_skipped.json`은 이번 실 데이터 디렉터리에는
   생성되지 않았다(테스트가 격리된 임시 디렉터리에서만 실행됐기 때문).

## 12. 발견된 문제

1. **다중 사용자/동시 편집 가정 없음.** 지금은 티몽 혼자 쓰는 로컬 도구를
   가정했다(요청사항에도 로그인/DB가 명시적으로 빠져 있음). 여러 탭을 열고
   동시에 같은 소재에 답하면 마지막 저장이 이긴다(기존 `upsert_answer`의
   동작 그대로이며, 이번에 새로 생긴 문제는 아니다).
2. **"관심 없음"은 아직 목록에서 걸러내지 않는다.** 상태만 표시할 뿐,
   "관심 없음 소재 숨기기" 같은 필터는 이번 MVP 범위 밖이다(요청에도 상태
   "구분"까지만 있었다).
3. **후속 질문(2~3개)은 구현하지 않았다.** 현재 `tak_scout.interview`는
   소재 1건당 질문 1개(A/B/C/D)만 만드는 구조이고, 여러 개의 후속 질문을
   만드는 기존 로직이 없다. "현재 코드에서 자연스럽게 재사용 가능하면"이라는
   조건이 있었는데, 자연스럽게 재사용할 기존 구조 자체가 없어서 이번
   단계에서는 만들지 않았다(만들려면 새 질문 생성 스키마를 설계해야 해서
   "복잡하게 만들지 않는다"는 제한과 충돌한다고 판단).
4. 서버가 요청마다 `data/tak_scout_daily.json`/`tak_interview_answers.json`
   등을 매번 다시 읽는다(캐시 없음). 오늘 소재가 10건 수준이라 성능 문제는
   없지만, 후보가 아주 많아지면 느려질 수 있다.
5. 페이지가 새로고침될 때마다 서버가 파일을 다시 읽으므로, 로컬에서 다른
   프로세스(예: 터미널에서 `run_interview.py`)가 동시에 같은 파일을 쓰고
   있으면 그 변경 사항이 즉시 반영된다(장점이자, 파일 잠금이 없다는 점에서는
   한계이기도 하다).

## 13. 다음 단계 (제안, 이번 단계에서는 실행하지 않음)

1. "관심 없음" 소재를 목록에서 접거나 필터링하는 UI를 추가할지 검토한다.
2. 후속 질문이 정말 필요하다면, 먼저 `tak_scout.interview`에 "질문 1개 →
   답 → 후속 질문" 같은 최소 구조를 설계하고 나서(코드 레벨 논의 필요),
   그 다음에 Dashboard에 연결하는 순서로 진행한다.
3. 승인(`review_knowledge.py --approve`)까지 Dashboard에서 처리할지는
   "MVP에서는 자동 승인하지 않는다"는 이번 원칙을 유지할지 사용자와 별도로
   논의한다.
4. 여러 기기에서 접속할 가능성이 생기면(예: 휴대폰), `--host 0.0.0.0`과
   최소한의 접근 제어(비밀번호 등)가 필요한지 검토한다 - 지금은 의도적으로
   `127.0.0.1`(로컬 전용)만 기본값으로 뒀다.
5. TAK MEDIA 실행, Threads/Naver 게시 연동은 이번 범위 밖이며 요청이 있을
   때 별도로 진행한다.
