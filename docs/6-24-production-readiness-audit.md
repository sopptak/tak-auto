# 6-24 Production Readiness Audit

## 1. 감사 목적

6-19~6-23에서 개별 안전장치(supersede lifecycle, 데이터 동기화, recovery
staging/approval)를 하나씩 쌓아 왔다. 이번 6-24는 새 기능을 만드는 대신,
TAK AUTO 전체를 SCOUT부터 Performance까지 실제 운영 관점에서 end-to-end로
감사해서 "무엇이 실제로 작동하고, 무엇이 문서/코드만 존재하고, 무엇이 운영을
막으며, 10월 1일 이후 무엇을 먼저 해야 하는가"를 확정한다.

이 문서는 코드/문서를 직접 읽은 근거(파일:줄번호 또는 파일명)를 반드시
동반한다 — 추측으로 채우지 않는다. 실제 Production Archive는 생성하지
않았고, 실제 외부 API도 호출하지 않았다(전부 read-only 감사 + tempfile
기반 테스트).

## 2. 전체 아키텍처

| 단계 | 입력 | 출력 | Source of truth | 주요 모듈 | 주요 CLI | Dashboard | GitHub Actions | 외부 API | Human approval | 자동화 | 테스트 | 운영 가능 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| SCOUT | `data/scout_sources.json`(RSS 목록) | `data/tak_scout_daily.json/.md` | scout_sources.json(설정만 tracked) | `tak_scout/collector.py`, `scoring.py` | `scripts/run_scout.py` | 없음(파일 열람) | `daily-scout.yml`(매일 KST 08:00) | RSS fetch | 불필요(rule-based) | 완전 자동 | `test_article_types.py` 등 | 가능 |
| KNOWLEDGE | SCOUT candidate + INTERVIEW 답변 | `data/tak_brain_knowledge.json`(pending) | tak_brain_knowledge.json(tracked) | `tak_scout/knowledge_bridge.py`, `tak_brain/knowledge.py` | `scripts/run_interview.py`, `apply_interview.py`, `create_knowledge.py`, `review_knowledge.py` | 있음(승인/거절) | 없음 | 없음 | **필수**(approved만 다음 단계 진입) | 반자동(사람 답변 필요) | 있음(감사에서 확인) | 가능 |
| MEDIA GENERATION | approved KNOWLEDGE | Blog 1 + Shorts 3 + Threads 5 = 9 draft | `data/tak_media_archive.json` 또는 generation pool | `content_engine/pipeline.py`, `generator.py`, `rewrite.py` | `scripts/run_media_batch.py` | 없음(생성 자체는 CLI 전용) | `daily-media-prepare.yml`(승인된 것만 준비, 생성은 안 함) | LLM(OpenAI 호환) | approved KNOWLEDGE만 입력(가능하지만, **P0 수정 전에는 재실행 시 승인된 결과가 조용히 바뀔 위험**, 4장) | 반자동 | 있음 | **가능(6-24 P0 수정 후)** |
| GENERATION POOL | MEDIA 배치 결과(`--as-generation`) | `(content_id, generation_id)` 복수 보존 | 별도 generation pool 파일(호출부 지정) | `content_engine/media_archive.py` | `scripts/run_media_batch.py --as-generation` | `/media/generations`에서 검토/승인 | 없음 | 없음 | 검토/승인 UI 있음 | 반자동 | 있음(6-06~6-09) | 가능 |
| HUMAN REVIEW | generation pool 후보 | 사람의 approve/dismiss/edit | 없음(행위, 상태만 archive에 반영) | `run_scout_dashboard.py` | 없음(UI 전용) | `/media`, `/media/generations` | 없음 | 없음 | 이 단계 자체가 human approval | 수동(의도됨) | 부분적(핸들러 단위) | 가능(단 promotion은 UI에 없음, 아래) |
| PROMOTION | 승인된 generation | production archive 갱신 | `data/tak_media_archive.json` | `content_engine/media_archive.py`(`check_promotion_conflict`) | `scripts/promote_media_generation.py` | **없음(의도적으로 CLI 전용)** | 없음 | 없음 | 이미 승인된 것만 대상 | 수동(CLI 필수) | 있음(6-06, 6-18) | 가능 |
| PRODUCTION ARCHIVE | promotion/legacy archive_report | 전체 이력(valid+rejected+error) | `data/tak_media_archive.json`(현재 NOT_PRESENT) | `content_engine/media_archive.py` | 여러 CLI 공유 | `/media`(레거시 직접 대상) | `daily-media-prepare.yml`(읽기 전용) | 없음 | archive 자체는 human approval의 결과 저장소 | 부분 자동 | 매우 두꺼움(6-06~6-23) | 가능(파일이 아직 없음) |
| PUBLISH READINESS | production archive + 각 채널 이력 | READY/NEEDS_HUMAN_REVIEW/BLOCKED/... | 없음(순수 판정) | `content_engine/publish_audit.py`, `publish_eligibility.py` | `scripts/audit_publish_candidates.py` | 없음(Markdown 보고서) | `daily-media-prepare.yml`(요약만) | 없음 | 판정만, 승인은 이미 되어 있어야 함 | 자동(read-only) | 있음 | 가능 |
| THREADS | approved+ready Threads draft | 실제 게시 + `threads_publish_log.json` | `data/tak_threads_pending.json` | `content_engine/threads_review.py`, `threads_publisher.py` | `scripts/generate_threads_draft.py` → Dashboard 승인 → `scripts/publish_approved_threads.py` | `/threads` 승인 화면 | `publish-approved-threads.yml`(workflow_dispatch), `daily-threads-post.yml`(**cron 비활성화**, 5-19) | Threads API | 필수(승인+발행 직전 재확인, 6-19) | 반자동(발행은 workflow_dispatch 수동) | 있음(21개, 6-19) | 가능 |
| SHORTS | approved shorts record | ShortsScript JSON + YouTube 업로드 | `data/shorts_scripts/*.json` | `content_engine/shorts_adapter.py`, `youtube_publisher.py` | `scripts/generate_approved_shorts_script.py`, `upload_youtube_short.py` | 없음(승인은 `/media`에서) | `daily-media-prepare.yml`(script 생성만) | YouTube API | 필수(`--content-id` 지정 시에만 재확인, P2) | 반자동 | 있음 | **부분 가능**(mp4 렌더링 코드 자체가 이 저장소에 없음, OAuth 최초 설정 스크립트 누락 — P1) |
| BLOG | approved blog record | `data/blog_publish_pack_daily.md` + 사람의 수동 게시 | `data/blog_publish_log.json`(**미tracked**, P1) | `content_engine/blog_publish_pack.py` | `scripts/generate_blog_publish_pack.py`, `mark_blog_published.py` | 없음(승인은 `/media`에서) | `daily-media-prepare.yml`(pack 생성, artifact 보존만) | 없음(Naver API 자체가 없음) | 필수 + 수동 copy/paste + 수동 mark | 반자동 | 있음 | 가능(수동 워크플로우) |
| PUBLISH AUDIT | production archive + 전 채널 이력 | Publish Readiness 보고서 | 없음(순수 판정) | `content_engine/publish_audit.py` | `scripts/audit_publish_candidates.py` | 없음 | 없음(수동 실행) | 없음 | 없음(판정만) | 자동(수동 실행 필요) | 있음 | 가능 |
| PERFORMANCE | 게시 이력 | 성과 지표 스냅샷 + 요약 텍스트 | `content_engine/performance/store.py`가 정의하는 스냅샷 파일 | `content_engine/performance/*.py` | `scripts/collect_performance.py`(`--confirm-live` 필수) | 없음 | 없음(어떤 workflow도 자동 호출 안 함) | Threads/YouTube 조회 API | 필수(`--confirm-live`) | 완전 수동 | 있음(수집/저장/요약) | **부분 가능 — "성과→다음 콘텐츠 전략" 피드백 루프는 없음(13장)** |

