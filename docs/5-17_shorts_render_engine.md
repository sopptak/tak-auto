# 5-17. "티몽의 지혜" Shorts 렌더링 엔진 구현

## 0. 사전 조사 요약

작업 전 확인한 기존 구조:

- `content_engine/models.py`의 `ShortDraft`는 `title + body`(단일 문자열) 구조이고, `content_engine/generator.py`가 KNOWLEDGE에서 규칙 기반으로 생성한다. 이 파이프라인은 이번 작업에서 전혀 수정하지 않았다.
- `scripts/upload_youtube_short.py` + `content_engine/youtube_publisher.py` + `content_engine/youtube_upload_history.py`가 "완성된 MP4 -> YouTube 업로드"를 담당한다. 역시 수정하지 않았다.
- 영상/이미지 렌더링 코드는 저장소에 전혀 없었다(TAK MEDIA는 텍스트 Draft까지만 생성). Codespace에는 `ffmpeg`(시스템 바이너리)와 한국어 폰트(나눔글꼴: `NanumMyeongjo`, `NanumGothic`, `NanumBarunGothic` 등)가 이미 설치되어 있었고, Python 이미지 라이브러리(Pillow)는 없었다.
- 저장소는 지금까지 외부 Python 의존성 없이 표준 라이브러리만 사용해왔다(`youtube_publisher.py`, `threads_publisher.py` 등 docstring에 명시). 카드뉴스 이미지 합성(그라데이션/반투명 패널/한글 자동 줄바꿈)에는 Pillow가 사실상 필수라, 진행 전 사용자에게 "Pillow + ffmpeg" vs "순수 ffmpeg 필터"를 확인했고 **Pillow + ffmpeg**로 진행하기로 결정했다(신규 의존성 1개 추가).

## 1. 구현 계획 (진행 전 보고한 대로 실행)

```
대본 JSON (title/subtitle/cards/takeaway/brand)
        ↓  content_engine/shorts_script.py   (순수 로직: 검증 + 화면 분할 + 노출시간 계산)
ScreenPlan[] (표지 → 본문 카드 → 마무리)
        ↓  content_engine/shorts_renderer.py (Pillow: 배경/카드패널/폰트 자동맞춤 + ffmpeg 인코딩)
1080x1920 무음 MP4
        ↓  scripts/upload_youtube_short.py (기존, 무수정)
YouTube PRIVATE/UNLISTED/PUBLIC
```

`shorts_script.py`와 `shorts_renderer.py`를 분리한 이유: 대본 검증/타이밍 계산은 Pillow/ffmpeg 없이도 빠르게 단위 테스트할 수 있어야 하고, 향후 TAK MEDIA `ShortDraft`(문자열 1개)를 "표지/카드/마무리로 나뉜 대본"으로 변환하는 어댑터를 추가할 때도 렌더링 엔진 자체는 건드릴 필요가 없도록 하기 위함이다(이번 작업 범위에는 그 어댑터 자체는 포함하지 않았다 - 사용자가 요청한 것은 렌더러이며, 어댑터는 "향후 연결"을 위한 인터페이스 설계까지만 요구했다).

## 2. 변경 파일

### 신규 파일
- `content_engine/shorts_script.py` — `ShortsScript`(대본 모델) + 검증 + `ScreenPlan`/화면별 노출시간 계산 (Pillow/ffmpeg 비의존)
- `content_engine/shorts_renderer.py` — 배경 6종, 카드 패널/텍스트 자동맞춤, ffmpeg 인코딩(xfade 크로스페이드), ffprobe 검증
- `scripts/render_youtube_short.py` — CLI (`--input`, `--output`, `--background`, `--dry-run`)
- `data/shorts_scripts/example_manman.json` — 실사용 예시 대본(커밋 대상)
- `requirements.txt` — 신규 의존성 `Pillow` 명시 및 사유 주석
- `tests/test_shorts_script.py`, `tests/test_shorts_renderer.py`, `tests/test_render_youtube_short_cli.py` — 신규 테스트 34건

