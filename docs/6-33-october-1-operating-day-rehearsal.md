# 6-33 October 1 Operating Day Rehearsal

## 1. 목적

10월 1일 실제 운영 첫날, 코드를 모르는 운영자가 최소한의 판단과
조작만으로 SCOUT→KNOWLEDGE→MEDIA→HUMAN REVIEW→PROMOTION→PRODUCTION
ARCHIVE→PUBLISH READINESS를 운영할 수 있는지 실제 운영자 관점에서
끝까지 검증한다. 새 기능을 많이 만들지 않았다 - 6-28/6-31/6-32가 이미
구축한 fixture와 함수를 최대한 재사용했고, 새로 만든 것은 딱 하나
(읽기 전용 상태 요약 CLI)뿐이다. 실제 외부 API/OAuth/네트워크는
호출하지 않았고, 실제 운영 데이터(`data/`)는 어디에서도 생성/수정하지
않았다.

First Sync Check: `git status --short`(clean), HEAD==origin/main
(9daebac) 확인 후 시작했다.

## 2. 현재 시스템 상태

6-32 결과를 그대로 이어받는다: SCOUT READY, KNOWLEDGE
READY_WITH_HUMAN_STEP, MEDIA READY, Generation Pool/content_id/
generation_id/Human Review/Content Safety/LLM failure handling/
Partial Generation/Regeneration/First Content Rehearsal/Failure
Injection 전부 VERIFIED, Performance NOT_IMPLEMENTED, Dashboard
IMPLEMENTED(SCOUT/MEDIA), YouTube BLOCKED(Shorts Renderer 없음,
6-30/6-31에서 EXTERNAL_MACHINE_REQUIRED→REBUILD_REQUIRED로 판단
갱신). 이번 세션은 이 상태를 바꾸지 않고, "운영자가 실제로 이걸
어떻게 쓰는가"를 검증한다.

## 3. 10월 1일 실제 운영 흐름

개발자가 아니라 "코드를 모르는 운영자" 관점에서 처음부터 끝까지
목록화했다(4장 First Run 시나리오로 synthetic 검증 완료).

| # | 단계 | 실제 명령 | 사람이 판단할 부분 | 실패 시 |
|---|---|---|---|---|
| 1 | 저장소 sync | `git fetch origin main && git status` | HEAD!=origin/main이면 pull 여부 | 충돌 시 조사 |
| 2 | SCOUT 실행 | `python scripts/run_scout.py` | 없음(자동) | source 1건 실패해도 계속 |
| 3 | 결과 확인 | `python scripts/show_operating_status.py`(6-33 신규) 또는 Dashboard `/` | 후보가 0건이면 오늘은 소재 없음 | - |
| 4 | KNOWLEDGE 후보 선택 | `python scripts/run_interview.py` | 어떤 뉴스를 다룰지, A/B/C/D 관점 선택 | - |
| 5 | KNOWLEDGE 승인 | `python scripts/review_knowledge.py --id <id> --approve` | 원문이 충분한가, source/evidence가 있는가 | - |
| 6 | MEDIA 생성 | `python scripts/run_media_batch.py --execute --as-generation --archive <pool>` | 없음(자동, 9개 생성) | LLM 설정 오류 시 exit 1 |
| 7 | Generation Pool 확인 | Dashboard `/media/generations` 또는 상태 CLI | 9개가 다 만들어졌는지 | - |
| 8 | Human Review | Dashboard `/media/generations` | 사실 오류, 금융/부동산 위험, 새 사실 여부 | - |
| 9 | 수정 | Dashboard 수정 폼 | 제목/본문 직접 수정 | - |
| 10 | 승인 | Dashboard 승인 버튼 또는 "전체 승인" | approved로 전이 | - |
| 11 | Promotion | `python scripts/promote_media_generation.py --archive <pool> --generation-id <id> --content-id <id> --execute` | approved인가, conflict 없는가 | dry-run 기본, `PromotionError`/`PromotionConflictError` |
| 12 | Publish Readiness | `python scripts/audit_publish_candidates.py` | READY/BLOCKED/NEEDS_HUMAN_REVIEW 구분 | - |
| 13 | 실제 게시 준비 | 채널별(12/13/14장) | Threads=사람이 --execute, YouTube=BLOCKED, Blog=copy-paste | - |

