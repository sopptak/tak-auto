# PROJECT 2030 작업 범위 분리 및 되돌림 보고서

## 왜 되돌렸는지

이번 작업은 TAK AUTO 콘텐츠공장의 운영 병목을 해결해야 했지만, 범위를 잘못 판단해
PROJECT 2030 GoJoseon 게임 코드를 `game_lab/`에 구현하고 GitHub `main`에 push했다.
게임 기능은 콘텐츠공장 개발 범위에 속하지 않는다. 기존 게임 작업은 보존하되 이번
작업에서 추가한 내용만 `git revert`로 되돌렸다. reset, force push, 파일 수동 삭제는
사용하지 않았다.

사용자가 지정한 문서 커밋 `ef573c6`은 GitHub 이력에 존재하지 않았다. 로그와 `git
show`에서 실제 연속 커밋은 `245de0e`와 `0f573c0`으로 확인되어, 동일 작업 의도의
실제 커밋 `0f573c0`을 대상으로 삼았다.

## 되돌린 커밋

최신 커밋부터 역순으로 되돌렸다.

1. `0f573c0` — `docs: record 6-70 integration commit`
   - `docs/6-70-gojoseon-history-card-integration.md` 수정분 1개 파일
2. `245de0e` — `6-70: connect GoJoseon discoveries to history cards`
   - `docs/6-70-gojoseon-history-card-integration.md` 신규 파일
   - `game_lab/history/history.js`
   - `game_lab/history/test/history.test.js`
   - `game_lab/rpg/explore-renderer.js`
   - `game_lab/rpg/gojoseon/index.html`
   - `tests/test_6_69_history.py`

두 커밋은 연속이었고 각 커밋의 `git show --name-status` 결과와 부모 관계를 확인한
뒤 revert했다. 생성된 revert 커밋은 `70970c4`(문서 후속 커밋 revert), `0e2d851`
(게임 구현 커밋 revert)이다.

## 콘텐츠공장에 보존된 변경사항

- revert 후 파일 트리는 게임 작업 직전 GitHub commit `b14b563`와 동일하다.
- `README.md`, `content_engine/`, `scripts/`, `tak_brain/`, `tak_scout/`, `operator/`,
  콘텐츠공장 문서와 데이터는 두 게임 커밋의 변경 범위에 포함되지 않았고 변경되지
  않았다.
- Production Archive와 다른 운영 JSON은 읽거나 쓰지 않았다.
- 원래 `/workspaces/tak-auto`에 있던 미커밋 변경 90건은 작업 내내 그대로 두었다.
  revert와 보고서 작업은 깨끗한 별도 worktree에서 진행했으며, 기존 변경을 stage하거나
  commit하지 않았다.
- 기존 `game_lab/` 게임 구현은 revert 대상이 아니며 `b14b563` 시점 그대로 보존했다.

## 테스트 결과

- GoJoseon 기준선 Python 테스트: **10 passed**.
- 역사 마스터 기준선 Python 테스트: **8 passed**.
- 게임 전체 Node 테스트(보드·Choice100·역사·RPG): **70 passed**.
- 전체 Python 테스트: **1,854개 실행, 31 errors, 118 skipped**. 오류는 기존
  Shorts Studio 테스트 경로에서 발생했다. Linux 환경에 코드가 요구하는 Windows
  폰트 `C:/Windows/Fonts/NotoSansKR-VF.ttf`가 없고, 한 테스트에는 외부 HTTP
  `RemoteDisconnected`도 있었다. revert 대상 및 콘텐츠공장 변경에서 새 오류가
  발생한 것은 아니다.
- `git diff --exit-code b14b563 HEAD` 통과. revert 후 tracked 파일 차이가 없다.

## GitHub main 최종 상태

- 두 revert 커밋을 non-force push했다. 최종 `main`에는 되돌림 커밋과 이 보고서가
  기록된 후속 커밋이 포함된다. 최종 HEAD는 보고서 커밋이며, push 후 원격 ref와
  대조한다.
- 작업 전의 콘텐츠공장 커밋을 되돌리거나 다른 작업자의 커밋을 변경하지 않았다.
- revert는 공개된 게임 변경을 삭제하는 대신 반대 변경 커밋으로 상쇄한다.

## 앞으로의 작업 범위 규칙

> 탁자동 콘텐츠공장 작업에서는 PROJECT 2030 게임 코드, 게임 데이터,
> 게임 문서, game_lab 관련 파일을 수정하지 않는다.

콘텐츠공장 작업의 구현·테스트·보고서 변경은 콘텐츠공장 소유 파일에 한정한다.
게임과 콘텐츠공장 간 연계가 필요해 보이더라도 해당 게임 파일은 이 작업에서 수정하지
않고, 먼저 별도의 명시적 작업 범위로 분리한다.