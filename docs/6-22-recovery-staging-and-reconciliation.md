# 6-22 Recovery Staging and Reconciliation

## 1. 목적

집 노트북1 등에 남아 있을 가능성이 있는 기존 운영 데이터(Production
Archive/Generation Pool/Threads pending/Shorts scripts 등)를 향후 안전하게
복구할 수 있도록, "직접 반영하지 않고 먼저 비교·검증·보고만 하는 Recovery
Staging 계층"을 설계하고 구현한다.

핵심 파이프라인(6-22 지시 3장):

```
SOURCE -> STAGING -> VALIDATION -> RECONCILIATION -> REPORT
-> HUMAN APPROVAL -> EXPLICIT APPLY
```

이번 작업은 **REPORT까지만 구현**했다. HUMAN APPROVAL/EXPLICIT APPLY는
설계만 문서화했고(9장), 실제로 실행 가능한 코드(`--apply` 같은 옵션)는
이 저장소 어디에도 추가하지 않았다 — 이는 지시사항의 절대 원칙("이번
작업에서는 실제 Production Archive를 복구하거나 GitHub에 운영 데이터를
추가하지 않는다")을 코드 구조로도 강제하기 위함이다.

## 2. 현재 데이터 구조

6-21(`docs/6-21-data-sync-and-recovery-architecture.md`)에서 이미 조사한
`data/` 전체 인벤토리를 그대로 전제로 삼는다 — 이번에 다시 조사하지 않았다.
6-22 시작 시점 기준 노트북2 상태(지시사항 0장과 실제 확인 결과 일치):

| 항목 | 상태 |
|---|---|
| Production Archive | NOT_PRESENT |
| Generation Pool | NOT_PRESENT |
| Shorts scripts | NOT_PRESENT |
| Blog drafts | 이 코드베이스 어떤 스크립트도 생성하지 않는 디렉터리(6-21 14장에서 이미 확인) |
| `tak_brain_knowledge.json` / `tak_threads_pending.json` | tracked, VALID |

이 상태는 6-22 작업 종료 후에도 그대로다(13장에서 재확인).

## 3. Recovery Staging 설계

기존 6-21 `scripts/audit_data_state.py`가 정의한 상태 체계
(`NOT_PRESENT`/`EMPTY`/`VALID`/`CORRUPTED`)를 그대로 재사용하기 위해, 먼저
그 판정 로직을 `content_engine/data_state.py`로 추출했다(6-22에서 새로
만든 유일한 리팩터링). `scripts/audit_data_state.py`는 이제 이 공유 모듈의
함수를 재노출(re-export)할 뿐 로직을 중복 정의하지 않는다 — 기존 11개
테스트(`tests/test_audit_data_state.py`)는 전혀 수정하지 않고도 그대로
통과한다(12장에서 확인).

그 위에 새로 만든 계층:

```
scripts/audit_recovery_source.py   (CLI, 읽기 전용, 항상 DRY-RUN)
        │
        ▼
content_engine/recovery_staging.py (판정 로직, 순수 함수)
        │  ├─ discover_source()              (4장: SOURCE)
        │  ├─ validate_production_archive()  (6장: VALIDATION - archive)
        │  ├─ validate_generation_pool_file()(7장: VALIDATION - generation)
        │  ├─ reconcile_threads_pending()    (8장: RECONCILIATION)
        │  ├─ reconcile_shorts_scripts()     (8장: RECONCILIATION)
        │  └─ build_reconciliation_report()  (9장: REPORT)
        │
        ▼
content_engine/data_state.py       (6-21이 정의한 4상태 판정 - 공유)
```

이 계층은 어떤 파일도 쓰지 않는다 — `save_archive()`/`upsert_archive()`
같은 쓰기 함수를 전혀 import하지 않는다(`content_engine/recovery_staging.py`
상단 import 목록에서 직접 확인 가능).

## 4. Source validation

`discover_source(source_dir)`가 다음 6개 위치를 조사한다(6-22 지시 4장의
목록과 동일):

| 이름 | 파일/디렉터리 |
|---|---|
| `archive` | `<source>/tak_media_archive.json` |
| `knowledge` | `<source>/tak_brain_knowledge.json` |
| `threads_pending` | `<source>/tak_threads_pending.json` |
| `generation_pool_files` | `<source>/tak_media_generation_*.json` (여러 건) |
| `shorts_scripts` | `<source>/shorts_scripts/` |
| `blog_drafts` | `<source>/blog_drafts/` |

**`data/` 운영 디렉터리를 기본 source로 쓰지 않는다** — `discover_source()`는
`source_dir` 인자를 반드시 받아야 하고, CLI(`scripts/audit_recovery_source.py`)도
`--source`를 `required=True`로 선언했다(생략하면 argparse가 즉시 오류로
거부한다).

파일 1건당 확인하는 항목(6-22 지시 5장, `SourceFileInfo`):

- `status`(NOT_PRESENT/EMPTY/VALID/CORRUPTED, `content_engine.data_state` 재사용)
- `size_bytes`
- `sha256`(11장)
- `record_count`(최상위가 list/dict일 때만)
- `top_level_type`("list"/"dict"/None)
- `mtime`(UTC)

**내용은 어디에도 저장·출력하지 않는다** — `sha256_of()`가 파일을 읽어
해시만 계산하고 즉시 버린다. secrets/API key가 데이터 파일 안에 있어도 이
계층이 그 값을 화면에 내보내는 경로 자체가 없다.

## 5. Production Archive validation

`validate_production_archive(path)`가 6-22 지시 6장의 A~M 오류를 전부
식별한다.

| 코드 | 의미 | 검증 방식 |
|---|---|---|
| K | 잘못된 JSON | `content_engine.data_state.json_file_status()` → `CORRUPTED` |
| L | 빈 archive | 같은 함수 → `VALID`/0건(파일이 없는 것과 구분됨) |
| M | archive 파일 없음 | 같은 함수 → `NOT_PRESENT` |
| B | invalid review_status | `MediaArchiveRecord.__post_init__`(기존 6-06 코드)의 예외를 재사용/분류 |
| C | invalid generation_status | 위와 동일 |
| D | superseded인데 superseded_by 없음(또는 반대) | 위와 동일(6-17 코드) |
| F | 자기 자신을 superseded_by로 지정 | 위와 동일(6-17 코드) |
| A | duplicate content_id | 신규 — `content_engine.publish_audit.audit_archive()`의 duplicate 판정과 같은 방식(카운팅)을 archive 검증 단계에 적용 |
| E | superseded_by가 존재하지 않는 대상을 가리킴(dangling) | 신규 — 기존 코드 어디에도 없던 검사 |
| G | approved인데 필수 필드(title/body/source_url) 없음 | 신규 — `content_engine.publish_audit`의 BLOCKED 판정 아이디어를 "발행 가능 여부"가 아니라 "archive 자체의 무결성" 관점에서 재적용 |
| J | superseded 쌍의 platform/source_url/knowledge_id 불일치 | 신규 — `scripts/supersede_media_record.py`의 `plan_supersede()`가 **쓰기 전에** 강제하는 바로 그 3개 조건을, 이미 쓰여진 archive에 대해 **사후 검증**으로 재적용 |

**"기존 정책과 충돌하지 않는 범위에서 검증하라"는 지시를 지킨 방법**: B/C/D/F는
새 규칙을 만들지 않고 `MediaArchiveRecord.__post_init__`의 예외 메시지를
그대로 분류(`_classify_schema_error()`)해서 재사용했다. G/J는 새 규칙이
아니라 이미 존재하는 정책(publish_audit의 BLOCKED 조건, supersede_media_record의
supersede 조건)을 "쓰기 전 강제"에서 "쓰여진 결과의 사후 검증"으로 관점만
바꿔 재적용한 것이다. A만 진짜 새로운 교차 레코드 검사이지만, 이 역시
`publish_audit.audit_archive()`가 이미 같은 목적(ERROR 판정)으로 쓰고 있던
방식(content_id 카운팅)과 동일하다.

각 malformed 레코드는 `__post_init__`이 첫 번째로 만난 위반 사유 하나만
예외로 던지므로(fail-fast), 레코드 1건당 이슈 1개가 원칙이다 — 이는 이
코드베이스 전역의 기존 검증 철학과 일치한다(예외 기반, 여러 위반을 동시에
보고하지 않음).

## 6. Generation Pool validation

`validate_generation_pool_file(path, archive_records)`가 6-22 지시 7장을
구현한다.

- **I(동일 content_id + 동일 generation 중복)**: 정상 pool 파일은
  `upsert_generation_archive()`가 `(content_id, generation_id)` 복합 키로
  upsert하므로 원래 중복이 있을 수 없다 — 하지만 recovery source는 외부에서
  가져온 파일이라 수기 편집/손상 가능성을 배제할 수 없으므로, 원본 JSON
  배열 단계에서 직접 이 쌍의 중복을 센다.
- **H(동일 content_id + 다른 generation 충돌)**: **새 판정 로직을 만들지
  않고, 6-18 `content_engine.media_archive.check_promotion_conflict()`를
  그대로 호출한다.** 이 함수가 `ArchiveConflictError`를 던지면
  `CONTENT_ID_CONFLICT`로 기록한다 — `scripts/promote_media_generation.py`가
  실제 promotion 직전에 쓰는 바로 그 함수이므로, Recovery Staging의 판정과
  실제 promotion 시점의 판정이 항상 같은 결론을 낸다(로직이 두 곳에
  따로 존재하지 않는다).
- 비교 결과는 4가지로 분류한다: `PRODUCTION_MATCH`(이미 같은 generation으로
  승격됨, 변경 없음), `GENERATION_ONLY`(production에 아직 없는 신규 후보),
  `CONTENT_ID_CONFLICT`(H), `SOURCE_URL_MISMATCH`(같은 content_id/generation_id인데
  source_url이 다른, 정상 운영에서는 있을 수 없는 방어적 이상 감지).

**production에 자동으로 올리지 않는다**는 원칙은 코드 구조로 보장된다 —
`validate_generation_pool_file()`은 `upsert_archive()`/`save_archive()`를
전혀 호출하지 않고, `ArchiveConflictError`도 그 자리에서 잡아서 보고
항목으로만 변환할 뿐 다시 던지거나 파일에 쓰지 않는다.

## 7. Downstream reconciliation

`reconcile_threads_pending()`/`reconcile_shorts_scripts()`가 6-22 지시 8장의
8개 상태를 구분한다: `MATCH`/`MISSING_PRODUCTION`/`SUPERSEDED`/`APPROVED`/
`UNREVIEWED`/`DISMISSED`/`CONTENT_ID_CONFLICT`/`INVALID`.

**설계 결정과 근거(투명하게 문서화 — 지시사항 원문이 이 8개를 "구분하라"고만
명시하고 서로 배타적인지/계층 구조인지는 규정하지 않았으므로, 실제 구현
방식을 명시한다)**:

- `content_engine.media_archive.REVIEW_STATUSES`는 정확히 4개 값
  (`unreviewed`/`approved`/`dismissed`/`superseded`)이다. Production Archive에서
  content_id를 찾았다면, 그 레코드의 review_status는 이 4개 중 하나이므로
  `SUPERSEDED`/`APPROVED`/`UNREVIEWED`/`DISMISSED` 네 상태가 "찾았을 때"의
  전체 경우를 남김없이 덮는다 — **1차 상태(primary status)**로 삼았다.
- `INVALID`는 downstream artifact 자체가 깨져 있어 content_id를 추출할 수조차
  없는 경우(JSON 파싱 실패, 파일명과 내부 content_id 불일치, content_id
  누락)에 쓴다 — 1차 상태 판정보다 먼저 검사한다.
- `CONTENT_ID_CONFLICT`는 content_id는 추출됐지만 그 content_id가 archive
  안에서 자체적으로 중복(A)인 경우 — 어느 레코드를 "정답"으로 볼지 코드가
  판단할 수 없으므로 1차 상태보다 먼저 이 상태로 분류한다.
- `MISSING_PRODUCTION`은 content_id를 찾을 수 없는 경우 — 기존
  `content_engine.publish_eligibility`의 orphan 정책과 정확히 같은 개념이다
  (그 모듈의 docstring: "레코드가 없으면 차단하지 않는다"). 이 재사용 관계를
  6-22 지시("기존 Publish Readiness semantics와 충돌하지 않도록")를 지키기
  위해 의도적으로 맞췄다 — MISSING_PRODUCTION을 "오류"가 아니라 "정상적으로
  있을 수 있는 상태"로 취급한다.
- `MATCH`는 review_status 축과는 **별개의 부가 정보**(`field_consistency`
  필드)로 뒀다 — downstream artifact가 자체적으로 들고 있는 값(threads
  draft의 `source_url`, shorts script의 platform 일치 여부)이 archive
  레코드와 실제로 같은지를 나타낸다. review_status 네 가지와 겹치는 다섯 번째
  "정상" 카테고리를 억지로 만들지 않기 위한 결정이다 — 예를 들어
  "APPROVED이면서 field_consistency=MISMATCH"인 항목은 "승인은 됐지만 내용이
  archive와 어긋난 상태"를 정확히 표현한다(둘 중 하나만 있었다면 이 조합을
  표현할 수 없었을 것이다).

