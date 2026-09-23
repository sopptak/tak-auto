# 6-36 Performance Insight Operationalization

## 1. 목적

6-35가 만든 Insight(Performance→Analysis→Insight Candidate→Human
Review)를 실제 운영자가 읽고 판단할 수 있는 운영 레이어로 발전시킨다:
PERFORMANCE→ANALYSIS→INSIGHT CANDIDATE→INSIGHT REPORT→HUMAN REVIEW→
OPERATIONAL DECISION→NEXT CONTENT. 이번에도 AI가 최종 전략을 자동
결정하지 않는다 - 이 원칙을 코드 부재(쓰기 함수 미import)로 직접
증명한다. 실제 외부 API는 호출하지 않았고, 실제 운영 데이터(`data/`
아래 Performance/Insight 파일 포함)는 어디에서도 생성/수정하지
않았다 - 전부 tempfile로만 검증했다.

First Sync Check: `git status --short`(clean), HEAD==origin/main
(25db4ad) 확인 후 시작했다.

## 2. 6-35 구조

`docs/6-35-performance-feedback-loop.md`와
`content_engine/performance_insight.py`를 재확인했다(변경하지
않음): `InsightRecord`(insight_id/created_at/analysis_window/scope/
scope_id/platform/metric/insight_type/result/observation/evidence/
sample_size/status), `analyze_trend()`/`detect_anomaly()`/
`compare_to_baseline()`/`check_traceability()`, append-only 저장
(`load_insights`/`append_insight(s)`/`set_insight_status`). 6-36은
이 API를 **그대로 재사용**한다 - 새 분석 로직을 다시 만들지 않았다.

## 3. 운영 레이어

새 모듈 `content_engine/insight_report.py`(6-36 신규)를 추가했다 -
**새 분석을 수행하지 않는다**: 이미 계산되어 저장된
`PerformanceRecord`/`InsightRecord` 목록을 입력으로 받아 필터링/
그룹화/집계만 한다. 책임 분리(19장 API Boundary)를 코드 구조로도
분리했다: Performance Provider(`content_engine/performance/`, 6-34) →
Insight Analyzer(`content_engine/performance_insight.py`, 6-35) →
Insight Store(6-35의 저장 함수) → **Report Generator(이 모듈, 6-36)** →
Human Review(이 모듈의 `record_decision()`, 사람이 직접 호출).

## 4. Daily Report

`DailyReportSummary`(`insight_report.py`)+`build_daily_report()`: 기간
내 measured content 수, valid/invalid metric 수(6-34
`check_metric_quality()` 재사용), candidate/accepted/rejected/
insufficient_sample/incomparable insight 수. `render_daily_report_text()`가
Section 15가 예시로 든 형식(Window/Data/Insights)을 그대로 출력한다.
실제 데이터가 없는 현재 환경에서 synthetic fixture로 검증했다
(`DailyReportTests`, 3개 신규 테스트).

## 5. Weekly Report

`WeeklyReportSummary`+`build_weekly_report()`: TREND/COMPARISON를
**platform별로 분리**해서 그룹화하고(`trend_by_platform`,
`comparison_by_platform`), KNOWLEDGE 수준 인사이트(`knowledge_insights`)와
Monetization(`monetization_insights`, 현재 항상 비어있음, 12장)을
따로 담는다. **Threads 7d와 Blog 30d를 하나의 평균으로 합치는 코드가
어디에도 없다** - `_group_by()`가 단순 나열만 하고 계산을 하지
않는다(`WeeklyReportTests::test_platforms_are_never_merged`로 확인).
`render_weekly_report_text()` 출력에 "최고"/"최악"/"1위"/BEST/WORST/
WINNER 문구가 없음을 직접 검증했다.

## 6. Insight 상태

`review_priority(insight)`(신규)가 "검토가 필요한 상태"만 반환한다
(좋고 나쁨이 아님, 7장 지시 정확히 반영):

| 조건 | Priority |
|---|---|
| status가 accepted/rejected | `REVIEWED` |
| status가 candidate + result=INSUFFICIENT_SAMPLE | `INSUFFICIENT_DATA` |
| status가 candidate + result=INCOMPARABLE | `INCOMPARABLE` |
| insight_type=traceability + result=INCONSISTENT | `INVALID` |
| 그 외 candidate | `NEW` |