## 3. End-to-End 콘텐츠 흐름

하나의 콘텐츠가 SCOUT부터 발행까지 흐른다고 가정했을 때, 실제로 필요한
사람의 개입 지점과 재실행 안전성을 확인했다.

| 단계 | 실행 가능? | 명령 | 필요한 human decision | 실패 기록 위치 | 재실행 시 중복 생성? | 이미 처리된 것 재처리? |
|---|---|---|---|---|---|---|
| SCOUT | 예 | `scripts/run_scout.py`(또는 daily-scout.yml) | 없음 | stderr(source 1건 실패해도 나머지 계속) | 매일 덮어씀(누적 아님) — 재실행이 "중복 생성"은 아니고 "당일 후보 재계산" | INTERVIEW/KNOWLEDGE 단계에서 `source_raw_id` 기준 차단(SCOUT 자체 dedup은 실행 내부만) |
| INTERVIEW | 예 | `scripts/run_interview.py` → `apply_interview.py` | **필수**(4지선다+D 답변) | 없음(사람이 직접 진행) | 같은 candidate 재인터뷰 시 `source_raw_id` 중복 방지가 KNOWLEDGE 생성을 막음 | 예(위와 동일) |
| KNOWLEDGE 승인 | 예 | Dashboard 또는 `scripts/review_knowledge.py` | **필수**(approve/reject) | 없음 | `review_knowledge_file()`이 상태만 바꿈, 중복 안 됨 | 이미 approved/rejected면 재승인 불필요 |
| MEDIA 9개 생성 | 예(6-24 수정 후 안전) | `scripts/run_media_batch.py --execute` | 없음(생성 자체는 AI) | archive의 `generation_status`(rejected/error) | **레거시 경로(`--as-generation` 없이)는 이제 approved/superseded content_id에 대해 거부한다(4장 P0)** | `archive_report()`가 content_id 기준 upsert — 동일 KNOWLEDGE 재실행은 같은 content_id로 수렴 |
| HUMAN REVIEW(MEDIA) | 예 | `/media` 또는 `/media/generations` | **필수**(approve/edit/dismiss) | 없음 | 승인 자체는 idempotent | approved 재승인해도 무해 |
| PROMOTION(generation pool 사용 시) | 예, **CLI 필수** | `scripts/promote_media_generation.py --execute` | 이미 완료된 승인을 재확인만 | `PromotionConflictError` | idempotent(같은 generation 재승격은 무변경) | 6-18이 차단 |
| Publish Readiness | 예 | `scripts/audit_publish_candidates.py` | 없음(판정만) | Markdown 보고서의 ERROR 섹션 | 매 실행 재계산(누적 아님) | 해당 없음 |
| Threads 발행 | 예 | `/threads` 승인 → `scripts/publish_approved_threads.py --execute` | **필수**(승인) | `failed` 상태 + stderr | `PublishHistory.is_published()`가 차단 | 6-19가 supersede/이미발행 모두 차단 |
| Shorts 발행 | 부분(렌더링 코드 없음) | `scripts/generate_approved_shorts_script.py` → (외부 렌더링) → `upload_youtube_short.py --content-id ...` | **필수**(승인) | stderr | `YouTubeUploadHistory.is_published()`가 차단(`--content-id` 지정 시만) | 6-19가 차단(`--content-id` 지정 시만) |
| Blog 발행 | 예(수동) | `scripts/generate_blog_publish_pack.py` → 사람이 Naver에 직접 게시 → `scripts/mark_blog_published.py` | **필수**(승인 + 실제 게시 + 기록) | 없음(사람이 직접 확인) | Pack은 매 실행 재생성(휘발성), 기록은 `mark_blog_published.py`가 idempotent | 이미 발행 기록되면 다음 Pack에서 제외 |

