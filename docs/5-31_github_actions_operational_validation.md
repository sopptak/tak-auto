# TAK AUTO 5-31 — GitHub Actions 운영 검증 보고

## 1. 작업 시작 상태

- 현재 브랜치: `main`
- 로컬 HEAD: `ed9571f` (docs: record final commit/push confirmation in 5-30 report)
- `origin/main`: `ed9571f` (fetch 결과 로컬과 동일, ahead/behind 없음)
- 사용자가 준 baseline(`c677d8c`)보다 최신 — 5-30 보고서 커밋(`ed9571f`)까지 이미 반영된 상태에서 시작한다.
- `git status` 기준 기존 미커밋 변경(건드리지 않음):
  - modified: `.gitignore`, `content_engine/__init__.py`, `content_engine/generator.py`, `content_engine/llm_provider.py`, `content_engine/rewrite.py`, `data/tak_brain_knowledge.json`, `tests/test_content_engine.py`, `tests/test_media_batch.py`
  - untracked: `.firebaserc`, `.github/workflows/youtube-shorts-upload.yml`, `content_engine/shorts_renderer.py`, `data/blog_draft_*.md`, `data/shorts_scripts/`(기존 `example_manman.json` 포함), 다수의 `docs/*.md`, `firebase.json`, `public/`, `requirements.txt`, `scripts/mark_blog_published.py`, `scripts/render_youtube_short.py`, `scripts/run_scout_score.py`, `scripts/youtube_oauth_setup.py`, 관련 테스트 다수
- 이번 작업은 이 목록의 파일을 하나도 수정/삭제/rollback하지 않는다. 이번 세션에서 실제로 건드린 파일만 아래 17장에 기록한다.

## 2. MEDIA archive 저장 경로 조사

`content_engine/media_archive.py` 확인 결과:

- `MediaArchiveRecord` / `load_archive()` / `save_archive()` / `upsert_archive()` / `archive_report()` 모두 `content_engine/threads_review.py`와 동일한 관례(JSON 배열, `tempfile` + `Path.replace()` 원자적 저장, `content_id` 기준 upsert)를 따른다.
- `archive_report()`는 기존 레코드의 `review_status`/`edited_title`/`edited_body`를 보존한 채 생성/검증 결과만 최신화한다 — 재실행이 사람의 승인 상태를 되돌리지 않는다.

`scripts/run_scout_dashboard.py` 확인 결과:

- `DashboardConfig.media_archive_path` 기본값: `ROOT / "data" / "tak_media_archive.json"` (`--media-archive` CLI 인자로 override 가능, 기본값과 동일 경로가 help 문자열에도 명시됨).
- `handle_media_approve_submission()` (POST `/media/{content_id}/approve` 처리 함수, L718-791):
  1. `find_media_archive_record()`로 기존 레코드 조회.
  2. 이미 `approved`면 그대로 반환(idempotent, 재저장 없음).
  3. `generation_status != "valid"`면 승인 거부.
  4. `updated = replace(record, review_status="approved")` 후 **`upsert_archive(archive_path, [updated])`를 즉시 호출** — 즉 Dashboard가 MEDIA 승인 버튼을 누르는 순간 `archive_path`(기본값 production `data/tak_media_archive.json`)에 실제로 파일 쓰기가 일어난다.
  5. `platform == "threads"`면 `tak_threads_pending.json`에 자동 upsert, `platform == "shorts"`면 `save_approved_shorts_script()`로 `data/shorts_scripts/<content_id>.json` 자동 생성. `platform == "blog"`는 자동 연결하지 않음(별도 CLI로 유지).

**핵심 질문에 대한 답:**

> "Dashboard에서 MEDIA를 승인했을 때 실제로 `data/tak_media_archive.json`이 생성/저장되는가?"

