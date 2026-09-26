# 6-53 Shorts V3 Production Layout Engine

LOCAL DEVELOPMENT / PREVIEW ONLY. YouTube / Threads / Naver / LLM / 외부 API 호출 0.
Production Archive, ShortsScript, approved/review/superseded 상태 변경 없음(작업 전후 sha256 동일).
실제 작업 시간: 2026-09-26 17:07 ~ 17:40 KST(약 35분). 요청은 5~6시간이었지만, 조사·구현·검증이 끝난 뒤에 시간을 채우려고 작업을 늘리지 않았다.

## 1. 목표

콘텐츠를 쓰는 것이 아니라 **콘텐츠를 넣으면 Shorts MP4가 나오는 생산 구조**를 만든다.
렌더러 코드를 고치지 않고 데이터(문서 JSON / 템플릿 JSON)만 바꿔 새 Shorts를 만든다. 기존 문장은 고치지 않았다.

## 2. 기존 구조 (baseline, 작업 시작 시점)

| 항목 | 값 |
|---|---|
| branch / HEAD / origin/main | main / `5d4ab23`(6-52) / `5d4ab23` — clean |
| 테스트 baseline | 1553 tests OK, skipped 11(`TAK_TEST_FFMPEG` 지정) |
| Production Archive | `data/tak_media_archive.json` VALID 2건, sha256 `bdc4cdb6…f269` |
| ShortsScript | `data/shorts_scripts/` 2개(`067e8dbb…`, `9c220c5b…`) |
| artifacts | 6-40, 6-41, 6-46, 6-48 staging, 6-51 preview(5 MP4), 6-52 preview(1 MP4) — git 제외 |
| 6-40 renderer | 정적 카드 + concat, 무음. `ShortsRenderError`, `ShortsScript` 스키마(title/subtitle/cards/takeaway/brand) |
| 6-41 V2 | 장면 설계 + 박자 타임라인 + kinetic text(rise/pop/blur) + 합성 음악 + 안전영역 검사 |
| 6-51 | V2로 5개 후보 렌더, lineage manifest, 품질검사(파일/디코드/길이/해상도/코덱/빈 화면) |
| 6-52 V3 | 문서/템플릿 분리, 3+1 레이아웃, 이미지 슬롯, footer, 진행 표시, adapter. 한계: 레이아웃 계산과 프레임 합성이 한 파일, 오류 코드 없음, 캐시/배치 없음, 템플릿 검증 약함, 숫자 일부 하드코딩 |
| 캐시/idempotency | 렌더 캐시 없음. YouTube 업로드 이력만 `artifact_sha256`으로 중복 방지(6-43) |

## 3. V3 architecture (코드 구조)

```
Shorts Content Data ── V3 문서 JSON / 기존 ShortsScript / Production Archive approved
        │  shorts_v3_pipeline.item_from_document / item_from_shorts_script / approved_items
        ▼
Legacy / V3 Content Adapter ── shorts_v3_adapter.document_from_shorts_script
        ▼
V3 Render Document ── shorts_v3_document.V3RenderDocument (검증, 오류 코드, 박자 타임라인)
        ▼
Template Resolver ── shorts_v3_template.resolve_template (로드 + 문서 덮어쓰기 병합 + INVALID_TEMPLATE 검증 + 해시)
        ▼
Layout Engine ── shorts_v3_layout.LayoutEngine (프레임, 영역 handler, 텍스트 엔진, 이미지 슬롯, issues)
        ▼
Media / Text / Source / Progress / Audio ── shorts_v3_renderer.ShortsV3Renderer (프레임 합성, 전환, 6-41 음악)
        ▼
Quality Gate ── shorts_v3_pipeline.structure_issues + media_issues -> gate (PASS/BLOCK, 오류 코드)
        ▼
MP4 + report.json(lineage, render key)  ── render_item / render_batch (캐시, 실패 격리)
```

