# 6-55 Shorts Content Studio (Human Editable Draft Pipeline)

LOCAL DRAFT / PREVIEW ONLY. YouTube / Threads / Naver / LLM / 외부 API 호출 0.
Production Archive, ShortsScript, approved/review_status/superseded 변경 없음(23장).
실제 작업 시간: 2026-09-27 10:24 ~ 11:00 KST(약 36분). 요청은 5~6시간이었다. 체크리스트와 37장 추가 조사(발견 2건 구현)를 끝낸 뒤 시간을 채우려고 작업을 늘리지 않았다.

## 1. 목표

6-54 V3 생산 pipeline 앞단에 사람이 JSON이나 renderer 코드를 고치지 않고 Shorts를 고칠 수 있는 화면을 둔다.

```
SHORTS CONTENT(Production, 읽기만) -> EDITOR(/shorts-studio) -> EDIT DRAFT(버전) -> PREVIEW(6-54 render_item) -> QUALITY GATE -> MP4
```

## 2. Architecture

| 파일 | 역할 |
|---|---|
| `content_engine/shorts_studio.py` | **신규** — 원본 목록(`list_sources`), Draft 저장소(`DraftStore`), 폼 → 문서(`apply_form`), 검사(`check`), 미리보기(`preview`), 배치(`render_drafts`), 오류 설명(`describe`) |
| `scripts/run_scout_dashboard.py` | `/shorts-studio` 라우트와 화면(기존 `_page`/CSS/`http.server` 재사용, 새 프레임워크 없음), `DashboardConfig` 필드 6개, `--ffmpeg`/`--shorts-drafts` |
| `content_engine/shorts_v3_template.py` | `audio.volume`(0~2)/`fade_in`/`fade_out` 검증 추가 — 편집기에서 `volume: "loud"`가 들어오면 렌더 중 crash하던 경로를 `INVALID_TEMPLATE`로 막음 |
| `.gitignore` | `data/shorts_drafts/`, `data/shorts_assets/`(로컬 작업 상태) |
| `tests/test_6_55_shorts_studio.py` | **신규** 41 tests |

새 renderer/검사기/스키마를 만들지 않았다. 렌더·레이아웃·품질 게이트·lineage·render key·manifest는 6-54 코드(`render_item`, `check_document`, `LayoutEngine`, `quality_gate`) 그대로다.

## 3. Production vs Draft

| | Production | Draft |
|---|---|---|
| 위치 | `data/tak_media_archive.json`, `data/shorts_scripts/*.json`(+ 6-48 staging) | `data/shorts_drafts/<draft_id>/`(gitignore) |
| 누가 쓰나 | 기존 승인/생성 스크립트 | Shorts Studio만 |
| Studio 권한 | 읽기(`load_archive`, 파일 read) | 읽기/쓰기 |
| 미리보기 출력 | - | `artifacts/shorts_studio/<draft_id>/`(gitignore) |

원본 → Draft 복제는 6-54 adapter(`document_from_shorts_script`)로 한다. 복제 후 원본과 Draft는 연결이 `base_content_sha256`(원본 ShortsScript 파일 sha256)뿐이다.

## 4. Draft schema

Draft 문서 본문은 **V3 Render Document(`shorts_v3_document/1`) 그대로**다 — 6-54 편집 계약(25장)대로 데이터 계약을 하나로 유지했다. 요청의 title/brand/scenes/layout/image/headline/body/source/duration/progress/audio는 모두 이 문서의 필드다.

```json
{
  "schema": "shorts_draft/1",
  "draft_id": "draft-content-ec0c38b9a20c424c",
  "draft_version": 3,
  "status": "draft",
  "content_id": "content-ec0c38b9a20c424c",
  "generation_id": "gen-20260920T033856-6e8d98fb",
  "base_content_sha256": "e2a6d05734c2…",
  "base": {"kind": "shorts_script", "script_path": "…/content-ec0c38b9a20c424c.json", "archive_path": "…",
           "review_status": "approved", "knowledge_id": "knowledge-scout-…"},
  "created_at": "…", "updated_at": "…", "note": "편집",
  "document": { "schema": "shorts_v3_document/1", "title": "…", "brand": "…", "progress": {…}, "audio": {…},
                "scenes": [{"layout", "headline", "body", "image": {"path", "fit", "position"}, "source", "duration", "transition"}],
                "lineage": {"content_id", "generation_id", "knowledge_id", "source_script", …} }
}
```

