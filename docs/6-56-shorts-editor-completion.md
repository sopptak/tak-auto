# 6-56 Shorts Editor 완성 (운영 워크플로)

LOCAL DRAFT / PREVIEW / RENDER ONLY. YouTube / Threads / Naver / LLM(Opus 포함) / 외부 API 호출 0.
Production Archive · ShortsScript · review_status · superseded 변경 0 (16장).
작업 시간: 2026-09-27 11:36 ~ 12:12 KST(약 36분). 요청은 5~6시간이었다. 아래 체크리스트, 실제 브라우저 검증, 실제 MP4 검증, 발견한 문제 수정(12장)을 끝낸 뒤 시간을 채우려고 기능을 늘리지 않았다.

## 1. 작업 목적

생성된 Shorts를 **비개발자 운영자가 브라우저에서** 보고 → 고치고 → 저장하고 → 미리보기 → 최종 렌더 → 확인 → 승인할 수 있는 Editor를 완성한다. 분야 확장, AI 연동, 게시는 하지 않는다.

```
[1] 목록에서 콘텐츠 선택 → [2] Editor → [3] 장면 정지 화면/영상 확인 → [4] 제목·Hook·본문·강조·자막·출처·이미지·레이아웃·길이·CTA 수정
→ [5] 저장 → [6] 새 버전 → [7] 미리보기 렌더 → [8] 품질 검사 → [9] 최종 렌더 → [10] 최종 MP4 확인 → [11] 사람 승인(Draft 기록)
→ [12] (다음 단계) 승인 기록의 publish_contract를 기존 게시 파이프라인이 읽는다 — 이번에는 게시하지 않음
```

## 2. 기존 상태 (6-55까지)

| 있던 것 | 한계 |
|---|---|
| `content_engine/shorts_studio.py`: Draft 저장소(버전 스냅샷, revert, 원본 초기화), 폼→문서, 저장 검증, 6-54 `render_item`으로 미리보기, lineage, 배치 | 미리보기 = 최종(구분 없음), 승인 없음, 분야/언어 없음, superseded/다른 generation 보호 없음 |
| `/shorts-studio` 화면(`run_scout_dashboard.py` 안) | 한 줄 입력칸 나열(개발자용), 이미지 = 경로 문자열, 프레임 추가/이동 없음, 오류가 코드 위주, 목록 필터 없음 |
| 6-54 V3 엔진: 문서 → 레이아웃 → 렌더 → 게이트 → manifest, render key, idempotency | 바꾸지 않음(렌더 결과 동일) |

문서 확인: docs/6-52~6-55, 관련 테스트(6-52~6-55), operator 문서.
baseline: HEAD `b2463c1`(= origin/main), 작업 트리 깨끗, **1657 tests OK, skipped 11**(`TAK_TEST_FFMPEG` 설정).

## 3. 구현 내용

| 파일 | 변경 |
|---|---|
| `content_engine/shorts_studio.py` | 사람이 읽는 품질 판정(PASS/WARNING/BLOCKED + "장면 N: …"), 편집기 경고 5종, 글꼴 누락 문자 검출, Draft meta(분야/주제/언어/locale/master_content_id), 버전 필드(parent_version/modified_by/document_sha256/check), guard(대체됨·generation 불일치·원본 없음), 미리보기/최종 렌더 모드, 장면 정지 화면(실제 렌더러), 사람 승인/취소(Draft 저장소 안), 상태 계산, 이미지 업로드 검증·저장, 프레임 위/아래 이동, 강조 문구 |
| `scripts/shorts_studio_web.py` | **신규** — Studio 화면 전부(목록/편집/요청 처리, multipart 업로드). 6-55에서 `run_scout_dashboard.py`에 넣었던 화면 코드를 옮겨 대시보드 파일은 연결만 한다(+55줄 vs 6-54) |
| `scripts/run_scout_dashboard.py` | Studio 요청을 `shorts_studio_web.handle`로 전달, 본문 크기 제한(413), **HTTP Range(206) 지원**(12장에서 발견), 6-55 화면 코드 제거 |
| `content_engine/shorts_v3_contract.py` | `check_document()` 결과에 장면 번호가 있는 원본 `issues` 추가(기존 키 유지) |
| `tests/test_6_56_shorts_editor.py` | **신규** 27 tests |
| `tests/test_6_55_shorts_studio.py` | 1개 기대값 갱신(아래 13장) |

