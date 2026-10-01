# 탁공장 P0 — 실제 Threads → Performance E2E 보고서

## 목표

하나의 동일한 `content_id`를 fresh SCOUT 결과, 승인 KNOWLEDGE, MEDIA generation, Production, 실제 Threads 게시 및 실제 Performance snapshot까지 연결한다.

## 작업 범위

- TAK 콘텐츠공장 경로만 사용했다. PROJECT 2030 및 `game_lab/`은 수정하지 않았다.
- 기존 SCOUT, interview/Knowledge, MEDIA generation pool, human review, promotion, Production approval, Threads publish/history, Performance collector를 재사용했다.
- Production에서 이미 approved인 Threads 레코드에 pending 초안이 없으면 연결이 복구되지 않던 경로를 수정했다. 승인 상태와 기존 pending이 있으면 유지하고, 누락된 초안만 한 건 생성하도록 했다. 관련 회귀 테스트를 추가했다.
- 원격 기준: `git fetch origin main` 후 `origin/main`과 일치한 기준 HEAD `68d325c4b3e73f9e65461e11924180cbd20134a2`.

## SCOUT 이슈

- 2026-10-01 fresh run: BBC Business 40건, Hacker News 30건을 수집하고 상위 후보 10건을 선정했다.
- 선택: `The AI telling farmers when to harvest` (`scout-4a093bcd52aa`), BBC 기사 발행 시각 `2026-09-30T23:02:21+00:00`.
- 원문에서 확인한 근거: AI 카메라와 날씨·관수 조건을 활용한 작황/수확 예측 실험, 과거 데이터 품질에 대한 예측 의존성, 업계의 미완성 통합 생태계 평가.
- 사용자가 인터뷰 관점 “긍정적으로 본다”를 입력했다. 나머지 9개 후보는 건너뛰었다.

## KNOWLEDGE

- ID: `knowledge-scout-cdfb9c5c8aaa`; `source_raw_id`는 위 SCOUT ID와 일치한다.
- 원문 요약/URL과 사용자 관점을 구분해 기록했다. 초기 상태 `pending`을 검토 후 사용자의 명시적 승인으로 `approved` 처리했다.
- `article_type=null`; `domain/category=금융`은 BBC Business RSS의 source category다. 본문 분류로 오인하지 않았다.

## MEDIA

- 승인된 KNOWLEDGE 한 건만 `run_media_batch.py --execute --as-generation --id ...`로 처리했다.
- 9개 draft 생성 결과: `valid 9 / rejected 0 / error 0`; generation ID `gen-20261001T071215-a5939e3f`.
- Threads 후보 중 `content-3978f6da76aebf01` 하나를 선택했다. 사용자가 확인한 205자 제목/본문을 generation edit 경로에 저장하고 `valid + approved` 상태로 전환했다.
- 9개 generation 레코드는 `data/tak_media_generation_p0_e2e.json`에 기존 pool API로 보존했다. 이 JSON은 `.gitignore` 대상이며 기기간 동기화되지 않는다.

## content_id / generation_id

- `content_id`: `content-3978f6da76aebf01`
- `generation_id`: `gen-20261001T071215-a5939e3f`
- `knowledge_id`: `knowledge-scout-cdfb9c5c8aaa`
- Production: `platform=threads`, `generation_status=valid`, `review_status=approved`, `superseded_by` 없음.
- production archive 최초 반영 후 동일 generation 재승격을 실행했다. 이미 같은 generation이라는 결과로 종료됐고 파일 변경은 없었다.

## 실제 Threads 게시

- Production 승인으로 pending draft를 생성하고, 사용자가 승인한 정확한 문구로 Threads 최종 승인을 마쳤다.
- Publish Readiness는 해당 항목을 `NEEDS_HUMAN_REVIEW`로 표시했다. source RSS category 기반 `domain=금융` 안전 규칙 때문이다. 사람의 최종 문구 검토/승인을 거쳤으며 이 readiness 분류 자체는 우회하거나 변경하지 않았다.
- 공식 publish CLI dry-run에서 단일 대상, 본문, 중복 없음, superseded 아님을 확인했다. 실제 게시 전용 계정 프로필 인증도 확인했다.
- `publish_approved_threads.py --execute` 실행 결과: **성공**, 실제 Threads API가 post ID를 반환했다.

## threads_post_id / external_url / published_at

- `threads_post_id`: `18085925933320004`
- `external_url`: https://www.threads.com/@tmong_wisdom/post/Dd8XUHsAUg8
- Threads API 서버 timestamp: `2026-10-01T07:23:19+0000`.
- publish history `published_at`: `2026-10-01T07:23:23.502999+00:00` (게시 응답 후 로컬 기록 시각). Performance에는 API timestamp를 UTC ISO 형식으로 사용했다.
- publish history에는 `content_id`, `knowledge_id`, post ID, 시각 및 source URL이 저장됐다.

