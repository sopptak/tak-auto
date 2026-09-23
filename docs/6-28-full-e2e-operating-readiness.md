# 6-28 Full E2E Operating Readiness

## 1. 목적

6-19~6-27이 각각 검증한 개별 안전장치(supersede lifecycle, 데이터
동기화, recovery, Threads/YouTube/Blog publish path)가 실제로 하나의
파이프라인으로 **연결되어 작동하는지**를 synthetic end-to-end 환경에서
검증한다. 새 정책을 만들지 않았다 - 6-19~6-27이 이미 결정한 정책을
그대로 기준 삼아 "정말 연결되어 있는가"만 확인했다. 10월 1일 운영 시작
가능 여부를 최종 판단하고, 10월 이후 우선순위를 정리한다.

이번 세션 전체에서 실제 외부 API 호출/OAuth 인증/Naver 접근은 0건이다
(19장에서 확인). 실제 운영 데이터(`data/tak_media_archive.json` 등)도
생성하지 않았다(23장에서 확인).

## 2. 전체 시스템 지도

6-24가 이미 만든 지도(`docs/6-24-production-readiness-audit.md` 2장)를
그대로 기준 삼아 재확인했다 - 6-24 이후(6-25~6-27) 변경된 부분만 갱신한다.

| 단계 | 입력 | 출력 | Source of truth | 승인 여부 | 실패 시 상태 | 다음 단계 연결 |
|---|---|---|---|---|---|---|
| SCOUT | `scout_sources.json` | `tak_scout_daily.json/.md` | scout_sources.json | 불필요(rule-based) | source 1건 실패해도 나머지 계속 | INTERVIEW |
| KNOWLEDGE | SCOUT + INTERVIEW 답변 | `tak_brain_knowledge.json`(pending) | tak_brain_knowledge.json | 필수(사람) | 미승인이면 `select_approved()`에서 제외 | MEDIA |
| MEDIA | approved KNOWLEDGE | Blog1+Shorts3+Threads5=9 draft | generation pool 또는 archive | 없음(생성은 AI) | rejected/error로 기록, 폐기 안 됨 | HUMAN REVIEW |
| HUMAN REVIEW | generation pool | review_status 변경 | generation pool 파일 | 필수(사람) | unreviewed로 계속 대기 | PROMOTION |
| PROMOTION | approved+valid generation | production archive 갱신 | production archive | 이미 완료된 승인 재확인만 | conflict 시 archive 불변(6-18) | PRODUCTION ARCHIVE |
| PRODUCTION ARCHIVE | promotion | 전체 이력 | `tak_media_archive.json`(현재 NOT_PRESENT) | archive 자체가 승인 결과 저장소 | - | PUBLISH READINESS |
| PUBLISH READINESS | archive + 각 채널 이력 | READY/BLOCKED/... | 없음(순수 판정) | 판정만 | - | 3 CHANNELS |
| Threads | approved+ready draft | 실제 게시 + 이력 | `tak_threads_pending.json` | 필수(발행 직전 재확인, 6-19/6-25) | failed 기록, history 미기록 | PUBLISH HISTORY |
| YouTube | approved+ready+ShortsScript | 업로드 + 이력 | `tak_media_archive.json` | 필수(6-26에서 강화) | 이력 미기록 | PUBLISH HISTORY |
| Blog | approved+ready | Publish Pack + 사람 게시 + 이력 | `tak_media_archive.json` | 필수(6-27에서 강화) | 이력 미기록 | PUBLISH HISTORY |
| PUBLISH HISTORY | 각 채널 발행 성공 | `*_publish_log.json` | 채널별 독립 파일 | - | - | (다음 실행 중복 방지) |
| PERFORMANCE | 발행 이력 | 지표 스냅샷 | 별도 파일(수동 수집) | 필수(`--confirm-live`) | - | 없음(18장에서 상세) |

## 3. Synthetic E2E Architecture

`tests/test_full_e2e_operating_readiness.py`(신규)가 구현했다. `tempfile`
안에 다음을 구성한다:

- `knowledge-TEST-001`(approved) 1건 → `run_media_batch()`(실제 함수,
  `MockRewriteProvider`) → 9개 draft(Blog1/Shorts3/Threads5).