## 4. Editor architecture

```
브라우저 ──HTTP──> run_scout_dashboard.py (127.0.0.1, http.server) ──> scripts/shorts_studio_web.py (화면/폼/업로드)
                                                                            │
                                                          content_engine/shorts_studio.py (Draft·검사·렌더·승인)
                                                             │ 읽기만                         │ 6-54 그대로
                                     Production Archive + ShortsScript        V3 문서 → LayoutEngine → ShortsV3Renderer → 게이트 → manifest
```
새 프레임워크 없음(표준 라이브러리 `http.server` + 서버 HTML, JS는 렌더 중 안내 오버레이 10줄뿐).

**콘텐츠 / 디자인 분리(7장 요구)** — 이미 분리돼 있어 재작성하지 않고 검증·보완만 했다:

| 층 | 가진 것 | 위치 |
|---|---|---|
| 디자인 시스템 | 글꼴 크기 범위·줄 수·영역 좌표·안전영역·색(look)·전환 시간·자막 등장 지연·음악 합성·인코더 | 템플릿 `content_engine/shorts_v3_templates/default.json` |
| 콘텐츠 + 장면별 디자인 선택 | 제목, 장면[]{Hook/헤드라인, 본문, 강조, 자막, 출처, 레이아웃 선택, 이미지+맞춤+기준점, 길이, 전환}, CTA, 진행 표시/음악 on·off | V3 문서(`shorts_v3_document/1`) = Draft `document` |
| 분류 | 분야, 주제, 언어, locale, master_content_id | Draft `meta`(렌더 결과와 무관 → render key 불변, 테스트) |

편집 화면도 장면마다 **내용 / 디자인 / 타이밍** 섹션으로 나눴다. 분야가 늘어도 문서·Editor·Renderer는 그대로이고, 분야별 모양이 필요하면 템플릿을 하나 더 만든다(코드 변경 없음, 6-54 37장 C).

## 5. Draft model

```json
{ "schema": "shorts_draft/1", "draft_id": "draft-<content_id>", "draft_version": 4, "parent_version": 3,
  "status": "draft", "content_id": "…", "generation_id": "…", "base_content_sha256": "<원본 ShortsScript sha256>",
  "base": {"kind": "shorts_script", "script_path": "…", "archive_path": "…", "review_status": "approved", "knowledge_id": "…"},
  "meta": {"category": "AI/테크", "topic": "…", "language": "ko", "locale": "ko-KR", "master_content_id": "<content_id>"},
  "created_at": "…", "updated_at": "…", "modified_by": "<OS 사용자>", "note": "편집",
  "document_sha256": "…", "check": {"verdict": "PASS", "codes": [], "warnings": []},
  "document": { V3 Render Document } }
```
저장소: `data/shorts_drafts/<draft_id>/`(gitignore) — `current.json`, `versions/vNNNN.json`(덮어쓰지 않음), `previews.json`(렌더 기록), `approvals.json`, `frames/<문서해시>/sceneNN.png`.
요청 14장의 `category/topic/language/locale/master_content_id/content_id/generation_id/version_id(=draft_version)/source/assets(장면 image)/frames(scenes)/render_document(document)`를 모두 수용한다.

## 6. Versioning

Original(원본 ShortsScript) → v1(복제) → v2 … : 저장할 때마다 새 스냅샷, `parent_version` 연결. **같은 내용(문서+meta)을 다시 저장하면 버전을 만들지 않는다**(테스트 V). 다른 탭이 먼저 저장했으면 `DRAFT_CONFLICT`(덮어쓰기 방지).
Reset: ① "원본 Production Content로 초기화" = 원본을 다시 읽어 **새 버전**으로 ② 버전 표의 "이 버전으로 되돌리기" ③ "저장 안 한 입력 버리기". 어느 것도 원본/Production을 바꾸거나 기록을 지우지 않는다.

## 7. Preview

