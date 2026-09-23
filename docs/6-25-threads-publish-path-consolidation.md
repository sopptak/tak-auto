# 6-25 Threads Publish Path Consolidation

## 1. 목적

6-24 Production Readiness Audit(`docs/6-24-production-readiness-audit.md` 10장,
18장 P1 두 번째 항목)에서 확인된 문제를 실제로 정리한다: Threads 발행에는
승인 게이트가 있는 공식 경로와 승인 게이트가 전혀 없는 레거시 경로가
동시에 존재했다. 이번 작업은

```
PRODUCTION ARCHIVE -> PUBLISH READINESS -> THREADS PUBLISH
```

라는 하나의 명확한 계약(Eligibility Contract)을 정의하고, 레거시 경로가
그 계약을 실제로 통과하도록(삭제가 아니라 재사용을 통해) 코드를 고쳤다.
실제 Threads API는 이번 세션 전체에서 단 한 번도 호출하지 않았다(모든
테스트는 mock/synthetic).

## 2. 기존 Threads 경로

3장 조사(실제 import/호출 관계 추적, 파일 목록만이 아님) 결과, 코드가
실제로 사용하는 경로는 정확히 2개다. 6-24가 이미 발견한 것과 일치한다 -
새로 발견한 문제는 만들지 않았다.

**PATH A(공식)**:
```
data/tak_brain_knowledge.json(approved)
  -> content_engine.pipeline.run_media_batch()
  -> (Dashboard "/media" 승인 → threads_review.upsert_pending()) 또는
     (scripts/generate_threads_draft.py의 독립 rotation)
  -> data/tak_threads_pending.json(status: pending)
  -> Dashboard "/threads" 승인(handle_threads_approve_submission, status: approved)
  -> scripts/publish_approved_threads.py --execute
      -> content_engine.publish_eligibility.check_content_supersede()
         (data/tak_media_archive.json을 발행 직전 다시 읽음)
      -> content_engine.threads_publisher.ThreadsClient
      -> data/threads_publish_log.json
```

**PATH B(레거시, 이번에 게이트 추가)**:
```
data/tak_brain_knowledge.json(approved)
  -> content_engine.pipeline.run_media_batch()  (매 실행마다 새로 생성)
  -> content_engine.media_archive.archive_report()  (review_status="unreviewed"로 시작)
  -> scripts/publish_threads.py --auto/--index
      -> [신규] content_engine.publish_eligibility.check_content_supersede()
         + find_production_record()로 review_status=="approved" 확인
      -> content_engine.threads_publisher.ThreadsClient
      -> data/threads_publish_log.json
```
`scripts/run_daily.py`가 PATH B의 유일한 실제 호출부다(grep 결과 재확인 -
다른 파일들은 전부 docstring/주석에서 "이건 안 쓴다"고 언급만 한다).

**PATH C(Dashboard) — 실제로는 PATH A의 일부**: `/threads`는 별도 발행
경로가 아니라 PATH A의 human review 단계(pending → approved 전이)다 -
발행 자체는 여전히 `publish_approved_threads.py`가 맡는다.

## 3. 공식 Publish 경로

`scripts/publish_approved_threads.py`(5-11 Phase 3)가 공식 경로다. 기존
동작(6-19까지 이미 구현됨, 이번에 손대지 않음)을 그대로 유지한다:

1. `data/tak_threads_pending.json`에서 `status == "approved"`인 draft만 선택.
2. `ALREADY_PUBLISHED`(`PublishHistory.is_published()`)를 최우선으로 확인
   (6-17/6-19 정책: "이미 나간 사실"이 가장 긴급).
3. `check_content_supersede()`(production archive 스냅샷 1회 읽기)로
   superseded 차단.
4. `final_title`/`final_body` 필수 필드 검증.
5. 기본 동작은 dry-run(`--dry-run`과 기본 실행이 동일하게 안전), `--execute`
   명시해야 실제 게시.
6. 실패 시 draft를 `failed`로 표시, `PublishHistory`는 갱신 안 함(성공 시에만).

