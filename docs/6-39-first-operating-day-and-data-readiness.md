# 6-39 First Operating Day and Data Readiness

## 1. 목적

6-38로 Operator Control Center가 완성됐다. 이번 6-39는 새 기능을 많이
만드는 것이 목적이 아니라, **실제 운영 투입 직전에 필요한 마지막 확인**을
한다:

1. 지금 이 PC(노트북1, fresh clone)의 실제 환경/데이터 상태를 정확히 조사
2. 어떤 데이터가 "진짜 운영 데이터"이고 어떤 게 코드/fixture/temp
   산출물인지 분류
3. 6-21~6-23 Recovery Architecture(SOURCE→STAGING→VALIDATION→
   RECONCILIATION→REPORT→HUMAN REVIEW→APPROVAL→APPLY, 이미 완성됨)를 실제
   운영 시작 절차에 연결
4. 첫 운영일에 사람이 할 일의 순서를 확정
5. "정상적으로 비어 있음"(STATE A)과 "복구가 필요한 상태"(STATE B/C)를
   코드로 구분
6. Production Archive를 실수로 덮어쓰지 않는 안전한 운영 진입점을 확정

이번 작업은 **운영 데이터 복구를 실제로 실행하지 않는다.** 발견된 데이터를
자동으로 Production에 적용하지 않으며, 실제 Production 데이터 변경/삭제/
overwrite/supersede/publish/외부 API 호출은 전혀 하지 않았다(17장에서
재확인).

First Sync Check: 작업 시작 시 `git status --short`(clean),
HEAD == origin/main(8ed202bb) 확인 후 시작했다(2장).

## 2. 현재 환경

| 항목 | 값 |
|---|---|
| 이 PC | 노트북1(fresh clone, 이 세션에서 GitHub `sopptak/tak-auto`를 새로 clone) |
| OS | Windows 11 Home 10.0.26200 |
| Git | 2.55.0.windows.3 |
| Python | 3.12.7(`py` 런처 - bare `python`은 WindowsApps 빈 스텁이라 동작하지 않음, 6-38에서 이미 발견) |
| branch | main |
| HEAD(작업 시작) | `8ed202bbd1e86f1267fb831569e5b18e9a6ee52c` |
| origin/main(작업 시작) | 동일(`8ed202bb...`) |
| working tree(작업 시작) | clean |
| docs/6-21~6-38 | 전부 존재(`ls docs/`로 확인, 6-32 파일명은 실제로
  `6-32-content-production-engine-hardening.md`, 6-31은
  `6-31-operational-rehearsal-and-october-1-first-run.md` - 지시사항 원문의
  파일명과 실제 파일명이 약간 다르지만 번호/내용은 모두 존재) |
| 최근 20 commit | `feat: add operator control center`(6-38)부터
  `6-19: record commit hash...`까지 전부 `feat`/`refactor`/`test`/`docs`
  타입의 정상적인 순차 히스토리, force-push 흔적 없음 |

## 3. 데이터 상태(이 PC, `scripts/audit_data_state.py` + `scripts/operator_control_center.py` 실행 결과)

| 파일 | 상태 | Git 추적 | 비고 |
|---|---|---|---|
| `data/tak_media_archive.json` | NOT_PRESENT | UNTRACKED(화이트리스트는 있으나 미커밋) | STATE A(6-21이 이미 확인, 이번에 `git log --all`로 재확인 - 5장) |
| `data/tak_brain_knowledge.json` | VALID(28건) | TRACKED | KNOWLEDGE 승인 상태 |
| `data/tak_threads_pending.json` | VALID(5건) | TRACKED | Threads 검수 대기열 |
| `data/scout_sources.json` | VALID(1건) | TRACKED | 수집 대상 설정 |
| `data/tak_scout_daily.json` | VALID(3건) | TRACKED | 당일 SCOUT 결과(clone 시점 커밋된 값) |
| `data/threads_publish_log.json` | VALID(7건) | TRACKED | 중복 게시 방지 근거 |
| `data/youtube_publish_log.json` | VALID(1건) | TRACKED | 중복 업로드 방지 근거 |
| `data/blog_publish_log.json` | NOT_PRESENT | UNTRACKED(화이트리스트 없음 - 6-21이 이미 지적한 정책 불일치, 이번에도 고치지 않음) | |
| `data/tak_media_batch_e2e_test.json` | VALID(5건) | TRACKED | CLI 기본값 샘플, 운영 데이터 아님(D) |
| `data/tak_media_generation_*.json`(Generation Pool) | NOT_PRESENT | IGNORED(의도) | |
| `data/shorts_scripts/` | NOT_PRESENT | 추적 가능(개별 파일) | |
| `data/blog_publish_pack_daily.md` | NOT_PRESENT | IGNORED(의도) | |
| `data/shorts/*.mp4` | NOT_PRESENT | 이 저장소 코드가 생성하지 않음 | |
| `data/tak_performance.json` | NOT_PRESENT | **IGNORED, 화이트리스트 없음**(`data/*.json` 블랭킷 규칙만 적용 - `git check-ignore -v`로 확인) | **6-39 신규 발견**(6장) |
| `data/tak_performance_insights.json` | NOT_PRESENT | 위와 동일 | **6-39 신규 발견**(6장) |
| Recovery staging report | N/A(파일 아님) | 해당 없음 | `audit_recovery_source.py`/`recover_media_archive.py`는 stdout에만 출력하고 기본으로 아무 파일도 쓰지 않는다(코드 확인) - "Recovery staging"이라는 이름의 영속 파일 자체가 이 저장소에 없다 |

