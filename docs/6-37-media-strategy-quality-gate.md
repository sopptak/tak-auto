# 6-37 Media Strategy & Quality Gate

## 1. 목적

KNOWLEDGE에서 MEDIA로 넘어가는 지점을 "콘텐츠 전략 및 품질 Gate"로
명확히 만든다. 10월 1일 실제 운영이 시작되면, 승인된 KNOWLEDGE가
들어왔다고 해서 무조건 Blog + Shorts + Threads를 생성하지 않는다 -
AI는 근거와 후보(`MediaStrategyCandidate`)만 제공하고, 사람이 최종
판단한다. 새 모듈 `content_engine/media_strategy.py`는 어떤 MEDIA도
생성하지 않고 KNOWLEDGE/Production Archive를 수정하지 않는다(쓰기
함수를 import하지 않음, 코드로 직접 증명). 실제 외부 API는 호출하지
않았고, 실제 운영 데이터는 어디에서도 생성/수정하지 않았다 - 전부
tempfile로만 검증했다.

First Sync Check: `git status --short`(clean), HEAD==origin/main
(1b5c1ff) 확인 후 시작했다.

## 2. 현재 KNOWLEDGE → MEDIA 구조

`docs/6-32-content-production-engine-hardening.md`,
`docs/6-33-october-1-operating-day-rehearsal.md`,
`docs/6-34-performance-loop-and-monetization-measurement.md`,
`docs/6-35-performance-feedback-loop.md`,
`docs/6-36-performance-insight-operations.md`를 재확인했다. 핵심
재확인 사항: `validate_knowledge()`(pending 강제),
`select_approved()`(승인만 필터), `run_media_batch()`(9개 draft),
`compute_content_id()`(원본 텍스트만 해시, generation-invariant,
6-34/6-35에서 이미 분석), `RewriteValidator`(새 사실 차단, 6-32에서
"경험" false positive 수정), `content_engine.blog_publish_pack.FINANCE_REVIEW_KEYWORDS`/
`is_review_required()`(금융/대출/경매/부동산 안전장치, 6-04/6-27).
duplicate detection은 **SCOUT 레벨(`dedupe_candidates()`, URL/제목
정규화)에만 존재하고 KNOWLEDGE/Production Archive 레벨에는 없었다** -
6-37에서 이 빈틈을 채운다(7장).

## 3. Strategy Candidate

`MediaStrategyCandidate`(신규, `content_engine/media_strategy.py`):
`knowledge_id`/`source_url`/`topic`/`category`/`domain`/`article_type`/
`platform_eligibility`(플랫폼별 독립 판정, 4장)/`risk_flags`/
`evidence_quality`/`novelty_signal`/`human_review_required`/
`reason_codes`/`status`/`content_angles`. **"추천"은 자동 발행을
의미하지 않는다** - `status=STRATEGY_READY`도 "생성 가능한 후보"일
뿐이다(15장). `evaluate_media_strategy(knowledge, production_records,
other_knowledge)`가 순수 함수로 이 candidate를 만든다 - 파일을
읽거나 쓰지 않는다(`content_engine.publish_audit`와 동일한 관례).

## 4. Platform Eligibility

`PlatformEligibility(platform, status, reason_codes)`를 Threads/
Blog/Shorts 각각 독립적으로 계산한다 - **점수를 합산해 "최고
플랫폼"을 정하지 않는다**(신규 테스트
`test_no_overall_ranking_field_exists`가 `best_platform`/`ranking`/
`overall_score` 필드가 없음을 확인). 고위험 주제처럼 콘텐츠 자체의
문제(`base_status != STRATEGY_READY`)는 세 플랫폼 모두에 동일하게
전파된다(KNOWLEDGE B 예시: Threads/Blog/Shorts 전부
`STRATEGY_REVIEW_REQUIRED`, 신규 테스트로 정확히 재현). `base_status`가
`STRATEGY_READY`일 때만 플랫폼별 추가 신호(단순 길이 휴리스틱, NLP
아님)를 독립적으로 반영한다: Threads는 evidence 1건 이상이면
충분, Blog는 설명 분량(80자 이상), Shorts는 evidence 또는 서술
분량(40자 이상) - 이 임계값은 "카드뉴스 3~5포인트로 나눌 수 있는가"
같은 실제 판단의 아주 단순한 대리 신호일 뿐이며, 향후 조정 가능한
상수로 남겨두었다.