## 4. Legacy 경로

`scripts/publish_threads.py`(원래 이름 그대로 유지 - 삭제하지 않음, 지시사항
7장 "단순 삭제하지 마라") + `scripts/run_daily.py`(유일한 실제 호출부).

**처리 방법 선택(지시사항 7장 A/B/C 중)**: **A(현재 공식 publish 경로를
호출하도록 변경)**를 택했다 - 단, "publish_approved_threads.py를 직접
호출"하는 방식이 아니라, **같은 eligibility 판정 함수를 재사용**하는
방식으로 구현했다. 두 스크립트는 입력 데이터 형태가 다르다
(`publish_approved_threads.py`는 `ThreadsPendingDraft` 목록,
`publish_threads.py`는 raw batch 항목 `dict` 목록) - 이 차이 때문에
CLI 자체를 통합할 수는 없지만, **판정 로직**(`content_engine.publish_eligibility`)은
완전히 동일하게 공유한다.

**왜 삭제(C)하지 않았는가**: `scripts/run_daily.py`가 여전히
`.github/workflows/daily-threads-post.yml`(cron은 비활성화, `workflow_dispatch`는
살아있음)에서 참조되고, git history상 최초 자동화 경로(`6e000c7`)이며
문서(`docs/5-19_daily_pipeline_investigation.md` 등, 6-24가 이미 인용)가
"완전히 폐기"가 아니라 "cron만 봉인"했다고 명시하므로, 지시사항 "운영
workflow를 깨뜨릴 수 있는 경우에는 호환 wrapper를 유지하라"에 해당한다고
판단했다.

**변경 내용**(`scripts/publish_threads.py`):
- `check_threads_item_eligibility(item, production_records)` 함수 추가 -
  `find_production_record()` + `check_content_supersede()`(둘 다 6-19
  기존 함수)를 그대로 호출한다. 새 판정 로직을 만들지 않았다.
- `--production-archive` 인자 추가(기본값 `data/tak_media_archive.json`,
  다른 스크립트와 동일한 관례).
- `--auto`: 후보를 `select_unpublished_threads_item()`에 넘기기 **전에**
  eligible한 것만 필터링(부적격 항목은 "후보에서 제외" 안내 후 건너뜀).
- `--index`: 선택된 항목이 eligible하지 않으면 즉시 오류 종료(수동 지정도
  더 이상 게이트를 우회할 수 없다).

**변경 내용**(`scripts/run_daily.py`): Threads 발행 단계에 방금 저장한
`--archive` 경로를 `--production-archive`로 명시적으로 전달한다(전에는
전달하지 않아 `publish_threads.py`가 자기 기본값을 썼다 - 우연히 같은
경로였지만 명시적으로 연결하는 편이 더 안전하다).

**실질적 효과**: `run_daily.py`는 매 실행마다 MEDIA를 새로 생성하고
`archive_report()`로 저장하는데, 새로 생성된 레코드는 항상
`review_status="unreviewed"`로 시작한다(6-06 기존 동작). 따라서 **PATH B는
이제 실질적으로 상시 no-op이 된다** - 어떤 content_id가 Threads로 자동
발행되려면 production archive에 이미 `approved`로 존재해야 하는데,
`run_daily.py`가 같은 실행에서 그 content_id를 다시 생성하면 6-24 P0
가드(`find_protected_overwrite_targets`)가 먼저 막는다. 결과적으로 PATH B는
"삭제하지 않고 살아있지만, 정상 운영에서는 절대 발행이 일어나지 않는"
상태가 됐다 - 삭제와 거의 같은 안전성을 호환성을 깨지 않고 얻었다.

## 5. Eligibility Contract

지시사항 5장의 10개 조건을 기존 terminology로 정리한다. 새 helper를
만들지 않고 기존 6-19 `content_engine.publish_eligibility`를 그대로
재사용했다(신규는 `find_protected_overwrite_targets` 하나뿐이며 이는
6-24에서 이미 만든 것, Threads와 무관하게 MEDIA archive 쓰기 경로 전체에
적용된다).