**기존 Publish Readiness semantics와의 관계**: `content_engine.publish_audit`의
`READY`/`NEEDS_HUMAN_REVIEW`/`BLOCKED`/`ALREADY_PUBLISHED`/`SUPERSEDED`/`ERROR`는
"지금 바로 게시할 수 있는가"를 답한다. 이 모듈의 8개 상태는 "이 downstream
파일이 가리키는 content_id가 (recovery source의) archive와 어떤 관계인가"를
답한다 — 완전히 다른 질문이다. 이름이 겹치는 `SUPERSEDED`는 우연이 아니라
의도적으로 같은 의미(6-17 lifecycle)를 가리키도록 맞춘 것이고, 두 모듈
모두 같은 `record.review_status`/`record.superseded_by` 필드를 읽을 뿐 서로
다른 결론(하나는 "게시 가능?", 하나는 "무엇과 대응되는가?")을 낸다.

`blog_drafts/`는 6-21에서 이미 확인했듯 이 코드베이스 어떤 스크립트도
생성하지 않는 디렉터리다. 존재하지 않는 개념에 스키마를 새로 만들면 추측이
되므로, `discover_source()`가 파일 수준 상태(존재 여부/개수)만 보고하고
content_id 단위 reconciliation은 만들지 않았다 — 실제로 이런 디렉터리가
발견되면 그때 스키마를 정의하는 것이 맞다(추측성 구현 금지 원칙).

