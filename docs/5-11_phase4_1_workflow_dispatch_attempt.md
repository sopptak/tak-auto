# Phase 4-1 — "TAK Threads Publish Approved" workflow dry_run 실행 시도

## 0. 결과 요약

**실행하지 못했다.** `gh workflow run`으로 `dry_run=true` dispatch를
시도했으나 GitHub API가 **403 Resource not accessible by integration**을
반환해 workflow가 트리거되지 않았다. **Threads 발행/실제 API 호출은 물론
일어나지 않았다** — dispatch 자체가 성립하지 않았기 때문이다.

## 1. 실행 전 확인한 전제 조건

- 대상 workflow: `TAK Threads Publish Approved (Phase 4-1, manual only)`
  (`.github/workflows/publish-approved-threads.yml`, workflow id
  `359245726`) — `gh workflow list` 결과 `active` 상태로 존재 확인.
- **중요 caveat(사전 보고 후 사용자 승인받음)**: `data/tak_threads_pending.json`
  이 아직 `origin/main`에 커밋된 적이 없어(`git log --all -- data/tak_threads_pending.json`
  결과 없음, `git show origin/main:data/tak_threads_pending.json` →
  "not in origin/main"), 설령 dispatch가 성공했더라도 원격 runner는
  방금 승인한 `content-43786cf3ee0d89c5` draft를 볼 수 없어 "발행 대상
  0건"으로 끝났을 것이다. 이 상태를 알린 뒤, 사용자가 "그래도 지금
  workflow 배선 자체만 검증하는 dry_run을 실행"하기로 결정해 진행했다
  (git add/commit/push는 하지 않음, 이 결정도 포함해서).

## 2. 실행 커맨드와 오류

```
$ gh workflow run "TAK Threads Publish Approved (Phase 4-1, manual only)" -f dry_run=true
could not create workflow dispatch event: HTTP 403: Resource not accessible by integration
(https://api.github.com/repos/sopptak/tak-auto/actions/workflows/359245726/dispatches)
```

## 3. 원인

```
$ gh auth status
github.com
  ✓ Logged in to github.com account sopptak (GITHUB_TOKEN)
  - Token: ghu_************************************

$ gh api -i user | grep -i oauth-scopes
X-Accepted-Oauth-Scopes:
X-Oauth-Scopes:
```

- 현재 `gh` CLI가 쓰고 있는 토큰은 `ghu_` 접두어의 **Codespaces가 자동
  발급한 임시 사용자 토큰**이며, OAuth scope가 비어 있다(둘 다 빈
  문자열).
- 이런 토큰은 repo 읽기/기본 git 작업에는 쓸 수 있지만, **Actions의
  workflow_dispatch API를 호출할 권한(`workflow` scope 또는 그에 준하는
  Actions 쓰기 권한)이 없다** — 그래서 GitHub 쪽에서 "Resource not
  accessible by integration"으로 거부한다. 이건 이 저장소나 workflow
  YAML의 문제가 아니라 **현재 인증된 자격 증명의 권한 부족** 문제다.

## 4. 해결하려면 (참고, 이번엔 실행하지 않음)

다음 중 하나가 필요하다(전부 사용자의 GitHub 계정 자격 증명이 필요한
작업이라 여기서 대신 실행하지 않았다):

- `workflow` scope가 포함된 GitHub Personal Access Token으로
  `gh auth login` 또는 `gh auth refresh -h github.com -s workflow`를
  실행한 뒤 다시 시도, 또는
- GitHub 웹 UI(`Actions` 탭 → `TAK Threads Publish Approved` →
  `Run workflow`)에서 사용자가 직접 `dry_run=true`로 실행.

## 5. 금지 사항 준수

- Threads API 호출: 없음 (dispatch 자체가 실패해 workflow가 시작되지
  않았음)
- git add/commit/push: 하지 않음
- 코드/데이터 수정: 하지 않음