### 수정 파일
- `content_engine/__init__.py` — 기존 컨벤션대로 새 모듈의 공개 API를 패키지 최상위에 재노출
- `tests/test_upload_youtube_short_cli.py` — **버그 수정**(아래 3번 참고)

### 생성되었지만 커밋 대상 아님(기존 `.gitignore`의 `data/shorts/*.mp4` 규칙에 이미 포함됨)
- `data/shorts/brand_style_test.mp4`

## 3. ⚠️ 작업 중 발견한 사고와 조치 (중요)

전체 회귀 테스트(`pytest`)를 처음 돌렸을 때 `tests/test_upload_youtube_short_cli.py::test_live_without_credentials_fails_with_clear_configuration_error`가 **실제로 YouTube에 테스트 영상을 업로드**하는 부작용을 일으켰다.

- 원인: 이 테스트는 "자격증명이 없을 때 업로드가 실패하는지" 검증하는 테스트인데, 이 Codespace에는 `YOUTUBE_CLIENT_ID/SECRET/REFRESH_TOKEN`이 이미 전역 환경변수로 설정되어 있어(이번 세션 앞부분에서 확인함) 자식 프로세스가 그 값을 그대로 물려받았다. 그 결과 `--dry-run` 없이 실제 API가 호출되어 가짜 바이트(`fake-mp4-bytes`)로 만든 파일이 **실제 계정에 private 영상(Video ID: `X2VDy4Xi3I4`, 제목 "제목")으로 업로드**되었고 `data/youtube_publish_log.json`에도 기록이 남았다.
- 이 영상 삭제는 사용자가 YouTube Studio에서 직접 처리하기로 함(요청에 따라 이 세션에서는 삭제 API를 호출하지 않았다).
- **재발 방지 조치**: `tests/test_upload_youtube_short_cli.py`를 수정해 해당 테스트가 `YOUTUBE_CLIENT_ID/SECRET/REFRESH_TOKEN`을 제거한 환경을 명시적으로 주입하도록 고쳤다. 이제 이 환경에 실제 자격증명이 있어도 이 테스트는 항상 "자격증명 없음" 상태를 결정적으로 재현하며, 실제 네트워크 호출을 하지 않는다.
- Shorts 렌더러 자체는 네트워크/YouTube API를 전혀 호출하지 않으므로 이번 사고와 렌더러 코드는 무관하다. 하지만 "기존 테스트를 모두 통과시킨다"는 요청을 안전하게 만족시키기 위해 반드시 고쳐야 했던 부분이라 함께 보고한다.

## 4. 새로 만든 렌더링 구조

- **입력 스키마** (`ShortsScript`): `title`, `subtitle`, `cards`(1~8개), `takeaway`, `brand`(기본값 "티몽의 지혜"). 요청하신 JSON 예시 그대로 사용 가능(`ShortsScript.from_dict`).
- **화면 분할** (`build_screen_plan`): 표지 1장 + 본문 카드 N장 + 마무리 1장. 렌더러는 문장을 새로 나누거나 요약하지 않고, 주어진 `cards` 배열을 그대로 화면 단위로 배치한다(요청하신 "문장 배치만 담당" 원칙).
- **노출 시간 자동 계산**: 공백 제외 글자 수 기반(초당 약 11자) + 화면별 min/max 클램프
  - 표지 2.0~3.0초, 본문 카드 3.0~5.0초, 마무리 3.0~4.0초
  - 카드가 많거나 문장이 길수록 전체 길이가 자동으로 늘어남(테스트로 검증)
