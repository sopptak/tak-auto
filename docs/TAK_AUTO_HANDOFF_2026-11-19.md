# TAK AUTO 개발 인수인계 — 2026-11-19

## 목적
Android ChatGPT 앱에서 기존 탁자동 개발 대화방을 열면 앱이 즉시 종료되는 문제가 있어, 대화방에 의존하지 않고 GitHub 저장소를 기준으로 개발을 이어가기 위한 체크포인트다.

## 저장소와 Git 상태
- Repository: https://github.com/sopptak/tak-auto
- 작업 브랜치: `feature/trend-content-factory-mvp`
- PR: https://github.com/sopptak/tak-auto/pull/3
- PR 상태: Open / Draft / 미병합
- PR base: `feature/perplexity-research-provider`
- PR head 확인 시점 SHA: `e5c1ffb7d0ca346e596c77c1aca6b3df65e79a41`
- PR 변경 규모: 58 files, +9,297 / -193, 399 commits
- GitHub 연결 권한: 저장소 push 권한 확인됨
- 주의: 작업 전 반드시 PR head SHA를 다시 조회하고, 이후 커밋이 생겼는지 확인한다. PR을 임의 병합하거나 base를 변경하지 않는다.

## 제품 범위
- TAK AUTO 1: 범용 최신 트렌드 발굴 및 콘텐츠 생산 공장.
- 특정 분야(법원경매 등)에 고정하지 않는다.
- 트렌드 조사 → 근거/키워드 확인 → 콘텐츠 패키지 생성 → 품질 검토 → 운영자 승인 → 선택적 게시.
- 경매 전용 기능은 후속 TAK AUTO 2로 분리한다.
- 네이버 블로그는 자동 게시가 아니라 수동 게시.
- 쇼츠 대본 생성과 MP4 렌더링은 별개이며, 완성 MP4를 등록해야 영상 플랫폼 게시 가능.

## 구현 범위(저장소 문서 및 README 기준)
- Perplexity Agent API 기반 트렌드 조사와 콘텐츠 생성.
- 블로그 원고, 30~90초 쇼츠 장면 구성(5~8장면), Threads 2개, Facebook 전용 문안 등 생성.
- 콘텐츠 구조 품질 체크, 검색 의도/답변 단서 점검, 쇼츠 후킹 패턴 점검.
- 출처 URL 무결성 및 콘텐츠 인용 URL 연결 검사.
- 문장별 사실 확인 후보 추출(단, 의미적 사실 검증은 아님).
- 원문 보존형 편집 수정 제안 및 일부 텍스트 필드 AI 수정본 생성·비교·선택 적용.
- OAuth 연결(YouTube, TikTok, Instagram, Facebook 페이지, Threads, 네이버 프로필), 암호화 토큰 저장.
- 승인형 게시 어댑터(Threads, Facebook 페이지 텍스트, YouTube Shorts MP4, Instagram Reels MP4, TikTok Direct Post MP4).
- 게시 이력, 중복 방지, 제한된 재시도, 불확실한 게시 결과의 운영자 확인.
- Threads/YouTube 성과 수집의 명시적 dry-run / live-confirm 경로.

## 안전 설정 — 변경 금지
- `TAK_AUTO_PUBLISHING_ENABLED=false` 또는 `TAK_AUTO_PUBLISHING_ENABLED=false`에 해당하는 기본 비활성 설정을 유지한다.
- PR 미병합 상태 유지. 사용자의 별도 승인 없이 PR 병합, Render 재배포, 유료 서비스/리소스 생성, SNS 실제 게시, OAuth 연결, 실계정 API 호출을 하지 않는다.
- 게시/성과 수집은 반드시 dry-run과 명시적 운영자 승인 절차를 거친다.
- API 키, OAuth secret, 토큰, 계정 비밀번호를 채팅이나 Git에 기록하지 않는다.

