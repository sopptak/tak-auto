# 6-13 Publish Operation Report

## 1. 작업 목적

6-12에서 실제로 승인 + batch promotion을 끝까지 실행해 Production Archive에
실제 콘텐츠 9건이 처음으로 반영됐다(9건 → 18건). 이번 6-13은 그 다음 단계,
즉 "Production Archive에 들어온 콘텐츠를 사람이 실제로 각 플랫폼에 게시하는
단계"를 준비하는 작업이다. 구체적으로는

- 6-12 결과의 무결성을 실제 데이터/코드로 재확인하고,
- Production Archive → 플랫폼별 게시 준비(Publish Pack) → 게시 → 게시 상태
  기록 → 성과 데이터로 이어지는 기존 구조를 조사하고,
- 부족한 부분(주로 "승인됨"과 "실제로 게시됨"을 혼동하지 않는 게시 상태 표시,
  YouTube 업로드 중복 방지)을 안전한 범위에서 보완하는 것

이 목적이다. 이번 작업에서 실제 외부 플랫폼(Naver/Threads/YouTube)에 아무것도
게시하지 않았다 - 모든 변경은 로컬 코드/테스트/문서이고, 실행한 명령은 전부
읽기 전용 조사이거나 `pytest`/`dry-run` 성격이다.

## 2. 작업 전 시스템 상태

- branch: `main`, HEAD: `cefe257` (6-12 보고서 커밋), `origin/main`과 완전히
  동기화된 상태(`git log origin/main..HEAD`/`git log HEAD..origin/main` 모두
  비어 있음)로 세션을 시작했다.
- `git status --short`: 이번 세션 시작 시점에 이미 존재하던 기존 미커밋
  변경(`.gitignore`, `content_engine/__init__.py`, `content_engine/generator.py`,
  `content_engine/llm_provider.py`, `content_engine/rewrite.py`,
  `data/tak_brain_knowledge.json`, `data/tak_threads_pending.json`,
  `tests/test_content_engine.py`, `tests/test_media_batch.py`)과, `docs/5-*`,
  `docs/6-01~6-12` 등 다수의 untracked 문서/스크립트 파일이 있었다. 이번
  세션은 이 기존 변경들을 건드리지 않았다(12장에서 재확인).
- 기존 전체 테스트: `python -m pytest -q` 실행 결과 **924 passed, 6 failed**
  (68 subtests passed 별도). 6건의 실패는 전부 6-12에서 실제로 production
  archive를 9건 → 18건으로 승격시킨 것 때문에, 6-06/6-07 회귀 테스트가
  하드코딩해 둔 "production archive는 정확히 9건"이라는 낡은 스냅샷 가정이
  깨진 것이었다(3장에서 원인과 수정 내용을 자세히 다룬다).
- `docs/`: 가장 최근 보고서는 `6-12_media_generation_promotion_execution.md`
  (실제 Generation 승인 + Batch Promotion 실행).
- `data/` 구조(비-JSON 포함): `blog_draft_*.md`, `blog_publish_pack_daily.md`,
  `shorts/`, `shorts_scripts/`, `tak_interview_questions.md`,
  `tak_scout_daily.md`, 그리고 다수의 JSON 저장소(KNOWLEDGE, MEDIA archive,
  generation pool, 각 채널별 pending/publish log 등).
