# 6-70 GoJoseon History Card Integration

## 1. 작업 목적

6-69에서 대한민국 역사 마스터(시대·인물·엔티티·관계·어빌리티)를 만들고,
게임 상태를 마스터 ID로 바꾸는 `Library.gojoseonUnlocks()`까지 구현했지만 실제
GoJoseon 플레이 화면은 이 라이브러리를 로드하지 않았다. 탐험에서 얻은 지식은
게임 내부 도감에만 남아 역사 마스터의 출처·역사 상태·게임 설정 구분으로 이어지지
않았다.

가장 최근 완료 보고서가 다음 단계로 지정한 “발견한 역사 카드 표시”를 구현해
플레이 선택 → 발견 → 역사 데이터·출처 확인의 한 운영 단위로 연결한다. 기존 RPG
규칙, 로컬 저장 포맷, TAK MEDIA/MONEY, 실제 서비스 연동은 변경하지 않는다.

## 2. 작업 전 상태

- GitHub 기준점: `origin/main` = `b14b563` (`6-69 Korea history master content system`, 2026-09-28).
- 원래 작업 폴더의 `main`은 `b5afc71`로 GitHub보다 52개 커밋 뒤에 있었고,
  수정·미추적 항목이 90개 있었다. 이 파일들을 보존하기 위해 원격 HEAD의 별도
  detached worktree(`/workspaces/tak-auto-head`)에서만 작업했다.
- GitHub HEAD의 최신 진행 기록은 [6-69 보고서](docs/6-69-korea-history-master-content-system.md).
- GoJoseon/역사 마스터 기준선: Python 6-68 10개, Python 6-69 8개, Node history
  11개 테스트 모두 통과.
- GitHub에 커밋된 운영 데이터: Production Archive 2건, KNOWLEDGE 28건, Threads
  pending 5건, Threads publish log 7건, YouTube log 2건.
- 원래 작업 폴더에는 별도의 미추적 Production Archive 18건(blog 2, Shorts 6,
  Threads 10; approved 16, unreviewed 2)이 존재한다. MONEY 런타임 JSON은 없다.
  두 환경은 서로 다르므로 합치거나 덮어쓰지 않았다. MONEY 최신 실운영 기록은
  [6-62 보고서](docs/6-62-first-real-money-run.md)의 PanelNow 기회 2건,
  실제 수익 0원이며, 원본 운영 파일은 GitHub에 없다.

## 3. 발견한 문제

- `game_lab/rpg/gojoseon/index.html`은 `game_lab/history/history.js`를 로드하지
  않았다.
- `explore-renderer.js`의 “기록(도감)”은 GoJoseon JSON 안의 knowledge·items·skills만
  표시했다. `history/data/links/gojoseon.json`이 정의한 master ID 연결은 테스트에서만
  확인되고 실제 플레이에는 사용되지 않았다.
- `history.js`에는 ID만 반환하는 `gojoseonUnlocks()`가 있지만, 화면이 출처가 포함된
  마스터 엔티티와 어빌리티 레코드를 얻는 API는 없었다.

## 4. 이번 작업에서 결정한 것

- 6-69의 데이터 구조와 6-68의 게임 엔진을 그대로 두고 기존 `gojoseonUnlocks()`를
  감싸는 읽기 전용 카드 조회만 추가한다.
- 브라우저는 동일 출처의 정적 `game_lab/history/data/*.json`만 읽는다. 모든
  파일을 기존 스키마 validator에 통과시킨 뒤 UI에 연결한다.
- 역사 데이터 로드가 실패해도 RPG 플레이는 계속하고, 도감에 제한 사유를 표시한다.
- 역사 기록/신화/전승/게임 설정을 구분하고, 출처가 있는 항목은 원 출처 링크를
  보여준다. 밸런스 수치와 효과는 역사 사실이 아니라 게임 설정으로 표시한다.
- MONEY의 실제 수익이나 TAK MEDIA 게시 상태와 무관한 플레이 가능한 게임 slice의
  개선으로 범위를 제한한다.

## 5. 구현 내용

- `Library.gojoseonCards(state)`가 기존 master ID 해금 계산 결과를 엔티티·어빌리티
  객체 목록으로 반환한다. 입력 상태는 읽기만 하고 결과는 중복 ID가 제거된 안정된
  순서로 유지한다.
- GoJoseon 페이지가 역사 라이브러리와 데이터 파일 10개를 불러온 뒤 전체 스키마를
  검증한다. 실패하면 경고를 기록하고 기존 플레이를 유지한다.
