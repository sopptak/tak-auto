# TAK AUTO 6-03 — KNOWLEDGE → MEDIA 실제 생성 파이프라인 검증

## 1. 작업 시작 상태

- 브랜치: `main`
- 로컬 HEAD(시작 시점): `025916d` (docs: record final commit/push confirmation in 6-02 report)
- `git fetch origin` 후 `git log origin/main..HEAD` 결과 비어 있음 — `origin/main`과 완전히 동기화된 상태에서 시작.
- `git status --short`(시작 시점) 기준 기존 미커밋 변경(전부 보존, 이번 세션에서 건드리지 않음):
  - modified: `.gitignore`, `content_engine/__init__.py`, `content_engine/generator.py`, `content_engine/llm_provider.py`, `content_engine/rewrite.py`, `data/tak_brain_knowledge.json`, `tests/test_content_engine.py`, `tests/test_media_batch.py`
  - untracked: `.firebaserc`, `.github/workflows/youtube-shorts-upload.yml`, `content_engine/shorts_renderer.py`, `data/blog_draft_*.md`, `data/shorts_scripts/`(`example_manman.json` 포함), 다수 `docs/*.md`, `firebase.json`, `public/`, `requirements.txt`, `scripts/mark_blog_published.py`, `scripts/render_youtube_short.py`, `scripts/run_scout_score.py`, `scripts/youtube_oauth_setup.py`, `tests/test_firebase_hosting.py`, `tests/test_render_youtube_short_cli.py`, `tests/test_scout_scoring.py`, `tests/test_shorts_renderer.py`, `tests/test_shorts_script.py`, `tests/test_threads_dashboard.py`, `tests/test_threads_review.py`, `tests/test_youtube_oauth_setup.py`, **`tests/test_youtube_publisher.py`**, **`tests/test_youtube_upload_history.py`**
- 전체 pytest(작업 시작 시점, 재실행으로 재확인): **807 passed, 68 subtests, 0 failed** — 6-02 종료 시점과 정확히 동일.

## 2. 6-02 결과 검증

6-02 보고서의 "남은 문제"를 실제 코드/데이터로 다시 확인했다:

| 6-02가 남긴 문제 | 이번 세션에서 재확인한 실제 상태 |
|---|---|
| 실제 production `data/tak_media_archive.json`이 없다 | **여전히 없다**(4장에서 상세 — 이번 세션의 핵심 조사 대상) |
| `data/blog_publish_log.json`도 없다 | 여전히 없음(재확인만) |
| YouTube legacy 1건에 content_id/knowledge_id 없음 | 그대로(6-02에서 이미 해결한 CLI 옵션은 신규 업로드부터만 적용 - 이번 세션 범위 아님) |
| threads_publish_log.json baseline migration 미실행 | 이번 세션에서도 실행하지 않음(범위 아님) |
| `--confirm-live` 게이트가 collect_performance.py에만 적용됨 | 이번 세션에서 다루지 않음(범위 아님, 이번 세션 핵심은 KNOWLEDGE→MEDIA) |

## 3. 현재 KNOWLEDGE 실제 데이터 상태

`data/tak_brain_knowledge.json`을 읽기 전용으로 확인했다(수정하지 않음):

- 전체 **28건**
- `knowledge_review_status` 분포: **approved 6건 / pending 13건 / rejected 9건**

approved 6건의 `id`/`article_type`/`domain`/제목:

| knowledge_id | article_type | domain | 제목(일부) |
|---|---|---|---|
| `knowledge-da6ddf5aa459` | `None` | 자기계발 | 57화) 개발을 모르는 내가 앱을 만들다 |
| `knowledge-e1cc05264953` | `finance` | 금융 | 은행에서 대출받을 때 재무제표에서 가장 먼저 보는 것은? |
| `knowledge-da8e52862a79` | `workplace` | 직장·인간관계 | 직장에서 인정받는 사람은 일을 잘하는 것보다 이것을 잘한다 |
| `knowledge-a3f43f9bb62e` | `workplace` | 직장·인간관계 | 거절을 잘하는 사람이 직장에서 더 신뢰받는 이유, 23년차 직장인이 보니 |
| `knowledge-scout-b28b782b2a33` | `finance` | 금융 | Anthropic boss Dario Amodei calls for AI... |
| `knowledge-scout-6d1d0e2fa762` | `finance` | 금융 | Uncontrolled AI could lead to 'silicon species' ri... |

