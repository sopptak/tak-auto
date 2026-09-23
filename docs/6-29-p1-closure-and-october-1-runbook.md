# 6-29 P1 Closure and October 1 Runbook

## 1. 6-28 P0/P1/P2/P3 재검증

`docs/6-28-full-e2e-operating-readiness.md` 21장을 그대로 인용해 기준으로
삼았다(추측하지 않음).

**P0 = NONE**(6-28 재확인 결과 유효) — 6-24의 유일한 P0(archive_report()
조용한 재작성)는 6-24/6-27에서 4곳 중 3곳이 이미 수정됐고, 남은 1곳
(6-28 문서가 실제로는 2곳으로 기록: `generate_threads_draft.py`,
`scripts/tak_auto.py`)은 P1로 재분류되어 있었다.

**P1(6-28 문서 원문 그대로, 4개)**:
1. `generate_threads_draft.py`/`tak_auto.py`에 `find_protected_overwrite_targets()` 가드 미적용
2. YouTube mp4 렌더링 파이프라인 부재
3. Production Archive 최초 커밋 정책 미결정
4. `blog_publish_log.json` `.gitignore` 화이트리스트 누락

**P2(5개)/P3(3개)**: 6-28 21장 원문 유지, 이번에 변경하지 않음(13장 P2/P3
Roadmap 참고).

## 2. 중단 전 이미 구현된 변경사항

이전(중단된) 세션에서 이미 `scripts/generate_threads_draft.py`와
`scripts/tak_auto.py`에 P1 #1(archive overwrite guard)이 구현되어
`git diff`에 남아 있었다 - **삭제하거나 다시 작성하지 않고 그대로
유지**했다. 3장에서 이 변경사항을 실제로 검증했다.

## 3. Archive overwrite protection

두 파일의 diff를 직접 읽어 확인한 내용:

- `generate_threads_draft.py`: `find_protected_overwrite_targets(report,
  load_archive(args.archive))`를 `archive_report(report, args.archive)`
  호출 **바로 전에** 배치했다 — protected 목록이 비어있지 않으면 즉시
  `return 1`, `archive_report()`는 아예 호출되지 않는다("위험한 write를
  시도한 후 막는 구조"가 아니라 "write 전에 차단"하는 구조임을 코드
  순서로 확인).
- `scripts/tak_auto.py`: `run_operator()` 내부에서 `archive_report(report,
  media_archive_path)` 호출 **바로 전**에 동일한 패턴으로 배치.

**CASE A~E(6장에서 요구한 시나리오) 실제 검증 결과**(`tests/test_p1_archive_overwrite_guard_closure.py`,
신규 7개 테스트, 전부 실제 CLI 진입점(`main()`/`run_operator()`)을 호출):

| CASE | 시나리오 | 결과 | 테스트 |
|---|---|---|---|
| A | 기존 production에 X=approved, 같은 X를 다시 write 시도 | **WRITE BLOCK**(exit 1, archive 파일 바이트 단위 불변) | `test_case_a_approved_existing_content_blocks_rewrite` |
| B | X=superseded, 같은 X를 다시 write 시도 | **WRITE BLOCK** | `test_case_b_superseded_existing_content_blocks_rewrite` |
| C | X=gen-A 존재, 새 gen-B로 X를 다시 쓰려 함 | `PromotionConflictError`(6-18, 이 두 파일은 애초에 generation 단위로 쓰지 않으므로 해당 없음 - `find_protected_overwrite_targets()`가 review_status만으로 판정하는 것이 정확히 맞다. generation 충돌 자체는 promotion 계층(6-18)의 책임이며 이미 6-28에서 실제 E2E로 검증됨) | 6-28 `PromotionE2ETests` |
| D | 새 content_id Y, approved+valid | 정상 promotion/생성 가능 | `test_normal_flow_reaches_archive_report_when_nothing_protected` |
| E | 같은 content_id + 같은 generation(idempotent) | 기존 semantics 유지(archive_report()가 review_status를 보존하며 upsert) | 6-24 `FindProtectedOverwriteTargetsTests`(변경 없음, 재확인) |