## 2026-11-19 확인 사항
- PR #3은 여전히 Draft / Open / 미병합으로 조회됨.
- README의 2026-11-19 추가 점검에는 Facebook 오류 응답 방어, YouTube/Threads OAuth 프로필 확인, YouTube refresh token 보존, GitHub Actions concurrency, 영구 저장소 readiness, 단일 인스턴스 JSON 큐 제약, YouTube 성과 수집 공통 OAuth 해석기 등이 기록되어 있다.
- README에는 Facebook 전용 테스트 10개, TAK AUTO 집중 회귀 테스트, TAK SCOUT 테스트 및 최신 집중 테스트 통과가 기재되어 있다.
- 전체 Python unittest는 별도 workflow에서 실행 대기 중이라고 README에 기재되어 있다. 이 문구는 실제 현재 상태로 간주하지 말고, 개발 재개 시 GitHub Actions에서 최신 head 기준으로 다시 확인한다.
- PR head SHA의 PR-triggered workflow runs 조회에서는 실행 항목이 반환되지 않았고, combined status에서도 확인 가능한 상태 항목이 반환되지 않았다. 따라서 CI 전체 성공을 단정하지 않는다.
- Render Blueprint에는 `tak-auto-trend-factory` 별도 서비스와 1GB Persistent Disk가 선언되어 있다. 실제 Render 서비스 생성/배포/환경변수/디스크 연결은 계정에서 확인되지 않았다.
- `/health`는 persistent storage 준비 여부를 반영하도록 강화되었다고 문서화되어 있다. 실제 운영 URL에서 검증한 것으로 간주하지 않는다.

## 다음 작업 우선순위
1. PR 최신 head SHA와 변경사항을 다시 확인한다.
2. 해당 SHA의 GitHub Actions 전체 workflow/run/check 결과를 조회하고, 미실행/대기/실패/통과를 분리해 기록한다.
3. 실패 테스트가 있으면 로그를 확보하고 원인별로 수정한다. 테스트를 실행하지 않은 상태에서 통과했다고 보고하지 않는다.
4. 품질검증의 한계를 유지하면서 출처 원문 대조, 검색 의도 적합성, 후킹 품질을 운영자가 검증할 수 있는 UI/테스트를 점검한다.
5. AI 수정본 생성·비교·선택 적용의 stale revision 방지, 원문 보존, 감사 이력, unresolved claims 확인 절차를 회귀 테스트한다.
6. Render 배포 전 설정·영속 디스크·단일 인스턴스·백업/복구 절차를 점검한다. 실배포는 사용자 승인 후에만 한다.
7. 실제 SNS 연결과 게시/성과 수집은 마지막 단계에서 사용자 승인 하에 테스트한다.

## 새 대화에서 이어갈 시작 지시
“탁자동 개발을 이어간다. 먼저 GitHub 저장소 sopptak/tak-auto의 PR #3과 feature/trend-content-factory-mvp 최신 head SHA를 다시 조회하라. 이 인수인계 문서와 현재 코드/CI 결과를 대조한 뒤, 안전 설정과 미병합 상태를 유지하면서 다음 미완료 개발 작업을 수행하라. 각 단계마다 실제 수정 파일, 커밋 SHA, 테스트 명령과 결과, MVP 기능 완성도 및 운영 준비도를 보고하라. 사용자에게 물어보지 말고 진행하되, 병합·배포·외부 게시·유료 리소스 생성·실계정 API 호출은 별도 승인 없이 실행하지 말라.”


## 2026-11-19 추가 진행 기록
- 운영 개시 및 장애 대응 체크리스트를 `docs/TAK_AUTO_OPERATIONS_RUNBOOK.md`로 추가했다.
- 운영 체크리스트 커밋: `e3c25eaf4ea9bea2000d75dc1740b94e9c6c108c`
- PR #3은 Draft / Open / 미병합 상태를 유지한다.
- `f9cdc21468f0d18f98dd53592ad18ca0cc21c7f2` 기준 TAK SCOUT research tests 성공, TAK AUTO trend content MVP tests 성공.
- 같은 SHA의 Python 전체 테스트 workflow는 실행 중 취소됨(cancelled). 전체 회귀 테스트 통과로 보고하지 않는다.
- 후속 문서 커밋 `e3c25eaf4ea9bea2000d75dc1740b94e9c6c108c` 기준 GitHub Actions workflow run은 아직 조회되지 않았다. 따라서 최신 head SHA에 대한 CI 결과는 미확정이다.
- 운영 체크리스트는 코드 기반 확인과 Render/SNS 운영자가 직접 수행해야 할 확인을 구분하며, Render 배포·SNS 연결·실제 게시 완료를 주장하지 않는다.

## 최신 재개 지시 추가
최신 브랜치 head는 인수인계 파일 자체가 갱신될 수 있으므로, 재개 시 PR #3의 head SHA를 다시 확인한다. 최신 head에서 GitHub Actions가 자동 시작되지 않으면 저장소 Actions 화면에서 최신 브랜치의 워크플로를 수동 실행하거나, 적절한 권한으로 재실행할 수 있는 절차를 확인한다. 이전 SHA에서 성공한 테스트를 최신 SHA의 통과 결과로 대체하지 않는다.
