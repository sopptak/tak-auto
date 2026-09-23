# 6-35 Performance Feedback Loop

## 1. 목적

PERFORMANCE→ANALYSIS→INSIGHT CANDIDATE→HUMAN REVIEW→CONTENT STRATEGY
INPUT 구조를 설계·구현한다. 6-34가 구축한 Performance 원자료 구조는
전혀 수정하지 않았다 - Insight는 완전히 분리된 별도 모듈
(`content_engine/performance_insight.py`)로 새로 만들었다. 핵심
원칙(작업 지시 10개) 전부를 코드/테스트로 직접 증명한다: Performance는
원자료, Insight는 파생 결과, 분석이 원자료를 수정하지 않음, Insight가
KNOWLEDGE/MEDIA를 자동 수정/생성하지 않음, 콘텐츠 전략을 자동
변경하지 않음, 사람이 최종 판단. 실제 외부 API는 호출하지 않았고,
실제 운영 데이터(`data/tak_performance.json`,
`data/tak_performance_insights.json` 포함)는 어디에서도 생성/수정하지
않았다 - 전부 tempfile로만 검증했다.

First Sync Check: `git status --short`(clean), HEAD==origin/main
(ce3fd46) 확인 후 시작했다.

## 2. Performance 원자료 구조 재확인 (6-34)

`docs/6-34-performance-loop-and-monetization-measurement.md`와
`content_engine/performance/`(models.py/store.py/summary.py/window.py/
quality.py/threads.py/youtube.py/blog.py/migration.py)를 다시 읽고
코드로 재확인했다 - 변경하지 않았다. 핵심 재확인 사항:

- `PerformanceRecord`: `content_id`/`knowledge_id`/`platform`/
  `published_at`/`metric_collected_at`/`metrics: dict[str,int]`/
  `source`/`title`/`external_id`/`raw`. `generation_id` 필드는
  없다(6-34 11장에서 이미 "필수 key가 아니다"로 결론남 - 14장에서
  6-35가 이 결론을 재사용한다).
- 저장 방식: append-only 시계열, `(content_id, metric_collected_at)`
  키로 idempotent.
- `PLATFORMS = ("threads", "youtube", "blog")` - **이 값은 MediaArchiveRecord의
  `platform`(`"blog"`/`"shorts"`/`"threads"`)과 이름 공간이 다르다**
  (12장에서 신규로 정밀 분석).
- `classify_measurement_window()`(6-34): 24h/72h/7d/30d/beyond_30d/
  unknown - 6-35의 비교 규칙(6장)이 그대로 재사용한다.
- `check_metric_quality()`(6-34): 음수/역전/감소 → WARNING(저장은
  막지 않음).

## 3. Insight 저장 구조

**Performance = 원자료, Insight = 파생 결과**를 물리적으로도
분리했다: 새 파일 `content_engine/performance_insight.py`(단일
모듈, 기존 `content_engine/publish_audit.py`/`content_engine/blog_publish_pack.py`
같은 "응집도 높은 단일 분석 모듈" 관례를 따름 - `content_engine/performance/`처럼
플랫폼별 하위 모듈이 필요하지 않으므로 패키지로 만들지 않았다). 이
모듈은:

- `content_engine.performance`(6-34)를 **읽기만** 한다 - import 목록에
  `content_engine.media_archive`/`tak_brain`의 쓰기 함수가 전혀 없다
  (신규 테스트 `test_accepted_status_alone_does_not_trigger_any_automatic_action`이
  소스 코드 자체에 `upsert_archive`/`save_archive`/`set_review_status`
  문자열이 없음을 직접 확인한다 - "코드가 없다"는 사실을 실행 가능한
  테스트로 증명).
- 저장 파일 경로 관례: `data/tak_performance_insights.json`(6-34의
  `data/tak_performance.json`과 형제 파일, task 3장이 제안한 이름
  그대로 채택) - **이 세션에서 이 파일을 실제로 만들지 않았다**, 전부
  tempfile.
- 저장 함수(`load_insights`/`append_insight(s)`/`insights_for_scope`/
  `set_insight_status`)는 `content_engine/performance/store.py`와
  정확히 같은 패턴(append-only, tempfile+`Path.replace()` 원자적
  저장, 중복 키는 조용히 건너뜀)을 재사용했다 - 새 저장 패턴을
  만들지 않았다.

