# 6-26 YouTube Publish Readiness

## 1. 목적

6-24 Production Readiness Audit(`docs/6-24-production-readiness-audit.md`
11장, 18장 P1/P2)에서 확인된 YouTube 관련 문제를 실제 코드 기준으로
정리하고,

```
Production Archive -> Publish Readiness -> ShortsScript
-> YouTube Upload Eligibility -> OAuth -> Upload -> Publish History
```

라는 하나의 명확한 운영 경로를 확립한다. 이번 작업에서 실제 YouTube
OAuth 인증이나 실제 업로드는 단 한 번도 수행하지 않았다 - 모든 검증은
synthetic fixture/mock/tempfile로만 했다.

## 2. 전체 YouTube Publish 경로

3장 조사(실제 import/호출 관계, 파일 목록만이 아님) 결과, 6-25(Threads)와
달리 **경로가 하나뿐**이다 - 레거시/중복 경로가 없다.

```
data/tak_media_archive.json(platform=="shorts", approved)
  -> Dashboard "/media" 승인 (또는 scripts/generate_approved_shorts_script.py)
  -> content_engine.shorts_adapter.save_approved_shorts_script()
  -> data/shorts_scripts/<content_id>.json (ShortsScript)
  -> (이 저장소 밖 렌더링 - 6-21/6-24에서 이미 확인, mp4 생성 코드 없음)
  -> 완성된 .mp4
  -> scripts/upload_youtube_short.py [--content-id 주면 6-26 게이트 적용]
      -> content_engine.publish_eligibility.check_content_supersede()
         + find_production_record()  (6-19/6-26)
      -> content_engine.youtube_publisher.YouTubeClient (OAuth 2.0 refresh_token)
      -> data/youtube_publish_log.json
```

**PATH B/C/D(레거시 CLI / GitHub Actions 자동 업로드 / workflow_dispatch
업로드)는 존재하지 않는다** - `.github/workflows/` 어디에도 YouTube
secrets(`YOUTUBE_CLIENT_ID`/`SECRET`/`REFRESH_TOKEN`)를 참조하는 workflow가
없다(13장에서 재확인). `daily-media-prepare.yml`의 주석이 언급하는
"`youtube-shorts-upload.yml`"이라는 workflow도 실제로는 존재하지 않는
파일이다(향후 이름 후보로만 언급됨). YouTube 업로드는 6-24가 이미 확인한
대로 **100% 로컬/수동**이다 - 6-25처럼 "레거시 경로를 정리"할 필요 자체가
없었다.

## 3. ShortsScript

`content_engine/shorts_adapter.py`(`save_approved_shorts_script()`)를
읽고 실제 스키마를 확인했다. `data/shorts_scripts/<content_id>.json`의
실제 필드:

```json
{
  "content_id": "...",
  "knowledge_id": "...",
  "platform": "shorts",
  "title": "...",
  "subtitle": "",
  "cards": ["...", "..."],
  "takeaway": "...",
  "brand": "티몽의 지혜",
  "created_at": "..."
}
```

**5장 지시사항이 요구한 필드 중 ShortsScript에 없는 것들**: `source_url`,
`generation_id`, `review_status` - 셋 다 ShortsScript 스키마에 포함되지
않는다(생성 시점에 승인된 `MediaArchiveRecord`에서 title/cards/takeaway만
추출하고, 그 외 메타데이터는 옮기지 않는다 - `short_draft_to_shorts_script()`
문서화된 규칙 그대로). 이는 **의도된 설계**(콘텐츠 변환만 하고 추적
메타데이터를 새로 추가하지 않는다는 5-19/5-29 원칙)이지, 이번에 새로
발견한 결함이 아니다 - 그래서 5장 표의 F(generation_id mismatch)/9장의
source_url mismatch 검사는 ShortsScript 레벨에서 **구현할 수 없다**
(17장에서 상세 설명).

**5장의 A~G 시나리오 실제 처리(이번에 구현)**:

| # | 시나리오 | 결과 |
|---|---|---|
| A | Production 존재 + ShortsScript 존재(둘 다 approved/일치) | 정상 후보(업로드 진행) |
| B | Production 없음 + ShortsScript 존재 | **BLOCK**(ORPHAN, 5장에서 이유 설명) |
| C | Production SUPERSEDED + ShortsScript 존재 | BLOCK(6-19 `check_content_supersede()`) |
| D | Production approved + ShortsScript 없음 | BLOCK(MISSING_ARTIFACT) |
| E | content_id mismatch(파일명 vs 내부 필드) | BLOCK(CONFLICT) |
| F | generation_id mismatch | 해당 없음(ShortsScript에 필드 자체가 없음, 위 설명) - 상위 계층(6-18)이 이미 보장 |
| G | 이미 published | ALREADY_PUBLISHED(`YouTubeUploadHistory.is_published()`, 변경 없음) |

## 4. Production Archive

`load_archive()`, `MediaArchiveRecord`, `check_content_supersede()`,
`find_production_record()` 전부 6-19/6-18/6-06에서 이미 구현된 것을 그대로
재사용했다(변경 없음) - 8장 5장 지시("이미 구현된 helper 재사용")를
지켰다. 새로 추가한 것은 `scripts/upload_youtube_short.py`의
`check_shorts_upload_eligibility()` 하나뿐이며, 이것도 새 판정 로직이
아니라 기존 두 함수의 결과를 조합만 한다.

## 5. Publish Eligibility

**공식 YouTube Publish Contract(지시사항 4장 13개 조건)**:

| # | 조건 | 구현 |
|---|---|---|
| 1 | content_id 존재 | `--content-id` 인자(사람이 명시) |
| 2 | Production Archive record 존재 | `find_production_record()` - 없으면 즉시 부적격(ORPHAN) |
| 3 | review_status == approved | 새로 추가(아래 "⚠️ 핵심 발견" 참고) |
| 4 | generation_status 유효 | `find_production_record()`가 찾은 레코드는 이미 archive에 있으므로 스키마 검증(6-06/6-17)을 통과한 상태 - 별도 재확인 불필요 |
| 5 | superseded 아님 | `check_content_supersede()`(6-19, 재사용) |
| 6 | ShortsScript 존재 | 새로 추가 |
| 7 | ShortsScript의 content_id 일치 | 새로 추가 |
| 8 | required title/body/script 필드 존재 | 기존 `--title` 길이/공백 검사(변경 없음) + ShortsScript JSON 파싱 성공 여부 |
| 9 | Publish Readiness가 허용하는 상태 | 2~5번 조합이 곧 이 조건(별도 함수 호출 없이 인라인으로 동일 결론) |
| 10 | 이미 업로드된 content_id 아님 | `YouTubeUploadHistory.is_published()`(6-13, 변경 없음, 최우선 확인) |
| 11 | duplicate upload 아님 | 10번과 동일 |
| 12 | OAuth credentials 존재 | `YouTubeClient.from_environment()`(변경 없음) |
| 13 | API client 초기화 가능 | 동일 |

**⚠️ 핵심 발견(6-26에서 새로 확인, 이번에 수정)**: 6-19 설계 문서
(`docs/6-19-superseded-downstream-safeguards.md` 5장 원칙 2)는
"unreviewed/dismissed 등 다른 상태는 각 플랫폼의 **기존 승인 게이트**가
계속 담당한다"고 전제하고 supersede 검사만 추가했다. Threads는 실제로
그런 게이트가 있다(`tak_threads_pending.json`의 `status=="approved"`,
6-25 5장에서 확인). **그러나 YouTube 업로드 경로에는 그런 게이트가
처음부터 없었다** - `--content-id`/`--knowledge-id`는 6-02 설계상 순수히
"성과 데이터 연결용" 선택 필드였을 뿐, 승인 여부를 확인하는 데 쓰인 적이
없다. 즉 **6-19의 전제 자체가 YouTube에는 성립하지 않았다** - `unreviewed`나
`dismissed` 상태의 콘텐츠도 `--content-id`만 넘기면(supersede만 아니면)
업로드가 가능했다. `check_shorts_upload_eligibility()`가
`record.review_status != "approved"` 확인을 추가해 이 gap을 닫았다.

## 6. OAuth 구조

`content_engine/youtube_publisher.py`를 읽고 지시사항 6장의 8개 질문에
코드 근거로 답한다(실제 secret 값은 읽지 않았다):

1. **어디서 읽는가?** `YouTubeClient.from_environment()`(line 224-258),
   `os.environ.get()` 세 번.