## 8. Conflict 정책

`build_reconciliation_report()`가 conflicts/warnings를 다음과 같이 집계한다:

**Conflicts(구조적 무결성 위반 — 사람의 결정 없이는 해석 자체가 위험함)**:
A, E, F, J, I, `INVALID_CONTAINER_TYPE`, 필수 필드 누락(`MISSING_CONTENT_ID`/
`MISSING_KNOWLEDGE_ID`), B, C, D, generation pool의 `CONTENT_ID_CONFLICT`(H),
downstream의 `CONTENT_ID_CONFLICT`.

**Warnings(데이터 품질 문제이지만 구조는 무너지지 않음)**: G(approved인데
필드 누락), generation pool의 `SOURCE_URL_MISMATCH`, downstream의 `INVALID`
또는 `field_consistency == MISMATCH`.

**Action 판정**:

| 조건 | action |
|---|---|
| archive가 NOT_PRESENT | `NO_SOURCE_ARCHIVE`(비교할 대상 자체가 없음) |
| archive가 CORRUPTED | `BLOCKED` |
| conflicts > 0 또는 warnings > 0 | `REVIEW_REQUIRED` |
| 그 외 | `OK` |

이 action은 **어떤 것도 자동으로 실행하지 않는다** — 순수히 사람이 다음
단계(9장 Apply 정책)를 밟을지 판단하기 위한 조언용 라벨이다.