- 지식·아이템·어빌리티 획득 결과에 “역사 도감에 추가” 알림을 붙인다.
- 기록 탭에 발견 카드의 이름·설명·역사 상태·출처 링크와 해금 어빌리티의 역사 연결,
  게임 설정 안내를 표시한다.
- 변경된 렌더러에 `gj1-5` 캐시 버전을 적용했다.

## 6. 변경된 파일

- `game_lab/history/history.js`
- `game_lab/history/test/history.test.js`
- `game_lab/rpg/explore-renderer.js`
- `game_lab/rpg/gojoseon/index.html`
- `tests/test_6_69_history.py`
- `docs/6-70-gojoseon-history-card-integration.md`

## 7. 데이터 변경

- 역사 master JSON, GoJoseon 게임 JSON, KNOWLEDGE, Production Archive, Shorts,
  Threads, YouTube, MONEY 데이터 변경 없음.
- 테스트는 운영 데이터를 쓰지 않는다. 브라우저는 마스터 JSON을 읽기만 한다.
- 원래 workspace의 18건 미추적 Archive와 90개 기존 변경은 별도 worktree를 통해
  보존했다.

## 8. 테스트 결과

- Python GoJoseon 회귀: **10 passed**.
- Python 역사 마스터 및 UI 연결: **9 passed**.
- Node 전체 게임 테스트(보드·Choice100·history·RPG): **71 passed**.
- 전체 Python 회귀: **1,855개 실행, 31 errors, 118 skipped**. 오류는 Shorts Studio
  10개 테스트 경로(하위 테스트 포함 31건)에서 발생했다. 저장소의 Shorts V3 문서가
  Linux에서 고정된 `C:/Windows/Fonts/NotoSansKR-VF.ttf`를 사용할 수 없다고 이미
  기록하고 있고, 로그도 같은 누락을 확인했다. 추가로 `test_draft_loading_and_reopen_keeps_edits`
  에서 외부 HTTP 연결의 `RemoteDisconnected`가 발생했다. GoJoseon/history 범위의
  오류는 없었다. 이 환경 불일치는 수정하지 않았다.
- `node --check` 대상 JavaScript 3개 파일 통과, `git diff --check` 통과.

## 9. 실제 운영 검증

- 로컬 서버 `http://127.0.0.1:8790/rpg/gojoseon/`에서 페이지를 제공했다.
- HTTP 스모크 테스트에서 GoJoseon 페이지와 history 스크립트, 마스터 JSON 경로 10개가
  모두 응답했다.
- 실제 매핑 검증: `k_dolmen`, `k_myth`, `tracking` 상태가 각각 `KN_DOLMEN`,
  `KN_DANGUN_MYTH`, `AB_TRACKING`으로 변환됐다.
- 외부 API, 게시, 결제, 로그인, 운영 데이터 변경은 없었다.
- 자동 브라우저 DOM/스크린샷 검증 도구는 이 환경에 없어, 시각적 상호작용은 별도
  확인하지 않았다. 게임 Director의 재미 판정도 아직 필요하다.

## 10. 남은 문제

- 전체 Python 테스트의 Windows 폰트 의존과 외부 연결 테스트는 Linux 환경에서 계속
  실패할 수 있다. 기존 Shorts 환경 이슈로 별도 작업이 필요하다.
- 6-68에서 요구한 Game Director의 실제 플레이테스트와 재미 판정은 코드 테스트로
  대체할 수 없다.
- GAME 플레이 성과는 로컬 analytics에만 기록되며, 아직 Operator/Performance 및
  수익 데이터와 연결하지 않았다. 광고·결제는 도입하지 않았다.
- 원래 workspace의 로컬 전용 Archive 18건은 GitHub의 커밋된 2건과 다르다. 이
  데이터는 recovery/reconciliation 승인 없이 동기화하지 않는다.

## 11. 다음 작업 후보

1. Game Director가 GoJoseon의 첫 플레이와 도감 상태 전이를 검토하고 재미/혼란 지점을
   기록한다.
2. 이 결과를 바탕으로 6-69의 다음 항목인 발견 역사 카드 UI와 영입 퀘스트를 확장한다.
3. 플레이 성과를 제품으로 확대하기 전에 기존 analytics의 보존·내보내기와
   Performance 연결 정책을 정한다.
4. 독립 작업으로 Shorts 렌더 환경에서 폰트 경로를 OS별 설정으로 만들고 전체 테스트를
   재검증한다.

## 12. Commit 정보

- 구현 및 보고서를 GitHub `main` 최신 HEAD에서 별도 worktree로 작성했다.
- commit: `b56ac2e` (`6-70: connect GoJoseon discoveries to history cards`).
- push 결과는 작업 완료 후 이 절에 기록한다.