## 4. Insight Record

| 필드 | 이유 |
|---|---|
| `insight_id` | 분석 입력(scope/metric/window/evidence)의 결정적 지문(SHA256) - `compute_content_id()`(6-34 11장에서 분석한 패턴)와 동일한 설계 원칙 |
| `created_at` | 이 스냅샷이 언제 계산됐는지(지문에는 포함 안 됨 - 언제 다시 돌려도 같은 입력이면 같은 insight_id가 나와야 하므로) |
| `analysis_window` | 6-34 `window.py` 값 재사용(24h/72h/7d/30d/beyond_30d/unknown/all) |
| `scope` | CONTENT/GENERATION/KNOWLEDGE/PLATFORM(13장) |
| `scope_id` | scope에 해당하는 실제 값 |
| `platform` | 6-34 `PLATFORMS` 값(threads/youtube/blog), KNOWLEDGE scope는 여러 platform을 아우르므로 빈 문자열 허용 |
| `metric` | 분석 대상 지표 이름(예: "views") |
| `insight_type` | TREND/COMPARISON/ANOMALY/TRACEABILITY/MONETIZATION/DISTRIBUTION(5장) |
| `result` | 중립적 상태값(INCREASING/ABOVE_BASELINE/OUTLIER_DETECTED/CONSISTENT 등) - "최고"/"우승" 같은 평가 아님 |
| `observation` | 사람이 읽는 설명 텍스트(17장 Explainability) |
| `evidence` | 근거가 된 원본 스냅샷 목록(content_id/metric_collected_at/value)(16장) |
| `sample_size` | 명시적 표본 수 |
| `status` | candidate/accepted/rejected(19장) |

**`confidence` 필드를 만들지 않았다** - 이 프로젝트에는 신뢰도를
계산할 통계적 근거(예: 표본 분산, ML 모델 출력)가 없어, 숫자를
지어내는 대신 `sample_size`(사실)만 남기고 신뢰 판단은 사람이 직접
하도록 했다("필요 없는 필드는 제거한다" 지시를 따름). 신규 테스트
(`test_no_confidence_field_exists`)로 고정했다.

## 5. Insight Type

| Type | 상태 | 이유 |
|---|---|---|
| TREND | `IMPLEMENTED` | 시계열 증가/감소/보합 판정, 명확한 실사용 가치(9장) |
| COMPARISON | `IMPLEMENTED` | baseline 대비 위치 판정(7장), 실사용 가치 명확 |
| ANOMALY | `IMPLEMENTED` | outlier 감지(10장), 데이터 품질에 직결 |
| TRACEABILITY | `IMPLEMENTED` | identity 체인 무결성(13장), 6-32의 category contamination류 문제 재발 방지에 직결 |
| DISTRIBUTION | `FUTURE` | ANOMALY(median 기반 outlier)로 실용적 필요는 이미 충족됨 - percentile 등 추가 통계는 "과도한 통계 기능"(10장 지시)에 해당해 이번에 만들지 않음 |
| MONETIZATION | `FUTURE` | 6-34에서 이미 확인했듯 실제 revenue 데이터가 아직 없음(20장) - 없는 데이터로 계산 함수를 지어내지 않는다 |

`INSIGHT_TYPES` 상수에 6개를 전부 예약해 두었다(향후 DISTRIBUTION/
MONETIZATION을 추가할 때 상수를 다시 정의하지 않아도 됨) - 실제
분석 함수는 4개만 구현했다.

## 6. 비교 규칙

