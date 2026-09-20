# TAK AUTO 6-08 — Generation Pool 인간검수 승인 + 안전한 Promotion 운영흐름 완성

## 1. 작업 목적

6-07까지 만든 흐름은 다음에서 멈춰 있었다.

```
KNOWLEDGE → Generation Pool → /media/generations(읽기 전용) → review_status=unreviewed → (더 이상 진행 불가)
```

이번 6-08의 목표는 이 흐름을 실제 운영 가능한 형태로 완성하는 것이다.

```
KNOWLEDGE → Generation Pool → 사람이 확인 → 개별 MEDIA 승인/보류
  → 승인된 generation만 안전하게 promotion → Production Archive
```

가장 중요한 제약: **"한 번의 클릭으로 무조건 Production에 덮어쓰기" 같은 구조를
만들지 않는다.** Generation Pool 승인(`review_status`)과 Production
Promotion(`data/tak_media_archive.json` 갱신)은 끝까지 서로 다른 두 단계로
분리한다.

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
 M scripts/run_scout_dashboard.py
 M tests/test_content_engine.py
 M tests/test_media_batch.py
 M tests/test_second_knowledge_correction_and_generation_pool.py
?? (다수의 기존 untracked 문서/스크립트 — 이번 작업과 무관, 손대지 않음)
?? data/tak_media_archive.json
```

**중요한 발견**: `scripts/run_scout_dashboard.py`와
`tests/test_second_knowledge_correction_and_generation_pool.py`가 이미
**커밋되지 않은 상태로 6-08이 요구하는 기능(승인/보류/전체승인 라우트,
auto-discovery, generation×knowledge 그룹핑)의 상당 부분을 구현하고 있었다** —
이전에 중단된 작업 시도의 산물로 보인다(커밋도, 전용 테스트 파일도, 보고서도
없었다). 이번 세션은 이 기존 미커밋 구현을 **처음부터 다시 만들지 않고**, 줄
단위로 전부 다시 읽고 6-08의 모든 안전 요구사항(3장/6장/7장/8장/13장/14장)을
실제로 만족하는지 검증한 뒤, 빠져 있던 부분(전용 테스트 스위트, 이 보고서,
실제 promotion 안전성 검증, 코멘트 정정)을 채워 완성했다.

baseline 전체 테스트(작업 시작 시점, 이미 있던 미커밋 dashboard 구현 포함):

```
858 passed, 68 subtests passed in 141.68s
```

6-07 보고서 baseline(840 + 신규 18)과 정확히 일치한다.

`.gitignore`, `content_engine/*`, `data/tak_brain_knowledge.json`의 나머지
16개 레코드, `tests/test_content_engine.py`, `tests/test_media_batch.py`,
`data/tak_media_archive.json`, 기타 untracked 문서/스크립트는 이번 작업과
무관한 다른 세션의 변경이므로 **전혀 건드리지 않았다**(`git reset --hard`,
`git clean -fd`, `git checkout -- .`, `git add .`, `git add -A` 전부 사용하지
않음).

## 3. 6-07 baseline 재확인

대상 generation:

- knowledge_id: `knowledge-scout-6d1d0e2fa762`
- generation_id: `gen-20260920T033856-6e8d98fb`
- 파일: `data/tak_media_generation_6-07_knowledge-scout-6d1d0e2fa762.json`

```python
records = load_archive("data/tak_media_generation_6-07_knowledge-scout-6d1d0e2fa762.json")
len(records) == 9  # True
{r.platform for r in records} == {"blog", "shorts", "threads"}
[r.generation_status for r in records] == ["valid"] * 9
[r.review_status for r in records] == ["unreviewed"] * 9
```

9건(Blog 1 + Shorts 3 + Threads 5) 전부 `generation_status="valid"`,
`review_status="unreviewed"`임을 재확인했다(6-07 보고서와 동일).

**첫 번째 KNOWLEDGE(`knowledge-scout-b28b782b2a33`, 6-05/6-06)의 Generation
Pool**: `data/` 디렉터리 전체를 확인한 결과 `tak_media_generation_*.json`
이름 규칙을 따르는 파일은 6-07의 것 하나뿐이다. 6-06 보고서(4장 근거 확인)를
다시 읽어 확인한 결과, 6-06은 `archive_generation_report()`/
`upsert_generation_archive()` 메커니즘을 **fixture로만 검증**했고, 첫 번째
KNOWLEDGE의 실제 9건은 그보다 이전(5-27 시절, generation pool 개념이 생기기
전)에 이미 `data/tak_media_archive.json`(production archive)에 legacy
레코드(`generation_id=None`)로 직접 들어가 있다. 즉 **이번에 검토해야 할 실제
generation pool 파일은 6-07의 것 1개뿐이다** — 첫 번째 KNOWLEDGE는 애초에
promotion 대상 generation pool이 없다(이미 production에 있음).

## 4. Generation Pool 현재 상태

`/media/generations`(auto-discovery, 10장 참고)로 실제 데이터를 조회하면:

- KNOWLEDGE×generation 조합: 1개
  (`knowledge-scout-6d1d0e2fa762`, `gen-20260920T033856-6e8d98fb`)
- 그 안에 platform별로 접힌 섹션: Blog(1건)/Shorts(3건)/Threads(5건)
- 전부 `generation_status=valid`, `review_status=unreviewed`

실제 서버를 띄워 GET 요청만으로 확인했다(POST 없음, 아래 8장 참고).

## 5. Dashboard 변경

기존 `/media`(production archive 최종 검수)와 `/media/generations`(generation
pool 검수)의 역할 구분은 그대로 유지했다(13장 요구사항). `/media/generations`에
다음을 추가했다.

- 각 레코드 카드에 `content_id`, `generation_id`, `platform`,
  `generation_status`, `review_status`, `rewritten_title`, `rewritten_body`
  (전문), `source_url`(링크), `created_at`, `validation_errors`(있으면 목록
  표시)를 전부 노출한다.
- `group_records_by_platform()`으로 blog/shorts/threads 순서로 `<details>`
  접이식 섹션에 담는다(대규모 UI 개편 없이 기존 `<details>`/`.card`/`.status`
  스타일 재사용).
- `group_generation_records_by_knowledge_and_generation()`으로
  `(knowledge_id, generation_id)` 쌍 단위로 그룹핑한다 — 같은 knowledge_id라도
  generation_id가 다르면 절대 같은 그룹에 섞이지 않는다.
- 승인/보류/전체승인 후 배너 알림(`notice=approved|dismissed|approved-all`
  쿼리 파라미터)을 표시한다.
- 화면 상단에 "승인/보류는 이 generation pool 파일에만 반영되고 production
  archive는 절대 바뀌지 않는다"는 안내 문구를 고정으로 표시한다.

## 6. 개별 승인 기능

새 라우트:

- `POST /media/generations/record/<content_id>/<generation_id>/approve`
- `POST /media/generations/record/<content_id>/<generation_id>/dismiss`

(`generation_id`가 없는 legacy 레코드는 URL 세그먼트 `"legacy"`로 인코딩하고
`_generation_id_from_url_segment()`가 다시 `None`으로 되돌린다.)

`handle_generation_review_submission()`이 처리한다.

- 새로운 상태값을 만들지 않았다 — 기존 `REVIEW_STATUSES =
  ("unreviewed", "approved", "dismissed")`를 그대로 재사용한다(14장 요구사항).
  승인 → `approved`, 보류 → `dismissed`.
- `generation_status != "valid"`인 레코드(rejected/error)는 애초에 검토 대상이
  아니므로 승인/보류 시도 시 `400`과 함께 명시적으로 거부한다
  (`test_approve_rejected_record_is_rejected_with_400`).
- 존재하지 않는 `(content_id, generation_id)`는 `404`.
- 이미 `approved`인 레코드는 다시 승인/보류 요청을 보내도 **그대로 유지**된다
  (`review_status == "approved"`이면 조기 반환하고 파일을 다시 쓰지 않음) —
  승인 후 실수로 dismiss를 눌러도 승인 상태가 뒤집히지 않는 안전장치이자,
  동시에 idempotency 보장이다(`test_double_approve_is_idempotent`,
  `test_dismiss_does_not_revert_an_already_approved_record`).
- 이 함수는 **production archive 경로를 아예 인자로 받지 않는다** — 구조적으로
  production archive를 쓸 방법이 없다. 오직 그 레코드가 들어있던 generation
  pool 파일만 `upsert_generation_archive()`로 갱신한다.

## 7. Generation 전체 승인 기능

`POST /media/generations/generation/<generation_id>/approve-all`을
`handle_generation_approve_all_submission()`이 처리한다.

- 그 `generation_id`를 가진 레코드 중 `_can_review_generation_record()`가
  참인 것(= `generation_status == "valid"` 이고 아직 `approved`가 아닌 것)만
  `approved`로 바꾼다.
- `rejected`/`error` 레코드는 "전체 승인"을 눌러도 승인되지 않는다(승인해도
  promotion이 어차피 막히는 무의미한 상태 전이이기 때문 — 8/9장에서 검증).
- 다른 `generation_id`의 레코드는 절대 건드리지 않는다
  (`test_approve_all_does_not_touch_a_different_generation`).
- 이 함수도 production archive 경로를 받지 않는다.

## 8. Production Archive 보호 검증

가장 중요한 안전 규칙이다. `tests/test_generation_review_and_promotion.py`의
`DashboardApprovalRouteTests.test_approving_generation_pool_never_touches_production_archive`가
다음을 실제로 증명한다.

1. 임시 production archive(1건, `review_status=approved`)의 SHA-256 해시를
   승인 액션 **전에** 기록한다.
2. 개별 승인 1건 + generation 전체 승인을 POST로 실제 실행한다.
3. 승인 액션 **후** 같은 파일의 해시를 다시 계산해 **완전히 동일함**을
   확인한다.
4. production archive의 레코드 수(1건)와 내용(`content_id`)도 승인 전/후로
   변하지 않았음을 다시 확인한다.

추가로 실제 데이터(`data/tak_media_archive.json`,
`data/tak_media_generation_6-07_...json`)에 대해서도 GET 전용으로 Dashboard를
띄워(`python3 scripts/run_scout_dashboard.py --port 8093`, auto-discovery
사용) 두 파일의 SHA-256 해시가 서버 기동 전/후로 동일함을 확인했다 — 이번
세션은 실제 파일에 **어떤 POST도 보내지 않았다**(읽기 전용 확인만 수행).

```
$ sha256sum data/tak_media_generation_6-07_knowledge-scout-6d1d0e2fa762.json data/tak_media_archive.json
(서버 기동 전)
ed6aa24461f40880489a9e88107cc253036316a2ef95dd1911f1af5a69676e9e  data/tak_media_generation_6-07_knowledge-scout-6d1d0e2fa762.json
823ba83930116cb3bf0cf9d46bd3876c7a833c58f5871a380a5de0cad3dd1662  data/tak_media_archive.json

(GET /media/generations 확인 후, 서버 종료 후 — 동일)
ed6aa24461f40880489a9e88107cc253036316a2ef95dd1911f1af5a69676e9e  data/tak_media_generation_6-07_knowledge-scout-6d1d0e2fa762.json
823ba83930116cb3bf0cf9d46bd3876c7a833c58f5871a380a5de0cad3dd1662  data/tak_media_archive.json
```

## 9. Promotion 안전성 검증

`scripts/promote_media_generation.py`(6-06)를 다시 전부 읽었다. 이 스크립트의
기존 설계는 **"generation 전체"가 아니라 `(content_id, generation_id)` 단위로
승격**하는 구조다(9장 조건 3가지: 레코드 존재, `generation_status=="valid"`,
`review_status=="approved"`; `--execute` 없으면 dry-run). 이 정책을 바꾸지
않고 그대로 유지·고정했다.

`tests/test_generation_review_and_promotion.py::PromotionSafetyTests`가 실제
파일 I/O로 다음 시나리오를 전부 검증한다(전부 `tempfile.TemporaryDirectory()`
안의 임시 archive만 사용 — 실제 `data/tak_media_archive.json`은 이 테스트
어디에서도 열리지 않는다).

| CASE | 조건 | 결과 | 테스트 |
|---|---|---|---|
| A | unreviewed + valid | `PromotionError` | `test_case_a_unreviewed_valid_blocks_promotion` |
| B | approved + rejected | `PromotionError` | `test_case_b_approved_rejected_blocks_promotion` |
| C | approved + valid | 승격 가능(`plan_promotion` 성공) | `test_case_c_approved_valid_is_allowed` |
| D | approved + valid + `--execute` | 임시 archive에 정상 추가, dry-run은 파일 자체를 만들지 않음 | `test_case_d_execute_writes_into_temporary_production_archive_only`, `test_case_d_dry_run_does_not_create_production_archive` |
| E | 같은 generation을 다시 promotion | 중복 추가 없이 idempotent(해시 동일) | `test_case_e_repeated_promotion_is_idempotent` |
| F | 같은 generation 안 일부만 approved | approved record만 승격, 나머지는 `PromotionError` | `test_case_f_partial_approval_only_promotes_approved_record` |

CASE F는 "generation 전체가 승인돼야 promotion 가능"이라는 정책이 **아니라는
점**을 그대로 검증한다 — 현재 설계가 이미 record 단위이므로, 일부만
approved여도 그 record만 개별적으로 승격할 수 있고, 나머지 unreviewed
record는 여전히 막힌다. 기존 설계 의도를 확인한 뒤 그대로 유지했다(임의로
"generation 전체 승인 필요" 정책으로 바꾸지 않았다).

## 10. Auto Discovery 구현

`discover_generation_pool_paths(data_dir)`가 `data_dir.glob("tak_media_generation_*.json")`로
자동 탐색한다. `resolve_generation_archive_paths(explicit_paths, data_dir)`가
CLI 진입점에서 최종 경로를 결정한다.

- `--generation-archive`를 하나 이상 명시하면 **그 목록만** 그대로 쓴다(기존
  동작 100% 보존 — 이름 규칙을 따르지 않는 6-05 legacy 파일도 명시하면 볼 수
  있다).
- 아무것도 지정하지 않으면 자동 탐색 결과를 쓴다.
- `data/tak_media_archive.json`(production archive)은 파일명이
  `tak_media_generation_`으로 시작하지 않으므로 glob 패턴 자체가 구조적으로
  제외한다 — 별도 하드코딩 필터가 필요 없다.
  `test_production_archive_is_never_discovered`로 고정.
- `data_dir`가 없으면 빈 튜플(예외 없음).

실제 CLI(`main()`)에서 `args.media_archive.parent`를 `data_dir`로 써서
production archive와 같은 디렉터리(`data/`)를 자동 탐색 대상으로 삼는다 —
이번 세션 시작 시점에 이미 이렇게 연결돼 있었고, 코드 리뷰로 이 동작이
올바름을 확인했다.

## 11. 테스트 결과

신규 파일 **`tests/test_generation_review_and_promotion.py`** (23개 테스트,
4개 클래스) 추가.

- `AutoDiscoveryTests` (5): 이름 규칙 매칭, production archive 제외, 디렉터리
  없음, `--generation-archive` 명시 우선, 미명시 시 자동 탐색.
- `DashboardApprovalRouteTests` (9): 개별 승인, production archive 불변,
  보류(unreviewed→dismissed), 이미 approved인 레코드는 dismiss로도 안 바뀜,
  전체 승인이 valid만/해당 generation만 처리, 존재하지 않는 레코드 404,
  rejected 레코드 승인 시도 400, 중복 승인 idempotent.
- `GenerationGroupingTests` (2): 같은 knowledge의 다른 generation이 섞이지
  않음, platform 순서(blog/shorts/threads).
- `PromotionSafetyTests` (7): CASE A~F(9장 표) + dry-run이 파일을 만들지
  않음.

기존 `tests/test_second_knowledge_correction_and_generation_pool.py`의
`test_generations_page_has_no_action_forms`는 이번 작업으로 화면에 폼이
생겼으므로(승인/보류 버튼) 더 이상 성립하지 않는 단언이었다 — 이미
`test_generations_page_forms_only_target_generation_pool_routes`로 교체돼
있었다(작업 시작 시점에 이미 이렇게 수정된 상태였음, 2장 참고). 이 테스트는
"폼이 있되, 전부 `/media/generations/` 하위 경로만 가리키고 production 경로나
promotion 실행 경로는 하나도 없어야 한다"를 검증한다 — 6-08의 핵심 원칙(폼
자체가 구조적으로 production을 건드릴 수 없어야 한다)을 그대로 코드로
확인한다.

전체 테스트 실행(최종):

```
881 passed, 68 subtests passed in 130.98s (0:02:10)
```

858(6-07 baseline, 이미 있던 미커밋 dashboard 구현 포함) + 23(이번 신규
`test_generation_review_and_promotion.py`) = 881. **0 failed.**

## 12. 실제 Production promotion 여부

**실행하지 않았다.**

이유:

- 이번 6-08의 기본 목표는 "운영 흐름 완성 및 안전 검증"이지 실제 콘텐츠
  발행이 아니다(작업 지시 10장).
- Dashboard의 승인 버튼에서 production promotion까지 한 번에 연결하지
  않는다는 원칙을 지키면, 실제 promotion은 **사람이** `/media/generations`에서
  9건을 직접 검토해 승인 여부를 결정한 뒤, 별도로
  `scripts/promote_media_generation.py --execute`를 실행해야 하는 단계다 —
  이 결정 자체가 이번 자율 작업 범위 밖이다.
- 9장에서 promotion 메커니즘 자체(조건 검증/실행/idempotency/부분 승인)는
  임시 archive로 전부 실증했으므로, 실제로 필요할 때 그대로 안전하게 쓸 수
  있음이 검증됐다.

만약 사람이 실제로 promotion을 실행하기로 결정한다면:

- **무엇을**: `knowledge-scout-6d1d0e2fa762`의 9건(blog 1 + shorts 3 +
  threads 5), `generation_id=gen-20260920T033856-6e8d98fb`.
- **왜**: 6-07에서 `article_type` 오류를 정정한 뒤 재생성한 결과이며, 11장
  검사(금융 템플릿 미검출)와 12/13장 검사(사실성)를 6-07에서 이미 통과했다.
- **확인해야 할 조건**: `/media/generations`에서 사람이 9건 각각(또는
  "전체 승인" 버튼으로)을 검토해 `review_status="approved"`로 바꾼 뒤,
  각 `content_id`에 대해
  `python3 scripts/promote_media_generation.py --archive data/tak_media_generation_6-07_knowledge-scout-6d1d0e2fa762.json --content-id <content_id> --generation-id gen-20260920T033856-6e8d98fb`로
  먼저 dry-run 결과를 확인한다.
- **production archive가 어떻게 변경되는가**: 각 `content_id`가 production
  archive에 새로 추가된다(이 knowledge는 production에 기존 활성 레코드가
  없으므로 "교체"가 아니라 "신규 추가"다 — 6-07 16장에서 이미 확인).
- **rollback 방법**: `data/tak_media_archive.json`은 git으로 추적되지 않는
  파일이지만(운영 데이터), 승격 직전 `cp data/tak_media_archive.json
  data/tak_media_archive_backup_<날짜>.json`으로 백업한 뒤 실행하면, 문제
  발생 시 그 백업으로 `cp`해 되돌릴 수 있다(`upsert_archive()`는 content_id
  단독 키이므로 해당 9개 content_id 레코드만 제거하거나 백업 전체로 복원하면
  된다).

**승인 상태와 promotion 상태의 차이**: `review_status="approved"`는
"사람이 이 generation pool 레코드의 내용을 보고 괜찮다고 판단했다"는 뜻일
뿐, `data/tak_media_archive.json`(실제 발행 파이프라인이 참조하는 production
archive)에는 **전혀 반영되지 않는다**. Production archive에 실제로 나타나야만
(즉 `scripts/promote_media_generation.py --execute`가 실행돼야만) 기존
`/media` 화면(및 그 이후의 Threads/YouTube/Blog 발행 파이프라인)이 그
콘텐츠를 볼 수 있다.

## 13. Git 변경 파일

이번 세션이 실제로 수정/추가한 파일만 (`git add .`/`git add -A` 사용하지
않음):

```
M scripts/run_scout_dashboard.py                                    (기존 미커밋 구현 검증 + 코멘트 정정)
M tests/test_second_knowledge_correction_and_generation_pool.py     (기존 미커밋 상태 그대로 - 이미 수정돼 있었음)
A tests/test_generation_review_and_promotion.py                     (신규, 23개 테스트)
A docs/6-08_generation_review_and_promotion.md                      (이 보고서)
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

`data/tak_brain_knowledge.json`은 이번 작업에서 어떤 KNOWLEDGE도 수정하지
않았으므로 6-05/6-07처럼 부분 staging(cacheinfo)이 필요하지 않았다.

## 14. Commit

staged diff 최종 확인 후 커밋했다.

```
$ git diff --cached --stat
 docs/6-08_generation_review_and_promotion.md                  | (신규)
 scripts/run_scout_dashboard.py                                | 448 +++++++++++++++++++++---
 tests/test_generation_review_and_promotion.py                 | (신규, 426 lines)
 tests/test_second_knowledge_correction_and_generation_pool.py |  23 +-
```

커밋 메시지: `feat: add generation review and safe promotion workflow`

```
[main 92a8a1f] feat: add generation review and safe promotion workflow
 4 files changed, 1314 insertions(+), 49 deletions(-)
 create mode 100644 docs/6-08_generation_review_and_promotion.md
 create mode 100644 tests/test_generation_review_and_promotion.py
```

## 15. Push

```
$ git push
To https://github.com/sopptak/tak-auto
   188f13c..92a8a1f  main -> main

$ git fetch origin   # (출력 없음)
$ git log origin/main..HEAD --oneline   # (출력 없음 — 비어 있음, origin과 완전히 동기화)
```

## 16. 최종 git status

```
$ git status --short
 M .gitignore
 M content_engine/__init__.py
 M content_engine/generator.py
 M content_engine/llm_provider.py
 M content_engine/rewrite.py
 M data/tak_brain_knowledge.json
 M tests/test_content_engine.py
 M tests/test_media_batch.py
?? (기존 untracked 문서/스크립트 — 2장과 동일한 목록, 변경 없음)
?? data/tak_media_archive.json
```

작업 시작 시점(2장)과 비교해, 이번 세션이 만든 변경(4개 파일)만 정확히
커밋에 반영되어 목록에서 빠졌고, 기존 미커밋 변경은 단 한 글자도 건드리지
않은 채 그대로 남아 있음을 확인했다. `scripts/run_scout_dashboard.py`와
`tests/test_second_knowledge_correction_and_generation_pool.py`도 더 이상
`M`으로 나타나지 않는다(이번 커밋에 포함돼 HEAD와 일치하게 됐기 때문).

## 17. 보안 검증

- `TAK_MEDIA_LLM_API_KEY`, `TAK_MEDIA_LLM_ENDPOINT`, `YOUTUBE_REFRESH_TOKEN`,
  `YOUTUBE_CLIENT_SECRET` 등 어떤 값도 로그/코드/테스트/보고서에 출력하지
  않았다 — 이번 6-08은 애초에 이 환경변수들을 참조하는 코드를 전혀 건드리지
  않았다(16장 목표대로 LLM을 전혀 호출하지 않았다).
- 신규 테스트(`tests/test_generation_review_and_promotion.py`)는 전부
  `tempfile.TemporaryDirectory()` 안의 합성 fixture만 사용한다 — 실제
  `data/tak_brain_knowledge.json`이나 실제 KNOWLEDGE/MEDIA 텍스트를 테스트
  데이터로 쓰지 않았다.
- 커밋 대상 4개 파일에 시크릿이 없음을 `git diff --cached`로 직접 확인했다.

## 18. 남은 문제

1. Generation Pool에는 편집(제목/본문 수정) 기능이 없다 — 15장 지시대로
   범위를 키우지 않기 위해 이번에 추가하지 않았다. `/media`의 기존 편집
   구현(`edited_title`/`edited_body`)을 재사용할 수 있는 구조이므로, 필요할
   때 그대로 확장 가능하다.
2. 승인 시 review note를 남기는 기능이 없다 — `MediaArchiveRecord`에
   `review_note` 필드 자체가 없어(`KnowledgeRecord`와 달리) 이번에 새로
   만들지 않았다(14장 "새 상태값/필드를 임의로 만들지 않는다" 원칙).
3. `scripts/promote_media_generation.py`는 여전히 "record 1건씩" 승격하는
   CLI다 — "이 generation 전체를 approved된 것만 한 번에 승격" 같은 배치
   승격 기능은 없다(9장에서 확인한 대로 이것이 기존 설계 의도이며, 이번
   세션은 이 정책을 바꾸지 않기로 결정했다). 실제 운영 시 9건을 한 건씩
   커맨드로 승격해야 하는 번거로움이 남는다.
4. RewriteValidator의 "경험" 오탐 이슈(6-05/6-06)는 여전히 미수정 — 이번
   작업 범위 밖(19장 지시).
5. 기존 production의 오염된 9건(6-05가 지적, 예: `content-5971ed5204437cdd`)은
   이번에도 손대지 않았다(18장 지시).
6. 첫 번째 KNOWLEDGE(`knowledge-scout-b28b782b2a33`)는 애초에 generation
   pool 파일이 없어(3장) `/media/generations` 화면에 나타나지 않는다 — 이미
   production에 legacy로 들어가 있으므로 문제는 아니지만, "두 KNOWLEDGE를
   하나의 Dashboard에서 구분해서 볼 수 있게 한다"는 2장 목표는 "generation
   pool이 있는 KNOWLEDGE에 한해" 충족된 것이다.

## 19. 다음 작업 제안

1. 사람이 `/media/generations`에서 9건을 실제로 검토 → 승인 → 12장의 절차대로
   `promote_media_generation.py --execute`를 9번(또는 스크립트로 반복) 실행해
   첫 실제 production promotion을 수행.
2. 배치 승격 CLI(`--content-ids-file` 같은 옵션으로 여러 건을 한 커맨드로
   승격) 필요성을 실제 운영해보고 판단.
3. Generation Pool에도 `/media`의 편집 기능을 공통 helper로 추출해 재사용할지
   설계 결정(18-1).
4. `review_note` 같은 승인 사유 기록이 실제로 필요한지 운영해보고 판단
   (18-2).
5. RewriteValidator `_FACT_RISK_TERMS` 세분화(6-06/6-07에서 이월).

## 20. 최종 상태 확인

```
KNOWLEDGE (knowledge-scout-6d1d0e2fa762)
  ↓
Generation Pool (gen-20260920T033856-6e8d98fb, 9건, 전부 valid/unreviewed)
  ↓
/media/generations: 개별 승인·보류·전체승인 가능 (이번 세션에서 추가/검증)
  ↓
Production Archive: 이번 세션 동안 완전히 그대로 (해시 불변, 8장에서 실증)
  ↓
Promotion: 임시 archive로 전체 안전성 실증 완료(9장) — 실제 production
  promotion은 사람의 결정을 기다리며 아직 실행하지 않음(12장)
```

전체 테스트: **881 passed, 68 subtests passed, 0 failed.**