KNOWLEDGE 레코드의 실제 필드 구조(첫 approved 레코드 기준, 읽기 전용 확인): `id, title, source_url, source_raw_id, category, domain, article_type, knowledge_type, evidence, key_points, lesson, opinion, judgment_rule, derived_insight, reusable_principle, factual_information, experience, case, problem, decision, action, result, inference_method, confidence, current_validity, privacy_risk, internal_information_risk, verification_required, knowledge_review_status, review_note, reviewed_at, created_at`. 이 레코드의 `created_at=2026-09-10T10:03:26+00:00`, `source_url=https://blog.naver.com/tmong2/224407187378...`, `evidence` 3건 확인 — 질문에서 언급된 `approved_at` 필드는 실제로는 없고 `reviewed_at`이 그 역할을 한다(추측하지 않고 실제 스키마를 그대로 기록).

**approved KNOWLEDGE는 실제로 존재한다 — "approved가 없다"는 것은 이번 사례의 원인이 아니다.** 이 6건 중 4건(`da6ddf5aa459`, `e1cc05264953`, `da8e52862a79`, `a3f43f9bb62e`)은 이미 `data/threads_publish_log.json`에 게시 이력이 있다(8장에서 상세) — 즉 이 KNOWLEDGE들은 이미 실제로 MEDIA 생성을 거쳐 Threads에 게시까지 된 적이 있다는 뜻이다. 이 파일은 이번 세션 전체에서 한 번도 쓰기 작업을 하지 않았다(`git status --short data/tak_brain_knowledge.json`이 세션 시작 시점과 동일).

## 4. 현재 MEDIA 실제 데이터 상태

읽기 전용으로 확인:

| 파일 | 상태 |
|---|---|
| `data/tak_media_archive.json` | **존재하지 않음**(5-31부터 네 세션째 이어지는 사실) |
| `data/threads_publish_log.json` | 존재, 실제 게시 이력 7건(6-02와 동일, 이번 세션에서 늘지 않음) |
| `data/blog_publish_log.json` | 존재하지 않음 |
| `data/youtube_publish_log.json` | 존재, 1건(legacy, content_id/knowledge_id 없음) |
| `data/tak_performance.json` | 존재하지 않음 |

## 5. KNOWLEDGE → MEDIA 코드 흐름

`scripts/run_scout_dashboard.py`, `content_engine/media_archive.py`, `content_engine/pipeline.py`(질문에서 언급된 `content_engine/media_batch.py`는 실재하지 않고 `content_engine/pipeline.py`가 그 역할을 한다 — grep으로 확인), `content_engine/generator.py`, `content_engine/rewrite.py`, `content_engine/llm_provider.py`, `data/tak_brain_knowledge.json`, `tak_brain/` 전체를 읽었다.

실제 데이터 흐름(코드 기준):

```
data/tak_brain_knowledge.json (KNOWLEDGE, knowledge_review_status)
   │  tak_brain.load_knowledge_records() + select_approved()
   ▼
승인된 KnowledgeRecord 목록 (knowledge_review_status == "approved"만)
   │  content_engine.generator.generate_content_bundle(knowledge)
   │    -> KNOWLEDGE 1건당 ContentDraft 9개(Blog 1 + Shorts 3 + Threads 5) 결정적으로 생성
   ▼
content_engine.pipeline.run_media_batch(records, provider=...)
   │  각 Draft를 RewriteService(provider).rewrite()로 재작성 + RewriteValidator로 검증
   │  provider가 None이면 기본값 MockRewriteProvider()(네트워크 없음) 사용
   ▼
MediaBatchReport (items: MediaBatchItem 9*N개, valid/rejected/error)
   │  content_engine.media_archive.archive_report(report, archive_path)
   │    -> compute_content_id()로 content_id 계산, review_status="unreviewed"로 신규 upsert
   ▼
data/tak_media_archive.json (MediaArchiveRecord 목록, JSON 배열)
   │  scripts/run_scout_dashboard.py: load_archive(config.media_archive_path)
   ▼
GET /media (Dashboard) - KNOWLEDGE별로 그룹화해 카드 렌더링
   │  사람이 "상세보기" -> GET /media/{content_id} -> 승인 폼
   ▼
POST /media/{content_id}/approve -> handle_media_approve_submission()
   -> upsert_archive()로 review_status="approved"로 갱신 (+ threads/shorts 자동 downstream 연결, 14장)
```

