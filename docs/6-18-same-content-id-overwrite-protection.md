# 6-18 — 동일 content_id / 다른 generation_id 자동 overwrite 차단

## 1. 작업 목적

Generation Pool에서 승인(approved)된 새 generation을 Production Archive로
승격(promote)할 때, **같은 content_id를 가졌지만 generation_id가 다른** 기존
Production 레코드가 이미 있으면 그 레코드를 조용히 덮어쓰는 구조적 위험이
있었다. 6-17 보고서(11장 마지막 문단)가 이미 이 사각지대를 합성 데이터로
재현해 "고치지 않고 사람의 결정 사항으로 남긴다"고 기록했고, 이번 6-18은 그
결정 사항을 실제로 해결한다.

목표는 정확히 하나다.

> "Generation Pool의 새로운 생성물이 기존 Production Archive의 동일
> content_id를 조용히 덮어쓰는 것을 구조적으로 차단한다."

이번 단계는 **보호장치 구현 + 테스트 + 시뮬레이션까지만** 한다. 실제
Production Archive의 콘텐츠 교체(예: `content-afc6060bc1957867` 승격,
`content-5971ed5204437cdd` supersede)는 이번 세션에서 실행하지 않았다 -
사람의 결정 이후 별도 단계에서 진행한다.

## 2. 시작 baseline

- git branch: `main`
- HEAD: `8d7f60c02c52ca6589c3eb779fffac089dafa1c1` (6-17 커밋)
- origin/main: `8d7f60c02c52ca6589c3eb779fffac089dafa1c1` (완전히 동기화됨,
  `git fetch origin main` 확인)
- git status: 이번 세션 시작 전부터 존재하던 다수의 unrelated uncommitted
  변경/미추적 파일이 있었다(예: `content_engine/__init__.py`,
  `content_engine/generator.py`, `docs/5-*` 등 수십 개, `data/tak_media_archive.json`
  포함). 이번 작업은 이 파일들을 하나도 건드리지 않았고, commit도 이번
  세션이 실제로 수정한 파일만 선택적으로 포함한다(18장 참고).
- 전체 pytest baseline: **1033 passed, 68 subtests passed** (165.19s)
- Production Archive(`data/tak_media_archive.json`) record 수: **18건**
  - review_status: approved 16 / unreviewed 2
  - generation_status: valid 16 / rejected 2
  - legacy(generation_id 없음): 9건
- Generation Pool 파일: `data/tak_media_generation_6-07_knowledge-scout-6d1d0e2fa762.json`
  1개, 9건
- Publish Readiness 요약(`scripts/audit_publish_candidates.py --no-report`,
  파일 저장 없이 터미널 출력만 확인):

  | 상태 | 건수 |
  |---|---|
  | READY | 9 |
  | NEEDS_HUMAN_REVIEW | 7 |
  | BLOCKED | 2 |
  | ALREADY_PUBLISHED | 0 |
  | SUPERSEDED | 0 |
  | ERROR | 0 |
  | 합계 | 18 |

- 절대 건드리면 안 되는 content_id 확인(19장 금지 목록):
  `content-5971ed5204437cdd`는 Production Archive에 `review_status=approved`,
  `generation_status=valid`, `superseded_by=None`으로 존재(6-17이 남긴 상태
  그대로). `content-afc6060bc1957867`는 아직 Production Archive에 없음(6-17이
  기록한 대로 - 사람 승인 전).

## 3. 기존 문제 재현

`scripts/promote_media_generation.py`의 `plan_promotion()`을 그대로 호출해
재현했다(임시 파일만 사용, 실제 `data/` 파일은 전혀 열지 않음).

```
PRODUCTION(기존): content_id=content-X, generation_id=gen-old,
                  review_status=approved, generation_status=valid,
                  rewritten_title="옛 텍스트"
NEW GENERATION:   content_id=content-X, generation_id=gen-new,
                  review_status=approved, generation_status=valid,
                  rewritten_title="새 텍스트"

plan_promotion(pool, production, "content-X", "gen-new")
  -> 예외 없이 (candidate, current_active) 반환  <- 버그
upsert_archive(production, [candidate])
  -> production archive 레코드 수: 1건 (그대로)
  -> rewritten_title: "새 텍스트" (옛 텍스트가 흔적 없이 사라짐)
  -> generation_id: "gen-new" (gen-old였다는 사실이 파일 어디에도 남지 않음)
```