| 파일 | 줄 | 역할 |
|---|---|---|
| `content_engine/shorts_v3_template.py` (신규) | 130 | `V3Error(code)`, 템플릿 로드/병합/검증/해시 |
| `content_engine/shorts_v3_document.py` | 322 | Render Document, 장면/이미지/출처 스키마, 검증, 타임라인 |
| `content_engine/shorts_v3_layout.py` (신규) | 389 | 레이아웃 엔진(6-52 renderer에서 분리) |
| `content_engine/shorts_v3_renderer.py` | 277 | 프레임 합성만 |
| `content_engine/shorts_v3_pipeline.py` (신규) | 229 | lineage, render key/캐시, 품질 게이트, 배치 |
| `content_engine/shorts_v3_adapter.py` | 87 | ShortsScript -> 문서 |
| `content_engine/shorts_qa.py` (신규) | 70 | ffprobe 요약 + 미디어 검사 — 6-41/6-51/V3 공용(원래 scripts 두 곳에 있던 것을 옮김) |
| `content_engine/shorts_v3_templates/default.json` | | 기본 템플릿 |
| `scripts/render_shorts_v3.py` | 78 | CLI(문서 / ShortsScript / `--approved`, `--validate-only`, `--force`) |

재사용: 6-41 `layout_text`/`draw_text_block`/`encode_frames`/`LOOKS`/`_blit`/비네트, 6-41 합성 음악, 6-51 미디어 검사,
6-19 `publish_eligibility.check_content_supersede`, 5-29 `shorts_script_output_path`, `media_archive.load_archive`, 기존 `ShortsScript.from_dict` 검증.
동일 기능 중복 제거: `probe()`(scripts/render_shorts_v2.py)와 `media_checks()`(6-51 script)를 `shorts_qa.py` 하나로 합치고, 기존 스크립트는 거기서 import한다(동작 동일, 6-41/6-51 테스트 통과).

## 4. Render Document

`V3RenderDocument` = 렌더러가 읽는 유일한 입력. 렌더러는 Production Archive나 ShortsScript를 모른다.

```json
{
  "schema": "shorts_v3_document/1",
  "id": "content-e787c9201b94a948",
  "template": "default",
  "title": "새로운 기술을 마주하는 나의 기준",
  "brand": "티몽의 지혜", "cta": "다음 편에서 또 만나요",          // 선택(템플릿 기본값 덮어쓰기)
  "progress": {"enabled": true, "position": "footer", "mode": "time", "counter": true},   // 선택
  "audio": {"enabled": true, "volume": 1.0, "fade_out": 1.5},                            // 선택
  "expected_duration": null,                                                             // 선택: 선언하면 장면 합계와 맞아야 함
  "lineage": {"content_id": "…", "generation_id": "…", "knowledge_id": "…",
              "source_script": "data/shorts_scripts/….json", "source_script_sha256": "…", "source_url": "…"},
  "scenes": [{
    "layout": "image_top",
    "image": {"path": "images/a.jpg", "alt": "…", "source": "사진 출처", "fit": "cover", "position": [0.5, 0.3], "scale": 1.2},
    "headline": "…", "body": "첫 문단\n\n둘째 문단", "emphasis": ["구절"], "subtitle": "…",
    "source": {"label": "출처", "value": "BBC News / 2026-09-16"},       // 또는 "BBC"
    "duration": 3.5, "transition": "punch", "audio": ["whoosh"]
  }]
}
```

- `content_id`/`generation_id`는 `lineage`에 한 번만 둔다(`doc.content_id`, `doc.generation_id` 속성으로 읽음). 두 곳에 두면 서로 어긋날 수 있다.
- 6-52 문서와 호환: `image_position`/`image_scale`/`image_fit`을 장면에 직접 써도 된다, `source`는 문자열도 된다, `ShortsV3Document`/`V3DocumentError` 이름 유지.
- 오류 코드: `INVALID_DOCUMENT`, `INVALID_DURATION`(0, 음수, 숫자 아님, 범위 밖, 읽기 시간 부족), `INVALID_LAYOUT`, `INVALID_TRANSITION`, `INVALID_IMAGE_SPEC`, `EMPTY_SCENE`, `TIMING_MISMATCH`, `INVALID_TEMPLATE`.

## 5. Template

`content_engine/shorts_v3_templates/default.json`(version 2). 이 파일만 고쳐도 모든 문서의 화면 틀이 바뀐다.