**실제 진입점(entry point)은 CLI다 — 자동으로 일어나지 않는다.** `scripts/run_media_batch.py`가 유일한 정식 entry point이며, 사람이(또는 workflow가) 명시적으로 실행해야 한다:

```bash
python3 scripts/run_media_batch.py --execute
```

`--execute` 없이 실행하면(기본값) LLM을 호출하지 않는 **dry-run**만 수행하고 archive에 아무 것도 쓰지 않는다(코드: `scripts/run_media_batch.py` L86-100). `--execute`가 있으면 `OpenAICompatibleRewriteProvider.from_environment()`로 **실제 LLM provider**를 만들고(L102), `run_media_batch_file()` -> `archive_report()`까지 실행한다(L103-113).

## 6. MEDIA Draft 없음의 원인

**결론(증거 기반, 추측 아님): 현재 Draft 없음의 직접 원인은 코드 문제가 아니라 "MEDIA 생성 명령(`scripts/run_media_batch.py --execute`)이 실제 LLM 자격증명으로 한 번도 실행되지 않았다"(9장 분류의 B)이다.**

근거:

1. **A(approved KNOWLEDGE 없음)가 아니다** — 3장에서 확인했듯 approved KNOWLEDGE 6건이 실제로 존재한다.
2. **C(코드-데이터 연결 오류)가 아니다** — 7장에서 실제 approved KNOWLEDGE 6건 전체를 `MockRewriteProvider`(LLM 호출 없음)로 실제 파이프라인에 통과시킨 결과, **9건×6 = 54건 전부 valid로 정상 생성되고, 임시 archive에 정상 저장되고, 임시 archive를 재로드한 결과와 완전히 일치했다.** 코드 연결에 결함이 없다는 뜻이다.
3. **D(Dashboard가 잘못된 파일을 읽음)가 아니다** — 8장에서 이 임시 archive를 실제 Dashboard 인스턴스(`scripts/run_scout_dashboard.py`의 `make_handler_class`)에 연결해 `GET /media`를 실제로 호출한 결과, "조건에 맞는 Draft가 없습니다" 문구가 사라지고 54건이 실제 KNOWLEDGE 제목/본문과 함께 정상 렌더링되었으며 상세 페이지의 승인 폼도 정상 작동했다.
4. **E(생성 과정 오류)가 아니다** — 위 54건 중 error 0건, rejected 0건(전부 valid). 코드 결함으로 인한 생성 실패가 없다.
5. **F(LLM provider 설정 문제)는 아니다** — `scripts/run_media_batch.py --execute`를 실행하면 `OpenAICompatibleRewriteProvider.from_environment()`가 정상적으로 provider를 만들 수 있는 환경(`TAK_MEDIA_LLM_API_KEY`/`ENDPOINT`/`MODEL` 전부 환경변수에 존재 - 값 자체는 확인하지 않고 이름 존재만 확인, 13/14장 참고)이다 - 즉 "설정이 잘못돼서 실패한다"가 아니라 "설정은 있지만 아무도 실행한 적이 없다."
6. **B(실행 누락)가 실제 원인이다** — `scripts/run_media_batch.py --execute`(또는 이를 호출하는 `scripts/run_daily.py`)가 로컬/Codespace에서 실제로 실행된 적이 없고, 이 CLI를 호출하는 GitHub Actions workflow도 없다(`daily-media-prepare.yml`은 archive를 **읽기만** 한다 - 5-30/5-31에서 이미 확인된 설계, 이번 세션에서 재확인).

### 부가 발견: `scripts/run_daily.py`(구 경로)가 실제로 archive를 만들지만 즉시 버려진다

`scripts/run_daily.py`(TAK BRAIN → TAK MEDIA → Threads 자동 게시, `.github/workflows/daily-threads-post.yml`이 호출)도 내부적으로 `run_media_batch()` → `archive_report(report, args.archive)`(기본값 `data/tak_media_archive.json`)를 호출한다(코드: `scripts/run_daily.py` L28, L151). 즉 **이 workflow가 `workflow_dispatch`로 수동 실행될 때마다(스케줄은 5-19에 비활성화됨, 아래 참고) 실제 archive가 GitHub Actions 러너 위에서 실제로 생성된다.**