## 4. 운영자 명령 목록

`scripts/` 26개 CLI를 필요/개발용/불필요로 분류했다(실제 코드 기준,
docstring 1차 조사 + 사용처 확인).

**10월 1일 실제로 필요한 명령(11개)**:
`run_scout.py`, `run_interview.py`, `apply_interview.py`,
`review_knowledge.py`, `run_media_batch.py`,
`run_scout_dashboard.py`(Human Review), `promote_media_generation.py`,
`audit_publish_candidates.py`, `generate_threads_draft.py`+
`publish_approved_threads.py`, `generate_blog_publish_pack.py`+
`mark_blog_published.py`, `show_operating_status.py`(6-33 신규,
6장/20장).

**개발/디버깅용(10월 1일에는 불필요)**: `experiment_llm_rewrite.py`,
`view_media_batch.py`, `audit_data_state.py`(장애 시에만),
`audit_recovery_source.py`/`recover_media_archive.py`(복구 시나리오
전용), `supersede_media_record.py`(정정 필요 시에만),
`generate_knowledge.py`/`create_knowledge.py`(블로그 RAW 임포트
경로, SCOUT 경로와 다름), `import_posts.py`/`import_naver_rss.py`/
`collect_naver_raw.py`/`check_naver_post.py`(별도 RAW 수집 경로),
`prepare_approved_media.py`(오케스트레이터, 아래 참고),
`generate_approved_shorts_script.py`+`youtube_oauth_setup.py`+
`upload_youtube_short.py`(YouTube - BLOCKED이므로 10월 1일 실행
대상 아님), `publish_threads.py`(legacy, run_daily.py 전용),
`run_daily.py`/`tak_auto.py`(완전 자동 오케스트레이터 - 아래 참고).

**`python scripts/run_tak_auto.py first-run` 같은 통합 명령이 실제로
도움이 되는가?** 조사 결과 이미 유사한 오케스트레이터가 2개
존재한다(`scripts/run_daily.py`: KNOWLEDGE→MEDIA→Threads 자동 게시
까지, `scripts/tak_auto.py`: SCOUT→INTERVIEW→KNOWLEDGE→승인→MEDIA).
둘 다 "사람이 승인 단계에서 멈추지 않고 끝까지 자동 진행"하는 것을
전제로 설계되어 있어, 10월 1일처럼 **각 단계마다 사람이 판단해야
하는 첫 실행**에는 오히려 맞지 않는다(운영자가 뭘 승인했는지 모른 채
다음 단계로 넘어갈 위험). 기존 구조를 깨뜨리면서까지 새 통합 CLI를
만들 필요는 없다고 판단했다 - 대신 "지금 어디까지 왔는지" 보여주는
**읽기 전용** 상태 CLI 하나만 추가했다(6장).

## 5. 운영자 판단 지점

| 단계 | 판단 |
|---|---|
| SCOUT | 어떤 뉴스를 선택하는가(INTERVIEW에서 A/B/C/D 관점 선택) |
| KNOWLEDGE | 원문이 충분한가, source/evidence가 있는가, 콘텐츠로 만들 가치가 있는가 |
| MEDIA | 사실 오류가 없는가, 금융/부동산 위험 콘텐츠인가, AI가 새 사실을 만들지 않았는가(6-32에서 "경험" false positive 수정 완료) |
| HUMAN REVIEW | 제목/본문 수정, 승인, dismiss |
| PROMOTION | approved인가, superseded가 아닌가, conflict가 없는가(9장 CASE A~G로 전부 synthetic 검증) |
| Publish Readiness | READY/BLOCKED/NEEDS_HUMAN_REVIEW 구분(11장 매트릭스) |

## 6. SCOUT

입력: `data/scout_sources.json`(RSS 주소). 실제 명령:
`python scripts/run_scout.py`. 결과 확인은 6-33에서 새로 추가한
`python scripts/show_operating_status.py`(또는 Dashboard `/`)로
"오늘 몇 건 수집됐는지"를 바로 볼 수 있다(이전에는 파일을 직접 열어
확인해야 했다).