- **장면 정지 화면(즉시)**: 편집 화면을 열 때 현재 버전의 각 장면 + 엔드카드를 **최종 MP4와 같은 렌더러**(`ShortsV3Renderer.frame`)로 그린다. MP4 검사와 같은 시점(장면 60%). 문서 해시로 캐시. 없는 이미지는 빈 틀로 그려 위치를 보여주고, 글이 넘치면 "화면을 그릴 수 없습니다: 본문이…"를 보여준다.
- **미리보기 렌더**: 같은 문서·렌더러·레이아웃·오디오·게이트, 인코더만 `ultrafast/crf28`. 테스트로 미리보기와 최종의 길이·프레임 수·장면 배치가 같고 템플릿 해시(인코더)만 다름을 확인.
- 실측(5개 후보): 미리보기 15~39초 / 최종 20~48초 — 약 20% 빠를 뿐이다. 병목이 인코딩이 아니라 프레임 합성이라서다(6-54 21장). 즉시 확인은 정지 화면이 맡는다.
- 렌더 중에는 "영상을 만드는 중입니다… 20~60초" 오버레이.

## 8. Render

"최종 렌더" = 템플릿 인코더 그대로(`medium/crf20`) = 게시용. 파일 `<draft_id>-v0004-final.mp4` + manifest(6-54 형식, `origin.mode = "final"`, `publish_contract`). 같은 버전을 다시 누르면 render key가 같아 `skipped`(다시 만들지 않음, 테스트).
**보호**: 원본이 대체(superseded)됐거나 Draft와 원본의 generation이 다르면 렌더하지 않는다(`SUPERSEDED`/`GENERATION_MISMATCH`, MP4 없음, 테스트 X/Y).

## 9. Quality Gate

6-54 게이트를 그대로 쓰고(별도 검사기 없음), 사람이 읽는 층만 얹었다.

| 판정 | 뜻 |
|---|---|
| PASS | 문제 없음 |
| WARNING | 렌더 가능, 확인 권장: 출처 말줄임, **출처 없음**, **본문 없는 영상**, **강조 문구가 본문에 없음**, **이미지가 45% 넘게 잘림(비율)**, **글꼴에 없는 문자(아랍어·이모지 등 → □)**, 빈 이미지 칸 |
| BLOCKED | 렌더 불가: 제목/헤드라인/본문/자막/출처 overflow, 이미지 없음/손상/형식, 안전영역, 진행 표시 겹침, 타이밍, 잘못된 레이아웃·길이·템플릿, lineage 없음, 렌더 실패, 게이트 실패, 대체됨, generation 불일치 |

표시: "장면 2: 본문이 화면에 들어가지 않습니다. 본문을 줄이거나, 장면을 복제해 나눠 쓰거나, '글자 중심' 레이아웃을 써 보세요." — 왼쪽 품질 검사 카드와 **해당 Frame 카드 안** 두 곳. 엔진 원문(좌표 등)은 마우스를 올릴 때만. BLOCKED면 렌더 버튼이 비활성화되고 이유가 보인다. traceback은 화면에 나오지 않는다(테스트).

## 10. Image editing

Frame 카드마다: **[현재 이미지](썸네일 / "이미지 없음" / 빨간 ASSET_MISSING)** → "이미지 바꾸기 / 빼기"를 누르면 **썸네일 갤러리**(asset 폴더 최신 60개 + "이미지 없음") → **"내 컴퓨터에서 새 이미지 올리기"**(PNG/JPEG/WEBP, 320px 이상, 20MB 이하 — 6-54 asset resolver와 같은 기준으로 검사 후 `data/shorts_assets/uploads/<sha12>-<이름>`에 저장, 같은 파일은 한 번만) → **맞춤**(꽉 채우기/전체 보이기) → **보여줄 부분**(3×3 기준점 버튼) → 레이아웃(글자 중심/이미지 위·글 아래/좌우 나눔/이미지 전체). 경로 직접 입력은 "고급"에 접어 둠. 인터넷에서 가져오지 않는다.

## 11. Frame editing

V3는 장면 수가 자유(1~N)이고 엔드카드(채널명 + CTA)는 자동으로 붙는다 — 고정 4프레임이 아니다. 화면 표기:

| Frame | 편집 |
|---|---|
| Frame 1 · Hook | "Hook 문구(헤드라인)"만 두고 본문을 비우면 제목 + 강한 한 줄만 있는 첫 화면(실제 MP4 01에서 확인) |
| Frame 2~N · 내용 | 헤드라인, 본문(문단), 강조 문구(한 줄에 하나), 하단 자막, 출처, 레이아웃, 이미지, 길이, 전환 |
| 마지막 Frame · 마무리 | 같은 필드(정리 문장 + 출처) |
| 엔딩 화면 | CTA 문구, 채널 이름 |

프레임 버튼: **↑ 위로 / ↓ 아래로 / 복제 / 삭제**(마지막 한 장면은 삭제 불가). 새 빈 장면은 `EMPTY_SCENE`이라 만들지 않고 "복제 후 고치기"로 추가한다(본문이 넘칠 때 두 프레임으로 나누는 실제 흐름 — MP4 04).
**현재 구조상 지원 범위(억지로 UI를 만들지 않음)**: 글자 위치는 레이아웃이 정한다(레이아웃 선택으로 바꿈, 좌표 직접 이동 없음). 안전영역은 템플릿이 정하고 게이트가 검사한다. 자막 등장 시점/문단 지연은 템플릿 `animation` 값(장면별 조절 없음). 제목은 영상 내내 위에 고정되는 이 채널의 형식이다.

## 12. Browser workflow

Claude in Chrome(실제 Chrome)으로 `127.0.0.1:8765`(Draft/출력은 `artifacts/6-56-shorts-editor/`, 원본은 실제 data 읽기 전용)를 조작했다.

| 단계 | 결과 |
|---|---|
| 1~2 Editor 진입, 후보 선택 | 목록 5개, 필터/개수, 제목 클릭 → Editor |
| 3~4 제목·본문 수정(키보드 입력) | ✓ |
| 5 이미지 확인/선택 | 갤러리 썸네일 → sample_abstract 선택 ✓ |
| 6 layout 변경 | image_top ✓ |
| 7 Save | v2, 상태 Edited, 장면 정지 화면이 새 이미지로 다시 그려짐 ✓ |
| 8 Preview | 오버레이 표시 → Preview Ready, 게이트 PASS ✓ |
| 9 Render | 최종 렌더 → Rendered ✓, 승인 버튼 활성 → 승인 → Approved ✓ |
| 10 MP4 확인 | **처음엔 재생 안 됨 → 수정 후 재생 확인**(아래) |
| 11~12 재진입, 값 확인 | 새로고침 후 제목/본문/레이아웃/이미지 유지 ✓ |
| 13~14 Reset, 원본 복구 | v3 = 원본 제목/본문/text_focus/이미지 없음, 이전 영상에 "v2 영상 — 지금 버전과 다름", 승인은 v2에만 남음 ✓ |
| 추가: overflow | 본문을 늘려 저장 → Blocked, 렌더 버튼 비활성 + 이유, 해당 Frame 카드에 빨간 문장 ✓ |

**브라우저 검증에서 찾아 고친 문제**
1. **영상이 재생되지 않음**: MP4의 moov가 파일 끝에 있고 서버가 `Range`를 무시해 Chrome이 영상을 못 읽었다(6-55의 "Range 없이 통째로" 한계가 실제 결함이었다). → `_send_file`에 206/416 Range 구현 → 재생 확인(0:24, 1080x1920 프레임). 테스트 추가.
2. **동작 버튼에 닿을 수 없음**: 왼쪽 고정 열(영상+정지 화면+게이트+동작)이 화면보다 길어 버튼이 화면 밖. → 동작 카드를 맨 위로, 영상 높이 52vh, 고정 열 자체 스크롤.
3. **BLOCKED 이유를 찾기 어려움** → 게이트 카드를 동작 바로 아래로, 해당 Frame 카드 안에도 표시, 렌더 버튼 비활성+이유, 엔진 좌표 메시지는 툴팁으로.
4. 시간이 UTC로 보임 → PC 시간으로 표시. 승인 조건 문구가 "승인하려면: 승인하려면…"으로 중복 → 정리. 복제/이동 후 해당 프레임으로 스크롤.

