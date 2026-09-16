# 5-11 Phase 3 자체 검토 보고서 — 승인된 Threads 발행 스크립트 안전성 재검증

> 이 문서는 `scripts/publish_approved_threads.py`(Phase 3 구현)를 다시 읽고,
> 5가지 안전 요구사항을 실제 코드 흐름 기준으로 재검증한 결과다. 코드 수정,
> git commit/push는 전혀 수행하지 않았다.

## 검토 대상

- `scripts/publish_approved_threads.py` (Phase 3 신규 구현)
- 검증 방법: 함수 호출 그래프를 실제로 추적해 각 분기가 도달 가능한지/불가능한지 확인

---

## 1. `--execute`가 없으면 어떤 상황에서도 Threads API가 호출되지 않는가

**PASS**

`ThreadsClient.from_environment()`는 파일 전체에서 딱 한 번, `main()` 루프 안의
한 지점에서만 호출된다. 그 지점에 도달하려면 순서대로:

- `if history.is_published(...)`를 통과해야 하고 (이미 published면 `continue`로
  빠짐 — `execute`와 무관하게 API 미호출)
- `if not execute: ... continue`를 통과해야 함

`execute = args.execute`는 `--execute`가 없으면 항상 `False`이므로, 두 번째
조건의 `continue`가 무조건 실행되어 API 호출 지점은 **코드 흐름상 도달
불가능**하다. `--dry-run` 여부와 무관하게 동일하다 — `--dry-run`은 `execute`
값을 바꾸지 않고, 오직 `--dry-run`+`--execute` 동시 지정을 막는 상호배제
검사에만 쓰인다.

## 2. `--dry-run`에서 pending JSON과 PublishHistory가 절대 변경되지 않는가

**PASS**

`execute=False`일 때 파일 쓰기 함수(`upsert_pending`, `history.append`)가
호출되는 지점을 모두 확인한 결과:

- 이력 중복 동기화 쓰기(`upsert_pending`)는 `if execute:` 블록 안에만 있어
  dry-run에서 스킵됨
- 성공/실패 시 쓰기 경로는 1번에서 확인했듯 애초에 도달 불가능

`history.is_published()`는 `PublishHistory.load()`만 호출하는 순수 읽기이고,
파일이 없으면 빈 리스트만 반환할 뿐 파일을 새로 생성하지도 않는다
(`content_engine/publish_history.py`의 `load()` 구현 확인). 따라서 dry-run
경로에서 실행되는 유일한 부작용은 `print()`뿐이다.

## 3. approved 상태이고 final_title/final_body가 있는 경우에만 실제 발행되는가

**PASS**

두 단계로 강제된다:

1. `load_approved_drafts()`가 `status == "approved"`만 필터링 —
   pending/published/failed는 애초에 루프에 들어오지 않음
2. 루프 진입 직후 `validate_final_text(draft)`가 `final_title`/`final_body`가
   `None`이거나 공백만이면 즉시 `continue`. 이 검증은 dry-run/execute 분기보다
   **먼저** 실행되므로, 실제 발행뿐 아니라 dry-run 미리보기 대상에서도
   제외된다.

`client.publish_text(draft.final_body)`에 도달하려면 이 두 조건을 모두
통과해야 하므로 요구사항과 정확히 일치한다.

## 4. Threads API 성공 전에 PublishHistory 기록/`published` 전환이 일어나지 않는가

**PASS**

`result = client.publish_text(...)`가 예외 없이 반환된 **뒤에만**
`published_at` 계산, `history.append(...)`, `mark_published(...)`이
실행된다. 예외가 나면 즉시 `mark_failed` + `continue`로 빠지므로
`history.append`/`mark_published`에 도달하지 않는다. "성공 확인 →
기록"의 순서가 코드 구조상 뒤바뀔 수 없다.

참고: "이미 history에 있음" 동기화 분기(5번 참고)는 이 순서와 무관한
별개 경로다 — 그 경우는 **과거에 이미 성공한 적 있는** content_id를
사후 동기화하는 것이지, 아직 성공하지 않은 것을 먼저 기록하는 게
아니다.

## 5. 같은 content_id가 이미 PublishHistory에 있거나 `published` 상태면 API를 호출하지 않는가

**PASS**

두 경우 모두 API 호출 전에 차단된다:

- **`published` 상태**: `load_approved_drafts()`가 `status == "approved"`만
  통과시키므로, `published` 상태 draft는 애초에 루프 대상 목록에 들어오지조차
  않는다.
- **PublishHistory에 이미 있음**: `if history.is_published(draft.content_id):`가
  참이면 안내 메시지 출력 + (execute일 때만) 기존 레코드 값으로 draft를
  `published`로 동기화하고 `continue` — API 호출에 도달하지 않는다.

---

## 종합

| # | 항목 | 결과 |
|---|---|---|
| 1 | `--execute` 없이는 API 미호출 | PASS |
| 2 | `--dry-run`에서 pending/PublishHistory 불변 | PASS |
| 3 | approved + final_title/body 있을 때만 발행 | PASS |
| 4 | API 성공 전 기록/상태전환 없음 | PASS |
| 5 | 중복 content_id(history/published) API 미호출 | PASS |

**5개 항목 전부 PASS.** 코드 수정은 하지 않았고, git commit/push도 수행하지
않았다.
