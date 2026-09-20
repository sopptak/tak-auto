# TAK AUTO 6-02 — 발행 이력 연결 및 성과 운영화

## 1. 작업 시작 상태

- 브랜치: `main`
- 로컬 HEAD(시작 시점): `f2988da` (docs: record final commit/push confirmation in 6-01 report)
- `origin/main`과 완전히 동기화된 상태에서 시작(`git fetch` 후 `git log origin/main..HEAD` 결과 비어 있음 확인).
- `git status --short`(시작 시점) 기준 기존 미커밋 변경 — 전부 6-01 시점과 동일하게 보존, 이번 세션에서 건드리지 않음:
  - modified: `.gitignore`, `content_engine/__init__.py`, `content_engine/generator.py`, `content_engine/llm_provider.py`, `content_engine/rewrite.py`, `data/tak_brain_knowledge.json`, `tests/test_content_engine.py`, `tests/test_media_batch.py`
  - untracked: `.firebaserc`, `.github/workflows/youtube-shorts-upload.yml`, `content_engine/shorts_renderer.py`, `data/blog_draft_*.md`, `data/shorts_scripts/`(`example_manman.json` 포함), 다수 `docs/*.md`, `firebase.json`, `public/`, `requirements.txt`, `scripts/mark_blog_published.py`, `scripts/render_youtube_short.py`, `scripts/run_scout_score.py`, `scripts/youtube_oauth_setup.py`, `tests/test_firebase_hosting.py`, `tests/test_render_youtube_short_cli.py`, `tests/test_scout_scoring.py`, `tests/test_shorts_renderer.py`, `tests/test_shorts_script.py`, `tests/test_threads_dashboard.py`, `tests/test_threads_review.py`, `tests/test_youtube_oauth_setup.py`, **`tests/test_youtube_publisher.py`**, **`tests/test_youtube_upload_history.py`**, `tests/test_youtube_upload_history.py`
- 전체 pytest(작업 시작 시점, 재실행으로 재확인): **762 passed, 68 subtests, 0 failed** — 6-01 종료 시점과 동일.

## 2. 이전 6-01 결과 검증

6-01 보고서의 "남은 문제"/"다음 5~6시간 작업"을 실제 코드/데이터로 다시 확인했다:

| 6-01이 남긴 문제 | 이번 세션에서 재확인한 실제 상태 |
|---|---|
| 실제 production `data/tak_media_archive.json`이 없다 | **여전히 없다**(`ls` 결과 확인) — 브라우저로 Dashboard를 조작하는 것은 이번 세션에서도 도구 권한상 불가능해 미실행으로 기록한다. |
| `data/youtube_publish_log.json`에 content_id/knowledge_id 없음 | 그대로 확인(1건, `video_id=h2X1fFMDffc`, privacy=private, content_id/knowledge_id 필드 자체가 없음) — 이번 세션 3~4장에서 이 문제를 실제로 해결했다. |
| `scripts/collect_performance.py` GitHub Actions 미연결 | 여전히 미연결(의도적, 6장 참고) — 이번 세션에서도 workflow를 새로 만들지 않았다. |
| `/performance` 화면이 최신 스냅샷만 표시 | 이번 세션 5장에서 시계열 추이로 확장했다. |
| `data/shorts_scripts/example_manman.json` 출처 불명 | 이번 세션에서도 다루지 않음(범위 밖, 16장에서 재언급). |

추가로 6-01 이후 실제 운영 데이터가 늘어난 것을 확인했다(8장에서 상세): `data/threads_publish_log.json`이 6-01 시점 2건 → 이번 세션 확인 시 **7건**으로 늘어났다(`TAK Threads Daily Post` workflow가 스케줄대로 계속 실행되며 쌓인 실제 게시 이력, 이번 세션이 만든 데이터 아님).

## 3. YouTube 발행 이력 구조 분석

`content_engine/youtube_upload_history.py`/`scripts/upload_youtube_short.py`/`tests/test_upload_youtube_short_cli.py`를 다시 읽었다.

