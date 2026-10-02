# 탁공장 P1 — 24h/72h Performance 자동 수집

## 목표

P0에서 실제 게시한 콘텐츠를 publish time 기준 24h/72h에 다시 조회하고, 기존 Performance store의 append-only/idempotent 구조에 기록한다. 새 SNS·수익 기능·자동 전략 변경은 범위에서 제외한다.

작업 기준은 fetch한 GitHub `main` HEAD `51b4ad20f8d72fc249ee793061be7f3e3987c0b7`이다. PROJECT 2030 파일은 수정하거나 테스트하지 않았다.

## P0 실제 게시물 확인

보고서를 그대로 신뢰하지 않고 현재 main의 원본들을 다시 읽어 확인했다.

- SCOUT: `scout-4a093bcd52aa`, “The AI telling farmers when to harvest”
- KNOWLEDGE: `knowledge-scout-cdfb9c5c8aaa`, approved, `source_raw_id`가 위 SCOUT ID
- generation pool: `gen-20261001T071215-a5939e3f`, `content-3978f6da76aebf01`, valid + approved
- Production Archive: 같은 `content_id`/`knowledge_id`/`generation_id`, `platform=threads`, approved, superseded 아님
- published pending 및 `threads_publish_log.json`: 같은 `content_id`, `knowledge_id`, `threads_post_id=18085925933320004`, published 상태
- 실제 게시 URL: https://www.threads.com/@tmong_wisdom/post/Dd8XUHsAUg8
- API server timestamp: `2026-10-01T07:23:19+0000`; publish history의 local 기록 시각은 `2026-10-01T07:23:23.502999+00:00`
- 기존 `data/tak_performance.json`: 같은 post/content/knowledge ID의 `threads_api` snapshot 1건, `metric_collected_at=2026-10-01T07:24:06.507668+00:00`; API가 반환한 views/likes/replies/reposts/quotes/shares는 모두 0

현재 데이터 교차 검증에서 전체 lineage가 일치했다. 기존 P0 snapshot에는 generation/window metadata가 없고 게시 직후 수집분이다. 이 레코드는 수정하지 않았으며 24h/72h sample로 세지 않는다.

## 현재 Performance 구조

- `collect_performance.py`의 Threads collector, `PerformanceRecord`, `threads_publish_log.json`, `content_id`, `external_id`, `published_at`을 그대로 재사용한다.
- 기존 record는 append-only이며 window metadata가 없으면 기존 `(content_id, metric_collected_at)` dedupe 규칙을 유지한다.
- scheduled record에만 `generation_id`, `measurement_window`, `external_post_id`, `collection_status=collected`, `unavailable_metrics`를 선택적으로 추가한다. legacy JSON은 deserialize/serialize 시 새 키를 덧붙이지 않는다.
- `metrics`에는 API가 실제 반환한 값만 저장한다. 요청한 metric 중 누락된 것은 `unavailable_metrics`에 기록하며, 응답의 실제 0은 `metrics` 안의 0으로 보존한다.

## 24h 측정 설계

`published_at` 기준 24시간 미만은 due 대상이 아니며 `측정 대기`로 남는다. 24시간 이상 72시간 미만에서 24h window가 없으면 due가 된다. 기록 시 실제 API 측정 시각은 `metric_collected_at`에 저장되어 목표 시각과 지연 정도를 구분할 수 있다.

매일 07:30 UTC 실행이므로 snapshot은 정확히 게시 후 24:00:00에 실행된다는 보장은 없다. 예를 들어 P0는 다음날 schedule이 게시 후 약 24시간 7분 시점이다. 실제 측정 시각을 기준 시각으로 가장하지 않는다.

## 72h 측정 설계

게시 후 72시간 이상이면 72h window를 선택한다. 이미 24h가 있더라도 72h는 별도 append-only snapshot이다. 72시간 이후까지 24h 수집이 누락됐다면 현재 값을 24h로 소급 표기하지 않고 72h만 수집한다. 이번 변경은 7d window를 추가하지 않았다.

## GitHub Actions

