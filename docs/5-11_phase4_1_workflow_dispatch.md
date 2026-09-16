# 5-11 Phase 4-1 구현 보고서 — `publish-approved-threads.yml` (workflow_dispatch 전용)

> 이번 Phase는 GitHub Actions에서 승인된 Threads 초안 발행 시스템을
> "workflow_dispatch 수동 실행"으로만 먼저 안전하게 연결한다. **schedule(cron)은
> 추가하지 않았고, 기존 `daily-threads-post.yml`도 전혀 수정하지 않았다.
> 실제 Threads API 호출, 실제 GitHub Actions 실행, 운영 데이터 변경, git
> commit/push는 전혀 수행하지 않았다.**

## 0. 다시 읽은 파일

`docs/5-11_phase4_github_actions_design.md`, `docs/5-11_phase3_publish_approved_threads.md`,
`scripts/publish_approved_threads.py`, `content_engine/threads_review.py`,
`content_engine/publish_history.py`, `content_engine/threads_publisher.py`,
`.github/workflows/daily-threads-post.yml`(전문 재확인), `tests/test_publish_approved_threads.py`.

Phase 4 설계 문서(10장)가 지적한 두 가지 테스트 갭을 실제 코드 변경 전에
먼저 보강했다.

## 1. 변경 파일

| 구분 | 파일 |
|---|---|
| 신규 | `.github/workflows/publish-approved-threads.yml` |
| 수정 | `tests/test_publish_approved_threads.py` (테스트 갭 2건 보강 + `FakeThreadsClient`에 순차 결과 큐 지원 추가) |
| 신규 | `docs/5-11_phase4_1_workflow_dispatch.md` (본 보고서) |

`scripts/publish_approved_threads.py`, `content_engine/threads_review.py`,
`content_engine/publish_history.py`, `content_engine/threads_publisher.py`는
**한 글자도 수정하지 않았다** — Phase 4-1은 순수하게 기존 스크립트를 감싸는
workflow 배선 작업이다. `.github/workflows/daily-threads-post.yml`,
`scripts/publish_threads.py`, `scripts/run_scout_dashboard.py`도 무수정.

## 2. workflow 구조

`publish-approved-threads.yml`은 단일 job(`publish-approved`)에 8개 스텝으로
구성된다:

```
1. Checkout repository
2. Set up Python (3.14)
3. Show Python version
4. Run existing test suite            (python3 -m unittest discover ...)
5. Publish (dry-run)   [id: publish_dry_run]  if: dry_run == 'true'
6. Publish (live)      [id: publish_live]     if: dry_run == 'false'
7. Check for pending/history changes  [id: publish_diff]  if: always() && (5 또는 6이 success/failure)
8. Commit and push publish results    if: publish_diff.outputs.changed == 'true'
```

트리거는 오직 `workflow_dispatch`이며, `schedule`/`push` 트리거는 이번
Phase에서 의도적으로 넣지 않았다. `permissions: contents: write`만 사용,
`concurrency: group: publish-approved-threads, cancel-in-progress: false`를
그대로 적용했다(요청받은 값 그대로).

## 3. `dry_run=true` 동작

5번 스텝(`id: publish_dry_run`)만 `if: github.event.inputs.dry_run == 'true'`
조건으로 실행되며, 커맨드는 항상:

```bash
python3 scripts/publish_approved_threads.py --dry-run          # content_id 없을 때
python3 scripts/publish_approved_threads.py --dry-run --id "$CONTENT_ID"   # 있을 때
```

