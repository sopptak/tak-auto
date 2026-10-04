# 5-11 Phase 1 구현 보고서 — Threads 초안 생성 → pending 저장

## 1. 목표

`docs/5-11_threads_human_review_design.md`에서 승인된 설계의 **Phase 1만** 구현한다.
기존 자동 Threads 발행 시스템은 절대 건드리지 않고, "Threads 초안 생성 → pending
파일 저장"까지만 구현한다. 코드 수정 후 commit/push는 하지 않는다(이번 지시).

## 2. 수정/생성 파일

| 구분 | 파일 |
|---|---|
| 신규 | `content_engine/threads_review.py` |
| 신규 | `scripts/generate_threads_draft.py` |
| 신규 | `tests/test_threads_review.py` |
| 신규 | `tests/test_generate_threads_draft.py` |
| 수정 | `.gitignore` (`!data/tak_threads_pending.json` 한 줄만 추가) |

## 3. 각 파일에서 한 일

### 3-1. `content_engine/threads_review.py`

- `ThreadsPendingDraft` dataclass 구현. 필드: `content_id`(compute_content_id
  재사용값을 그대로 저장, 새로 계산하지 않음), `knowledge_id`, `source_url`,
  `evidence_unit_ids`, `article_type`, `knowledge_type`, `original_title/body`,
  `ai_rewritten_title/body`, `final_title/body`, `edited_by_user`, `status`,
  `created_at`, `approved_at`, `published_at`, `failed_at`, `failure_reason`,
  `threads_post_id` — 설계 문서 6장의 필드를 모두 포함.
- `__post_init__`에서 필수 필드(`content_id`/`knowledge_id`/`created_at`) +
  `status ∈ {pending, approved, published, failed}` 검증.
- `load_pending()` / `save_pending()`(tempfile + `Path.replace()` 원자적 저장) /
  `upsert_pending()` — 기존 `PublishHistory`/`InterviewSession`과 동일한 저장
  패턴을 그대로 따름.
- `has_unresolved_draft()` — pending/approved만 "미해결"로 판단, published/failed는
  제외(설계 문서 5장 idempotency 기준).
- 상태 전이 helper 3개만 추가: `mark_approved`, `mark_published`, `mark_failed`.
  `_ALLOWED_TRANSITIONS` 딕셔너리로 `pending→approved`, `approved→{published,
  failed}`, `failed→approved`만 허용하고 그 외는 `ThreadsPendingError`를 던짐 —
  과도한 기능(취소, 강제 발행 등)은 추가하지 않았다.
- `content_engine.publish_history`(`PublishHistory`/`PublishRecord`)는 import조차
  하지 않음 — 완전히 독립적인 데이터 구조.

### 3-2. `scripts/generate_threads_draft.py`

- `run_daily.py`의 1~3단계(TAK BRAIN 로드 → `run_media_batch` →
  `select_unpublished_threads_item`)를 그대로 재사용.
- idempotency: `has_unresolved_draft()`가 True면 실제 LLM을 호출하기 전에
  즉시 종료(비용 절감 + 중복 생성 방지).
- `ThreadsClient`/`content_engine.threads_publisher`를 어디에서도 import하지
  않음 — 실수로도 실제 게시 코드 경로가 존재하지 않도록 원천 차단.
- `PublishHistory`는 읽기만(rotation 판단용), `append()` 호출 없음.
- `compute_content_id()`를 직접 호출하지 않고, `select_unpublished_threads_item()`이
  반환한 `content_id`를 그대로 저장(설계 문서 7장 정책 그대로).
- `article_type`/`knowledge_type`은 `MediaBatchItem`에 없는 필드라서, 승인
  KNOWLEDGE 목록에서 `knowledge_id`로 조회해 함께 저장.
- `run_daily.py`, `publish_threads.py`, `daily-threads-post.yml`,
  `select_unpublished_threads_item()` 자체는 전혀 수정하지 않음.

### 3-3. `.gitignore`

- `!data/threads_publish_log.json` 다음 줄에 `!data/tak_threads_pending.json`
  한 줄만 추가. 그 외 이미 존재하던(이번 작업과 무관한) 변경 사항은 그대로 유지.

## 4. 설계-코드 충돌 여부

