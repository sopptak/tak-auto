# 6-84 Marketing Factory 운영 E2E 검증

브랜치 `chore/untracked-file-triage-20261004`, 시작 HEAD 4858519(6-83). 관련 문서: [6-79](6-79-ai-marketing-intelligence.md), [6-80](6-80-marketing-brief-to-content.md), [6-81](6-81-marketing-data-persistence-and-media-bridge-investigation.md), [6-82](6-82-marketing-persistence-and-media-bridge-plan.md), [6-83](6-83-marketing-knowledge-linking.md).

## 1. 목적

6-79~6-83에서 만든 기능을 **운영자가 실제로 쓰는 순서와 명령**으로 한 바퀴 돌려 연결이 끊기지 않는지 확인한다. 범위는 Market Demand → Idea → Brief → Knowledge → Generation → MEDIA Review → Promotion → Performance → Insight다.

함께 확인한 것: 자동 승인, 자동 발행, 잘못된 성과 귀속, Production 오염이 일어나지 않는가. 새 기능은 추가하지 않았고, 발견된 연결 문제만 최소로 수정했다.

## 2. 검증 환경

- 탐색 실행: scratchpad 임시 디렉터리에서 실제 CLI를 shell로 순서대로 실행했다(4~5장).
- 회귀 고정: `tests/test_marketing_e2e_operational.py`
  - 각 테스트가 임시 디렉터리를 만들고, 모든 CLI를 **subprocess**로 실행한다. 경로 인자는 `--data-dir`, `--input`, `--archive`, `--production-archive`이고 모두 임시 경로를 가리킨다.
  - 가드: subprocess에 `sitecustomize.py`를 주입한다.
    - 소켓 연결(`connect`, `create_connection`, `getaddrinfo`)을 막는다.
    - `ThreadsClient`/`YouTubeClient`의 모든 메서드와 기본 HTTP transport 호출을 막는다.
    - 호출되면 예외를 던지고 `guard.log`에 기록한다. CLI가 예외를 삼켜도 기록이 남으므로 감지된다.
  - publisher 모듈의 **import**는 허용한다. `content_engine/__init__.py`가 `threads_publisher`를 패키지 수준에서 import하기 때문에 모든 CLI가 모듈을 로드한다(6-84에서 확인). 로드는 아무것도 호출하지 않는다.
  - LLM, Threads, YouTube, Perplexity 환경변수는 subprocess 환경에서 제거한다.
- 실제 저장소 `data/`는 테스트 클래스 전후의 SHA-256을 비교한다. 작업 전후 비교는 10장에 있다.

## 3. 실제 운영 순서

```
Market Demand ─ market_demand.py --write
  → Idea Candidate (tak_idea_candidates.json)
  → MarketingBrief ─ marketing_brief.py --write draft IDEA --research mock  (공통 브리프 + pending 리서치 KNOWLEDGE)
  → platforms --write (blog/threads/shorts/youtube 브리프, draft)
  → approved KNOWLEDGE ─ review_knowledge.py --input … --id K --approve   (기존 KNOWLEDGE 검토)
  → knowledge add (미리보기 → --write)
  → review → set DIM.ELEM VALUE … → approve
  → generate --rewrite mock (미리보기 → --write)  → tak_marketing_contents.json (review_required)
  → bridge (미리보기 → --write) → tak_media_generation_marketing-<brief>.json (unreviewed)
  → /media/generations 검토 handler(handle_generation_review_submission)로 사람이 승인
  → promote_media_generation.py --archive POOL --production-archive PROD --generation-id GEN (dry-run → --execute)
  → PerformanceRecord(production content_id) → tak_performance.json
  → marketing_brief.py insights → brief_id 귀속
```

## 4. CLI 명령과 단계별 결과

### [CLI 검증] 실행 순서와 결과

