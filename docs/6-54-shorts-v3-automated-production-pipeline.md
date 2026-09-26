# 6-54 Shorts V3 Automated Production Pipeline

LOCAL DEVELOPMENT / PREVIEW ONLY. YouTube / Threads / Naver / LLM / 외부 API 호출 0.
Production Archive, ShortsScript, approved/review/superseded 상태 변경 없음(26장).
실제 작업 시간: 2026-09-26 17:45 ~ 18:37 KST(약 52분). 요청은 5~6시간이었다. 체크리스트와 추가 조사(37장)를 끝낸 뒤 시간을 채우려고 작업을 늘리지 않았다.

## 1. 목적

6-53의 V3 엔진을 **여러 콘텐츠에 반복 실행되는 생산 공정**으로 연결한다:
입력 → adapter → Render Document → asset 확인 → 템플릿 → 레이아웃 → 렌더 → 품질 게이트 → MP4 → manifest/보고서.

## 2. Architecture

```
resolve_content()        V3 문서 JSON | 기존 ShortsScript | 사람이 만든 fixture | dict | archive approved  → ContentItem
build_render_document()  → V3RenderDocument (스키마 + 템플릿 검증, 오류 코드)
resolve_assets()         → {장면: ResolvedAsset}  (존재/형식/디코드/크기/비율/sha256, 캐시)      [shorts_v3_assets]
validate()               → LayoutEngine(배치) + structure_issues(타이밍/lineage)                   [shorts_v3_layout]
(idempotency)            render key가 같고 MP4가 그대로면 SKIP(ALREADY_RENDERED), 손상/삭제면 재렌더
render()                 → MP4 (프레임 합성 + 6-41 음악 + x264)                                  [shorts_v3_renderer]
inspect_media()          → 규격/디코드/길이/빈 화면/전환 프레임/프레임 수/오디오 레벨·fade          [shorts_qa]
quality_gate()           → PASS/BLOCK + 오류 코드
write_manifest()         → <name>.manifest.json
render_batch()           → 항목별 격리 + batch_manifest.json + batch_report.md                    [shorts_v3_pipeline]
```

| 파일 | 이번 변경 |
|---|---|
| `content_engine/shorts_v3_assets.py` | **신규** — AssetRequest/ResolvedAsset/AssetResolver, `resolve_assets`, `resolve_asset`, `AssetProvider`(향후 자동 수집 인터페이스) |
| `content_engine/shorts_v3_contract.py` | **신규** — 편집기용 `editable_fields()`, `check_document()`(렌더 없는 검사) |
| `content_engine/shorts_v3_pipeline.py` | 단계 함수로 재구성, manifest, SKIP/재렌더, 배치 manifest + MD 보고서, 성능 수치, publish contract |
| `content_engine/shorts_v3_layout.py` | 이미지 슬롯이 resolver 결과 사용(`ASSET_*` 코드, 템플릿 정책), 진행 표시 geometry 일원화 + `PROGRESS_OVERLAP` |
| `content_engine/shorts_v3_document.py` | 기준점 `{x, y}`, `fit: crop`(cover 별칭), URL 출처 → 읽을 수 있는 이름(`readable_source`) |
| `content_engine/shorts_v3_renderer.py` | 엔진 주입, 성능 최적화(30장 32절), 인코더 설정·정확한 길이 |
| `content_engine/shorts_v2_renderer.py` | `encode_frames()`에 `preset`/`crf`/`exact_length` 선택 인자(기본값 = 기존 동작, V2 출력 불변) |
| `content_engine/shorts_qa.py` | ffprobe `nb_frames`, `audio_levels()` |
| `content_engine/shorts_v3_templates/default.json` | `encoder`, `image.formats/min_width/min_height/on_missing`, `source_labels` |
| `content_engine/shorts_v3_adapter.py` | 출처를 원문 URL로 보존(화면에는 `출처 · BBC`) |
| `scripts/render_shorts_v3.py` | `--generation-id`를 여러 `--shorts-script`와 순서대로 짝지음, 배치 요약 출력 |

## 3. Input