- 신규 `.github/workflows/daily-performance-collection.yml`: 매일 `30 7 * * *` UTC schedule 및 수동 dispatch를 제공한다. 수동 dispatch 기본값은 dry-run이다.
- live step만 기존 `THREADS_ACCESS_TOKEN` secret과 `TAK_PERFORMANCE_ALLOW_GITHUB_ACTIONS=true`를 받고, collector에도 `--confirm-live`를 전달한다. CLI는 GitHub Actions opt-in만으로 호출하지 않고 두 조건을 모두 요구한다.
- concurrency는 `cancel-in-progress: false`; 수집 대상이 없어도 성공적으로 종료한다. API 오류가 있으면 실패를 반환하고 snapshot은 저장하지 않아 다음 실행에서 재시도한다.
- API 실패 전 이미 성공 저장한 다른 대상이 있으면 workflow가 실패해도 성과 파일 변경을 commit한다. 동시 다른 workflow push와 경합할 경우 `git pull --rebase origin main` 후 push한다.
- 현재 GitHub Actions 실제 실행은 하지 않았다. P0가 아직 24h 미만이므로 live API 호출은 없으며, 수동 dry-run 경로와 workflow YAML은 로컬 테스트로 검증했다. 기존 secret 이름은 재사용하지만 실제 repository secret 설정 여부는 이 세션에서 확인하지 않았다.

## 데이터 구조

새 scheduled record 예:

```json
{
  "content_id": "content-3978f6da76aebf01",
  "knowledge_id": "knowledge-scout-cdfb9c5c8aaa",
  "generation_id": "gen-20261001T071215-a5939e3f",
  "platform": "threads",
  "external_id": "18085925933320004",
  "external_post_id": "18085925933320004",
  "published_at": "2026-10-01T07:23:19+00:00",
  "metric_collected_at": "<actual API collection time>",
  "measurement_window": "24h",
  "metrics": {"views": 0, "likes": 1},
  "unavailable_metrics": ["replies", "reposts", "quotes", "shares"],
  "source": "threads_api",
  "collection_status": "collected"
}
```

예시는 schema 설명일 뿐 실제 수치를 나타내지 않는다. Workflow commits only `data/tak_performance.json`; `.gitignore`에 whitelist를 추가해 ephemeral Actions checkout 사이에 측정/중복 상태를 보존한다. 이번 commit에는 이미 존재하던 실제 P0 initial snapshot 1건도 원본 값 그대로 포함한다.

## Idempotency

- scheduled window key: `(content_id, external_post_id, measurement_window)`. 같은 workflow를 여러 번 실행하거나 같은 window를 다른 시각에 재시도해도 기존 snapshot을 덮어쓰거나 중복 추가하지 않는다.
- windowless legacy/manual snapshot key는 기존 `(content_id, metric_collected_at)` 의미를 유지한다.
- collector는 publish history ID뿐 아니라 production의 valid/approved/non-superseded generation, published pending의 post ID/knowledge ID/published time까지 교차 확인한다. 중복/모호한 history, legacy/orphan, mismatched content/knowledge/post, generation 없는 레코드는 fail-closed로 제외한다.

## 테스트 결과

요구된 10개 시나리오를 단위/CLI mock으로 검증했다.

1. 24h 전 측정 대기 및 API client 미생성
2. 정확히 24h 시 due
3. 72h 시 72h window 선택, 늦은 24h 소급 방지
4. 다른 수집 시각의 동일 window 재실행 dedupe
5. Threads API 실패 시 snapshot 미저장/실패 반환
6. 일부 metric 미제공 시 `unavailable_metrics`로 구분
7. 이미 수집된 window 재대상화 방지
8. content/knowledge/post lineage mismatch 제외
9. superseded 및 generation 없는 Production 제외
10. published 상태가 아닌 test/legacy/orphan 게시 제외