- `YouTubeUploadRecord`(frozen dataclass): `video_id, uploaded_at, title, privacy_status, video_path="", tags=()` — `content_id`/`knowledge_id` 필드 자체가 없었다.
- `YouTubeUploadHistory.load()`는 저장된 JSON을 **파싱하지 않고 원본 dict 그대로 반환**한다(`PublishHistory`/`MediaArchive`와 다른 설계 — 이 모듈만의 기존 관례, 이번 세션에서 바꾸지 않았다).
- `tests/test_upload_youtube_short_cli.py`의 주석에서 **실제 사고 기록을 발견했다**: "5-17 실측: 실제 계정에 테스트 영상이 업로드됨" — 과거에 subprocess로 CLI를 테스트하다 환경변수의 실제 자격증명을 그대로 물려받아 실제 YouTube에 업로드된 사고가 있었고, 그 이후 이 테스트 파일은 subprocess 대신 `main()`을 같은 프로세스에서 직접 호출하고 `YouTubeClient.from_environment`를 항상 patch하는 방식으로 바뀌어 있었다. 이 안전한 테스트 방법론을 이번 세션의 새 테스트에도 동일하게 적용했다(9장/13장).
- `content_engine/youtube_upload_history.py`/`scripts/upload_youtube_short.py`/`tests/test_upload_youtube_short_cli.py` 세 파일 모두 `git status`상 이미 커밋된 clean 파일임을 확인 — 직접 수정해도 기존 미커밋 변경과 섞이지 않는다. 반면 `tests/test_youtube_upload_history.py`는 이번 세션 시작 시점에 이미 untracked 상태였다 — 이 파일은 건드리지 않기로 했다(4장에서 상세).

## 4. YouTube content_id / knowledge_id 연결 구현

### 4.1 모델 확장

`content_engine/youtube_upload_history.py`의 `YouTubeUploadRecord`에 `content_id: str = ""`, `knowledge_id: str = ""`를 추가했다(둘 다 기본값 빈 문자열). `to_dict()`에도 두 키를 포함시켰다.

**backward compatibility 검토**: 기본값이 있으므로 기존 호출부(`YouTubeUploadRecord(video_id=..., uploaded_at=..., title=..., privacy_status=...)`처럼 4개 필수 인자만 넘기던 코드)는 전혀 수정 없이 그대로 동작한다. `YouTubeUploadHistory.load()`가 원본 dict를 그대로 반환하는 기존 설계 덕분에, `content_id`/`knowledge_id` 키가 아예 없는 과거 JSON 레코드를 읽어도 에러가 나지 않는다(그 키가 없는 dict 그대로 반환될 뿐) — 이 사실을 `tests/test_youtube_upload_history_content_id.py::test_legacy_records_without_content_id_still_load_as_raw_dicts`로 직접 검증했다.

### 4.2 CLI 확장

`scripts/upload_youtube_short.py`에 `--content-id`/`--knowledge-id`(둘 다 선택)를 추가했다.

**Validation 규칙(4가지 조합 검토 결과)**:

| content_id | knowledge_id | 결과 |
|---|---|---|
| 있음 | 있음 | 허용 — 둘 다 `YouTubeUploadRecord`에 저장 |
| 있음 | 없음 | **거부**(exit 1) — content_id만 있으면 어느 KNOWLEDGE에서 나왔는지 알 수 없는 반쪽 데이터가 저장된다 |
| 없음 | 있음 | **거부**(exit 1) — knowledge_id만으로는 `compute_content_id()`로 계산된 정확한 지문과 연결이 안 된다 |
| 없음 | 없음 | 허용(기본값, 기존 동작과 완전히 동일) — **backward compatibility 100% 유지** |

이 규칙은 `PerformanceRecord.__post_init__()`이 이미 두 값을 모두 필수로 요구하는 것과 의도적으로 동일하다 — 절반만 있는 연결 정보를 저장소 어디에도 허용하지 않는다는 원칙을 일관되게 적용했다.

