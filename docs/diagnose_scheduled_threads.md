# Scheduled Threads 진단

이 문서는 읽기 전용 점검 결과다. **이번 점검에서 코드 수정, 커밋/푸시, 실제 Threads 게시는
전혀 수행하지 않았다.** 모든 사실은 로컬 저장소 상태(`git log`, `git show`)와 GitHub CLI
(`gh`)로 조회한 실제 API 응답을 근거로 작성했다.

---

## 1. 확인된 사실

1. **workflow 파일은 main 브랜치에 실제로 존재하며 로컬과 완전히 동일하다.**
   - `.github/workflows/daily-threads-post.yml`이 로컬 워킹 디렉터리에 존재.
   - `git ls-files`로 git 추적 대상임을 확인.
   - `git show origin/main:.github/workflows/daily-threads-post.yml`로 원격 main의 내용을
     받아 로컬 파일과 `diff` 했을 때 **완전히 동일**(차이 없음).

2. **schedule 설정 자체는 문법상 정확하다.**
   - `on.schedule[0].cron: '0 23 * * *'` — UTC 23:00 = KST 08:00(다음날), 파일 내 주석과
     실제 cron 표현식이 일치함. 5-필드 표준 cron 문법으로 문법 오류 없음.
   - `on.workflow_dispatch.inputs.dry_run`도 정상 구조.

3. **이 workflow 파일은 저장소 역사상 딱 한 번, 최근에 추가되었다.**
   - `git log --diff-filter=A -- .github/workflows/daily-threads-post.yml` 결과:
     커밋 `6e000c7`, 시각 **2026-09-13 12:53:53 UTC**, 메시지 "feat: automate daily Threads
     publishing". 이 파일이 저장소에 존재한 것은 이 시점부터이며, 그 이전 커밋 이력에는
     이 workflow 자체가 없었다.

4. **GitHub Actions가 이 workflow를 등록(active)한 시각도 같은 시점이다.**
   - `gh api repos/.../actions/workflows` 결과: `id=357097842`,
     `state="active"`, `created_at="2026-09-13T12:56:33.000Z"`.
   - 즉 GitHub이 이 workflow의 schedule 트리거를 인식하기 시작한 시점은
     **2026-09-13 12:56:33 UTC**이며, 그 이전에는 이 workflow의 schedule이 GitHub 서버에
     전혀 등록되어 있지 않았다.

5. **오늘(2026-09-13) KST 08:00에 해당하는 UTC 시각은 이미 workflow 생성 이전이었다.**
   - KST 08:00(2026-09-13) = UTC 2026-09-12 23:00.
   - workflow가 GitHub에 등록된 시각은 UTC 2026-09-13 12:56:33 — 즉 **문제의 "오늘 KST
     08:00" 시점보다 약 14시간 뒤에** workflow가 처음 생성되었다.

6. **실제 workflow 실행 이력은 수동 실행(workflow_dispatch) 3건뿐이며, schedule 이벤트로
   실행된 기록은 전무하다.**
   - `gh api repos/.../actions/workflows/357097842/runs` 결과 3건 모두 `event:
     "workflow_dispatch"` (실패 1건 13:07:15, 성공 2건 13:17:09 / 13:40:37 UTC).
   - `event: "schedule"`인 run은 하나도 없음.

7. **cron이 등록된 이후 처음 도래하는 schedule 시각은 2026-09-13 23:00 UTC(=2026-09-14
   KST 08:00)이며, 점검 시점(2026-09-13 23:10 UTC) 기준으로 아직 확정적으로 판단하기엔
   이르다.**
   - 점검 시각(`date -u` = 2026-09-13 23:10:42 UTC) 기준으로 이 최초 schedule 시각을
     10분 정도 지난 상태였으나, 그 시점까지도 `event: "schedule"` run은 나타나지 않았다.
   - GitHub Actions의 schedule 트리거는 부하 상황에 따라 수 분~수십 분 지연될 수 있다고
     공식적으로 알려져 있어, 10분 경과만으로 "누락되었다"고 단정할 근거는 부족하다. 다만
     이 문서 작성 시점까지는 해당 첫 실행이 아직 관측되지 않았다는 사실 자체는 기록해 둔다.

