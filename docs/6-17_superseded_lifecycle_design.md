# 6-17 SUPERSEDED Lifecycle Design

## 1. 작업 목적

6-16이 CRITICAL로 남긴 문제 — 승인된(approved) Production Archive 레코드
`content-5971ed5204437cdd`(blog, finance 템플릿 오염)를 정정본
`content-afc6060bc1957867`로 "교체"할 방법이 현재 코드에 없다(promotion은
"추가"만 가능하고, edit/dismiss는 approved 레코드를 코드 레벨에서 거부한다) —
를 해결하기 위한 `SUPERSEDED` 생명주기를 **설계하고, synthetic
fixture/tempfile로 전체 동작을 검증**하는 것이 이번 세션의 유일한 목적이다.

절대 원칙(작업 지시 0장)에 따라 이번 세션에서는 다음을 전혀 하지 않았다:

- 외부 Naver/Threads/YouTube 게시, LLM 호출
- Production Archive(`data/tak_media_archive.json`)/KNOWLEDGE/Threads pending/
  publish log 실제 변경
- `content-5971ed5204437cdd`, `content-afc6060bc1957867`에 대한 실제 승인/대체
  실행

이번 세션이 실제로 변경한 파일(전부 코드/테스트/문서, 데이터 파일 아님):

- `content_engine/media_archive.py` (SUPERSEDED review_status + `superseded_by`
  필드 추가)
- `content_engine/publish_audit.py` (SUPERSEDED 분류 추가)
- `scripts/audit_publish_candidates.py` (SUPERSEDED 카운트 출력 추가)
- `scripts/supersede_media_record.py` (신규 CLI)
- `tests/test_media_superseded_lifecycle.py` (신규, 25개 테스트)
- `docs/publish_readiness_latest.md`, `docs/threads_publish_consistency_latest.md`
  (18장에서 재실행 — 스크립트의 정상 설계 동작, 실제 데이터가 안 바뀌었으므로
  타임스탬프 + SUPERSEDED 카운트 줄만 추가되고 나머지는 6-16과 동일)
- 이 문서

## 2. 시작 상태

```
$ git branch --show-current
main
$ git rev-parse HEAD
1f826d3c71af0986051748361682e07c277a7a59
$ git fetch origin   # (출력 없음)
$ git log --oneline -10
1f826d3 6-16: audit critical media replacement path
8b3f816 fix: repair category/article_type integrity and Threads publish consistency (6-15)
...
$ git log origin/main..HEAD    # (비어 있음)
$ git log HEAD..origin/main    # (비어 있음)
```

Baseline 전체 테스트:

```
1008 passed, 68 subtests passed in 163.08s, 0 failed
```

지시서 예상치(1008 passed, 0 failed)와 정확히 일치했다.

`git status --short`의 기존 미커밋 변경 목록(`.gitignore`,
`content_engine/__init__.py`, `content_engine/generator.py`,
`content_engine/llm_provider.py`, `content_engine/rewrite.py`,
`tests/test_content_engine.py`, `tests/test_media_batch.py`, 그리고 다수의
기존 untracked 문서/스크립트)은 6-16 종료 시점과 동일했다 — 이번 세션에서
전혀 손대지 않았다.

데이터 파일 SHA256(작업 전, 17장에서 작업 후와 비교):

```
ebe1249fe36c3fe681660c3659d2199f5ecd4f6949b7890479fac9a4e8ea8d33  data/tak_media_archive.json
e2ad1d39fa254ceaad4fb646124cb3e9b0b8e591ea688c1e0836fa1b6f706a31  data/tak_brain_knowledge.json
d122a0b68c093fb0e894251e60d5d987b40d9a268cd9b44522c4385bf5cabf72  data/tak_threads_pending.json
d89074291327bc759d5416531c6cc6fb9a8cad0c5fcb6e8dc32660535d995c68  data/threads_publish_log.json
```

## 3. 현재 Approved Lifecycle 분석

`content_engine/media_archive.py`, `content_engine/publish_audit.py`,
`scripts/promote_media_generation.py`, `scripts/run_scout_dashboard.py`,
`tests/test_media_versioning_and_promotion.py`,
`tests/test_media_dashboard.py`,
`tests/test_critical_content_replacement_audit.py`를 코드/docstring 근거로
직접 확인했다(임의로 의미를 만들지 않음).

| 상태/필드 | 실제 의미(코드 근거) | 전이 가능 방향(변경 전) |
|---|---|---|
| `generation_status`(`valid`/`rejected`/`error`) | `MediaBatchItem.status`를 그대로 옮긴 값 — "이 생성 시도가 배치 검증을 통과했는가"라는 **생성 단계의 사실**. 사람이 바꿀 수 없다(`media_archive.py` 19~21행). | 불변(재생성해야만 새 값이 나온다) |
| `review_status`(`unreviewed`/`approved`/`dismissed`) | "사람이 Dashboard에서 검토했는가" — 신규 항목은 항상 `unreviewed`. | `unreviewed ↔ dismissed`(자유 왕복), `unreviewed/dismissed → approved`(승인) |
| `approved` | `_can_review_media_record()`(`run_scout_dashboard.py:852`)가 **되돌릴 수 없는 종결 상태**로 취급 — `handle_media_edit_submission`/`handle_media_dismiss_submission` 둘 다 approved면 거부(각각 "이미 승인된 콘텐츠는 수정/보류할 수 없습니다"). | approved에서 나가는 전이 자체가 코드에 없음(6-16이 `dir()`로 고정) |
| `dismissed` | "사람이 보류함" — `_can_review_media_record()`가 True를 반환해 unreviewed와 동일하게 다시 검토 가능. | `dismissed → unreviewed`(edit 시) 또는 `dismissed → approved`(승인 시) |
| `generation_id` | "몇 번째 생성 시도인가"(6-06). 기존(5-27) 레코드는 `None`("legacy generation"). `content_id`의 의미(콘텐츠 슬롯 식별자)와 무관한 별도 축. | production archive는 `content_id` 단독 키(`upsert_archive`), generation pool은 `(content_id, generation_id)` 복합 키(`upsert_generation_archive`) |

**Promotion 경로**(`promote_media_generation.py`): generation pool에서
`(content_id, generation_id)`가 정확히 일치하고 `generation_status=="valid"`이고
`review_status=="approved"`인 record만 production archive에
`upsert_archive()`로 반영한다. 이 스크립트는 승인 기능이 없다(이미 approved된
generation만 대상).