이 validation은 `--dry-run`에서도 동작한다(사람이 실제 업로드 전에 명령을 미리 검증할 수 있게).

### 4.3 실제 업로드는 실행하지 않음

이번 세션에서 `scripts/upload_youtube_short.py`를 `--dry-run` 없이 실행한 적이 **단 한 번도 없다**. 모든 검증은 `tests/test_upload_youtube_short_cli.py`(기존 clean 파일, 이어서 작성)에 추가한 6개 신규 테스트로 수행했으며, 전부 3장에서 발견한 안전한 방법론(`main()` 직접 호출 + `YouTubeClient.from_environment` 항상 patch)을 그대로 따른다 — 실제 네트워크가 전혀 일어나지 않는다.

## 5. Performance Dashboard 시계열 구현

### 5.1 새 모듈: `content_engine/performance/summary.py`

순수 함수로만 구성된 신규 모듈(파일 I/O 없음):

- `summarize_content_history(records)` → `ContentPerformanceSummary`(첫/이전/최신 스냅샷, 전체 이력 `history`, 스냅샷 개수).
- `ContentPerformanceSummary.metric_delta()` — 최초 대비 최신 변화량. **두 스냅샷 모두에 있는 metric만 계산**한다(한쪽에만 있으면 0으로 채우지 않고 제외 — 4장 지시 "없는 metric을 0으로 만들어서는 안 된다"를 그대로 지켰다).
- `ContentPerformanceSummary.baseline_is_migration` — 첫 스냅샷의 `source`가 `migration_baseline`인지. True면 화면에 경고를 띄운다(4장 지시 "실제 성과 비교의 기준점으로 오해하지 않도록 표시").
- `pick_headline_metric(records)` — 대표 지표를 **하드코딩하지 않고** 실제 존재하는 metric 키에서 고른다(`views`가 있으면 그것을, 없으면 알파벳순 첫 키).
- `render_text_trend(records, metric_name)` — `"100 → 430 → 2,300"` 형태의 순수 텍스트 추이. 새 차트 라이브러리/JS 프레임워크를 추가하지 않았다(16장 원칙 그대로 준수).

### 5.2 설계 중 발견/수정한 버그

처음에는 `ContentPerformanceSummary`가 `first`/`previous`/`latest` 3개 레코드만 들고 있었는데, **스냅샷이 정확히 2개일 때 `first`와 `previous`가 같은 레코드를 가리켜** 추이 텍스트가 `"100 → 100 → 850"`처럼 중복 표시되는 버그를 테스트 작성 중 발견했다. `ContentPerformanceSummary`에 전체 시간순 이력(`history: tuple[PerformanceRecord, ...]`)을 추가로 들고 있도록 고쳐서 해결했고, `tests/test_performance_summary.py::test_history_holds_full_ordered_snapshots_not_just_first_previous_latest`와 `test_two_snapshots_do_not_duplicate_the_first_value`로 회귀를 막았다.

### 5.3 Dashboard 연결

`scripts/run_scout_dashboard.py`의 `/performance` 라우트를 `latest_snapshot_per_content()`(최신 1건만) 대신 `load_snapshots()` 전체 → content_id별로 그룹화 → `summarize_content_history()`로 바꿨다. 화면에 표시되는 정보(4장 지시 항목과 대조):

| 지시 항목 | 구현 여부 |
|---|---|
| 제목 | ✅ (archive의 `final_title` 참고, 6-01부터 있던 로직 재사용) |
| platform | ✅ |
| published_at | ✅ |
| 최근 수집시각 | ✅ |
| 최근 metrics | ✅ |
| 이전 metrics | ✅(신규) |
| snapshot 개수 | ✅(신규) |
| 최초 대비 변화량 | ✅(신규, `metric_delta()`) |

## 6. 성과 수집 CLI 안전장치

### 6.1 설계

`scripts/collect_performance.py`에 `--confirm-live` 플래그와 `_guard_live_network_call()` 순수 판단 함수를 추가했다:

- `--dry-run`: 항상 허용(기존과 동일).
- `--dry-run`도 `--confirm-live`도 없음: **거부**(이전에는 이 조합이 "진짜 호출"이었다 — 이번에 가장 위험했던 기본 동작을 안전한 기본값으로 바꿨다).
- `--confirm-live`만 있음: `GITHUB_ACTIONS=true`가 아니면 허용.
- `GITHUB_ACTIONS=true`: `--confirm-live`를 줘도 거부.
- `--platform blog`: 이 게이트의 적용을 받지 않는다(네트워크 자체가 없음).

**5장 지시("기존 publish_threads.py / upload_youtube_short.py의 기존 운영 방식을 함부로 변경하지 않는다")를 그대로 지켰다** — 이 두 기존 스크립트는 전혀 수정하지 않았다. `collect_performance.py`는 아직 실제 운영에 쓰인 적이 없는 신생 스크립트(6-01에서 처음 만듦)라 더 엄격한 기본값으로 바꿔도 기존 사용자의 실제 사용 패턴을 깨뜨릴 위험이 없다고 판단했다.

### 6.2 테스트로 증명

신규 파일 `tests/test_collect_performance_live_gate.py`(20개 테스트)로 5장이 요구한 5가지를 전부 검증했다:

1. credential 환경변수가 있어도 기본 실행은 외부 API를 호출하지 않는다 → `test_threads_without_any_flag_never_creates_client`/`test_youtube_without_any_flag_never_creates_client` — `ThreadsClient`/`YouTubeClient.from_environment`를 "호출되면 AssertionError"로 patch해 두고 실행, `mocked.assert_not_called()`로 직접 증명.
2. 명시 옵션 없으면 네트워크 접근 안 함 → 위와 동일.
3. mock transport로 정상 성과 수집 → `test_threads_confirm_live_proceeds_with_mocked_client`/`test_youtube_confirm_live_proceeds_with_mocked_client` — `--confirm-live` + `from_environment`를 fake client로 patch, 실제 저장까지 end-to-end로 확인.
4. blog manual collection은 기존처럼 정상 동작 → `test_blog_does_not_require_confirm_live`(6-01 기존 테스트들도 전부 그대로 재확인).
5. 실제 token 값이 노출되지 않음 → `test_configuration_error_after_confirm_live_does_not_leak_token`.

## 7. Performance store 검증

### 7.1 중복 판정 키에 source를 포함할지 검토

`(content_id, metric_collected_at)`이 같은데 `source`가 다른 경우를 검토했다. **결론: source를 키에 포함하지 않는다(기존 동작 유지)** — 같은 순간의 측정값이 서로 다르면 어느 쪽이 맞는지 이 저장소가 판단할 근거가 없고, 실제 운영 데이터가 아직 없어 "같은 순간을 다른 source로 교정하고 싶다"는 요구가 검증된 적이 없기 때문이다. `content_engine/performance/store.py`의 `_snapshot_key()` 옆에 이 결정과 근거를 문서화했고, `tests/test_performance_store.py::test_same_content_and_time_different_source_is_still_a_duplicate`로 "의도된 동작"임을 테스트로 고정했다(나중에 요구가 생기면 `overwrite=True` 옵션 추가를 권장한다고 코드에 남겨둠 — 지금 만들지는 않음).

### 7.2 timezone 처리 버그 발견 및 수정

`snapshots_for_content()`/`latest_snapshot_per_content()`가 `metric_collected_at` 문자열을 **사전식(lexicographic) 비교**로 정렬하고 있었다 — 전부 같은 timezone offset이면 우연히 맞지만, tz-naive 값과 aware 값이 섞이거나 offset이 다르면(`+09:00` vs `+00:00`) 실제 시간 순서와 어긋난다는 것을 확인했다. `_sort_key()`를 추가해 `datetime.fromisoformat()`으로 파싱 후 비교하도록 고쳤다(tz-naive는 UTC로 간주 — `tak_scout/scoring.py`의 `_parse_datetime()`과 동일한 규칙을 이 패키지 안에 복제, `content_engine`이 `tak_scout`을 import하는 새 패키지 의존성은 만들지 않았다). 파싱 실패 값은 예외 없이 맨 앞으로 보낸다.

