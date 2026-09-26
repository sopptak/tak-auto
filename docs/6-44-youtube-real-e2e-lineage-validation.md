# 6-44 YouTube Real E2E Lineage Validation

## 결론 요약

| 항목 | 결과 |
|---|---|
| 판정 | **BLOCKED** — 이 PC에 실제 운영 콘텐츠(content_id가 있고, valid·approved이며 superseded가 아닌 Shorts와 그 ShortsScript)가 **존재하지 않는다** |
| 실제 YouTube upload | **없음 (0회)** — 지시 2장("기존 정상 콘텐츠가 없다면 … BLOCKED")과 5장("하나라도 실패하면 API 호출하지 말고 BLOCKED")에 따름 |
| YouTube API 호출 | **0회** (토큰 갱신 포함, 이번 세션에서는 전혀 호출하지 않음) |
| content_id / video_id | none / none |
| 운영 경로 리허설 | **통과** — 실제 CLI(ShortsScript 생성 → 6-40 운영 렌더러로 실제 MP4 → 업로드 CLI)에 가짜 YouTube 클라이언트만 넣어 content_id → MP4 → video_id → publish log → 중복 차단 → Operator까지 확인(임시 디렉터리) |
| lineage 구조 | READY(6-43 구조, 리허설로 확인). 실제 데이터로는 미검증 |
| duplicate guard | READY — 실제 CLI 경로로 확인, 두 번째 시도는 dry-run·live 모두 API 호출 없이 차단 |
| operator | READY(리허설) — content_id → video_id → privacy → lifecycle 표시, "YouTube Shorts: ALREADY_PUBLISHED" |
| production mutation | **없음** — data/ 파일 해시가 6-43 종료 시점과 모두 같음 |
| 테스트 | 1509 tests, failures 0, errors 9(사전 존재 Windows 이슈, 6-41~6-43과 같은 9건), skipped 17. 신규 4 tests |
| secret scan | 깨끗함(작업 트리 0, git 전체 이력 0, 자격증명 파일 추적 0) |

## 1. 목적

content_id를 가진 실제 운영 콘텐츠 1건으로
ShortsScript → Shorts MP4 → YouTube PRIVATE 업로드 → video_id → publish history → Operator
전체 lineage를 실제 운영 경로에서 검증한다. 6-43 구조를 그대로 쓰고, 실제 업로드는 최대 1회(PRIVATE)만 허용된다.

## 2. 선정한 content_id

**선정 불가.** 조사 결과(추측 없이 파일·git으로 확인):

| 확인 대상 | 결과 |
|---|---|
| `data/tak_media_archive.json`(Production Archive) | **없음** |
| git 전체 이력의 `data/tak_media_archive.json` | **한 번도 커밋된 적 없음**(`git log --all -- data/tak_media_archive.json` 결과 없음) — 6-39 분류로 STATE A, 복구할 원본이 저장소에 없다 |
| `data/shorts_scripts/` | 없음(git 이력에도 없음) |
| 사용자 폴더 전체(깊이 4, Temp 제외)의 `tak_media_archive*.json` / `tak_media_generation*.json` / `shorts_scripts` | `artifacts/6-40-content-preview/shorts_scripts`만 발견 — 6-40 QA 대본이며 **content_id 필드가 없다**(title/subtitle/cards만) |
| `data/tak_media_batch_e2e_test.json` | 과거 샘플 배치 리포트이며 항목 0건(Production Archive 아님) |
| `data/tak_threads_pending.json` | Threads 5건 — Threads 플랫폼이고 Shorts Production 레코드가 아님 |
| KNOWLEDGE | 28건 중 approved 6건 — 원료는 있지만 MEDIA 생성·사람 검수 승인·promotion을 거친 Shorts가 없다 |

선정 조건(valid, approved, not superseded, content_id, ShortsScript) 중 **첫 단계(Production 레코드)부터 충족하는 콘텐츠가 0건**이다.

만들어서 진행하지 않은 이유:
- 지시: "임의로 content_id를 새로 만들지 않는다", "Production Archive를 불필요하게 변경하지 않는다".
- `review_status=approved`는 설계상 **사람이 MEDIA Dashboard에서 내리는 결정**이다(`handle_media_approve_submission`). 이것을 에이전트가 대신 채우면 승인 게이트를 우회하게 된다.
- 6-41 finance MP4(6-42 영상)는 content_id가 없어 지시 3장에 따라 재사용하지 않았다(재사용해도 6-43 가드가 해시로 차단함).

## 3. ShortsScript lineage

실제 데이터: 없음(2장).

