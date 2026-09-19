# TAK AUTO 5-30 — 승인 콘텐츠 자동 준비 Workflow + 운영 안정화

작업 시작: commit `0780305`(+ 뒤이은 문서 전용 커밋 `b96c2ab`) 기준.

## 1. 작업 시작 상태

- main 기준 commit: `0780305` (문서 후속 커밋 `b96c2ab` 포함, 코드 변경 없음)
- 전체 pytest: 684 passed / 68 subtests / 0 failed
- 완료된 구조: SCOUT → INTERVIEW → KNOWLEDGE → 승인 → TAK MEDIA 9개 생성 →
  ARCHIVE → MEDIA Dashboard(수정/승인/보류) → Blog(`--from-archive` 수동
  CLI) / Shorts(승인 시 자동 ShortsScript 저장) / Threads(승인 시 자동
  pending 연결) → `scripts/prepare_approved_media.py`(Blog+Shorts+Threads
  요약을 한 번에)
- 실제 외부 발행은 전부 별도 workflow(`publish-approved-threads.yml`,
  `youtube-shorts-upload.yml`)로 분리되어 있고, 이번 작업에서도 이 경계를
  유지한다.

## 2. 기존 구조 조사

### 기존 CLI 3개(재사용, 무수정)

- `scripts/prepare_approved_media.py` — Blog Pack + Shorts Script + Threads
  요약을 한 번에 실행하는 오케스트레이터(5-29). LLM/외부 API를 전혀
  호출하지 않는다. 이 workflow가 그대로 호출할 핵심 CLI.
- `scripts/generate_blog_publish_pack.py --from-archive` — 승인된 Blog만
  Pack으로. `--limit`은 이 모드에서 무시됨(안내만 출력).
- `scripts/generate_approved_shorts_script.py` — 승인된 Shorts만
  `data/shorts_scripts/<content_id>.json`으로. 이미 있으면 재생성 안 함.

### 기존 GitHub Actions workflow 4개 전수 재조사

| workflow | trigger | Secrets 사용 | git commit 대상 |
|---|---|---|---|
| `daily-scout.yml` | `schedule: '0 23 * * *'`(KST 08:00) + `workflow_dispatch` | 없음 | `data/tak_scout_daily.json`, `.md` |
| `daily-threads-post.yml` | `workflow_dispatch`만(schedule은 5-19에서 주석 처리로 비활성화) | THREADS_ACCESS_TOKEN, TAK_MEDIA_LLM_* | `data/threads_publish_log.json` |
| `publish-approved-threads.yml` | `workflow_dispatch`만 | THREADS_ACCESS_TOKEN(live일 때만) | `data/tak_threads_pending.json`, `threads_publish_log.json` |
| `youtube-shorts-upload.yml` | `workflow_dispatch`만 | YOUTUBE_CLIENT_ID/SECRET/REFRESH_TOKEN(live일 때만) | `data/youtube_publish_log.json` |

공통 패턴(전부 동일하게 재사용):
1. `actions/checkout@v4` → `actions/setup-python@v5`(3.14) → 버전 출력
2. **`python3 -m unittest discover -s tests -p 'test*.py'`로 전체 테스트를
   먼저 실행** - 실패하면 이후 단계로 진행하지 않음(4개 workflow 전부 동일)
3. 본 작업 실행
4. `git add <구체적 파일 목록>` → `git diff --cached --quiet`로 변경 여부
   확인 → 변경 있을 때만 `git commit && git push`
5. `concurrency: {group: <workflow명>, cancel-in-progress: false}`로 동시
   실행을 취소 대신 대기시킴(재게시/중복 커밋 경합 방지)
6. **어느 workflow도 `on: push` 트리거를 쓰지 않는다** - 전부
   `schedule`/`workflow_dispatch`뿐이다. 즉 이 workflow들이 커밋+푸시해도
   그 push가 어떤 workflow도 재트리거하지 않는다(애초에 `push` 이벤트를
   구독하는 workflow 자체가 없음) - "자기 자신을 무한 재실행시키는 구조"가
   될 조건 자체가 이 저장소에는 존재하지 않는다. 게다가 GitHub Actions는
   기본 `GITHUB_TOKEN`으로 만든 push가 다른 workflow를 트리거하지 않도록
   막아주는 안전장치도 기본으로 갖고 있어(이중 안전) `paths-ignore` 같은
   추가 조치가 필요 없다.