`tests/test_performance_store.py`에 실제로 **문자열 비교라면 틀리게 정렬됐을** 케이스(`"2026-09-16T23:00:00+09:00"`의 실제 UTC 시각이 `"2026-09-17T00:00:00+00:00"`보다 이른 경우)를 재현하는 테스트를 추가해 수정을 검증했다.

## 8. 실제 production 데이터 검증 결과

읽기 전용으로 확인했다(어떤 파일도 쓰지 않음, `git status --short data/`로 재확인):

| 파일 | 상태 |
|---|---|
| `data/threads_publish_log.json` | **실제 데이터 7건** 존재(6-01 시점엔 2건 — 스케줄 workflow가 계속 쌓은 것). 전부 `content_id`/`knowledge_id`/`threads_post_id` 갖춤. |
| `data/youtube_publish_log.json` | 실제 데이터 1건(`video_id=h2X1fFMDffc`, privacy=private, 5-16/5-17 테스트 업로드로 추정). `content_id`/`knowledge_id` 없음 — 6-02 이전에 만들어진 legacy 기록이라 정상. |
| `data/blog_publish_log.json` | **없음**(아직 실제 Blog 게시가 없었다는 뜻 — 없다고 그대로 기록). |
| `data/tak_media_archive.json` | **없음**(5-31/6-01부터 이어지는 미해결 사항, 여전히 미해결). |

`content_engine/performance/migration.py`의 `migrate_threads_or_blog_baseline_records()`를 실제 `data/threads_publish_log.json`(7건) 로드 결과에 **읽기 전용으로** 실행해봤다(파일에 쓰지 않음, 메모리상 계산만) — 7건 모두 정상적으로 baseline `PerformanceRecord`로 변환 가능함을 확인했다. **이 결과를 실제로 저장하지는 않았다**(7장 지시 "migration을 실제 production 파일에 실행하지 않는다"를 그대로 지켰다 — 저장 여부는 사람의 판단이 필요한 별도 결정으로 남긴다, 16장).

## 9. 테스트 결과

신규 테스트 파일:

- `tests/test_youtube_upload_history_content_id.py`(4개) — YouTubeUploadRecord content_id/knowledge_id
- `tests/test_collect_performance_live_gate.py`(9개) — `--confirm-live` 안전 게이트
- `tests/test_performance_summary.py`(14개) — 시계열 요약/추이 순수 함수

기존 파일에 추가한 테스트:

- `tests/test_upload_youtube_short_cli.py` — content_id/knowledge_id validation 6개 케이스 추가(기존 clean 파일)
- `tests/test_performance_store.py` — 중복판정 source 무관 확인 1개 + timezone 정렬 4개 추가
- `tests/test_performance_dashboard.py` — 시계열 표시(이전 metrics/변화량/추이/baseline 경고) 3개로 재작성

전체 pytest(작업 종료 직전):

```
807 passed, 68 subtests passed in 124.67s (0:02:04)
```

**0 failed.** 시작 시점(762 passed) 대비 45건 추가, 기존 테스트는 전부 그대로 통과 — 회귀 없음.

## 10. 보안 검증

- 새로 만들거나 수정한 파일 어디에도 `secrets.`, 하드코딩된 토큰/키 문자열이 없다.
- `.github/workflows/*.yml`을 이번 세션에서 전혀 수정하지 않았다(`git status`로 재확인).
- 실제 토큰 값을 Markdown 보고서(이 문서, `docs/performance_operations.md`)나 코드 주석 어디에도 출력/기록하지 않았다 — 이 문서에 등장하는 값은 전부 공개된 실제 post_id(threads_post_id, video_id)나 예시 placeholder뿐이다.
- `--confirm-live` 게이트 자체가 새로운 보안 계층이다(6장).

## 11. 외부 API 호출 여부

**전부 없음.** 이번 세션에서 실행한 모든 명령/테스트를 기준으로:

- `scripts/upload_youtube_short.py`를 `--dry-run` 없이 실행한 적 없음(4장).
- `scripts/collect_performance.py`를 `--platform threads`/`--platform youtube` + `--confirm-live` 조합으로 **실제 환경변수를 사용해** 실행한 적 없음 — `--confirm-live`를 테스트한 모든 경우 `ThreadsClient`/`YouTubeClient.from_environment`를 mock/fake로 patch했다(6장).
- LLM 호출 없음(새 코드 어디에도 `llm_provider` import 없음).
- Naver 로그인/스크래핑 없음(애초에 그런 코드가 없다).

## 12. 변경 파일

**신규 파일:**

- `content_engine/performance/summary.py`
- `docs/performance_operations.md`
- `docs/6-02_publish-performance-operationalization.md`(이 파일)
- `tests/test_youtube_upload_history_content_id.py`
- `tests/test_collect_performance_live_gate.py`
- `tests/test_performance_summary.py`

**기존 파일 수정(전부 작업 시작 시점에 이미 git에 커밋된 clean 파일):**

- `content_engine/youtube_upload_history.py` — `content_id`/`knowledge_id` 필드 추가.
- `content_engine/performance/__init__.py` — summary 함수 재노출.
- `content_engine/performance/store.py` — timezone-safe 정렬(`_sort_key`), 중복판정 키 설계 문서화.
- `scripts/upload_youtube_short.py` — `--content-id`/`--knowledge-id` 인자 + validation.
- `scripts/collect_performance.py` — `--confirm-live` 게이트.
- `scripts/run_scout_dashboard.py` — `/performance` 시계열 렌더링으로 교체.
- `tests/test_upload_youtube_short_cli.py` — content_id/knowledge_id 테스트 추가.
- `tests/test_collect_performance_cli.py` — 안전 게이트 관련 docstring 갱신.
- `tests/test_performance_store.py` — 중복판정/timezone 테스트 추가.
- `tests/test_performance_dashboard.py` — 시계열 표시 테스트로 재작성.

**의도적으로 건드리지 않은, 작업 시작 시점에 이미 미커밋 상태였던 파일**: `tests/test_youtube_upload_history.py`(6-01과 동일한 이유 — 이 파일에 이어 쓰면 무관한 이전 세션 내용이 섞인다. 대신 신규 파일 `tests/test_youtube_upload_history_content_id.py`로 분리했다).

## 13. 기존 미커밋 변경 보존 확인

작업 종료 시점 `git status --short`를 시작 시점과 비교했다 — 1장에 나열한 기존 미커밋 변경(`.gitignore`, `content_engine/__init__.py`, `content_engine/generator.py`, `content_engine/llm_provider.py`, `content_engine/rewrite.py`, `data/tak_brain_knowledge.json`, `tests/test_content_engine.py`, `tests/test_media_batch.py`, 그 외 모든 untracked 파일)가 **글자 하나 바뀌지 않고 그대로** 남아 있음을 확인했다 — commit 직전 `git status --short` 전체 출력에서 이 파일들의 상태(`M`/`??`)가 1장 기록과 정확히 동일했고, `git add`에 이 파일들을 하나도 넘기지 않았으므로 staging에도 포함되지 않았다(14장 commit 결과 참고).

## 14. Commit

`git status --short`로 staging 대상을 먼저 확인한 뒤, 이번 작업에서 실제로 만들거나 수정한 파일 16개만 파일명을 하나씩 나열해 `git add`했다(`git add .`/`git add -A` 사용하지 않음). staging 결과를 다시 `git status --short`로 확인해 의도한 파일만 `A`/`M`으로 표시되고 1장에 나열한 기존 미커밋 변경은 전부 여전히 공백+`M`(unstaged)로 남아 있음을 확인한 뒤 커밋했다:

```
[main 9e99a47] feat: operationalize publish performance tracking
 16 files changed, 1475 insertions(+), 45 deletions(-)
 create mode 100644 content_engine/performance/summary.py
 create mode 100644 docs/6-02_publish-performance-operationalization.md
 create mode 100644 docs/performance_operations.md
 create mode 100644 tests/test_collect_performance_live_gate.py
 create mode 100644 tests/test_performance_summary.py
 create mode 100644 tests/test_youtube_upload_history_content_id.py
```

## 15. Push

```
$ git push
To https://github.com/sopptak/tak-auto
   f2988da..9e99a47  main -> main

$ git fetch origin
(변경 없음)

$ git log origin/main..HEAD --oneline
(빈 결과)

$ git status --short | grep "^[MA]"
(빈 결과 - 커밋 대상이었던 파일 중 unstaged/staged로 남은 것 없음)
```

`origin/main`이 로컬 HEAD(`9e99a47`)와 완전히 일치함을 확인했다. push 성공.

## 16. 남은 문제

1. **실제 production `data/tak_media_archive.json`이 여전히 없다** — 5-31부터 세 세션째 이어지는 최우선 미해결 사항. 브라우저 조작이 필요해 이 세션들의 도구 권한으로는 해결할 수 없다.
2. `data/blog_publish_log.json`도 없다 — 실제 Blog 게시가 한 번도 기록된 적이 없다.
3. `data/youtube_publish_log.json`의 legacy 1건(`h2X1fFMDffc`)은 이번에 추가한 `content_id`/`knowledge_id` 필드가 없는 채로 남아 있다 — `migrate_youtube_baseline_records()`로 채우려면 이 영상이 실제로 어떤 KNOWLEDGE에서 나왔는지 사람이 먼저 확인해야 한다(추측 금지).
4. `data/threads_publish_log.json`(실제 7건)에 대한 baseline migration을 실행할지는 사람의 판단이 필요하다 — 이번 세션은 "가능하다"는 것만 읽기 전용으로 검증했다.
5. `scripts/collect_performance.py`를 GitHub Actions에 연결하는 workflow가 여전히 없다(의도적 — 6장).
6. `data/shorts_scripts/example_manman.json` 출처 불명 문제는 이번에도 다루지 않았다.
7. `--confirm-live` 게이트는 이 CLI 하나에만 적용했다 — `scripts/publish_threads.py`/`scripts/upload_youtube_short.py`는 여전히 "`--dry-run` 없으면 실제 호출"이다(5장 지시로 의도적으로 유지). 이미 실제로 사고가 한 번 있었던 이력(3장)을 생각하면, 같은 종류의 게이트를 이 두 스크립트에도 확장할지는 사람이 판단할 문제로 남긴다.

## 17. 다음 5~6시간 작업 제안

1. **실제 MEDIA 승인 최소 1건**(16장 1번) — 세 세션째 이어지는 최우선 과제. 사람이 직접 Dashboard를 열어 승인해야 한다.
2. YouTube legacy 레코드(`h2X1fFMDffc`)의 실제 content_id/knowledge_id를 사람이 확인해 `migrate_youtube_baseline_records()`로 채울지 결정.
3. `data/threads_publish_log.json`(실제 7건)에 baseline migration을 실제로 실행할지 결정 — 실행한다면 `data/tak_performance.json`에 7개의 `source="migration_baseline"` 레코드가 생기고, 이후 `--confirm-live`로 실제 성과를 한 번 수집해 `/performance` 화면에서 첫 실사용 데이터를 확인할 수 있다.
4. `scripts/publish_threads.py`/`scripts/upload_youtube_short.py`에도 `--confirm-live`류 게이트를 확장할지 결정(16장 7번, 실제 사고 이력이 있으므로 우선순위 있음 — 단 기존 운영 스크립트라 신중한 논의 필요).
5. `/performance` 화면에 "여러 content_id를 knowledge_id/카테고리 단위로 묶어 비교"하는 집계 뷰 추가(현재는 content_id 단위 나열만 지원).
6. `docs/performance_operations.md`를 실제 운영 경험이 쌓이면 갱신(현재는 설계 시점 기준 작성).