재현 결과: **버그 확인됨.** `plan_promotion()`은 `current_active`가 있고
generation_id가 다른 경우를 전혀 걸러내지 않고 그대로 반환했고, 그 뒤
`upsert_archive()`(content_id 단독 키 upsert, 5-27 설계 그대로)가 옛 레코드를
review_status·rewritten_title 등 전부 포함해 조용히 덮어썼다.

batch promotion(`plan_batch_promotion()`)도 동일한 근본 원인으로 취약했다:
`current_active.generation_id == generation_id`가 아니면 무조건
`action="promote"`로 분류했으므로, "신규 content_id"와 "충돌하는 기존
content_id"를 구분하지 못했다.

## 4. 문제 원인

- `upsert_archive()`(`content_engine/media_archive.py`)는 5-27 설계 그대로
  content_id 단독 키로 upsert한다 - 이 동작 자체는 정상이고, Dashboard의
  approve/dismiss/edit, `scripts/supersede_media_record.py`처럼 "같은
  content_id를 의도적으로 갱신"하는 다수의 정당한 호출부가 이 동작에
  의존한다(그래서 이번 수정은 `upsert_archive()`를 바꾸지 않았다 - 5장 참고).
- 문제는 그 한 단계 위인 `scripts/promote_media_generation.py`의
  `plan_promotion()`/`plan_batch_promotion()`에 있었다: candidate 자체의
  승인 게이팅(unreviewed/rejected 차단)은 있었지만, **"이 content_id에 이미
  다른 generation_id의 활성 레코드가 있는가"**를 검사하는 로직이 아예 없었다.
- `_print_plan()`의 dry-run 출력에는 "기존 production 활성 레코드가 이
  promotion으로 교체됩니다"라는 경고 문구가 있었지만, 이는 사람이 화면을
  직접 읽어야만 보이는 것이지 실행을 막지도, 데이터에 기록을 남기지도
  않았다(6-17 11장이 이미 지적한 정확히 그 문제).

## 5. 보호정책 (6-18 채택)

작업 지시 4장의 정책 A~E를 그대로 채택했다.

- **정책 A**: Production Archive에 동일 content_id가 이미 있으면 새
  generation을 단순 upsert하지 않는다 - "자동 overwrite 금지"가 기본.
- **정책 B**: 기존 record의 review_status(approved/published/superseded 등
  무엇이든)와 무관하게 자동 덮어쓰기를 허용하지 않는다.
- **정책 C**: 교체가 필요하면 명시적인 supersede 절차
  (`scripts/supersede_media_record.py`)만 사용한다.
- **정책 D**: 이번 단계에서 자동 supersede는 구현하지 않는다 - 충돌 시
  **BLOCK/ERROR**로 명확히 중단한다.
- **정책 E**: 동일 content_id + 동일 generation_id는 idempotent 성공을
  허용한다(기존 6-06/6-09 동작 그대로, 변경 없음).
- 본문/제목이 같아 보인다는 이유로 overwrite를 허용하는 "최적화"는 만들지
  않았다(7장 지시 그대로) - 검사는 오직 `(content_id, generation_id)` 비교
  1가지 기준만 쓴다.
- legacy record(`generation_id=None`)도 예외 없이 보호 대상이다(16장 지시).
- `--force` 같은 우회 CLI 옵션은 추가하지 않았다(8장 지시: 기본은 추가하지
  않는 방향을 우선하며, 4가지 안전 조건을 전부 충족하지 못하면 추가하지
  말 것 - 이번 단계에서는 그 조건을 검토할 필요조차 없었다. 왜냐하면 명시적
  대체 경로인 `scripts/supersede_media_record.py`가 이미 존재하기 때문이다).

## 6. 구현 파일

| 파일 | 변경 |
|---|---|
| `content_engine/media_archive.py` | `ArchiveConflictError` 예외 + `check_promotion_conflict()` 순수 함수 추가 (+39줄) |
| `scripts/promote_media_generation.py` | `PromotionConflictError` 추가, `plan_promotion()`/`plan_batch_promotion()`에 충돌 검사 연결, CLI 출력에 CONFLICT 표시, 더 이상 발생할 수 없는 "교체됨" 문구 제거 (+79줄/-11줄) |
| `tests/test_same_content_id_overwrite_protection.py` | 신규 테스트 29건 |
| `docs/6-18-same-content-id-overwrite-protection.md` | 이 보고서 |