**`--execute`는 이 스텝의 어떤 분기에도 등장하지 않는다.** 이 스텝의 `env:`
블록에는 `THREADS_ACCESS_TOKEN`을 아예 넘기지 않았다 — `--dry-run` 경로는
`ThreadsClient.from_environment()` 호출 지점에 도달하지 않는다는 사실이
Phase 3 self-review(1번, PASS)로 이미 증명되어 있으므로, 토큰을 애초에
필요로 하지 않는 스텝이라는 것을 env 배선으로도 드러냈다. Threads API
호출·pending/history 파일 변경이 없다는 것은 `scripts/publish_approved_threads.py`
자체의 계약(Phase 3)이며, 이번 Phase 4-1에서 그 계약을 실제로 실행해
검증하지는 않았다(9장 "실제 GitHub Actions 미실행" 참고) — 대신 로컬
unittest로 이미 검증된 계약을 그대로 신뢰하고 workflow는 "올바른 플래그로
스크립트를 호출하는가"만 담당한다.

## 4. `dry_run=false` 동작

6번 스텝(`id: publish_live`)만 `if: github.event.inputs.dry_run == 'false'`
조건으로 실행되며, 커맨드는:

```bash
python3 scripts/publish_approved_threads.py --execute
python3 scripts/publish_approved_threads.py --execute --id "$CONTENT_ID"
```

이 스텝의 `env:` 블록에만 `THREADS_ACCESS_TOKEN: ${{ secrets.THREADS_ACCESS_TOKEN }}`을
넘긴다. 5번/6번 스텝의 `if` 조건은 서로 배타적(`== 'true'` vs `== 'false'`)이며,
`dry_run` input이 `required: true`인 boolean이라 이 두 값 외의 상태로 이
workflow가 실행될 수 없다 — **동시 실행은 YAML 구조상 불가능하다**(3번
안전 조건 충족).

## 5. content_id 전달 방식

두 발행 스텝 모두 동일한 패턴을 쓴다:

```bash
if [ -n "$CONTENT_ID" ]; then
  python3 scripts/publish_approved_threads.py --dry-run --id "$CONTENT_ID"   # (또는 --execute)
else
  python3 scripts/publish_approved_threads.py --dry-run                      # (또는 --execute)
fi
```

`CONTENT_ID`는 `env: CONTENT_ID: ${{ github.event.inputs.content_id }}`로
주입되며, `content_id` input의 기본값이 빈 문자열(`""`)이므로 `-n "$CONTENT_ID"`
(비어있지 않을 때만 참) 조건으로 정확히 "값이 있으면 `--id` 전달, 없으면
전달하지 않음"을 구현했다. 스크립트 자체는 이미 `--id`를 지원하므로(Phase 3),
새 코드는 필요 없었다.

## 6. secret 처리

`THREADS_ACCESS_TOKEN`은 기존 `daily-threads-post.yml`과 **정확히 동일한
이름**(`secrets.THREADS_ACCESS_TOKEN`)으로 참조한다 — 새 시크릿을 만들지
않았다. 이 토큰은 `publish_live` 스텝의 `env:` 블록에만 존재하며, `run:`
블록의 어떤 셸 명령에서도 `echo`/`print`로 노출하지 않는다(직접 grep으로
확인 — 아래 10장). `publish_dry_run` 스텝에는 이 시크릿을 아예 넘기지 않아,
dry-run 경로에서는 프로세스 환경변수에조차 토큰이 존재하지 않는다(추가적인
방어층). `scripts/run_scout_dashboard.py`(Dashboard)는 이번 Phase에서도
전혀 수정하지 않았으므로 Dashboard에는 여전히 토큰이 없다.

## 7. concurrency

```yaml
concurrency:
  group: publish-approved-threads
  cancel-in-progress: false
```

요청받은 값 그대로 적용했다. `cancel-in-progress: false`이므로 같은
workflow가 겹쳐 트리거되면 두 번째 실행은 취소되지 않고 첫 실행이 끝날
때까지 큐에서 대기한다 — 실행 중인 발행을 취소하면 API 호출은 끝났지만
커밋 전에 잘릴 수 있어, 다음 실행이 그 상태를 못 보고 같은 draft를 다시
처리하려 들 위험이 더 크다는 기존 `daily-threads-post.yml`의 근거를 그대로
계승했다. (설계 문서 7장에서 지적했듯, 이 큐잉은 **같은 workflow 파일
안에서만** 유효하고, `daily-threads-post.yml`처럼 다른 workflow 파일과는
그룹이 공유되지 않는다 — 이 위험은 Phase 4-3에서 기존 workflow 비활성화로
해소할 계획이며, 이번 Phase 4-1은 아직 그 단계가 아니다.)

