# TAK AUTO 현재 상태

기준: GitHub `main` HEAD `8d84672651c25c5c54af19c6e8b289a2f0043b55` (2026-10-01).
이 문서는 코드를 변경하지 않고 GitHub의 코드, 추적 데이터, 주요 작업 문서를 대조해 작성했다.
이 확인은 원격 HEAD와 같은 별도 worktree에서 했다. 기존 `/workspaces/tak-auto`의
local `main`은 `b5afc71`이며 90개 미커밋 변경이 남아 있다. 해당 변경은 이 보고서의
Source of Truth에 섞지 않았고 전혀 수정하지 않았다.

## 1. 프로젝트 최초 목표

최초 파일럿은 네이버 블로그 원문을 RAW로 안전하게 보존하고, 근거가 있는 KNOWLEDGE로 분리하는 것이었다([README.md](../README.md), [KNOWLEDGE 추출 설계](knowledge_extraction_design.md)).
후속 SCOUT/INTERVIEW 설계가 이를 공개 이슈 발견과 사람의 의견 수집으로 확장했다([SCOUT + INTERVIEW MVP](5-5_tak_scout_interview_mvp.md)). 현재 운영 목표는 사용자가 지정한 다음의 최소 E2E로 고정한다.

```text
AI 이슈 Scout
→ 글감 1개 선정 및 사람의 관점 수집
→ 승인 KNOWLEDGE
→ 근거·안전 검증을 거친 콘텐츠 생성
→ 사람 검수·승인
→ 실제 외부 채널 게시
→ 게시 ID와 content_id 연결
→ 실제 트래픽/성과 스냅샷 수집
→ Insight를 사람이 검토
→ 다음 콘텐츠 전략에 반영
```

성과가 좋다는 이유만으로 AI가 KNOWLEDGE, 사용자 의견, 게시 여부를 자동 변경하는 것은 현재 원칙이 아니다.

## 2. 현재 전체 구조

```text
공개 RSS → SCOUT 수집·점수화 → 사람이 인터뷰/선택 → KNOWLEDGE pending
  → 사람이 승인 → MEDIA strategy 점검 → MEDIA 생성(9개/KNOWLEDGE)
  → generation pool → 사람이 수정·승인 → 명시적 promotion
  → Production Archive → Publish Readiness
  → Threads / YouTube Shorts / Blog
  → 채널별 publish history → Performance snapshot
  → Insight / 사람의 결정 → 다음 콘텐츠
```

- `tak_scout/`, `tak_brain/`, `content_engine/`, `scripts/`, `operator/`, `data/`, `tests/`가 콘텐츠공장 코드와 운영 데이터의 주요 경계다.
- GitHub `main`에는 **89개 Markdown 문서**가 있다. 번호순으로 초기 SCOUT/품질/게시 문서, 5-29~5-31 운영 자동화, 6-01~6-62 운영·채널·MONEY, 6-63~6-69 PROJECT 2030 게임 기록(경계 참고), 6-71 되돌림 기록 및 공통 설계 문서를 검토했다. 최신 게임 작업 6-70은 되돌렸고 `main`에는 없다.
- README는 여전히 최초 네이버 RAW import 파일럿을 현재 프로젝트처럼 소개한다. 실제 확장된 운영 구조와 제약은 dated docs와 현재 코드가 더 정확히 설명한다.
- 본문에는 과거 세션의 환경별 상태와 현재 GitHub 상태를 구분해 기록한다. 특히 6-45/6-46의 fresh clone, 6-48 export staging, 6-50의 2건 적용은 서로 다른 시점/환경이다.

## 3. SCOUT 상태

- 구현: 공개 RSS 수집, URL/정규화 제목 기준 실행 내 dedup, 규칙 기반 A~E 점수, 후보 출력. `scripts/run_scout.py`가 진입점이며 `.github/workflows/daily-scout.yml`은 KST 08:00 schedule 및 수동 dispatch로 SCOUT만 실행하고 결과 JSON/Markdown만 갱신한다. 인터뷰, MEDIA, 발행은 호출하지 않는다.
- 흐름: `data/scout_sources.json` → `tak_scout/collector.py`/`rss.py`/`scoring.py` → `data/tak_scout_daily.json`/`.md` → `run_interview.py`에서 사람이 후보를 선택하고 A/B/C/D로 답한다.
- 코드와 docs는 SCOUT RSS category와 본문 기반 `article_type`을 별도 축으로 유지한다. RSS 소스 분류를 finance 템플릿 분류로 승격해 오염시킨 과거 문제는 6-04/6-15/6-32에서 다뤄졌고 회귀 검증이 있다.
- 현재 GitHub 데이터: source 설정 1개, 추적된 SCOUT snapshot 5개 후보, 생성 시각 `2026-09-19T03:36:16Z`. 이는 현재 시각(10월 1일)의 새 실행 결과가 아니라 마지막 커밋된 snapshot이다. schedule 설정은 실행 코드를 뜻하며 최근 성공 run을 증명하지 않는다.
- cross-run 의미 기반 dedup은 없다. 같은 실행의 URL/제목 dedup과 KNOWLEDGE의 `source_raw_id` 중복 방지가 서로 다른 단계에서 동작한다.

