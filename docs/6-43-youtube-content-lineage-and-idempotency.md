# 6-43 YouTube Content Lineage and Idempotency

## 결론 요약

| 항목 | 결과 |
|---|---|
| content lineage | **READY** — 운영 업로드는 content_id가 필수이고, content_id / knowledge_id / generation_id / MP4 sha256 / video_id / 상태를 한 기록에 저장한다 |
| 6-42 영상(`RAZ3E4UBj6E`) ↔ content_id | **연결하지 않음(근거 없음)** — 원본에 content_id가 존재하지 않는다. 추측으로 만들지 않고 `upload_mode=test`, MP4 sha256, 출처(장면 설계 파일)만 사실대로 기록했다 |
| duplicate protection | **READY** — content_id 중복, 같은 content_id의 다른 generation, 같은 MP4(sha256)의 다른 content_id 우회, content_id 없는 운영 업로드를 모두 차단한다. 6-42 영상 재업로드도 이제 차단된다 |
| processing lifecycle | **READY** — UPLOAD_PENDING / UPLOADED / PROCESSING / SUCCEEDED / FAILED, 실패 사유와 last_checked_at 기록, 조회 전용 재확인 CLI |
| operator | **READY** — Operator Control Center에 "YouTube Uploads" 행 추가, 게시 감사에 업로드 기록을 연결(ALREADY_PUBLISHED 표시) |
| production mutation | Production Archive와 콘텐츠: 없음. `data/youtube_publish_log.json`: 스키마 migration과 상태 재확인만(식별 필드 불변, 백업 있음) |
| 실제 YouTube API | 새 업로드 **없음**. 6-42 영상 1건 상태 **조회만**(videos.list 1회 + 토큰 갱신). 공개 상태 변경·삭제 없음 |
| 테스트 | 1505 tests, failures 0, errors 9(사전 존재 Windows 이슈, 6-41~6-42와 같은 9건), skipped 17. 신규 24 tests |
| secret scan | 깨끗함 — 작업 트리와 git 전체 이력에서 client secret / refresh·access token / API key / OAuth client id 패턴 0건, 자격증명 파일 추적 0건 |

## 1. 작업 목적

"Shorts 생성 → ShortsScript → MP4 → content_id → YouTube video_id → publish history → 향후 성과 데이터"를
하나의 추적 가능한 lifecycle로 연결한다. 기존 구현은 다시 만들지 않고 연결·보강한다.

## 2. 기존 6-42 구조 (조사 결과)

| 구성 | 파일 | 6-42 시점 동작 |
|---|---|---|
| 업로드 클라이언트 | `content_engine/youtube_publisher.py` | OAuth refresh → resumable upload, `get_video_status()` / `wait_for_processing()`(6-42 추가) |
| 업로드 CLI | `scripts/upload_youtube_short.py` | `--content-id/--knowledge-id` **선택**. 있으면 Production Archive 재확인(approved, superseded, ShortsScript 일치)과 `is_published()` 중복 차단. **없으면 아무 검사 없이 업로드** |
| 업로드 기록 | `content_engine/youtube_upload_history.py` → `data/youtube_publish_log.json` | append 전용. 필드: video_id, uploaded_at, title, privacy_status, video_path, tags, url, content_id, knowledge_id, processing_status |
| Production Archive | `content_engine/media_archive.py` → `data/tak_media_archive.json` | `MediaArchiveRecord`(content_id, knowledge_id, platform, generation_status, review_status, generation_id, superseded_by). content_id는 `publish_history.compute_content_id()` 결정적 해시 |
| ShortsScript | `content_engine/shorts_adapter.py` → `data/shorts_scripts/<content_id>.json` | 승인된 Shorts 레코드에서만 생성, content_id/knowledge_id를 파일 안에 저장 |
| 중복 방지 | `YouTubeUploadHistory.is_published()` | **content_id 기준만** — content_id 없는 기록은 판정 대상 아님 |
| superseded 보호 | `publish_eligibility.check_content_supersede()` | content_id가 있을 때만 적용 |
| 게시 감사 | `publish_audit.audit_archive()` | `youtube_history`가 주어지면 shorts ALREADY_PUBLISHED 판정 |
| Operator | `content_engine/operator_summary.py` | 게시 감사를 호출하면서 **youtube_history를 넘기지 않음** → shorts의 ALREADY_PUBLISHED가 절대 표시되지 않는 상태였다 |
| 성과 | `content_engine/performance/youtube.py`, `scripts/collect_performance.py` | `--content-id`를 사람이 직접 넘김. 업로드 기록에서 대상을 꺼내는 경로 없음 |