### `.gitignore` 조사 — 중요한 발견

```
data/*.json
!data/tak_brain_knowledge.json
!data/tak_media_batch_e2e_test.json
!data/threads_publish_log.json
!data/tak_threads_pending.json
!data/blog_publish_log.json
!data/scout_sources.json
!data/youtube_publish_log.json
!data/tak_scout_daily.json
```

- `data/tak_media_archive.json`은 **화이트리스트에 없다 → 현재 git에서
  무시된다.** 로컬(Codespace)에서 사람이 Dashboard로 승인 작업을 해도, 그
  결과는 git에 커밋되지 않고 로컬 파일시스템에만 남는다.
- 반면 `data/tak_threads_pending.json`은 **이미 화이트리스트에 있다** -
  왜냐하면 기존에도 이미 "사람이 로컬/Dashboard에서 승인 → 그 상태를 git에
  커밋 → GitHub Actions(`publish-approved-threads.yml`)가 커밋된 상태를
  읽어서 처리"라는 흐름이 5-11부터 이미 성립해 있었기 때문이다(GitHub
  Actions 러너는 매번 새로 `checkout`하므로, 커밋되지 않은 로컬 상태는
  워크플로우가 절대 볼 수 없다).
- **결론(중요): 오늘 만들 `daily-media-prepare.yml`이 뭔가를 실제로
  "준비"하려면, `data/tak_media_archive.json`도 반드시 git에 커밋
  가능해야 한다** - 안 그러면 워크플로우는 매번 빈 archive만 보고 "준비할
  것 없음"으로 끝난다. 이건 새로운 정책이 아니라 `tak_threads_pending.json`
  에 이미 적용된 것과 완전히 동일한 원칙을 archive에도 그대로 적용하는
  것뿐이다. → **`.gitignore`에 `!data/tak_media_archive.json` 추가 필요**
  (아래 6장에서 근거 재정리).
- `data/shorts_scripts/*.json`은 `data/*.json`(최상위 파일만 매칭, `*`가
  `/`를 넘지 않음)에 걸리지 않는다 → **애초에 무시 대상이 아니다**, 그냥
  아직 한 번도 커밋되지 않은 untracked 상태일 뿐이다(현재 `data/shorts_scripts/
  example_manman.json` 1개가 이미 이 상태로 존재). 즉 별도 gitignore 수정 없이
  바로 `git add`할 수 있다.