하지만 `daily-threads-post.yml`의 commit 스텝(`Check for publish history changes`/`Commit and push publish history`, L122-146)은 **`data/threads_publish_log.json`만 `git add`하고 `data/tak_media_archive.json`은 전혀 건드리지 않는다.** 그 결과 매 실행마다 만들어진 archive(실제 LLM 호출 결과물)는 러너가 종료되며 그대로 사라진다 - 로컬/Codespace의 새 checkout에는 절대 나타나지 않는다.

이것이 `data/threads_publish_log.json`에 이미 실제 게시 이력이 7건 있는데도(= 실제 LLM 호출과 MEDIA 생성이 이미 여러 번 일어났다는 증거) `data/tak_media_archive.json`은 한 번도 존재한 적이 없는 이유를 설명한다 - **생성은 됐지만 저장(커밋)되지 않고 사라진 것이다.**

이 경로를 고쳐서(예: `daily-threads-post.yml`의 commit 스텝에 archive도 추가) archive가 남게 만드는 것은 **이번 세션에서 하지 않는다** - 이유는 `.github/workflows/daily-threads-post.yml` 자체의 기존 주석(5-19)에 명시되어 있다: 이 workflow는 "사람의 승인 없이 실제 Threads API에 자동 게시하는 구(舊) 경로"이고, 5-11 이후의 신(新) 경로(Dashboard 승인 기반)로 대체하기 위해 **스케줄을 의도적으로 비활성화**한 상태다. 이 구 경로가 archive까지 남기도록 고치면 "사람 승인 없이 이미 게시된" 콘텐츠가 "사람 승인 대기 중"인 것처럼 Dashboard에 섞여 나타나 오히려 혼란을 만든다 - 프로젝트가 이미 명시적으로 결정한 마이그레이션 방향(구 경로 폐기, 신 경로로 이관)과 반대로 가는 수정이라 판단해 손대지 않았다(10장/18장에서 재확인).

## 7. 실제 MEDIA generation 실행 결과

**"실제 LLM API를 호출하지 않고 검증할 수 있는 방법을 먼저 사용한다"는 7장 지시에 따라, `content_engine.pipeline.run_media_batch()`의 기본 provider인 `MockRewriteProvider()`(네트워크 호출 없음, 원본 Draft를 그대로 반환)로 실제 production KNOWLEDGE 6건 전체를 처리했다.** 이것은 "가짜 fixture"가 아니라 **실제 production `data/tak_brain_knowledge.json`을 읽기 전용으로 입력에 사용**한 것이다 - `content_engine/pipeline.py`/`content_engine/generator.py`의 실제 로직이 그대로 실행됐고, 유일하게 대체한 것은 "재작성 문구를 실제로 바꾸는 LLM 호출" 부분뿐이다(이 부분이 없어도 원본 Draft가 이미 KNOWLEDGE의 실제 evidence/본문에서 결정적으로 만들어지므로 구조 검증에는 영향이 없다).

실행 결과:

```
전체 KNOWLEDGE: 28건, 승인: 6건
총 Draft: 54건 (valid=54, rejected=0, error=0)
  knowledge-da6ddf5aa459: 9건 -> blog×1, shorts×3, threads×5 (전부 valid)
  knowledge-e1cc05264953: 9건 -> blog×1, shorts×3, threads×5 (전부 valid)
  knowledge-da8e52862a79: 9건 -> blog×1, shorts×3, threads×5 (전부 valid)
  knowledge-a3f43f9bb62e: 9건 -> blog×1, shorts×3, threads×5 (전부 valid)
  knowledge-scout-b28b782b2a33: 9건 -> blog×1, shorts×3, threads×5 (전부 valid)
  knowledge-scout-6d1d0e2fa762: 9건 -> blog×1, shorts×3, threads×5 (전부 valid)
```

기존 설계(Blog 1 + Shorts 3 + Threads 5 = 9)와 **정확히 일치**한다. 결과는 임시 디렉터리(`tempfile.mkdtemp()`)에만 저장했고, 저장 직후 `production archive 존재 여부: False`로 production 파일이 생성되지 않았음을 재확인했다.