| 키 | 내용 |
|---|---|
| canvas, safe_area, look | 1080x1920/30fps, 안전영역, 팔레트(6-41 `ai`) |
| frames | title / content / footer 좌표 |
| footer_rows | 진행 표시 줄, 출처 줄, 자막 줄 높이, 간격 |
| text | title/headline/body/subtitle/source/counter/watermark: size_max·size_min·max_lines·weight·color·line_gap_min·paragraph_gap·align·top_row·share, 출처 label/separator |
| layouts | layout_type -> image/text 영역 비율, scrim, credit_position, fallback(대체 기하) |
| image | 모서리, Ken Burns, 출처 표시 크기/위치, 기본 fit |
| animation | 헤드라인→본문, 문단, 자막, 출처 등장 지연, 이미지 등장 시간 |
| transition | 기본 전환, punch/dissolve/slide 시간·강도 |
| progress, audio, brand, timing | 진행 표시, 음악 기본값(+ loop/ducking 예약), 브랜드/CTA/엔드카드 크기, 읽기 속도(한글·라틴)·장면 최소/최대 |

`validate_template()` -> `INVALID_TEMPLATE`: 필수 키 누락, canvas, 안전영역 밖 프레임, 프레임 겹침/순서, 영역 비율 범위, 빈 레이아웃, 글자 크기 범위, 오디오 스타일/BPM, 진행 표시 위치/모드, footer 줄 합계, 음수 애니메이션 지연, 없는/깨진 템플릿 파일. 문서가 덮어쓴 결과도 다시 검증한다(문서가 템플릿을 깨뜨릴 수 없음).

이번에 코드에서 템플릿으로 옮긴 값(6-52에서 하드코딩): footer 줄 높이(40/40/64/6/16), 제목 위 워터마크 줄(64), 헤드라인 몫(0.45), 등장 지연(0.2/0.25/0.3/0.5/0.35), 엔드카드 글자 크기(104/40), 이미지 출처 위치.

## 6. Content

사람이 읽고 고치는 JSON(4장). `--shorts-script`로 변환하면 `<out>/<id>.document.json`이 생기고, 그 파일을 고쳐 `--document`로 다시 렌더한다.
이번 preview의 문서: `artifacts/6-53-v3-layout-preview/documents/0N-*.document.json`.

## 7. Frame system

```
y=260  ┌ TITLE   [90,260,910,540]   워터마크 줄(64) + 제목(76→48px, ≤3줄, 정렬 center/top/bottom)
y=572  ├ CONTENT [90,572,910,1196]  layouts 영역 비율로 IMAGE/TEXT. footer가 비면 진행 표시 줄 위까지 확장
y=1212 ├ FOOTER  [90,1212,910,1360] 아래에서 위로: 진행 표시 줄(40) → 출처(40) → 자막(≤64)
y=1360 └ (안전영역 끝, 아래는 YouTube UI)
```
전환은 CONTENT+FOOTER 영역에만 적용 — 제목/워터마크/진행 표시는 고정.

## 8. Layout system

레이아웃 = 템플릿 데이터(영역 비율). 코드는 **영역 종류별 handler**(`REGION_HANDLERS = {"image": …, "text": …}`)만 가진다 — layout_type마다 if/else를 늘리지 않는다.

| layout | 기본 기하 | fallback(글이 넘칠 때) |
|---|---|---|
| image_top | image 0~52%, text 56~100% | image 0~38%, text 42~100% |
| split | image 0~47% 폭, text 52~100% | image 0~36%, text 40~100% |
| text_focus | text 전체 | — |
| image_full | image 전체 + text 55~97%(scrim, 출처 표시 오른쪽 위) | text 30~97% |

조합: 이미지만 / 글만 / 이미지+헤드라인 / 이미지+헤드라인+본문 / 헤드라인+본문 / 이미지+출처 모두 된다(장면에 image/headline/body 중 하나만 있으면 됨).
확장: quote/person/book/comparison처럼 image+text 조합이면 템플릿에 영역만 추가. chart/list처럼 새 그림이 필요하면 `REGION_HANDLERS`에 handler 하나 추가.

## 9. Image slot

