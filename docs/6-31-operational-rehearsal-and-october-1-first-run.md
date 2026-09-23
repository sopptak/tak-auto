# 6-31 Operational Rehearsal and October 1 First Run

## 1. 목적

10월 1일 Codespaces 사용량이 복구되었을 때, TAK AUTO를 실제로 처음부터
끝까지(SCOUT→KNOWLEDGE→MEDIA→HUMAN REVIEW→PROMOTION→PRODUCTION
ARCHIVE→PUBLISH READINESS→Threads/YouTube/Blog→PUBLISH HISTORY→
PERFORMANCE) 돌릴 수 있는지를 synthetic fixture로 리허설한다. 새
기능을 만드는 것이 아니라, 기존(6-06~6-30) 코드가 실제로 처음부터
끝까지 연결되는지를 코드 수준으로 검증하고, 10월 1일 실제 운영자가
그대로 따라 할 수 있는 절차를 정리하는 것이 목표다. 실제 외부 API/
OAuth/네트워크 호출은 전혀 하지 않았고, 실제 운영 데이터(`data/`)는
전혀 생성/수정하지 않았다 - 모든 검증은 tempfile + mock + synthetic
fixture로만 수행했다.

이 세션은 노트북2(수협)에서 실행되었고, 노트북1/Codespaces에는
접근하지 않았다. "노트북1이 TAK AUTO를 로컬에서 개발한 적이 없고
GitHub/Codespaces 기반이었다"는 사실은 이번 작업의 전제 조건으로
주어졌다 - 이 세션이 그 사실 자체를 새로 검증하지는 않았으며(노트북1에
접근할 수 없으므로), "노트북1에서 renderer를 복구한다"는 접근은
시도하지 않았다(6-30의 EXTERNAL_MACHINE_REQUIRED 판정과 일관됨).

First Sync Check: `git status --short`(clean), HEAD==origin/main(e4f9ef5)
확인 후 시작했다.

## 2. 현재 시스템 Entry Point

문서로 추측하지 않고 실제 코드를 읽어 확인했다(`scripts/` 26개 CLI 전체
docstring 1차 조사 + 필요한 파일은 전문 확인).

| 단계 | Entry Point | 비고 |
|---|---|---|
| SCOUT | `scripts/run_scout.py` | 공개 RSS만 읽기, 로그인/크롤링 없음 |
| KNOWLEDGE(수집→검토) | `scripts/run_interview.py` → `scripts/apply_interview.py` → `scripts/review_knowledge.py` | INTERVIEW 답변이 있어야 KNOWLEDGE로 전이(TAK BRAIN pending) |
| KNOWLEDGE(대안 경로) | `scripts/create_knowledge.py`, `scripts/generate_knowledge.py` | RAW 1건 변환 / RAW 전체 일괄 변환 |
| MEDIA | `scripts/run_media_batch.py`, `content_engine.pipeline.run_media_batch()` | 승인 KNOWLEDGE 1건당 Blog1/Shorts3/Threads5=9 draft |
| REVIEW | Dashboard(`scripts/run_scout_dashboard.py`) `/media`, `/media/generations` | review_status 전이(unreviewed→approved/dismissed) |
| PROMOTION | `scripts/promote_media_generation.py`(`plan_promotion`/`plan_batch_promotion`) | generation pool → production archive |
| PRODUCTION ARCHIVE | `content_engine/media_archive.py`(`load_archive`/`upsert_archive`), `scripts/audit_data_state.py`(읽기 전용 감사) | |
| PUBLISH READINESS | `content_engine/publish_audit.py`(`audit_archive`), `scripts/audit_publish_candidates.py` | |
| Threads | `scripts/generate_threads_draft.py`(초안) → `scripts/publish_approved_threads.py`(발행, `--execute` 필요) | `scripts/publish_threads.py`는 별도 레거시 단건 경로(6-25에서 통합) |
| YouTube | `scripts/youtube_oauth_setup.py --check` → `scripts/generate_approved_shorts_script.py` → (renderer, 6-30: EXTERNAL_MACHINE_REQUIRED) → `scripts/upload_youtube_short.py` | |
| Blog | `scripts/generate_blog_publish_pack.py` → 사람이 Naver에 직접 게시 → `scripts/mark_blog_published.py` | 자동 게시 없음(설계상 의도) |
| PUBLISH HISTORY | `content_engine/publish_history.py`(`PublishHistory`), 채널별 `*_publish_log.json` | |
| PERFORMANCE | `scripts/collect_performance.py`, `content_engine/performance/` | 수집/저장만, 피드백 루프 NOT_IMPLEMENTED(6-28/6-29/6-30과 동일) |
| Recovery(참고) | `scripts/audit_recovery_source.py`, `scripts/recover_media_archive.py` | 18장에서 재사용 |

