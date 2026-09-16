# 5-11 Phase 3 구현 보고서 — 승인된 Threads 초안 발행 스크립트

## 1. 구현 목적

`docs/5-11_threads_human_review_design.md` 9-2장에서 설계한 "발행 스크립트"를
구현한다. Dashboard(Phase 2)가 만든 `approved` 상태의 Threads 초안을, 기존
`ThreadsClient`(`content_engine/threads_publisher.py`, 무수정)를 재사용해 실제
Threads Graph API로 게시하고, 성공/실패에 따라 `PublishHistory`와 pending 상태를
갱신한다. 이번 단계의 범위는 "승인된 Threads 발행 스크립트"까지이며, GitHub
Actions workflow와 Dashboard는 수정하지 않았다.

## 2. 먼저 읽은 파일

지시받은 파일 전부를 실제로 읽었다: `docs/5-11_threads_human_review_design.md`,
`docs/5-11_phase2_dashboard_review.md`, `content_engine/threads_review.py`,
`content_engine/publish_history.py`, `content_engine/threads_publisher.py`,
`scripts/publish_threads.py`, `scripts/generate_threads_draft.py`,
`scripts/run_scout_dashboard.py`, `tests/test_threads_review.py`,
`tests/test_generate_threads_draft.py`, `tests/test_threads_dashboard.py`,
`.github/workflows/daily-threads-post.yml`, `content_engine/__init__.py`,
`.gitignore`.

**확인 결과**: `.gitignore`에 `!data/tak_threads_pending.json`이 이미 Phase 1에서
추가되어 있었다(추가 수정 불필요). 설계 문서(9-2장)가 예견한 상태 전이 헬퍼
(`mark_published`/`mark_failed`, `approved → published/failed`)가 Phase 1
`content_engine/threads_review.py`에 이미 정확히 구현되어 있어 그대로 재사용했다.

## 3. 변경 파일

| 구분 | 파일 |
|---|---|
| 신규 | `scripts/publish_approved_threads.py` |
| 신규 | `tests/test_publish_approved_threads.py` |

기존 파일은 **한 글자도 수정하지 않았다** — `scripts/publish_threads.py`,
`content_engine/publish_history.py`, `content_engine/threads_publisher.py`,
`scripts/run_scout_dashboard.py`, `.github/workflows/daily-threads-post.yml`,
`content_engine/threads_review.py` 전부 무수정.

## 4. 발행 상태 흐름

```
approved ──[Threads API 성공]──▶ published (종결, PublishHistory에도 동시 기록)
   │
   └──[Threads API 실패]──▶ failed (PublishHistory 불변, failure_reason 기록)

pending      → 발행 대상 아님 (final_title/body가 아직 없음)
published    → 발행 대상 아님 (종결 상태, 재발행 시도 자체를 안 함)
failed       → 발행 대상 아님 (자동 재발행 없음 — 사람이 Dashboard 등에서
               mark_approved()로 failed → approved 재승인해야만 다시 대상이 됨.
               이 스크립트는 재승인 UI를 만들지 않는다 — Phase 2가 다룬 범위 밖)
```

상태 전이는 전부 Phase 1의 `mark_published`/`mark_failed`(둘 다 무수정 재사용)만
호출하며, 새 전이 규칙을 만들지 않았다. `_ALLOWED_TRANSITIONS`가 `approved`에서
`published`/`failed`로만 전이를 허용하므로, 이 스크립트가 실수로 다른 상태 전이를
시도하면 `ThreadsPendingError`가 발생해 안전하게 막힌다(이 스크립트는 항상
`status == "approved"`인 draft만 골라 처리하므로 실제로 이 예외가 발생할 일은 없다).

## 5. CLI 옵션

```
python3 scripts/publish_approved_threads.py [--input PATH] [--history PATH] [--id CONTENT_ID] [--dry-run | --execute]
```

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `--input` | `data/tak_threads_pending.json` | 검수 대기 draft 경로 |
| `--history` | `data/threads_publish_log.json` | 게시 이력 경로 |
| `--id` | 없음 | 특정 content_id 1건만 발행 대상으로 제한 |
| `--dry-run` | - | 안전한 미리보기 (기본 실행과 동일) |
| `--execute` | - | 실제 발행 (명시적으로 필요) |