**결론**: 콘텐츠 하나가 SCOUT부터 발행까지 가려면 최소 **4번의 명시적 사람
개입**(INTERVIEW 답변, KNOWLEDGE 승인, MEDIA 승인, 채널별 발행 승인)과
**최소 2번의 터미널 명령**(promotion, 실제 발행 CLI — Dashboard만으로는
끝나지 않는다, 8장)이 필요하다. 이것은 버그가 아니라 "AI가 자동 발행하지
않는다"는 설계 원칙이 실제로 구현된 결과다(15장).

## 4. SCOUT

**현재 상태**: 운영 가능. RSS source(`data/scout_sources.json`, `{name,url,category}`
스키마) → `tak_scout/collector.py`의 `dedupe_candidates()`(URL 정규화 +
제목 정규화, 같은 실행 내 중복만 제거) → `tak_scout/scoring.py`(A~E 5축
rule-based 점수, LLM 미사용) → `data/tak_scout_daily.json/.md`(매일 덮어씀).

**"RSS category와 article_type 혼동" 문제**: 완전히 해결됨. `ScoutCandidate.category`
(RSS 원본 카테고리)와 `tak_brain.article_types.ArticleClassification.article_type`
(제목+본문 규칙 기반 분류)은 서로 다른 단계·다른 dataclass의 별개 필드라
구조적으로 혼동 불가능하다. 과거 실제 사고(Production Archive의
`knowledge-scout-6d1d0e2fa762` category 오표시)는 commit `8b3f816`(6-15)에서
수정됐다(`docs/6-15_data_integrity_and_publish_readiness_report.md` 2장).
**Regression test 존재**: `tests/test_article_types.py`(`ArticleTypePipelineTests`,
11개) + `tests/test_critical_content_replacement_audit.py`(6-15 전수 검증
전용).

**갭**: SCOUT 단계 자체에는 cross-run(날짜를 넘어선) dedup 저장소가 없다 —
`tak_scout_daily.json`은 매일 덮어쓴다. 실질적으로는 KNOWLEDGE 단계의
`source_raw_id` 중복 방지(`tak_brain/knowledge.py`)가 이를 보완해, 같은
원문에서 KNOWLEDGE가 중복 생성되지는 않는다. **P2로 분류**(치명적이지 않음
— 보완 장치가 이미 있음).

**실제 운영 가능 여부**: 가능. 외부 API 의존이 RSS fetch뿐이라 LLM/API
비용도 없다.

## 5. KNOWLEDGE

**현재 상태**: `knowledge_review_status` ∈ {pending, approved, rejected}만
허용(`tak_brain/knowledge.py`의 `set_review_status()`가 강제). 신규 생성은
항상 `pending`(`validate_knowledge()`). `knowledge_id`는 INTERVIEW 답변
기반 결정적 해시(`tak_scout/knowledge_bridge.py`). 중복은 `source_raw_id`
기준으로 방지(`append_knowledge_file()`).

**핵심 확인 사항 — 미승인 KNOWLEDGE 자동 진입 경로**: `select_approved()`가
`review_status == "approved"`만 반환하고, `scripts/run_media_batch.py:96`이
이 함수의 **유일한 실사용처**다(grep으로 확인). **미승인 KNOWLEDGE가
자동으로 production content가 되는 경로는 없다.**

**실제 운영 가능 여부**: 가능. approval gate가 단일 함수(`select_approved`)에
집중되어 있어 감사가 쉽고 우회 경로가 구조적으로 없다.

## 6. MEDIA

**9개 draft 구성**: `content_engine/generator.py`가 1 KNOWLEDGE당 Blog 1 +
Shorts 3 + Threads 5를 하드코딩(profile별 함수). `bundle.validate_counts()`로
개수를 검증.

**⚠️ P0(6-24에서 발견·수정)**: `scripts/run_media_batch.py --execute`를
`--as-generation` 없이(문서화된 기본 동작) 실행하면 `content_engine.media_archive.archive_report()`가
호출되는데, 이 함수는 `review_status`/`edited_*`는 보존하지만
`rewritten_title`/`rewritten_body`/`generation_status`는 **항상 최신 LLM
결과로 덮어쓴다**(`media_archive.py:414-437`, 이 동작 자체는 문서화되어
있었다). 결과적으로 이미 `approved`인 content_id를 같은 KNOWLEDGE로
재실행하면, `review_status`는 "approved"로 남지만 실제 승인받은 문구와
다른 내용이 조용히 그 자리에 들어갈 수 있었다. `scripts/run_daily.py`도
동일한 `archive_report()`를 직접 호출해 같은 위험을 가졌다.

**수정 내용**(17장/19장에서 테스트 결과 확인):
- `content_engine/media_archive.py`에 `find_protected_overwrite_targets(report, existing_records)`
  순수 함수를 추가했다 — `archive_report()`로 덮어쓰였을 때 이미
  `approved`/`superseded`인 content_id 목록을 반환한다.
- `scripts/run_media_batch.py`(비-`--as-generation` 분기)와
  `scripts/run_daily.py`가 `archive_report()` 호출 **직전에** 이 함수를
  호출해, 보호 대상 content_id가 있으면 즉시 중단(exit 1)하고 아무것도
  쓰지 않는다.
- `archive_report()` 자체의 동작(review_status 보존, KNOWLEDGE 정정 후
  재생성 시 새 content_id 허용)은 바꾸지 않았다 — 6-05
  `tests/test_knowledge_correction_media_regeneration.py`가 검증하는
  정당한 재실행 경로는 그대로 동작한다(content_id가 달라지므로 애초에
  보호 대상이 아니다).