## 3. 발견된 content_id 연결 문제

코드와 데이터를 직접 읽어 확인한 사실:

| 질문 | 답(근거) |
|---|---|
| A. 6-42 video_id | `RAZ3E4UBj6E` (`data/youtube_publish_log.json` 2번째 기록, 6-42 문서) |
| B. 업로드 MP4 | `artifacts/6-41-shorts-v2/shorts_v2_finance.mp4`, sha256 `aba5b3a8…4cb`(업로드 이후 파일 변경 없음 — 수정 시각 09-26 08:22 < 업로드 10:07) |
| C. 원본 | `content_engine/shorts_v2_specs/finance.json`(6-41에서 사람이 쓴 QA 장면 설계). **ShortsScript가 아니고, Production Archive·KNOWLEDGE에서 생성되지 않았다** |
| D. content_id | **없음** — 장면 설계 파일에 content_id 필드가 없고, 이 PC에는 Production Archive(`data/tak_media_archive.json`)도 `data/shorts_scripts/`도 없다 |
| E. knowledge_id | **없음**. 주제가 비슷한 KNOWLEDGE(`knowledge-e1cc05264953`, 은행 대출 재무제표 글)가 있지만 finance 장면 설계의 출처라는 기록이 없어 연결하지 않았다(추측 금지) |
| F. 기록 구조 | 2장 표. 6-42 기록은 content_id="" (legacy 업로드) |
| G. Archive ↔ history 연결 | content_id 문자열 일치만. generation_id·MP4는 기록되지 않았다 |
| H. YouTube 중복 판정 기준 | content_id만 → **content_id 없는 6-42 영상은 같은 명령으로 다시 올라갈 수 있었다**(6-42 문서 12장이 경고한 위험) |

추가로 발견한 문제:
1. content_id 없는 운영 업로드가 아무 경고 없이 허용됐다.
2. 같은 MP4를 다른 content_id로 올려도 막을 방법이 없었다(artifact 보호 정책이 저장소 어디에도 없음).
3. 같은 content_id인데 generation이 바뀐 경우를 구분하지 못했다(업로드 기록에 generation_id 없음).
4. `generation_status`가 valid가 아닌 레코드도 approved면 업로드 대상이 될 수 있었다.
5. 처리 상태를 나중에 다시 확인해 기록하는 경로가 없었다(업로드 직후 1회뿐).
6. Operator 게시 감사에 업로드 기록이 연결되지 않았다(2장 마지막 줄).

## 4. 최종 lineage 구조

```
KNOWLEDGE (knowledge_id)
  └─ MEDIA 생성 (generation pool: content_id + generation_id)
       └─ promote → Production Archive (content_id, knowledge_id, generation_id, review_status=approved, generation_status=valid)
            └─ ShortsScript  data/shorts_scripts/<content_id>.json  (content_id, knowledge_id 내장)
                 └─ MP4 (artifact_sha256)
                      └─ upload_youtube_short.py --content-id --knowledge-id
                           └─ publish log 기록 (content_id, knowledge_id, generation_id, artifact_sha256,
                                               video_id, privacy/upload/processing 상태, last_checked_at)
                                └─ performance_targets() → collect_performance.py --content-id (향후)
```

- content_id, knowledge_id: 사람이 CLI로 넘기고, 업로드 전에 Production Archive·ShortsScript와 일치하는지 검증한다(기존 6-26 계약).
- generation_id: 사람이 넘기지 않고 **Production Archive 레코드에서 읽어** 기록한다(입력 실수 방지).
- MP4: 업로드 직전 sha256을 계산해 기록한다.
- 테스트 업로드: content_id 대신 `source_ref`(출처 사실)와 sha256만 남기고 `upload_mode=test`로 구분한다. 성과 데이터와 연결하지 않는다.