- **한국어 줄바꿈**: 실제 폰트 픽셀 폭을 측정해 단어 단위로 줄바꿈하고, 공백 없는 긴 단어는 글자 단위로 강제 줄바꿈한다. 원문 글자를 자르거나 바꾸지 않음(테스트로 "줄바꿈 후 재조합 = 원문"을 검증).
- **자동 폰트 크기 맞춤**: 제목/본문/마무리 각각 후보 크기 목록(큰 것부터)을 시도해 카드 안전 영역에 들어가는 가장 큰 크기를 선택.
- **영상 인코딩**: 화면마다 정지 이미지를 만들고, ffmpeg `xfade` 필터로 화면 사이 0.4초 크로스페이드만 적용(줌/팬/흔들림 없음). H.264, `yuv420p`, `-an`(오디오 스트림 자체를 만들지 않음), `+faststart`.
- **사후 검증**: 생성된 mp4를 ffprobe로 다시 열어 해상도(1080x1920)와 오디오 트랙 없음을 확인하고, 어긋나면 `ShortsRenderError`를 발생시켜 절대 "조용히 잘못된 파일"을 만들지 않도록 함.
- **CLI** (`scripts/render_youtube_short.py`): `--input`, `--output`(디렉터리 자동 생성), `--background`(수동 지정), `--dry-run`(네트워크/렌더링 없이 화면 구성·예상 길이만 출력).

## 5. 브랜드 스타일 구현 내용

- **색감**: 아이보리/베이지/브라운/짙은 회갈색 텍스트 + 노을빛 포인트(테라코타/골드) 팔레트로 통일.
- **폰트**: 제목·마무리는 `NanumMyeongjo`(명조/세리프, "책 읽는 느낌"), 본문은 `NanumGothic`/`NanumBarunGothic`(가독성 우선), 페이지 번호는 명조 볼드.
- **레이아웃**: 반투명 아이보리 카드 패널 + 은은한 그림자를 배경 위에 얹는 "카드뉴스" 구조. 본문 카드는 좌상단에 `01, 02, ...` 페이지 번호, 마무리 화면은 얇은 금색 룰라인으로 강조.
- **브랜드명 표시**: 모든 화면 하단 동일한 위치에 "— 티몽의 지혜 —" 알약형 배지로 일관되게 표시.
- **배경 6종** (모두 Pillow로 프로그램 생성, 외부 이미지 없음 → 저작권 문제 없음):
  `book_desk`(책+나무책상+조명), `tea_book`(책+찻잔), `sunset_book`(노을+책), `hanji_paper`(한지 질감), `classic_cover`(고전 책 표지, 금테두리), `silhouette_warm`(사람 실루엣+따뜻한 배경)
  - 영상 1개당 대본 내용(제목+브랜드) 해시로 배경 스타일 1개를 결정적으로 선택해 "매번 완전히 동일한 배경 반복"은 피하면서도 한 영상 안에서는 통일감을 유지.
  - 화면 순서에 따라 밝기를 미세하게(최대 ±8%) 흔들어 "완전한 정지화면 복사"가 아니게 함.
- **움직임**: 화면 내부는 완전히 정지, 화면 전환은 0.4초 크로스페이드만 사용(줌/팬/흔들림/화려한 전환 없음).

실제 렌더링 결과를 프레임 단위로 육안 확인했다(표지/본문 카드/마무리 3개 화면 모두 확인) — 텍스트 가독성, 브랜드 배지, 페이지 번호, 골드 룰라인 모두 의도대로 표시됨.

## 6. 생성된 테스트 MP4

| 항목 | 값 |
|---|---|
| 경로 | `data/shorts/brand_style_test.mp4` (Git 커밋 대상 아님 - 기존 `.gitignore` 규칙 적용) |
| 원본 대본 | `data/shorts_scripts/example_manman.json` |
| 해상도 | **1080x1920** |
| 길이 | **17.17초** (표지 3.0s + 본문 4카드 3.0~4.2s + 마무리 3.0s, 크로스페이드 겹침 반영) |
| 화면 수 | 6 (표지 1 + 본문 카드 4 + 마무리 1) |
| 오디오 | **없음** (ffprobe로 오디오 스트림 부재 확인) |
| 배경 스타일 | `classic_cover` (대본 내용 기반 자동 선택) |
| 코덱 | H.264 (`libx264`), `yuv420p`, `+faststart` |

## 7. 테스트 결과

새로 추가한 테스트 34건(모두 통과):