- 데이터: `path`, `alt`, `source`, `fit`(cover/contain), `position`(center/top/bottom/left/right 또는 [x,y] 기준점), `scale`(1~4).
- cover: 슬롯 비율로 기준점 주위를 확대해 자름. contain: 이미지 전체 + 흐리게 한 같은 이미지 배경. 가로/세로/정사각형 모두 테스트.
- 이미지 출처 표시는 이미지 모서리(템플릿 `credit_position`).
- 없을 때: 경로 없음 -> placeholder + `IMAGE_SLOT_EMPTY`(경고), 파일 없음 -> placeholder + `IMAGE_MISSING`(오류), 이미지 아님 -> placeholder + `IMAGE_DECODE_FAILED`(오류). **렌더러는 죽지 않는다**; 오류는 품질 게이트가 막는다.
- 이미지 바이트가 render key에 들어간다 — 이미지만 바꿔도 다시 렌더된다.

## 10. Text engine

넘칠 때 순서(문장을 자르거나 요약하지 않음):
1. 폰트 `size_max` → `size_min`(2px 단위)
2. 줄 간격 기본값 → `line_gap_min`
3. 영역 확장: 헤드라인을 최소 크기로 줄여 본문 자리 확보 → 템플릿 `fallback` 기하 → 빈 footer만큼 CONTENT 확장
4. 그래도 안 되면 `TITLE_OVERFLOW` / `HEADLINE_OVERFLOW` / `BODY_OVERFLOW` / `SUBTITLE_OVERFLOW`로 BLOCK(렌더러는 `V3LayoutError(code)`, 파이프라인은 blocked)

지원: 어절 줄바꿈(6-41), 최대 줄 수, 줄 간격, 문단(빈 줄) 간격, 강조(`*구절*` 또는 `emphasis`), 제목 세로 정렬, 모든 bbox의 프레임·안전영역 포함 검사(`FRAME_VIOLATION`, `SAFE_AREA_VIOLATION`).
읽기 시간: 한글 9자/초, 라틴 문자 15자/초(템플릿). 6-52에서 영어 장면이 11초로 길어지던 문제를 줄였다.

## 11. Source footer

`source`: 문자열 또는 `{label, value}` → `{label}{separator}{value}`(기본 `출처 · BBC`). 긴 출처(`출처 · BBC News / 2026-09-16`, URL)는 30→24px 축소 뒤 말줄임 + `SOURCE_TRUNCATED` 경고(원문은 문서/lineage에 그대로). 한 줄도 불가능하면 `SOURCE_OVERFLOW`. 출처·자막이 없으면 footer가 비고 CONTENT가 내려온다.

## 12. Progress

템플릿/문서 `progress`: `enabled`, `position`(footer/top), `mode`(time: 시간 기준 6-41 진행 바 / scene: 장면 단위), `bar`, `counter`(`01 / 04`), `height`. 엔드카드 동안은 숨김.

## 13. Audio

6-41 합성 음악을 그대로 쓴다(`soundtrack_spec()`이 V3 타임라인의 박자 수를 6-41 합성기 장면 목록으로 옮김 — 장면 전환이 박자 위). 데이터: `enabled`, `background`(ai/finance/human), `bpm`, `volume`, `fade_in`, `fade_out` → ffmpeg `loudnorm` 뒤 `volume`/`afade`.
`loop`, `ducking`은 스키마만 예약: 합성 음악은 항상 영상 길이와 같아 loop가 필요 없고, 내레이션 트랙이 없어 ducking 대상이 없다. TTS/내레이션이 생기면 `audio_filter()`에 sidechain을 붙이는 자리다.

## 14. Transition

템플릿 `transition.default`(punch) + 장면 `transition`: `cut`, `punch`(6-41 줌 펀치), `dissolve`/`fade`(별칭), `slide`(오른쪽에서 밀려 들어옴). 시간·강도는 템플릿. 과한 효과는 넣지 않았다.

## 15. Legacy adapter

`ShortsScript`(변경 없음) → `document_from_shorts_script()` → 문서 dict. 카드 = text_focus 장면, 본문 프레임에 안 들어가면 문장 경계에서만 나눔, `출처: URL` → 모든 장면 footer(도메인), 원문 URL은 lineage. 기존 approved 콘텐츠를 migration하지 않는다(읽기만).

### 기존 5개 후보 adapter validation (렌더 없음)

`artifacts/6-53-v3-layout-preview/candidate_validation.json`