**자동화 환경 한계(기록)**: 자동화 탭이 백그라운드(`visibilityState: hidden`)일 때 Chrome이 미디어 로딩을 미룬다 — 탭이 보일 때 재생됐다. 한 번은 저장 클릭이 레이아웃 이동 때문에 영상 위에 떨어졌고, 고정 열이 있는 상태에서 일부 textarea 입력이 들어가지 않아 그 단계(프레임 나누기)는 같은 서버에 HTTP로 수행했다(22장 04). 서버 로그로 요청 여부를 확인했다.

## 13. 테스트 결과

| 항목 | 결과 |
|---|---|
| baseline(시작, b2463c1, ffmpeg) | 1657 OK, skipped 11 |
| 최종 전체(ffmpeg) | **1684 tests OK, skipped 11** (baseline 1657 + 신규 27, FAIL 0, ERROR 0, 새 오류 0) |
| 신규 | `tests/test_6_56_shorts_editor.py` 27개 |
| 기존 테스트 수정 | `test_6_55…test_editor_has_no_approve_publish_or_secret_inputs` 1개: 6-55는 "approve/upload 컨트롤 없음"을 고정했는데 6-56 요구사항이 사람 승인·이미지 업로드다. 삭제/skip하지 않고 "승인은 Draft 범위 route 하나만, publish/youtube/threads/naver/token/secret/password 컨트롤 없음"으로 좁혔다 |
| KNOWN ENVIRONMENT ERROR | 이번 실행들에서 발생하지 않음 |
| skip 11 | 기존과 동일(환경 조건부 테스트) |

요청 11장 매핑: A `test_a_editor_load…` · B/C/E/F `test_b_c_e_f…` · D `test_d_image…`, `test_d_upload_image_through_editor_form`, `test_upload_validation` · G `test_g_frame_duplicate_move_delete` · H/I `test_h_reset_and_i_version_fields` · J/K/Z `test_j_k_z_preview_then_final_then_approve…` · L/M `test_l_pass_and_m_blocked…` · N/O/P/Q/R `test_n_missing_asset_and_o_p_q_r_long_text` · S/T/U `test_s_t_u_korean_english_numbers_symbols…` · V `test_v_same_content_is_idempotent` + 렌더 `skipped` · W 모든 StudioCase `tearDown` 원본 sha256 비교 + 실제 후보 테스트 전후 해시 · X `test_x_same_content_id_other_generation…` · Y `test_y_superseded…`, `test_superseded_row_is_locked_in_list` · 실제 5개 `test_five_candidates_open_and_check`. 그 밖: Range 206/416, 정지 화면 캐시/라우트 차단, 목록 필터·검색, 승인 조건·원본 변경 시 승인 차단, meta는 render key 불변, 강조/자막, 글꼴 누락 문자, 이미지 비율 경고, 상태 계산.

## 14. 실제 MP4 검증 결과

`artifacts/6-56-shorts-editor/production_run/`(Draft·렌더), `production_run_report.json`(단계별 기록·lineage), `contact_sheet.png`(최종 MP4에서 직접 뽑은 Frame 1/2 가운데 프레임). Editor HTTP 경로로 load → edit → save → preview → final → approve.