**6-16이 실증한 핵심 문제**: 정정본이 `original_title`/`original_body`가
달라져 `compute_content_id()` 결과(=content_id)가 바뀌면(9건 중 2건이 실제로
그랬다), promotion은 옛 승인 레코드를 "교체"하지 않고 "추가"한다 — 결과적으로
같은 `knowledge_id`에 approved 레코드 2건이 동시에 존재하게 된다. 그리고
그 옛 레코드는 approved이므로 edit/dismiss 둘 다 거부돼, "이 레코드는 대체됐다"고
표시할 방법이 코드에 전혀 없었다.

## 4. SUPERSEDED 상태 정의

작업 지시 3장의 8개 질문에 코드 근거로 답한다.

1. **`superseded`는 `review_status`에 들어가는 것이 맞는가?** — 그렇다.
   `generation_status`는 배치 검증 결과라는 별개 축(질문 2)이고, superseded는
   순전히 "사람이 이미 approved한 것을 나중에 운영상 대체 결정한 것"이므로
   review_status 축의 성격과 일치한다. `threads_review.py`가 이미
   `ThreadsPendingDraft.status`에 `_ALLOWED_TRANSITIONS` 딕셔너리로 명시적
   전이 그래프를 두는 선례가 있다 — 같은 관례를 media review_status에도
   적용한다(`REVIEW_STATUS_TRANSITIONS`, 5장).
2. **`generation_status`에 넣는 것은 왜 부적절한가?** — `generation_status`는
   "이 특정 생성 시도가 검증을 통과했는가"라는 **불변의 과거 사실**이고,
   `promote_media_generation.py`의 gating 조건(`generation_status=="valid"`)이
   이 불변성에 의존한다. 여기에 superseded를 섞으면 "이미 승격된 valid
   레코드가 나중에 superseded되면 재승격이 막히는가?" 같은 새로운 모호성이
   생기고, 기존 promotion 코드를 반드시 함께 고쳐야 한다 — 축이 다르다.
3. **`superseded` == "사람이 승인 취소한 것"과 같은 의미인가?** — 아니다.
   "취소(unapprove/revoke)"는 "그 승인이 애초에 잘못됐다"는 뜻으로
   `unreviewed`로 되돌리는 것을 함의하지만, superseded는 "그 승인은 그
   시점에 정당했고, 이후 더 나은 버전이 나와 활성 후보 자리를 넘겨준다"는
   뜻이다. 이 차이 때문에 superseded는 unreviewed로 돌아가지 않고 **종결
   상태**로 설계한다(5장).
4. **`dismissed`와 어떻게 다른가?** — `dismissed`는 **승인 전** 상태에서
   "지금은 보류, 나중에 다시 검토 가능"이라는 가역적 결정이다(코드가 실제로
   `dismissed → approved` 전이를 허용). `superseded`는 **승인 후**에만
   일어나고 다시 검토 대상으로 돌아가지 않는 비가역적 결정이다 — 발생
   조건(approved에서만)과 가역성 둘 다 다르다.
5. **`superseded` = "정정본이 존재하는 이전 버전"이라는 의미인가?** — 그렇다.
   이것이 정확한 정의다. 이 레코드 자체에 문제가 있었다는 뜻이 아니라
   "더 나은 대체본이 존재하므로 이 레코드는 더 이상 활성 후보가 아니다"라는
   순수한 상태 표시다.
6. **이력 보존을 위해 Production Archive에 남아 있어야 하는가?** — 그렇다.
   삭제하지 않는다(작업 지시 4장 원칙). `content_id`/제목/본문/`created_at`/
   `knowledge_id`/`source_url`/`evidence`/publish history 등 어떤 필드도
   건드리지 않고, `review_status`와 새 필드 `superseded_by`만 갱신한다.
7. **Publish Readiness에서 어떻게 취급해야 하는가?** — 8장 참고. 활성 후보가
   아니지만 BLOCKED/ALREADY_PUBLISHED와 성격이 다르므로 별도 `SUPERSEDED`
   분류를 신설했다.
8. **이미 publish된 경우와 아직 안 된 경우를 구분해야 하는가?** — 그렇다.
   이미 게시된 적이 있다면(외부에 이미 나간 사실) `ALREADY_PUBLISHED`가
   `SUPERSEDED`보다 우선한다 — 사람이 "재게시 여부"가 아니라 "회수 필요
   여부"를 판단해야 하는, 더 긴급한 정보이기 때문이다(8장에서 테스트로
   고정: `PublishReadinessExcludesSupersededTests.
   test_already_published_takes_precedence_over_superseded`).

## 5. 상태 전이표

```python
# content_engine/media_archive.py
REVIEW_STATUS_TRANSITIONS: dict[str, frozenset[str]] = {
    "unreviewed": frozenset({"approved", "dismissed"}),
    "dismissed":  frozenset({"unreviewed", "approved"}),
    "approved":   frozenset({"superseded"}),
    "superseded": frozenset(),
}
```

허용:

```
UNREVIEWED  → APPROVED
UNREVIEWED  → DISMISSED
DISMISSED   → UNREVIEWED  (edit)
DISMISSED   → APPROVED
APPROVED    → SUPERSEDED  (신규 - 이번 세션이 도입)
```

명시적으로 허용하지 않음(테스트로 고정, `SupersededStatusRecognizedTests`):

```
SUPERSEDED  → APPROVED       (금지 - "복권"은 새 레코드를 만들어야 함, 기존 레코드를 되살리지 않음)
SUPERSEDED  → UNREVIEWED     (금지)
SUPERSEDED  → DISMISSED      (금지)
SUPERSEDED  → SUPERSEDED(다시) (금지 - 이중 supersede 방지, plan_supersede()가 명시적으로 거부)
UNREVIEWED  → SUPERSEDED     (금지 - supersede는 approved에서만 발생)
DISMISSED   → SUPERSEDED     (금지 - 위와 동일)
```

이 상수(`REVIEW_STATUS_TRANSITIONS`)는 현재 **문서화/신규 코드 참고용**이다.
기존 `handle_media_edit_submission`/`handle_media_dismiss_submission`/
`handle_media_approve_submission`은 각자 개별 조건문으로 전이를 막고 있고,
이번 세션은 그 함수들을 이 표를 강제하도록 리팩터링하지 않았다(기존 동작을
바꾸지 않는다는 원칙 — 리팩터링은 별도 세션의 판단 사항, 19장).