**성과 데이터 연결 가능성(data lineage) 확인**: 임시 archive의 레코드 1건을 직접 확인한 결과 `content_id`(예: `content-d2d6a366ede28c65`), `knowledge_id`(예: `knowledge-da6ddf5aa459`), `platform`(`blog`/`shorts`/`threads`), `final_title`이 전부 채워져 있음을 확인했다 - `content_engine.performance.models.PerformanceRecord`가 요구하는 필드와 정확히 같은 이름/의미다(6-01/6-02에서 만든 성과 수집 계층이 나중에 그대로 연결될 수 있다는 뜻이다). 이번 세션에서는 실제 Performance API 호출은 하지 않았다(범위 밖).

**실제 LLM 호출은 이 세션 전체에서 단 한 번도 하지 않았다.** `TAK_MEDIA_LLM_API_KEY`/`ENDPOINT`/`MODEL` 환경변수가 이 Codespace에 실제 값으로 존재하는 것을 확인했지만(13/17장 - 값 자체는 절대 출력/기록하지 않음), `scripts/run_media_batch.py --execute`를 실제로 실행하지 않았다 - 사용자의 별도 승인 없이는 실행하지 않는다는 원칙(7장 지시)을 그대로 지켰다. **"실제 LLM credential이 필요한 단계에서 중단"한 지점은 정확히 여기다: `python3 scripts/run_media_batch.py --execute`(또는 `--id <knowledge_id>`로 1건만)를 사람이 직접 실행하는 것.**

## 8. Dashboard 연결 검증

`scripts/run_scout_dashboard.py`의 `/media` 라우트가 실제로 무엇을 읽는지 코드로 확인했다(`config.media_archive_path`, 기본값 `data/tak_media_archive.json`) → 7장에서 만든 임시 archive를 가리키는 `DashboardConfig`로 실제 `make_handler_class()` 핸들러를 띄우고 실제 HTTP 요청으로 검증했다(임시 데이터는 `tempfile.mkdtemp()`에만 저장, production에 전혀 쓰지 않음):

| 확인 항목 | 결과 |
|---|---|
| `GET /media` 상태 코드 | 200 |
| "조건에 맞는 Draft가 없습니다" 문구 | 사라짐(정상) |
| 총 건수 표시 | `총 54건 · KNOWLEDGE 6건`(정확히 일치) |
| 카드에 상세보기 링크(`/media/{content_id}`) | 존재 |
| `GET /media/{content_id}` 상태 코드 | 200 |
| 상세 페이지에 승인 폼(`/media/{content_id}/approve`) | 존재 |
| production `data/tak_media_archive.json` 생성 여부 | 생성되지 않음(확인) |

이 결과는 이후 `tests/test_media_archive.py::MediaArchiveToDashboardIntegrationTests`로 자동화된 회귀 테스트로 고정했다(10장).

## 9. 코드 수정 내용

**이번 세션에서는 코드를 수정하지 않았다.** 이유: 6장에서 증거로 확인했듯 KNOWLEDGE→MEDIA→archive→Dashboard 전체 사슬에 코드 결함이 없다 - 유일한 blocker는 B(실행 누락)이며, 이것은 코드가 아니라 운영(사람이 `--execute`를 실행해야 함)의 문제다. 10장 지시("실제 코드 문제를 발견하면 수정한다")의 전제 자체가 성립하지 않았다 - 없는 버그를 억지로 만들어 "수정했다"고 기록하지 않는다.

발견한 것은 정확히 하나였다: 이번 세션에서 작성한 새 테스트(`MediaArchiveToDashboardIntegrationTests`)의 첫 버전에 **내 실수**가 있었다 - `/media` 목록 페이지에 `/approve` 링크가 있을 것이라고 잘못 가정했다(실제로는 목록 페이지는 상세보기 링크만 보여주고, 승인 폼은 상세 페이지 전용이다 - `_media_card_html`/`render_media_detail_html` 구조). 이건 프로덕션 코드 버그가 아니라 테스트 작성 실수였고, 테스트를 수정해 해결했다(코드는 건드리지 않음).

## 10. 테스트 결과