| # | 명령 | 결과 |
|---|---|---|
| 1 | `market_demand.py --input demands.json --min-score 30 --data-dir D --write` | 수요 1, 아이디어 1(점수 83.5) |
| 2 | `marketing_brief.py --data-dir D --write draft IDEA --research mock` | 브리프 draft(근거 46건), pending 리서치 KNOWLEDGE 9건 |
| 3 | `marketing_brief.py --write platforms BRIEF` | 플랫폼 브리프 4건(draft) |
| 4 | `review_knowledge.py --input D/tak_brain_knowledge.json --id knowledge-exp-1 --approve` | `knowledge-exp-1: approved` |
| 5 | `knowledge add YT_BRIEF knowledge-exp-1` (미리보기) | 존재/approved/미연결/연결 가능 출력. 파일 변경 없음 |
| 6 | `--write knowledge add …` | knowledge_ids에 추가. 브리프는 draft 유지 |
| 7 | `review YT_BRIEF` | 연결된 KNOWLEDGE별 상태, 승인·생성 차단 사유 |
| 8 | `approve YT_BRIEF` (요소를 채우기 전) | exit 2, "승인 조건 미충족" |
| 9 | `set YT_BRIEF <요소> <값>` ×20, `approve` | `approved` |
| 10 | `generate YT_BRIEF --rewrite mock` → `--write` | 후보 3건(youtube→shorts, rewritten). 미리보기는 파일 없음 |
| 11 | `bridge YT_BRIEF` → `--write` | pool 파일 1개, 3건 unreviewed, generation_id 1개 |
| 12 | `promote_media_generation.py … --generation-id GEN` (dry-run) | 승인한 1건만 `PROMOTE`, 2건 `SKIP`. production 파일 없음 |
| 13 | `… --execute` | 임시 production에 1건 승격 |
| 14 | `marketing_brief.py insights` | `- brief=… platform=youtube content=… generation=… attention=1000.0 engagement=40.0 conversion=12.0 …` |

### [Python/API 검증] CLI로는 할 수 없는 단계

| 단계 | 사용한 기존 API | 이유 |
|---|---|---|
| MEDIA Review | `scripts/run_scout_dashboard.discover_generation_pool_paths`, `handle_generation_review_submission` | 대시보드 POST 처리 로직. 서버 없이 같은 함수를 호출한다 |
| Performance | `content_engine.performance.store.append_snapshot(PerformanceRecord(source="manual"))` | YouTube 성과 저장은 `collect_performance.py --confirm-live`(실제 API)뿐이다. `--dry-run`은 저장하지 않는다 |
| 기존 배치 generation(격리 검증용) | `pipeline.run_media_batch` + `media_archive.archive_generation_report` | 같은 슬롯의 비교군을 만드는 기존 경로 |

### [파일 검증] 단계별 생성/변경 파일(임시 `data/`)

| 단계 | 파일 |
|---|---|
| Demand/Idea | `tak_market_demands.json`, `tak_idea_candidates.json` 생성 |
| Brief/platforms/knowledge/set/approve | `tak_marketing_briefs.json` 생성/갱신, `tak_brain_knowledge.json`(리서치 pending 추가, 검토 승인) |
| generate --write | `tak_marketing_contents.json` 생성 |
| bridge --write | `tak_media_generation_marketing-<brief>.json` 생성, contents에 generation_id 기록, 브리프 `media_generations` 기록 |
| 검토 handler | 같은 pool 파일의 review_status만 변경 |
| promote dry-run / --execute | 변경 없음 / `tak_media_archive.json` 생성 |
| Performance | `tak_performance.json` 생성 |
| 전 과정 | 발행 로그(`*_publish_log.json`) 생성 없음, guard.log 없음 |

happy path가 끝난 뒤 임시 `data/`에 있는 파일은 정확히 8개다(테스트가 집합으로 고정): knowledge, ideas, demands, briefs, contents, pool, production, performance.

## 5. 데이터 흐름

`demand_id` → `idea.demand_ids` → `brief.idea_id` + `evidence(market_demand)` → `brief.knowledge_ids`(approved만 생성 입력) → 후보(`brief_id, platform=youtube, media_platform=shorts, content_id`) → pool 레코드(`content_id, generation_id, platform=shorts`) → production 레코드(같은 키) → `PerformanceRecord.content_id` → `MarketingInsight(brief_id, content_id, generation_id)`.

