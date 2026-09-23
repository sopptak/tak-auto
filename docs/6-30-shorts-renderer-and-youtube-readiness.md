# 6-30 Shorts Renderer and YouTube Readiness

## 1. 목적

TAK AUTO의 Shorts Renderer(mp4 생성 엔진)와 YouTube 업로드 경로를 실제
운영 관점에서 조사하고, 현재 이 노트북(노트북2/수협)에서 10월 1일 첫
운영 시점에 실제로 사용 가능한지를 판정한다. 이 세션은 노트북2에서
실행 중이며 노트북1(집)의 파일시스템에는 접근할 수 없다 - 따라서
"노트북1에 파일이 있다"는 가정을 사실로 취급하지 않고, Git repository /
Git history / 현재 파일시스템 / 문서 / 테스트만을 근거로 결론을
내린다. 실제 YouTube API 호출, 실제 OAuth 로그인, 실제 업로드, 실제
운영 데이터 생성은 전혀 하지 않았다 - 모든 검증은 tempfile/mock/synthetic
fixture로만 수행했다.

## 2. 현재 repository 상태

세션 시작 시점(First Sync Check):

```
$ git status --short
(출력 없음 - clean)
$ git branch --show-current
main
$ git rev-parse HEAD
7bf40ff...
$ git rev-parse origin/main
7bf40ff... (HEAD와 동일)
```

HEAD == origin/main, working tree clean 확인 후 작업을 시작했다. 이
세션에서 기존 변경사항을 삭제하거나 `git reset --hard`/`git restore`를
실행한 적이 없다.

읽어야 할 3개 선행 문서(`docs/6-29-p1-closure-and-october-1-runbook.md`,
`docs/6-28-full-e2e-operating-readiness.md`, `docs/6-26-youtube-publish-readiness.md`)를
모두 다시 읽었다. 6-29는 이미 "YouTube 렌더러가 6-28이 기록한 것과 달리
'만든 적 없는 기능'이 아니라 '만들었지만 커밋을 놓친 코드'"라고
결론지었으나, 그 근거가 된 실제 git 이력 조사(`git log --all`)의 전체
출력은 6-29 문서에 기록되지 않았다 - 6-30에서 그 조사를 직접 재현하고
더 엄밀한 분류(CASE A/B/C, RECOVERABLE_FROM_GIT/RECOVERABLE_FROM_HISTORY/
EXTERNAL_MACHINE_REQUIRED)를 적용한다.

## 3. Shorts Renderer 조사

검색한 키워드: `shorts_renderer.py`, `render_short`, `render_shorts`,
`ShortsRenderer`, `ShortsScript`, `shorts_scripts`, `youtube_short`,
`upload_youtube_short`.

```
$ git ls-files | grep -i "short\|renderer\|youtube"
content_engine/performance/youtube.py
content_engine/shorts_adapter.py
content_engine/shorts_script.py
content_engine/youtube_publisher.py
content_engine/youtube_upload_history.py
data/youtube_publish_log.json
docs/5-18_shorts_render_engine_cleanup.md
docs/6-26-youtube-publish-readiness.md
scripts/generate_approved_shorts_script.py
scripts/upload_youtube_short.py
scripts/youtube_oauth_setup.py
tests/test_performance_youtube.py
tests/test_shorts_adapter.py
tests/test_upload_youtube_short_cli.py
tests/test_youtube_oauth_setup.py
tests/test_youtube_performance_client.py
tests/test_youtube_upload_eligibility.py
tests/test_youtube_upload_history_content_id.py
tests/test_youtube_upload_history_dedup.py
```

`content_engine/shorts_renderer.py`, `scripts/render_youtube_short.py`,
`tests/test_render_youtube_short_cli.py`는 이 목록에 **없다**.

```
$ git log --all --oneline -- "*renderer*"
(출력 없음)
$ git log --all --oneline -- "*short*"
(9개 커밋 - 전부 shorts_script.py/shorts_adapter.py/youtube 업로드 관련,
 renderer 파일 자체를 담은 커밋은 없음)
$ git log --all --stat -- "*short*"
(위 9개 커밋의 상세 - 0049d27만 shorts/renderer와 직접 관련된 문서를
 포함하지만, 포함된 파일은 data/youtube_publish_log.json,
 docs/5-18_shorts_render_engine_cleanup.md,
 tests/test_upload_youtube_short_cli.py 3개뿐이다. renderer 코드 자체는
 이 커밋에도 없다)
```

