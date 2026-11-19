# TAK AUTO 운영 개시 및 장애 대응 체크리스트

작성일: 2026-11-19
대상: `tak-auto-trend-factory` (범용 트렌드 콘텐츠 MVP)

이 문서는 코드 테스트 통과와 실제 서비스 운영 준비를 구분한다. 체크박스는 운영자가 Render·SNS 계정에서 직접 확인한 경우에만 완료로 표시한다. 저장소 코드나 CI 결과만으로 배포·계정 연결·영속 저장·외부 게시가 완료됐다고 간주하지 않는다.

## 1. 배포 전 승인 게이트

- [ ] PR #3의 최신 head SHA와 변경 파일을 확인한다.
- [x] 2026-11-19 확인: 코드/테스트 head `97d71b37abc9364b525ff37fbbfd70a882c68a53`에서 TAK SCOUT [#634](https://github.com/sopptak/tak-auto/actions/runs/44470487353), TAK AUTO trend content MVP [#720](https://github.com/sopptak/tak-auto/actions/runs/44470487290), Python 전체 테스트 [#610](https://github.com/sopptak/tak-auto/actions/runs/44470487443)가 모두 성공했다. 이후 커밋이 생기면 반드시 새 head에서 재검증한다.
- [ ] PR의 base 브랜치와 병합 대상이 의도한 구조인지 검토한다. 현재 PR은 `feature/perplexity-research-provider`를 base로 하는 Draft이므로, main 배포용 PR로 오인하지 않는다.
- [ ] Render 계정 소유자가 새 서비스 생성 및 Starter 플랜·Persistent Disk 비용을 승인한다.
- [ ] 게시 기능은 계속 `TAK_AUTO_PUBLISHING_ENABLED=false`로 둔다.
- [ ] 실제 SNS 게시·성과 API 조회는 별도 운영 승인 전 실행하지 않는다.

## 2. Render 서비스 설정 확인

대상 서비스: `tak-auto-trend-factory`

예상 공개 주소(실제 발급·접속 상태는 Render에서 확인):
`https://tak-auto-trend-factory.onrender.com`

필수 환경변수:
- `TAK_WEB_USERNAME`
- `TAK_WEB_PASSWORD`
- `TAK_SCOUT_PERPLEXITY_API_KEY`
- `TAK_AUTO_DATA_DIR=/var/data/trend-factory`
- `TAK_AUTO_PUBLISHING_ENABLED=false`
- `TAK_AUTO_PUBLISHER=content_engine.trend_publishers:publish`

SNS 연결을 준비할 경우에만 추가:
- `TAK_AUTO_OAUTH_ENCRYPTION_KEY`
- `TAK_AUTO_MEDIA_SIGNING_KEY`
- YouTube, TikTok, Instagram, Facebook, Threads, Naver Login 앱별 client ID/secret
- `TAK_AUTO_PUBLIC_URL`은 실제 Render 서비스의 HTTPS URL과 일치시킨다.

보안:
- [ ] 비밀값은 Render Secret Environment Variable에만 입력한다.
- [ ] GitHub 저장소, 커밋, 로그, 화면 캡처, 채팅에 비밀값이 없는지 확인한다.
- [ ] Render 서비스가 Starter 플랜인지 확인한다.
- [ ] Persistent Disk가 실제로 `/var/data/trend-factory`에 연결됐는지 확인한다.
- [ ] 데이터 경로와 mountPath가 정확히 일치하는지 확인한다.
- [ ] 서비스 인스턴스는 단일 인스턴스로 유지한다. 현재 JSON 대기열은 프로세스 내부 잠금이므로 다중 인스턴스 확장은 금지한다.

## 3. 배포 후 최소 검증

1. 브라우저에서 공개 HTTPS 주소에 접속한다.
2. Basic Auth가 설정된 계정만 대시보드에 접근할 수 있는지 확인한다.
3. `/health`를 확인한다. 정상 운영 준비 조건은 다음과 같다.
   - `status=ok`
   - `perplexity_configured=true`
   - `web_auth_configured=true`
   - `storage_persistent=true`
   - `storage_mode=persistent_disk`
   - 게시 비활성화 상태(`publishing_enabled=false`)
   - `ready=true`
4. 화면에서 최신 트렌드 조사를 실행한다.
5. 트렌드 1개를 선택해 블로그, 쇼츠 장면 구성, Threads 2개 등 콘텐츠 패키지를 생성한다.
6. 출처 링크를 직접 열어 발행일·주장·숫자를 대조한다.
7. 품질 점수와 출처 URL 검사 결과를 사실 검증 완료로 오인하지 않는다.
8. 서버 재시작 또는 재배포 후 트렌드·초안 데이터가 유지되는지 확인한다.
9. `/health`의 revision이 기대한 Render 커밋 SHA와 일치하는지 확인한다.

검증 중 하나라도 실패하면 외부 게시를 진행하지 않는다.

## 4. 콘텐츠 운영 승인 절차

각 콘텐츠에 대해 운영자는 다음을 확인한다.

- [ ] 독자 검색 의도에 직접 답하는가?
- [ ] 제목이 콘텐츠 본문과 일치하는가?
- [ ] 원문 출처가 실제 주장을 뒷받침하는가?
- [ ] 숫자·날짜·정책·법률·가격·통계는 원문에서 재확인했는가?
- [ ] 이미지·영상·음원·인용의 저작권 및 플랫폼 정책을 확인했는가?
- [ ] 개인정보·금융기관 내부정보가 포함되지 않았는가?
- [ ] 블로그, 쇼츠, Threads 각 채널의 문안이 채널 특성에 맞는가?
- [ ] MP4를 쓰는 경우 실제 영상의 자막·음성·화면이 승인된 대본과 일치하는가?
- [ ] 최종 승인자와 승인 시각을 기록했는가?

구조 품질 점수는 편집 보조 지표다. 사실 정확성, 검색 순위, 클릭률, 조회수, 수익을 보증하지 않는다.

## 5. 플랫폼별 게시 준비 조건

| 플랫폼 | 운영 전 확인 |
|---|---|
| Threads | OAuth 연결, `threads_content_publish` scope, 실제 계정 확인 |
| Facebook 페이지 | 선택한 페이지, Page access token, `pages_manage_posts` 및 페이지 작업 권한 |
| YouTube Shorts | OAuth refresh token, `youtube.upload`, 완성 MP4, 기본 비공개 업로드 확인 |
| Instagram Reels | 프로페셔널 계정, 게시 scope, 공개 HTTPS 미디어 URL, 컨테이너 FINISHED 확인 |
| TikTok | Direct Post 앱 심사, `video.publish`, 계정 허용 공개 범위, 완성 MP4 |
| 네이버 블로그 | 수동 게시. 자동 게시 기능이 제공된다고 안내하지 않는다. |

계정 연결 성공은 게시 가능 또는 게시 승인을 뜻하지 않는다. 게시 기능 전역 스위치는 별도 승인 전까지 false로 유지한다.

## 6. 게시 결과가 불확실할 때

대기열 상태가 `needs_review`이면 자동 재시도하지 않는다.

1. 해당 플랫폼 계정에서 실제 게시물 존재 여부를 확인한다.
2. 게시됐다면 외부 게시 ID를 확보해 운영자 확인 절차로 완료 이력을 기록한다.
3. 게시되지 않았음을 확인한 경우에만 운영자 이름과 확인 시각을 기록하고 재예약한다.
4. 게시 여부를 확인할 수 없으면 재시도하지 않고 작업을 보류한다.
5. 같은 콘텐츠가 중복 게시된 경우 게시 이력과 원인을 보존하고 수동 조치한다.

## 7. 장애 대응

### 서비스가 시작되지 않음
- Render deploy logs에서 Python import 오류, 누락 환경변수, 의존성 설치 실패를 확인한다.
- 비밀값 원문을 로그나 이슈에 복사하지 않는다.
- 마지막 정상 배포 SHA와 현재 SHA를 비교한다.

### `ready=false` 또는 `ephemeral_fallback`
- Persistent Disk가 실제 mount됐는지 확인한다.
- mountPath와 `TAK_AUTO_DATA_DIR`가 일치하는지 확인한다.
- 데이터 보존을 확인하기 전 콘텐츠·게시 작업을 운영하지 않는다.

### OAuth 연결 실패
- 개발자 앱의 제품 활성화, 앱 모드, 테스트 사용자/역할, 권한 승인, Redirect URI를 점검한다.
- 암호화 키가 기존 토큰 저장 당시의 키와 동일한지 확인한다.
- 키 교체 시 기존 암호화 토큰을 읽지 못할 수 있으므로 임의 교체하지 않는다.

### 미디어 등록 또는 재생 실패
- MP4 컨테이너, 파일 크기(최대 100MB), Persistent Disk 저장 여부를 확인한다.
- 서명 URL의 HTTPS 도메인, 서명 키, 만료 시각을 확인한다.
- 공개 미디어 URL은 승인된 영상에만 발급한다.

### 게시 실패 또는 중복 의심
- `TAK_AUTO_PUBLISHING_ENABLED`를 false로 유지하거나 즉시 false로 되돌린다.
- 대기열 상태, 플랫폼별 게시 이력, 원격 게시물 ID를 보존한다.
- `needs_review`는 실제 플랫폼 확인 전 재시도하지 않는다.

## 8. 백업·복구 및 확장 제한

- 현재 JSON 저장소는 영속 디스크가 있어도 외부 백업을 대체하지 않는다.
- `scripts/backup_trend_factory_data.py`로 로컬 데이터 디렉터리를 manifest/SHA-256 검증 ZIP으로 백업·검증·새 경로 복구할 수 있다. 운영 보관본은 반드시 암호화한다.
- 예시(운영 데이터를 직접 읽거나 Render에 접속하는 명령이 아니다):
  - `python scripts/backup_trend_factory_data.py create --source <정지된 데이터 복제본> --output <보호된 백업 경로>/tak-auto.takbak --encrypt`
  - `python scripts/backup_trend_factory_data.py verify --archive <보호된 백업 경로>/tak-auto.takbak`
  - `python scripts/backup_trend_factory_data.py restore --archive <보호된 백업 경로>/tak-auto.takbak --destination <새 복구 경로>`
- 생성·검증·복구 시 암호문구를 터미널에 직접 입력한다. 길고 추측하기 어려운 고유 암호문구를 사용하고, 16자 이상으로 설정하며 백업 파일과 다른 보안 장소에 보관한다. 암호문구를 잃으면 복구할 수 없다. 명령 인자·환경 변수·로그에 암호문구를 전달하지 않는다.
- 입력 중 EOF 또는 Ctrl+C로 취소하면 CLI가 종료 오류를 간결히 표시한다. 백업 생성은 암호문구 확인이 끝난 뒤 시작하므로 취소 시 새 아카이브가 만들어지지 않는다.
- 생성 명령에는 `--source`를 반드시 직접 지정해야 한다. 기본 운영 데이터 경로를 실수로 백업하지 않도록 자동 source 경로를 두지 않는다.
- 생성 시 CLI는 `--encrypt` 또는 명시적 예외인 `--allow-unencrypted` 중 하나를 요구한다. OAuth 토큰 파일·미디어를 포함할 수 있는 운영 데이터에는 평문 옵션을 사용하지 않는다.
- 암호화는 PBKDF2-HMAC-SHA256으로 키를 유도하고 AES-256-GCM으로 ZIP 출력을 바로 스트리밍 암호화한다. 생성 중 평문 ZIP 파일은 디스크에 만들지 않는다. 검증·복구 때는 인증 태그를 확인한 뒤 복호화 임시본을 ZIP으로 연다. 잘못된 암호문구나 변조된 아카이브는 거부된다.
- 검증·복구 중 복호화 임시본이 로컬 파일시스템에 잠시 만들어진다. POSIX에서는 권한을 소유자 전용으로 제한하지만, 강제 종료 시 잔존할 수 있고 삭제가 물리적 보안 삭제를 뜻하지 않는다. 임시파일이 놓이는 장치도 신뢰하고 여유 공간을 확보한다.
- 일관된 파일 집합을 위해 백업 중에는 해당 데이터 디렉터리에 쓰는 프로세스를 정지한다. 서비스 중인 Render 디스크를 이 도구가 자동 스냅샷하지 않는다.
- ZIP 내부에는 암호화된 OAuth 토큰 파일, 게시 이력, 콘텐츠 및 업로드 MP4가 포함될 수 있다. 암호화된 `.takbak`을 접근 제한된 별도 보관 위치에 저장하고 채팅·저장소·공개 링크에 올리지 않는다.
- OAuth 복호화 키와 기타 환경변수 비밀값은 데이터 디렉터리에 포함되지 않는다. 키는 별도 비밀 관리 절차로 보관하고, 키를 잃으면 백업 안의 OAuth 토큰을 복호화할 수 없다.
- 생성은 기존 아카이브를 덮어쓰지 않으며, 검증은 경로 탈출·중복 경로·유형 불일치·크기/SHA 불일치를 거부한다. 복구는 이미 존재하는 경로(끊어진 심볼릭 링크 포함)를 덮어쓰지 않으며, 압축 해제 전에 manifest 크기와 여유 공간을 비교하고 최종 복구 디렉터리 이름 변경도 대상 없음 조건으로 원자 처리한다.
- 복구 리허설은 운영 데이터가 아닌 복제본과 새 대상 경로에서 수행하고, 파일 목록과 애플리케이션의 읽기 가능 여부를 확인한다. 이 도구의 테스트 통과는 Render 백업이 실제 존재한다는 뜻이 아니다.
- Render 디스크에서 복사본을 가져오고 보호된 외부 보관 위치에 정기 저장하는 실제 운영 절차는 서비스 생성 후 별도 승인·운영 설정이 필요하다.
- 현재 게시 대기열 및 일부 상태 저장은 단일 프로세스 잠금에 의존한다. 다중 인스턴스 또는 독립 worker를 여러 개 운영하지 않는다.
- 다중 인스턴스 전환 전 PostgreSQL 등 트랜잭션·원자적 작업 claim을 지원하는 공유 저장소로 이전하고 중복 게시 회귀 테스트를 추가한다.

## 9. 현재 확인 상태

2026-11-19 저장소 점검 시점:
- 검증 SHA `97d71b37abc9364b525ff37fbbfd70a882c68a53`: TAK SCOUT research tests 성공
- 같은 SHA: TAK AUTO trend content MVP tests 성공
- 같은 SHA: Python 전체 테스트 성공
- PR #3: Draft / Open / 미병합
- Render 실제 서비스 생성·배포: 미확인
- SNS OAuth 실계정 연결: 미확인
- 외부 게시 기능: 비활성화 설정 유지
- 운영 데이터 백업·복구 리허설: 미확인

이 상태 표는 운영자가 실제로 확인한 결과에 따라 갱신한다. 최신 검증 SHA에 대한 Actions 링크는 위 1절에 기록한다.


## 2026-11-19 최신 저장소 점검

- 최신 검증 SHA `651275680874e5e8256ccfa6e8552fc3ad4155b5`에서 3개 workflow 모두 성공 완료했다.
- 영상 업로드는 Basic Auth + same-origin 확인 + `video/mp4` + 1~100MB 제한 + MP4 `ftyp` 컨테이너 시그니처 + 서명 URL + Range 응답으로 보호된다. `ftyp` 검사는 컨테이너 식별용 1차 검사이지 영상 전체 디코딩/재생 품질 검증은 아니다. 실제 업로드 후 플랫폼 사전 검증이 필요하다.
- 게시 승인 요청은 인증 및 same-origin 확인을 통과해야 하며, TikTok은 공개 범위를 필수로 지정한다. 네이버 블로그는 수동 게시만 지원한다.
- 게시 대기열은 작업 시작 전 `processing` 상태를 영속 저장하고, 불확실한 응답이나 장시간 중단은 `needs_review`로 전환해 자동 중복 게시를 막는다.
- 현재 JSON 대기열 및 자산 인덱스의 동시성 제어는 단일 프로세스/인스턴스 기준이다. 다중 인스턴스 운영은 공유 DB 및 원자적 claim 구조로 이전하기 전까지 금지한다.
- 위 점검은 저장소 코드와 CI에 대한 검토다. Render 실제 배포, Persistent Disk 연결, 백업/복구, SNS 실계정 인증 및 게시 성공은 확인하지 않았다.


## 최신 게시 준비 UI 보완 — 2026-11-19

- 게시 플랫폼 선택은 실제 계정 연결 메타데이터와 실제 부여 scope를 기준으로 활성화한다.
- OAuth 대시보드 데이터는 액세스 토큰 원문을 전달하지 않는다. `access_token_configured`는 토큰이 암호화 저장소에 존재하는지만 나타내는 비밀값 없는 표시다.
- Threads는 `threads_content_publish`, Instagram은 `instagram_business_basic` 및 `instagram_business_content_publish`, YouTube Shorts는 `youtube.upload`와 refresh token, TikTok은 `video.publish`, Facebook은 페이지 게시 scope와 `CREATE_CONTENT` 또는 `MANAGE` 작업 권한을 요구한다.
- 만료 시각이 기록된 Meta/TikTok 토큰은 만료 여부를 검사해 게시 플랫폼 선택을 비활성화한다. YouTube는 refresh token 보유 여부로 액세스 토큰 갱신 가능성을 확인한다.
- 영상 플랫폼은 등록 MP4가 필요하며 Instagram Reels는 공개 HTTPS URL도 필요하다.
- 관련 회귀 테스트는 부여 scope 누락, 미디어 누락, 공개 URL 미설정, 만료 토큰, 토큰 존재 표시 누락을 포함한다.
- 최신 코드 SHA `d62ad49a48cea2a532e33beb2d6ca38dff676f20`에서 TAK AUTO MVP 및 TAK SCOUT 테스트는 성공했다. Python 전체 테스트는 완료 여부 미확정이며, 통과로 기록하지 않는다.


## 최신 Instagram 성과 수집 코드 검증 — 2026-11-19

- PR #3 head `0b467c252bee5b91622b48a52779a36886c66463` 기준 TAK AUTO trend content MVP, TAK SCOUT research, Python 전체 회귀(2,183 tests)가 모두 통과했다.
- Instagram Reels 조회는 `instagram_business_basic` 권한으로 `like_count`/`comments_count`만 가져온다. API가 제공하지 않은 값은 누락으로 유지하며 views를 추정하지 않는다. CLI 실제 호출은 `--confirm-live`로 보호된다.
- 이 확인은 코드/CI 점검이다. Instagram OAuth 실계정, 실제 API 응답, Render 배포 및 영구 디스크, 백업/복구 리허설, 외부 게시는 확인하지 않았다. 게시 비활성화 설정은 그대로 유지한다.


## 운영 백업 암호화 코드 검증 — 2026-11-19

- 백업 CLI는 source 경로를 명시해야 하며, 생성 시 암호화 또는 명시적 평문 선택을 요구한다. 운영 데이터에는 `--encrypt`를 사용한다.
- 암호화 생성은 ZIP 출력을 AES-GCM 암호화 writer에 바로 전달한다. 생성 중 평문 ZIP 파일은 만들지 않는다. 검증 및 복구는 임시 복호화 ZIP을 쓰고 인증 태그가 맞은 뒤에만 읽는다.
- 로컬 관련 테스트 결과는 최신 인수인계 문서의 집중 테스트 기록을 따른다. 평문·암호화 모드의 원본 변경 경합 거부, 복구 전 디스크 여유 공간 확인, 기존 경로(끊어진 symlink 및 사전 확인 뒤 생성된 빈 디렉터리 포함) 덮어쓰기 방지, 임시 파일 정리, 암호문구 입력 취소 시 안전 종료를 확인했다. Render 디스크에서 백업 복사·보관, 운영 데이터 복구 리허설은 미수행이다.
- 이 코드는 실제 외부 백업 서비스나 자동 보관 일정을 만들지 않는다. 운영자는 강한 암호문구를 백업과 별도 보안 위치에 보관해야 한다.