**예.** `handle_media_approve_submission()`이 `upsert_archive()`를 직접 호출하고, `upsert_archive()` 내부의 `save_archive()`가 `target.parent.mkdir(parents=True, exist_ok=True)`로 `data/` 디렉터리를 만들고 파일이 없으면 새로 만든다. 코드 경로상 승인 즉시 파일이 생성/갱신된다는 데 모호함이 없다.

> "그 파일이 GitHub Actions가 checkout했을 때 존재할 수 있는가?"

**조건부로 예.** 파일은 로컬(또는 Codespace)의 워킹 디렉터리에만 생성된다 — Dashboard 프로세스 자체는 git과 전혀 상호작용하지 않는다(`run_scout_dashboard.py`에 `subprocess`/`git` 호출 없음, 3장에서 재확인). 따라서 **사람이 승인 후 직접 `git add data/tak_media_archive.json && git commit && git push`를 해야만** GitHub Actions 러너가 그 상태를 볼 수 있다. 5-30 보고서가 지적한 "로컬 production 파일 자체가 없다"는 문제는 코드 결함이 아니라 **아직 아무도 실제로 승인 → 커밋 → 푸시를 해본 적이 없다는 운영 이력의 부재**임을 재확인했다(실제로 `ls data/tak_media_archive.json` → 파일 없음, `git ls-files`에도 없음).

## 3. Dashboard 승인 → archive 흐름

승인 흐름 요약(코드 경로 기준, 실제 HTTP 서버 미기동 상태로 함수 레벨 확인):

```
POST /media/{content_id}/approve
  -> handle_media_approve_submission(archive_path, knowledge_path, threads_pending_path, content_id, shorts_scripts_path)
    -> find_media_archive_record()            (읽기)
    -> upsert_archive(archive_path, [updated]) (production 파일 쓰기)
    -> platform=="threads": upsert_pending()   (production 파일 쓰기)
    -> platform=="shorts":  save_approved_shorts_script() (production 파일 쓰기)
    -> platform=="blog":    아무 것도 안 함 (Pack은 별도 CLI)
```

`run_scout_dashboard.py` 전체를 대상으로 `git`, `subprocess`, `os.system` 참조를 검색한 결과 **일치 없음** — Dashboard 프로세스 자체는 git 명령을 전혀 실행하지 않는다(4장의 "Dashboard에 GitHub token을 넣지 않는다" 제약과 별개로,애초에 그럴 코드 경로 자체가 없음을 확인).

## 4. Git 관리 정책

### A안 vs B안

- **A안**(승인 → 파일 생성 → 사람이 commit/push → Actions가 읽음)이 현재 구현된 유일한 구조다. `run_scout_dashboard.py`에 git 연동 코드가 전혀 없으므로 B안(자동 commit/push)은 애초에 구현되어 있지 않다.
- 이 작업에서 B안을 새로 구현하지 않는다(지시사항 준수) — Dashboard에 GitHub 인증/토큰을 넣는 것은 금지 항목이다.
- 결론: **A안 유지가 맞다.** "사람 승인" 원칙(Threads 발행도 동일하게 사람이 최종 승인해야 pending → 실제 발행 후보가 되는 구조)과 일관되고, Dashboard 프로세스에 저장소 쓰기 권한(토큰)을 부여할 필요가 없어 공격 표면이 늘지 않는다.

### 상태별 git 추적 여부 재검토 (기준: "다음 GitHub Actions 실행에서도 이 상태를 기억해야 하는가?")

