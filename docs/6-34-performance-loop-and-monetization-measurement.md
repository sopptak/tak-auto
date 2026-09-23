# 6-34 Performance Loop and Monetization Measurement

## 1. 목적

TAK AUTO의 Performance Loop(CONTENT→PUBLISH→PERFORMANCE→ANALYSIS→
LEARNING→NEXT CONTENT)를 실제 코드 기준으로 감사하고, 향후 실제 게시
성과를 콘텐츠 생산 시스템과 연결할 수 있는 측정·분석 기반의 남은
빈틈만 최소로 채운다. **성과 자동 최적화는 구현하지 않았다** - AI가
성과를 보고 콘텐츠 방향을 자동으로 바꾸는 코드는 이번에도, 앞으로도
이 패키지에 없다(기존 `content_engine/performance/__init__.py`
docstring이 이미 이 원칙을 명시하고 있었다 - 이번 세션이 이 원칙을
어기지 않았음을 재확인했다). 실제 외부 API는 호출하지 않았고, 실제
운영 성과 데이터(`data/tak_performance.json`)를 포함해 어떤 운영
데이터도 생성/수정하지 않았다 - 전부 tempfile로만 검증했다.

First Sync Check: `git status --short`(clean), HEAD==origin/main
(ba3706b) 확인 후 시작했다.

## 2. 현재 Performance 상태

**이 조사에서 가장 중요한 발견**: Performance는 6-34 이전에 이미
`content_engine/performance/`(models.py/store.py/summary.py/blog.py/
threads.py/youtube.py/migration.py, 총 749줄)와 91개의 기존 테스트로
상당히 성숙하게 구현되어 있었다(6-01/6-02, `docs/6-01_operational_loop_and_performance.md`,
`docs/6-02_publish-performance-operationalization.md`). 6-28~6-33의
여러 문서가 Performance를 "NOT_IMPLEMENTED(피드백 루프)"로 반복
기록한 것은 **정확했다**(피드백 루프, 즉 성과→콘텐츠 전략 자동 반영은
실제로 없다) - 하지만 그 기록들이 "수집/저장/추이 요약" 자체도
`NOT_IMPLEMENTED`인 것처럼 오해될 여지가 있었다. 이번 조사로 정확히
구분한다.

| 항목 | 상태 |
|---|---|
| 성과 데이터 저장(스냅샷) | `IMPLEMENTED`(`store.py`, append-only 시계열) |
| 게시 기록(publish history)과의 연결 | `IMPLEMENTED`(`migration.py`, content_id/knowledge_id 공유) |
| 게시 날짜/플랫폼/콘텐츠 식별자 | `IMPLEMENTED`(`PerformanceRecord`) |
| 조회수/좋아요/댓글/공유 | `IMPLEMENTED`(Threads/YouTube API 정규화, `metrics: dict[str, int]`) |
| 저장/클릭 | `PARTIALLY_IMPLEMENTED`(스키마가 임의 키를 허용하므로 저장 가능하지만, Threads/YouTube 공식 API 응답에 해당 필드가 없어 실제로 채워지지 않음) |
| CTR | `NOT_IMPLEMENTED`(계산 함수 없음, 13/14장) |
| 유입/수익 | `NOT_IMPLEMENTED`(15/16장, 이번에도 구현하지 않음) |
| 성과 집계(콘텐츠별 추이) | `IMPLEMENTED`(`summary.py::summarize_content_history()`) |
| 성과 비교(콘텐츠 간 우열 판단) | `NOT_IMPLEMENTED`(의도적, 15장 금지 영역) |
| 리포트(Daily/Weekly/Monthly) | `DOCUMENTED_ONLY`(이번에 설계만, 16장) |
| Dashboard 표시 | `IMPLEMENTED`(`/performance`, content_id별 목록) |

## 3. Content Traceability

`PerformanceRecord`는 `content_id`+`knowledge_id`를 필수로 요구한다
(`models.py` `__post_init__`, 없으면 `PerformanceRecordError`). 4장의
핵심 관계(knowledge_id→content_id→generation_id→platform→
publish_status→publish_timestamp→performance)를 코드로 검증했다.

## 4. Performance Record

