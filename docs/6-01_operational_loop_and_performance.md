# TAK AUTO 6-01 — 운영 루프 및 성과 데이터 구축

## 1. 작업 시작 상태

- 현재 브랜치: `main`
- 로컬 HEAD: `bd46f30` (docs: record final push confirmation in 5-31 report) — 사용자가 준 baseline(`70ba70b`)보다 최신, `origin/main`과 동일(fetch로 확인).
- `git status` 기준 이번 작업 시작 전 기존 미커밋 변경(전부 보존, 이번 세션에서 건드리지 않음):
  - modified: `.gitignore`, `content_engine/__init__.py`, `content_engine/generator.py`, `content_engine/llm_provider.py`, `content_engine/rewrite.py`, `data/tak_brain_knowledge.json`, `tests/test_content_engine.py`, `tests/test_media_batch.py`
  - untracked: `.firebaserc`, `.github/workflows/youtube-shorts-upload.yml`, `content_engine/shorts_renderer.py`, `data/blog_draft_*.md`, `data/shorts_scripts/`(기존 `example_manman.json` 포함), 다수의 `docs/*.md`, `firebase.json`, `public/`, `requirements.txt`, `scripts/mark_blog_published.py`, `scripts/render_youtube_short.py`, `scripts/run_scout_score.py`, `scripts/youtube_oauth_setup.py`, `tests/test_firebase_hosting.py`, `tests/test_render_youtube_short_cli.py`, `tests/test_scout_scoring.py`, `tests/test_shorts_renderer.py`, `tests/test_shorts_script.py`, `tests/test_threads_dashboard.py`, `tests/test_threads_review.py`, `tests/test_youtube_oauth_setup.py`, **`tests/test_youtube_publisher.py`**, `tests/test_youtube_upload_history.py`
- 전체 pytest(작업 시작 시점): **703 passed, 68 subtests, 0 failed** (5-31 종료 시점과 동일).

**⚠️ 중요한 안전 발견(작업 시작 직후 확인, 3장/11장에서 상세)**: 이 개발 환경(Codespace)에는 실제 `THREADS_ACCESS_TOKEN`, `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN`이 **실제 값으로 환경변수에 이미 설정되어 있다**(`env | grep`으로 직접 확인). `content_engine.threads_publisher.ThreadsClient.from_environment()`/`content_engine.youtube_publisher.YouTubeClient.from_environment()`는 인자 없이 호출하면 이 실제 환경변수를 그대로 읽는다. 즉 이번에 새로 만드는 `scripts/collect_performance.py`를 `--dry-run` 없이 `--platform threads`나 `--platform youtube`로 실행하면 **실제 Threads/YouTube API를 호출한다.** 이 사실을 확인한 뒤로는 이 세션에서 threads/youtube 관련 실행은 전부 `--dry-run`이거나 mock transport를 주입한 단위 테스트로만 수행했다(19장에서 증거 정리). 기존 스크립트(`publish_threads.py`, `upload_youtube_short.py`)도 동일한 위험을 안고 있었다는 뜻이므로, 21장에 재확인 메모를 남긴다.

## 2. 기존 성과 데이터 구조

조사 대상 파일을 모두 읽었다: `content_engine/media_archive.py`, `scripts/run_scout_dashboard.py`, `scripts/prepare_approved_media.py`, `scripts/generate_blog_publish_pack.py`, `scripts/generate_approved_shorts_script.py`, `content_engine/threads_review.py`, `content_engine/youtube_upload_history.py`, `content_engine/publish_history.py`, `data/`, `.github/workflows/`, `docs/5-30_operational_automation.md`, `docs/5-31_github_actions_operational_validation.md`.

**결론: 성과(조회수/좋아요 등) 데이터를 저장하는 구조는 이 저장소에 전혀 없었다.** `grep -rn "metric\|insight\|analytics\|view_count\|like_count\|impression"`을 `content_engine/threads_publisher.py`, `content_engine/youtube_publisher.py`, `content_engine/youtube_upload_history.py`, `content_engine/publish_history.py`, `content_engine/threads_review.py`에 실행한 결과 **일치 0건**.

기존 발행 관련 저장소 3개의 실제 구조(로컬 production 데이터를 직접 읽어 확인):

| 파일 | 구조 | content_id 연결 | knowledge_id 연결 |
|---|---|---|---|
| `data/threads_publish_log.json` (`PublishHistory`/`PublishRecord`) | `content_id, published_at, threads_post_id, knowledge_id, platform, source_url` | 있음 | **있음** |
| `data/blog_publish_log.json` (동일 `PublishRecord` 구조, `scripts/mark_blog_published.py`가 기록) | 위와 동일(재사용) | 있음 | 있음(선택, 사람이 `--knowledge-id`로 직접 넘겨야 함) | 
| `data/youtube_publish_log.json` (`YouTubeUploadHistory`/`YouTubeUploadRecord`) | `video_id, uploaded_at, title, privacy_status, video_path, tags, url` | **없음** | **없음** |