8. **저장소는 fork가 아니고, archived/disabled 상태도 아니다.**
   - `gh api repos/sopptak/tak-auto` 결과: `{"fork": false, "archived": false,
     "disabled": false}`. (GitHub은 fork 저장소의 scheduled workflow를 기본적으로
     비활성화하는데, 이 저장소는 fork가 아니므로 이 문제는 해당하지 않는다.)

9. **저장소 자체가 매우 최근에 생성되었다.**
   - `git log --reverse` 최초 커밋 시각: 2026-09-10 16:13:53 +0900. 최신 커밋(main HEAD)
     시각: 2026-09-13 22:57:15 UTC. GitHub은 60일 이상 커밋이 없는 저장소의 scheduled
     workflow를 자동 비활성화하지만, 이 저장소는 생성된 지 며칠밖에 되지 않아 이 규칙에
     해당하지 않는다.

10. **일부 저장소 설정(Actions 권한, 기본 workflow 권한)은 현재 인증 토큰으로 조회할 수
    없었다.**
    - `gh api repos/.../actions/permissions` 및 `.../actions/permissions/workflow` 호출이
      모두 `403 Resource not accessible by integration`으로 실패. 이는 현재 세션에 발급된
      GitHub 토큰(`GITHUB_TOKEN`, `ghu_...`)의 권한 범위 밖이라는 뜻이며, "그 설정이
      잘못되어 있다"는 근거는 아니다 — **단순히 이 세션에서는 확인할 수 없었다는 사실**만
      기록한다.
    - 같은 이유로 `gh secret list`도 `403`으로 실패해 Secrets 목록(이름조차)을 확인할 수
      없었다. 다만 아래 11번 사실이 Secrets가 실제로 존재하고 정상 동작함을 간접적으로
      증명한다.

11. **Secrets는 최소한 수동 실행 기준으로는 정상 동작했다.**
    - 3건의 수동 실행 중 마지막 성공 실행(2026-09-13T13:40:37Z)이 실제로
      `data/threads_publish_log.json`을 변경했고, 그 결과 커밋 `7833255`
      ("chore: update Threads publish history")가 **`github-actions[bot]`** 계정으로
      2026-09-13T13:44:03Z에 자동 생성되었다. 이는 workflow의 live 게시 경로가 실제로
      `THREADS_ACCESS_TOKEN` 등 Secrets를 사용해 끝까지 성공했다는 뜻이다(수동 실행
      기준). 즉 Secrets 미설정이 원인일 가능성은 낮다(다만 schedule 컨텍스트에서도 동일
      Secrets가 노출되는지는 이 토큰 권한으로는 직접 확인 불가 — 통상적으로 schedule과
      workflow_dispatch는 같은 repository secrets를 공유하므로 문제가 될 가능성은 낮다).

---

## 2. 정상인 부분

- workflow YAML 문법 자체(스텝 구조, `if` 조건, `permissions`, `concurrency`)에는 문제가
  없다 — 실제로 3건의 workflow_dispatch 실행이 정상적으로 파싱되고 실행되었다.
- `schedule.cron` 표현식(`'0 23 * * *'`)은 KST 08:00 목표와 정확히 일치하며 문법 오류가
  없다.
- workflow 파일은 main(기본 브랜치)에 존재하며 로컬과 원격이 100% 동일하다 — "파일이
  실제로는 다른 브랜치에만 있다" 같은 문제는 아니다.
- 저장소는 fork가 아니고 archived/disabled도 아니므로, GitHub이 scheduled workflow를
  구조적으로 막는 대표적인 두 사유(fork 기본 비활성화, 저장소 비활성화)에는 해당하지
  않는다.
- 저장소가 생성된 지 며칠밖에 되지 않아 "60일 미활동으로 인한 schedule 자동 비활성화"
  규칙과도 무관하다.
- GitHub Actions가 이 workflow를 `state: "active"`로 인식하고 있다 — workflow 자체가
  "disabled(비활성화)" 상태는 아니다.