- `data/blog_publish_pack_daily.md`는 명시적으로 무시 대상이다(주석: "매
  실행마다 새로 생성/덮어쓰는 휘발성 결과물"). 이 정책을 그대로 존중한다 -
  workflow가 이 파일을 git에 커밋하지 않고, 대신 `actions/upload-artifact`로
  다운로드 가능한 CI 아티팩트로만 남긴다(사람이 굳이 로컬에서 CLI를 다시
  실행하지 않아도 내용을 확인할 수 있게).

## 3. 자동화 설계

### 결정 A — 새 workflow `daily-media-prepare.yml` 추가

기존 4개와 동일한 구조(checkout → setup-python → 전체 테스트 →
본작업 → diff 확인 → 조건부 commit/push)를 그대로 재사용한다. 새 패턴을
발명하지 않는다.

### 결정 B — schedule은 기존 daily-scout와 30분 offset

`daily-scout.yml`이 이미 `0 23 * * *`(UTC, KST 08:00)에 실행 중이다. 이
workflow는 SCOUT 결과 시점과 무관하게(그날그날 이미 승인된 것을 준비할
뿐) 아무 때나 실행해도 되지만, 동시 실행 시 두 workflow가 거의 같은
시각에 git push를 시도할 가능성을 줄이기 위해 30분 뒤인
`30 23 * * *`(UTC, KST 08:30)로 지정한다. `daily-threads-post.yml`의
schedule은 이미 비활성화되어 있어 시간 충돌 검토 대상에서 제외한다.
`workflow_dispatch`도 함께 지원한다(수동 실행 + 필요시 `dry_run`으로
"준비는 하되 commit/push는 하지 않음" 선택 가능).

### 결정 C — `data/tak_media_archive.json`을 `.gitignore` 화이트리스트에 추가

2장에서 근거를 이미 기록했다. `data/tak_threads_pending.json`에 적용된
것과 동일한 원칙(사람이 승인한 상태는 GitHub Actions가 읽을 수 있도록
git에 커밋 가능해야 한다)을 archive에도 동일하게 적용한다. **이
workflow 자체는 archive를 쓰지 않는다(읽기 전용)** - 사람이 로컬에서
Dashboard로 승인한 뒤 그 archive 파일을 직접 커밋/푸시해야 workflow가
그 상태를 볼 수 있다는 사실을 workflow 파일 주석에도 명시한다.

### 결정 D — Blog Pack은 git에 커밋하지 않고 아티팩트로만 남긴다

기존 정책(`data/blog_publish_pack_daily.md`는 휘발성, git 비영속)을 그대로
존중한다. `actions/upload-artifact@v4`로 Pack 파일을 워크플로우 실행 결과에
첨부한다.

### 결정 E — Shorts Script는 git에 커밋한다

`data/shorts_scripts/<content_id>.json`은 Blog Pack과 성격이 다르다 - 매번
다시 계산되는 스냅샷이 아니라, 한 번 생성되면 고정되는 영구 산출물이다
(5-29 설계: "이미 생성된 경우에는 중복 생성하지 않는다"). 이 "이미 생성됨"
판단 자체가 **git에 커밋되어 있어야만** 다음 날 워크플로우 실행(새
`checkout`)에서도 유효하다 - 커밋하지 않으면 매번 빈 디렉터리에서 새로
시작해 매일 "새로 생성"으로 잘못 보고하게 된다. 따라서 이 파일들은 반드시
커밋 대상이다.

### 결정 F — Rollback은 이번 단계에서 구현하지 않는다(설계만)

9장에서 상세 근거를 기록한다. 결론만 먼저: "안전하지 않은 rollback은
구현하지 않는다"는 사용자 지침을 그대로 따라 **구현하지 않는다.**

### 결정 G — Audit Log는 이번 단계에서 구현하지 않는다(조사만)

10장에서 상세 근거를 기록한다. 결론만 먼저: 기존 `MediaArchiveRecord`
스키마에 필드를 추가하는 것 자체는 (5-29에서 이미 `edited_title`/
`edited_body`를 추가할 때 그랬듯) 하위 호환을 유지하며 가능하지만, "누가"
승인했는지를 기록할 방법이 이 프로젝트에는 아직 없다(단일 운영자, 로그인
개념 자체가 없는 로컬 HTTP 서버) - "누가"가 의미 없는 값(항상 티몽 1명)이
되므로 지금 추가하는 것은 실질적 이득 없이 스키마만 복잡해진다. 구현하지
않는다.

### 결정 H — Dashboard 변경은 최소화(문구 1줄 정도만 검토)

8장에서 상세 기록. 현재 downstream 상태 표시(5-29)가 이미 "승인됨 (Pack
생성 가능)" / "Script 생성됨" / pending 상태 라벨을 전부 보여주고 있어,
"자동 준비 완료"라는 새 상태를 추가로 만들 필요가 크지 않다고 판단했다 -
기존 라벨이 이미 그 의미를 전달한다. Dashboard 코드는 이번 작업에서
수정하지 않는다(과도한 UI 변경 금지 지침 그대로 따름).

## 4. GitHub Actions 구현

`.github/workflows/daily-media-prepare.yml`(신규) 최종 구조:

```
checkout → setup-python(3.14) → python3 --version
→ python3 -m unittest discover(전체 테스트, 실패 시 이후 중단)
→ scripts/prepare_approved_media.py 실행(BLOG_MAX만 env로 전달, Secrets 없음)
→ Blog Pack을 actions/upload-artifact로 첨부(git commit 안 함)
→ (dry_run이 아니면) git add data/shorts_scripts + git diff --cached --quiet
→ 변경 있으면만 git commit && git push
```

- Trigger: `schedule: '30 23 * * *'`(UTC, KST 08:30 — `daily-scout.yml`의
  `0 23 * * *`에서 30분 offset) + `workflow_dispatch`(`dry_run`,
  `blog_max` 입력 지원).
- `permissions: contents: write`만(그 외 기본값=read로 최소화),
  `concurrency`로 동시 실행을 취소 대신 대기.
- `env:` 블록은 딱 하나(`BLOG_MAX`, `github.event.inputs.blog_max` 그대로 —
  Secrets 아님) - `secrets.*` 참조가 워크플로우 전체에 단 하나도 없다.
- `github.event.inputs.dry_run` 비교는 기존 `daily-threads-post.yml`이
  이미 쓰는 안전한 패턴(`github.event_name != 'workflow_dispatch' ||
  github.event.inputs.dry_run == 'false'`)을 그대로 재사용 - `schedule`
  트리거에는 `inputs` 자체가 없다는 사실에 기대는 대신, `event_name`을
  먼저 명시적으로 확인한다.

## 5. 안전성 검증

- 실행 코드(주석 제외) 전수 grep: `ThreadsClient`/`threads_publisher`/
  `YouTubeClient`/`youtube_publisher`/`llm_provider`/
  `OpenAICompatibleRewriteProvider`/`publish_threads.py`/
  `publish_approved_threads.py`/`upload_youtube_short.py` 전부 **없음**.
- `secrets.` 참조, `THREADS_ACCESS_TOKEN`/`TAK_MEDIA_LLM_*`/`YOUTUBE_*`
  환경변수 이름 전부 **없음**(주석에서 "이런 게 필요 없다"고 설명하는
  것 제외).
- `on:`에 `push:` 트리거 없음 - 이 workflow의 `git push`가 어떤
  workflow(자기 자신 포함)도 재트리거할 수 없다(정적 확인 +
  `tests/test_daily_media_prepare_workflow.py::test_does_not_trigger_on_push`).
- `scripts/generate_blog_publish_pack.py`(기존 파일) 자체에는 여전히
  `OpenAICompatibleRewriteProvider` import가 있다(비-archive 기본 모드가
  실제 LLM을 쓰기 때문) - 하지만 이 workflow는 `--from-archive` 인자로만
  호출하는 `scripts/prepare_approved_media.py`를 거치므로, 실행 경로상
  이 import가 실제로 호출되지 않는다(5-28에서 이미
  `mocked_from_env.assert_not_called()`로 검증됨). 이번에 이 사실을
  재확인만 했다.

## 6. 중복 실행 검증

- **A. ShortsScript 중복 없음**: `save_approved_shorts_script()`가 파일
  존재 시 재생성하지 않음(5-29 구현, 이번에 워크플로우 관점에서
  `tests/test_daily_media_prepare_workflow.py::PrepareApprovedMediaEndToEndTests`
  로 재확인).
- **B. Threads pending 중복 없음**: 이 workflow는 Threads에 아무 것도
  쓰지 않는다(읽기 전용 요약만) - 애초에 중복 생성 경로 자체가 없다.
  MEDIA 승인 시점의 기존 가드(5-28, `upsert_pending` 전 존재 확인)는
  무수정.
- **C. Blog publish history와 충돌 없음**: `select_approved_blog_candidates_
  from_archive()`가 이미 `PublishHistory.published_content_ids()`로
  게시된 것을 제외한다(5-29 구현, 무수정).