## 5. YouTube publish record 구조

기존 `YouTubeUploadRecord` / `data/youtube_publish_log.json`을 그대로 확장했다(새 저장소 없음, 추가 필드는 전부 선택값, 기본값 "").

| 필드 | 의미 | 도입 |
|---|---|---|
| video_id, url | YouTube 식별자 | 기존 |
| uploaded_at | 업로드 성공 시각(UTC) | 기존 |
| title, tags, video_path | 요청 metadata / 로컬 경로 | 기존 |
| privacy_status | 공개 상태(재확인 시 실제 값으로 갱신) | 기존 |
| content_id, knowledge_id | lineage 키 | 6-02 |
| processing_status | YouTube `processingDetails.processingStatus` 원본 값(또는 WAITING_PROCESSING/UNKNOWN) | 6-42 |
| **generation_id** | Production 레코드의 generation | 6-43 |
| **upload_mode** | `production` / `test` / `legacy_unlinked` | 6-43 |
| **artifact_sha256** | 업로드한 MP4 sha256(중복 방지 키) | 6-43 |
| **source_ref** | content_id가 없는 업로드의 출처(사실만) | 6-43 |
| **upload_status** | YouTube `status.uploadStatus` 원본 값 | 6-43 |
| **processing_failure_reason** | `processingFailureReason` / `failureReason` / `rejectionReason`, 또는 조회 불가 사유 | 6-43 |
| **last_checked_at** | 마지막 상태 조회 시각 | 6-43 |

platform=youtube, format=shorts는 이 파일 자체가 YouTube Shorts 전용 저장소이므로 필드로 중복 저장하지 않았다.
superseded 여부는 Production Archive(`review_status/superseded_by`)가 원본이므로 복사하지 않고 업로드 시점에 조회한다.
lifecycle 상태는 원본 값(processing_status/upload_status)에서 `lifecycle_state()`로 계산한다(중복 필드 없음).

## 6. duplicate protection 정책

`scripts/upload_youtube_short.py`에서 네트워크 호출 **전에** 순서대로 판정한다.

| # | 상황 | 결과 | 검증 테스트 |
|---|---|---|---|
| 1 | 같은 content_id + 같은 generation이 이미 기록됨 | 재업로드 안 함(안내 후 exit 0, 멱등) | `test_same_content_id_same_generation_is_not_reuploaded` |
| 2 | 같은 content_id + 다른 generation | **차단(exit 1)**, 덮어쓰기 없음. 정정본은 supersede 절차로 새 content_id를 만들어 올리라고 안내 | `test_same_content_id_different_generation_is_blocked_not_overwritten` |
| 3 | superseded content_id | 차단(기존 6-19/6-26 로직) | `test_superseded_content_is_blocked` 외 기존 테스트 |
| 4 | invalid content(generation_status≠valid 또는 platform≠shorts) | **차단(6-43 추가)** | `test_invalid_generation_is_blocked` |
| 5 | content_id 없는 운영 업로드 | **차단(6-43)**. `--test-upload`(private 전용, content_id와 함께 쓸 수 없음)만 허용 | `test_production_upload_without_content_id_is_blocked`, `test_explicit_test_upload_is_allowed_only_private_and_without_content_id` |
| 6 | 정상 approved content | 업로드, 전체 lineage 기록 | `test_production_upload_records_full_lineage` |
| 7 | video_id가 이미 기록된 content | 재업로드 차단(1과 같은 경로) | 1과 동일 |
| 8 | 같은 MP4를 다른 content_id(또는 테스트 모드)로 우회 | **차단(6-43, sha256)** | `test_same_mp4_under_another_content_id_is_blocked`, `test_same_mp4_blocked_even_in_test_mode` |