- Performance/collector/workflow focused suite: **81 passed**.
- 게임 테스트 파일을 제외한 전체 pytest: **1695 passed, 31 failed, 118 skipped, 271 subtests passed**.
- 31개 실패는 모두 기존 `test_6_55_shorts_studio.py`의 Windows 경로 `C:/Windows/Fonts/NotoSansKR-VF.ttf`가 Linux에서 없어서 발생했고, 관련 Windows 폰트/대시보드 환경 오류다. 새 P1 테스트는 모두 통과했다.
- 실제 API 테스트는 실행하지 않았다. Threads Insights는 fake transport로만 검증했다.

## 실제 운영 검증

2026-10-01 `08:00:07Z`에 현재 P0 데이터로 `python scripts/collect_performance.py --scheduled --dry-run`을 실행했다. 결과는 “측정 대기”; API 호출 및 파일 변경은 없었다. 기준 publish time으로부터 약 37분만 경과했으므로 실제 24h/72h 데이터는 아직 존재하지 않는다.

## 조기 검증 재확인 (2026-10-02T00:47Z)

origin/main HEAD(`8d70745`)를 별도 git worktree로 체크아웃해 현재 작업 트리는 건드리지 않고 재확인했다.

- `python scripts/collect_performance.py --scheduled --dry-run` 재실행 결과: `측정 대기/완료: 현재 due target 없음` (exit 0), 전날 검증과 동일.
- P0 publish 후 경과 약 17시간(24h 미도달, 24h 도달 예정 `2026-10-02T07:23Z` 근방). `select_due_threads_targets`가 due 대상을 반환하지 않아 `ThreadsClient` 생성/API 호출 자체가 일어나지 않음을 소스로 재확인.
- 실행 전/후 `data/tak_performance.json`, `data/threads_publish_log.json` md5 동일, 신규/중복 snapshot 없음(`git status` clean).
- `daily-performance-collection.yml`의 `workflow_dispatch` 입력 `dry_run` 기본값 `true` → dry-run 경로만 실행되고 live 수집/commit 스텝은 스킵됨을 정적 확인. `gh workflow run`으로 실제 트리거를 시도했으나 Codespace `GITHUB_TOKEN`에 `actions:write` 권한이 없어 `HTTP 403`으로 거부되어 실제 Actions 실행 검증은 보류.
- 실제 24h 수집이 되려면: (1) publish 후 24h 경과, (2) 다음 `30 7 * * *` UTC schedule 또는 권한 있는 수동 `workflow_dispatch`(dry_run=false) 실행, (3) `THREADS_ACCESS_TOKEN` secret 유효성이 모두 충족되어야 한다. 이번 세션에서는 어느 것도 강제하거나 가짜 데이터로 대체하지 않았다.

## 현재 측정 상태

- initial: 실제 `threads_api` snapshot 1건, P0 게시 직후 수집, API 반환 값 6개 모두 0. legacy snapshot이라 `measurement_window`/`generation_id` metadata는 없고 재작성하지 않았다.
- 24h: 대기. 다음 예정 schedule은 `2026-10-02 07:30 UTC`; 실제 측정은 workflow가 due 확인 후 API 응답을 받은 시각이다.
- 72h: 대기. 게시 후 72h 이상인 첫 daily run에서 수집한다.
- 현재 API 호출 수: P1 검증 중 0회. 향후 값을 실적으로 오인하지 않도록 mock/dry-run과 분리했다.

## 남은 검증 사항

- GitHub Actions schedule이 실제 runner에서 시작되고 `THREADS_ACCESS_TOKEN` secret이 유효한지는 첫 due 실행 전까지 미검증이다.
- 실제 24h/72h API 응답값, 미제공 metric 조합 및 workflow commit/retry 동작은 실제 실행 뒤 확인해야 한다.
- 매일 한 번 실행하는 schedule 특성상 측정 시각은 목표 window보다 늦을 수 있다. 매 snapshot의 `published_at`/`metric_collected_at`을 함께 확인한다.

## 다음 작업

첫 due workflow가 P0의 24h snapshot을 저장했는지 확인하고, 같은 `content_id`/post/generation/window로 중복 없이 commit됐는지 검증한다. 이후 72h 수집을 확인한다. 광고수익, 다른 SNS, Shorts/Blog, 자동 콘텐츠 전략 변경은 수행하지 않는다.