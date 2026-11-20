# TAK AUTO 개발 인수인계 — 2026-11-19

## 목적
Android ChatGPT 앱에서 기존 탁자동 개발 대화방을 열면 앱이 즉시 종료되는 문제가 있어, 대화방에 의존하지 않고 GitHub 저장소를 기준으로 개발을 이어가기 위한 체크포인트다.

## 저장소와 Git 상태
- Repository: https://github.com/sopptak/tak-auto
- 작업 브랜치: `feature/trend-content-factory-mvp`
- PR: https://github.com/sopptak/tak-auto/pull/3
- PR 상태: Open / Draft / 미병합
- PR base: `feature/perplexity-research-provider`
- PR head 확인 시점 SHA: `806d3c67f50df45c0047d8bb46a494456a431810`
- PR 변경 규모: 64 files, +9,567 / -206 (최신 GitHub PR API 기준)
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


## 2026-11-19 추가 OAuth 점검 및 수정
- Meta 공식 Business Login 문서를 확인한 결과 Instagram Login의 현재 게시 권한은 `instagram_business_content_publish`이며, 기존 코드/설정 문서의 `instagram_business_content_publishing`은 구식 scope 값이었다. 공식 문서: https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/business-login
- Meta 공식 토큰 교환 예시는 응답을 `data` 배열 안에 반환한다. 기존 코드는 최상위 `access_token`만 읽어 Instagram OAuth 연결이 실패할 수 있었다.
- `content_engine/social_oauth.py`에서 최신 scope로 수정하고 `data` 배열의 단일 토큰 envelope를 처리하도록 보완했다. 여러 계정/토큰이 섞인 모호한 응답은 안전하게 거부한다. 토큰의 `permissions` 필드를 승인 scope로 보존한다.
- `tests/test_social_oauth.py`는 Meta 문서의 `data` 배열 응답, 권한 보존, 복수 envelope 거부를 검증하도록 갱신했다.
- `docs/social_account_oauth_setup.md`도 최신 권한명과 응답 형식에 맞춰 수정했다.
- 코드/테스트/문서 수정 커밋: `5b1183131af3ff08d46cc4c4f9df4794aa3d0abf`, `b5cbaf09b6614bb010b161a58df4d12ef5bbbade`, `4fddc5d7d175d47b87ab43d847c4a49f6a77a4f1`, `806d3c67f50df45c0047d8bb46a494456a431810`.
- `e848e54a21584cea128ba1ed356eb0567d548f7c`에서는 TAK SCOUT tests, TAK AUTO trend content MVP tests, Python 전체 tests가 모두 성공으로 완료된 것을 확인했다. 단, 이 성공은 Instagram OAuth 수정 이전 SHA에 대한 결과다.
- 최신 head `806d3c67f50df45c0047d8bb46a494456a431810`에 대한 새 Actions run은 조회되지 않았다. GitHub App 기반 커밋 이후 워크플로가 자동 트리거되지 않은 상태이므로, 새 OAuth 테스트의 실행/통과는 아직 미검증이다. 이전 SHA 테스트 성공을 최신 SHA 테스트 성공으로 보고하지 않는다.
- PR #3은 계속 Draft / Open / 미병합이며 base 변경, 병합, 배포, 실제 SNS 계정 연결은 하지 않았다.