기존 `PerformanceRecord`(`models.py`)의 필드 설계를 그대로 유지했다
(불필요한 필드를 무조건 추가하지 않는다는 5장 지시를 따라, 이미 있는
합리적인 설계를 다시 만들지 않았다):

| 필드 | 필요한 이유 | 확보 가능 여부 |
|---|---|---|
| `content_id`/`knowledge_id` | 콘텐츠/원본 KNOWLEDGE 추적의 핵심 key | 항상 확보 가능(발행 이력에 이미 있음) |
| `platform` | 채널별 metric 분리(threads/youtube/blog) | 항상 확보 가능 |
| `published_at`/`metric_collected_at` | window 계산(6장), 시계열 정렬 | 항상 확보 가능 |
| `metrics: dict[str, int]` | views/likes/comments/shares 등 **플랫폼마다 다른 지표를 고정 스키마 없이 수용** | API 응답 또는 사람 입력 |
| `source` | 이 숫자를 얼마나 신뢰할지(API/manual/migration_baseline) | 항상 확보 가능 |
| `external_id` | 플랫폼 원본 ID(post id/video id/blog url) - 향후 재조회 key | API/manual 둘 다 가능 |
| `raw` | 원본 응답 보존(감사/디버깅) | API만(manual은 원본이 없음) |

**`generation_id`를 추가하지 않았다** - 11/12장에서 그 이유를
구조적으로 분석했다(핵심 발견, 이번 세션의 결론).
**`revenue`/`currency`/`ctr`/`engagement_rate`도 추가하지 않았다** -
15/17장에서 설명하듯 계산값(metrics로부터 파생)이거나 이번 단계의
구현 범위 밖이기 때문이다.

## 5. Platform Metrics

| | Threads | YouTube Shorts | Blog |
|---|---|---|---|
| 핵심 metric | views/likes/replies/reposts/quotes/shares | views/likes/comments | 사람이 확인한 임의 키(보통 views/likes/comments) |
| 측정 시점 | 호출 시점(스냅샷) | 호출 시점(스냅샷) | 사람이 네이버 관리자 페이지를 확인한 시점 |
| 측정 window | 호출부가 결정(6장) | 호출부가 결정 | 호출부가 결정 |
| 데이터 출처 | Threads Graph API(`get_media_insights`, 공식 문서 기준 필드명, `content_engine/performance/threads.py`) | YouTube Data API v3(`videos.list?part=statistics`, `content_engine/performance/youtube.py`) | 사람 수동 입력만(네이버는 조회수 공개 API 없음, `content_engine/performance/blog.py` docstring에 조사 근거 기록됨) |
| API 가능 여부 | `IMPLEMENTED`(코드 있음, 실제 호출은 안 함) | `IMPLEMENTED`(코드 있음, 실제 호출은 안 함) | `EXTERNAL_DEPENDENCY`(공식 API 자체가 없음) |
| 수동 입력 가능 여부 | 가능(`source="manual"`) | 가능 | 유일한 경로 |
| 향후 자동화 가능 여부 | 이미 자동화 코드 있음(수집 CLI만 스케줄링하면 됨) | 이미 자동화 코드 있음 | 불가능(네이버 정책상 공식 API 없음, 스크래핑은 이 프로젝트 원칙 위반) |

이번 세션에서 실제 API를 호출하지 않았다 - 위 표는 전부 기존 코드를
읽어서 확인했다.

## 6. Measurement Window

`content_engine/performance/window.py`(6-34 신규)에
`classify_measurement_window(published_at, metric_collected_at)`을
추가했다 - 24h/72h/7d/30d 4개 표준 window로 경과 시간을 분류하는
순수 함수다(새 저장 구조 없음, 기존 `published_at`/
`metric_collected_at` 필드만 사용). Shorts와 Blog의 성과 곡선이
다르다는 사실을 반영해, **이 함수는 "어떤 window가 좋다/나쁘다"를
판단하지 않는다** - 분류만 한다. 파싱 불가/역전(측정이 게시보다 이전)은
`"unknown"`으로, 30일 초과는 `"beyond_30d"`로 분류해 예외 없이
동작한다. 7개 신규 테스트로 각 경계값(24h/72h/7d/30d/beyond/unknown/
역전)을 검증했다.

## 7. Snapshot vs Event