**핵심 발견 1(6-39 신규)**: `tak_performance.json`/`tak_performance_insights.json`은
threads/youtube publish log와 달리 `.gitignore` 화이트리스트에 없다 -
`data/*.json` 블랭킷 규칙에 그대로 걸려 매번 무시된다. 즉 **한 PC에서 수집한
Performance/Insight 데이터는 git을 통해 다른 PC로 전파되지 않는다** -
`blog_publish_log.json`과 똑같은 성격의 정책 공백이다(6-21 3장/8장이 이미
지적한 문제의 세 번째 사례). 이번 6-39에서도 정책을 바꾸지 않는다(실제
Performance 데이터가 아직 없어 검증할 방법이 없고, "판단은 실제 데이터
생기고 나서"라는 6-21의 기존 원칙을 그대로 따른다) - 28장에 후속 작업으로
남긴다.

## 4. 데이터 분류표

| 데이터 | 역할 | 현재 상태(이 PC) | 출처 | Git 보존 | 운영 중요도 | 복구 방법 | Production 적용 필요 |
|---|---|---|---|---|---|---|---|
| SCOUT daily | 당일 후보 | VALID(3건) | `daily-scout.yml` / `run_scout.py` | TRACKED | 낮음(매일 재계산 가능) | 재실행(`run_scout.py`) | 아니오 |
| KNOWLEDGE | 승인된 지식 | VALID(28건) | 사람 승인(Dashboard/`review_knowledge.py`) | TRACKED | **높음**(승인 이력 자체가 산출물) | Git history | 아니오(이미 Git에 있음) |
| MEDIA generation pool | 승격 전 초안 | NOT_PRESENT | `run_media_batch.py` | IGNORED(의도) | 낮음(승격된 것만 중요) | 재생성(`run_media_batch.py`) | 아니오 |
| Production Archive | 전체 승인/거절/supersede 이력 | NOT_PRESENT(STATE A) | 사람 승인(MEDIA Dashboard) | UNTRACKED(화이트리스트는 있음, 미커밋) | **가장 높음** | 6-22/6-23 Recovery Staging/Review(14장) | **예 - 실제 발견 시** |
| Threads pending | 검수 대기 draft | VALID(5건) | `threads_review.py` | TRACKED | 높음 | Git history | 아니오 |
| Blog publish pack | 발행용 스냅샷 | NOT_PRESENT | `generate_blog_publish_pack.py` | IGNORED(의도, ephemeral) | 없음(매번 재생성) | 재생성 | 아니오 |
| Shorts script | Shorts 업로드용 초안 | NOT_PRESENT | `generate_approved_shorts_script.py` | 추적 가능 | 중간 | Production Archive에서 재생성 | 아니오(archive가 source of truth) |
| YouTube publish history | 중복 업로드 방지 | VALID(1건) | `upload_youtube_short.py` | TRACKED | 높음 | Git history | 아니오 |
| Performance snapshot | 성과 원본 | NOT_PRESENT | `collect_performance.py` | **IGNORED, 화이트리스트 없음**(3장 발견) | 높음(있으면) | 재수집 또는 Git 정책 보완 필요 | 아니오(로컬 전용 - 현재 정책) |
| Performance insight | 분석 결과 | NOT_PRESENT | `analyze_performance.py` | 위와 동일 | 중간 | 재계산(`analyze_performance.py`) | 아니오 |
| Performance decision(review 상태) | Insight 승인/거절 | NOT_PRESENT(Insight 파일 안의 필드) | 사람(Dashboard) | 위와 동일 | 중간 | 재입력 필요(별도 파일 없음) | 아니오 |
| Recovery staging(report) | 비교 결과 | N/A(파일로 존재하지 않음, stdout only) | `audit_recovery_source.py` | 해당 없음 | 낮음(매번 재계산) | 재실행 | 아니오 |
| Recovery report(recover 단계) | 승인/apply 판정 | N/A(파일로 존재하지 않음, stdout only) | `recover_media_archive.py` | 해당 없음 | 낮음 | 재실행 | 아니오 |

"없음"도 정상 결과다 - Generation Pool/Blog Pack/Shorts script/Recovery
report는 **원래 이 시점에 없는 것이 맞다**(설계상 ephemeral이거나, 아직
아무도 실행한 적이 없기 때문).

## 5. Recovery Architecture 현재 상태(6-21~6-23 코드 근거)

6-21/6-22/6-23이 이미 다음 파이프라인을 완전히 구현했다(이번에 다시 만들지
않았다):

```
SOURCE -> STAGING -> VALIDATION -> RECONCILIATION -> REPORT
       -> HUMAN REVIEW -> EXPLICIT APPROVAL -> APPLY
```

**10개 질문에 대한 코드 근거 답변**:

1. **SOURCE는 무엇인가?** `content_engine.recovery_staging.discover_source(source_dir)` -
   `--source`(필수)로 지정한 디렉터리 안의 archive/knowledge/threads_pending/
   generation_pool_files/shorts_scripts/blog_drafts 6종(`docs/6-22` 4장).
   `data/`를 기본값으로 쓰지 않는다(사람이 명시해야 함).
2. **STAGING은 어디에 생성되는가?** 별도 디렉터리에 생성되지 않는다 - 이
   계층은 **읽기만** 하고 결과를 메모리 안의 `SourceFileInfo`/
   `ArchiveValidationReport`/`RecoveryReport` 객체로만 보관한다(파일로
   materialize하지 않음, 4장에서 확인한 사실과 일치).
3. **VALIDATION은 어떤 함수/CLI가 담당하는가?**
   `content_engine.recovery_staging.validate_production_archive()`(archive
   A~M 오류)/`validate_generation_pool_file()`(generation pool H/I).
   CLI는 `scripts/audit_recovery_source.py`.
4. **RECONCILIATION은 어떤 기준으로 판단하는가?**
   `reconcile_threads_pending()`/`reconcile_shorts_scripts()`가 downstream
   artifact의 content_id를 target archive와 대조해 MATCH/MISSING_PRODUCTION/
   SUPERSEDED/APPROVED/UNREVIEWED/DISMISSED/CONTENT_ID_CONFLICT/INVALID
   8개로 분류(`docs/6-22` 7장).
5. **REVIEW_REQUIRED와 SAFE_TO_REVIEW의 차이?**
   `content_engine.recovery_decision`의 7개 상태 중 `SAFE_TO_REVIEW`는
   "구조적으로 안전해 승인 대상이 될 수 있음", `REVIEW_REQUIRED`는
   "구조는 안전해 보이지만 관련 downstream이 superseded/불일치라 사람이 한
   번 더 봐야 함"(`docs/6-23` 2장 표).
6. **APPLY는 어떤 guard를 가지는가?**
   `content_engine.recovery_apply`(정확히는 `recovery_decision.evaluate_apply_guard()`)의
   12개 조건(source validation PASS/reconciliation 완료/conflict 0/
   invalid 0/human approval 명시/overwrite 없음/same content_id conflict
   없음/resurrection 없음/SHA256 drift 확인/target 상태 확인/apply 대상
   명시/apply 직전 재검증) - `docs/6-23` 5장.
7. **rollback은 어디까지 가능한가?** 쓰기 자체가 원자적(`upsert_archive()`,
   tempfile+`Path.replace()`)이라 쓰기 도중 실패해도 원본이 그대로
   남는다(복원 불필요). **쓰기 후 검증**이 실패하면(방어적 케이스) 쓰기 전
   bytes로 즉시 롤백(원래 없었으면 파일 삭제) - `docs/6-23` 7장,
   `apply_recovery()`.
8. **Production Archive 보호장치는 어디에 있는가?** `media_archive.py`의
   `MediaArchiveRecord.__post_init__`(스키마 검증) + `check_promotion_conflict()`(6-18,
   동일 content_id 다른 generation 차단) + Apply Guard 6/7/8번 조건(6-23) -
   3중 방어.
9. **같은 content_id 충돌은 어떻게 막는가?** `check_promotion_conflict()`를
   recovery_staging(6-22)과 recovery_decision(6-23) 양쪽이 **그대로 재사용** -
   `ArchiveConflictError` → `CONFLICT`/`BLOCK`.
10. **SUPERSEDED 데이터가 다시 게시되는 것을 어떻게 막는가?** 발행 시점은
    6-19 downstream safeguard(21개 테스트), 복구 시점은 6-23의 resurrection
    체크(`_decide_generation_item()`가 target의 활성 레코드가 superseded인데
    같은 슬롯을 되살리려 하면 `BLOCKED`) - 방향은 반대지만 같은 원칙
    (`REVIEW_STATUS_TRANSITIONS`, superseded는 종결 상태)을 공유한다.

**결론**: Recovery Architecture는 REPORT까지(6-22)뿐 아니라 APPLY까지(6-23)
**이미 완전히 구현되어 있다.** 6-39가 새로 만든 것은 이 구조를 우회하는
새 경로가 아니라, Operator Control Center에 "지금 복구가 필요한
상태인가?"를 보여주는 **한 개의 읽기 전용 요약 행**뿐이다(9장).

## 6. 실제 데이터 출처(환경별 발견 가능성)

| 환경 | 데이터가 있을 가능성 | 확인 방법 | 이번에 실제로 확인했는가 |
|---|---|---|---|
| 이 PC(노트북1, fresh clone) | Production Archive 등은 `NOT_PRESENT`(3장에서 실측) | `audit_data_state.py`/`operator_control_center.py` | **예**(직접 실행) |
| 노트북2 | 6-19/6-20 문서상 과거 세션이 언급한 환경 - 이 세션은 그 PC에 물리적으로 접근할 수 없다 | 접근 불가 | **UNVERIFIED**(추측하지 않음) |
| GitHub repository(`sopptak/tak-auto`) | `git log --all -- data/tak_media_archive.json`이 어떤 브랜치에도 빈 결과 → **한 번도 커밋된 적 없음**(확정 사실) | `git log --all` | **예** |
| GitHub Codespaces | 이 세션에서 Codespaces에 접근하지 않았다 - "Codespace 워크스페이스에 파일이 남아있을 가능성"과 "GitHub repository에 커밋으로 보존된 데이터"는 **서로 다른 질문**이다(아래 별도 경고) | 접근 불가 | **UNVERIFIED** |
| 프로젝트 내부 recovery/staging 경로 | 이 저장소 안에 그런 이름의 영속 디렉터리/파일이 없다(3/4장에서 확인) | 코드/파일시스템 조사 | **예**(없음을 확인) |
| git history(전체 브랜치) | `git branch -a`/`git log --all` | 아래 확인 | **예** |
| 기타(예: 로컬 `.bak`, 외부 클라우드 동기화 폴더) | 이 저장소 코드가 참조/생성하지 않음 - 있다면 사람이 직접 인지해야 하는 저장소 밖 자산 | 해당 없음(범위 밖) | **UNVERIFIED**(이 저장소 코드/문서로는 알 수 없음) |

```
$ git branch -a
* main
  remotes/origin/HEAD -> origin/main
  remotes/origin/main
$ git log --all --oneline -- data/tak_media_archive.json
(빈 결과)
```

**중요 경고(지시사항이 명시적으로 요구한 구분)**: GitHub에 **commit되지
않은** 운영 데이터는 `git clone`만으로는 **어떤 방법으로도 복구되지
않는다** - clone은 저장된 커밋 내용을 그대로 가져올 뿐, 존재한 적 없는
커밋을 만들어내지 않는다. 마찬가지로 GitHub Codespaces의 컨테이너
워크스페이스(디스크)는 그 컨테이너의 수명 동안만 존재하는 별개의
저장소이며, **그 워크스페이스에 있었을 수 있는 파일**과 **그 Codespaces가
실제로 커밋해서 GitHub repository에 push한 내용**은 다르다 - Codespace가
삭제/재생성되면 커밋되지 않은 변경분은 그 컨테이너와 함께 사라지고, 이
저장소(`sopptak/tak-auto`)에는 애초에 존재한 적 없는 것과 동일해진다. 이
문서는 "노트북1/노트북2/Codespaces 중 어딘가에 Production Archive가 남아
있을 것"이라고 **추측하지 않는다** - 5장의 데이터 분류표와 이 표는
"확인된 사실"과 "확인 불가(UNVERIFIED)"만 구분해서 기록한다.

## 7. Fresh Clone의 정상 상태 정의(STATE A)

다음 조건을 **모두** 만족하면 "정상적인 fresh clone/아직 운영 데이터가
없는 상태"(STATE A)다 - 오류로 취급하지 않는다:

- `git status --short`가 clean이고 `HEAD == origin/main`
- `data/tak_media_archive.json`이 `NOT_PRESENT`
- **그리고** `git log --all -- data/tak_media_archive.json`이 빈 결과(=이
  파일이 어떤 브랜치/커밋에도 존재한 적이 없음)
- Generation Pool/Shorts scripts/Blog drafts/Performance/Insight가
  `NOT_PRESENT`(전부 설계상 로컬 전용이거나 사람이 아직 실행하지 않은
  단계)
- `tak_brain_knowledge.json`/`tak_threads_pending.json`/publish log류는
  `VALID`(Git으로 정상 동기화됨)

이 PC는 지금 이 조건을 전부 만족한다(2/3장, 6-38에서도 이미 확인). 6-38의
Operator Control Center는 이 상태를 이미 가짜 READY로 만들지 않고
`NOT_PRESENT`로 정확히 보여준다 - 이번 6-39가 추가한 유일한 개선은
"이것이 STATE A인지 STATE B인지"를 git 이력으로 자동 구분해서 RECOVERY
행에 보여주는 것이다(9장).

## 8. 운영 데이터 부재 상태 정의(STATE B/C)

| 상태 | 정의 | 판정 신호(코드 근거) | Operator Center 표시 |
|---|---|---|---|
| STATE A | 정상 - 아직 없음 | `production_archive_status == NOT_PRESENT` **그리고** `git log --all`이 빈 결과 | RECOVERY: `NOT_REQUIRED` |
| STATE B | 있었는데 사라짐(복구 필요) | `production_archive_status == NOT_PRESENT` **그런데** `git log --all`에 이 파일의 커밋이 존재 | RECOVERY: `RECOVERY_REQUIRED` |
| STATE C | 존재하지만 검증/복구 필요 | `production_archive_status == CORRUPTED`(파싱 실패) 또는 `VALID`인데 6-22 `validate_production_archive()`가 이슈(중복 content_id 등)를 발견 | RECOVERY: `REVIEW_REQUIRED`(손상) 또는 `CONFLICT`(정합성 이슈) |
| 확인 불가 | git 이력을 확인할 수 없음(저장소 밖 경로, git 명령 실패 등) | `git log --all`이 0/1이 아닌 오류 종료 코드를 반환 | RECOVERY: `UNVERIFIED`(문제 있다고 단정하지 않음) |

이 표가 바로 `content_engine.operator_summary.build_recovery_status()`(6-39
신규, 11/12장)의 전체 판정 규칙이다 - 새 검증 로직이 아니라 기존
`git log`/6-22 `validate_production_archive()`의 결과를 그대로 재사용한다.

## 9. Operator Control Center 연결

6-38의 `OperatorSummary`에 **RECOVERY** 필드를 하나 추가했다
(`content_engine/operator_summary.py`):

- `build_recovery_status(inputs) -> StatusWhyAction` - 8장의 표를 그대로
  구현. 새 상태는 `RECOVERY_REQUIRED`(진짜 새 개념) 하나뿐이고, `CONFLICT`/
  `REVIEW_REQUIRED`는 6-23 `content_engine.recovery_decision`의 기존 7개
  상태를 그대로 import해서 재사용한다(새 이름을 만들지 않음).
- `scripts/operator_control_center.py`가 `--production-archive` 경로에 대해
  `git log --all --oneline -- <경로>`(신규 `_ever_tracked_in_git()`)와 6-22
  `validate_production_archive()`(기존 함수, 그대로 호출)를 실행해 그 결과를
  `OperatorInputs.production_archive_ever_tracked`/`production_archive_issue_count`로
  전달한다 - **판정 로직 자체는 여전히 operator_summary 밖(git/6-22)에
  있다.**
- Dashboard `/operator`와 CLI 텍스트 출력 양쪽에 `RECOVERY` 섹션이 새로
  추가됐다(DATA HEALTH 다음, PERFORMANCE/INSIGHT 앞) - 여전히 완전
  읽기 전용이다(`<form>` 태그 없음, 15장에서 재확인).
- `system_status`는 `RECOVERY_REQUIRED`/`CONFLICT`/`REVIEW_REQUIRED`일
  때만 `NEEDS_REVIEW`로 격상된다 - `UNVERIFIED`(확인 불가)는 격상하지
  않는다("모른다"를 "문제 있다"로 오판하지 않기 위함, 8장 표와 일치).

이 PC(fresh clone)에서 실행한 실제 결과:

```
--- RECOVERY ---
RECOVERY: NOT_REQUIRED
    WHY: Production Archive가 git에 커밋된 적이 없습니다 - 정상적인 fresh clone 상태입니다(STATE A).
```

## 10. 첫 운영일 Readiness 판정(새 enum 없음)

지시사항이 예시로 든 `NOT_READY`/`READY_FOR_SCOUT`/`WAITING_HUMAN_REVIEW`/
`READY_FOR_MEDIA`/`WAITING_PUBLISH_ACTION`/`WAITING_PERFORMANCE`/
`RECOVERY_REQUIRED`/`BLOCKED` 8개를 검토한 결과, **이미 존재하는 체계로
충분히 표현 가능하다** - 새 단일 enum을 만들지 않았다:

| 예시 상태 | 이미 있는 표현 |
|---|---|
| `NOT_READY` | `system_status == SYSTEM_ERROR`(pipeline에 ERROR가 있을 때) |
| `READY_FOR_SCOUT` | `pipeline[0]("SCOUT").status == NOT_PRESENT` + `system_status != SYSTEM_BLOCKED` |
| `WAITING_HUMAN_REVIEW` | `system_status == SYSTEM_READY_WITH_HUMAN_STEP` + `human_actions`가 비어있지 않음 |
| `READY_FOR_MEDIA` | `pipeline[KNOWLEDGE].status == PUBLISH_READY`(승인된 KNOWLEDGE 존재) |
| `WAITING_PUBLISH_ACTION` | `pipeline[PUBLISH].status == "ACTION_REQUIRED"` |
| `WAITING_PERFORMANCE` | `pipeline[PERFORMANCE].status == NOT_PRESENT` |
| `RECOVERY_REQUIRED` | **6-39 신규** `recovery.status == RECOVERY_REQUIRED`(8/9장) - 유일하게 정말 없던 개념 |
| `BLOCKED` | `system_status == SYSTEM_BLOCKED` |

운영자는 "지금 한 화면 상태가 8개 중 몇 번인가"를 계산할 필요 없이, 이미
있는 `system_status` + `pipeline` + `recovery` 조합을 그대로 읽으면 된다 -
**단일 숫자 점수(예: "80점")는 만들지 않았다**(지시사항 10장 명시적 금지,
6-38도 이미 이 원칙을 지켰다).

## 11/12. Dry Run 현황 + Dry Run → Review → Explicit Apply 안전 경계

**이 저장소에 이미 있는 dry-run 지원 CLI(전수 조사)**:

| CLI | 기본 동작 | 실제 적용 방법 |
|---|---|---|
| `run_media_batch.py` | dry-run(파일 안 씀) | `--execute` |
| `promote_media_generation.py` | dry-run | `--execute` |
| `supersede_media_record.py` | dry-run | `--execute` |
| `generate_blog_publish_pack.py` | 파일을 쓰지만 Naver 게시는 안 함(사람이 수동 게시) | 항상 수동 |
| `audit_recovery_source.py`(6-22) | **항상** dry-run(`--apply` 자체가 없음) | 없음(설계상 REPORT까지만) |
| `recover_media_archive.py`(6-23) | 기본 dry-run, `--approve` 있어도 apply 안 함 | `--approve <id> ... --apply` 둘 다 명시해야 함 |
| `collect_performance.py` | 실행하면 스냅샷을 씀(대신 GitHub Actions 환경에서만 실제 API 호출 - live gate) | 로컬에서는 read-only 소스만 사용 |

**DRY RUN → REVIEW → EXPLICIT APPLY 경계는 이미 지켜지고 있다** - 모든
쓰기 경로가 기본값을 dry-run으로 두고 있으며, 가장 위험한 Production
Archive 쓰기 경로(recovery apply)는 **두 개의 명시적 플래그**
(`--approve <content_id>`, `--apply`)를 모두 요구한다(6-23). 6-39가 이
경계에 추가로 구현한 것은 없다 - 이미 충분하다고 판단했다(부족한 부분을
찾지 못했으므로 지시사항 8장의 "부족한 부분이 있으면 최소한의 개선만"에
해당하는 개선 대상이 없었다).

## 13. Human Action(운영자가 실제로 할 일)

Operator Control Center의 `HUMAN ACTION` 섹션이 이미 이를 담당한다(6-38).
6-39가 추가한 유일한 human action은 **RECOVERY_REQUIRED가 뜰 때**의
행동이다: "다른 PC의 데이터를 확인한 뒤
`python scripts/audit_recovery_source.py --source <복사본>`으로
검토하세요" - 자동 실행 버튼이 아니라 CLI 안내 문자열이다(6-38과 동일한
원칙, 15장에서 재확인).