**동일 content_id + 다른 generation_id 충돌 보호 범위**: 6-18
`check_promotion_conflict()`는 `promote_media_generation.py`(승격 경로)에만
적용된다. 위 P0 수정으로 `archive_report()` 직접 호출 경로(레거시)도
이제 "이미 approved/superseded인 것"에 한해 보호받는다 — `unreviewed`/
`dismissed` 상태의 동일 content_id 재작성은 기존과 동일하게 허용된다(정상
운영에서 흔한 "아직 검토 전인데 다시 생성" 케이스이므로).

**edited_title/edited_body**: Dashboard `/media/{content_id}/edit`
(`run_scout_dashboard.py`)에서만 입력 가능하며, 저장 시 `review_status`를
강제로 `unreviewed`로 되돌린다(재검토 강제) — 안전하게 구현되어 있었다
(이번에 손대지 않음).

**실제 운영 가능 여부**: 가능(P0 수정 후).

## 7. Human Review

`/media`(레거시, production archive 직접 대상)와 `/media/generations`
(6-06 이후, generation pool 대상) 두 화면이 공존한다.

**핵심 질문 — UI만으로 승인이 완결되는가?**: **아니오, 의도적으로 아니다.**
`/media/generations`에서 검토(edit/approve/dismiss)는 화면으로 가능하지만,
**production 반영(promotion)은 의도적으로 UI에 없다** —
`run_scout_dashboard.py`가 이를 명시적으로 설명한다("promotion 버튼/링크는
여기 없다 - `scripts/promote_media_generation.py`를 사람이 CLI로 직접
실행해야 한다"). supersede(`scripts/supersede_media_record.py`)도 100% CLI
전용이며 Dashboard에 노출된 UI가 없다.

**이것은 버그가 아니라 안전장치다** — Dashboard 승인만으로 즉시 production이
바뀌지 않고, 터미널 명령이라는 두 번째 마찰(friction)을 의도적으로 둔
설계로 읽힌다(주석에 근거 명시). "고쳐야 할 버그"로 분류하지 않았다.

**generation label**: "세대 {generation_id} (활성)" / "레거시 생성" /
"(legacy, generation_id 없음)" 라벨이 화면에 노출된다 — 정보 제공은
충분해 보인다.

**실제 운영 가능 여부**: 가능하지만, 운영자는 "Dashboard 검토 → 터미널
promotion/supersede"라는 2단계가 필요하다는 것을 알아야 한다(21장 runbook에
명시).

## 8. Production Archive

**현재 상태**: `data/tak_media_archive.json`은 여전히 `NOT_PRESENT`(6-20/6-21에서
이미 확인, 이번에도 재확인 — 생성하지 않았다).

**NOT_PRESENT/EMPTY/CORRUPTED/VALID 구분**: 6-21이 만든
`content_engine/data_state.py`(6-22가 공유 모듈로 추출)가 이 네 상태를
파일 시스템 레벨에서 직접 구분하며, `load_archive()`(파일 없음/빈 파일을
전부 빈 목록으로 취급하는 기존 동작)는 손대지 않았다 — 이 이원화(가시성
도구는 4상태 구분, 내부 로직은 단순화된 2분법)가 의도된 설계임을 6-21/6-22
문서가 이미 설명한다.

**source of truth로 쓰는 코드 전체**: `load()`(`media_archive.load_archive`),
`parse()`(`MediaArchiveRecord.from_dict`, 6-06/6-17이 필드별 검증),
`validation`(6-22 `validate_production_archive`가 A~M 오류 체계로 심층
검증), `promotion`(6-06/6-09/6-18), `conflict`(6-18
`check_promotion_conflict`), `superseded`(6-17), `publish eligibility`
(6-19 `publish_eligibility.py`), `downstream`(6-19 downstream safeguards) —
전부 6-19~6-23에서 이미 상세히 감사했고 이번에 재확인만 했다(코드 변경
없음, 4장의 P0만 예외).

