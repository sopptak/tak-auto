# 6-82 Marketing 데이터 보존 / YouTube 정합성 / Media Bridge

작성: 2026-10-04, 브랜치 `chore/untracked-file-triage-20261004` @ 1a60ed9. 6-81 조사 결과를 반영한 계획(0~7장)이며, 사용자 승인 후 구현했다. 구현 결과는 8장에 있다.

## 0. 추가 조사로 확인한 사실

- `export_operational_data.discover()`는 `audit_data_state.FILE_SPECS`를 그대로 순회한다. 따라서 FILE_SPECS에 등록하면 export package에도 자동으로 들어간다.
- `data/tak_media_generation_*.json`도 이미 export(`C/D: generation pool`)와 lineage 분석(`analyze_lineage`) 대상이다. marketing pool 파일이 이 이름 규칙을 따르면 별도 등록 없이 export, 대시보드 `/media/generations`, `promote_media_generation.py`가 모두 그대로 처리한다.
- FILE_SPECS/EXTRA_FILES의 내용을 고정하는 테스트는 없다(grep 결과 0건).
- `PerformanceRecord.platform`은 `youtube`이지만 `content_id`는 production archive의 값을 쓴다. 이 값은 `platform="shorts"` 기준으로 계산된다(`collect_performance.py`가 archive에서 대상을 찾는다). 그래서 YouTube 성과를 브리프에 연결하려면 브리프에 **shorts 기준 content_id**가 연결되어 있어야 한다.
- scheduled 성과 스냅샷(24h/72h)에는 `generation_id`가 있고, 수동 스냅샷에는 없다.
- `promote_media_generation.plan_batch_promotion(pool, production, generation_id)`은 파일을 쓰지 않는 계획 함수다. E2E 테스트에서 "promotion 대상"을 검증하는 데 그대로 쓸 수 있다.
- `media_archive.archive_generation_report(report, path, generation_id)`는 같은 `(content_id, generation_id)` 레코드가 이미 있으면 사람의 `review_status`와 `edited_*`를 보존한다. 따라서 bridge를 다시 실행해도 검토 상태가 초기화되지 않는다.

## 1. 데이터 보존 정책

| 파일 | 분류 | Git | audit/export |
|---|---|---|---|
| `tak_idea_candidates.json` | A: 사람의 아이디어 상태(accept/reject) | `.gitignore` 화이트리스트 추가 | FILE_SPECS 등록 |
| `tak_marketing_briefs.json` | A: 승인/반려/편집 + **lineage(아래 4장)** | 화이트리스트 추가 | FILE_SPECS 등록 |
| `tak_marketing_suggestions.json` | A: 제안 accept/reject 결정 | 화이트리스트 추가 | FILE_SPECS 등록 |
| `tak_marketing_contents.json` | C/D: 승격 전 후보(generation pool과 같은 등급) | 계속 무시 | FILE_SPECS 등록(C/D, export에는 포함) |
| `tak_market_demands.json` | A: 수동 입력 원천 데이터(**2026-10-04 사용자 결정**) | 화이트리스트 추가 | FILE_SPECS 등록 |

**tak_marketing_contents를 C/D로 두는 근거(6-21 기준과 비교)**

- 내용은 generation pool과 같은 "승격 전 초안"이다. bridge 이후에는 같은 텍스트가 pool(C/D)에 들어가고, 사람이 승인한 것만 production archive(A)로 승격된다. 6-21이 pool을 무시하는 이유("승격된 것은 production archive에 남아 있어 무관")가 그대로 적용된다.
- 사람의 결정은 이 파일에 저장되지 않는다. 결정은 브리프(approved)와 pool/archive(`review_status`)에 있다.
- 규칙 기반 초안은 같은 브리프와 KNOWLEDGE로 결정적으로 다시 만들 수 있다. LLM 재작성 결과는 다시 만들 수 없지만, 그 결과도 bridge 후에는 pool에 보존된다(pool의 등급과 같다).
- **전제 조건:** `(content_id, generation_id) → brief_id` lineage는 이 파일에만 두면 안 된다. 승격 후 성과를 브리프로 귀속하려면 lineage가 Git 추적 파일에 있어야 한다. 그래서 lineage는 `tak_marketing_briefs.json`(A)에 저장한다(4장).
- 화이트리스트는 "커밋 가능하게 허용"만 한다. 실제 커밋 여부는 6-21 원칙대로 사람이 결정한다. 현재 이 Codespace에는 해당 data 파일이 없어서 이번 작업에서 data 파일을 커밋할 일은 없다.