- 파이프라인 각 단계 실제 상태(이번 세션이 코드를 읽어서 확인한 것):
  - **SCOUT**: `tak_scout/` 패키지(수집/스코어링/인터뷰) - 이번 작업과 직접
    관련 없어 코드 변경 없음.
  - **KNOWLEDGE**: `data/tak_brain_knowledge.json` 총 28건
    (`knowledge_review_status`: approved 6 / pending 13 / rejected 9).
  - **INTERVIEW**: `tak_scout/interview_session.py` 등 - 이번 작업 범위 밖,
    변경 없음.
  - **MEDIA(생성)**: `content_engine/pipeline.py`의 `run_media_batch()` -
    KNOWLEDGE 1건당 Blog 1 / Shorts 3 / Threads 5 = 9건 생성. 무수정.
  - **Generation Pool**: `content_engine/media_archive.py`의
    `archive_generation_report()`/`upsert_generation_archive()` - content_id
    단독 키가 아니라 `(content_id, generation_id)` 복합 키로, 같은 콘텐츠
    슬롯의 여러 생성 시도를 모두 보존한다(6-06). 현재 실제 파일은
    `data/tak_media_generation_6-07_knowledge-scout-6d1d0e2fa762.json`
    1개뿐(9건, 전부 `generation_id=gen-20260920T033856-6e8d98fb`).
  - **Human Review**: `/media`(production archive 최종 검수) +
    `/media/generations`(promotion 전 generation pool 검수) 두 화면으로
    분리(6-07/6-08). 서로 다른 파일을 갱신하고, 서로 다른 폼 action만
    가리킨다(교차 오염 없음 - 기존 테스트가 이미 검증).
  - **Approval**: `MediaArchiveRecord.review_status`
    (`unreviewed`/`approved`/`dismissed`, `content_engine/media_archive.py`)와
    generation pool 레코드에도 동일한 필드가 재사용된다. `review_status`는
    "사람이 검토했는가"만 의미하고, "실제로 외부에 게시됐는가"는 전혀
    나타내지 않는다(5장에서 이 구분을 어떻게 지켰는지 설명).
  - **Promotion**: `scripts/promote_media_generation.py` - generation
    pool에서 `generation_status=="valid" and review_status=="approved"`인
    레코드만 골라 production archive(`data/tak_media_archive.json`)로
    `content_id` 단독 키 upsert. `--execute` 없이는 항상 dry-run.
  - **Production Archive**: `data/tak_media_archive.json` - 이번 세션 시작
    시점에 이미 18건(legacy 9 + 6-12 promoted 9). 이번 세션은 이 파일을
    한 번도 쓰지 않았다(11장에서 해시로 재확인).
  - **Threads pending**: `content_engine/threads_review.py` -
    `pending → approved → published|failed` 상태 기계. 현재 실제 파일
    (`data/tak_threads_pending.json`) 5건: pending 4 / approved 1.
  - **Blog publish pack**: `content_engine/blog_publish_pack.py` +
    `scripts/generate_blog_publish_pack.py`. 현재 `data/blog_publish_log.json`
    (실제 게시 이력)은 아직 없음(한 건도 게시 기록이 없음).
  - **Shorts script**: `content_engine/shorts_adapter.py` -
    `data/shorts_scripts/`에 실제 content_id 연결 파일 2건
    (`content-e787c9201b94a948.json`, `content-3ae2d78568210164.json`) +
    예시 파일 1건.
  - **YouTube workflow**: `content_engine/youtube_publisher.py` +
    `scripts/upload_youtube_short.py` + `.github/workflows/
    youtube-shorts-upload.yml`(workflow_dispatch 전용, scaffold). 현재
    `data/youtube_publish_log.json` 1건.

## 3. 6-12 결과 검증

### 3-1. Production Archive/Generation Pool 실측 확인

```
$ python3 -c "..."  # data/tak_media_archive.json 직접 로드
총 record: 18
by knowledge_id: {'knowledge-scout-b28b782b2a33': 9, 'knowledge-scout-6d1d0e2fa762': 9}
generation_id: {None: 9, 'gen-20260920T033856-6e8d98fb': 9}
review_status: {'approved': 16, 'unreviewed': 2}
```

- legacy 9건(`knowledge-scout-b28b782b2a33`, `generation_id=None`)과 6-12가
  승격한 신규 9건(`knowledge-scout-6d1d0e2fa762`,
  `generation_id=gen-20260920T033856-6e8d98fb`)이 정확히 분리되어 공존한다.
- `review_status`가 16 approved / 2 unreviewed인 것은 6-12 보고서 8장이
  기록한 대로, legacy KNOWLEDGE의 남은 항목을 사용자가 `/media`에서 계속
  직접 검토하고 있어서다(이번 세션과 무관한, 정상적인 별개 활동).
- Generation Pool 파일(`data/tak_media_generation_6-07_...json`) 9건은 전부
  `review_status=="approved"`, promotion 이후에도 전혀 바뀌지 않았다
  (`promote_media_generation.py`는 generation pool을 읽기만 한다는 구조가
  그대로 보장한다 - 6-12 보고서 7장과 동일한 결론).
- 두 파일의 SHA-256 해시가 6-12 보고서가 마지막에 기록한 값과 **정확히
  일치**한다:
  - `data/tak_media_archive.json`: `ebe1249f...` (6-12 종료 시점 값과 동일)
  - `data/tak_media_generation_6-07_knowledge-scout-6d1d0e2fa762.json`:
    `9aa3677e...` (6-12 종료 시점 값과 동일)

  즉 6-12 종료 이후 이번 세션 시작까지 두 파일 모두 어떤 변경도 없었다(단,
  `review_status` 카운트가 16/2로 바뀐 것은 파일 자체는 그 사이 누군가
  갱신했다는 뜻인데, 최종 해시는 세션 시작 시점 기준으로 동일했다 - 즉 내
  조사 이전까지의 사용자 활동은 이미 반영된 상태로 세션이 시작됐고, 이후
  이번 세션 동안은 내가 다시 한번도 쓰지 않았다는 의미다).

### 3-2. "Generation Pool → Approval → Promotion → Production Archive" 우회 경로 점검

코드를 직접 추적해 두 갈래 콘텐츠 유입 경로를 확인했다.

1. **신규(6-06+) 경로**: `run_media_batch()` → `archive_generation_report()`
   (generation pool, unreviewed 시작) → `/media/generations`에서 사람이
   승인 → `scripts/promote_media_generation.py --execute`로만 production
   archive에 반영(`review_status=="approved"`인 것만 게이팅 통과, 코드:
   `scripts/promote_media_generation.py`의 `plan_promotion()`).