## 7. KNOWLEDGE

`python scripts/run_interview.py` → `apply_interview.py` →
`review_knowledge.py --pending`(대기 목록) → `--id <id> --approve`
(승인). `scripts/show_operating_status.py`가 pending 건수를 바로
보여준다.

## 8. MEDIA

`python scripts/run_media_batch.py --execute --as-generation --archive <pool>`.
Blog 1 + Shorts 3 + Threads 5 = 9개 생성(6-28/6-31/6-32에서 반복
검증, 변경 없음).

## 9. Human Review

8장 질문에 대한 답(실제 코드 기준, `scripts/run_scout_dashboard.py`):

1. **9개를 하나씩 승인해야 하는가?** 아니오 -
   `handle_generation_approve_all_submission()`(POST
   `/media/generations/generation/{id}/approve-all`)가 이미 존재한다 -
   generation 전체를 한 번에 승인할 수 있다(VALID+아직 미승인인
   것만, REJECTED/ERROR는 대상 제외).
2. **generation-wide approval이 가능한가?** 예(위와 동일).
3. **edit → approve가 가능한가?** 예 -
   `handle_generation_edit_submission()`으로 제목/본문을 수정한 뒤
   `handle_generation_review_submission()`으로 승인하는 2단계 흐름을
   4장 First Run 시나리오에서 실제로 검증했다.
4. **dismiss 처리가 가능한가?** 예 -
   `handle_generation_review_submission(..., "dismissed")`.
5. **승인 후 promotion은 별도 단계인가?** 예 - Dashboard의
   승인(review_status 전이)과 `scripts/promote_media_generation.py`
   (production archive 반영)는 완전히 분리된 CLI/화면이다.
6. **운영자가 실수하기 쉬운 부분?** (a) `--as-generation` 없이
   `run_media_batch.py`를 다시 실행하면 이미 approved인 content_id를
   덮어쓸 뻔하지만 6-24 가드가 exit 1로 막는다(6-32에서 CLI 레벨
   재확인). (b) promotion에서 `--execute`를 깜빡해도 안전하다 -
   기본값이 dry-run이다(10장). (c) generation_id를 잘못 지정하면
   `PromotionError`("찾을 수 없습니다")로 명확히 실패한다(자동으로
   엉뚱한 generation을 승격하지 않는다).

**결론: 배치 승인/개별 수정/dismiss 전부 이미 구현되어 있다** - 이번
세션에서 새 Human Review 기능을 추가하지 않았다(이미 충분함을
확인만 했다).

## 10. Promotion 운영성

`scripts/promote_media_generation.py`의 실제 옵션: `--archive`(필수,
generation pool 경로), `--production-archive`(단건 승격 시 생략하면
`data/tak_media_archive.json` 기본값 - **batch 승격은 안전을 위해
반드시 명시해야 하며 기본값이 없다**, 6-09 설계), `--content-id`
(생략 시 batch), `--generation-id`(필수), `--execute`(생략 시
dry-run).

**"절대로 발생하면 안 되는 4가지"를 신규 테스트로 직접 검증했다**
(`DryRunFilesystemProtectionTests`, `ApprovalMatrixTests`):

- dry-run 명령 → production 변경: **발생하지 않음** - `--execute`
  없이 실행하면 production archive 파일 자체가 생성되지 않는다
  (`test_dry_run_promotion_writes_nothing`).
- unreviewed → production: **발생하지 않음** - `plan_promotion()`이
  `PromotionError`(CASE A).
- invalid(rejected/error) → production: **발생하지 않음** -
  동일하게 `PromotionError`(CASE D).
- superseded → production: **발생하지 않음** - superseded는애초에
  Production Archive에 승격된 이후에만 생기는 상태이므로 다시
  promotion 대상이 되지 않는다(생성 pool에는 이 값이 없다).

## 11. Publish Readiness