## Performance 실제 수집

- `collect_performance.py --platform threads --confirm-live`로 위 post ID의 실제 Threads Insights API를 조회했다.
- `source=threads_api`, `metric_collected_at=2026-10-01T07:24:06.507668+00:00`.
- API 응답 지표: `views=0`, `likes=0`, `replies=0`, `reposts=0`, `quotes=0`, `shares=0`. 모두 API 원응답에 실제로 포함된 값이다. 응답에 없는 지표를 추가하지 않았다.
- 원응답은 `data/tak_performance.json`에 보존했다. 이 파일은 `.gitignore` 대상이므로 commit/push 대상이 아니며 이 환경에만 남는다.

## 전체 lineage

```text
scout-4a093bcd52aa
  → knowledge-scout-cdfb9c5c8aaa (approved)
  → gen-20261001T071215-a5939e3f
  → content-3978f6da76aebf01 (Threads, valid + approved)
  → Production Archive (approved, not superseded)
  → Threads post 18085925933320004
  → Performance (threads_api, 실제 Insights 응답)
  → content-3978f6da76aebf01
```

각 저장소를 다시 읽어 7개 lineage 조건을 검사했고 모두 통과했다.

## Idempotency

- 동일 content_id의 다른 generation이 Production을 덮어쓰지 않도록 기존 promotion conflict 보호를 유지했다.
- 같은 generation을 재승격하면 `already_promoted`로 아무것도 쓰지 않았다.
- 실제 게시 후 CLI 재실행에서는 게시된 초안이 대상에서 빠졌다. 별도 임시 stale-approved fixture로 publish history 중복 분기도 확인했으며, API 호출 없이 기존 post ID로 종료했다.
- 같은 `(content_id, metric_collected_at)`로 Performance collector를 재실행했을 때 실제 API를 다시 조회했지만 저장소가 중복 snapshot 저장을 건너뛰었다. snapshot은 한 건이다.

## 테스트 결과

- 수정 직후 `test_media_dashboard.py`: **45 passed**.
- SCOUT/Knowledge/promotion/Threads publish/readiness/Performance 관련 테스트 묶음: **201 passed**.
- 전체 Python 테스트(게임 테스트 파일 제외): **1663 passed, 31 failed, 118 skipped, 271 subtests passed**.
- 전체 실행의 31개 실패는 모두 `test_6_55_shorts_studio.py`에서 Windows 전용 폰트 경로 `C:/Windows/Fonts/NotoSansKR-VF.ttf`가 없어서 발생했다. 이번 변경과 무관하다. PROJECT 2030 게임 테스트는 실행하거나 수정하지 않았다.

## 실패/제약

- `NEEDS_HUMAN_REVIEW`는 계속 유지된다. Finance source-category를 사용하는 현재 안전 정책의 결과다.
- Performance는 게시 직후 snapshot 하나뿐이고 모든 현재 지표가 0이다. 추세/Insight나 콘텐츠 전략 변화가 입증된 것은 아니다.
- `data/tak_threads_pending.json`은 ignore 패턴과 별개로 이미 Git 추적 중이므로 이번 변경에 포함한다. `data/tak_performance.json`과 generation pool은 ignore 대상이라 Git에 포함하지 않으며 이 환경에만 남는다. publish log, Knowledge, Production Archive와 SCOUT snapshot은 기존 whitelist에 따라 추적할 수 있다.
- 기본 publish path는 history에 저장된 로컬 `published_at`을 API timestamp와 별도 필드로 보관하지 않는다. 이 보고서는 API가 반환한 게시 시각과 로컬 history 시각을 구분한다.

## MVP 달성 여부

- **CODE READY:** YES. 누락된 approved-Production→Threads-pending 연결을 멱등 복구하도록 보완했다.
- **TEST VERIFIED:** YES. 관련 테스트 201개 통과. 비게임 전체 테스트의 환경 의존 실패 31개는 위와 같다.
- **ACTUALLY PUBLISHED:** YES. 사용자가 승인한 한 건이 공식 Threads API로 게시됐다.
- **ACTUAL PERFORMANCE COLLECTED:** YES. 실제 Threads Insights API snapshot 한 건을 동일 `content_id`로 저장했다.
- P0의 핵심 성공 기준인 “하나의 `content_id`가 실제 Threads 게시와 실제 Performance까지 연결”은 달성했다. 다중 시점/Insight 운영은 아직 검증하지 않았다.

## 다음 작업

24h/72h/7d 이후 실제 Insights를 다시 수집하고, 여러 시점 데이터가 쌓인 뒤 기존 Insight/report를 사람이 검토한다. 그 전까지 이번 즉시 0 지표를 성과 추세로 해석하지 않는다.