6-35의 `STATUSES`(candidate/accepted/rejected)와 **충돌하지 않는다** -
`review_priority()`는 기존 `status` 필드를 대체하지 않고 그 위에
얹은 별도 분류다.

## 7. Human Review

CANDIDATE→REVIEWED→ACCEPTED/REJECTED을 `record_decision()`으로
구현했다 - 내부적으로 6-35 `set_insight_status()`를 그대로 호출해서
`InsightRecord.status`를 갱신하고, 그와 별개로 `DecisionRecord`
이력을 남긴다. **Accepted Insight가 다음 행동을 자동으로 실행하지
않는다** - `content_engine/insight_report.py` 소스 문자열에
`upsert_archive`/`save_archive`/`set_review_status`/`import tak_brain`가
전혀 없음을 테스트로 직접 증명했다
(`test_accepted_insight_never_triggers_knowledge_or_media_write`).

## 8. Decision Record

```
insight_id: str
decision: "accepted" | "rejected"
reviewed_at: str(ISO 8601)
reviewer_note: str = ""(사람이 직접 입력, AI가 채우지 않음)
```

실명/이메일 등 개인정보 필드를 요구하지 않았다(9장 지시). append-only
로 저장해 같은 insight_id에 대한 재검토 이력이 전부 보존된다
(`decisions_for_insight()`로 조회, 신규 테스트로 재검토 시 이력이
1건이 아니라 누적됨을 확인).

## 9. Evidence Drill-down

`drill_down_evidence(insight, performance_records, media_records=None)`이
Insight→Evidence→Performance snapshot→content_id→knowledge_id→
generation_id→platform까지 역추적한다. `knowledge_id`/`platform`은
Performance snapshot에서 직접 조회한다. **`generation_id`는
`PerformanceRecord`/`InsightRecord` 어디에도 저장되어 있지 않으므로**
(6-35 11장 결론 유지), `media_records`(MediaArchiveRecord 목록)를
**읽기 전용으로 조인**해서만 표시한다 - Production Archive를 쓰지
않고, generation_id를 Insight 스키마에 저장하지도 않는다. 존재하지
않는 identity는 `None`으로 남긴다(`media_records`를 생략하면
`generation_id`가 전부 `None` - 억지로 연결하지 않음을 확인).

## 10. Superseded

OLD(approved→published→성과)→superseded→NEW(approved→published→
성과) synthetic 구조로 검증했다(`SupersededReportTests`,
`FullEndToEndTest`): Daily Report에서 OLD/NEW가 서로 다른
content_id로 각각 집계된다(`measured_content_count=2`). Insight
계산에서도 OLD 3건/NEW 3건이 정확히 독립적으로 유지되고, OLD 성과가
NEW로 복사되지 않는다. Superseded는 삭제가 아니다 - OLD의 스냅샷과
Insight가 전부 그대로 조회 가능하다.

## 11. Generation

**6-35의 `NOT_IMPLEMENTED` 결정을 재검토했고, 조건부로만 구현했다**:

- 조건 "현재 구조에 자연스럽게 연결 가능": `MediaArchiveRecord.generation_id`를
  읽기 전용으로 조인하면 가능 → 만족.
- 조건 "legacy generation_id 없음도 처리": `media_records`를 생략하면
  `None`으로 안전하게 처리됨 → 만족.
- 조건 "content_id와 충돌 없음": 별도 필드로 표시만 하고 content_id
  기반 scope/저장 구조를 바꾸지 않음 → 만족.
- 조건 "production archive 변경 없음": 읽기만 함 → 만족.
- 조건 **"기존 schema를 깨뜨리지 않음"**: `InsightRecord`/
  `PerformanceRecord` 스키마 자체에는 `generation_id`를 **추가하지
  않았다** - 스키마를 건드리면 이 조건을 어기게 되므로.

**결론**: `scope="generation"`을 Insight의 분석 단위로 만들지는
않았다(스키마 불변 원칙 유지) - 대신 **표시(display) 레이어에서만**
`drill_down_evidence()`가 generation_id를 보여준다(9장). 이것이
"실제 구현 여부를 다시 판단"한 결과 - 전면 `NOT_IMPLEMENTED`도
전면 `IMPLEMENTED`도 아닌, **읽기 전용 조인만 `IMPLEMENTED`, 저장/분석
단위로서의 generation scope는 여전히 `NOT_IMPLEMENTED`**(6-35 근거
그대로 유지)로 정확히 구분했다.