## 6. superseded_by / supersedes 데이터 모델 비교

| 평가 기준 | A안(양방향: old.superseded_by + new.supersedes) | **B안(단방향: old.superseded_by만) — 채택** |
|---|---|---|
| 데이터 중복 | 두 레코드에 관계 정보가 나뉘어 저장됨 | 한 필드만 존재 — 중복 없음 |
| dual-consistency 위험 | 두 값이 어긋날 수 있음(예: old.superseded_by는 갱신됐는데 new.supersedes는 안 됐거나, 그 반대) | 위험 없음(단일 진실 소스) |
| backward compatibility | 새 레코드 스키마도 확장해야 함 | 새 레코드는 **전혀 건드리지 않음** — 기존 promotion 결과를 그대로 재사용 |
| frozen dataclass | 두 레코드 모두 `dataclasses.replace()` 필요 | old 레코드 1건만 `replace()` — 변경 지점이 절반 |
| content_id uniqueness | 영향 없음(둘 다) | 영향 없음 |
| generation pool / promotion | 새 레코드가 generation pool에서 나올 때 이미 `supersedes`를 채워야 하므로 `promote_media_generation.py`까지 수정 필요 | **수정 불필요** — 새 레코드는 기존 promotion 그대로, supersede는 그 이후 별도 1단계 |
| rollback | 두 레코드를 동시에 되돌려야 함 | old 레코드 1건만 되돌리면 됨(백업본으로 교체) |
| 사람이 읽기 쉬운 이력 | 양쪽에서 바로 보임(장점) | old→new는 필드로 바로 보이고, new→old(역방향)는 `superseded_by == new_content_id`인 레코드를 archive에서 찾는 한 줄 쿼리로 구할 수 있음 — 정보 손실 없음 |
| 테스트 용이성 | 두 레코드의 정합성까지 매번 검증해야 함 | old 레코드 1건의 필드 정합성만 검증하면 됨(`__post_init__`이 이미 강제) |

**결론 — B안 채택**. 양방향 정보가 필요할 때는 조회(archive 전체에서
`superseded_by == X`인 레코드 찾기)로 항상 구할 수 있으므로 정보 손실이
없고, 원자성/일관성 위험은 B안이 구조적으로 더 낮다. 새 레코드를 전혀
건드리지 않는다는 점이 결정적이었다 — 그 덕분에 supersede 연산이 "옛 레코드
1건 갱신"으로 완전히 축소되고, 9장의 원자성 분석이 단순해진다.

구현(`content_engine/media_archive.py`):

```python
superseded_by: str | None = None   # MediaArchiveRecord의 새 필드, 기본값 None
```

`__post_init__`에서 강제하는 정합성 규칙(테스트: `SupersededStatusRecognizedTests`):

- `review_status == "superseded"` ⇒ `superseded_by`가 반드시 있어야 함
- `superseded_by`가 있으면 ⇒ `review_status`가 반드시 `"superseded"`여야 함
- `superseded_by != content_id`(자기 자신을 가리킬 수 없음)

## 7. Production Archive 호환성

기존 Production Archive(18건)에는 legacy `generation_id=None`,
`approved`/`unreviewed`/`rejected`, 여러 `knowledge_id`, 동일 knowledge의
여러 platform이 이미 섞여 있다. `superseded_by` 필드는 6-06의 `generation_id`
도입 때와 **완전히 동일한 backward-compatible 패턴**을 그대로 재사용했다:

```python
# from_dict()
superseded_by=_optional_str(data.get("superseded_by")),  # 키 없으면 None
```

`LegacyRecordCompatibilityTests.test_record_without_superseded_by_key_parses_with_default_none`으로
고정: `superseded_by` 키가 아예 없는 dict(=기존 18건과 동일한 모양)도
KeyError 없이 `superseded_by=None`으로 파싱된다. **migration이 전혀
필요없다** — 이 사실은 17장의 SHA256 확인(실제 파일을 열지도 않고 바이트
단위로 동일함을 재확인)으로도 뒷받침된다. 실제로 이번 세션 내내
`data/tak_media_archive.json`은 `load_archive()`로 읽기만 했고(11장의
시뮬레이션에서도 tmp 사본에만 썼다), 쓰기는 단 한 번도 하지 않았다.

## 8. Publish Readiness 연동

`content_engine/publish_audit.py`에 `SUPERSEDED` 분류를 추가했다.

```python
PUBLISH_READINESS_STATUSES = (READY, NEEDS_HUMAN_REVIEW, BLOCKED, ALREADY_PUBLISHED, SUPERSEDED, ERROR)
```

`audit_record()`의 판정 순서(우선순위, 기존 순서에 한 단계만 삽입):

1. `ERROR`(구조적 이상 — content_id 중복) — 기존 그대로, 최우선
2. 채널별 실제 게시 이력 확인 → `ALREADY_PUBLISHED` — 기존 그대로, 여전히
   두 번째로 우선. **superseded 레코드도 이미 게시된 적이 있다면 여기서
   먼저 걸린다** — SUPERSEDED보다 위에 있으므로 절대 가려지지 않는다.
3. **(신규) `record.superseded_by`가 채워져 있으면 → `SUPERSEDED`.** BLOCKED의
   "review_status가 approved가 아님" 사유에 섞이지 않도록 별도 분류로
   분리했다 — superseded는 "정상적으로 처리 완료된 상태"이지 "문제가 있어
   차단된 상태"가 아니기 때문이다.
4. 기존 BLOCKED 사유(generation_status/review_status/필수 필드/Shorts Script)
   — 기존 그대로
5. `is_review_required()` → `NEEDS_HUMAN_REVIEW` — 기존 그대로
6. `READY` — 기존 그대로

이 순서 덕분에 "OLD APPROVED → SUPERSEDED → 후보 제외" / "NEW APPROVED →
READY(또는 조건에 따라 NEEDS_HUMAN_REVIEW)"라는, 작업 지시 7장이 요구한
관계가 정확히 성립한다(15장의 실측 시뮬레이션으로 확인).

