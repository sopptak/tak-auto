# TAK AUTO 6-09 — Batch Promotion 운영화 + 실제 Production 반영 준비

## 1. 작업 목적

6-08까지 다음 구조가 완성됐다.

```
KNOWLEDGE → Generation Pool → /media/generations → Human Review
  → review_status=approved → Promotion Gate → Production Archive
```

단, `scripts/promote_media_generation.py`는 `(content_id, generation_id)`
**1건씩만** 처리했다. 실제 대상 generation(`knowledge-scout-6d1d0e2fa762`,
`gen-20260920T033856-6e8d98fb`)은 9건이므로, 사람이 승인한 뒤 9번 CLI를 따로
실행해야 하는 번거로움이 있었다(6-08 보고서 18-3).

이번 6-09의 목표는 사람이 승인한 여러 MEDIA를 **한 번에 안전하게**
promotion할 수 있는 운영 도구(batch promotion)를 완성하는 것이다 — 단,
**AI가 콘텐츠 승인 여부를 임의로 결정하지 않는다는 원칙**은 절대 깨지 않는다.

```
Generation Pool → Human Review → approved → Batch Dry Run
  → 사람이 결과 확인 → Batch Execute → Production Archive
```

이번 6-09에서는 실제 Batch Execute를 real production archive에 수행하지
않는다 — 실제 9건은 여전히 `review_status=unreviewed`이고, 이 작업은 그
상태를 바꾸지 않는다(1장 절대 원칙).

## 2. 작업 시작 상태

```
$ git branch --show-current
main

$ git fetch origin   # (출력 없음, 최신)
$ git log origin/main..HEAD --oneline   # (출력 없음, 앞서가는 커밋 없음)
```

`git status --short`(작업 시작 시점 전체):

```
 M .gitignore
 M content_engine/__init__.py
 M content_engine/generator.py
 M content_engine/llm_provider.py
 M content_engine/rewrite.py
 M data/tak_brain_knowledge.json
 M tests/test_content_engine.py
 M tests/test_media_batch.py
?? (다수의 기존 untracked 문서/스크립트 — 이번 작업과 무관, 손대지 않음)
?? data/tak_media_archive.json
```

6-08과 달리 이번에는 `scripts/run_scout_dashboard.py`와
`tests/test_second_knowledge_correction_and_generation_pool.py`가 이미 깨끗한
상태(HEAD와 일치)였다 — 6-08이 정상적으로 커밋/푸시됐음을 재확인했다.

`.gitignore`, `content_engine/*`, `data/tak_brain_knowledge.json`의 나머지
16개 레코드, `tests/test_content_engine.py`, `tests/test_media_batch.py`,
`data/tak_media_archive.json`, 기타 untracked 문서/스크립트는 이번 작업과
무관한 다른 세션의 변경이므로 전혀 건드리지 않았다(`git reset --hard`,
`git clean -fd`, `git checkout -- .`, `git add .`, `git add -A` 전부 사용하지
않음).

## 3. 6-08 baseline 재확인

```
881 passed, 68 subtests passed in 141.35s
```

6-08 보고서 최종 숫자와 정확히 일치한다. 실제 대상 generation도 재확인했다.

```python
records = load_archive("data/tak_media_generation_6-07_knowledge-scout-6d1d0e2fa762.json")
len(records) == 9  # True
[r.knowledge_id for r in records] == ["knowledge-scout-6d1d0e2fa762"] * 9
[r.generation_id for r in records] == ["gen-20260920T033856-6e8d98fb"] * 9
[r.generation_status for r in records] == ["valid"] * 9
[r.review_status for r in records] == ["unreviewed"] * 9  # 6-08 종료 시점과 동일 - 아직 아무도 승인하지 않음
```

`scripts/run_scout_dashboard.py`, `scripts/promote_media_generation.py`,
`tests/test_generation_review_and_promotion.py`,
`docs/6-08_generation_review_and_promotion.md`를 전부 다시 읽었다. 특히
`scripts/promote_media_generation.py`의 기존 설계 3가지 조건
(`(content_id, generation_id)` 존재, `generation_status=="valid"`,
`review_status=="approved"`)과 `--execute` 없는 기본 dry-run, idempotency
(같은 content_id·generation_id면 재실행해도 아무것도 쓰지 않음)를 정확히
이해한 뒤, 이 정책을 절대 바꾸지 않고 그 위에 batch 모드를 추가하기로
했다(4장).

