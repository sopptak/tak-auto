# 6-23 Recovery Review and Approval Gate

## 1. 목적

6-22(`docs/6-22-recovery-staging-and-reconciliation.md`)가 만든

```
SOURCE -> STAGING -> VALIDATION -> RECONCILIATION -> REPORT
```

위에

```
REPORT -> HUMAN REVIEW -> EXPLICIT APPROVAL -> APPLY
```

단계를 완성한다. 핵심 원칙은 지시사항 원문 그대로다: **"Recovery는 자동
복구가 아니라 사람이 확인한 뒤 명시적으로 승인하는 작업이다."** 이번
작업에서 실제 운영 데이터 복구는 실행하지 않았다 — 모든 apply 경로는
tempfile 기반 synthetic 대상에만 실행됐다(13장 시나리오 L/M/N, 15장에서
재확인).

**6-22와의 차이(중요)**: 6-22는 `--apply` 자체를 구현하지 않았다(설계만
문서화). 6-23은 **실제로 동작하는 apply 경로를 구현**했다 — 단, 이 저장소
안에서 그 경로가 실제 `data/tak_media_archive.json`을 대상으로 실행된 적은
단 한 번도 없다(모든 실행/테스트가 tempfile 대상).

## 2. Recovery 상태 모델

**2장 조사 결과에 대한 답(지시사항 2장 6개 질문)**:

1. **현재 reconciliation 결과는 어떤 상태를 반환하는가?** 6-22는 이미
   `GenerationPoolItem.comparison`(PRODUCTION_MATCH/GENERATION_ONLY/
   CONTENT_ID_CONFLICT/SOURCE_URL_MISMATCH)과
   `DownstreamReconciliationItem.status`(MATCH/MISSING_PRODUCTION/SUPERSEDED/
   APPROVED/UNREVIEWED/DISMISSED/CONTENT_ID_CONFLICT/INVALID) 두 축을
   반환한다. 이 값들은 6-23이 **그대로 재사용**했다(새로 만들지 않음).
2. **conflict는 어떻게 표현되는가?** `ArchiveIssue.code`(A~M 계열 문자열)와
   `GenerationPoolItem.comparison == "CONTENT_ID_CONFLICT"`로 표현된다 —
   둘 다 6-22가 이미 만든 것이고 6-23은 이를 집계만 한다.
3. **report는 사람이 읽기 쉬운가?** 6-22의 `render_report_text()`는 이미
   사람이 읽는 요약을 만든다. 6-23은 지시사항 9장이 요구한 정확한 필드
   구성(Approval/RECOVERY_ACTION 등)을 추가한 새 렌더러
   (`render_recovery_report_text()`)를 만들었다 — 기존 렌더러를 고치지
   않고 별도로 뒀다(6-22 REPORT와 6-23 Human Review Report는 목적이 다르기
   때문).
4. **machine-readable JSON report가 필요한가?** 그렇다 — `--json` 옵션이
   이미 6-22에도 있었고, 6-23의 CLI(`scripts/recover_media_archive.py`)도
   동일하게 지원한다(`RecoveryReport.to_dict()`).
5. **approval 상태를 어디에 저장하는 것이 적절한가?** **저장하지 않기로
   결정했다.** 3장/5장에서 근거를 설명한다.
6. **approval 자체를 운영 데이터로 저장하면 새로운 source of truth가
   생기지 않는가?** 그렇다 — 정확히 그 문제를 피하기 위해 approval을 영구
   저장소에 남기지 않고, **CLI 인자(`--approve`)로만 존재하는 ephemeral
   확인**으로 설계했다(5장).

**Recovery Decision Model(7개 상태, `content_engine/recovery_decision.py`)**:

| 상태 | 의미 | 기본 action |
|---|---|---|
| `SAFE_TO_REVIEW` | target production에 이 content_id가 아예 없음(순수 신규) | `ADD` |
| `IDENTICAL` | target에 같은 content_id+generation_id로 필드까지 완전히 동일하게 이미 있음 | `SKIP` |
| `ALREADY_PRESENT` | 같은 content_id+generation_id로 이미 있지만 일부 필드(review_status 등)가 다름 | `SKIP` |
| `REVIEW_REQUIRED` | 구조적으로는 안전(SAFE_TO_REVIEW)해 보이지만, 같은 content_id를 가리키는 downstream artifact가 SUPERSEDED이거나 필드가 어긋남 | `SKIP` |
| `CONFLICT` | 같은 content_id가 target에 **다른** generation_id로 이미 있음(H), 또는 source_url이 다름 | `BLOCK` |
| `BLOCKED` | target의 현재 활성 레코드가 이미 `superseded`인데 후보가 그 슬롯을 되살리려 함(resurrection) | `BLOCK` |
| `INVALID` | 후보 레코드 자체가 스키마상 유효하지 않음(파싱 실패, 필수 필드 누락, 같은 파일 안에서 (content_id, generation_id) 중복) | `SKIP` |

**기존 project terminology와의 관계(지시사항 3장 요구사항)**: `content_engine.publish_audit`의
`READY`/`NEEDS_HUMAN_REVIEW`/`BLOCKED`/`ALREADY_PUBLISHED`/`SUPERSEDED`/`ERROR`는
"지금 바로 게시할 수 있는가"를 답한다. 이 7개는 "이 recovery 후보를
production archive에 반영해도 되는가"를 답한다 — 완전히 다른 질문이다.
이름이 겹치는 것은 `BLOCKED` 하나뿐이고, 이마저도 서로 다른 함수·다른
입력·다른 파일(`publish_audit.py` vs `recovery_decision.py`)에서 나온다.
6-22의 `SUPERSEDED`/`CONTENT_ID_CONFLICT`(downstream용)와도 이름이
겹치지 않도록 recovery decision 쪽은 항상 이 7개 이름만 쓴다.

## 3. Human Review