`--dry-run`과 `--execute`를 동시에 지정하면 오류 메시지를 출력하고 exit code 1을
반환한다(`tests/test_publish_approved_threads.py::test_dry_run_and_execute_together_is_rejected`).

## 6. dry-run 동작 (기본 실행과 동일)

**핵심 안전 설계**: `--execute`가 명시적으로 주어지지 않으면(즉 `--dry-run`을 준
경우든, 아무 플래그도 안 준 기본 실행이든) 코드 경로는 완전히 동일하다 —
`execute = args.execute`(기본값 `False`)이므로, `if not execute:` 분기가 dry-run과
기본 실행을 모두 처리한다. 즉 **`--dry-run`은 실질적으로 문서화 목적의 별칭이고,
진짜 안전장치는 `--execute`의 부재 자체**다(요구사항 7, 8을 코드 구조로 직접
보장).

이 경로에서는:
- `ThreadsClient.from_environment()`를 전혀 호출하지 않는다(정적으로 `if execute:`
  블록 안에서만 이 호출이 등장한다 - 코드 흐름상 도달 불가능).
- `data/tak_threads_pending.json`, `data/threads_publish_log.json` 둘 다 갱신하지
  않는다.
- 대상 approved 목록을 순회하며 `content_id`, `knowledge_id`, `final_title`,
  `final_body`를 표준출력에 그대로 출력한다.
- history에 이미 존재하는 content_id는 "API를 호출하지 않습니다" 안내만 출력하고
  상태를 건드리지 않는다(동기화도 execute일 때만 수행 — 아래 7장).

## 7. execute 동작

`--execute`가 있을 때만 아래 경로에 진입한다:

1. `validate_final_text()`로 `final_title`/`final_body`가 비어 있지 않은지 확인.
   비어 있으면 오류 출력 + exit code 1, **상태는 바꾸지 않고** 다음 draft로 넘어간다.
2. `PublishHistory.is_published(content_id)`로 이미 게시된 콘텐츠인지 확인.
   이미 있으면 API를 호출하지 않고, 기존 history 레코드의 `threads_post_id`/
   `published_at`으로 pending draft를 `published`로 동기화한다(8장 참고 — 이례적인
   상태 불일치를 복구하는 안전한 경로).
3. `ThreadsClient.from_environment()`로 클라이언트를 생성하고
   `client.publish_text(draft.final_body)`를 호출한다 — **`final_title`은 API
   페이로드에 포함되지 않는다**. 이는 새 규칙이 아니라 기존
   `content_engine/threads_publisher.py:133-161`의 `publish_text(text)` 시그니처
   자체가 본문 텍스트 하나만 받는 기존 계약을 그대로 따른 것이다(`scripts/publish_threads.py`도
   동일하게 `rewritten_body`만 게시하고 제목은 API에 보내지 않는다). `final_title`은
   여전히 "발행에 필요한 필수 필드"로 검증되지만(1단계), 그 용도는 Dashboard
   표시/데이터 완결성이지 Threads API 페이로드가 아니다.
4. 성공 → `PublishHistory.append()` + `mark_published()` + `upsert_pending()`.
5. 실패(`ThreadsConfigurationError`/`ThreadsAPIError`/`ValueError`) → `mark_failed()` +
   `upsert_pending()`, `PublishHistory`는 건드리지 않는다.

## 8. 중복 방지 방식

`content_id`를 기준으로 기존 `PublishHistory`와 대조한다(`PublishHistory.is_published()`,
무수정 재사용). 이미 history에 기록된 content_id는 **API를 호출하지 않는다** —
대신 execute 모드에서는 기존 history 레코드 값으로 pending draft 상태를
`published`로 동기화해 둔다(정상 운영에서는 발생하지 않아야 하는 이례적 상황을
안전하게 복구하는 방어적 경로 — 예: 과거에 다른 경로로 이미 게시된 content_id가
어떤 이유로 다시 `approved` 상태로 남아 있는 경우). dry-run에서는 이 동기화도
수행하지 않는다(파일 변경 완전 금지 원칙).

`published`/`pending`/`failed` 상태의 draft는 애초에 `load_approved_drafts()`가
`status == "approved"`만 필터링하므로 대상 목록에 아예 들어오지 않는다 — 이것이
1차 방어선이고, history 대조가 2차 방어선이다.

