# 6-32 Content Production Engine Hardening

## 1. 목적

10월 1일 실제 운영에서 가장 먼저 실행될 SCOUT→KNOWLEDGE→MEDIA 생산
구간을 실제 코드 기준으로 집중 점검하고, 발견된 실제 결함(false
positive)을 최소 수정으로 고친다. 새 기능을 만들지 않고, 기존 로직이
안전하게 동작하는지 확인하는 것이 목표다. 실제 외부 API(RSS 네트워크
포함)는 어디에서도 호출하지 않았고, 실제 운영 데이터(`data/`)는 전혀
생성/수정하지 않았다 - 모든 검증은 tempfile + synthetic fixture로만
수행했다.

First Sync Check: `git status --short`(clean), HEAD==origin/main
(c91ec5e) 확인 후 시작했다.

## 2. SCOUT 구조

Entry point: `scripts/run_scout.py` → `tak_scout.collector.build_daily_pack()`
→ `data/tak_scout_daily.json`/`.md`. 입력은 `data/scout_sources.json`에
등록된 RSS 주소 목록뿐이다(로그인/크롤링/접근 제한 우회 없음). 각
source는 `collect_from_source()` → `parse_rss_items()`(`tak_scout/rss.py`)로
`ScoutCandidate`(scout_id/title/summary/source_url/published_at/
source_name/category) 목록을 만든다. `collect_all()`은 source 1건이
`ScoutRssError`를 던져도 나머지 source는 계속 수집한다(기존 6-24
원칙, 이번에 재확인).

## 3. SCOUT scoring

`tak_scout/scoring.py`가 LLM 없이 순수 규칙 기반(rule-based,
deterministic) 점수를 매긴다. 5개 차원(총 100점): A. 콘텐츠 관심도
(0~25), B. 티몽 전문성 연관성(0~25, 금융/대출/경매/부동산), C. 의견
형성 용이성(0~20), D. 수익화 관련성(0~15), E. 최신성(0~15). 키워드
목록은 코드 상수(`_INTEREST_KEYWORDS` 등)로 관리하며, 단어 경계(`\b`)로
매칭해 "ai"가 "said"에 우연히 걸리는 것을 막는다. `category` 필드는
보조 신호로만 약하게 반영한다(`_FINANCE_LIKE_CATEGORIES`) - 카테고리
하나로 후한 점수를 주지 않는다.

## 4. Category / Domain / ArticleType

**6-04에서 이미 발견·수정된 문제를 이번 세션에서 CASE A~D로 재현·재확인했다**
(`ScoutCategoryContaminationTests`, 신규 4개 테스트, 전부 PASS):

- **CASE A(회귀 감지)**: BBC Business RSS(`category="finance"`)로 들어온
  AI 안전성 기사가 `article_type=None`으로 유지되는지 확인했다 -
  `tak_scout/knowledge_bridge.py::build_knowledge_from_interview()`가
  `article_type = None`을 명시적으로 고정한다(78-97행 주석에 6-04의
  원래 재현 사례: `knowledge-scout-b28b782b2a33`가 그대로 기록되어
  있다). SCOUT 경로에는 본문을 실제로 분석하는 content-based 분류기가
  없으므로, 없는 신호를 있는 것처럼 만들지 않는다는 원칙이 지금도
  유지된다.
- **CASE B**: 실제 금융 콘텐츠는 `article_type="finance"`가 될 수
  있다 - 단 `tak_brain.article_types.ArticleTypeClassifier`(본문
  키워드 분석)를 통해서만 가능하다(블로그 RAW 임포트 경로에서 사용,
  SCOUT 경로에는 적용되지 않음). 확인했다.
- **CASE C**: `category`/`domain`에 "부동산"이 포함되면
  `content_engine.blog_publish_pack.is_review_required()`가
  `article_type`과 무관하게 독립적으로 True를 반환한다 - 안전장치가
  이중으로 작동함을 확인했다.
- **CASE D**: 등록되지 않은 category는 `_map_category()`가 "기타"로
  안전하게 fallback한다(크래시 없음).

**결론: `IMPLEMENTED`/`VERIFIED`** - 6-04의 수정이 여전히 유효하고,
이번 세션에서 코드를 바꾸지 않았다(회귀 없음 확인만).