## 3. First Run 전체 흐름

16단계 각각의 INPUT/ACTION/OUTPUT/SUCCESS CONDITION/BLOCK CONDITION/
HUMAN ACTION을 실제 코드 기준으로 정리했다.

| # | 단계 | INPUT | ACTION | OUTPUT | SUCCESS | BLOCK | HUMAN ACTION |
|---|---|---|---|---|---|---|---|
| 1 | git pull | 없음 | `git fetch && git status` | HEAD==origin/main | 확인됨 | 충돌 시 `git pull --ff-only`만 | 충돌 조사 |
| 2 | 환경 점검 | 없음 | `python --version` | 버전 출력 | 3.x 확인 | 없음(이미 확인, 6-30 13장) | 없음 |
| 3 | dependency 점검 | 없음 | 없음(requirements.txt 없음, 전부 stdlib) | - | - | - | YouTube renderer용 ffmpeg/Pillow는 별도(6-30 13/16장) |
| 4 | 테스트 | 없음 | `python -m unittest discover -s tests -p "test_*.py"` | 1111 tests OK | failed=0 | 실패 시 다음 단계 진행 금지 | 원인 조사 |
| 5 | SCOUT | `data/scout_sources.json` | `scripts/run_scout.py` | `data/tak_scout_daily.json/.md` | 후보 생성 | source 1건 실패해도 계속(6-24) | 없음 |
| 6 | KNOWLEDGE | SCOUT 후보 | `run_interview.py`→`apply_interview.py` | KNOWLEDGE(pending) | 답변 완료 | 사람이 보류(N) 선택 시 정지(정상) | 인터뷰 답변 |
| 7 | MEDIA | 승인 KNOWLEDGE | `run_media_batch.py --execute` | 9개 draft | Blog1/Shorts3/Threads5 | 6-29 overwrite guard 발동 시 중단(정상, 안전장치) | 없음(원인 조사만) |
| 8 | Human Review | 9개 draft | Dashboard `/media/generations` | review_status 전이 | 승인 | 미승인 시 다음 단계로 안 감(정상) | 승인/보류/수정 |
| 9 | Promotion | approved+valid record | `promote_media_generation.py --execute` | production archive 반영 | 반영됨 | `PromotionConflictError`(10장) | `supersede_media_record.py`로 명시 처리 |
| 10 | Production Archive | - | `audit_data_state.py` | VALID, count 증가 | 확인됨 | - | - |
| 11 | Publish Readiness | production archive | `audit_publish_candidates.py`, `audit_archive()` | READY/NEEDS_HUMAN_REVIEW/BLOCKED/... | 상태 구분됨 | - | - |
| 12 | Threads | approved+READY | Dashboard 승인 → `publish_approved_threads.py --execute` | Threads 게시 | 게시 성공 | superseded 차단(6-19) | 실제 게시는 사람이 직접 실행(이 세션은 미실행) |
| 13 | YouTube | ShortsScript+mp4 | `upload_youtube_short.py --execute` | YouTube 게시 | 게시 성공 | **renderer 부재로 mp4 자체가 없음(6-30) → BLOCKED** | mp4를 만들 방법이 생기기 전까지 불가 |
| 14 | Blog | approved+READY | `generate_blog_publish_pack.py` → 수동 게시 → `mark_blog_published.py` | Blog 게시 이력 | 기록됨 | superseded 재검증(6-27) | Naver에 직접 게시 |
| 15 | Publish History | 각 채널 게시 결과 | 채널별 `PublishHistory.append()` | `*_publish_log.json` | 기록됨 | - | - |
| 16 | Performance | 게시된 content_id | `collect_performance.py --confirm-live` | 스냅샷 저장 | 저장됨 | 피드백 루프 NOT_IMPLEMENTED(수집만 가능) | 실제 채널에서 수치 확인 |

