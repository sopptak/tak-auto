# 6-52 Shorts V3 Layout Engine — 콘텐츠와 무관한 자동 영상 틀

목표: **콘텐츠 데이터만 바꾸면 같은 화면 틀로 Shorts MP4가 자동 생성**되게 한다.
콘텐츠 품질 개선은 이번 범위가 아니다. 기존 문장은 바꾸지 않았다.

```
CONTENT DATA (V3 문서 JSON)  ─┐
                              ├─> 레이아웃 엔진(프레임 / 줄바꿈 / 폰트 자동 조정 / 이미지 크롭 / overflow 검사)
TEMPLATE (템플릿 JSON)       ─┘        └─> 매 프레임 합성(6-41 kinetic text) + 6-41 합성 음악 -> ffmpeg -> MP4
기존 ShortsScript ─> legacy adapter ─> V3 문서 JSON
```

LOCAL PREVIEW ONLY. YouTube/Threads/Naver/LLM/외부 API 호출 0. Production Archive·ShortsScript·approved 상태 변경 없음.

## 결론 요약

| 항목 | 결과 |
|---|---|
| V3 renderer | READY — `content_engine/shorts_v3_renderer.py` |
| template/content separation | 템플릿 `content_engine/shorts_v3_templates/default.json` / 문서 JSON. 렌더러 코드에 제목·브랜드·좌표·폰트 크기·레이아웃 비율 하드코딩 없음 |
| layouts | **4** — image_top, split, text_focus(필수 3) + image_full(템플릿 데이터만으로 추가) |
| image slot | 경로/alt/출처/기준점/확대, cover 크롭, Ken Burns, 없음·못 읽음이면 placeholder(렌더 실패 없음) |
| source footer | 별도 필드, `출처 · X`, 길면 폰트 축소 후 말줄임 + 경고, 없으면 footer 공간을 CONTENT가 채움 |
| progress | ON/OFF, 위치(footer/top), 높이, 장면 번호(01 / 04) — 템플릿/문서 데이터 |
| audio | 6-41 합성 음악을 그대로 연결(박자 동기). 배경 스타일/BPM/볼륨/fade in·out은 데이터 |
| legacy adapter | ShortsScript -> V3 문서. 글자 보존, 출처 -> footer, lineage 기록 |
| auto layout | 줄바꿈, 폰트 자동 축소(템플릿 범위), 이미지 크롭, 안전영역, overflow 검출 |
| quality gate | 11개 검사, 대표 MP4 11/11 PASS |
| preview MP4 | 1개(content-ec0c38b9a20c424c), 29.0초, 1080x1920, h264 + aac |
| 테스트 | 신규 17개 포함 전체 회귀 — 아래 14장 |

## 1. 현재 구조 (조사 결과)

| 구성 | 파일 | V3에서 |
|---|---|---|
| 6-40 renderer | `content_engine/shorts_renderer.py` — 정적 PNG 카드 + concat, 무음. `ShortsRenderError` | 오류 타입만 재사용 |
| 6-40 ShortsScript | `content_engine/shorts_script.py` — content_id 없는 `title/subtitle/cards/takeaway/brand` 검증 모델. 파일(JSON)에는 `content_id/knowledge_id/platform/created_at`도 있음 | adapter 입력. 스키마 검증 재사용 |
| 6-41 V2 | `shorts_v2_scene.py`(장면 설계·박자 타임라인·읽기 시간), `shorts_v2_renderer.py`(layout_text, kinetic text, Look 팔레트, 비네트/그레인, ffmpeg 파이프), `shorts_v2_audio.py`(합성 음악) | 대부분 재사용(아래) |
| 6-51 preview | `scripts/render_production_shorts_preview.py` — ShortsScript를 V2 장면으로 쪼개 렌더, lineage manifest, 품질검사 | 품질검사를 `media_checks()`로 분리해 V3도 사용 |
| Production Archive | `data/tak_media_archive.json` VALID 2건(approved). 읽기만 함 | 무변경(sha256 `bdc4cdb6…f269`) |
| generation pool | Production에는 없음. staging export 18건(`artifacts/6-48-recovery-staging/data/`) | 대표 preview 입력으로 staging ShortsScript 1개 읽기만 함 |
| publish readiness | `upload_youtube_short.check_shorts_upload_eligibility()` — archive approved + ShortsScript content_id 일치 | 변경 없음 |
| content_id / generation_id / MP4 lineage | 6-51 manifest(sha256) | V3 문서의 `lineage` + 렌더 리포트(document/template/MP4 sha256) |