2. **레거시(5-27~) 경로**: `scripts/generate_threads_draft.py`/
   `scripts/generate_blog_publish_pack.py`(비-`--from-archive` 모드)가
   `run_media_batch()` 결과를 `archive_report()`로 production archive에
   **직접** upsert한다(`review_status` 기본값 `unreviewed`). 이후
   `/media`에서 사람이 승인해야 `review_status=="approved"`가 된다.

두 경로 모두 **"실제로 downstream(Blog Pack `--from-archive`/Shorts Script
생성/Threads 발행 CLI)에 쓰이려면 production archive의
`review_status=="approved"`를 반드시 거쳐야 한다"**는 단일 게이트로
수렴한다 - 우회 경로는 없었다. 근거:
   - `content_engine/shorts_adapter.py`의
     `approved_media_archive_record_to_shorts_script()`가
     `review_status != "approved"`면 `ShortsAdapterError`를 던진다.
   - `content_engine/blog_publish_pack.py`의
     `select_approved_blog_candidates_from_archive()`가
     `review_status == "approved"`만 후보로 삼는다.
   - `scripts/publish_approved_threads.py`가 대상으로 삼는
     `tak_threads_pending.json`의 draft는 애초에 `/media`에서
     `review_status`를 `approved`로 바꿀 때만
     (`handle_media_approve_submission` → `upsert_pending`) 생성된다.

한 가지 예외를 발견했다: `scripts/generate_blog_publish_pack.py`를
`--from-archive` **없이** 실행하면(기본 모드) `build_blog_publish_pack()`이
방금 실행한 `MediaBatchReport`에서 "KNOWLEDGE가 승인됐는가"만 보고 Blog
Publishing Pack을 만든다 - **콘텐츠(문구) 단위 사람 승인 없이** Pack에
포함될 수 있다. 다만 실제로 매일 자동 실행되는 워크플로
(`.github/workflows/daily-media-prepare.yml` → `scripts/
prepare_approved_media.py`)는 이 기본 모드를 쓰지 않고, 명시적으로
`--from-archive`(승인 게이트 적용 모드)만 호출한다
(`scripts/prepare_approved_media.py` 108~117행). 즉 **자동화된 운영
경로에는 우회가 없고**, 사람이 CLI를 직접 `--from-archive` 없이 수동
실행할 때만 이 경로를 탈 수 있다 - Naver 게시 자체도 항상 사람이 손으로
복사/붙여넣기하므로 즉각적인 위험은 낮지만, 원칙적으로는 승인 게이트를
우회할 수 있는 CLI 옵션 조합이 남아 있다는 사실은 14장에 기록해 둔다(이번
세션에서 CLI의 fallback 동작 자체를 바꾸지는 않았다 - 기존 사용자가 그
기본 모드에 의존하고 있을 가능성을 배제할 수 없어, 동작을 바꾸는 결정은
범위 밖으로 판단했다).

### 3-3. 발견한 문제와 수정 - 6개 회귀 테스트의 낡은 스냅샷 가정

`python -m pytest -q` 6개 실패 전부 원인이 같았다: 6-06/6-07 시절 작성된
회귀 테스트가 실제 `data/tak_media_archive.json`을 직접 읽어
"정확히 9건"이라고 하드코딩했는데, 6-12가 실제로 9건을 더 승격시켜 지금은
18건이 정상이다. **코드 버그가 아니라 테스트의 낡은 가정**이었으므로(6-13
지시 2장 "문서에 적힌 내용보다 현재 코드와 현재 데이터가 우선"), 안전한
범위로 판단해 이번 세션에서 직접 수정했다.

| 파일 | 실패 테스트 | 수정 내용 |
| --- | --- | --- |
| `tests/test_media_versioning_and_promotion.py` | `test_real_production_archive_records_are_legacy_generations` | "전체 9건"이 아니라 "`generation_id is None`인 legacy 부분집합만 9건"으로 범위를 좁힘 |
| 〃 | `test_production_archive_still_has_exactly_nine_unreviewed_legacy_records` | 위와 동일하게 legacy 부분집합만 검사 |
| 〃 | `test_new_generation_added_to_a_temp_copy_does_not_drop_existing_nine` | 절대값 `10` 대신 `len(original) + 1`로 비교(원본이 몇 건이든 "1건 추가돼도 기존이 사라지지 않는다"는 본질은 동일) |
| `tests/test_second_knowledge_correction_and_generation_pool.py` | `test_all_nine_start_as_unreviewed` | 이름/내용을 `test_all_nine_are_approved_after_6_12_review`로 변경 - 6-12에서 사람이 이미 approve-all을 실행했으므로 현재 실제 상태는 "unreviewed"가 아니라 "approved" |
| 〃 | `test_no_content_id_collision_with_production_archive` | `test_content_ids_are_now_promoted_into_production_archive`로 변경 - promotion 전에는 "겹치지 않아야" 정상이었지만, 6-12에서 실제로 승격됐으므로 이제는 "pool의 9건이 production의 부분집합"이어야 정상(반대로 뒤집힘). generation_id/review_status까지 함께 재검증하도록 강화 |
| 〃 | `test_production_archive_still_has_only_the_original_nine_records` | `test_production_archive_still_has_the_original_nine_plus_promoted_nine`로 변경 - legacy 9건(불변) + 6-12가 승격한 9건(`generation_id` 값까지 특정) = 18건임을 검증 |