## 12. Monetization

`classify_monetization_attribution(record)`(신규, 설계 목적)이
"어떤 데이터가 들어오면 어떻게 분류하는가"만 정의한다: `metrics`에
`"revenue"` 키가 있으면 `DIRECT`(content_id→revenue 직접 귀속),
`"attributed_revenue_estimate"` 키가 있으면 `INDIRECT`(추정값 - 실제
revenue와 절대 같은 신뢰도로 취급하지 않음), 둘 다 없으면(현재
사실상 전부) `NOT_APPLICABLE`. **실제 revenue 데이터가 없는 현재
상태에서 가짜 수익 숫자를 만들지 않았다** - 이 함수는 단지 "만약
값이 들어온다면 어떻게 분류할지"만 정의하고, 실제로 값을 계산하거나
추정하지 않는다. 신규 테스트가 추정값(INDIRECT)이 DIRECT로 잘못
분류되지 않음을 확인했다.

## 13. CLI

`scripts/performance_insight_report.py`(신규): `--daily`/`--weekly`,
`--performance`/`--insights`(둘 다 필수, 읽기 전용), `--window-start`/
`--window-end`(필수), `--platform`/`--knowledge-id`/`--content-id`
(선택 필터). 완전한 읽기 전용 - 어떤 파일도 쓰지 않는다(6-35
`analyze_performance.py`처럼 `--output`조차 없다 - 이 CLI는 순수
조회 전용이고, 새 Insight 계산이나 결정 기록은 다른 도구(6-35 CLI,
`record_decision()` Python API)의 책임이다).

## 14. Dashboard

기존 `/media`/`/media/generations`/`/publish-readiness`/`/performance`
경로를 조사했다 - 전부 `DashboardConfig`의 경로 필드로 서로 독립적
이라 충돌 위험이 없었다. 최소 화면 `/performance/insights`(신규,
`render_insight_list_html()`)를 추가했다 - `platform`/`type`/
`status`/`knowledge_id`/`content_id` 5개 쿼리 파라미터 필터를
지원한다(17장 지시한 필터 목록 그대로, "기간" 필터는 이미 CLI의
`--window-start`/`--window-end`가 담당하므로 Dashboard 화면에는
추가하지 않았다 - 대규모 UI 금지 원칙에 따라 최소한만 구현). nav에
"🔎 Insights" 링크 1개만 추가했다 - 대규모 frontend 작업은 하지
않았다.

## 15. API Boundary

Performance Provider/Insight Analyzer/Insight Store/Report Generator/
Human Review 5개 책임을 물리적으로 분리했다(3장 표): 각각
`content_engine/performance/`, `content_engine/performance_insight.py`
(분석+저장), `content_engine/insight_report.py`(리포트+결정 기록)로
나뉘어 있다. 향후 외부 API(예: Slack 알림, 외부 대시보드)를 연결할
때는 `insight_report.py`의 순수 함수(`build_daily_report()` 등)
출력을 그대로 소비하면 된다 - 이번에는 실제로 연결하지 않았다.

## 16. Idempotency

동일 Performance dataset을 두 번 분석해도 같은 `insight_id`/
`evidence`/`observation`이 나온다(6-35 설계 재확인,
`IdempotencyTests::test_same_dataset_analyzed_and_reported_twice_is_identical`).
Report 생성 자체도 순수 함수라 같은 입력에 같은 출력을 낸다
(`test_report_generation_is_pure_no_side_effects`). 중복 Insight가
저장소에 두 번 쌓이지 않는다(6-35 `append_insights()` 재사용,
`test_duplicate_insight_not_stored_twice`).

## 17. Failure Injection