| content_id | 출처 | generation_id | 결과 | 장면 | 길이 | ShortsScript sha256(6-51과 일치) |
|---|---|---|---|---|---|---|
| content-e787c9201b94a948 | data/shorts_scripts | (legacy) | **PASS** | 2 | 11.5s | 067e8dbbba11… |
| content-3ae2d78568210164 | data/shorts_scripts | (legacy) | **PASS** | 2 | 13.0s | 9c220c5b2f20… |
| content-ec0c38b9a20c424c | 6-48 staging | gen-20260920T033856-6e8d98fb | **PASS** | 4 | 25.0s | e2a6d05734c2… |
| content-e3b8d986ea6db98e | 6-48 staging | gen-20260920T033856-6e8d98fb | **PASS** | 3 | 24.0s | 3655a9c6f7fd… |
| content-91869ed8be17f3f3 | 6-48 staging | gen-20260920T033856-6e8d98fb | **PASS** | 2 | 24.5s | b5e12b374bb5… |

5/5 V3 schema + 레이아웃 + lineage 검증 PASS. data/ 무변경.

## 16. Lineage

리포트(`<name>.report.json`)의 `lineage`: `content_id`, `generation_id`, `knowledge_id`, `source_script`, `source_script_sha256`, `source_url`, `document_sha256`(문서 JSON 정규화 해시), `template_id`, `template_sha256`(문서 덮어쓰기까지 반영한 최종 템플릿 해시), `assets`(이미지 파일 해시), `renderer_version`, `render_key`, `mp4_sha256`.
같은 콘텐츠라도 템플릿이 바뀌면 `template_sha256`과 `render_key`가 바뀌어 다른 렌더 결과로 구분된다(이번 작업 중 템플릿 수정 뒤 4개 preview의 key가 모두 바뀐 것으로 확인).

## 17. Render key / cache

- 기존 캐시 구조 없음 → 최소 설계: `render_key = sha256(renderer_version, document_sha256, template_sha256, 이미지 해시, fps)`.
- `render_item()`: 같은 이름의 리포트가 있고 key가 같고 품질 PASS이고 MP4 해시가 리포트와 같으면 **다시 렌더하지 않음**(`cached`). `--force`로 무시.
- 실측: 4개 렌더 90초 → 같은 명령 재실행 1초(`cached` 4).
- **결정적 출력**: 6-52까지는 그레인을 시드 없이 만들어 같은 입력도 MP4 바이트가 달랐다. V3 그레인을 문서 id 시드로 고정 → 같은 입력 = 같은 MP4(테스트로 확인). V2는 건드리지 않았다.
- `RENDERER_VERSION`(현재 `shorts_v3/6-53.3`)은 렌더 결과가 바뀌는 코드 변경 때 올린다(분산 캐시는 만들지 않음).

## 18. Quality gate

`gate()` → `{"status": "PASS"|"BLOCK", "errors", "warnings", "codes"}`. 렌더 전 오류가 있으면 MP4를 만들지 않는다(blocked).

| 단계 | 오류 코드 |
|---|---|
| 템플릿 | INVALID_TEMPLATE |
| 문서 | INVALID_DOCUMENT, INVALID_DURATION, INVALID_LAYOUT, INVALID_TRANSITION, INVALID_IMAGE_SPEC, EMPTY_SCENE, TIMING_MISMATCH |
| 레이아웃 | TITLE_OVERFLOW, HEADLINE_OVERFLOW, BODY_OVERFLOW, SUBTITLE_OVERFLOW, SOURCE_OVERFLOW, SAFE_AREA_VIOLATION, FRAME_VIOLATION |
| 에셋 | IMAGE_MISSING, IMAGE_DECODE_FAILED |
| 구조 | SCENE_TIMING_INVALID, LINEAGE_MISSING |
| 미디어(렌더 후) | FILE_MISSING, DECODE_ERROR, DURATION_MISMATCH, RESOLUTION_MISMATCH, CODEC_MISMATCH, AUDIO_MISSING, AUDIO_MISMATCH, BLANK_FRAME |
| 배치 | SHORTS_SCRIPT_MISSING, INVALID_SHORTS_SCRIPT, RENDER_EXCEPTION |
| 경고(PASS 유지) | SOURCE_TRUNCATED, IMAGE_SLOT_EMPTY |

## 19. Batch render