기존 설계(`store.py` 모듈 docstring, 6-01)가 이미 **SNAPSHOT** 방식을
채택했다 - 이번에 다시 설계하지 않았다. 장단점(기존 코드에 기록된
그대로): 누적 snapshot은 "그 시점의 절대값"을 그대로 보존해 나중에
어떤 window로든 재계산할 수 있고(증가분만 저장하면 window를 바꿀 때
재계산이 불가능하다), 대신 저장 용량이 이벤트 방식보다 크다 - TAK
AUTO 규모(콘텐츠 수가 크지 않음)에서는 이 트레이드오프가 합리적이라고
기존 설계가 이미 판단했다. `append_snapshot()`이 `(content_id,
metric_collected_at)` 키로 idempotent하게 중복을 막는다(9-01장에서
정한 방식, 20/21장에서 재검증).

## 8. Publish History

Publish History(`content_engine/publish_history.py`,
`content_engine/youtube_upload_history.py`)와 Performance는 완전히
분리된 파일/모델이다. `migration.py`가 이 둘의 비대칭을 이미 발견해
기록해 두었다: Threads/Blog(`PublishRecord`)는 처음부터 content_id/
knowledge_id를 가지므로 그대로 baseline으로 옮길 수 있지만,
**YouTube(`YouTubeUploadRecord`)는 video_id/title/uploaded_at만 있고
content_id/knowledge_id가 없다** - YouTube 업로드가 설계 당시(5-13/
5-14) MEDIA archive와 연결되지 않았기 때문이다. `migrate_youtube_baseline_records()`가
호출부에게 `{video_id: (content_id, knowledge_id)}` 매핑을 명시적으로
요구하고, 매핑이 없는 video_id는 추측하지 않고 건너뛴다. 이 비대칭은
이번 세션에서 발견한 것이 아니라 기존 코드에 이미 기록되어 있었다 -
재확인만 했다.

`external_id`(threads post id/youtube video id/blog url)가 향후
성과 재조회의 핵심 key가 될 수 있는지: **가능하다** - Threads/
YouTube 모두 이 ID로 API를 다시 조회하는 구조(`get_media_insights(media_id)`,
`videos.list(id=...)`)가 이미 구현되어 있다.

## 9. Superseded 콘텐츠

OLD content_id가 superseded되어도 성과 데이터는 **절대 삭제/병합되지
않는다** - `PerformanceRecord`/`store.py`가 `review_status`나
`superseded_by`를 전혀 참조하지 않기 때문에(25장 경계), OLD의 스냅샷은
구조적으로 영향받을 방법이 없다. 신규 테스트
(`test_superseded_old_content_performance_is_never_deleted_or_merged`)로
직접 확인했다 - OLD content_id의 시계열이 그대로 보존됨을 snapshot
2건으로 검증했다.

**KNOWLEDGE 수준 추적**: `knowledge_id`가 이미 모든 `PerformanceRecord`에
있으므로, "이 KNOWLEDGE에서 파생된 모든 content_id"는 이미 조인
가능하다 - 새 필드가 필요 없었다. 다만 이를 "한 번에 조회"하는
헬퍼가 없어서 6-34에서 `store.py`에
`snapshots_for_knowledge(path, knowledge_id)`(신규, 8줄)를 추가했다 -
content_id별로 **분리해서** 반환하며 절대 합치지 않는다(10장).

## 10. Generation 비교

`snapshots_for_knowledge()`가 같은 knowledge_id 아래 여러 content_id
(OLD/NEW, 또는 플랫폼별)를 분리해서 보여준다는 것을 9장에서
확인했다. `generation_id`를 Performance의 필수 key로 만들 것인가
(11장 질문)는 다음 장에서 구조 분석으로 답한다.

## 11. Content Fingerprint

**핵심 분석(6-34 신규 발견)**: `content_engine/publish_history.py::compute_content_id()`는
`knowledge_id`/`platform`/`source_url`/`evidence_unit_ids`/
`original_title`/`original_body`만 해시 입력으로 쓰고,
**`rewritten_title`/`rewritten_body`(LLM 출력, generation마다 달라짐)는
쓰지 않는다**(주석에 명시적 설계 의도로 기록되어 있음). 즉:

- 같은 KNOWLEDGE 슬롯을 여러 번 재생성해도(서로 다른 `generation_id`),
  원본(`original_*`/`evidence_unit_ids`)이 같으면 **항상 같은
  content_id**가 나온다. 신규 테스트
  (`test_content_id_is_stable_across_different_generation_ids`)로
  SHA256 기반이므로 사실상 항상 성립함을 확인했다.
- KNOWLEDGE 정정(원본 텍스트 변경) 시에만 content_id가 바뀐다
  (`test_content_id_changes_when_original_content_changes`).
- "같은 내용인데 content_id가 달라지는 경우"는 KNOWLEDGE 정정이 있을
  때만 발생하며(의도된 동작 - 정정 전/후는 실제로 다른 버전이므로
  달라지는 것이 맞다), "다른 내용인데 content_id가 같아지는 경우"는
  SHA256 해시 충돌이 필요해 실질적으로 발생하지 않는다.
- 기존 overwrite protection(`check_promotion_conflict()`, 6-18)은
  바로 이 사실에 기반한다 - "같은 content_id에 다른 generation_id가
  promotion되려 하면 충돌"이라는 규칙이 성립하는 이유가, content_id가
  generation과 무관하게 "이 슬롯"을 가리키기 때문이다.

**결론(11장 질문에 대한 답)**: `generation_id`를 Performance의 필수
key로 만들 필요가 **없다**. Promotion 단계의 overwrite protection이
이미 "한 content_id로 실제 게시된 것은 항상 정확히 하나의
generation"임을 보장하므로, content_id만으로 게시된 콘텐츠를
유일하게 식별할 수 있다. content_id만으로 충분한 경우가
대부분이며(사실상 전부), legacy 데이터(과거 generation_id 없이
만들어진 content_id)와도 자동으로 호환된다 - 새 ID 체계를 만들지
않았다(12장 지시 준수).

## 12. Data Quality

`content_engine/performance/quality.py`(6-34 신규, 68줄)에
`check_metric_quality()`를 추가했다 - `PerformanceRecordError`(models.py,
구조적 오류만 막음, `BLOCKED`에 해당)와 별개로, **구조적으로는
유효하지만 값이 의심스러운 경우**를 `WARNING`으로만 표시하고 저장은
막지 않는다:

| 오류 | 상태 |
|---|---|
| missing content_id | `BLOCKED`(기존 `PerformanceRecordError`, models.py) |
| missing platform | `BLOCKED`(기존, `PLATFORMS` 화이트리스트) |
| missing published_at | `VALID`(빈 문자열 허용 - `metric_collected_at`만 필수, 기존 설계 유지) |
| negative views | `WARNING`(신규 `quality.py`) |
| views 감소 | `WARNING`(신규, 이전 스냅샷과 비교) |
| likes > views | `WARNING`(신규) |
| duplicate measurement | `BLOCKED`(기존 idempotency, `store.py` - 조용히 skip, 에러 아님) |
| wrong generation_id | 해당 없음(4장 - generation_id 필드 자체가 없음) |
| wrong knowledge_id | `VALID`(구조적으로 검증 불가 - 실제 KNOWLEDGE 존재 여부까지는 이 레이어가 확인하지 않는다, 25장 경계와 동일한 이유) |
| superseded content | `VALID`(9장 - Performance는 review_status를 모른다, 의도된 경계) |

**왜 WARNING이지 BLOCKED가 아닌가**: 조회수 감소가 실제로 API의
스팸 필터링 보정일 수도 있어, 이 레이어가 "틀렸다"고 단정할 근거가
없다 - 최종 판단은 사람이 한다(15장 원칙과 동일). 5개 신규 테스트로
검증했다.

## 13. Metric Validation