## 9. Apply 정책

이번 작업에서 **`--apply`(또는 그와 동등한 실제 반영 옵션)를 구현하지
않았다** — `scripts/audit_recovery_source.py`의 옵션은 `--source`/`--json`/
`--verbose`/`--strict` 4개뿐이며, `tests/test_recovery_staging.py`의
`CliDoesNotHaveApplyOptionTests`가 이를 회귀 테스트로 고정한다. 이 장은
**향후 설계만** 문서화한다(6-22 지시 10장).

**기본 원칙(향후 구현 시에도 지켜야 함)**:

- 자동 merge 금지
- 기존 production overwrite 금지
- 동일 content_id overwrite 금지
- 기존 approved record overwrite 금지
- superseded record resurrection(부활) 금지
- 다른 generation 자동 교체 금지
- source_url mismatch 자동 merge 금지

**새 데이터가 기존 데이터와 충돌하면 BLOCK해야 한다** — 이 원칙은 사실
이미 부분적으로 코드에 구현되어 있다: 6-18 `check_promotion_conflict()`가
"동일 content_id + 다른 generation"을 이미 예외로 차단하고,
`scripts/promote_media_generation.py`/`scripts/supersede_media_record.py`
모두 기본이 dry-run이며 `--execute`를 명시해야만 쓴다. **향후 Recovery
Apply를 만든다면, 새 명령을 발명하지 않고 이 기존 두 스크립트를 그대로
재사용하는 방식으로 설계해야 한다**:

