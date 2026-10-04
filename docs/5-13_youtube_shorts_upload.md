# 5-13. YouTube Shorts 자동 업로드 구현

## 목표

완성된 9:16 MP4(음성 없음, 고정 이미지, 카드뉴스/정보형) Shorts 영상을 YouTube Data
API v3 공식 방식(OAuth 2.0, Access/Refresh Token)으로 자동 업로드하는 기능을 추가한다.

흐름: 완성된 MP4 → 제목 → 설명 → 해시태그 → YouTube Shorts 업로드 → 업로드 결과 기록.

이번 작업 범위는 "YouTube 자동 업로드"만이다. TAK BRAIN, TAK MEDIA, Threads 자동화는
전혀 수정하지 않았다.

## 1. 추가/수정 파일

### 신규 파일
- `content_engine/youtube_publisher.py` — `YouTubeClient` (OAuth2 access/refresh token
  갱신 + resumable upload 프로토콜, 표준 라이브러리 `urllib`만 사용)
- `content_engine/youtube_upload_history.py` — 업로드 이력 저장소
  (`data/youtube_publish_log.json`, 원자적 JSON append)
- `scripts/upload_youtube_short.py` — 업로드 CLI
- `scripts/youtube_oauth_setup.py` — 최초 1회 OAuth 인증 도구 (Device Authorization Grant)
- `.github/workflows/youtube-shorts-upload.yml` — `workflow_dispatch`-only 워크플로 구조
  (스케줄 없음, 다음 단계에서 연결)
- `tests/test_youtube_publisher.py`, `tests/test_youtube_upload_history.py`,
  `tests/test_upload_youtube_short_cli.py`

### 수정 파일 (둘 다 추가(append)만, 기존 내용 변경 없음)
- `content_engine/__init__.py` — 새 클래스/예외 export 추가
- `.gitignore` — `data/youtube_publish_log.json` allow-list 추가, `data/shorts/*.mp4` 무시 추가

기존 `content_engine/threads_publisher.py`, `content_engine/publish_history.py`,
`scripts/publish_threads.py`, `scripts/run_daily.py`, `.github/workflows/daily-threads-post.yml`,
`.github/workflows/publish-approved-threads.yml` 등은 한 줄도 건드리지 않았다.

## 2. 구현된 기능

- **`YouTubeClient`** (`content_engine/youtube_publisher.py`)
  - `from_environment()`: `YOUTUBE_CLIENT_ID` / `YOUTUBE_CLIENT_SECRET` /
    `YOUTUBE_REFRESH_TOKEN` 환경변수로부터 생성. 하나라도 없으면
    `YouTubeConfigurationError`.
  - `upload_short(...)`: refresh_token으로 access_token을 새로 발급받은 뒤,
    YouTube Data API v3 **resumable upload** 프로토콜(메타데이터 POST →
    `Location` 헤더로 영상 바이너리 PUT)로 업로드.
  - 업로드 전 로컬 검증: 파일 존재 여부, `.mp4` 확장자, 제목 비어있음/100자 초과,
    `privacy_status`가 `private`/`unlisted`/`public` 중 하나인지 — 검증 실패 시
    네트워크 호출 자체가 일어나지 않는다.
  - `token_transport`/`upload_transport`를 주입 가능하게 설계해 실제 네트워크
    없이 단위 테스트 가능 (Threads client와 동일한 설계 원칙).
  - HTTP 오류 메시지에서 토큰 등 민감정보를 제거하고 `message`/`code`/`reason`
    (또는 OAuth 표준 `error`/`error_description`)만 추출.
- **`YouTubeUploadHistory`** (`content_engine/youtube_upload_history.py`)
  - `data/youtube_publish_log.json`에 업로드 성공 건만 원자적으로 append
    (`video_id`, `uploaded_at`, `title`, `privacy_status`, `video_path`, `tags`, `url`).
- **`scripts/upload_youtube_short.py`**
  - `--video`/`--title`/`--description`/`--tags`/`--privacy`/`--category-id`/
    `--history`/`--dry-run` 인자 지원.
  - `--dry-run`은 실제 YouTube API를 전혀 호출하지 않고 업로드 예정 내용만 출력,
    업로드 이력도 기록하지 않는다.
  - 실패 시 원인이 명확한 오류 메시지를 stderr로 출력하고 0이 아닌 종료 코드 반환.
  - 성공 시 video ID와 URL을 출력하고 이력 파일에 기록.
- **`scripts/youtube_oauth_setup.py`**
  - Device Authorization Grant로 최초 1회 refresh_token을 발급받는 CLI.
  - refresh_token은 **화면에만 1회 출력**하고 어떤 파일에도 저장하지 않는다.