## 14. Platform별 운영 절차(요약, 상세는 6-25~6-27/6-30)

| 플랫폼 | 자동화 범위 | 사람이 할 일 |
|---|---|---|
| Threads | 검수 완료된 draft를 workflow가 자동 게시(`publish-approved-threads.yml`) | Dashboard `/threads`에서 승인 |
| Blog(Naver) | 게시 안 함(설계상 의도) | Publish Pack을 사람이 직접 Naver에 복사/붙여넣기 |
| YouTube Shorts | renderer가 없어 항상 BLOCKED(6-30) | 외부 머신에서 renderer 확보 여부 확인, OAuth 환경변수 확인 |

## 15. Performance 시작 절차

1. `python scripts/collect_performance.py`로 스냅샷 수집(로컬은 read-only
   소스, 실제 라이브 호출은 GitHub Actions 환경에서만 - `test_collect_performance_live_gate.py`가
   이 게이트를 검증).
2. `python scripts/analyze_performance.py`로 Insight 계산.
3. Operator Control Center `PERFORMANCE`/`INSIGHT` 행에서 결과 확인(6-38).
4. **주의(3장 신규 발견)**: 이 두 파일은 현재 git에 커밋되지 않으므로,
   여러 PC에서 운영한다면 PC마다 별도로 수집/분석해야 한다(28장 후속
   과제).