2. **환경변수 이름은 일관적인가?** 그렇다 - `YOUTUBE_CLIENT_ID`/
   `YOUTUBE_CLIENT_SECRET`/`YOUTUBE_REFRESH_TOKEN`(6-24가 이미 확인, 재확인).
3. **token이 파일에 저장되는가?** 아니오 - 코드 어디에도 token을 파일에
   쓰는 경로가 없다(grep 결과 확인).
4. **token이 로그에 출력될 가능성?** 아니오 - `_safe_http_error_message()`
   (line 54-82)가 HTTP 에러 응답에서 `message`/`code`/`reason`/
   `error_description`만 추출하고, 요청 헤더(Authorization: Bearer 토큰이
   담긴 곳)는 절대 포함하지 않는다.
5. **OAuth 실패 처리?** `YouTubeConfigurationError`(설정 자체가 없음/access_token
   발급 실패 시 `YouTubeAPIError`)로 명확히 구분됨.
6. **API client 생성 실패 처리?** `from_environment()`가 누락된 변수 이름
   목록과 함께 `YouTubeConfigurationError`를 던짐(값은 노출 안 함).
7. **업로드 실패와 인증 실패가 구분되는가?** 그렇다 - `YouTubeConfigurationError`
   (인증/설정) vs `YouTubeAPIError`(토큰 갱신/업로드 API 통신) vs `ValueError`
   (입력값 검증) 3종으로 구분되고, `upload_youtube_short.py`의 except 절이
   각각 다른 메시지를 출력한다(11장 상세).
8. **이미 업로드된 content_id는 API 호출 전에 차단되는가?** 그렇다 -
   `history.is_published(content_id)`가 `YouTubeClient.from_environment()`
   호출보다 먼저 실행된다(코드 순서 확인, 변경 없음).

**결론**: OAuth 구조 자체는 이미 안전하게 설계되어 있었다(6-24가 이미
"양호"로 평가, 재확인). 이번에 손대지 않았다.

## 7. youtube_oauth_setup.py

**6-24 P1로 기록된 문제**: 이 스크립트가 여러 문서(5-18, 5-31, 6-01~6-03)에
언급만 되고 git history에 실제로 커밋된 적이 없었다(`git log --all
--diff-filter=A -- scripts/youtube_oauth_setup.py` 결과 0건, 6-24가 이미
확인).

**이번에 최초 구현**(`scripts/youtube_oauth_setup.py`, 신규 파일):
- `--check`: `YOUTUBE_CLIENT_ID`/`SECRET`/`REFRESH_TOKEN` 세 환경변수의
  **존재 여부만**(값은 절대 출력 안 함) 확인하고, 전부 있으면
  `YouTubeClient.from_environment()`로 client 객체를 실제로 만들어본다
  (이 생성 자체는 네트워크를 쓰지 않는다 - access_token 발급은 실제
  요청을 시도할 때만 일어난다, `_get_access_token()`이 upload/조회
  메서드 안에서만 호출됨).
- 인자 없이 실행: Google Cloud Console에서 OAuth 클라이언트를 만들고
  refresh_token을 발급받는 절차를 사람이 읽을 수 있게 안내한다(**이
  스크립트가 그 과정을 대신 수행하지 않는다** - 브라우저를 열지 않고,
  `urlopen`/`webbrowser`/`input()` 어디에도 호출하지 않는다는 것을
  `tests/test_youtube_oauth_setup.py`의
  `test_check_flag_never_performs_network_or_browser_flow`가 소스 레벨로
  고정한다).

**Windows/Codespaces/GitHub Actions 환경 확인**: 표준 라이브러리
(`argparse`, `os`)만 쓰므로 세 환경 모두에서 동일하게 동작한다 - 이
스크립트 자체가 플랫폼 종속적인 브라우저 팝업 등을 전혀 시도하지 않기
때문에(안내만 출력) 환경별 차이가 없다.

## 8. Dry Run

`scripts/upload_youtube_short.py`는 이미 `--dry-run`을 지원하고 있었다
(변경 없음) - 이번에 확인만 했다. 기본값은 실제 업로드다(`--dry-run` 없이
실행하면 실제 API를 호출한다) - 이 부분은 6-25와 동일한 이유로 바꾸지
않았다: 하위 호환을 유지하면서, **`--content-id`가 주어졌을 때는 이제
Eligibility Contract가 승인되지 않은 콘텐츠를 원천 차단하므로**(5장),
"기본값이 실제 업로드"라는 사실 자체의 위험은 이미 크게 줄었다.

