# 6-42 YouTube Real Upload Validation — 실제 업로드 1건 검증 + 게시 파이프라인

## 결론 요약

| 항목 | 결과 |
|---|---|
| 실제 YouTube 업로드 | **SUCCESS — PRIVATE 1건** |
| video ID | **`RAZ3E4UBj6E`** (https://www.youtube.com/watch?v=RAZ3E4UBj6E — 비공개, 채널 소유자만 볼 수 있음) |
| privacyStatus | **private** (업로드 요청값 + API 재조회 값 일치) |
| processing | `processingDetails.processingStatus` = **succeeded**, `status.uploadStatus` = **processed** |
| publish history | `data/youtube_publish_log.json`에 1건 추가(기존 1건 변경 없음), `processing_status: succeeded` |
| 실제 API 호출 | YouTube만: OAuth 인증 1회, 토큰 교환, videos.insert **1회**, videos.list(상태 조회) |
| Production mutation | 없음 (publish history 추가는 기존 기록 구조를 통한 정상 기록) |
| 테스트 | 1481 tests, failures 0, errors 9(6-41과 같은 사전 존재 Windows 이슈), skipped 17 |

진행은 두 세션으로 나뉘었다.
- **1차 세션**: 이 PC에 인증 정보가 없어 BLOCKED. 업로드 없이 조사, 파이프라인 보강(processing 확인 등), 보호장치 검증을 했다.
- **2차 세션**: 사용자가 Desktop OAuth client를 만들어 준 뒤 로컬 OAuth 인증을 하고, finance Shorts 1건을 PRIVATE로 실제 업로드했다.

client_id, client_secret, refresh_token, access_token 값은 이 문서, 채팅, 코드, git 어디에도 기록하지 않았다.

## 1. 목적

6-41 Shorts V2 중 1건을 PRIVATE로 실제 업로드해
MP4 → OAuth → Upload → Processing → Publish History → TAK AUTO 상태 전체 경로가 작동하는지 검증한다.
PUBLIC 게시는 하지 않는다. 실제 외부 API는 YouTube로 한정하고, 업로드는 1건이다.

## 2. 테스트 MP4

우선순위 1번(finance) 파일이 존재하고 정상이어서 이것을 선택했다. 다른 영상은 올리지 않았다.

```
C:\Users\soppt\tak-auto\artifacts\6-41-shorts-v2\shorts_v2_finance.mp4
```

| 검사 | 결과 |
|---|---|
| exists | YES (28,397,173 bytes, sha256 앞 16자리 `aba5b3a8ffd8665a`) |
| playable | YES — `ffmpeg -v error -i ... -f null -` 전체 디코드 오류 0 |
| 해상도 | 1080×1920 (9:16) |
| video | h264 High, yuv420p, 30fps |
| audio | aac LC, 2ch |
| duration | 36.000초 (Shorts 60초 이하) |

## 3. Renderer 상태

READY. `content_engine/shorts_renderer.py`(6-40)와 `shorts_v2_renderer.py`(6-41)가 존재하고,
Operator Control Center도 renderer를 BLOCKED로 표시하지 않는다.
`content_engine/operator_summary.py`의 오래된 주석("현재 항상 False")만 사실에 맞게 고쳤다(동작 변경 없음).

## 4. Uploader 상태 (기존 구현 그대로 사용, 새 uploader를 만들지 않음)

| # | 항목 | 구현 |
|---|---|---|
| 1 | OAuth 방식 | OAuth 2.0 refresh_token으로 access_token 갱신(`oauth2.googleapis.com/token`), 표준 라이브러리 urllib |
| 2 | 환경변수 | `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN` |
| 3 | upload 함수 | `YouTubeClient.upload_short()` — resumable upload(세션 POST 후 바이너리 PUT), CLI `scripts/upload_youtube_short.py` |
| 4 | metadata | CLI 인자(title 100자 이하, description, tags, categoryId 22), `selfDeclaredMadeForKids=False` |
| 5 | privacyStatus | CLI·클라이언트 기본값 `private`. 6-42부터 public은 `--confirm-public`이 있어야 허용 |
| 6 | upload history | `data/youtube_publish_log.json`(`YouTubeUploadHistory`, atomic 저장) — 업로드 성공 후에만 기록 |
| 7 | duplicate protection | `--content-id`가 있으면 `is_published()`로 dry-run/live 모두 중단 |
| 8 | already published | 7과 같음(`published_content_ids()` 기반) |
| 9 | superseded protection | `--content-id`가 있으면 Production Archive를 다시 확인: approved 여부, `check_content_supersede()`, ShortsScript 존재·일치 |
| 10 | processing status | 원래 **없었음** → 6-42에서 추가(9장) |
| 11 | 실패 시 retry | 없음 — 중복 업로드 위험을 피하는 보수적 설계로 보고 그대로 둠 |
| 12 | 실패 시 history | 실패는 기록하지 않음(성공만 기록). history 저장 실패는 경고로 표시 |
| 13 | 실제 API 호출 로그 | "업로드 중:", "성공: ... (Video ID: ...)", "확인: found/privacy/upload/processing" 출력. 오류는 `_safe_http_error_message()`로 토큰을 빼고 message/code/reason만 출력 |

## 5. OAuth 상태

**1차 세션:** 3개 환경변수가 현재 프로세스, Windows User, Machine 범위 모두 NOT_SET이었고 `.env`도 없어 BLOCKED였다.

**2차 세션 (로컬 OAuth 인증):**

- 입력: 사용자가 Google Cloud에서 만든 **Desktop OAuth client JSON**
  (`%USERPROFILE%\Downloads\client_secret_<client-id>.apps.googleusercontent.com.json`, 유형 `installed`,
  redirect `http://localhost`). 같은 내용의 `(1)` 사본도 있었다(sha256 동일). 구조만 확인하고 값은 출력하지 않았다.
- 새 스크립트 `scripts/youtube_oauth_authorize.py`로 인증했다. 기존 `youtube_oauth_setup.py`는
  "네트워크/브라우저를 쓰지 않는다"는 6-26 보장이 테스트로 고정돼 있어 건드리지 않았다.
  - Google "installed app" 공식 방식: 127.0.0.1 임의 포트의 1회용 로컬 콜백 + **PKCE(S256)** + state 검증,
    `access_type=offline`, `prompt=consent`.
  - 요청 범위: `youtube.upload` + **`youtube.readonly`**(업로드 후 상태 조회용 — 1차 세션에서 찾은 위험을 해소).
  - 사용자가 브라우저에서 Google 계정 로그인과 YouTube 권한 승인을 직접 진행했다.
  - 결과: **인증 성공, 승인된 권한 `youtube.readonly`, `youtube.upload`**.
- 저장: 3개 값을 **Windows 사용자 환경변수(HKCU\Environment)**에 저장했다(winreg 직접 기록, 명령줄 인자로
  값을 넘기지 않음). 기존 `YouTubeClient.from_environment()`가 그대로 읽는다. 저장소 파일과 git에는 아무것도 쓰지 않았다.
- 확인: `youtube_oauth_setup.py --check` → 3개 모두 SET, "API client 초기화 가능: YES".

주의: 사용자 환경변수는 이 Windows 계정의 레지스트리에 평문으로 저장된다(`.env`와 같은 신뢰 수준).
OAuth 동의 화면이 **Testing** 상태이면 Google 정책상 refresh token이 약 7일 후 만료될 수 있다.
만료되면 `youtube_oauth_authorize.py`를 다시 실행하면 된다(19장).

## 6. 실제 upload 결과

실행한 명령은 딱 1회다(인증 정보는 사용자 환경변수에서 프로세스로만 불러옴):

```
py scripts/upload_youtube_short.py --video artifacts/6-41-shorts-v2/shorts_v2_finance.mp4 ^
  --title "대출 받을 때 은행이 먼저 보는 3가지" ^
  --description "티몽의 지혜 — 금융·대출 관련 실무 관점에서 정리한 짧은 정보입니다." ^
  --tags "대출,DSR,금융,티몽의지혜" --privacy private
```

출력:

```
업로드 중: shorts_v2_finance.mp4 (공개 상태: private)...
성공: YouTube Shorts 업로드 완료! (Video ID: RAZ3E4UBj6E)
URL: https://youtu.be/RAZ3E4UBj6E
확인: found=True privacy=private upload=processed processing=succeeded
exit=0
```

실행 직전 `--dry-run`으로 같은 인자를 확인했다. 업로드는 한 번도 재시도하지 않았다.

## 7. video ID

**`RAZ3E4UBj6E`**

- https://www.youtube.com/watch?v=RAZ3E4UBj6E
- https://youtu.be/RAZ3E4UBj6E

PRIVATE이므로 채널 소유자 계정으로 로그인해야 보인다(YouTube Studio → 콘텐츠).

## 8. privacy status

**private** — 업로드 요청값(`--privacy private`, 기본값과 같음)과 업로드 후 `videos.list` 재조회 값
(`status.privacyStatus`)이 같다. PUBLIC 게시는 하지 않았다.

## 9. processing status

업로드 직후 자동 확인과 별도 재조회가 모두 같은 결과를 냈다:

| 필드 | 값 |
|---|---|
| `processingDetails.processingStatus` | **succeeded** |
| `status.uploadStatus` | **processed** |

첫 조회에서 이미 succeeded여서 polling 대기는 없었다.

6-42에서 추가한 단계(1차 세션 구현, 2차 세션에서 실제 작동 확인):
- `YouTubeClient.get_video_status(video_id)` — `videos.list?part=snippet,status,processingDetails`
- `YouTubeClient.wait_for_processing()` — `processing`인 동안만 최대 6회(10초 간격) 조회하고, 끝까지 processing이면
  `WAITING_PROCESSING`으로 기록한다. 무한 polling은 하지 않는다.
- 조회 실패는 업로드 성공을 되돌리지 않고 `UNKNOWN`으로 기록한다. 결과는 history의 `processing_status`에 저장한다.

## 10. metadata

`videos.list`로 다시 조회한 실제 값:

| 필드 | 요청 | YouTube에 저장된 값 |
|---|---|---|
| title | 대출 받을 때 은행이 먼저 보는 3가지 | 대출 받을 때 은행이 먼저 보는 3가지 ✔ |
| description | 티몽의 지혜 — 금융·대출 관련 실무 관점에서 정리한 짧은 정보입니다. | 같음 ✔ |
| privacyStatus | private | private ✔ |
| publishedAt | — | 2026-09-26T01:07:09Z |
| tags | 대출, DSR, 금융, 티몽의지혜 | (조회 part에 포함 안 함) |
| categoryId | 22 (People & Blogs) | — |

제목과 설명은 영상 내용(은행이 먼저 보는 3가지: 상환능력/기존 부채/신용·거래)과 맞고, clickbait 표현은 없다.

## 11. publish history

새 history를 만들지 않고 기존 `data/youtube_publish_log.json`(`YouTubeUploadRecord`) 구조로만 기록했다.
git diff는 **추가 17줄**뿐이고, 기존 기록(`h2X1fFMDffc`, 2026-09-17, 다른 환경에서 한 private 업로드)은 바뀌지 않았다.

```json
{
  "video_id": "RAZ3E4UBj6E",
  "uploaded_at": "2026-09-26T01:07:47.160132+00:00",
  "title": "대출 받을 때 은행이 먼저 보는 3가지",
  "privacy_status": "private",
  "video_path": "artifacts\\6-41-shorts-v2\\shorts_v2_finance.mp4",
  "tags": ["대출", "DSR", "금융", "티몽의지혜"],
  "url": "https://youtu.be/RAZ3E4UBj6E",
  "content_id": "",
  "knowledge_id": "",
  "processing_status": "succeeded"
}
```

`content_id`가 빈 이유: 이 PC에는 `data/tak_media_archive.json`이 없고(fresh 상태), 6-41 Shorts V2는 QA 산출물이라
Production Archive에 없다. `--content-id`를 주면 `ORPHAN`으로 차단된다(정상). Production Archive를 억지로
만들지 않았으므로 이번 업로드는 content_id 없는 **legacy 업로드**다(분류 J).

## 12. duplicate protection

| 경로 | 상태 |
|---|---|
| content_id가 있는 업로드 | **작동** — 격리 fixture로 검증: 업로드 1회 → 같은 content_id dry-run에서 "이미 YouTube 업로드 이력에 있습니다"(ALREADY_PUBLISHED) → live 재실행해도 업로드 호출 수 1회 그대로, history 1건 그대로(`tests/test_6_42_youtube_upload_pipeline.py`) |
| 이번 실제 업로드(`RAZ3E4UBj6E`, content_id 없음) | **적용되지 않음** — `published_content_ids()`는 content_id가 있는 기록만 본다(현재 `set()`). 같은 명령을 다시 실행하면 **두 번째 업로드가 된다** |

두 번째 실제 업로드는 하지 않았다. 이 영상은 **다시 업로드하지 말 것.** 추적이 필요하면
Production Archive/ShortsScript 경로에 정식으로 등록한 뒤 `--content-id/--knowledge-id`로 올려야 한다(19장).

## 13. superseded protection

fixture로 검증: `review_status=superseded, superseded_by=c2` 레코드의 content_id로 업로드를 시도하면
exit 1, "superseded" 차단 메시지, **업로드 호출 0회, history 파일 미생성**.
기존 `test_superseded_downstream_safeguards.py`, `test_youtube_upload_eligibility.py`(시나리오 2/15/17/18),
`test_media_superseded_lifecycle.py`도 모두 통과했다. SUPERSEDED → YouTube upload 경로는 막혀 있다.

## 14. dashboard 상태

`scripts/operator_control_center.py`(READ-ONLY):

| 항목 | 1차(인증 전) | 2차(인증 후) | 실제와 일치? |
|---|---|---|---|
| Renderer | BLOCKED 아님 | BLOCKED 아님 | 일치 |
| YOUTUBE OAUTH | ACTION_REQUIRED | **표시 없음(해결됨)** | 일치 |
| YouTube Shorts(PUBLISH STATUS) | NOT_PRESENT | NOT_PRESENT | Production Archive 기준으로는 일치 |
| Production Archive | NOT_PRESENT | NOT_PRESENT | 일치 |

한계: 대시보드의 게시 상태는 Production 레코드와 history의 content_id로 연결된다. 이번 업로드와 과거 업로드는
content_id가 없어 대시보드의 "YouTube 업로드됨"에 나타나지 않는다. 설계대로이며 코드는 바꾸지 않았다.
`run_scout_dashboard.py`도 approved와 "YouTube 업로드됨"을 별도 상태로 판정한다.

## 15. publish readiness

- 상태는 섞이지 않는다: Production `review_status == "approved"`(승인)와 YouTube history 존재(게시됨)는 따로 판정된다.
- 6-41 finance Shorts는 Production Archive에 없어서 content_id 기반 경로에서는 ORPHAN(업로드 불가)이다.
  legacy 업로드로 올라간 사실은 history에만 있다 — "APPROVED"로도, content_id 기준 "PUBLISHED"로도 표시되지 않는다.

## 16. API project verification 상태

- YouTube Data API 공식 문서(`videos` 리소스): "2020년 7월 28일 이후 생성된 **검증되지 않은 API 프로젝트**에서
  `videos.insert`로 올린 영상은 private 보기 모드로 제한된다." 공개 업로드를 하려면 감사(audit)를 받아야 한다.
- 이번 OAuth client는 방금 만든 프로젝트이고 동의 화면은 검증 전(Testing) 상태로 보인다. PRIVATE 업로드는
  정상 작동했다. PUBLIC 가능 여부는 확인하지 않았고, 검증 우회도 시도하지 않았다.

## 17. 실패/문제

| 분류 | 내용 | 상태 |
|---|---|---|
| A. OAuth credentials | 1차 세션에서 이 PC에 인증 정보 없음 | **해결**(로컬 OAuth 인증) |
| B. API 권한 | `youtube.upload` 범위만으로는 상태 조회가 안 될 수 있었음 | **해결**(`youtube.readonly` 추가 승인, 실제 조회 성공) |
| E. uploader 코드 | 업로드 후 processing 확인 단계가 없었음 | **해결**(추가, 실제 작동 확인) |
| J. Production 데이터 부재 | Production Archive 없음 → legacy 업로드, content_id 중복 방지 미적용 | **남음**(12장) |
| 안전 | `--privacy public`을 추가 확인 없이 쓸 수 있었음 | **해결**(`--confirm-public` 필수) |
| 운영 | Testing 상태 OAuth는 refresh token이 약 7일 뒤 만료될 수 있음 | **남음**(19장) |

## 18. 수정 사항

| 파일 | 변경 | 세션 |
|---|---|---|
| `content_engine/youtube_publisher.py` | `_default_status_transport`, `YouTubeVideoStatus`, `get_video_status()`, `wait_for_processing()`(횟수 제한), `WAITING_PROCESSING`/`STATUS_UNKNOWN` | 1차 |
| `content_engine/youtube_upload_history.py` | `YouTubeUploadRecord.processing_status` 선택 필드 | 1차 |
| `scripts/upload_youtube_short.py` | 업로드 후 상태 확인(best-effort), 제목/공개 상태 불일치 경고, `--skip-status-check`, public은 `--confirm-public` 필수 | 1차 |
| `content_engine/operator_summary.py` | 오래된 주석 1줄 | 1차 |
| `tests/test_upload_youtube_short_cli.py` | 가짜 클라이언트에 네트워크 없는 `wait_for_processing()` 추가 | 1차 |
| `tests/test_6_42_youtube_upload_pipeline.py` | 신규 10 tests | 1차 |
| `scripts/youtube_oauth_authorize.py` | **신규** — Desktop client JSON으로 로컬 OAuth(PKCE/state/loopback), 사용자 환경변수 저장, 값 미출력 | 2차 |
| `tests/test_youtube_oauth_authorize.py` | **신규 6 tests** — PKCE/offline/scope URL, state 불일치·거부 차단, refresh_token 필수, web 유형 거부, 127.0.0.1 콜백 전체 흐름(값 미출력 확인), 시간 초과 시 저장 안 함 | 2차 |
| `data/youtube_publish_log.json` | 실제 업로드 기록 1건 추가(기존 기록 유지) | 2차 |

기본 공개 상태는 원래 정책대로 private이다. 테스트는 실제 API를 호출하지 않는다(가짜 transport, urlopen 차단,
로컬 127.0.0.1 콜백만 사용).

### 테스트 결과

| 실행 | 결과 |
|---|---|
| `test_youtube_oauth_authorize` + `test_youtube_oauth_setup` | 16 OK |
| `test_6_42_youtube_upload_pipeline` | 10 OK |
| YouTube 관련 7개 파일(upload CLI/eligibility/history dedup·content_id/oauth setup/performance) | 56 OK |
| 전체 회귀 `py -m unittest discover -s tests` | **1481 tests, failures 0, errors 9, skipped 17** |

errors 9는 6-38~6-41에서 기록한 것과 같은 사전 존재 Windows 이슈다(`subprocess.run(capture_output=True)`의
`stdout=None`): test_content_engine 1, test_knowledge_review 1, test_media_batch 2, test_media_viewer 1,
test_run_scout_cli 1, test_threads_publisher 3. 6-41에서 깨끗한 HEAD worktree로도 재현됨을 확인했다.
기존 테스트를 지우거나 skip하지 않았다.

### Production 보호

| 항목 | 결과 |
|---|---|
| `data/tak_media_archive.json` | 전후 모두 없음(만들지 않음) |
| `data/tak_threads_pending.json` | 해시 `c9a51eae8ca1b1dc` 전후 동일 |
| `data/threads_publish_log.json` | 해시 `5e7eeede28dc8599` 전후 동일 |
| `data/youtube_publish_log.json` | 기존 기록 유지 + 이번 업로드 1건 추가(정상 publish history 기록) |
| 기타 data/*.json | 해시 전후 동일 |
| performance/recovery 데이터 | 해당 파일 없음, 만들지 않음 |
| Threads/TikTok/Instagram/Naver/기타 API | 호출 없음 |
| 다른 영상 업로드 | 없음(finance 1건만) |
| secret/token 출력·기록 | 없음(SET/NOT_SET만 확인) |

## 19. 다음 단계

1. **YouTube Studio에서 직접 확인**: 채널 소유자 계정 → 콘텐츠 → "대출 받을 때 은행이 먼저 보는 3가지"(비공개).
   화질, 소리, 제목/설명, Shorts로 분류됐는지 확인한다.
2. **이 영상은 다시 올리지 말 것** — content_id가 없어 CLI가 중복을 막지 못한다(12장).
3. refresh token이 만료되면(Testing 상태는 약 7일) 다시 인증한다:
   ```
   py scripts/youtube_oauth_authorize.py --client-secrets "%USERPROFILE%\Downloads\client_secret_<client-id>.apps.googleusercontent.com.json"
   ```
   오래 운영하려면 OAuth 동의 화면을 "프로덕션"으로 전환하는 것을 검토한다.
4. 새로 여는 터미널은 사용자 환경변수를 자동으로 읽는다. 이미 열려 있던 터미널에서는 다시 열어야 적용된다.
5. Shorts V2를 content_id로 추적하려면 먼저 Production Archive/ShortsScript에 정식 등록해야 한다.
   그 뒤부터 `--content-id/--knowledge-id` 업로드로 중복 방지와 대시보드 연결이 적용된다.
6. 운영자가 실제 결과에 만족한 뒤에 "PUBLIC 자동 게시를 허용할 것인가"를 정한다. 그 전에 API 프로젝트 감사
   상태를 확인해야 한다(16장). 이번 작업에서는 PUBLIC 게시를 하지 않았다.