## 16. 장애/복구 절차

Production Archive가 STATE B(`RECOVERY_REQUIRED`)로 뜨면:

1. **먼저 원인을 조사한다** - 삭제/`git reset`/`git restore` 등 되돌리기
   시도를 하지 않는다(절대 원칙 0장).
2. `git log --all -- data/tak_media_archive.json`으로 어느 커밋에 있었는지
   확인한다.
3. 그 커밋이 origin에 push된 것이면 `git show <commit>:data/tak_media_archive.json`으로
   내용을 먼저 확인한 뒤, 사람이 직접 복원 여부를 결정한다(자동 복원
   스크립트를 만들지 않았다 - 6-21 5장 시나리오 C와 같은 원칙, 추측성
   자동화 금지).
4. 다른 PC에 최신 데이터가 있다고 의심되면 6-22 15장/6-23 14장의 절차
   (복사 → `audit_recovery_source.py` → `recover_media_archive.py --approve
   ... --apply`)를 그대로 따른다 - 이 문서가 그 절차를 대신하지 않는다.

## 17. Scenario A~H

각 시나리오에서 "다음에 할 일"과 "절대 하면 안 되는 일"을 정의한다.
전부 이 PC에서 `production_archive_status`/`production_archive_ever_tracked`
등을 조합해 tempfile로 재현/검증했다(19장 테스트).