`tests/test_media_archive.py`(작업 시작 시점에 이미 git에 커밋된 clean 파일)에 새 테스트 클래스 `MediaArchiveToDashboardIntegrationTests`(2개 테스트)를 추가했다 - 기존 `MediaArchiveTests`(6개)가 이미 잘 다루고 있는 단위 수준 검증(9개 Draft 생성, valid/rejected 분리, knowledge_id/content_id 보존, CLI `--execute`)은 중복해서 새로 만들지 않고 그대로 재사용했다(11장 지시).

새 테스트 2개:

1. `test_real_approved_knowledge_generates_drafts_the_dashboard_can_render` — 실제 production approved KNOWLEDGE 전체를 `MockRewriteProvider`로 처리 → archive → **실제 Dashboard HTTP 서버**에 연결해 `/media`, `/media/{content_id}` 렌더링까지 검증(7장/8장의 수동 검증을 자동화된 회귀 테스트로 고정).
2. `test_pending_and_rejected_knowledge_never_reach_the_archive` — pending/rejected KNOWLEDGE가 `select_approved()` → `run_media_batch()` 사슬에서 절대 섞여 들어오지 않는지 재확인(11장 지시 9번).

전체 pytest(작업 종료 직전):

```
809 passed, 68 subtests passed in 128.13s (0:02:08)
```

**0 failed.** 시작 시점(807 passed) 대비 2건 추가, 기존 테스트는 전부 그대로 통과 — 회귀 없음.

## 11. 보안 검증

- 새로 만들거나 수정한 파일(`tests/test_media_archive.py`, 이 보고서) 어디에도 토큰/API key 하드코딩이 없다.
- `TAK_MEDIA_LLM_API_KEY`/`ENDPOINT`/`MODEL` 값 자체는 이 세션 어디에서도 출력/기록하지 않았다 - "환경변수 이름이 실제로 설정되어 있다"는 사실만 확인했다(13장).
- `.github/workflows/*.yml`을 전혀 수정하지 않았다.
- 실제 Threads/YouTube/Naver/LLM 호출 없음(12장에서 상세).
- 테스트 fixture(임시 archive, 임시 Dashboard 인스턴스)가 production data를 덮어쓴 적이 없음 - 매 테스트에서 `production archive 존재 여부: False`를 직접 확인.

## 12. 실제 외부 API 호출 여부

**전부 없음.**

- 실제 LLM API 호출: 없음(7장 - `MockRewriteProvider`만 사용, `OpenAICompatibleRewriteProvider.from_environment()`를 실제로 호출한 적 없음).
- 실제 Threads 게시/insights 호출: 없음.
- 실제 YouTube 업로드/statistics 호출: 없음.
- 실제 Naver 로그인/스크래핑: 없음(애초에 코드가 없음).

## 13. production 데이터 변경 여부

**변경 없음.** 작업 시작/종료 시점 각각 다음을 확인했다:

- `data/tak_brain_knowledge.json`: 세션 내내 어떤 Write/Edit 도구도 호출하지 않음 - 시작 시점의 기존 미커밋 diff(protected)가 그대로 유지됨.
- `data/tak_media_archive.json`: 세션 시작/종료 모두 "존재하지 않음" - 이번 세션의 모든 archive 생성은 `tempfile.mkdtemp()` 경로에만 이루어졌다.
- `data/threads_publish_log.json`/`data/youtube_publish_log.json`: 읽기만 함, 쓰기 없음.
- KNOWLEDGE approved/MEDIA 승인 상태: 사람의 승인 버튼을 코드로 대신 누른 적 없음 - `handle_media_approve_submission()`을 이 세션에서 호출한 적이 없다(14장은 코드 재확인만, 실제 실행 아님).

## 14. 변경 파일

**신규 파일:**

- `docs/6-03_knowledge_to_media_operational_validation.md`(이 파일)

**기존 파일 수정(작업 시작 시점에 이미 git에 커밋된 clean 파일):**

- `tests/test_media_archive.py` — `MediaArchiveToDashboardIntegrationTests` 클래스(테스트 2개) 추가.

**코드(런타임 동작) 변경은 없다** - 9장에서 설명한 대로 수정이 필요한 버그를 발견하지 못했다.

## 15. 기존 미커밋 변경 보존 확인