| 파일 | 다음 실행에서 기억해야 하는가 | 현재 `.gitignore` 상태 | 판단 |
|---|---|---|---|
| `data/tak_media_archive.json` | **예** — `review_status=approved`가 다음 checkout에서도 보여야 `prepare_approved_media.py`가 무엇을 준비할지 알 수 있다 | whitelist 추가됨(`!data/tak_media_archive.json`, 미커밋 상태의 기존 변경) | 올바름. 이번 세션에서 변경하지 않음(3.14절 "기존 .gitignore 변경 섞지 않음" 지시 준수) |
| `data/tak_threads_pending.json` | 예 — 이미 whitelist, 이미 git에 커밋됨(`git ls-files`로 확인) | 기존 whitelist(기존 세션에서 이미 완료) | 올바름, 변경 불필요 |
| `data/shorts_scripts/*.json` | 예 — "이미 생성된 Shorts는 재생성하지 않는다" 판단이 다음 checkout에서도 유효해야 함 | `data/*.json`이 기본 ignore이지만 `data/shorts_scripts/`는 하위 디렉터리라 `data/*.json` 패턴(단일 레벨 glob)에 걸리지 않아 **기본적으로 추적 대상**이다. 실제로 workflow가 `git add data/shorts_scripts`로 직접 add한다 | 올바름 — 워크플로우가 스스로 add/commit하는 유일한 예외 |
| `data/blog_publish_log.json` | 예 — 이미 게시한 Blog를 중복 후보로 다시 뽑지 않으려면 이력이 남아야 함 | whitelist 추가됨(`!data/blog_publish_log.json`, 미커밋 상태의 기존 변경) | 올바름, 변경 불필요. 단 로컬에 파일 자체가 아직 없음(실제 Blog 게시 이력 없음 — 정상, 아직 운영 전) |
| `data/blog_publish_pack_daily.md` | **아니오** — 매 실행마다 그날 승인된 Blog로 새로 만드는 휘발성 결과물, 다음 실행이 "기억"할 필요가 없다(오히려 매번 새로 만드는 게 맞음) | ignore 유지, artifact로만 업로드 | 올바름, 변경 불필요 |

**결론: 새로운 DB 도입 불필요, 기존 whitelist 정책이 이미 올바르게 설계되어 있다.** 이 부분은 5-30에서 이미 결정된 내용을 재검증한 것이며, 이번 세션에서 `.gitignore`를 추가로 수정할 필요를 찾지 못했다.

## 5. daily-media-prepare.yml 실제 검증

실제 GitHub Actions 실행은 9장에서 보듯 권한상 불가능했다. 대신 워크플로우가 실행하는 것과 **완전히 동일한 스크립트**(`scripts/prepare_approved_media.py`, 워크플로우가 그대로 호출)를 로컬 isolated tmp 디렉터리에서 직접 실행해 검증했다(스크래치패드 스크립트, production 미접촉 — 실행 후 `data/tak_media_archive.json exists: False`, `data/shorts_scripts/5-31-shorts-1.json exists: False`로 재확인).

시나리오: 승인된 Blog 1건 + Shorts 1건 + Threads 1건을 담은 임시 archive를 만들고 `prepare_approved_media.py`를 두 번 연속 실행(재실행 안전성 확인).

결과:
- 1차 실행: `종료 코드: 0`. Blog Pack 1건 생성, Shorts JSON 1건 신규 저장, Threads는 "준비할 작업 없음 + 현재 상태 읽기"만 출력.
- 2차 실행(동일 archive, 재실행): `종료 코드: 0`. Blog Pack은 동일 내용으로 재생성(매 실행마다 새로 만드는 게 설계 의도 — 4장 표 참고), Shorts는 "이미 존재해 건너뜀 1건"으로 **중복 생성되지 않음**.

## 6. Blog Pack 검증