저장 구조: `current.json` + `versions/v0001.json …`(한 번 쓰면 덮어쓰지 않음 — 같은 번호가 있으면 `DRAFT_CONFLICT`) + `previews.json`(미리보기 기록).

## 5. Editor

`py scripts/run_scout_dashboard.py --ffmpeg "C:/Program Files (x86)/clipdown/ffmpeg.exe"` → `http://127.0.0.1:8000/shorts-studio` (홈 nav에 🎬 Shorts Studio). 127.0.0.1 바인딩 그대로.

| route | 동작 |
|---|---|
| `GET /shorts-studio` | content selector |
| `POST /shorts-studio/open` | 원본 → Draft(이미 있으면 그대로 연다 — 편집 내용을 덮어쓰지 않음) |
| `GET /shorts-studio/<draft_id>` | 편집 화면 + 검사 결과 + 최신 preview + 버전 목록 |
| `POST /shorts-studio/<draft_id>/save` | `action=save` 저장 / `action=preview` 저장 후 렌더 |
| `POST /shorts-studio/<draft_id>/reset` | `target=base`(원본) / `target=vN`(이전 버전) |
| `GET /shorts-studio/<draft_id>/file/<name>` | 미리보기 MP4 (그 draft 출력 폴더, `[A-Za-z0-9._-]+.mp4|png`만) |
| `GET /shorts-studio/asset?path=` | 현재 이미지 썸네일(저장소/asset 폴더 안의 PNG/JPEG/WEBP만) |

화면: Title(여러 줄) · Brand · CTA · Progress ON/OFF + 위치 · Audio ON/OFF + 음악 + 음량 · 장면별(Layout, Duration, Transition, Image 경로/fit/position + 썸네일 또는 `ASSET_MISSING`, Headline, Body, Source label/value) · Save Draft / Save + Render Preview · 원본으로 초기화 / 마지막 저장 상태로(입력 버리기) / 버전별 되돌리기.
선택지(레이아웃·전환·fit·음악)는 6-54 `editable_fields(template)`에서 온다 — 템플릿에 레이아웃을 추가하면 화면에 자동으로 나온다.

폼 규칙: 빈 칸 = 키 제거(템플릿 기본값/자동 길이/출처 없음/이미지 없음). 이 때문에 Studio POST만 `parse_qs(keep_blank_values=True)`로 읽는다(기존 라우트는 기본값 그대로). 숫자로 읽히지 않는 값은 버리지 않고 그대로 넘겨 검증이 코드로 알려준다.

## 6. Content selector

`list_sources([(archive, scripts_dir), …])`: archive에서 `platform == "shorts"`이고 ShortsScript 파일이 있는 레코드. 앞 source 우선(같은 content_id 중복 제외). 기본 source = Production(`media_archive_path`, `shorts_scripts_path`) + 6-48 staging.
표시: content_id, title(ShortsScript), generation_id, platform, review_status, fact_check(6-51 preview manifest의 기록 — archive에는 fact-check 필드가 없다), Draft 버전.
실측: 5개 후보가 모두 나온다(Production 2 + staging 3). staging의 `content-cabd37f3a2745724`는 ShortsScript가 없어 나오지 않는다.

## 7. Title editing

짧은/긴/여러 줄 제목을 입력 그대로 저장한다(자동 수정 없음). 저장 전 검사:
- 빈 제목 → `TITLE_EMPTY`, 저장 거부.
- 4000자 초과(모든 텍스트 칸 공통) → `FIELD_TOO_LONG`, 저장 거부.
- 화면 overflow 가능성 → 레이아웃 엔진 `TITLE_OVERFLOW`, 저장은 되고 화면에 표시, 미리보기는 게이트에서 막힘.

