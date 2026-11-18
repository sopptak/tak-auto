# TAK AUTO SNS 계정 웹 연결 설정

TAK AUTO의 **게시 계정 연결 현황**에서 YouTube, TikTok, Instagram, Facebook 페이지, Threads, 네이버 계정을 OAuth로 연결할 수 있습니다. 이 흐름은 계정 프로필을 확인하고 인증 정보를 암호화해 보관합니다. 계정을 연결해도 게시나 예약 게시가 시작되지는 않습니다.

웹 로그인은 계정 연결 상태를 확인합니다. Threads는 `threads_content_publish`, Instagram은 `instagram_business_content_publishing`, Facebook은 `pages_show_list`, `pages_read_engagement`, `pages_manage_posts` 권한을 요청합니다. 연결 자체로 게시되지는 않습니다. 게시물은 운영자 승인 대기열을 통과해야 하며 전역 게시 스위치는 기본적으로 꺼져 있습니다.

암호화 저장소에 Threads 웹 연결 기록이 있으면 게시 어댑터는 그 토큰을 사용하며 `threads_content_publish` 권한이 확인되지 않으면 게시를 거부합니다. Threads 연결 기록이 없을 때만 기존 `THREADS_ACCESS_TOKEN` 설정을 사용할 수 있습니다. YouTube Shorts와 Instagram Reels는 승인 대기열 게시 어댑터가 구현되어 있지만, 실제 계정 인증·영상 준비·운영 검증은 별도입니다. Facebook 페이지 텍스트 게시 어댑터도 구현되어 있습니다. 선택한 페이지의 Page access token을 사용하며 게시 요청은 `/PAGE_ID/feed`에 전달됩니다. 네이버 블로그 자동 게시 어댑터는 지원하지 않습니다. TikTok Direct Post는 `video.publish` 승인 및 계정 연결이 완료된 경우에만 사용할 수 있습니다.

## 1. Render 보안 설정

Render의 `tak-auto-trend-factory` 서비스에서 **Environment**에 아래 값을 설정하세요. 인증 비밀값은 채팅, 저장소, 화면 캡처에 넣지 않습니다.

- `TAK_AUTO_PUBLIC_URL`: `https://tak-auto-trend-factory.onrender.com`
- `TAK_AUTO_OAUTH_ENCRYPTION_KEY`: Fernet 키. 서비스의 암호화 파일에 SNS 토큰을 저장하는 데 사용합니다.
- `TAK_AUTO_MEDIA_SIGNING_KEY`: 32자 이상의 무작위 비밀값. MP4 미디어 공개 URL에 48시간 HMAC 서명을 생성하는 데 사용합니다.
- `YOUTUBE_OAUTH_CLIENT_ID`, `YOUTUBE_OAUTH_CLIENT_SECRET`
- `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`
- `INSTAGRAM_APP_ID`, `INSTAGRAM_APP_SECRET`
- `FACEBOOK_APP_ID`, `FACEBOOK_APP_SECRET`
- `THREADS_APP_ID`, `THREADS_APP_SECRET`
- `NAVER_LOGIN_CLIENT_ID`, `NAVER_LOGIN_CLIENT_SECRET`

키는 새로 생성해 Render Secret Environment Variable에 넣습니다. 생성 명령은 로컬에서 실행하고 그 출력값을 채팅에 붙이지 마세요.

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

미디어 서명 키는 별도로 생성합니다. 이 값도 Render Secret Environment Variable에만 입력하고 저장소나 채팅에 붙이지 마세요.

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

## 2. 각 개발자 앱에 콜백 주소 등록

앱 등록 시 해당 서비스의 웹 OAuth/Login 제품을 활성화하고 아래 주소를 **그대로** 등록하세요.

| 서비스 | 등록할 OAuth 콜백 주소 |
|---|---|
| YouTube | `https://tak-auto-trend-factory.onrender.com/connections/oauth/callback/youtube_shorts` |
| TikTok | `https://tak-auto-trend-factory.onrender.com/connections/oauth/callback/tiktok` |
| Instagram | `https://tak-auto-trend-factory.onrender.com/connections/oauth/callback/instagram_reels` |
| Facebook | `https://tak-auto-trend-factory.onrender.com/connections/oauth/callback/facebook` |
| Threads | `https://tak-auto-trend-factory.onrender.com/connections/oauth/callback/threads` |
| 네이버 로그인 | `https://tak-auto-trend-factory.onrender.com/connections/oauth/callback/blog` |