## 4. Synthetic KNOWLEDGE

새 fixture를 만들지 않고 6-28이 이미 구축한 `TEST_KNOWLEDGE`
(`tests/test_full_e2e_operating_readiness.py`)를 그대로 재사용했다 -
`tests/fixtures/rehearsal_fixture.py`가 이를 재수출(re-export)해서
"리허설 fixture는 여기서 찾는다"는 하나의 진입점을 만들었다(6장
지시, 새 코드 추가 없음). 실제 외부 source/URL을 전혀 호출하지 않고,
`source_url="https://example.test/..."` 형태의 테스트용 값만 쓴다.
필드 구성: `id`, 제목, `domain`/`category`/`knowledge_type`, 6하원칙
서술(`experience`/`problem`/`action`/`decision`/`result`/`lesson`),
`evidence`(2건), `knowledge_review_status="approved"`.

## 5. Synthetic MEDIA

`content_engine.pipeline.run_media_batch()`를 `MockRewriteProvider`와
함께 그대로 호출해 Blog 1 + Shorts 3 + Threads 5 = 9개 draft를
생성한다(`E2EFixtureMixin.setUp()`, 6-28에서 이미 구축, 이번에
재사용만 함). 새 generation pipeline을 만들지 않았다.

## 6. Human Review

`tests/test_full_e2e_operating_readiness.py::HumanReviewSimulationTests`가
UNREVIEWED→APPROVED/DISMISSED, `PromotionCaseBToGTests`(신규,
`tests/test_6_31_operational_rehearsal.py`)가 APPROVED→SUPERSEDED
전이를 검증한다. 기존 lifecycle(`review_status` 상태 머신, 6-17)을
그대로 썼다 - 새 상태를 추가하지 않았다.

## 7. Promotion

CASE A~H 전체를 실제 함수 호출로 검증했다:

| CASE | 조건 | 결과 | 검증 위치 |
|---|---|---|---|
| A | approved + valid | 승격 성공 | 6-28 `test_approved_valid_record_promotes_successfully` |
| B | unreviewed | `PromotionError` | 신규 `test_case_b_unreviewed_promotion_blocked` |
| C | dismissed | `PromotionError` | 신규 `test_case_c_dismissed_promotion_blocked` |
| D | generation_status="rejected" | `PromotionError` | 신규 `test_case_d_invalid_generation_status_promotion_blocked` |
| E | approved 승격 후 superseded | 이후 `audit_archive()`에서 SUPERSEDED | 신규 `test_case_e_approved_superseded_excluded_from_publish_candidates` |
| F | 같은 content_id + 다른 generation_id | `PromotionConflictError`, production archive 불변 | 6-28 `test_same_content_id_different_generation_is_conflict` |
| G | 신규 content_id | 정상 승격 | 신규 `test_case_g_new_content_id_promotes_normally` |
| H | 같은 content_id + 같은 generation_id | idempotent(예외 없음) | 6-28 `test_promotion_is_idempotent_for_same_generation` |

## 8. Production Archive

`content_engine/media_archive.py`의 `load_archive()`/`upsert_archive()`를
tempfile 경로로 직접 호출해 실제 production archive 파일을 만들지
않고도 읽기/쓰기 계약을 검증했다. `load_archive()`는 파일이 없거나
비어 있으면 빈 목록을 반환하고(안전), JSON 파싱 실패 시에만
`MediaArchiveError`를 던진다(18장에서 상세 확인).

## 9. Publish Readiness