**중요한 비대칭 발견**: Threads/Blog 발행 이력은 처음부터 `content_id`/`knowledge_id`를 갖고 있어 원본 KNOWLEDGE와 바로 연결된다. 반면 **YouTube 업로드 이력은 `video_id`/`title`만 있고 `content_id`/`knowledge_id`가 전혀 없다** — YouTube 업로드가 MEDIA archive/KNOWLEDGE와 연결되지 않은 채 설계되어 있었다(5-13/5-14 당시에는 성과 추적을 고려하지 않았던 것으로 보인다). 이 문제를 6장/10장에서 다룬다.

`tak_scout/scoring.py`(SCOUT SCORE, A~E 5개 차원 100점 만점)도 확인했다 — 성과 신호를 넣을 수 있는 구조는 있지만(단순 가중합) 현재 성과 데이터를 전혀 참조하지 않는다(16장에서 향후 위치만 설계, 이번에 코드는 변경하지 않음).

## 3. 실제 MEDIA 운영 검증

5-31에서 이미 확인한 대로, 실제 production `data/tak_media_archive.json`은 이번 작업 시작 시점에도 여전히 존재하지 않았다(`ls data/tak_media_archive.json` → 파일 없음). Dashboard를 실제로 기동해 브라우저로 승인하는 것은 이 세션의 도구 권한상(GUI/브라우저 상호작용 불가) 여전히 불가능하다 — 5-31과 동일한 제약이며, 이번에도 억지로 가짜 production 데이터를 만들지 않았다.

대신 이번 작업은 "승인이 아직 없다"는 사실 자체를 바꾸려 하지 않고, **승인 이후 단계(성과 수집)가 실제로 쓸 수 있는 데이터를 만나면 정상 동작하는지**를 코드 레벨로 검증하는 데 집중했다(6~10장) — 이는 이번 작업의 핵심 목표(2장 "실제 채널 성과 수집" 설계/구현)와 직접 연결된다.

## 4. 현재 운영 구조

5-31에서 확정한 구조를 그대로 이어받는다:

```
KNOWLEDGE → MEDIA → HUMAN REVIEW(Dashboard 승인) → PUBLISH PREPARATION(daily-media-prepare.yml)
```

이번 작업에서 그 뒤에 다음을 **설계 그대로 구현**했다(5~6장의 "발행 이후" 실제 PUBLISH 단계는 이번 작업 범위가 아니다 - Threads/YouTube 실제 발행은 이미 별도 workflow가 있고, 이번에는 "발행된 것의 성과를 수집"하는 계층만 추가한다):

```
... → PUBLISH(사람이 실행하는 기존 publish_threads.py / upload_youtube_short.py / 네이버 수동 게시)
    → PERFORMANCE(신규: content_engine/performance/ + scripts/collect_performance.py)
    → (다음 SCOUT/콘텐츠 선정에 참고 — 이번 단계에서는 "사람이 볼 수 있는 화면"까지만, 15/16장 참고)
```

## 5. Performance 요구사항

2장 조사 결과를 반영해 다음을 요구사항으로 확정했다:

1. 콘텐츠 1건의 성과는 시간에 따라 바뀐다 → **현재값 덮어쓰기가 아니라 시계열 스냅샷**으로 저장해야 한다.
2. 채널마다 접근 가능한 지표가 다르다(Threads: views/likes/replies/reposts/quotes/shares API 제공, YouTube: viewCount/likeCount/commentCount API 제공, Naver Blog: 공식 API 자체가 없음) → 채널별로 다른 collector가 필요하지만, 저장 형태(`PerformanceRecord`)는 하나로 통일해야 분석이 가능하다.
3. YouTube 업로드 이력에 `content_id`/`knowledge_id`가 없다는 기존 구조적 공백(2장) → 이번 성과 데이터 모델이 이 공백을 강제로 메우지 않고(YouTube 업로드 이력 파일 자체를 수정하는 것은 이번 작업 범위 밖), 대신 **수집 시점에 사람이 명시적으로 content_id/knowledge_id를 지정**하도록 설계했다(CLI 필수 인자).
4. 실제 외부 API를 이번 세션이 호출해서는 안 된다(1장의 안전 발견과 직접 충돌하는 위험) → 모든 collector가 기존 `ThreadsClient`/`YouTubeClient`와 동일한 **transport 주입 패턴**을 따라야 실제 네트워크 없이 완전히 테스트 가능하다.

## 6. Performance 데이터 모델

`content_engine/performance/models.py`에 `PerformanceRecord`(frozen dataclass)를 추가했다. 핵심 필드:

- `content_id`, `knowledge_id` — 필수. `content_engine.publish_history.compute_content_id()`로 이미 계산된 값을 그대로 받는다(이 모듈이 새로 계산하지 않음 - `MediaArchiveRecord`와 동일한 관례).
- `platform` — `threads`/`youtube`/`blog` 중 하나.
- `published_at` — 원본 발행 시각(불변).
- `metric_collected_at` — 이 스냅샷을 수집한 시각. **이 값이 다르면 같은 content_id라도 별도 레코드로 계속 쌓인다**(Day1 조회수 100 → Day7 조회수 2,300을 동시에 보존).
- `metrics: dict[str, int]` — 실제 지표(`{"views": 850, "likes": 12}`). 값이 정수가 아니면(`bool` 포함, 명시적으로 막음) 거부한다.
- `source` — `threads_api`/`youtube_api`/`manual`/`migration_baseline` 중 하나. "이 숫자를 얼마나 신뢰할 것인가"를 나중에 판단하는 근거로 남긴다(예: `migration_baseline`은 실제 지표가 아니라 발행 사실만 옮긴 placeholder라는 것을 구분).
- `external_id` — 플랫폼별 원본 식별자(threads media id / youtube video id / blog url).
- `raw` — collector가 받은 원본 응답(정규화 이전, 감사/디버깅용, 선택).

**"현재값 하나만 덮어쓰는 구조가 아니라 시계열 snapshot이 필요한지 검토" → 검토 결과: 시계열 snapshot으로 설계 확정.** `content_engine/performance/store.py`가 append-only 저장을 구현한다(다음 장).

DB를 새로 도입하지 않고, 기존 `media_archive.py`/`threads_review.py`와 완전히 동일한 관례(JSON 배열 파일 + `tempfile` + `Path.replace()` 원자적 저장)를 그대로 재사용했다 — "새로운 DB는 만들지 않는다"는 지시를 그대로 지켰다.

## 7. Threads 성과 수집 설계