## 5. Duplicate Detection

`tak_scout/collector.py::dedupe_candidates()`가 URL(소문자/공백
정규화/trailing slash 제거) 또는 제목(공백 정규화/소문자화) 중 하나라도
같으면 먼저 나온 후보만 남긴다 - **같은 `build_daily_pack()` 실행
1회 내에서만** 동작한다(과거 실행 결과나 기존 KNOWLEDGE와는 비교하지
않는다).

신규 테스트(`ScoutDuplicateDetectionTests`, 6개)로 확인한 사실:
- URL 대소문자/trailing slash 차이 → 중복 제거됨.
- 제목 공백/대소문자 차이(다른 source/URL이어도) → 중복 제거됨.
- 실제로 다른 이야기 → 중복 제거되지 않음(정상).
- **번역은 dedup에 영향을 주지 않는다** - `tak_scout/title_translation.py`의
  번역은 별도 파일(`scout_id` 키)에 저장되고 INTERVIEW 표시 단계에서만
  쓰인다(`InterviewLLMProvider.translate_titles()`). `dedupe_candidates()`는
  원문 `candidate.title`만 비교하므로 번역 유무와 무관하게 동일한
  결과를 낸다 - 구조적으로 참이다.
- 같은 `scout_id`에 같은 답변을 두 번 적용해도(재실행 시나리오)
  `knowledge_id = sha256(scout_id:option:custom)[:12]`가 결정적으로
  동일해 idempotent함을 확인했다 - 중복 KNOWLEDGE가 생기지 않는다.

**"같은 뉴스가 하루에 여러 번 들어오면 KNOWLEDGE가 중복 생성될
가능성이 있는가?"**: 같은 실행 내에서는 URL/제목 매칭으로 방지된다.
서로 다른 실제 URL로 같은 사건을 다루는 기사(다른 매체의 후속 보도
등)는 현재 정책상 감지되지 않는다 - 이는 의도된 설계 트레이드오프다
(`tak_scout/models.py::compute_scout_id()`의 docstring이 "제목과 원문
URL로 deterministic한 scout_id"를 명시하며, LLM 기반 의미 유사도
매칭을 쓰지 않는다는 rule-based 원칙을 scoring.py와 동일하게 따른다).
**기존 ID 정책을 변경하지 않았다** - 이 문서에 사실만 기록한다.

**결론: `VERIFIED`**(동일 실행 내 dedup) / 크로스데이 의미 기반 dedup은
`NOT_IMPLEMENTED`(의도된 설계, `FUTURE` 대상 아님).

## 6. KST Schedule

`.github/workflows/daily-scout.yml`의 cron은 `'0 23 * * *'`(UTC
23:00) = KST(UTC+9) 익일 08:00이다. 신규 테스트
(`KstScheduleTests::test_workflow_cron_is_23_00_utc_which_is_08_00_kst_next_day`)로
워크플로 파일의 실제 cron 문자열과 산술을 함께 검증했다. 한국은
DST(서머타임)를 시행하지 않으므로 이 오프셋(+9)은 연중 항상
고정이다 - 미국/유럽 cron처럼 계절별 재조정이 필요 없다.

**결론: `VERIFIED`**.

## 7. KNOWLEDGE Bridge

`tak_scout/knowledge_bridge.py::build_knowledge_from_interview()`가
`ScoutCandidate` + `InterviewAnswer`를 `pending` 상태의
`KnowledgeRecord`로 변환한다. 유지되는 필드: `id`(knowledge_id),
`source_raw_id`(scout_id), `source_url`, `title`, `category`/`domain`
(SCOUT category에서 변환, 4장), `evidence`(SOURCE FACT/SOURCE URL/
USER ANGLE 또는 USER ORIGINAL THOUGHT 라벨 유지), `created_at`,
`knowledge_review_status="pending"`(항상 고정). **SCOUT source
category와 KNOWLEDGE article_type은 4장에서 확인한 대로 완전히
분리되어 있다** - `article_type`은 SCOUT 경로에서 항상 `None`이다.

## 8. KNOWLEDGE Approval