## 4. KNOWLEDGE 상태

- SCOUT 후보는 `run_interview.py`/`apply_interview.py`에서 사람 답변을 거쳐 `pending` KNOWLEDGE가 된다. `review_knowledge.py`가 승인·거절을 기록한다. 신규 KNOWLEDGE 자동 승인은 없고 `select_approved()`만 후속 MEDIA 입력을 고른다.
- RAW/evidence/source와 사용자의 의견을 분리해 기록하고, 부족한 근거는 추측으로 채우지 않는 원칙은 [지식 추출 설계](knowledge_extraction_design.md) 및 [6-32 hardening](6-32-content-production-engine-hardening.md)에 있다.
- 현재 GitHub `data/tak_brain_knowledge.json`: **28건**, `approved 6 / pending 13 / rejected 9`. 사람의 다음 행동으로는 pending 13건 검토가 남아 있다.
- `verification_required`/`current_validity` 같은 표시는 검토에 도움을 주지만 사실 확인이나 승인 자체를 대신하지 않는다.

## 5. MEDIA 상태

- `content_engine.generator.generate_content_bundle()`은 KNOWLEDGE 1건당 Blog 1 + Shorts 3 + Threads 5, 총 9개 draft를 만든다. `content_engine.pipeline.run_media_batch()`가 재작성·검증하고 valid/rejected/error 및 생성 시각을 보존한다. 실제 `--execute`에는 OpenAI 호환 LLM 환경변수가 필요하다.
- `scripts/run_media_batch.py --as-generation --archive ...`는 `(content_id, generation_id)` generation pool에 결과를 저장하고 Production을 바꾸지 않는다. `/media/generations` 사람 검토 후 `scripts/promote_media_generation.py`로 별도 승격한다. 같은 content_id의 다른 generation overwrite는 `check_promotion_conflict()`가 막고, supersede는 명시적 lifecycle이다.
- Production Archive의 승인/수정·Threads/Shorts downstream 준비, promotion/readiness/recovery가 존재한다. 5-29의 ShortsScript 저장, 6-06~6-23의 versioning·review·promotion·conflict·supersede·recovery를 다시 만들 필요는 없다.
- `content_engine.media_strategy`/`scripts/audit_media_strategy.py`는 출처·중복·고위험·플랫폼 적합성 후보를 읽기 전용으로 평가하고 Operator에 표시한다. 실제 `run_media_batch.py`의 현재 자동 진입 게이트는 approved KNOWLEDGE 선택이며, 이 strategy 결과는 실행 CLI와 별도다.
- 현재 GitHub `data/tak_media_archive.json`: **2건**, 둘 다 Shorts, `valid + approved`, superseded 0. 둘 다 6-50에서 recovery 승인 후 명시적으로 적용된 레코드다. generation pool은 0개이며, 현재 Archive 두 content_id와 Threads pending/publish ID 사이의 교집합도 0이다.
- `.github/workflows/daily-media-prepare.yml`은 승인된 Archive를 읽어 Blog Pack·ShortsScript 준비와 Threads 현황 요약만 한다. LLM 생성이나 외부 게시를 하지 않는다.

## 6. PUBLISH 상태