**A. 현재 renderer 코드가 존재하는가?** 아니오. 현재 파일시스템/git
tracked files 어디에도 `content_engine/shorts_renderer.py`,
`scripts/render_youtube_short.py`가 없다.

**B. 과거 커밋에 존재했는가?** 아니오. `git log --all`은 이 저장소의
모든 브랜치/reflog가 아닌 모든 ref를 검색하는데, 두 파일 모두 add된
기록조차 없다(diff-filter=A로도 0건).

**C. 어느 커밋에서 추가/삭제되었는가?** 해당 없음 - 추가된 적 자체가
없으므로 삭제된 커밋도 없다.

**D. GitHub origin/main에 존재하는가?** 아니오(HEAD==origin/main이고
로컬 `git log --all`이 전체 ref를 포함하므로, origin에 있는데 로컬에
없는 상황은 아니다 - `git fetch` 이후 조사했으므로 origin의 모든 ref가
로컬에 반영되어 있다).

**E. README/문서는 어떤 renderer를 사용한다고 말하는가?**
`README.md`에는 renderer 관련 언급이 전혀 없다(`grep` 결과 0건).
`content_engine/shorts_script.py`의 모듈 docstring은 "렌더링은
content_engine.shorts_renderer가 담당한다"고 명시하지만, 그 모듈은
존재하지 않는다 - 즉 코드 자체가 존재하지 않는 의존성을 문서화하고
있는 상태다. `docs/5-18_shorts_render_engine_cleanup.md`가 유일하게
renderer의 실제 동작을 구체적으로 설명하는 문서다(9장 참고).

**F. GitHub Actions가 renderer를 호출하는가?**
```
$ grep -rn "render" .github/workflows/*.yml
(출력 없음)
```
아니오. 4개 workflow 파일(`daily-scout.yml`, `daily-media-prepare.yml`,
`daily-threads-post.yml`, `publish-approved-threads.yml`) 어디에도
renderer/mp4 생성 관련 호출이 없다.

**G. 실제 mp4 생성 코드는 어디에 있는가?** 이 저장소 안에는 없다.
`content_engine/shorts_script.py`(존재)는 ShortsScript **데이터**(제목/
카드 텍스트/takeaway)만 만들 뿐 영상을 만들지 않는다. mp4를 실제로
만드는 코드(ffmpeg 호출, 이미지 렌더링)는 이 저장소 어디에도 없다.

**H. renderer와 YouTube uploader의 연결점은 무엇인가?** 설계상
연결점은 `data/shorts_scripts/<content_id>.json`(ShortsScript) →
(존재하지 않는 renderer) → mp4 파일 경로 → `scripts/upload_youtube_short.py
--video <mp4 경로> --content-id <content_id>`다. `upload_youtube_short.py`는
mp4 파일의 **경로만** 인자로 받을 뿐, ShortsScript나 renderer를 직접
import하지 않는다 - 즉 코드 수준에서는 완전히 분리되어 있고, 연결은
사람이 `--video`로 넘기는 파일 경로로만 이루어진다(느슨한 결합).

**I. renderer 없이 YouTube publish readiness는 어떻게 판정되는가?**
`scripts/upload_youtube_short.py`의 `check_shorts_upload_eligibility()`는
mp4 파일의 **존재나 내용을 전혀 확인하지 않는다** - Production Archive의
review_status, supersede 여부, ShortsScript 파일 존재/content_id 일치만
확인한다. mp4 존재 여부는 `main()`에서 `--video` 인자 자체의
`Path.exists()`로 별도 확인한다(7장 표 참고). 즉 "renderer가 있는지"는
이 판정 로직과 무관하다 - renderer가 없어도 이 함수는 정상 동작하며,
실제 차단은 "업로드할 mp4 파일 자체가 없다"는 물리적 사실에서
발생한다.

## 4. Git history 조사