## 2026-11-19 추가 권한 검증 개선
- 추가 코드 점검에서 OAuth 승인 화면에 요청한 scope를 실제 승인된 권한으로 간주하는 fallback을 발견했다. 이는 권한 동의가 일부 거부되었거나 토큰 응답이 scope를 생략한 경우 게시 준비 상태를 잘못 표시할 수 있다.
- `content_engine/social_oauth.py`에서 요청 scope를 승인 scope로 추정하지 않도록 변경했다. Instagram `permissions` 배열/문자열은 일관된 쉼표 구분 문자열로 정규화한다.
- Threads는 장기 토큰 교환 응답에 scope가 없으면 Meta Graph API `/debug_token`을 서버 측 App Access Token으로 조회해 `is_valid`와 실제 `scopes`를 확인한다. 검증 실패 시 계정 연결 자체는 보존하되 게시 권한은 빈 값/미확인으로 둔다.
- Meta 공식 문서는 `/debug_token`이 토큰 유효성 및 부여된 `scopes`를 반환한다고 명시한다: https://developers.facebook.com/docs/graph-api/reference/debug_token/
- 관련 코드 커밋: `ff4b0a0780cb50484c507d4bab160281b519b815`, `7f64fc33c25d6965bb6b38ae28b4385d53b79201`.
- 관련 회귀 테스트는 Instagram 권한 배열 정규화, Threads debug_token 정상/무효/요청 실패, YouTube 응답 scope 누락 시 승인 권한을 추정하지 않는 경우를 포함한다.
- 테스트 중 발견된 데이터 구분자 불일치와 테스트 mock 라우팅 오류를 수정했다. 최신 테스트 수정 커밋: `3788817805306bc6e8239caa2e2c2a5dde6185bd`, `c8e50fadd4f5b603b32d93c794e5c1330d38ed94`.
- `3788817805306bc6e8239caa2e2c2a5dde6185bd`의 TAK AUTO 집중 테스트는 Threads mock 응답 라우팅 오류로 실패했으며, `c8e50fadd4f5b603b32d93c794e5c1330d38ed94`에서 테스트를 바로잡았다. 이 최신 커밋의 CI 결과는 아직 확인 전이다.
- `3788817805306bc6e8239caa2e2c2a5dde6185bd`의 TAK SCOUT 테스트는 성공했으며, 전체 Python 테스트는 해당 커밋에서 실행 대기/미확정 상태였다.
- PR #3은 Draft / Open / 미병합 유지. 자동 게시 비활성화, 실배포·실계정 연결·실제 게시 미실행.


## 2026-11-19 최신 재개 상태 — 이후 기록이 이전 상태를 대체함

- 최신 코드 변경 커밋: `d62ad49a48cea2a532e33beb2d6ca38dff676f20`.
- PR #3은 Open / Draft / 미병합이며 base는 `feature/perplexity-research-provider`다.
- Instagram Login 현재 게시 scope `instagram_business_content_publish` 및 Meta `data` 토큰 envelope 처리, Threads debug_token 기반 실제 승인 scope 확인, 장기 토큰 교환 후 최초 승인 scope 보존, 게시 어댑터의 최신 scope 검사까지 반영했다.
- OAuth 대시보드용 `public_connections()`는 액세스 토큰 원문을 내보내지 않는다. 최신 변경에서는 토큰 존재 여부만 `access_token_configured` boolean 문자열로 노출해, 화면이 비밀값을 읽지 않고 연결 준비 상태를 판단하도록 했다.
- 게시 플랫폼 선택 UI는 실제 계정 ID, 안전한 토큰 존재 표시, 실제 부여된 게시 scope, 만료 여부, 영상 파일, Instagram 공개 HTTPS URL 조건을 확인한다. 준비 조건이 부족하면 해당 플랫폼 선택을 비활성화한다.
- MP4 업로드는 인증·same-origin·Content-Type·크기·MP4 컨테이너 헤더 검사를 수행한다. 컨테이너 헤더 검사는 실제 디코딩/재생 품질 검증을 대체하지 않는다.
- 최신 코드 SHA `d62ad49...`에서 TAK AUTO trend content MVP tests 성공, TAK SCOUT research tests 성공. Python 전체 테스트는 GitHub Actions에서 실행 중이며, 마지막 확인 시 폰트 설치 단계에 머물러 완료/통과 여부가 미확정이었다. Python 전체 통과로 보고하지 않는다.
- 이전 문서의 SHA 및 CI 상태는 이 섹션의 최신 기록으로 대체한다. 문서 변경 커밋 후 CI가 새로 실행되면 그 결과를 별도로 확인한다.
- Render 실제 서비스 생성·배포, Persistent Disk 연결, 백업/복구 리허설, SNS 실계정 연결, 외부 게시 성공은 여전히 미확인이다. `TAK_AUTO_PUBLISHING_ENABLED=false` 유지.
- 다음 작업: 최신 head의 Python 전체 테스트 완료 확인 → 문서 변경 커밋의 CI 재확인 → 실제 운영 배포 전 체크리스트 최종 검토. PR 병합/배포/실계정 연결/게시/유료 리소스 생성은 별도 사용자 승인 없이는 하지 않는다.


## 2026-11-19 다음 개발 단계 — 검증 가능한 백업·복구 도구