1. `scripts/audit_recovery_source.py --source <PATH>`로 REPORT까지 실행,
   `action == OK`이고 `conflicts == 0`인지 확인한다.
2. `GENERATION_ONLY`로 분류된 항목만, 사람이 recovery source의 generation
   pool 파일을 로컬 `data/`의 generation pool 위치로 **수동으로 복사**한다
   (이 도구가 자동 복사하지 않는다).
3. 복사한 뒤 기존 `scripts/promote_media_generation.py --execute`로, 이미
   있는 6-18 conflict 보호를 그대로 받으며 승격한다.
4. `CONTENT_ID_CONFLICT`/`SOURCE_URL_MISMATCH`/`J_SUPERSEDE_PAIR_MISMATCH`
   등으로 분류된 항목은 **자동화 대상에서 완전히 제외**하고, 사람이
   content_id 단위로 직접 검토 후 어느 쪽을 신뢰할지 결정해야 한다 — 이
   결정을 대신 내리는 코드는 만들지 않는다(6-21 5장 시나리오 C와 동일한
   원칙).

이렇게 설계하면 "Recovery Apply"라는 새 쓰기 경로를 만드는 대신, 기존에
이미 검증된 promotion/supersede 파이프라인의 **입력을 준비하는 도구**로
Recovery Staging을 위치시킬 수 있다 — 새로운 쓰기 로직 자체를 최소화하는
방향이다.

## 10. SHA256 / Backup

`content_engine.recovery_staging.sha256_of()`가 recovery source의 각 파일
내용을 SHA256으로 식별한다. 파일 전체를 복제하거나 자동 백업하지 않고,
해시값(그리고 크기/record_count/mtime)만 `SourceFileInfo`에 담아 "원본 확인용
metadata"로만 쓴다(6-22 지시 11장 — "새로운 source of truth를 만들지 마라"를
지키기 위해, 이 해시는 어디에도 영속 저장하지 않고 매 실행마다 그 자리에서
다시 계산한다).

이 metadata로 구분 가능한 경우:

| 경우 | 판정 방법 |
|---|---|
| 동일 파일 | 로컬 archive와 source archive의 SHA256이 같음 |
| 내용은 다르지만 schema 동일 | SHA256은 다르지만 둘 다 `VALID`이고 `validate_production_archive()`의 `issues`가 둘 다 비어 있음 |
| content_id 일부 겹침 | `validate_generation_pool_file()`의 `PRODUCTION_MATCH`/`CONTENT_ID_CONFLICT` 항목 존재 여부 |
| 완전히 새로운 데이터 | `GENERATION_ONLY` 항목만 존재 |
| 손상된 데이터 | `status == CORRUPTED` 또는 `issues`에 A/E/F/J 등 존재 |

## 11. CLI 사용법

```
python scripts/audit_recovery_source.py --source <PATH> [--json] [--verbose] [--strict]
```

