# 6-38 Operator Control Center

## 1. 목적

6-24~6-37까지 구축된 TAK AUTO의 각 상태(SCOUT/KNOWLEDGE/MEDIA/HUMAN
REVIEW/PROMOTION/PRODUCTION ARCHIVE/PUBLISH/PERFORMANCE/INSIGHT)를
10월 1일 실제 운영자가 한 화면에서 확인할 수 있도록 통합한다. 새로운
독립 기능을 많이 만드는 것이 목적이 아니다 - 새 모듈
`content_engine/operator_summary.py`는 6-14/6-17/6-19(publish_audit),
6-21(data_state), 6-26(YouTube eligibility), 6-33
(show_operating_status의 패턴), 6-37(media_strategy),
6-35/6-36(performance_insight/insight_report)이 이미 계산한 상태를
**재사용/집계만** 한다 - 새로운 상태 체계를 불필요하게 만들지
않았다. 실제 외부 API는 호출하지 않았고, 실제 운영 데이터는 어디에서도
생성/수정하지 않았다.

First Sync Check: `git status --short`(clean), HEAD==origin/main
(fd87cd2) 확인 후 시작했다.

## 2. Operator Center 범위

개발자용 Admin Console이 아니다 - "오늘 운영자가 무엇을 확인하고
무엇을 해야 하는가"만 답한다. 첫 화면을 8개 영역으로 제한했다:
TODAY STATUS/PIPELINE STATUS/HUMAN ACTION/BLOCKED·RISK/PUBLISH
STATUS/DATA HEALTH/PERFORMANCE·INSIGHT/NEXT ACTION. **Operator
Center 자체는 완전히 READ-ONLY다** - approve/dismiss/promote/
publish/delete/restore/repair/regenerate 중 어떤 것도 실행하지
않는다(16장, 코드 부재로 직접 증명).

## 3. TODAY STATUS