이 수정들은 검증하는 안전장치의 본질(legacy 레코드가 손상 없이 보존되는가,
같은 content_id의 승격 전/후가 정확히 대응하는가)을 하나도 약화시키지
않았다 - 단지 "정확히 9건"이라는 스냅샷을 "legacy 9건은 여전히 9건"으로
좁히거나, "이제는 이렇게 바뀌는 게 맞다"로 갱신했을 뿐이다. 수정 후
`python -m pytest -q tests/test_media_versioning_and_promotion.py
tests/test_second_knowledge_correction_and_generation_pool.py` → **42
passed**.

## 4. 이번 작업에서 구현한 내용

기존 구조(Publish Pack, 게시 이력, Dashboard downstream 상태)가 이미
상당히 완성되어 있음을 확인했으므로(6장·7장), 새 시스템을 만드는 대신
아래 세 가지로 범위를 좁혀 기존 구조를 확장했다.

1. **YouTube 업로드 중복 방지** - Blog(`PublishHistory.is_published`)/
   Threads(`PublishHistory.is_published` + pending draft 상태)에는 이미
   있던 "이미 게시된 content_id는 다시 게시하지 않는다" 안전장치가
   YouTube 업로드(`scripts/upload_youtube_short.py`)에는 없었다(업로드
   전 이력을 전혀 확인하지 않고 무조건 API를 호출했다). `content_engine/
   youtube_upload_history.py`에 `published_content_ids()`/`is_published()`를
   추가하고(기존 `PublishHistory`와 동일한 이름/관례), CLI가 `--content-id`가
   이미 이력에 있으면 dry-run/live 모두 API를 호출하지 않고 기존
   `video_id`/URL만 안내하도록 했다.
2. **Dashboard downstream 상태에 "YouTube 업로드됨" 추가** -
   `compute_media_downstream_status()`(5-29, `/media` 목록·상세 화면)가
   Shorts에 대해 "Script 생성됨 (MP4 생성됨/미생성)"까지만 보여주고
   실제 YouTube 업로드 여부는 전혀 반영하지 않았다. `YouTubeUploadHistory`를
   읽어 업로드 이력이 있으면 "YouTube 업로드됨"을 보여주도록 확장했다 -
   `review_status=="approved"`(사람의 승인)와 실제 게시 여부를 같은
   의미로 취급하지 않는다는 6-13 지시 5장의 원칙을 Blog/Threads에 이어
   Shorts/YouTube까지 완전히 맞췄다.
3. **6-12로 인해 낡아진 6개 회귀 테스트의 스냅샷 가정 보정**(3-3장).

## 5. 수정된 파일 목록

| 파일 | 무엇을 | 왜 | 핵심 함수/route | 데이터 흐름 역할 |
| --- | --- | --- | --- | --- |
| `content_engine/youtube_upload_history.py` | `published_content_ids()`, `is_published()` 메서드 추가 | `PublishHistory`와 동일한 중복 판정 수단을 YouTube 이력에도 제공 | `YouTubeUploadHistory.published_content_ids/is_published` | content_id 기준으로 "이미 YouTube에 업로드됐는가"를 판정하는 단일 진실 소스 |
| `scripts/upload_youtube_short.py` | 업로드 전 `content_id` 중복 검사 추가(중복이면 API 호출 없이 기존 이력 안내 후 종료) | 중복 게시 방지(6-13 지시 6장) - Blog/Threads와 동일한 idempotency 원칙 적용 | `main()` | Shorts→YouTube 업로드 CLI의 진입점 - 승인된 Shorts Script를 실제 업로드하는 마지막 단계 |
| `scripts/run_scout_dashboard.py` | `DashboardConfig.youtube_history_path` 필드 추가(기본값 있음, 기존 호출부 무수정 동작), `compute_media_downstream_status()`의 Shorts 분기에 YouTube 업로드 여부 확인 추가 | Human Review 화면에서 "승인됨"과 "실제 게시됨"을 구분해 보여주기 위함(6-13 지시 5·7장) | `compute_media_downstream_status()`, `/media`, `/media/{content_id}` | Production Archive 레코드 1건이 지금 어디까지 진행됐는지 사람이 한눈에 보는 화면 |
| `tests/test_media_versioning_and_promotion.py` | 3개 테스트의 하드코딩된 "9건" 가정을 legacy 부분집합/상대값 비교로 수정 | 6-12로 production archive가 18건이 된 것을 반영(3-3장) | `GenerationIdTests`, `ExistingProductionArchiveUntouchedTests` | 회귀 테스트 |
| `tests/test_second_knowledge_correction_and_generation_pool.py` | 3개 테스트를 6-12 이후 실제 상태(approved, promoted)에 맞게 이름/내용 변경 | 〃 | `RealGenerationPoolResultTests` | 회귀 테스트 |
| `tests/test_upload_youtube_short_cli.py` | dry-run/live 각각에서 중복 content_id를 건너뛰는지, 새 content_id는 정상 업로드되는지 검증하는 테스트 3건 추가 | 4장 1번 기능 검증 | `UploadYouTubeShortCLITests` | 회귀 테스트 |
| `tests/test_youtube_upload_history_dedup.py`(신규) | `published_content_ids()`/`is_published()` 단위 테스트 5건 | 4장 1번 기능 검증(기존 파일 분리 관례를 따라 새 파일로 추가) | `YouTubeUploadHistoryDedupTests` | 회귀 테스트 |
| `tests/test_media_dashboard.py` | `youtube_history_path`를 테스트 config에 연결하고, "YouTube 업로드됨" 상태 전이를 검증하는 테스트 1건 추가 | 4장 2번 기능 검증 | `MediaDownstreamStatusHttpTests` | 회귀 테스트 |
| `docs/6-13_publish_operation_report.md`(신규) | 이 보고서 | 6-13 지시 13장 | - | 인수인계 문서 |