- `new_generation_id()`로 generation_id 부여 → generation pool에 저장.
- OLD/NEW 두 세트의 synthetic `MediaArchiveRecord`(content-OLD*/content-NEW*,
  gen-A/gen-B)를 Threads/YouTube/Blog 세 플랫폼 전부에 대해 구성.

**"현재 환경에서 검증 불가"로 명확히 기록한 부분**: 실제 KNOWLEDGE 승인
UI(Dashboard 클릭), 실제 렌더링된 MP4, 실제 Naver 게시, 실제 OAuth 토큰
발급 - 전부 사람의 행위이거나 외부 시스템이 필요해 synthetic 환경에서
재현할 수 없다. 이 문서는 이 부분들을 "설계/절차 문서화"로만 다룬다(22장).

## 4. SCOUT → KNOWLEDGE

6-24가 이미 감사했다(`docs/6-24-production-readiness-audit.md` 4~5장) -
이번에 코드를 바꾸지 않았으므로 재검증만 했다. `select_approved()`가
KNOWLEDGE→MEDIA 진입의 유일한 게이트라는 결론(6-24)은 여전히 유효하다
(`scripts/run_media_batch.py`가 유일한 실사용처, grep 재확인).

## 5. KNOWLEDGE → MEDIA

`tests/test_full_e2e_operating_readiness.py`의
`KnowledgeToMediaLinkageTests`가 실제로 확인했다:

- 1 KNOWLEDGE → 정확히 9개(Blog1/Shorts3/Threads5) - 하드코딩된 정책
  재확인(`content_engine/generator.py`, 변경 없음).
- 9개 전부 `knowledge_id`/`source_url`이 원본 KNOWLEDGE와 동일.
- 9개의 `content_id`가 서로 유일함(`compute_content_id()` 충돌 없음).
- category(KNOWLEDGE 원본)/domain(자유서술)/article_type(별도 분류
  단계 산출물, KNOWLEDGE 원본 dict에는 없음)이 서로 다른 필드임을 재확인.

**finance template contamination 재발 여부**: 6-15에서 이미 해결됐고
(6-24, 6-27에서도 재확인) 전담 regression test(`tests/test_article_types.py`,
`tests/test_critical_content_replacement_audit.py`)가 이번 전체 테스트
실행(25장)에서도 그대로 통과했다 - 새로 발생한 교차 오염 없음.

## 6. HUMAN REVIEW

`HumanReviewSimulationTests`가 5가지 상태를 전부 구현·확인했다:

1. **unreviewed**(기본값) - 신규 생성 시 항상 이 상태.
2. **approved** - `replace(record, review_status="approved")`.
3. **dismissed** - 동일 방식.
4. **edited then approved** - `edited_title`/`edited_body`를 설정하면
   `record.final_title`/`final_body`가 정확히 그 값을 반영함을 확인
   (edited > rewritten > original 우선순위, 5-29 설계 재확인).
5. **superseded** - approved에서만 도달 가능(6-17 상태 전이 규칙, 이번에
   재확인).

**미승인 콘텐츠는 promotion되지 않는다**: `plan_promotion()`이 `review_status
!= "approved"`면 즉시 `PromotionError`를 던진다(6-06, 이번에 CLI를 통한
실제 시도로도 재확인 - exit 1, production archive 파일 자체가 생성되지
않음).

## 7. PROMOTION

`PromotionE2ETests`가 8장 지시사항의 항목을 전부 실제로 실행했다:

- approved+valid만 승격됨.
- 같은 generation 재승격은 idempotent(파일 불변, 예외 없음).
- **핵심**: 동일 content_id + 다른 generation_id는 `PromotionConflictError`로
  즉시 차단되고, 이 시점에 production archive는 **전혀 쓰여지지 않는다**
  (바이트 단위로 불변 확인).
- batch promotion에서 일부만 승인된 경우, 승인된 것만 정확히 골라
  승격 대상이 됨(나머지는 skip, 데이터 손실 없음).

## 8. PRODUCTION ARCHIVE

6-21(`data_state.py`, NOT_PRESENT/EMPTY/VALID/CORRUPTED)과 6-22/6-23
(recovery staging/approval)이 이미 구축한 상태 판정/복구 체계를 이번
E2E에서 다시 만들지 않고 그대로 전제로 삼았다 - 이번 세션에서 이 계층에
새 코드를 추가하지 않았다(변경 없음, 재확인만).