- `--from-archive` 경로(`_run_from_archive()`)는 `run_media_batch`/`OpenAICompatibleRewriteProvider`를 전혀 호출하지 않는다(코드상 `if args.from_archive: return _run_from_archive(...)`가 LLM Provider 생성 코드보다 먼저 return함 — 6.1절에서 직접 확인).
- 로컬 실행 결과 Pack 파일에 다음이 정상적으로 포함됨을 확인: 승인된 글의 제목/본문 전문, 카테고리, 핵심 키워드, 해시태그, 이미지 권장 문구, "금융/부동산/대출 → 사람 확인 필요" 체크박스, 원본 knowledge_id/source_url.
- "네이버 블로그 게시는 자동으로 수행되지 않습니다" 경고 문구가 CLI 출력과 Pack 파일 본문 양쪽에 명시되어 있음을 확인 — 자동 게시로 오인할 여지 없음.
- `approved`만 선택되는지: `build_blog_publish_pack_from_archive()`가 `PublishHistory`로 이미 게시된 content_id를 제외하는 로직은 기존 `tests/test_blog_publish_pack.py`에서 이미 커버됨(재확인만, 신규 아님) — 이번 로컬 실행에서도 `blog_publish_log.json`이 비어있는 상태에서 승인된 1건이 정상적으로 후보에 포함됨을 확인.

## 7. ShortsScript 검증

- `data/shorts_scripts/<content_id>.json` 형식으로 정상 저장됨(6.1절 로컬 실행 결과: `title`, `subtitle`, `cards`, `takeaway`, `brand`, `created_at` 필드 모두 채워짐).
- 재실행 시 "이미 존재해 건너뜀"으로 **중복 생성 없음**을 직접 확인(5장 2차 실행 결과).
- 이 동작 자체는 기존 `tests/test_shorts_adapter.py`, `tests/test_daily_media_prepare_workflow.py`에서 이미 테스트로 커버되어 있었다(신규 발견 아님) — 이번에는 실제 워크플로우가 호출하는 것과 동일한 CLI 경로로 다시 한번 수동 재현해 확인한 것.

## 8. Threads 안전성 검증

- `prepare_approved_media.py`의 3단계(`_print_threads_summary()`)는 `content_engine.threads_review.load_pending()`만 호출한다 — **파일 쓰기 없음, `content_engine/threads_publisher.py` import 없음**.
- 로컬 실행 로그: `[Threads] 준비할 작업 없음 (MEDIA 승인 시점에 이미 pending queue로 자동 연결됨)` — 이 workflow는 Threads pending 상태를 만들지도, 바꾸지도, 발행하지도 않고 **읽기만** 한다는 설계 의도가 실제 실행 결과와 일치함을 확인.
- `daily-media-prepare.yml` 파일 자체에서 `publish_threads.py`/`publish_approved_threads.py`/`threads_publisher` 문자열이 실행 가능한(비-주석) 라인에 전혀 없음을 재확인(9장, 기존 `tests/test_daily_media_prepare_workflow.py::test_no_forbidden_references`와 동일 결론 재검증).

## 9. 실제 GitHub Actions 실행 결과

### 권한 확인

- `gh auth status`: `sopptak` 계정으로 로그인됨, 토큰 타입 `GITHUB_TOKEN`(`ghu_...` — GitHub App user-to-server 토큰으로 추정), `X-OAuth-Scopes` 헤더 비어있음(App 토큰은 OAuth scope 대신 App 권한을 사용).
- `gh api repos/sopptak/tak-auto --jq .permissions` → `{"admin":true,"maintain":true,"pull":true,"push":true,"triage":true}` — 저장소 **콘텐츠 push 권한은 있음**.
- `gh api repos/sopptak/tak-auto/actions/permissions` → **403 Resource not accessible by integration**.
- `gh workflow run "daily-media-prepare.yml" -f dry_run=true` → **403: could not create workflow dispatch event: Resource not accessible by integration** (`/repos/sopptak/tak-auto/actions/workflows/361943999/dispatches`).

**결론: 이 세션의 GitHub 인증으로는 workflow_dispatch를 실제로 트리거할 수 없다.** repo `push`(콘텐츠) 권한과 Actions 실행/관리 권한은 GitHub 권한 모델에서 별개이며, 현재 토큰은 후자를 갖고 있지 않다. → **6장 지시대로, "실행 불가"임을 명확히 기록하고 로컬에서 가능한 범위까지만 검증한다.**

### 읽기 권한으로 확인 가능한 사실