**V2 코드 변경(동작 동일)**:
- `layout_text()`에 `max_width`, `center_x` 선택 인자 추가(기본값 = 기존 동작). V3 좁은 열(split)에 필요.
- `ShortsV2Renderer._draw_text` 본문을 모듈 함수 `draw_text_block()`으로 옮김(메서드는 위임).
- `render_short_v2`의 ffmpeg 인코딩을 `encode_frames()`로 분리(V3 공용).
- 검증: 이전 커밋의 V2 렌더러와 새 렌더러로 finance/human/ai 3개 spec의 7개 시점 프레임을 비교 — 그레인 레이어(원래 매 실행 무작위)를 같게 두면 **바이트 동일**. 6-41 테스트 20개 통과.

## 2. V3 architecture

```
1080 x 1920 (템플릿 frames, px)
┌──────────────────────────┐  y=260  (안전영역 top)
│ ● 티몽의 지혜  (watermark) │
│ TITLE FRAME  90..910 × 260..540      제목만. 2~3줄, 76→48px 자동
├──────────────────────────┤  y=572
│ CONTENT FRAME 90..910 × 572..1196    layout_type별 IMAGE 슬롯 + HEADLINE/BODY
│   (footer가 비면 ~1296까지 확장)
├──────────────────────────┤  y=1212
│ FOOTER 90..910 × 1212..1360          자막 / 출처 · X / 진행 바 + 01 / 04
└──────────────────────────┘  y=1360 (안전영역 bottom, 아래는 YouTube UI)
```

| 파일 | 역할 |
|---|---|
| `content_engine/shorts_v3_document.py` | 문서 스키마(`ShortsV3Document`, `V3Scene`, `Media`), 템플릿 로드·병합, 검증, 박자 타임라인 |
| `content_engine/shorts_v3_templates/default.json` | 기본 템플릿(화면 틀 전부) |
| `content_engine/shorts_v3_renderer.py` | 레이아웃 엔진(`fit_text`, 프레임 계산, 이미지 슬롯) + 프레임 합성 + `render_short_v3()` + `layout_report()` |
| `content_engine/shorts_v3_adapter.py` | 기존 ShortsScript -> V3 문서 |
| `scripts/render_shorts_v3.py` | CLI: 문서 또는 ShortsScript -> MP4 + 미리보기 + 품질 게이트 리포트 |
| `tests/fixtures/shorts_v3/*.json` | fixture 문서 10개 |
| `tests/test_6_52_shorts_v3.py` | 17 tests |

새 의존성 없음(Pillow, 로컬 ffmpeg).

## 3. Template / content separation

| TEMPLATE(`shorts_v3_templates/default.json`) | CONTENT(문서 JSON) |
|---|---|
| canvas(1080x1920, fps), safe_area | title |
| frames(title/content/footer 좌표) | scenes[] (image, headline, body, subtitle, source, duration, transition, emphasis, audio cue) |
| text 스타일(title/headline/body/subtitle/source/counter/watermark: 크기 범위·최대 줄·굵기·색), gap | lineage |
| layouts(layout_type -> 영역 비율, scrim) | (선택) brand, cta, progress, audio 덮어쓰기 |
| image(모서리, Ken Burns, 출처 크기) | |
| progress / audio / brand / timing 기본값, look(팔레트: V2 `LOOKS`) | |