- **현재 readiness 실측**: `python scripts/audit_publish_candidates.py --no-report` 결과 전체 2, `READY 0`, `NEEDS_HUMAN_REVIEW 2`, `BLOCKED 0`, `ALREADY_PUBLISHED 0`, `SUPERSEDED 0`, `ERROR 0`. 두 Shorts는 approved이지만 금융/부동산/대출 등 민감 콘텐츠 최종 확인이 필요하다고 분류된다.
- **Threads**: `/media` 승인 시 pending 연결, `/threads`에서 최종 승인, `scripts/publish_approved_threads.py --execute` 또는 수동 `publish-approved-threads.yml` dispatch로 게시한다. 발행 직전에 duplicate/supersede 검사와 publish history 기록이 있다. 오래된 `daily-threads-post.yml` schedule은 비활성화돼 있다. 현재 pending은 `published 1 / pending 4`, publish log는 7건이나 현재 Production Archive와 겹치는 content_id는 0건이다. log와 pending 교집합은 1건, 나머지 과거 log는 현재 pending에 없는 legacy 기록이다.
- **YouTube Shorts**: ShortsScript → `scripts/render_shorts_v3.py`의 승인된 항목 렌더 → 품질 게이트/manifest → `scripts/upload_youtube_short.py`가 공식 경로다. 운영 업로드는 content_id/knowledge_id가 필요하고 승인·generation·ShortsScript·중복·supersede 조건을 검사한다. 공개 업로드는 추가 `--confirm-public`가 필요하다. GitHub workflow에 YouTube upload는 없다.
- 현재 YouTube log는 2건이며 모두 private, `content_id` 연결 0건: `test` 1, `legacy_unlinked` 1. 하나는 6-42에서 실제 업로드된 QA 영상이지만 Production 콘텐츠 lineage와 무관하고, 다른 하나도 legacy unlinked다. `YouTubeUploadHistory.performance_targets()` 대상은 0건이다. 이를 Production 게시로 세지 않는다.
- **Blog**: `--from-archive` Publish Pack은 approved 후보를 만들고, 운영자가 Naver에 직접 복사/게시한 뒤 `mark_blog_published.py`로 기록한다. 자동 로그인·게시 API는 없다. 현재 `blog_publish_log.json`은 NOT_PRESENT이며 `.gitignore` whitelist도 없다.
- `docs/publish_readiness_latest.md`와 `docs/threads_publish_consistency_latest.md`는 **2026-09-21 생성 스냅샷**이다. 당시 Archive 18건의 결과이므로 현재 2건 상태의 수치로 사용하면 안 된다.

## 7. PERFORMANCE 상태

- 이미 구현됨: `PerformanceRecord`, `(content_id, metric_collected_at)` append-only 저장, 중복 방지, Threads Insights API/YouTube statistics API collector, Naver Blog 수동 입력, measurement window, quality warning, content/knowledge 분석, trend/anomaly/comparison/traceability Insight, 일간/주간 report, evidence drill-down, 사람의 accepted/rejected decision, `/performance` 및 `/performance/insights` 읽기 화면.
- `scripts/collect_performance.py`는 반드시 content_id, knowledge_id, published_at을 받고 Threads/YouTube에는 external ID와 `--confirm-live`를 요구한다. Blog는 사람이 지표를 입력한다. 수집 CLI를 실행하는 GitHub workflow는 없다.
- 현재 GitHub 데이터: `tak_performance.json` 및 `tak_performance_insights.json` **둘 다 없음**. `scripts/analyze_performance.py`, `scripts/performance_insight_report.py`와 report/dashboard는 구현돼 있지만 현재 원자료/Insight가 없다.
- 6-35/6-36은 Performance→Insight→사람의 결정까지만 구현한다. `MONETIZATION` 분류/필드 이름은 준비돼도 실제 revenue collector/귀속 계산은 없다. 승인된 Insight가 KNOWLEDGE나 SCOUT score를 자동 변경하지 않는다.
- 저장 데이터의 `.gitignore` 정책도 한계다: Performance와 Insight 파일은 현재 GitHub에 추적되지 않아 여러 기기 간 동기화되지 않는다(6-39에서 확인).

## 8. MONEY 상태

- MONEY는 온라인 작업 수익(설문 등)용 별도 개인 운영 도구다. 예상 보상과 실제 받은 원/시간을 분리하고, 작업 발견→new/open/done/skipped→중복 방지→KST별 통계→실제 시급 보정→첫 10,000원 목표를 기록한다.
- Browser Scout는 읽기 전용 agent 결과만 받아 개인정보 제거·정규화·staging·중복 병합한다. 현재 정책상 PanelNow만 자동 읽기 허용, Ovey는 app-only, Heypoll은 약관상 자동 접근 금지, AdPost는 browser-restricted다. 설문 응답·제출·로그인·CAPTCHA 우회는 하지 않는다.
- 실제 수익 루프(UI/코드)는 구현됐지만, 6-62의 마지막 실운영 보고는 PanelNow 기회 2건(700P/25분, 3P/1분), **실제 수익 0원**, `REAL_REVENUE_PENDING`이다. 약관 동의 팝업은 사용자 판단으로 남겼고, 설문 완료/금액·시간 입력은 사람이 해야 한다.
- MONEY는 content_id/knowledge_id와 연결되지 않는 별도 task/log 구조다. 콘텐츠 채널의 수익/광고/후원/구매 attribution과는 다른 시스템이다.
- GitHub `main`/현재 clean worktree에는 `money_*.json` 운영 파일이 없다. 6-62에서 만든 기회/staging JSON은 gitignore된 환경별 데이터라 해당 기록이 현재 GitHub에 보존됐다고 볼 수 없다. 현재 Operator는 `MONEY: EMPTY`, 0원/0건을 보여준다.