**없음.** 설계 문서의 데이터 구조/idempotency/상태 모델과 실제 기존 코드
(`compute_content_id`, `select_unpublished_threads_item`, `MediaBatchItem`) 사이에
충돌하는 지점은 발견되지 않았다. `MediaBatchItem`에 `article_type`/`knowledge_type`
필드가 없다는 점은 설계 문서 6장에서 이미 예견되어 있었고("생성 시점에 함께
저장"), 실제 구현에서도 그대로 승인 KNOWLEDGE 조회로 채워 해결했다 — 기존 코드를
임의로 바꾸지 않았다.

## 5. 테스트

### 5-1. `tests/test_threads_review.py` (37개)

| 분류 | 검증 내용 |
|---|---|
| 필수 필드 검증 | content_id/knowledge_id/created_at 누락, 잘못된 status(`from_dict` 경로 포함), non-dict, evidence_unit_ids가 list가 아님 |
| 저장(원자성) | 파일 없음/빈 파일/공백만 있는 파일 로드, 손상된 JSON, list가 아닌 JSON, save/load round trip(None 필드 포함), 부모 디렉터리 자동 생성, **원자적 저장**(연속 저장 후 디렉터리에 임시 파일이 남지 않음, 저장된 JSON이 항상 완전한 구조) |
| upsert | 같은 content_id 덮어쓰기, 새 content_id 추가 |
| has_unresolved_draft | pending/approved=True, published/failed=False, 혼합 상황 |
| 상태 전이 | pending→approved, approved→published, approved→failed, failed→approved(재시도), 수정 여부에 따른 edited_by_user 계산, **잘못된 전이 전부 거부**(pending→published/failed 직접, published→어디로도, failed→published, approved→approved 재승인) |

**결과: 37/37 PASS**

### 5-2. `tests/test_generate_threads_draft.py` (9개)

| 검증 내용 |
|---|
| 생성된 pending draft의 필드가 정확한지(knowledge_id, article_type, knowledge_type, source_url, evidence_unit_ids, ai_rewritten_*=original_*(MockRewriteProvider), content_id 형식) |
| 승인 전 final_title/final_body가 None인지 |
| rotation 재사용: 이미 published된 content_id가 재선정되지 않고 같은 KNOWLEDGE의 다음 valid 후보로 폴백 |
| idempotency: pending/approved draft가 있으면 LLM조차 호출하지 않고 새로 생성 안 함(`assert_not_called()`로 검증) |
| published만 있으면(미해결 아님) 다시 생성을 시도함 |
| `ThreadsClient`/`threads_publisher`를 import 구문에서도, 모듈 속성으로도 참조하지 않음(정적 검사) |
| 승인 KNOWLEDGE 없음 → exit 0, pending 파일 미생성 |
| KNOWLEDGE 파일 없음 → exit 1 |

실제 LLM 호출은 `OpenAICompatibleRewriteProvider.from_environment`를
`MockRewriteProvider`로 patch(`tests/test_run_daily.py`와 동일한 방법론)해 완전히
차단했다.

**결과: 9/9 PASS**

### 5-3. 전체 스위트

```
python3 -m unittest discover -s tests -p 'test_*.py'
Ran 406 tests in 13.078s
OK
```

기존 360개 + 신규 46개(37+9) = **406/406 PASS**. 기존 테스트 파일은 한 줄도
수정하지 않았다.

## 6. 기존 운영 코드 변경 여부

**없음.** `run_daily.py`, `publish_threads.py`, `daily-threads-post.yml`,
`content_engine/publish_history.py`(rotation/`compute_content_id`),
`content_engine/generator.py`, `content_engine/rewrite.py`를 전혀 수정하지
않았다. (`content_engine/generator.py`, `rewrite.py`, `__init__.py`,
`llm_provider.py`, `tak_scout/__init__.py`, `data/tak_brain_knowledge.json`,
`tests/test_content_engine.py`, `tests/test_media_batch.py`에 남아 있던 diff는
이번 대화 이전부터 있던 별개 작업(blog_publish_pack 등)이며 이번 Phase 1에서
건드리지 않았다.)

## 7. 실제 Threads API 호출 여부

**없음.** 모든 테스트가 `MockRewriteProvider`로 LLM을 대체했고, `ThreadsClient`는
`scripts/generate_threads_draft.py` 어디에서도 참조되지 않는다(정적 검사
테스트로 확인).

## 8. 운영 데이터 변경 여부

**없음.** `data/tak_threads_pending.json` 실제 파일은 생성되지 않았다(모든
테스트가 `tempfile.TemporaryDirectory()` 사용). `data/threads_publish_log.json`,
`data/tak_brain_knowledge.json`도 건드리지 않았다.

## 9. 최종 git status

```
On branch main (origin/main보다 1커밋 뒤처짐 - fetch만 하고 pull은 안 함)

수정: .gitignore (1줄 추가)
신규 미추적: content_engine/threads_review.py
             scripts/generate_threads_draft.py
             tests/test_threads_review.py
             tests/test_generate_threads_draft.py

그 외 기존 modified/untracked 항목은 이번 작업 이전부터 있던 별개 변경사항,
전혀 손대지 않음.
```

commit/push는 지시대로 수행하지 않았다.

## 10. 결론

Phase 1 목표("생성 → pending 파일 저장까지만")를 설계 문서와 충돌 없이 구현했다.
`ThreadsClient`가 물리적으로 import되지 않는 구조이므로 실수로 실제 게시가
발생할 코드 경로 자체가 존재하지 않는다. rotation/`compute_content_id`/
`PublishHistory`는 전부 기존 함수를 무수정 재사용했고, 신규 46개 테스트를 포함해
전체 406개 테스트가 통과했다. Phase 2(발행 스크립트)로 진행할 준비가 되었다.