`content_engine.publish_audit.audit_archive()`가 반환하는 6개 상태
(`READY`/`NEEDS_HUMAN_REVIEW`/`BLOCKED`/`ALREADY_PUBLISHED`/
`SUPERSEDED`/`ERROR`)를 전부 신규 테스트(`PublishReadinessStateCoverageTests`)로
재확인했다. **`ORPHAN`은 `audit_archive()`의 상태 값이 아니다** -
Production Archive에 이미 존재하는 레코드를 감사하는 `audit_archive()`의
대상 자체가 아니기 때문이다. `ORPHAN`은 채널별 eligibility 함수
(`scripts/upload_youtube_short.py::check_shorts_upload_eligibility()`가
`--content-id`에 대응하는 Production Archive 레코드가 아예 없을 때 쓰는
용어)에서만 쓰이는 별도 레벨의 개념이다 - 이번에 이 구분을 명시적으로
확인했다(기존 semantics를 바꾸지 않았다).

## 10. Threads

`content_engine.publish_eligibility.check_content_supersede()`/
`find_production_record()`(6-19/6-25에서 이미 구축)를 그대로 재사용해
검증했다: approved+not superseded+not published → ELIGIBLE, superseded →
BLOCKED, already published → ALREADY_PUBLISHED(우선순위 최상위, 6-17),
unreviewed → BLOCKED(`audit_archive()` 기준으로는 이 조건 자체가
"approved가 아니므로 READY가 될 수 없다"는 원칙에 걸림). Production
Archive가 없는 경우(ORPHAN)는 기존 정책 그대로 - Threads pending
draft가 있어도 Production Archive 레코드가 없으면 차단하지 않는다
(6-28 `IntegratedRaceConditionTests::test_case_d_threads_pending_created_then_production_deleted_is_orphan_not_blocked`,
이번에 정책을 바꾸지 않았다).

## 11. YouTube

renderer가 없으므로(6-30, `EXTERNAL_MACHINE_REQUIRED`) 실제 mp4를
만들지 않고, "mock renderer" 개념(가짜 mp4 bytes를 tempfile에 쓰는
헬퍼)으로 경로만 검증했다: Production Archive → ShortsScript
(`save_approved_shorts_script()`) → mock mp4 경로 →
`scripts/upload_youtube_short.py`의 eligibility 검증
(`check_shorts_upload_eligibility()`)까지는 정상 동작한다(6-30에서
이미 CASE A~F 전체를 `main()` CLI 경로로 검증 완료, 이번에 다시
반복하지 않고 인용만 함). 최종 실제 API 호출 단계는 `EXTERNAL_DEPENDENCY`로
표시한다(실제 YouTube Data API는 이 세션에서 호출하지 않았다).

## 12. Blog

`content_engine/blog_publish_pack.py::build_blog_publish_pack_from_archive()`가
approved+not superseded 레코드만 Pack 후보로 포함한다(6-27에서 이미
구축, 이번에 정책을 바꾸지 않았다). superseded candidate는 자동으로
제외된다(6-28 `SupersededFullE2ETests::test_old_blog_is_blocked_new_blog_is_ready`가
이미 검증). 최종 게시는 여전히 "Human Copy/Paste Publish"이며, 이
세션에서 실제 Naver 게시를 시도하지 않았다(HUMAN_ACTION).

## 13. Publish History

`content_engine.publish_history.PublishHistory`를 tempfile 경로로
사용해 검증했다: content_id A(미게시) → READY(`audit_archive()` 기준
READY로 이어짐), content_id B(이미 게시) → `ALREADY_PUBLISHED`, content_id
C(superseded지만 과거 게시 이력 있음) → `ALREADY_PUBLISHED`가
`SUPERSEDED`보다 우선(6-17 정책, `test_already_published_and_superseded`로
재확인). 중복 게시 방지 semantics는 그대로 유지된다 - 새 로직을
추가하지 않았다.

## 14. Full E2E Rehearsal