## 6. content_id / generation_id lineage

- `content_id`는 기존 `compute_content_id`에 MEDIA 플랫폼을 넣어 계산한다. youtube 후보는 같은 KNOWLEDGE의 기존 shorts 슬롯과 같은 ID다(테스트가 `run_media_batch` 결과와 비교).
- `generation_id`는 bridge 1회당 1개(`gen-<UTC>-<hash>`)이며, 브리프의 `media_generations`(Git 추적 파일)에 `(content_id, generation_id)`로 기록된다.
- insights는 production 활성 레코드(또는 스냅샷)의 generation_id가 브리프 lineage에 있을 때만 귀속한다. 같은 슬롯을 기존 배치 generation이 승격한 경우 성과는 0건으로 귀속된다(테스트 고정).

## 7. 안전 게이트와 불변조건

| 불변조건 | 검증 위치(`tests/test_marketing_e2e_operational.py`) |
|---|---|
| A. 미승인 Brief는 generate/bridge 안 됨 | `GateTests.test_unapproved_brief_is_not_generated` |
| B. approved가 아닌 KNOWLEDGE는 연결 안 됨 | `GateTests.test_unapproved_knowledge_is_not_linked`(pending, rejected, 없음) |
| C. KNOWLEDGE 없는 Brief는 generate/bridge 안 됨 | `GateTests.test_brief_without_usable_knowledge_is_not_generated_or_bridged`(pending만 연결 / 전부 해제) |
| D. bridge는 자동 승인하지 않음 | `MediaSafetyTests.test_bridge_does_not_approve_or_promote`, happy path |
| E. bridge는 자동 promotion하지 않음 | 위 테스트(승인 없이는 `--execute`여도 production 불변) |
| F. promotion 전 production 불변 | `MediaSafetyTests.test_dry_run_does_not_modify_existing_production`(기존 레코드가 있는 production) |
| G. 같은 content_id, 다른 generation_id 성과 미귀속 | `MediaSafetyTests.test_same_content_id_other_generation_not_attributed` |
| H. youtube→shorts, content_id shorts 기준 | `MediaSafetyTests.test_youtube_content_id_is_shorts_slot`, happy path |
| I. pool이 `tak_media_generation_*.json`으로 발견됨 | happy path(`discover_generation_pool_paths == (pool,)`) |
| J. knowledge remove가 후보/pool/production/성과/lineage 불변 | `MediaSafetyTests.test_knowledge_remove_preserves_existing_data_and_lineage`(파일 SHA 비교) |
| K. 생성된 콘텐츠 lineage 보존 | 위 테스트: remove 후에도 insights 귀속 유지 |
| L. publisher/외부 API 미호출 | `GuardTests`(가드 동작 확인 + 전체 루프를 가드 아래서 실행, guard.log 없음) |
| 실제 `data/` 불변 | 모든 테스트 클래스 `tearDownClass`의 SHA 비교 + 10장 작업 전후 비교 |

## 8. 발견된 문제와 수정

