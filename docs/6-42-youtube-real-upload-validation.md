# 6-42 YouTube Real Upload Validation — 실제 업로드 1건 검증 + 게시 파이프라인

## 결론 요약

| 항목 | 결과 |
|---|---|
| 실제 YouTube 업로드 | **BLOCKED** — 이 PC에 `YOUTUBE_CLIENT_ID` / `YOUTUBE_CLIENT_SECRET` / `YOUTUBE_REFRESH_TOKEN`이 전부 **NOT_SET** |
| 실제 API 호출 | **0건** (OAuth 토큰 요청도 없음 — `from_environment()`에서 네트워크 전에 중단) |
| video ID | none |
| 실패 분류 | **A. OAuth credentials 문제**(이 PC에 인증 정보 없음) + I. 환경 문제 |
| 파이프라인 보강 | 업로드 후 processing 상태 조회(bounded polling), history에 processing_status 기록, PUBLIC 명시 확인 가드 |
| Production mutation | 없음 |
| 테스트 | 1475 tests, failures 0, errors 9(사전 존재 Windows 이슈, 6-41과 동일 9건), skipped 17 |

지시 3장("NOT_SET이면 실제 업로드를 시도하지 말고 BLOCKED로 종료")에 따라 업로드는 하지 않았다.
업로드를 제외한 조사, MP4 검증, dry-run, 보호장치 검증, 빠져 있던 processing 확인 단계 보강,
테스트, 문서화는 진행했다. 인증 정보만 설정되면 바로 실행할 수 있는 명령은 19장에 있다.

## 1. 목적

6-41 Shorts V2 중 1건을 PRIVATE로 실제 업로드해
MP4 → OAuth → Upload → Processing → Publish History → TAK AUTO 상태 전체 경로를 검증한다.
PUBLIC 게시는 하지 않는다. 실제 외부 API는 YouTube로 한정하고, 업로드는 최대 1건이다.

## 2. 테스트 MP4

우선순위 1번(finance)이 존재하고 정상이어서 이 파일을 선택했다.

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

READY. `content_engine/shorts_renderer.py`(6-40) + `shorts_v2_renderer.py`(6-41)가 존재한다.
Operator Control Center도 renderer를 BLOCKED로 표시하지 않는다(14장).
`content_engine/operator_summary.py`의 오래된 주석("현재 항상 False")만 사실에 맞게 고쳤다(동작 변경 없음).

## 4. Uploader 상태 (기존 구현 그대로 사용, 새 uploader 만들지 않음)

| # | 항목 | 현재 구현 |
|---|---|---|
| 1 | OAuth 방식 | OAuth 2.0 refresh_token → access_token 갱신(`oauth2.googleapis.com/token`), 표준 라이브러리 urllib만 사용 |
| 2 | 환경변수 | `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN` |
| 3 | upload 함수 | `YouTubeClient.upload_short()` → resumable upload(세션 POST → 바이너리 PUT), `scripts/upload_youtube_short.py` CLI |
| 4 | metadata | CLI 인자(title ≤100자, description, tags, categoryId 22), `selfDeclaredMadeForKids=False` |
| 5 | privacyStatus | CLI 기본값 `private`, 클라이언트 기본값 `private`. 6-42에서 public은 `--confirm-public` 필수로 변경 |
| 6 | upload history | `data/youtube_publish_log.json`(`YouTubeUploadHistory`, atomic 저장) — 업로드 성공 후에만 기록 |
| 7 | duplicate protection | `--content-id`가 있으면 `is_published()`로 dry-run/live 모두 중단 |
| 8 | already published | 동일(`published_content_ids()` 기반) |
| 9 | superseded protection | `--content-id`가 있으면 Production Archive 재확인: approved 여부, `check_content_supersede()`, ShortsScript 존재·일치 |
| 10 | processing status | **없었음** → 6-42에서 추가(7장) |
| 11 | 실패 시 retry | 없음(업로드 재시도 없음 — 중복 업로드 위험을 피하는 보수적 설계로 보고 그대로 둠) |
| 12 | 실패 시 history | 실패는 기록하지 않음(성공만 기록). history 저장 실패는 경고로 표시 |
| 13 | 실제 API 호출 로그 | "업로드 중:", "성공: ... (Video ID: ...)" 출력. 오류 메시지는 `_safe_http_error_message()`로 토큰을 제외한 message/code/reason만 출력 |