- 기본 동작: 항상 읽기 전용(DRY-RUN). 어떤 옵션 조합으로도 파일을 쓰지 않는다.
- `--source`(필수): 검사할 recovery source 디렉터리. `data/`를 기본값으로
  쓰지 않는다.
- `--json`: 사람이 읽는 요약 대신 구조화된 JSON을 출력한다(자동화용).
- `--verbose`: archive issue/generation pool/threads/shorts 항목별 상세
  내역까지 출력한다.
- `--strict`: conflicts 또는 warnings가 1건이라도 있으면 종료 코드 1을
  반환한다(스크립트에서 결과를 바로 분기하고 싶을 때).
- `--apply`: **존재하지 않는다**(9장 참고, 의도적으로 구현하지 않았다).

## 12. 테스트

| 구분 | 결과 |
|---|---|
| 신규(`tests/test_recovery_staging.py`) | 29 passed, 0 failed, 0 errors |
| 기존 6-21(`tests/test_audit_data_state.py`, 리팩터링 후 재확인) | 11 passed, 0 failed, 0 errors(변경 없음) |
| 6-19 회귀(`tests/test_superseded_downstream_safeguards.py`) | 21 passed, 0 failed, 0 errors(작업 전후 동일) |
| 전체(`python -m unittest discover -s tests -p "test_*.py"`) | **964 passed(918 실행+17 skip=… 정확히는 `Ran 964 tests ... OK (skipped=17)`), 0 failed, 0 errors** — 6-21 종료 시점 935개에서 이번에 추가한 29개(신규 테스트)만큼 정확히 늘어남 |

6-22 지시 13장이 요구한 18개 최소 시나리오는 `tests/test_recovery_staging.py`
안에 테스트 이름/docstring에 번호를 그대로 달아 1:1로 대응시켰다(예:
`test_1_source_missing`, ..., `test_18_no_external_api_called`).

## 13. 운영 데이터 변경 여부

작업 전후로 확인했다.

- `git status --short`: 이번 세션이 만든 5개 파일
  (`content_engine/data_state.py`, `content_engine/recovery_staging.py`,
  `scripts/audit_recovery_source.py`, `tests/test_recovery_staging.py`, 그리고
  리팩터링한 `scripts/audit_data_state.py`)과 이 문서 외에는 **아무 변경
  없음**.
- `git diff --stat -- data/`: 빈 결과(변경 없음).
- `data/tak_brain_knowledge.json`, `data/tak_threads_pending.json`: mtime
  기준 변경 없음(`tests/test_recovery_staging.py`의
  `test_17_no_tracked_data_modified`가 이를 회귀 테스트로 고정 — 전체
  `data/` 파일의 mtime 스냅샷을 CLI 실행 전후로 비교).
- `data/tak_media_archive.json`: 생성되지 않음(`test_16_no_production_file_created`).
- `data/tak_media_generation_*.json`, `data/shorts_scripts/`,
  `data/blog_drafts/`: 생성되지 않음(수동 확인 + 위 테스트들이 검증하는
  "data/ 전체 파일 목록 불변"에 포함됨).
- 실제 Threads/YouTube API 호출, Naver 게시, 외부 DB 연결: 전혀 발생하지
  않음 — `test_18_no_external_api_called`가 관련 클라이언트/모듈명이
  `content_engine/recovery_staging.py`, `scripts/audit_recovery_source.py`
  소스 어디에도 없음을 정적으로 확인한다.
- 스모크 테스트(이번 세션 중 CLI 동작 확인용)에 쓴 fixture는 세션 스크래치
  디렉터리(`AppData\Local\Temp\claude\...\scratchpad\recovery_smoke`)에만
  만들었고, 이 저장소 안에는 어떤 파일도 남기지 않았다.

## 14. 남은 위험

- `--apply` 미구현은 의도된 설계이지만, 실제로 노트북1 데이터를 복구해야
  하는 순간이 오면 9장의 설계를 실제 코드로 옮기는 작업이 또 한 번
  필요하다 — 이번 작업은 그 순간을 위한 "안전한 착륙 지점"만 만들었다.