## 5. Quality Gate

`STRATEGY_READY`/`STRATEGY_REVIEW_REQUIRED`/`STRATEGY_BLOCKED`/
`STRATEGY_INSUFFICIENT_EVIDENCE`/`STRATEGY_DUPLICATE_RISK`/
`STRATEGY_SUPERSEDED`/`STRATEGY_INVALID` - `STRATEGY_` 접두어로
`content_engine.publish_audit`의 `READY`/`BLOCKED`/`SUPERSEDED`와
이름이 겹치지 않게 했다(6장 지시). 이것은 "발행 가능 여부"가
아니라 **"MEDIA 생성 전 전략/품질 상태"**다 - Publish Readiness는
Production Archive 승격 **이후** 게시 가능 여부를 판정하고
(`publish_audit.py`), Strategy Gate는 그보다 훨씬 앞선 KNOWLEDGE
승인 직후 MEDIA 생성 여부를 판정한다. 우선순위는
`publish_audit.py`의 ERROR>ALREADY_PUBLISHED>SUPERSEDED>BLOCKED>
NEEDS_HUMAN_REVIEW>READY 패턴을 그대로 재사용했다: INVALID>BLOCKED>
SUPERSEDED>DUPLICATE_RISK>INSUFFICIENT_EVIDENCE>REVIEW_REQUIRED>READY.

## 6. Reason Codes

`SOURCE_MISSING`/`SOURCE_WEAK`/`EVIDENCE_INSUFFICIENT`/
`HIGH_RISK_TOPIC`/`DUPLICATE_RISK`/`RECENTLY_COVERED`/
`SUPERSEDED_SOURCE`/`PLATFORM_MISMATCH`/`KNOWLEDGE_NOT_APPROVED`/
`ARTICLE_TYPE_UNKNOWN`/`CATEGORY_UNKNOWN`/`DOMAIN_UNKNOWN`/
`MISSING_KNOWLEDGE_ID` - 전부 사실 기반이다(추측/평가 문구 없음).
`ARTICLE_TYPE_UNKNOWN`/`CATEGORY_UNKNOWN`/`DOMAIN_UNKNOWN`은
**정보성 코드일 뿐 그 자체로 상태를 낮추지 않는다** - 6-04에서 이미
확인했듯 SCOUT 경로 KNOWLEDGE는 `article_type=None`이 정상이기
때문이다(신규 테스트
`test_reason_codes_are_facts_not_forced_to_block`).

## 7. Duplicate / Novelty

`assess_novelty()`(신규)가 `NO_MATCH`/`POSSIBLE_DUPLICATE`/
`HIGH_DUPLICATE_RISK` 3단계로 구분한다: 같은 source_url과 같은
정규화 제목(공백/대소문자 무시, `tak_scout.collector._normalize_title()`과
동일한 원칙을 이 모듈 안에서 독립적으로 재구현 - 패키지 경계 너머
비공개 함수를 직접 import하지 않았다)이 **둘 다** 일치하면
`HIGH_DUPLICATE_RISK`(→`STRATEGY_DUPLICATE_RISK`), 하나만
일치하면 `POSSIBLE_DUPLICATE`(→사람 확인 필요,
`STRATEGY_REVIEW_REQUIRED`는 아님, `human_review_required=True`만).
**동일 source_url이라도 새로운 관점(제목이 다름)이면 자동 차단하지
않는다**(신규 테스트 `test_same_source_new_angle_is_not_auto_blocked`) -
비교 대상은 다른 KNOWLEDGE, Production Archive 둘 다 포함한다.