`content_engine.publish_audit.audit_archive()`의 우선순위(ERROR>
ALREADY_PUBLISHED>SUPERSEDED>BLOCKED>NEEDS_HUMAN_REVIEW>READY, 6-14/
6-17/6-19)를 synthetic matrix로 재확인했다(`PublishReadinessMatrixTests`):
approved+published→`ALREADY_PUBLISHED`(superseded보다 우선),
approved+invalid(generation_status="rejected")→`BLOCKED`, unreviewed→
`BLOCKED`, content_id 중복→`ERROR`. 기존 semantics를 바꾸지 않았다.

## 12. Threads

공식 경로(`scripts/generate_threads_draft.py` → 사람 승인 →
`scripts/publish_approved_threads.py --execute`)와 레거시 경로
(`scripts/publish_threads.py`, `run_daily.py`가 호출)를 코드로
구분했다. **두 경로가 6-25에서 정확히 같은
`content_engine.publish_eligibility.check_content_supersede`
함수 객체를 공유함을 `assertIs()`로 직접 확인했다** - 공식/레거시
어느 쪽으로 게시해도 supersede 차단 정책이 동일하게 적용된다.
CASE(approved+not published→ELIGIBLE, superseded→BLOCKED, orphan
pending→차단 안 됨, content_id 충돌) 전부 synthetic으로 재확인했다.
외부 API는 호출하지 않았다.

## 13. YouTube

현재 상태(`BLOCKED`, Shorts Renderer=`EXTERNAL_DEPENDENCY`/
`REBUILD_REQUIRED`, 6-30/6-31)를 그대로 유지한다 - 이번 세션에서
renderer를 구현하지 않았다. 운영자가 READY/BLOCKED/
EXTERNAL_DEPENDENCY를 쉽게 구분할 수 있도록 `show_operating_status.py`
(6-33 신규)가 항상 "YouTube: BLOCKED(Shorts Renderer 없음, docs/6-30
참고)"를 고정 출력한다 - 운영자가 별도로 파일을 찾아보지 않아도
현재 상태를 한 줄로 알 수 있다.

## 14. Blog

`content_engine.blog_publish_pack.build_blog_publish_pack_from_archive()`가
approved+not superseded+valid Blog 레코드만 Pack에 포함함을 신규
테스트로 재확인했다(`BlogPackCandidateTests`) - unapproved/
superseded/invalid(generation_status="error") 3가지 모두 Pack에서
제외됨을 확인했다. 10월 1일 실제 작업은 여전히 Production Archive→
approved Blog candidate→Publish Pack→사람이 복사→Naver Blog 게시
순서다(자동 게시 없음, 의도된 설계).

## 15. Traceability

`TraceabilityTest`가 하나의 synthetic 콘텐츠로 전체 체인을 확인했다.
실제 synthetic ID 예시(테스트에서 그대로 생성됨):

```
source_url = https://example.test/trace-1
-> scout_id = scout-trace-1
-> knowledge_id = knowledge-scout-<sha256(scout_id:A:)[:12]>
-> content_id = content-<sha256 기반 8자리>
-> generation_id = gen-<타임스탬프 기반>
-> platform = threads
-> review_status = (Human Review에서 결정)
-> production = MediaArchiveRecord(content_id, knowledge_id, generation_id 전부 보존)
-> publish readiness = READY(승인 후)
```

이 체인이 향후 Performance 연결의 핵심이다(6-32 20장과 동일한 결론,
이번에 실제 ID 형태까지 구체적으로 기록했다).

## 16. Failure Rehearsal