- `gh run list --workflow=daily-media-prepare.yml` → **0건** (실행 이력 없음). `gh api .../actions/workflows/361943999/runs --jq .total_count` → `0`으로 재확인.
- 다른 workflow(`daily-scout.yml`, `daily-threads-post.yml` 등)의 `gh run list`는 정상적으로 과거 실행 이력을 반환함 → 읽기 권한 자체는 정상 작동, "0건"은 권한 문제가 아니라 **실제로 이 workflow가 아직 한 번도 실행된 적이 없다**는 사실.
- workflow 메타데이터(`gh api .../workflows/361943999`): `state: active`, `created_at: 2026-09-19T08:14:28Z` — `c677d8c` 커밋(같은 타임스탬프대)으로 최초 등록됨. `schedule: cron '30 23 * * *'`는 아직 도래하지 않았거나(이 샌드박스의 로컬 시계와 GitHub 서버 실시간 사이에 괴리가 있을 수 있음) 실행 이력에 반영되지 않은 상태.
- workflow 파일 자체(`secrets.` 문자열 검색 결과 0건)와 실제 `origin/main`에 올라간 파일이 로컬 워킹 트리와 동일함(`git fetch` 후 `git log origin/main --oneline -5`가 로컬 HEAD와 일치)을 확인 — 즉 **실행은 못 시켰지만, GitHub에 올라간 workflow YAML 자체는 로컬에서 정적 검증한 내용과 100% 동일하다.**

## 10. Artifact 결과

**실행 불가로 인해 실제 artifact 생성 여부는 확인하지 못했다.** 대신 로컬에서 `scripts/prepare_approved_media.py`를 격리된 임시 archive로 직접 실행해 artifact의 소스가 되는 `blog_publish_pack_daily.md` 생성 로직을 검증했다(아래 12장 로컬 검증 결과 참고). 기존 `tests/test_daily_media_prepare_workflow.py`의 `PrepareApprovedMediaEndToEndTests`도 동일한 내용을 이미 tmp_path 기준으로 검증하고 있었다(신규 발견 아님, 재확인).

## 11. 보안 검증

- `secrets.` — `daily-media-prepare.yml` 전체에서 0건 (`grep -n "secrets\." .github/workflows/daily-media-prepare.yml` → no match).
- `permissions: contents: write`만 존재, 그 외 permission 블록 없음(기본값 read로 최소화).
- `env:` 블록은 `BLOG_MAX`(workflow_dispatch input 값)만 존재 — API key/토큰 계열 환경변수 없음.
- `scripts/generate_blog_publish_pack.py`(`--from-archive` 경로), `scripts/generate_approved_shorts_script.py` 둘 다 `requests`/`urllib.request`/`httpx`/`openai` 등 네트워크 호출 코드가 없음(`grep` 결과 0건).
- `_run_from_archive()`가 `OpenAICompatibleRewriteProvider` 생성 코드보다 먼저 `return`하므로 LLM Provider 인스턴스 자체가 생성되지 않음(모듈 import는 되지만 API 키 요구/네트워크 호출 없음).
- 이번 세션에서 `.github/workflows/*.yml` 파일을 수정하지 않았으므로 새로운 `secrets.*` 참조가 추가될 여지 자체가 없음.

## 12. 테스트 결과

전체 pytest 실행(`python3 -m pytest -q`):

```
703 passed, 68 subtests passed in 133.25s (0:02:13)
```

**0 failed.** 5-30 종료 시점과 정확히 동일한 수치(703 passed / 68 subtests) — 이번 세션은 코드를 수정하지 않았으므로(순수 조사/로컬 실행/문서화) 회귀도, 신규 테스트 추가도 없음.

13번 과제 체크리스트(A~L) 대응 현황:

| 항목 | 상태 | 근거 |
|---|---|---|
| A. Dashboard 승인 → archive 저장 | 기존 테스트로 이미 커버 | `tests/test_media_dashboard.py::test_approve_sets_review_status_to_approved_and_shows_banner` 등 |
| B. archive reload 후 approved 유지 | 기존 테스트로 이미 커버 + 이번 세션 수동 재확인 | `tests/test_media_dashboard.py::test_edit_saves_are_preserved_across_reload`, 6.1절 수동 실행 |
| C. workflow가 archive를 읽을 수 있음 | 이번 세션 수동 재확인 | 5장 수동 실행(같은 CLI 경로) |
| D. dry-run은 commit하지 않음 | 기존 테스트로 이미 커버 | `tests/test_daily_media_prepare_workflow.py`의 YAML if-조건(`dry_run == 'false'`) 정적 검증 + `WorkflowGitCommitLogicTests` |
| E. 실제 workflow 실행 시 Blog Pack artifact 생성 | **확인 불가(권한 문제)** | 9장 — workflow_dispatch 403, 대안으로 동일 스크립트 로컬 실행은 6장에서 성공 확인 |
| F. ShortsScript 생성 | 이번 세션 수동 재확인 | 7장 |
| G. ShortsScript 중복 없음 | 이번 세션 수동 재확인(2차 실행) | 5장/7장 |
| H. Threads publish 없음 | 정적 검증 + 실행 로그 재확인 | 8장 |
| I. YouTube upload 없음 | 정적 검증(코드에 참조 자체 없음) | 워크플로우/스크립트 어디에도 youtube 관련 import 없음 |
| J. Naver publish 없음 | 정적 검증(자동화 코드 자체 없음) | 16장 |
| K. LLM 호출 없음 | 정적 검증 + 코드 흐름 확인 | 11장 |
| L. 전체 회귀 테스트 | **0 failed** | 위 pytest 결과 |

## 13. 실제 LLM 호출 여부

없음 — 확인 내용은 6장/11장/12장 참고.

## 14. 실제 Threads 발행 여부

없음.

## 15. 실제 YouTube 업로드 여부

없음.

## 16. 실제 Naver 게시 여부

없음(저장소에 Naver 게시 자동화 코드 자체가 없음, 기존 사실 재확인).

## 17. 변경 파일

이번 세션에서 실제로 만든/수정한 파일은 다음 1개뿐이다:

- `docs/5-31_github_actions_operational_validation.md` (신규)

코드(`content_engine/`, `scripts/`, `.github/workflows/`, `tests/`)는 **전혀 수정하지 않았다** — 조사와 로컬 실행 검증 결과 기존 구현(5-29/5-30에서 이미 완성된 archive 저장 경로, Dashboard 승인 흐름, `.gitignore` whitelist 정책, `daily-media-prepare.yml` 안전장치)이 이미 올바르게 설계되어 있음을 확인했을 뿐, 새로 고치거나 추가해야 할 결함/CLI/DB를 발견하지 못했다.

`scripts/sync_approved_media.py` 같은 별도 동기화 CLI는 만들지 않았다(9장 지시 검토 결과) — 사람이 해야 하는 남은 단계는 이미 `git add data/tak_media_archive.json [data/shorts_scripts/*.json] && git commit && git push` 한 줄 수준으로 단순하며, 이보다 더 얇은 CLI를 추가해도 실질적으로 줄어드는 타이핑이 없다고 판단했다(20/21장 참고).

임시 로컬 검증 스크립트(`/tmp/.../scratchpad/manual_verify.py`)는 스크래치패드에서만 실행했고 저장소에는 포함되지 않는다.

## 18. Commit

```
git add docs/5-31_github_actions_operational_validation.md
git commit -m "docs: record 5-31 GitHub Actions operational validation report"
```

기존 미커밋 변경(`.gitignore`, `content_engine/*`, `tests/test_content_engine.py`, `tests/test_media_batch.py`, `data/tak_brain_knowledge.json` 등)과 다수의 미커밋 `docs/*.md`/`scripts/*.py`/`tests/*.py`는 이번 커밋에 포함하지 않는다 — `git add`로 이 보고서 파일 하나만 명시적으로 스테이징한다.