`upsert_archive()` 자체, `scripts/supersede_media_record.py`,
`content_engine/publish_audit.py`는 전혀 수정하지 않았다(대규모 리팩터링
금지 지시 준수 - 5장/12장).

## 7. 변경 내용

### 7.1 `content_engine/media_archive.py`

```python
class ArchiveConflictError(MediaArchiveError):
    """production archive에 이미 존재하는 content_id를, generation_id가 다른
    레코드로 자동 upsert하려고 할 때 발생한다."""


def check_promotion_conflict(existing, candidate) -> None:
    if existing is None:
        return
    if existing.content_id != candidate.content_id:
        return
    if existing.generation_id == candidate.generation_id:
        return
    raise ArchiveConflictError(
        f"content_id={candidate.content_id!r}가 production archive에 이미 존재하며 "
        f"generation_id가 다릅니다(기존 generation_id={existing.generation_id!r}, "
        f"신규 generation_id={candidate.generation_id!r}, 기존 review_status="
        f"{existing.review_status!r}) - 자동 overwrite는 금지됩니다. ..."
    )
```

파일을 읽거나 쓰지 않는 순수 함수다 - `existing`은 호출부가 미리 조회해
넘긴다. `upsert_archive()` 안에서 호출하지 않는다(그 이유는 5장 참고).

### 7.2 `scripts/promote_media_generation.py`

- `PromotionConflictError(PromotionError)` 추가 - 기존 `except PromotionError`
  호출부가 그대로 잡아낸다(하위 호환).
- `plan_promotion()`: `current_active`를 조회한 직후
  `check_promotion_conflict()`를 호출하고, `ArchiveConflictError`를
  `PromotionConflictError`로 감싸 던진다. 이 함수는 파일을 쓰지 않으므로,
  예외가 발생해도 production archive는 호출 전 상태 그대로다.
- `plan_batch_promotion()`: `BatchPromotionItem`에 `"conflict"` action과
  `old_generation_id` 필드를 추가했다. 기존 `current_active is not None and
  generation_id 같음 -> already_promoted / 아니면 -> promote` 이분법을,
  "같음 -> already_promoted / 있지만 다름 -> conflict / 없음 -> promote"
  삼분법으로 바꿨다 - `else` 분기 하나를 나눈 것 외에 다른 로직은 건드리지
  않았다.
- `_print_plan()`: `current_active`가 있으면서 generation_id가 다른 경우는
  이제 `plan_promotion()`이 먼저 예외를 던지므로 이 함수에 도달할 수 없다 -
  더 이상 도달 불가능해진 "교체됩니다" 안내 문구를 제거했다(죽은 코드를
  남기지 않기 위함).
- `_print_batch_plan()`: `conflict:` 건수 줄과, CONFLICT 레코드마다
  `content_id / old_generation_id / new_generation_id / result=CONFLICT /
  reason`을 명시적으로 출력하는 "CONFLICT 상세" 섹션을 추가했다(13장 요구
  형식).

## 8. Promotion 상태별 동작

| 상황 | 기존 record | 새 generation | 결과 |
|---|---|---|---|
| A | 없음 | valid+approved | PROMOTE |
| B | same content_id + same generation_id | valid+approved | IDEMPOTENT (변경 없음) |
| C | same content_id + different generation_id | valid+approved | **CONFLICT**(`PromotionConflictError`, 단건 CLI exit 1) |
| D | published(=approved, 실제 게시 이력 있음) existing | different generation_id | **CONFLICT** (E와 동일 경로 - review_status만으로 판단, publish history는 원래부터 이 스크립트가 참조하지 않는다) |
| E | superseded existing | different generation_id | **CONFLICT** (SUPERSEDED와 CONFLICT는 별개 개념 - superseded 레코드도 그 content_id 슬롯의 "마지막 확정 상태"이므로 자동 대체 금지. 12장 참고) |

candidate 자체의 기존 게이팅(unreviewed 차단, rejected/error 차단)은
conflict 검사보다 먼저 실행되며 전혀 바뀌지 않았다.

## 9. batch promotion 동작

같은 generation_id를 가진 여러 record를 한 번에 처리할 때:

```
content-A (신규 content_id)              -> PROMOTE
content-B (기존 production과 충돌)        -> CONFLICT (skip과 별도 카운트)
content-C (신규 content_id)              -> PROMOTE
```

- A/C는 정상적으로 promotion되고, B만 conflict로 분류되어 production archive
  변경에서 제외된다(하나의 충돌이 다른 정상 record를 막지 않는다, 11장
  지시).
- `--execute` 실행 시 exit code는 **0**을 유지했다(기존 관례: unreviewed/
  rejected로 인한 "skip"도 스크립트 실패로 취급하지 않았으므로, "정상적으로
  처리했지만 일부는 대기/충돌 상태"인 partial 결과를 동일하게 취급 - 예상치
  못한 transaction semantics 변경을 하지 않기 위함, 11장 지시). CONFLICT는
  `conflict:` 카운트 줄과 "=== CONFLICT 상세 ===" 섹션으로 눈에 띄게
  출력되므로 사람이 놓치기 어렵다.
- 단건(`--content-id`) 모드의 conflict는 기존 관례(다른 `PromotionError`와
  동일하게)대로 exit code **1**로 실패 처리한다 - 사람이 명시적으로 지정한
  대상 1건이 안전하지 않다는 뜻이므로 즉시 실패가 맞다고 판단했다.

## 10. 테스트 목록

`tests/test_same_content_id_overwrite_protection.py` (신규, 29건):

| 클래스 | 대응 요구사항 |
|---|---|
| `CaseANoExistingRecordPromotesNormallyTests` | A |
| `CaseBSameGenerationIdIsIdempotentTests` | B |
| `CaseCDConflictBlocksPromotionAndPreservesExistingTests` | C, D |
| `CaseEFGExistingRecordReviewStatusPolicyTests` | E, F, G |
| `CaseHICandidateGatingUnaffectedByConflictCheckTests` | H, I |
| `CaseJBatchPromotionIsolatesConflictFromNormalRecordsTests` | J |
| `CaseKLMFileImmutabilityAfterConflictTests` | K, L, M |
| `LegacyRecordIsNotExemptFromConflictProtectionTests` | 16장(legacy record 우회 금지) |
| `ExistingProductionArchiveReadOnlyRegressionTests` | 실제 production archive 18건 불변 확인(읽기 전용) |

N(기존 supersede lifecycle 테스트 전부 통과)과 O(전체 suite 통과)는 15장에
실행 결과로 기록한다.

## 11. 테스트 결과

```
$ python -m pytest -q tests/test_same_content_id_overwrite_protection.py
29 passed in 0.18s

$ python -m pytest -q tests/test_media_versioning_and_promotion.py \
    tests/test_batch_promotion.py tests/test_generation_review_and_promotion.py \
    tests/test_media_archive.py tests/test_media_superseded_lifecycle.py \
    tests/test_critical_content_replacement_audit.py \
    tests/test_same_content_id_overwrite_protection.py
162 passed in 17.75s

$ python -m pytest -q
1062 passed, 68 subtests passed
```

baseline(1033 passed, 68 subtests) 대비 정확히 +29건(신규 테스트 수와 일치),
subtests 수는 그대로다 - 기존 테스트를 삭제/약화하지 않았다.

## 12. 실제 운영 데이터 SHA256 (전/후)

`data/` 아래 모든 `*.json` 파일(31개) 기준, 작업 전/후 SHA256이 **완전히
동일**했다(`diff` 결과 없음). 핵심 파일만 표시:

| 파일 | SHA256 (전=후) |
|---|---|
| `data/tak_media_archive.json` | `ebe1249fe36c3fe681660c3659d2199f5ecd4f6949b7890479fac9a4e8ea8d33` |
| `data/tak_media_generation_6-07_knowledge-scout-6d1d0e2fa762.json` | `9aa3677e90ac110698dbeda645c764ea2d3d066037eff9b741fd0711624aab84` |
| `data/tak_brain_knowledge.json` | `e2ad1d39fa254ceaad4fb646124cb3e9b0b8e591ea688c1e0836fa1b6f706a31` |
| `data/tak_threads_pending.json` | `d122a0b68c093fb0e894251e60d5d987b40d9a268cd9b44522c4385bf5cabf72` |
| `data/threads_publish_log.json` | `d89074291327bc759d5416531c6cc6fb9a8cad0c5fcb6e8dc32660535d995c68` |
| `data/youtube_publish_log.json` | `a6c9491a4c446826210a7566e5bdbb5ca20e3495df9e7e88356f868acde608c2` |