| 입력 | 함수 | 비고 |
|---|---|---|
| A. 기존 ShortsScript | `item_from_shorts_script(path, generation_id=)` | adapter로 변환, 원본 sha256 기록 |
| B. V3 Render Document JSON | `item_from_document(path)` | 문서 파일 sha256 기록 |
| C. 사람이 만든 local fixture | 같음(B) | `tests/fixtures/shorts_v3*/` |
| dict / 경로 자동 판별 | `resolve_content(x)` | `cards`가 있고 `scenes`가 없으면 ShortsScript |
| Production approved | `approved_items(archive, scripts_dir)` | 읽기 전용, 6-19 supersede 기준 재사용 |

모든 입력은 `V3RenderDocument`로 정규화된다. 읽을 수 없는 입력은 예외 대신 오류 코드가 담긴 항목(`INVALID_DOCUMENT`, `SHORTS_SCRIPT_MISSING`, `INVALID_SHORTS_SCRIPT`)이 된다.

## 4. Adapter

6-52/6-53 adapter 유지. 변경: `출처: URL`의 **원문 URL을 장면 source에 그대로** 두고, 화면 표시는 템플릿 `source_labels`로 `BBC`가 된다(6-53까지는 도메인 `bbc.co.uk`를 데이터에 적었다).

## 5. RenderDocument

6-53 스키마 + 이번 추가: `image.position: {"x": 0.5, "y": 0.3}`, `image.fit: "crop"`(= cover). 잘못된 값(숫자가 아닌 좌표, 문자 scale)은 `INVALID_IMAGE_SPEC`.

## 6. Asset resolver

`AssetResolver.resolve(AssetRequest)`: ① 경로 ② 존재 ③ 형식(템플릿 `image.formats`: PNG/JPEG/WEBP) ④ 디코드(`verify()` + `load()` — 잘린 파일 검출) ⑤ 크기(`min_width/min_height` 320) ⑥ 비율·방향 ⑦ sha256. crop/position은 레이아웃 엔진이 적용.

| 결과 | 코드 | 게이트 |
|---|---|---|
| 파일 없음 | `ASSET_MISSING` | 템플릿 `image.on_missing: block`(기본)이면 BLOCK, `fallback`이면 경고 + placeholder |
| 형식 아님(GIF 등) | `ASSET_UNSUPPORTED_FORMAT` | 〃 |
| 디코드 실패/잘린 파일 | `ASSET_DECODE_FAILED` | 〃 |
| 너무 작음 | `ASSET_TOO_SMALL` | 〃 |
| 경로 없는 슬롯 | `IMAGE_SLOT_EMPTY`(경고) | 레이아웃이 `image_required: true`면 `ASSET_REQUIRED`(BLOCK) |

렌더러는 어떤 경우에도 crash하지 않는다(placeholder로 그림). BLOCK이면 파이프라인이 **렌더 전에** 멈춰 MP4를 만들지 않는다.

**메타데이터**(`ResolvedAsset`): path, resolved_path, filename, width, height, aspect_ratio, orientation(portrait/landscape/square ±5%), format, bytes, sha256, alt, source, status, code, message. manifest `assets`에 장면별로 기록.

**캐시**: (경로, 크기, 수정시각) → sha256 한 번만 계산, sha256 → 디코드 이미지 LRU(16). 배치 안에서 resolver를 공유 — 실측: fixture 배치에서 이미지 3개를 문서 5개가 써도 해시 3회·디코드 3회.

## 7. Image system

| fit | 동작 |
|---|---|
| cover / crop | 슬롯 비율로 기준점 주위를 `scale`배 확대해 자름 |
| contain | 이미지 전체 + 같은 이미지를 흐리게 한 배경 |

기준점: `center/top/bottom/left/right` 또는 `{x, y}`/`[x, y]`(0~1). portrait/landscape/square × image_top/split/image_full 9조합을 모두 렌더(23장)하고, 테스트는 사분면 색 이미지로 기준점이 고른 사분면이 슬롯 가운데 오는지, contain이 네 색을 모두 보여주는지 확인한다.

## 8. Text system