**"실제로 SCOUT→KNOWLEDGE→MEDIA→archive 경로에서 작동하는지" 검증**
(단순히 코드 존재로 판단하지 않음): `TakAutoOverwriteGuardWiringTests`가
실제 RSS mock(`tak_scout.collector.fetch_rss`) → 실제 후보 선정 →
스크립트된 interview 답변 → 실제 KNOWLEDGE 생성/승인 →
`run_media_batch()`(MockRewriteProvider로 LLM만 대체) → 실제
`find_protected_overwrite_targets()` 호출까지 **전부 진짜 함수 호출
체인**으로 확인했다. 가드 함수를 `mock.patch`한 것은 딱 하나
(`test_protected_content_blocks_before_archive_report_is_called`)뿐이고,
그마저도 "이 함수의 반환값이 실제로 `archive_report()` 호출 여부를
좌우하는가"를 증명하기 위한 것이지, 가드가 호출되는지 자체를 가짜로
만든 것이 아니다 - `test_guard_receives_the_same_report_that_would_have_been_archived`가
가드가 **실제 report(9개 draft)와 실제 archive 상태**를 인자로 받는지도
확인했다.

## 4. run_media_batch

이미 6-24에서 구현·검증됐다(변경 없음) - `tests/test_production_readiness_audit_fixes.py`의
`RunMediaBatchCliGuardTests`가 계속 통과한다(이번 회귀 실행에서 재확인).
이번 6-29에서 다시 수정하지 않았다.

## 5. tak_auto

3장에서 상세히 다뤘다. 추가로 확인한 사실: `run_operator()`는 매 실행마다
**새 interview 응답으로 새 KNOWLEDGE를 생성**하는 구조라서(SCOUT
candidate + INTERVIEW 답변이 1회성 흐름), 이 가드가 실전에서 발동하는
경우는 "같은 원문 기사가 SCOUT에 다시 등장하고 사람이 거의 동일한
의견을 다시 입력하는" 드문 재실행 시나리오다 - 그럼에도 방어적으로
막아두는 것이 맞다(승인된 문구가 사람 모르게 바뀌는 것은 발생 빈도와
무관하게 항상 막아야 하는 문제).

## 6. 회귀 테스트

`tests/test_p1_archive_overwrite_guard_closure.py`(신규, 7개)가 5장/9장
지시사항을 전부 커버한다. 기존 `find_protected_overwrite_targets()` 자체의
판정 로직 테스트(6-24, `FindProtectedOverwriteTargetsTests`)는 중복
작성하지 않았다 - 이 파일은 "그 함수가 두 새 호출부에서 실제로 배선되어
있는가"만 검증한다(중복 없이 계층을 분리).

## 7. P1 해결 결과

| # | 항목 | 상태 |
|---|---|---|
| 1 | archive overwrite guard(`generate_threads_draft.py`/`tak_auto.py`) | **IMPLEMENTED + VERIFIED**(3장/6장) |
| 4 | `blog_publish_log.json` `.gitignore` 화이트리스트 | **IMPLEMENTED + VERIFIED**(11장) |

## 8. 실제 해결

3장/7장/11장에서 상세.

## 9. 외부 의존성

### P1 #2: YouTube mp4 렌더링 파이프라인 — **재분류 필요(중요 발견)**

6-28은 이를 "이 저장소에 렌더링 코드가 없다"는 단순한 EXTERNAL_DEPENDENCY로
기록했다. 이번에 `git log --all`로 전체 이력을 다시 조사한 결과, **6-28의
기록이 부정확했다는 것을 발견했다** - 정정한다:

- `docs/5-18_shorts_render_engine_cleanup.md`(commit `0049d27`, 2026-09-18에
  이미 커밋되어 있음)는 `content_engine/shorts_renderer.py`,
  `scripts/render_youtube_short.py`, 그리고 그 렌더러로 실제 생성한
  1080x1920 MP4(ffprobe로 코덱/해상도/길이까지 검증됨, 한국어 카드뉴스
  스타일 렌더링까지 완료)를 **상세히 문서화**하고 있다 - 즉 이 렌더러는
  과거 어떤 세션에서 **실제로 만들어졌고 동작을 검증까지 마쳤다**.