- 문서의 `brand`(문자열 또는 객체), `cta`, `progress`(bool 또는 객체), `audio`(객체)는 템플릿 값 위에 깊은 병합된다.
- 문서 `"template": "default"` — 다른 이름/경로의 템플릿 파일을 만들면 문서는 그대로 두고 틀만 바꿀 수 있다.
- 테스트 `test_template_values_move_frames_without_code_change`: 템플릿 title frame 값만 바꿔 제목 위치가 바뀌는 것을 확인.

## 4. Scene schema

```json
{
  "schema": "shorts_v3_document/1",
  "id": "content-…",
  "template": "default",
  "title": "AI 의식 연구, 어디까지 허용할까?",
  "brand": "티몽의 지혜",               // 선택, 없으면 템플릿
  "cta": "다음 편에서 또 만나요",        // 선택, 엔드카드 문구
  "progress": {"enabled": true, "position": "footer", "counter": true},   // 선택
  "audio": {"volume": 0.8, "fade_out": 1.0},                              // 선택
  "lineage": {"content_id": "…", "generation_id": "…", "knowledge_id": "…", "source_script": "…", "source_script_sha256": "…"},
  "scenes": [
    {
      "layout": "image_top",                       // image_top | split | text_focus | image_full (템플릿 layouts 키)
      "image": {"path": "images/a.jpg", "alt": "…", "source": "사진 출처"},   // 또는 "image": "images/a.jpg"
      "image_position": "top",                     // center|top|bottom|left|right 또는 [x, y] (0~1)
      "image_scale": 1.2,                          // 1.0~4.0
      "headline": "…", "body": "…",
      "emphasis": ["강조할 구절"],                 // 또는 본문에 *구절*
      "subtitle": "하단 자막 한 줄",
      "source": "BBC",
      "duration": 3.0,                             // 생략 시 글자 수로 자동, 박자 단위로 올림
      "transition": "punch",                       // cut | punch | dissolve
      "audio": ["whoosh"]                          // 효과음 cue(6-41 합성기)
    }
  ]
}
```

모든 필드는 선택이다(장면에는 image/headline/body 중 하나만 있으면 됨). 이미지만 / 텍스트만 / 이미지+텍스트 / 출처 있는 장면 모두 가능.
검증(`V3DocumentError`): 빈 scenes, 빈 title, 템플릿에 없는 layout, 내용 없는 장면, image_scale 범위, 최소 길이(1.2초), **읽기 시간보다 짧은 duration**, 다른 schema.

## 5. Image slot

- 문서 폴더 기준 상대 경로(또는 절대 경로). 이미지만 바꾸고 다시 렌더하면 된다(코드 수정 없음).
- **cover 크롭**: 슬롯 비율로 자르되 `image_position`을 기준점으로, `image_scale`만큼 확대. 가로/세로 이미지 모두 슬롯 비율로 맞춰짐(테스트).
- 장면 동안 느린 줌 인(`image.ken_burns`, 기본 4%), 둥근 모서리(`image.radius`), 등장 페이드/슬라이드.
- `image.source`가 있으면 이미지 오른쪽 아래에 작은 출처 표시(넘치면 말줄임).
- `image_full`은 템플릿 `scrim: true`로 이미지 아래쪽을 어둡게 깔고 글자를 올린다.
- **fallback**: 경로 없음 -> `fallback:missing`, 파일 없음 -> `fallback:missing` + 경고, 이미지가 아닌 파일 -> `fallback:unreadable` + 경고. 모두 팔레트 그라디언트 + 이미지 자리 아이콘으로 대체하고 **렌더는 계속**된다.

## 6. Title frame

- 제목만 표시(본문 없음). 모든 장면에 고정, 엔드카드에서만 숨김. 첫 장면은 첫 프레임부터 보인다(6-41 headstart 재사용).
- `text.title`: 76px에서 시작해 2px씩 줄여 48px까지, 최대 3줄. 그래도 안 들어가면 `V3LayoutError`.
- 브랜드 워터마크는 제목 위 한 줄(`brand.watermark`, `brand.text`). 코드에 "티몽의 지혜"/제목 하드코딩 없음(엔드카드·워터마크 모두 템플릿/문서 값).
- 전환(punch/dissolve)은 CONTENT+FOOTER 영역에만 적용 — 제목은 흔들리지 않는다.