| # | 시나리오 | 다음에 할 일 | 절대 하면 안 되는 일 |
|---|---|---|---|
| A | 완전 fresh clone(운영 데이터 없음) | `python scripts/run_scout.py`로 SCOUT부터 시작 | 빈 Production Archive를 미리 만들어두기 |
| B | SCOUT 있음, KNOWLEDGE 없음 | `python scripts/create_knowledge.py`/`generate_knowledge.py` | KNOWLEDGE 없이 MEDIA 생성 시도 |
| C | KNOWLEDGE 있음, MEDIA 없음 | `python scripts/run_media_batch.py --execute --as-generation` | KNOWLEDGE를 승인 없이 강제 진행 |
| D | MEDIA generation 있음, Production Archive 없음 | 검토 후 `python scripts/promote_media_generation.py --execute` | 검토 없이 전체 승격 |
| E | Production Archive 있음 | `python scripts/audit_publish_candidates.py`로 Publish Readiness 확인 | READY가 아닌 것을 강제 발행 |
| F | 일부 데이터만 있음(Recovery 필요 의심) | `RECOVERY` 행 확인 → `RECOVERY_REQUIRED`면 16장 절차 | 임의로 파일을 새로 만들어 "복구됨"으로 위장 |
| G | 동일 content_id 충돌 존재 | `python scripts/audit_recovery_source.py --verbose`로 상세 확인, 사람이 직접 판단 | 자동으로 한쪽을 덮어쓰기 |
| H | SUPERSEDED 데이터 존재 | 그대로 둔다(6-19가 이미 발행 차단, 6-23이 이미 resurrection 차단) | superseded 레코드를 다시 `approved`로 되돌리기 |