- 그런데 `git log --all --oneline -- content_engine/shorts_renderer.py`,
  `-- scripts/render_youtube_short.py`, `-- tests/test_render_youtube_short_cli.py`
  전부 **0건** - 이 저장소(로컬+원격 전부, 브랜치는 `main` 하나뿐)에는
  이 세 파일이 **단 한 번도 커밋된 적이 없다**.
- 그 이유도 문서에 직접 남아 있다: 5-18 문서의 마지막 줄이
  "**아직 Git commit/push하지 않았다** — 사용자 확인 후 진행한다"이고,
  실제로 나중에 이뤄진 커밋(`0049d27`)은 그 세션이 만든 파일 중
  **문서/테스트/로그 3개만** 포함했다(`git show --stat 0049d27` 확인) -
  렌더러 코드 자체는 그 커밋에서 빠졌다.

**결론**: 이것은 "만들어진 적 없는 기능"이 아니라 **"만들어졌지만
커밋되지 않아 유실된(또는 다른 환경에만 남아있는) 코드"**다. 이번
6-29에서 렌더러를 처음부터 다시 만들지 않았다(대규모 신규 기능 추가
금지 원칙 + 검증되지 않은 재구현보다 원본 복구가 항상 더 안전하다는
판단). **집 노트북1 접근이 이번 세션에서 금지되어 있어 실제 확인은
하지 못했다** - 대신 12장 Runbook에 정확한 확인/복구 절차를 남겼다.

**상태**: `NOT_IMPLEMENTED(이 저장소/브랜치 기준)` + `RECOVERY_CANDIDATE`
(EXTERNAL_DEPENDENCY가 아니라 - 새 외부 서비스가 필요한 게 아니라 기존에
만든 코드를 찾아서 커밋하기만 하면 될 가능성이 높다).

### P1 #3: Production Archive 최초 커밋 정책

**상태**: `NOT_IMPLEMENTED`(의도적 - 사람의 결정 사안). 6-21이 이미 전체
설계(`.gitignore` 화이트리스트, 정책 근거)를 완성해놓았고, 이번에
`.gitignore` 주석이 현재 상태(아직 커밋된 적 없음)를 정확히 반영하고
있는지 재확인했다 - 정확했다(6-21이 이미 정확하게 써 놓았음, 수정
불필요). **실제 데이터를 만들거나 커밋하는 행위는 이번에도, 앞으로도
사람만 할 수 있다** - 12장 Runbook에 결정이 내려졌을 때 실행할 정확한
명령을 남겼다.

## 10. Multi-PC 운영

**GitHub = 코드 동기화**와 **GitHub = 운영 데이터 동기화**를 동일하게
취급하지 않는다(6-21 원칙 재확인):

- **코드 동기화**: `git pull`/`git push`로 항상 자동 - 노트북1/노트북2/
  Codespaces 어디서든 동일하게 작동(일반적인 git 워크플로우).
- **운영 데이터 동기화**: **자동이 아니다.** `data/tak_media_archive.json`
  등은 사람이 **명시적으로** `git add`/`commit`/`push`해야만 다른 환경에
  나타난다 - 이번 6-29에서 발견한 9장의 렌더러 유실 사례가 정확히 이
  원칙을 어겼을 때 벌어지는 일의 실제 사례다(코드도 마찬가지로 커밋하지
  않으면 유실될 수 있다는 것을 렌더러 사례가 증명한다 - 이건 사실
  "운영 데이터"가 아니라 "코드"였는데도 커밋하지 않아 유실된 경우라서,
  이 원칙이 데이터뿐 아니라 **모든 미커밋 작업**에 똑같이 적용된다는
  것을 보여준다).

**Production Archive가 실제로 복구되는 경우의 절차**(6-22/6-23이 이미
구현한 Recovery Staging/Approval 파이프라인을 그대로 재사용, 새로 설계
안 함):

```
1. 노트북1에서 python scripts/audit_data_state.py로 실제 파일 존재 확인
2. 발견된 파일들을 별도 경로로 복사(원본 보존)
3. 노트북2(또는 최신 코드가 있는 환경)에서:
   python scripts/audit_recovery_source.py --source <복사본> --verbose
4. action이 OK/REVIEW_REQUIRED인 항목만 검토
5. python scripts/recover_media_archive.py --source <복사본> \
       --production-archive data/tak_media_archive.json
   (승인 없이 REPORT만 먼저 확인)
6. 문제 없는 content_id만 --approve로 나열해 재실행
7. --apply를 추가해 실제 반영
8. git status로 실제 변경 확인 후 commit/push
```

