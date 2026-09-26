# 5-15. Firebase Hosting 홈페이지 / 개인정보처리방침 페이지 추가

## 목적

Google Cloud OAuth 동의 화면에 등록할 "애플리케이션 홈페이지 URL"과
"개인정보처리방침 URL"을 실제로 접근 가능한 정적 페이지로 만든다.
YouTube 업로드 로직, Threads, TAK BRAIN, TAK MEDIA 등 기존 자동화는 전혀
건드리지 않는다.

## 사전 조사 결과

- 저장소 전체(`.venv` 제외)에서 `firebase`를 검색했으나 기존 Firebase 설정(`.firebaserc`,
  `firebase.json`, `public/` 등)이 **전혀 없었다** — 이번이 최초 구성이다.
- `firebase` CLI는 설치되어 있지 않았고, `gcloud` CLI도 없다.
- `node`/`npm`/`npx`는 사용 가능 (`npx firebase-tools@latest --version` → `15.30.1` 정상 응답
  확인, 로그인 없이도 버전 조회는 가능함을 확인했다. 이 저장소에 firebase-tools를
  영구 설치하지 않고 `npx`로 그때그때 받아 쓰는 방식을 택해, Python 전용이던 기존
  저장소 구조에 Node 의존성(package.json, node_modules)을 추가하지 않았다).
- 이 문서를 처음 작성할 당시(구현 직후)에는 Firebase/Google Cloud 로그인 세션이
  없어 `tmong-golf-diary` 프로젝트 실존 여부, Hosting 활성화 여부, 커스텀 도메인
  연결 여부를 확인할 수 없었다. 이후 사용자가 `firebase login --no-localhost`로
  직접 인증을 진행해 로그인을 완료했고, 그 결과로 4~5장의 실제 배포까지 이어졌다.

## 1. 추가/수정 파일

### 신규 파일
- `public/index.html` — 홈페이지 ("티몽의 지혜" 브랜드, 4개 항목, 모바일 대응)
- `public/privacy.html` — 개인정보처리방침 (`cleanUrls`로 `/privacy` 경로로 접근)
- `firebase.json` — Hosting 설정 (`public: "public"`, `cleanUrls: true`)
- `.firebaserc` — 기본 프로젝트를 `tmong-golf-diary`로 지정
- `tests/test_firebase_hosting.py` — 파일 존재/설정값/페이지 내용/로컬 서버 접근 검증 (20건)
- 본 문서

### 수정 파일 (추가만, 기존 항목 변경 없음)
- `.gitignore` — Firebase CLI가 로컬에서 만드는 캐시/로그(`.firebase/`,
  `firebase-debug*.log`)만 무시 대상에 추가. 인증정보 파일이 아니다.

`content_engine/youtube_publisher.py`, `content_engine/youtube_upload_history.py`,
`scripts/upload_youtube_short.py`, `scripts/youtube_oauth_setup.py`, Threads/TAK BRAIN/
TAK MEDIA 관련 파일은 전혀 수정하지 않았다.

## 2. 페이지 내용

### 홈페이지 (`/`)
- 제목: 티몽의 지혜
- 설명: "AI를 활용해 콘텐츠를 만들고 관리하는 개인 콘텐츠 자동화 프로젝트입니다."
- 항목: 콘텐츠 기획 / 정보 및 지식 정리 / YouTube Shorts 콘텐츠 제작 / 콘텐츠 자동 게시 및 관리
- 모바일 대응: `viewport` 메타 태그 + 최대 640px 폭의 단순 레이아웃, 다크모드 대응

### 개인정보처리방침 (`/privacy`)
현재 이 프로젝트가 실제로 처리하는 범위만 기술했다.
- 이 웹페이지 자체는 방문자의 개인정보(이름/이메일/쿠키/로그 등)를 수집하지 않는다는 점을 명시
- Google OAuth 2.0으로 운영자 본인의 YouTube 계정을 인증할 수 있다는 점
- 업로드에 필요한 최소 권한만 요청한다는 점
- Access Token/Refresh Token은 안전하게 관리하며 공개 저장소(Git)에 저장하지 않는다는 점
- 제3자 제공 없음, 콘텐츠 업로드 목적으로만 YouTube Data API를 사용한다는 점
- `myaccount.google.com/permissions`에서 사용자가 직접 접근 권한을 철회할 수 있다는 점
- 하지 않는 것(로그인/회원가입/광고추적/분석쿠키 등)은 없다고 명시 — 사용하지 않는 기능을
  수집한다고 거짓 기재하지 않았다