| # | 조건 | PATH A(공식) 구현 | PATH B(레거시, 이번 수정) 구현 |
|---|---|---|---|
| 1 | content_id 존재 | `compute_content_id()`가 pending draft 생성 시 이미 계산됨 | `check_threads_item_eligibility()`가 `compute_content_id()` 호출 |
| 2 | Production Archive record 존재 | **불필요할 수 있음**(아래 설명) | **필수** - 없으면 즉시 부적격 |
| 3 | review_status == approved | pending draft 자체의 `status == "approved"`(별도 승인 트랙, 아래 설명) | production archive record의 `review_status == "approved"` |
| 4 | generation_status 유효 | 암묵적(승인 전 단계에서 이미 valid만 pending으로 옴) | `check_threads_item_eligibility()`가 확인하지 않음 - `load_valid_threads_items()`가 `status=="valid"`로 이미 필터링(구조가 다름, 6장 참고) |
| 5 | superseded 아님 | `check_content_supersede()` | `check_content_supersede()`(동일 함수) |
| 6 | required content 존재 | `validate_final_text()` | 기존 `publish_text` 빈 문자열/500자 검사(변경 없음) |
| 7 | source_url 정책 만족 | 명시적 cross-check 없음(9장 참고, 기존 동작 유지) | 동일(변경 없음) |
| 8 | Publish Readiness READY | 직접 호출하지 않음(같은 판정을 인라인으로 재구현, `publish_audit.py`와 결론은 동일) | 동일 |
| 9 | 이미 published 아님 | `PublishHistory.is_published()`(최우선 확인) | `select_unpublished_threads_item()`이 동일 히스토리로 필터링 |
| 10 | duplicate publish 아님 | 9번이 곧 이 조건(같은 함수) | 동일 |

**조건 2/3에서 PATH A와 PATH B가 다른 이유(추측이 아니라 코드로 확인한
설계 의도, 8장에서 상세 근거)**: PATH A는 **두 개의 독립적인 승인
트랙**을 갖는다 - MEDIA 레벨(`/media`, production archive `review_status`)과
Threads 레벨(`/threads`, pending draft `status`)이 서로 다른 사람의
결정이며, `run_scout_dashboard.py`의 주석(6장에서 인용)이 이를 명시한다.
Threads pending draft는 (a) `/media` 승인을 거쳐 만들어지거나(이 경우
production archive도 approved) (b) `generate_threads_draft.py`의
독립 rotation으로 만들어질 수 있다(이 경우 production archive는
`unreviewed`일 수 있음) - **두 경우 모두 `/threads` 승인 자체가 최종
게이트로 설계되어 있다**. 그래서 PATH A는 production archive record 존재/
approved 여부를 추가로 요구하지 않아도 안전하다(6-19의 supersede
재확인만으로 충분 - superseded는 production archive에서만 판단 가능한
상태이므로 그것만 다시 읽는다). 반면 PATH B(레거시)는 이런 별도 승인
트랙이 **전혀 없다** - `--auto`/`--index`의 유일한 판단 근거가
"LLM 생성이 검증을 통과했는가"(`generation_status=="valid"`)뿐이었으므로,
이번에 추가한 게이트가 유일하게 쓸 수 있는 승인 신호는 production archive
`review_status`뿐이다.

## 6. Pending 데이터 정책

`data/tak_threads_pending.json`은 `ThreadsPendingDraft.status` ∈
{pending, approved, published, failed}(`content_engine/threads_review.py`,
6-25에서 변경하지 않음)로 상태를 구분한다. 6장 지시사항이 요구한
pending/approved/published/superseded/orphan/duplicate 여섯 상태는 이
필드 하나로는 다 표현되지 않는다 - superseded/orphan은 **production
archive와 대조해야만** 알 수 있고, 이는 정확히 `publish_approved_threads.py`가
발행 **직전**에 수행하는 일이다(3장):