`_build_git_status()`가 HEAD/origin/main 일치 여부(SYNCED/
OUT_OF_SYNC)와 working tree clean 여부(DIRTY)를 보여준다.
`_build_test_status()`는 **이 모듈이 테스트를 직접 실행하지 않는다** -
호출부(`--test-status` CLI 인자)가 최근 실행 결과를 명시적으로
넘겨야 하고, 생략하면 `UNKNOWN`으로 정직하게 표시한다(4장 지시 "실제
상태를 임의로 만들지 않는다"). 외부 의존성 상태는 6장/7장의 Human
Action/Blocked 목록과 동일한 데이터를 재사용한다(중복 판정 로직
없음).

## 4. PIPELINE

`build_pipeline()`이 SCOUT→KNOWLEDGE→MEDIA→HUMAN REVIEW→PROMOTION→
PRODUCTION ARCHIVE→PUBLISH→PERFORMANCE→INSIGHT 9단계를 항상 이
순서로 반환한다(신규 테스트로 순서 고정). 각 단계는 기존 함수를
그대로 재사용한다:

| 단계 | 재사용한 기존 함수/데이터 |
|---|---|
| SCOUT | `tak_scout.collector.load_daily_pack()`(6-33 패턴) |
| KNOWLEDGE | `tak_brain`의 `knowledge_review_status` 필터(기존 스키마) |
| MEDIA | Generation Pool 레코드 카운트(6-06/6-07/6-33 패턴) |
| HUMAN REVIEW | `review_status == "unreviewed"` 카운트(기존 필드) |
| PROMOTION | `(content_id, generation_id)`가 Production Archive에 아직 없는 approved+valid 레코드(6-06/6-18 overwrite protection과 동일한 키 사용) |
| PRODUCTION ARCHIVE | `content_engine.data_state.json_file_status()`(6-21, NOT_PRESENT/EMPTY/VALID/CORRUPTED) |
| PUBLISH | `content_engine.publish_audit.audit_archive()`(6-14/6-17/6-19, 새 판정 로직 없음) |
| PERFORMANCE | `content_engine.performance.store.load_snapshots()`(6-34) |
| INSIGHT | `content_engine.insight_report.review_priority()`(6-36) |

실제 데이터가 없으면(`NOT_PRESENT`) **자동으로 READY로 표시하지
않는다** - 신규 테스트(`test_scout_not_present_when_no_daily_pack`,
`test_scenario_f_production_archive_not_present`)가 이를 직접
확인한다.

## 5. HUMAN ACTION

`build_human_actions()`가 AI가 자동으로 해결할 수 없는 작업만
모은다: KNOWLEDGE REVIEW(pending 존재), MEDIA REVIEW(unreviewed
generation 존재), PROMOTION APPROVAL(승격 대기), THREADS PUBLISH
(pending draft 존재), YOUTUBE OAUTH(renderer 없음 또는 OAuth
env var 없음), NAVER MANUAL PUBLISH(승인된 Blog 후보 존재). **자동
실행 버튼은 없다** - `action` 필드는 CLI 명령 안내 문자열일 뿐이며,
이 문자열을 실행하는 코드가 어디에도 없다(신규 테스트
`test_no_automatic_execution_buttons_in_action`).

## 6. BLOCKED/RISK

`build_blocked_items()`가 **실제로 막혀 있는 것만** 표시한다 -
경고를 과도하게 만들지 않는다(신규 테스트
`test_not_excessive_warnings_only_actionable_items`가 safe한
KNOWLEDGE는 빈 목록을 반환함을 확인). YouTube는 renderer가 없는 한
항상 `BLOCKED`(6-30 사실 재사용), KNOWLEDGE는
`content_engine.media_strategy.evaluate_media_strategy()`(6-37)의
결과가 `STRATEGY_READY`/`STRATEGY_BLOCKED`가 아닌 경우(예:
`STRATEGY_DUPLICATE_RISK`, `STRATEGY_REVIEW_REQUIRED`)만 표시한다.

## 7. PUBLISH

`build_publish_status()`가 Threads/Blog/YouTube Shorts를 완전히
독립적으로 보여준다 - `content_engine.publish_audit.audit_archive()`
(기존, 새 판정 로직 없음)의 결과를 플랫폼별로 묶어 우선순위
(ERROR>ALREADY_PUBLISHED>SUPERSEDED>BLOCKED>NEEDS_HUMAN_REVIEW>
READY, 6-14/6-17/6-19 그대로)로 대표 상태 하나만 뽑는다.
**"가장 좋은 플랫폼" 판단을 하지 않는다** - 신규 테스트
(`test_no_ranking_field`)가 `rank`/`best` 필드가 없음을 확인한다.

## 8. DATA HEALTH

`build_data_health()`가 Production Archive/Generation Pool/
KNOWLEDGE/Threads Pending/Shorts Scripts/Blog Drafts/Performance/
Insight 8개 대상을 `content_engine.data_state`(6-21)의 NOT_PRESENT/
EMPTY/VALID/CORRUPTED 상태 그대로 표시한다 - 새 상태 이름을 만들지
않았다. **파일이 없다고 자동 생성하지 않는다** - 신규 테스트
(`test_does_not_auto_generate_missing_production_archive`)가 이를
직접 확인한다.

## 9. PERFORMANCE

`build_performance_summary()`가 6-34의 `PerformanceRecord`를 그대로
읽어 상태(NOT_PRESENT/VALID)와 건수, 사용 가능한 플랫폼 목록을
보여준다. **실제 revenue 데이터가 없으면 0원이라고 임의 표시하지
않는다** - 신규 테스트(`test_no_fake_revenue_shown`)가 통화 기호/
"원"이 출력에 없음을 확인한다(6-34/6-35의 monetization 결론을
그대로 따름).

## 10. INSIGHT

`build_insight_summary()`가 6-35/6-36의 `InsightRecord`/
`review_priority()`를 재사용해 new/review_required/decision_required
건수를 보여준다. **6-38 개발 중 발견한 내부 일관성 버그를
수정했다**: 이 함수가 처음에는 review가 필요한 상황에서도 항상
`VALID`를 반환했다(파이프라인용 `_build_insight_stage()`는 이미
`NEEDS_HUMAN_REVIEW`를 정확히 반환하고 있었는데, `summary.insights`
필드용 함수만 그 규칙을 빠뜨렸다) - 신규 테스트
(`test_scenario_m_insight_review_required`)가 이 버그를 실제로
잡아냈고, 두 함수가 같은 규칙을 공유하도록 수정했다(재발 방지를
위해 수정 이유를 코드 주석에도 남겼다).

## 11. NEXT ACTION

`build_next_actions()`가 human_actions/blocked_items에 이미 나열된
순서(코드 작성 순서 자체가 우선순위)를 그대로 따라 최대 3개만
반환한다 - **새 점수 시스템을 만들지 않았다**(신규 테스트
`test_no_numeric_priority_score_field`). AI가 운영자의 의사결정을
대신하지 않는다 - "다음에 뭘 봐야 하는지"만 안내한다.

## 12. STATUS-WHY-ACTION

`StatusWhyAction(label, status, why, action, count, detail_route)`을
모든 주요 상태가 공유한다(pipeline/human_actions/blocked_items/
publish_status/data_health/performance/insights 전부 이 하나의
구조를 쓴다) - 기존 코드와 충돌하지 않는 새 공통 helper를 1개만
만들었다(12장 지시 그대로). `detail_route`가 클릭 시 이동할 기존
상세 화면 경로를 담는다(15장).

## 13. UI

기존 `run_scout_dashboard.py` 구조(stdlib `http.server`만 사용, 새
프레임워크 도입 없음)에 `/operator`(신규)를 추가했다 - 기존
`/media`/`/media/strategy`/`/publish-readiness`/`/performance`/
`/performance/insights`와 독립적인 경로다. `render_operator_center_html()`가
기존 `.card` CSS 클래스만 재사용해 카드 레이아웃으로 8개 영역을
위→아래 순서(TODAY→PIPELINE→HUMAN ACTION→BLOCKED/RISK→PUBLISH→
DATA HEALTH→PERFORMANCE/INSIGHT→NEXT ACTION)로 렌더링한다 - 모바일
가로폭에서도 카드가 세로로 쌓이므로 별도 반응형 CSS를 추가하지
않았다(기존 Dashboard 전체가 이미 이 원칙을 따름).

## 14. Detail Navigation

`detail_route` 필드가 `/`, `/media/generations`, `/media/strategy`,
`/publish-readiness`, `/performance`, `/performance/insights`,
`/threads`로 연결한다 - **새 상세 화면을 만들지 않았다**, 전부
6-25~6-37에서 이미 만들어진 기존 화면이다.

## 15. Read-only Policy

`/operator`에는 `<form>` 태그가 전혀 없다(신규 테스트
`test_no_form_tags_in_operator_html`). approve/dismiss/promote/
publish/delete/restore/repair/regenerate 관련 문구가 렌더링된
HTML에 없음을 확인했다(`test_no_forbidden_action_words_in_html`).
`do_POST`에 `/operator` 라우트가 없음을 소스 검사로 확인했다
(`test_no_post_route_for_operator_path`). `content_engine/operator_summary.py`
소스에 `upsert_archive`/`save_archive`/`set_review_status`/
`upsert_pending`/`append_snapshot`/`record_decision` 등 쓰기 함수
호출이 전혀 없음을 확인했다.

## 16. Filters

CLI(`--status`는 이번에 구현하지 않았다 - Operator Center 자체는
집계 결과이므로, 세부 필터는 각 상세 화면(`/media`, `/media/strategy`
등, 이미 6-33/6-37에서 필터를 지원함)에서 하도록 책임을 분리했다)는
`--json` 출력 전체를 제공하고, 필요하면 `jq` 등으로 사후 필터링할
수 있다 - **불필요한 중복 필터 UI를 만들지 않았다**(P2로 분류,
27장).

## 17. Refresh

Operator Center는 자동 polling을 하지 않는다 - `/operator`를 새로고침
(manual refresh)하면 최신 상태를 다시 계산한다(파일을 매번 다시
읽는 stateless 설계, 캐시 없음). 자동 polling은 `FUTURE`로 남겼다
(30장).

## 18. Security

API key/refresh token/access token/Authorization header/.env
secret/credential 값이 `/operator` HTML, CLI 텍스트/JSON 출력, 로그
어디에도 노출되지 않는지 3개 신규 테스트로 확인했다: (1)
`KnowledgeRecord.evidence`에 시크릿 마커를 넣고 `OperatorSummary.to_dict()`
JSON 직렬화 결과에 없음을 확인, (2) CLI 텍스트 출력에 없음을 확인,
(3) `operator_control_center.py` 소스에 `os.environ`의 값을 직접
출력하는 코드가 없음을 확인(존재 여부만 `bool()`로 확인, 6-26
`youtube_oauth_setup.py`와 동일한 원칙 재사용).

## 19. Multi-PC

6-21의 멀티 PC 정책을 그대로 유지했다 - Operator Center가 "현재
PC에서 보이지 않는 운영 데이터"를 자동으로 생성하거나 복구하지
않는다(신규 테스트
`test_does_not_auto_generate_missing_production_archive`). Git
HEAD/origin/main/working tree 상태를 TODAY STATUS에 명확히
표시한다(`_build_git_status()`) - `OUT_OF_SYNC`면 `SYSTEM_NEEDS_REVIEW`로
전체 시스템 상태를 끌어올린다(13장).

## 20. Synthetic Fixture

실제 운영 데이터를 생성하지 않고 `tempfile` + 순수 값(`OperatorInputs`)
기반 synthetic fixture로 13개 시나리오(A~M)를 전부 검증했다
(`SyntheticScenariosTests`): all READY(A), Human Action 존재(B),
Blocked 존재(C), External Dependency 존재(D), Production Archive
NOT_PRESENT(F)/VALID(G), Superseded content(H), YouTube BLOCKED(I),
Naver HUMAN_ACTION(J), Threads READY(K), Performance NOT_PRESENT(L),
Insight REVIEW_REQUIRED(M) - M은 10장에서 설명한 실제 버그를
발견했다.

## 21. OperatorSummary

```
OperatorSummary:
    system_status: str
    generated_at: str
    git_status: StatusWhyAction
    test_status: StatusWhyAction
    pipeline: tuple[StatusWhyAction, ...]
    human_actions: tuple[StatusWhyAction, ...]
    blocked_items: tuple[StatusWhyAction, ...]
    publish_status: tuple[StatusWhyAction, ...]
    data_health: tuple[StatusWhyAction, ...]
    performance: StatusWhyAction
    insights: StatusWhyAction
    next_actions: tuple[str, ...]
```

`OperatorInputs`(별도 dataclass)가 모든 미리 로드된 데이터를
묶는다 - `content_engine.publish_audit.PublishAuditInputs`와 동일한
관례(호출부가 파일을 미리 읽어 넘김, 이 모듈은 파일을 읽지 않음).
`to_dict()`가 JSON 직렬화 가능함을 신규 테스트로 확인했다.

## 22. Idempotency

같은 synthetic `OperatorInputs`를 10번 읽어 `build_operator_summary()`를
호출해도 완전히 동일한 `OperatorSummary`가 나온다
(`test_same_synthetic_data_read_ten_times_identical`) - 시간/
randomness를 쓰는 코드가 이 모듈에 없다(순수 함수, `generated_at`도
입력으로 받을 뿐 내부에서 계산하지 않음).

## 23. Failure Injection

missing/empty/corrupted 데이터, missing/pending/rejected knowledge,
missing source, evidence insufficient, duplicate risk, superseded
content, YouTube/Threads blocked, Blog human action, Performance/
Insight missing, Git mismatch, secret-like input, unexpected
exception(빈 파이프라인 포함)을 `MissingCorruptedDataTests`/
`SecurityTests`/`MultiPcTests`/`SyntheticScenariosTests`에서 검증했다 -
어떤 경우에도 민감정보를 출력하지 않았고, `CORRUPTED` 상태도
크래시 없이 그대로 표시했다.

## 24. E2E

`FullEndToEndTest`가 SCOUT(1건)→KNOWLEDGE(승인)→MEDIA STRATEGY(암묵적,
Blocked 목록에 반영)→MEDIA(generation pool 1건)→HUMAN REVIEW→
PROMOTION→PRODUCTION(1건)→PUBLISH→PERFORMANCE(1건)→INSIGHT까지
하나의 synthetic 흐름이 `OperatorSummary`에 정확히 반영되는지
확인한다 - SCOUT 카운트, Production Archive 카운트, Performance
카운트, YouTube BLOCKED 항목까지 전부 검증했고, 실제 HTML 렌더링도
확인했다. 실제 외부 API는 호출하지 않았다.

## 25. Tests

`tests/test_6_38_operator_control_center.py`(신규, 68개) -
OperatorSummary, pipeline aggregation, human actions, blocked/risk,
publish status, data health, performance, insight, next actions,
status/why/action, CLI, read-only, security, multi-PC, missing/
corrupted data, idempotency, synthetic 시나리오 A~M, E2E, dashboard
route, JSON output 전부 포함.

```
python -m unittest discover -s tests -p "test_6_38*.py" -v   # 68 OK
python -m unittest discover -s tests -p "test_6_37*.py" -v   # 68 OK(회귀)
python -m unittest discover -s tests -p "test_6_36*.py"      # 46 OK(회귀)
python -m unittest discover -s tests -p "test_6_35*.py"      # 48 OK(회귀)
python -m unittest discover -s tests -p "test_performance_*.py"  # 67 OK(회귀)
python -m unittest discover -s tests -p "test_6_33*.py"      # 25 OK(회귀)
python -m unittest discover -s tests -p "test_6_32*.py"      # 21 OK(회귀)
python -m unittest discover -s tests -p "test_*.py"
# Ran 1411 tests in 79.600s
# OK (skipped=17)
```

failed=0, errors=0. skip으로 문제를 숨기지 않았다. `git status --short`를
테스트 전/후 모두 확인했고 `data/` 아래 운영 데이터는 전혀
생성/수정되지 않았다.

## 26. October 1 Operation

**October 1 Operator View(synthetic example, 실제 운영 데이터
아님)**:

```
TAK AUTO - October 1 (SYNTHETIC EXAMPLE)

SYSTEM: READY_WITH_HUMAN_STEP

PIPELINE
  SCOUT               READY (5건)
  KNOWLEDGE           NEEDS_HUMAN_REVIEW (3건)
  MEDIA               READY (9건)
  HUMAN REVIEW        WAITING (4건)
  PROMOTION           READY (2건)
  PRODUCTION ARCHIVE  VALID (12건)
  PUBLISH             ACTION_REQUIRED (3건)
  PERFORMANCE         VALID (8건)
  INSIGHT             NEEDS_HUMAN_REVIEW (2건)

HUMAN ACTION
  1. KNOWLEDGE REVIEW (3건)
  2. MEDIA REVIEW (4건)
  3. YOUTUBE OAUTH

BLOCKED / RISK
  YouTube: BLOCKED (Shorts Renderer 없음)

PUBLISH STATUS
  Threads: READY
  Blog: NEEDS_HUMAN_REVIEW
  YouTube Shorts: BLOCKED

DATA HEALTH
  Production Archive: VALID
  Performance: VALID

NEXT ACTION
  1. KNOWLEDGE REVIEW
  2. MEDIA REVIEW
  3. YOUTUBE OAUTH
```

이것은 **synthetic 예시일 뿐이다** - 실제 운영 데이터로 오인하지
않는다. 10월 1일 실제 운영자는 `python scripts/operator_control_center.py`
또는 Dashboard `/operator`로 이 화면을 실제 데이터 기준으로 그대로
확인할 수 있다.

**October 1 Checklist**:

```
[ ] GitHub/Codespaces available
[ ] HEAD == origin/main
[ ] working tree clean
[ ] Python READY
[ ] Full tests PASS (python -m unittest discover -s tests -p "test_*.py")
[ ] SCOUT READY
[ ] KNOWLEDGE READY
[ ] MEDIA READY
[ ] HUMAN REVIEW READY
[ ] PROMOTION READY
[ ] PRODUCTION ARCHIVE 상태 확인
[ ] Threads dependency 확인(THREADS_ACCESS_TOKEN 존재 여부만)
[ ] YouTube dependency 확인(renderer 여전히 BLOCKED, 6-30/6-31)
[ ] Naver manual workflow 확인
[ ] Performance READY
[ ] Insight READY
[ ] Operator Center READY (python scripts/operator_control_center.py 또는 Dashboard /operator)
[ ] Secrets 확인(값 출력 없이 존재 여부만)
[ ] 실제 API 실행 전 human confirmation
```

## 27. P1

없음 - Operator Center의 핵심 경로(집계/CLI/Dashboard/E2E)가 전부
`IMPLEMENTED`/`VERIFIED`다. 6-30/6-31에서 이미 기록된 YouTube
renderer 확보만 이 작업과 무관하게 P1으로 남아있다.

## 28. P2

- `/operator`에 status/platform 필터 UI 추가(현재는 상세 화면에서만
  필터 가능, 16장).
- `--test-status`를 CI 결과와 자동 연동(현재는 사람이 수동으로
  전달).

## 29. P3

- 자동 polling(17장, 현재는 manual refresh만).
- 여러 세션/PC의 Operator Center 상태를 비교하는 기능.

## 30. Future

- 자동 게시/자동 의사결정/자동 복구/자동 콘텐츠 전략 결정: 이번에도,
  앞으로도 Operator Center의 책임이 아니다 - 이 모듈은 "보여주기"만
  한다.
- 실시간 analytics(현재는 파일 스냅샷 기반 정적 집계).
- Revenue automation(6-34/6-35/6-36이 이미 결론 내린 대로, 실제
  revenue 데이터 연결이 선행되어야 함).