테스트 검증:
- `test_content_id_already_in_history_skips_api_call`
- `test_content_id_already_in_history_is_untouched_in_dry_run`
- `test_pending_status_is_not_published`
- `test_published_status_is_not_republished`
- `test_failed_status_is_not_auto_republished`

## 9. 성공/실패 처리

**성공** (Threads API 호출 성공 시에만):
- `PublishHistory.append(PublishRecord(...))` — `content_id`, `published_at`,
  `threads_post_id`, `knowledge_id`, `platform="threads"`, `source_url` 기록.
- `mark_published(draft, threads_post_id=..., published_at=...)` 후
  `upsert_pending()`으로 원자적 저장(tempfile + `Path.replace()`, Phase 1 그대로
  재사용 — 새 저장 로직을 만들지 않았다).

**실패** (Threads API 호출 실패 시):
- `PublishHistory`는 전혀 건드리지 않는다.
- `mark_failed(draft, failure_reason=str(err), failed_at=...)` 후 `upsert_pending()`으로
  draft를 `failed` 상태로 저장.
- 표준에러로 명확히 실패를 보고하고 exit code 1을 반환한다.

`OSError`로 `PublishHistory.append()` 자체가 실패하는 극단적 경우(디스크 오류 등)는
`scripts/publish_threads.py:170-174`와 동일한 방어 로직을 그대로 복제했다 — 게시는
성공했지만 이력 저장에 실패했다는 경고만 출력하고 draft는 이미 `published`로
표시한다(이 경로는 테스트하지 않았다 — 기존 `publish_threads.py`도 마찬가지로
테스트되지 않은 방어 로직이며, 동일한 관례를 그대로 따랐다).

## 10. 테스트 결과

### 10-1. `tests/test_publish_approved_threads.py` (22개, 신규)

모두 `unittest.mock.patch.object(ThreadsClient, "from_environment", ...)`로
실제 네트워크를 대체한다 — `tests/test_threads_dashboard.py`의 8, 9번 테스트와
동일한 방법론.

| 요구 항목 | 테스트 |
|---|---|
| 1. approved 1건이 dry-run에서 조회 | `test_dry_run_lists_approved_draft` |
| 2. dry-run API 호출 0회 | `test_dry_run_calls_api_zero_times` |
| 3. dry-run에서 pending/history 불변 | `test_dry_run_does_not_modify_pending_or_history` |
| 4. execute에서 final_title/body가 API로 전달 | `test_execute_publishes_final_body_not_ai_rewritten` (ai_rewritten_*과 final_*을 의도적으로 다르게 설정해 검증) |
| 5, 6. 성공 시 published + threads_post_id | `test_execute_success_marks_published_with_post_id` |
| 7. 성공 시 PublishHistory 기록 | `test_execute_success_appends_publish_history` |
| 8. 실패 시 failed 상태 | `test_execute_failure_marks_failed_with_reason` |
| 9. 실패 시 PublishHistory 불변 | `test_execute_failure_does_not_touch_publish_history` |
| 10. pending은 발행 안 됨 | `test_pending_status_is_not_published` |
| 11. published는 재발행 안 됨 | `test_published_status_is_not_republished` (+ `test_failed_status_is_not_auto_republished`) |
| 12. history 중복 시 API 미호출 | `test_content_id_already_in_history_skips_api_call`, `test_content_id_already_in_history_is_untouched_in_dry_run` |
| 13. --id로 단건 제한 | `test_id_flag_limits_to_single_content_id`, `test_id_flag_with_unknown_content_id_errors` |
| 14. final_title/body 없는 approved 거부 | `test_approved_without_final_fields_is_rejected_safely`, `test_approved_with_blank_final_body_is_rejected_safely` |
| 15. --dry-run + --execute 동시 지정 거부 | `test_dry_run_and_execute_together_is_rejected` |
| 16. 기본 실행에서도 API 미호출 | `test_default_run_without_flags_calls_api_zero_times`, `test_default_run_does_not_modify_pending_or_history` |
| (추가) 승인 대상 없음/파일 없음 | `test_no_approved_drafts_exits_zero`, `test_no_pending_file_exits_zero` |