## 9. Operator 상태

- `content_engine.operator_summary`는 SCOUT→KNOWLEDGE→MEDIA→HUMAN REVIEW→PROMOTION→PRODUCTION→PUBLISH→PERFORMANCE→INSIGHT 9단계를 기존 판정 함수로 집계한다. `/operator`와 `scripts/operator_control_center.py --json`은 읽기 전용이며, 승인·게시·복구·재생성 버튼이 없다.
- 실제 `operator_control_center.py --json` (2026-10-01) 요약: `READY_WITH_HUMAN_STEP`, Git SYNCED, SCOUT 5, KNOWLEDGE pending 13, MEDIA generation NOT_PRESENT, human media review 0, promotion 0, Production Archive VALID 2, PUBLISH ACTION_REQUIRED, Performance/Insight NOT_PRESENT, Recovery NOT_REQUIRED, YouTube Uploads 2건(legacy/test unlinked), MONEY EMPTY.
- 이 상태는 시스템 준비 수준의 집계다. `test_status=UNKNOWN`은 Operator가 테스트를 자동 실행하지 않았기 때문이다. readiness 2건은 둘 다 `NEEDS_HUMAN_REVIEW`이므로 게시 가능 `READY`와 혼동하면 안 된다.

## 10. 현재 실제 운영 가능한 E2E 구간

1. 공개 RSS 수집·점수화와 인터뷰/승인 KNOWLEDGE 생성 경로가 있다. 현재 tracked SCOUT pack은 5건이지만 9월 19일 생성본이라 fresh run 증거는 아니다.
2. 승인 KNOWLEDGE로 9개 채널별 draft 생성, validation, generation pool, 사람 수정/승인, promotion, Production Archive까지 코드와 회복 경로가 연결되어 있다. Current Archive의 실제 적용 데이터는 승인된 Shorts 2건이다.
3. Threads는 승인 pending→최종 승인→실제 API 호출→publish log의 운영 경로가 있고 GitHub에 7건의 publish history가 기록돼 있다. 단 현재 Production Archive 2건과 그 이력의 content_id 교집합은 0이다.
4. YouTube는 V3 렌더/품질검사, upload eligibility, private/public safety, lineage/history, 중복 방지 코드가 있다. 과거 PRIVATE 업로드 실증은 있지만 현재 log에서 둘 다 content_id가 비어 있어 운영 콘텐츠 E2E로는 연결되지 않는다.
5. 성과 API 수집·저장·Insight·사람의 판단 경로는 이미 구현돼 있다. 그러나 현재 Performance snapshot이 없으므로 이 구간은 synthetic 테스트만 입증한다.

**결론:** 실제 운영 사례와 mock/synthetic E2E는 존재하지만, 현재 GitHub 운영 데이터에서 첫 단계부터 같은 `content_id`로 이어지는 **Scout→새 Knowledge→실제 외부 게시→실제 성과 snapshot** 완결 사례는 확인되지 않는다.

## 11. 현재 끊어진 E2E 구간

```text
최신 SCOUT 결과 → 사람 선택/인터뷰 → 승인 KNOWLEDGE → LLM MEDIA generation
  → 사람 검수/승격 → 채널별 최종 승인/게시 → publish ID 저장
  → 24h/72h/7d metric 수집 → Insight 사람 검토 → 다음 소재 선택
```

- 이번 snapshot은 오래됐고, current generation pool은 없어서 fresh issue의 media 생성/검수를 이어갈 작업 상태가 main에 없다.
- Media strategy는 코드/CLI/Operator 점검이 있으나, 현재 batch CLI의 명시적 입력 게이트는 KNOWLEDGE `approved`; 전략 결과를 자동 실행 차단으로 연결하지 않는다.
- Current Production은 2개 Shorts뿐이며 둘 다 Readiness REVIEW 상태다. Thread 게시 이력은 별도 lineage이고, YouTube 기록은 test/legacy이며, Blog 게시 history가 없다.
- Performance 데이터가 전무해 조회·좋아요·댓글을 content_id/knowledge_id에 붙인 실제 결과가 없다. Insights도 0이다.
- MONEY의 실제 원화 수익 루프는 별도 task 관리이며, 콘텐츠 수익을 `content_id`에 귀속하지 않는다.