`scripts/recover_media_archive.py`는 `--source`/`--production-archive`만
주고 `--approve`를 생략하면 REPORT를 출력하고 **거기서 멈춘다** — Apply
Guard조차 평가하지 않는다("승인된 content_id가 없습니다 - 여기서
멈춥니다"). 자동 approval이 없다는 것을 코드 흐름 자체로 보장한다.

다음 항목은 전부 `SAFE_TO_REVIEW` 이외의 상태로 분류되므로 **자동
승인되지 않는다**(지시사항 4장이 나열한 6개 항목과 대응):

| 지시사항 4장 항목 | 대응 상태 |
|---|---|
| 새로운 content_id | `SAFE_TO_REVIEW`(사람이 `--approve`해야만 적용 대상이 됨 - "자동"이 아니라 "가능") |
| 동일 content_id 다른 generation | `CONFLICT` |
| source_url mismatch | `CONFLICT` |
| superseded record | `BLOCKED`(resurrection) |
| 기존 approved record | `IDENTICAL`/`ALREADY_PRESENT`(Apply Guard 6번 조건이 `SAFE_TO_REVIEW`만 허용하므로 승인해도 적용되지 않음) |
| downstream orphan | 후보 자체는 `SAFE_TO_REVIEW`로 남지만, 관련 downstream이 `SUPERSEDED`/불일치면 `REVIEW_REQUIRED`로 격상 |

## 4. Explicit Approval

`--approve <content_id>`를 CLI 인자로, **여러 번, content_id 단위로**
줘야 한다 — "승인 전체"류 옵션은 없다. `evaluate_apply_guard()`가 승인된
각 content_id를 후보 목록에서 다시 찾아 `SAFE_TO_REVIEW`인지 재확인한다
(승인 목록에 `CONFLICT`/`BLOCKED`/`ALREADY_PRESENT` 상태의 content_id를
넣어도 가드가 막는다 — "승인했으니 통과"가 아니라 "승인 + 상태 자체가
안전해야 통과").

## 5. Apply Guard

`content_engine/recovery_apply.py`의 `evaluate_apply_guard()`가 지시사항
6장의 12개 조건을 전부 구현한다.

| # | 조건 | 구현 |
|---|---|---|
| 1 | source validation PASS | `source_archive.status == VALID` 그리고 `issues == ()` |
| 2 | reconciliation 완료 | `report` 객체 존재 자체가 완료를 의미(추가 검사 불필요) |
| 3 | conflict 0 | 전체 후보 중 `CONFLICT` 상태가 0건 |
| 4 | invalid 0 | 전체 후보 중 `INVALID` 상태가 0건 |
| 5 | human approval 명시 | `--approve` 목록이 비어 있지 않음 |
| 6 | 기존 production overwrite 없음 | 승인된 각 content_id의 상태가 `SAFE_TO_REVIEW`여야 함(그 외는 전부 거부) |
| 7 | same content_id conflict 없음 | 6번과 3번이 이미 함께 보장 |
| 8 | superseded resurrection 없음 | 승인된 content_id가 `BLOCKED`면 즉시 실패 |
| 9 | source SHA256 확인 | `expected_source_sha256`(REPORT 생성 시점 스냅샷)와 지금 값을 비교 |
| 10 | 대상 Production Archive 존재 여부 확인 | `target_archive.status == CORRUPTED`면 거부(NOT_PRESENT는 "신규 생성"이라 허용) |
| 11 | apply 대상 명시 | 승인 목록이 비어 있지 않고, 각 content_id가 정확히 하나의 후보에만 대응(모호하면 거부 - `unambiguous_target`) |
| 12 | dry-run 결과와 apply 대상 동일성 확인 | `reevaluate_before_apply()`가 apply 직전에 REPORT를 다시 만들어 승인된 각 content_id가 여전히 `SAFE_TO_REVIEW`인지 재확인 |

하나라도 실패하면 `ApplyGuardResult.passed == False`이고, **실패 사유를
전부 모아서**(첫 번째에서 멈추지 않고) 반환한다 — 사람이 한 번에 무엇을
고쳐야 하는지 볼 수 있도록.

## 6. Dry Run

`scripts/recover_media_archive.py`의 기본 동작은 언제나 DRY-RUN이다 —
`--apply`를 명시해야만 실제로 쓴다(`scripts/promote_media_generation.py`,
`scripts/supersede_media_record.py`와 동일한 관례). `--apply` 없이
`--approve`만 주면 Apply Guard까지는 평가해서 통과/실패를 보여주지만,
`apply_recovery()`는 호출하지 않는다(13장 시나리오 I가 이를 회귀로
고정한다).

## 7. Atomic Apply

`apply_recovery()`(`content_engine/recovery_apply.py`)가 실제로 쓰는 유일한
경로다.

- **쓰기 메커니즘 자체는 새로 만들지 않았다** — 6-06 `upsert_archive()`
  (tempfile + `Path.replace()`, 이미 원자적)를 그대로 재사용한다.
- **쓰기 전**: target의 현재 원시 bytes를 메모리에 백업한다(파일이 없으면
  `None`).
- **쓰기 실패 시**(예: OS 오류로 `Path.replace()`가 실패): `upsert_archive()`
  자체가 원자적이므로 target은 호출 전 상태 그대로 남는다 — 복원할 필요조차
  없다(시나리오 M, 12장에서 검증).
- **쓰기 후 검증**: `validate_production_archive()`로 결과를 다시 검증한다.
  문제가 있으면(정상 운영에서는 발생하지 않아야 하지만, 이 apply 코드
  자체의 버그 등 예기치 못한 경우를 대비한 방어적 장치) 쓰기 전 bytes로
  즉시 복원한다 — 같은 tempfile+`Path.replace()` 패턴을 재사용한다(새
  메커니즘이 아니다). target이 원래 없었다면(신규 생성 시도) 복원 대신
  파일을 삭제해 `NOT_PRESENT`로 되돌린다(시나리오 N, 12장에서 검증).

## 8. Same content_id Conflict

6-18 `check_promotion_conflict()`를 6-22에 이어 6-23도 **그대로 재사용**한다
(`recovery_staging.validate_generation_pool_file()`이 이미 이 함수를
호출하고, `recovery_decision._decide_generation_item()`은 그 결과
(`comparison == "CONTENT_ID_CONFLICT"`)를 `CONFLICT`/`BLOCK`으로만 옮긴다) —
새 정책을 만들지 않았다. 동일 content_id + 동일 generation은
`item.record.to_dict() == target_active_record.to_dict()`이면 `IDENTICAL`,
아니면(예: review_status만 다름) `ALREADY_PRESENT`로 6-18의 idempotency
semantics(`PromotionConflictError`를 던지지 않고 조용히 "이미 승격됨"으로
처리하는 것)와 일치하게 처리한다.

## 9. SUPERSEDED

- **old를 되살리지 않는다**: target의 활성 레코드가 `superseded`인데
  같은 (content_id, generation_id)를 가진 후보가 다시 올라오면 `BLOCKED`
  (`_decide_generation_item()`의 resurrection 체크).
- **superseded_by 관계를 무시하지 않는다**: source archive 자체의
  `superseded_by`가 깨져 있으면(대상 없음/자기참조/필드 불일치) 6-22의
  A~M 검증(E/F/J)이 이미 이를 issue로 잡고, `_determine_recovery_action()`이
  이를 즉시 `BLOCKED`로 escalate한다.
- **downstream artifact가 old를 가리키면 REVIEW/BLOCK**: `SAFE_TO_REVIEW`
  후보라도 관련 downstream item이 `SUPERSEDED` 상태면 `REVIEW_REQUIRED`로
  격상한다(2장 표, `build_recovery_report()`의 escalation pass).
- **new가 이미 production에 있다면 IDENTICAL 또는 ALREADY_PRESENT**: 8장과
  동일 로직.
- **관계가 깨져 있으면 INVALID/BLOCK**: 위와 같이 E/F/J issue →
  `source_archive.issues` 비어있지 않음 → `_determine_recovery_action()`이
  `BLOCKED` 반환.

6-19(`docs/6-19-superseded-downstream-safeguards.md`)의 downstream
safeguard와의 일관성: 6-19는 "이미 production에 있는 superseded 레코드가
downstream(Threads/Shorts/YouTube) 발행을 차단"하는 것이고, 6-23은 "recovery
source가 이미 superseded된 슬롯을 다시 살리는 것"을 막는다 — 방향은
반대지만("발행 시점의 방어" vs "복구 시점의 방어") 둘 다 같은 원칙("superseded는
종결 상태이고 되돌아가지 않는다", `content_engine.media_archive.REVIEW_STATUS_TRANSITIONS`)
위에 서 있다. 6-19 테스트 21개는 이번 작업에서 코드를 건드리지 않았으므로
전부 그대로 통과한다(12장에서 재확인).

## 10. Downstream Artifact

**핵심 아키텍처 결정**: `apply_recovery()`는 Production Archive **1개
파일만** 쓴다. Threads pending(`tak_threads_pending.json`), Shorts scripts
(`shorts_scripts/`), Blog drafts는 recovery apply 경로가 **아예 import조차
하지 않는다**(`content_engine/recovery_apply.py`,
`content_engine/recovery_decision.py` 어디에도 `threads_review`/
`shorts_adapter`의 저장 함수에 대한 참조가 없다 - 테스트
`ScenarioH.test_h_...`가 이를 정적으로 확인한다). 그래서 "old superseded
content가 downstream artifact에 남아 있어도 자동 삭제/자동 publish하지
않는다"는 원칙이 **구조적으로** 보장된다 — 애초에 그 파일들에 쓸 수 있는
코드 경로 자체가 없다.

reconciliation(orphan/superseded/missing production/approved/unreviewed/
dismissed/conflict 구분)은 6-22가 이미 구현한
`reconcile_threads_pending()`/`reconcile_shorts_scripts()`를 그대로 재사용
한다 — 단, 6-22는 downstream을 recovery **source**의 archive와 비교했지만
(source 번들 자체의 내부 일관성 확인), 6-23은 downstream을 **target**(실제
반영될 production archive)과 비교한다(`build_recovery_report()`에서
`target_archive_report.records`를 넘김) — "이 downstream을 가져왔을 때
실제 로컬 환경과 맞는가"를 확인하는 것이 recovery 맥락에서 더 중요하기
때문이다.

## 11. Synthetic E2E Scenarios

`tests/test_recovery_review_and_approval.py`가 지시사항 13장의 A~N을 전부
구현한다(클래스/테스트 이름에 알파벳을 그대로 남겼다).

| 시나리오 | 결과 |
|---|---|
| A. empty production + valid new source | 승인 없이는 `REVIEW_REQUIRED`, 승인하면 `READY_FOR_EXPLICIT_APPLY`(2장에서 설명한 "자동 승인 금지" 원칙에 따라 승인 이전에는 절대 `READY_FOR_EXPLICIT_APPLY`가 될 수 없다) |
| B. identical source + production | `IDENTICAL`/`SKIP` |
| C. same content_id + different generation | `CONFLICT`/`BLOCK`, 보고서 `action == BLOCKED` |
| D. approved old superseded + approved new | old는 `BLOCKED`(resurrection 차단), new는 이미 있으면 `IDENTICAL`/`ALREADY_PRESENT` |
| E. broken superseded_by | source archive validation이 `E_DANGLING_SUPERSEDED_BY`로 잡고 `action == BLOCKED` |
| F. source_url mismatch | `CONFLICT` |
| G. downstream orphan | `MISSING_PRODUCTION`(6-22/기존 orphan 정책 재사용) - `BLOCKED`로 격상되지 않음 |
| H. already published | recovery apply 경로가 publish history/외부 클라이언트를 전혀 참조하지 않음(정적 검증) - "이미 게시됨" semantics를 건드릴 방법이 없다 |
| I. dry-run | `--apply` 없이는 target 파일이 생성/수정되지 않음 |
| J. explicit apply guard without approval | CLI가 승인 전에 멈춤(exit 0, 아무것도 안 씀); guard 단독 호출도 `explicit_approval` 실패 |
| K. explicit apply guard with conflict | 무관한 content_id를 승인해도 다른 CONFLICT가 있으면 전체가 막힘(`conflict_zero` 실패, CLI exit 1, target 불변) |
| L. explicit apply guard with valid approved candidate | tempfile target에만 정상 반영(실제 파일 경로가 저장소 밖 tempfile임을 테스트가 직접 확인) |
| M. atomic write failure simulation | `Path.replace()` 실패를 monkeypatch로 시뮬레이션 - target 원본 bytes 그대로 보존 |
| N. post-write validation failure | 쓰기 후 검증 실패를 시뮬레이션 - 원래 bytes로 롤백(기존 파일 있던 경우)/파일 삭제(원래 없던 경우) |

## 12. 테스트 결과

| 구분 | 결과 |
|---|---|
| 신규(`tests/test_recovery_review_and_approval.py`) | 26 passed, 0 failed, 0 errors |
| 기존 6-21(`tests/test_audit_data_state.py`) | 11 passed(변경 없음) |
| 기존 6-22(`tests/test_recovery_staging.py`) | 29 passed(변경 없음) |
| 6-19 회귀(`tests/test_superseded_downstream_safeguards.py`) | 21 passed, 0 failed, 0 errors(작업 전후 동일) |
| 전체(`python -m unittest discover -s tests -p "test_*.py"`) | **990 passed(973 실행+17 skip), 0 failed, 0 errors** — `Ran 990 tests ... OK (skipped=17)`. 6-22 종료 시점 964개에서 이번에 추가한 26개만큼 정확히 늘어남 |

6-20이 추가한 `skipUnless(PRODUCTION_ARCHIVE_PATH.exists(), ...)` 가드 3곳은
이번에도 건드리지 않았다 — skip 17건은 전부 그 정책 그대로다.

## 13. 운영 데이터 보호

- `git status --short`: 이번 세션이 만든 4개 파일(`content_engine/recovery_decision.py`,
  `content_engine/recovery_apply.py`, `scripts/recover_media_archive.py`,
  `tests/test_recovery_review_and_approval.py`)과 이 문서 외에는 아무 변경
  없음.
- `git diff --stat -- data/`: 빈 결과.
- `data/tak_brain_knowledge.json`, `data/tak_threads_pending.json`: mtime
  기준 변경 없음(`NoRealDataMutatedTests.test_no_tracked_data_modified`가
  전체 `data/` 파일 mtime 스냅샷을 CLI 실행(승인+`--apply` 포함) 전후로
  비교해서 회귀로 고정).
- `data/tak_media_archive.json`, `data/tak_media_generation_*.json`,
  `data/shorts_scripts/`, `data/blog_drafts/`: 생성되지 않음
  (`test_no_production_file_created_by_report_only` + 수동 확인).
- 모든 apply 관련 테스트(L/M/N 포함)는 `tempfile.TemporaryDirectory()`
  안의 경로만 `--production-archive`/`target_archive_path`로 사용했다 —
  이 저장소의 `data/` 디렉터리를 가리킨 적이 단 한 번도 없다.

## 14. 실제 복구 시 운영 절차

6-22 15장의 절차를 그대로 잇는다(1~9단계는 6-22와 동일 - "노트북1에서 파일
확인 -> 복사 -> read-only audit -> reconciliation"). 6-23이 추가하는 부분은
7번(승인) 단계 이후다:

7. `python scripts/recover_media_archive.py --source <복사본> --production-archive
   data/tak_media_archive.json`로 REPORT를 확인한다(아직 `--approve` 없이).
8. `action`이 `REVIEW_REQUIRED`이면(정상 - 승인 전에는 항상 이 상태다)
   `--verbose`로 후보별 상세를 확인하고, `CONFLICT`/`BLOCKED`/`INVALID`가
   하나도 없는지 확인한다. 하나라도 있으면 **그 content_id는 승인 목록에
   절대 넣지 않는다** — 먼저 원인을 조사한다.
9. 사람이 승인할 content_id를 하나씩 `--approve`로 나열해 다시 실행한다
   (`--apply` 없이) — `Apply Guard [PASS]`가 나오는지 확인한다.
10. 같은 명령에 `--apply`를 추가해 실제로 반영한다. 결과(`SUCCESS`/`FAILED`)를
    확인한다.
11. `python scripts/audit_data_state.py`(6-21)로 반영 후 record count/상태를
    다시 확인한다.
12. `git status`/`git diff -- data/tak_media_archive.json`로 실제 변경 내용을
    확인한다 — 의도한 content_id만 추가됐는지 사람이 직접 눈으로 검토한다.
13. commit/push 여부는 별도로 판단한다(6-21 16장과 동일한 원칙 - Production
    Archive를 언제 처음 git에 커밋할지는 이 문서들이 대신 결정하지 않는다).

## 15. 남은 위험

- Apply Guard의 9번 조건(SHA256 drift 확인)은 **REPORT 생성 시점의
  SHA256**을 호출부가 직접 전달해야만 작동한다 — CLI(`scripts/recover_media_archive.py`)의
  현재 구현은 REPORT를 만들자마자 그 자리에서 곧바로 guard를 평가하므로
  drift가 사실상 발생하지 않는다(같은 프로세스 실행 안에서 REPORT 생성과
  guard 평가 사이에 시간차가 없다). 만약 사람이 REPORT를 먼저 파일로
  저장해두고 한참 뒤에 별도로 approve/apply를 실행하는 워크플로우를
  원한다면, 그 사이 시간차를 메우는 "저장된 REPORT를 다시 불러와 approve"
  기능이 추가로 필요하다 — 이번 6-23 범위에서는 만들지 않았다(현재 CLI는
  한 번의 실행 안에서 REPORT부터 apply까지 전부 처리한다).
- `REVIEW_REQUIRED`(downstream escalation)는 오직 threads/shorts
  reconciliation 결과만 본다 — `blog_drafts/`는 6-22와 마찬가지로 실존하지
  않는 디렉터리라 이 escalation 대상에 포함되지 않는다.
- 여러 generation pool 파일에 같은 content_id가 서로 다른 generation_id로
  나타나는 경우(예: 노트북1에서 여러 번 재생성한 흔적), Apply Guard 11번
  조건(`unambiguous_target`)이 이를 잡아 거부하지만, 이 상황을 자동으로
  정리해주는 도구는 없다 — 사람이 generation pool 파일 자체를 먼저
  정리해야 한다(추측성 자동 정리 로직을 만들지 않기로 결정 - 6-21/6-22와
  같은 원칙).

## 16. 향후 개선

- REPORT를 파일로 저장하고 나중에 다시 불러와 승인하는 2단계 워크플로우
  (15장의 SHA256 drift 관련 위험 완화).
- `blog_drafts/`를 실제로 쓰는 코드가 이 저장소에 생기면, 그때
  `reconcile_blog_drafts()`를 6-22/6-23에 함께 추가한다.
- 실제로 노트북1 데이터를 복구하게 되면, 14장의 절차를 실행하면서 발견되는
  예상 밖의 케이스(예: generation pool 파일이 여러 개인 경우의 실제 UX)를
  이 문서에 후속 장으로 추가한다.