## 3. OAuth 최초 인증 방법

### 3-1. Google Cloud Console 설정 (최초 1회, 사람이 직접 해야 함)

1. https://console.cloud.google.com 에서 프로젝트 생성(또는 기존 프로젝트 선택).
2. "API 및 서비스 → 라이브러리"에서 **YouTube Data API v3** 활성화.
3. "API 및 서비스 → OAuth 동의 화면" 구성 (User Type: 외부/테스트 모드로 시작 가능).
   - 스코프에 `https://www.googleapis.com/auth/youtube` 추가.
   - (주의) Device Authorization Grant(TVs and Limited Input devices)는 Google이
     문서화한 허용 scope 목록에 `youtube.upload`를 포함하지 않는다. 허용되는 것은
     `youtube`(전체)와 `youtube.readonly`뿐이며, `videos.insert`(업로드)는 전체
     `youtube` scope로도 정상 동작하므로 이 값을 사용한다 (5-14 수정).
4. "API 및 서비스 → 사용자 인증 정보 → 사용자 인증 정보 만들기 → OAuth 클라이언트 ID"
   - **애플리케이션 유형: "TV 및 제한된 입력 기기(TVs and Limited Input devices)"**
     선택 — 이 유형이어야 아래 Device Authorization Grant 흐름을 쓸 수 있다.
   - 생성된 **Client ID**, **Client Secret**을 기록해둔다 (git에 저장하지 않는다).

### 3-2. Refresh Token 발급 (Device Authorization Grant)

Codespaces처럼 브라우저가 없는 헤드리스 환경에서도 동작하도록, 로컬 리다이렉트
서버가 필요 없는 Device Flow를 사용한다.

```bash
python scripts/youtube_oauth_setup.py \
  --client-id "<Google Cloud OAuth Client ID>" \
  --client-secret "<Google Cloud OAuth Client Secret>"
```

1. 스크립트가 인증 URL과 코드(user code)를 출력한다.
2. 아무 기기(휴대폰 등)의 브라우저에서 그 URL을 열고 코드를 입력, 업로드 권한을 승인한다.
3. 승인이 완료되면 스크립트가 자동으로 polling을 마치고 `YOUTUBE_REFRESH_TOKEN=...`
   한 줄을 터미널에 출력한다.
4. 이 값을 **GitHub Secret(`YOUTUBE_REFRESH_TOKEN`)** 또는 로컬 `.env`
   (반드시 `.gitignore` 대상)로 직접 옮긴다. 스크립트 자체는 어떤 파일에도
   저장하지 않는다.

이후에는 매 업로드마다 이 refresh_token으로 access_token을 자동 갱신하므로,
재인증 없이 계속 사용할 수 있다 (Google 계정에서 앱 접근을 취소하지 않는 한).

## 4. 필요한 환경변수 / GitHub Secret

| 이름 | 용도 | 어디서 얻나 |
|---|---|---|
| `YOUTUBE_CLIENT_ID` | OAuth 클라이언트 ID | Google Cloud Console (3-1) |
| `YOUTUBE_CLIENT_SECRET` | OAuth 클라이언트 시크릿 | Google Cloud Console (3-1) |
| `YOUTUBE_REFRESH_TOKEN` | 장기 인증용 refresh token | `scripts/youtube_oauth_setup.py` (3-2) |

세 값 모두 코드/저장소에 하드코딩하지 않으며, 로그에도 출력하지 않는다
(`content_engine/youtube_publisher.py`의 오류 메시지 처리 참고).

## 5. CLI 사용법

```bash
# dry-run (네트워크 호출 없음, 토큰 불필요)
python scripts/upload_youtube_short.py \
  --video data/shorts/short_001.mp4 \
  --title "60대 이후에도 꼭 곁에 두어야 할 진짜 인연 5가지" \
  --description "티몽의 지혜..." \
  --tags "인간관계,인생,명언,채근담,티몽의지혜" \
  --privacy private \
  --dry-run

# 실제 업로드 (환경변수 3개 필요)
export YOUTUBE_CLIENT_ID="..."
export YOUTUBE_CLIENT_SECRET="..."
export YOUTUBE_REFRESH_TOKEN="..."
python scripts/upload_youtube_short.py \
  --video data/shorts/short_001.mp4 \
  --title "60대 이후에도 꼭 곁에 두어야 할 진짜 인연 5가지" \
  --description "티몽의 지혜..." \
  --tags "인간관계,인생,명언,채근담,티몽의지혜" \
  --privacy private
```

## 6. dry-run 결과 (실제 실행 확인)