기존 동작 변경(의도된 변경): 6-42까지 허용되던 "content_id 없이 바로 live 업로드"는 이제 `--test-upload`가 있어야 한다.
이 동작을 전제로 한 기존 테스트 8개(`test_upload_youtube_short_cli` 4, `test_superseded_downstream_safeguards` 1, `test_6_42_youtube_upload_pipeline` 3)는
삭제하거나 skip하지 않고 `--test-upload`를 명시하도록만 바꿨다(단언은 그대로). `--dry-run`은 content_id 없이도 계속 되며,
"live 실행은 --content-id 또는 --test-upload가 필요"라고 안내한다.

## 7. generation / superseded 처리

- 기존 정책(6-06, 6-17)을 그대로 따른다: Production Archive에는 content_id당 활성 레코드가 1건이고, 정정본은 generation pool에서 승격되며, 옛 승인본은 `superseded`(→ `superseded_by`)가 된다.
- 업로드 기록에는 업로드 당시의 generation_id를 남긴다. 나중에 같은 content_id에 다른 generation이 승격돼도 **자동 재업로드나 기록 덮어쓰기를 하지 않는다**(6장 #2). 운영자가 supersede 절차를 밟아야 한다.
- superseded content_id는 업로드 전에 차단된다(6장 #3).
- 테스트 업로드는 Production과 무관하므로 generation 판정 대상이 아니다.

## 8. processing lifecycle

| 상태 | 판정 규칙(`youtube_upload_history.lifecycle_state`) |
|---|---|
| UPLOAD_PENDING | 기록이 아직 없는 승인 콘텐츠(게시 감사의 READY와 같은 의미의 파생 상태 — 기록에 저장하지 않음) |
| UPLOADED | 기록은 있지만 처리 상태를 모름(조회 실패 UNKNOWN, legacy 등) |
| PROCESSING | processing_status가 `processing` 또는 `WAITING_PROCESSING`(폴링 한도 도달) |
| SUCCEEDED | processing_status `succeeded` 또는 upload_status `processed` |
| FAILED | processing_status `failed`/`terminated` 또는 upload_status `rejected`/`failed`/`deleted` |

- 업로드 직후: `wait_for_processing()`(최대 6회)로 확인하고 privacy/upload/processing 상태, 실패 사유, last_checked_at을 기록한다.
- 처리 실패: video_id와 실패 사유를 보존한다(기록 삭제·자동 재업로드 없음) — `test_processing_failure_keeps_video_id_and_reason`.
- 상태 조회 자체 실패: 업로드는 성공으로 두고 `UNKNOWN`(→ UPLOADED)으로 기록한다.
- 나중에 다시 확인: **`scripts/refresh_youtube_status.py --video-id <id>`**(신규). videos.list **조회만** 하고, publish log에 있는 video_id만 허용한다(다른 영상 조회 거부).
  privacy/upload/processing/실패 사유/last_checked_at만 `update_record()`로 갱신한다 — 식별 필드(video_id/content_id/knowledge_id/uploaded_at/url)는 바꿀 수 없다.
  영상을 찾지 못하면 사유를 기록한다.

## 9. 6-42 실제 영상 연결 결과

**Migration (before snapshot → migration → after validation)** — `scripts/migrate_youtube_publish_log.py`(신규, 네트워크 없음):

1. dry-run: 변경 대상 2건 확인.
2. before snapshot: `data/youtube_publish_log.backup-6-43-20260926T012204Z.json`
   (원본과 바이트 동일 확인, sha256 앞자리 `e3dcb1cb6bb169a6` = migration 전 파일. `data/*.json` 규칙으로 git에서 제외됨).
3. migration(순수 함수 `migrate_history_records`):
   - `RAZ3E4UBj6E` → `upload_mode=test`, `artifact_sha256`=finance MP4 실제 해시, `source_ref`=
     "content_engine/shorts_v2_specs/finance.json (6-41 QA 장면 설계, content_id 없음)". **content_id/knowledge_id는 빈 값 그대로.**
     근거: 6-42 문서가 이 업로드를 PRIVATE 테스트 업로드로 기록했고, MP4 해시는 실제 파일에서 계산했다.
   - `h2X1fFMDffc`(2026-09-17, 다른 환경의 업로드) → `upload_mode=legacy_unlinked`. MP4(`data/shorts/youtube_upload_test.mp4`)가 이 PC에 없어 해시를 만들 수 없다. 추정 값을 넣지 않았다.
4. after validation: 레코드 수·순서·식별 필드(video_id/uploaded_at/title/url/content_id/knowledge_id/video_path/tags) 불변 확인, 저장 후 다시 읽어 일치 확인.
5. 재실행: "변경 대상 0건 — 파일을 쓰지 않습니다"(멱등).

**조회 전용 상태 재확인**(실제 API, 6-42 영상만):

```
RAZ3E4UBj6E: found=True privacy=private upload=processed processing=succeeded lifecycle=SUCCEEDED
```
→ `upload_status=processed`, `last_checked_at=2026-09-26T01:22:12Z` 기록. 공개 상태는 private 그대로.

**보호 확인**(실제 데이터, 네트워크 없음):
- 같은 finance MP4를 `--test-upload`로 다시 올리려 하면 → "차단: 같은 MP4가 이미 업로드되어 있습니다(video_id=RAZ3E4UBj6E…)" exit 1 (dry-run과 live 모두).
- `shorts_v2_ai.mp4`를 content_id 없이 올리려 하면 → "차단: content_id 없는 운영 업로드는 허용하지 않습니다" exit 1.
- 두 시도 모두 publish log를 바꾸지 않았다.

**결론:** 6-42 영상은 content_id와 연결할 수 없다(원본에 content_id가 존재한 적이 없음). 대신 test 업로드로 명확히 구분됐고,
MP4 해시로 재업로드가 막혔으며, 성과 수집 대상(`performance_targets()`)에서도 빠진다.
content_id로 추적하려면 이 콘텐츠를 KNOWLEDGE → MEDIA → Production 승인 → ShortsScript 경로로 정식 등록해야 하는데,
그렇게 만든 새 MP4는 새 업로드 대상이다(이번 작업에서는 하지 않음).

## 10. Operator Control Center 연결

- `OperatorInputs.youtube_history`(신규, 읽기 전용)를 `scripts/operator_control_center.py`와 `run_scout_dashboard.py`의 Operator 화면에서 `data/youtube_publish_log.json`으로 채운다.
- 게시 감사에 `youtube_history`를 넘긴다 → Production shorts 레코드가 업로드됐으면 "YouTube Shorts: ALREADY_PUBLISHED"로 보인다(기존에는 불가능했음).
- 새 단독 필드 `OperatorSummary.youtube_uploads`("YouTube Uploads" 행, performance/recovery와 같은 패턴). 기존 6-38 계약(PUBLISH STATUS는 3개 플랫폼, DATA HEALTH는 8개 분류)은 바꾸지 않았다.
- 실제 출력(이 PC):
  ```
  YouTube Uploads: UPLOADED (2건)
      WHY: legacy_unlinked 1건, test 1건 / h2X1fFMDffc[legacy_unlinked] content_id=- privacy=private lifecycle=UPLOADED
           / RAZ3E4UBj6E[test] content_id=- privacy=private lifecycle=SUCCEEDED
      ACTION: 중복 방지 키(content_id/MP4 hash)가 없는 legacy 기록: ['h2X1fFMDffc'] - 같은 파일 재업로드를 CLI가 감지하지 못합니다.
  ```
  전체 상태가 UPLOADED인 이유: `h2X1fFMDffc`는 처리 상태가 기록된 적이 없고, 이번 작업에서는 6-42 영상만 조회하도록 제한했다.
- Operator는 계속 READ-ONLY다(history는 `load()`만 호출).

## 11. 테스트 결과

| 실행 | 결과 |
|---|---|
| 신규 `tests/test_6_43_youtube_lineage.py` | **24 OK** — lineage 기록, content_id 없는 운영 업로드 차단, 테스트 모드 제약, 같은/다른 generation, superseded, invalid, 같은 MP4 우회(운영/테스트), processing 실패/성공/조회 실패, 성과 대상 필터, lifecycle 매핑, 식별 필드 보호, migration(표시·멱등·충돌·미존재 video·CLI 백업·실패 시 파일 불변·재실행 무기록), 상태 재확인(갱신·미등록 video 거부·미발견 사유), operator(행·ALREADY_PUBLISHED·legacy 경고·없음) |
| Operator/6-38/6-39 | 111 OK(6-43 테스트 포함) |
| YouTube 관련(6-42, upload CLI, eligibility, superseded, 6-30, e2e) | 87 OK |
| 전체 회귀 `py -m unittest discover -s tests` | **1505 tests, failures 0, errors 9, skipped 17** |

errors 9는 **사전 존재 오류**다: `subprocess.run(capture_output=True)`의 `stdout=None`(Windows 환경) —
test_content_engine 1, test_knowledge_review 1, test_media_batch 2, test_media_viewer 1, test_run_scout_cli 1, test_threads_publisher 3.
6-41에서 깨끗한 HEAD worktree로 재현했고, 6-42와 파일·건수가 같다.

작업 중 생긴 **신규 오류 2건은 모두 고쳤다**:
1. `test_6_39 …does_not_write_target_file`: 테스트가 만든 argparse Namespace에 새 인자가 없어서 → `getattr`로 선택 처리.
2. `test_6_38 …test_three_platforms_independent`: PUBLISH STATUS에 4번째 행을 넣어 계약이 깨져서 → 단독 필드로 옮김(계약 유지).

모든 테스트는 실제 YouTube API를 호출하지 않는다(urlopen 차단 + 가짜 transport).

## 12. 보안 검사 결과

| 검사 | 결과 |
|---|---|
| 자격증명 이름의 추적·미추적 파일(`client_secret*`, `*token*.json`, `.env`) | 0건 |
| 작업 트리 패턴(Google client secret `GOCSPX-`, access token `ya29.`, refresh token `1//0`, API key `AIza`, OAuth client id `…apps.googleusercontent.com`) | 0건(artifacts 제외 전체) |
| git 전체 이력(`git log -p --all`) 같은 패턴 | 0건 |
| OAuth client JSON | `%USERPROFILE%\Downloads`에만 있고 저장소 밖이다 |
| 자격증명 값 | Windows 사용자 환경변수에만 있다. 이 작업 중 출력하지 않았다 |

## 13. 남은 위험

1. **6-42 영상은 content_id가 없다** — 성과 데이터와 연결되지 않는다(설계대로 제외).
2. **`h2X1fFMDffc`는 중복 방지 키가 없다** — 원본 MP4가 이 PC에 없다. 그 파일을 다시 올리면 CLI가 감지하지 못한다(Operator ACTION에 표시).
3. **MP4 해시는 바이트 기준이다** — 같은 내용을 다시 인코딩하면 해시가 달라져 우회된다. 같은 content_id면 1차 차단이 막지만, 다른 content_id + 재인코딩은 막지 못한다.
4. 이 PC에는 Production Archive가 없어 운영 경로(content_id 업로드)를 실제 데이터로 끝까지 실행해 보지 못했다(fixture로만 검증).
5. OAuth 동의 화면이 Testing이면 refresh token이 약 7일 뒤 만료될 수 있다(6-42 문서).
6. publish log는 git에 커밋되는 파일이라 여러 PC가 동시에 업로드하면 병합 충돌 위험이 있다(기존 설계, 이번에 바꾸지 않음).

## 14. 다음 작업 후보

1. 이 PC에 Production Archive를 복구하거나 새로 만들고(6-39 복구 절차), 승인된 Shorts 1건으로 ShortsScript → 렌더 → `--content-id` PRIVATE 업로드까지 운영 경로를 실제로 한 번 실행하기.
2. `performance_targets()`를 `scripts/collect_performance.py`에 연결해(대상 자동 선택) 첫 성과 스냅샷 수집하기 — statistics 호출은 소량으로.
3. 6-41 v2 렌더러를 ShortsScript 입력과 연결해(`spec_from_shorts_script` 확장) Production 콘텐츠에서 곧바로 v2 스타일 MP4를 만들기.
4. 재인코딩 우회를 막으려면 영상 지문(perceptual hash) 검토 — 필요성부터 판단.
5. PUBLIC 전환 정책과 API 프로젝트 감사(audit) 여부 결정(6-42 16장).