분류 기준(6-30 지시사항):
- **CASE A** (현재 저장소에 존재) → `RECOVERABLE_FROM_GIT`
- **CASE B** (과거 커밋에는 존재했으나 현재 브랜치에 없음) → `RECOVERABLE_FROM_HISTORY`
- **CASE C** (git 이력 전체에 존재한 적이 없음) → `EXTERNAL_MACHINE_REQUIRED`

3장의 조사 결과, `content_engine/shorts_renderer.py`,
`scripts/render_youtube_short.py`,
`tests/test_render_youtube_short_cli.py`,
`docs/5-17_shorts_render_engine.md`(renderer를 최초로 설계한 문서로
추정됨, 0049d27의 후속 문서인 5-18이 언급함) 4개 파일 모두:

```
$ git log --all --oneline --diff-filter=A -- "content_engine/shorts_renderer.py"
(출력 없음)
$ git log --all --oneline --diff-filter=A -- "scripts/render_youtube_short.py"
(출력 없음)
$ git log --all --oneline --diff-filter=A -- "docs/5-17_shorts_render_engine.md"
(출력 없음)
```

**이 저장소의 git 이력 전체에 이 파일들이 추가된 커밋이 단 한 번도
없다.** → **CASE C → EXTERNAL_MACHINE_REQUIRED**.

`RECOVERABLE_FROM_GIT`도 `RECOVERABLE_FROM_HISTORY`도 아니다 - 두 용어
모두 "이 저장소의 커밋 그래프 어딘가에 코드가 존재한다"를 전제하는데,
그 전제 자체가 성립하지 않는다.

## 5. 노트북1 의존성 여부

이 세션은 노트북1의 파일시스템에 접근하지 않았고, 접근할 수도 없다 -
따라서 "노트북1에 파일이 실제로 있다"는 것은 **이 세션이 확인한 사실이
아니다**. 다만 간접 정황은 다음과 같다:

- `docs/5-18_shorts_render_engine_cleanup.md`(git에 커밋됨, 0049d27)는
  1080x1920/H.264/무음성/6화면 mp4를 **실제로 만들어 검증했다**고
  구체적으로 기술한다(9장). 문서만으로 이런 구체적 출력 특성(정확한
  17.166667초 길이, "classic_cover" 스타일명 등)을 기술하기는
  어렵다 - **실행 가능한 코드가 어떤 환경에서든 한 번은 존재했다**는
  정황이 강하다.
- 같은 문서의 마지막 줄은 "아직 Git commit/push하지 않았다 - 사용자
  확인 후 진행한다"로 끝난다. 즉 그 세션 시점에는 해당 코드가 **그
  세션이 실행되던 머신의 working tree(커밋 전 상태)**에 존재했다.
- 이후 실제로 커밋된 것은 문서 2건과 로그 파일 1건뿐이며(3장), 코드
  본체는 커밋되지 않은 채로 남았다.

이 정황들을 종합하면 "코드가 어떤 로컬 머신의 uncommitted 상태로 한때
존재했을 가능성이 높다"는 가설은 세울 수 있지만, **그 머신이
노트북1인지, 그 상태가 지금도 남아있는지는 이 세션에서 검증할 수 없는
사실**이다. 이 문서는 그 가능성을 가설로만 남기고, "노트북1에 있다"고
단정하지 않는다 - 확인은 사람이 노트북1에서 직접 `git status`,
`ls content_engine/shorts_renderer.py`로 해야 한다.

## 6. Renderer 복구 가능성

6장 6개 하위 질문에 대한 답:

1. **Git history에서 복구 가능한가?** 아니오(4장, CASE C).
2. **문서 스펙만으로 충분한가?** 부분적으로만. `docs/5-18_shorts_render_engine_cleanup.md`는
   출력 결과(해상도/코덱/화면 수/스타일명/폰트 종류)는 상세히
   기술하지만, **실제 구현 알고리즘(카드 레이아웃 좌표, 폰트 파일
   경로, ffmpeg 명령어 전체, 타이밍 계산식)은 기술하지 않는다** - 이
   문서만으로 동일한 출력을 재현하는 것은 스펙 문서라기보다는
   "요구사항 설명"에 가깝다.