## 8. Superseded

OLD KNOWLEDGE→OLD MEDIA→SUPERSEDED, NEW KNOWLEDGE→NEW MEDIA
synthetic case를 검증했다(`SupersededTests`, E2E 테스트): 이
knowledge_id에서 나온 Production 레코드가 **하나 이상 있고 전부**
superseded면 `STRATEGY_SUPERSEDED`(자동으로 READY가 되지 않음).
아직 Production 레코드가 없는 신규 KNOWLEDGE는(정상적인 신규 후보)
`STRATEGY_SUPERSEDED`가 아니다 - "생성된 적 없음"과 "생성됐지만
전부 superseded됨"을 명확히 구분했다. NEW는 완전히 독립적으로
평가되고, NEW의 evidence가 OLD와 절대 섞이지 않는다.

## 9. High Risk Topic

`content_engine.blog_publish_pack.FINANCE_REVIEW_KEYWORDS`(금융/
대출/경매/부동산, 6-27에서 이미 검증됨)를 **그대로 재사용**하고,
이번 지시대로 세금/법률/투자/건강만 추가했다(`HIGH_RISK_KEYWORDS`) -
기존 금융 안전장치를 다시 만들지 않았다. **6-04/6-32 원칙을 재확인**:
category/domain이 고위험이어도 `article_type`을 임의로 바꾸지
않는다(`test_category_alone_does_not_set_article_type`) - candidate의
`article_type`은 원본 `KnowledgeRecord.article_type`을 그대로
보존한다. 6-04의 구체적 재현 사례(BBC Business RSS의 AI 기사가
"finance" category로 태깅됨)와 동일한 패턴을 이 경계에서도
재확인했다: category 자체의 안전장치(사람 확인)는 독립적으로
유지되면서도 article_type은 오염되지 않는다.

## 10. Source / Evidence

`_assess_evidence()`가 source_url 존재/형식(http/https 시작 여부),
evidence 존재를 확인한다 - 둘 다 없으면 `EVIDENCE_MISSING`, 하나만
문제면 `EVIDENCE_INSUFFICIENT`, 둘 다 정상이면 `EVIDENCE_SUFFICIENT`.
**출처가 없으면 AI가 출처를 만들어내지 않는다** -
`candidate.source_url`은 원본 KNOWLEDGE 값을 그대로 옮길 뿐, 빈
값을 다른 값으로 채우지 않는다(신규 테스트로 확인).

## 11. Content Angle

`suggest_content_angles()`(신규)가 FACT/EXPLANATION/ANALYSIS/
PRACTICAL/QUESTION/SUMMARY 중 KNOWLEDGE에 **이미 채워진 필드만
보고** 가능한 후보를 나열한다 - 실제 문장을 생성하지 않는다(라벨만
반환, 신규 테스트 `test_angles_do_not_generate_actual_text`). 한
KNOWLEDGE에 여러 angle이 동시에 가능하다(예: lesson+judgment_rule이
둘 다 있으면 EXPLANATION+ANALYSIS 모두 후보가 됨).

## 12. User Voice

이번 작업에서 user voice rewriting/automatic personalization/
metric-based style mutation을 **구현하지 않았다** - `media_strategy.py`
소스에 `rewrite`/`paraphrase` 관련 코드가 없음을 직접 확인했다
(`test_no_automatic_user_voice_rewriting`). Human Review가 최종
표현을 결정한다 - 이 모듈은 원본 텍스트를 그대로 두고 메타데이터
(status/reason_codes)만 만든다.

## 13. Generation Handoff