- **ORPHAN**(production archive에 이 content_id 없음): 차단하지 않음(5장
  설명 - PATH A는 Threads 자체 승인 트랙이 있으므로 정상적으로 있을 수
  있는 상태).
- **SUPERSEDED**: `check_content_supersede()`가 차단.
- **ALREADY_PUBLISHED**: `PublishHistory.is_published()`가 재게시 방지, 이
  판정이 SUPERSEDED보다 우선(6-17 정책 유지).
- **duplicate**: `upsert_pending()`이 content_id를 dict key로 upsert하므로
  구조적으로 파일 안에 중복이 생길 수 없다(변경 없음, 기존 동작 확인만).

이 문서가 강조하는 원칙("pending 파일만 보고 publish 가능하다고 판단하면
안 된다")은 PATH A에서는 이미 지켜지고 있었고(6-19), PATH B에서는 이번에
새로 적용했다(4장).

## 7. Publish History

`data/threads_publish_log.json`(`content_engine/publish_history.py`,
`PublishHistory`)은 두 경로가 공유한다 - 새 이력 저장소를 만들지 않았다.
`is_published(content_id)`로 판정하며, 성공 시에만 append한다(실패 시
기록 안 함 - 두 경로 모두 동일, 12장 테스트로 재확인).

## 8. SUPERSEDED 보호

`content_engine.publish_eligibility.check_content_supersede()`(6-19)를
두 경로가 완전히 동일하게 호출한다(새 함수를 만들지 않았음을
`tests/test_threads_publish_path_consolidation.py`의
`SharedEligibilityHelperTests`가 소스 레벨로 고정한다). superseded 레코드는
어느 경로로도 발행되지 않는다(12장 시나리오 2).

## 9. Same content_id 보호

동일 content_id + 다른 generation_id 충돌은 **production archive에 쓰는
시점**(6-18 `check_promotion_conflict()`, 6-24 `find_protected_overwrite_targets()`)에서
이미 막힌다 - Threads 발행 시점에는 그 archive를 읽기만 하므로, 이 문제가
Threads 계층까지 내려올 수 없다(발행 시점에 archive에 존재하는 레코드는
이미 conflict 검사를 통과한 것). 이번 작업에서 Threads 발행 코드에 별도
검사를 추가하지 않았다 - 이미 상위 계층이 보장하는 불변조건이기 때문이다.

## 10. Race Condition

**분석(코드 구조 기준, 실제 동시 실행은 재현하지 않음)**:

1. **같은 실행 안의 스냅샷 경계**: `publish_approved_threads.py`/
   `publish_threads.py --auto` 둘 다 production archive와 publish history를
   **루프 시작 전 한 번만** 읽는다(6-19 설계 의도: "모든 draft가 같은
   스냅샷을 기준으로 판정받도록"). 만약 실행 도중 **다른 프로세스**가
   `supersede_media_record.py`를 실행해 같은 content_id를 superseded로
   바꾸면, 이번 실행은 그 사실을 모른 채 계속 진행할 수 있다 -
   `tests/test_threads_publish_path_consolidation.py`의
   `test_official_path_snapshot_does_not_see_supersede_written_after_load`가
   이 경계를 재현한다.
2. **두 프로세스 동시 실행**: 프로세스 A와 B가 동시에 같은 content_id를
   대상으로 CLI를 실행하면, 둘 다 "아직 게시 안 됨" 스냅샷을 보고 둘 다
   실제 Threads API를 호출할 수 있다(중복 게시). API 호출 자체가 끝난
   뒤에는 `PublishHistory.append()`가 파일을 다시 읽어 병합하지만(atomic
   write이므로 파일 손상은 없다), **이미 나간 두 번째 게시물 자체는 막을
   방법이 없다** - 이력 파일의 정합성과 "실제로 무엇이 게시됐는가"는
   별개 문제다.

**왜 새 lock/DB를 추가하지 않았는가(지시사항 10장 원칙)**: 이 프로젝트는
파일 기반이고, 실제 발행은 **사람이 명시적으로 CLI를 실행**해야만
일어난다(자동 스케줄은 6-24/6-25로 사실상 봉인됨, 4장) - "두 사람이 동시에
같은 발행 CLI를 실행한다"는 시나리오는 이미 낮은 확률이고, 여기에 파일
락을 추가해도 "락을 못 잡으면 뭘 해야 하는가"(재시도? 대기? 실패?)라는
새로운 복잡도만 생긴다. **기존에 이미 있는 완화책**을 그대로 신뢰하기로
했다: `.github/workflows/daily-threads-post.yml`/`publish-approved-threads.yml`의
`concurrency: group: ${{ github.workflow }}, cancel-in-progress: false`가
CI에서의 동시 실행을 직렬화한다(이미 존재, 이번에 수정하지 않음). 로컬
수동 실행 간의 레이스는 **운영 절차**(15장의 실제 발행 절차 - "동시에 두
곳에서 발행 CLI를 실행하지 않는다")로 남긴다.

## 11. Dry Run

두 경로 모두 기본 동작이 이미 안전했다(변경 없음, 재확인만):
- `publish_approved_threads.py`: 기본 실행 == `--dry-run`(둘 다 API 호출
  없음), `--execute`만 실제 발행.
- `publish_threads.py`: `--dry-run` 플래그가 명시적으로 있어야 안전 모드
  (기본값 자체는 `--dry-run` 없이 실행하면 실제 발행 시도 - 이 부분은
  변경하지 않았다, 아래 참고).

**변경하지 않은 이유**: `publish_threads.py`의 기본(비-dry-run) 동작을
"기본은 항상 dry-run"으로 바꾸는 것은 이 스크립트의 기존 CLI 계약을 깨는
행동 변경(behavior change)이고, `run_daily.py`가 이 스크립트를 다른
기본값으로 호출하고 있어 하위 호환에 영향을 준다 - 이번 작업의 핵심은
"승인되지 않은 콘텐츠가 발행되는 것을 막는 것"이지 "dry-run 기본값을
바꾸는 것"이 아니므로, 범위를 좁게 유지했다. 대신 4~5장의 eligibility
게이트가 이미 "승인되지 않은 콘텐츠"를 원천 차단하므로, dry-run 기본값
문제의 실질적 위험은 이미 사라졌다(승인된 것만 --auto 후보가 되고,
run_daily.py는 정상 운영에서 그 후보를 만들 수 없다, 4장).

## 12. Dashboard

`/threads` 목록(`render_threads_list_html`)과 상세
(`render_threads_review_html`) 화면을 조사했다(코드는 수정하지 않음 -
"Dashboard 전면개편 금지" 원칙 + 이번 핵심 목표가 백엔드 경로 정리였기
때문).

**현재 표시되는 정보**: 상태(status), 제목, 원본 제목, KNOWLEDGE ID,
source_url, content_id - 전부 상세 화면에 있다.

**표시되지 않는 정보(6-24 지시 14장 체크리스트 대비)**: production
status(이 content_id의 archive `review_status`), Publish Readiness 판정,
superseded 여부. 사람이 `/threads`에서 초안을 승인할 때, 그 초안의
production archive record가 이미 superseded 상태인지 화면만으로는 알 수
없다 - 승인 자체는 되지만(pending draft 레벨 검증만 통과하면 됨),
`publish_approved_threads.py --execute` 시점에 비로소 차단된다는 사실을
사람이 사전에 알 방법이 없다.

**이번에 UI를 고치지 않은 이유**: 이 gap은 실제 발행을 막지 못하게
하지는 않는다(3장의 발행 직전 재확인이 최종 방어선으로 이미 작동) - "사람이
승인 버튼을 눌렀는데 나중에 조용히 막힌다"는 UX 문제이지 안전성 문제가
아니다. `render_threads_review_html()`을 고치려면 그 함수에 production
archive 조회 의존성을 새로 추가해야 하는데(현재는 `draft` 하나만 받음),
Dashboard 렌더링 함수 시그니처를 바꾸는 것은 이번 세션의 핵심 범위(백엔드
발행 경로 통합)를 벗어난다고 판단해 22장(향후 개선)에 후속 작업으로만
남겼다.

## 13. GitHub Actions

두 workflow를 재조사했다(6-24가 이미 본 것과 결론 동일, 이번에 코드
변경은 `run_daily.py` 호출 인자 하나뿐):

| workflow | 트리거 | 읽는 파일 | Production Archive 확인? | legacy CLI 호출? |
|---|---|---|---|---|
| `daily-threads-post.yml` | `workflow_dispatch`만(cron 비활성화, 5-19) | `scripts/run_daily.py` 경유 | 이제 **예**(4장 수정으로 간접 확인) | 예(`run_daily.py` → `publish_threads.py --auto`) |
| `publish-approved-threads.yml` | `workflow_dispatch`만 | `scripts/publish_approved_threads.py` 직접 | 예(원래부터) | 아니오(공식 경로만) |

secrets 사용은 변경하지 않았다(`THREADS_ACCESS_TOKEN`만, 6-24에서 이미
확인). workflow YAML 파일 자체는 수정하지 않았다 - `run_daily.py`가 내부적으로
`--production-archive`를 추가했을 뿐, workflow가 넘기는 인자는 그대로다
(`python3 scripts/run_daily.py`, 인자 없음 - 스크립트 자체의 기본값 로직이
알아서 연결한다).

## 14. 테스트

지시사항 12장의 18개 시나리오 전부 다뤘다.

| # | 시나리오 | 구현 위치 |
|---|---|---|
| 1 | approved+valid+not published → READY | `test_publish_threads_auto_select.PublishThreadsEligibilityGateTests.test_approved_and_not_superseded_is_eligible` |
| 2 | approved+superseded → BLOCKED | 같은 클래스 `test_superseded_record_blocks_publish` |
| 3 | unreviewed → BLOCKED | `test_unreviewed_record_blocks_publish` |
| 4 | dismissed → BLOCKED | `test_dismissed_record_blocks_publish` |
| 5 | missing production → (PATH B는 BLOCKED, 5장 설명) | `test_missing_production_archive_file_blocks_auto`, `test_missing_archive_record_blocks_index` |
| 6 | already published → ALREADY_PUBLISHED | 기존 `test_auto_skips_already_published_item`(변경 없이 통과) |
| 7 | duplicate pending | `upsert_pending()` 구조적 방지, 6장에서 확인(신규 테스트 불필요 - 기존 threads_review 테스트가 이미 커버) |
| 8 | same content_id different generation → CONFLICT | 9장 설명 - 상위 계층(6-18/6-24)이 이미 보장, 6-18/6-24 테스트가 커버 |
| 9 | source_url mismatch | 기존 동작 유지(변경 없음), 22장에 향후 검토로 기록 |
| 10 | required field missing → BLOCKED | 기존 `validate_final_text()`(변경 없음, 기존 테스트 커버) |
| 11 | legacy CLI → official eligibility path 사용 | `test_threads_publish_path_consolidation.SharedEligibilityHelperTests` 2건 |
| 12 | legacy publish bypass → 차단 | `PublishThreadsEligibilityGateTests` 전체 + `test_run_daily`의 5건 갱신 |
| 13 | race-like supersede | `test_threads_publish_path_consolidation.test_official_path_snapshot_does_not_see_supersede_written_after_load` |
| 14 | dry-run → 외부 API 호출 0 | 기존 다수 테스트(변경 없음) + 신규 게이트 테스트 전부 `from_env.assert_not_called()` 확인 |
| 15 | API failure → history 오염 없음 | 기존 `test_real_publish_failure_does_not_record_history`(변경 없음) |
| 16 | successful mock publish → history 기록 | 기존 `test_real_publish_success_records_history_with_post_id`(변경 없음) |
| 17 | already published 재실행 → 중복 API 호출 0 | 기존 `test_auto_returns_no_content_when_all_items_already_published` |
| 18 | superseded after initial eligibility | 13번과 동일 테스트가 커버 |

**전체 결과**:

| 구분 | 결과 |
|---|---|
| 신규(`tests/test_threads_publish_path_consolidation.py`) | 4 passed |
| 신규(`PublishThreadsEligibilityGateTests`, 기존 파일에 추가) | 7 passed |
| 갱신(`test_publish_threads_auto_select.py` 기존 13건) | 13 passed(전부 archive 자동 승인 fixture로 갱신, 결과 동일) |
| 갱신(`test_run_daily.py` 18건, 그중 5건 재작성 + 1건 강화) | 18 passed |
| 갱신(`test_threads_publisher.py` 2건) | 14 passed(전체) |
| 6-19 회귀(`test_superseded_downstream_safeguards.py`) | 21 passed(변경 없음) |
| 전체(`python -m unittest discover -s tests -p "test_*.py"`) | **1012 passed(995 실행+17 skip), 0 failed, 0 errors** — 6-24 종료 1001개에서 이번에 순증가한 11개(신규 4+7)와 정확히 일치(기존 테스트는 삭제하지 않고 전부 갱신) |

## 15. 실제 운영 시 Threads 발행 절차

6-24 21장의 11a 단계를 더 구체화한다(실제 실행은 하지 않았다):

```
1. python scripts/audit_data_state.py           # 현재 상태 확인
2. Dashboard "/threads"에서 승인 대기 draft 확인
3. 승인(있다면 "AI 초안 그대로 승인" 또는 "수정하여 승인")
4. python scripts/publish_approved_threads.py \
       --production-archive data/tak_media_archive.json
   (기본은 dry-run - 무엇이 발행될지 먼저 확인)
5. 문제 없으면:
   python scripts/publish_approved_threads.py \
       --production-archive data/tak_media_archive.json --execute
6. data/threads_publish_log.json 변경 확인(git diff)
7. 동시에 다른 위치(다른 PC/터미널)에서 같은 명령을 실행하지 않는다
   (10장 레이스 컨디션 - 이 CLI 자체는 동시 실행을 막지 않는다)
8. git add data/threads_publish_log.json data/tak_threads_pending.json
   && git commit && git push
```

`scripts/publish_threads.py`/`scripts/run_daily.py`(PATH B)는 정상 운영
절차에 포함하지 않는다 - 4장에서 설명했듯 이제 상시 no-op이며, 존재
이유는 오직 `daily-threads-post.yml`의 `workflow_dispatch` 호환성
유지뿐이다.

## 16. 남은 위험

- **12장(Dashboard)**에서 확인한 대로, `/threads` 승인 화면이 production
  archive의 superseded 상태를 미리 보여주지 않는다 - 발행 시점에는
  안전하게 차단되지만, 사람이 승인할 때 "이거 나중에 막히겠다"를 미리 알
  방법이 없다. UX 개선 여지(22장).
- **10장(Race Condition)**의 "같은 실행 안의 스냅샷" 경계는 설계상
  의도된 트레이드오프이지만, 실제 운영에서 supersede 직후 곧바로 발행
  CLI를 실행하는 습관이 있다면 이론상 아주 좁은 창이 존재한다(수 초~수십초
  단위, 실제로는 사람이 순차적으로 명령을 실행하므로 극히 드묾).
- **9장(source_url mismatch)**: pending draft의 source_url과 production
  archive record의 source_url을 발행 시점에 교차 검증하지 않는다(6-22
  Recovery Staging은 이 비교를 하지만, 실시간 발행 경로에는 없다) -
  `compute_content_id()`가 이미 source_url을 지문에 포함하므로 정상
  운영에서는 불일치가 발생할 수 없지만(같은 content_id면 같은 source_url),
  archive가 수동 편집되는 등 비정상 경로에 대한 방어는 아니다.
- PATH B(`publish_threads.py`/`run_daily.py`)를 완전히 제거할지는 여전히
  사람의 결정 사안이다 - 이번에는 "안전하게 무력화"만 했다(4장).