6-53 엔진(폰트 축소 → 줄 간격 → 영역 확장/대체 기하 → BLOCK) 유지. 이번에 실제로 확인:
- 제목 1/2/3줄 각각 줄 수와 세로 가운데 정렬(±2px), 매우 긴 제목 `TITLE_OVERFLOW`.
- 본문 짧음/중간 → 기본 기하, 긴 본문 → 대체 기하(`variant: fallback`), 매우 긴 본문 → `BODY_OVERFLOW`. 문장을 자르거나 요약하지 않는다.
- long_text fixture를 실제 MP4로 렌더(42초, 4장면): 3줄 제목, 긴 본문 최소 폰트, 긴 출처 말줄임.

## 9. Source

`source`는 문자열 또는 `{label, value}`. URL이면 화면에는 템플릿 `source_labels`(도메인 → 이름: BBC, Reuters, AP, Euronews, TechCrunch, Fortune, Yahoo; 서브도메인 포함)의 이름, 없으면 도메인만. 원문 URL은 문서/lineage에 남는다. 테스트: BBC, Reuters URL, 책 제목, 모르는 도메인, 긴 출처(말줄임 + `SOURCE_TRUNCATED` 경고), 출처 없음(footer 정리).

## 10. Progress

진행 바/번호 위치를 엔진의 `progress_boxes()` 하나에서 계산하고 렌더러와 검사가 같은 값을 쓴다. 제목·본문·이미지·출처·자막 bbox와 겹치면 `PROGRESS_OVERLAP`, 안전영역 밖이면 `SAFE_AREA_VIOLATION`.
**이 검사로 6-53의 실제 결함을 찾았다**: `position: top`일 때 장면 번호가 바 *위*(안전영역 밖, y≈224)에 그려지고 있었다 → 바 아래로 옮겼다.
테스트: 장면 1~6개 × footer/top 겹침 없음, OFF면 상자 없음, 줄 높이를 줄인 템플릿에서 겹침 검출.

## 11. Audio

6-41 합성 음악 그대로(새 음악 없음). 검사 추가(`audio_levels()`: 모노 PCM 0.1초 구간 RMS):
- 존재/코덱/2ch, 오디오 길이 = 영상 길이(±0.2초), 무음이면 `AUDIO_SILENT`, `fade_out`이 있는데 마지막 0.3초가 가운데의 절반 이상이면 `AUDIO_FADE_MISSING`.
- 모든 preview: middle ≈ 0.15, tail ≈ 0.001(fade 확인). `volume: 0.5` → middle 비율 0.35~0.65(테스트).
- **placeholder 조사**: `loop` — 합성 음악은 항상 영상 길이와 같게 만들어져 반복이 필요 없다(파일 배경음악이 생길 때 `-stream_loop`로 구현할 자리). `ducking` — 내레이션 트랙이 없어 대상이 없다. 둘 다 스키마만 유지하고 구현하지 않았다(구현할 입력이 없음).

## 12. Transition

cut / fade(=dissolve) / slide / punch를 한 영상(transitions fixture, 5장면)에서 실제 렌더. `inspect_media()`가 각 전환의 0.05초·중간 시점 프레임을 MP4에서 뽑아 빈/검은 화면을 검사하고, 프레임 수·오디오 길이를 확인 → PASS. `transitions_contact_sheet.png`.

**발견·수정**: 모든 V3 MP4가 **마지막 프레임 1개가 빠져** 있었다(90 → 89). ffmpeg `-shortest`가 오디오 경계에서 영상 마지막 프레임을 떨어뜨린다. 6-53 게이트는 ±1 허용이라 못 잡았다. V3는 `-t <프레임수/fps>`로 길이를 고정(`exact_length=True`)하고, 프레임 수 검사를 정확 일치로 바꿨다(`FRAME_COUNT_MISMATCH`). V2(6-41)는 기본값 그대로.

## 13. Batch render