YouTube는 Google Cloud에서 YouTube Data API v3를 활성화하고 OAuth 클라이언트 유형을 **웹 애플리케이션**으로 생성합니다. 계정 확인에는 `youtube.readonly`만 요청합니다. 기존 로컬 인증 스크립트의 Desktop 앱 JSON은 웹 콜백에 사용할 수 없습니다.

TikTok 앱에는 Login Kit와 Content Posting API 제품을 추가하고 `user.info.basic`, `video.publish` 권한을 설정합니다. Direct Post 사용 전 TikTok 개발자 앱의 Direct Post 구성을 활성화하고 앱 심사를 완료해야 합니다. `video.publish` 권한을 요청하며, TikTok 앱의 Direct Post 제품 설정과 권한 승인이 필요합니다. Meta 앱에서는 Facebook Login, Instagram Login, Threads API 제품을 각각 설정하고 위 콜백을 등록합니다. Facebook 페이지 게시에는 `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`를 요청하고, Instagram에는 `instagram_business_basic`과 `instagram_business_content_publishing`, Threads에는 `threads_basic`과 `threads_content_publish`를 요청합니다. Instagram 계정은 프로페셔널(비즈니스 또는 크리에이터) 계정이어야 하며, 릴스 게시에는 암호화된 연결 토큰에 두 Instagram 권한이 모두 있어야 합니다. Threads 연결 카드에 게시 권한이 표시되어야 승인 대기열의 텍스트 어댑터가 암호화된 웹 로그인 토큰을 사용할 수 있습니다. Meta 개발 앱이 개발 모드이면 앱 역할로 등록된 테스트 계정만 연결될 수 있습니다. 플랫폼이 앱 검토를 요구하면 해당 검토를 완료해야 다른 계정이 연결될 수 있습니다.

네이버 앱에는 네이버 로그인을 추가하고 콜백 URL을 등록합니다. 이 연결은 네이버 사용자 프로필을 확인합니다. 네이버 블로그 글쓰기 Open API는 종료되어 계정 연결이 블로그 자동 게시를 열어주지는 않습니다.

## 3. 웹에서 계정 연결

Render 환경변수를 저장한 다음 서비스를 재시작하세요. 대시보드의 **게시 계정 연결 현황**에서 각 서비스의 **계정 연결**을 누르고 해당 SNS에 로그인한 뒤 권한을 승인합니다. Facebook은 관리 중인 페이지 목록이 나오므로 연결할 페이지를 선택합니다. 이후 카드에는 계정 이름, 연결 시각, 만료 정보가 표시됩니다.

연결 해제는 TAK AUTO의 암호화 저장소에서 토큰을 삭제합니다. 플랫폼의 앱 권한까지 해제하려면 해당 SNS의 연결된 앱/보안 설정에서도 접근 권한을 철회하세요.


## 4. Instagram Reels 영상 준비

Instagram Reels 어댑터는 Meta가 서버에서 직접 가져갈 수 있는 **공개 HTTPS 영상 URL**을 받습니다. Render 내부 파일 경로, 로컬 PC 경로, 로그인/쿠키가 필요한 URL은 사용할 수 없습니다. 콘텐츠 payload에는 `video_url`과 `caption`을 넣습니다. `share_to_feed`는 선택값이며 기본값은 `true`입니다.

게시 흐름은 Meta의 미디어 컨테이너 생성 → 컨테이너 처리 상태 확인 → `FINISHED` 확인 후 `media_publish` 순서입니다. 처리 중이거나 실패한 컨테이너는 게시하지 않습니다. API 응답이 유실되어 게시 여부를 확정할 수 없으면 자동 재시도하지 않고 운영자 확인 상태로 보냅니다.