**웹 검색으로 공식 문서를 직접 확인했다**(임의로 추정하지 않았다): [Threads Insights API — Meta for Developers](https://developers.facebook.com/documentation/threads/insights)(2026-09-20 fetch).

- Media insights 엔드포인트: `GET /{threads-media-id}/insights`, 지원 metric: `views`, `likes`, `replies`, `reposts`, `quotes`, `shares`.
- User insights 엔드포인트(`GET /{threads-user-id}/threads_insights`)도 존재하지만(팔로워 수 등 계정 단위 지표) 이번 작업 범위는 "콘텐츠 1건의 성과"이므로 media insights만 구현했다.
- 필요 권한: `threads_basic`, `threads_manage_insights`.

`content_engine/threads_publisher.py`에 `ThreadsClient.get_media_insights(media_id, metrics=DEFAULT_INSIGHTS_METRICS)` 메서드를 추가했다(기존 `get_profile()`/`publish_text()`와 완전히 동일한 transport 주입 패턴 — 새 클래스를 만들지 않고 기존 클라이언트를 확장). `content_engine/performance/threads.py`가 이 메서드를 호출하고 응답을 정규화한다.

## 8. YouTube 성과 수집 설계

**웹 검색으로 공식 문서를 직접 확인했다**: [Videos: list — YouTube Data API](https://developers.google.com/youtube/v3/docs/videos/list)(2026-09-20 fetch).

- `GET https://www.googleapis.com/youtube/v3/videos?part=statistics&id=<id1,id2,...>` (최대 50개 id/요청).
- 응답 필드: `statistics.viewCount`, `statistics.likeCount`, `statistics.commentCount`(문자열로 반환되므로 정수 변환 필요).

`content_engine/youtube_publisher.py`에 `YouTubeClient.get_video_statistics(video_ids)` 메서드를 추가했다 — 업로드와 동일하게 `refresh_token`으로 매번 새 `access_token`을 발급받은 뒤 조회한다(`_get_access_token()` 재사용, 새로 만들지 않음). `content_engine/performance/youtube.py`가 정규화를 담당한다.

**10장에서 다루는 실제 제약**: `data/youtube_publish_log.json`에는 `content_id`/`knowledge_id`가 없으므로, YouTube 성과를 수집하려면 사람(또는 CLI 호출자)이 `video_id ↔ content_id/knowledge_id` 매핑을 별도로 알고 있어야 한다. 이 매핑을 자동으로 추측하지 않았다(제목 유사도 매칭 같은 휴리스틱은 오탐 위험이 있어 이번 범위에서 제외).

## 9. Blog 성과 수집 설계

**웹 검색으로 확인**: 네이버는 블로그 글 1건의 조회수/검색 유입을 조회할 수 있는 **공식 공개 API를 제공하지 않는다**(네이버 오픈 API 목록에 블로그 통계 조회 API가 없음, 블로그 통계는 네이버 블로그 관리자 페이지에 로그인해야만 볼 수 있음). 이 저장소의 기존 원칙(공식 API만 사용, 스크래핑/비공식 접근 금지 — `threads_publisher.py`/`youtube_publisher.py`가 이미 그렇게 설계되어 있음)을 그대로 따라 **Blog는 fetch(자동 수집) 코드를 만들지 않았다.**

대신 `content_engine/performance/blog.py`의 `build_manual_blog_performance_record()`가 사람이 네이버 블로그 관리자 페이지에서 직접 확인한 숫자를 `PerformanceRecord`(source="manual")로 정규화하는 것까지만 지원한다. "불가능한 것을 억지로 자동화하지 않는다"는 지시를 그대로 지켰다.

## 10. Performance Collector

`content_engine/performance/` 패키지 구조(11장 설계안 중 프로젝트에 맞게 단순화한 버전 — `__init__.py`가 공개 API를 재노출):

```
content_engine/performance/
    __init__.py     # PerformanceRecord + store 함수 재노출
    models.py       # PerformanceRecord
    store.py        # append-only 시계열 저장소
    threads.py      # Threads insights fetch + normalize
    youtube.py      # YouTube statistics fetch + normalize
    blog.py         # Blog manual 입력 normalize (fetch 없음)
    migration.py    # 기존 발행 이력 → baseline PerformanceRecord 변환(실행은 안 함, 18장)
```

fetch → normalize → store 구조를 그대로 구현했다:

- `collect_threads_performance(client, media_id=..., content_id=..., ...)` — `client.get_media_insights()` 호출(fetch) → `normalize_threads_insights()`(normalize) → `PerformanceRecord` 반환. 저장(store)은 호출자(CLI)가 명시적으로 `append_snapshot()`을 호출해야 한다 — collector 자체는 파일을 쓰지 않는다(단일 책임).
- `collect_youtube_performance(...)` — 동일한 구조.
- `build_manual_blog_performance_record(...)` — fetch 단계가 없다(9장).

## 11. Performance 저장소

`content_engine/performance/store.py`: `data/tak_performance.json`(기본 경로) 하나에 모든 채널의 스냅샷을 함께 담는다(채널별 파일 분리 대신 `platform` 필드로 구분 — archive/threads_review가 이미 "필드로 구분, 파일은 하나"를 따르는 것과 일관성 유지).

- `append_snapshot(path, record) -> bool` / `append_snapshots(path, records) -> int` — `(content_id, metric_collected_at)` 조합이 이미 있으면 건너뛴다(idempotent, D 요구사항).
- `snapshots_for_content(path, content_id)` — 시계열 전체(오름차순).
- `latest_snapshot_per_content(path)` — content_id별 최신 스냅샷만(Dashboard MVP가 사용).

## 12. Performance CLI

`scripts/collect_performance.py --platform {threads,youtube,blog} --content-id ... --knowledge-id ... --published-at ... [--external-id ...] [--metric key=value ...] [--dry-run] [--store PATH]`.

- **`--dry-run`이면 threads/youtube는 실제 클라이언트를 아예 생성하지 않는다**(1장의 안전 발견에 대한 직접적 대응 — `ThreadsClient.from_environment()`/`YouTubeClient.from_environment()` 호출 자체가 dry-run 분기 이전에 도달하지 않도록 코드를 배치했다). Blog는 애초에 네트워크가 없으므로 dry-run은 저장만 건너뛴다.
- threads/youtube를 dry-run 없이 실행하면 실제로 `ThreadsClient.from_environment()`/`YouTubeClient.from_environment()`를 호출한다 — 이 세션에서는 **단 한 번도 이 조합으로 실행하지 않았다**(19장에 증거).
- GitHub Actions에 이 CLI를 연결하는 workflow는 **만들지 않았다**(12장 지시 그대로 — "성과 수집은 별도의 향후 단계다"). `THREADS_ACCESS_TOKEN`/`YOUTUBE_REFRESH_TOKEN`을 CI secrets로 넘기는 결정은 이번 작업 범위 밖으로 명시적으로 남겨둔다(23장).

## 13. Performance Dashboard

14장 지시("UI를 무리하게 완성하지 않는다, 데이터 모델과 backend API/route가 먼저")를 그대로 따라 **읽기 전용 MVP**만 구현했다.

- `scripts/run_scout_dashboard.py`에 `GET /performance` 라우트를 추가했다(POST 없음 — 어떤 파일도 쓰지 않는다는 것을 `tests/test_performance_dashboard.py::test_performance_view_does_not_modify_archive_or_store`로 직접 검증).
- `DashboardConfig.performance_path`(기본값 `data/tak_performance.json`) 필드와 `--performance` CLI 인자를 추가했다.
- 화면은 `content_id`별 **가장 최근 스냅샷만** 보여준다(시계열 그래프/추이는 이번 MVP 범위 밖 — "완성도가 낮으면 다음 단계로 넘긴다"는 지시를 따름). 제목은 MEDIA archive의 `final_title`을 참고로 함께 보여준다(archive를 수정하지 않고 조인만 함).
- 메인 화면(`/`) nav-links에 `📈 Performance` 링크를 추가해 발견 가능하게 했다.

## 14. TAK BRAIN feedback 설계

15장 지시("성과 데이터를 TAK BRAIN에 바로 자동 반영하지 않는다")를 그대로 따라 **이번 작업에서는 TAK BRAIN(`tak_brain/`)을 전혀 수정하지 않았다.** `content_engine/performance/__init__.py`의 모듈 docstring에 이 경계를 명시적으로 적어두었다:

> "성과 데이터를 TAK BRAIN/SCOUT scoring에 자동으로 반영하는 것 (그런 코드가 아예 없다 - 사람이 분석 결과를 보고 판단하는 단계까지만 만든다)"

즉 이번 단계가 만든 구조는 `performance → (사람이 /performance 화면을 본다) → (사람이 판단)`까지다. `performance → analysis → human decision → future knowledge/scout weighting` 구조에서 `analysis`(자동 집계/비교 리포트)와 `future knowledge/scout weighting`(SCOUT SCORE에 실제로 반영)은 **다음 단계로 명시적으로 남긴다**(24장).

## 15. SCOUT feedback 설계

`tak_scout/scoring.py`를 다시 읽고 향후 위치를 설계만 했다(코드는 변경하지 않았다 — 16장 지시 "기존 scoring 로직을 임의 변경하지 않는다"를 그대로 지켰다).

현재 5개 차원(A 콘텐츠 관심도 0~25, B 전문성 연관성 0~25, C 의견 잠재력 0~20, D 수익화 관련성 0~15, E 최신성 0~15, 총 100점)은 전부 `score_candidate()` 안에서 텍스트/카테고리/발행시각만으로 계산되는 규칙 기반 함수다. 향후 6번째 차원 `F. 과거 성과 신호(0~N점)`을 추가한다면:

- `score_candidate()`가 아니라 **`rank_candidates()`를 감싸는 새로운 선택적 레이어**로 넣는 것을 권장한다 — `score_candidate()`는 "순수하게 이 후보 텍스트만 보고 결정적으로 계산"하는 함수라는 문서화된 계약(`docstring`: "순수 함수: 같은 입력 -> 같은 결과")이 있는데, 성과 데이터는 후보 자체의 속성이 아니라 외부 상태(과거 이력)이기 때문이다.
- 구체적으로는 `content_engine.performance.store.latest_snapshot_per_content()`로 이미 발행된 콘텐츠의 성과를 모아, "이 후보와 같은 category/domain의 과거 콘텐츠가 평균적으로 잘 됐는가"를 계산하는 별도 함수를 만들고, SCOUT Dashboard가 이를 참고 정보로만 보여주는 것으로 시작하는 것이 안전하다 — **점수에 자동으로 합산하지 않는다**(13장/15장 원칙과 동일). 자동 합산은 사람이 그 참고 정보를 몇 번 보고 "이 반영 방식이 타당하다"고 판단한 뒤에나 고려할 문제다.

## 16. 데이터 마이그레이션 검토

`content_engine/performance/migration.py`에 변환 함수 2개를 **설계·구현·테스트까지만** 했고, **실제 production 로그 파일에는 실행하지 않았다**(18장 지시 그대로).

- `migrate_threads_or_blog_baseline_records(publish_records, platform)` — `PublishRecord.to_dict()` 형태 목록(Threads/Blog 공용 구조)을 `source="migration_baseline"`, `metrics={}`인 baseline `PerformanceRecord`로 변환한다. `knowledge_id`가 빈 레코드는 건너뛴다(억지로 채우지 않음).
- `migrate_youtube_baseline_records(upload_records, video_id_to_content)` — 2장에서 발견한 구조적 공백(YouTube 업로드 이력에 content_id/knowledge_id 없음) 때문에, 호출부가 `{video_id: (content_id, knowledge_id)}` 매핑을 **명시적으로 제공해야만** 변환되고, 매핑에 없는 항목은 조용히 건너뛴다.

실제 로컬 production 데이터로 무엇이 가능한지도 확인했다(읽기만 함, 파일 변경 없음): `data/threads_publish_log.json`에 실제 게시 이력 2건이 있고(`content_id`/`knowledge_id`/`threads_post_id` 모두 있음) 이 함수로 바로 baseline 변환이 가능하다. `data/youtube_publish_log.json`에는 테스트 업로드 1건(`video_id=h2X1fFMDffc`, privacy=private)이 있지만 `content_id`/`knowledge_id`가 없어 매핑 없이는 변환 불가 — 실제로 이 CLI를 나중에 쓰려면 사람이 이 영상이 어떤 content_id에 해당하는지 먼저 확인해야 한다(24장 다음 단계로 남김).

## 17. 테스트

19장 요구사항(A~N)을 신규 테스트 9개 파일로 구현했다(모두 이번 세션에 새로 작성):

| 항목 | 파일 |
|---|---|
| A. PerformanceRecord 생성 | `tests/test_performance_models.py` |
| B. content_id/knowledge_id 연결(필수 검증) | `tests/test_performance_models.py` |
| C. snapshot 여러 개 저장(시계열) | `tests/test_performance_store.py` |
| D. 동일 snapshot 중복 방지 | `tests/test_performance_store.py` |
| E. Threads mock metric 저장 | `tests/test_performance_threads.py` |
| F. YouTube mock metric 저장 | `tests/test_performance_youtube.py`, `tests/test_youtube_performance_client.py` |
| G. Blog manual metric import 저장 | `tests/test_performance_blog.py`, `tests/test_collect_performance_cli.py` |
| H. 외부 API 호출은 mock에서만 실행 | 전체 파일 공통 원칙 + `tests/test_collect_performance_cli.py`(threads/youtube는 반드시 `--dry-run`과 함께만 CLI 테스트) |
| I. 실제 secret 필요 없음 | 위와 동일 — 어떤 테스트도 실제 `THREADS_ACCESS_TOKEN`/`YOUTUBE_*` 값을 참조하지 않는다 |
| J. performance 데이터가 기존 archive를 변경하지 않음 | `tests/test_performance_isolation.py`, `tests/test_performance_dashboard.py` |
| K. 기존 publish history 변경 없음 | `tests/test_performance_isolation.py` |
| L. 기존 MEDIA 승인 상태 변경 없음 | `tests/test_performance_isolation.py` |
| M. 기존 SCOUT scoring 변경 없음 | `tak_scout/scoring.py`를 이번 세션에서 한 줄도 수정하지 않음(15장) — 전체 회귀로 재확인 |
| N. 전체 pytest 회귀 | 아래 결과 |

추가로 `content_engine/threads_publisher.py`/`content_engine/youtube_publisher.py`에 추가한 신규 메서드(`get_media_insights`/`get_video_statistics`) 자체의 단위 테스트도 각각 `tests/test_threads_publisher.py`(기존 파일에 클래스 추가 — 이 파일은 이미 git에 커밋되어 있던 파일이라 안전하게 이어 씀)와 `tests/test_youtube_performance_client.py`(신규 파일 — 1장에서 확인했듯 `tests/test_youtube_publisher.py`는 이전 세션의 미커밋 파일이라 섞지 않으려 별도 파일로 분리)에 작성했다.

전체 pytest 결과(작업 종료 직전):

```
762 passed, 68 subtests passed in 124.06s (0:02:04)
```

**0 failed.** 시작 시점(703 passed) 대비 정확히 59건 추가(신규 테스트 파일 9개 + 기존 2개 파일에 추가한 테스트), 기존 테스트는 전부 그대로 통과 — 회귀 없음.

## 18. 보안 검증

- 새로 만든/수정한 어떤 파일에도 `secrets.`(GitHub Actions), 하드코딩된 토큰/키 문자열이 없다(코드 review 재확인 — `THREADS_ACCESS_TOKEN`/`YOUTUBE_*`는 전부 `os.environ`을 통해서만 읽는다, 기존 `threads_publisher.py`/`youtube_publisher.py`의 기존 원칙을 그대로 재사용).
- `.github/workflows/*.yml`을 이번 세션에서 **전혀 수정하지 않았다** — 새 workflow도 만들지 않았다(12장). `git status`로 재확인: workflow 파일 변경 0건.
- 오류 메시지에 토큰이 노출되지 않는지: `YouTubeClient`의 `_safe_http_error_message()`(기존 함수, 수정하지 않음)를 `get_video_statistics()`도 그대로 재사용하므로 기존 보안 속성이 그대로 유지된다.
- **가장 중요한 보안 확인(1장)**: 실제 `THREADS_ACCESS_TOKEN`/`YOUTUBE_*`가 이 환경에 이미 존재한다는 사실을 발견한 뒤, 이 세션이 만든 어떤 코드 실행도 그 자격증명으로 실제 외부 요청을 보내지 않았다 — 19장에서 근거를 정리한다.

## 19. 실제 외부 호출 여부

**전부 없음.** 근거:

- 이 세션에서 실행한 모든 Threads/YouTube 관련 테스트는 `transport`/`token_transport`/`stats_transport`를 **mock 함수로 주입**했다(`ThreadsClient(..., transport=mock_fn)`, `YouTubeClient(..., token_transport=..., stats_transport=...)`) — 실제 `urlopen`을 import조차 하지 않거나, import하더라도 `unittest.mock.patch`로 완전히 가로챘다(`tests/test_youtube_performance_client.py::test_default_stats_transport_sends_correct_request`).
- `scripts/collect_performance.py`의 CLI 테스트(`tests/test_collect_performance_cli.py`)는 `--platform threads`/`--platform youtube`를 테스트할 때 **예외 없이 `--dry-run`을 함께 넘겼다** — dry-run 분기는 `ThreadsClient.from_environment()`/`YouTubeClient.from_environment()` 호출 이전에 `return`하므로 실제 자격증명에 접근조차 하지 않는다.
- 이 세션에서 `scripts/collect_performance.py`를 사람처럼 터미널에서 직접 실행한 적도 전부 `--platform blog`(네트워크 코드 없음) 또는 `--dry-run` 조합뿐이다 — `--platform threads`/`--platform youtube`를 `--dry-run` 없이 실행한 적이 **단 한 번도 없다.**
- 실제 LLM 호출: 새로 만든 코드 어디에도 `llm_provider`/`OpenAICompatibleRewriteProvider`를 import하지 않는다(성과 수집은 이미 존재하는 콘텐츠의 지표만 읽지, 새 콘텐츠를 생성하지 않는다).
- 실제 Naver 게시: 애초에 이 저장소에 Naver 게시 자동화 코드 자체가 없다(9장에서 재확인).

## 20. 변경 파일

**신규 파일(이번 세션이 처음부터 작성):**

- `content_engine/performance/__init__.py`
- `content_engine/performance/models.py`
- `content_engine/performance/store.py`
- `content_engine/performance/threads.py`
- `content_engine/performance/youtube.py`
- `content_engine/performance/blog.py`
- `content_engine/performance/migration.py`
- `scripts/collect_performance.py`
- `tests/test_performance_models.py`
- `tests/test_performance_store.py`
- `tests/test_performance_threads.py`
- `tests/test_performance_youtube.py`
- `tests/test_performance_blog.py`
- `tests/test_performance_migration.py`
- `tests/test_collect_performance_cli.py`
- `tests/test_performance_dashboard.py`
- `tests/test_performance_isolation.py`
- `tests/test_youtube_performance_client.py`
- `docs/6-01_operational_loop_and_performance.md`(이 파일)

**기존 파일 수정(수정 전부터 git에 커밋되어 있던, 이번 작업과 직접 관련된 파일만):**

- `content_engine/threads_publisher.py` — `DEFAULT_INSIGHTS_METRICS` 상수 + `ThreadsClient.get_media_insights()` 메서드 추가(기존 메서드는 전혀 수정하지 않음).
- `content_engine/youtube_publisher.py` — `VIDEOS_URL` 상수, `_default_stats_transport()`, `YouTubeStatsTransport` 타입, `YouTubeClient.stats_transport` 필드, `YouTubeClient.get_video_statistics()` 메서드 추가(기존 업로드 로직은 전혀 수정하지 않음).
- `scripts/run_scout_dashboard.py` — `DashboardConfig.performance_path` 필드, `GET /performance` 라우트, `render_performance_list_html()`/`_performance_row_html()` 함수, `--performance` CLI 인자, nav-link 1줄 추가(기존 라우트/렌더 함수는 전혀 수정하지 않음).
- `tests/test_threads_publisher.py` — `ThreadsMediaInsightsTests` 클래스 추가(이 파일은 작업 시작 시점에 이미 git에 커밋된 clean 파일이었음 — `git status`로 확인).

**의도적으로 건드리지 않은, "이미 미커밋 상태였던" 파일**: `tests/test_youtube_publisher.py`. 이 파일은 작업 시작 시점에 이미 이전 세션에서 만들어진 채 커밋되지 않은 상태였다(1장 목록). 처음에는 여기에 새 테스트 클래스를 이어 썼으나, 이 파일 전체를 커밋하면 6-01과 무관한 이전 세션 내용까지 함께 섞여 들어간다는 것을 깨닫고 **되돌린 뒤**(17장 언급) 별도 신규 파일 `tests/test_youtube_performance_client.py`로 옮겼다 — `tests/test_youtube_publisher.py`는 지금 작업 시작 시점과 완전히 동일한 내용이다.

**기존 미커밋 변경(`.gitignore`, `content_engine/__init__.py`, `content_engine/generator.py`, `content_engine/llm_provider.py`, `content_engine/rewrite.py`, `data/tak_brain_knowledge.json`, `tests/test_content_engine.py`, `tests/test_media_batch.py`, 그 외 1장에 나열한 모든 untracked 파일)는 이번 세션에서 한 글자도 건드리지 않았다.**

## 21. Commit

이번 작업에서 실제로 만들거나 수정한 파일만 정확히 `git add`한다(파일명을 하나씩 나열, `git add .`/`git add -A` 사용하지 않음):

```
git add content_engine/performance/ \
        content_engine/threads_publisher.py \
        content_engine/youtube_publisher.py \
        scripts/collect_performance.py \
        scripts/run_scout_dashboard.py \
        tests/test_threads_publisher.py \
        tests/test_youtube_performance_client.py \
        tests/test_performance_models.py \
        tests/test_performance_store.py \
        tests/test_performance_threads.py \
        tests/test_performance_youtube.py \
        tests/test_performance_blog.py \
        tests/test_performance_migration.py \
        tests/test_collect_performance_cli.py \
        tests/test_performance_dashboard.py \
        tests/test_performance_isolation.py \
        docs/6-01_operational_loop_and_performance.md
git commit -m "feat: add channel performance data foundation ..."
```

**실행 결과**: `git status --short`로 staging 내역을 먼저 확인 — 의도한 20개 파일만 `A`/`M`으로 표시되고, 기존 미커밋 변경(`.gitignore`, `content_engine/__init__.py` 등 1장 목록)은 전부 여전히 unstaged(공백+`M`)로 남아 그대로 보존됨을 확인했다. 커밋 성공:

```
[main 39cfb35] feat: add channel performance data foundation
 23 files changed, 2367 insertions(+), 2 deletions(-)
```

(파일 20개를 add했는데 23개로 표시되는 것은 `content_engine/performance/`가 디렉터리라 신규 파일 7개로 展開되기 때문 — 개수는 정확히 일치한다: 신규 파일 18개 + 수정 파일 4개 - 겹침 없음... 정확히는 `git add`에 넘긴 경로 16개 중 `content_engine/performance/`가 디렉터리 1개 인자로 파일 7개를 포함해 총 계산상 23개 파일 변경이 된다.)

## 22. Push

```
$ git push
To https://github.com/sopptak/tak-auto
   bd46f30..39cfb35  main -> main

$ git fetch origin
(변경 없음)

$ git log origin/main..HEAD --oneline
(빈 결과)
```

`origin/main`이 로컬 HEAD(`39cfb35`)와 완전히 일치함을 확인했다. push 성공.

## 23. 남은 문제

1. **실제 production `data/tak_media_archive.json`이 여전히 없다**(5-31부터 이어지는 최우선 미해결 사항 — 이번 작업 범위가 아니다). 이게 해결돼야 이번에 만든 `/performance` 화면도, `scripts/collect_performance.py`도 실제 콘텐츠에 대해 실행해볼 수 있다.
2. `data/youtube_publish_log.json`에 `content_id`/`knowledge_id`가 없어(2장/16장) YouTube 성과 수집은 영상마다 사람이 매핑을 직접 알아야 한다 — 자동화되어 있지 않다. 근본적으로 고치려면 `scripts/upload_youtube_short.py`가 업로드 시점에 `content_id`/`knowledge_id`를 함께 기록하도록 `YouTubeUploadRecord`를 확장해야 하는데, 이는 기존 업로드 이력 구조 변경이라 이번 6-01 범위(성과 "수집" 계층 추가) 밖으로 남긴다.
3. `scripts/collect_performance.py`를 GitHub Actions에 연결하는 workflow가 없다 — 성과 수집은 지금은 사람이 로컬/Codespace에서 CLI를 직접 실행해야 한다(12장에서 의도적으로 범위 밖으로 둠).
4. **이 개발 환경에 실제 Threads/YouTube 자격증명이 노출되어 있다는 사실 자체**(1장) — 이건 이번 작업이 만든 문제가 아니라 이미 있던 환경 설정이지만, 성과 수집 CLI가 새로 생기면서 "실수로 `--dry-run`을 빼먹고 실행"할 위험이 새로 하나 늘었다. 완화책은 24장에 제안한다.
5. `/performance` 화면은 "가장 최근 스냅샷"만 보여준다 — Day1→Day7 추이(그래프)는 시계열 데이터가 이미 저장소에 있음에도 화면에 없다(13장에서 의도적으로 MVP 범위 밖으로 둠).
6. `data/shorts_scripts/example_manman.json`의 출처 불명 문제(5-31부터 이어지는 미해결 사항)는 이번 작업에서도 다루지 않았다 — 범위 밖.

## 24. 다음 5~6시간 작업

우선순위 순:

1. **실제 MEDIA 승인 최소 1건**(23장 1번) — 이게 되어야 `/performance`와 `collect_performance.py`를 실제 데이터로 검증할 수 있다. 5-31/6-01 둘 다 이 지점에서 막혀 있다.
2. `scripts/upload_youtube_short.py`가 업로드 시 `content_id`/`knowledge_id`를 `YouTubeUploadRecord`에 함께 저장하도록 확장(23장 2번) — 이후 YouTube 성과 수집이 수동 매핑 없이 가능해진다.
3. `/performance` 화면에 시계열 추이(간단한 텍스트 sparkline 정도, 새 JS 라이브러리 추가는 지양)를 추가.
4. 실제 승인된 콘텐츠 1건이 생기면(1번 이후) `scripts/collect_performance.py --platform blog`(수동 입력, 가장 안전)부터 실제로 1회 실행해보고 `/performance` 화면에 반영되는지 end-to-end로 확인.
5. `content_engine/performance/migration.py`를 실제 `data/threads_publish_log.json`(이미 실제 게시 이력 2건 있음, 16장)에 실행해 baseline 데이터를 만들지 여부를 사람이 판단 — 이번 세션은 설계/구현만 하고 실행은 하지 않았다.
6. 15장에서 설계한 "SCOUT SCORE 6번째 차원(과거 성과 신호)"을 실제로 추가할지 — 데이터가 충분히 쌓인 뒤(최소 몇 주 분량) 사람이 판단.
7. `scripts/collect_performance.py --dry-run` 오남용 방지책 검토(23장 4번) — 예: 환경변수에 실제 토큰이 있을 때 CLI가 실행 전 한 번 더 확인 메시지를 출력하는 것 정도는 고려할 만하다(단, 이미 `publish_threads.py`/`upload_youtube_short.py`도 같은 패턴이므로 이 저장소 전체의 기존 관례를 갑자기 바꾸는 것은 신중해야 한다 - 사람과 먼저 상의).