## 7. Content frame

| layout | 템플릿 기하(CONTENT 기준 비율) | 용도 |
|---|---|---|
| image_top | image `[0,0,1,0.52]`, text `[0,0.56,1,1]` | 기본: 위 이미지 + 아래 헤드라인/본문 |
| split | image `[0,0,0.47,1]`, text `[0.52,0,1,1]` | 세로 이미지, 인물 |
| text_focus | text `[0,0,1,1]` | 글 중심 |
| image_full | image `[0,0,1,1]`, text `[0.05,0.55,0.95,0.97]`, scrim | 전체 이미지 위 글 |

- 새 layout_type(quote/book/person/chart 등)은 **템플릿 `layouts`에 영역을 추가**하면 image/text 조합은 코드 수정 없이 동작한다. chart처럼 새 그래픽이 필요한 타입은 렌더러 확장이 필요하다(이번에 만들지 않음).
- 헤드라인(최대 2줄, 64→44px)과 본문(최대 7줄, 54→36px)은 영역 안에서 묶음으로 세로 가운데 정렬.

## 8. Source footer

- `source`는 본문과 분리된 장면 필드. 표시: 템플릿 `text.source.prefix`(`출처 · `) + 값.
- 길면 30→24px로 줄이고, 그래도 넘치면 뒤를 `…`로 줄이고 `source_truncated` 경고(원문은 문서/lineage에 그대로).
- 장면에 source/subtitle이 없으면 footer가 비고 **CONTENT 프레임이 진행 바 바로 위까지 내려온다**(테스트).

## 9. Progress subtitle

- 템플릿 `progress`: `enabled`, `position`(footer | top), `height`, `counter`(장면 번호 `02 / 05`).
- 진행 바는 엔드카드를 뺀 콘텐츠 길이 기준으로 채워진다. 색은 팔레트 강조색(6-41 AI 스타일 진행 바와 같은 느낌).
- 문서에서 `"progress": false` 또는 객체로 덮어쓸 수 있다(fixture 09: `position: top`).
- 하단 자막(`subtitle`)은 장면 필드, footer 윗줄에 표시.

## 10. Audio

- 음악을 새로 만들지 않았다. V3 타임라인(박자 수)을 6-41 합성기가 읽는 장면 목록으로 옮기는 `soundtrack_spec()`만 추가 — **장면 전환이 박자 위에 있다는 6-41 원칙 유지**.
- 템플릿/문서 `audio`: `enabled`, `background`(6-41 스타일: ai/finance/human), `bpm`, `volume`, `fade_in`, `fade_out` -> ffmpeg `loudnorm` 뒤 `volume`/`afade` 필터.
- 장면별 효과음은 문서 `audio` cue, 엔드카드는 chime.

## 11. Legacy ShortsScript adapter

`document_from_shorts_script(data, generation_id=…, source_script=…)`:
- 기존 `ShortsScript.from_dict()` 검증을 그대로 통과해야 한다.
- 카드 하나 = text_focus 장면 하나. 본문 프레임(최소 폰트·최대 줄)에 안 들어가면 **문장 경계에서만** 나눈다(글자 그대로, 테스트).
- `takeaway`의 `출처: URL` -> 모든 장면의 `source`(도메인 표시), 원문 URL은 `lineage.source_url`. 출처 형식이 아닌 takeaway는 마지막 장면 본문으로.
- `lineage`: content_id, generation_id, knowledge_id, source_script 경로, sha256.
- CLI `--shorts-script`는 변환 결과를 `<id>.document.json`으로 저장한 뒤 그 파일로 렌더한다 — 사람이 그 JSON을 고쳐 `--document`로 다시 렌더하면 된다.
- 기존 production data는 migration하지 않았다(읽기만).