## 18. 테스트 결과

| 구분 | 결과 |
|---|---|
| 6-39 신규(`tests/test_6_39_first_operating_day_and_data_readiness.py`) | **19 passed, 0 failed, 0 errors** |
| 6-38 회귀(`test_6_38_operator_control_center.py`) | 68 passed(변경 없음, RECOVERY 필드 추가 후에도 전부 통과) |
| 6-37 회귀 | 68 passed |
| 6-36 회귀 | 46 passed |
| 6-35 회귀 | 48 passed |
| 6-33 회귀 | 25 passed |
| 6-32 회귀 | 21 passed |
| `test_media_dashboard.py` | 44 passed |
| `test_performance_dashboard.py` | 7 passed |
| `test_recovery_staging.py`(6-22) | 29 passed(변경 없음) |
| `test_recovery_review_and_approval.py`(6-23) | 26 passed(변경 없음) |
| `test_audit_data_state.py`(6-21) | 11 passed(변경 없음) |
| 전체(`python -m unittest discover -s tests -p "test_*.py"`) | **1430 tests, errors=9, skipped=17** - 아래 19장에서 분류 |

## 19. 실패/오류 분류(지시사항 12장 A~G)

전체 회귀에서 나온 9개 error는 전부 **분류 C: 환경 의존**이며, 6-39가
만든 코드 회귀(A)가 아니다:

- 대상: `test_content_engine.py::LLMRewriteExperimentTests`,
  `test_knowledge_review.py::KnowledgeReviewPersistenceTests`,
  `test_media_batch.py::MediaBatchPipelineTests`(2건),
  `test_media_viewer.py::MediaViewerTests`, `test_run_scout_cli.py`,
  `test_threads_publisher.py::ThreadsPublisherTests`(2건).
- **6-39 커밋 diff에 이 6개 파일이 전혀 포함되지 않는다**
  (`git diff --stat`로 확인 - 6-39는 `content_engine/operator_summary.py`,
  `scripts/operator_control_center.py`, `scripts/run_scout_dashboard.py`,
  신규 테스트 1개, 이 문서만 건드렸다).
- 증상: `subprocess.run(..., capture_output=True, text=True, check=True)`가
  `returncode == 0`인데도 `result.stdout`이 `None`이 되어
  `assertIn(..., result.stdout)`에서 `TypeError`. **6-38에서 이미 동일한
  현상을 발견하고 원인을 분리했다** - 이번에 재검증한 결과와 완전히
  일치한다:
  - 실패한 테스트 파일을 **단독으로**(`python -m unittest tests.test_media_batch`)
    실행하면 통과한다.
  - 실패한 테스트를 **클래스 단위로**(예: `ContentEngineTests` +
    `LLMRewriteExperimentTests` + `RewriteLayerTests` 3개를 명시적으로
    나열) 실행해도 통과한다.
  - `subprocess.run`을 트레이싱 래퍼로 감싸기만 해도(로직 변경 없이) 통과한다.
  - 동일한 `subprocess.run` 호출을 REPL에서 직접 실행하면 항상 정상
    (`stdout`에 실제 내용이 들어있음)이다.
  - PowerShell로 실행해도 Git Bash와 동일하게 재현된다(shell 문제가 아님).
  - 두 번 연속 전체 실행에서 **정확히 같은 9개**가 실패한다(랜덤 flaky가
    아니라 `python -m unittest discover` 특정 실행 경로에서만 나타나는
    타이밍성 문제로 추정 - Windows 실시간 보안 스캔이 새로 spawn되는
    `python.exe` 자식 프로세스의 익명 파이프 생성에 개입하는 것으로 의심되나,
    이 저장소 코드로는 원인을 100% 확정할 수 없다).
  - **결론**: 이 6개 파일의 코드/테스트 자체에는 결함이 없다(단독/클래스
    단위 실행 100% 통과) - 노트북1의 `python -m unittest discover` 실행
    방식에 한정된 환경 의존 현상이며, 6-38 보고서의 기록과 완전히
    일관된다. skip 처리하지 않고 그대로 기록한다(지시사항 12장 준수).
- skip 17건: 전부 6-20이 이미 추가한 "Production Archive 파일이 없어 실제
  운영 데이터 회귀 테스트를 검증할 수 없다"는 기존 정책의 skip이다(분류
  D: 운영 데이터 부재 - 이 PC가 fresh clone이므로 정상). 6-39가 새로
  skip을 추가하지 않았다.

## 20. 운영자가 반드시 알아야 할 금지사항

- Production Archive가 `NOT_PRESENT`라고 임의로 빈 archive를 만들지 않는다.
- `RECOVERY_REQUIRED`가 뜨면 **먼저 원인을 조사**한다 - `git reset`/
  `git restore`로 되돌리려 하지 않는다.
- 동일 content_id를 발견해도 자동으로 한쪽을 덮어쓰지 않는다 -
  `check_promotion_conflict()`가 이미 이를 막고 있으므로, 억지로 우회하는
  코드를 짜지 않는다.
- superseded 레코드를 다시 `approved`로 되돌리지 않는다.
- Performance/Insight 파일이 git에 없다고 해서(3장 발견) 화이트리스트를
  임의로 바꾸지 않는다 - 실제 데이터가 생기고 나서 사람이 결정한다.
- Operator Control Center에서 어떤 버튼도 클릭할 수 없다(애초에 없다) -
  실제 조치는 항상 안내된 CLI 명령을 사람이 직접 실행해야 한다.

---

## 6-39 FINAL STATUS

목적:
6-21~6-23 Recovery Architecture를 실제 운영 시작 절차에 연결하고,
첫 운영일에 사람이 할 일의 순서를 확정하며, "정상적으로 비어 있음"과
"복구가 필요한 상태"를 코드로 구분 가능하게 만든다. 실제 복구는 실행하지
않는다.

핵심 발견:
1) Production Archive는 git에 한 번도 커밋된 적이 없다(STATE A, 6-21이
이미 확인 - 이번에 `git log --all`로 재확인해 Operator Center에 자동
반영). 2) Performance/Insight 스냅샷 파일이 `.gitignore` 화이트리스트에
없어 PC 간 동기화되지 않는다(`blog_publish_log.json`과 같은 성격의 정책
공백, 6-39 신규 발견). 3) Recovery Architecture(SOURCE→...→APPLY)는 이미
6-22/6-23에서 완전히 구현되어 있어 6-39가 새로 만들 필요가 없었다.