| # | 시나리오 | 결과 |
|---|---|---|
| 1 | empty performance | Daily report가 0건으로 안전하게 반환(크래시 없음) |
| 2 | missing metric | 6-35에서 이미 처리(evidence에서 자동 제외) |
| 3 | invalid metric | 6-34 `quality.py`가 WARNING(재확인만) |
| 4 | duplicate snapshot | 6-34에서 이미 idempotent |
| 5 | mixed platform | Weekly report가 platform별로 분리해서 보여줌(합치지 않음) |
| 6 | mixed window | 6-35 `compare_to_baseline()`이 이미 처리 |
| 7 | missing content_id | 6-34 models.py가 이미 차단(PerformanceRecordError) |
| 8 | missing knowledge_id | 동일 |
| 9 | missing generation_id | 해당 없음(11장 - 스키마 자체에 필드가 없음, 항상 "missing"이 정상) |
| 10 | unknown content_id | `check_traceability()` → INCONSISTENT |
| 11 | superseded content | Daily report에 그대로 포함(10장 - 삭제/구분 없이 존재하는 그대로 집계) |
| 12 | insufficient sample | Daily report의 `insufficient_sample_count`로 별도 집계 |
| 13 | malformed insight | `load_insights()`가 `InsightError`로 명시적 예외 |
| 14 | duplicate insight | `append_insights()`가 조용히 건너뜀(16장) |
| 15 | invalid timestamp | 6-34 `classify_measurement_window()`가 이미 `"unknown"`으로 안전 처리 |
| 16 | security-sensitive note | 18장 - reviewer_note에 시크릿이 들어와도 report/CLI/Dashboard 어디에도 원본 그대로 노출되지 않도록 evidence 구조가 content_id/timestamp/value만 담는다(title/raw는 애초에 담지 않음, 6-35 설계 유지) |

## 18. Security

API key/OAuth token/refresh token/secret/password/email/Authorization
header가 report/CLI/Dashboard에 노출되지 않는지 3개 신규 테스트로
확인했다: (1) `PerformanceRecord.title`에 시크릿 마커를 넣고 Daily/
Weekly report 텍스트에 나타나지 않음, (2)
`scripts/performance_insight_report.py`의 실제 stdout에 나타나지
않음, (3) `render_insight_list_html()`의 HTML 출력에 나타나지 않음.
Insight의 `evidence`가 `content_id`/`metric_collected_at`/`value`만
담고(6-35 설계) `title`/`raw`/`external_id`를 포함하지 않으므로
구조적으로 안전하다 - 6-36에서 이 경계를 바꾸지 않았다.

## 19. E2E

`FullEndToEndTest::test_knowledge_through_report_to_decision_with_superseded`가
전체를 검증한다: KNOWLEDGE(`knowledge-e2e`) → OLD/NEW Generation
(각 `gen-A`/`gen-B`) → Threads 게시(OLD 이후 superseded) →
Performance(OLD 3건/NEW 3건) → Analysis(trend×2 + traceability) →
Report(Daily+Weekly) → Human Review(`record_decision`, accepted) →
Evidence Drill-down(generation_id까지 조회). 검증: identity(OLD/NEW
분리 유지), evidence(traceability가 CONSISTENT), report(daily/weekly
정상 생성), review(decision이 accepted로 기록), superseded(OLD/NEW
각 3건 독립), generation(drill-down이 media_records로 정확한
generation_id 반환), duplicate prevention(재분석 idempotent),
**production isolation**(전체 과정 전후 archive 파일 바이트 완전
동일).

## 20. Production Isolation

작업 전/후 `data/tak_media_archive.json`은 존재하지 않으므로
비교할 대상이 없다(생성하지 않았다). `IsolationTests`/`FullEndToEndTest`가
tempfile 기반으로 "리포트 생성+결정 기록 전체 과정이 Production
Archive/Threads pending/Publish History/Performance 원자료를 바이트
단위로 전혀 건드리지 않음"을 직접 증명했다(6-35와 동일한 검증
패턴 재사용).

## 21. Tests

`tests/test_6_36_performance_insight_operations.py`(신규, 46개) -
report schema, daily/weekly report, insight/status grouping, evidence
drilldown, superseded handling, generation handling, monetization
handling, human review, decision record, idempotency, failure
injection, security redaction, dashboard read-only 동작, E2E,
Production Archive isolation, operating data isolation 전부 포함.

실행 순서(지시사항 26/27장 그대로):