**결정됨: `tak_market_demands.json`도 A(Git source of truth)로 둔다** (2026-10-04 사용자 승인)

- `tak_idea_candidates`가 `demand_ids`로 수요 레코드를 참조한다. 그리고 `draft`는 연결된 수요가 없으면 실패한다.
- 새 Codespace나 checkout에서도 Market Demand → Idea → MarketingBrief 흐름을 재현할 수 있어야 한다.
- 수동 입력 원천 데이터라서 재생성 가능한 cache가 아니다.

## 1-1. 구현 결과 (1단계)

- `.gitignore`: `tak_market_demands`, `tak_idea_candidates`, `tak_marketing_briefs`, `tak_marketing_suggestions` 화이트리스트를 추가했다. `tak_marketing_contents`와 `tak_media_generation_*`는 계속 무시한다.
- `scripts/audit_data_state.py`: 위 5개 파일을 FILE_SPECS에 등록했다(A 4개, C/D 1개). `export_operational_data.discover()`가 FILE_SPECS를 순회하므로 export에도 자동으로 들어간다. export 스크립트는 수정하지 않았다.
- `tests/test_marketing_persistence.py`가 다음을 고정한다.
  - A 파일은 Git 추적 가능하고, C/D 파일은 무시된다(`git check-ignore`).
  - audit 분류(A / C/D)가 맞다.
  - export가 마케팅 파일과 marketing pool 파일을 발견한다.
  - 새 환경 시뮬레이션: 환경 A에서 실제 CLI로 수요, 아이디어, 브리프를 만든 뒤 Git이 추적하는 파일만 환경 B로 복사한다. B에서도 demand → idea → brief 참조가 유지되고 `draft`가 다시 동작한다. demands가 없으면 `draft`가 실패한다는 음성 케이스도 확인한다.

## 2. YouTube 정합성

- Marketing 계층에서는 그대로 둔다: `brief.platform="youtube"`, 후보 `platform="youtube"`, YouTube 생성 계약과 `shorts_script`.
- MEDIA 경계에서 정규화한다. `generation.py`에 `media_platform(platform)`을 추가한다. `youtube`는 `shorts`로, 나머지는 그대로 매핑한다.
  - 후보에 `media_platform` 필드를 기록한다. 기존 `draft_platform`을 대체하고, 이 필드는 모든 플랫폼에 기록한다.
  - `content_id = compute_content_id({...record, "platform": media_platform})`로 계산한다. 기존 규칙 함수를 그대로 쓰고, 입력의 platform만 MEDIA 값으로 바꾼다.
- 그 결과는 다음과 같다.
  - `brief.content_ids`에 연결되는 ID가 production archive와 성과 데이터의 ID와 같아진다.
  - blog/threads/shorts의 content_id는 지금과 같다. 바뀌는 것은 youtube뿐이다.
- 테스트로 고정한다(실제 `--write` 전에).
  - youtube 후보의 content_id는 같은 KNOWLEDGE를 `run_media_batch`로 만든 shorts 항목을 `MediaArchiveRecord.from_item`에 넣었을 때의 content_id와 같아야 한다.
  - `platform`은 youtube로 유지되어야 한다.
  - youtube 후보와 shorts 후보의 content_id가 같은 슬롯에서 같아야 한다. 같은 콘텐츠 슬롯이고, 구분은 generation_id로 한다.

## 3. media_bridge.py (기존 MEDIA 모듈 수정 없음)

새 파일 `content_engine/marketing/media_bridge.py`:

- `candidate_to_batch_item(candidate) -> MediaBatchItem`(기존 `pipeline.MediaBatchItem` 사용)
  - 필드: `platform = media_platform`, `status`는 `rewritten → valid`, `rejected → rejected`, `error → error`, `rejection_reasons = validation_errors`, `error_message = rewrite_error`, 원본/재작성 텍스트, 근거, `created_at`은 그대로 옮긴다.
  - `rewrite_status == "not_requested"`는 **bridge 대상에서 제외**하고 사유를 반환한다. validator를 거치지 않은 후보가 `valid`로 들어가면 안 된다. 다시 하려면 `generate --rewrite mock|llm`으로 생성한다.
- `pool_path_for(data_dir, brief_id) -> data/tak_media_generation_marketing-<brief_id>.json`
  - 이름이 `GENERATION_POOL_GLOB`과 맞는지 assert한다. 그래야 대시보드와 export가 자동으로 발견한다.
- `bridge_to_generation_pool(candidates, pool_path, generation_id=None) -> BridgeResult`
  - 기존 `archive_generation_report(MediaBatchReport, path, generation_id)`를 호출한다.
  - `generation_id`는 기존 `new_generation_id(knowledge_id)` 형식을 쓰고, bridge 실행 1회에 브리프당 1개를 쓴다.
  - pool에는 **unreviewed**로만 들어간다. 승인, 승격, 발행을 하지 않으며 publisher도 import하지 않는다.
  - 같은 후보를 다시 bridge하면 기존 generation_id를 재사용한다. 후보에 기록된 `generation_id`가 있으면 그것을 쓰므로 중복 generation이 생기지 않는다.
- 브리프 게이트를 다시 확인한다. 저장소의 브리프가 지금도 `generation_blockers == []`일 때만 bridge한다.
- CLI: `marketing_brief.py bridge BRIEF_ID`. 기본은 미리보기이고, `--write`일 때만 pool에 쓰고 lineage를 기록한다.

## 4. lineage: (content_id, generation_id) → brief_id

- `MarketingBrief`에 `media_generations: tuple[MediaGenerationRef, ...]`를 추가한다. 항목은 `{content_id, generation_id}`이고, 기본값은 `()`라서 기존 JSON도 그대로 읽힌다. `to_dict`/`from_dict`도 대응한다.
- `store.link_media_generation(path, brief_id, content_id, generation_id)`를 추가한다. 중복 없이 추가하고, `content_ids`에도 `link_content`와 같은 규칙으로 연결한다.
- 저장 위치는 Git 추적 대상인 `tak_marketing_briefs.json`이다. 무시되는 contents나 pool이 사라져도 lineage는 남는다. MEDIA 스키마(`MediaArchiveRecord`)는 바꾸지 않는다.
- `lineage.resolve_brief(briefs, content_id, generation_id) -> brief_id | None`를 추가한다.
- `insight.collect_marketing_insights(briefs, snapshots, archive_records=None)`를 확장한다. 기존 호출과는 호환된다.
  - 스냅샷에 `generation_id`가 있으면 그 값을 쓴다. 없으면 production archive에서 그 content_id의 활성 레코드의 `generation_id`를 쓴다.
  - 그 generation이 이 브리프의 `media_generations`에 있을 때만 브리프에 귀속한다.
  - 같은 content_id의 기존 배치 버전(다른 generation_id) 성과는 마케팅 브리프로 잘못 귀속되지 않는다.
  - `archive_records`를 주지 않고 generation_id도 없으면 지금처럼 content_id만으로 매칭한다(하위 호환).

## 5. E2E 테스트 (`tests/test_marketing_e2e_lineage.py`, 임시 디렉터리, 네트워크 없음)

1. approved youtube 브리프와 approved KNOWLEDGE로 `generate_candidates(provider=MockRewriteProvider)`를 실행하고 `save_candidates`로 저장한다.
2. `bridge_to_generation_pool`로 pool 파일을 만든다. `discover_generation_pool_paths(data_dir)`가 이 파일을 발견하는지 확인한다(대시보드 함수를 import해서 사용).
3. 사람의 승인은 테스트 안에서 기존 `handle_generation_review_submission`으로 시뮬레이션한다. bridge 자체는 승인하지 않는다.
4. `plan_batch_promotion`이 해당 record를 `promote`로 계획하는지 확인한다. 실행 전에 production archive는 변하지 않아야 한다.
   - 실제 승격은 기존 `upsert_archive`로 수행한다(promote CLI `--execute`와 같은 경로).