```python
summary = render_batch([doc_path, shorts_script_path, doc_dict, ContentItem(...), ...], out_dir, ffmpeg=..., validate_only=False, force=False)
# {"schema": "shorts_v3_batch/1", "total", "success", "failed", "counts": {success/skipped/validated/blocked/failed},
#  "performance": {...}, "results": [{name, content_id, generation_id, status, error_code, reasons, output_path,
#                                    manifest_path, render_key, template, layouts, duration, sha256, bytes, render_seconds, lineage}]}
```
`success` = success + skipped + validated, `failed` = blocked + failed. CLI: `py scripts/render_shorts_v3.py --document … --shorts-script … --generation-id … --approved [--validate-only] [--force] --out … --ffmpeg …`.

## 14. Failure isolation

항목마다 독립 처리: `V3Error` → blocked(코드), 그 밖의 예외 → failed(`RENDER_EXCEPTION` + 짧은 traceback). 실측 fixture 배치: portrait/landscape/square/long_text **4 SUCCESS**, broken_asset **1 FAILED(`ASSET_MISSING`)**, MP4는 만들어지지 않음, 나머지 4개 정상.

## 15. Manifest

`<name>.manifest.json`(`shorts_v3_manifest/1`): render_key, renderer_version, lineage, origin, assets(장면별 메타데이터), output(path/sha256/bytes/duration/width/height/fps/frames/codec/audio), visual_review(title/scene_count/layouts/image_types/sources/duration/audio/transitions), quality(PASS/BLOCK, errors, warnings, codes), media_checks, audio_levels, layout(bbox 전체), timing, rerender_reason, **publish_contract**(37장 F).
배치: `batch_manifest.json` + 사람용 `batch_report.md`(name, content_id, generation_id, template, layouts, status, output, duration, sha256, error).

## 16. Lineage

content_id, generation_id, knowledge_id, source_script(경로), **source_script_sha256**, source_url, **document_sha256**(Render Document), template_id, **template_sha256**, **asset_sha256**(경로 → sha256), **mp4_sha256**, renderer_version, render_key. 템플릿이 바뀌면 template_sha256과 render key가 바뀐다.

## 17. Render key

`render_key = sha256(renderer_version, content_id, generation_id, document_sha256, template_sha256, asset sha256들, fps)`. 인코더 설정은 템플릿에 있으므로 template_sha256에 포함된다. 테스트: generation_id / content_id / 문서 / 템플릿(encoder) / 이미지 바이트 변경 → key 변경, 같은 입력 → 같은 key.

## 18. Idempotency

| 상황 | 결과 |
|---|---|
| 같은 key + PASS manifest + MP4 sha256 일치 | `skipped`, `ALREADY_RENDERED`(렌더 안 함) |
| MP4가 손상/수정됨 | 재렌더, `rerender_reason: ARTIFACT_CHANGED` |
| MP4 삭제 | 재렌더, `ARTIFACT_MISSING` |
| manifest 깨짐 | 재렌더, `MANIFEST_UNREADABLE` |
| `--force` | 항상 렌더 |

기존 cache 구조는 repo에 없었다(YouTube 업로드 이력의 `artifact_sha256` 중복 방지만 있음) → manifest + render key로 충분하게 두고 별도 캐시 시스템은 만들지 않았다. V3 출력은 결정적이다(같은 입력 → 같은 MP4 바이트, 손상 후 재렌더한 파일의 sha256이 원래와 같음을 테스트로 확인).
실측: fixture 문서 하나(long_text)만 고친 뒤 같은 배치를 다시 돌리면 3개 skipped, 1개만 렌더.

## 19. Quality gate

6-53 코드 + 이번 추가: `ASSET_MISSING`, `ASSET_UNSUPPORTED_FORMAT`, `ASSET_DECODE_FAILED`, `ASSET_TOO_SMALL`, `ASSET_REQUIRED`, `PROGRESS_OVERLAP`, `FRAME_COUNT_MISMATCH`, `AUDIO_SILENT`, `AUDIO_FADE_MISSING`. (6-53의 `IMAGE_MISSING`/`IMAGE_DECODE_FAILED`는 `ASSET_*`로 바뀜.)
모든 preview: 1080x1920, h264/aac 2ch, 길이 = 타임라인, 프레임 수 정확, 제목/본문/출처 overflow 없음, 이미지 디코드, 장면 타이밍, 안전영역, 진행 표시 겹침 없음, lineage 있음 → **PASS**(long_text만 `SOURCE_TRUNCATED` 경고).

