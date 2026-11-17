# TAK AUTO SNS 계정 웹 연결 설정

TAK AUTO의 **게시 계정 연결 현황**에서 YouTube, TikTok, Instagram, Facebook 페이지, Threads, 네이버 계정을 OAuth로 연결할 수 있습니다. 이 흐름은 계정 프로필을 확인하고 인증 정보를 암호화해 보관합니다. 계정을 연결해도 게시나 예약 게시가 시작되지는 않습니다.

현재 웹 계정 연결은 계정 프로필 확인에 필요한 최소 권한만 요청합니다. 게시 권한은 요청하지 않습니다. 실제 게시 어댑터가 준비되고 게시 설정을 별도로 승인할 때 필요한 플랫폼 권한을 추가합니다.

## 1. Render 보안 설정

Render의 `tak-auto-trend-factory` 서비스에서 **Environment**에 아래 값을 설정하세요. 인증 비밀값은 채팅, 저장소, 화면 캡처에 넣지 않습니다.

- `TAK_AUTO_PUBLIC_URL`: `https://tak-auto-trend-factory.onrender.com`
- `TAK_AUTO_OAUTH_ENCRYPTION_KEY`: Fernet 키. 서비스의 암호화 파일에 SNS 토큰을 저장하는 데 사용합니다.
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

TikTok 앱에는 Login Kit 웹 제품을 추가하고 `user.info.basic` 권한을 설정합니다. 게시 권한인 `video.publish`는 현재 요청하지 않습니다. Meta 앱에서는 Facebook Login, Instagram Login, Threads API 제품을 각각 설정하고 위 콜백을 등록합니다. 계정 확인에는 Facebook `pages_show_list`, Instagram `instagram_business_basic`, Threads `threads_basic` 권한을 사용하며 게시 권한은 요청하지 않습니다. Meta 개발 앱이 개발 모드이면 앱 역할로 등록된 테스트 계정만 연결될 수 있습니다. 플랫폼이 앱 검토를 요구하면 해당 검토를 완료해야 다른 계정이 연결될 수 있습니다.

네이버 앱에는 네이버 로그인을 추가하고 콜백 URL을 등록합니다. 이 연결은 네이버 사용자 프로필을 확인합니다. 네이버 블로그 글쓰기 Open API는 종료되어 계정 연결이 블로그 자동 게시를 열어주지는 않습니다.

## 3. 웹에서 계정 연결

Render 환경변수를 저장한 다음 서비스를 재시작하세요. 대시보드의 **게시 계정 연결 현황**에서 각 서비스의 **계정 연결**을 누르고 해당 SNS에 로그인한 뒤 권한을 승인합니다. Facebook은 관리 중인 페이지 목록이 나오므로 연결할 페이지를 선택합니다. 이후 카드에는 계정 이름, 연결 시각, 만료 정보가 표시됩니다.

연결 해제는 TAK AUTO의 암호화 저장소에서 토큰을 삭제합니다. 플랫폼의 앱 권한까지 해제하려면 해당 SNS의 연결된 앱/보안 설정에서도 접근 권한을 철회하세요.

## 보안 및 게시 상태

- OAuth state는 브라우저의 HttpOnly 쿠키와 대조하고 한 번만 사용합니다. Google 웹 OAuth에는 PKCE를 적용합니다.
- access token과 refresh token은 `TAK_AUTO_OAUTH_ENCRYPTION_KEY`로 암호화해 Render 영구 디스크에 저장합니다. 토큰 원문은 대시보드에 표시하지 않습니다.
- 게시 스위치는 `TAK_AUTO_PUBLISHING_ENABLED=false`로 유지합니다. 로그인/연결은 승인이나 외부 게시를 실행하지 않습니다.