## 12. Auto layout

| 상황 | 처리 | fixture |
|---|---|---|
| 제목 짧음 / 김 | 76→48px, 최대 3줄 | 01 / 02 |
| 본문 짧음 / 김 | 54→36px, 최대 7줄 | 01 / 02, 08 |
| 이미지 가로 / 세로 | 슬롯 비율 cover 크롭 + 기준점 | 06, 07 |
| 이미지 없음 / 파일 없음 / 이미지 아님 | placeholder, 렌더 계속 | 03 |
| 출처 없음 / 있음 / 김 | footer 정리 / 표시 / 말줄임 | 05 / 04 |
| 장면 2 / 4 / 5 / 6 | 진행 번호·바 자동 | 09 / 04 / 10 / 05 |
| 최소 폰트로도 넘침 | 자르지 않고 `V3LayoutError`(adapter는 문장 단위로 미리 분할) | 테스트 |

모든 텍스트/이미지 bbox를 `layout_report()`에 모으고, 각 bbox가 **자기 프레임과 안전영역 안**에 있는지 검사한다.

## 13. Quality gate

`scripts/render_shorts_v3.py`의 `quality_gate()` = 6-51 `media_checks()`(분리해 재사용) + V3 구조 검사:

| 검사 | 방법 |
|---|---|
| file_exists_nonempty / decode_clean | 크기, `ffmpeg -v error -f null` 전체 디코드 |
| duration_matches_spec | ffprobe 길이 == 타임라인 합계(±0.2초), > 0 |
| resolution_1080x1920, codec_h264_aac | ffprobe |
| no_blank_scene | 장면마다 MP4에서 프레임 추출, 밝기 표준편차 |
| no_overflow | 제목/워터마크/헤드라인/본문/자막/출처/이미지 bbox ⊂ 프레임 ∩ 안전영역 |
| image_region_ok | 이미지 상태가 loaded 또는 fallback, 영역 크기 > 0 |
| scene_durations_ok | 장면 ≥ 최소 길이, 박자 정수배, 합계 == 전체 |
| audio_ok | 2ch, 오디오 길이 == 영상 길이(±0.2초) |
| lineage_present | 문서 `lineage.content_id` |
| data 무변경 | 렌더 전후 `data/tak_media_archive.json`, `data/shorts_scripts/*` sha256 |

## 14. 테스트

`tests/test_6_52_shorts_v3.py` 17개:
- fixture 10개 각각: schema 로드, 장면마다 실제 프레임 렌더(1080x1920, 빈 화면 아님), overflow 0, 구조 검사(lineage·장면 길이·이미지 영역) 통과.
- 긴 제목 3줄 이내, 장면 수 2/4/5/6, 이미지 fallback 3종, 가로/세로 크롭 비율, 긴 출처 말줄임, footer 정리, emphasis, 문서 덮어쓰기(brand/cta/progress/audio), 박자 타임라인 = 6-41 합성기 타임라인.
- 템플릿 값만 바꿔 프레임 이동, schema 오류 6종, 최소 폰트로도 넘치는 본문은 오류.
- adapter: 글자 보존, 문장 단위 분할, 출처 -> footer, lineage.
- (ffmpeg) 실제 MP4 렌더 + 품질 게이트 PASS.

전체 회귀 결과는 이 문서 끝의 "테스트/보안" 표.

## 15. Preview 결과

입력: `artifacts/6-48-recovery-staging/data/shorts_scripts/content-ec0c38b9a20c424c.json`(6-50 FACT_CHECK_PASSED, staging — Production 아님) -> adapter -> 사람 편집 예시로 **레이아웃 필드만** 두 장면 변경(장면 1 image_top, 장면 2 split, 이미지 경로는 비워 placeholder 슬롯) -> 렌더. 문장은 원문 그대로.