`build_generation_handoff(candidate, knowledge)`(신규)가 Knowledge +
Strategy Candidate + Platform Eligibility + Risk Flags + Evidence +
Human Review Requirement를 하나의 dict로 묶는다. **이 함수는 MEDIA를
생성하지 않는다** - `content_engine.generator`/`content_engine.pipeline`을
전혀 import하지 않음을 확인했다
(`test_strategy_ready_is_not_automatic_generation`). handoff의
`knowledge` 필드는 아무 변형 없이 **기존**
`content_engine.generator.generate_content_bundle()`에 그대로 넘길
수 있다(신규 테스트로 실제 호출까지 확인) - 어댑터가 필요 없을
만큼 기존 generator와 완전히 호환된다. `generation_permitted`
필드가 `status == STRATEGY_READY`일 때만 True가 되지만, 이 필드
자체도 정보 제공일 뿐 실제로 generation을 트리거하지 않는다.

## 14. Generation Policy

- `strategy READY ≠ 자동 generation`: `handoff["generation_permitted"]`가
  True여도 이 모듈은 아무것도 실행하지 않는다(신규 테스트로 확인).
- `strategy READY → generation 가능한 후보`: 사람이
  `scripts/run_media_batch.py`를 직접 실행해야 실제로 생성된다.
- `REVIEW_REQUIRED → generation 대기`: 사람이 먼저 확인해야 한다.
- `HIGH_RISK → 추가 human review`: `human_review_required=True`가
  명시적으로 표시된다.

## 15. Media Matrix

5개 이상 synthetic KNOWLEDGE로 검증했다(`content_engine/media_strategy.py`의
평가 함수 + 신규 테스트 다수):

| KNOWLEDGE | 시나리오 | status | Threads | Blog | Shorts |
|---|---|---|---|---|---|
| A | AI/Tech, 안전 | STRATEGY_READY | READY | READY(분량 충분 시) | READY |
| B | 금융(대출 금리) | STRATEGY_REVIEW_REQUIRED | REVIEW_REQUIRED | REVIEW_REQUIRED | REVIEW_REQUIRED |
| C | 부동산 | STRATEGY_REVIEW_REQUIRED(HIGH_RISK_TOPIC) | 동일하게 전파 | 동일 | 동일 |
| D | 일반 인문(짧은 본문) | STRATEGY_READY | READY(evidence만 있으면) | REVIEW_REQUIRED(분량 부족) | 분량에 따라 다름 |
| E | duplicate 가능성(같은 URL+제목) | STRATEGY_DUPLICATE_RISK | 동일하게 전파 | 동일 | 동일 |
| F | source 부족(source_url 없음) | STRATEGY_INSUFFICIENT_EVIDENCE | 동일 | 동일 | 동일 |
| G | superseded | STRATEGY_SUPERSEDED | 동일 | 동일 | 동일 |
| H | article_type 불명(None, 정상) | STRATEGY_READY(정보성 코드만) | 독립 판정 | 독립 판정 | 독립 판정 |

**"가장 좋은 플랫폼" 같은 overall ranking은 만들지 않았다** - 표의
각 셀은 독립적으로 계산된 결과다.

## 16. CLI

`scripts/audit_media_strategy.py`(신규): `--knowledge-id`/
`--platform`/`--status`/`--all`/`--json` 옵션. 기본값은 승인된
KNOWLEDGE만 평가한다(`--all`로 전체 평가 가능). 완전한 읽기 전용 -
`content_engine.pipeline`/`content_engine.media_archive`의 쓰기
함수를 import하지 않는다. 신규 테스트가 어떤 파일도 생성하지 않음을
직접 확인했다(`test_cli_does_not_write_any_file`).

## 17. Dashboard

기존 `/media`/`/media/generations`/`/publish-readiness`/
`/performance`/`/performance/insights` 경로를 조사했다 - 전부
`DashboardConfig`의 독립 경로 필드라 충돌 위험이 없었다. 최소 화면
`/media/strategy`(신규, `render_media_strategy_list_html()`)를
추가했다 - `status`/`knowledge_id` 쿼리 필터를 지원한다. **이
화면에는 어떤 form/버튼도 없다** - generate/approve/promote/publish로
이어지는 액션이 전혀 없음을 신규 테스트 2개로 확인했다(HTML에
`<form>` 없음, `do_POST`에 `/media/strategy` 라우트 없음).