## 9. Threads E2E

`SupersededFullE2ETests.test_old_threads_is_blocked_new_threads_is_ready`가
실제 `scripts/publish_approved_threads.py`의 `main()`을 호출해서 확인:

- OLD(superseded) → `--execute` 시도해도 exit 1, history 미기록.
- NEW(approved, 정정본) → `--execute` 성공, history에 정확히 기록됨
  (mock `ThreadsClient`만 사용, 실제 API 0건).

10장 지시사항의 A~G는 6-19(`tests/test_superseded_downstream_safeguards.py`,
21개)와 6-25(`tests/test_threads_publish_path_consolidation.py`,
`tests/test_publish_threads_auto_select.py`)가 이미 전담 검증하고 있고,
이번 전체 테스트 실행에서 전부 그대로 통과했다(변경 없음) - 이번 E2E는
"실제로 연결되어 작동하는가"라는 A/B(READY/BLOCK) 핵심 케이스만 통합
경로로 재확인했다.

## 10. YouTube E2E

`SupersededFullE2ETests.test_old_youtube_is_blocked_new_youtube_is_ready`가
`scripts/upload_youtube_short.py`의 `main()`과
`check_shorts_upload_eligibility()`를 실제로 호출해서 확인:

- OLD(superseded) → `check_shorts_upload_eligibility()`가 차단 사유 반환.
- NEW(approved + 매칭되는 ShortsScript) → 사유 없음(`None`) → 실제
  `main()` 호출로 업로드 성공(mock `YouTubeClient`), history에 정확히
  기록됨.

11장 지시사항의 A~K는 6-19와 6-26(`tests/test_youtube_upload_eligibility.py`,
`tests/test_upload_youtube_short_cli.py`)이 이미 전담하고, 전체 테스트
실행에서 그대로 통과했다.

## 11. Blog E2E

`SupersededFullE2ETests.test_old_blog_is_blocked_new_blog_is_ready`가
`build_blog_publish_pack_from_archive()`와
`scripts/mark_blog_published.py`의 `main()`을 실제로 호출해서 확인:

- OLD(superseded) → Blog Publish Pack 후보에서 자동 제외
  (`select_approved_blog_candidates_from_archive`의 등호 비교, 4장/6장
  6-27 설계). `mark_blog_published.py --content-id content-OLD-blog` →
  exit 1, history 미기록.
- NEW(approved) → Pack 후보에 포함됨. `mark_blog_published.py` → exit 0,
  history에 정확히 기록됨.

12장 지시사항의 A~J는 6-19와 6-27(`tests/test_blog_publish_readiness.py`,
`tests/test_blog_publish_pack.py`)이 이미 전담하고, 전체 테스트 실행에서
그대로 통과했다.

## 12. Cross-Channel Consistency

`CrossChannelConsistencyTests`가 확인했다:

- `content_engine.publish_audit.audit_archive()`의 우선순위(ERROR >
  ALREADY_PUBLISHED > SUPERSEDED > BLOCKED > NEEDS_HUMAN_REVIEW > READY,
  6-14/6-17/6-19)가 Threads/Shorts/Blog 세 플랫폼 모두에서 동일한
  레코드 구조로 동일하게 작동함을 확인(순서/의미 변경 없음).
- ALREADY_PUBLISHED가 SUPERSEDED보다 항상 우선한다는 6-17 정책이
  Threads/Blog 각각에서 재확인됨(YouTube의 동일 정책은 6-19
  `YouTubeUploadSupersedeBlockTests.test_already_published_takes_priority_over_superseded`가
  이미 전담).
- "Production SUPERSEDED인데 Blog만 READY" 같은 모순 상태는 발생하지
  않는다 - 9~11장의 SUPERSEDED E2E 테스트가 세 채널 전부 일관되게
  BLOCK되는 것으로 이미 확인됐다.

## 13. Publish History