## 20. Test matrix

신규 36개: `tests/test_6_54_shorts_v3_pipeline.py` 31(단위) + `tests/test_6_54_shorts_v3_pipeline_integration.py` 5(ffmpeg). 6-52/6-53 테스트는 바뀐 이름(`ASSET_*`, `fallback:decode_failed`, `manifest`, `skipped`, URL 출처)에 맞춰 기대값만 갱신(삭제/skip 없음).

| 요구 항목 | 테스트 |
|---|---|
| RenderDocument validation | `test_invalid_position_values`, 6-53 DocumentValidationTests |
| Asset resolver | `test_failure_codes`(5종), `test_resolve_assets_skips_empty_slots`, `test_resolve_asset_entry_point…` |
| Image metadata | `test_metadata_for_three_orientations`, `test_orientation_tolerance`, `test_hash_and_decode_are_cached` |
| Image crop | `test_cover_focal_point_selects_quadrant`, `test_crop_is_cover_alias`, `test_contain_keeps_whole_image`, `test_prepared_image_matches_slot_ratio…`(3×3) |
| Title / Body / Source wrapping | `test_title_one_two_three_lines_and_centering`, `test_body_reflow_order`, `test_source_labels`, `test_source_absent_collapses_footer` |
| Layout selection / missing asset | `test_missing_asset_blocks_by_default…`, `test_layout_can_require_an_image`, `test_editable_fields_come_from_template` |
| Progress | `test_scene_counts_one_to_six_without_overlap`, `test_progress_off_has_no_boxes`, `test_overlap_is_detected` |
| Batch / failure isolation / report | `test_fixture_batch_validate_isolates_broken_asset`, `test_fixture_batch_four_success_one_asset_missing`(실렌더), `test_markdown_report_has_required_columns` |
| Manifest / lineage / render key / idempotency | `test_manifest_contract`, `test_lineage_fields`, `test_render_key_inputs`, `test_idempotency_skip_and_repair` |
| Quality gate / audio / transition | `test_audio_fade_and_volume`, `test_all_transitions_render_without_blank_or_missing_frames` |
| Legacy adapter / input | `test_resolve_content_normalizes_all_inputs` |
| 5 candidate compatibility | `test_candidates_validate`(원본 해시 전후 비교) |
| Content-agnostic | `test_engine_has_no_content_specific_strings`(엔진 코드에 content_id/generation_id/제목/문장 없음) |
| Template / editor | `test_encoder_is_validated_template_data`, `test_check_document_gives_codes_without_rendering` |

## 21. Performance

프레임 합성 병목(cProfile): 매 프레임 전체 배경 리사이즈, 비네트·그레인 전체 화면 합성 2회, scrim/모서리 마스크 매 프레임 생성. 개선(화질 동일):
- 느린 카메라 줌을 0.05% 단위로 양자화해 배경 재사용(영상 전체에서 약 80번만 리사이즈),
- 비네트+그레인을 미리 합성해 1회 합성, scrim/마스크 캐시.
- 최적화 전후 프레임 차이: 평균 0.18/255, 최대 1(반올림 수준).

| | 6-53 | 6-54 |
|---|---|---|
| 프레임 합성(순차) | 38~51 ms | 15~25 ms |
| 11.5초 영상 1개 렌더 | 약 22.5초 | 약 17초 |

이제 병목은 x264 `medium` 인코딩(1080x1920에서 약 28fps)이다. 화질을 낮추는 변경은 하지 않았고, 대신 preset/CRF를 템플릿 `encoder` 값으로 옮겨 속도/용량/화질 선택을 데이터로 할 수 있게 했다(기본값 medium/20 유지).

5개 실제 후보 배치: 총 158.2초(렌더 평균 25.5초, 영상 합계 98초), 실패 0, 출력 38,438,463 bytes.

## 22. 5 candidate compatibility