```
=== YouTube Shorts Upload (Dry-run) ===
영상 파일: /tmp/tmpmz5txu6y.mp4
제목: 60대 이후에도 꼭 곁에 두어야 할 진짜 인연 5가지
설명: 티몽의 지혜...
태그: ['인간관계', '인생', '명언', '채근담', '티몽의지혜']
공개 상태: private
카테고리 ID: 22
--------------------------------------------------
네트워크 호출 없음. 실제 업로드에는 --dry-run 없이 YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET / YOUTUBE_REFRESH_TOKEN 환경변수가 필요합니다.
Dry-run에서는 업로드 이력을 기록하지 않습니다.
```
(exit code 0, API 호출 없음 확인)

## 7. 실제 private 업로드 테스트 결과

**이번 세션에서는 실제 YouTube 업로드를 수행하지 않았다.** 이유:

- 이 개발 환경(Codespaces)에는 `YOUTUBE_CLIENT_ID`/`YOUTUBE_CLIENT_SECRET`/
  `YOUTUBE_REFRESH_TOKEN`이 설정되어 있지 않다 (확인됨: `env | grep YOUTUBE` 결과 없음).
- 실제 업로드를 하려면 위 3-1(Google Cloud Console에서 OAuth 클라이언트 생성)과
  3-2(브라우저로 직접 열어 코드 입력·권한 승인)를 **사용자 본인이** 완료해야 하며,
  이는 자동화 에이전트가 대신 수행할 수 없는 단계다(사람의 Google 계정 승인 필요).

대신 자격증명이 없을 때의 동작을 실제로 실행해 확인했다:

```bash
$ python scripts/upload_youtube_short.py --video short.mp4 --title "실제 업로드 시도 테스트" --privacy private
설정 오류: 다음 환경변수가 필요합니다: YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN
(exit code 1)
```

업로드 로직 자체(메타데이터 구성, resumable upload 2단계 요청, 응답 파싱, 이력 기록)는
`tests/test_youtube_publisher.py`에서 네트워크를 모킹한 단위 테스트로 검증했다
(access_token 발급 → 업로드 요청 → video_id 반환 → 오류 시 민감정보 미노출까지 전부 커버).

**다음 단계에서 사용자가 3-1/3-2를 완료해 실제 `YOUTUBE_REFRESH_TOKEN`을 발급받으면,
바로 위 CLI 명령으로 실제 private 업로드 테스트를 진행할 수 있다.**

## 8. YouTube video ID

위 7번 사유로 이번 세션에서는 실제 업로드를 수행하지 않았으므로 발급된 video ID가 없다.

## 9. 전체 테스트 결과

```
$ python3 -m unittest discover -s tests -p 'test*.py'
...
Ran 482 tests in 28.5s

OK
```

기존 테스트를 포함해 전체 482건 모두 통과 (신규 YouTube 관련 테스트 약 25건 포함,
기존 Threads/TAK BRAIN/TAK MEDIA 테스트는 수정 없이 그대로 통과).

## 10. 다음 단계에서 연결할 것

1. **실제 OAuth 인증 완료**: 사용자가 3-1/3-2를 진행해 `YOUTUBE_REFRESH_TOKEN` 발급 →
   GitHub Secret(`YOUTUBE_CLIENT_ID`/`YOUTUBE_CLIENT_SECRET`/`YOUTUBE_REFRESH_TOKEN`) 등록.
2. **실제 private 업로드 1건 테스트**: 발급된 자격증명으로
   `scripts/upload_youtube_short.py`를 `--privacy private`로 실행해 실제 video ID 확보.
3. **TAK MEDIA → MP4 렌더링 파이프라인과 연결**: 현재는 "완성된 MP4를 인자로 받는
   업로드"만 구현했다. 고정 이미지 기반 9:16 MP4를 실제로 만드는 렌더링 단계
   (이미지 → 카드뉴스 스타일 합성 → MP4 인코딩)는 이번 범위 밖이며, 그 산출물 경로를
   `--video`로 넘기기만 하면 이 업로더가 바로 동작한다.
4. **`.github/workflows/youtube-shorts-upload.yml`에 cron 연결**: 현재는
   `workflow_dispatch`만 있다. Threads 쪽 `daily-threads-post.yml`과 마찬가지로,
   운영이 안정화된 뒤 스케줄을 추가할지 검토한다.
5. **`scripts/run_daily.py`와의 통합 여부 결정**: 현재 오케스트레이터는 Threads까지만
   잇는다. Shorts 렌더링이 준비되면 "TAK MEDIA → MP4 렌더링 → YouTube 업로드"를
   별도 오케스트레이터로 만들지, `run_daily.py`에 단계를 추가할지는 이번 범위에서
   결정하지 않았다.