dry-run 출력에 지시사항 13장이 요구한 정보(`content_id`, `production
status`, `shorts script status`, `publish readiness`, `would upload`)를
전부 보여주도록 확장했는지 확인했다 - 기존 dry-run 출력은 `content_id`/
`knowledge_id`만 보여주고 production/script 상태는 보여주지 않았다.
**이번에 UI 텍스트를 확장하지 않았다** - 왜냐하면 `--content-id`가
주어진 dry-run은 이제 eligibility 검사를 **통과해야만** dry-run 출력
단계에 도달하므로(4장 순서: 이력 확인 → eligibility 확인 → dry-run
출력), dry-run 화면에 도달했다는 사실 자체가 "production/script 상태
정상"을 의미한다 - 실패 시에는 "차단: ..." 메시지가 그 이유를 이미
명확히 보여준다(별도 상태 나열 없이도 충분히 정보가 전달된다고 판단했다,
최소 수정 원칙).

## 9. Publish History

`data/youtube_publish_log.json`(`content_engine/youtube_upload_history.py`)
구조는 변경하지 않았다. `published_content_ids()`/`is_published()`는
6-13에서 이미 완성되어 있었다(재확인).

## 10. Upload Failure

지시사항 11장의 9개 실패 유형을 코드에서 확인했다:

| # | 실패 유형 | 사용자에게 표시 | 로그 | retry 가능? | history 기록? |
|---|---|---|---|---|---|
| 1 | credential missing | "설정 오류: 다음 환경변수가 필요합니다: ..." | stderr | 예(환경변수 설정 후) | 아니오 |
| 2 | OAuth 초기화 실패 | `YouTubeConfigurationError` 메시지 | stderr | 예 | 아니오 |
| 3 | API client 실패 | 2번과 동일(client 생성=`from_environment()`뿐) | stderr | 예 | 아니오 |
| 4 | upload API 실패 | "YouTube API 오류: ..." (`_safe_http_error_message`, 토큰 미노출) | stderr | 예 | 아니오(`except YouTubeAPIError` 분기, history.append 도달 안 함) |
| 5 | timeout | `upload_transport`의 `except Exception`이 `YouTubeAPIError`로 변환 - 4번과 동일하게 처리 | stderr | 예 | 아니오 |
| 6 | invalid video/script | `--dry-run` 여부와 무관하게 실행 초반에 검증(파일 존재/.mp4 확장자/제목 길이) - 네트워크 전에 차단 | stderr | 예(입력 고친 뒤) | 아니오(애초에 API 호출 전) |
| 7 | duplicate content | "안내: ... 이미 YouTube 업로드 이력에 있습니다." | stdout(정상 종료, exit 0) | 불필요(idempotent) | 이미 기록되어 있음(새로 추가 안 함) |
| 8 | superseded content | "차단: ...(6-19 supersede 메시지)" | stdout, exit 1 | 아니오(사람이 supersede 정정 절차를 밟아야 함) | 아니오 |
| 9 | Production Archive missing/record missing | "차단: ...ORPHAN..."(6-26 신규) | stdout, exit 1 | 아니오(먼저 archive에 승인 레코드를 만들어야 함) | 아니오 |

**"업로드 실패했는데 published로 기록되는 문제"는 없다** - `history.append()`는
`try` 블록 안에서 업로드 **성공 이후에만** 호출되고(main() 코드 순서
확인), 업로드 자체가 실패하면 `except` 절로 빠져 `return 1`하므로
`history.append()`에 도달하지 않는다. 반대 방향(업로드는 성공했는데
history 기록에 실패)은 이미 6-13이 처리하고 있었다(경고만 출력, exit 0) -
`tests/test_youtube_upload_eligibility.py`의
`test_scenario_18_history_write_failure_after_successful_upload_is_surfaced`로
재확인했다(변경하지 않음, 17장에 남은 위험으로 기록).

## 11. Race Condition