```python
items = approved_items("data/tak_media_archive.json", "data/shorts_scripts")   # 읽기 전용
summary = render_batch(items, out_dir, ffmpeg=..., validate_only=False, force=False)
# summary = {"counts": {...}, "results": [{name, content_id, generation_id, status, reasons, errors, output, report, render_key, lineage}]}
```
- `approved_items()`: platform=shorts, review_status=approved, supersede 차단 아님(6-19 기준) → ShortsScript 경로(5-29 규칙) → adapter.
- CLI: `py scripts/render_shorts_v3.py --approved --validate-only --out <dir>` → 검증만, 그다음 `--validate-only` 없이 렌더.
- status: `validated` / `blocked`(렌더 전 차단) / `cached` / `success` / `failed`(렌더 후 게이트 실패 또는 예외). `batch_summary.json` 저장.

## 20. Failure isolation

항목마다 `try`: `V3Error` → blocked(코드), 그 밖의 예외 → failed(`RENDER_EXCEPTION`, 짧은 traceback). 다음 항목은 계속된다.
통합 테스트: 5개 중 인코더 예외 1, 제목 overflow 1, 이미지 없음 1 → 나머지 2개 MP4 정상, overflow는 MP4를 만들지 않음, summary `{"success": 2, "failed": 1, "blocked": 2}`.

## 21. Test matrix

`tests/test_6_53_shorts_v3_engine.py`(단위 22, ffmpeg 없음) + `tests/test_6_53_shorts_v3_integration.py`(통합 5, ffmpeg) + 6-52 테스트 17(새 API로 갱신).

| # | 항목 | 테스트 |
|---|---|---|
| 1 | 짧은 제목 | 6-52 fixture 01, `test_short_and_long_title…`("A") |
| 2 | 긴 제목 | 6-52 fixture 02, `test_short_and_long_title…`, TITLE_OVERFLOW |
| 3 | 짧은 본문 | fixture 01, 통합 테스트 문서 |
| 4 | 긴 본문 | fixture 02/08, `test_fallback_geometry…`, BODY_OVERFLOW |
| 5 | 이미지 있음 | fixture 06/07, `image_full`, `square_contain` |
| 6 | 이미지 없음 | fixture 03, `test_image_slot_status_codes` |
| 7 | landscape | fixture 06, `square_contain`(가로 contain) |
| 8 | portrait | fixture 07, `image_full` 2번 장면 |
| + | square / contain / 기준점 | `test_square_contain_and_focal_point` |
| 9 | source 있음 | fixture 04, `paragraphs_source_object`(객체형) |
| 10 | source 없음 | fixture 05(footer 정리) |
| 11 | 2 scenes | fixture 09 |
| 12 | 5 scenes | fixture 10 |
| 13~16 | image_top / split / text_focus / image_full | fixture 06 / 07 / 08 / `image_full`, 4개 preview |
| 17 | audio ON (+OFF) | `test_audio_on_passes_gate_with_lineage`, `test_audio_off_renders_silent_video` |
| 18 | progress ON (+OFF/top/scene) | `test_progress_modes`, `paragraphs_source_object` |
| 19 | invalid template | `test_invalid_templates`(13종), `test_missing_or_broken_template_file`, `test_document_cannot_break_template` |
| 20 | overflow detection | `test_overflow_codes`(4종), `test_line_gap_tightens_before_blocking` |
| 경계값 | 제목 1자, 매우 긴 제목/본문/출처, duration 0/음수/문자/범위 밖, 경로 없음/잘못된 경로, scene 1/0개, 합계 불일치 | `DocumentValidationTests`, `test_source_object_label_and_long_source` |
| 파이프라인 | render key, lineage, 캐시, force, 결정적 MP4, 배치 격리(검증/렌더), approved archive 읽기 전용 | `LineageBatchTests`, 통합 테스트 |

## 22. Preview 결과

