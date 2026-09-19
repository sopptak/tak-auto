# TAK MEDIA 운영 파이프라인 완성 단계 (5-29)

작업 시작: commit `0e6778d` 기준. 이 문서는 작업 중 계속 갱신되며, 최종적으로
이 문서 하나만 읽으면 이번 작업에서 무엇을 했고 무엇이 남았는지 알 수 있도록
작성한다.

## 1. 작업 시작 상태

- 기준 commit: `0e6778d` ("feat: add human edit + dismiss on MEDIA Dashboard, wire Blog/Shorts downstream")
- 전체 pytest: 669 passed, 68 subtests passed
- 완료된 흐름: SCOUT → INTERVIEW → KNOWLEDGE → 승인 → TAK MEDIA 9개 생성 →
  ARCHIVE → MEDIA Dashboard(사람 수정/저장/승인/보류) → Blog downstream(Pack
  생성 함수) → Shorts downstream(ShortsScript 객체 반환) → Threads pending 연결
- 알려진 남은 작업(사용자 지정):
  1. ShortsScript를 실제 파일로 영구 저장하는 단계 없음
  2. Blog `--from-archive`는 수동 CLI 실행
  3. Dashboard에 승인 후 다음 행동 안내 없음
  4. Blog/Shorts/Threads의 downstream 상태를 한눈에 확인하기 어려움
  5. 향후 자동화할 수 있는 운영 단위가 아직 CLI 중심으로 흩어져 있음

(진행 중 - 아래 섹션은 조사/구현 진행에 따라 계속 채워진다)

## 2. 기존 구조 조사

### A. MEDIA archive가 현재 저장하는 상태

`content_engine/media_archive.py`의 `MediaArchiveRecord`: `content_id`,
`knowledge_id`, `platform`, `generation_status`(valid/rejected/error),
`original_title/body`, `rewritten_title/body`, `edited_title/body`(nullable),
`final_title/body`(property: edited 우선, 없으면 rewritten, 그것도 없으면
original), `source_url`, `evidence`, `evidence_unit_ids`, `created_at`,
`validation_errors`, `error_message`, `review_status`(unreviewed/approved/
dismissed). 저장 파일 `data/tak_media_archive.json`은 실제 운영에서 아직 한 번도
생성된 적이 없다(로컬에 파일 자체가 없음 - 이전 세션들에서 전부 tmp_path로만
테스트).

### B. approved 콘텐츠가 채널별로 어디까지 이동 가능한가 (현재)

- **Threads**: MEDIA 승인(`handle_media_approve_submission`) → 이미
  `content_engine.threads_review.upsert_pending()`으로
  `data/tak_threads_pending.json`에 `status="pending"` draft 생성 → 기존
  `/threads` Dashboard 화면에서 사람이 재검토/최종 승인(`status="approved"`)
  → `scripts/publish_approved_threads.py --execute`(사람이 수동 실행,
  workflow_dispatch 전용)로 실제 게시 + `threads_publish_log.json` 기록.
  **이미 완결된 체인.**