이번 세션이 건드리지 않은 것: `data/` 아래 어떤 JSON 파일도 쓰지 않았다
(11장), `scripts/generate_blog_publish_pack.py`의 기본 모드 동작은
바꾸지 않았다(3-2장 - 정책 결정이 필요해 범위 밖으로 남김), 기존
미커밋 변경(`gitignore`, `content_engine/generator.py` 등)은 전혀
건드리지 않았다.

## 6. Publish Pack 구조

셋 다 "새로 설계"가 아니라 **이미 존재하는 구조를 확인**한 것이다 - 6-13
지시 4장이 예시로 든 필드 목록과 대조해 무엇이 이미 있고 무엇이 없는지
정리한다.

### Blog Publish Pack

`content_engine/blog_publish_pack.py`의 `BlogPublishItem` +
`build_blog_publish_pack_from_archive()`(승인된 archive 레코드 기반,
6-08 이후 운영에서 실제로 쓰이는 경로). 필드: `sequence`, `title`, `body`,
`category`(추천), `keywords`, `hashtags`, `image_ideas`, `knowledge_id`,
`source_url`, `review_required`(금융/대출/경매/부동산 여부),
`content_id`. `render_markdown()`으로 사람이 바로 복사할 수 있는 Markdown
(`data/blog_publish_pack_daily.md`)을 만든다. 지시 4장이 예시로 든
"생성일"/"검수 상태" 텍스트 라벨은 없지만(둘 다 "예:"로 표시된 선택
항목), `content_id`로 production archive를 다시 조회하면 `created_at`/
`review_status`를 얻을 수 있어 정보 자체가 없는 것은 아니다 - 이번
세션에서는 낮은 우선순위로 판단해 추가하지 않았다(15장 추천 참고).

### Threads Publish Pack

별도의 "Pack 파일"이 아니라 `content_engine/threads_review.py`의
`ThreadsPendingDraft`(`data/tak_threads_pending.json`)가 그 역할을 한다.
필드: `content_id`, `knowledge_id`, `source_url`, `evidence_unit_ids`,
`original_*`/`ai_rewritten_*`/`final_*`(게시 텍스트), `status`
(`pending`→`approved`→`published`|`failed`, 곧 승인 상태 자체),
`threads_post_id`, `published_at`/`failed_at`/`failure_reason`. 지시
4장의 "게시 순서/thread group"은 현재 데이터 모델에 대응 개념이 없다 -
`content_engine/models.py`의 `ThreadDraft`는 각각 독립된 단일 게시물이고,
여러 게시물을 하나의 스레드(멀티 포스트)로 묶는 기능 자체가 없다(생성
단계부터 없음). 필요해지면 별도 설계가 필요하다(15장에 남김).

### Shorts Publish Pack

`content_engine/shorts_adapter.py`의 `save_approved_shorts_script()`가
`data/shorts_scripts/<content_id>.json`으로 저장하는 ShortsScript JSON이
그 역할. 필드: `content_id`, `knowledge_id`, `platform`, `title`,
`subtitle`, `cards`(카드 순서), `takeaway`, `brand`, `created_at`. 지시
4장 예시 중 `source_url`은 저장 스키마에 없다(`ShortDraft`에는 있지만
저장 시 드롭됨) - `content_id`로 archive를 다시 조회하면 얻을 수 있다.
"업로드 준비 상태"는 이 파일의 존재 자체가 "준비됨"을 뜻하고, 실제
업로드 여부는 이번 세션에서 추가한 `YouTubeUploadHistory`로 별도 판정한다
(7장).

## 7. 게시 상태 구조