`tests/test_6_31_operational_rehearsal.py::FullChainSingleWalkthroughTest::test_single_knowledge_reaches_threads_publish_history`가
하나의 synthetic KNOWLEDGE를 시작점으로 KNOWLEDGE→MEDIA(9개 draft)→
HUMAN REVIEW(승인)→PROMOTION→PRODUCTION ARCHIVE→PUBLISH READINESS
(READY 확인)→THREADS(pending 생성→승인→`publish_approved_threads.py
--execute`, `ThreadsClient.from_environment`만 mock, 실제 API 호출
없음)→PUBLISH HISTORY(기록 확인)까지 실제 함수/CLI를 순서대로
호출해서 연결을 확인한다. 테스트 종료 시 `tempfile.TemporaryDirectory`가
정리되어 실제 `data/`에는 어떤 파일도 남지 않는다(직접 확인:
`self.assertFalse(Path(tmp).exists())`). YouTube/Blog 경로는 11/12장에서
이미 별도로 검증했으므로 이 단일 walkthrough에는 포함하지 않았다
(renderer 부재로 YouTube를 같은 walkthrough에 넣으면 처음부터 mock을
전제해야 해서 오히려 "실제 코드 연결 확인"이라는 이 테스트의 목적이
흐려지기 때문).

## 15. Failure Injection

12가지 장애를 실제 코드 경로로 주입해 확인했다(`FailureInjectionTests`):

| # | 장애 | 멈추는 곳 | 왜 | 사용자에게 보여줄 것 |
|---|---|---|---|---|
| 1 | missing knowledge | `run_media_batch([])` | 승인 KNOWLEDGE 없음 | 0건, 정상 종료(크래시 없음) |
| 2 | invalid knowledge | `select_approved()` | `knowledge_review_status != "approved"` | 조용히 제외(0건) |
| 3 | media generation failure | `plan_promotion()` | `generation_status="error"` | `PromotionError` 메시지 |
| 4 | human review missing | `plan_promotion()` | `review_status="unreviewed"` | `PromotionError` 메시지 |
| 5 | promotion conflict | `plan_promotion()`(2차 호출) | 같은 content_id+다른 generation_id | `PromotionConflictError`, archive 불변 |
| 6 | superseded production | `check_content_supersede()` | `review_status="superseded"` | `blocked=True` |
| 7 | duplicate content_id | `audit_archive()` | 같은 content_id 2회 이상 | `ERROR` 상태 |
| 8 | missing ShortsScript | `check_shorts_upload_eligibility()` | 파일 없음 | "ShortsScript 파일이 없습니다" |
| 9 | missing mock mp4 | `upload_youtube_short.py main()` | `--video` 경로 미존재 | "영상 파일을 찾을 수 없습니다", exit 1 |
| 10 | already published | `YouTubeUploadHistory.is_published()` | history에 이미 존재 | idempotent, 크래시 없음 |
| 11 | missing Production Archive | `load_archive()` | 파일 없음 | 빈 목록 반환(크래시 없음) |
| 12 | corrupted synthetic JSON | `load_archive()` | JSON 파싱 실패 | `MediaArchiveError` 명시적 예외 |

## 16. Recovery Rehearsal

6-22가 정의한 `content_engine.data_state.json_file_status()`(NOT_PRESENT/
EMPTY/VALID/CORRUPTED)를 새로 만들지 않고 그대로 재사용해 Production
Archive tempfile 4가지 상태를 검증했다(`RecoveryRehearsalTests`):
NOT_PRESENT/EMPTY → `load_archive()`가 안전하게 빈 목록 반환, VALID →
정상 로드, CORRUPTED(JSON 파싱 자체가 실패) → `load_archive()`가
`MediaArchiveError`를 명시적으로 던진다(자동 복구를 시도하지 않고
사람에게 알린다 - 6-22/6-23 설계와 일관됨).

이번에 새로 확인한 것: `json_file_status()`(6-21 레이어)는 "파싱
가능한 JSON인가"만 보므로 `{"not": "a list"}`처럼 유효한 JSON이지만
list가 아닌 파일은 `VALID`로 분류한다 - 반면 `load_archive()`(6-06
레이어)는 list가 아니면 별도로 거부한다. 즉 같은 파일이 두 레이어에서
다르게 판정될 수 있다(`test_valid_json_but_wrong_shape_is_a_separate_layer_from_corrupted`) -
버그가 아니라 두 레이어의 책임 범위가 다른 것이며, 정책을 바꾸지
않고 사실만 기록한다.

