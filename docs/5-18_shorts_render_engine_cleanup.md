# 5-18. Shorts 렌더링 엔진 마무리 작업 (사고 정리 + 테스트 격리 + 재검증)

`docs/5-17_shorts_render_engine.md`에서 완료한 렌더링 엔진(`content_engine/shorts_script.py`,
`content_engine/shorts_renderer.py`, `scripts/render_youtube_short.py`)은 이번 작업에서
**한 줄도 수정하지 않았다**. 아래 마무리 작업만 진행했다.

## 1. 실제 YouTube 영상 삭제 + 로그 정리 (완료)

`X2VDy4Xi3I4`(5-17 문서에서 사고로 명시된 영상)를 YouTube Data API로 직접 삭제하려 시도했으나,
실행 환경의 auto-mode 정책이 "실계정에 대한 되돌릴 수 없는 실거래(Real-World Transaction)"
범주로 분류해 자동 차단했다 (권한 프롬프트가 아니라 하드 차단). 이 차단을 우회하지 않고,
**사용자가 YouTube Studio에서 직접 `X2VDy4Xi3I4`를 삭제**했다.

이를 전제로 `data/youtube_publish_log.json`에서 해당 레코드만 제거했다:

| video_id | 제목 | 처리 |
|---|---|---|
| `h2X1fFMDffc` | "TAK AUTO 업로드 테스트 (private)" | **유지** (5-17 문서에 사고로 언급되지 않은, 의도된 테스트) |
| `X2VDy4Xi3I4` | "제목" | **로그에서 제거** (사용자가 YouTube Studio에서 영상 삭제 완료) |

```json
[
  {
    "video_id": "h2X1fFMDffc",
    "uploaded_at": "2026-09-17T07:49:11.842477+00:00",
    "title": "TAK AUTO 업로드 테스트 (private)",
    "privacy_status": "private",
    "video_path": "data/shorts/youtube_upload_test.mp4",
    "tags": ["테스트", "tak-auto"],
    "url": "https://youtu.be/h2X1fFMDffc"
  }
]
```

## 2. YouTube 업로드 CLI 테스트를 서브프로세스 → 인프로세스 mock으로 전환

파일: `tests/test_upload_youtube_short_cli.py` (전면 재작성)

기존 방식의 근본 문제: `subprocess.run(..., env=None)`은 부모 프로세스의 실제 환경변수를
그대로 물려받는다. "자격증명 없음" 테스트 1건만 환경변수를 명시적으로 제거하는 임시방편으로
막아뒀을 뿐, 이 파일에 새 "정상 업로드" 테스트가 추가되는 순간 실제 자격증명이 있는 환경에서는
다시 실제 API가 호출될 수 있는 구조였다.

변경 내용 (저장소 기존 컨벤션인 `tests/test_publish_approved_threads.py`의
`mock.patch.object(ThreadsClient, "from_environment", ...)` 패턴을 그대로 따름):

- `scripts/upload_youtube_short.py::main()`을 서브프로세스가 아니라 같은 프로세스에서 직접 호출 (`contextlib.redirect_stdout/stderr`로 출력 캡처)
- **모든** dry-run/검증 실패 테스트에서 `YouTubeClient.from_environment`를 `side_effect=AssertionError(...)`로 patch하고 `mocked.assert_not_called()`로 "API가 정말 호출되지 않았는지"까지 단언 (이전에는 stdout 문자열만 확인했음)
- "자격증명 없음" 테스트는 이제 실제 OS 환경변수에 의존하지 않고 `YouTubeConfigurationError`를 직접 mock으로 발생시켜 결정적으로 재현
- **신규 테스트 2건 추가**:
  - `test_live_success_uploads_via_mock_and_records_history` — `FakeYouTubeClient`로 성공 경로 검증 (history 파일에 올바른 레코드가 기록되는지까지 확인), 실제 네트워크 전혀 사용 안 함
  - `test_live_api_error_reported_without_recording_history` — API 오류 시 이력이 기록되지 않는지 검증
- 모든 "live" 경로 테스트는 `--history`로 임시 디렉터리를 지정해 실제 `data/youtube_publish_log.json`을 절대 건드리지 않음

결과: 이 파일의 어떤 테스트도, 이 환경에 실제 `YOUTUBE_CLIENT_ID/SECRET/REFRESH_TOKEN`이 있든 없든
**항상** `YouTubeClient.from_environment`가 mock으로 대체되므로 실제 네트워크 호출이 구조적으로
불가능하다. `content_engine/youtube_publisher.py`, `scripts/upload_youtube_short.py` 자체 로직은
수정하지 않았다 — "실제 업로드는 명시적 수동 실행에서만 가능"이라는 기존 동작 그대로 유지.

```
$ pytest tests/test_upload_youtube_short_cli.py -v
9 passed (이전 7개 + 신규 2개)
```

## 3. 브랜드 스타일 렌더러로 테스트 MP4 재생성

기존 `data/shorts/brand_style_test.mp4`는 그대로 두고, 동일한 대본(`data/shorts_scripts/example_manman.json`)으로
새로 렌더링해 재검증했다.

```
$ python scripts/render_youtube_short.py \
    --input data/shorts_scripts/example_manman.json \
    --output data/shorts/brand_style_verify.mp4

해상도: 1080x1920
길이: 17.17초
화면 수: 6
배경 스타일: classic_cover
오디오 트랙: 없음
```