| content_id | 입력 | generation_id | adapter → 문서 → 검증 | 실제 렌더 | 길이 | ShortsScript sha256 |
|---|---|---|---|---|---|---|
| content-e787c9201b94a948 | data/shorts_scripts | (legacy) | PASS | PASS | 11.5s | 067e8dbbba11… |
| content-3ae2d78568210164 | data/shorts_scripts | (legacy) | PASS | PASS | 13.0s | 9c220c5b2f20… |
| content-ec0c38b9a20c424c | 6-48 staging | gen-20260920T033856-6e8d98fb | PASS | PASS | 25.0s | e2a6d05734c2… |
| content-e3b8d986ea6db98e | 6-48 staging | 〃 | PASS | PASS | 24.0s | 3655a9c6f7fd… |
| content-91869ed8be17f3f3 | 6-48 staging | 〃 | PASS | PASS | 24.5s | b5e12b374bb5… |

schema gap: 없음. 참고(콘텐츠가 아니라 데이터 구조): 기존 ShortsScript에는 이미지·헤드라인·장면 길이가 없어 adapter 결과는 전부 text_focus다. 이미지를 쓰려면 문서 JSON에 `image`를 추가해야 한다(렌더러 수정 불필요). `--approved --validate-only`(Production archive 읽기 전용)도 2/2 validated.

## 23. Preview

`C:\Users\soppt\tak-auto\artifacts\6-54-v3-production-preview\` — 이미지는 모두 로컬 샘플/테스트 패턴이다(실제 사진 아님). 콘텐츠 문장은 원문 그대로.

| 폴더 | 내용 |
|---|---|
| `candidates/` | 실제 후보 5개 MP4 + `<id>.document.json`(adapter 결과, 고쳐서 다시 렌더 가능) + manifest |
| `layouts/` | 같은 콘텐츠(content-e787c9201b94a948) 4 레이아웃 |
| `fixtures/` | portrait / landscape / square / long_text MP4 + broken_asset(차단) |
| `transitions/` | cut/fade/slide/punch |
| `contact_sheet.png` | 4 레이아웃 비교, `contact_sheet_frames.png`(TITLE/CONTENT/FOOTER/안전영역 테두리) |
| `ratio_text_contact_sheet.png` | 이미지 비율 3종 × 레이아웃 3종 + 긴 글 4장면 |
| `transitions_contact_sheet.png` | 전환 중간 프레임 |

Visual review data (manifest `visual_review`):

| filename | layout | title | scenes | image type | source | duration | audio | frames | size | sha256(앞 16) | gate |
|---|---|---|---|---|---|---|---|---|---|---|---|
| layouts/01-image-top.mp4 | image_top | 새로운 기술을 마주하는 나의 기준 | 2 | landscape(샘플) | 출처 · BBC | 11.5 | aac 2ch | 345 | 4,754,087 | a3dd61899e6a8ac3 | PASS |
| layouts/02-split.mp4 | split | 〃 | 2 | landscape(샘플) | 출처 · BBC | 11.5 | aac 2ch | 345 | 4,779,282 | b4f00146827ad2dd | PASS |
| layouts/03-text-focus.mp4 | text_focus | 〃 | 2 | - | 출처 · BBC | 11.5 | aac 2ch | 345 | 4,838,733 | 39c7b860435e9ded | PASS |
| layouts/04-image-full.mp4 | image_full | 〃 | 2 | landscape(샘플) | 출처 · BBC | 11.5 | aac 2ch | 345 | 4,782,840 | 34c04bd9a864e107 | PASS |
| candidates/content-e787c9201b94a948.mp4 | text_focus | 새로운 기술을 마주하는 나의 기준 | 2 | - | 출처 · BBC | 11.5 | aac 2ch | 345 | 4,826,985 | ac039c5a4ca7eeff | PASS |
| candidates/content-3ae2d78568210164.mp4 | text_focus | 신기술을 마주하는 내 기준 | 2 | - | 출처 · BBC | 13.0 | aac 2ch | 390 | 5,397,144 | 6dd5ad9fcc409c51 | PASS |
| candidates/content-ec0c38b9a20c424c.mp4 | text_focus | AI 의식 연구, 어디까지 허용할까? | 4 | - | 출처 · BBC | 25.0 | aac 2ch | 750 | 9,787,894 | f054a89246bcecca | PASS |
| candidates/content-e3b8d986ea6db98e.mp4 | text_focus | AI 의식 연구, 어디까지 허용해야 할까? | 3 | - | 출처 · BBC | 24.0 | aac 2ch | 720 | 9,254,656 | 9c02a275994e6c1d | PASS |
| candidates/content-91869ed8be17f3f3.mp4 | text_focus | AI 의식 연구, 어디까지 허용할까? | 2 | - | 출처 · BBC | 24.5 | aac 2ch | 735 | 9,171,784 | 91994b0e0b6b9657 | PASS |
| fixtures/fixture-654-ratio_portrait.mp4 | image_top/split/image_full | 세로 이미지 비율 테스트 | 3 | portrait | BBC, Reuters | 9.5 | aac 2ch | 285 | 4,068,542 | 296c945b4911f1d9 | PASS |
| fixtures/fixture-654-ratio_landscape.mp4 | 〃 | 가로 이미지 비율 테스트 | 3 | landscape | BBC, Reuters(URL) | 8.5 | aac 2ch | 255 | 3,752,270 | 713042ffb5ae5c17 | PASS |
| fixtures/fixture-654-ratio_square.mp4 | 〃 | 정사각형 이미지 비율 테스트 | 3 | square | 자료 · 책 「사피엔스」 | 9.5 | aac 2ch | 285 | 4,114,362 | 56497ca0f83fe975 | PASS |
| fixtures/fixture-654-long_text.mp4 | text_focus/image_top | (3줄 긴 제목) | 4 | landscape | 긴 출처(말줄임) | 42.0 | aac 2ch | 1260 | 15,248,579 | ba813e77b3194cce | PASS(경고 SOURCE_TRUNCATED) |
| fixtures/(broken_asset) | image_top | 잘못된 이미지 경로 | 1 | - | - | - | - | - | - | - | BLOCK `ASSET_MISSING` |
| transitions/fixture-654-transitions.mp4 | text_focus/image_top/split | 전환 확인 | 5 | landscape, portrait | 출처 · BBC | 10.0 | aac 2ch | 300 | 4,389,949 | 6ce472277925d94d | PASS |

공통 template_sha256 `fa787ae73bbd…`, renderer_version `shorts_v3/6-54.3`. 전체 sha256·render key·문서 해시는 각 manifest.

## 24. Future image automation interface

```
CONTENT → IMAGE QUERY → AssetProvider.search(query) → 선택 → AssetProvider.fetch(candidate, dest) → 로컬 파일
        → AssetRequest(path, alt, source) → resolve_asset() / AssetResolver → 레이아웃 → 렌더