3. **현재 ShortsScript 스키마만으로 재구성 가능한가?** `content_engine/shorts_script.py`의
   `ShortsScript`(title/subtitle/cards/takeaway/brand)는 렌더링에 필요한
   **콘텐츠**는 제공하지만, 렌더링에 필요한 **스타일/레이아웃 파라미터**
   (카드 색상, 폰트, 애니메이션 여부)는 포함하지 않는다 - 별도로
   설계해야 한다.
4. **renderer가 10월 1일 실제 운영에 반드시 필요한가?** YouTube
   채널만 놓고 보면 예(7장) - mp4 없이는 업로드 자체가 불가능하다.
   하지만 SCOUT→KNOWLEDGE→MEDIA→HUMAN REVIEW→PROMOTION→PRODUCTION
   ARCHIVE→Threads/Blog 경로는 renderer와 무관하게 완전히 동작한다
   (6-28/6-29에서 이미 확인, 이번에도 유효).
5. **mp4가 YouTube 업로드 전에 반드시 필요한가?** 예 -
   `scripts/upload_youtube_short.py`의 `main()`은 `--video` 인자가
   가리키는 파일이 존재하고 확장자가 `.mp4`가 아니면 즉시 오류로
   종료한다(코드 196-201행).
6. **GitHub Actions가 자동 renderer를 필요로 하는가?** 아니오(3장 F).
   YouTube 업로드는 현재 100% 로컬/수동 경로이며 CI 자동화가 전혀
   없다.

**결론(이 장의 분류): `EXTERNAL_DEPENDENCY`** - "이번 세션에서
재구현이 필요하다(REBUILD_REQUIRED)"고 단정하지 않는다. Git에서 복구
불가능하다는 사실과, 코드가 한때 다른 환경에 존재했다는 정황(5장)이
공존하므로, 가장 정확한 분류는 "이 저장소/이 세션만으로는 해결할 수
없고 외부(다른 머신 확인 또는 처음부터 재작성)에 의존한다"는
`EXTERNAL_DEPENDENCY`다. YouTube 채널 자체는 renderer 없이는 물리적으로
동작할 수 없지만, 이는 시스템 전체의 첫 실행을 막지 않으므로 시스템
차원에서는 `NOT_REQUIRED_FOR_FIRST_RUN`(16장 참고)이기도 하다 - 이
두 판정은 서로 다른 레벨(채널별 vs 시스템 전체)에 적용되며 모순이
아니다.

## 7. YouTube publish flow

| 단계 | 입력 | 출력 | 필요 조건 | 실패 조건 | 현재 구현 상태 |
|---|---|---|---|---|---|
| Production Archive | approved MediaArchiveRecord | 승인된 content_id | review_status=="approved" | superseded/dismissed/unreviewed | READY(구조) |
| Publish Readiness | Production Archive | READY/BLOCKED/... 판정 | `content_engine.publish_audit` | 매칭 레코드 없음 → NEEDS_HUMAN_REVIEW | READY(구현됨) |
| ShortsScript | approved+platform=="shorts" 레코드 | `data/shorts_scripts/<content_id>.json` | `scripts/generate_approved_shorts_script.py` 실행 | generation_status!="valid" 등 → 생성 거부 | READY(구현됨, 실행하면 실제 데이터 생성 - 이번 세션은 실행하지 않음) |
| Renderer | ShortsScript | mp4 파일 | **이 저장소에 코드 없음** | 항상 실패(코드 부재) | **EXTERNAL_DEPENDENCY**(6장) |
| YouTube OAuth | env vars(CLIENT_ID/SECRET/REFRESH_TOKEN) | access token | 3개 env var 설정 + 실제 Google Cloud OAuth 클라이언트 등록 | env var 누락 → `YouTubeConfigurationError` | READY(구조), 실제 인증은 사람이 최초 1회 수행 필요 |
| uploader | mp4 경로 + title/description/tags + content_id(선택) | video_id, URL | mp4 존재, .mp4 확장자, title<=100자, eligibility 통과(--content-id 지정 시) | eligibility 차단, API 오류, mp4 없음 | READY(구현·테스트됨) |
| Publish History | 업로드 성공 결과 | `data/youtube_publish_log.json` append | 업로드 성공 | history 쓰기 실패 시 경고만(업로드 자체는 성공 처리, 6-13 기존 동작) | READY |