- PR #3 최신 확인 head `4538d1a74bb8f593c90640fffe0cf884389f86d0`은 Draft/Open이며, TAK AUTO MVP, TAK SCOUT, Python 전체 CI가 모두 성공했다.
- Windows 동시 JSON 교체의 간헐 오류는 `scripts/run_trend_content_mvp.py`에서 교체 단계를 직렬화하고 일시 `PermissionError`에 제한 재시도하도록 보완했다. 권한 비트 테스트는 POSIX에서만 평가한다.
- `content_engine/trend_data_backup.py`와 `scripts/backup_trend_factory_data.py`에 create/verify/restore 도구를 추가했다. checksum manifest 검증, 경로 탈출·심볼릭 링크 거부, 기존 파일/복구 경로 덮어쓰기 방지, 임시 경로에서 검증 후 복구 이동을 제공한다.
- `tests/test_trend_data_backup.py`의 생성/검증/복구, 변조, 경로 탈출, 덮어쓰기 차단 테스트를 추가했고, `trend-content-mvp-tests.yml`에 경로 감지와 새 테스트 실행을 연결했다.
- 당시 백업 아카이브는 암호화되지 않았으며 OAuth 암호문, 게시/미디어 정보를 포함할 수 있었다. 이 보안 상태는 아래 “운영 백업 아카이브 암호화” 섹션의 변경으로 대체됐다. 실제 Render 디스크 복사·보관·복구 리허설은 수행하지 않았다.
- runbook은 데이터 작성 프로세스를 정지한 복제본에서의 명령과 보안 한계를 안내한다. Render 실서비스 생성 후 운영자 설정과 승인이 필요한 부분은 미완료다.


## 2026-11-19 Instagram Reels 성과 수집

- 작업 시작 시점 PR #3 head `6fb8efa716362e681926af31c27f37fc1e78d7b3`은 Draft/Open이며, TAK AUTO MVP, TAK SCOUT, Python 전체 CI가 성공했다.
- Instagram Reels 미디어의 `like_count`/`comments_count`를 암호화 OAuth vault의 실제 `instagram_business_basic` 승인 scope로 수집하는 경로를 추가했다. 플랫폼/소스 모델, CLI와 대기열 연결, 명시적 `--confirm-live` 가드, dry-run, 테스트와 운영 문서를 갱신했다.
- 조회수는 추정하지 않고 미제공 필드는 unavailable로 기록한다. 미디어 ID가 API 응답과 정확히 일치해야 하며, 토큰은 Authorization header로만 전달한다.
- 실계정 API 요청은 수행하지 않았다. 모의 transport와 dry-run 테스트만 실행한다. 이 플랫폼을 실제 계정에서 검증하려면 별도의 승인 이후 진행해야 한다.
- 로컬 회귀 테스트 118개가 통과했다. `tests.test_instagram_performance`, `tests.test_collect_performance_live_gate`, `tests.test_collect_performance_cli`, `tests.test_performance_models`, `tests.test_performance_dashboard`, `tests.test_trend_publishers`, `tests.test_social_oauth`, `tests.test_social_oauth_routes`를 실행했다. `compileall`과 `git diff --check`도 통과했다.
- PR head `779ca54f1cbd7e6625f27e18d2898f3db24aedcb`에서는 TAK AUTO MVP와 TAK SCOUT CI가 성공했지만 Python 전체 테스트 2,183개 중 1개가 실패했다. `tests/test_6_63_game_factory_doc.py`가 새 플랫폼 모델을 반영하지 않은 고정 문자열을 검사하는 회귀였다. 이를 현재 platform tuple로 갱신했고, CI를 재실행할 후속 커밋에 포함한다.
- PR은 계속 Draft/Open으로 유지하며, Render 배포/실제 SNS 연결/게시/병합은 수행하지 않는다.
- 후속 커밋 `0b467c252bee5b91622b48a52779a36886c66463`에서 Instagram metrics의 대시보드 렌더링 테스트와 구식 platform 튜플 검사 갱신을 포함했다. 로컬 집중 테스트 65개, `compileall`, `git diff --check`가 통과했다.
- 이 최신 SHA에서는 TAK AUTO trend content MVP run 710, TAK SCOUT research run 624, Python 전체 테스트 run 600(2,183개 테스트)이 모두 성공했다. 앞선 SHA의 단일 실패는 후속 수정으로 해결했다.
- 운영 상태: `instagram_business_basic` OAuth 승인을 이용해 likes/comments를 읽도록 구현했으나, 실계정 연결이나 실제 API 요청은 하지 않았다. Render 배포·백업/복구 리허설·외부 게시는 미확인이다.