## 19. Push

```
$ git push
To https://github.com/sopptak/tak-auto
   ed9571f..70ba70b  main -> main

$ git fetch origin
(변경 없음)

$ git log origin/main..HEAD --oneline
(빈 결과)
```

`origin/main`이 로컬 HEAD(`70ba70b`)와 완전히 일치함을 확인했다. push 성공.

## 20. 남은 문제

1. **가장 중요한 미해결 문제: 실제 production `data/tak_media_archive.json`이 아직 존재하지 않는다.** 코드 경로는 정상 동작함을 이번 세션에서 재확인했지만, Dashboard로 실제 MEDIA 승인을 1건이라도 수행한 적이 없어 production archive 파일 자체가 로컬에도 GitHub에도 없다. `daily-media-prepare.yml`이 "실행은 되어도 준비할 게 없다"는 상태로 계속 공회전(빈 Pack, Threads "draft 없음" 요약)할 것이다.
2. 이 세션의 GitHub 인증(`ghu_` App 토큰)은 저장소 `push`(contents) 권한은 있지만 **Actions 실행 권한(`actions:write`)이 없어** `workflow_dispatch`를 직접 트리거할 수 없다. 실제 GitHub Actions 러너에서의 실행 성공 여부(체크아웃/Python 설치/테스트/artifact 업로드)는 **한 번도 실증된 적이 없다** — 로컬 실행 결과로 강하게 추정할 뿐 증명하지는 못했다.
3. `daily-media-prepare.yml`의 스케줄(`cron: '30 23 * * *'`)이 등록된 이후(2026-09-19T08:14Z) 아직 한 번도 자동 실행되지 않았다(`gh run list` 0건) — 이 세션의 로컬 시계(2026-09-20T00:04Z 기준 스케줄 시각을 이미 지남)와 GitHub 서버의 실제 스케줄 실행 사이에 괴리가 있는지, 혹은 다음 실행까지 정상적으로 대기 중인지는 이 세션의 권한으로는 확인할 수 없었다.
4. `data/shorts_scripts/`에 이번 세션과 무관한 기존 untracked 파일(`example_manman.json`)이 남아 있다 — 실제 승인 흐름으로 만들어진 파일인지 이전 세션의 수동 테스트 산출물인지 이번 조사만으로는 특정하지 못했다. 삭제/커밋 여부는 사람의 판단이 필요하다(이번 세션에서 건드리지 않음).

## 21. 다음 단계

1. **가장 우선순위 높음:** 실제 Dashboard(`scripts/run_scout_dashboard.py`)를 기동해 실제 MEDIA 항목 최소 1건을 진짜로 승인하고, 생성된 `data/tak_media_archive.json`(+ 필요하면 `data/shorts_scripts/*.json`)을 `git add && git commit && git push`로 GitHub에 반영한다. 이것이 되어야만 `daily-media-prepare.yml`이 실제로 "준비할 것이 있는" 상태에서 실행되는 것을 볼 수 있다.
2. 위 1번 이후, Actions 쓰기 권한이 있는 사람(레포 소유자, 브라우저 또는 `actions:write` 스코프가 있는 토큰)이 GitHub UI 또는 `gh workflow run daily-media-prepare.yml -f dry_run=true`로 실제 dry-run을 1회 수행해 9장에서 확인하지 못한 "실제 러너에서의 성공"을 검증하는 것을 권장한다.
3. 스케줄이 예정대로 도는지(3번 남은 문제) 하루 이상 지난 뒤 `gh run list --workflow=daily-media-prepare.yml`로 재확인한다.
4. `data/shorts_scripts/example_manman.json`의 출처를 사람이 확인해 정리(커밋 또는 삭제)할지 결정한다.