참고 사실: `data/youtube_publish_log.json`에는 이미 **다른 환경에서 수행된 실제 private 업로드 1건**이 있다
(`h2X1fFMDffc`, 2026-09-17T07:49:11Z, "TAK AUTO 업로드 테스트 (private)", content_id 없음).
즉 업로드 코드 경로는 인증 정보가 있는 기기에서 이미 한 번 작동했다. 이번 세션에서 이 기록은 읽기만 했다.

## 5. OAuth 상태

값은 출력하지 않고 존재 여부만 확인했다(현재 프로세스, Windows User, Machine 범위 전부).

| 변수 | 상태 |
|---|---|
| YOUTUBE_CLIENT_ID | NOT_SET |
| YOUTUBE_CLIENT_SECRET | NOT_SET |
| YOUTUBE_REFRESH_TOKEN | NOT_SET |

- 저장소 루트에 `.env` 없음. 기존 `scripts/youtube_oauth_setup.py --check`도 3개 모두 MISSING(exit 1).
- 이 저장소의 OAuth 안내 범위(scope)는 `https://www.googleapis.com/auth/youtube.upload` 하나다.

## 6. 실제 upload 결과

**BLOCKED — 업로드하지 않음.**

- `--dry-run`: 정상(파일/제목/설명/태그/private 확인, 네트워크 없음, history 미기록).
- `--dry-run` 없이 실행: `설정 오류: 다음 환경변수가 필요합니다: YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN`
  → exit 1. `from_environment()`에서 멈추므로 **토큰 요청을 포함한 어떤 네트워크 호출도 일어나지 않는 경로**다.
  실행 전후 `data/youtube_publish_log.json` 해시 동일(`15682f1c710883be`).

## 7. video ID

none (업로드 미수행).

## 8. privacy status

해당 없음(업로드 미수행). 예정 값은 **private**(CLI/클라이언트 기본값, dry-run 출력으로 확인).

## 9. processing status

해당 없음(업로드 미수행). 대신 기존 uploader에 **없던 단계를 추가**했다:

- `YouTubeClient.get_video_status(video_id)` — `videos.list?part=snippet,status,processingDetails`
  → `YouTubeVideoStatus`(found/title/description/privacy_status/upload_status/processing_status/published_at).
- `YouTubeClient.wait_for_processing(video_id, attempts=6, interval_seconds=10)` — `processing`인 동안만
  최대 6회(최대 약 50초) 조회. 끝까지 `processing`이면 **`WAITING_PROCESSING`**. 무한 polling 없음.
- CLI는 업로드 성공 직후 이를 실행해 `found/privacy/upload/processing`을 출력하고, 제목·공개 상태가
  요청과 다르면 경고한다. 결과는 history의 새 선택 필드 `processing_status`에 저장한다.
- 상태 조회가 실패해도(권한/네트워크) **업로드 성공은 되돌리지 않고** `UNKNOWN`으로 기록한다.
- `--skip-status-check`로 건너뛸 수 있다.

공식 값(YouTube Data API `videos` 리소스 문서 확인): `processingDetails.processingStatus` =
processing / succeeded / failed / terminated, `status.uploadStatus` = uploaded / processed / rejected / failed / deleted.
`processingDetails`는 영상 소유자에게만 반환된다.