상태값은 `knowledge_review_status`: `pending`/`approved`/`dismissed`
(`tak_brain/knowledge.py`). `validate_knowledge()`가 새로 생성되는
KNOWLEDGE는 반드시 `pending`이어야 한다고 강제한다(83-84행) - **AI가
직접 approved를 설정하는 코드 경로는 없다**. 승인은
`scripts/review_knowledge.py --approve --id <id>`로만 가능하고,
이는 사람이 명시적으로 CLI를 실행해야 하는 동작이다(`assess_knowledge_quality()`는
권고만 하고 자동 적용하지 않는다). 신규 테스트
(`test_approval_missing_means_media_batch_produces_nothing`)로 미승인
KNOWLEDGE가 `select_approved()`에서 제외됨을 재확인했다.

**결론: `VERIFIED`** - 자동 승인 경로 없음.

## 9. MEDIA Generation

`content_engine.pipeline.run_media_batch()`가 approved KNOWLEDGE
1건당 Blog 1 + Shorts 3 + Threads 5 = 9개 `MediaBatchItem`을
생성한다(6-28 fixture 재사용으로 재확인). 각 아이템은 `content_id`
(`compute_content_id()`), `generation_id`(배치 단위 공유),
`platform`, `source_url`, `knowledge_id`, `original_title`/
`original_body`, `rewritten_title`/`rewritten_body`,
`review_status`(초기 `unreviewed`), `generation_status`(`valid`/
`rejected`/`error`)를 갖는다(`MediaArchiveRecord.from_item()`로 변환).

## 10. Generation Pool

`content_engine/media_archive.py::upsert_generation_archive()`는
`(content_id, generation_id)` **복합 키**로 upsert한다 - 같은
content_id라도 generation_id가 다르면 서로 다른 레코드로 **둘 다
보존**한다. Production Archive(`upsert_archive()`, content_id 단일
키)와의 차이는 바로 이 지점이다: generation pool은 "이 콘텐츠 슬롯의
여러 생성 시도 전체"를, production archive는 "지금 활성 상태인 정확히
하나"를 담는다. review_status/generation_status/edited_title/
edited_body/approval/dismissal은 generation pool 단계(Dashboard
`/media/generations`)에서 바뀌고, supersede/promotion은 production
archive 단계(`scripts/promote_media_generation.py`,
`scripts/supersede_media_record.py`)에서만 일어난다.

## 11. content_id / generation_id

과거 문제("동일 content_id + 다른 generation_id" overwrite)의 보호가
MEDIA generation 단계까지 실제로 적용되는지 CLI 레벨로 재확인했다
(`MediaGenerationOverwriteProtectionTests`, 신규):