대시보드의 **쇼츠 영상 파일 등록**에서 완성된 MP4를 업로드하면 Render 영구 디스크에 저장되고, Instagram 게시 시점에 48시간짜리 서명 HTTPS URL이 생성됩니다. 공개 URL은 서명과 만료 시각이 맞아야만 영상 파일을 제공하며 대시보드 로그인 인증과 분리됩니다. 최대 업로드 크기는 100MB입니다. 다만 현재 트렌드 생성기는 쇼츠 대본과 장면 구성까지만 만들며 MP4 렌더링은 별도입니다. 영상 편집/렌더링을 완료한 MP4를 등록한 뒤에만 YouTube Shorts 또는 Instagram Reels 예약을 진행하세요.

## 보안 및 게시 상태

- OAuth state는 브라우저의 HttpOnly 쿠키와 대조하고 한 번만 사용합니다. Google 웹 OAuth에는 PKCE를 적용합니다.
- access token과 refresh token은 `TAK_AUTO_OAUTH_ENCRYPTION_KEY`로 암호화해 Render 영구 디스크에 저장합니다. 토큰 원문은 대시보드에 표시하지 않습니다.
- 게시 스위치는 `TAK_AUTO_PUBLISHING_ENABLED=false`로 유지합니다. 로그인/연결은 승인이나 외부 게시를 실행하지 않습니다.


## 5. TikTok Direct Post 영상 준비

TikTok Direct Post는 승인된 MP4를 TikTok 서버로 직접 전송합니다. 예약 전에 TikTok 계정 연결에 `video.publish` 권한이 있어야 하며, 콘텐츠 payload에는 사용자가 선택한 `privacy_level`이 필요합니다. 현재 계정에서 허용하지 않는 공개 범위는 TikTok 크리에이터 정보 조회 결과와 비교해 게시를 거부합니다.

- 공개 범위: `PUBLIC_TO_EVERYONE`, `MUTUAL_FOLLOW_FRIENDS`, `FOLLOWER_OF_CREATOR`, `SELF_ONLY` 중 계정에서 허용된 값만 사용
- AI 생성 영상은 예약 화면에서 AI 생성 표시를 선택해 `is_aigc=true`로 전달
- 영상 파일은 MP4, 서비스 업로드 한도는 100MB
- TikTok이 발급한 업로드 URL로 순차 청크 전송 후 게시 상태가 `PUBLISH_COMPLETE`인지 확인
- API 응답이 유실되거나 최종 상태를 확인할 수 없으면 중복 게시 방지를 위해 운영자 확인 상태로 전환

TikTok Direct Post 앱 심사를 통과하지 않은 클라이언트는 게시물이 비공개로 제한될 수 있습니다. 따라서 앱 심사 전에는 공개 게시를 보장하지 않습니다. Content Posting API 앱 제품 설정, `video.publish` 승인, 계정 동의가 완료된 후 실제 계정으로 검증해야 합니다.

## 6. Facebook 페이지 텍스트 게시

Facebook OAuth를 다시 연결해 아래 권한을 승인해야 페이지 게시 메뉴가 활성화됩니다.

- `pages_show_list`: 관리 가능한 페이지 목록 확인
- `pages_read_engagement`: 페이지 및 게시 권한 확인에 필요한 권한
- `pages_manage_posts`: 페이지 이름으로 게시물 작성
- 연결 마지막 단계에서 실제 게시할 Facebook 페이지를 선택합니다. 선택된 페이지의 Page access token과 페이지 ID가 암호화 저장소에 보관됩니다.
- 게시 권한이 있는 페이지에서 `CREATE_CONTENT` 작업 권한을 가진 계정이어야 합니다.
- 페이지 선택 화면에는 `CREATE_CONTENT` 또는 `MANAGE` 작업 권한이 있는 페이지만 표시됩니다. 현재 자동 게시 어댑터는 Facebook 전용 문안의 텍스트 게시만 지원합니다. 사진·영상·릴스는 Facebook 게시 어댑터 범위에 포함되지 않습니다.
- 게시 예약은 콘텐츠 승인 대기열을 사용합니다. 전역 게시 스위치가 켜져 있고 운영자 승인 조건이 충족되기 전에는 외부 페이지에 게시되지 않습니다.
- 게시 응답이 유실되면 중복 게시 방지를 위해 자동 재시도하지 않고 운영자 확인 상태로 전환합니다.

Meta 공식 요구사항은 Page access token, `pages_manage_posts`, `pages_read_engagement`, `pages_show_list` 및 해당 페이지의 `CREATE_CONTENT` 또는 `MANAGE` 작업 권한입니다.