## 12. MVP까지 남은 핵심 작업

코드를 중복 구현하기 전에 기존 경로를 이용해 아래 단일-content 운영 cycle을 먼저 완주해야 한다.

1. 오늘의 SCOUT 결과를 새로 만들고, 운영자가 이슈 1개를 선택해 인터뷰/근거를 확인한 뒤 KNOWLEDGE를 승인한다.
2. 해당 ID 하나만 `run_media_batch.py --execute --as-generation --id ...`로 생성한다. LLM credentials는 환경에만 두고, generation pool 결과를 수동 검토·수정·승인한다.
3. conflict/supersede 보호를 거쳐 명시적으로 promotion한 뒤 Production `/media`에서 해당 콘텐츠의 최종 검토를 완료한다.
4. 우선 실제 게시를 이미 지원하는 **Threads** 한 건으로 끝까지 간다: pending draft 최종 승인 → `publish_approved_threads.py --execute` 또는 workflow dispatch → 발행 ID/시각 기록. 외부 게시 실행은 운영자의 별도 명시 승인과 credentials가 필요하다.
5. 실제 게시 이력의 `threads_post_id`, `content_id`, `knowledge_id`, `published_at`을 사용해 24h/72h/7d 중 첫 Performance snapshot을 수집한다(`--confirm-live`는 실제 API 호출임을 인지하고 사용).
6. 적어도 세 시점/필요 표본이 쌓인 뒤 기존 Insight/report를 실행하고, 사람이 결과를 받아 다음 주제/angle 선택을 기록한다. 자동으로 전략을 바꾸지 않는다.
7. 이 첫 cycle 이후, 수동 입력이 반복되는 것이 확인되면 게시 이력에서 Performance target을 안전하게 채우는 orchestration을 우선 검토한다. 기존 collector/Insight/MONEY를 다시 만들지 않는다.

## 13. PROJECT 2030과의 경계

- 6-63~6-69 게임 관련 문서는 프로젝트 맥락 파악에만 읽었다. 6-63은 TAK GAME FACTORY를 미래의 후보 content format으로 논의했지만, 현재 콘텐츠공장의 `media_strategy.PLATFORMS`는 `threads/blog/shorts`뿐이다.
- GitHub `main`의 [6-71 되돌림/범위 보고서](6-71-project-2030-scope-separation-revert.md)가 6-70 게임 코드 변경을 revert하고 다음 규칙을 기록했다.

> 탁자동 콘텐츠공장 작업에서는 PROJECT 2030 게임 코드, 게임 데이터,
> 게임 문서, game_lab 관련 파일을 수정하지 않는다.

- 현재 `game_lab/`는 별도 파일 공간이며, `content_engine/`, `scripts/`, `tak_brain/`, `tak_scout/`에서 `game_lab`을 import/참조하지 않는다. 이 보고서 작성에서도 game_lab 및 6-63~6-69 게임 문서는 작업 대상이 아니다.

## 14. 다음 개발 우선순위

**P0 — 한 건의 content_id를 끝까지 잇는 실제 Threads→Performance cycle.** 현재 막힌 것은 기능이 전혀 없는 것이 아니라, fresh Scout 기반 운영 입력·사람의 approval·실제 post history·성과 snapshot이 한 lineage로 이어지는 증거가 없는 점이다. 기존 production/recovery/publish/Performance 기능을 재사용해 12장의 단일 콘텐츠 절차를 완주한다.

이 작업 후에야 P1로 **publish history에서 수집 대상의 external ID·발행 시각을 자동 선택하는 얇은 연결**을 검토한다. 현재 YouTube history에는 content_id 기반 `performance_targets()`가 있으나, 지금 GitHub에는 production-mode linked record가 0이며 collector CLI는 외부 ID/시각을 직접 받는다. P2는 실제 Performance/Insight가 쌓인 뒤 human-reviewed insight를 소재 전략에 반영하는 운영 절차다.

## 문서 학습 범위

기준 파일 목록은 `origin/main`의 `docs/**/*.md`이며 89개다. 초기 품질/SCOUT 설계, MEDIA persistence·versioning·approval, recovery/data safety, Publish/Readiness, Threads·YouTube·Blog, Shorts V2/V3/Studio, Performance/Insight/Operator, MONEY, 그리고 6-71 범위 보고서를 시간순으로 검토했다. PROJECT 2030 문서는 분리 원칙 확인만을 위해 읽었다. 6-28/6-29의 readiness/runbook 및 6-45~6-51의 데이터 회복 문서는 역사적 environment 결과와 현재 GitHub main 상태를 구분하는 근거로 사용했다.