```
C:\Users\soppt\tak-auto\artifacts\6-52-shorts-v3-preview\content-ec0c38b9a20c424c.mp4
C:\Users\soppt\tak-auto\artifacts\6-52-shorts-v3-preview\content-ec0c38b9a20c424c.document.json   (고쳐서 다시 렌더 가능)
C:\Users\soppt\tak-auto\artifacts\6-52-shorts-v3-preview\content-ec0c38b9a20c424c.report.json     (lineage/ffprobe/layout/quality)
C:\Users\soppt\tak-auto\artifacts\6-52-shorts-v3-preview\preview\ , preview\guides\ , frames\
```

| 항목 | 값 |
|---|---|
| size | 21,839,972 bytes |
| duration | 29.0초(장면 11.0 / 8.0 / 4.5 / 3.5 + 엔드카드 2.0, 120 BPM 박자 정수배) |
| video / audio | 1080x1920, 30fps, h264 / aac 2ch 29.0초 |
| mp4 sha256 | `4d045ed88870e879dbcb90bb67f3743e7940b2bca1a4c04df7a6981348081e8b` |
| lineage | content-ec0c38b9a20c424c / gen-20260920T033856-6e8d98fb / knowledge-scout-6d1d0e2fa762, source_script sha256 기록 |
| quality gate | 11/11 PASS, 경고 0 |
| production data | 무변경 |

관찰(콘텐츠가 아니라 엔진 관점):
- 영어 장면이 11초 — 읽기 시간 계산(9자/초)이 한글 기준이라 영어 글자 수를 많이 센다. 필요하면 `duration`을 문서에서 직접 지정하면 된다.
- split 열은 좁아 본문이 36px까지 줄었다. 긴 본문은 text_focus/image_top이 맞다.

## 16. 사람이 수정할 수 있는 지점 (코드 수정 없음)

| 바꾸고 싶은 것 | 고칠 곳 |
|---|---|
| 제목, 본문, 헤드라인, 자막, 강조 | 문서 `title`, `scenes[].headline/body/subtitle/emphasis` |
| 이미지, 위치, 확대, 이미지 출처 | `scenes[].image`, `image_position`, `image_scale` |
| 출처 | `scenes[].source` |
| 카드(장면) 수, 순서, 길이, 전환 | `scenes[]`, `duration`, `transition` |
| 레이아웃 | `scenes[].layout` (새 조합은 템플릿 `layouts`에 추가) |
| 진행 자막 ON/OFF·위치·번호 | 문서/템플릿 `progress` |
| CTA, 브랜드 | 문서 `cta`, `brand` 또는 템플릿 `brand` |
| 음악 스타일·BPM·볼륨·fade | 문서/템플릿 `audio` |
| 프레임 위치, 폰트 크기 범위, 줄 수, 색, 간격, 모서리 | 템플릿 JSON |

운영 V3 문서를 둘 위치는 정하지 않았다(이번에는 preview만 `artifacts/`). 제안: `data/shorts_v3/<content_id>.json` + 이미지 `data/shorts_v3/images/` — 커밋 정책은 `data/shorts_scripts/`와 같이 사람이 결정.

## 하지 않은 것

- quote/book/person/chart 전용 그래픽, 내레이션/TTS, 새 음악, 이미지 자동 수집, 콘텐츠 문장 수정, 5개 전체 재렌더, 운영 데이터 migration.

## 테스트 / 보안 / 외부 호출

| 항목 | 결과 |
|---|---|
| 전체 회귀(`TAK_TEST_FFMPEG` 지정) | **1553 tests OK, skipped 11** (6-51의 1536 + 신규 17) |
| 기존 Windows subprocess 오류 | 이번 실행에서 발생하지 않음. 신규 실패 0 |
| secret scan(자격증명 파일, 토큰/키 패턴) | 0 |
| V3 코드의 네트워크/API import | 0 |
| YouTube / Threads / Naver / LLM / 외부 API | 0 / 0 / 0 / 0 / 0 |
| Production Archive / ShortsScript / approved 상태 | 변경 없음(렌더 전후 sha256 동일) |