운영 경로 자체는 리허설로 확인했다(`tests/test_6_44_e2e_lineage_rehearsal.py`, 임시 디렉터리):
- 임시 Production Archive에 approved/valid Shorts 레코드 1건(content_id `content-e2e0001`, knowledge_id `knowledge-e2e`, generation_id `gen-e2e-1`) — **테스트 fixture 값이며 운영 데이터가 아니다**.
- `scripts/generate_approved_shorts_script.py --content-id content-e2e0001` 실제 실행 → `<dir>/content-e2e0001.json`, 파일 안의 content_id 일치 확인.

## 4. MP4 artifact

실제 운영 MP4: 없음.

리허설: `scripts/render_youtube_short.py`(6-40 운영 렌더러, 로컬 ffmpeg)로 위 ShortsScript를 **실제 MP4로 렌더링** → 업로드 CLI가 계산한 sha256이 publish log의 `artifact_sha256`과 일치함을 확인했다.
(6-41 v2 렌더러는 아직 ShortsScript 입력과 연결되지 않은 프로토타입이라 "운영 렌더러"로 쓰지 않았다.)

## 5. 실제 YouTube video_id

없음 — 업로드하지 않았다. 기존 6-42 영상 `RAZ3E4UBj6E`는 건드리지 않았다(재업로드·상태 변경·조회 없음).

## 6. privacy

해당 없음. 리허설에서 업로드 요청의 `privacyStatus`가 `private`임을 확인했다(PUBLIC/UNLISTED 없음).

## 7. processing 결과

실제: 해당 없음.

리허설: 가짜 상태 응답을 `processing` → `succeeded` 순서로 주어 `wait_for_processing()` 폴링 경로를 통과시켰다
→ 기록 `processing_status=succeeded`, `upload_status=processed`, lifecycle **SUCCEEDED**, `last_checked_at` 기록.
처리 실패 응답(`failed`, `transcodeFailed`)에서는 video_id와 실패 사유가 보존되고 lifecycle **FAILED**, exit 0(업로드 자체는 성공으로 기록).

## 8. content_id ↔ video_id 연결

실제: 없음.

리허설 기록(publish log 1건):

| 필드 | 값 |
|---|---|
| content_id | content-e2e0001 |
| knowledge_id | knowledge-e2e |
| generation_id | gen-e2e-1 (Production 레코드에서 읽음) |
| upload_mode | production |
| artifact_sha256 | 렌더링한 MP4의 실제 sha256 |
| video_id | video-e2e-1 (가짜 클라이언트) |
| privacy_status / upload_status / processing_status | private / processed / succeeded |
| uploaded_at / last_checked_at | 둘 다 기록됨 |

## 9. duplicate 재시도 차단 결과

실제 업로드가 없어 실데이터로는 수행할 수 없었다. 리허설(실제 업로드 CLI 경로):
- 1회차: content-e2e0001 → video-e2e-1 (가짜 API 업로드 1회)
- 2회차 `--dry-run`: "이미 YouTube 업로드 이력에 있습니다. 다시 업로드하지 않습니다." (DUPLICATE BLOCKED)
- 3회차 live: 같은 메시지, **API 업로드 호출 수 1 그대로**, publish log 1건 그대로.

업로드 직전 가드(지시 5장)도 확인했다 — 모두 API 호출 0회로 차단:
unapproved(unreviewed), invalid(generation_status=rejected), superseded, ShortsScript 없음, content_id 없음.
(same content_id / different generation 차단은 6-43 테스트가 이미 검증했다.)

실제 데이터에서 확인한 가드: `--content-id any`로 dry-run하면
"차단: content_id=any: production archive에 이 레코드가 없습니다(ORPHAN)" exit 1.

## 10. Operator 결과

리허설에서 `build_operator_summary()` 결과:
- `youtube_uploads.why`에 `video-e2e-1[production] content_id=content-e2e0001 privacy=private lifecycle=SUCCEEDED`
- PUBLISH STATUS의 "YouTube Shorts" = **ALREADY_PUBLISHED**(6-43에서 연결한 게시 감사 경로)
- 중복 방지 상태: content_id와 MP4 hash가 모두 있어 legacy 경고가 없다.

이 PC의 실제 Operator 출력은 6-43과 같다(YouTube Uploads: UPLOADED 2건 — legacy 1, test 1).
Operator 코드는 이번에 바꾸지 않았다.

## 11. 테스트 결과

| 실행 | 결과 |
|---|---|
| 신규 `tests/test_6_44_e2e_lineage_rehearsal.py` | **4 OK** — 실제 렌더러를 포함한 전체 체인, 렌더러 없는 체인, 처리 실패 보존, 업로드 전 가드 5종(모두 API 0회) |
| 전체 회귀 `py -m unittest discover -s tests`(ffmpeg 지정) | **1509 tests, failures 0, errors 9, skipped 17** |