| CASE | 증상 | 원인 | 운영자 행동 | 재시작 위치 |
|---|---|---|---|---|
| 1 | GitHub sync 실패 | `git pull` 충돌 | 수동 조사(자동 삭제 금지) | git 상태 확인 후 |
| 2 | SCOUT 결과 0건 | source 전부 실패 또는 오늘 새 기사 없음 | 정상 종료 확인, 내일 재시도 | SCOUT부터 |
| 3 | KNOWLEDGE 승인 없음 | 사람이 아직 판단 안 함 | 대기(정상) | KNOWLEDGE 승인부터 |
| 4 | LLM generation 실패 | env var 누락/네트워크 오류 | `OpenAICompatibleRewriteProvider.from_environment()` 오류 메시지 확인 | 원인 해결 후 MEDIA부터 |
| 5 | 9개 중 일부 실패 | 개별 draft 예외(6-32 15/16장) | 성공분만 검토 진행, 실패분은 재실행으로 재생성 | Human Review부터(성공분) |
| 6 | Human Review 미완료 | 사람이 아직 승인 안 함 | 자연히 다음 단계로 안 감(정상) | Human Review부터 |
| 7 | Promotion conflict | 같은 content_id 다른 generation | `supersede_media_record.py`로 명시 처리 | Promotion부터(충돌 해결 후) |
| 8 | Publish Readiness BLOCKED | review_status 미승인 등 | 원인 확인(unreviewed/dismissed/rejected) | Human Review 또는 Promotion부터 |
| 9 | Threads 이미 게시 | `is_published()` True | idempotent, 재게시 안 함(정상) | 다음 콘텐츠로 |
| 10 | YouTube renderer 없음 | 6-30 확정 사실 | Threads/Blog로 계속 진행, YouTube만 보류 | 해당 없음(구조적 BLOCKED) |
| 11 | Blog Pack 생성 실패 | approved Blog 후보 0건 등 | "생성할 후보 없음" 정상 메시지 확인 | Human Review부터 |

## 17. Resume / Restart

`ResumeRestartTests`(신규)로 확인했다: MEDIA generation 완료 후
프로세스가 재시작되어도 generation pool 파일이 디스크(또는 git
커밋)에 남아있으므로 다시 읽어 Human Review부터 이어갈 수 있다(MEDIA
를 중복 생성할 필요 없음). Promotion 완료 후 재시작도 같은
content_id/generation_id로 다시 promotion을 시도하면 idempotent하게
동작한다(현재 active generation_id를 그대로 반환, 에러 없음) -
Publish Readiness부터 재개하면 된다.

| 완료된 단계 | 재개 위치 |
|---|---|
| SCOUT 완료 | KNOWLEDGE부터 |
| KNOWLEDGE 승인 완료 | MEDIA부터 |
| MEDIA generation 완료 | Human Review부터(generation pool 파일 재사용) |
| Human Review 완료 | Promotion부터 |
| Promotion 완료 | Publish Readiness부터(idempotent 재시도 안전) |

## 18. 운영 체크리스트

```
[ ] Git sync             - git fetch origin main && git status
[ ] SCOUT                - python scripts/run_scout.py
[ ] 후보 확인             - python scripts/show_operating_status.py (또는 Dashboard "/")
[ ] KNOWLEDGE 승인        - python scripts/review_knowledge.py --id <id> --approve
[ ] MEDIA generation      - python scripts/run_media_batch.py --execute --as-generation --archive <pool>
[ ] Generation Pool 확인  - Dashboard "/media/generations"
[ ] Human Review          - Dashboard "/media/generations" (수정/승인/dismiss)
[ ] 승인                  - Dashboard 승인 버튼 또는 "전체 승인"
[ ] Promotion dry-run     - python scripts/promote_media_generation.py --archive <pool> --generation-id <id> --content-id <id>
[ ] Promotion execute     - 위 명령에 --execute 추가
[ ] Publish Readiness     - python scripts/audit_publish_candidates.py
[ ] Threads 준비          - python scripts/generate_threads_draft.py -> Dashboard 승인 -> publish_approved_threads.py --execute
[ ] Blog Pack             - python scripts/generate_blog_publish_pack.py --from-archive -> Naver 직접 게시 -> mark_blog_published.py
[ ] YouTube 상태 확인      - python scripts/show_operating_status.py (BLOCKED 고정 표시)
```

## 19. Security

API key/token/secret/refresh token/password는 어디에도 출력하지
않았다. 신규 CLI(`scripts/show_operating_status.py`)는 파일
내용(제목/본문 등)을 출력하지 않고 건수/상태 라벨만 출력하도록
설계했다 - 값 자체를 읽어 화면에 보여주는 필드가 없다(재검토
완료).

## 20. 테스트

실행 순서(지시사항 21장 그대로):