CTR/engagement_rate/completion_rate 계산 함수는 **만들지 않았다** -
14장 지시("플랫폼마다 분모가 다르면 플랫폼별 정의를 분리한다",
"통일된 숫자 하나를 만들기 위해 의미가 다른 지표를 억지로 합치지
않는다")를 검토한 결과, 현재 수집되는 metric만으로는 각 플랫폼의
정확한 분모(예: CTR의 impressions, completion_rate의 video 길이)가
없다 - Threads insights는 views/likes/replies/reposts/quotes/shares만
제공하고 impressions/노출수는 별도 권한이 필요한 필드다(threads.py가
실제로 가져오는 필드 목록에 없음), YouTube Shorts의 completion_rate는
`averageViewDuration`/영상 길이가 필요한데 현재 `youtube.py`는
viewCount/likeCount/commentCount만 정규화한다. **없는 데이터로 지표를
지어내지 않는다** - `summary.py`가 이미 "없는 metric은 0으로 가정하지
않는다"는 동일한 원칙을 갖고 있다(모듈 docstring). 계산 가능한 것만
계산하도록 향후 확장할 수 있는 여지(`metrics` dict에 원본이 이미
있음)는 남겨두었다.

## 14. Performance Report

Daily/Weekly/Monthly 리포트 구조를 **설계만** 했다(`DOCUMENTED_ONLY`) -
실제 데이터가 없는 현재 환경에서 synthetic fixture로 구조 원형
(`summarize_content_history()`, `snapshots_for_knowledge()`)은 이미
검증했지만, 날짜 범위로 집계하는 별도 리포트 함수는 만들지 않았다
(28장 "기존 코드를 불필요하게 수정하지 마라", 16장 지시의 "synthetic
fixture로 구조만 검증한다"에 따름):

- **DAILY**: 게시 수/플랫폼별 게시 수는 `publish_history`에서 이미
  조회 가능(날짜 필터만 얹으면 됨). 24h views/engagement/clicks는
  `window.py`(6장)로 분류한 스냅샷을 집계하면 된다. publish failures는
  각 발행 CLI의 종료 코드/로그가 이미 있다(새 저장소 불필요).
- **WEEKLY**: KNOWLEDGE별/플랫폼별/generation별 성과 -
  `snapshots_for_knowledge()`(9장)로 KNOWLEDGE별은 이미 가능. platform
  필터는 `PerformanceRecord.platform`으로 이미 가능. generation별은
  11장 결론에 따라 필요성이 낮다.
- **MONTHLY**: 콘텐츠 생산량(Production Archive count), 게시량(publish
  history count), 누적 조회/참여/클릭(스냅샷 합산), 수익(15장,
  구현 없음).

## 15. Monetization

수익 자동화는 구현하지 않았다(0장 지시). 5개 수익원의 연결 구조만
검토했다:

| 수익원 | source→content→traffic→revenue 연결 가능성 |
|---|---|
| YouTube 광고 | `EXTERNAL_DEPENDENCY` - YouTube renderer가 없어(6-30) 콘텐츠 자체가 아직 없다. 연결 구조상으로는 `external_id`(video_id)로 YouTube Analytics API의 estimatedRevenue를 조회하면 `PerformanceRecord.metrics`에 `revenue`를 추가할 수 있다(구현 안 함). |
| Blog 광고(애드포스트 등) | `EXTERNAL_DEPENDENCY` - 5장과 동일한 이유(공식 API 없음), 수동 입력만 가능. |
| Affiliate | `EXTERNAL_DEPENDENCY` - 클릭→구매 전환은 제휴 플랫폼(쿠팡파트너스 등)의 대시보드에서만 확인 가능, 이 프로젝트가 직접 연결할 API 없음. content_id를 제휴 링크의 subid로 심어두면(구현 안 함) 향후 수동 매칭이 가능하다는 구조만 확인. |
| 상품/서비스 | `EXTERNAL_DEPENDENCY` - 완전히 프로젝트 밖의 판매 채널. |
| 기타 콘텐츠 기반 수익 | `NOT_IMPLEMENTED` |

수익이 콘텐츠 하나에 직접 귀속되지 않는 경우(예: 여러 콘텐츠가 같은
제품을 홍보)는 16장(Attribution)에서 별도로 다룬다. `PerformanceRecord`에
`revenue`/`currency` 필드를 추가하지 않았다 - 실제 수익원이 하나도
연결되지 않은 상태에서 빈 필드를 미리 만드는 것은 "필요하지 않은
필드를 무조건 추가하지 마라"(5장 지시)에 어긋난다. 필요해지면
`metrics`(이미 임의 키를 허용하는 `dict[str, int]`)에 정수 단위(원/
센트)로 넣는 것으로 충분하다 - 스키마 변경이 필요 없다.

## 16. Attribution

과도한 attribution을 하지 않는다는 원칙을 기존 `source` 필드가 이미
부분적으로 구현하고 있었다 - `source="migration_baseline"`은 "발행
사실만 옮긴 것이지 실제 성과가 아니다"를 명시적으로 표시하고,
`ContentPerformanceSummary.baseline_is_migration`이 이 사실을 화면에
경고로 보여줄 수 있게 되어 있다(6-02, 재확인만 함). 직접 측정
가능한 것(Blog→Affiliate 클릭, API가 제공하는 views/likes)과
추정이 필요한 것(Shorts→브랜드 인지도→나중 검색 유입)을 구분하는
새 필드는 만들지 않았다 - `source` 값(`threads_api`/`youtube_api`/
`manual`/`migration_baseline`)이 이미 "이 숫자를 얼마나 신뢰할
것인가"의 대리 지표 역할을 한다. 신규 테스트
(`test_attribution_direct_vs_indirect_is_distinguishable_by_source`)로
이 구분이 실제로 동작함을 확인했다.

## 17. Human Analysis

Performance→Human Analysis→Content Insight→KNOWLEDGE/MEDIA 개선
루프에서, AI가 자동으로 콘텐츠 전략을 결정하는 코드는 없다(재확인,
`content_engine/performance/__init__.py` docstring이 이미 이 경계를
명시). `render_text_trend()`(summary.py)가 "100 → 430 → 2,300"
형태로 **사실만** 보여주고, "이게 좋다/나쁘다"는 판단을 붙이지
않는다 - 이 원칙이 6-01부터 이미 지켜지고 있었다.

## 18. Performance Dashboard

`/performance`(Dashboard, `render_performance_list_html()`)가 이미
content_id별 시계열 요약을 보여준다(`IMPLEMENTED`). **필터(플랫폼별/
KNOWLEDGE별/기간별)는 현재 없다** - 최근 수집 순 정렬만 있다
(`NOT_IMPLEMENTED`). 이번 세션에서 대규모 UI를 만들지 않기로 한
지시(20장)에 따라 필터 UI를 새로 만들지 않았다 - 대신 필터에 필요한
데이터 조회 함수(`snapshots_for_knowledge()`, `platform` 필드로 직접
필터링 가능)는 이미 준비되어 있으므로, 필터 UI 자체는 향후 작은
추가만으로 가능하다(`FUTURE`, 27장).

## 19. Manual Import

`scripts/collect_performance.py`(기존)는 1건씩 `--metric key=value`로
입력받는다 - 여러 건을 한 번에 넣으려면 번거롭다. 6-34에서
`scripts/import_performance_snapshots.py`(신규)를 추가했다 - JSON
배열 파일 하나를 읽어 기존 `append_snapshots()`(이미 있는 bulk
idempotent 저장 함수)를 그대로 호출한다. 새 저장/검증 로직을 만들지
않았다 - `PerformanceRecord.from_dict()`(기존)로 각 레코드를
검증하고, `check_metric_quality()`(12장)로 이상을 경고만 한다.
`--output`에 기본값을 두지 않았다(promote_media_generation.py의
batch 안전 원칙과 동일 - 실수로 실제 운영 파일을 건드리지 않도록).
6개 신규 테스트(정상 import/멱등성/malformed JSON/필수 필드 누락/
알 수 없는 platform/입력 파일 없음)로 검증했다.

## 20. Idempotency

기존 `append_snapshots()`(store.py, 6-01)이 `(content_id,
metric_collected_at)` 키로 이미 idempotent했다 - 새로 만들지 않았다.
6-34에서 `import_performance_snapshots.py`(19장) CLI 레벨로 재확인했다:
같은 입력 파일을 두 번 import해도 저장소에 정확히 1건만 남는다
(`test_reimporting_same_file_is_idempotent`). "import A → import B"의
누적/변화량 계산 정확성은 `summary.py::metric_delta()`(기존, first↔latest
비교, 공통 key만 계산)가 이미 검증되어 있다(6-02, 재확인만 함).

## 21. Failure Injection

| 오류 | 결과 |
|---|---|
| malformed JSON | `BLOCKED` - `import_performance_snapshots.py`가 exit 1, 저장소 파일 자체를 만들지 않음 |
| duplicate record | `BLOCKED`(기존 idempotency) - 조용히 skip, 경고 없이 정상 처리 |
| unknown content_id | 해당 없음 - Performance 레이어는 content_id의 "존재"를 검증하지 않는다(25장 경계, Production Archive와 독립) |
| unknown generation_id | 해당 없음(4/11장 - 필드 자체가 없음) |
| unknown platform | `BLOCKED` - `PLATFORMS` 화이트리스트(models.py, 기존) |
| invalid metric(정수 아님) | `BLOCKED` - `PerformanceRecordError`(기존) |
| timestamp 오류 | `WARNING`/`unknown`(6장 - window 분류가 `"unknown"`으로 안전하게 처리, 저장 자체는 막지 않음 - `metric_collected_at`이 빈 문자열이 아니기만 하면 저장 가능) |
| superseded record | `VALID`(9장 - Performance는 review_status를 모름, 의도된 경계) |
| already imported snapshot | `BLOCKED`(20장과 동일 - idempotent skip) |

## 22. 10월 1일 운영 연결

6-33의 SCOUT→KNOWLEDGE→MEDIA→REVIEW→PROMOTION→PUBLISH 흐름 이후:

```
PUBLISH(Threads/Blog 게시 완료, YouTube는 6-30 기준 BLOCKED)
  ↓
24h: python scripts/collect_performance.py --platform threads --confirm-live
     또는 --platform blog(사람이 네이버 관리자 페이지 확인 후 --metric 입력)
  ↓
72h/7d/30d: 위 명령을 각 window에 맞춰 재실행(같은 content_id,
            새 --published-at 기준 metric-collected-at은 실행 시각이 자동 반영됨)
  ↓
언제든: python scripts/run_scout_dashboard.py 실행 후 "/performance"에서 추이 확인
  ↓
사람이 판단(17장) - 자동 반영 없음
```

운영자가 무엇을 언제 해야 하는지: 게시 직후에는 수집할 필요가
없다(플랫폼 API가 아직 유의미한 값을 반환하지 않을 수 있음) - 최소
24h 이후 최초 수집을 권장하고, 이후 72h/7d/30d 시점에 같은 명령을
반복 실행하면 된다(6-33 Runbook과 동일하게, 정확한 "몇 시 몇 분"은
코드로 확정할 수 없으므로 추정하지 않는다).

## 23. Production Archive 경계

Performance는 Production Archive(`data/tak_media_archive.json`,
`MediaArchiveRecord`)를 **전혀 import하지 않는다**(코드 재확인) -
`review_status`를 읽지도, `superseded`를 발생시키지도, Archive
파일을 쓰지도 않는다. 기존 `tests/test_performance_isolation.py`
(6-01, 2개 테스트)가 이미 이를 바이트 단위로 검증하고 있었다 - 이번
세션에서 다시 실행해 통과를 재확인했다(변경 없음).

## 24. Human Review 경계

성과가 좋다고 자동 승인하거나, 나쁘다고 자동 폐기하는 코드는 없다
(재확인). `content_engine/threads_review.py`(`review_status` 전이)를
Performance 어디에서도 import하지 않는다 - `test_performance_isolation.py`가
Threads pending 파일도 함께 불변임을 검증한다(기존, 재확인).

## 25. 구현 범위

이번 세션에서 실제로 추가한 코드(전부 독립 모듈/함수, 기존 Production/
Media/Publish 코드는 수정하지 않았다 - `content_engine/performance/store.py`에
함수 1개를 추가한 것과 `__init__.py`의 재수출만 예외):

1. `content_engine/performance/window.py`(신규, 51줄) - 측정 window 분류.
2. `content_engine/performance/quality.py`(신규, 68줄) - 데이터 품질 경고.
3. `content_engine/performance/store.py::snapshots_for_knowledge()`(추가, 17줄).
4. `scripts/import_performance_snapshots.py`(신규, CLI) - 일괄 import.
5. `content_engine/performance/__init__.py` - 위 4개 재수출(기존 관례 유지).

**만들지 않은 것**(설계만 하고 구현하지 않음, 대규모 자동화 금지
원칙에 따라): CTR/engagement_rate/completion_rate 계산 함수(13장,
필요한 원본 데이터 자체가 없어 지어낼 수 없음), Daily/Weekly/Monthly
리포트 함수(14장, 기존 조회 함수 조합만으로 가능함을 설계로 확인),
Monetization/revenue 필드(15장), Dashboard 필터 UI(18장).

## 26. 테스트

실행 순서(지시사항 28장 그대로):

1. 신규 테스트: `tests/test_6_34_performance_loop_and_monetization.py` - 24개 전부 PASS.
2. 기존 Performance 테스트 전체 재실행(91개, `store.py` 수정의 영향 범위): `python -m unittest discover -s tests -p "test_performance_*.py"` → 67개(파일 8개) + `test_collect_performance_*.py`/`test_youtube_performance_client.py` 별도 - 전부 PASS, 회귀 없음.
3. 전체 회귀:

```
python -m unittest discover -s tests -p "test_*.py"
Ran 1181 tests in 78.299s
OK (skipped=17)
```

failed=0, errors=0. 테스트 수를 맞추기 위해 기존 테스트를 삭제하거나
skip 처리하지 않았다(17건은 이 세션 이전부터 존재하던 조건부 skip).
`git status --short`를 테스트 전/후 모두 확인했고 `data/` 아래
운영 데이터(`tak_performance.json` 포함)는 전혀 생성/수정되지
않았다.

## 27. P1

없음 - Performance 수집/저장/추이 요약의 핵심 경로는 이미
`IMPLEMENTED`/`VERIFIED`다. 6-30/6-31에서 이미 기록된 YouTube renderer
확보만 여전히 P1으로 남아있다(Performance와 직접 관련 없음, 변경
없음).

## 28. P2

- Dashboard `/performance` 필터(플랫폼/KNOWLEDGE/기간, 18장) - 데이터
  조회 함수는 준비됐으나 UI는 없음.
- Daily/Weekly/Monthly 집계 리포트 함수(14장, 설계만 완료).
- YouTube 업로드 이력의 content_id/knowledge_id 연결 개선(8장에서
  발견한 기존 비대칭 - `migrate_youtube_baseline_records()`가 이미
  수동 매핑으로 우회하고 있으나, `scripts/upload_youtube_short.py`가
  업로드 시점에 이 연결을 자동으로 기록하도록 개선하면 수동 매핑이
  불필요해진다).

## 29. P3

- CTR/engagement_rate/completion_rate 계산(13장) - 필요한 원본
  데이터(impressions, 영상 길이)가 API에서 추가로 확보되어야 가능.
- Monetization 실제 연결(15장) - 각 수익원의 실제 API/대시보드 접근이
  선행되어야 함.
- Content Fingerprint 관련 실제 위험(12장에서 분석한 대로, SHA256
  충돌은 실질적 위험이 아니므로 우선순위 낮음).

## 30. 결론

Performance Loop의 핵심 인프라(스냅샷 저장, idempotency, 채널별
수집기, content별 추이 요약, Production Archive/Human Review 격리)는
6-01/6-02에서 이미 견고하게 구현되어 있었다 - 이번 세션은 그 사실을
정확히 재확인하고(2장), 남은 구조적 빈틈 4개(측정 window 분류, 데이터
품질 경고, KNOWLEDGE 단위 조회, 일괄 import)만 독립 모듈로 최소
추가했다. 가장 중요한 새 발견은 **`compute_content_id()`가 원본
텍스트만 해시하고 LLM 재작성 결과를 쓰지 않아서, `generation_id`가
Performance의 필수 key일 필요가 없다**는 구조적 분석이다(11/12장) -
이는 향후 Performance 스키마를 불필요하게 복잡하게 만들지 않아도
된다는 근거가 된다.

수익화(Monetization)는 이번 단계에서 자동화하지 않았고, 5개 수익원
모두 실제 연결에는 외부 의존성이 필요함을 확인했다(15장). AI가
성과를 보고 콘텐츠 전략을 자동으로 바꾸는 기능은 이번에도 만들지
않았다 - Performance는 여전히 "사람이 보는 사실"만 제공하고, 판단은
사람이 한다(17/24장). 전체 1181개 테스트가 failed=0/errors=0으로
통과했고, 실제 `data/` 운영 디렉터리(성과 데이터 포함)는 어디에서도
생성/수정되지 않았다.