현재 운영 데이터:
Production Archive/Generation Pool/Shorts scripts/Blog draft/Performance/
Insight 전부 NOT_PRESENT(정상, STATE A). KNOWLEDGE(28)/Threads
pending(5)/publish log류는 VALID, Git으로 정상 동기화됨.

Recovery 상태:
NOT_REQUIRED(STATE A) - 이 PC는 Production Archive가 git 이력에 존재한
적이 없으므로 정상적인 fresh clone이다. 복구가 필요한 상태(STATE B/C)는
발생하지 않았다.

첫 운영일 준비 상태:
Runbook(STEP 0~14, 6-33 확장) + Scenario A~H + Dry Run 경계(이미 충분)
전부 문서화 완료. 실제 첫 실행은 `python scripts/run_scout.py`부터
시작하면 된다(Scenario A).

Operator Control Center:
6-38의 8개 영역에 RECOVERY(9번째)를 추가했다 - `/operator`와 CLI 텍스트
출력 양쪽. 여전히 완전 읽기 전용(form 없음, POST route 없음). 새 enum
없이 기존 상태(NOT_PRESENT/CORRUPTED/VALID, 6-23의 CONFLICT/
REVIEW_REQUIRED)를 재사용했고, 진짜 새 개념은 `RECOVERY_REQUIRED`
하나뿐이다.

신규 구현:
`content_engine/operator_summary.py`(`build_recovery_status()`, `OperatorInputs`
2개 필드, `OperatorSummary.recovery` 필드, `_determine_system_status()`
escalation 조건 추가) + `scripts/operator_control_center.py`
(`_ever_tracked_in_git()`, 6-22 `validate_production_archive()` 재사용
연결, RECOVERY 텍스트 출력) + `scripts/run_scout_dashboard.py`(RECOVERY
HTML 섹션). 새 스크립트/새 모듈/새 검증 로직은 만들지 않았다 - 전부
기존 6-21/6-22/6-23/6-38 함수의 재사용/집계다.

신규 테스트:
`tests/test_6_39_first_operating_day_and_data_readiness.py` - 19개, 지시사항
11장의 12개 최소 시나리오(fresh clone/데이터 부재/staging 존재/recovery
필요/production 보호/dry-run 무변경/read-only 유지/superseded 제외/
content_id 충돌/첫 운영일 readiness/UNVERIFIED/데이터 분류)를 전부
포함한다.

전체 테스트:
- total: 1430
- passed: 1404
- failed: 0
- errors: 9(전부 분류 C: 환경 의존, 19장에서 원인 분리 완료 - 6-39
  코드와 무관함을 diff로 확인)
- skipped: 17(전부 분류 D: 이 PC에 Production Archive가 없어서 발생하는
  기존 정책의 skip, 6-20부터 존재)

실패/오류 분석:
19장 참고. 9개 error 전부 Windows 노트북1의 `python -m unittest discover`
실행 방식에 한정된 `subprocess.run(capture_output=True)` 타이밍성 현상
(6-38에서 이미 동일하게 발견/기록) - 단독 실행/클래스 단위 실행 100%
통과로 코드 결함이 아님을 확인했다. 6-39가 건드린 파일 목록에 해당 6개
테스트 파일이 없다.

운영 데이터 변경:
NO (`git diff --stat -- data/`가 빈 결과, 작업 전후 `data/` 파일 목록/개수
동일)

외부 API:
NO (Threads/YouTube/Naver 어떤 것도 호출하지 않음 - `build_recovery_status()`/
`_ever_tracked_in_git()` 둘 다 로컬 git/파일시스템만 읽음)

Production Archive 변경:
NO (여전히 NOT_PRESENT, 이 세션이 생성/수정한 적 없음)

P0:
없음.

P1:
YouTube Shorts renderer 부재(6-30에서 이미 기록된 기존 P1, 6-39와 무관하게
계속 남아 있음).

P2:
1) `blog_publish_log.json`에 이어 `tak_performance.json`/
`tak_performance_insights.json`도 `.gitignore` 화이트리스트에 없어 PC 간
동기화되지 않는다(3장) - 실제 Performance 데이터가 생기면 화이트리스트
포함 여부를 사람이 결정해야 한다. 2) Apply Guard의 SHA256 drift 검사는
"REPORT 생성 후 한참 뒤에 approve/apply"하는 2단계 워크플로우를 지원하지
않는다(6-23 15장에서 이미 기록된 기존 제한, 이번에도 그대로 남김).

남은 BLOCKER:
없음(운영 시작을 막는 코드/데이터 문제 없음 - YouTube Shorts만 외부 환경
의존으로 계속 BLOCKED).

다음 작업:
1) 실제 Production Archive가 처음 생기면(사람이 KNOWLEDGE→MEDIA→승인을
실행한 뒤) 그 커밋을 사람이 직접 검토 후 commit(6-21 16장 원칙 유지).
2) Performance 데이터가 실제로 쌓이면 `.gitignore` 화이트리스트 정책을
재검토. 3) 노트북2/Codespaces에 실제로 접근 가능해지면 6-22 15장 절차로
`audit_recovery_source.py`를 실행해 실제 데이터 유무를 최초로 확인.

commit:
e8887d075531b938fde4b7906eefdbc80d7b88ac

push:
YES

HEAD == origin/main:
YES

working tree:
CLEAN

6-39_STATUS: COMPLETE