`C:\Users\soppt\tak-auto\artifacts\6-53-v3-layout-preview\` — 같은 콘텐츠(content-e787c9201b94a948, Production approved), 레이아웃만 다름.
이미지 슬롯에는 **로컬에서 그린 샘플 추상 이미지**(`documents/sample_images/sample_abstract.png`)를 넣었다 — 실제 사진/콘텐츠가 아니다. 문장은 원문 그대로.

| filename | content_id | generation_id | template | layout | duration | resolution | video/audio | size | sha256 | 게이트 |
|---|---|---|---|---|---|---|---|---|---|---|
| 01-image-top.mp4 | content-e787c9201b94a948 | (legacy) | default | image_top | 11.5s | 1080x1920 30fps | h264 / aac 2ch | 4,771,397 | `51c0c5517343048d4d76a6c1f7da645b253d57321922cc553f36eaa8d100da10` | PASS |
| 02-split.mp4 | 〃 | 〃 | default | split | 11.5s | 〃 | 〃 | 4,756,211 | `8f6ce8dad1492641b16d17fc87ea0ce8e02728e299a1d3325c1e1cab0bd2b408` | PASS |
| 03-text-focus.mp4 | 〃 | 〃 | default | text_focus | 11.5s | 〃 | 〃 | 4,793,781 | `9132875d92f2fdef30055711535c1b3a55f251f6efc71531d2fb7e925db2e11c` | PASS |
| 04-image-full.mp4 | 〃 | 〃 | default | image_full | 11.5s | 〃 | 〃 | 4,778,756 | `df07f10204853f389c5836f74711fd9b892f01380feab29940c3f6ca9c7d8d3e` | PASS |

- template_sha256 `9e744c1e92554285…`(4개 공통), ShortsScript sha256 `067e8dbbba11…`, render key/문서 해시는 각 `.report.json`.
- `contact_sheet.png`: 위 줄 = 네 레이아웃의 첫 장면 프레임(MP4에서 추출), 아래 줄 = 같은 프레임에 TITLE(빨강)/CONTENT(파랑)/FOOTER(라임)/안전영역(흰색) 테두리.
- preview 중 발견·수정: image_full에서 이미지 출처 표시가 본문과 겹침 → 템플릿 `credit_position: top_right`로 해결(코드는 위치를 읽기만).
- 11.5초로 짧은 이유: 이 콘텐츠의 카드가 2장뿐이다. 길이를 늘리려고 문장을 만들지 않았다.
- 그 밖의 산출물: `documents/`(렌더에 쓴 문서 4개), `candidate_validation.json`, `batch_summary.json`, `frames/`.

## 23. 향후 editor 연결 지점

JSON 편집 → 같은 렌더러. Editor(또는 DB)는 문서 JSON만 만들면 된다.
- 편집 가능하게 노출: `title`, `brand`, `cta`, `progress.{enabled,position,mode,counter}`, `audio.{enabled,background,volume,fade_in,fade_out}`, 장면별 `layout`(선택지 = 템플릿 `layouts` 키), `image.{path,alt,source,fit,position,scale}`, `headline`, `body`, `emphasis`, `subtitle`, `source.{label,value}`, `duration`, `transition`, 장면 추가/삭제/순서.
- 읽기 전용으로 보여줄 것: `lineage`, 템플릿 id, 계산된 장면 길이/전체 길이, 품질 게이트 결과(오류 코드 → 해당 장면 표시).
- 실시간 검사: `LayoutEngine(doc).report()`는 렌더 없이 수백 ms 안에 돈다 → 편집 중 overflow/이미지 문제를 바로 보여줄 수 있다.
- 저장 위치 제안: `data/shorts_v3/<content_id>.json` + `data/shorts_v3/images/`(커밋 정책은 사람이 결정). 이번에는 만들지 않았다.

## 24. 향후 이미지 자동 수집 연결 지점

- 현재 인터페이스: 장면 `image`(path/alt/source/fit/position/scale). 수집기는 파일을 저장하고 이 필드만 채우면 된다. render key가 이미지 바이트를 해시하므로 교체하면 자동으로 다시 렌더된다.
- 추가가 필요한 필드: `license`, `author`, `url`(원본), `retrieved_at`, `provider`, `query` — 저작권/출처 추적용. 게이트에 `IMAGE_LICENSE_MISSING`(외부 이미지인데 license 없음)을 추가하는 자리.
- 추천 구조: `ImageProvider.resolve(scene, document) -> Media`를 adapter 다음·검증 전에 두는 단계(렌더러는 그대로).

## 25. 하지 않은 작업 (다음 단계 후보)

콘텐츠 문장 대량 수정, 새 콘텐츠 작성, 자동 뉴스 검색, 이미지 웹 자동 수집, TTS/내레이션, 새 음악 생성, YouTube 업로드, Threads 업로드, Naver 업로드, Production Archive migration, Dashboard editor UI, 병렬/분산 렌더, quote/chart/list 전용 그래픽.

## 추가 조사 (READ-ONLY, 41장)

**A. 이미지 자동 수집에 필요한 interface** — 24장. 요약: Media에 license/author/url/retrieved_at/provider 필드 추가, adapter와 검증 사이에 `ImageProvider` 단계, 게이트에 license 검사.

**B. Dashboard Editor에 노출할 field** — 23장. 템플릿은 editor에서 고치지 않고 선택만 하게 두는 편이 안전하다(템플릿 수정 = 모든 영상의 key 변경).

**C. approved Shorts 10~20개 배치 interface** — `approved_items()` + `render_batch()`를 두 단계로: ① `--approved --validate-only`로 전부 검증(수 초) → ② 통과한 것만 렌더. 순차 처리 기준 11초 영상 1개 약 22초(4개 90초) → 20개 약 8~15분(장면 길이에 비례). 다음 단계에서 항목별 프로세스 풀(`concurrent.futures.ProcessPoolExecutor`)을 붙이기 쉬운 구조(항목끼리 공유 상태 없음, 출력 경로가 항목 이름별).

**D. 가장 큰 유지보수 위험**
1. V3가 6-41 모듈의 비공개 함수(`_blit`, `_font`, `_gradient`, `_radial_mask`, `_clamp`)에 기대고 있다 — V2를 고치면 V3가 깨질 수 있다. 공용 그래픽 모듈로 옮기는 것이 다음 정리 후보.
2. 폰트 경로가 `C:/Windows/Fonts`로 고정(6-41) — Linux/GitHub Actions에서는 폰트 테스트가 skip되고 렌더가 불가능하다.
3. `RENDERER_VERSION`을 사람이 올려야 한다 — 렌더 코드를 바꾸고 안 올리면 예전 캐시가 재사용될 수 있다(문서/템플릿/이미지 변경은 자동 반영).
4. Pillow 프레임 합성 CPU 비용(프레임당 수십 ms) — 대량 렌더 시간의 대부분.
5. V3 CLI가 6-51 스크립트의 `data_fingerprint()`를 import한다(스크립트 간 결합).

**E. 콘텐츠와 renderer 결합이 남은 곳**
- adapter의 출처 표시가 URL 도메인(`bbc.co.uk`) — 매체 이름 변환 표 없음(콘텐츠 쪽에서 `source.value`로 고치면 됨).
- 배경 점 무늬, 비네트 강도, 그레인, scrim 곡선, 엔드카드 박스 여백, 워터마크 점 모양이 아직 코드 값(스타일 요소 — 템플릿 `look` 확장 후보).
- 효과음 cue 이름은 6-41 합성기 어휘(whoosh/impact/pop/riser/chime)에 묶여 있다.
- 팔레트는 템플릿이 이름(`look: ai`)으로만 고른다 — 색을 템플릿에서 직접 정의하려면 `LOOKS` 대신 템플릿 색 필드가 필요하다.
- 콘텐츠 → 렌더러 방향의 결합(제목/본문 길이 때문에 코드를 고치는 것)은 없다: 넘침은 템플릿 범위와 오류 코드로 처리된다.

## 테스트 / 보안 / 외부 호출

| 항목 | 결과 |
|---|---|
| baseline(시작) | 1553 tests OK, skipped 11 |
| 최종 전체 회귀 | **1580 tests OK, skipped 11** (baseline 1553 + 신규 27, 새 실패 0) |
| 신규 | 27 tests(단위 22, 통합 5). 6-52 테스트 17개는 새 API(문단 블록 목록, `fallback:empty`, 오류 코드 게이트, 프레임 겹침 금지)에 맞춰 기대값 갱신 — 삭제/skip 없음 |
| KNOWN ENVIRONMENT ERROR | 이번 실행들에서 발생하지 않음(과거 Windows subprocess `stdout=None` 9건) |
| secret scan | 추적·미추적 파일 + 6-53 artifacts: 토큰/키 패턴 0, 자격증명 파일 0. 새 코드에 환경변수/토큰 읽기·출력 없음, 네트워크 import 없음 |
| YouTube / Threads / Naver / LLM / 외부 API | 0 / 0 / 0 / 0 / 0 |
| Production mutation | NO — `data/tak_media_archive.json` `bdc4cdb6…f269`, ShortsScript 2개 해시 동일(CLI가 매 실행 전후 확인) |