작업 종료 시점 `git status --short`를 시작 시점(1장)과 비교했다 - 1장에 나열한 기존 미커밋 변경이 **글자 하나 바뀌지 않고 그대로** 남아 있음을 확인했다(이번 세션은 `tests/test_media_archive.py`와 이 보고서 외에 어떤 파일도 Write/Edit하지 않았다).

## 16. Commit

```
git add tests/test_media_archive.py docs/6-03_knowledge_to_media_operational_validation.md
git commit -m "fix: validate knowledge to media operational pipeline"
```

(실행 결과는 아래에 이어서 기록한다.)

## 17. Push

(commit 이후 실행 결과를 이어서 기록한다.)

## 18. 남은 문제

1. **실제 production `data/tak_media_archive.json`이 여전히 없다 — 다섯 세션째 이어지는 최우선 미해결 사항.** 이번 세션에서 명확히 확인했듯, 이제 이 문제는 "코드가 안 된다"가 아니라 **"아무도 `python3 scripts/run_media_batch.py --execute`(실제 LLM 호출 포함)를 실행한 적이 없다"**는 순수한 운영 실행 문제다. 코드는 이미 준비되어 있고 정상 동작함이 이번 세션에서 증명되었다.
2. `scripts/run_daily.py`(구 경로, `daily-threads-post.yml`)가 실행될 때마다 실제 archive가 러너 위에서 만들어졌다가 커밋되지 않고 사라진다(6장 부가 발견). 이 경로를 고칠지, 완전히 폐기할지는 프로젝트의 마이그레이션 방향(구 경로 → 신 경로)에 대한 사람의 결정이 필요하다 - 이번 세션에서는 손대지 않았다.
3. approved KNOWLEDGE 6건 중 4건은 이미 구 경로(`run_daily.py`)를 통해 Threads에 게시된 이력이 있다(`threads_publish_log.json`). 만약 `--execute`를 실제로 실행해 새 archive를 만들면, 이 4건도 다시 MEDIA Draft(Blog/Shorts/Threads 9개)로 Dashboard에 나타난다 - 이미 Threads로 게시된 것과 새로 만들어진 Draft 사이의 관계를 사람이 어떻게 이해해야 하는지(예: 이미 게시된 Threads 항목은 승인해도 되는지, Blog/Shorts는 아직 게시 이력이 없으니 새로 승인해도 되는지) 운영 가이드가 없다 - 다음 단계에서 정리가 필요하다.
4. `data/blog_publish_log.json`도 여전히 없다 - 실제 Blog 게시가 한 번도 기록된 적이 없다(6-02와 동일).
5. `data/shorts_scripts/example_manman.json` 출처 불명 문제는 이번에도 다루지 않았다(범위 밖으로 명시적으로 제외됨).

## 19. 다음 5~6시간 작업 제안

1. **가장 중요한 다음 단계: 사람이 직접 `python3 scripts/run_media_batch.py --execute` 실행 여부를 결정.** 실행하면(사람이 명시적으로 승인) 실제 `data/tak_media_archive.json`이 처음으로 production에 생성되고, Dashboard `/media`에서 실제 Draft 54건을 볼 수 있게 된다. 이 단계는 AI가 대신 실행하지 않는다(7장 원칙).
2. 위 1번을 실행하기 전에, 3번 남은 문제(이미 게시된 4건 KNOWLEDGE가 다시 Draft로 나타나는 것)를 사람이 어떻게 처리할지 미리 정리해두면 혼란을 줄일 수 있다 - 예: "이미 Threads에 게시된 항목은 Threads Draft만 보류(dismiss)하고 Blog/Shorts만 검토" 같은 간단한 운영 규칙.
3. `--id <knowledge_id>`로 KNOWLEDGE 1건만 먼저 `--execute`해서 실제 LLM 품질을 소규모로 먼저 확인하는 것을 권장한다(58건을 한 번에 처리하기 전 리스크를 줄임).
4. `scripts/run_daily.py`/`daily-threads-post.yml`(구 경로)를 완전히 폐기(workflow 삭제 또는 명시적 deprecated 처리)할지 결정 - 5-19의 결정을 완성하는 다음 단계.
5. 실제 archive가 생기면, 6-01/6-02에서 만든 `scripts/collect_performance.py`/`/performance` 화면을 처음으로 실제 데이터에 연결해볼 수 있다.