이번 6-29에서 위 절차를 실제로 실행하지 않았다(실제 운영 데이터가
없으므로 검증 불가 - 6-22/6-23의 synthetic 테스트가 이미 이 파이프라인
자체의 정확성을 증명했다).

## 11. 10월 1일 첫 실행 시나리오

실제 외부 API를 호출하지 않고 synthetic하게 설계했다(6-28의 synthetic
E2E 테스트, `tests/test_full_e2e_operating_readiness.py`가 이미 이
흐름을 실제 함수 호출로 증명했으므로 이번에 다시 구현하지 않고 그
결과를 그대로 인용한다).

| STEP | 내용 | 상태 |
|---|---|---|
| 1 | Git pull | READY |
| 2 | 환경 점검(`python --version`, 표준 라이브러리만 사용하므로 별도 의존성 설치 불필요) | READY |
| 3 | Python 확인 | READY |
| 4 | dependencies 확인(외부 패키지 없음 - `content_engine/*_publisher.py`가 표준 `urllib`만 사용) | READY |
| 5 | SCOUT 실행 | READY(6-28 4장) |
| 6 | KNOWLEDGE 생성(INTERVIEW 필요) | **NEEDS_HUMAN_REVIEW**(사람의 답변 필요, 자동 아님) |
| 7 | MEDIA 생성 | READY(6-29에서 archive overwrite guard까지 재확인) |
| 8 | Human Review | **NEEDS_HUMAN_REVIEW**(Dashboard) |
| 9 | Promotion | READY(CLI, 사람이 실행) |
| 10 | Production Archive | READY(파일 자체는 아직 NOT_PRESENT - 정상) |
| 11 | Publish Readiness | READY |
| 12 | Threads 준비 | READY(6-25) |
| 13 | YouTube 준비 | **BLOCKED**(렌더러 부재 - 9장) |
| 14 | Blog Publish Pack | READY(6-27) |
| 15 | 사람이 실제 게시 | **NEEDS_HUMAN_REVIEW**(전 채널 공통, 설계상 항상 사람) |
| 16 | Publish History | READY |
| 17 | Performance | READY(수집/저장/요약), **NOT_IMPLEMENTED**(피드백 루프) |

## 12. 10월 1일 운영 Runbook