- **D. 재실행해도 불필요한 변경 없음** /
  **E. git diff 없으면 빈 commit 없음**: 실제 workflow가 실행하는 것과
  정확히 동일한 git 명령(`git add data/shorts_scripts` +
  `git diff --cached --quiet -- data/shorts_scripts`)을 격리된 임시 git
  저장소에서 직접 실행해 검증
  (`WorkflowGitCommitLogicTests` 4건: 변경 없음 감지, 새 파일 감지,
  재실행 후 무변경 확인, 두 번째 실행이 새 파일만 감지하고 기존 파일을
  다시 건드리지 않는지).

## 7. Dashboard 변경

**변경 없음.** 3장 "결정 H"에서 기록한 대로, 5-29에서 이미 구현한
downstream 상태 라벨("승인됨 (Pack 생성 가능)", "Script 생성됨" 등)이
"자동 준비 완료" 개념을 이미 충분히 전달한다고 판단해 이번 단계에서는
Dashboard 코드를 전혀 건드리지 않았다. 새 DB를 만들지 않는다는 원칙도
자연히 지켜졌다(변경 자체가 없으므로).

## 8. Rollback 검토

**구현하지 않음(설계만).** 이유:

승인된 콘텐츠는 채널마다 서로 다른 "이미 진행된 부작용"을 가질 수 있다.
- Threads: `tak_threads_pending.json`에 이미 `status="pending"` draft가
  생성되어 있을 수 있고, 사람이 그걸 또 `/threads`에서 이미 `approved`나
  `published`로 진행시켰을 수도 있다.
- Shorts: `data/shorts_scripts/<id>.json`이 이미 생성되어 있을 수 있고,
  사람이 이미 그 파일로 MP4를 렌더링했을 수도 있다(이 프로젝트가 추적하지
  않는, Dashboard 밖에서 일어나는 행동).
- Blog: 이미 여러 번의 Pack 생성에 포함됐을 수 있고(Pack 자체는
  비영속이라 추적 안 됨), 사람이 이미 네이버에 게시하고
  `mark_blog_published.py`로 기록했을 수도 있다.

