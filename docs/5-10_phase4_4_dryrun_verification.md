# 5-10 Phase 4-4 — 실제 운영 반영 후 rotation 검증 (GitHub Actions dry-run 진단)

## 1. 목적

Phase 4-4 rotation 커밋(`fcc1bd8`)이 `origin/main`에 반영된 뒤, **실제 Threads를
발행하지 않고** GitHub Actions의 dry-run을 1회 실행해 현재 실제 history/KNOWLEDGE
데이터 기준으로 다음 자동 선택 후보가 rotation 정책대로 바뀌었는지 확인한다.
코드 수정, commit, push, 실제 Threads 발행, history/운영 데이터 수정은 전혀
하지 않는다.

## 2. 원격 상태 확인

```
git fetch origin
git status --short   → 이번 Phase 4-4 관련 unrelated 변경 없음(다른 untracked 파일만 존재)
git rev-parse origin/main → 926e58ff50df1383d9ff0f5f71013512dac560e4
```

`f1c1b8d`(사용자 메시지에 언급된 커밋 해시)는 `git cat-file -t f1c1b8d` 결과
**존재하지 않는 객체**였다 — 오타로 판단. 실제 Phase 4-4 커밋은 `fcc1bd8`이며,
`git merge-base --is-ancestor fcc1bd8 origin/main` 결과 **true** — Phase 4-4가
`origin/main`에 정상적으로 포함되어 있음을 확인했다.

## 3. workflow 파일 확인

`.github/workflows/daily-threads-post.yml` 확인 결과: `workflow_dispatch`
입력값 `dry_run`(기본값 `true`)에 따라 "dry-run" 스텝과 "live" 스텝이 상호
배타적 `if` 조건으로 정확히 하나만 실행되도록 설계되어 있음을 확인.

## 4. workflow_dispatch 실행 시도 — 권한 문제 발견

```
gh workflow run daily-threads-post.yml -f dry_run=true
→ 실패: HTTP 403: Resource not accessible by integration
```

`gh auth status` 확인 결과 이 세션의 토큰은 Codespaces가 발급한 GitHub App
토큰(`ghu_...`)이었다. `gh api repos/.../permissions` 조회 결과 `admin`/`push`
권한은 있었으나, **GitHub이 이런 토큰에는 의도적으로 `workflow_dispatch` API
호출 권한을 막아둔다**(Actions 실행을 통한 권한 상승을 막기 위한 정책) — 저장소
권한과 무관하게 발생하는 제약임을 확인했다.

이 문제를 해결할 방법을 사용자에게 질의(AskUserQuestion)한 결과, **"사용자가
GitHub 웹 UI에서 직접 실행"**을 선택받았다.

## 5. 실행된 workflow run 확인

`gh run list --workflow=daily-threads-post.yml`로 조회한 결과, 새 workflow_dispatch
run(`34927542094`, 2026-09-15T04:06:43Z, 결과 success)을 발견했다.

## 6. ⚠️ 핵심 발견 — 이번 실행은 dry-run이 아니라 실제(live) 게시였음

`gh run view 34927542094 --json jobs`로 스텝별 결과를 확인한 결과:

| 스텝 | 결과 |
|---|---|
| `Run daily orchestrator (dry-run, no actual Threads post)` | **skipped** |
| `Run daily orchestrator (live, actual Threads post)` | **success** |
| `Check for publish history changes` | success |
| `Commit and push publish history` | **success** |

→ `dry_run` 입력값이 `true`가 아니라 `false`로 전달되어, **실제 게시 경로로
실행되었다.**

## 7. `python3 scripts/run_daily.py` 스텝 로그 (테스트 fixture 이후, 실제 실행분만)

```
TAK BRAIN: 승인 KNOWLEDGE 4건 확인
TAK MEDIA: 배치 실행 중 (콘텐츠 생성 + LLM 재작성 + 검증)...
TAK MEDIA 완료: 총 Draft 36건 (valid 33, rejected 0, error 3)
Threads 게시 단계 실행 중 (scripts/publish_threads.py --auto)...
Threads 계정 확인 완료: @tmong_wisdom (ID: 28696404183316849)
게시 중: 자동 선택 (게시 이력에 없는 첫 valid 항목, content_id=content-ff8909844fa80b99) KNOWLEDGE=knowledge-e1cc05264953...
성공: Threads 게시 완료! (Post ID: 18150952027524083)
```

이후 `git commit -m "chore: update Threads publish history"` (커밋 `4a3c911`) →
`git push` → `926e58f..4a3c911 main -> main` 성공.

## 8. 핵심 rotation 검증

- **예상**: 3일 연속 선택되던 `knowledge-da6ddf5aa459` 대신, 아직 history에
  등장한 적 없는 `knowledge-e1cc05264953`가 선택되어야 함.
- **실제 로그**: `knowledge-e1cc05264953` — **예상과 정확히 일치.**
- `knowledge-da6ddf5aa459`는 이번에 재선택되지 않음.

**→ rotation 로직 자체는 실제 운영 데이터로 재현·검증 완료(PASS).**

## 9. `data/threads_publish_log.json` 전후 비교

| | before (origin/main, 3건) | after (origin/main, 4건) |
|---|---|---|
| 마지막 레코드 | `knowledge-da6ddf5aa459` / `content-45d8e97f0fab7b16` (2026-09-15T01:12:52Z) | **`knowledge-e1cc05264953` / `content-ff8909844fa80b99` / Post ID `18150952027524083`** (2026-09-15T04:10:33Z) 추가 |

history가 실제로 변경되었다 — dry-run이었다면 변경되지 않았어야 할 부분이다.

## 10. 최종 출력

- **workflow run ID**: `34927542094`
- **run 결과**: success — 단, **의도한 dry-run이 아니라 실제(live) 실행**
- **선택된 knowledge_id**: `knowledge-e1cc05264953`
- **선택된 content_id**: `content-ff8909844fa80b99`
- **기존 `knowledge-da6ddf5aa459` 재선택 여부**: 재선택 안 됨(정상 rotation)
- **PublishHistory 변경 여부**: 변경됨(4번째 레코드 추가, `4a3c911` push됨) —
  dry-run 전제가 깨졌기 때문
- **실제 Threads 발행 여부**: 실제로 발생함 — Post ID `18150952027524083`
  (실제 운영 계정 `@tmong_wisdom`)
- **Phase 4-4 rotation 검증 결과**: **로직 자체는 PASS**(예측 KNOWLEDGE와 정확히
  일치, 실제 운영 데이터로 재현 확인). **다만 이번 실행은 "dry-run 검증"이라는
  절차 요건을 충족하지 못함** — GitHub UI에서 `dry_run` 값이 `false`로 실행되어
  실제 게시와 history 변경이 발생했다.

## 11. 이 세션(Claude)이 수행한 작업 범위

코드 수정·commit·push·API 게시·history/데이터 파일 수정을 전혀 하지 않았다
(로컬 저장소는 read-only 조회/fetch만 수행). 실제 게시와 history 변경은
**사용자가 웹 UI에서 실행한 workflow run(`34927542094`) 자체**에서
`dry_run=false`로 발생한 것이다.