## 8. Body editing

headline / body(빈 줄 = 문단) / 장면별 텍스트. 긴 텍스트도 저장된다(요약·자르기 없음, 테스트로 확인). overflow는 `BODY_OVERFLOW`/`HEADLINE_OVERFLOW`로 게이트가 검사한다.

## 9. Image editing

장면별 `image.path`(로컬 파일, `data/shorts_assets/` 목록을 datalist로 제안), `fit`(cover/contain/crop), `position`(center/top/bottom/left/right 또는 `x,y`). 파일이 없으면 편집 화면에 `ASSET_MISSING`(= IMAGE_MISSING) 표시, 미리보기는 렌더 전에 차단(MP4 없음). 잘못된 fit/position → `INVALID_IMAGE_SPEC` 저장 거부. 인터넷에서 가져오지 않는다.

## 10. Layout editing

장면별 image_top / split / text_focus / image_full(템플릿의 레이아웃 전체). 없는 레이아웃 → `INVALID_LAYOUT` 저장 거부. 변경 후 Save + Render Preview 한 번으로 확인.

## 11. Source editing

value(BBC, Reuters, 책 제목, URL …) + 선택 label. 비우면 출처 없음(footer 정리). 긴 출처 → `SOURCE_TRUNCATED` 경고(말줄임), 한 줄에 못 들어가면 `SOURCE_OVERFLOW`.

## 12. Duration

장면별 초. 비우면 자동(글자 수 → 박자). 0 이하 / 숫자 아님 / 템플릿 범위(1.2~20초) 밖 / 글을 읽을 수 없는 길이 → `INVALID_DURATION` 저장 거부. 장면 합계 = 영상 길이는 렌더러가 박자 타임라인으로 계산하고 게이트(`SCENE_TIMING_INVALID`)와 검사 결과 `scenes/total`로 확인(테스트).

## 13. Progress

ON/OFF + 위치(footer/top). 잘못된 위치 → `INVALID_TEMPLATE`.

## 14. Audio

기존 6-41 합성 음악만: ON/OFF, 음악(ai/finance/human), 음량 0~2. 새 음악 생성 없음. 이번에 템플릿 검증에 음량/fade 범위를 추가했다(이전에는 문자열 음량이 검증을 통과해 렌더 중 예외).

## 15. Preview

```
Draft(current 버전) -> ContentItem(name=<draft_id>-v0003, origin=draft lineage) -> 6-54 render_item
  -> asset -> 레이아웃 -> (BLOCK이면 여기서 끝, MP4 없음) -> 렌더 -> inspect_media -> quality_gate -> manifest
```
결과 기록(`previews.json`, 화면): status, error_code + 설명, video(`<video>`로 재생), duration, resolution, codec, audio, quality, render key, mp4 sha256, lineage. 같은 버전을 다시 누르면 6-54 idempotency로 `skipped`(다시 렌더 안 함).

## 16. Quality gate

6-54 `quality_gate`를 그대로 쓴다(별도 checker 없음): title/headline/body/source overflow, `ASSET_*`, 해상도, 코덱, 길이, 프레임 수, 오디오(무음/fade), 안전영역, 진행 표시 겹침, lineage. 편집 중에는 같은 엔진의 렌더 없는 검사(`check_document`)를 저장마다 돌려 화면에 보여준다.

## 17. Versioning

저장마다 `draft_version + 1`, `versions/vNNNN.json` 스냅샷. 내용이 같으면 버전을 올리지 않는다(`unchanged`). 편집 화면은 `expected_version`을 보내 다른 탭이 먼저 저장했으면 `DRAFT_CONFLICT`(덮어쓰기 방지).

## 18. Reset

두 가지 다 구현: ① 원본 Production Content로 초기화(`reset_to_base`, 원본을 다시 adapter로 읽음) ② 이전 버전으로 되돌리기(`revert`). 둘 다 **새 버전**으로 쌓는다 — 기록을 지우지 않는다. "저장 안 한 입력 버리기"는 마지막 저장 상태를 다시 여는 링크. Production 데이터는 읽기만.