`check_comparable(platform_a, window_a, platform_b, window_b)`가
"YouTube 24h views vs Blog 30d views" 같은 비교를 명시적으로
거부한다(신규 테스트로 그 정확한 예시를 검증). `compare_to_baseline()`이
`target_platform`/`target_window`를 받으면 baseline의 platform/window와
비교해 불일치 시 무조건 `INCOMPARABLE`을 반환한다 - 강제로 계산하지
않는다. content_type/knowledge_id/generation_id/content_id는 별도
비교 로직을 두지 않았다 - `scope`+`scope_id`로 이미 분리되어 호출되므로
(예: content scope는 항상 정확히 하나의 content_id만 다룸), 서로 다른
scope_id를 섞어 부르는 것 자체가 호출부의 책임이며 이 함수는 그 경계
안에서만 정확성을 보장한다(6-34 publish_audit.py의 "순수 함수, 호출부가
올바른 입력을 넘긴다" 관례와 동일).

## 7. Baseline

가장 단순하고 설명 가능한 방식(평균, `statistics.mean`)을 선택했다 -
"현재 규모에서" 표준편차/회귀 등 더 복잡한 통계는 과도하다고
판단했다(10장 지시 재적용). `BASELINE_TOLERANCE_RATIO = 0.2`(±20%)
허용 오차로 ABOVE_BASELINE/BELOW_BASELINE/NEAR_BASELINE을 나눈다.
**BEST/WORST/WINNER 라벨을 만들지 않았다** - 신규 테스트
(`test_no_automatic_best_worst_winner_labels`)가 `result`/`observation`
어디에도 이 단어들이 나타나지 않음을 직접 검증한다. baseline 표본이
`MIN_SAMPLE_SIZE`(3) 미만이면 `UNKNOWN`을 반환한다.

## 8. Minimum Sample

`MIN_SAMPLE_SIZE = 3`(8장 - 2점만으로는 "추세"라고 말하기 부족하다고
판단, 중간값이 최소 1개 필요). 1/2/3/5/10/20 표본 전부를 synthetic
fixture로 테스트했다: 1/2는 `INSUFFICIENT_SAMPLE`, 3 이상은 정상
분석 진행(`MinimumSampleTests`). Insight를 강제로 만들지 않는다는
원칙을 정확히 지켰다.

## 9. Trend

과제가 제시한 3개 synthetic 데이터셋을 그대로 검증했다: A(100→120→150→180)
→ `INCREASING`, B(180→150→120→100) → `DECREASING`, C(100→100→100→100)
→ `STABLE`. 첫값-끝값 비교만으로 방향을 정하는 단순한 방식을
선택했다(중간 변동은 `observation`의 전체 시계열 텍스트로 사람이
직접 확인 - "추세를 코드가 과도하게 해석하지 않는다"는 절제 원칙).
데이터 부족 시 `UNKNOWN`이 아니라 `INSUFFICIENT_SAMPLE`을 쓴다 - 더
구체적인 상태값이 "왜 판단하지 않았는지"를 명확히 전달하기 때문이다.

## 10. Outlier

`[100, 110, 120, 115, 10000]` 예시를 median 기반으로 검증했다: 최신값
10000이 나머지(100/110/120/115)의 중앙값(112.5) 대비 `OUTLIER_RATIO`
(3배) 이상 벗어나면 `OUTLIER_DETECTED`다. mean이 아니라 median을
택한 이유: outlier 자체가 mean을 크게 왜곡하므로(10000 하나가 평균을
크게 끌어올림), outlier가 아닌 나머지 값들의 median이 "정상 범위"를
더 안정적으로 대표한다. 통계 기능을 과도하게 만들지 않기 위해
표준편차/z-score 등은 쓰지 않았다.

## 11. Platform 분석

Threads/YouTube/Blog를 완전히 분리해서 분석한다 - `analyze_trend()`/
`detect_anomaly()`가 항상 하나의 `platform`(또는 명시적으로 빈 문자열인
knowledge scope)만 다룬다. 플랫폼 간 종합 순위(예: "Threads가 Blog보다
낫다")를 만드는 함수는 어디에도 없다 - `PlatformContentSeparationTests::test_platforms_are_analyzed_separately_not_merged`가
서로 다른 platform의 Insight가 서로 다른 `insight_id`를 갖고
독립적으로 계산됨을 확인한다.

## 12. Content 분석 (Platform 명명 불일치 신규 발견)

**6-35에서 새로 발견한 핵심 사실**: `MediaArchiveRecord.platform`(MEDIA가
생성하는 콘텐츠 종류: `"blog"`/`"shorts"`/`"threads"`)과
`PerformanceRecord.platform`(실제 게시 채널: `"blog"`/`"youtube"`/`"threads"`)은
**같은 개념이 아니다** - Shorts로 생성된 콘텐츠는 YouTube에
업로드되므로 Performance에는 `platform="youtube"`로 기록된다(기존
`content_engine/performance/youtube.py`/`migration.py`가 이미 이렇게
하드코딩하고 있었다 - 6-35가 처음 명시적으로 이름 붙였다). 이 매핑을
`MEDIA_PLATFORM_TO_PERFORMANCE_PLATFORM = {"blog": "blog", "shorts":
"youtube", "threads": "threads"}` 상수로 명시하고
`test_media_platform_shorts_maps_to_performance_platform_youtube`로
고정했다 - **6-32의 finance contamination(SCOUT category와 KNOWLEDGE
article_type 혼동)과 같은 종류의 위험**을 이번에는 코드가 실제로
갖고 있기 전에 발견해서 명시적으로 문서화/테스트로 막았다.

`article_type`/`category`/`domain`은 `KnowledgeRecord`에만 있고
`PerformanceRecord`에는 없다 - content-type 인식 분석이 필요하면
호출부가 KNOWLEDGE를 별도로 조회해 넘겨야 한다(이번에 그런 분석
함수를 만들지 않았다 - `IMPLEMENTED`된 4개 insight type은 platform/
scope만으로 충분하다).

## 13. KNOWLEDGE 분석

3개 분석 레벨(CONTENT/GENERATION/KNOWLEDGE)을 `scope` 필드로 명확히
구분했다: CONTENT(`scope="content"`, scope_id=content_id) - 특정 Blog
하나. **GENERATION은 별도 scope로 지원하지 않았다** - 14장에서 그
이유를 설명한다. KNOWLEDGE(`scope="knowledge"`, scope_id=knowledge_id) -
동일 KNOWLEDGE에서 파생된 전체 콘텐츠를 **합산**해서 분석한다(예:
`KnowledgeGenerationScopeTests::test_knowledge_scope_groups_multiple_content_ids`
가 content-A/content-B 두 개를 knowledge scope로 합쳐 sample_size=6을
확인). CONTENT와 KNOWLEDGE는 서로 다른 insight_id를 가지므로 섞이지
않는다.

## 14. Generation 분석

**`scope="generation"`을 지원하지 않기로 결정했다** - 6-34 11장의
구조 분석(`compute_content_id()`가 `rewritten_*`을 쓰지 않아
content_id가 generation-invariant함)을 그대로 재사용한 결론이다:
`PerformanceRecord`에 애초에 `generation_id` 필드가 없으므로(2장),
generation 단위로 Performance를 분리할 데이터 자체가 없다.
`scripts/analyze_performance.py --scope generation`을 실행하면
"PerformanceRecord에는 generation_id가 없습니다... --scope content로
다시 실행하세요"라는 안내와 함께 exit 1을 반환한다(CLI 레벨로
명시). generation A/B가 서로 다른 Blog/Shorts/Threads를 만들어도,
**최종적으로 게시된 것은 항상 하나의 content_id**(promotion
overwrite protection이 보장, 6-31/6-34)이므로 실질적으로
generation_id 없이도 정확성이 유지된다. legacy 데이터(generation_id
개념 자체가 없던 시절)도 이 설계 덕분에 **자동으로 호환된다** -
`KnowledgeGenerationScopeTests::test_legacy_records_without_generation_concept_still_work`로
확인했다.

## 15. Superseded

OLD(approved→published→성과 발생)→superseded→NEW(approved→published→
성과 발생) 구조를 synthetic으로 만들어 검증했다
(`SupersededPreservationTests`, `FullEndToEndTest`): OLD의 3개
스냅샷과 NEW의 2개 스냅샷이 **완전히 독립적으로 계산**된다 - NEW의
`sample_size`가 2로 정확히 유지되고(OLD의 3개가 섞여 5가 되지
않음), NEW는 `MIN_SAMPLE_SIZE` 미만이라 `INSUFFICIENT_SAMPLE`로
정직하게 보고된다("데이터를 억지로 합쳐서 표본을 부풀리지 않는다").
OLD 성과를 NEW로 복사하지 않는다 - Insight 계산 함수 어디에도 그런
복사 로직이 없다. KNOWLEDGE 수준(`scope="knowledge"`)에서는 OLD+NEW
합산(5건)이 여전히 가능함을 함께 확인했다 - "동일 KNOWLEDGE 연결은
유지되어야 한다"는 지시를 정확히 만족한다.

## 16. Evidence

모든 Insight의 `evidence`는 실제 사용된 원본 스냅샷의
`content_id`/`metric_collected_at`/`value`를 담은 목록이다 - 요약값만
남기지 않고, 계산에 실제로 쓰인 개별 레코드를 전부 보존한다(신규
테스트 `test_evidence_contains_content_id_and_raw_values`).
`test_evidence_allows_human_to_trace_back`이 evidence에 담긴
content_id가 실제로 그 분석에 쓰인 것과 정확히 일치함을 확인했다 -
사람이 "왜 이 Insight가 나왔는가"를 역추적할 수 있다.

## 17. Explainability

`observation` 필드가 항상 원본 값의 나열("100 → 120 → 150 → 180")과
결과("INCREASING")를 함께 보여준다(신규 테스트
`test_explainability_observation_shows_raw_series`) - 결과만 던지지
않고 근거가 되는 실제 숫자를 사람이 바로 읽을 수 있게 했다.

## 18. False Insight 방지

| 조건 | 처리 |
|---|---|
| sample 부족 | `INSUFFICIENT_SAMPLE`(8장) |
| metric 부족 | sample_size=0 → `INSUFFICIENT_SAMPLE`(해당 metric이 없는 레코드는 evidence에서 자동 제외) |
| measurement window 불일치 | `compare_to_baseline()`이 `target_window` 불일치 시 `INCOMPARABLE`(6장) |
| platform 혼합 | `check_comparable()`/`compare_to_baseline()`의 `target_platform` 검사로 `INCOMPARABLE` |
| duplicate snapshot | Performance 레이어(6-34)가 이미 idempotent하게 처리 - Insight 계산에 중복이 넘어오지 않음(넘어와도 evidence에 같은 (content_id, metric_collected_at)이 두 번 나타나지 않음, store.py의 원천 dedup 덕분) |
| invalid metric | Insight 계산 함수가 `metric in r.metrics` 필터만 하므로 애초에 존재하지 않는 metric은 조용히 제외(값 지어내지 않음) |
| timestamp 오류 | `classify_measurement_window()`가 `"unknown"`으로 안전 처리(6-34) |
| identity 불명확 | `check_traceability()`가 `INCONSISTENT` 반환(13장) |
| superseded 관계 불명확 | Insight 레이어는 애초에 `review_status`/`superseded_by`를 모른다(23장 경계와 동일 이유) - 관계 판단은 호출부(Production Archive를 아는 코드)의 책임 |

## 19. Human Review

`status`는 `candidate`(기본값)→`accepted`/`rejected`로만 전이한다
(`set_insight_status()`). **accepted도 자동 행동을 의미하지 않는다** -
19장 지시를 코드 부재로 증명했다(3장 참고, 소스 문자열 검사 테스트).
재분석(같은 입력)이 이미 accepted/rejected된 status를 조용히
candidate로 되돌리지 않는다(`append_insights()`가 insight_id가 이미
존재하면 완전히 건너뛰므로 - `test_reanalysis_does_not_revert_accepted_status`).

## 20. Monetization

6-34의 monetization 구조(15/16/17장, "content_id→revenue 직접 귀속
가능한 것과 간접 귀속을 구분, 추정값을 실제 revenue처럼 저장하지
않는다")를 재사용했다 - 5장에서 설명했듯 `INSIGHT_TYPES`에
`"monetization"`을 예약만 하고 실제 분석 함수는 만들지 않았다(6-34가
이미 확인했듯 revenue 필드 자체가 아직 채워지지 않으므로, 없는
데이터로 귀속을 계산하는 함수를 지어내지 않는다). 신규 테스트
(`test_monetization_insight_type_is_reserved_but_not_implemented`)로
이 경계를 고정했다.

## 21. Performance Report

DAILY/WEEKLY 리포트의 데이터 조회 요소는 기존 함수 조합으로 이미
가능함을 확인했다(6-34 14장과 동일한 결론 패턴): 측정 가능
콘텐츠/measurement pending/데이터 오류는 6-34의 `quality.py`+ 이번의
`INSUFFICIENT_SAMPLE`/`INCOMPARABLE` 상태값 조합으로 표현 가능.
platform별 metric은 `analyze_trend(scope="platform", ...)`. KNOWLEDGE별
관찰은 `scope="knowledge"`. Monetization 관찰은 20장에 따라 아직
`FUTURE`. **단순 ranking이나 winner 선정 함수는 만들지 않았다**(7장과
동일 원칙) - 실제 리포트 렌더링 함수(Dashboard 화면 등)는 이번에
구현하지 않았다(`FUTURE`, 대규모 UI 금지 원칙 - 6-33/6-34와 동일한
판단).

## 22. CLI

`scripts/analyze_performance.py`(신규)를 추가했다 - Performance
저장소를 **읽기만** 하고, `--output`을 명시하지 않으면 아무 파일도
쓰지 않는다(완전한 읽기 전용 실행). `--type trend`/`--type anomaly`를
지원한다(comparison/traceability는 baseline 레코드 등 추가 입력이
필요해 프로그래밍 API로만 제공 - "필요하다면 CLI 하나만"이라는
지시에 따라 CLI를 과도하게 확장하지 않았다). `--output`을 명시하면
계산 결과를 그 경로에 idempotent하게 추가하지만 기본값은 없다
(`scripts/import_performance_snapshots.py`, 6-34와 동일한 안전
원칙). 항상 `status="candidate"`로만 만든다.

## 23. Idempotency

`ANALYZE A`를 두 번 실행해도 `insight_id`가 동일해(입력 데이터의
결정적 지문이므로) `append_insights()`가 1건만 저장한다(신규
테스트). `ANALYZE A` 후 `ANALYZE B`(다른 입력 - 새 스냅샷이 추가된
경우)는 새 `insight_id`가 나와 2번째 Insight로 **추가**된다(덮어쓰지
않음) - Performance와 마찬가지로 "변화의 역사"가 보존된다.

## 24. Failure Injection

| # | 시나리오 | 결과 |
|---|---|---|
| 1 | missing content_id | 해당 없음(PerformanceRecord 자체가 6-34 models.py에서 이미 차단) |
| 2 | missing knowledge_id | 해당 없음(동일) |
| 3 | missing platform | 해당 없음(동일) |
| 4 | unknown content_id | `check_traceability()` → `INCONSISTENT`(레코드 없음) |
| 5 | unknown generation_id | 해당 없음(14장 - scope 자체가 없음) |
| 6 | duplicate snapshot | Performance 레이어가 이미 idempotent(6-34) |
| 7 | invalid views(음수) | 6-34 `quality.py`가 `WARNING`(Insight 계산은 그 값을 그대로 반영 - 지어내지 않음) |
| 8 | decreasing views | `analyze_trend()` → `DECREASING`(정상 분류, 오류 아님) |
| 9 | mixed windows | `compare_to_baseline()`의 `analysis_window` 필터로 자동 분리(`test_mixed_windows_is_handled_by_explicit_window_param`) |
| 10 | mixed platforms | `check_comparable()`/`target_platform` 검사로 `INCOMPARABLE` |
| 11 | superseded content | 18장 - Insight 레이어는 판단하지 않음(호출부 책임) |
| 12 | insufficient sample | `INSUFFICIENT_SAMPLE`/`UNKNOWN`(8장) |
| 13 | malformed performance data | 6-34 `store.py`가 이미 `MediaArchiveError`류로 차단(Insight 레이어에 도달하지 않음) |
| 14 | duplicate insight | `append_insights()`가 `insight_id` 기준으로 조용히 제외(23장) |

## 25. END-TO-END

`FullEndToEndTest::test_knowledge_to_accepted_insight_with_superseded_lineage`가
전체를 한 번에 검증한다: KNOWLEDGE(`knowledge-e2e`) → Generation(OLD/
NEW 두 콘텐츠) → Threads 게시(review_status="approved", 이후 OLD가
superseded) → Performance snapshot(OLD 3건, NEW 2건) → Analysis
(trend + traceability) → Insight Candidate → Human Review
simulation(`set_insight_status`) → Accepted. 검증한 것: content
identity(OLD/NEW가 각자의 content_id로 분리), knowledge identity
(둘 다 knowledge-e2e로 연결), generation identity(해당 없음, 14장
결론), performance separation(OLD 3건/NEW 2건 정확히 유지),
superseded preservation(NEW가 INSUFFICIENT_SAMPLE로 정직하게 보고,
OLD와 섞이지 않음), evidence(traceability의 evidence가 실제
content_id를 담음), explainability(trend observation이 원본 시계열
포함), duplicate prevention(재분석 시 append 결과가 idempotent),
**Production Archive isolation**(분석 전후 archive 파일 바이트가
완전히 동일함을 직접 비교).

## 26. Security

API key/OAuth token/refresh token/secret/이메일/인증정보가 Insight
출력에 노출되지 않는지 신규 2개 테스트로 확인했다: (1)
`PerformanceRecord.title`에 시크릿 유사 문자열을 넣고 Insight를
계산한 뒤 `to_dict()`를 JSON 직렬화한 결과에 그 문자열이 없음을
확인(Insight 계산 함수들이 `title`/`raw`/`external_id`를 evidence에
포함하지 않고 `content_id`/`metric_collected_at`/`value`만 담기
때문에 구조적으로 안전하다), (2) `scripts/analyze_performance.py`의
실제 stdout 출력을 캡처해 같은 시크릿 마커가 없음을 확인했다.

## 27. 테스트

실행 순서(지시사항 27/28장 그대로):

1. 신규 테스트: `python -m unittest discover -s tests -p "test_6_35*.py" -v` - 48개 전부 PASS.
2. 관련 회귀(Performance 기존 테스트, `content_engine/performance/`를 수정하지 않았으므로 회귀 위험 최소).
3. 전체:

```
python -m unittest discover -s tests -p "test_*.py"
Ran 1229 tests in 77.815s
OK (skipped=17)
```

failed=0, errors=0. skip으로 문제를 숨기지 않았다(17건은 이 세션
이전부터 존재하던 조건부 skip). `git status --short`를 테스트 전/후
모두 확인했고 `data/` 아래 운영 데이터(`tak_performance.json`,
`tak_performance_insights.json` 포함)는 전혀 생성/수정되지 않았다.

## 28. 운영 데이터 보호

작업 전/후 `git status --short`로 확인했다 - `data/`
아래 파일 목록에 변화가 없다(신규 코드 3개 파일만 추가됨). 기존에
없던 `data/tak_performance_insights.json`은 이 세션에서도 만들지
않았다 - 여전히 없는 상태로 유지된다.

## 29. 10월 1일 운영 연결

```
SCOUT → KNOWLEDGE → MEDIA → HUMAN REVIEW → PROMOTION →
PRODUCTION ARCHIVE → PUBLISH → PERFORMANCE → INSIGHT →
HUMAN ANALYSIS → NEXT CONTENT
```

Insight가 KNOWLEDGE/MEDIA를 자동으로 변경하지 않는다는 것은 3/19장에서
코드 부재로 증명했다. 10월 1일부터 실제 Performance 데이터가
쌓이면: (1) `scripts/collect_performance.py`(6-34)로 스냅샷 수집 →
(2) `scripts/analyze_performance.py`(6-35 신규)로 candidate 계산 →
(3) 사람이 결과를 보고 `set_insight_status()`로 accept/reject(현재는
CLI 없이 Python API로만 가능 - Dashboard 통합은 `FUTURE`) → (4) 그
분석 결과를 참고해 사람이 직접 다음 KNOWLEDGE/콘텐츠 전략을
결정한다(자동화 없음). 이 구조는 실제 데이터가 없는 지금도 synthetic
fixture로 전부 연결 확인이 끝났으므로, 10월 1일 이후 실제 Performance가
쌓이는 즉시 같은 경로로 그대로 연결할 수 있다.

## 30. 결론

Performance(원자료)와 Insight(파생 결과)를 물리적으로 분리된 모듈로
구현했고, 10개 핵심 원칙(Performance=원자료, Insight=파생결과,
Performance 불변, KNOWLEDGE/MEDIA 자동 미수정, 콘텐츠 전략 자동
미변경, 사람 최종 판단, 외부 API 미호출, 운영 데이터 미생성/수정,
synthetic/tempfile만 사용, 그리고 이번에 코드로 증명한 "accepted도
자동 행동이 아님")을 전부 테스트로 직접 증명했다. TREND/COMPARISON/
ANOMALY/TRACEABILITY 4개 insight type을 구현했고, DISTRIBUTION/
MONETIZATION은 근거 있는 이유로 `FUTURE`로 남겼다. **가장 중요한 신규
발견은 MediaArchiveRecord.platform("shorts")과 PerformanceRecord.platform
("youtube")의 이름 불일치**다(12장) - 실제 버그가 되기 전에 명시적
매핑 상수와 회귀 테스트로 미리 막았다. 전체 1229개 테스트가
failed=0/errors=0으로 통과했고, 실제 `data/` 운영 디렉터리는 어디에서도
생성/수정되지 않았다.