지시 5장의 핵심 원칙("`review_status=="approved"`가 곧
`publish_status=="published"`가 되어서는 안 된다")을 **이미 대부분
지키고 있었고**, 이번 세션은 마지막 빈틈(Shorts/YouTube)만 메웠다.
새로운 `publish_status` 필드나 상태 기계를 새로 만들지 않았다 - 기존
채널별 이력 파일을 그때그때 읽어서 계산하는 `compute_media_downstream_status()`
(`scripts/run_scout_dashboard.py`, 5-29)가 이미 이 책임을 지고 있었기
때문이다(같은 결정을 다시 설계하지 않고 그대로 확장).

| 플랫폼 | DRAFT(승인 전) | READY(승인됨, 미게시) | PUBLISHED | FAILED |
| --- | --- | --- | --- | --- |
| Blog | "승인 전" | "승인됨 (Pack 생성 가능)" | "게시 기록됨"(`blog_publish_log.json`에 기록되면) | 없음(사람이 직접 게시하므로 API 실패 개념 자체가 없음) |
| Threads | "승인 전" | "승인됨 (대기열 생성 예정)"/`pending`/`approved` 라벨 | "발행됨"(`ThreadsPendingDraft.status=="published"`) | "발행 실패"(`status=="failed"`, `failure_reason` 보존) |
| Shorts/YouTube | "승인 전" | "Script 생성됨 (MP4 미생성/생성됨)" | **"YouTube 업로드됨"(이번 세션에서 추가, `youtube_publish_log.json` 기준)** | 없음(업로드 실패 시 이력에 기록하지 않고 종료 코드만 반환 - 14장 LOW 항목) |

세 플랫폼 모두 `review_status`(승인 여부)와 게시 상태(위 표)가 **서로
다른 필드/계산**이며, 하나가 다른 하나를 자동으로 바꾸지 않는다 -
`review_status`는 오직 `/media`, `/media/generations`의 승인 액션으로만
바뀌고, 게시 상태는 오직 각 채널의 실제 게시 이력 파일로만 바뀐다.

## 8. 중복 게시 방지 구조

| 플랫폼 | 판정 기준 | 저장소 | 기존/신규 |
| --- | --- | --- | --- |
| Blog | `content_id` | `PublishHistory`(`data/blog_publish_log.json`) | 기존(5-10) |
| Threads | `content_id` | `PublishHistory`(`data/threads_publish_log.json`) + `ThreadsPendingDraft.status` | 기존(5-10/5-11) |
| YouTube | `content_id`(선택적 - `--content-id` 생략 시 판정 불가) | `YouTubeUploadHistory`(`data/youtube_publish_log.json`) | **신규(이번 세션, `published_content_ids()`/`is_published()`)** |

셋 다 실제 외부 API 호출은 이 세션에서 하지 않았다 - YouTube의 신규
중복 방지도 순수 로컬 파일 비교(성공 시에만 append되는 이력)로 동작하며,
`--content-id`를 생략한 기존 호출은(6-02 이전 관례) 판정 대상에서
자동으로 제외되어 하위 호환을 깨지 않는다.

## 9. Human Review와의 관계

`/media`(production archive 최종 검수)와 `/media/generations`(promotion
전 generation pool 검수) 둘 다 이번 세션이 새로 만들지 않았다(6-07/6-08).
이번 세션이 `/media` 목록·상세 화면에 더한 것은 오직 "YouTube 업로드됨"
downstream 라벨 하나뿐이다 - 승인/보류/수정 폼, 라우트 구조, generation
pool과의 관계(3-2장)는 전혀 바꾸지 않았다. `/media/generations`는 이번
세션에서 아예 건드리지 않았다.

## 10. Production Archive와의 관계

`data/tak_media_archive.json`(`MediaArchiveRecord`) 자체의 스키마/저장
로직(`content_engine/media_archive.py`)은 이번 세션에서 전혀 수정하지
않았다. 이번 세션이 다룬 모든 "게시 상태"는 이 파일을 **읽기만** 해서
(`review_status`, `content_id`) 다른 채널별 이력 파일과 조인해 계산한
파생 정보다 - production archive에 새 필드를 추가하지 않았다(예:
`publish_status` 컬럼을 archive 레코드 자체에 넣지 않았다 - 채널별 이력
파일이 이미 그 역할을 하고 있어 중복 저장소를 만들 필요가 없다고
판단했다).

## 11. 데이터 무결성 검증

이번 세션이 시작된 이후 종료 시점까지 `data/` 아래 어떤 JSON도 쓰지
않았다. 아래는 이번 세션 종료 시점의 실측값이며, `tak_media_archive.json`/
generation pool 두 파일의 해시는 6-12 보고서가 기록한 종료 시점 값과
**정확히 일치**한다(3-1장).

| 파일 | SHA-256 | 레코드 수 | 이번 세션 중 변경 여부 |
| --- | --- | --- | --- |
| `data/tak_media_archive.json` | `ebe1249f...`(6-12 종료 값과 동일) | 18 | 없음 |
| `data/tak_media_generation_6-07_knowledge-scout-6d1d0e2fa762.json` | `9aa3677e...`(6-12 종료 값과 동일) | 9 | 없음 |
| `data/tak_threads_pending.json` | `9dd8a8c0...` | 5(pending 4, approved 1) | 없음(이 세션은 읽기만 함 - 값 자체는 세션 시작 전 사용자의 별개 활동으로 이미 이 상태였음) |
| `data/tak_brain_knowledge.json` | `a4cbb521...` | 28(approved 6 / pending 13 / rejected 9) | 없음 |
| `data/threads_publish_log.json` | `d8907429...` | 7 | 없음 |
| `data/youtube_publish_log.json` | `a6c94919...` | 1 | 없음 |
| `data/blog_publish_log.json` | (파일 없음) | 0 | 없음(존재한 적 없음) |

이번 세션이 실제로 변경한 파일은 `git status --short`(12장) 기준 소스
코드 3개 + 테스트 4개(수정) + 테스트 1개(신규) + 이 보고서뿐이며, 그 외
이번 세션 시작 시점에 이미 존재하던 기존 미커밋 변경(`data/
tak_brain_knowledge.json`, `data/tak_threads_pending.json` 포함)은 세션
시작 때와 완전히 동일하게 남아 있다(위 해시들도 그 사실을 재확인한다 -
세션 시작 전부터의 diff는 있지만, 세션 **도중**의 추가 변경은 없다).

## 12. 테스트 결과

```
$ python -m pytest -q          # 작업 시작 시점(수정 전)
924 passed, 68 subtests passed, 6 failed in 158.47s

$ python -m pytest -q tests/test_media_versioning_and_promotion.py \
    tests/test_second_knowledge_correction_and_generation_pool.py   # 3-3장 수정 직후
42 passed in 3.33s

$ python -m pytest -q tests/test_upload_youtube_short_cli.py \
    tests/test_youtube_upload_history_dedup.py \
    tests/test_youtube_upload_history.py \
    tests/test_youtube_upload_history_content_id.py                # 4장 1번 기능
32 passed in 0.25s

$ python -m pytest -q tests/test_media_dashboard.py                 # 4장 2번 기능
44 passed in 21.44s

$ python -m pytest -q          # 전체 재실행(최종)
939 passed, 68 subtests passed in 143.27s (0:02:23)
```

실패 0건. 삭제하거나 약화시킨 테스트는 없다(3-3장에 각 수정의 근거를
기록) - 오히려 8건의 테스트를 새로 추가했다(YouTube 중복 방지 5건 +
CLI 3건 + Dashboard 1건 = 9건, 이 중 8건이 순증가이고 나머지는 기존
6건을 대체).

## 13. Git 결과

```
$ git branch --show-current
main

$ git rev-parse HEAD origin/main   # 작업 시작 시점
cefe257224273126c41800332831fc796ab89ddc
cefe257224273126c41800332831fc796ab89ddc
```

이번 세션이 수정/추가한 파일 9개만 정확히 `git add`했다(기존 미커밋
변경은 포함하지 않음):

```
$ git add content_engine/youtube_upload_history.py \
    scripts/run_scout_dashboard.py \
    scripts/upload_youtube_short.py \
    tests/test_media_versioning_and_promotion.py \
    tests/test_second_knowledge_correction_and_generation_pool.py \
    tests/test_upload_youtube_short_cli.py \
    tests/test_youtube_upload_history_dedup.py \
    tests/test_media_dashboard.py \
    docs/6-13_publish_operation_report.md
$ git status --short   # 위 9개 파일만 M/A로 표시, 나머지는 기존과 동일한 M/?? 그대로
```

```
$ git commit -m "feat: add YouTube dedup + publish status visibility, fix stale 6-06/6-07 snapshots (6-13)" (+본문)
[main 745d67c] feat: add YouTube dedup + publish status visibility, fix stale 6-06/6-07 snapshots (6-13)
 9 files changed, 824 insertions(+), 24 deletions(-)
 create mode 100644 docs/6-13_publish_operation_report.md
 create mode 100644 tests/test_youtube_upload_history_dedup.py
```

**커밋 해시: `745d67c`**

```
$ git push
To https://github.com/sopptak/tak-auto
   cefe257..745d67c  main -> main

$ git fetch origin
$ git log origin/main..HEAD --oneline
(출력 없음)
$ git log HEAD..origin/main --oneline
(출력 없음)
```

**Push 완료. origin/main과 완전히 동기화됨(양방향 모두 비어 있음).**

```
$ git status --short
```

커밋 직후 `git status --short`가 작업 시작 시점(2장)과 정확히 같은
기존 미커밋(`.gitignore`, `content_engine/__init__.py`,
`content_engine/generator.py`, `content_engine/llm_provider.py`,
`content_engine/rewrite.py`, `data/tak_brain_knowledge.json`,
`data/tak_threads_pending.json`, `tests/test_content_engine.py`,
`tests/test_media_batch.py`)과 untracked 문서/스크립트만 남았고, 이번에
커밋한 9개 파일은 더 이상 목록에 나타나지 않는다 - 이번 작업에서
만든/수정한 파일만 정확히 commit됐고, 기존 미커밋 변경은 작업 시작 때와
동일하게 그대로 보존됐다.

## 14. 남은 문제

**HIGH**
- (없음)

**MEDIUM**
- `scripts/generate_blog_publish_pack.py`를 `--from-archive` 없이 수동
  실행하면 콘텐츠(문구) 단위 사람 승인 없이 Blog Publishing Pack이
  만들어진다(3-2장). 실제 자동화 워크플로는 이 경로를 쓰지 않지만, CLI
  수준에서는 여전히 가능하다 - 기본 동작을 바꿀지, 아니면 최소한
  `--from-archive`를 쓰지 않을 때 경고 문구를 출력할지는 정책 결정이
  필요해 이번 세션에서 판단을 미뤘다.
- YouTube 업로드 실패는 `youtube_publish_log.json`에 전혀 기록되지 않는다
  (성공 시에만 append, 실패는 stderr 출력 후 종료 코드 1로만 남는다) -
  Threads(`failed` 상태)와 비대칭이다. 실패 이력이 없으면 "왜 이 Shorts만
  업로드가 안 됐는지" 나중에 추적하기 어렵다.
- `content_engine/performance/` 패키지(6-01, 성과 데이터 기반)는 이미
  완성돼 있지만 이를 호출하는 GitHub Actions workflow가 하나도 없다
  (`scripts/collect_performance.py` 자체 docstring이 이를 명시). 성과
  데이터가 실제로 쌓이려면 사람이 CLI를 수동 실행해야 한다.

**LOW**
- Blog Publishing Pack(`BlogPublishItem`)에 "생성일"/"검수 상태" 텍스트
  라벨이 없다(6장) - `content_id`로 다시 조회하면 얻을 수 있는 정보라
  기능 손실은 아니다.
- ShortsScript 저장 파일(`data/shorts_scripts/<content_id>.json`)에
  `source_url`이 없다(6장) - 마찬가지로 archive 재조회로 우회 가능.
- Threads Publish Pack에는 "게시 순서/thread group"(멀티 포스트 스레드)
  개념이 없다 - 현재 생성 단계(`content_engine/models.py`)부터 각 Threads
  콘텐츠가 독립된 단일 게시물이라 대응할 데이터가 아예 없다. 실제로
  멀티 포스트 스레드가 필요해지면 생성 단계부터 재설계가 필요하다.

## 15. 다음 작업 추천

1. **`generate_blog_publish_pack.py` 기본 모드 정책 결정**(14장 MEDIUM
   1번) - `--from-archive`를 기본값으로 바꿀지, 명시적 경고를 추가할지
   사람이 결정한 뒤 구현.
2. **성과 데이터 수집 자동화** - `scripts/collect_performance.py`를
   호출하는 workflow(예: 주간 1회, `workflow_dispatch` 우선 - 6-01이
   이미 만든 `--dry-run`/`--confirm-live`/`GITHUB_ACTIONS` 3중 안전장치를
   그대로 재사용) 설계. 실제 API 토큰을 CI에 넣는 결정이 선행돼야 한다.
3. **YouTube 업로드 실패 이력 기록**(14장 MEDIUM 2번) - Threads의
   `mark_failed()`와 대칭되는 구조를 `YouTubeUploadHistory` 또는 별도
   저장소에 추가.
4. **`/media` 화면에 성과 요약 노출** - `/performance`(6-01)가 이미
   있으니, production archive 레코드 상세 화면에 해당 `content_id`의
   최신 성과 스냅샷을 링크/요약으로 연결(이미 있는
   `content_engine.performance.summarize_content_history()` 재사용
   가능).
5. **Blog/Shorts/Threads 실제 게시 1회차 실행** - 6-12가 Production
   Promotion을 실제로 1회 실행해본 것처럼, 이번에 준비된 Publish Pack/
   중복 방지 구조로 실제 Blog 1건(사람이 Naver에 직접 게시 +
   `mark_blog_published.py` 기록) 또는 승인된 Threads 1건
   (`publish_approved_threads.py --execute`, 이미 존재하는 CLI)을
   사람이 명시적으로 승인한 뒤 실제로 실행해, 이 세션이 정리한 게시
   상태 구조가 실제 데이터로도 "PUBLISHED"까지 도달하는지 확인.

## 16. 작업 결론

**PASS**

- 코드 변경은 전부 기존 구조의 순수 확장(중복 방지 메서드 추가, downstream
  상태 라벨 하나 추가)이며 새 저장소/새 상태 기계를 만들지 않았다.
- 6-12가 만든 실제 production 데이터는 이번 세션 동안 단 한 번도 쓰이지
  않았다(11장 해시로 재확인).
- 전체 테스트 939 passed, 0 failed(12장).
- 실제 외부 플랫폼(Naver/Threads/YouTube) 게시, 실제 계정에 영향을 주는
  작업은 이번 세션에서 전혀 수행하지 않았다.
- 정책 판단이 필요한 항목(14장 MEDIUM)은 코드로 임의 수정하지 않고
  명시적으로 다음 작업으로 넘겼다.