- `tests/test_shorts_script.py` (14건): 대본 검증(빈 title/takeaway/cards, cards 개수 초과, 빈 카드 항목, dict 변환), 화면 분할 개수, 카드/문장 길이에 따른 길이 증가, 내용 보존 검증
- `tests/test_shorts_renderer.py` (13건): 한국어 줄바꿈(단문/장문/빈 문자열/공백없는 긴 단어), 줄바꿈 전후 내용 동일성, 배경 스타일 결정성/수동 지정/오류 처리, 화면 이미지 크기(1080x1920)·모드, 배경 6종 전체 렌더 성공, **실제 ffmpeg 렌더 통합 테스트**(해상도/오디오없음/길이>0/카드 수에 따른 길이 증가/출력 디렉터리 자동 생성)
- `tests/test_render_youtube_short_cli.py` (7건): dry-run 정상 동작, 입력파일 없음/JSON 오류/빈 cards/빈 title/알 수 없는 배경 옵션 오류 처리, **실제 렌더링으로 재생 가능한 mp4 생성**

```
$ python -m pytest -q
547 passed, 68 subtests passed in 101.39s
```

전체 저장소 기존 테스트를 포함해 **회귀 없이 전부 통과**(기존 테스트 1건은 3번 항목에서 설명한 안전 문제를 수정해 통과시킴 - 로직 자체는 변경하지 않고 테스트의 환경 격리만 보강함).

## 8. Git 상태 (이 작업 관련 파일 기준)

```
신규(??):
  content_engine/shorts_renderer.py
  content_engine/shorts_script.py
  scripts/render_youtube_short.py
  data/shorts_scripts/example_manman.json
  requirements.txt
  tests/test_shorts_renderer.py
  tests/test_shorts_script.py
  tests/test_render_youtube_short_cli.py
  docs/5-17_shorts_render_engine.md

수정(M):
  content_engine/__init__.py   (새 모듈 export 추가)
  tests/test_upload_youtube_short_cli.py   (자격증명 격리 버그 수정)

커밋 대상 아님(.gitignore):
  data/shorts/brand_style_test.mp4
```

그 외 `.gitignore`, `content_engine/generator.py` 등 기존에 이미 수정되어 있던 파일들은 이번 작업에서 건드리지 않았다(세션 시작 전부터 있던 변경분).

**아직 커밋하지 않았다** — 사용자 확인 후 커밋 여부를 진행할지 알려달라.

## 9. 기존 YouTube 업로더와 연결 가능한지

가능하다. `render_shorts_video()`가 만드는 파일은 `scripts/upload_youtube_short.py`가 요구하는 조건(`.mp4` 확장자, 실존 파일, 1080x1920, 오디오 없음이어도 업로드 자체에는 무관)을 그대로 만족한다. 실제로 다음과 같이 이어 쓸 수 있다(둘 다 무수정):

```bash
python scripts/render_youtube_short.py \
  --input data/shorts_scripts/example_manman.json \
  --output data/shorts/manman_01.mp4

python scripts/upload_youtube_short.py \
  --video data/shorts/manman_01.mp4 \
  --title "좋은 사람이 만만한 사람이 되지 않으려면" \
  --description "티몽의 지혜" \
  --tags "인간관계,티몽의지혜" \
  --privacy private
```

`youtube_publisher.py`/`youtube_upload_history.py`는 이번 작업에서 한 줄도 수정하지 않았다.

## 10. 향후 남은 일 (이번 범위 밖)

- TAK MEDIA `ShortDraft`(title+body 단일 문자열)를 `ShortsScript`(표지/카드/마무리)로 변환하는 어댑터는 아직 없음 — 다음 단계에서 `content_engine/generator.py`가 만드는 문장들을 이 스키마로 매핑하는 작업이 필요.
- 배경 스타일은 현재 6종 고정 세트이며, 추후 "티몽 인터뷰 콘텐츠"용으로 재사용할 때도 동일한 `ShortsScript`/`render_shorts_video()` 인터페이스를 그대로 쓸 수 있음(콘텐츠 도메인에 특화된 로직이 아님).
- 사고로 업로드된 YouTube 영상(`X2VDy4Xi3I4`) 삭제는 사용자가 직접 처리하기로 함.