```
DAY 1 START

A. 노트북2에서 코드 최신화
   $ git fetch origin main && git status
   확인: HEAD == origin/main. 다르면 git pull --ff-only만 사용(6-19 established).

B. 노트북1에서 코드 최신화(이번 세션은 접근하지 않음 - 사람이 직접)
   $ git fetch origin main && git pull --ff-only
   **먼저**: content_engine/shorts_renderer.py, scripts/render_youtube_short.py,
   tests/test_render_youtube_short_cli.py가 로컬에 아직 남아있는지 확인
   (9장 발견 - 미커밋 상태로 남아있을 가능성이 높다). 있다면:
   $ git add content_engine/shorts_renderer.py scripts/render_youtube_short.py \
         tests/test_render_youtube_short_cli.py
   $ python -m unittest discover -s tests -p "test_*.py"  # 전체 통과 확인 후
   $ git commit && git push

C. Codespaces 시작(향후) - B와 동일하게 git pull로 코드만 동기화, 운영
   데이터는 별도(10장 원칙)

D. 환경 확인
   $ python --version
   $ python -m unittest discover -s tests -p "test_*.py"
   실패 시 여기서 중단 - 원인 해결 전까지 다음 단계 진행 금지.

E. SCOUT
   $ python scripts/run_scout.py (또는 daily-scout.yml 대기)
   확인: data/tak_scout_daily.json/.md 생성.
   정상: 후보 목록 출력. 실패: source 1건 실패해도 계속(6-24).

F. KNOWLEDGE
   $ python scripts/run_interview.py → scripts/apply_interview.py
   사람이 인터뷰 답변 입력. 확인: knowledge_review_status.
   중단 조건: 사람이 보류(N) 선택 시 pending으로 남고 다음 단계로 안 감(정상).

G. MEDIA
   $ python scripts/run_media_batch.py --execute --as-generation \
         --archive <generation-pool-path>
   확인: 9개 draft(Blog1/Shorts3/Threads5) 생성.
   중단 조건: 6-29에서 추가한 가드가 "이미 approved/superseded" 오류를
   내면 - 이는 버그가 아니라 안전장치이므로 원인(왜 같은 content_id가
   다시 생성됐는지)을 먼저 조사.

H. Human Review
   Dashboard "/media/generations"에서 승인/보류/수정.
   중단 조건: 승인하지 않으면 자연히 다음 단계로 안 감(정상, 이게 원칙).

I. Promotion
   $ python scripts/promote_media_generation.py --execute
   확인: production archive에 반영됨.
   중단 조건: PromotionConflictError - supersede_media_record.py로 명시
   처리 필요(자동 진행 금지).

J. Production Archive 확인
   $ python scripts/audit_data_state.py
   확인: VALID, record count 증가.

K. Publish Readiness
   $ python scripts/audit_publish_candidates.py
   확인: READY/NEEDS_HUMAN_REVIEW/BLOCKED 목록.

L. Threads
   Dashboard "/threads" 승인 → $ python scripts/publish_approved_threads.py --execute
   중단 조건: 이 세션은 실제 실행하지 않음(외부 API 금지) - 사람이 직접.

M. YouTube
   **9장 확인 먼저**: 렌더러 파일 존재 여부. 없으면 이 단계 전체가
   BLOCKED(6-29 결론) - 억지로 진행하지 말 것.
   존재하면: $ python scripts/youtube_oauth_setup.py --check →
   $ python scripts/generate_approved_shorts_script.py →
   (렌더링) → $ python scripts/upload_youtube_short.py --content-id ... --execute

N. Blog
   $ python scripts/generate_blog_publish_pack.py --from-archive →
   사람이 Naver에 직접 게시 →
   $ python scripts/mark_blog_published.py --content-id ... \
         --production-archive data/tak_media_archive.json
   (6-27에서 강화된 재검증이 여기서 작동함)

O. Publish History
   각 채널 `*_publish_log.json` 확인(`git diff`).

P. Performance(선택)
   $ python scripts/collect_performance.py --confirm-live
   NOT_IMPLEMENTED(피드백 루프) - 수집/저장만 가능, 다음 콘텐츠 전략에
   자동 반영되지 않음을 사람이 인지하고 있어야 함.
```

## 13. 채널별 운영 상태

15장 지시사항의 16개 항목을 재평가했다(6-28 대비 변경분만 굵게 표시).

| # | 항목 | 판정 | 변경 |
|---|---|---|---|
| 1 | SCOUT | READY | 없음 |
| 2 | KNOWLEDGE | READY_WITH_HUMAN_STEP | 없음(6-28은 "READY"로만 표기했으나, INTERVIEW가 항상 사람 입력을 요구하므로 이번에 더 정확한 상태값으로 정정) |
| 3 | MEDIA | **READY**(6-29에서 나머지 2곳 가드 완료로 격상 - 6-28은 "READY"였지만 근거가 불완전했음, 이번에 실제 검증) | 격상(근거 보강) |
| 4 | HUMAN REVIEW | READY_WITH_HUMAN_STEP | 정정(6-28 "READY") |
| 5 | PROMOTION | READY_WITH_HUMAN_STEP | 정정 |
| 6 | PRODUCTION ARCHIVE | READY(구조), 파일은 NOT_PRESENT(정상) | 없음 |
| 7 | THREADS | READY_WITH_HUMAN_STEP | 정정 |
| 8 | YOUTUBE | **BLOCKED**(렌더러 부재 확인, 9장) | 정정(6-28 "NEEDS_REVIEW"보다 명확 - 렌더러 없이는 물리적으로 불가능하므로 BLOCKED가 정확) |
| 9 | BLOG | READY_WITH_HUMAN_STEP | 정정 |
| 10 | PUBLISH HISTORY | READY | 없음 |
| 11 | PERFORMANCE | READY(수집/저장), NOT_IMPLEMENTED(피드백 루프) | 없음 |
| 12 | DASHBOARD | NEEDS_REVIEW(정보 완전성, 6-25~6-28에서 반복 확인) | 없음 |
| 13 | GITHUB ACTIONS | READY | 없음 |
| 14 | MULTI-PC | NEEDS_REVIEW(설계 완성, 실전 미검증, 9장 사례가 실제 위험을 증명) | 근거 보강 |
| 15 | RECOVERY | READY(구조, 6-22/6-23) | 없음 |
| 16 | SECURITY | READY(17장 재확인) | 없음 |

