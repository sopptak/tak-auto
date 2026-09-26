# 5-11 Phase 2 구현 보고서 — Threads 초안 브라우저 검수 Dashboard

## 1. 구현 목적

`docs/5-11_threads_human_review_design.md`의 Phase 2: "pending Threads 초안을
브라우저 Dashboard에서 확인하고, 티몽이 직접 수정하거나 그대로 승인할 수 있게
하는 것"을 구현한다. 이번 Phase는 `pending → approved` 상태 전이까지만 다루며,
실제 Threads 발행(`approved → published/failed`)은 다음 Phase의 책임이다.

## 2. 먼저 읽은 파일과 실제 코드 확인 결과

지시받은 파일 전부를 실제로 읽었다: `docs/5-11_threads_human_review_design.md`,
`content_engine/threads_review.py`, `scripts/generate_threads_draft.py`,
`scripts/run_scout_dashboard.py`, `tak_scout/dashboard_state.py`,
`tak_scout/interview_session.py`, `content_engine/publish_history.py`,
`scripts/publish_threads.py`, `scripts/run_daily.py`,
`.github/workflows/daily-threads-post.yml`, `tests/test_threads_review.py`,
`tests/test_generate_threads_draft.py`, `tests/test_scout_dashboard.py`.

**설계 문서와 실제 코드 충돌 여부**: 없음. `ThreadsPendingDraft`/`mark_approved`/
`load_pending`/`upsert_pending`/`UNRESOLVED_STATUSES`(Phase 1 실제 구현)는
설계 문서가 예견한 그대로였고, 상태 전이 허용 목록(`pending→approved`,
`approved→{published,failed}`, `failed→approved`)도 Phase 1 코드에 이미
정확히 구현되어 있어 그대로 재사용했다. `run_scout_dashboard.py`의
`DashboardConfig`/`make_handler_class` 구조도 설계 문서가 가정한 그대로였다.

## 3. 수정/생성 파일

| 구분 | 파일 |
|---|---|
| 수정 | `scripts/run_scout_dashboard.py` (Threads 검수 라우트/렌더링/로직 추가) |
| 신규 | `tests/test_threads_dashboard.py` |

**별도 스크립트로 만들지 않고 기존 Dashboard에 통합한 이유**: 지시받은 우선순위
("가능하면 현재 Dashboard에 추가")를 따랐다. 실제로 붙여본 결과, SCOUT
인터뷰 로직(`/`, `/candidate/...`)과 Threads 검수 로직(`/threads`,
`/threads/{content_id}`)은 라우트 경로도, 사용하는 데이터 모델도, 렌더링
함수도 전혀 겹치지 않아 **서로 완전히 독립적인 섹션으로 같은 파일 안에
공존**할 수 있었다(공유하는 것은 `_page()`/`_PAGE_STYLE`/`ThreadingHTTPServer`
부트스트랩 정도의 얇은 뼈대뿐). 파일 길이는 911줄 → 약 1140줄로 늘었지만,
섹션 구분 주석(`# --- Threads 검수 화면 (5-11 Phase 2) ---`)으로 명확히
나뉘어 있어 "과도하게 복잡해졌다"고 판단하지 않았다. 별도 파일로 쪼갤 경우
오히려 `DashboardConfig`를 두 파일이 공유해야 하는 등 불필요한 결합이 생겨,
현재 구조가 더 단순하다고 판단했다.

## 4. Dashboard route

| Method | Path | 동작 |
|---|---|---|
| GET | `/threads` | 미해결(pending+approved) draft 목록. 정확히 1개면 상세 화면으로 303 리다이렉트, 0개면 안내 문구, 2개 이상이면 카드 목록 |
| GET | `/threads/{content_id}` | `status=="pending"`이면 편집 가능한 검수 화면, 그 외(approved/published/failed)면 읽기 전용 화면. 없는 content_id면 404 |
| POST | `/threads/{content_id}/approve` | 승인 처리(5장 참고). 없는 content_id면 404, 검증 실패면 400 + 폼 재표시, 성공하면 303으로 상세 화면 리다이렉트 |

## 5. 승인 흐름

폼에 버튼 2개(`name="mode" value="ai_original"` / `value="edited"`)를 두고,
같은 POST 엔드포인트로 보낸다. 서버가 `mode` 값으로 정확히 분기한다(문자열
비교로 "수정했는지" 추론하지 않음):

- **`mode=ai_original`**: 사용자가 입력창에 뭘 남겼든 전부 무시하고
  `final_title = draft.ai_rewritten_title`, `final_body = draft.ai_rewritten_body`를
  명시적으로 대입한다. 요구사항 A("최종 텍스트가 AI 초안과 정확히 같아야 한다")를
  문자열 비교가 아니라 코드로 직접 보장한다.