**실제 운영 가능 여부**: 가능(파일이 없다는 사실 자체는 "운영 시작 전
정상 상태").

## 9. Publish Readiness

`content_engine/publish_audit.py`의 상태 우선순위(코드 순서 그대로):
1. `ERROR`(duplicate content_id — 구조적 이상)
2. `ALREADY_PUBLISHED`(각 채널 실제 게시 이력 — 승인/보류 상태와 무관하게 최우선)
3. `SUPERSEDED`(6-17, 이미 게시된 적 없을 때만)
4. `BLOCKED`(미승인/미검증/필수 필드 누락/Shorts Script 미생성 등, 여러 사유 동시 표시)
5. `NEEDS_HUMAN_REVIEW`(승인+검증 통과했지만 민감 콘텐츠)
6. `READY`

**플랫폼별 실제 발행 조건**(코드에서 확인):
- **Threads**: `review_status=="approved"` + `check_content_supersede()` 통과(발행 직전 재확인) + `PublishHistory.is_published()`가 False
- **Shorts**: 위와 동일 + `shorts_script_output_path()` 파일 존재 + `YouTubeUploadHistory.is_published()`가 False
- **Blog**: `select_approved_blog_candidates_from_archive()`가 `review_status=="approved"`만 통과 + `blog_publish_log.json`에 없음

approved/valid/not superseded/required fields/publish history가 전부
반영되는지 6-19~6-23에서 이미 21개 테스트로 검증됐고, 이번에 코드를 다시
읽어 재확인했다(변경 없음).

## 10. Threads

- **정식 경로**(`scripts/publish_approved_threads.py`, 5-11): `tak_threads_pending.json`에서
  `status=="approved"`만 대상, 발행 직전 production archive를 다시 읽어
  `check_content_supersede()`(6-19)로 차단, `ALREADY_PUBLISHED`가
  `SUPERSEDED`보다 우선(정책 일치). 기본 dry-run, `--execute` 필수.
- **⚠️ 레거시 경로**(`scripts/publish_threads.py --auto`,
  `scripts/run_daily.py`가 호출): **`review_status`/승인 게이트가 전혀
  없다** — `item.get("status")=="valid"`(생성 검증 통과 여부일 뿐, 사람의
  승인과 무관)와 발행 이력 미존재만 확인한다(`publish_threads.py:41-45`,
  `load_valid_threads_items`).
- 이 레거시 경로를 실행하는 `.github/workflows/daily-threads-post.yml`의
  **schedule(cron)은 2026-09-18(5-19)에 이미 비활성화**됐다 — workflow
  파일 자체의 주석이 정확한 이유를 남기고 있다("두 경로가 동시에 실제
  Threads에 게시할 수 있어 운영 원칙과 충돌"). `workflow_dispatch`의
  `dry_run` 기본값도 `true`로 안전하게 설정되어 있다.
  **다만 사람이 `workflow_dispatch`에서 `dry_run=false`로 수동 실행하거나
  로컬에서 `THREADS_ACCESS_TOKEN`을 가지고 직접 실행하면, 승인/supersede
  검사를 모두 우회하는 실제 게시가 여전히 가능하다 — P1(잔존 리스크, 새
  버그는 아니지만 해소되지 않았다).**
- 다른 확인 사항(중복 publish, stale pending, publish log 불일치)은 정식
  경로 한정으로 전부 방지됨을 확인.

## 11. Shorts

- `ShortsScript(JSON)` → **렌더링(mp4 생성) 코드가 이 저장소에 없다**(6-21
  결론 재확인, grep 결과 없음 — 외부 산출물을 가정) → `upload_youtube_short.py`.
- `--content-id`를 지정했을 때만 `YouTubeUploadHistory.is_published()`(중복
  방지)와 `check_content_supersede()`(6-19)가 적용된다. **`--content-id`를
  생략(레거시 호출)하면 두 안전장치 모두 건너뛴다** — 의도된 하위호환이지만
  사람이 습관적으로 생략하면 보호가 사라진다(P2, 문서화 필요).
- **`scripts/youtube_oauth_setup.py`가 존재하지 않는다** — `upload_youtube_short.py`
  자체 docstring과 여러 docs(5-18, 5-31, 6-01~6-03)가 이 스크립트를
  언급하지만 git history에 커밋된 적이 없다. 최초 `YOUTUBE_REFRESH_TOKEN`
  발급 경로가 **문서에만 있고 구현이 없다** — 실제 Shorts 업로드 운영
  시작의 진짜 blocker(P1).
- 어떤 GitHub workflow도 YouTube 관련 secrets를 참조하지 않는다 — 업로드는
  100% 로컬/수동이 전제.

## 12. Blog

- `generate_blog_publish_pack.py`: 승인된(`review_status=="approved"`)
  MEDIA만 Markdown Pack으로 생성(`content_engine/blog_publish_pack.py:253`).
- Naver 자동 게시는 **의도적으로 구현되어 있지 않다**(docstring에 원칙
  명시) — 사람이 Pack을 보고 직접 Naver에 copy/paste한다.
- `mark_blog_published.py`(6-20에서 새로 구현)로 게시 완료를 수동
  기록해야 다음 Pack 생성에서 해당 content_id가 제외된다 — idempotent(중복
  기록 방지 확인됨).
- **워크플로우 자체는 명확하고 운영 가능**하다. 단, `data/blog_publish_log.json`이
  다른 채널 이력과 달리 `.gitignore` 화이트리스트에 없어(6-21에서 이미
  발견) 멀티 PC 간 "이미 게시됨" 상태가 동기화되지 않는다 — P1(재확인,
  미해결 상태 유지).

## 13. Performance Loop

**"게시 → 성과 → 분석 → 다음 콘텐츠" 루프는 없다.** 명확히 그렇다고
기록한다(6-24 지시사항 원칙 준수 — 있는 것처럼 부풀리지 않는다).

`content_engine/performance/`(blog.py, migration.py, models.py, store.py,
summary.py, threads.py, youtube.py)와 `scripts/collect_performance.py`는
다음만 구현한다:
- **수집**: Threads/YouTube 조회 API로 지표를 가져온다(`--confirm-live` 필수,
  어떤 workflow도 자동 호출하지 않음 — 100% 수동).
- **저장**: 스냅샷을 append/load하는 저장소.
- **요약**: 트렌드를 사람이 읽는 텍스트로 렌더링.

SCOUT scoring이나 KNOWLEDGE 우선순위에 performance 데이터를 피드백하는
코드는 어디에도 없다. **가짜 performance 시스템을 이번에 만들지 않았다**
(지시사항 준수) — 24장에 향후 작업 후보로만 남긴다.

## 14. Human vs AI 책임

| 분류 | 항목 | 확인 결과 |
|---|---|---|
| AI 자동 가능 | research(SCOUT 수집/scoring) | 자동, 위반 없음 |
| AI 자동 가능 | draft(MEDIA rewrite) | 자동, 위반 없음(5장 P0 수정 후 승인된 결과는 더 이상 조용히 안 바뀜) |
| AI 자동 가능 | classification(article_type) | 자동, 위반 없음 |
| AI 자동 가능 | validation(rewrite validator, archive schema) | 자동, 위반 없음 |
| AI 자동 가능 | report(publish readiness, recovery reconciliation) | 자동, 위반 없음(전부 read-only 판정) |
| Human required | KNOWLEDGE approval | `select_approved()` 단일 게이트, 위반 없음 |
| Human required | media approval | `/media`, `/media/generations`, 위반 없음(6장 P0는 "승인 후 재실행"의 갭이었지 "승인 자체를 우회"는 아니었다 — 이제 수정됨) |
| Human required | publish | **정식 경로는 위반 없음. 레거시 경로(`run_daily.py`/`publish_threads.py --auto`)는 구조적으로 승인 게이트가 없다 — cron은 막혀 있지만 코드 자체는 여전히 이 원칙을 위반할 수 있는 상태(10장 P1)** |
| Human required | sensitive content review | `is_review_required()`, 위반 없음 |
| Human required | recovery approval | 6-23의 Apply Guard, 위반 없음(approve 없이는 `READY_FOR_EXPLICIT_APPLY`조차 안 됨) |

**결론**: 이 원칙을 위반하는 자동 경로가 실제로 하나 존재했다(6장 P0,
이번에 수정) — 나머지 하나(10장, Threads 레거시 경로)는 "존재하지만
수동 개입 없이는 실행 안 됨"으로 이미 봉인되어 있어 즉시 위반은 아니지만
완전히 닫혀 있지도 않다.

## 15. Security

값은 읽지 않고 이름/구조만 확인했다.

- **환경변수 인벤토리**: `THREADS_ACCESS_TOKEN`, `THREADS_API_BASE`,
  `TAK_MEDIA_LLM_API_KEY/ENDPOINT/MODEL`, `YOUTUBE_CLIENT_ID/SECRET/REFRESH_TOKEN`.
- **GitHub Actions secrets**: `THREADS_ACCESS_TOKEN`,
  `TAK_MEDIA_LLM_API_KEY/ENDPOINT/MODEL` 4개뿐(YouTube는 CI에서 미사용 —
  11장과 일치, 업로드가 전적으로 로컬 수동이기 때문).
- **⚠️ P1(이번에 수정)**: `.env`가 `.gitignore`에 없었다(`git check-ignore .env`
  확인 결과 exit 1). 현재 `.env` 파일 자체는 저장소에 없어 즉시 유출은
  아니지만, 로컬에서 만들면 실수로 커밋될 위험이 있는 latent gap이었다.
  `.gitignore`에 `.env`/`.env.*`(예외: `.env.example`)를 추가했다(17장).
- 클라이언트 코드(`threads_publisher.py`, `youtube_publisher.py`,
  `llm_provider.py`) 어디에도 토큰/키를 `print`하거나 파일에 저장하는
  코드가 없다 — 양호.
- OAuth token은 파일로 저장하지 않고 env로만 전달 — 양호(단, 11장의
  `youtube_oauth_setup.py` 부재로 최초 발급 과정 자체가 미구현).

## 16. Multi-PC 운영

6-21에서 이미 상세히 감사했다(`docs/6-21-data-sync-and-recovery-architecture.md`).
이번에는 재확인만 했고 새로 바뀐 것은 없다:

- **pull/push 대상**: `tak_brain_knowledge.json`, `tak_threads_pending.json`,
  `scout_sources.json`, `tak_scout_daily.json/.md`, `threads_publish_log.json`,
  `youtube_publish_log.json`, `tak_media_batch_e2e_test.json`,
  `shorts_scripts/*.json` — 전부 tracked, 정상 동기화 대상.
- **수동 관리 대상**: `tak_media_archive.json`(화이트리스트는 있으나 아직
  한 번도 커밋된 적 없음, 6-20/6-21에서 이미 발견, 여전히 미해결 —
  P1, 사람의 결정 필요), `tak_media_generation_*.json`(의도적으로
  git 미추적), `blog_publish_log.json`(**화이트리스트 누락, P1, 6-21
  재확인**).
- Recovery Staging/Review/Approval(6-22/6-23)이 이 수동 관리 대상을 다른
  PC에서 안전하게 가져오는 경로를 이미 제공한다(`scripts/audit_recovery_source.py`,
  `scripts/recover_media_archive.py`) — 이번에 코드를 다시 읽어 6-19~6-23
  문서가 주장하는 내용과 실제 구현이 정확히 일치함을 확인했다(18장).

## 17. P0 문제

| 문제 | 근거 파일 | 현재 상태 | 실제 영향 | 해결 방법 | 예상 작업량 |
|---|---|---|---|---|---|
| `archive_report()` 레거시 경로가 이미 approved/superseded인 content_id를 재실행 시 조용히 재작성 | `content_engine/media_archive.py:414-437`(원인), `scripts/run_media_batch.py`(비-`--as-generation`), `scripts/run_daily.py` | **이번 세션에서 수정 완료** | 사람이 승인한 문구가 재실행만으로 사람 모르게 바뀔 수 있었음 | `find_protected_overwrite_targets()` 신규 함수 + 두 CLI에 쓰기 전 가드 추가 | 완료(수정 + 신규 테스트 11개 + 전체 회귀 통과, 19장) |

이번 감사에서 발견한 유일한 P0였다. 다른 후보(10장 Threads 레거시 경로)는
"이미 cron이 비활성화되어 즉시 실행되지 않는다"는 이유로 P1로 분류했다
(운영 시작을 막지는 않지만 방치하면 안 됨).

## 18. P1 문제

| 문제 | 근거 파일 | 현재 상태 | 실제 영향 | 해결 방법 | 예상 작업량 |
|---|---|---|---|---|---|
| `.env`가 `.gitignore`에 없음 | `.gitignore`(수정 전) | **이번 세션에서 수정 완료** | 로컬 `.env`를 실수로 커밋할 위험 | `.gitignore`에 `.env`/`.env.*` 추가 | 완료 |
| Threads 레거시 자동 발행 경로(승인 게이트 없음)가 여전히 코드에 존재 | `scripts/publish_threads.py:41-45`, `scripts/run_daily.py`, `.github/workflows/daily-threads-post.yml` | cron 비활성화(5-19)로 봉인, 코드는 그대로 | `workflow_dispatch`(dry_run=false) 수동 실행 또는 로컬 실행 시 승인 우회 발행 가능 | 이 workflow/스크립트를 완전히 retire하거나, `publish_threads.py --auto`에 production archive의 `review_status=="approved"` 확인을 추가 | 반나절(신중한 테스트 필요 — 실제 발행 코드라 이번 세션에서 서두르지 않았다) |
| `scripts/youtube_oauth_setup.py`가 문서에만 있고 구현 없음 | `scripts/upload_youtube_short.py` docstring, docs 5-18/5-31/6-01~6-03 | 미구현 | 최초 YouTube OAuth 설정을 사람이 수작업으로 해결해야 함(문서화된 안내가 실제 도구로 이어지지 않음) | OAuth 최초 인증 흐름을 안내하는 CLI 신규 작성 | 반나절~한나절 |
| `blog_publish_log.json`이 `.gitignore` 화이트리스트 누락 | `.gitignore`, 6-21 3장 재확인 | 미해결(6-21에서 이미 발견) | Blog "이미 게시됨" 상태가 PC/CI 간 동기화 안 됨 | 화이트리스트에 추가할지 정책 결정(사람의 판단 필요 — 6-21이 이미 "바로 바꾸지 마라"고 판단) | 결정 후 1줄 |
| Production Archive가 어느 브랜치에도 커밋된 적 없음 | 6-20/6-21에서 이미 발견, 이번에 재확인(git log 결과 0건) | 미해결(사람의 결정 대기) | 첫 실제 운영 시작 시 CI(`daily-media-prepare.yml`)가 승인 상태를 못 봄 | 사람이 "언제 처음 커밋할지" 결정(6-21 16장에 이미 설계됨) | 결정 필요, 코드 작업 없음 |

## 19. P2 문제

| 문제 | 근거 파일 | 현재 상태 | 실제 영향 | 해결 방법 | 예상 작업량 |
|---|---|---|---|---|---|
| `upload_youtube_short.py`를 `--content-id` 없이 호출하면 중복 업로드/supersede 방지 우회 | `scripts/upload_youtube_short.py` | 의도된 하위호환 | 습관적 생략 시 보호 상실 | runbook에 `--content-id` 필수 사용 명시(21장에 반영) | 문서화만 |
| SCOUT에 명시적 cross-run dedup 저장소 없음 | `tak_scout/collector.py` | KNOWLEDGE 단계가 보완 | 낮음(현재 문제 없음) | 필요해지면 SCOUT 레벨 dedup 추가 | 미정(지금 안 함) |
| Dashboard에 superseded 전용 UI 배지 없어 보임 | `run_scout_dashboard.py`(포크 조사, 시간 제약으로 HTML 렌더링 전체 미확인) | 불확실 | 운영자가 CLI로만 확인 가능할 수 있음 | 실제 화면 확인 후 필요시 배지 추가 | 미정 |
| Recovery Staging의 SHA256 drift 가드가 "저장된 REPORT를 나중에 승인" 워크플로우 미지원 | `content_engine/recovery_apply.py`, 6-23 15장 | 이미 문서화된 남은 위험 | 같은 세션 안에서만 REPORT→승인이 안전 | 저장된 REPORT 재로드 기능 추가 | 6-23에서 이미 향후 작업으로 기록 |

## 20. P3 / 지금 만들지 않을 것

- Performance → 다음 콘텐츠 전략 자동 피드백 루프(13장에서 "없다"고 명시,
  가짜로 만들지 않음).
- 외부 DB(Supabase 등) 도입 — 이번 지시사항이 금지, 향후에도 신중히
  검토(6-21 10장이 이미 "이번에 도입하지 않는다"로 결론).
- 서로 다른 Production Archive 자동 병합 도구(6-21 5장 시나리오 C) —
  실제로 발생한 적 없어 추측성 구현 위험(6-21/6-22가 이미 이렇게 결정).
- 여러 generation pool 파일 자동 정리 도구(6-23 15장) — 같은 이유로
  보류.
- Dashboard 대규모 개편 — 이번 감사에서 발견한 것은 "누락된 기능"이
  아니라 "의도된 CLI 전용 안전장치"였으므로 UI를 새로 만들 근거가 없다
  (7장).

## 21. 실제 운영 시작 절차

**주의**: 아래는 실제 운영 데이터가 있는 환경(노트북1 또는 향후 복구된
노트북2)에서 실행할 절차다. 현재 노트북2(Production Archive `NOT_PRESENT`)
에서는 실행하지 않았다 — "현재 환경에서 검증 불가"이며, 억지로 만들지
않았다.

```
1.  git fetch origin main && git status          # 최신 상태 확인(6-19 SYNC CHECK 패턴)
2.  python -m unittest discover -s tests -p "test_*.py"   # 환경 확인
3.  python scripts/run_scout.py                  # 또는 daily-scout.yml 대기
4.  python scripts/run_interview.py              # SCOUT candidate에 답변
5.  python scripts/apply_interview.py            # KNOWLEDGE(pending) 생성
6.  (Dashboard 또는) python scripts/review_knowledge.py --approve <id>
7.  python scripts/run_media_batch.py --execute --as-generation \
        --archive <generation-pool-path>          # MEDIA 9개 생성(generation pool)
8.  (Dashboard /media/generations) 승인/보류/수정
9.  python scripts/promote_media_generation.py --archive <pool> \
        --production-archive data/tak_media_archive.json \
        --content-id <id> --generation-id <gid> --execute
10. python scripts/audit_publish_candidates.py    # Publish Readiness 확인
11a. (Threads) Dashboard /threads 승인 →
     python scripts/publish_approved_threads.py --execute
11b. (Shorts) python scripts/generate_approved_shorts_script.py →
     (외부 렌더링) → python scripts/upload_youtube_short.py --content-id <id>
11c. (Blog) python scripts/generate_blog_publish_pack.py →
     사람이 Naver에 직접 게시 →
     python scripts/mark_blog_published.py --content-id <id>
12. python scripts/audit_publish_candidates.py    # 발행 후 재확인
13. python scripts/collect_performance.py --confirm-live   # 필요시 수동 수집
14. git status && git add data/tak_media_archive.json ... && git commit && git push
```

7번에서 `--as-generation` 없이 실행하면 6장 P0 수정에 따라, 이미
approved/superseded인 content_id가 있으면 **의도적으로 거부**된다 — 이는
버그가 아니라 이번에 추가한 안전장치다.

## 22. 10월 1일 이후 우선 작업

우선순위는 P0/P1/P2/P3로만 분류한다("최고/최악" 등 평가 표현 없음).

1. **[P1] Threads 레거시 자동 발행 경로 완전 정리**
   - 목적: `run_daily.py`/`publish_threads.py --auto`의 승인 우회 가능성을
     구조적으로 제거.
   - 선행조건: 없음(6-24가 이미 원인 파악 완료).
   - 예상 산출물: workflow 삭제 또는 스크립트에 승인 게이트 추가 + 회귀 테스트.
   - 운영 데이터 영향: 없음(코드/workflow만).
   - 예상 난이도: 중(실제 발행 코드라 신중한 테스트 필요).

2. **[P1] `scripts/youtube_oauth_setup.py` 구현**
   - 목적: 문서에만 있는 최초 OAuth 발급 절차를 실제 도구로 제공.
   - 선행조건: YouTube Data API 프로젝트/클라이언트 ID 발급(사람이 콘솔에서).
   - 예상 산출물: 신규 CLI 1개 + 사용법 문서.
   - 운영 데이터 영향: 없음.
   - 예상 난이도: 중.

3. **[P1] Production Archive 최초 커밋 정책 결정 및 실행**
   - 목적: 6-21 11/16장이 이미 설계한 정책을 실제로 적용.
   - 선행조건: 사람의 결정(언제, 어느 PC에서).
   - 예상 산출물: 첫 `data/tak_media_archive.json` 커밋(또는 정책 문서 갱신).
   - 운영 데이터 영향: **있음**(이 작업 자체가 운영 데이터 생성) — 이번
     6-24에서는 하지 않음.
   - 예상 난이도: 낮음(코드), 결정은 사람 몫.

4. **[P1] `blog_publish_log.json` 화이트리스트 정책 결정**
   - 목적: 6-21이 발견한 정책 불일치 해소.
   - 선행조건: 3번과 함께 검토하면 효율적(둘 다 "언제 커밋을 시작할지" 결정).
   - 예상 산출물: `.gitignore` 1줄 + 정책 문서 갱신.
   - 운영 데이터 영향: 결정에 따라 있음.
   - 예상 난이도: 낮음.

5. **[P2] Shorts mp4 렌더링 파이프라인 소재 확인**
   - 목적: "이 저장소가 렌더링하지 않는다"가 맞는지, 다른 저장소/수작업인지 확정.
   - 선행조건: 없음.
   - 예상 산출물: 조사 결과 문서 1개.
   - 운영 데이터 영향: 없음.
   - 예상 난이도: 낮음(순수 조사).

6. **[P2] `upload_youtube_short.py --content-id` 누락 시 경고 추가**
   - 목적: 습관적 생략으로 보호가 조용히 사라지는 것을 방지.
   - 선행조건: 없음.
   - 예상 산출물: stderr 경고 문구(하위호환 유지, 차단은 하지 않음).
   - 운영 데이터 영향: 없음.
   - 예상 난이도: 낮음.

7. **[P2] Recovery Staging에 "저장된 REPORT 재승인" 기능 추가**
   - 목적: 6-23이 이미 기록한 남은 위험 해소.
   - 선행조건: 실제 recovery 시나리오가 한 번이라도 발생한 뒤가 이상적
     (추측성 구현 회피).
   - 예상 산출물: `scripts/recover_media_archive.py`에 `--report-file` 옵션.
   - 운영 데이터 영향: 없음(read-only 확장).
   - 예상 난이도: 중.

8. **[P2] Dashboard의 superseded 상태 가시성 확인/개선**
   - 목적: 19장에서 불확실하다고 남긴 부분을 확정.
   - 선행조건: 실제 브라우저로 `/media`, `/media/generations` 렌더링 확인.
   - 예상 산출물: 조사 결과 + 필요시 최소 UI 추가.
   - 운영 데이터 영향: 없음.
   - 예상 난이도: 낮음~중.

9. **[P3, 실제 필요해지면] Performance → 콘텐츠 전략 피드백 루프 설계**
   - 목적: 13장에서 "없다"고 확인한 gap을 실제로 메울지 결정.
   - 선행조건: 실제 게시 이력이 충분히 쌓인 뒤(현재는 검증할 데이터 자체가 없음).
   - 예상 산출물: 설계 문서 우선, 구현은 그 다음.
   - 운영 데이터 영향: 없음(설계 단계).
   - 예상 난이도: 높음(새 개념 설계).

10. **[P3, 실제 필요해지면] SCOUT 레벨 cross-run dedup 저장소**
    - 목적: 4장의 갭을 명시적으로 메울지 결정.
    - 선행조건: KNOWLEDGE 단계 보완만으로 실제 문제가 생기는 사례 관찰.
    - 예상 산출물: 설계 문서.
    - 운영 데이터 영향: 없음.
    - 예상 난이도: 낮음~중.