| # | content_id | 시나리오 | 최종 | layout | 길이 | 규격 | 프레임 | sha256(16) | gate | 미리보기/최종(초) | 상태 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 01 | content-e787c9201b94a948 | 글자 중심 + **Hook 프레임**(헤드라인만) + 분야 | v3 | text_focus | 13.5 | 1080x1920 h264/aac 2ch | 405 | a814b43044db080f | PASS | 15.5 / 19.5 | APPROVED |
| 02 | content-3ae2d78568210164 | **이미지 중심 image_full** + 책 출처(`자료 · 책 「사피엔스」`) | v2 | image_full,text_focus | 13.0 | 〃 | 390 | c679e107179e88a0 | PASS | 15.3 / 20.4 | APPROVED |
| 03 | content-ec0c38b9a20c424c | **split** + 세로 이미지 전체 보이기 + Reuters | v2 | text_focus,split | 25.0 | 〃 | 750 | 77dedb1f7ab37140 | PASS | 28.1 / 32.7 | APPROVED |
| 04 | content-e3b8d986ea6db98e | **긴 본문** → BLOCKED(BODY_OVERFLOW, MP4 없음) → 프레임 복제해 나눔 + 헤드라인 | v4 | text_focus | 41.5 | 〃 | 1245 | 00203e1c9edc419e | PASS | 38.7 / 47.6 | APPROVED |
| 05 | content-91869ed8be17f3f3 | **다른 출처 구조**(`인터뷰 · BBC News · …`) + 강조(Anthropic 하이라이트) + 하단 자막 + 진행 표시 위 + CTA + 음량 0.6 | v2 | text_focus | 26.0 | 〃 | 780 | 489b9ba1c52f9c20 | PASS | 24.0 / 30.7 | APPROVED |

5개 모두 최종 게이트 PASS(경고 0), 프레임 수 = 길이×30 정확. 이미지는 로컬 샘플/테스트 패턴(실제 사진 아님). 문장은 원문 그대로이고 사람이 고친 부분만 다르다.

## 15. 보안 검사

- API key / OAuth / refresh token / client secret / password 입력칸·저장·로그 없음. 편집 화면의 form action/input 이름에 publish/youtube/threads/naver/token/secret/password 없음(테스트).
- secret scan(패턴: `sk-`, `AIza`, `ya29.`, `1//`, `ghp_`, private key, `api_key|client_secret|refresh_token|access_token|password = "…"`): 변경 코드·테스트·문서·`artifacts/6-56-shorts-editor/`(Draft·manifest·보고서) **0건**.
- 환경변수의 실제 토큰/키 값(3개 후보)이 위 파일 67개에 들어 있는지 대조 → **0건**(값은 출력하지 않음).
- 네트워크: Studio 코드에 `requests/urllib.request/http.client/socket/openai/anthropic` import 없음. 서버는 127.0.0.1 바인딩 그대로.
- 파일 제공 범위: MP4 = 그 Draft 출력 폴더 + 파일명 정규식, 정지 화면 = 16자리 해시 폴더 + `sceneNN.png`, 이미지 = 저장소/asset 폴더 안 PNG/JPEG/WEBP(경로 조작·다른 파일 404 테스트). 업로드 = 20MB/320px/형식 검사 후 해시 이름으로만 저장, 본문 크기 초과는 읽기 전에 413.

## 16. Production data 변경 여부

| 항목 | 시작(11:37) | 종료 |
|---|---|---|
| `data/*.json` 12개 + `data/shorts_scripts/*.json` 2개 + 6-48 staging 5개(archive/export/ShortsScript) sha256 | 기록 | **모두 동일** |
| Production archive 레코드 (content_id, generation_id, review_status, superseded_by) 18건 | 기록 | **동일** (approved 2 그대로) |
| `data/` 아래 새 파일/폴더 | - | 없음(모든 Draft·렌더·업로드는 `artifacts/6-56-shorts-editor/`와 테스트 임시 폴더) |

Production mutation: **NO**. 승인 5건은 `artifacts/6-56-shorts-editor/production_run/drafts/*/approvals.json`에만 있다.

## 17. 남은 문제

- 미리보기가 최종보다 약 20%만 빠르다(병목 = 프레임 합성). 정지 화면이 즉시 확인을 맡지만, 긴 영상의 미리보기를 더 빠르게 하려면 프레임 합성 병렬화(6-54 21장)나 해상도 절반 미리보기(레이아웃 좌표 스케일링 필요)가 다음 후보.
- 렌더는 요청 안에서 동기 실행(로컬 1인용). 여러 명이 동시에 쓰면 작업 큐가 필요하다.
- 승인은 Draft 저장소 기록일 뿐이다 — 게시 파이프라인은 아직 이것을 읽지 않는다(18장).
- 글자 위치 직접 이동·장면별 자막 타이밍은 지원하지 않는다(11장, 템플릿 영역).
- 글꼴은 Noto Sans KR 하나 — 아랍어·히브리어·이모지는 경고만 하고 그리지 못한다(20장).
- 목록 분야는 Draft meta에만 있다(원본 archive에 분야 필드 없음).
- 브라우저 자동 검증의 자동화 한계(12장).