## 4. Batch Promotion 설계

`scripts/promote_media_generation.py`에 **새 CLI를 만들지 않고 기존
스크립트에 batch 옵션을 추가**했다(4장 지시: 기존 CLI 호환성 유지).

- 기존 단건 모드: `--content-id`를 주면 6-06 때와 **완전히 동일하게** 동작한다
  (`plan_promotion()` 함수 자체를 건드리지 않았다 - 시그니처/로직 무변경).
- 신규 batch 모드: `--content-id`를 **생략**하고 `--generation-id`만 주면,
  그 generation_id를 가진 generation pool의 모든 record를 조회해 조건을
  만족하는 것만 promotion 대상으로 삼는다(`plan_batch_promotion()`, 새 함수).

이렇게 "`--content-id` 유무로 모드를 나누는" 설계를 택한 이유: 이미 필수
인자였던 `--content-id`를 선택 인자로 낮추는 것만으로 기존 커맨드라인이
100% 그대로 동작하고(생략하지 않았으므로), 새 동작을 위한 별도 서브커맨드나
플래그(`--batch` 등)를 배우지 않아도 자연스럽게 확장된다.

새로 추가한 데이터 구조:

```python
@dataclass(frozen=True)
class BatchPromotionItem:
    record: MediaArchiveRecord
    action: str   # "promote" | "already_promoted" | "skip"
    reason: str   # 예: "approved+valid", "review_status=unreviewed (아직 검토 전)"
```

`plan_batch_promotion(generation_archive_path, production_archive_path,
generation_id)`이 순수 조회 함수다 - 파일을 쓰지 않는다. `generation_id`를
가진 record가 generation pool에 하나도 없으면 `PromotionError`를 던진다
(9장 M).

## 5. CLI 사용법

**단건 promotion (6-06, 변경 없음)**:

```
python3 scripts/promote_media_generation.py \
  --archive data/tak_media_generation_6-07_knowledge-scout-6d1d0e2fa762.json \
  --production-archive data/tak_media_archive.json \
  --content-id content-80a05485e895abf4 \
  --generation-id gen-20260920T033856-6e8d98fb
```

**Batch promotion (6-09, 신규)**:

```
python3 scripts/promote_media_generation.py \
  --archive data/tak_media_generation_6-07_knowledge-scout-6d1d0e2fa762.json \
  --production-archive data/tak_media_archive.json \
  --generation-id gen-20260920T033856-6e8d98fb
```

(`--content-id`를 생략하면 batch 모드.) 기본은 dry-run이며, 결과를 사람이
확인한 뒤 `--execute`를 추가해야 실제로 쓴다 — 단건/batch 모두 동일한 관례.

**6-09 신규 안전장치**: batch 모드는 `--production-archive`를 **반드시
명시적으로** 줘야 한다(dry-run 포함). 생략하면 다음과 같이 즉시 오류로
끝난다(파일을 열지도 않는다).

```
$ python3 scripts/promote_media_generation.py --archive <pool> --generation-id <gid>
오류: batch promotion(--content-id 생략)은 --production-archive를 명시적으로
지정해야 합니다 - 실수로 실제 production archive를 건드리는 것을 막기 위한
안전장치입니다(docs/6-09_batch_promotion_and_production_readiness.md 참고).
$ echo $?
1
```

반면 단건 모드는 `--production-archive`를 생략하면 6-06 때와 동일하게
`data/tak_media_archive.json`(모듈 상수 `DEFAULT_PRODUCTION_ARCHIVE_PATH`)로
자동 폴백한다 - **이 기본값 동작 자체는 바꾸지 않았다**(하위 호환,
`SingleModeRegressionTests` 테스트로 고정).

## 6. Partial approval 정책

9장의 A~E 요구사항을 그대로 만족한다 - **"generation 전체가 승인돼야
promotion 가능"이라는 정책으로 바꾸지 않았다.** record 단위로 독립적으로
판정한다.

| 상태 | 판정 | 사유(reason) 예시 |
|---|---|---|
| `generation_status != "valid"` (rejected/error) | `skip` | `generation_status=rejected (검증 실패)` |
| `review_status == "unreviewed"` | `skip` | `review_status=unreviewed (아직 검토 전)` |
| `review_status == "dismissed"` | `skip` | `review_status=dismissed (사람이 보류함)` |
| `generation_status=="valid"` + `review_status=="approved"` + production에 아직 없거나 다른 generation | `promote` | `approved+valid` |
| `generation_status=="valid"` + `review_status=="approved"` + production이 이미 이 generation | `already_promoted` | `이미 승격됨(변경 없음)` |