```
python -m unittest discover -s tests -p "test_6_36*.py" -v   # 46 OK
python -m unittest discover -s tests -p "test_performance_*.py" -v  # 67 OK(6-34 회귀)
python -m unittest discover -s tests -p "test_6_35*.py" -v   # 48 OK(6-35 회귀)
python -m unittest discover -s tests -p "test_*.py"
# Ran 1275 tests in 77.997s
# OK (skipped=17)
```

failed=0, errors=0. skip으로 문제를 숨기지 않았다(17건은 이 세션
이전부터 존재하던 조건부 skip). `git status --short`를 테스트 전/후
모두 확인했고 `data/` 아래 운영 데이터는 전혀 생성/수정되지
않았다.

## 22. October 1 Operation

```
SCOUT → KNOWLEDGE → MEDIA → HUMAN REVIEW → PROMOTION →
PRODUCTION ARCHIVE → PUBLISH → PERFORMANCE → INSIGHT → REPORT →
HUMAN REVIEW → NEXT CONTENT
```

**NEXT CONTENT는 자동 결정되지 않는다** - 사람이
`scripts/performance_insight_report.py --daily`/`--weekly`(또는
Dashboard `/performance/insights`)로 Insight Report를 읽고, 필요하면
`content_engine.insight_report.record_decision()`으로 검토 결정을
남긴 뒤, 그 정보를 참고해 다음 KNOWLEDGE/콘텐츠 방향을 사람이
직접 정한다. 10월 1일부터 실제 Performance가 쌓이면 이 구조가 그대로
연결된다 - 코드를 추가로 바꿀 필요가 없다(전부 synthetic으로 이미
검증 완료).

## 23. P1

없음 - Insight 운영 레이어의 핵심 경로(Report 생성, Human Review,
Decision Record, Evidence Drill-down)가 전부 `IMPLEMENTED`/
`VERIFIED`다. 6-30/6-31에서 이미 기록된 YouTube renderer 확보만
Performance/Insight와 무관하게 P1으로 남아있다.

## 24. P2

- Dashboard `/performance/insights`에 기간(날짜 범위) 필터 UI 추가
  (현재는 CLI에만 있음, 14장).
- Slack 등 외부 알림 채널로 Daily Report를 발송하는 통합(15장 API
  Boundary가 이미 순수 함수 출력을 제공하므로 연결만 하면 됨).

## 25. P3

- Monetization 실제 데이터 연결(12장, 각 수익원의 실제 API/대시보드
  접근이 선행되어야 함, 6-34/6-35와 동일한 결론).
- `scope="generation"`을 정식 분석 단위로 승격(11장 - 스키마 변경이
  필요해 신중한 검토 필요).

## 26. Future

- 통계적으로 더 정교한 baseline/outlier 계산(현재는 median/mean
  기반 단순 방법, 6-35 원칙 유지 - 과도한 통계 기능을 만들지 않는다).
- 여러 KNOWLEDGE/콘텐츠를 가로지르는 자동 요약(랭킹이 아닌 순수
  사실 요약이라면 향후 검토 가능, 지금은 미구현).

## 27. Conclusion

6-35의 Insight 분석 엔진을 전혀 수정하지 않고, 그 위에 운영 레이어
(`content_engine/insight_report.py`, `scripts/performance_insight_report.py`,
Dashboard `/performance/insights`)를 추가했다. Daily/Weekly Report는
새 분석을 하지 않고 이미 계산된 데이터를 정리만 하며, platform/
measurement window를 자동으로 합치지 않는다. Human Review는
CANDIDATE→REVIEWED→ACCEPTED/REJECTED로 명확히 정의했고, Decision
Record가 "언제/무엇을/왜"를 사람의 입력으로만 남긴다 - Accepted
Insight가 KNOWLEDGE/MEDIA를 자동으로 바꾸는 코드는 이번에도
만들지 않았다(코드 부재로 직접 증명). Generation 처리는 6-35의
`NOT_IMPLEMENTED` 결정을 재검토한 결과 "저장/분석 단위로는 여전히
NOT_IMPLEMENTED, 표시 레이어의 읽기 전용 조인만 IMPLEMENTED"로
정확히 구분했다 - 스키마를 깨뜨리지 않았다. 전체 1275개 테스트가
failed=0/errors=0으로 통과했고, 실제 `data/` 운영 디렉터리는
어디에서도 생성/수정되지 않았다.