- Secrets는 최소한 수동 실행 기준으로 정상 동작이 확인되었다(실제 게시 성공 + history
  커밋/푸시까지 완주).

---

## 3. 의심되는 원인

아래는 이번 점검에서 실제로 관측된 사실에 기반한 가설이며, 확정 여부에 따라 표시했다.

1. **(사실상 확정) workflow가 문제의 "오늘 KST 08:00" 시점에는 아예 존재하지 않았다.**
   해당 시각(UTC 2026-09-12 23:00)은 workflow 최초 등록 시각(UTC 2026-09-13 12:56:33)보다
   약 14시간 앞선다. GitHub은 workflow 파일이 등록되기 이전 시점의 schedule을 소급 실행하지
   않는다 — 이는 GitHub Actions의 알려진 동작이며, 이번 점검에서 실제로 그 시점에 run이
   전혀 생성되지 않았다는 사실(§1-6)과도 정합적이다.

2. **(가능성 있음, 미확정) 다음 schedule 시각(2026-09-13 23:00 UTC)의 최초 실행이 아직
   지연 중이거나, 이 문서 작성 시점 이후에 발생할 가능성.** 점검 시점이 그 시각을 10분
   남짓 지난 상태였고, GitHub의 schedule 실행은 공식적으로 "정확한 시각 보장이 아닌
   best-effort"로 문서화되어 있어(부하가 높을 때 지연 발생), 이 시점만으로는 "두 번째도
   실패했다"고 결론 내릴 수 없다.

3. **(가능성 낮음, 확인 불가) 저장소/조직 수준의 Actions 정책이 scheduled workflow를
   추가로 제한하고 있을 가능성.** `actions/permissions` API가 403으로 막혀 있어 이
   세션에서는 직접 확인할 수 없었다. 다만 수동 dispatch는 정상 동작했으므로, Actions 자체가
   완전히 막혀 있는 상태는 아니다 — 있다면 "schedule 이벤트만 선택적으로 제한하는" 조직
   정책 정도의 좁은 가능성만 남는다.

4. **(가능성 매우 낮음) 최근 커밋들이 default branch를 자주 바꿨을 가능성.** 확인 결과
   `origin`의 default branch는 시종일관 `main`이었고, workflow 파일도 계속 `main`에만
   존재했다. 이 가설은 실측으로 배제된다.

---

## 4. 가장 가능성 높은 원인

**workflow(및 그 안의 schedule 트리거)가 GitHub에 등록된 시각(2026-09-13 12:56:33 UTC)이,
사용자가 기대한 "오늘 KST 08:00" 실행 시각(2026-09-12 23:00 UTC)보다 약 14시간 늦다.**

즉 코드나 YAML 문법의 결함이 아니라, **"scheduled workflow를 추가한 시점 자체가 오늘 아침
목표 시각보다 늦었다"는 시점(timing) 문제**다. GitHub Actions는 schedule 트리거를 위해
"cron 표현식이 가리키는 미래 시각"만 큐에 등록하며, workflow 파일이 아직 존재하지 않았던
과거 시각의 schedule을 소급 실행하지 않는다. 이번 저장소의 경우:

- 오늘 새벽 KST 08:00(UTC 전날 23:00) 시점 → workflow 자체가 아직 저장소에 없었음(당연히
  미실행).
- 그 이후 낮 시간에 workflow가 추가되고 GitHub이 이를 인식(active).
- 다음으로 cron 조건을 만족하는 시각은 오늘 UTC 23:00(=내일 KST 08:00)이며, 이는 아직
  결과를 판단하기엔 이른 시점(점검 당시 10분 경과)이다.

따라서 "매일 KST 08:00에 정상적으로 실행되지 않는다"는 근본 결함이 아니라, **workflow를
등록한 첫날치고는 당연한 결과**일 가능성이 가장 높다. 이 결론이 맞다면, 내일(2026-09-14)
KST 08:00 전후로 `event: "schedule"` run이 정상적으로 나타나야 한다.

---

## 5. 해결 방법 후보