- **`mode=edited`(또는 알 수 없는 값)**: 사용자가 제출한 `title`/`body` 값을
  **한 글자도 바꾸지 않고** 그대로 `final_title`/`final_body`로 쓴다. `strip()`도,
  다른 어떤 정규화도 하지 않는다 - 요구사항 B("사용자 입력과 정확히 일치해야
  한다")를 위해 SCOUT 인터뷰의 `custom_answer.strip()` 관례를 이번 기능에는
  의도적으로 적용하지 않았다.
- 두 모드 모두 `content_engine.threads_review.mark_approved()`(Phase 1, 무수정)를
  그대로 호출한다 - `edited_by_user`는 이 함수가 `final_*`와 `ai_rewritten_*`를
  비교해 자동으로 계산한다(새 로직 아님, Phase 1 재사용).
- 사용자 수정 문장은 **어떤 LLM에도 다시 보내지 않는다** - 승인 핸들러
  (`handle_threads_approve_submission`)는 `OpenAICompatibleRewriteProvider`나
  `InterviewLLMProvider`를 import조차 하지 않는다.

## 6. 데이터 저장 방식

`content_engine.threads_review`의 `load_pending`/`upsert_pending`/`mark_approved`만
사용한다. 새 JSON 구조를 만들지 않았고, `ThreadsPendingDraft`의 필드도 늘리지
않았다. 저장은 Phase 1의 tempfile + `Path.replace()` 원자적 저장을 그대로
상속받는다(Dashboard 쪽에서 별도 파일 I/O를 하지 않기 때문에 저절로 보장됨).

## 7. 상태 전이

이번 Phase가 Dashboard를 통해 수행하는 전이는 **`pending → approved`
하나뿐**이다. `failed → approved`(재시도)는 Phase 1 코드에 이미 구현되어
있지만, 이번 Phase의 승인 핸들러는 `draft.status != "pending"`이면 무조건
거부하도록 명시적으로 막아뒀다 - `mark_approved()` 자체는 `failed → approved`를
허용하지만, **Dashboard UI에서는 이번 단계 범위를 넘는 그 경로를 의도적으로
차단**했다(지시사항: "approved → published/failed는 다음 Phase"). `published`/
`failed` 상태의 draft는 GET으로 열어도 편집 폼이 아예 렌더링되지 않는다
(`render_threads_resolved_html`).

## 8. 사용자 수정 보존 방식

폼 필드(`title`, `body`)에서 읽은 값을 어떤 방식으로도 가공하지 않고 그대로
`ThreadsPendingDraft.final_title`/`final_body`에 저장한다. 실제 HTTP 통합
테스트(10장)에서 특수문자·개행·탭·앞뒤 공백을 포함한 문자열로 byte-level
일치를 직접 확인했다.

## 9. 보안

- Dashboard는 **`127.0.0.1` 기본 바인딩**을 그대로 유지한다(`main()`의
  `--host` 기본값 무변경). 외부 인터넷에 노출하지 않는다.
- `THREADS_ACCESS_TOKEN`을 요구하지 않는다 - `ThreadsClient`/
  `content_engine.threads_publisher`를 이 파일 어디에서도 import하지 않는다
  (정적 검사 + 동적 테스트 8, 9번으로 이중 확인).
- `PublishHistory`도 import하지 않는다 - Threads 검수 라우트는 히스토리 파일의
  경로조차 알지 못한다.
- 금융/대출/부동산(`article_type == "finance"`) 콘텐츠는 검수 화면에 경고
  배너("⚠ 금융 관련 콘텐츠입니다...")를 띄운다. 다만 이것은 **경고일 뿐 차단이
  아니다** - `RewriteValidator`의 검증 로직 자체는 손대지 않았고(그 로직은
  Phase 1 생성 단계에서 이미 한 번 적용됨), 사람이 최종 확인 후 발행하는
  이번 반자동화의 취지상 사람의 최종 판단을 막지 않는다. 기존 안전장치를
  "우회"하지는 않았다 - 그 안전장치가 검증하는 대상(LLM 재작성 단계)에는
  전혀 손대지 않았기 때문이다.
- Threads 500자 제한은 **새로 만든 규칙이 아니라** `ThreadsClient.publish_text`
  (`content_engine/threads_publisher.py:143`)와
  `RewriteValidator._threads_length_errors`(`content_engine/rewrite.py:265`)에
  이미 있던 것과 정확히 같은 값(500)을 승인 단계에도 그대로 적용한 것이다.

## 10. 테스트 결과

### 10-1. `tests/test_threads_dashboard.py` (27개, 전부 실제 소켓을 여는 HTTP 통합 테스트)

| 요구 항목 | 테스트 |
|---|---|
| 1. pending 목록 표시 | 0개(안내 문구) / 1개(자동 리다이렉트) / 2개 이상(카드 목록) 3가지 |
| 2. pending 상세 표시 | 10개 필수 요소 전부 존재 확인 + source_url 링크 형식 + 금융 배너 유무 |
| 3. AI 초안 그대로 승인 | `final_*`가 정확히 `ai_rewritten_*`와 같고 `edited_by_user=False` |
| 4~6. 제목/본문/둘 다 수정 승인 | 각각 개별 테스트 |
| 7. byte-level 저장 | 특수문자·개행·탭·앞뒤공백 포함 문자열로 정확히 일치 확인 |
| 8. LLM 호출 없음 | `OpenAICompatibleRewriteProvider.from_environment`를 예외 발생으로 patch, 승인이 예외 없이 성공 |
| 9. Threads API 호출 없음 | `ThreadsClient.from_environment`를 예외 발생으로 patch, 승인이 예외 없이 성공 |
| 10. PublishHistory 무변경 | 히스토리 파일 경로 자체가 생성되지 않음을 확인 |
| 11. 재승인 방지 | 두 번째 승인 시도가 크래시 없이 무시되고, 첫 승인 값이 그대로 유지됨 + 재방문 시 읽기 전용 화면 |
| 12~13. published/failed 목록 제외 | 각각 확인, 상세 화면도 편집 폼 없이 읽기 전용으로만 표시 |
| 14. 잘못된 content_id | GET/POST 둘 다 404 |
| 15~16. 빈 제목/본문 거부 | 400 + 오류 메시지, draft는 `pending`으로 유지 |
| 17. atomic save 유지 | 여러 번 요청 후에도 디렉터리에 최종 파일 하나만 존재, JSON 로드 성공 |
| (추가) 500자 제한 | 501자 거부, 정확히 500자는 허용 |

**결과: 27/27 PASS**

### 10-2. 기존 테스트 회귀

```
python3 -m unittest tests.test_scout_dashboard -v
Ran 26 tests in 11.212s
OK
```

기존 SCOUT Dashboard 테스트 26개는 **한 줄도 수정하지 않고** 전부 재통과했다
(요구사항 18).

### 10-3. 전체 테스트 스위트

```
python3 -m unittest discover -s tests -p 'test_*.py'
Ran 433 tests in 26.834s
OK
```

기존 406개 + 신규 27개 = **433/433 PASS**.

## 11. 실제 HTTP 통합 테스트 결과

지시받은 순서(pending → GET /threads → GET /threads/{content_id} → 수정 →
POST 승인 → pending JSON 확인)대로, 운영 데이터가 아닌 `tempfile` 임시
디렉터리에 draft 2건을 직접 구성해 실제 소켓으로 검증했다.

**Case 1 — "수정하여 승인"(byte-level 확인)**

| 확인 항목 | 결과 |
|---|---|
| `GET /threads` (초안 1개) | 200, "AI가 만든 초안 제목" 포함 확인 |
| `GET /threads/{content_id}` | 200, source_url/KNOWLEDGE ID/입력창 전부 확인 |
| `POST .../approve` (mode=edited) | 200 |
| `final_title` byte-exact | `"  티몽이 실제로 고친 제목  "` (앞뒤 공백 그대로) — **일치** |
| `final_body` byte-exact | `"특수문자 테스트!! @#$%\n둘째 줄\t탭 포함 — 정확히 이대로 저장되어야 한다.\"인용\""` — **일치** |
| `edited_by_user` | `true` |
| `status` | `"approved"` |
| `approved_at` | `"2026-09-15T05:20:14.184576+00:00"` (기록됨) |

**Case 2 — "AI 초안 그대로 승인"**

| 확인 항목 | 결과 |
|---|---|
| `POST .../approve` (mode=ai_original) | 200 |
| `final_title == ai_rewritten_title` | **true** |
| `final_body == ai_rewritten_body` | **true** |
| `edited_by_user` | **false** |

최종 `pending.json`(임시 디렉터리, `/tmp/tmpkamtczc0/tak_threads_pending.json`)
원문:

```json
[
  {
    "content_id": "content-integration-test-1",
    ...
    "final_title": "  티몽이 실제로 고친 제목  ",
    "final_body": "특수문자 테스트!! @#$%\n둘째 줄\t탭 포함 — 정확히 이대로 저장되어야 한다.\"인용\"",
    "edited_by_user": true,
    "status": "approved",
    "approved_at": "2026-09-15T05:20:14.184576+00:00",
    ...
  },
  {
    "content_id": "content-integration-test-2",
    ...
    "final_title": "AI 초안 제목 2",
    "final_body": "AI 초안 본문 2입니다.",
    "edited_by_user": false,
    "status": "approved",
    ...
  }
]
```

## 12. 기존 자동발행 코드 변경 여부

**없음.** `scripts/run_daily.py`, `scripts/publish_threads.py`,
`.github/workflows/daily-threads-post.yml`, `content_engine/publish_history.py`
(rotation/`compute_content_id`), `content_engine/threads_review.py`(Phase 1)를
전혀 수정하지 않았다. `git status` 확인 결과 이 Phase에서 변경된 파일은
`scripts/run_scout_dashboard.py`(수정)와 `tests/test_threads_dashboard.py`
(신규)뿐이다. 기존 자동발행 workflow와 새 Dashboard 검수 시스템은 여전히
**연결되어 있지 않다** - 이는 의도된 상태다(다음 Phase에서 연결).

## 13. Threads API 호출 여부

**없음.** `scripts/run_scout_dashboard.py`의 Threads 관련 코드 어디에도
`ThreadsClient`가 import되지 않는다. 테스트 8, 9번이 `ThreadsClient.from_environment`/
`OpenAICompatibleRewriteProvider.from_environment`를 호출 시 예외를 던지도록
patch한 상태에서 승인 흐름이 예외 없이 끝나는 것으로 직접 증명했다.

## 14. PublishHistory 변경 여부

**없음.** Threads 검수 라우트는 `PublishHistory`를 import하지 않고, history
파일 경로 자체를 알지 못한다. 테스트 10번과 실제 통합 테스트 모두, 승인
과정에서 `data/threads_publish_log.json`류의 파일이 전혀 생성/변경되지 않음을
확인했다.

## 15. 운영 데이터 변경 여부

**없음.** 모든 테스트와 실제 HTTP 통합 테스트가 `tempfile.TemporaryDirectory()`
기반 임시 경로만 사용했다. `git status --short data/`에는 이번 작업 이전부터
있던 무관한 `data/tak_brain_knowledge.json` 수정만 남아 있고, 실제 운영
`data/tak_threads_pending.json`(애초에 존재하지 않음)이나
`data/threads_publish_log.json`은 이번 작업으로 생성되거나 변경되지 않았다.

## 16. 알려진 문제

1. **"카드 목록"(2개 이상 미해결) 경로는 정상 운영에서는 사실상 발생하지 않는다** —
   Phase 1의 idempotency 설계상 미해결 draft는 항상 0~1개이기 때문이다. 다만
   수동으로 pending 파일을 조작하거나 향후 Phase에서 "여러 초안 동시 생성"으로
   확장할 경우를 대비해 방어적으로 구현·테스트해 뒀다.
2. **동시 요청에 대한 진짜 lock은 없다** — 지시대로 복잡한 locking 시스템을
   도입하지 않았다. 두 요청이 정확히 동시에 도착하면 파일이 손상되지는
   않지만(atomic replace), 마지막에 쓴 요청이 이길 수 있다(lost update). 순차적인
   "이미 approved인데 또 승인 시도"는 명시적으로 막혀 있지만, 진짜 동시성
   경쟁은 이번 범위 밖으로 남겨뒀다.
3. **금융 경고는 차단이 아니라 배너뿐**이다 - 사람이 무시하고 그대로 승인할
   수 있다(5-11 설계 문서 16장에서 이미 인지된 트레이드오프).
4. **`mode` 파라미터가 없거나 알 수 없는 값이면 "edited"로 처리된다** - 폼을
   벗어난 임의의 POST 요청(예: API 직접 호출)에서는 이 기본값이 사용자
   의도와 다를 수 있으나, 실제 Dashboard 폼은 항상 두 버튼 중 하나의 값만
   보내므로 정상 사용 흐름에서는 문제가 없다.

## 17. Phase 3 준비사항

- `scripts/publish_approved_threads.py`(설계 문서 9-2장)를 신규 작성해
  `status == "approved"`인 draft를 찾아 `ThreadsClient.publish_text()`를
  호출하고, 성공 시 `PublishHistory.append()` + `mark_published()`, 실패 시
  `mark_failed()`를 호출하는 로직이 필요하다 - `mark_published`/`mark_failed`는
  이미 Phase 1에 구현되어 있어 그대로 재사용 가능하다.
- `failed → approved`(재시도) UI는 이번 Phase에서 의도적으로 제외했으므로,
  Phase 3 또는 이후 Phase에서 Dashboard에 "재승인" 버튼을 추가할지 결정이
  필요하다(현재는 `mark_approved()` 함수 자체는 이미 이 전이를 지원한다).
- 신규 워크플로(`daily-threads-generate.yml`, `publish-approved-threads.yml`)와
  `.gitignore`의 `data/tak_threads_pending.json` 커밋 정책은 설계 문서 10, 13장에
  이미 정리되어 있다 - 이번 Phase는 로컬 Dashboard까지만 다뤘으므로 GitHub
  Actions 연결은 여전히 남은 작업이다.