## 제품 가이드 지원 범위 동기화 — 2026-11-19

- `docs/trend_content_factory_mvp.md`의 오래된 “성과 API는 Threads/YouTube만 지원” 문구를 바로잡았다. 현재 문서는 Instagram Reels의 likes/comments만 수집하고 views는 수집하지 않는 범위, `instagram_business_basic` scope, dry-run/live 조건을 반영한다.
- 대시보드 설명도 Instagram 성과 카드가 포함되도록 갱신했다. Facebook/TikTok 성과 API는 미지원으로 명시했다.
- 문서 정합성 변경의 로컬 관련 회귀 테스트 112개 통과, `git diff --check` 통과. 변경 후 PR CI는 새 head에서 재확인한다.


## 운영 백업 아카이브 암호화

- 미완료 운영 위험 점검에서 백업 ZIP이 OAuth 암호문·게시 이력·콘텐츠·MP4를 포함할 수 있지만 파일 자체는 평문임을 확인했다.
- `content_engine/trend_data_backup.py`에 PBKDF2-HMAC-SHA256 키 유도와 스트리밍 AES-256-GCM 암호화/인증을 추가했다. ZIP 출력을 암호화 스트림에 직접 연결해 생성 중 평문 ZIP 임시본을 만들지 않는다. 인증된 뒤에만 복호화 ZIP을 읽으며, 암호문구는 저장하지 않는다.
- CLI는 데이터 `--source` 경로와 `--encrypt` 또는 명시적 `--allow-unencrypted`를 요구하고, 암호문구를 터미널에서 숨겨 입력한다. 인증 실패/변조 시 복구 대상이 생성되지 않는다. 임시 평문 파일은 존재할 수 있고 보안 삭제를 보장하지 않는 점을 runbook에 기록했다.
- 관련 집중 회귀는 이 섹션 아래 최신 기록을 따른다. 암호화 백업 왕복, 2MB 초과 streaming, 원본 변경 감지, 복구 공간 사전 확인, 복구 대상 보호, 잘못된 암호문구/태그 변조, private file permissions, CLI 취소 동작을 검증했다.

## 운영 백업 경합 회귀 검증 및 이전 PR CI