모든 검증에서 실제 `data/tak_media_archive.json`을 만들거나 건드리지
않았다(tempfile만 사용).

## 17. Multi-PC

| 환경 | 역할 | 비고 |
|---|---|---|
| 노트북2(수협) | 이 세션이 실행 중인 환경 | 코드 작업 가능, 운영 데이터 로컬 보유 여부는 `git status`로 확인 필요 |
| 노트북1(집) | TAK AUTO를 로컬에서 개발한 적 없음(이번 작업 전제) | GitHub/Codespaces 기반 - 이 세션이 접근하지 않았고 접근할 수도 없다 |
| Codespaces | 클라우드 개발 환경 | 10월 1일 사용량 복구 후 재개 예정, 이 세션은 접근하지 않았다 |
| GitHub | 코드 동기화 | 모든 환경이 `git pull`/`git push`로만 동기화(6-19 원칙 유지) |
| 운영 데이터(`data/`) | 현재 정책 | `.gitignore`가 대부분 제외하되 일부(`tak_media_archive.json`,
`tak_brain_knowledge.json`, `*_publish_log.json` 등)는 화이트리스트로 git에 커밋 가능(6-21/6-29) |

10월 1일 작업을 어디서 시작하는 것이 안전한가: **Codespaces 또는
노트북2에서 `git pull`로 최신 코드를 받은 뒤 시작하는 것이 안전하다**
- 노트북1에 TAK AUTO 로컬 작업본이 없으므로(이번 작업 전제) 노트북1을
기준점으로 삼을 이유가 없다. renderer만 예외적으로 "다른 어딘가에
있을 가능성"이 6-30에서 가설로 남아 있으나, 이번 6-31의 전제(노트북1은
로컬 개발 이력이 없음)에 따르면 그 가설의 근거도 약해진다 - **renderer는
사실상 REBUILD_REQUIRED에 가깝다**는 것이 이번 세션의 갱신된 판단이다
(19장에서 재확인).

## 18. 10월 1일 First Run 명령 세트

현재 repository에 실제로 존재하는 명령만 사용한다(3장 표와 동일한
근거, 여기서는 그대로 복붙 가능한 형태로 정리).

```
# 1. git pull
git fetch origin main
git status
# HEAD != origin/main이면:
git pull --ff-only

# 2. 환경 확인
python --version

# 3. dependency 점검
# requirements.txt 없음(전부 stdlib) - YouTube renderer 재구현 시에만
# ffmpeg/Pillow 별도 설치 필요(6-30 13장, EXTERNAL DEPENDENCY)

# 4. 테스트
python -m unittest discover -s tests -p "test_*.py"
# failed=0, errors=0 확인 전까지 다음 단계 진행 금지

# 5. SCOUT
python scripts/run_scout.py

# 6. KNOWLEDGE
python scripts/run_interview.py
python scripts/apply_interview.py

# 7. MEDIA
python scripts/run_media_batch.py --execute --as-generation --archive <generation-pool-path>

# 8. Human Review
# Dashboard: python scripts/run_scout_dashboard.py 실행 후 브라우저에서
# "/media/generations"에서 승인/보류

# 9. Promotion
python scripts/promote_media_generation.py --archive <generation-pool-path> \
    --generation-id <generation_id> --content-id <content_id> --execute

# Publish Readiness 확인
python scripts/audit_publish_candidates.py
```

외부 API가 필요한 나머지 단계는 EXTERNAL DEPENDENCY 또는 HUMAN ACTION으로 표시한다:

```
# Threads(HUMAN ACTION: 실제 게시는 사람이 --execute로 직접 실행)
python scripts/generate_threads_draft.py
python scripts/publish_approved_threads.py --id <content_id> --execute

# YouTube(EXTERNAL DEPENDENCY: renderer 부재로 mp4 자체가 없음, 6-30)
python scripts/youtube_oauth_setup.py --check
python scripts/generate_approved_shorts_script.py
# (mp4 렌더링 - 현재 이 저장소에 코드 없음)
python scripts/upload_youtube_short.py --video <mp4> --content-id <id> --execute

# Blog(HUMAN ACTION: 실제 게시는 사람이 Naver에 직접)
python scripts/generate_blog_publish_pack.py --from-archive
python scripts/mark_blog_published.py --content-id <id> --production-archive data/tak_media_archive.json
```

## 19. Dashboard

`scripts/run_scout_dashboard.py`(stdlib `http.server`만 사용, 새
프레임워크 도입 없음)에 이미 nav 메뉴로 `/`, `/threads`, `/media`,
`/media/generations`, `/publish-readiness`, `/performance` 6개 경로가
존재한다. `/publish-readiness`는 `build_publish_audit_inputs()` +
`render_publish_readiness_html()`로 **콘텐츠(content_id)별** Publish
Readiness 상태를 이미 보여준다 - 이는 3장 표의 11번(Publish Readiness)
단계에 해당한다.

다만 3장 표 16단계(SCOUT~Performance) 전체를 **파이프라인 단계별로**
한눈에 보여주는 단일 요약 화면은 없다 - 기존 페이지들은 전부
콘텐츠/draft 단위 목록이다. 이번 세션은 "필요한 경우에만, 큰 UI 개편
금지"라는 명시적 제약에 따라 **새 UI를 만들지 않았다** - 기존
`/publish-readiness`가 이미 콘텐츠 단위 요약을 제공하고, 파이프라인
단계별 요약은 10월 1일 첫 실행에 필수 조건이 아니므로(3장/18장의
명령 세트만으로 각 단계 상태를 순서대로 확인할 수 있다)
`NOT_IMPLEMENTED`(단계별 통합 요약)로 남기고 `FUTURE`(P2/P3)로
분류한다.

## 20. Performance

대규모 기능을 만들지 않았다(22장 지시). 대신 Full E2E Rehearsal(14장)에서
`knowledge_id`("knowledge-TEST-001") → `content_id`(threads 항목의
`compute_content_id()` 결과) → `generation_id`(`new_generation_id()`
결과) → `platform`("threads") → `publish_status`(PublishHistory에 기록됨)가
전부 하나의 체인으로 연결되어 있음을 확인했다(`MediaArchiveRecord`와
`PublishRecord`가 같은 `content_id`를 공유). 이 연결이 향후
Performance 피드백 루프의 기반이 된다 - 이번에는 그 기반이 실제로
끊기지 않고 이어진다는 사실만 확인했다(구현 없음, `NOT_IMPLEMENTED`
유지, 6-28/6-29/6-30과 동일).

## 21. Security

API key/OAuth token/refresh token/client secret/password는 어디에도
출력하지 않았다. `content_engine/youtube_publisher.py`,
`scripts/youtube_oauth_setup.py`의 시크릿 이름 사용 위치는 6-30에서
이미 확인했고 이번에 바뀐 것이 없다(재확인만 함, 재출력하지 않음).

## 22. 테스트 결과

실행 순서(지시사항 24장 그대로):

1. 신규 테스트: `tests/test_6_31_operational_rehearsal.py` - 28개 전부 PASS.
2. 관련 기존 테스트: `tests/test_full_e2e_operating_readiness.py`(6-28) 포함해 재실행 - PASS.
3. 6-19/6-21/6-22/6-23/6-25/6-26/6-27/6-28/6-29 관련 파일은 전체 회귀에 포함되어 실행됨.
4. 전체 회귀:

```
python -m unittest discover -s tests -p "test_*.py"
Ran 1111 tests in 77.014s
OK (skipped=17)
```

failed=0, errors=0. 기존 테스트를 삭제하거나 무조건 skip 처리하지
않았다(17건은 이 세션 이전부터 존재하던 조건부 skip). `git status
--short`를 테스트 전/후 모두 확인했고 `data/` 아래 운영 데이터는
전혀 변경되지 않았다(신규 파일 2건만 추가: 테스트 파일 1개 + fixture
재수출 모듈 1개).