errors 9는 사전 존재 오류다(`subprocess.run(capture_output=True)`의 `stdout=None`, Windows 환경):
test_content_engine 1, test_knowledge_review 1, test_media_batch 2, test_media_viewer 1, test_run_scout_cli 1, test_threads_publisher 3.
6-41에서 깨끗한 HEAD worktree로 재현했고, 6-42/6-43과 파일·건수가 같다. 신규 오류는 0건이다.

지시 11장 항목과 검증 위치:

| 항목 | 위치 |
|---|---|
| 정상 content_id → upload allowed | 6-44 체인 테스트, 6-43 `test_production_upload_records_full_lineage` |
| content_id 없음 / invalid / unapproved / superseded → blocked | 6-44 `test_pre_upload_guards_block_before_api`, 6-43 |
| duplicate content_id → blocked, idempotency | 6-44 체인(dry-run+live 재시도), 6-43 |
| same content_id / different generation | 6-43 `test_same_content_id_different_generation_is_blocked_not_overwritten` |
| video_id lineage, processing succeeded/failed persistence | 6-44, 6-43 |
| Operator summary | 6-44 체인, 6-43 OperatorTests |
| **실제 6-44 upload record persistence** | **미수행 — 실제 업로드가 없음(BLOCKED)** |

## 12. 보안 검사

| 검사 | 결과 |
|---|---|
| 자격증명 이름의 추적·미추적 파일 | 0건 |
| 작업 트리 패턴(client secret, access/refresh token, API key, OAuth client id) | 0건 |
| git 전체 이력 같은 패턴 | 0건 |
| 이번 세션의 자격증명 사용 | 없음(API를 호출하지 않았으므로 환경변수를 불러오지도 않음) |

## 13. production mutation

**없음.** `data/*.json` sha256(앞 16자리)이 작업 전후 동일하다:
scout_sources `62b192f7…`, tak_brain_knowledge `b10724da…`, tak_media_batch_e2e_test `48ef75ee…`, tak_scout_daily `16e069e1…`,
tak_threads_pending `c9a51eae…`, threads_publish_log `5e7eeede…`, youtube_publish_log `07a027e1…`(6-43 migration 후 값 그대로).
Production Archive는 만들지 않았고, supersede·삭제도 하지 않았다. 리허설은 전부 임시 디렉터리에서 실행됐다.

## 14. 남은 문제

1. **이 PC에는 운영 콘텐츠가 없다.** Production Archive가 git에 한 번도 커밋되지 않았으므로, 다른 PC에 있거나 아직 만들어진 적이 없다.
2. content_id가 있는 실제 업로드와 실데이터 중복 차단은 **아직 한 번도 실행되지 않았다**(리허설로만 검증).
3. 운영 렌더러는 6-40 카드뉴스 스타일이다. 사용자가 좋게 평가한 6-41 v2 스타일은 ShortsScript와 연결되지 않았다.
4. refresh token이 Testing 상태라면 약 7일 뒤 만료될 수 있다(6-42). 업로드 전에 `youtube_oauth_setup.py --check`와 조회로 확인해야 한다.

## 15. 다음 단계 (BLOCKED 해제 절차 — 사람의 승인 필요)

1. Production Archive가 있는 PC가 있으면 그 파일을 이 PC로 복구한다(6-39/6-21 복구 절차). 없으면 아래 2~4로 새로 만든다.
2. 승인된 KNOWLEDGE(현재 6건)로 MEDIA를 생성한다: `py scripts/run_media_batch.py …` → generation pool.
3. **사람이** MEDIA Dashboard(`scripts/run_scout_dashboard.py`)에서 Shorts 1건을 검수·승인하고, `py scripts/promote_media_generation.py … --execute`로 Production Archive에 승격한다.
4. `py scripts/generate_approved_shorts_script.py --content-id <id>` → `py scripts/render_youtube_short.py --input data/shorts_scripts/<id>.json --output <mp4> --ffmpeg <ffmpeg>`.
5. 업로드 전 가드: `py scripts/upload_youtube_short.py --video <mp4> --title … --content-id <id> --knowledge-id <kid> --privacy private --dry-run`.
6. 가드를 통과하면 같은 명령을 `--dry-run` 없이 **1회** 실행한다(PRIVATE). 그 뒤 `py scripts/refresh_youtube_status.py --video-id <vid>`와 Operator로 확인하고, 같은 명령 재실행이 차단되는지 dry-run으로 확인한다.
7. (선택) 6-41 v2 렌더러에 ShortsScript 입력을 연결해 운영 콘텐츠를 v2 스타일로 렌더링한다.