- `tests/test_trend_data_backup.py`는 평문과 암호화 백업 모두에서 manifest 생성 뒤 원본 파일이 바뀌는 경합을 확인한다. checksum 불일치로 생성을 거부하고 최종 아카이브나 임시 파일을 남기지 않는지 검증한다.
- 코드/테스트 head `97d71b37abc9364b525ff37fbbfd70a882c68a53`에서 TAK AUTO trend content MVP [run 720](https://github.com/sopptak/tak-auto/actions/runs/44470487290), TAK SCOUT [run 634](https://github.com/sopptak/tak-auto/actions/runs/44470487353), Python 전체 [run 610](https://github.com/sopptak/tak-auto/actions/runs/44470487443)가 모두 성공했다.
- PR #3은 계속 Draft/Open이며 미병합이다. Render 배포, 유료 리소스 생성, 실계정 OAuth/API 호출, 외부 게시는 수행하지 않았다.

## 복구 대상 경합 보호 — 2026-11-19

- 사전 `exists()` 검사 후 `os.rename(stage, destination)`까지의 경합에서 Linux가 새로 생긴 빈 디렉터리를 교체할 수 있음을 확인했다. 복구 대상 보호 약속과 달라 실패 시나리오 회귀를 추가했다.
- Linux에서는 `renameat2(RENAME_NOREPLACE)`로 대상 없음 조건을 원자적으로 강제하고, Windows에서는 덮어쓰기 없는 `os.rename`을 사용한다. 다른 운영체제나 지원되지 않는 Linux 런타임에서는 안전한 원자 연산 없이 복구하지 않고 fail closed한다.
- Windows 백업 집중 테스트는 26개 중 24개 통과, symlink 생성 제약 테스트 2개 skip이다. 새 파일 추가 경합, 빈 대상 폴더 생성 경합, 실제 ZIP 파일이 manifest 크기를 넘을 때 첫 1MiB 뒤 읽기 중단을 확인했다. `compileall` 및 `git diff --check`가 통과했다.
- 직전 Windows 전체 회귀는 2,200개 실행 중 2,155개 통과, 44개 환경상 skip, loopback HTTP 테스트 1개 오류로 끝났다. 콘텐츠 형식 사전 거절 테스트가 불필요한 업로드 본문을 보내지 않도록 조정한 뒤 해당 HTTP 테스트 파일을 연속 3회 실행해 매회 5개 통과했다. 이후 최신 코드/테스트 head `91b3a959e9bee4537c3ece53894b41a532cde89b`에서 전체 회귀를 다시 실행해 2,202개 실행, 2,158개 통과, 44개 환경상 skip, 실패 0을 확인했다.
- 백업 검증 뒤 원본 경로 목록을 다시 확인해 생성 도중 추가·삭제된 파일과 링크/특수 파일 변경을 거부한다. 도구는 마지막 목록 확인 직후의 변경을 막을 스냅샷/잠금을 제공하지 않으므로 백업 중 데이터 쓰기 중지는 여전히 필요하다. 평문·암호화 모드 각각의 새 파일 경합 테스트가 실패 시 최종 아카이브와 임시 파일을 남기지 않는지 확인한다.
- 코드/테스트 head `91b3a959e9bee4537c3ece53894b41a532cde89b`의 TAK SCOUT #644, TAK AUTO trend content MVP #730, Python 전체 #620 CI가 모두 성공했다. Windows 전체 회귀는 2,202개 실행, 2,158개 통과, 44개 환경상 skip, 실패 0이다. 관련 8개 집중 테스트 모듈은 138개 실행, 136개 통과, 2개 symlink 환경 skip이다. 이후 추가한 Render 설정 starter 플랜 단언은 별도 정적 설정 모듈 10개 테스트 통과로 확인했다.
- 검증 코드/테스트 head 뒤 runbook 표현을 바로잡은 문서 전용 커밋이 추가됐다. PR #3은 확인 시 Draft/Open/미병합이며 base는 `feature/perplexity-research-provider`다. 재개 시 PR head와 해당 SHA의 CI를 새로 조회한다. Render 배포, 유료 리소스 생성, 실계정 API 연결, 외부 게시를 하지 않았다.
- 배포 준비 추가 점검에서 기존 정적 테스트가 트렌드 팩토리 서비스의 실제 데이터 경로와 Persistent Disk 경로 일치를 확인하지 않는 점을 보완했다. `tests/test_web_deployment_security.py`는 그 경로와 `/health`, 1GB 디스크, starter 플랜, 외부 비밀 변수, 게시 비활성화를 검증하며 10개 테스트가 통과했다. 실제 Render 서비스 검증은 아니다.

## 2026-11-19 백업 검증기 메모리 상한

- `content_engine/trend_data_backup.py` 검토 중 ZIP manifest를 크기 제한 없이 한 번에 메모리로 읽는 점을 확인했다. 압축 해제 기준 16MiB 상한을 추가하고 metadata 검사 뒤 본문을 읽기 전에 초과를 거부한다.
- `tests/test_trend_data_backup.py`에 압축된 과대 manifest 테스트를 추가했다. manifest 본문 read 호출이 없음을 확인한다. 백업 집중 테스트 27개 중 25개 통과, Windows symlink 제약 2개 skip이다.
- Windows 전체 회귀는 2,203개 실행, 2,159개 통과, 44개 환경상 skip, 실패 0이다.
- 코드/테스트 head `4c9a8b85e1c8d444f0378a422527f8c9e4f996f1`의 TAK AUTO trend content MVP [#732](https://github.com/sopptak/tak-auto/actions/runs/44489189308), TAK SCOUT [#646](https://github.com/sopptak/tak-auto/actions/runs/44489189407), Python 전체 [#622](https://github.com/sopptak/tak-auto/actions/runs/44489189141)가 모두 성공했다.
- PR #3은 Draft/Open/미병합 상태이고 base는 `feature/perplexity-research-provider`다. Render 실배포, 유료 리소스, 실계정 API, 외부 게시를 하지 않았다.

## 백업 복구 추출 상한 — 2026-11-19

- 복구 단계에서 manifest 크기대로 제한 읽기를 적용해, 검증 이후 평문 ZIP이 교체되더라도 초과 바이트를 staging 파일에 기록하지 않도록 했다. 경합 회귀는 검증 함수를 대체한 뒤 manifest보다 큰 ZIP 항목을 넣어 조기 중단과 staging 정리를 확인한다.
- 집중 백업 테스트 28개 중 26개 통과, 2개 Windows symlink 제약 skip. 최신 코드 전체 Windows 회귀는 2,204개 실행, 2,160개 통과, 44개 환경상 skip, 실패 0이다.
- 최신 코드 head `859f99e22e768272a463302ae39781d746a1529d`의 TAK AUTO trend content MVP #734와 TAK SCOUT #648은 성공했다. Python 전체 #624는 Ubuntu 한글 글꼴 설치 단계에서 실행 중이며 테스트 단계에 아직 도달하지 않았다. 직전 문서 head `f7379062ce9a82e5b8f8558ae08fe5fb9fedc176`에서는 세 CI가 모두 성공했다.
- PR #3은 Draft/Open/미병합이고 head는 위 SHA다. 작업 트리는 깨끗하다. Render 배포, 유료 리소스, 실계정 API 연결, 외부 게시를 하지 않았다.

## 최신 문서 head 확인

- 최신 PR head `497bc1e502bc49f9b1975dda265df52ca7f09c42`는 앞선 코드/테스트 head `859f99e22e768272a463302ae39781d746a1529d`를 기록한 handoff 문서 갱신이다.
- 최신 문서 head의 TAK AUTO MVP #735, TAK SCOUT #649, Python 전체 #625가 모두 성공했다. 같은 코드 기반의 Windows 전체 회귀는 2,204개 실행, 2,160개 통과, 44개 환경상 skip, 실패 0이다.
- PR #3은 Draft/Open/미병합이며 base `feature/perplexity-research-provider`다. Render/외부 서비스 운영은 시작하지 않았다.

## Windows 전체 회귀 결과 — 2026-11-19

- 앞선 Windows `python -m unittest discover -s tests -q` 실행은 2,193개 통과, 43개 환경상 skip이다. 최신 전체 회귀 결과는 위 “복구 대상 경합 보호” 항목을 참고한다.
- 앞선 전체 실행 4개 실패는 테스트가 `0547065b4f9b65ada8af6a3c33cc636d97b43345`의 아카이브 스냅샷을 요구했으나 local clone에 해당 과거 객체가 없어 발생했다. 커밋을 저장소에서 가져온 뒤 실패했던 4개 테스트를 다시 실행해 모두 통과시켰다. 이 과정에서 테스트/프로덕션 데이터를 수정하지 않았다.
- 한 번의 재실행에서는 Windows loopback HTTP 테스트에서 `WinError 10053`이 났고, 단독 재실행은 통과했다. 후속 전체 실행은 통과했다.
- 두 테스트 자원 누수를 정리했다. `tests/test_6_56_shorts_editor.py`는 PIL 프레임을 context manager로 닫고, `tests/test_run_scout_cli.py`는 HTTP 서버 종료 후 listening socket을 닫는다. 후속 전체 로그에는 `ResourceWarning`이 없었다. `python -W error::ResourceWarning -m unittest tests.test_run_scout_cli -v`도 6개 통과했다.

## 복구 공간 사전 확인 — 2026-11-19

- `restore_backup`은 archive manifest 검증 후 목적 파일시스템 여유 공간을 총 복구 바이트와 비교한다. 여유 공간이 부족하거나 용량 조회에 실패하면 staging 디렉터리 없이 중단한다.
- 공간 부족/조회 실패 경로 회귀를 추가했다. 백업 및 관련 성과 경로 134개 집중 테스트를 실행했다.

## 2026-11-20 성과 수집 무결성 및 동시성 보완

- 성과 JSON 저장소의 append read-modify-write 구간에 프로세스 내부 잠금을 추가했다. 대시보드 요청 스레드의 동시 저장이 서로의 스냅샷을 덮어쓰지 않도록 하는 회귀 테스트를 포함한다. 이 잠금은 프로세스 간 동시성을 제공하지 않으므로 운영은 기존처럼 단일 인스턴스를 유지한다.
- Threads/YouTube 성과 정규화는 음수·불리언 카운트를 버린다. YouTube는 API 응답의 영상 ID가 요청한 ID와 일치하지 않으면 저장을 거부한다.
- 성과 레코드 역직렬화는 불리언·분수형 지표와 객체가 아닌 `metrics` 컨테이너를 거부한다. 정수 문자열은 호환 지원하며, `metrics` 누락/null은 빈 dict로 처리한다.
- 집중 PR CI에 `test_performance_store`, `test_performance_threads`, `test_performance_youtube`를 추가해 해당 모듈 변경 때 빠른 회귀 검증을 수행한다.
- 확인 head `597e923769c5beb6b589d07675daf4a900986a57`에서 Python 전체 회귀 2,252개 통과, 118개 skip. TAK AUTO 집중 회귀 407개 테스트 및 TAK SCOUT 테스트도 모두 통과했다. [Python 전체](https://github.com/sopptak/tak-auto/actions/runs/44746138231), [TAK AUTO 집중](https://github.com/sopptak/tak-auto/actions/runs/44746138162), [TAK SCOUT](https://github.com/sopptak/tak-auto/actions/runs/44746138287).
- PR #3은 Draft/Open 상태이며 base는 `feature/perplexity-research-provider`다. 이 작업은 코드와 GitHub CI 검증만 수행했다. Render 배포, 실계정 OAuth/API 호출, 실제 SNS 게시 및 PR 병합은 수행하지 않았다.

## HTTP 요청 본문 입력 검증 — 2026-11-20

- POST `Content-Length`는 ASCII 숫자만 허용하고, 숫자 변환 전에 크기를 제한한다. 폼 본문은 선언한 바이트 수와 실제 읽은 길이가 일치하고 UTF-8로 해석될 때만 처리한다. MP4 업로드와 일반 폼 요청의 상한은 각각 100MB와 16KB로 유지한다.
- `tests.test_trend_content_queue_routes` 52개가 Python 3.12에서 통과했고 `git diff --check`도 통과했다.
- 로컬 전체 회귀는 2,254개 테스트 실행 후 실패 8개, 오류 173개, skip 40개였다. 로그에는 Windows 관리 환경의 loopback `WinError 10013`, 임시 파일 원자 교체 `WinError 5`, 실제 아카이브 fixture 개수 차이가 포함됐다. 이 결과는 CI와 분리해 기록하며, 이 과정에서 데이터 아카이브나 보안 검사를 변경하지 않았다.
- 이 변경은 요청 파싱에만 적용한다. 게시 승인 게이트와 `TAK_AUTO_PUBLISHING_ENABLED=false`는 유지한다. Render 배포, OAuth 연결, 실계정 API, 외부 게시 및 PR 병합은 수행하지 않았다.
- 코드 head `f0dbea1d16d6e5681cad32721149462efa0ed256`에서 GitHub CI 전체가 통과했다. TAK AUTO 집중 409개 [#44750141522](https://github.com/sopptak/tak-auto/actions/runs/44750141522), TAK SCOUT [#44750142368](https://github.com/sopptak/tak-auto/actions/runs/44750142368), Python 전체 2,254개 통과/118개 skip [#44750141563](https://github.com/sopptak/tak-auto/actions/runs/44750141563).

## HTTP 본문 프레이밍 및 최신 CI — 2026-11-20

- HTTP 요청 경계 검증을 추가로 강화했다. `Content-Length`가 중복되거나 `Transfer-Encoding`이 포함되면 POST 본문을 읽거나 상태를 바꾸기 전에 400으로 거부한다. 기존 ASCII 숫자, 본문 길이 일치, UTF-8, 폼 16KB 및 MP4 100MB 상한 검사는 유지한다.
- Python 3.12에서 라우트 테스트 53개와 배포 보안 테스트 10개가 통과했고 `git diff --check`도 통과했다.
- 커밋 `b7ad26ff72b4ab6eb47f4ba752e8733e6f6c494f`에서 TAK AUTO 410개 [#44753876002](https://github.com/sopptak/tak-auto/actions/runs/44753876002), TAK SCOUT 345개 [#44753876022](https://github.com/sopptak/tak-auto/actions/runs/44753876022), Python 전체 2,255개 실행/118개 skip/실패 0 [#44753875987](https://github.com/sopptak/tak-auto/actions/runs/44753875987)가 모두 성공했다.
- 이전 전체 Python 실행 [#44396321404](https://github.com/sopptak/tak-auto/actions/runs/44396321404)도 성공했으며 2,155개 실행, 118개 skip, 실패 0이다. 최신 실행은 테스트 총 100개가 더 포함된 head 기준이다.
- PR #3은 Draft/Open이며 base `feature/perplexity-research-provider`다. 현재 로컬에는 운영 아카이브 회귀가 참조하는 과거 커밋 `0547065b4f9b65ada8af6a3c33cc636d97b43345`가 없어 해당 fixture 의존 테스트를 로컬에서 재현할 수 없다. 이 제한과 앞선 로컬 전체 실행의 환경 오류는 GitHub 전체 회귀 성공 결과와 구분한다.
- Render 서비스 설정은 읽지 않았다. 저장소 `render.yaml`은 게시 비활성화(`TAK_AUTO_PUBLISHING_ENABLED=false`)를 유지하지만, 연결된 서비스의 Auto-Deploy가 Off인지 운영자 확인이 남아 있다. 이 세션에서는 Render 배포, SNS OAuth 연결, 라이브 API, 외부 게시, PR 병합을 수행하지 않았다.

## 불확실한 게시 작업 상태 보호 — 2026-11-21

- 대기열 `reject()`는 `processing` 또는 `needs_review` 작업을 거절 처리하지 않는다. 외부 플랫폼에 게시됐을 가능성이 있는 작업을 일반 거절로 숨기지 못하게 하고, 운영자가 게시 여부를 확인한 뒤 완료 기록 또는 미게시 확인 재시도를 선택하게 한다. 잘못된 상태 형식도 거절 처리하지 않는다.
- Python 3.12 로컬 검증: 게시 대기열 22개, 발행 어댑터 34개, 트렌드 라우트 53개 통과. `git diff --check` 통과.
- 코드 head `e3eafc1a000676a378d1a810f61e7139c44a80e1`에서 TAK AUTO 413개 [#44826463589](https://github.com/sopptak/tak-auto/actions/runs/44826463589), TAK SCOUT 345개 [#44826463516](https://github.com/sopptak/tak-auto/actions/runs/44826463516), Python 전체 2,258개 실행/118개 skip/실패 0 [#44826463528](https://github.com/sopptak/tak-auto/actions/runs/44826463528)가 모두 성공했다.
- PR #3은 Draft/Open이며 미병합이다. `TAK_AUTO_PUBLISHING_ENABLED=false` 유지; Render 배포, 실계정 OAuth, 라이브 API, 외부 게시 및 PR 병합은 수행하지 않았다.

## 수동 검토 이력 대시보드 — 2026-11-21

- `confirm_published` 및 `retry_after_review` 결정은 대기열 항목의 `review_history`에 누적된다. 기존 소비자 호환을 위해 최신 항목을 `last_review`에도 유지한다. 손상된 검토 이력은 조정 요청을 거부하고 게시 상태를 변경하지 않는다.
- 대기열 대시보드에서 항목별 확인 이력을 펼쳐 볼 수 있다. 최근 20건까지 결정, 운영자, 시각, 외부 게시 ID 또는 재시도 예약 시각을 표시하며 사용자 입력은 HTML 이스케이프한다.
- Python 3.12 로컬 테스트: 대기열 25개, 발행 어댑터 34개, 트렌드 라우트 53개 통과. `git diff --check` 통과.
- 코드 head `10ead2eef3fa8dbe31d5d54edd53b3810d7dcbe9`에서 TAK AUTO 416개 [#44828115858](https://github.com/sopptak/tak-auto/actions/runs/44828115858), TAK SCOUT 345개 [#44828115706](https://github.com/sopptak/tak-auto/actions/runs/44828115706), 전체 Python 2,261개 실행/118개 skip/실패 0 [#44828115909](https://github.com/sopptak/tak-auto/actions/runs/44828115909)가 모두 성공했다.
- PR #3은 Draft/Open이며 병합하지 않았다. 게시 전역 비활성화 설정을 유지했고 실제 Render 배포, SNS 실계정 연결, 라이브 API 및 외부 게시는 하지 않았다.