각 채널이 **독립된 파일**(`threads_publish_log.json`/`youtube_publish_log.json`/
`blog_publish_log.json`)을 쓰지만 **동일한 패턴**(`content_id` 키,
atomic write, "이미 있으면 재기록 안 함")을 공유한다는 것을 6-19/6-25~6-27이
이미 확인했다 - 이번 E2E에서 9~11장의 테스트가 세 파일 모두 실제로
정확히 기록되는 것을 재확인했다. `generation_id`는 세 이력 파일 어디에도
저장되지 않는다(Threads/Blog는 `PublishRecord`, YouTube는
`YouTubeUploadRecord` - 둘 다 이 필드가 없음, 6-27에서 이미 "content_id만으로
충분"이라고 판단한 것을 재확인) - 이는 결함이 아니라, 한 content_id당
활성 generation이 정확히 하나(6-06 promotion 규칙)이므로 content_id만으로
이력을 완전히 식별할 수 있기 때문이다.

## 14. Race Condition

`IntegratedRaceConditionTests`가 15장 지시사항의 5개 CASE를 확인했다:

- **CASE A**(재확인 → supersede → publish): 스냅샷을 먼저 읽은 프로세스는
  그 이후의 supersede를 감지하지 못하지만(알려진 경계, 6-25/6-26/6-27이
  이미 개별 채널에서 확인한 것과 동일), **다음 실행(새 스냅샷)은 정확히
  차단**한다 - 이번엔 이를 명시적 통합 테스트로 고정했다.
- **CASE B**(Pack 생성 → supersede → human publish): 11장의
  `test_old_blog_is_blocked_new_blog_is_ready`가 정확히 이 시나리오다 -
  `mark_blog_published.py`가 최종 방어선 역할.
- **CASE C**(YouTube readiness 확인 → 이미 다른 프로세스에서 published):
  `YouTubeUploadHistory.is_published()`가 `YouTubeClient.from_environment()`
  호출보다 먼저 실행되므로(6-26에서 이미 확인), 발행 시도 자체가 API
  호출 전에 멈춘다.
- **CASE D**(Threads pending 생성 → Production 삭제): 기존 ORPHAN 정책
  (6-19)대로 차단하지 않는다 - PATH A(Threads)는 별도 승인 트랙이 있어
  안전하다는 6-25의 결론을 재확인했다.
- **CASE E**(Blog Pack 생성 중 다른 generation이 같은 content_id 차지):
  `PromotionConflictError`로 명시적 차단, 자동 병합 없음, 기존 production
  불변 확인.

**새 DB/lock system은 만들지 않았다** - 6-25/6-26/6-27과 동일한 판단
(기존 워크플로우 concurrency 직렬화 + "동시에 같은 CLI를 두 곳에서
실행하지 않는다"는 운영 규율에 의존).

## 15. Failure Matrix

지시사항 16장의 16개 상태가 실제로 **어느 단계**에서 발생하는지 코드
근거와 함께 정리한다. 서로 다른 상태를 합치지 않았다.

| 상태 | 발생 단계 | 근거 |
|---|---|---|
| NOT_PRESENT | Production Archive/generation pool 파일 자체 부재 | `content_engine/data_state.py`(6-21) |
| EMPTY | 파일은 있으나 내용 없음(`[]` 또는 빈 디렉터리) | 동일 |
| CORRUPTED | JSON 파싱 실패 | 동일 |
| INVALID | 레코드 구조가 스키마를 위반(content_id/knowledge_id 누락 등) | `MediaArchiveRecord.__post_init__`(6-06/6-17), 6-22 A~M 오류 체계 |
| UNREVIEWED | HUMAN REVIEW 이전 기본 상태 | `REVIEW_STATUSES`(6-06) |
| DISMISSED | 사람이 명시적으로 보류 | 동일 |
| SUPERSEDED | approved에서만 도달, 정정본으로 대체됨 | 6-17, `REVIEW_STATUS_TRANSITIONS` |
| ORPHAN | Production Archive에 해당 content_id 레코드 자체가 없음(downstream artifact는 있음) | `content_engine/publish_eligibility.py`(6-19), Threads/Blog는 통과, YouTube는 6-26에서 BLOCK으로 정책 변경(5장 근거는 `docs/6-26-youtube-publish-readiness.md` 5장) |
| CONFLICT | 동일 content_id + 다른 generation_id가 이미 production에 존재 | `check_promotion_conflict()`(6-18), `PromotionConflictError` |
| ALREADY_PUBLISHED | 채널별 publish history에 이미 기록됨, SUPERSEDED보다 항상 우선 | 6-17 정책, `PublishHistory.is_published()`/`YouTubeUploadHistory.is_published()` |
| MISSING_ARTIFACT | Production은 approved인데 downstream artifact(ShortsScript)가 없음(Blog는 별도 artifact 개념이 없어 해당 없음, 6-27) | 6-26 `check_shorts_upload_eligibility()` |
| CREDENTIALS_REQUIRED | OAuth 환경변수(`YOUTUBE_CLIENT_ID` 등) 부재 | `YouTubeConfigurationError`(6-26) |
| AUTH_ERROR | OAuth 토큰 갱신 실패(client 생성은 됐지만 access_token 발급 실패) | `YouTubeAPIError`(토큰 엔드포인트), `content_engine/youtube_publisher.py` |
| UPLOAD_ERROR | 업로드 API 자체 실패(4xx/5xx) | `YouTubeAPIError`(업로드 엔드포인트), `ThreadsAPIError` |
| NEEDS_HUMAN_REVIEW | approved+valid+not-superseded지만 금융/부동산/대출 등 민감 콘텐츠 | `is_review_required()`(5-10, `content_engine/blog_publish_pack.py`), `content_engine/publish_audit.py` |
| READY | 모든 조건 충족, 즉시 발행 가능 | `content_engine/publish_audit.py` |

## 16. Publish Readiness

`content_engine/publish_audit.py`의 우선순위(ERROR → ALREADY_PUBLISHED →
SUPERSEDED → BLOCKED → NEEDS_HUMAN_REVIEW → READY)를 이번에 바꾸지
않았다 - 12장/14장의 E2E 테스트가 이 순서가 Threads/YouTube/Blog 세
플랫폼 모두에서 모순 없이 작동함을 재확인했다.

## 17. Dashboard

6-25/6-26/6-27이 각각 `compute_media_downstream_status()`
(`scripts/run_scout_dashboard.py`, 6-13)를 재확인했고, 세 문서 모두
동일한 gap을 발견했다: Superseded/Stale 상태를 별도 배지로 보여주지
않는다. 이번에도 UI를 고치지 않았다(전면개편 금지 + 세 플랫폼에 걸친
공통 함수라 한 번에 고치는 것이 합리적이라는 판단을 재확인, 21장 P2).
KNOWLEDGE/MEDIA/REVIEW/PRODUCTION/PUBLISH READINESS/Threads/YouTube/Blog
상태가 서로 다른 화면(`/media`, `/threads`, `/media/generations`)에
분산되어 있지만 전부 같은 데이터(archive의 `review_status`)를 기준으로
계산되므로 **논리적으로는 연결되어 있다** - 물리적으로 한 화면에
통합되어 있지는 않다(이것도 "UI 전면개편" 범주로 판단, 이번에 손대지
않음).

## 18. Performance

지시사항 19장의 6개 질문에 코드 근거로 답한다(`content_engine/performance/`,
`scripts/collect_performance.py` 재확인, 변경 없음):

1. **publish 이후 어떤 데이터가 저장되는가?** `PerformanceRecord`
   (content_id/knowledge_id/platform/published_at/metric_collected_at/
   metrics/source/title/external_id/raw) - `scripts/collect_performance.py
   --confirm-live`로 사람이 수동 수집해야만 쌓인다.
2. **content_id가 유지되는가?** 그렇다 - 필수 필드(`__post_init__`이
   강제).
3. **platform별 성과를 연결할 수 있는가?** 그렇다 - `platform` 필드
   (`threads`/`youtube`/`blog`)로 구분.
4. **KNOWLEDGE까지 역추적 가능한가?** 그렇다 - `knowledge_id` 필수
   필드.
5. **generation_id가 유지되는가?** **아니다** - `PerformanceRecord`에
   이 필드가 없다. 13장에서 확인했듯 content_id만으로 충분하다는 논리가
   여기도 적용된다(한 content_id당 활성 generation은 하나뿐).
6. **superseded content가 성과 데이터에서 어떻게 처리되는가?** **처리되지
   않는다** - Performance 모듈은 Production Archive의 `review_status`를
   전혀 참조하지 않는다. 발행 후 supersede된 content_id의 과거 성과
   데이터는 그대로 남아있고, 수집/조회 어느 단계에서도 필터링되지 않는다
   (있는 그대로 기록 - "이 content_id가 한때 이런 성과를 냈다"는 역사적
   사실이므로 지우는 것이 오히려 부적절할 수 있다. 다만 요약/리포트
   단계에서 "지금도 활성 콘텐츠인가"를 구분하지 않는다는 점은 명확한
   gap이다).

**"게시 → 성과 → 분석 → 다음 콘텐츠" 피드백 루프는 여전히 없다**(6-24가
이미 확인한 것과 동일 결론, 이번에도 억지로 구현하지 않았다) - 수집/저장/
요약까지만 구현되어 있다.

## 19. 10월 1일 운영 가능성

| # | 항목 | 판정 | 근거 |
|---|---|---|---|
| 1 | SCOUT | READY | 6-24 감사, rule-based, 외부 의존 RSS fetch뿐 |
| 2 | KNOWLEDGE | READY | `select_approved()` 단일 게이트, 우회 경로 없음(6-24, 6-28 재확인) |
| 3 | MEDIA | READY | 6-24 P0(archive_report 조용한 재작성) 수정 완료, 6-27에서 나머지 한 곳(Blog)도 수정 완료 |
| 4 | HUMAN REVIEW | READY | Dashboard `/media`, `/media/generations`로 가능(6-24에서 이미 확인) |
| 5 | PROMOTION | READY | CLI 필수지만 안전(6-18/6-24), 6-28에서 실제 실행으로 재확인 |
| 6 | PRODUCTION ARCHIVE | READY(단, 파일 자체는 NOT_PRESENT) | 6-21 상태 판정 체계 완성, 실제 데이터는 아직 없음(정상 - 운영 시작 전이므로) |
| 7 | Threads | READY | 6-19/6-25로 공식 경로 완성, 레거시 경로는 사실상 무력화됨 |
| 8 | YouTube | **NEEDS_REVIEW** | eligibility/OAuth 구조는 READY(6-26)지만, mp4 렌더링 파이프라인이 이 저장소에 없고(6-21/6-24/6-26 공통 확인) 실제 OAuth 인증이 아직 한 번도 된 적 없음(당연히 - 이번 세션에서 금지됨) |
| 9 | Blog | READY | 6-27로 공식 경로 완성, Naver 자동화는 정책상 의도적으로 없음(정상) |
| 10 | Publish History | READY | 세 채널 모두 독립 파일 + 동일 패턴, 6-28에서 실제 연결 재확인 |
| 11 | Performance | **NOT_IMPLEMENTED**(피드백 루프만) / READY(수집·저장·요약 자체는) | 6-24/6-28에서 동일 결론 - "완성"과 "운영 가능"을 구분(20장) |
| 12 | Dashboard | READY(기능), NEEDS_REVIEW(정보 완전성) | 승인/발행 자체는 가능, Superseded/Stale 표시는 부족(17장) |
| 13 | GitHub Actions | READY | 6-24/6-25/6-26/6-27이 각각 확인, 자동 발행 경로 없음(안전한 방향으로 이미 봉인) |
| 14 | Multi-PC operation | **NEEDS_REVIEW** | 6-21 설계는 완성됐지만 Production Archive가 어느 브랜치에도 커밋된 적 없음(6-20/6-21/6-24에서 반복 확인) - 사람의 결정 대기 |
| 15 | Recovery | READY(구조) | 6-22/6-23으로 Report→Approval→Apply 파이프라인 완성, 실제 사용 사례는 아직 없음(정상) |
| 16 | Security | READY | `.env` gitignore(6-24), secrets 미노출(6-19~6-27 전체에서 반복 확인), 이번 6-28도 재확인 |

## 20. 운영 가능 vs 완성

**"운영 가능"과 "완성"을 혼동하지 않기 위한 명확한 구분**:

- **SCOUT → KNOWLEDGE → MEDIA → HUMAN REVIEW → PROMOTION → PRODUCTION
  ARCHIVE → Threads/Blog 발행**은 **운영 가능하다**(이번 세션의 synthetic
  E2E가 이를 실제 함수 호출로 증명했다) - Performance 피드백 루프가
  없어도 이 흐름 자체는 완결된다.
- **YouTube는 코드/게이트 수준에서는 완성됐지만 운영 가능하지 않다** -
  실제 OAuth 인증(사람이 직접 해야 함, 이번 세션에서 절대 금지)과 mp4
  렌더링 파이프라인(이 저장소 밖)이 없으면 업로드 자체가 물리적으로
  불가능하다. **mock 테스트를 통과했다고 "운영 가능"으로 판단하지
  않았다** - 이것이 지시사항 21장이 명시적으로 경고한 함정이다.
- **Performance는 완성되지 않았다**(피드백 루프 없음) - 그러나 이것이
  SCOUT→CONTENT→PUBLISH 흐름 자체를 막지는 않는다. "완성되지 않은
  기능이 있다"와 "운영을 시작할 수 없다"는 다른 명제다.
- **Multi-PC 동기화는 설계가 완성됐지만 실전 검증이 안 됐다** - 실제로
  두 대의 PC에서 Production Archive를 동기화해 본 적이 아직 한 번도
  없다(노트북1 접근 금지가 이번 세션에도 유지됨).

## 21. P0/P1/P2/P3 Roadmap

10월 1일 이후 우선순위(6-24~6-27의 누적 발견 + 6-28의 재확인 결과를
종합, 새로 발견한 문제를 임의로 확대하지 않았다).

**P0(운영 시작을 막는 문제) — 없음.** 6-24에서 발견된 유일한 P0
(archive_report() 조용한 재작성)는 6-24/6-27에서 발견된 3곳 중 2곳
(`run_media_batch.py`, `run_daily.py`, `generate_blog_publish_pack.py`)이
수정됐다. 남은 2곳(`generate_threads_draft.py`, `scripts/tak_auto.py`)은
아래 P1으로 분류한다 - 이미 실사용 빈도가 낮고(자동화 워크플로우가
안전 경로만 쓴다, 6-25/6-27에서 확인) 운영 시작 자체를 막지는 않는다.

**P1(운영 시작은 가능하지만 조기 해결 필요)**:

| 문제 | 근거 | 영향 | 예상 작업량 | 의존성 |
|---|---|---|---|---|
| `generate_threads_draft.py`/`tak_auto.py`에 `find_protected_overwrite_targets()` 가드 미적용 | 6-27 5장 | 승인된 콘텐츠가 조용히 재작성될 수 있음(낮은 빈도) | 각 30분 내외(기존 패턴 재사용) | 없음 |
| YouTube mp4 렌더링 파이프라인 부재 | 6-21/6-24/6-26/6-28 공통 | Shorts 업로드가 물리적으로 불가능 | 불명(외부 파이프라인 조사 필요) | 렌더링 도구 소재 확인 먼저 |
| Production Archive 최초 커밋 정책 미결정 | 6-20/6-21/6-24 | Multi-PC/CI가 승인 상태를 못 봄 | 낮음(코드), 결정은 사람 몫 | 사람의 판단 |
| `blog_publish_log.json` `.gitignore` 화이트리스트 누락 | 6-21 | Blog 발행 이력 PC간 미동기화 | 매우 낮음(1줄) | 위와 함께 검토 |

**P2(운영 중 개선)**:

| 문제 | 근거 |
|---|---|
| Dashboard에 Superseded/Stale 배지 없음(Threads/YouTube/Blog 공통) | 6-25/6-26/6-27/6-28 |
| YouTube upload failure 영속 기록 없음(Threads의 `failed` 상태에 대응하는 개념 없음) | 6-26 |
| Performance가 superseded content를 필터링하지 않음 | 6-28(18장) |
| `upload_youtube_short.py --content-id` 생략 시 보호 우회 가능(의도된 하위호환) | 6-24/6-26 |
| Recovery Staging의 "저장된 REPORT 재승인" 2단계 워크플로우 미지원 | 6-23 |

**P3(장기 확장)**:

| 항목 | 근거 |
|---|---|
| Performance → 다음 콘텐츠 전략 피드백 루프 | 6-24/6-28, 실제 게시 이력이 쌓인 뒤 설계해야 함 |
| 서로 다른 Production Archive 자동 병합 도구 | 6-21/6-22, 실제 발생 사례 없어 추측성 구현 회피 |
| YouTube OAuth 설정 CLI의 실제 인증 자동화(`youtube_oauth_setup.py --check` 이상) | 6-26, Google 정책상 완전 자동화는 애초에 부적절할 수 있음 |

## 22. 실제 운영 시작 Runbook

6-24 21장 + 6-25/6-26/6-27의 절차를 하나로 합친다(실제 실행은 하지
않았다 - 노트북2에 실제 운영 데이터가 없기 때문).

```
1.  git fetch origin main && git status
2.  python -m unittest discover -s tests -p "test_*.py"   # 전체 통과 확인
3.  python scripts/audit_data_state.py                     # 현재 상태 확인
4.  python scripts/run_scout.py                             # 또는 daily-scout.yml 대기
5.  python scripts/run_interview.py → apply_interview.py   # KNOWLEDGE 생성
6.  Dashboard 또는 scripts/review_knowledge.py로 KNOWLEDGE 승인
7.  python scripts/run_media_batch.py --execute --as-generation \
        --archive <generation-pool-path>
8.  Dashboard "/media/generations"에서 승인/보류/수정
9.  python scripts/promote_media_generation.py --execute
10. python scripts/audit_publish_candidates.py              # Publish Readiness 확인
11a. Threads: Dashboard "/threads" 승인 →
     python scripts/publish_approved_threads.py --execute
11b. YouTube: (사전 필요) python scripts/youtube_oauth_setup.py --check →
     python scripts/generate_approved_shorts_script.py →
     (외부 렌더링) → python scripts/upload_youtube_short.py --content-id ... --execute
11c. Blog: python scripts/generate_blog_publish_pack.py --from-archive →
     사람이 Naver에 직접 게시 →
     python scripts/mark_blog_published.py --content-id ...
12. python scripts/audit_publish_candidates.py로 재확인
13. python scripts/collect_performance.py --confirm-live (선택)
14. git add data/... && git commit && git push
```

**단계 8(YouTube 사전 준비)**은 이 저장소 밖의 작업(OAuth 클라이언트
발급, refresh_token 발급, mp4 렌더링 파이프라인 확보)이 선행되어야
한다 - 20장에서 이미 구분했듯 이 부분은 "완성"되지 않았다.

## 23. 남은 위험

- **21장 P1**의 4개 항목이 아직 해결되지 않았다.
- YouTube의 "운영 가능"은 이 저장소 코드 범위로 한정된다 - 외부
  요인(OAuth 발급, mp4 렌더링)이 갖춰지지 않으면 코드가 완벽해도 실제
  업로드는 불가능하다.
- Multi-PC 동기화는 설계만 검증됐고 실전 사례가 없다(15장 Recovery도
  마찬가지).
- Dashboard의 정보 완전성 gap(17장)은 세 세션(6-25/6-26/6-27)에 걸쳐
  반복 발견된 패턴이다 - 개별 수정보다 공통 함수 개선이 필요해 보이지만
  아직 손대지 않았다.

## 24. 결론

6-19에서 6-27까지 쌓아온 안전장치는 **개별적으로도, 서로 연결된
파이프라인으로도** 실제로 작동한다 - 이번 6-28의 synthetic E2E(18개
신규 테스트, 특히 "OLD→NEW supersede가 Threads/YouTube/Blog 세 채널
모두에서 일관되게 처리되는가"라는 가장 중요한 테스트)가 실제 함수
호출로 이를 증명했다. 전체 테스트 1066건이 실패/에러 없이 통과했다.

10월 1일 운영 시작은 **SCOUT→KNOWLEDGE→MEDIA→HUMAN REVIEW→PROMOTION→
PRODUCTION ARCHIVE→Threads/Blog 발행** 경로에 한해 **가능**하다(P0
없음). YouTube는 코드는 준비됐지만 외부 요인(OAuth, 렌더링)이 남아있어
**부분 가능**이다. Performance 피드백 루프는 없지만 이것이 운영 시작을
막지 않는다는 것을 20장에서 명확히 구분했다.