## 8. OAuth

`content_engine/youtube_publisher.py`의 `YouTubeClient`는 stdlib
`urllib`만 사용하는 OAuth 2.0 refresh_token 기반 클라이언트다.
`YouTubeClient.from_environment()`가 다음 3개 환경변수를 읽는다(값은
이 문서에 출력하지 않음):

- `YOUTUBE_CLIENT_ID`
- `YOUTUBE_CLIENT_SECRET`
- `YOUTUBE_REFRESH_TOKEN`

3개 중 하나라도 없으면 `YouTubeConfigurationError`를 발생시키고, 실제
네트워크 호출은 시도하지 않는다. `scripts/youtube_oauth_setup.py --check`는
이 3개 변수의 **존재 여부만** 확인하고(`check_environment()`), 값은
전혀 출력하지 않는다 - 실제 브라우저 OAuth 플로우(`webbrowser`,
`input()`)는 이 파일에 코드로 존재하지 않는다(grep으로 재확인, 0건).
즉 최초 1회 실제 OAuth 인증은 **사람이 Google Cloud Console에서
수동으로 진행해야 한다** - 이 저장소에는 그 과정을 자동화하는 코드가
없다.

`_safe_http_error_message()`가 YouTube API 오류 응답에서 민감정보를
제거한 뒤에만 출력하도록 되어 있다(코드 재확인, 변경 없음).

## 9. Production Archive 보호

6-19/6-24에서 추가된 `content_engine.media_archive.find_protected_overwrite_targets()`가
`archive_report()` 호출 전에 이미 승인/superseded된 content_id의
rewritten_title/rewritten_body가 조용히 덮어써지는 것을 막는다. 이
가드는 YouTube 경로와 직접 관련은 없지만(YouTube는 Production
Archive를 쓰지 않고 읽기만 한다), Production Archive 자체의 신뢰성을
보장하는 전제 조건이므로 재확인했다 - `scripts/upload_youtube_short.py`는
`--production-archive`로 지정된 파일을 **읽기만** 하며 절대 쓰지
않는다(코드 재확인, `load_archive()`만 호출).

## 10. Superseded 보호

`tests/test_6_30_shorts_renderer_and_youtube_readiness.py::FullCliCaseAToFTests`(신규,
17장)로 CASE A~F를 실제 `scripts/upload_youtube_short.py`의 `main()`
CLI 진입점으로 재검증했다(기존 6-26 테스트는 헬퍼 함수만 호출했다):

| CASE | 조건 | 판정 | 검증 결과 |
|---|---|---|---|
| A | 이미 publish history에 있음 | ALREADY_PUBLISHED(idempotent no-op) | exit 0, 업로드 API 미호출 - PASS |
| B | Production approved | 업로드 가능 | exit 0, 업로드 API 1회 호출 - PASS |
| C | Production superseded | BLOCKED | exit 1, 업로드 API 미호출 - PASS |
| D | Production unreviewed | NEEDS_HUMAN_REVIEW(BLOCKED) | exit 1, 업로드 API 미호출 - PASS |
| E | Production 레코드 없음(ORPHAN) | BLOCKED(기존 정책 - Threads와 다름, 6-26) | exit 1, 업로드 API 미호출 - PASS |
| F | ShortsScript 내부 content_id 불일치(CONFLICT) | BLOCKED | exit 1, 업로드 API 미호출 - PASS |

기존 정책을 변경하지 않고 실제 코드 동작만 검증했다.

## 11. Duplicate protection

질문: ShortsScript가 존재하고 렌더러가 만든(것으로 가정한) mp4 파일이
실제로 디스크에 있어도, Production Archive가 superseded되면 재업로드를
막을 수 있는가?