- `--as-generation` 없이 `scripts/run_media_batch.py`를 다시 실행하면,
  `find_protected_overwrite_targets()`(6-24)가 이미 approved인
  content_id를 감지해 `main()`을 **exit 1로 차단**한다(단위 함수
  테스트가 아니라 실제 CLI 진입점으로 재확인, 6-29의 "실제 호출 경로를
  추적하라" 기준 유지).
- generation pool 자체는 복합 키 구조상 애초에 덮어쓰기가 구조적으로
  불가능하다(10장).
- Production Archive로의 최종 반영(promotion)은
  `check_promotion_conflict()`가 담당하며, 이미 6-31에서 CASE F로
  전체 검증했다(재인용, 이번에 새로 만들지 않음).

**결론: `VERIFIED`** - 3개 방어선(generation pool 복합 키 / MEDIA
재실행 가드 / promotion 충돌 검사) 모두 실제 코드로 확인됨.

## 12. Human Review

MEDIA 생성 직후 모든 아이템은 `review_status="unreviewed"`로
시작한다. Dashboard `/media/generations`에서 사람이 승인/수정/보류하고,
`scripts/promote_media_generation.py`가 `review_status=="approved"`
+ `generation_status=="valid"`인 레코드만 승격 대상으로 받아들인다
(`plan_promotion()`이 그 외는 전부 `PromotionError`). AI가 직접
승인 상태를 바꾸는 코드는 어디에도 없다(8장과 동일한 원칙).

## 13. Content Safety

과거 문제였던 항목을 재조사했다:

- **finance contamination**: 4장에서 재확인, `IMPLEMENTED`/`VERIFIED`.
- **new facts**: `RewriteValidator._fact_scope_errors()`가 숫자
  (`_new_number_errors`)/엔티티(사람·기관·상품명)/위험 단어를 원문에
  없으면 차단한다 - 14장에서 구체적으로 재검증.
- **source URL 누락**: `RewriteValidator.validate()`가
  `rewritten_draft.source_url != request.source_url`이면 무조건
  차단한다(기존 로직, 변경 없음).
- **rewritten text 안전 경계**: `_finance_errors()`가 금융 콘텐츠의
  "공식 심사 기준" 관련 확정적 표현을 차단한다(변경 없음).
- **experience false positive**: 14장에서 실제로 재현하고 수정했다.

## 14. LLM Boundary

`content_engine/llm_provider.py::OpenAICompatibleRewriteProvider`가
API key/endpoint/model을 환경변수(`TAK_MEDIA_LLM_API_KEY`/
`TAK_MEDIA_LLM_ENDPOINT`/`TAK_MEDIA_LLM_MODEL`)로만 받는다(`from_environment()`,
값을 하드코딩하지 않음). prompt는 `content_engine/rewrite.py`의
`RewriteRequest`가 구성하고, validator(`RewriteValidator`)가 provider
응답을 사후 검증한다 - provider 자체를 신뢰하지 않는 구조다. 이번
세션에서 실제 API를 호출하지 않았고, 전부 `MockRewriteProvider`만
사용했다.

**"경험" false positive 재현·수정** (신규 발견, 이번 세션의 유일한
프로덕션 코드 변경):

- **재현**: `content_engine/rewrite.py`의 `_FACT_RISK_TERMS`에
  "경험"이 포함되어 있었다. `_fact_scope_errors()`는 재작성된 텍스트에
  이 목록의 단어가 있는데 `source_text`(KNOWLEDGE 필드 + 원본 draft +
  evidence)에는 없으면 "사실 범위를 넓히는 표현이 추가되었습니다"로
  차단한다. `knowledge_type="의견"`인 SCOUT 경로 KNOWLEDGE에서, 재작성이
  "제가 이 도구를 써 본 경험을 나눕니다"처럼 **새로운 사실이 전혀
  없는데도** "경험"이라는 글자 하나 때문에 거부되는 것을 실제로
  재현했다(`tests/test_6_32_scout_knowledge_media_hardening.py`의
  수정 전 상태로 재현, 수정 후 `test_using_the_word_experience_alone_is_not_flagged`로
  고정).
- **원인**: "경험"은 다른 항목(성과/수익/매출/계약/투자/창업 등)과
  달리 그 자체로 구체적인 새 사실·주장을 나타내지 않는 일반 서술
  단어다. `knowledge_type == "경험"`인 KNOWLEDGE는 `source_text`에
  `knowledge_type` 필드 값 자체가 포함되어 "경험"이 이미 들어있으므로
  문제가 드러나지 않았지만, SCOUT 경로(`knowledge_type="의견"`)처럼
  그 글자가 우연히 없는 경우에만 false positive가 발생했다.
- **최소 수정**: `content_engine/rewrite.py`의 `_FACT_RISK_TERMS`에서
  "경험"만 제거했다(1줄). 나머지 19개 위험 단어는 전부 유지했다 -
  `test_genuinely_new_facts_are_still_rejected`로 "매출"/"계약" 같은
  실제 새 사실은 여전히 차단됨을 확인했다. **validator를 느슨하게
  만들어 새로운 사실을 통과시키는 방향으로 수정하지 않았다**(지시사항
  준수).
- **regression test**: `ExperienceFalsePositiveRegressionTests`(2개)로
  고정. `tests/test_content_engine.py`의 기존 49개 테스트도 이 수정
  이후 전부 그대로 통과함을 확인했다(다른 위험 단어로 이미 차단되던
  테스트들은 영향받지 않음).

## 15. LLM Failure Handling

`content_engine/pipeline.py::run_media_batch()`의 draft별 루프(179-227행)가
각 draft를 **개별 try/except**로 감싼다 - 하나의 provider 예외가
다른 8개 draft의 처리를 막지 않는다. 8가지 synthetic 실패를 코드
기준으로 매핑했다:

| # | 실패 | 결과 | production까지 도달? | 근거 |
|---|---|---|---|---|
| 1 | timeout | 해당 draft `status="error"`, `error_message` 기록 | 아니오 | `except Exception` 캐치 |
| 2 | invalid JSON | provider 구현 책임(현재 `MockRewriteProvider`/`OpenAICompatibleRewriteProvider`는 파싱 실패 시 예외) | 아니오 | 위와 동일 경로 |
| 3 | empty output | `RewriteValidator`가 빈 제목/본문을 새 사실 없음으로 통과시킬 수 있음(별도 빈값 검증은 현재 없음) | 조건부 - `NOT_IMPLEMENTED`(빈 문자열 명시적 차단 없음, 기존 정책) | `_fact_scope_errors` 등은 "새로 추가된" 것만 봄 |
| 4 | missing title | `ContentDraft.title`이 없으면 `generate_content_bundle()` 단계에서 `bundle.status != "complete"`로 이미 걸러짐 | 아니오 | pipeline.py 157-175행 |
| 5 | missing body | 4와 동일 | 아니오 | 동일 |
| 6 | unsupported new fact | `_fact_scope_errors`/`_new_number_errors`가 차단 → `status="rejected"` | 아니오(rejected는 promotion 불가) | `RewriteValidator` |
| 7 | validator rejection | `status="rejected"`, `rejection_reasons` 기록 | 아니오 | 동일 |
| 8 | partial platform generation | 18장 참고 | 실패분만 제외, 성공분은 정상 처리 | pipeline.py |

**결론: 대부분 `IMPLEMENTED`/`VERIFIED`** - retry는 현재 없음
(`NOT_IMPLEMENTED`, 실패한 draft는 사람이 재실행으로만 복구), human
review로는 자동 전달되지 않는다(애초에 promotion 후보가 되지 못하므로
review 대상에도 안 올라감 - "조용히 사라지는" 것이 아니라 report에
`status="error"/"rejected"`로 명시적으로 남는다).

## 16. Partial Generation

9개 중 일부만 성공하는 경우(예: 7 성공 + 2 실패)를 15장의 개별
try/except 구조로 확인했다: 성공한 7개는 `status="valid"`로 정상
report에 포함되고, 실패한 2개는 `status="error"`/`"rejected"`로 같은
report에 함께 남는다(리포트 자체가 부분 실패로 무효화되지 않는다).
실패한 2개는 `generation_status`가 `valid`가 아니므로
`plan_promotion()`이 구조적으로 거부한다(6-31에서 CASE D로 이미
검증, 재인용) - **production에 실패한 결과가 들어갈 방법이 없다**.
재생성은 같은 KNOWLEDGE로 `run_media_batch.py`를 다시 실행하면 되며,
이는 17장의 Regeneration과 동일한 경로다.

## 17. Regeneration

같은 KNOWLEDGE에서 generation 1, generation 2가 생성되는 경우:
`upsert_generation_archive()`가 `(content_id, generation_id)` 복합
키로 둘 다 보존하므로 generation 1의 기록이 사라지지 않는다(10장).
review_status는 generation마다 독립적으로 관리된다. **기존
production을 자동 overwrite하지 않는다** - promotion은 항상 사람이
`--content-id`+`--generation-id`를 명시해서 실행해야 하고
(`check_promotion_conflict()`가 다른 generation_id로의 승격을 막는다,
11장/6-31 CASE F).

## 18. 10월 1일 First Content Rehearsal

`FirstContentRehearsalTest::test_scout_candidate_reaches_publish_readiness`(신규)가
SCOUT candidate(synthetic) → KNOWLEDGE pending(`build_knowledge_from_interview()`)
→ Human approval(replace로 명시적 승인, AI가 바꾸지 않음) → MEDIA
generation(`run_media_batch()`, 9개) → Generation Pool
(`upsert_generation_archive()`) → Human Review(승인) → Promotion
(`plan_promotion()`) → Production Archive(`upsert_archive()`) →
Publish Readiness(`audit_archive()` → `READY`)까지 실제 함수를 순서대로
호출해서 연결을 확인한다. 테스트 종료 시 `tempfile.TemporaryDirectory`가
정리되어 실제 `data/`에는 어떤 파일도 남지 않는다.

## 19. Failure Injection

SCOUT/KNOWLEDGE 레벨 6가지를 이번 세션에서 새로 검증했다
(`ScoutKnowledgeFailureInjectionTests`, `ScoutDuplicateDetectionTests`):

| 구간 | 장애 | 최종 상태 |
|---|---|---|
| SCOUT | source unavailable | 해당 source만 error 기록, 나머지 계속(`SourceCollectionResult.error`) |
| SCOUT | malformed feed | `ScoutRssError` 명시적 예외(범용 크래시 아님) |
| SCOUT | duplicate | 같은 실행 내에서 `dedupe_candidates()`가 제거 |
| KNOWLEDGE | missing evidence | `validate_knowledge()`는 강제하지 않음(현재 정책, 사람이 review 단계에서 확인) |
| KNOWLEDGE | missing source | `validate_knowledge()`가 `ValueError`로 명시적 차단 |
| KNOWLEDGE | approval missing | `select_approved()`가 조용히 제외, MEDIA 대상 0건(크래시 없음) |

MEDIA/REVIEW/PROMOTION 레벨 6가지(LLM timeout/invalid JSON/validator
reject/partial generation, dismissed/unreviewed, conflict/superseded)는
15/16/17장과 6-31의 `FailureInjectionTests`(12종)에서 이미 코드
경로로 검증되어 있으므로 이번에 중복 작성하지 않고 인용만 했다.

## 20. Performance 연결

이번에도 대규모 구현을 하지 않았다. `FirstContentRehearsalTest`에서
`knowledge_id`("knowledge-scout-..." 형태) → `content_id`
(`compute_content_id()`) → `generation_id`(`new_generation_id()`) →
`platform`("threads")가 하나의 체인으로 정확히 연결됨을 확인했다
(`MediaArchiveRecord.from_item()`이 이 4개 필드를 모두 채운다). 향후
`publish_status`/`views`/`likes`/`comments`/`CTR`을 연결할 수 있는
구조인지: `content_engine/performance/models.py`의 `PerformanceRecord`가
이미 `content_id`/`knowledge_id`를 필수 필드로 요구하므로(6-01/6-02),
연결 가능한 구조임을 코드로 재확인했다(구현은 여전히
`NOT_IMPLEMENTED` - 피드백 루프 자체가 없음, 6-28/6-29/6-30/6-31과
동일).

## 21. 실제 운영 명령

문서에서 추측하지 않고 실제 `scripts/` CLI를 기준으로 작성했다(6-31
18장과 동일한 근거, 여기서는 SCOUT~Readiness 구간만 재정리).

```
# SCOUT
python scripts/run_scout.py

# KNOWLEDGE
python scripts/run_interview.py
python scripts/apply_interview.py
python scripts/review_knowledge.py --pending
python scripts/review_knowledge.py --id <knowledge_id> --approve

# MEDIA
python scripts/run_media_batch.py --input data/tak_brain_knowledge.json \
    --execute --as-generation --archive <generation-pool-path>

# Review (Dashboard)
python scripts/run_scout_dashboard.py
# 브라우저에서 "/media/generations"

# Promotion
python scripts/promote_media_generation.py --archive <generation-pool-path> \
    --generation-id <generation_id> --content-id <content_id> --execute

# Readiness
python scripts/audit_publish_candidates.py
```

## 22. Dashboard

`scripts/run_scout_dashboard.py`의 root(`/`) 페이지가 이미 SCOUT
candidate 목록을 보여주고, `/media`+`/media/generations`가 MEDIA
draft/generation pool 상태를 보여준다(기존 구현, 변경 없음). **KNOWLEDGE
전용 Dashboard 페이지는 없다** - `scripts/review_knowledge.py` CLI가
유일한 진입점이다. 이는 기존 의도된 설계이고(review_knowledge.py의
`--pending`/`--report`/`--show` 옵션이 이미 사람이 읽기 좋은 형태를
제공한다), 10월 1일 첫 실행을 막는 gap이 아니므로 이번 세션에서 새
UI를 만들지 않았다(지시사항의 "큰 UI 개편 금지" 준수).

**결론: `NOT_IMPLEMENTED`(KNOWLEDGE Dashboard 페이지, 의도된 설계) /
`IMPLEMENTED`(SCOUT/MEDIA Dashboard 페이지)**.

## 23. Security

API key/token/secret/refresh token/password는 어디에도 출력하지
않았다. `TAK_MEDIA_LLM_API_KEY`/`TAK_MEDIA_LLM_ENDPOINT`/
`TAK_MEDIA_LLM_MODEL`의 사용 위치(`content_engine/llm_provider.py`의
`from_environment()`)만 확인했다(재확인, 새로 발견된 것 없음).

## 24. 테스트

실행 순서(지시사항 26장 그대로):

1. 신규 테스트: `tests/test_6_32_scout_knowledge_media_hardening.py` - 21개 전부 PASS.
2. `tests/test_content_engine.py`(RewriteValidator 수정의 직접 영향 범위) - 49개 재확인, 전부 PASS.
3. SCOUT/KNOWLEDGE/MEDIA 관련 기존 테스트는 전체 회귀에 포함되어 실행됨.
4. 6-19/6-21/6-22/6-23/6-25/6-26/6-27/6-28/6-29/6-30/6-31 관련 파일은 전체 회귀에 포함되어 실행됨.
5. 전체 회귀:

```
python -m unittest discover -s tests -p "test_*.py"
Ran 1132 tests in 77.478s
OK (skipped=17)
```

failed=0, errors=0. 테스트 수를 맞추기 위해 기존 테스트를 삭제하거나
skip 처리하지 않았다(17건은 이 세션 이전부터 존재하던 조건부 skip).
`git status --short`를 테스트 전/후 모두 확인했고 `data/` 아래
운영 데이터는 전혀 변경되지 않았다.

## 25. 남은 P1/P2/P3

- **P2**: KNOWLEDGE 전용 Dashboard 페이지(22장, 의도된 설계이나 향후
  운영자 편의를 위해 고려 가능) - 10월 1일 첫 실행을 막지 않으므로
  P2로 유지.
- **P2**: 크로스데이 의미 기반 SCOUT 중복 감지(5장, 의도된 설계
  트레이드오프) - LLM 없는 rule-based 원칙을 유지하는 한 우선순위
  낮음.
- **P2**: LLM 실패 시 retry 미구현(15장) - 현재는 사람이 재실행.
- **P3**: empty output(빈 제목/본문)에 대한 명시적 validator 차단
  (15장, 현재 이런 입력이 실제로 발생한 사례는 없음).
- **P1**(6-30/6-31에서 이미 기록, 변경 없음): YouTube renderer 확보.

## 26. 결론

SCOUT→KNOWLEDGE→MEDIA 생산 구간을 실제 코드 기준으로 점검한 결과,
2026-06-04에 발견·수정된 "finance contamination" 문제는 여전히
올바르게 방어되고 있음을 CASE A~D로 재확인했다(4장). 이번 세션에서
새로 발견한 유일한 실제 결함은 `content_engine/rewrite.py`의
"경험" false positive였다(14장) - 재현 → 원인 확인 → 1줄 최소 수정
→ regression test 순서로 처리했고, 다른 위험 단어(성과/수익/매출/
계약/투자 등)의 보호 수준은 전혀 낮추지 않았다. content_id/
generation_id overwrite 보호는 generation pool 복합 키, MEDIA 재실행
가드, promotion 충돌 검사 3중으로 실제 CLI 경로에서 작동함을
확인했다(11장). 전체 1132개 테스트가 failed=0/errors=0으로
통과했고, 실제 `data/` 운영 디렉터리는 어디에서도 생성/수정되지
않았다.

10월 1일 SCOUT→KNOWLEDGE→MEDIA 구간은 21장의 명령 세트를 그대로
따라가면 안전하게 실행 가능하다 - 이번 세션에서 발견된 유일한 실제
버그를 수정했으므로, 6-31이 판정한 READY/READY_WITH_HUMAN_STEP 상태는
그대로 유지되며 신뢰도가 더 높아졌다.