## 8. 부분 실패 시 commit 처리

요청하신 핵심 요구사항 — "publish script가 여러 approved 항목을 처리하다가
일부 실패해 exit code 1이 되어도, 성공한 항목의 published/PublishHistory와
실패한 항목의 failed 상태가 모두 커밋되어야 한다"를 다음과 같이 구현했다:

```yaml
- name: Check for pending/history changes
  id: publish_diff
  if: |
    always() &&
    (steps.publish_dry_run.outcome == 'success' || steps.publish_dry_run.outcome == 'failure' ||
     steps.publish_live.outcome == 'success' || steps.publish_live.outcome == 'failure')
  run: ...
```

- `always()`는 앞선 스텝의 성공/실패와 무관하게 이 스텝을 평가하게 만든다.
- 다만 `steps.publish_dry_run.outcome`/`steps.publish_live.outcome`이
  `success` 또는 `failure`일 때만 실제로 실행되도록 추가 조건을 걸었다 —
  두 스텝 모두 애초에 **실행되지 않은(outcome == 'skipped')** 경우(예: 4번
  "테스트 스위트" 스텝이 실패해 5/6번 스텝이 GitHub Actions의 기본 규칙에
  따라 자동으로 건너뛰어진 경우)는 이 조건이 거짓이 되어 diff 체크/커밋
  스텝 자체가 실행되지 않는다.
- 즉 **"발행 스크립트가 실제로 한 번이라도 실행된 경우"에는 exit code와
  무관하게 커밋 후보가 되고, "발행 스크립트가 아예 실행되지 못한 경우"에는
  커밋 후보가 되지 않는다** — 요청하신 정확한 경계를 만족한다.
- 커밋 대상은 `data/tak_threads_pending.json`, `data/threads_publish_log.json`
  **정확히 이 두 파일뿐**이다(`git add` 대상도 이 두 경로로 한정, `git diff
  --cached --quiet -- <두 경로>`로 diff 유무 판정). 다른 파일은 어떤 경로로도
  `git add`되지 않는다.
- job 자체의 성공/실패 표시(빨간 X 등)는 스크립트의 exit code를 그대로
  따른다 — 부분 실패가 있었다는 사실은 여전히 사람에게 보이도록 의도적으로
  유지했다(자동 재시도가 없다는 Phase 3/4 설계 원칙과 일관).

## 9. 기존 workflow와의 관계

- `.github/workflows/daily-threads-post.yml`은 **한 글자도 수정하지
  않았다**(`git diff` 확인, 변경 없음).
- 두 workflow는 서로 다른 파일, 서로 다른 `concurrency.group`
  (`${{ github.workflow }}` vs `publish-approved-threads`)을 가지므로
  서로를 큐잉시키지 않는다 — 이는 설계 문서 4/7장이 이미 지적한 위험이며,
  Phase 4-1 시점에는 신규 workflow가 **workflow_dispatch로만** 실행되므로
  기존 cron과 "동시에 자동으로" 실행될 경로가 없다(사람이 의도적으로 동시에
  두 workflow를 수동/자동으로 겹쳐 트리거하지 않는 한 실무에서 발생하지
  않음). schedule 추가와 기존 cron 비활성화를 동시에 하는 것은 설계 문서
  9장 Phase 4-3의 몫으로 남겨두었다.
- 두 workflow가 호출하는 스크립트(`scripts/run_daily.py` vs
  `scripts/publish_approved_threads.py`)는 서로 다른 파일이며, 이번 Phase는
  후자만 호출한다 — 전자는 전혀 건드리지 않았다.

## 10. 테스트 결과

### 10-1. 테스트 갭 보강 (Phase 4 설계 문서 10장이 지적한 2건)