1. 신규 테스트: `tests/test_6_33_october_1_operating_day_rehearsal.py` - 25개 전부 PASS.
2. 관련 기존 테스트(6-28/6-31/6-32 fixture 재사용 파일 포함)는 전체 회귀에 포함되어 실행됨.
3. 전체 회귀:

```
python -m unittest discover -s tests -p "test_*.py"
Ran 1157 tests in 77.242s
OK (skipped=17)
```

failed=0, errors=0. 테스트 수를 맞추기 위해 기존 테스트를 삭제하거나
skip 처리하지 않았다(17건은 이 세션 이전부터 존재하던 조건부 skip).
`git status --short`를 테스트 전/후 모두 확인했고 `data/` 아래
운영 데이터는 전혀 변경되지 않았다(신규 파일 2건: CLI 1개 + 테스트
1개).

## 21. P1

- YouTube renderer 확보(6-30/6-31/6-32에서 이미 기록, 변경 없음) -
  사람이 노트북1/Codespaces 이력을 확인한 뒤 REBUILD_REQUIRED로
  방향을 확정해야 한다.

## 22. P2

- LLM 실패 시 retry 미구현(6-32에서 이미 기록).
- KNOWLEDGE 전용 Dashboard 페이지(6-32에서 이미 기록, CLI로 충분히
  대체 가능함을 이번에 재확인).
- 크로스데이 의미 기반 SCOUT 중복 감지(6-32에서 이미 기록, 의도된
  설계 트레이드오프).

## 23. P3

- empty output(빈 제목/본문)에 대한 명시적 validator 차단(6-32에서
  이미 기록).
- renderer 실행 환경(ffmpeg/Pillow/폰트) 준비(6-30에서 이미 기록).

## 24. 10월 1일 최종 Runbook

18장의 체크리스트가 곧 최종 Runbook이다 - 정확한 소요시간은 추정하지
않았고(코드에서 확인 불가), 순서만 코드 기준으로 확정했다: **08:00
SCOUT(cron 기준, 6-32 6장) → 사람이 깨어있는 시간에 KNOWLEDGE 승인
→ MEDIA generation(수 초~수십 초, LLM 응답 시간에 의존) → Human
Review(사람 소요, 추정 안 함) → Promotion(즉시) → Publish
Readiness(즉시) → Threads/Blog는 사람이 준비되면 언제든**. GitHub
Actions(`daily-scout.yml`)가 1단계를 자동화하고, 나머지는 사람이
그날 편한 시간에 순서대로 실행하면 된다 - 정해진 마감 시각은 코드
어디에도 없다(운영자가 하루 중 원하는 때 진행 가능하다는 뜻이며,
이는 실제 시스템 제약이지 추정이 아니다).

## 25. 결론

10월 1일 실제 운영자는 개발자 지식 없이도 18장의 체크리스트 12개
항목만으로 SCOUT부터 Publish Readiness까지 진행할 수 있다 - 이번
세션에서 4장(3개 SCOUT 후보→1개 선택→끝까지)으로 이 흐름 전체를
synthetic하게 재확인했다. Human Review는 이미 배치 승인/수정/
dismiss가 전부 구현되어 있어 "9개를 하나씩 클릭"할 필요가
없다(9장). Promotion은 dry-run이 기본값이고, unreviewed/invalid/
superseded가 production에 도달할 방법이 구조적으로 없다(10장,
`DryRunFilesystemProtectionTests`/`ApprovalMatrixTests`로 직접
검증). 유일한 신규 구현은 읽기 전용 상태 요약 CLI
(`scripts/show_operating_status.py`) 하나뿐이다 - 기존 구조를
깨뜨리는 통합 오케스트레이터는 만들지 않았다(4장에서 근거 있게
판단). 전체 1157개 테스트가 failed=0/errors=0으로 통과했고, 실제
`data/` 운영 디렉터리는 어디에서도 생성/수정되지 않았다.

YouTube만 여전히 renderer 부재로 BLOCKED다(변경 없음) - 그 외
SCOUT→KNOWLEDGE→MEDIA→HUMAN REVIEW→PROMOTION→PRODUCTION ARCHIVE→
PUBLISH READINESS→Threads/Blog 경로는 10월 1일 실제 운영에 필요한
만큼 검증되었다.