## 7. Dry-run 결과

`_print_batch_plan()`이 7장이 요구한 정보를 정확히 출력한다: generation_id,
knowledge_id, 총 record 수, approved/unreviewed/dismissed/rejected/error 수,
promotion 예정 수, skip 수, 그리고 각 content_id별
platform/generation_status/review_status/promotion action.

실제 데이터로 재현한 dry-run(읽기 전용, `/tmp`의 임시 production archive
경로만 지정 - 파일 자체는 생성되지 않았다):

```
$ python3 scripts/promote_media_generation.py \
    --archive data/tak_media_generation_6-07_knowledge-scout-6d1d0e2fa762.json \
    --production-archive /tmp/tak_media_archive_6-09_readonly_preview.json \
    --generation-id gen-20260920T033856-6e8d98fb

=== MEDIA Generation Batch Promotion [DRY-RUN (파일 변경 없음)] ===
generation_id:   gen-20260920T033856-6e8d98fb
knowledge_id:    knowledge-scout-6d1d0e2fa762
총 record:       9
  valid:         9
  rejected:      0
  error:         0
  approved:      0
  unreviewed:    9
  dismissed:     0
promotion 예정:  0건
이미 승격됨:      0건 (변경 없음, idempotent)
skip:            9건

  content-80a05485e895abf4  [blog]  ... -> SKIP (review_status=unreviewed (아직 검토 전))
  content-ec0c38b9a20c424c  [shorts]  ... -> SKIP (review_status=unreviewed (아직 검토 전))
  ... (9건 전부 동일하게 SKIP)

dry-run 완료. 실제로 반영하려면 --execute를 추가하세요.
```

명령 실행 전후로 `data/tak_media_generation_6-07_...json`과
`data/tak_media_archive.json`의 SHA-256 해시가 완전히 동일함을 확인했다
(8장 참고). `/tmp/tak_media_archive_6-09_readonly_preview.json` 파일 자체도
dry-run이라 생성되지 않았다.

## 8. Execute 테스트 결과

전부 합성 fixture + `tempfile.TemporaryDirectory()`에서만 실행했다(실제
`data/tak_media_archive.json`은 이 테스트들 어디에서도 열리지 않는다).

`tests/test_batch_promotion.py::BatchPromotionCliTests`:

- `test_batch_execute_writes_only_approved_records`: approved 1건 +
  unreviewed 1건 + dismissed 1건 중 **approved 1건만** production archive에
  기록됨을 확인.
- `test_batch_dry_run_does_not_touch_production_archive`: dry-run 후
  production archive 파일 자체가 생성되지 않음을 확인(`.exists() == False`).
- `test_batch_zero_promotable_records_is_not_an_error`: 전부 unreviewed일 때
  dry-run/execute 모두 `exit code 0`(오류 아님), execute도 파일을 만들지
  않음(9장 N 요구사항 그대로).
- `test_batch_without_explicit_production_archive_refuses_to_run`:
  `--production-archive` 없이 batch 모드 실행 시 `exit code 1`.
- `test_batch_nonexistent_generation_returns_clear_error`: 존재하지 않는
  `generation_id`는 `exit code 1`과 함께 명확한 오류 메시지.

## 9. Idempotency 결과

`test_batch_execute_twice_is_idempotent`: 같은 generation을 `--execute`로
두 번 실행해도 production archive에 레코드가 **정확히 1건**만 남고(중복
추가 없음), 두 번째 실행 출력에 `ALREADY PROMOTED`와 `promotion 대상이
없습니다`가 나타남을 확인했다. `plan_batch_promotion()` 내부에서 매
record마다 `find_active_record()`로 production의 현재 활성 레코드를 조회해
`generation_id`가 같으면 `already_promoted`로 분류하는 방식이므로,
**record 단위로도 idempotent**하다(일부만 이미 승격되고 나머지가
새로 승격되는 상황도 안전하게 처리된다 - 별도 테스트로 확인하지는
않았지만 로직상 record별 독립 판정이라 자명하다).

## 10. Dashboard 승인 현황

6-09 14~15장 요구사항대로 `/media/generations`의 각 generation 그룹 헤더에
검수 현황 요약을 추가했다(production archive는 전혀 읽지 않는, 순수
generation pool 집계).