**미확인 위험:** 현재 안내된 OAuth 범위는 `youtube.upload` 하나다. 이 범위만으로 `videos.list`
(상태 조회)가 허용되는지는 공식 문서에서 명확히 확인하지 못했다. 거부되면(예: 403
insufficientPermissions) 업로드는 성공하고 processing_status는 `UNKNOWN`으로 기록된다 — 이 경우
`youtube.readonly` 범위를 추가로 받아야 한다(분류 B). 6-01 성과 수집(`get_video_statistics`)도 같은 문제를 가질 수 있다.

## 10. metadata

예정 metadata(dry-run으로 확인, 영상 내용과 일치, clickbait 없음):

| 필드 | 값 |
|---|---|
| title | 대출 받을 때 은행이 먼저 보는 3가지 |
| description | 티몽의 지혜 — 금융·대출 관련 실무 관점에서 정리한 짧은 정보입니다. |
| tags | 대출, DSR, 금융, 티몽의지혜 |
| categoryId | 22 (People & Blogs) |
| privacyStatus | private |
| selfDeclaredMadeForKids | false |

업로드 후 재조회 검증(title/description/privacyStatus/publishedAt/processingStatus)은 9장의 새 단계가
자동으로 수행하도록 준비됐다.

## 11. publish history

- 새 별도 history를 만들지 않고 기존 `data/youtube_publish_log.json`(`YouTubeUploadRecord`)을 그대로 쓴다.
- 필드: video_id, uploaded_at(UTC), title, privacy_status, video_path, tags, url, content_id, knowledge_id,
  **processing_status(6-42 추가, 선택 필드 — 과거 기록은 빈 값으로 두고 채우지 않음)**.
- 이번 세션에서 이 파일은 변경되지 않았다.
- **중요한 발견(J. Production 데이터 부재):** 이 PC에는 `data/tak_media_archive.json`이 없다(fresh 상태).
  6-41 Shorts V2는 QA 산출물이라 Production Archive에 없고, `--content-id shorts-v2-finance`로
  dry-run하면 `차단: ... production archive에 이 레코드가 없습니다(ORPHAN)`가 나온다(정상 동작).
  따라서 지금 이 영상을 올리려면 content_id 없는 **legacy 업로드**가 되고, 그 경우 history에
  content_id가 없어 `is_published()` 중복 방지가 적용되지 않는다. Production Archive를 억지로 만들지 않았다.

## 12. duplicate protection

실제 API 없이 격리 fixture(tempdir)로 검증했다(`tests/test_6_42_youtube_upload_pipeline.py`):

1. approved Production 레코드 + ShortsScript fixture → 가짜 클라이언트로 live 업로드 1회 → history 1건.
2. 같은 content_id `--dry-run` → "이미 YouTube 업로드 이력에 있습니다. 다시 업로드하지 않습니다." (= ALREADY_PUBLISHED)
3. 같은 content_id live 재실행 → 업로드 호출 수 1회 그대로, history 1건 그대로.

기존 `test_youtube_upload_history_dedup.py`(5), `test_upload_youtube_short_cli.py` idempotency 테스트도 통과.
두 번째 실제 API 업로드는 없음(실제 업로드 자체가 0건).

## 13. superseded protection

fixture로 검증: `review_status=superseded, superseded_by=c2` 레코드의 content_id로 업로드 시도 →
exit 1, "superseded" 차단 메시지, **업로드 호출 0회, history 파일 미생성**.
기존 `test_superseded_downstream_safeguards.py`, `test_youtube_upload_eligibility.py`(시나리오 2/15/17/18),
`test_media_superseded_lifecycle.py` 모두 통과. SUPERSEDED → YouTube upload 경로는 막혀 있다.

## 14. dashboard 상태

`scripts/operator_control_center.py`(READ-ONLY, 파일을 쓰지 않음) 실제 실행 결과:

| 항목 | 표시 | 실제와 일치? |
|---|---|---|
| Renderer | BLOCKED로 표시되지 않음(renderer 존재) | 일치 |
| YOUTUBE OAUTH | ACTION_REQUIRED — "YouTube OAuth 환경변수가 설정되지 않았습니다." / ACTION `python scripts/youtube_oauth_setup.py --check` | 일치 |
| YouTube Shorts(PUBLISH STATUS) | NOT_PRESENT | 일치(Production Archive 없음) |
| Production Archive | NOT_PRESENT | 일치 |

- 과거 legacy 업로드(h2X1fFMDffc)는 content_id가 없어 대시보드의 콘텐츠별 상태에 연결되지 않는다 — 설계대로다.
- `run_scout_dashboard.py`는 approved와 "YouTube 업로드됨"을 별도 상태로 표시한다(history의 content_id로만 판정).

## 15. publish readiness

- 상태는 섞이지 않는다: Production `review_status == "approved"`(승인)와 YouTube history 존재(게시됨)는
  별개로 판정된다. approved라도 history가 없으면 업로드 대상, history에 content_id가 있으면 ALREADY_PUBLISHED.
- 6-41 finance Shorts: Production Archive에 없음 → content_id 기반 업로드는 ORPHAN으로 차단(정상).

## 16. API project verification 상태

- YouTube Data API 공식 문서(`videos` 리소스): "2020년 7월 28일 이후 생성된 **검증되지 않은 API 프로젝트**에서
  `videos.insert`로 올린 영상은 private 보기 모드로 제한된다." 공개 업로드는 감사(audit)를 거쳐야 한다.
- 이번에는 API를 호출하지 않았으므로 프로젝트 검증 여부는 **확인 불가**. PRIVATE 테스트는 이 제한과
  무관하게 정상적인 안전장치다. 검증 우회는 시도하지 않았다.

## 17. 실패/문제

| 분류 | 내용 |
|---|---|
| A. OAuth credentials | **원인.** 이 PC에 YouTube 인증 정보 3개 모두 없음 → BLOCKED |
| B. API 권한(잠재) | 안내된 scope가 `youtube.upload`뿐 — 상태 조회(`videos.list`)가 거부될 수 있음(9장) |
| E. uploader 코드 | 업로드 후 processing 확인 단계가 없었음 → 추가 |
| J. Production 데이터 부재 | Production Archive 없음 → Shorts V2는 content_id 없는 legacy 업로드만 가능, 그 경우 중복 방지가 적용되지 않음 |
| 안전 | CLI에서 `--privacy public`을 추가 확인 없이 쓸 수 있었음 → `--confirm-public` 요구로 변경 |

## 18. 수정 사항

| 파일 | 변경 |
|---|---|
| `content_engine/youtube_publisher.py` | `_default_status_transport`, `YouTubeVideoStatus`, `get_video_status()`, `wait_for_processing()`(bounded), `WAITING_PROCESSING`/`STATUS_UNKNOWN` 상수. 기존 upload/stats 경로 변경 없음 |
| `content_engine/youtube_upload_history.py` | `YouTubeUploadRecord.processing_status` 선택 필드(기본 "") |
| `scripts/upload_youtube_short.py` | 업로드 후 상태 확인 + 제목/공개 상태 불일치 경고 + history 기록(best-effort, 실패해도 업로드 결과 유지), `--skip-status-check`, `--privacy public`은 `--confirm-public` 필수 |
| `content_engine/operator_summary.py` | 오래된 주석 1줄 수정(동작 변경 없음) |
| `tests/test_upload_youtube_short_cli.py` | 가짜 클라이언트에 네트워크 없는 `wait_for_processing()` 추가(기존 단언 변경 없음) |
| `tests/test_6_42_youtube_upload_pipeline.py` | 신규 10 tests — 상태 파싱, bounded polling, public 가드, private 기본값, processing_status 기록, 상태 조회 실패 시 UNKNOWN, 업로드 후 ALREADY_PUBLISHED, SUPERSEDED 차단. urlopen을 막아 실제 네트워크 호출 시 실패 |