## 19. Lineage

preview 기록/manifest: `draft_id`, `draft_version`, `base_content_id`, `generation_id`, `base_content_sha256`, `document_sha256`, `template_sha256`, `asset_sha256`, `render_key`, `mp4_sha256`(+ manifest `origin.kind = "shorts_draft"`).
render key는 **내용** 기준이다(6-54 그대로): 버전 번호는 key에 들어가지 않아 v1로 되돌리면 v1과 같은 key(테스트). "몇 번째 수정본인가"는 파일 이름(`<draft_id>-v0003.mp4`)과 `origin.draft_version`으로 안다.

## 20. Batch preview

`render_drafts(store, [draft_id, …], out_root, ffmpeg=)` → `{total, success, failed, results[]}`. 항목별 격리(없는 draft, 잘못된 id, BLOCK, 렌더 예외가 다른 항목을 멈추지 않음), asset resolver 캐시 공유. UI 버튼은 만들지 않았다.

## 21. Error handling

화면에는 코드 + 한국어 설명(`shorts_studio.ERROR_TEXT`)만, traceback은 보이지 않는다(테스트).

| 요청 코드 | 실제 코드 | 시점 |
|---|---|---|
| TITLE_OVERFLOW / BODY_OVERFLOW / SOURCE_OVERFLOW | 동일(+ HEADLINE_OVERFLOW, SOURCE_TRUNCATED 경고) | 저장 후 검사 표시, 미리보기 차단 |
| IMAGE_MISSING | `ASSET_MISSING`(6-54에서 이름 변경, 설명에 IMAGE_MISSING 표기) | 편집 화면 + 미리보기 차단 |
| INVALID_DURATION / INVALID_LAYOUT / INVALID_TEMPLATE | 동일(+ INVALID_IMAGE_SPEC, INVALID_TRANSITION, TITLE_EMPTY, FIELD_TOO_LONG) | 저장 거부, **입력값은 화면에 그대로 남음**(400) |
| RENDER_FAILED | 렌더 중 예외(ffmpeg 없음 등) | 미리보기 |
| QUALITY_GATE_FAILED | MP4는 만들어졌으나 게이트 BLOCK | 미리보기 |

## 22. Tests

`tests/test_6_55_shorts_studio.py` 41개(신규). ffmpeg 필요한 2개는 `TAK_TEST_FFMPEG`가 있을 때만.

| 요구 | 테스트 |
|---|---|
| 1 draft creation | `test_draft_creation_clones_source` |
| 2 loading | `test_draft_loading_and_reopen_keeps_edits`, `test_missing_and_malicious_draft_ids` |
| 3/4 save·versioning | `test_save_versions_are_immutable_snapshots`, `test_unchanged_save_does_not_bump_version`, `test_stale_editor_gets_conflict` |
| 5 reset | `test_reset_to_production_content`, `test_revert_to_previous_version` |
| 6 source immutable | 모든 StudioCase `tearDown`이 원본 archive/ShortsScript sha256 비교 |
| 7 title | `test_title_short_long_multiline_stored_verbatim`, `test_empty_title_rejected`, `test_overflowing_title_is_saved_but_flagged`, `test_field_too_long_rejected` |
| 8 body | `test_body_and_headline_edit_without_rewriting`, `test_long_body_saved_and_overflow_reported` |
| 9 image | `test_image_edit_path_fit_position`, `test_invalid_image_spec_rejected` |
| 10 layout | `test_every_layout_can_be_selected` |
| 11 source | `test_source_edit` |
| 12 duration | `test_duration_validation` |
| 13 progress | `test_progress_edit` |
| audio | `test_audio_edit_and_volume_validation` |
| 14/15/16 preview·gate·lineage | `test_preview_render_quality_gate_and_lineage`(실렌더), `test_preview_blocked_before_render_writes_no_mp4`, `test_render_exception_becomes_render_failed` |
| 17 render key | `test_render_key_follows_content_not_version` |
| 18 batch | `test_batch_isolates_failures`, `test_batch_preview_success_and_failure`(실렌더) |
| 19 missing image | `test_missing_image_blocks_preview_with_asset_missing` |
| 20 invalid layout | `test_invalid_layout_rejected` |
| selector | `test_lists_only_shorts_with_script_and_dedupes_sources`, `test_fact_checks_from_manifest` |
| Dashboard | `test_selector_open_edit_save_reset_flow`, `test_invalid_save_keeps_user_input_and_explains`, `test_preview_button_shows_error_code_not_traceback`, `test_file_routes_do_not_leak_other_files`, `test_editor_has_no_approve_publish_or_secret_inputs` |
| 보호 | `test_studio_never_imports_production_writers_or_network`(AST), `test_apply_form_does_not_mutate_input`, `test_base_drift_detected_without_touching_source` |
| 장면 복제/삭제 | `test_scene_duplicate_and_delete` |