5. production content_id로 `PerformanceRecord(platform="youtube")`를 만들고 `append_snapshot`으로 저장한다.
6. `latest_snapshot_per_content`와 `collect_marketing_insights(..., archive_records)`가 브리프 ID, 플랫폼, 속성까지 연결되는지 확인한다.
7. 음성 케이스를 확인한다.
   - 같은 content_id의 다른 generation(기존 배치) 성과는 귀속되지 않아야 한다.
   - not_requested 후보는 bridge되지 않아야 한다.
   - publisher와 urlopen이 호출되지 않아야 한다.

## 6. 변경 대상 파일

| 파일 | 변경 |
|---|---|
| `.gitignore` | 화이트리스트 3개 추가(+demands는 결정에 따름) |
| `scripts/audit_data_state.py` | FILE_SPECS에 마케팅 파일 등록(데이터 등록만, 로직 변경 없음) |
| `scripts/export_operational_data.py` | FILE_SPECS를 통해 자동 포함되므로 원칙적으로 변경 없음. 필요하면 주석만 추가 |
| `content_engine/marketing/generation.py` | `media_platform`, content_id 정규화 |
| `content_engine/marketing/models.py` | `MediaGenerationRef`, `MarketingBrief.media_generations` |
| `content_engine/marketing/store.py` | `link_media_generation` |
| `content_engine/marketing/media_bridge.py` | 신규 |
| `content_engine/marketing/lineage.py` | 신규(`resolve_brief`). 필요하면 media_bridge에 합친다 |
| `content_engine/marketing/insight.py` | `archive_records` 선택 인자 |
| `content_engine/marketing/__init__.py` | export |
| `scripts/marketing_brief.py` | `bridge` 명령 |
| tests | `test_marketing_generation.py`(youtube 기대값 갱신), 신규 `test_marketing_media_bridge.py`, `test_marketing_e2e_lineage.py`, audit 등록 테스트 |
| docs | 6-82(이 문서, 구현 결과 반영), 6-80에 링크, 6-81 커밋 |

수정하지 않는 것: `media_archive.py`, `pipeline.py`, `generator.py`, `run_scout_dashboard.py`, `promote_media_generation.py`, `performance/*`, publisher, `.vscode/`.

## 7. 커밋 순서

1. 보존 정책: `.gitignore`, audit 등록, 테스트, 6-81/6-82 문서
2. YouTube 정합성과 테스트
3. media_bridge, CLI `bridge`, 테스트
4. lineage(models/store/insight)와 테스트
5. E2E 테스트, 문서 갱신, 전체 테스트, diff check, secret scan

## 8. 구현 결과

| 단계 | 커밋 | 내용 |
|---|---|---|
| 1 | b60bde9 | 화이트리스트 4개, audit FILE_SPECS 5개, 6-81/6-82 문서, `test_marketing_persistence.py` |
| 2 | 95c086c | `media_platform`/`media_content_id`, youtube content_id 정규화, 6-80 갱신 |
| 3 | 0d21368 | `media_bridge.py`, CLI `bridge`, `test_marketing_media_bridge.py` |
| 4 | 53710bd | `MediaGenerationRef`/`media_generations`, `link_media_generation`, `lineage.py`, generation 인식 insights, `test_marketing_lineage.py` |
| 5 | 1f21e7c | `test_marketing_e2e_lineage.py` |

계획에서 달라진 점:

- export 스크립트는 수정하지 않았다. FILE_SPECS를 통해 자동으로 포함되므로 수정할 필요가 없었다.
- 후보의 `draft_platform` 필드를 없애고 모든 플랫폼에 `media_platform`을 기록한다.
- bridge 재실행 시 이미 `generation_id`가 있는 후보는 "이미 bridge됨"으로 건너뛴다. 새 generation을 만들지 않으므로 pool이 중복되지 않고 사람의 검토 상태도 그대로 남는다.
- E2E의 승격은 `upsert_archive`를 직접 호출하지 않고 기존 `promote_media_generation.py` CLI(`--execute`)를 그대로 실행한다.

### 불변조건과 테스트