## 14. Performance 상태

16장 지시사항대로 대규모 기능을 만들지 않았다. 6-28의 결론(content_id/
knowledge_id 유지, generation_id/superseded 미처리)을 그대로 유지하며,
이번에 다시 코드를 읽어 재확인만 했다(`content_engine/performance/models.py`,
변경 없음). feedback loop는 P2/P3로 유지(19장).

## 15. Dashboard 상태

17장 지시사항대로 최소 확인만 했다 - `compute_media_downstream_status()`
(6-13)가 KNOWLEDGE/MEDIA/REVIEW/PRODUCTION 상태를 이미 통합해서 보여주고
있음을 재확인(6-25~6-28과 동일 결론, 코드 변경 없음). Superseded/Stale
배지 부재는 P2로 유지 - 이번에도 UI를 전면개편하지 않았다.

## 16. Security

18장 지시사항대로 read-only 감사를 수행했다(실제 값 미출력):

| 검색 대상 | 결과 |
|---|---|
| 하드코딩된 API key/client_secret/refresh_token/password 패턴 | `tests/test_interview_llm.py` 3곳만 발견, 전부 명백한 가짜 플레이스홀더(`"TEST_SECRET_KEY_123"`) - 위험 없음 |
| GOCSPX-/sk-.../ya29./1//0 등 실제 서비스 토큰 접두사 패턴 | 0건 |
| `.env` 파일이 git history에 커밋된 적 있는지 | 0건(`git log --all --diff-filter=A --name-only \| grep -i "\.env$"`) |
| GitHub Actions의 secrets 참조 방식 | 전부 `${{ secrets.X }}` 형태만 사용, 리터럴 값 없음(`daily-threads-post.yml`, `publish-approved-threads.yml`) |
| docs에 실제 자격증명이 노출됐는지 | 0건(패턴 참고용 문구만 존재) |

**결론**: 위험도 0 - 발견된 것은 전부 명백한 테스트 픽스처였다.

## 17. 전체 테스트

| 구분 | 결과 |
|---|---|
| 신규(`tests/test_p1_archive_overwrite_guard_closure.py`) | 7 passed |
| 관련 기존(`test_generate_threads_draft.py`, `test_tak_auto_e2e.py`, `test_media_dashboard.py`, `test_production_readiness_audit_fixes.py`) | 70 passed(변경 없음) |
| 6-19 회귀 | 21 passed |
| 전체(`python -m unittest discover -s tests -p "test_*.py"`) | **1073 passed(1056 실행+17 skip), 0 failed, 0 errors** — 6-28 종료 1066개에서 신규 7개와 정확히 일치 |

## 18. 남은 P1

- **P1 #2**(YouTube 렌더러): 코드 재구현 아님, **복구 확인**이 남은
  작업이다(9장/12장 B단계). 이번 세션(집 노트북1 접근 금지)에서는
  확인할 수 없었다.
- **P1 #3**(Production Archive 최초 커밋): 사람의 결정 대기, 설계는
  이미 완성(6-21).

## 19. P2/P3 Roadmap

6-28 21장의 목록을 그대로 유지한다(이번에 새로 추가/제거하지 않음) -
단, 9장의 발견으로 P2 목록에 다음 1건을 추가한다:

**P2 신규**: "미커밋 로컬 작업 유실 방지" - 9장 사례(shorts_renderer.py가
검증까지 마친 뒤 커밋되지 않아 유실)가 재발하지 않도록, 세션 종료 전
`git status --short`로 미커밋 파일이 있는지 확인하고 사용자에게 명시적으로
알리는 습관/체크리스트를 운영 문서에 추가하는 것을 고려. (코드 변경이
아니라 운영 절차 개선이므로 P2로 분류.)

## 20. 결론