```
- 지금 있는 것: `AssetRequest`, `ResolvedAsset`(메타데이터), `resolve_asset()`, `AssetProvider`(search/fetch 인터페이스만, `NotImplementedError`). 네트워크 코드 없음.
- 붙일 때 필요한 최소 asset schema(E): `url`(원본), `license`, `author`, `provider`, `retrieved_at`, `query` — 문서 `image`에 추가하고 manifest `assets`에 기록. 게이트에 `ASSET_LICENSE_MISSING` 추가 권장. 받은 파일은 문서 옆 `images/`에 저장해 `image.path`로만 렌더러에 들어간다(렌더러는 네트워크를 모름). render key가 이미지 바이트를 해시하므로 교체하면 자동으로 다시 렌더된다.

## 25. Future editor interface

`content_engine/shorts_v3_contract.py`:
- `editable_fields(template)` — 편집기가 보여줄 필드와 선택지(레이아웃 목록은 템플릿에서, 전환/fit/위치 목록은 스키마에서). 읽기 전용: schema, id, template, lineage.
- `check_document(data, base_dir)` — 렌더 없이 즉시 검사: `{ok, codes, errors, warnings, total, scenes[start/duration/layout]}`.
- 최소 API(D): `GET fields`(editable_fields) · `POST check`(check_document) · `POST render`(render_batch 1건 → manifest) · `GET manifest`. 데이터 계약은 V3 문서 JSON 하나 — 제목/본문/이미지/레이아웃/출처/길이를 고치면 그대로 렌더러에 들어간다.

## 26. Production data protection

| 항목 | 시작(17:45) | 종료 |
|---|---|---|
| data/tak_media_archive.json | `bdc4cdb66adb61bd…f269` | 동일 |
| data/shorts_scripts/content-3ae2d78568210164.json | `9c220c5b2f20ef78…` | 동일 |
| data/shorts_scripts/content-e787c9201b94a948.json | `067e8dbbba11c944…` | 동일 |
| review_status / superseded_by | approved/None × 2 | 동일 |

CLI는 매 실행 전후 data/ 해시를 비교해 `production_data_unchanged: true`를 출력했다(모든 실행).

## 27. 하지 않은 것

콘텐츠 문장 수정·재작성, 새 콘텐츠, LLM 호출, 웹 이미지 검색/다운로드, TTS/내레이션, 새 음악, audio loop/ducking 구현(입력 없음), YouTube/Threads/Naver 업로드, Production Archive migration, 자동 승인/게시, Dashboard editor UI, 병렬 렌더, 인코더 기본값 변경.

## 추가 조사 (READ-ONLY, 37장)

**A. 가장 강한 결합** — V3가 6-41 모듈의 비공개 함수(`_blit`, `_font`, `_gradient`, `_radial_mask`, `_clamp`)와 `LOOKS` 팔레트, `draw_text_block`/`layout_text`에 기댄다. V2를 고치면 V3 출력이 바뀔 수 있다. 공용 그래픽 모듈로 옮기는 것이 다음 정리 후보(이번에는 V2 출력 불변을 우선해 옮기지 않음). 폰트 경로 `C:/Windows/Fonts` 고정도 같은 결합.

**B. 콘텐츠가 렌더러에 침투하는 부분** — 없음. 엔진 파일 8개에 실제/fixture 콘텐츠의 content_id·generation_id·제목·문장이 없음을 테스트로 고정했다. 콘텐츠 길이 차이는 템플릿 범위 + 오류 코드로 처리된다.

**C. 템플릿 수정만으로 해결되는 부분** — 프레임/글자 크기 범위/줄 수/간격, 레이아웃 추가(image+text 조합), 출처 이름 표, 이미지 정책(형식·최소 크기·missing 처리), 인코더 속도/화질, 진행 표시 위치·방식, 음악 스타일·볼륨·fade. 아직 코드에 있는 스타일 값: 배경 점 무늬, 비네트 강도, 그레인 세기, scrim 곡선, 엔드카드 상자 여백(→ 템플릿 `look` 확장 후보).

**D. Dashboard Editor 최소 API** — 25장.

**E. 이미지 자동수집 최소 asset schema** — 24장.

**F. YouTube 업로드 artifact contract** — manifest `publish_contract`: video 경로, artifact_sha256, content_id, knowledge_id, generation_id, title, duration, quality_status, source_url. 업로드 CLI(`scripts/upload_youtube_short.py`)가 요구하는 `--video/--title/--content-id/--knowledge-id`를 이 값으로 채울 수 있다. 실제 업로드 가능 여부는 기존 가드(Production Archive approved + ShortsScript content_id 일치 + supersede)가 판정한다 — staging 후보 3개는 여전히 ORPHAN으로 막힌다. 연결 시 추가 권장: `quality_status == PASS`가 아니면 업로드 CLI가 거부, publish log에 render_key 기록.

## 테스트 / 보안

| 항목 | 결과 |
|---|---|
| baseline(시작, d2e6df1) | 1580 tests OK, skipped 11 |
| 최종 전체 회귀 | **1616 tests OK, skipped 11** (baseline 1580 + 신규 36, 새 실패 0) |
| KNOWN ENVIRONMENT ERROR | 이번 실행들에서 발생하지 않음 |
| secret scan | 추적·미추적 파일 + 6-54 artifacts(manifest/보고서/문서): API key·OAuth/refresh token·client secret·private key 패턴 0. JSON `access_token` 패턴에 걸린 2건은 기존 테스트의 가짜 값(`"fresh-token"`, `"fresh-access-token"`, 6-54 변경 없음). 새 코드에 환경변수/토큰 읽기·출력 없음, 네트워크 import 없음 |