- **Blog**: MEDIA 승인은 archive의 `review_status`만 바꾼다. 그 다음은
  `scripts/generate_blog_publish_pack.py --from-archive`(5-28에서 추가)를
  사람이 수동 실행해야 `data/blog_publish_pack_daily.md`가 만들어진다.
  실제 게시는 사람이 네이버에 직접 복사/붙여넣기 후
  `scripts/mark_blog_published.py`로 수동 기록. **Pack 생성이 자동 연결되어
  있지 않다(오늘 작업 대상 #2).**
- **Shorts**: MEDIA 승인은 archive의 `review_status`만 바꾼다.
  `content_engine.shorts_adapter.approved_media_archive_record_to_shorts_script()`
  는 존재하지만 이 함수를 실제로 호출해 파일로 저장하는 코드가 어디에도 없다.
  **가장 크게 비어 있는 연결 지점(오늘 작업 대상 #1).**

### C. Blog/Shorts/Threads 사이에 downstream 상태를 "추가로" 저장할 필요가 있는가

- **Threads**: 필요 없음. `data/tak_threads_pending.json`의
  `ThreadsPendingDraft.status`(pending/approved/published/failed) 자체가
  이미 downstream 상태의 단일 진실 공급원(source of truth)이다. Dashboard는
  이 파일을 읽기만 하면 된다.
- **Blog**: 필요 없음. "Pack에 들어갔는지"는 별도로 저장할 상태가 아니라
  "현재 승인됐고 아직 게시 이력(`data/blog_publish_log.json`, `PublishHistory`)에
  없는" 상태에서 **항상 유도 가능한 사실**이다(Pack은 매번 현재 승인 목록에서
  다시 계산되는 스냅샷이지, 한 번 생성되면 고정되는 이벤트가 아니다). 따라서
  Dashboard에는 "승인됨(Pack 생성 가능)" vs "게시 기록됨" 2단계만 표시하면
  충분하고, 이 두 값 모두 기존 `PublishHistory.is_published()`로 이미 판단
  가능하다.
- **Shorts**: 오늘 새로 만들 `data/shorts_scripts/<content_id>.json`
  **파일의 존재 여부 자체**가 "Script 생성됨" 상태를 그대로 나타낸다. 별도
  인덱스나 DB가 필요 없다 - 파일 존재 확인이 곧 상태 조회다. MP4 존재 여부도
  마찬가지로 `data/shorts/<content_id>.mp4` 존재 확인으로 충분하다(단, 이
  경로에 실제로 파일이 생기게 만드는 렌더링은 이번 작업에서 절대 실행하지
  않는다 - 사람이 나중에 `scripts/render_youtube_short.py`를 수동 실행했을
  경우를 위한 "있는 그대로 읽기"일 뿐이다).

**결론: 새로운 저장소/DB는 만들지 않는다.** 유일한 신규 파일은 Shorts용
`data/shorts_scripts/<content_id>.json`인데, 이것도 "새 DB"가 아니라 기존
`content_engine/shorts_script.py`의 `ShortsScript.from_dict()`가 이미 읽을 수
있는 스키마(title/subtitle/cards/takeaway/brand) + 추적용 메타데이터(
content_id/knowledge_id/platform/created_at, `from_dict()`가 무시하는
필드)를 그대로 담은 파일이다. `scripts/render_youtube_short.py --input`에
바로 넘길 수 있다(무수정 호환).

### D. 재사용 가능한 기존 구조

- `content_engine/threads_review.py`의 원자적(tempfile+replace) 저장 패턴 -
  Shorts JSON 저장도 동일 패턴을 그대로 쓴다.
- `content_engine.publish_history.PublishHistory`/`compute_content_id` -
  Blog downstream 상태 판정에 그대로 재사용(새 로직 없음).
- `content_engine.shorts_adapter.approved_media_archive_record_to_shorts_script()`
  (5-29 이전 세션에서 이미 구현) - 오늘은 이 함수의 결과를 "파일로 저장"만
  추가한다. 변환 로직 자체는 무수정.
- `content_engine.blog_publish_pack.build_blog_publish_pack_from_archive()`
  (5-29 이전 세션) - Blog Pack 생성 자체는 이미 완성되어 있음. 오늘은 이걸
  "하나의 명확한 운영 명령"으로 확인/보완만 한다(아래 5장 참고).
- GitHub Actions 조사 결과(`.github/workflows/*.yml` 4개 전부 확인):
  `daily-scout.yml`(SCOUT 수집만, 게시 없음), `daily-threads-post.yml`
  (cron이 이미 5-19에서 비활성화됨 - 자동 실제 게시 없음, workflow_dispatch만
  남음), `publish-approved-threads.yml`(workflow_dispatch 전용, dry-run
  기본값 true), `youtube-shorts-upload.yml`(workflow_dispatch 전용, dry-run
  기본값 true). **네 workflow 모두 이미 "자동 실제 게시"가 켜져 있지 않다** -
  이번 작업에서 새 workflow를 만들거나 기존 workflow를 활성화할 필요도,
  이유도 없다(10장에서 설계 메모만 남긴다).

### E. 새 저장소가 정말 필요한가 — 최종 판단

필요한 것은 딱 하나: `data/shorts_scripts/<content_id>.json` (Shorts
렌더러가 이미 읽는 스키마의 파일, 새 DB 아님). 그 외 모든 downstream 상태는
기존 파일(`tak_threads_pending.json`, `blog_publish_log.json`, 파일 존재
여부)을 읽어서 그때그때 계산한다.

## 3. 발견한 문제

1. Shorts는 "ShortsScript 객체 반환"에서 멈춰 있고 파일로 저장하는 코드가
   없다 - 렌더러(`scripts/render_youtube_short.py`)가 입력으로 받을 파일
   자체가 생성되지 않는다.
2. Blog Pack 생성이 MEDIA 승인과 완전히 분리된 별도 수동 CLI 실행으로만
   가능하다 - 승인 후 "다음에 뭘 해야 하는지" Dashboard에 안내가 없다.
3. Dashboard `/media` 목록과 `/media/<id>` 상세 어디에도 승인 이후
   downstream(Pack/Script/pending) 진행 상태가 보이지 않는다 - 승인 버튼을
   누른 뒤 결과를 확인하려면 파일 시스템을 직접 뒤져야 한다.
4. Threads/Shorts/Blog 세 채널의 "승인 시점 자동 연결 정도"가 서로 다르다
   (Threads는 이미 자동, Blog/Shorts는 수동) - 이 비대칭이 의도적인지 우연인지
   문서화된 적이 없었다.

## 4. 설계 결정

### 결정 1 — MEDIA 승인 POST에서 Shorts는 자동 연결하고, Blog는 하지 않는다

**핵심 근거(코드 조사 결과):** Threads pending 생성과 Shorts Script 생성은
둘 다 "레코드 1건 -> 파생 파일/상태 1건"의 순수하고 멱등(idempotent)한
변환이며, 외부 API를 호출하지 않는다 - Threads는 이미 승인 POST 안에서 이
패턴으로 동작하고 있다(5-28). Shorts도 정확히 같은 성격이므로 동일하게 승인
POST 안에서 자동 연결해도 안전하다.

반면 **Blog Pack은 레코드 1건짜리 변환이 아니라, "현재 승인된 모든 Blog
레코드 중에서" 서로 다른 KNOWLEDGE 우선 + 게시 이력 제외 + `max_count`
제한을 적용해 매번 다시 고르는 배치(batch) 선정 결과물**이다
(`select_approved_blog_candidates_from_archive`). 어떤 Blog 레코드 1건을
승인하는 시점에 Pack 전체를 재생성하면, 그 Pack의 실제 구성(어떤 5건이 뽑히는지)
은 그 시점 이후에 승인될 수도 있는 "다른" Blog 레코드에 따라 계속 달라진다 -
즉 "승인 시점에 즉시 Pack을 만든다"는 개념 자체가 이 선정 로직과 맞지 않는다
(매번 다시 계산해야 의미가 있는 스냅샷이지, 승인 1건에 대응하는 고정된
산출물이 아니다). 그래서 Blog Pack 생성은 여전히 "승인된 것들을 모아 한 번에
계산하는" 별도의 명시적 배치 단계(`--from-archive`)로 남긴다.

**따라서:** Threads(기존 유지) + Shorts(오늘 추가)는 승인 POST에서 자동
연결한다. Blog는 명시적 CLI(`scripts/generate_blog_publish_pack.py
--from-archive`, 필요하면 `scripts/prepare_approved_media.py`로 다른
채널과 함께 한 번에)로 분리된 채로 둔다. 이 비대칭은 리스크 회피가 아니라
Blog 선정 로직 자체의 구조적 차이(1건 vs 배치) 때문이다.

### 결정 2 — Shorts Script 저장은 idempotent(이미 있으면 재생성 안 함)

`data/shorts_scripts/<content_id>.json`이 이미 있으면 다시 쓰지 않는다.
요구사항 3장/4장에 명시된 "이미 같은 content_id 파일이 존재하면 중복 생성하지
않는다"를 문자 그대로 구현한다. 부작용: Script 생성 **이후**에 사람이 MEDIA
화면에서 다시 수정하더라도(승인 취소 없이 재수정은 애초에 불가능하도록
5-28에서 이미 막아뒀다 - approved면 수정 폼 자체가 안 보임) 파일이 자동
갱신되지는 않는다. 재생성하려면 사람이 파일을 직접 지워야 한다 - 이는 이미
Blog의 "게시 완료 후에는 `mark_blog_published.py`로 사람이 명시적으로
기록해야 한다"는 것과 같은 성격의 "최종 확정은 사람이 명시적으로"라는 이
프로젝트의 기존 원칙과 일치한다.

### 결정 3 — downstream 상태는 새 저장소 없이 기존 파일을 읽어서 계산한다

2장 C에서 이미 근거를 기록했다. 요약: Threads는
`tak_threads_pending.json`, Blog는 `blog_publish_log.json`
(`PublishHistory`), Shorts는 `data/shorts_scripts/<content_id>.json`
존재 여부. 셋 다 "쓰기"가 아니라 "읽기"로만 상태를 계산한다.

### 결정 4 — 통합 운영 CLI(`scripts/prepare_approved_media.py`)는 만든다, 단 아주 얇게

Blog(`--from-archive`)와 Shorts(신규 `generate_approved_shorts_script.py`)
둘 다 이미 각자 안전한(외부 호출 없는) 단독 CLI로 존재하므로, 통합 CLI는 새
비즈니스 로직을 넣지 않고 그 둘의 `main()`을 순서대로 호출 + Threads pending
현황을 읽기 전용으로 요약 출력하는 것까지만 한다(`scripts/run_daily.py`가
`scripts.publish_threads.main(...)`을 함수로 호출하는 기존 관례와 동일).
"매번 여러 CLI를 따로 실행하지 않아도 된다"는 요구를 얇은 오케스트레이터로
해결한다 - 새 저장/판단 로직은 없다.

### 결정 5 — GitHub Actions는 이번 단계에서 손대지 않는다

조사 결과 4개 workflow 모두 이미 "실제 자동 게시"가 꺼져 있다(2장 D). 오늘
추가하는 세 작업(Blog Pack/Shorts Script 생성, 통합 CLI)은 전부 LLM/외부
API를 전혀 쓰지 않으므로, 이론적으로는 가장 안전하게 자동화할 수 있는
후보다(Secrets가 전혀 필요 없다). 다만 이번 작업 범위에는 포함하지 않고,
아래 "다음 단계 제안"에 설계 메모로만 남긴다.

## 5. 구현 내용

### 5-1. Shorts 영구 저장 (`content_engine/shorts_adapter.py`)

- `shorts_script_output_path(output_dir, content_id)` — 경로 계산 규칙을
  한 곳에만 둔다(CLI, 승인 자동 연결, 존재 여부 확인이 전부 같은 함수를 쓴다).
- `save_approved_shorts_script(record, output_dir, brand=..., created_at=...)`
  — 이미 파일이 있으면 그대로 반환(중복 생성 안 함), 없으면
  `approved_media_archive_record_to_shorts_script()`(무수정)로 변환한 뒤
  `tempfile` + `Path.replace()`로 원자적 저장. 저장 스키마:
  `{content_id, knowledge_id, platform, title, subtitle, cards, takeaway,
  brand, created_at}` — 앞 5개(title~brand)는 `ShortsScript.from_dict()`가
  읽는 그대로라 `scripts/render_youtube_short.py --input`에 바로 넘길 수
  있다(수동 확인 완료).

### 5-2. Shorts CLI (`scripts/generate_approved_shorts_script.py`, 신규)

`--content-id` 지정 시 그 1건이 `platform=shorts`가 아니거나
`generation_status!=valid`이거나 `review_status!=approved`이면 각각 다른
문구로 exit 1(명확한 오류). 생략하면 조건을 만족하는 전체를 처리하고
불만족 항목은 조용히 건너뛴다(개수만 보고). `--dry-run` 지원. MP4
렌더링/YouTube 업로드 코드는 import조차 하지 않는다(정적 확인).

### 5-3. Blog 운영 CLI 보완 (`scripts/generate_blog_publish_pack.py`)

기존 `--from-archive`(5-28)가 이미 "승인된 것만 → Pack" 요건을 만족했음을
재확인(수동 smoke test: `--knowledge/--archive/--history/--pack-output` 네
인자 + `--from-archive`만으로 한 번에 완결). 유일하게 보완한 것: `--limit`을
`--from-archive`와 함께 주면(이 모드에서는 무시되는 값) 조용히 무시하는
대신 안내 문구를 출력하도록 1줄 추가 - 기존 기본 동작(비-archive 모드)은
전혀 수정하지 않았다.

### 5-4. Dashboard downstream 상태 + 다음 단계 안내 (`scripts/run_scout_dashboard.py`)

- `DashboardConfig`에 `shorts_scripts_path`(기본 `data/shorts_scripts`),
  `blog_history_path`(기본 `data/blog_publish_log.json`) 필드 추가(둘 다
  기본값이 있어 기존 호출부/테스트가 그대로 동작).
- `compute_media_downstream_status(record, config)` — 새 저장소 없이 기존
  파일만 읽어서 상태 문자열을 계산(2장 C/결정 3 그대로 구현).
- `/media` 목록 카드에 downstream 상태 1줄 추가, `/media/<id>` 상세에
  "⑦ Downstream 상태" 섹션 신규 추가(현재 상태 + `review_status==approved`일
  때만 `_MEDIA_NEXT_STEP_HINTS`의 채널별 안내 문구).
- `handle_media_approve_submission()`에 `shorts_scripts_path` 파라미터 추가
  - `platform=="shorts"`면 승인 즉시 `save_approved_shorts_script()` 자동
    호출(결정 1). 실패해도 승인 자체(`review_status` 갱신)는 이미 끝난
    뒤이므로 승인을 되돌리지 않는다(방어적 처리, 정상 경로에서는 발생하지
    않음 - 조건은 이미 승인 직전에 확인됨).
  - `platform=="threads"` 자동 연결은 5-28 그대로 무수정.
  - `platform=="blog"`는 이 함수에서 아무 것도 자동 실행하지 않는다(결정 1
    근거 그대로).

### 5-5. 통합 운영 CLI (`scripts/prepare_approved_media.py`, 신규)

새 비즈니스 로직 없음 - `generate_blog_publish_pack.main([..., "--from-archive"])`와
`generate_approved_shorts_script.main([...])`을 순서대로 함수 호출하고,
Threads는 `tak_threads_pending.json`을 읽기 전용으로 요약 출력만 한다(결정
4). 세 단계 중 어느 것도 LLM/외부 API를 호출하지 않는다 - Secrets이 전혀
필요 없는 CLI다.

### 5-6. GitHub Actions

**변경 없음.** 2장 D/결정 5에 근거를 기록한 대로, 이번 작업에서는 workflow
파일을 하나도 만들거나 수정하지 않았다. "다음 단계 제안"에 설계 메모만
남긴다(아래 최종 보고 18장).

## 6. 테스트

사용자 지정 A~R 전부 대응:

| 항목 | 검증 위치 |
|---|---|
| A. approved Shorts → ShortsScript JSON 생성 | `tests/test_prepare_approved_media.py`, 수동 smoke test + `generate_approved_shorts_script.py` 자체 CLI 실행으로 확인. `save_approved_shorts_script`의 직접 단위 테스트는 기존 `tests/test_shorts_adapter.py`의 변환 테스트와 결합해 `MediaDownstreamStatusHttpTests::test_shorts_downstream_status_shows_script_ready_after_approval`(승인 → 실제 파일 존재)로 커버 |
| B. edited 콘텐츠가 ShortsScript에 반영 | 기존(5-29 이전 세션) `tests/test_shorts_adapter.py::ApprovedMediaArchiveRecordConversionTests::test_approved_record_uses_edited_content_when_present` |
| C. 미승인 Shorts 거부 | 기존 `test_not_yet_approved_raises` (shorts_adapter) |
| D. REJECTED Shorts 거부 | 기존 `test_non_valid_generation_status_raises` (shorts_adapter) |
| E. 동일 content_id 재실행 시 중복 없음 | `generate_approved_shorts_script.py` idempotent 동작을 수동 smoke test로 확인(2번째 실행이 "건너뜀" 출력) - `save_approved_shorts_script`의 존재 확인 분기가 핵심 로직 |
| F. approved Blog → Pack 생성 | 5-28 세션의 `BlogPublishPackFromArchiveTests::test_only_approved_blog_records_become_candidates` |
| G. edited Blog 콘텐츠가 Pack에 반영 | 5-28 `test_build_pack_from_archive_uses_final_title_and_body` |
| H. 미승인 Blog 제외 | 5-28 `test_only_approved_blog_records_become_candidates` |
| I. 이미 게시 기록이 있는 Blog 제외 | 5-28 `test_candidate_excluded_after_marked_published` |
| J. Threads pending 상태 표시 | `tests/test_media_dashboard.py::MediaDownstreamStatusHttpTests::test_threads_downstream_status_reflects_pending_file_status`, `test_threads_downstream_status_before_approval` |
| K. Dashboard downstream 상태 표시 | `test_list_shows_blog_ready_for_pack_before_publish`, `test_blog_downstream_status_shows_published_once_history_recorded`, `test_shorts_downstream_status_shows_script_ready_after_approval` |
| L. 승인 후 다음 단계 안내 표시 | `test_next_step_hint_shown_after_{blog,shorts,threads}_approval`, `test_no_next_step_hint_before_approval` |
| M. 실제 외부 API 호출 없음 | `test_prepare_approved_media.py::test_module_never_imports_external_clients_or_renderer` + 기존 dashboard 정적 검사 재확인 |
| N. 실제 LLM 호출 없음 | 위 정적 검사(llm_provider/OpenAICompatibleRewriteProvider import 없음) + 5-28 `mocked_from_env.assert_not_called()` |
| O. 실제 MP4 렌더링 없음 | 위 정적 검사(shorts_renderer import 없음) |
| P. 실제 YouTube 업로드 없음 | 위 정적 검사(youtube_publisher/YouTubeClient import 없음) |
| Q. 실제 Naver 게시 없음 | 위 정적 검사(naver 토큰 문자열이 import 구문에 없음, Naver 클라이언트 자체가 이 코드베이스에 없음) |
| R. 기존 669개 테스트 회귀 없음 | 전체 pytest 684 passed(기존 669 + 신규 15), 실패 0 |

신규 테스트 파일: `tests/test_prepare_approved_media.py`(5건). 기존 파일
확장: `tests/test_media_dashboard.py`(+9, downstream 상태/다음 단계 안내),
`tests/test_blog_publish_pack.py`(+1, `--limit` 무시 안내 문구).

## 7. 보안/외부 호출 검증

- 새로 만들거나 수정한 모든 파일(`content_engine/shorts_adapter.py`,
  `content_engine/blog_publish_pack.py`, `scripts/run_scout_dashboard.py`,
  `scripts/generate_approved_shorts_script.py`,
  `scripts/prepare_approved_media.py`,
  `scripts/generate_blog_publish_pack.py`)에서
  `ThreadsClient`/`YouTubeClient`/`threads_publisher`/`youtube_publisher`/
  `shorts_renderer`/naver 관련 import를 grep으로 전수 확인 - **전부 없음**.
- 시크릿 값(API key, refresh token 등)을 print/로그로 출력하는 코드 없음 -
  이번에 추가한 코드는애초에 환경변수 자체를 전혀 읽지 않는다(archive/knowledge
  파일만 읽고 쓴다).
- `git diff` 전체에서 하드코딩된 API key/secret/private key 패턴 grep -
  **매치 없음**.
- 실제 외부 API 호출이 필요한 상황 자체가 발생하지 않았다(이번 작업 범위가
  전부 로컬 파일 읽기/쓰기이므로 mock 전환이 필요한 지점이 없었다).

## 8. Git 변경사항

**변경 파일**(기존 추적 파일):
- `content_engine/shorts_adapter.py`
- `scripts/generate_blog_publish_pack.py`
- `scripts/run_scout_dashboard.py`
- `tests/test_blog_publish_pack.py`
- `tests/test_media_dashboard.py`

**신규 파일**:
- `scripts/generate_approved_shorts_script.py`
- `scripts/prepare_approved_media.py`
- `tests/test_prepare_approved_media.py`
- `docs/5-29_media_operational_pipeline.md`(이 문서)

**이번 작업과 무관해 commit에 포함하지 않은 기존 미커밋 변경**(그대로 보존):
`.gitignore`, `content_engine/__init__.py`, `content_engine/generator.py`,
`content_engine/llm_provider.py`, `content_engine/rewrite.py`,
`data/tak_brain_knowledge.json`, `tests/test_content_engine.py`,
`tests/test_media_batch.py`, 그리고 그 외 다수의 이전 세션 untracked 파일.

**작업 중 발견/수정한 사고**: 테스트 실행 중 `DashboardConfig`의 새 필드
(`shorts_scripts_path`, `blog_history_path`)에 기본값으로 실제 프로덕션
경로(`data/shorts_scripts`, `data/blog_publish_log.json`)가 들어있는데,
`tests/test_media_dashboard.py`의 기존 두 테스트 클래스가 이 필드들을
명시적으로 tmp 경로로 넘기지 않고 있었다. 그 결과 첫 전체 테스트 실행에서
실제로 `data/shorts_scripts/content-shorts-1.json`이 생성되는 사고가
발생했다 - 즉시 발견해 (1) 두 테스트 클래스의 `DashboardConfig` 생성부에
tmp 경로를 명시적으로 추가하고 (2) 방금 전 테스트가 실수로 만든 파일 1개를
삭제해 원상 복구했다(파일 생성 시각이 이번 세션 작업 시각과 정확히 일치함을
`stat`으로 확인 후 삭제 - 사용자의 기존 데이터가 아님을 검증했다). 이후
재실행으로 더 이상 프로덕션 경로에 파일이 생기지 않음을 확인했다.

## 9. 최종 결과

- 전체 pytest: **684 passed, 68 subtests passed, 0 failed**
- 실제 LLM 호출: 없음
- 실제 Threads 발행: 없음
- 실제 YouTube 업로드: 없음
- 실제 Naver 게시: 없음
- production 데이터(`data/tak_brain_knowledge.json`,
  `data/tak_threads_pending.json`, `data/blog_publish_pack_daily.md`) 수정
  시각이 이번 세션 이전과 동일함을 `stat`으로 확인 - 손대지 않았다.

## 10. 남은 작업

아래 "다음 단계 제안"(최종 보고 18장)과 동일 내용을 요약하면: GitHub
Actions 자동화 설계 검토, Dashboard 수정 이력(누가 언제 무엇을 고쳤는지)
기록, Blog "Pack에 이미 포함됨" 표시(현재는 승인/게시 2단계만 구분),
Shorts MP4 렌더링 연결, 승인 취소(rollback) 기능.

---

# [MEDIA OPERATIONAL PIPELINE 완료 보고]

## 1. 작업 기준 commit

`0e6778d` (이번 작업 시작 시점 main)

## 2. 변경 파일

- `content_engine/shorts_adapter.py` — `save_approved_shorts_script()`,
  `shorts_script_output_path()` 추가
- `scripts/generate_blog_publish_pack.py` — `--from-archive` + `--limit` 조합
  시 안내 문구 추가(기본 동작 무수정)
- `scripts/run_scout_dashboard.py` — downstream 상태 계산/표시, 다음 단계
  안내, Shorts 승인 자동 연결, `DashboardConfig` 필드 2개 추가
- `tests/test_blog_publish_pack.py`, `tests/test_media_dashboard.py` — 관련
  테스트 보강

## 3. ShortsScript 영구 저장

`content_engine/shorts_adapter.save_approved_shorts_script()`가
`data/shorts_scripts/<content_id>.json`에 원자적으로 저장. 이미 있으면
재생성하지 않음(idempotent). `ShortsScript.from_dict()` 호환 스키마 +
`content_id`/`knowledge_id`/`platform`/`created_at` 추적 필드. MEDIA 승인
시점에 `platform=="shorts"`면 자동 생성되고, 별도 CLI
`scripts/generate_approved_shorts_script.py`(`--content-id`/`--dry-run`
지원)로도 수동 실행 가능. MP4 렌더링/YouTube 업로드는 절대 호출하지 않음.

## 4. Blog Publishing Pack 연결

기존 `scripts/generate_blog_publish_pack.py --from-archive`(5-28)가 이미
"승인된 것만 → Pack" 요건을 만족함을 재확인. `--limit`이 이 모드에서
무시된다는 사실을 안내 문구로 명확히 함. LLM/Naver API 호출 없음(그대로).
MEDIA 승인 POST에서는 자동 실행하지 않음 - Blog Pack은 여러 레코드를 모아
매번 다시 계산하는 배치 결과물이라 "레코드 1건 승인 = Pack 1개 생성"이라는
대응이 성립하지 않기 때문(4장 결정 1 근거).

## 5. Dashboard downstream 상태

`/media` 목록 카드 + `/media/<id>` 상세 "⑦ Downstream 상태" 섹션에 채널별
실제 상태 표시. 새 저장소 없이 기존 파일(`tak_threads_pending.json`,
`blog_publish_log.json`, `shorts_scripts/<id>.json` 존재 여부)만 읽어서
계산. `review_status=="approved"`일 때 채널별 "다음 단계" 안내 문구도 함께
표시.

## 6. 통합 운영 CLI

`scripts/prepare_approved_media.py`(신규) — Blog Pack 준비 +
Shorts Script 준비 + Threads pending 현황 요약을 한 명령으로 실행. 새
비즈니스 로직 없이 기존 두 CLI를 함수로 호출할 뿐이며, Secrets이 전혀
필요 없다(LLM/외부 API를 아무 것도 호출하지 않으므로).

## 7. 중복 방지

- Shorts: 파일 존재 확인 후 있으면 재생성 안 함(`save_approved_shorts_script`).
- Blog: 순수 함수라 상태 누적이 없고, `PublishHistory` 기록 후 자동 후보
  제외(5-28에서 이미 검증, 이번에 재확인).
- Threads: 기존 `upsert_pending()`의 "이미 있으면 덮어쓰지 않음" 가드
  무수정 재사용, 새 저장 구조를 만들지 않음.
- MEDIA archive 자체: content_id 기준 upsert(5-27부터 유지).

## 8. 데이터 보존

`original_title/body`, `rewritten_title/body`, `edited_title/body`,
`final_title/body`(계산 프로퍼티), `validation_errors`, `review_status`,
`generation_status`, `created_at`, `content_id`, `knowledge_id` 전부
이번 작업에서 스키마·값 어느 쪽도 변경하지 않았다 - 오직 이 값들을
"읽어서" downstream 파일을 만드는 코드만 추가했다.

## 9. 테스트 결과

A~R 전부 대응 완료(6장 표 참고). 신규 5건(`test_prepare_approved_media.py`)
+ 기존 파일 확장 10건(`test_media_dashboard.py` +9,
`test_blog_publish_pack.py` +1).

## 10. 전체 pytest 결과

**684 passed, 68 subtests passed, 0 failed**

## 11. 실제 LLM 호출 여부

**없음.**

## 12. 실제 Threads 발행 여부

**없음.**

## 13. 실제 YouTube 업로드 여부

**없음.**

## 14. 실제 Naver 게시 여부

**없음.**

## 15. commit

(아래 실행 후 기록)

## 16. push

(아래 실행 후 기록)

## 17. 남은 작업

- Blog Pack "이미 포함됨" 세분화 표시(현재는 승인/게시 2단계만 구분, Pack에
  실제로 뽑혔는지는 표시 안 함 - 매번 다시 계산되는 값이라 저장하지 않기로
  했음, 필요하면 Pack 생성 시점에 "최근 Pack 포함 여부"를 읽기 전용으로
  다시 계산해 보여주는 것은 가능).
- Shorts MP4 렌더링을 이 파이프라인에 연결하는 것은 여전히 사람의 별도
  판단 영역으로 남겨둠(의도된 설계).
- 승인 취소(approved -> unreviewed rollback) 기능 없음 - 현재는 승인이
  사실상 종결 상태.
- Dashboard에 "누가 언제 수정/승인했는지" 감사 로그 없음(단일 운영자
  가정이라 우선순위 낮음).

## 18. 다음 단계 제안

1. `scripts/prepare_approved_media.py`를 매일 아침 실행하는 GitHub Actions
   workflow 추가 검토 - LLM/외부 API를 전혀 쓰지 않으므로 Secrets 없이도
   동작하는, 이 프로젝트에서 가장 안전하게 자동화할 수 있는 후보다(단,
   실제 발행은 여전히 별도 승인 workflow로 분리 유지).
2. Blog Pack에 "이번에 실제로 뽑힌 content_id 목록"을 Markdown과 함께
   가볍게 기록해 두면(새 DB 없이 Pack 파일 자체에 주석으로), Dashboard에서
   "이 항목이 최근 Pack에 포함됐는지"까지 보여줄 수 있다.
3. Shorts Script가 쌓인 뒤 사람이 렌더링을 결정하는 화면(예:
   `/media`에서 "Script 생성됨" 항목만 모아 보여주는 필터 조합 활용법
   안내)을 문서화.
4. 승인 취소(rollback) 버튼 - 실수로 승인한 경우 되돌릴 방법이 현재
   없다(REJECTED/ERROR처럼 명확히 실패한 게 아니라 "사람이 잘못 눌렀다"는
   케이스).
5. `content_engine/shorts_renderer.py`/`scripts/render_youtube_short.py`를
   실제로 `data/shorts_scripts/*.json`과 연결해 렌더링까지 자동화할지는
   별도 승인 단계로 신중히 설계(MP4 생성 자체는 외부 API가 아니지만, 그
   다음 YouTube 업로드로 이어지는 입구이므로).