## 23. 실제 운영에서 사람이 해야 하는 것

- KNOWLEDGE 인터뷰 답변(6단계) - 자동화되지 않음, 의도적.
- Human Review 승인/보류/수정(8단계) - Dashboard에서 사람이 직접.
- Promotion 충돌 발생 시 `supersede_media_record.py`로 명시적 처리(9단계).
- Threads 실제 발행 `--execute` 실행(12단계) - 이 세션은 실행하지 않음.
- YouTube: OAuth 최초 인증(Google Cloud Console에서 직접, 6-30 8장),
  그리고 renderer 자체가 없으므로 mp4를 만들 방법을 사람이 먼저
  결정해야 함(재구현 또는 대체 수단, 19장).
- Blog: Naver에 실제로 복사/붙여넣기 게시(14단계) - 자동화되지 않음,
  의도적 설계.
- Performance: 실제 채널에서 수치를 확인해 `--confirm-live`로 수집
  (16단계) - 피드백 루프 자체는 아직 없음.

## 24. 남은 P1/P2/P3

- **P1**: YouTube renderer 재구현 또는 확보 - 6-30에서
  `EXTERNAL_MACHINE_REQUIRED`였으나, 이번 세션에서 주어진 전제("노트북1은
  TAK AUTO를 로컬에서 개발한 적이 없다")를 반영하면 **`REBUILD_REQUIRED`에
  가깝다**(17장). 사람이 최종 확인 후 방향을 정해야 한다.
- **P1**: YouTube 실제 OAuth 최초 인증(6-30에서 이미 기록, 변경 없음).
- **P2**: 파이프라인 단계별 통합 Dashboard 요약 화면(19장, 신규 발견) -
  10월 1일 첫 실행 자체를 막지 않으므로 P2로 분류.
- **P2**: Performance feedback loop 미구현(6-28/6-29/6-30에서 이미 기록,
  변경 없음).
- **P3**: renderer 실행 환경(ffmpeg/Pillow/폰트) 준비 - renderer
  방향 결정 이후 진행.

## 25. 결론

이번 세션은 새 기능을 만들지 않고, 6-06~6-30이 이미 구축한 코드가
실제로 KNOWLEDGE부터 PUBLISH HISTORY까지 하나로 연결되는지를 synthetic
fixture로 리허설했다. `tests/test_full_e2e_operating_readiness.py`
(6-28)의 fixture를 재사용해 `tests/fixtures/rehearsal_fixture.py`로
재수출했고, `tests/test_6_31_operational_rehearsal.py`(신규 28개
테스트)로 6-28이 다루지 않았던 빈틈(Promotion CASE B/C/D/E/G, Publish
Readiness 6개 상태 전부 + ORPHAN 개념 구분, 단일 Full Chain
walkthrough, Failure Injection 12종, Recovery Rehearsal 4상태)을
채웠다. 전체 1111개 테스트가 failed=0/errors=0으로 통과했고, 실제
`data/` 운영 디렉터리는 어디에서도 생성/수정되지 않았다.

10월 1일 첫 실행은 **SCOUT→KNOWLEDGE→MEDIA→HUMAN REVIEW→PROMOTION→
PRODUCTION ARCHIVE→PUBLISH READINESS→Threads/Blog** 경로에서 18장의
명령 세트를 그대로 따라가면 가능하다(6-28/6-29/6-30 결론과 일관됨).
YouTube만 renderer 부재로 막혀 있으며, 이번 세션에서 "노트북1에
TAK AUTO 로컬 개발 이력이 없다"는 사실이 주어짐에 따라 renderer의
최종 방향은 `EXTERNAL_MACHINE_REQUIRED`보다 `REBUILD_REQUIRED`에 더
가까운 것으로 판단을 갱신한다 - 다만 최종 결정은 사람이 노트북1/
Codespaces 이력을 직접 확인한 뒤 내려야 한다.