| # | 문제 | 분류 | 조치 |
|---|---|---|---|
| 1 | `draft --research`가 pending 리서치 KNOWLEDGE를 출처로 `knowledge_ids`에 넣는데(6-79 설계), `review`에는 연결된 KNOWLEDGE의 승인 상태가 보이지 않는다. 그래서 어떤 연결이 생성에 쓰일지 알 수 없고, `knowledge add`는 "이미 연결됨: 예 + 연결 불가"를 함께 표시한다 | 운영 가시성 | **수정**(2570bc7): `review`가 연결된 KNOWLEDGE별 상태와 "생성 가능한 approved KNOWLEDGE N건"을 출력한다 |
| 2 | `insights` CLI가 "연결된 콘텐츠 성과 N건"과 lift만 출력해, 운영자가 brief/content/generation/지표 귀속을 확인할 수 없다 | 운영 가시성 | **수정**(2570bc7): 귀속된 콘텐츠마다 `brief= platform= content= generation=`와 관측 지표를 1줄씩 출력한다 |
| 3 | 모든 CLI가 `content_engine/__init__.py`를 통해 publisher 모듈을 import한다 | 확인(문제 아님) | 수정하지 않음. 호출은 없다는 것을 가드로 고정 |
| 4 | 리서치 KNOWLEDGE는 `factual_information`만 있고 생성기 입력 필드(experience/problem/action/lesson…)가 없다. 승인해도 생성에는 `insufficient_distinct_evidence`가 된다 | 설계상 동작 | 문서화. 생성에는 경험/판단 KNOWLEDGE를 연결해야 한다 |
| 5 | YouTube 성과를 수동으로 저장하는 CLI가 없다(`collect_performance.py`의 youtube는 live API 또는 저장하지 않는 dry-run뿐) | 운영 공백 | 문서화(11장) |

수정 1, 2는 `scripts/marketing_brief.py`의 출력만 바꿨다. 데이터와 계약은 그대로다. 재현 테스트(E2E와 `test_marketing_cli.py`)가 실패하는 것을 먼저 확인한 뒤 수정했다.

연결 실패(인자 불일치, 경로 전달, status 전이, generation_id 전달, content_id 불일치, pool discovery, dashboard/promote 호환, production↔performance 연결, insight 귀속)는 **발견되지 않았다**.

## 9. 수정하지 않은 것

`content_engine/media_archive.py`, `pipeline.py`, `generator.py`, `scripts/run_scout_dashboard.py`, `scripts/promote_media_generation.py`, `content_engine/performance/*`, publisher, `tak_brain/*`, `scripts/review_knowledge.py`, `.vscode/`. 52fb0bb 대비 diff가 비어 있다(10장).

## 10. 테스트 결과

| 항목 | 결과 |
|---|---|
| 신규 테스트 | 13개: `test_marketing_e2e_operational.py` 11(전부 subprocess CLI, 약 60초) + `test_marketing_cli.py` 2 |
| 전체 | 2062 passed, 33 failed, 108 skipped(6-83 종료 시 2049 passed / 33 failed) |
| 기존 실패 | 33: `test_6_55_shorts_studio.py` 31(Windows 폰트/네트워크, 테스트 24 + subtest 7), `test_second_knowledge_correction_and_generation_pool.py` 2(production archive count) |
| 신규 실패 | 0 |
| 금지 파일(52fb0bb 대비) | 변경 없음: media_archive, pipeline, generator, run_scout_dashboard, promote_media_generation, performance/*, publisher, tak_brain/*, review_knowledge.py, .vscode |
| 실제 운영 data | 작업 전후 SHA-256과 mtime이 같다: `tak_media_archive.json`, `tak_performance.json`, `tak_brain_knowledge.json`, `tak_threads_pending.json`, 기존 generation pool. 마케팅 파일은 작업 전후 모두 없음 |
| `git diff --check` / secret scan | 통과 / 발견 없음 |
| 커밋 | 2570bc7(review/insights 출력 수정), 0102740(운영 E2E 테스트), 문서 커밋(이 문서) |

## 11. 실제 운영 전 남은 과제

- YouTube/Threads 성과의 수동 입력 CLI가 없다. live 수집(`--confirm-live`) 전에는 API로만 기록할 수 있다.
- 브리프 요소를 채우는 데 `set`을 여러 번 실행해야 한다. 이번 시나리오는 20회였다. 일괄 편집 UX가 없다.
- 리서치 KNOWLEDGE는 생성 입력이 되지 않는다. 생성용 KNOWLEDGE를 따로 준비해 연결해야 한다(4번).
- Marketing 데이터 파일(A 등급)의 실제 커밋은 사람이 결정한다(6-82). 아직 운영 data에 마케팅 파일이 없다.
- 실제 LLM(`--rewrite llm`)과 실제 리서치 provider로는 검증하지 않았다(외부 호출 금지 범위).