"승인 → unreviewed로 되돌리기"를 archive의 `review_status` 필드 하나만
바꿔서 구현하면, **위 세 가지 downstream 부작용은 전혀 되돌리지 않은 채
archive만 "아직 승인 안 됨"으로 거짓 표시**하게 된다 - 특히 이미 Threads에
실제로 발행됐거나 Naver에 실제로 게시된 경우, "승인 취소"가 마치 그
발행/게시 자체를 취소한 것처럼 오인시킬 위험이 크다(사용자 지침 원문:
"이미 실제 발행된 콘텐츠를 rollback하면 안 된다. 따라서 단순 상태 변경으로
해결하면 안 된다"). 안전하게 구현하려면 채널별로 "이미 어디까지
진행됐는지"를 먼저 정확히 판별하고, 진행된 단계별로 서로 다른 되돌리기
정책(예: pending 상태의 Threads draft는 삭제 가능하지만 published는
불가, Shorts script 파일은 지울 수 있지만 이미 렌더링된 MP4까지는 이
프로젝트가 알 방법이 없음, Blog는애초에 "포함 이력" 자체를 추적하지
않으므로 rollback할 상태가 없음)을 전부 설계해야 하는데, 이는 이번
1~2시간 작업 범위를 넘어서는 별도 설계 과제라고 판단했다. **사용자 지침
그대로: "안전하지 않은 rollback은 구현하지 않는다."**

## 9. Audit Log 검토

**구현하지 않음(조사만, 근거는 3장 "결정 G"에 이미 기록).** 요약: 이
프로젝트는 로그인/사용자 구분 개념이 아예 없는 단일 운영자용 로컬 HTTP
서버다(`scripts/run_scout_dashboard.py`는 인증 없이 `127.0.0.1`에만
바인딩). "누가"를 기록해도 항상 같은 값(티몽 1명)이 되어 실질적 정보
가치가 없고, `created_at`(생성 시각)은 이미 `MediaArchiveRecord`에
있으니 "언제"는 이미 부분적으로 추적되고 있다. "무엇을 수정/승인/
보류했는지"의 이력(변경 전/후 diff)까지 남기려면 archive를 append-only
로그 구조로 바꿔야 하는데, 이는 현재의 "content_id 기준 upsert(최신값만
유지)" 스키마와 근본적으로 다른 저장 모델이라 하위 호환이 깨질 위험이
크다(사용자 지침: "기존 데이터 호환성이 깨질 위험이 있으면 구현하지
않는다"). 구현하지 않는다.

## 10. 테스트 결과

사용자 지정 A~P 전부 대응:

| 항목 | 검증 위치 |
|---|---|
| A. workflow 파일 존재 | `WorkflowFileStaticChecks::test_workflow_file_exists` |
| B. workflow_dispatch 존재 | `test_has_workflow_dispatch_trigger` |
| C. schedule 존재 | `test_has_schedule_trigger`, `test_schedule_does_not_collide_with_daily_scout` |
| D. 실제 publish 스크립트 호출 없음 | `test_no_forbidden_references`, `test_calls_only_prepare_approved_media_script` |
| E. YouTube upload 없음 | `test_no_forbidden_references`(YouTubeClient/youtube_publisher/upload_youtube_short.py) |
| F. Threads publish 없음 | `test_no_forbidden_references`(ThreadsClient/threads_publisher/publish_threads.py/publish_approved_threads.py) |
| G. Naver publish 없음 | `test_no_naver_reference_outside_comments_explaining_absence` |
| H. LLM provider 없음 | `test_no_forbidden_references`(llm_provider/OpenAICompatibleRewriteProvider) |
| I. Secrets 사용 없음 | `test_no_secrets_usage`, `test_has_no_env_block_with_tokens` |
| J. prepare CLI 정상 실행 | `PrepareApprovedMediaEndToEndTests::test_prepare_cli_runs_successfully_and_produces_both_outputs` |
| K. 변경 없을 때 빈 commit 없음 | `WorkflowGitCommitLogicTests::test_no_new_shorts_scripts_reports_no_changes` |
| L. 동일 workflow 재실행 idempotent | `test_rerunning_after_commit_reports_no_further_changes`, `test_second_run_with_new_content_id_only_reports_the_new_file` |
| M. ShortsScript 중복 없음 | 5-29 `tests/test_shorts_adapter.py` + 이번 `test_new_shorts_script_is_detected_as_a_change` |
| N. Threads pending 중복 없음 | 5-28 `tests/test_media_dashboard.py::test_threads_approval_does_not_overwrite_existing_pending_draft` |
| O. Blog publish history와 충돌 없음 | 5-29 `tests/test_blog_publish_pack.py::test_candidate_excluded_after_marked_published` |
| P. 기존 전체 pytest 회귀 | 전체 703 passed(기존 684 + 신규 19), 실패 0 |

신규 테스트 파일: `tests/test_daily_media_prepare_workflow.py`(19건, 3개
클래스: `WorkflowFileStaticChecks`, `WorkflowGitCommitLogicTests`,
`PrepareApprovedMediaEndToEndTests`).

## 11. 실제 LLM 호출 여부

**없음.**

## 12. 실제 Threads 발행 여부

**없음.**

## 13. 실제 YouTube 업로드 여부

**없음.**

## 14. 실제 Naver 게시 여부

**없음.**

## 15. 변경 파일

**신규**:
- `.github/workflows/daily-media-prepare.yml`
- `tests/test_daily_media_prepare_workflow.py`
- `docs/5-30_operational_automation.md`(이 문서)

**변경**(기존 추적 파일, 정확히 1개 hunk만 - 아래 "작업 중 발견한 사고"
참고):
- `.gitignore` — `!data/tak_media_archive.json` 추가(결정 C 근거)

**이번 작업과 무관해 commit에 포함하지 않은 기존 미커밋 변경**(그대로
보존): `content_engine/__init__.py`, `content_engine/generator.py`,
`content_engine/llm_provider.py`, `content_engine/rewrite.py`,
`data/tak_brain_knowledge.json`, `tests/test_content_engine.py`,
`tests/test_media_batch.py`, 그리고 `.gitignore` 자체에 남아있는 그 외
다수의 이전 세션 미커밋 라인(YouTube MP4 gitignore, Firebase 캐시,
secrets/ 디렉터리 등 - 전부 내가 추가한 게 아니라 이미 있던 것).

**작업 중 발견한 사고 예방**: `.gitignore`가 이미 이전 세션들의
미커밋 변경(여러 줄)을 담고 있는 상태였다. `git add .gitignore`를
그대로 했다면 그 무관한 변경들까지 이번 commit에 전부 휩쓸려 들어갈
뻔했다 - `git show HEAD:.gitignore`로 커밋된 원본을 따로 뽑고, 거기에
내가 추가한 5줄(`!data/tak_media_archive.json` + 설명 주석 4줄)만 얹은
버전을 만들어 `git hash-object` + `git update-index --cacheinfo`로
**정확히 그 5줄만** git index에 올렸다(작업 트리 파일 자체는 손대지
않음 - 이전 세션들의 변경은 여전히 그대로 남아있다). `git status`가
`.gitignore`를 `MM`(staged 변경 + 남은 unstaged 변경)으로 보여주는 것으로
정확성을 확인했다.

## 16. Commit

`c677d8c` — "feat: automate approved media preparation"
(4 files changed, 856 insertions(+))

## 17. Push

`origin/main`에 반영 완료 (`b96c2ab..c677d8c`). push 후 `git fetch` +
`git log origin/main..HEAD` 결과가 비어 있음을 확인(반영 완료 재검증).

## 18. 남은 작업

- `data/tak_media_archive.json`이 실제로 한 번도 git에 커밋된 적이 없다
  (로컬에 파일 자체가 아직 없다) - 이 workflow가 실제로 뭔가를
  "준비"하려면, 사람이 먼저 로컬/Codespace에서 MEDIA Dashboard로 최소
  1건을 승인하고 `data/tak_media_archive.json`을 직접 커밋/푸시해야
  한다. 이건 이번 작업의 버그가 아니라 원래 그렇게 설계된 흐름(2장/3장
  "결정 C" 참고)이지만, 사람이 이 사실을 놓치기 쉬우므로 운영 문서에
  "Dashboard 승인 후 archive를 커밋/푸시하는 것을 잊지 말 것"이라는
  안내가 필요하다.
- Rollback, Audit Log는 설계 검토만 하고 구현하지 않았다(8장/9장 근거).
- Blog Pack의 "실제로 포함된 content_id 목록"을 추적하는 기능은 여전히
  없다(5-29의 남은 작업과 동일).

## 19. 다음 단계 제안

1. `docs/`(또는 README)에 "MEDIA Dashboard 승인 후 `data/tak_media_
   archive.json`을 커밋/푸시해야 daily-media-prepare.yml이 그 승인을
   볼 수 있다"는 운영 가이드 한 줄 추가 - 이번 작업에서 발견한 가장 중요한
   운영상 함정이다.
2. `daily-media-prepare.yml`을 실제로 최소 1회 `workflow_dispatch`(
   `dry_run: true`)로 수동 실행해, 실제 GitHub Actions 환경(이 샌드박스가
   아닌 진짜 러너)에서도 동일하게 동작하는지 확인 - 이 문서의 검증은
   전부 로컬 시뮬레이션이었다.
3. Shorts Script가 쌓인 뒤 "렌더링 대상 후보 목록"을 사람이 한눈에 보는
   방법(예: `find data/shorts_scripts -newer <어제 커밋>`) 문서화.
4. Rollback을 실제로 구현하게 될 경우, 채널별 진행 단계를 먼저
   열거하는 설계 문서를 8장 내용을 기반으로 별도로 작성.
5. Audit Log가 실제로 필요해지는 시점(예: 운영자가 2명 이상이 되는 경우)이
   오면, 그때는 archive를 append-only로 바꾸는 마이그레이션 자체를 먼저
   설계해야 한다 - 지금 스키마에 필드만 추가하는 식으로는 풀리지 않는다는
   점을 9장에 남겨둔다.