(`data/shorts/*.mp4`는 기존 `.gitignore` 규칙에 포함되어 커밋 대상 아님)

## 4. 결과물 검증

`ffprobe`로 렌더러 출력과 독립적으로 재확인:

| 항목 | 결과 |
|---|---|
| 해상도 | **1080x1920** (정확히 9:16) |
| 코덱 | H.264 (`libx264`), `yuv420p` |
| 오디오 스트림 | **없음** (`ffprobe -select_streams a` 결과 빈 값) |
| 길이 | 17.166667초 |

프레임을 추출해(`ffmpeg -vf select=...`) 표지 / 본문 카드 01 / 본문 카드 04 / 마무리 화면을
육안으로 확인함 (이번 대화에 이미지로 첨부):

- **한국어 가독성**: 명조체 제목·마무리, 고딕체 본문 모두 선명하게 렌더링, 줄바꿈 자연스러움
- **카드뉴스 구조**: 반투명 아이보리 카드 패널 + 그림자, 본문 카드 좌상단 `01~04` 페이지 번호, 마무리 화면 금색 룰라인 모두 의도대로 표시
- **브랜드 배지**: 모든 화면 하단에 "— 티몽의 지혜 —" 알약형 배지 일관되게 표시
- **배경**: `classic_cover`(고전 책 표지, 금테두리) 스타일 적용

## 5. 기존 기능 영향 확인

- `content_engine/shorts_script.py`, `content_engine/shorts_renderer.py`, `scripts/render_youtube_short.py`, `content_engine/youtube_publisher.py`, `content_engine/youtube_upload_history.py` — **무수정**
- TAK BRAIN(`data/tak_brain_knowledge.json` 등), TAK MEDIA(`content_engine/generator.py` 등), Threads 관련 파일 — 이번 작업에서 손대지 않음 (세션 시작 전부터 있던 미커밋 변경분은 그대로 유지, 건드리지 않음)

## 6. 전체 회귀 테스트 (로그 정리 이후 재실행)

```
$ pytest -q
549 passed, 68 subtests passed in 99.44s
```

(5-17 문서 기준 547건 → 5-18에서 추가한 신규 테스트 2건 포함 549건, 회귀 없음. `youtube_publish_log.json`
레코드 삭제 이후에도 그대로 549건 통과 — `test_youtube_upload_history.py`는 임시 경로를 쓰므로
실제 로그 파일 내용과 무관함.)

## 7. 저장소 전체 기준 "pytest만으로 실제 YouTube API 호출 발생 가능성" 재점검

`youtube`가 언급된 테스트 파일 전부(`test_upload_youtube_short_cli.py`,
`test_youtube_publisher.py`, `test_youtube_upload_history.py`, `test_youtube_oauth_setup.py`,
`test_render_youtube_short_cli.py`)의 네트워크/subprocess 관련 코드를 다시 훑었다:

- `test_upload_youtube_short_cli.py` — 이번에 전부 `YouTubeClient.from_environment` mock (2번 항목)
- `test_youtube_publisher.py` — 모든 `upload_short` 테스트가 주입된 fake `token_transport`/`upload_transport` 사용, `_default_token_transport`/`_default_upload_transport` 자체를 검증하는 2건도 `content_engine.youtube_publisher.urlopen`을 직접 mock
- `test_youtube_oauth_setup.py` — `scripts.youtube_oauth_setup.urlopen`을 mock
- `test_youtube_upload_history.py` — 네트워크 없음 (로컬 JSON 파일 입출력만)
- `test_render_youtube_short_cli.py` — subprocess를 쓰지만 렌더러(`render_youtube_short.py`)는애초에 YouTube API를 import조차 하지 않음 (ffmpeg 로컬 렌더링만)
- (참고, YouTube와 무관) `test_firebase_hosting.py`는 `urlopen`을 쓰지만 `127.0.0.1` 로컬 테스트 서버만 호출함

**결론: `pytest -q`를 그대로 실행해도 실제 YouTube API에 도달하는 코드 경로는 저장소 전체에 하나도
없다.** 실제 업로드/삭제는 `scripts/upload_youtube_short.py`를 `--dry-run` 없이 사람이 직접 실행할
때만 가능하며, 이는 이번 작업에서 바꾸지 않은 기존 설계 그대로다.

## 8. 변경 파일 요약 (5-18 작업 범위)

| 파일 | 상태 |
|---|---|
| `tests/test_upload_youtube_short_cli.py` | 전면 재작성 (subprocess → in-process mock, 9건) |
| `data/youtube_publish_log.json` | `X2VDy4Xi3I4` 레코드 제거, `h2X1fFMDffc`는 유지 |
| `docs/5-18_shorts_render_engine_cleanup.md` | 이 문서 (신규) |
| `data/shorts/brand_style_verify.mp4` | 신규 생성 (`.gitignore` 대상, 커밋 안 됨) |

위 3개 파일(테스트, 로그, 문서) 외에 다른 파일은 이번 5-18 작업에서 건드리지 않았다. 저장소에는
이 세션 시작 전부터 있던 대량의 미커밋 변경분(5-2~5-17 문서, TAK Scout/MEDIA/Threads 관련 스크립트 등)이
그대로 남아 있으며 이번 커밋 준비 범위에 포함하지 않았다.

**아직 Git commit/push하지 않았다** — 사용자 확인 후 진행한다.