| 불변조건 | 고정한 테스트 |
|---|---|
| Marketing youtube → MEDIA shorts | `test_marketing_generation.MediaPlatformInvariantTests.test_media_platform_mapping`, `test_youtube_keeps_marketing_platform_and_normalizes_media_platform`, `test_marketing_media_bridge.MappingTests.test_youtube_candidate_becomes_shorts_batch_item_with_same_content_id` |
| youtube의 media_content_id는 기존 shorts 기준 `compute_content_id`와 일치 | `MediaPlatformInvariantTests.test_youtube_media_content_id_matches_existing_shorts_rule`(`run_media_batch` + `MediaArchiveRecord.from_item`과 비교), `test_youtube_save_links_media_content_ids` |
| 기존 blog/threads/shorts content_id는 변경하지 않음 | `MediaPlatformInvariantTests.test_blog_threads_shorts_content_ids_unchanged` |
| (content_id, generation_id) lineage가 brief_id까지 추적 가능 | `test_marketing_lineage.*`, `test_marketing_media_bridge.CliTests.test_bridge_cli_records_lineage_in_brief`, `test_marketing_e2e_lineage.test_lineage_from_brief_to_insight`, `test_lineage_persisted_only_in_tracked_brief_file` |
| 다른 generation(기존 배치)의 같은 슬롯 성과는 귀속하지 않음 | `test_marketing_e2e_lineage.test_same_slot_from_batch_generation_is_not_attributed`, `test_marketing_lineage.ResolveAndInsightTests` |
| marketing candidate는 자동 승인/승격하지 않음 | `test_marketing_media_bridge.SafetyTests`, `PoolTests.test_pool_written_unreviewed_and_discovered`, E2E의 승인 전 `plan_batch_promotion` 결과가 모두 `skip`인지 확인 |
| not_requested rewrite는 valid로 위장하지 않음 | `test_marketing_media_bridge.MappingTests.test_not_requested_is_never_valid`, `CliTests.test_bridge_cli_skips_not_requested` |
| 기존 MEDIA 모듈은 수정하지 않음 | `SafetyTests.test_bridge_module_imports_only_pool_apis`(bridge가 쓰는 MEDIA API를 pool 쓰기 API로 한정, upsert_archive/save_archive/promote/publish 사용 금지). 파일 미변경은 아래 diff 검증으로 확인 |
| 새 환경에서 market demand → idea → brief 참조 유지 | `test_marketing_persistence.FreshEnvironmentTests`(Git이 추적하는 파일만 복사한 새 환경), `GitPolicyTests` |

"기존 MEDIA 모듈은 수정하지 않음"의 범위:

- 테스트가 직접 고정하는 것은 bridge가 사용하는 MEDIA API의 범위다.
- MEDIA 파일이 바뀌지 않았다는 사실은 테스트가 아니라 검증 절차로 확인했다(`git diff 52fb0bb HEAD`). 파일 해시를 테스트에 고정하면 앞으로의 정당한 MEDIA 수정까지 막기 때문이다.
- 이번 작업 전체에서 아래 파일은 변경되지 않았다: `media_archive.py`, `pipeline.py`, `generator.py`, `shorts_adapter.py`, `publish_history.py`, `performance/*`, `run_scout_dashboard.py`, `promote_media_generation.py`, `export_operational_data.py`, publisher, `threads_review.py`, `blog_publish_pack.py`.

### 운영 절차(요약)

```
python scripts/marketing_brief.py --write generate BRIEF_ID --rewrite mock|llm
python scripts/marketing_brief.py bridge BRIEF_ID              # 미리보기
python scripts/marketing_brief.py --write bridge BRIEF_ID      # pool 저장 + lineage 기록
# 대시보드 /media/generations 에서 사람이 검토/승인
python scripts/promote_media_generation.py --archive data/tak_media_generation_marketing-BRIEF_ID.json \
    --production-archive data/tak_media_archive.json --generation-id GEN_ID          # dry-run 후 --execute
git add data/tak_marketing_briefs.json ...   # A 파일 커밋은 사람이 결정(6-21 원칙)
```

같은 content_id의 다른 generation이 이미 production에 있으면 기존 promote가 `conflict`로 막는다. 그 경우의 처리(supersede 등)는 기존 6-17/6-18 절차를 따른다.