```python
def summarize_generation_reviews(records) -> dict:
    # {"total": 9, "valid": 9, "rejected": 0, "error": 0,
    #  "approved": 0, "unreviewed": 9, "dismissed": 0}

def summarize_platform_approval(records) -> list[tuple[str, int, int]]:
    # [("blog", 0, 1), ("shorts", 0, 3), ("threads", 0, 5)]
```

실제 렌더링 결과(합성 fixture로 재현, 실제 9건 형태와 동일):

```
총 9 · Valid 9 · Approved 0 · Unreviewed 9 · Dismissed 0
BLOG 0/1 · SHORTS 0/3 · THREADS 0/5
```

이 두 함수는 시그니처에 `records`만 받는다 - production archive 경로를
아예 받을 수 없으므로 구조적으로 production을 참조할 수 없다
(`test_summary_never_touches_production_archive`로 고정).

**Dashboard 승인 버튼과 promotion의 분리(12장)**: `_generation_group_html()`의
"이 generation 전체 승인" 폼은 여전히
`/media/generations/generation/<id>/approve-all`만 가리킨다(6-08과 동일) -
이번에 batch **promotion**과 연결하는 버튼/링크는 추가하지 않았다. 승인은
`review_status`만 바꾸고, batch promotion은 사람이 CLI로 별도 실행해야
한다는 원칙을 그대로 유지했다.

## 11. 실제 Production promotion 여부

**실행하지 않았다.** 실제 9건(`knowledge-scout-6d1d0e2fa762`,
`gen-20260920T033856-6e8d98fb`)은 이 세션 시작 전과 마찬가지로 전부
`review_status="unreviewed"`다 - 이번 세션은 이 값을 **단 1건도** 바꾸지
않았다(10장 절대 원칙). 근거:

```
$ sha256sum data/tak_media_generation_6-07_knowledge-scout-6d1d0e2fa762.json
(작업 시작 전/후 동일)
ed6aa24461f40880489a9e88107cc253036316a2ef95dd1911f1af5a69676e9e

$ sha256sum data/tak_media_archive.json
(작업 시작 전/후 동일)
823ba83930116cb3bf0cf9d46bd3876c7a833c58f5871a380a5de0cad3dd1662
```

사람이 `/media/generations`에서 9건을 직접 읽고 승인한 뒤, 13장의 명령으로
직접 promotion을 실행해야 한다.

## 12. Production Archive 보호

- 이번 세션의 모든 신규 테스트(`tests/test_batch_promotion.py`)는
  `tempfile.TemporaryDirectory()` 안의 임시 파일만 사용한다.
- 실제 `data/tak_media_archive.json`, 실제 generation pool 파일
  (`data/tak_media_generation_6-07_...json`)은 GET/dry-run 조회로만
  건드렸고, 두 파일의 SHA-256 해시가 작업 시작 전/후로 완전히 동일함을
  11장에서 확인했다.
- Batch 모드의 `--production-archive` 명시 필수 안전장치(5장)가 "기본값으로
  실제 production을 덮어쓴다"는 사고를 구조적으로 막는다.
- Dashboard의 승인/전체승인 액션(6-08에서 이미 검증됨)은 이번에도 변경하지
  않았다 - production archive 경로를 인자로 받지 않는 함수만 그대로 쓴다.

## 13. Production Promotion 실행 준비 명령

사람이 실제로 9건을 검토해 승인한 뒤 사용할 정확한 명령이다.

**1단계 - 사람이 `/media/generations`에서 9건을 읽고 승인** (개별 승인 또는
"이 generation 전체 승인" 버튼).

**2단계 - dry-run으로 결과 미리 확인**:

```
python3 scripts/promote_media_generation.py \
  --archive data/tak_media_generation_6-07_knowledge-scout-6d1d0e2fa762.json \
  --production-archive data/tak_media_archive.json \
  --generation-id gen-20260920T033856-6e8d98fb
```

**3단계 - 출력을 사람이 확인**: "promotion 예정" 수가 승인한 건수와
일치하는지, "skip" 사유가 예상과 맞는지 확인한다.

**4단계 - 실제 반영**:

```
python3 scripts/promote_media_generation.py \
  --archive data/tak_media_generation_6-07_knowledge-scout-6d1d0e2fa762.json \
  --production-archive data/tak_media_archive.json \
  --generation-id gen-20260920T033856-6e8d98fb \
  --execute
```