## 18. 다음 단계

1. **승인 → 게시 연결**: `approvals.json`의 `publish_contract`(video, artifact_sha256, content_id, knowledge_id, generation_id, title, duration, quality_status, source_url) + `render_key`를 `scripts/upload_youtube_short.py`가 입력으로 받게 한다. 업로드 직전 재확인: MP4 sha256 == 승인값, 현재 Draft 버전 == 승인 버전, 원본 sha256 == `base_content_sha256`, superseded 아님. Production archive 반영은 6-55 37장 D(새 generation + supersede, compare-and-swap)로.
2. 미리보기 속도(17장).
3. 템플릿 선택 UI(분야별 템플릿이 생길 때).

## 19. 향후 multi-category 확장 구조

```
ONE ENGINE (V3 문서 + 템플릿 + 렌더러 + 게이트 + Editor)
  └ MANY CATEGORIES: 분야별 Content Engine이 V3 문서를 만든다(지식/AI/금융/부동산/공인중개사/공무원/건강/역사/심리/게임/영화/음악/어린이/스토리)
       └ 분야별 모양 = 템플릿 파일 추가(글꼴·색·레이아웃·음악) — Editor는 레이아웃 목록을 템플릿에서 읽으므로 그대로
            └ MANY LANGUAGES(20장) → MANY PLATFORMS(Shorts 9:16 → Reels/TikTok 같은 비율, Threads/Blog는 텍스트 경로) → TRAFFIC → MONETIZATION
```
Editor가 분야에 의존하는 곳: `CATEGORIES` 선택 목록(표시용)뿐. 문서·검사·렌더에는 분야 분기가 없다(6-54 content-agnostic 테스트 유지).

## 20. 향후 multilingual 확장 구조

- 저장/HTTP/폼 모두 UTF-8(한글·영문·숫자/기호·일본어·한자 테스트 PASS).
- 글꼴: 템플릿 `look` → 글꼴 하나. 언어별로는 `look`(글꼴 경로)을 추가하고 Draft `meta.language`로 템플릿을 고르면 된다. **깨질 문자를 미리 알 수 있게** `missing_glyphs()`(글꼴 .notdef 비교)로 `FONT_GLYPH_MISSING` 경고를 만들었다 — 아랍어/히브리어/이모지는 현재 경고.
- 줄바꿈/overflow: 레이아웃 엔진은 글자 폭을 실제 글꼴로 재므로 언어와 무관. 읽는 속도는 템플릿 `chars_per_second`/`latin_chars_per_second`(언어별 값 추가 자리).
- RTL: 지금은 미지원. 하드코딩된 한국어 문장 규칙은 없고, 필요한 것은 텍스트 방향(Pillow `direction="rtl"` + raqm)과 정렬 — `draw_text_block` 한 곳.

## 21. 향후 AI Director 연결 구조

AI는 **V3 문서 한 장**만 만들면 된다 — 지금 구조가 그대로 맞다(API 구현 없음).

| ShortsBlueprint | V3 문서 / Draft |
|---|---|
| title | `title` |
| hook | `scenes[0].headline`(본문 없음) |
| frames[].text | `scenes[i].headline/body/emphasis/subtitle` |
| frames[].image_request | `scenes[i].image` 비워 두고 `image_request`(검색어/설명)를 문서에 추가 → 6-54 `AssetProvider.search/fetch`가 `data/shorts_assets/`에 받으면 Editor 갤러리에 뜬다 |
| frames[].layout / duration | `scenes[i].layout` / `duration` |
| source | `scenes[i].source` |
| CTA | `cta` |
| category/language | Draft `meta` |

흐름: AI Director → Blueprint(JSON) → V3 문서 → `DraftStore`(v1, `note: "AI 초안"`) → 사람이 Editor에서 수정 → 렌더 → 게이트 → 사람 승인. 검증은 저장 때와 같은 `check()`가 하므로 AI 결과가 틀려도 코드와 한국어 설명으로 막힌다.