## 18. Idempotency

같은 KNOWLEDGE를 같은 환경에서 10번 평가해도 완전히 동일한
`MediaStrategyCandidate`가 나온다(`test_same_knowledge_evaluated_ten_times_is_identical`) -
시간/randomness를 사용하는 코드가 이 모듈에 없다(순수 함수).

## 19. Security

API_KEY/REFRESH_TOKEN/Authorization 형태의 synthetic secret을
evidence/note에 넣고 CLI/candidate 출력/Dashboard HTML 어디에도
노출되지 않는지 3개 신규 테스트로 확인했다. `MediaStrategyCandidate`가
evidence 원문을 복사하지 않고(존재 여부/형식만 판정) reason_code만
담으므로 구조적으로 안전하다.

## 20. Failure Injection

20개 시나리오를 검증했다(`FailureInjectionTests`): missing/pending/
dismissed knowledge → BLOCKED, missing/invalid source → 
INSUFFICIENT_EVIDENCE(SOURCE_MISSING/SOURCE_WEAK), missing evidence →
INSUFFICIENT_EVIDENCE, unknown category/domain/article_type →
READY 유지(정보성 코드만), duplicate source+title → DUPLICATE_RISK,
superseded → SUPERSEDED, high-risk topic → REVIEW_REQUIRED, secret-like
text → 크래시 없음(19장과 연결), empty input(CLI) → 크래시 없이 정상
종료. `MediaArchiveRecord` 자체가 content_id를 필수로 요구하므로
"missing content_id"는 더 상위 레이어(`media_archive.py`)에서 이미
막힘을 직접 확인했다(media_strategy가 별도 방어할 필요 없음).

## 21. E2E

`FullEndToEndTest`가 SCOUT(synthetic 후보 대신 직접 KNOWLEDGE로
시작)→KNOWLEDGE APPROVAL→MEDIA STRATEGY→PLATFORM ELIGIBILITY→
(Human Review는 status/human_review_required로 표시)→MEDIA GENERATION
CANDIDATE(handoff)까지 검증한다: OLD(superseded)→SUPERSEDED 유지,
NEW→독립적으로 STRATEGY_READY, handoff의
`generation_permitted=True`. 실제 generation/publish는 수행하지
않았다. 전체 과정 전후 Production Archive 파일 바이트가 완전히
동일함을 확인했다.

## 22. Production Isolation

작업 전/후 `data/tak_media_archive.json`,
`data/tak_brain_knowledge.json`, `data/tak_threads_pending.json`,
`data/tak_performance.json`은 이 저장소에 아직 존재하지 않으므로
비교 대상이 없다(생성하지 않았다). `ProductionIsolationTests`가
tempfile 기반으로 "KNOWLEDGE 전체 평가 과정이 KNOWLEDGE 파일/
Production Archive 파일을 바이트 단위로 전혀 건드리지 않음"을 직접
증명했다.

## 23. Tests

`tests/test_6_37_media_strategy_gate.py`(신규, 68개) - strategy
schema, platform eligibility, reason codes, evidence, source,
duplicate, novelty, superseded, high-risk, article_type separation,
human review, generation handoff, idempotency, failure injection,
security, CLI, dashboard, E2E, production isolation 전부 포함.

```
python -m unittest discover -s tests -p "test_6_37*.py" -v   # 68 OK
python -m unittest discover -s tests -p "test_6_32*.py"      # 21 OK(회귀)
python -m unittest discover -s tests -p "test_6_33*.py"      # 25 OK(회귀)
python -m unittest discover -s tests -p "test_performance_*.py"  # 67 OK(회귀)
python -m unittest discover -s tests -p "test_6_35*.py"      # 48 OK(회귀)
python -m unittest discover -s tests -p "test_6_36*.py"      # 46 OK(회귀)
python -m unittest discover -s tests -p "test_*.py"
# Ran 1343 tests in 78.008s
# OK (skipped=17)
```