`tests/test_6_30_shorts_renderer_and_youtube_readiness.py::CliLevelSupersededMp4Tests::test_superseded_record_with_existing_mp4_is_blocked_by_full_cli`로
검증했다 - 실제 renderer가 없으므로 "mock renderer"(가짜 mp4 bytes를
tempfile에 쓰는 헬퍼 `_mock_render_mp4()`)로 mp4가 실제로 디스크에
존재하는 상황을 재현했다. 결과: **이미 차단된다** - 기존
`check_shorts_upload_eligibility()`가 `main()`에서 `--content-id`가
주어졌을 때 review_status를 다시 확인하고(90행), mp4 파일이 물리적으로
존재하는지 여부와 무관하게 superseded 레코드를 차단한다(6-26 코드,
변경 없음). **새 차단 코드를 추가할 필요가 없었다** - 이번 세션은
검증만 하고 프로덕션 코드는 수정하지 않았다.

단, `--content-id`를 생략한 legacy/자유 업로드 경로는 이 검증을 전혀
거치지 않는다(docstring에 명시된 의도적 설계, 24-29행) - TAK MEDIA
파이프라인과 무관한 영상을 올리는 정당한 사용법이기 때문이다. 이는
새로운 위험이 아니라 기존에 문서화된 경계이므로 이번 세션에서 정책을
바꾸지 않았다.

## 12. GitHub Actions

`.github/workflows/`의 4개 파일(`daily-scout.yml`,
`daily-media-prepare.yml`, `daily-threads-post.yml`,
`publish-approved-threads.yml`)을 이번 세션에서 다시 읽었다:

- renderer 실행: 없음(`grep -rn "render"` 0건).
- ShortsScript 생성: `daily-media-prepare.yml`이 TAK MEDIA 배치를
  실행하며 shorts_scripts/*.json을 git에 직접 커밋한다(기존 확인
  재확인) - 단 이는 ShortsScript **데이터**일 뿐 mp4가 아니다.
- artifact 보관: Blog Pack은 14일 아티팩트로 업로드(git 커밋 아님).
- YouTube 관련 secrets(`YOUTUBE_CLIENT_ID`/`SECRET`/`REFRESH_TOKEN`)
  참조: 4개 workflow 전체에서 0건.
- 이 세션은 어떤 workflow도 실제로 실행하지 않았다.

**YouTube 업로드는 100% 로컬/수동 경로이며 CI 자동화가 전혀 없다**
(6-24/6-26/6-28/6-29와 동일한 결론, 이번에 다시 확인).

## 13. Windows 환경

읽기 전용으로만 확인했다(패키지 설치 시도 없음):

```
$ where ffmpeg
찾을 수 없음
$ where ffprobe
찾을 수 없음
$ python --version
Python 3.13.15
$ python -c "import PIL"
ModuleNotFoundError: No module named 'PIL'
$ ls assets/fonts, fonts, assets
전부 존재하지 않음
```

**이 노트북(노트북2)에는 ffmpeg/ffprobe가 PATH에 없고, Pillow가 설치되어
있지 않으며, 폰트 자산 디렉터리도 없다.** `docs/5-18_shorts_render_engine_cleanup.md`가
설명하는 renderer는 ffmpeg/ffprobe를 명시적으로 사용했다고 기술한다 -
설치 필요(설치를 이번 세션에서 시도하지 않았다). Pillow는
requirements.txt/pyproject.toml이 이 저장소에 전혀 없어(전부 stdlib
전제) 문서만으로 확정할 수 없지만, 한글 카드 텍스트를 이미지로
렌더링하려면 이미지 라이브러리가 사실상 필요하므로 설치 필요로
문서화한다. 이번 세션은 어떤 패키지도 설치하지 않았고 환경을 오염시키지
않았다.

## 14. 10월 1일 Shorts 시나리오

| 단계 | 상태 |
|---|---|
| KNOWLEDGE | READY_WITH_HUMAN_STEP |
| MEDIA | READY |
| Human Review | READY_WITH_HUMAN_STEP |
| Production Archive | READY_WITH_HUMAN_STEP(Promotion 포함) |
| ShortsScript 생성 | READY_WITH_HUMAN_STEP(스크립트 실행은 사람이 트리거) |
| Renderer | **BLOCKED**(코드 없음, 6장) |
| MP4 | BLOCKED(Renderer가 BLOCKED이므로 연쇄 차단) |
| Publish Readiness(uploader 진입 전 확인) | READY(구현·테스트됨, mp4 유무와 무관하게 정상 판정) |
| YouTube uploader 실행 | **EXTERNAL_DEPENDENCY**(실제 YouTube API 호출은 이 세션 범위 밖이며, mp4 자체가 없어 실행 불가) |

renderer 단계가 BLOCKED이므로 YouTube 채널 전체가 실질적으로
막혀 있다. 나머지 채널(Threads/Blog)은 이 체인과 독립적이다(6-28/6-29
결론 유지).

## 15. 운영 상태 판정

최종 renderer 복구 판정(6개 선택지 중 정확히 하나):

**E. `EXTERNAL_MACHINE_REQUIRED`**

근거: 4장에서 확인했듯, `content_engine/shorts_renderer.py`,
`scripts/render_youtube_short.py`, `docs/5-17_shorts_render_engine.md`
모두 이 저장소의 git 이력 전체(모든 ref)에 추가된 적이 없다(CASE C).
`RECOVERABLE_FROM_GIT`(현재 브랜치에 존재)도 `RECOVERABLE_FROM_HISTORY`
(과거 커밋에는 존재)도 성립하지 않는다 - 이 저장소만으로는 코드를
되살릴 방법이 없다. `docs/5-18_shorts_render_engine_cleanup.md`가
묘사하는 구체적 실행 결과는 코드가 한때 어떤 로컬 머신에서 실제로
동작했음을 강하게 시사하지만(5장), 그 머신이 노트북1인지/지금도 그
상태인지는 이 세션이 검증할 수 없는 사실이므로 `CURRENTLY_AVAILABLE`이나
`RECOVERABLE_FROM_GIT`으로 판정하지 않는다. `REBUILD_REQUIRED`(처음부터
재작성)는 아직 "다른 머신에 있을 가능성"을 사람이 직접 확인하기 전에
단정할 수 없으므로 이번 세션의 최종 판정으로 선택하지 않았다 - 사람이
노트북1을 확인한 뒤에도 코드가 없다면 그때 `REBUILD_REQUIRED`로
전환하는 것이 맞다.

## 16. 실제 필요한 작업

15장 판정이 `EXTERNAL_MACHINE_REQUIRED`이므로, 이 세션은 renderer를
새로 만들지 않았다(지시사항 16장: "이번 작업에서는 실제 운영용
대규모 renderer를 무리하게 만들지 마라" - 조건인 "Git history에서
복구 가능"이 성립하지 않으므로 최소 구현 제안 대상에도 해당하지
않는다).

대신 이번 세션은 다음만 수행했다:
1. `tests/test_6_30_shorts_renderer_and_youtube_readiness.py`에
   renderer 모듈이 import되지 않는다는 회귀 감지 테스트를 추가했다
   (나중에 복구되면 이 테스트가 실패로 알려준다).
2. 11장의 "mock renderer" 검증(실제 renderer 없이 가짜 mp4 bytes로
   supersede 보호를 확인) - 프로덕션 코드는 수정하지 않았다.

사람이 다음에 해야 할 일(코드 작업 아님, 문서화만):
- 노트북1에서 `content_engine/shorts_renderer.py`,
  `scripts/render_youtube_short.py`가 실제로 남아있는지 직접 확인.
  있다면 `git add` 후 전체 테스트 통과 확인 후 커밋/푸시(6-29 Runbook
  12장 B단계에 이미 안내되어 있음, 이번 세션에서 그 안내를 뒤집지
  않는다).
- 없다면 `REBUILD_REQUIRED`로 전환 - 최소 구현시 우선순위(지시사항
  16장 그대로): 1080x1920, H.264, 무음성, 한글 텍스트, 카드 3-5장,
  마지막 takeaway, content_id 연결, 결정적(deterministic) 출력,
  tempfile로 테스트 가능. `data/`에 실제로 쓰지 않아야 한다.
- 재구현 전 이 노트북에 ffmpeg 설치, Pillow(또는 대체 이미지
  라이브러리) 설치, 한글 폰트 자산 준비가 선행되어야 한다(13장).

## 17. Security

시크릿 **이름**이 사용되는 위치만 확인했다(값은 절대 출력하지
않음):

- `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN`:
  `content_engine/youtube_publisher.py`(`YouTubeClient.from_environment()`),
  `scripts/youtube_oauth_setup.py`(`REQUIRED_ENV_VARS`)에서만 참조된다.
  두 파일 모두 값을 print/log하지 않는다(재확인).
- 범용 패턴(`API_KEY`/`TOKEN`/`SECRET`/`PASSWORD`) 검색 결과, YouTube
  관련 파일에서 새로 발견된 것은 없다 - 기존 6-24 Security 감사
  범위와 동일하다.
- `.env`, `.env.*`는 `.gitignore`에 이미 포함되어 있다(`!.env.example`만
  예외, 재확인).

## 18. 테스트

실행 순서(지시사항 17장 그대로):

1. 신규 테스트: `tests/test_6_30_shorts_renderer_and_youtube_readiness.py` - 10개, 전부 PASS.
2. YouTube 관련 기존 테스트(`test_youtube_oauth_setup`,
   `test_youtube_upload_eligibility`, `test_upload_youtube_short_cli`,
   `test_shorts_adapter`, `test_performance_youtube`,
   `test_youtube_performance_client`,
   `test_youtube_upload_history_content_id`,
   `test_youtube_upload_history_dedup`) - 75개, 전부 PASS.
3. 전체 회귀: `python -m unittest discover -s tests -p "test_*.py"`

```
Ran 1083 tests in 76.750s
OK (skipped=17)
```

failed=0, errors=0. 기존 테스트를 삭제하거나 무조건 skip 처리한 것은
없다(17건의 skip은 이 세션 이전부터 존재하던 조건부 skip이다).

`git status --short`를 테스트 전/후 모두 확인했다 - `data/` 아래
운영 데이터 파일은 전혀 생성/수정되지 않았다(신규 테스트 파일
1건만 추가됨, 9장/18장 참고).

## 19. 남은 P1/P2/P3

- **P1**: Shorts Renderer 복구 또는 재구현(15/16장) - 이 저장소만으로는
  해결 불가, 사람의 확인(노트북1) 또는 재작성 결정이 필요하다.
- **P1**: YouTube 실제 OAuth 최초 인증(8장) - 코드는 준비되어 있으나
  실제 인증은 사람이 Google Cloud Console에서 직접 진행해야 한다.
- **P2**: ffmpeg/Pillow/폰트 등 renderer 실행 환경 준비(13장) - renderer
  복구/재구현이 결정된 이후에 진행.
- **P2**: Performance feedback loop 미구현(6-28/6-29에서 이미 기록,
  변경 없음).
- **P3**: Multi-PC 운영 설계의 실전 검증(6-29에서 이미 기록, 변경
  없음).

## 20. 결론

Shorts Renderer는 이 저장소의 git 이력 전체(모든 ref)에 존재한 적이
없다 - `CURRENTLY_AVAILABLE`도, `RECOVERABLE_FROM_GIT`도,
`RECOVERABLE_FROM_HISTORY`도 아니며, 최종 판정은
`EXTERNAL_MACHINE_REQUIRED`다(15장). `docs/5-18_shorts_render_engine_cleanup.md`가
증언하는 실행 이력은 코드가 한때 어떤 로컬 환경에 존재했음을
시사하지만, 그 환경이 노트북1인지 이 세션은 확인할 수 없다 - 사람의
직접 확인이 필요하다. 이 세션은 그 조건(Git history 복구 가능)이
성립하지 않았으므로 renderer를 새로 만들지 않았다(16장).

YouTube 업로드 경로 자체(OAuth 구조, eligibility 검증, supersede/중복
차단, publish history 기록)는 코드 수준에서 이미 READY하고 이번
세션에서 CASE A~F 전체를 실제 CLI 진입점으로 재검증했다(10장) -
문제는 renderer 부재로 인한 mp4 부재뿐이다(`EXTERNAL_DEPENDENCY`, 14장).

10월 1일 운영은 **SCOUT→KNOWLEDGE→MEDIA→HUMAN REVIEW→PROMOTION→
PRODUCTION ARCHIVE→Threads/Blog** 경로에서 여전히 가능하다(6-28/6-29
결론 유지, 변경 없음). YouTube 채널만 renderer 복구/재구현 전까지
BLOCKED다.