`render_readiness_markdown()`/`summarize()`/`scripts/audit_publish_candidates.py`
터미널 출력에도 SUPERSEDED 카운트와 전용 섹션(`## Superseded`)을 추가했다 —
기존 5개 상태(READY/NEEDS_HUMAN_REVIEW/BLOCKED/ALREADY_PUBLISHED/ERROR)의
카운트/판정 로직은 **한 글자도 바뀌지 않았다**(17장에서 실제 데이터로 재확인
— 6-16과 완전히 동일한 결과가 나왔다).

## 9. Generation Pool / Promotion 연동

**결정: promotion과 supersede를 하나의 트랜잭션으로 묶지 않고, 완전히 분리된
두 단계로 설계한다.**

```
1단계(기존, 변경 없음): promote_media_generation.py
   generation pool의 approved+valid 정정본을 production archive에 추가
   → 이 시점부터 production archive에 old(approved)와 new(approved)가 동시 존재

2단계(신규): scripts/supersede_media_record.py
   이미 production archive에 있는 old/new 두 레코드만 보고,
   old.review_status를 "superseded"로, superseded_by를 new.content_id로 갱신
```

이렇게 분리한 이유(작업 지시 8장이 요구한 "하나의 transaction-like
workflow" 검토 결과): 6장에서 결정한 B안(단방향 필드)은 새 레코드를 전혀
건드리지 않으므로, 두 단계를 하나로 합쳐도 실질적인 원자성 이득이 없다 —
1단계가 이미 원자적(단일 파일 upsert)이고 2단계도 원자적(단일 파일 upsert)
이므로, 합치면 오히려 "1단계는 성공, 2단계는 실패"라는 부분 실패 시나리오를
하나의 함수 안에서 처리해야 하는 복잡성만 늘어난다. 분리하면 각 단계가
독립적으로 재시도 가능하고(idempotent), 실패 시나리오도 각자 명확하다(10장).

`scripts/supersede_media_record.py`의 `plan_supersede()`가 검증하는 조건
(작업 지시 9장 CASE 1~10과 대응):

| 조건 | 대응 CASE | 위반 시 |
|---|---|---|
| old_content_id가 production archive에 존재 | CASE 5 | `SupersedeError`, old 변경 없음 |
| new_content_id가 production archive에 존재(이미 promotion 완료) | (신규 — 순서 의존성) | `SupersedeError` |
| old.content_id != new.content_id | CASE 4 관련(자기 자신 대체 방지) | `SupersedeError` |
| old.review_status == "approved"(이미 superseded면 거부) | (이중 supersede 방지) | `SupersedeError` |
| new.generation_status == "valid" | CASE 1 | `SupersedeError`, old는 approved 유지 |
| new.review_status == "approved" | CASE 2 | `SupersedeError`, old는 approved 유지 |
| old.knowledge_id == new.knowledge_id | CASE 6 | `SupersedeError` |
| old.platform == new.platform | (추가 안전장치) | `SupersedeError` |
| old.source_url == new.source_url | CASE 7(정책 결정, 아래) | `SupersedeError` |

**CASE 7 정책 결정(source_url이 다른 경우)**: 이번 세션은 **다르면 무조건
거부**하는 정책을 채택했다. 이유: "supersede"의 정의(4장 질문 5)는 "같은
원문의 정정본"이다. source_url이 다르면 그것은 "정정"이 아니라 "완전히
다른 콘텐츠로의 교체"이므로, 안전 장치가 약한 이 워크플로우로 처리하면
실수로 무관한 콘텐츠가 조용히 "정정본"이라는 이름으로 승인 이력을 이어받을
위험이 있다. 이 정책은 **바꿀 수 없는 것이 아니라 명시적 선택**이며, 향후
"같은 knowledge_id, 다른 source_url"을 정당하게 supersede해야 하는 실제
사례가 나오면 사람이 재검토해야 한다(19장).

## 10. Atomicity / Rollback

| CASE | 검증 결과 |
|---|---|
| 1. new가 invalid | `plan_supersede()`가 파일을 쓰기 전에 예외 — old는 파일에 손대지 않아 **원래 상태 그대로** (`test_case1_invalid_new_candidate_rejected_old_stays_approved`) |
| 2. new가 unreviewed | 위와 동일 (`test_case2_unreviewed_new_candidate_rejected_old_stays_approved`) |
| 3. new가 approved | `updated_old.review_status=="superseded"`, `superseded_by==new.content_id` (`test_case3_approved_new_candidate_supersedes_old`) |
| 4. new content_id가 old와 같음 | `plan_supersede()` 예외(자기 자신 대체 방지) (`test_case4_new_content_id_same_as_old_rejected`) |
| 5. old content_id가 존재하지 않음 | `plan_supersede()` 예외 (`test_case5_missing_old_content_id_rejected`) |
| 6. old/new knowledge_id가 다름 | `plan_supersede()` 예외 (`test_case6_knowledge_id_mismatch_rejected`) |
| 7. old/new source_url이 다름 | 정책상 거부(9장) (`test_case7_source_url_mismatch_rejected_by_policy`) |
| 8. old가 이미 외부 게시됨 | `plan_supersede()`는 publish history를 확인하지 않는다(promotion과 동일하게 publish 이력을 아예 참조하지 않음 — 6-16이 이미 지적한 사각지대, 11장에서 재논의). **다만 publish_audit 단계에서는 ALREADY_PUBLISHED가 SUPERSEDED보다 우선하므로(8장) 사람은 결과 화면에서 즉시 알 수 있다** — supersede 실행 자체를 막지는 않지만, 결과를 잘못 해석할 위험은 없다. |
| 9. 파일 저장 도중 실패 | `save_archive()`가 `tempfile.NamedTemporaryFile` + `Path.replace()`(원자적 rename)를 쓰므로, 쓰기 도중 프로세스가 죽어도 원본 파일은 그대로 남는다 — `upsert_archive()`/`execute_supersede()` 전체가 이 보장을 상속받는다. 새 코드를 추가하지 않고 기존 원자적 저장 패턴을 그대로 재사용했다. |
| 10. promotion 후 audit 실패 | `plan_supersede`/`execute_supersede`는 audit을 호출하지 않는다(완전히 분리된 읽기 전용 모듈, `content_engine/publish_audit.py`). audit이 실패해도(예: 파일 파싱 오류) production archive 상태는 이미 일관된 상태(old=superseded, new=approved)로 저장이 끝난 뒤이므로 "롤백"이 필요 없다 — audit은 언제든 다시 실행 가능한 순수 읽기 함수이기 때문이다. |

**핵심 설계 근거**: 6장에서 B안(단방향 필드)을 선택한 결과, supersede
연산이 "옛 레코드 1건만 갱신하는 단일 `upsert_archive()` 호출"로 축소됐다 —
그래서 진짜 의미의 "여러 파일/여러 레코드에 걸친 트랜잭션"이 애초에
필요없어졌다. 원자성은 기존 `save_archive()`의 tempfile+replace 패턴만으로
충분하다.

## 11. content_id / publish history 사각지대

6-16이 이미 지적한 사각지대(정정으로 content_id가 바뀌면 "이미 게시된
knowledge/source"인지 자동 감지가 안 됨)를 다시 검토했다. 4가지 정책안
비교:

| 정책 | false positive | false negative | 운영 복잡성 |
|---|---|---|---|
| A. content_id 기준만 | 없음 | **높음** — content_id가 바뀌면 같은 knowledge/source가 이미 게시됐어도 못 잡음(현재 상태) | 매우 낮음(변경 없음) |
| B. knowledge_id + platform 보조 검사 | 낮음(같은 knowledge를 의도적으로 여러 platform에 재활용하는 정상 케이스가 있다면 오탐 가능 — 실제로 knowledge 1건당 blog/shorts×N/threads×N 여러 개가 정상이므로 이 조합은 **오탐이 실제로 발생**) | 낮음 | 중간 |
| C. knowledge_id + source_url + platform 보조 검사 | B보다는 낮음(knowledge:source가 1:1이면 B와 사실상 동일) | 낮음 | 중간 |
| D. knowledge_id + source_url + platform + publish history 보조 검사 | **가장 낮음** — 실제 게시 이력과 대조하므로 "아직 게시 안 됐지만 같은 knowledge/platform의 다른 content_id가 production에 있다"는 정상 케이스(예: 이번 세션의 old+new 공존)를 오탐하지 않는다 | 가장 낮음 | 가장 높음(여러 저장소를 대조해야 함) |

**권고(설계만, 이번 세션에서 구현하지 않음)**: D가 가장 안전하지만,
`promote_media_generation.py`와 `content_engine/publish_audit.py` 양쪽에
publish history 조회 의존성을 추가해야 하는 구조 변경이라 이번 세션 범위(작은
추가 변경) 밖이다. 이 세션이 실제로 구현한 SUPERSEDED lifecycle은 이
사각지대를 직접 해결하지 않는다 — 다만 `superseded_by` 필드 덕분에 "이
content_id는 이미 대체됐다"는 사실이 최소한 production archive 안에
persist되므로, D를 나중에 구현할 때 "supersede된 적 있는 content_id 사슬을
따라가며 publish history를 확인한다"는 형태로 자연스럽게 확장할 수 있는
기반은 마련됐다.

**이번 세션이 새로 발견한 관련 사실(합성 데이터로 재현·확인, 6-16에는 없던
내용)**: content_id가 **같은** 경우(6-05 재생성 9건 중 7건이 실제로 이
상황)에도, `promote_media_generation.py`로 이미 approved인 production
레코드를 다른 generation으로 promotion하면 `upsert_archive()`가 이전
텍스트를 **아무 흔적도 없이 덮어쓴다**(테스트로 직접 재현 —
`plan_promotion()`은 이 경우를 막지 않고, CLI의 dry-run 출력에 경고 문구가
찍히긴 하지만 그건 사람이 화면을 읽어야만 보이는 것이지 데이터에 남는
기록이 아니다). 이것은 이번 세션이 설계한 SUPERSEDED(다른 content_id 대체)
경로와는 **다른, 이미 존재하던 별개의 사각지대**다 — content_id가 같으면
"대체"가 아니라 "같은 슬롯의 갱신"으로 취급되기 때문에 애초에 SUPERSEDED가
적용될 자리가 없다(같은 content_id를 자기 자신으로 가리킬 수 없다는
`superseded_by != content_id` 제약과 정확히 같은 이유). 이 발견은 고치지
않고 19장에 사람의 결정 사항으로 남긴다.

## 12. 동일 KNOWLEDGE 7개 승인 콘텐츠 조사

`knowledge-scout-b28b782b2a33`의 approved 7건을 실제 데이터에서 **읽기만
해서** 다시 확인했다(6-16과 동일한 결과 — 이번 세션에서 아무것도 바뀌지
않았으므로 당연하다).

| content_id | platform | review_status | generation_status | generation_id | downstream artifact | 실제 게시 여부 |
|---|---|---|---|---|---|---|
| content-5971ed5204437cdd | blog | approved | valid | None(legacy) | 없음(blog는 Publish Pack 생성 전) | NOT_PUBLISHED(`data/blog_publish_log.json` 파일 자체 부재) |
| content-e787c9201b94a948 | shorts | approved | valid | None | `data/shorts_scripts/content-e787c9201b94a948.json` 존재 | NOT_PUBLISHED(YouTube 이력 없음, MP4 없음) |
| content-3ae2d78568210164 | shorts | approved | valid | None | `data/shorts_scripts/content-3ae2d78568210164.json` 존재 | NOT_PUBLISHED |
| content-dbf0fb4eb5cfd791 | threads | approved | valid | None | `data/tak_threads_pending.json`에 status=`pending` draft 존재 | NOT_PUBLISHED |
| content-81d4e7c5723598f6 | threads | approved | valid | None | 위와 동일(pending) | NOT_PUBLISHED |
| content-4015df0692e0bcc4 | threads | approved | valid | None | 위와 동일(pending) | NOT_PUBLISHED |
| content-cbcf705b6056c9fc | threads | approved | valid | None | 위와 동일(pending) | NOT_PUBLISHED |

Finance contamination(6-16 3~4장 재확인, 이번 세션에서 다시 텍스트를 읽어
독립 검증): blog 1건만 뚜렷한 오염(finance 템플릿 제목 슬롯 + 금융기관 면책
문구)이 있고, shorts/threads 6건은 finance 프로파일이 건드리는 슬롯이 아니라
가시적 오염은 없다(6-05/6-08의 기존 결론과 일치).

**플랫폼별 supersede 시 downstream 처리 차이**(13장에서 정책으로 구체화):

- **Blog**: downstream artifact가 아직 없다(Publish Pack 미생성) — supersede
  실행 자체가 어떤 파일에도 영향을 주지 않는다. 가장 단순한 케이스.
- **Shorts**: `ShortsScript` JSON 파일이 이미 생성돼 있다. 이 파일은
  `content_id`로 이름 붙여진 별도 파일이라, old의 `superseded_by`를
  세팅해도 그 파일은 그대로 남는다(삭제 코드가 없다 — 자동으로 사라지지
  않는다는 뜻이지, 안전하다는 보장이 코드로 강제된 것은 아니다).
- **Threads**: `data/tak_threads_pending.json`에 `status="pending"` draft가
  이미 있다. supersede는 이 파일을 열지도 않는다(11장, 10장 CASE 9/10 관련
  설계) — pending draft는 old가 superseded된 후에도 그대로 "미해결" 상태로
  남는다. **이것이 13장의 핵심 정책 질문**이다: 옛 pending draft가 나중에
  실수로 승인/발행되면 어떻게 되는가?

## 13. downstream artifact 정책

**원칙(작업 지시 13장, 절대 위반하지 않음): supersede는 어떤 downstream
artifact도 자동으로 삭제하지 않는다.** `scripts/supersede_media_record.py`는
production archive 파일 하나만 열고 쓴다 — ShortsScript, Threads pending,
publish history 파일은 import조차 하지 않는다(코드로 확인 가능:
`supersede_media_record.py` 상단 import 목록에 `threads_review`,
`shorts_adapter`, `publish_history`가 없다). 이 사실을 테스트로 고정했다
(`DownstreamArtifactNotDeletedTests.test_supersede_does_not_touch_publish_history_file`
— publish history 파일의 바이트/mtime이 supersede 전후로 완전히 동일함을
확인).

플랫폼별 제안 정책(**설계만, 이번 세션에서 구현하지 않음**):

- **Blog**: downstream이 Publish Pack(매번 다시 선정되는 배치 산출물)이므로
  별도 정책이 필요 없다 — `select_blog_publish_candidates()`가 다음 실행
  때 production archive를 다시 읽으므로, superseded 레코드를 자동으로
  제외하도록 그 함수에 `review_status != "superseded"` 조건을 추가하는 것을
  제안한다(이번 세션에서 구현 안 함 — `blog_publish_pack.py`를 건드리지
  않았다).
- **Shorts**: 이미 생성된 `ShortsScript` 파일은 그대로 둔다(이력 보존
  원칙). 다만 향후 "렌더링/업로드 실행 전에 production archive를 재확인해
  superseded면 중단"하는 안전장치를 `scripts/render_youtube_short.py` 계열에
  추가하는 것을 제안한다 — 지금은 ShortsScript 파일 존재만으로 렌더링을
  진행할 수 있으므로, 사람이 수동으로 old 것을 렌더링하지 않도록 주의해야
  한다(코드가 막아주지 않는다는 뜻, 19장에 남김).
- **Threads**: pending draft가 이미 있는 것이 가장 위험한 경우다 —
  `/threads` 검수 화면은 production archive의 review_status를 재확인하지
  않고 pending draft의 자체 status만 본다. 제안: `/threads` 승인 처리
  직전에 원본 production archive record를 조회해 `superseded_by`가 있으면
  경고를 표시하거나 승인을 차단하는 로직을 추가한다(이번 세션에서 구현 안
  함 — `threads_review.py`/`run_scout_dashboard.py`의 Threads 승인 경로를
  건드리지 않았다).

## 14. Dashboard 영향

`scripts/run_scout_dashboard.py`(3064줄)를 조사했다. `/media`,
`/media/generations`, `/publish-readiness` 3개 화면 모두 review_status
문자열을 그대로 표시하거나(`_MEDIA_REVIEW_STATUS_LABELS.get(record.review_status,
record.review_status)` — 매핑에 없는 값은 원문 그대로 폴백되므로 "superseded"
문자열이 그대로 보인다, 크래시 없음) `PublishAuditResult.status`를 표로
렌더링한다. 이번 세션은 **UI 코드를 전혀 수정하지 않았다**(작업 지시 14장
"정말 필요한 코드 변경이 아니라면 설계 문서에만 기록한다"를 따름) — 다음은
설계 제안뿐이다.

제안(구현 안 함):

- `_MEDIA_REVIEW_STATUS_LABELS`에 `"superseded": "대체됨"` 추가, `/media`
  필터 옵션(`_MEDIA_REVIEW_STATUS_OPTIONS`)에도 추가해 사람이 superseded
  레코드만 따로 볼 수 있게 한다.
- 레코드 상세 화면(`render_media_detail_html` 계열)에 "Superseded by:
  `<new_content_id>` (링크)" 배지를 추가한다 — `find_superseded_by_record()`
  같은 조회 함수 하나만 있으면 된다(단방향 필드이므로 구현이 단순, 6장).
- 새 레코드 쪽에는 역방향 배지("이전 버전 보기") — archive 전체를
  `superseded_by == 이 레코드의 content_id`로 필터링하면 구할 수 있다(추가
  저장 없이 조회만으로 가능, 6장에서 이미 검증한 성질).
- `/publish-readiness` 요약에 SUPERSEDED 카운트 줄 추가(이미 markdown
  보고서 레벨에서는 8장에서 구현됨 — HTML Dashboard 쪽 렌더링 함수는 아직
  안 건드림).

## 15. Synthetic Simulation 결과

11장(작업 지시 11장)이 요구한 시나리오를 실제 데이터를 **읽기만 해서** tmp
사본에 재현했다. 스크립트는 세션 스크래치패드에만 남겼다(저장소에는
포함하지 않음 — 절차는 `tests/test_media_superseded_lifecycle.py`에 재현
가능한 형태로 고정했다).

```
real production archive record count: 18
new candidate review_status (as stored in regen file): unreviewed

=== (가정: 사람이 정정본을 승인하고 promotion했다고 시뮬레이션) ===
tmp production archive record count after simulated promotion: 19

=== plan_supersede() 결과 ===
old -> superseded superseded_by= content-afc6060bc1957867

=== AFTER supersede (tmp만) ===
total records: 19
content-5971ed5204437cdd: superseded superseded_by= content-afc6060bc1957867
content-afc6060bc1957867: approved

=== Publish Readiness 분류(tmp archive + 실제 KNOWLEDGE/이력을 읽기 전용 입력으로) ===
OLD status: SUPERSEDED ('정정본으로 대체됨(superseded_by=content-afc6060bc1957867) - 더 이상 활성 게시 후보가 아님',)
NEW status: NEEDS_HUMAN_REVIEW ('금융/부동산/대출 등 민감 콘텐츠 - 게시 전 사람의 최종 확인 필요',)

full summary over tmp archive (19 records): {'READY': 9, 'NEEDS_HUMAN_REVIEW': 7, 'BLOCKED': 2, 'ALREADY_PUBLISHED': 0, 'SUPERSEDED': 1, 'ERROR': 0}
```

작업 지시 11장이 예상한 결과와 정확히 일치한다: OLD는 활성 후보에서
제외됐고(SUPERSEDED), NEW는 `knowledge-scout-b28b782b2a33`의 category가
여전히 "금융"이므로(이번 세션도 category를 바꾸지 않았다) READY가 아니라
NEEDS_HUMAN_REVIEW가 됐다 — 안전장치가 그대로 작동한다는 뜻이다.
NEEDS_HUMAN_REVIEW 총 카운트는 supersede 전후로 7건 그대로다(OLD가 그
버킷에서 빠지고 NEW가 그 자리를 채웠다) — 이는 "옛 레코드를 제외하고 새
레코드를 정상적으로 후보에 편입시킨다"는 목표가 정확히 구현됐다는 추가
확인이다.

이 시뮬레이션이 쓴 파일은 세션 스크래치패드의 tmp 파일 2개뿐이다 — 실제
`data/tak_media_archive.json`, `data/tak_brain_knowledge.json`,
`data/tak_threads_pending.json`, `data/threads_publish_log.json`,
`data/tak_media_archive_6-05_b28b782b2a33_regeneration.json`은 전부
`load_archive()`/`load_knowledge_records()`/`load_pending()`으로 **읽기만**
했다.

## 16. 테스트 결과

신규 파일 **`tests/test_media_superseded_lifecycle.py`**(25개 테스트, 8개
클래스). 전부 synthetic fixture 또는 `tempfile`만 쓰고, 실제 데이터 파일
경로를 전혀 참조하지 않는다(`test_critical_content_replacement_audit.py`와
동일한 관례).

```
$ python -m pytest tests/test_media_superseded_lifecycle.py -v
...
25 passed in 0.20s
```

커버리지:

- 데이터 모델 정합성(6개): superseded가 REVIEW_STATUSES에 있음, approved
  에서만 도달 가능, 종결 상태(전이 없음), superseded_by 없이 superseded 불가,
  superseded_by 있는데 approved인 것 불가, 자기 자신 참조 불가
- Legacy 호환성(2개): `superseded_by` 키 없는 기존 레코드 파싱, round-trip 보존
- `plan_supersede()` 정상 경로(3개): CASE 3(대체 성공), 파일에는 old
  레코드만 갱신됨, **연쇄 supersede(A→B→C)**가 안전하게 동작함
- `plan_supersede()` 거부 경로(10개): CASE 1/2/4/5/6/7, platform 불일치,
  old가 approved가 아닌 경우, **이미 superseded된 것을 다시 supersede하는
  것 거부**
- Publish Readiness 연동(2개): superseded가 활성 후보에서 제외됨,
  **ALREADY_PUBLISHED가 SUPERSEDED보다 우선함**
- Downstream artifact 보존(1개): supersede가 publish history 파일을 전혀
  건드리지 않음(바이트/mtime 동일)

이미 `tests/test_media_versioning_and_promotion.py`(generation pool
보존/승격 게이팅), `tests/test_media_dashboard.py`(approved 콘텐츠 edit/
dismiss 버튼 없음), `tests/test_critical_content_replacement_audit.py`(정정
promotion의 additive 특성, content_id 충돌 위험, publish history gap)가
다루는 내용은 다시 만들지 않았다.

최종 전체 테스트:

```
$ python -m pytest -q
1033 passed, 68 subtests passed in 147.81s, 0 failed
```

(1008 baseline + 25 신규 = 1033. subtests 수 68은 그대로 — 신규 테스트가
`subTest`를 쓰지 않아 예상과 일치.) 기존 미커밋 변경으로 인한 실패는 없었다.

## 17. 실제 데이터 무결성

작업 전/후 SHA256:

```
                                   작업 전                                ==  작업 후
data/tak_media_archive.json      ebe1249fe36c3fe681660c3659d2199f5ecd4f6949b7890479fac9a4e8ea8d33   ==  (동일)
data/tak_brain_knowledge.json    e2ad1d39fa254ceaad4fb646124cb3e9b0b8e591ea688c1e0836fa1b6f706a31   ==  (동일)
data/tak_threads_pending.json    d122a0b68c093fb0e894251e60d5d987b40d9a268cd9b44522c4385bf5cabf72   ==  (동일)
data/threads_publish_log.json    d89074291327bc759d5416531c6cc6fb9a8cad0c5fcb6e8dc32660535d995c68   ==  (동일)
```

4개 파일 전부 세션 시작 시점과 바이트 단위로 완전히 동일하다.

실제 데이터로 audit 스크립트를 재실행해 6-16과 완전히 같은 결과가 나오는지
확인했다(코드에 SUPERSEDED 분류를 추가했지만, 실제 레코드 중
`superseded_by`가 채워진 것이 하나도 없으므로 결과가 바뀔 이유가 없다 —
아래 결과가 이를 실증한다):

```
$ python3 scripts/audit_publish_candidates.py
전체 Production 콘텐츠: 18
게시 가능(READY): 9
사람 검토 필요(NEEDS_HUMAN_REVIEW): 7
게시 차단(BLOCKED): 2
이미 게시됨(ALREADY_PUBLISHED): 0
정정본으로 대체됨(SUPERSEDED): 0   <- 신규 항목, 항상 0(실제 데이터엔 superseded 레코드가 없음)
오류(ERROR): 0
```

6-16의 결과(READY 9/NEEDS_HUMAN_REVIEW 7/BLOCKED 2/ALREADY_PUBLISHED
0/ERROR 0)와 **완전히 동일**하다.

```
$ python3 scripts/audit_threads_publish_consistency.py
전체 대상 content_id: 11
CONSISTENT: 1
PENDING_WITHOUT_PUBLISH_LOG: 4
ORPHAN: 6
DUPLICATE: 0
```

이 역시 6-16과 **완전히 동일**하다(이 스크립트는 이번 세션에서 아예 수정하지
않았다).

## 18. 실제 구현 여부

작업 지시 16장의 CASE A/B 기준으로 판단했다.

**데이터 모델 + 핵심 워크플로우 로직 → CASE A(최소 구현)를 채택했다.**
근거:

- `MediaArchiveRecord`에 필드 1개(`superseded_by`, 기본값 `None`)와
  `REVIEW_STATUSES` enum에 값 1개를 추가하는 것으로 끝난다 — 이미
  `generation_id` 도입(6-06) 때 검증된 것과 동일한 backward-compatible
  패턴이라 위험이 낮다.
- 실제 데이터 마이그레이션이 불필요함을 7장/17장에서 실증했다.
- 새 워크플로우(`scripts/supersede_media_record.py`)는 기존
  `promote_media_generation.py`의 dry-run/execute/명시적 경로 요구 관례를
  그대로 재사용했고, 새 레코드를 전혀 건드리지 않아(6장 B안) 원자성이
  단순하다(10장).
- `content_engine/publish_audit.py`의 변경은 기존 5개 상태의 판정 로직을
  전혀 바꾸지 않고 새 상태 1개를 삽입만 했다 — 17장에서 실제 데이터로 그
  안전성을 재확인했다.

**Dashboard UI → CASE B(설계만, 구현하지 않음)를 채택했다.** 근거: 작업
지시 14장이 "정말 필요한 코드 변경이 아니라면 설계 문서에만 기록"하라고
명시했고, `run_scout_dashboard.py`는 3064줄짜리 단일 파일로 HTML
렌더링/HTTP 핸들러/필터 로직이 밀접하게 얽혀 있어 실제 운영 화면(배지,
필터, 승인 라우트)을 건드리는 것은 이번 세션이 다룬 "핵심 lifecycle이
안전한가"라는 질문보다 훨씬 큰 blast radius를 가진다. 14장에 구체적인 제안을
남겼다.

**`promote_media_generation.py` 자체는 변경하지 않았다** — supersede는 이미
승격된 레코드를 대상으로 동작하는 완전히 독립된 후속 단계(9장)로 설계했기
때문에, promotion 코드를 건드릴 이유가 없었다.

## 19. 남은 사람 결정사항

Claude가 임의로 결정하면 안 되는 사항과, 이번 세션이 설계/코드 수준에서
이미 답을 낸 사항을 명확히 구분한다.

**사람이 반드시 결정해야 하는 것(정책/운영 판단):**

1. **`content-5971ed5204437cdd`(및 형제 6건)를 실제로 supersede할지, 그리고
   언제.** 이번 세션은 안전한 구조가 존재함을 검증했을 뿐, 실제 콘텐츠는
   전혀 건드리지 않았다. 사람이 정정본(`content-afc6060bc1957867`)을
   Dashboard에서 실제로 읽고 승인한 뒤, `promote_media_generation.py` →
   `scripts/supersede_media_record.py` 순서로 실행할지 결정해야 한다.
2. **shorts 2건/threads 4건 형제도 함께 정정할지.** 6-16 5장에 따르면 이
   6건은 blog와 달리 가시적 오염이 없다 — "오염이 없는데도 굳이 정정본으로
   교체할 필요가 있는가"는 콘텐츠 품질 판단이지 코드가 결정할 사항이
   아니다.
3. **CASE 7 정책(source_url이 다르면 무조건 거부)을 유지할지.** 9장에서
   보수적으로 결정했지만, 실제 운영에서 "같은 knowledge, 다른 source"의
   정당한 정정 사례가 나오면 재검토가 필요하다.
4. **13장의 downstream 정책 제안(Blog Pack 자동 제외, Shorts 렌더링 전
   재확인, Threads 승인 차단)을 실제로 구현할지.** 설계만 했고 코드는
   전혀 바꾸지 않았다 — 특히 Threads pending draft가 이미 존재하는 채로
   old가 superseded되는 경우, 아무 코드도 그 draft의 승인을 막지 않는다는
   것이 현재 상태다.
5. **11장의 content_id 사각지대(정책 A/B/C/D)를 어느 수준까지 강화할지.**
   D가 가장 안전하지만 구조 변경 범위가 크다.
6. **14장의 Dashboard UI 제안(배지/필터/상세 화면 링크)을 구현할지, 어떤
   우선순위로.**
7. **11장에서 새로 발견한, content_id가 같을 때 promotion이 이미 approved인
   레코드를 흔적 없이 덮어쓰는 기존 사각지대**를 이번 세션 범위로 볼지, 별도
   세션으로 다룰지.

**이번 세션이 이미 코드/테스트로 확정한 것(재검토 없이 재사용 가능):**

- SUPERSEDED는 review_status의 4번째 값이고, approved에서만 도달 가능하며
  종결 상태다(5장).
- `superseded_by` 단방향 필드 모델(B안, 6장)과 그 근거.
- `plan_supersede()`/`execute_supersede()`의 10가지 CASE 검증 로직(9~10장).
- SUPERSEDED가 Publish Readiness에서 별도 분류로 취급되고, ALREADY_PUBLISHED가
  항상 우선한다는 것(8장).
- 기존 5개 publish readiness 상태의 판정 로직과 실제 데이터 결과는 전혀
  바뀌지 않았다는 것(17장, SHA256 + audit 재실행으로 이중 확인).

## 20. 다음 단계

1. (사람 결정 후) `content-afc6060bc1957867`를 Dashboard에서 실제로 검토/
   승인 → `promote_media_generation.py --execute`로 production archive에
   추가 → `scripts/supersede_media_record.py --execute`로
   `content-5971ed5204437cdd`를 superseded 표시. 이 순서 자체가 이번
   세션이 검증한 안전한 절차다.
2. shorts/threads 형제 6건에 대한 사람의 정정 필요성 판단(19장 2번).
3. 13장 downstream 정책 중 우선순위가 가장 높은 것(Threads 승인 차단 —
   가장 위험도가 높음)부터 별도 세션에서 구현 여부 결정.
4. 14장 Dashboard UI 최소 배지("대체됨"/"Superseded by") 구현 여부 결정 —
   구현하면 사람이 CLI 없이도 supersede 상태를 볼 수 있다.
5. 11장 content_id 사각지대 강화(정책 D) 여부와, 이번 세션이 새로 발견한
   "같은 content_id 덮어쓰기" 사각지대(11장 마지막 문단)의 처리 방침 결정.