- `GenerationPoolItem`의 `SOURCE_URL_MISMATCH`는 정상 운영에서는 이론상
  발생할 수 없는(같은 content_id는 같은 fingerprint 구성요소에서 계산되므로)
  방어적 검사다 — 실제로 이 상태가 나타난다면 `compute_content_id()`
  해시 충돌이나 더 심각한 데이터 손상을 의심해야 하는데, 이번 작업은 그
  이상 원인 조사까지는 다루지 않는다(감지만 한다).
- `blog_drafts/`에 대한 content_id 단위 reconciliation을 만들지 않았으므로,
  만약 향후 이 디렉터리를 실제로 쓰는 코드가 생기면 그때 이 모듈에
  `reconcile_blog_drafts()`를 추가해야 한다(지금은 추측성 스키마를 피하기
  위해 의도적으로 비워뒀다).
- SHA256 metadata는 매 실행마다 다시 계산할 뿐 어디에도 저장하지 않으므로,
  "이전에 봤던 source와 지금 source가 같은지"를 비교하려면 사람이 이전
  실행의 출력(예: `--json` 결과)을 직접 보관해야 한다 — 이 도구 자체는 실행
  이력을 남기지 않는다(7장에서 의도적으로 "새 source of truth를 만들지
  않기" 위해 내린 결정의 자연스러운 결과).

## 15. 집 노트북1에서 실제 데이터 발견 후 실행할 절차

1. 집 노트북1에서 `python scripts/audit_data_state.py`(6-21)를 실행해 실제로
   어떤 파일이 존재하는지 먼저 확인한다 — 이 문서를 작성한 노트북2에서는
   이 단계를 수행할 수 없다(지시사항: 다른 컴퓨터 파일에 접근하지 않음).
2. 존재가 확인된 파일들의 SHA256을 기록해 둔다(`sha256_of()`를 그 자리에서
   호출하거나, `python scripts/audit_recovery_source.py --source data --json`을
   노트북1 자신의 `data/`를 대상으로 실행해 metadata로 남긴다 — 단, 이건
   노트북1 자신의 local 확인용이며 이번 6-22 작업의 일부가 아니다).
3. 그 파일들을(또는 그 디렉터리 전체를) 별도 경로로 복사한다 — 원본은
   건드리지 않는다.
4. 복사본을 `--source`로 지정해 `python scripts/audit_recovery_source.py
   --source <복사본 경로> --verbose`를 실행한다(read-only audit).
5. 결과 보고서의 `action`을 확인한다. `OK`가 아니면 `--verbose` 출력에서
   구체적인 conflict/warning 목록을 확인한다.
6. `GENERATION_ONLY`/`PRODUCTION_MATCH`처럼 충돌이 없는 항목과, `CONTENT_ID_
   CONFLICT`/`SOURCE_URL_MISMATCH`/`J_SUPERSEDE_PAIR_MISMATCH`처럼 사람의
   판단이 필요한 항목을 구분해서 정리한다.
7. 충돌이 없는 항목에 한해, 사람이 직접 승인한 뒤 9장에서 설계한 절차대로
   기존 `scripts/promote_media_generation.py`/`scripts/supersede_media_record.py`를
   `--execute`와 함께 명시적으로 실행한다(이번 6-22 작업이 만든 어떤 도구도
   이 단계를 대신하지 않는다 — 사람이 직접, 별도 명령으로 실행해야 한다).
8. 적용 후 `python scripts/audit_data_state.py`(6-21)로 SHA256 대신 record
   count/상태를 다시 확인하고, 적용 전 기록해 둔 SHA256과 비교해 "의도한
   변경만 반영됐는가"를 확인한다.
9. `git status`로 실제로 어떤 파일이 바뀌었는지 확인한다 — 의도하지 않은
   파일이 바뀌어 있다면 즉시 원인을 조사한다(삭제/되돌리기 전에 먼저 조사,
   이번 6-21/6-22의 안전 원칙과 동일).
10. commit/push 여부는 이 단계에서 별도로 판단한다 — Production Archive를
    언제 처음 git에 커밋할지는 6-21 15/16장에서 이미 "사람의 결정이
    필요하다"고 명시한 사안이며, 이번 6-22도 그 결정을 대신 내리지 않는다.