`git diff -- data/` 결과도 비어 있다(추적 대상 데이터 파일에 변경 없음).
`scripts/audit_publish_candidates.py --no-report`로 읽기 전용 감사도 실행해
Publish Readiness 요약이 2장의 baseline과 동일함을 확인했다(READY 9 /
NEEDS_HUMAN_REVIEW 7 / BLOCKED 2 / ALREADY_PUBLISHED 0 / SUPERSEDED 0 /
ERROR 0).

## 13. git diff

```
 content_engine/media_archive.py     | 49 ++++++++++++++++++
 scripts/promote_media_generation.py | 79 +++++++++++++++++++++++++------
 2 files changed, 117 insertions(+), 11 deletions(-)
```

(+ 신규 파일 `tests/test_same_content_id_overwrite_protection.py`,
`docs/6-18-same-content-id-overwrite-protection.md`)

commit에는 이 4개 파일만 포함했다 - 세션 시작 전부터 있던 unrelated
uncommitted 변경(예: `content_engine/__init__.py`, `content_engine/generator.py`,
`.gitignore`, 수십 개의 미추적 `docs/5-*.md` 등)은 전혀 건드리지도, stage/commit
하지도 않았다.

## 14. commit hash

<!-- 커밋 후 채움 -->

## 15. push 결과

<!-- push 후 채움 -->

## 16. 남은 리스크

- 이 보호는 **promotion 경로(`scripts/promote_media_generation.py`)에서만**
  작동한다. `upsert_archive()`를 generation pool 없이 직접 호출하는 코드는
  여전히 같은 content_id를 조용히 덮어쓸 수 있다(`tests/test_critical_content_replacement_audit.py`의
  `ContentIdCollisionSilentOverwriteRiskTests`가 이 사실을 의도적으로
  고정해두었다) - 이는 6-16/6-17이 이미 확인한, 이번 단계 범위 밖의 별개
  사각지대다.
- content_id 자체가 바뀌는 정정(6-05/6-06/6-16에서 실제로 발생한 9건 중
  2건 케이스)은 이번 보호의 대상이 아니다 - 그 경우는 "충돌"이 아니라
  "추가"이고, 명시적 supersede 절차(`scripts/supersede_media_record.py`)가
  이미 담당한다(6-17).
- `promote_media_generation.py`는 여전히 publish history를 참조하지 않는다
  (6-16/6-17이 남긴 별개 사각지대, 11장 정책 D 참고 - 이번 단계에서 구현
  범위에 포함하지 않았다).
- batch 실행 시 conflict가 있어도 exit code는 0으로 유지했다(9장 설명) -
  CI에서 conflict를 자동으로 실패시키고 싶다면 별도 플래그(`--fail-on-conflict`
  같은)가 필요할 수 있다 - 이번 단계에서는 "예상치 못한 transaction
  semantics 변경 금지" 지시에 따라 추가하지 않았다.

## 17. 다음 단계 제안

1. (사람 결정) `content-afc6060bc1957867`를 Dashboard에서 검토/승인 ->
   이번에 추가된 보호장치 덕분에, 만약 `content-5971ed5204437cdd`와
   content_id가 우연히 같아지는 경우가 생기면 이제 자동으로 CONFLICT
   처리되어 옛 승인 레코드가 사라지지 않는다(다만 실제로는 두 content_id가
   다르므로 이번 케이스는 CONFLICT 대상이 아니라 정상 PROMOTE 대상이다 -
   6-17 절차대로 promote 후 supersede 진행).
2. 16장의 "promotion 경로 밖 직접 upsert_archive() 위험"을 어느 수준까지
   막을지 결정(예: `upsert_archive()`를 직접 호출할 수 있는 곳을 코드
   리뷰/lint로 제한하는 등 - 코드 변경 없이 정책/리뷰 절차로 대응할지, 아니면
   또 다른 세션에서 구조적으로 막을지).
3. batch conflict의 exit code 정책(현재 0)을 CI 자동화 요구사항에 맞게
   재검토할지 결정.
4. publish history 대조(6-17 11장 정책 D)를 이번 6-18 보호와 함께
   구현할지 여부 결정.