| 항목 | 결과 |
|---|---|
| baseline(시작, a1f6d67) | 1616 OK, skipped 28(ffmpeg 없이) / **1616 OK, skipped 11**(`TAK_TEST_FFMPEG` 설정) |
| 최종 전체 회귀(`TAK_TEST_FFMPEG` 설정) | **1657 tests OK, skipped 11** (baseline 1616 + 신규 41, 새 실패 0) |
| KNOWN ENVIRONMENT ERROR | 이번 실행들에서 발생하지 않음 |
| 삭제/skip한 기존 테스트 | 없음 |

참고: 요청서의 HEAD `a1f66d7`은 실제 6-54 커밋 `a1f6d67`(origin/main과 같음)의 오타로 판단했다.

## 22-1. 실제 후보 5개 (Editor 경유)

Dashboard를 실제로 띄우고 HTTP로 `GET /shorts-studio` → `POST open` → `POST save(action=preview)`를 5번 호출했다(Draft 저장소와 출력은 `artifacts/6-55-shorts-studio-preview/` 아래, `data/`에는 아무것도 만들지 않음). 값은 바꾸지 않았다.

| # | content_id | draft | layout | 길이 | 규격 | 코덱 | 프레임 | sha256(앞 16) | gate |
|---|---|---|---|---|---|---|---|---|---|
| 01 | content-e787c9201b94a948 | v1 | text_focus | 11.5 | 1080x1920 | h264/aac 2ch | 345 | ac039c5a4ca7eeff | PASS |
| 02 | content-3ae2d78568210164 | v1 | text_focus | 13.0 | 1080x1920 | h264/aac 2ch | 390 | 6dd5ad9fcc409c51 | PASS |
| 03 | content-ec0c38b9a20c424c | v1 | text_focus | 25.0 | 1080x1920 | h264/aac 2ch | 750 | f054a89246bcecca | PASS |
| 04 | content-e3b8d986ea6db98e | v1 | text_focus | 24.0 | 1080x1920 | h264/aac 2ch | 720 | 9c02a275994e6c1d | PASS |
| 05 | content-91869ed8be17f3f3 | v1 | text_focus | 24.5 | 1080x1920 | h264/aac 2ch | 735 | 91994b0e0b6b9657 | PASS |

편집하지 않은 Draft의 MP4는 6-54 후보 MP4와 **바이트 단위로 같다**(sha256 5개 모두 6-54 23장 표와 일치) — Studio 경로가 렌더 결과를 바꾸지 않는다.

## 22-2. Sample edit (26장)

후보 03(`content-ec0c38b9a20c424c`)을 화면 폼으로 고쳤다: 제목(2줄로 직접 나눔 `AI 의식 연구,
어디까지 허용해야 할까?`), 장면 1 → image_top + 샘플 이미지 + 헤드라인 + 출처 `BBC News`, 장면 2 → split + 세로 이미지 + 본문에 문단 추가, 진행 표시 top.