**결과: 22/22 PASS**

### 10-2. 전체 테스트 스위트

```
python3 -m unittest discover -s tests -p 'test_*.py'
Ran 455 tests in 26.889s
OK
```

기존 433개 + 신규 22개 = **455/455 PASS**. 기존 테스트는 한 줄도 수정하지 않았다.

## 11. 실제 Threads API 호출 여부

**없음.** 모든 테스트가 `ThreadsClient.from_environment`를 `unittest.mock.patch.object`로
대체했다(Fake 클라이언트 또는 `side_effect=AssertionError`). 특히
`test_dry_run_calls_api_zero_times`, `test_default_run_without_flags_calls_api_zero_times`,
`test_pending_status_is_not_published` 등은 `from_environment`가 호출되면 즉시
`AssertionError`를 던지도록 patch한 상태에서 스크립트를 실행해 예외 없이 끝나는
것으로 "API가 전혀 호출되지 않았음"을 직접 증명한다. 이 세션에서 실제
`THREADS_ACCESS_TOKEN` 환경변수를 사용하거나 실제 네트워크 호출을 시도한 적이
없다.

## 12. 실제 운영 데이터 변경 여부

**없음.** `data/tak_threads_pending.json`은 이 저장소에 애초에 존재하지 않는다
(`ls data/tak_threads_pending.json` → No such file or directory) — Phase 1/2에서도
운영 데이터로 실제로 생성된 적이 없다. `data/threads_publish_log.json`도 이번
작업으로 전혀 건드리지 않았다. 모든 테스트는 `tempfile.TemporaryDirectory()` 기반
임시 경로만 사용했다(`git status --short` 확인 결과 `data/` 아래 변경은 이 세션
시작 시점부터 있던 `tak_brain_knowledge.json` 관련 무관한 변경뿐).

## 13. Git 변경 여부

이번 작업으로 새로 생긴 파일은 다음 2개뿐이다(`git status --short` 확인):

```
?? scripts/publish_approved_threads.py
?? tests/test_publish_approved_threads.py
```

`content_engine/publish_history.py`, `content_engine/threads_publisher.py`,
`scripts/publish_threads.py`, `scripts/run_scout_dashboard.py`,
`.github/workflows/` 전체는 `git diff --stat` 결과 변경 없음(무수정 확인). 지시대로
**git add/commit/push는 전혀 수행하지 않았다.**

## 14. 남은 이슈

1. **재승인(failed → approved) 대상에 대한 Dashboard UI가 아직 없다.** 이 스크립트는
   `mark_approved()`가 이미 지원하는 `failed → approved` 재시도 전이를 자동으로
   막지 않지만(`status == "approved"`인 draft만 대상으로 삼으므로, 재승인된 draft는
   당연히 다음 실행에서 정상적으로 발행 대상이 된다), Dashboard(Phase 2)는 이
   전이를 트리거하는 UI를 아직 만들지 않았다 — Phase 2 보고서의 "Phase 3 준비사항"에
   이미 명시된 남은 작업이다.
2. **history append 실패(`OSError`) 방어 경로는 테스트되지 않았다** —
   `scripts/publish_threads.py`의 기존 동일 로직도 마찬가지로 테스트되지 않은
   방어 코드이며, 이번 구현은 그 기존 관례를 그대로 복제했을 뿐 새로운 위험을
   추가하지 않았다.
3. **GitHub Actions 연결은 이번 범위 밖이다** — 설계 문서 10장의
   `publish-approved-threads.yml`(승인 커밋 push 트리거)은 아직 만들지 않았다.
   이번 Phase는 로컬 CLI 실행까지만 다룬다.
4. **동시 실행에 대한 lock은 없다** — 같은 pending 파일에 대해 이 스크립트를
   두 프로세스가 동시에 `--execute`로 실행하면, atomic save 자체는 손상되지
   않지만 두 프로세스가 같은 draft에 대해 동시에 Threads API를 두 번 호출할
   가능성이 이론적으로 있다. 정상 운영(하루 1회, 순차 실행)에서는 발생하지
   않는 시나리오이며, 이번 범위에서는 복잡한 locking을 도입하지 않았다(9-2장
   설계와 동일한 판단).