`tests/test_publish_approved_threads.py`에 `FakeThreadsClient`가 호출별로
다른 결과를 순서대로 반환/발생시킬 수 있도록 `outcomes` 파라미터를
추가하고, 아래 2개 테스트를 새로 작성했다:

**`test_multiple_approved_partial_failure_reports_correctly`**
- approved 2건(`content-first`, `content-second`)을 `--id` 없이 `--execute`.
- `FakeThreadsClient(outcomes=[ThreadsAPIError(...), ThreadsPublishResult(...)])`로
  첫 호출은 실패, 둘째 호출은 성공하도록 구성.
- 검증: `content-first` → `failed` + `failure_reason`에 "500" 포함,
  `content-second` → `published` + `threads_post_id` 저장, `PublishHistory`에는
  `content-second`만 정확히 1건 기록(`content-first`는 없음), 전체 exit
  code == 1(부분 실패를 정확히 보고), 두 draft 모두 API 호출을 받았음
  (`publish_text_calls == ["첫 번째 본문", "두 번째 본문"]`, 발행 순서 =
  pending 배열 순서와 일치).

**`test_failed_then_reapproved_then_reexecuted_succeeds`**
- 1차: approved 1건을 실패시키는 fake client로 `--execute` → `failed` 상태 +
  `failure_reason`/`failed_at` 저장, `PublishHistory` 완전히 비어있음 확인.
- 재승인 전 재실행: `ThreadsClient.from_environment`가 호출되면
  `AssertionError`를 던지도록 patch한 채 다시 `--execute` 실행 → exit
  code 0(대상 없음, `failed`는 `load_approved_drafts()`에서 필터링되어
  자동으로 다시 대상이 되지 않음을 확인) + 상태가 여전히 `failed`로 불변.
- `mark_approved(failed_draft, ...)`로 사람의 재승인을 시뮬레이션(Phase 1
  `failed → approved` 전이, 무수정 재사용) → `upsert_pending()`으로 저장.
- 2차: 성공하는 fake client로 다시 `--execute` → `published` +
  `threads_post_id` 저장, `PublishHistory`에 정확히 1건 기록됨을 확인.

### 10-2. `tests/test_publish_approved_threads.py` 전체

```
python3 -m unittest tests.test_publish_approved_threads -v
Ran 24 tests in 0.073s
OK
```

기존 22개 + 신규 2개 = **24/24 PASS**.

### 10-3. 전체 테스트 스위트

```
python3 -m unittest discover -s tests -p 'test_*.py'
Ran 457 tests in 26.634s
OK
```

기존 455개 + 신규 2개 = **457/457 PASS**. 기존 테스트는 한 줄도 수정하지
않았다(`FakeThreadsClient`에 파라미터를 추가만 했을 뿐, 기존 호출부의
동작은 그대로다 — `outcomes=None`이면 기존 `result`/`error` 방식 그대로
동작).

### 10-4. workflow YAML 정적 검증

로컬에 `actionlint`가 없어 공식 배포 스크립트로 임시 다운로드해 검증한 뒤
바로 삭제했다(저장소에 흔적 없음, `git status`로 확인):

```
$ ./actionlint .github/workflows/publish-approved-threads.yml
(출력 없음, exit code 0)

$ ./actionlint .github/workflows/daily-threads-post.yml
(출력 없음, exit code 0 — 기존 workflow도 문제 없음을 함께 확인해 도구 자체가
 정상 동작함을 교차 검증)
```

`actionlint`는 YAML 문법뿐 아니라 GitHub Actions 표현식(`${{ }}`) 문법,
`if:` 조건 오타, 액션 버전 등을 검사하는 전용 정적 분석 도구이며, 신규
workflow에서 오류 0건을 확인했다. 추가로 `python3 -c "import yaml; ..."`로
YAML 자체의 파싱 가능 여부와 `on`/`permissions`/`concurrency`/`jobs.*.steps`
구조(스텝 8개, `id`/`if` 배치)를 직접 출력해 의도한 구조와 일치함을
육안으로도 재확인했다.