아래는 모두 "이렇게 하면 된다"는 제안일 뿐이며, **이번 점검에서 실행하지 않았다.**

1. **다음 schedule 시각(오늘 UTC 23:00 / 내일 KST 08:00) 이후 다시 확인한다.** 가장
   비용이 낮고 확실한 방법. `gh run list --workflow=daily-threads-post.yml`로
   `event: "schedule"` run이 생성되었는지 재확인.
2. **그래도 schedule run이 생성되지 않으면, Actions 탭 UI에서 해당 workflow 페이지 상단에
   "This scheduled workflow is disabled" 같은 배너가 있는지 사람이 직접 확인한다.** 이
   배너는 API로는 완전히 동일하게 노출되지 않는 경우가 있어 웹 UI 확인이 더 확실하다.
3. **저장소 Settings → Actions → General에서 "Allow all actions and reusable workflows"
   및 scheduled workflow 관련 옵션이 켜져 있는지 사람이 직접 확인한다.** 이번 세션의 토큰
   권한으로는 이 설정을 API로 조회할 수 없었다(§1-10).
4. **필요하다면 빈 커밋(예: `git commit --allow-empty -m "chore: touch"`)으로 default
   branch를 한 번 더 push해 GitHub의 workflow 캐시를 확실히 갱신시키는 방법도 있다.**
   다만 이번 사례는 이미 workflow가 `state: active`로 정상 인식되어 있어 필요성은 낮다.
5. **cron 시각을 등록 직후에도 바로 검증하고 싶다면, `workflow_dispatch`로 대체 실행하는
   현재 운영 방식(이미 3회 수행됨)을 당분간 유지**하면서 schedule은 "내일 아침 결과"로
   판단하는 것을 권장.

---

## 6. 코드 수정 필요 여부

**현재까지 확인된 사실만으로는 코드/YAML 수정이 필요하다는 근거가 없다.**

- cron 표현식, trigger 구조, permissions, concurrency 설정 모두 문법·논리상 정상이다.
- 문제의 원인으로 가장 유력한 것(§4)은 "workflow를 등록한 시점이 오늘 아침 목표 시각보다
  늦었다"는 **시점 문제**이지, YAML이나 스크립트의 결함이 아니다.
- 따라서 다음 schedule 시각(오늘 UTC 23:00 / 내일 KST 08:00) 이후에도 `event: "schedule"`
  run이 전혀 생성되지 않는 경우에만, 그 시점에 코드 수정 여부를 재검토하는 것이 합리적이다.
  (그 경우에도 우선 §5의 UI/설정 확인이 먼저이며, YAML 자체를 바꿀 근거는 이번 점검에서는
  발견되지 않았다.)

---

## 7. 다음 조치

1. **관찰 대기**: 오늘 UTC 23:00(=내일 KST 08:00) 이후 `gh run list --repo sopptak/tak-auto
   --workflow=daily-threads-post.yml`로 `event: "schedule"` run이 생성되었는지 재확인한다.
2. **UI 재확인**: GitHub 웹의 Actions 탭에서 workflow 페이지 상단에 비활성화 경고 배너가
   있는지 사람이 직접 확인한다(API 토큰 권한 제약으로 이번 세션에서는 확인 불가했던 부분,
   §1-10).
3. **설정 재확인**: 저장소 Settings → Actions에서 scheduled workflow 관련 옵션이 켜져
   있는지 사람이 직접 확인한다(같은 이유로 이번 세션에서는 API로 확인 불가).
4. **위 1~3에서도 schedule run이 계속 생성되지 않을 경우에만** 코드/YAML 수정 여부를 별도
   단계에서 다시 논의한다 — 이번 점검 결과만으로는 수정이 필요하다는 근거가 없으므로
   지금 단계에서 YAML을 건드리지 않는다.

---

**이번 점검에서는 코드 수정, 커밋/푸시, 실제 Threads 게시를 전혀 수행하지 않았다. 읽기
전용 조회(`git log`, `git show`, `git diff`, `gh api`, `gh run list`, `gh workflow list`,
`gh repo view`)만 수행했다.**