이번 6-09에서는 이 4단계 명령을 **실행하지 않았다** - 사람의 승인 결정을
기다린다.

## 14. Generation Pool 편집 기능 (이번에 추가하지 않음)

11장 지시대로 `/media`의 기존 편집 구조(`handle_media_edit_submission()`,
`scripts/run_scout_dashboard.py:832`)를 다시 읽었다. 이 함수는
`edited_title`/`edited_body`만 바꾸고 `review_status`를 `"unreviewed"`로
되돌리는 패턴을 쓴다(수정하면 다시 검토해야 한다는 안전장치) -
`MediaArchiveRecord`에 이미 `edited_title`/`edited_body` 필드가 있고,
`final_title`/`final_body` 프로퍼티가 이 값을 최우선으로 쓰므로,
`promote_media_generation.py`는 코드 변경 없이도 이미 이 필드를 그대로
승격한다(구조적으로 지원됨).

**그럼에도 이번에 추가하지 않기로 판단했다.** 이유:

1. 이번 6-09의 최우선순위는 batch promotion이었고(11장 지시: "이번 작업의
   최우선순위는 Batch Promotion이다"), 편집 기능까지 추가하면 새 POST
   라우트(`/media/generations/record/.../edit`) + 폼 렌더링 + 검증 로직을
   또 만들어야 해서 범위가 커진다.
2. `/media`의 `handle_media_edit_submission()`을 그대로 재사용하려면
   production archive 경로 대신 generation pool 경로를 받도록 시그니처를
   바꾸거나 공통 helper로 추출해야 하는데, 이 리팩터링 자체가 이번 batch
   promotion 작업과 무관한 별도 변경이다.
3. 현재 실제 9건은 재작성(rewritten_*) 텍스트를 그대로 승인/보류하는
   시나리오이고, 사람이 이번 세션에서 실제로 편집을 요청하지 않았다.

**다음에 필요해지면**: `handle_media_edit_submission()`의 로직(제목/본문 받기
→ `replace(record, edited_title=..., edited_body=..., review_status="unreviewed")`
→ 저장)을 "어느 archive에 쓸지"만 매개변수화한 공통 함수로 추출하고,
generation pool 쪽은 `upsert_generation_archive()`를, production 쪽은
`upsert_archive()`를 넘기면 될 것으로 예상된다(19장에 이월).

## 15. 테스트 결과

신규 파일 **`tests/test_batch_promotion.py`** (19개 테스트, 4개 클래스).

- `BatchPromotionPlanningTests` (8): CASE A/B/C/D/E + generation 간 미혼입
  (K) + legacy(`generation_id=None`) record와 충돌 없음(L) + 존재하지 않는
  generation 오류(M).
- `BatchPromotionCliTests` (6): dry-run이 파일을 안 만듦, execute가 approved
  record만 씀, 두 번 execute해도 idempotent, `--production-archive` 없으면
  거부, promotion 대상 0건이어도 오류 아님(N), 존재하지 않는 generation 오류.
- `SingleModeRegressionTests` (2): 명시적 `--production-archive`로 단건
  promotion 정상 동작, 미명시 시 기존 기본 경로로 폴백(하위 호환, 실제
  파일은 건드리지 않고 상수를 patch해서 검증).
- `DashboardReviewSummaryTests` (3): 실제 9건과 같은 모양의 요약이 정확한
  카운트를 내는지, platform별 승인 카운트, 두 함수가 production archive를
  구조적으로 참조할 수 없는지.

기존 `tests/test_generation_review_and_promotion.py`(6-08, 23개),
`tests/test_media_versioning_and_promotion.py`(6-06),
`tests/test_second_knowledge_correction_and_generation_pool.py`(6-07)는
전부 변경 없이 그대로 통과했다 - 이번 변경이 기존 단건 promotion 동작이나
승인/보류 라우트를 깨지 않았다는 회귀 확인이다.

전체 테스트 실행(최종):

```
900 passed, 68 subtests passed in 142.14s (0:02:22)
```

881(6-08 baseline) + 19(이번 신규 `test_batch_promotion.py`) = 900.
**0 failed.**

## 16. Git 변경 파일

이번 세션이 실제로 수정/추가한 파일만(`git add .`/`git add -A` 사용하지
않음):

```
M scripts/promote_media_generation.py   (batch promotion 추가, 단건 모드 로직 무변경)
M scripts/run_scout_dashboard.py        (검수 현황 요약 함수 2개 + 렌더링 추가)
A tests/test_batch_promotion.py         (신규, 19개 테스트)
A docs/6-09_batch_promotion_and_production_readiness.md  (이 보고서)
```

다음은 이번 커밋에 포함하지 않았다(다른 세션의 기존 미커밋 변경, 무관):

```
.gitignore
content_engine/__init__.py
content_engine/generator.py
content_engine/llm_provider.py
content_engine/rewrite.py
data/tak_brain_knowledge.json  (나머지 16개 미커밋 레코드 - 이번 세션은 이 파일을 전혀 열지 않았다)
tests/test_content_engine.py
tests/test_media_batch.py
data/tak_media_archive.json    (untracked, 읽기만 함)
기타 untracked 문서/스크립트
```

## 17. Commit

## 18. Push

## 19. 최종 git status

(15~17장의 실제 커밋/푸시/최종 상태는 아래에 기록한다.)

## 20. 보안 검증

- `TAK_MEDIA_LLM_API_KEY`, `TAK_MEDIA_LLM_ENDPOINT`, `YOUTUBE_REFRESH_TOKEN`,
  `YOUTUBE_CLIENT_SECRET`, access/refresh token, password, cookie, session
  secret 등 어떤 값도 로그/코드/테스트/보고서에 출력하지 않았다 - 이번
  6-09는 이 환경변수들을 참조하는 코드를 전혀 건드리지 않았고, LLM을 전혀
  호출하지 않았다(16장 지시).
- 신규 테스트는 전부 `tempfile.TemporaryDirectory()`의 합성 fixture만
  사용한다.
- 커밋 대상 4개 파일에 시크릿이 없음을 `git diff --cached`로 직접 확인했다.

## 21. 남은 문제

1. Generation Pool 편집 기능은 여전히 없다(14장에서 이번에 추가하지 않기로
   결정한 이유 기록).
2. `plan_batch_promotion()`의 idempotency는 "record 단위 독립 판정" 로직상
   자명하지만, "일부는 이미 승격되고 나머지는 새로 승격되는" 혼합
   시나리오를 별도 테스트로 직접 재현하지는 않았다(9장에서 언급).
3. Dashboard에 batch promotion **미리보기**(dry-run 결과를 화면에 표시)는
   추가하지 않았다 - CLI 출력으로 충분하다고 판단했다(12장 원칙: 승인
   화면에서 promotion 자체를 실행하지 않으므로, 미리보기까지 화면에 넣으면
   "승인 화면이 promotion을 안내"하는 형태가 되어 경계가 흐려질 수 있다고
   보수적으로 판단).
4. 실제 9건의 production promotion은 여전히 사람의 결정을 기다린다(11장).
5. RewriteValidator "경험" 오탐 이슈, 기존 오염된 production 9건은 이번에도
   손대지 않았다(6-05/6-06/6-07/6-08과 동일한 범위 원칙).

## 22. 다음 작업 제안

1. 사람이 `/media/generations`에서 실제 9건을 검토 → 승인 → 13장의 dry-run
   → execute 절차로 첫 실제 batch production promotion을 수행.
2. 14장에서 이월한 Generation Pool 편집 기능을 `handle_media_edit_submission()`
   공통화로 구현.
3. Dashboard에 batch dry-run 미리보기를 넣을지(21-3) 실제 운영 경험을 보고
   결정.
4. 여러 generation_id/여러 knowledge_id를 한 커맨드로 순회하는 "전체
   promotion" CLI(현재는 generation_id 1개씩) 필요성 검토.

## 23. 최종 상태 확인

```
KNOWLEDGE (knowledge-scout-6d1d0e2fa762)
  ↓
Generation Pool (gen-20260920T033856-6e8d98fb, 9건, 전부 valid/unreviewed - 변경 없음)
  ↓
/media/generations: 검수 현황 요약 표시(총/valid/approved/unreviewed/dismissed,
  platform별) - 이번 세션에서 추가
  ↓
Batch Promotion CLI: dry-run/execute/idempotency/partial approval 전부 임시
  archive로 실증 완료 - 이번 세션에서 추가
  ↓
Production Archive: 이번 세션 동안 완전히 그대로(해시 불변) - 실제 promotion
  미실행, 사람의 승인 결정 대기
```

전체 테스트: **900 passed, 68 subtests passed, 0 failed.**