| 단계 | 버전 | 결과 |
|---|---|---|
| 첫 시도 | v2 | **blocked `BODY_OVERFLOW`**(split 텍스트 영역에 늘린 본문이 안 들어감) — MP4 없음, 화면에 코드+설명 |
| 사람이 장면 2를 text_focus로 바꿔 다시 미리보기(문장은 그대로) | v3 | **success / PASS**, 28.0초 |

| | 원본(v1) | 편집(v3) |
|---|---|---|
| base_content_sha256(ShortsScript) | e2a6d05734c22d1a… | e2a6d05734c22d1a…(원본 그대로) |
| document sha256 | 211073ef1da72d3e… | 7e04d89a35dfd992… |
| render key | 6d94fe680ee55173… | 03552719b3ee8c46… |
| MP4 sha256 | f054a89246bcecca… | f3532ec92aa8c9f2… |

이 과정이 실제 결함 하나를 드러냈다 → 37장 A(장면 복제/삭제 추가).

## 22-3. Contact sheet

`artifacts/6-55-shorts-studio-preview/contact_sheet.png` — 01~05 + sample_edit의 2.5초 프레임, 각 칸 아래 파일/content_id/title/layout. `report.json`에 전체 lineage, 버전 목록, 전후 해시.
이미지는 6-54의 로컬 샘플/테스트 패턴(실제 사진 아님)을 `assets/`로 복사해 썼다.

## 23. Production protection

| 항목 | 시작 | 종료 |
|---|---|---|
| data/tak_media_archive.json | `bdc4cdb66adb61bd…f269` | 동일 |
| data/shorts_scripts/content-3ae2d78568210164.json | `9c220c5b2f20ef78…` | 동일 |
| data/shorts_scripts/content-e787c9201b94a948.json | `067e8dbbba11c944…` | 동일 |
| 6-48 staging archive/export/ShortsScript 6개 | 시작 시 기록 | 동일 |
| review_status / superseded_by(Production 18건, approved 2) | 기록 | 동일 |