기본 공개 상태 private은 원래 정책 그대로다. 테스트 suite는 실제 API를 호출하지 않는다.

### 테스트 결과

| 실행 | 결과 |
|---|---|
| 신규 `test_6_42_youtube_upload_pipeline` | 10 OK |
| YouTube 관련 7개 파일(upload CLI/eligibility/history dedup·content_id/oauth setup/performance) | 56 OK |
| 전체 회귀 `py -m unittest discover -s tests` | **1475 tests, failures 0, errors 9, skipped 17** |

errors 9는 6-38~6-41에서 기록한 것과 같은 사전 존재 Windows 이슈다(`subprocess.run(capture_output=True)`의
`stdout=None`): test_content_engine 1, test_knowledge_review 1, test_media_batch 2, test_media_viewer 1,
test_run_scout_cli 1, test_threads_publisher 3. 6-41에서 깨끗한 HEAD worktree로 재현 확인했다.
작업 중 기존 가짜 클라이언트(Mock)와의 호환 문제로 일시적으로 errors 15/12가 났고, 상태 조회를
best-effort(기능 없는 클라이언트는 건너뛰고, `YouTubeVideoStatus`가 아닌 결과는 UNKNOWN 처리)로
바꿔 해결했다. 기존 테스트 삭제/skip 없음.

### Production 보호

| 항목 | 결과 |
|---|---|
| `data/tak_media_archive.json` | 작업 전후 모두 없음(생성하지 않음) |
| `data/tak_threads_pending.json` | 해시 `c9a51eae8ca1b1dc` 전후 동일 |
| `data/youtube_publish_log.json` | 해시 `15682f1c710883be` 전후 동일 |
| `data/threads_publish_log.json` | 해시 `5e7eeede28dc8599` 전후 동일 |
| performance/recovery 데이터 | 해당 파일 없음, 생성하지 않음 |
| Threads/TikTok/Instagram/Naver/기타 API | 호출 없음 |
| secret/token 출력·기록 | 없음(SET/NOT_SET만 확인) |

외부 접속은 YouTube 공식 개발자 문서 열람(WebFetch)뿐이다 — API 호출이 아니다.

## 19. 다음 단계

1. **인증 정보가 있는 기기에서 업로드 1건 실행** — 과거 업로드(h2X1fFMDffc)를 한 기기, 또는 이 PC에
   OAuth를 설정한다(`python scripts/youtube_oauth_setup.py` 안내 참고, `.env`는 gitignore됨).
   가능하면 상태 조회를 위해 `youtube.readonly` 범위도 함께 받는다.
2. 준비된 명령(PRIVATE, 1건, content_id 없는 legacy 업로드 — 중복 방지가 적용되지 않으므로 **한 번만** 실행):
   ```
   py scripts/upload_youtube_short.py ^
     --video "C:\Users\soppt\tak-auto\artifacts\6-41-shorts-v2\shorts_v2_finance.mp4" ^
     --title "대출 받을 때 은행이 먼저 보는 3가지" ^
     --description "티몽의 지혜 — 금융·대출 관련 실무 관점에서 정리한 짧은 정보입니다." ^
     --tags "대출,DSR,금융,티몽의지혜" --privacy private
   ```
   출력에서 video ID와 `확인: found=... privacy=private ... processing=...`를 확인한다.
3. YouTube Studio에서 채널 소유자로 영상, 제목, 설명, private 상태를 확인한다.
4. Shorts V2를 content_id로 추적하려면 먼저 Production Archive/ShortsScript 경로에 정식으로 올려야 한다
   (현재는 QA 산출물). 그 다음부터 `--content-id/--knowledge-id` 업로드로 중복 방지가 적용된다.
5. 운영자가 결과에 만족한 뒤에 "PUBLIC 자동 게시를 허용할 것인가"를 결정한다. 그 전에 API 프로젝트
   검증(audit) 상태를 확인해야 한다(16장). 이번 작업에서는 PUBLIC 게시를 하지 않았다.