- "문의" 섹션은 처음에는 자리표시자로 남겨뒀으나, 사용자가 제공한 연락처
  `mygolfdiary01@gmail.com`으로 채워 넣고 재배포했다(6장 참고).

## 3. URL (실제 배포 후 확인 완료)

`npx firebase-tools deploy --only hosting` 실행 결과와 배포 후 직접 HTTP 요청으로
아래 두 URL이 실제로 200을 반환함을 확인했다 (추측이 아니라 배포 후 검증된 값이다).

- 홈페이지: **https://tmong-golf-diary.web.app/**
- 개인정보처리방침: **https://tmong-golf-diary.web.app/privacy**

동일 프로젝트의 보조 도메인(`https://tmong-golf-diary.firebaseapp.com/`,
`.../privacy`)도 동일하게 200으로 응답함을 확인했다. 커스텀 도메인은 연결되어
있지 않다(`hosting:sites:list` 결과에 기본 사이트 하나만 존재).

## 4. Firebase Hosting 설정 상태

| 항목 | 상태 |
|---|---|
| `.firebaserc` / `firebase.json` | 신규 생성, 커밋 대상 |
| `public/` 디렉터리(정적 페이지) | 신규 생성, 커밋 대상 |
| Firebase CLI 로그인 | **완료** (`sopptak@gmail.com`, `firebase login <authorizationCode>`로 인증 — 자격증명은 로컬 CLI 설정에만 저장되며 이 저장소/Git에는 전혀 기록되지 않음) |
| `tmong-golf-diary` 프로젝트 | **실존 확인** (Project Display Name: "My Golf Diary", Project Number: 404175467987) |
| Hosting 사이트 | **기존 활성화 상태 확인** (`tmong-golf-diary` 사이트, 기본 URL `tmong-golf-diary.web.app`) |
| 실제 배포 | **완료** (2건 파일 업로드, 새 버전 릴리스) |

## 5. 실제 배포 여부

**완료했다.** 사용자가 `firebase login --no-localhost`로 발급받은 authorization
code를 제공해 로그인을 마쳤고, `projects:list`/`use tmong-golf-diary`로 대상
프로젝트를 확인한 뒤 `deploy --only hosting`으로 `public/index.html`,
`public/privacy.html` 2개 파일을 배포했다. 배포 로그:

```
=== Deploying to 'tmong-golf-diary'...
i  hosting[tmong-golf-diary]: found 2 files in public
✔  hosting[tmong-golf-diary]: file upload complete
✔  hosting[tmong-golf-diary]: version finalized
✔  hosting[tmong-golf-diary]: release complete
✔  Deploy complete!

Hosting URL: https://tmong-golf-diary.web.app
```

## 6. 이후 참고용 재배포 명령

`public/index.html`, `public/privacy.html`, `firebase.json`을 다시 고칠 때마다
아래 명령으로 재배포할 수 있다 (이번에 로그인은 이미 완료되어 있으므로, 이후에는
`login` 단계 없이 바로 `deploy`만 실행하면 된다 — 단, 다른 환경/새 세션이라면
`login`부터 다시 필요할 수 있다).

```bash
npx firebase-tools deploy --only hosting
```

`public/privacy.html`의 "6. 문의" 섹션은 사용자가 제공한 연락처
(`mygolfdiary01@gmail.com`)로 채워 넣고 재배포까지 완료했다 — Google OAuth
동의 화면 검토를 위한 남은 필수 작업은 없다.

## 7. 전체 테스트 결과

```
$ python3 -m unittest discover -s tests -p 'test*.py'
Ran 508 tests in 29.6s

OK
```

기존 487건 + 신규 Firebase Hosting 검증 21건(문의 이메일 반영 후 1건 추가) =
508건 전체 통과. 신규 테스트는 파일 존재, `firebase.json`/`.firebaserc` 설정값,
페이지 필수 문구(6장 요구 항목 + 문의 이메일), 그리고 로컬 `ThreadingHTTPServer`
(`cleanUrls` 규칙 재현)로 `/`, `/privacy` 두 URL이 실제로 200을 반환하는지까지
검증한다. 실제 Firebase 서버/네트워크 호출은 없었다(배포 자체는 4~5장에서 별도로
수행).