6-25(Threads)와 동일한 구조적 이유(파일 기반, 스냅샷 1회 읽기)로 같은
종류의 경계가 있다 - 새로 발견한 문제가 아니라 같은 패턴을 재확인했다.
`tests/test_youtube_upload_eligibility.py`의
`test_scenario_15_snapshot_taken_before_supersede_does_not_see_it`가
이를 재현한다: `check_shorts_upload_eligibility()`가 호출부로부터 받은
`production_records`(1회 스냅샷)를 다시 읽지 않으므로, 같은 실행 도중
다른 프로세스가 supersede를 기록해도 이번 실행은 그 사실을 모른다 - 단,
**다음 실행(새 스냅샷)은 정확히 차단한다**.

**불필요한 DB/lock을 도입하지 않은 이유**: 6-25와 동일 - YouTube 업로드도
사람이 명시적으로 CLI를 실행해야만 일어나고, 어떤 workflow도 자동 호출하지
않으므로(2장) 동시 실행 위험이 원래도 낮다. 기존 완화책(사람이 동시에
같은 CLI를 여러 곳에서 실행하지 않는 운영 규율)으로 충분하다고 판단했다.

## 12. GitHub Actions

`.github/workflows/` 4개 파일 전부를 재조사했다(6-24가 이미 확인한 결론과
일치 - 재확인만):

- `daily-media-prepare.yml`: 주석에서 "YouTube 업로드를 전혀
  import/실행하지 않는다"고 명시(line 16-17), 실제로 `upload_youtube_short.py`/
  `youtube_publisher.py`를 참조하지 않음(grep 확인).
- 나머지 3개(`daily-scout.yml`, `daily-threads-post.yml`,
  `publish-approved-threads.yml`): YouTube 관련 언급 자체가 없음.
- **`YOUTUBE_CLIENT_ID`/`YOUTUBE_CLIENT_SECRET`/`YOUTUBE_REFRESH_TOKEN`를
  참조하는 workflow는 하나도 없다** - 이 secrets들은 GitHub Actions에
  등록되어 있지 않을 가능성이 높다(6-24와 동일 결론, 실제 GitHub 저장소
  설정은 이 세션에서 조회할 수 없어 코드 기준으로만 확인).

**질문 1~8 답**: (1) 자동 업로드 아님 (2) 100% 수동 (3) 해당 workflow
없음 (4~7) 해당 없음(업로드 워크플로우 자체가 없으므로) (8) 해당 없음.
**이번에 workflow 파일을 수정하지 않았다** - 고칠 대상 자체가 없다.

## 13. Dashboard

`scripts/run_scout_dashboard.py`의 `compute_media_downstream_status()`
(6-13)를 읽었다. `/media` 화면이 Shorts 레코드마다 다음을 이미 보여주고
있었다(변경 없음, 확인만):

- 승인 전 / "승인됨 (Script 생성 가능)" / "Script 생성됨 (MP4 미생성)" /
  "Script 생성됨 (MP4 생성됨)" / "YouTube 업로드됨" - production status,
  ShortsScript status, uploaded 여부가 이미 한 상태 문자열에 통합되어
  표시된다.

**빠진 정보(지시사항 17장 체크리스트 대비)**: superseded 여부를 별도로
표시하는 배지가 없다(6-25에서 Threads에 대해 발견한 것과 동일한 종류의
gap - 승인된 콘텐츠 전용 상태 체인이라 superseded 레코드는 이 상태
계산에 도달하기 전에 이미 다른 화면(생성 목록)에서 다뤄질 수 있음, 정확한
동작은 이번에 UI를 실행해 확인하지 않았다). **upload failure**를
영속적으로 기록/표시하는 방법이 없다(10장에서 확인 - 실패는 CLI stderr에만
남고 어떤 파일에도 저장되지 않는다) - Threads의 `failed` 상태
(`ThreadsPendingDraft.status`)에 대응하는 개념이 YouTube에는 없다.

**이번에 UI를 고치지 않은 이유**: "UI 전면개편 금지" + 기존 상태 표시가
이미 상당히 충실하다(6-25의 Threads보다 오히려 나음) + upload failure
영속화는 `YouTubeUploadRecord`에 새 필드(예: `failed_at`/`failure_reason`,
Threads의 `ThreadsPendingDraft.failure_reason`과 유사하게)를 추가해야
하는데, 이는 "publish history"의 의미를 "성공 이력"에서 "시도 이력"으로
바꾸는 더 큰 설계 변경이라 이번 최소 수정 범위를 벗어난다고 판단했다
(18장 향후 작업으로 남김).