failed=0, errors=0. skip으로 문제를 숨기지 않았다.
`git status --short`를 테스트 전/후 모두 확인했고 `data/` 아래
운영 데이터는 전혀 생성/수정되지 않았다.

## 24. October 1 Operation

```
SCOUT → KNOWLEDGE → KNOWLEDGE APPROVAL → MEDIA STRATEGY GATE →
HUMAN REVIEW → MEDIA GENERATION → GENERATION REVIEW → PROMOTION →
PRODUCTION ARCHIVE → PUBLISH → PERFORMANCE → INSIGHT → REPORT →
HUMAN DECISION
```

AI가 사람의 최종 콘텐츠 전략을 대신하지 않는다 - Strategy Gate는
근거(`reason_codes`/`risk_flags`/`platform_eligibility`)만 제공하고,
`scripts/audit_media_strategy.py` 또는 Dashboard `/media/strategy`로
사람이 확인한 뒤 `scripts/run_media_batch.py`를 직접 실행해야 MEDIA가
만들어진다.

**October 1 Operator Checklist**(추가):

```
[ ] GitHub/Codespaces 사용 가능
[ ] HEAD == origin/main
[ ] working tree clean
[ ] Python environment READY
[ ] tests PASS (python -m unittest discover -s tests -p "test_*.py")
[ ] SCOUT READY
[ ] KNOWLEDGE READY
[ ] MEDIA STRATEGY GATE READY (python scripts/audit_media_strategy.py)
[ ] MEDIA READY
[ ] HUMAN REVIEW READY
[ ] PROMOTION READY
[ ] PRODUCTION ARCHIVE READY
[ ] Threads dependency 확인(THREADS_ACCESS_TOKEN)
[ ] YouTube dependency 확인(renderer 여전히 BLOCKED, 6-30/6-31)
[ ] Naver manual workflow 확인(Publish Pack + 수동 게시)
[ ] Performance READY
[ ] Insight READY
[ ] Dashboard READY(/media/strategy, /performance/insights 포함)
[ ] Secrets 확인(값 출력 없이 존재 여부만)
[ ] 실제 운영 API는 human approval 후 실행
```

## 25. P1

없음 - Strategy Gate의 핵심 경로(평가/CLI/Dashboard/E2E)가 전부
`IMPLEMENTED`/`VERIFIED`다. 6-30/6-31에서 이미 기록된 YouTube
renderer 확보만 이 작업과 무관하게 P1으로 남아있다.

## 26. P2

- Platform eligibility의 분량 휴리스틱(80자/40자 임계값)을 실제
  운영 데이터가 쌓인 뒤 재조정 검토.
- Dashboard `/media/strategy`에 카테고리/도메인 필터 추가(현재는
  status/knowledge_id만).

## 27. P3

- 더 정교한 novelty 판정(현재는 정규화 제목/URL 정확 일치만, 의미
  기반 유사도는 LLM 없는 원칙상 보류).
- Strategy Candidate와 Insight(6-35/6-36)를 연결해 "이 전략 판단이
  실제 성과와 어떻게 연결되는지" 추적하는 기능(향후 검토).

## 28. Future

- Content Angle을 실제 프롬프트 생성 시 참고 정보로 자동 전달하는
  통합(현재는 후보 나열만, 실제 LLM 프롬프트 연결은 미구현).
- 여러 KNOWLEDGE의 Strategy 상태를 가로지르는 일일/주간 요약
  (6-36의 Insight Report와 유사한 패턴을 Strategy Gate에도 적용
  가능, 지금은 미구현).