- 코드 수준: `shorts_studio.py`는 archive에서 `load_archive`만 import(AST 테스트). 승인/게시/업로드 함수, 네트워크 모듈 import 없음. Studio 화면의 form action/input 이름에 approve/publish/upload/token/secret 없음(테스트).
- 쓰기 위치: `DraftStore.root/draft-*/`와 preview `out_dir`뿐. draft_id는 `draft-` 접두사 정규식만 허용 → 저장소 root를 `data/`로 잘못 줘도 `shorts_scripts/` 같은 기존 폴더를 가리킬 수 없다. content_id도 정규식 검사(`../` 차단).
- 파일 제공 라우트: MP4는 그 draft의 출력 폴더 + 파일명 정규식, 이미지는 저장소/asset 폴더 안 PNG/JPEG/WEBP만(`data/tak_media_archive.json`, `C:/Windows/win.ini`, `../` 요청이 404인 것을 테스트).
- 보안: API key/OAuth/secret 입력칸 없음. secret scan(패턴: sk-/AIza/ya29/1//refresh/ghp_/private key/`api_key|client_secret|refresh_token|access_token|password = "…"`) — 새 코드·문서·테스트·6-55 artifacts 0건. 환경변수의 실제 토큰/키 값 3개가 산출물에 들어 있는지도 검사 → 0건.
- 외부 API: YouTube 0 / Threads 0 / Naver 0 / LLM 0 (dashboard의 기존 LLM provider는 `/shorts-studio`에서 쓰지 않음; 테스트/실행 모두 `llm_provider=None`).

## 24. 향후 approval 연결

### 37장 추가 조사 (READ-ONLY → 필요한 보완 구현)

**A. 사람이 가장 자주 고칠 필드** — 실제 5개 기준: ① 이미지(5개 모두 text_focus, 이미지 0 — 이미지가 들어가는 순간 레이아웃이 바뀐다) ② 본문(03은 영어 원문 인용 `Mustafa Suleyman says…`가 그대로 한 장면, adapter의 카드 → 장면 자동 분할 결과를 사람이 나누거나 합칠 필요) ③ 제목(03/05 제목이 완전히 같음, 줄바꿈 위치). 실제 편집에서 본문+레이아웃 변경이 `BODY_OVERFLOW`로 막혔고, 사람의 자연스러운 해결은 "장면을 나눈다"인데 편집기에 방법이 없었다 → **장면 복제/삭제 버튼 구현**(빈 장면 추가는 `EMPTY_SCENE`이라 복제 후 두 장면의 본문을 나눠 고치는 방식, 마지막 장면은 삭제 불가).

**B. 이미지 자동 수집 asset interface** — 6-54 `AssetProvider.search/fetch`가 받은 파일을 `data/shorts_assets/`에 두면 편집기 datalist에 자동으로 나온다(코드 변경 불필요). 편집기는 `image`의 알 수 없는 키를 보존한다(`{**image, "path": …}`) → `url/license/author/provider/retrieved_at/query`를 image에 실어도 저장·해시·lineage에 남는다. 붙일 때: 편집 화면에 license 읽기 전용 표시, 게이트 `ASSET_LICENSE_MISSING`.

**C. 승인 workflow 최소 contract** — 승인 요청 = `{draft_id, draft_version, render_key, mp4_sha256, base_content_sha256, reviewer, at}`. 승인 가능 조건: 그 버전의 preview 기록이 `status in (success, skipped)` + `quality == PASS`, MP4 파일 sha256 == 기록, Draft current 버전 == 요청 버전(이후 편집 없음), `base_drift() is None`. 지금 이 값들이 모두 `previews.json`/manifest에 있다.

**D. Draft → Production promotion 안전장치** — (1) 위 C 조건 전부 (2) Production 쪽 원본 sha256이 `base_content_sha256`과 같을 때만(동시 수정 방지 — compare-and-swap) (3) 기존 6-19 supersede 규칙: 원본 레코드를 덮어쓰지 말고 새 content_id/generation으로 만들고 원본은 `superseded_by` (4) ShortsScript 형식으로 되돌리는 역-adapter가 필요(이미지/레이아웃/장면 길이는 ShortsScript에 없음 — 6-54 22장) → Production 쪽에 V3 문서를 저장할 자리를 정하는 것이 선행 결정 (5) 사람이 명시적으로 누르는 별도 명령(자동 없음), 실행 전후 data/ 해시 기록.

**E. 편집기가 Production을 건드릴 수 있는 경로** — 조사: ① `DraftStore` 쓰기(root/draft-* 한정, 위 정규식) ② preview 출력(config `shorts_studio_out_path`) ③ `reset_to_base`/`list_sources`/`base_drift`(읽기만) ④ 이미지 경로(렌더러가 읽기만) ⑤ 파일 제공 라우트(읽기, 범위 제한). 쓰기 경로에 Production 파일이 들어갈 수 있는 곳은 ①뿐이었고, 정규식이 `draft-` 접두사를 요구하지 않아 root를 `data/`로 주면 `data/<임의 이름>/current.json`을 가리킬 수 있었다(실제로는 파일이 먼저 있어야 저장되지만) → **`draft-` 접두사 강제**로 막았다.
추가 발견: 원본 ShortsScript가 Draft 생성 후 바뀌면 사람이 모른 채 옛 내용으로 작업한다 → **`base_drift()` + 편집 화면 `BASE_CHANGED` 경고** 구현.

### 하지 않은 것

YouTube/Threads/Naver 업로드, 자동 승인, Production Archive 변경, LLM 재작성, 이미지 웹 검색, TTS, 새 음악, 게시 UI, 대량 렌더 UI 버튼, 브라우저 자동 조작으로 화면 스크린샷 검증(화면은 HTTP 테스트와 실제 서버 호출로 확인).
알려진 한계: 미리보기 렌더는 요청 안에서 동기 실행(후보당 16~30초, 로컬 1인용이라 큐 없음 — 여러 명이 쓰면 백그라운드 작업으로). 영상 파일은 Range 없이 통째로 보낸다(재생 OK, 탐색은 브라우저에 따라 제한). lineage의 `source_script`는 로컬 절대 경로.