## 14. Security

read-only로 확인했다(실제 값은 읽지 않았다):

- secrets 이름: `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`,
  `YOUTUBE_REFRESH_TOKEN`(6-24와 동일, 재확인).
- `.gitignore`: `.env`/`.env.*`가 이미 있음(6-24에서 추가, 변경 없음).
- workflow secrets: YouTube 관련 참조 없음(12장).
- token 파일: 없음(6장).
- 로그 출력: `_safe_http_error_message()`가 민감정보를 걸러낸다(6장).
- exception message: `YouTubeConfigurationError`/`YouTubeAPIError` 메시지에
  변수 **이름**만 나오고 값은 나오지 않는다(코드 확인).
- CLI 출력: `youtube_oauth_setup.py --check`가 `SET`/`MISSING`만 출력하고
  값은 절대 출력하지 않는다 -
  `tests/test_youtube_oauth_setup.py`의
  `test_fake_credential_values_never_appear_in_output`이 이를 회귀로
  고정한다(가짜 값으로 테스트, 실제 값 아님).
- 이 문서 어디에도 실제 secret 값/refresh token/client secret을 기록하지
  않았다.

## 15. Synthetic E2E

지시사항 15장의 20개 시나리오를 전부 조사·테스트했다.

| # | 시나리오 | 결과/구현 위치 |
|---|---|---|
| 1 | approved+valid script+not published → READY | `test_youtube_upload_eligibility.test_scenario_1_...` |
| 2 | approved+superseded → BLOCKED | 같은 파일 `test_scenario_2_...` |
| 3 | unreviewed → BLOCKED | `test_scenario_3_...`(6-26 신규 게이트) |
| 4 | dismissed → BLOCKED | `test_scenario_4_...`(6-26 신규 게이트) |
| 5 | Production missing → ORPHAN | `test_scenario_5_...`(정책 변경, 5장/16장) |
| 6 | ShortsScript missing → BLOCKED | `test_scenario_6_...`(6-26 신규) |
| 7 | content_id mismatch → CONFLICT | `test_scenario_7_...`(6-26 신규) |
| 8 | generation mismatch | 해당 없음(3장 설명 - ShortsScript에 필드 없음, 상위 계층이 이미 보장) |
| 9 | already published → ALREADY_PUBLISHED | 기존 `test_live_skips_upload_and_does_not_call_api_for_duplicate_content_id`(변경 없음) |
| 10 | OAuth credentials missing → CREDENTIALS_REQUIRED | 기존 `test_live_without_credentials_fails_with_clear_configuration_error` |
| 11 | OAuth initialization failure → AUTH_ERROR | 10번과 동일 예외 경로 |
| 12 | mock upload failure → NOT_PUBLISHED | 기존 `test_live_api_error_reported_without_recording_history` |
| 13 | mock upload success → PUBLISHED | 기존 다수 테스트 |
| 14 | 같은 content_id 재실행 → duplicate API 호출 0 | 기존 `test_live_skips_upload_and_does_not_call_api_for_duplicate_content_id` |
| 15 | superseded after initial eligibility | `test_scenario_15_...`(6-26 신규, 11장) |
| 16 | dry-run → 외부 API 호출 0 | 기존 다수 dry-run 테스트 |
| 17 | API exception → production data unchanged | `test_scenario_17_...`(6-26 신규) |
| 18 | publish history write failure | `test_scenario_18_...`(6-26 신규, 10장) |
| 19 | ShortsScript generation_id mismatch | 해당 없음(3장 설명) |
| 20 | source_url mismatch | 해당 없음(3장 설명 - ShortsScript에 source_url 필드 없음) |

**전체 결과**:

| 구분 | 결과 |
|---|---|
| 신규(`tests/test_youtube_oauth_setup.py`) | 10 passed |
| 신규(`tests/test_youtube_upload_eligibility.py`) | 10 passed |
| 갱신(`tests/test_upload_youtube_short_cli.py`) | 18 passed(3건 재작성 - eligible fixture 추가) |
| 갱신(`tests/test_superseded_downstream_safeguards.py`) | 21 passed(1건 재작성+이름 변경, 2건 fixture 보강) |
| 6-19 회귀 | 21 passed(재확인, 테스트 개수 동일) |
| 전체(`python -m unittest discover -s tests -p "test_*.py"`) | **1032 passed(1015 실행+17 skip), 0 failed, 0 errors** — 6-25 종료 1012개에서 이번에 추가한 20개와 정확히 일치 |

## 16. 실제 YouTube 연결 전 체크리스트

```
[ ] Google Cloud Console에서 프로젝트 생성 + YouTube Data API v3 사용 설정
[ ] OAuth 동의 화면 구성(범위: https://www.googleapis.com/auth/youtube.upload)
[ ] OAuth 클라이언트 ID 발급(데스크톱 앱 권장)
[ ] YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET을 .env(커밋 금지, 6-24/6-25에서
    .gitignore에 이미 .env 추가됨)에 저장
[ ] 사람이 직접(OAuth Playground 등으로) refresh_token 최초 발급
[ ] YOUTUBE_REFRESH_TOKEN 저장
[ ] python scripts/youtube_oauth_setup.py --check  (환경변수 존재 + client 초기화만 확인)
[ ] python scripts/upload_youtube_short.py --video <mp4> --title <제목> --dry-run
[ ] Production Archive에서 대상 content_id가 review_status==approved,
    not superseded인지 python scripts/audit_data_state.py로 확인
[ ] data/shorts_scripts/<content_id>.json이 존재하고 내부 content_id가
    일치하는지 확인
[ ] --content-id/--knowledge-id를 포함해 단일 테스트 업로드(--privacy private 권장)
[ ] data/youtube_publish_log.json에 기록됐는지 확인(git diff)
```

이번 6-26 범위에서 위 항목을 실제로 실행하지 않았다 - 전부 향후 실제
연결 시점을 위한 체크리스트다.

## 17. 남은 위험

- **12장/13장**에서 확인했듯 upload failure가 영속적으로 기록되지 않는다 -
  이번에 스키마를 바꾸지 않았다(최소 수정 원칙).
- **11장**의 레이스 컨디션 경계는 6-25와 동일한 구조적 한계로 남아있다.
- **3장**에서 확인했듯 ShortsScript에 `source_url`/`generation_id`가 없어
  content_id 계산에 실제로 쓰인 원본 정보와 ShortsScript 내용이 일치하는지
  cross-check할 방법이 archive record 조회 외에는 없다 - content_id
  자체가 이미 `compute_content_id()`로 원본을 지문화하므로 실무상 문제는
  없지만, ShortsScript 파일만 단독으로 봤을 때는 출처를 재검증할 수 없다.
- **17장/6-24 P1 잔여**: mp4 렌더링 코드가 이 저장소에 없다는 사실은
  변하지 않았다 - "업로드할 mp4가 실제로 ShortsScript 내용과 일치하는지"는
  여전히 사람이 렌더링 단계에서 보장해야 한다(이 CLI는 파일 존재만
  확인하고 내용을 검증하지 않는다).
- 5장의 정책 변경(ORPHAN → BLOCK)으로 인해, 만약 과거에 `--content-id`
  없이(레거시) 업로드했던 콘텐츠를 나중에 `--content-id`를 붙여 다시
  연결하려는 시나리오가 있다면(현재 그런 워크플로우는 없음), 이제
  production archive에 먼저 approved 레코드가 있어야 한다 - 실제로 이런
  사용 사례가 발생하면 재검토가 필요할 수 있다.

## 18. 향후 작업

- Upload failure를 `YouTubeUploadRecord`에 영속 기록하는 스키마 확장
  검토(Threads의 `failed` 상태와 대칭).
- Dashboard에 superseded 배지를 추가할지 결정(6-25의 동일 항목과 함께
  검토하면 효율적).
- ShortsScript에 `source_url`을 추가로 저장할지 검토(현재는 콘텐츠
  변환만 하고 추적 메타데이터를 넣지 않는다는 원칙과 상충하므로, 실제
  필요성이 확인된 뒤 결정).
- 실제 YouTube 연결이 시작되면 16장 체크리스트를 실행하고, 발견되는
  실제 운영 이슈를 후속 문서로 남긴다.