## 11. 실제 Threads API 호출 여부

**없음.** 이번 Phase는 workflow YAML 파일과 로컬 unittest만 작성/실행했다.
신규 테스트 2건도 기존 22건과 동일하게 `mock.patch.object(ThreadsClient,
"from_environment", ...)`로 실제 네트워크를 완전히 대체했다. `THREADS_ACCESS_TOKEN`
환경변수를 이 세션에서 설정하거나 사용한 적이 없다.

## 12. 운영 데이터 변경 여부

**없음.** `data/tak_threads_pending.json`은 이 저장소에 여전히 존재하지
않는다(`ls` 결과 No such file or directory). `data/threads_publish_log.json`은
`git diff --stat`으로 변경 없음을 확인했다(마지막 변경 커밋은 이전 세션의
것). 모든 신규 테스트는 `tempfile.TemporaryDirectory()` 기반 임시 경로만
사용했다.

## 13. git commit/push 여부

**없음.** 이번 Phase에서 생성/수정한 파일은 다음 3개뿐이며, `git add`/`git
commit`/`git push`는 전혀 실행하지 않았다:

```
?? .github/workflows/publish-approved-threads.yml
 M tests/test_publish_approved_threads.py
?? docs/5-11_phase4_1_workflow_dispatch.md
```

`.github/workflows/daily-threads-post.yml`, `scripts/publish_threads.py`,
`content_engine/publish_history.py`, `content_engine/threads_publisher.py`,
`scripts/run_scout_dashboard.py`는 `git diff --stat` 결과 변경 없음(무수정
확인). 실제 GitHub Actions에서 이 workflow를 실행한 적도 없다(트리거된
run 없음, 로컬 검증만 수행).

## 14. 남은 Phase 4-2 작업

1. **실제 GitHub Actions 환경에서 `dry_run=true` 1회 수동 실행** — 이번
   Phase는 로컬 unittest + actionlint 정적 검증까지만 했고, 실제 워크플로
   실행 로그는 아직 확인하지 않았다. 설계 문서 9장 Phase 4-2의 첫 단계.
2. **실제 승인된 draft가 정확히 1건 있을 때 `dry_run=false`로 딱 한 번
   수동 실행**해 실제 발행 1건이 의도대로 동작하는지 확인(설계 문서 9장).
   이 시점까지 cron은 추가하지 않는다.
3. **`content_id` 입력값 경로의 실제 GitHub Actions 실행 검증** — 로컬
   unittest는 `--id` 옵션 자체가 스크립트 레벨에서 올바르게 동작함을
   Phase 3에서 이미 검증했지만, workflow의 bash 조건문(`if [ -n
   "$CONTENT_ID" ]`)이 실제 GitHub Actions 러너에서 정확히 같은 방식으로
   해석되는지는 아직 실행해보지 않았다.
4. **동시 실행 큐잉(concurrency)의 실제 동작 확인** — 같은 workflow를
   짧은 간격으로 두 번 수동 트리거해, 두 번째 실행이 "Queued"로 대기하는지
   GitHub Actions UI에서 육안 확인(자동화 불가 항목, 설계 문서 10장).
5. **부분 실패 시나리오의 실제 워크플로 로그 확인** — 로컬 테스트로는
   "여러 approved 항목 중 일부 실패 시 job이 실패로 표시되면서도 커밋은
   정상적으로 이루어지는지"를 코드 레벨로만 검증했다. 실제 GitHub Actions
   UI에서 이 job이 정말 "빨간 X + 성공한 커밋"의 조합으로 보이는지 사람이
   한 번은 직접 확인해야 한다.
6. **Phase 4-3 준비**: 위 검증이 모두 끝나면 `schedule` 트리거 추가와
   기존 `daily-threads-post.yml`의 cron 비활성화를 **동시에** 진행하는
   것을 설계 문서 9장이 이미 권고했다 — Phase 4-2가 끝나기 전까지는
   손대지 않는다.