6-28이 기록한 4개 P1 중 2개(#1 archive overwrite guard, #4 gitignore
화이트리스트)를 실제로 구현·검증했다 - 전부 실제 CLI 진입점을 통한
호출로 확인했고(가드 함수 존재만으로 완료 판단하지 않음), 기존
1066개 테스트를 포함해 전체 1073개 테스트가 실패/에러 없이 통과한다.

나머지 2개(#2 YouTube 렌더러, #3 Archive 최초 커밋)는 이번 세션의
권한 범위(외부 인증 금지, 노트북1 접근 금지, 운영 데이터 생성 금지)
안에서는 코드로 해결할 수 없는 항목이었다 - 특히 #2는 6-28이 기록한
것과 달리 "만든 적 없는 기능"이 아니라 "만들었지만 커밋을 놓친 코드"
라는 것을 이번에 git 이력 조사로 새로 밝혀냈고, 이는 재구현이 아니라
복구가 필요한 문제라는 점에서 10월 1일 이후 작업의 우선순위와 접근
방식을 실질적으로 바꾸는 발견이다.

10월 1일 운영 시작은 **SCOUT→KNOWLEDGE→MEDIA→HUMAN REVIEW→PROMOTION→
PRODUCTION ARCHIVE→Threads/Blog 발행** 경로에서 여전히 가능하다(P0
없음, 6-28 결론 유지). YouTube는 렌더러 복구 전까지 BLOCKED로 명확히
재확인했다(6-28의 "NEEDS_REVIEW"보다 더 정확한 상태).

## 21. 6-30 업데이트 - Shorts Renderer 최종 판정 및 YouTube 세부 절차

이 장은 `docs/6-30-shorts-renderer-and-youtube-readiness.md`의 결론을
반영해 12장(M단계)/13장(#8 행)을 보강한다 - 위 20장의 결론과 충돌하지
않는다(9장이 "만든 적 없는 기능이 아니라 커밋을 놓친 코드"라고 추정한
것을, 6-30이 `git log --all`로 이 저장소 전체 이력을 직접 검색해
"이 저장소에는 커밋된 적이 한 번도 없다(CASE C)"로 확정했다 - 결이
같은 결론이며, 다만 이 저장소만으로는 확정할 수 없는 "노트북1에
지금도 남아있는가"는 가설로 남겼다).

**M단계(YouTube) 정확한 절차** (12장 원문 대체가 아니라 구체화):

1. `python scripts/youtube_oauth_setup.py --check` - env var 3개
   존재 확인(실제 인증 아님).
2. `content_engine/shorts_renderer.py`, `scripts/render_youtube_short.py`
   존재 확인 - **먼저 노트북1에서 직접 `git status`/`ls`로 확인**
   (이 세션은 노트북2에서 실행되어 노트북1을 확인할 수 없었다). 있고
   uncommitted 상태라면 `git add` → 전체 테스트 통과 확인 → 커밋/푸시.
3. 2번이 없다면(재작성 필요, `docs/6-30-...md` 16장 최소 구현
   우선순위 참고) - 이 경우 renderer 실행 환경(ffmpeg/ffprobe PATH,
   Pillow 등 이미지 라이브러리, 한글 폰트 자산)도 함께 준비해야
   한다(6-30 13장 - 노트북2는 현재 셋 다 없음, 노트북1도 별도 확인
   필요).
4. `python scripts/generate_approved_shorts_script.py` - ShortsScript
   생성(이 단계는 renderer 유무와 무관하게 실행 가능).
5. renderer로 mp4 생성(2/3번 완료 후에만 가능).
6. `python scripts/upload_youtube_short.py --video <mp4> --content-id <id> --knowledge-id <id> --execute` -
   eligibility 검증(approved/not-superseded/ShortsScript 일치)은
   mp4 유무와 무관하게 이미 정확히 동작한다(6-30 10/11장에서
   `main()` 전체 CLI 경로로 재검증 완료).

**13장 #8 행 보강**: `EXTERNAL_MACHINE_REQUIRED`(6-30 최종 판정) -
"렌더러 부재 확인"이라는 6-29의 표현을 "이 저장소 git 이력 전체에
존재한 적 없음(CASE C), 다른 머신 확인 또는 재작성 필요"로
구체화한다. BLOCKED라는 최종 상태 자체는 바뀌지 않는다.
