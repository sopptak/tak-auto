# [MEDIA HUMAN EDIT + DOWNSTREAM 구현 완료]

목표: MEDIA Dashboard → AI 결과 확인 → 사람이 직접 수정 → 수정 내용 저장 →
승인 → 채널별 다음 단계로 이동. 이번 단계는 "사람 수정 + 승인 상태 관리 +
Blog/Shorts downstream 연결"까지만 구현했다. 실제 외부 발행은 전혀 실행하지
않았다.

## 1. 변경 파일
- `content_engine/media_archive.py` — `edited_title`/`edited_body` 필드,
  `final_title`/`final_body` 프로퍼티 추가. `archive_report()`가 재실행 시
  `review_status`뿐 아니라 사람이 남긴 수정 내용도 보존하도록 변경.
- `scripts/run_scout_dashboard.py` — `/media/<content_id>` 상세 화면에
  수정 폼(제목 input + 본문 textarea) + `[저장]`/`[승인]`/`[보류]` 버튼 추가,
  `POST /media/<id>/edit`·`POST /media/<id>/dismiss` 라우트 신규, Threads
  approve 시 `final_title`/`final_body` 사용하도록 수정.
- `scripts/generate_blog_publish_pack.py` — `--from-archive` 플래그 추가
  (기본 동작은 무수정).

## 2. 신규 파일
없음(모두 기존 파일 확장). `content_engine/blog_publish_pack.py`는 이전
세션부터 있던 미커밋 파일이었으나, 이번 작업에서 새 함수
(`select_approved_blog_candidates_from_archive`,
`build_blog_publish_pack_from_archive`)를 추가하며 처음 커밋에 포함했다.

## 3. 수정 기능
- `/media/<content_id>`에서 `generation_status == "valid"`이고 아직
  `review_status != "approved"`인 동안 제목 `<input>`/본문 `<textarea>` 폼이
  항상 보임(기본값: `edited_*`가 있으면 그 값, 없으면 `rewritten_*`).
- `[저장]` → `edited_title`/`edited_body`만 갱신, `original_*`/`rewritten_*`는
  절대 건드리지 않음. 저장 후 `review_status`는 항상 `"unreviewed"`로 되돌아감
  (수정만으로는 승인되지 않음, 사람이 다시 `[승인]`을 눌러야 함).
- REJECTED/ERROR, 이미 approved인 콘텐츠는 수정 폼/버튼 자체가 렌더링되지
  않고, 서버 측에서도 POST를 거부함(400) — UI 우회를 막는 이중 방어.

## 4. dismissed 기능
- `[보류]` 버튼(VALID + 미승인일 때만) → `review_status = "dismissed"`,
  데이터 삭제 없음.
- dismissed 상태에서도 `unreviewed`와 동일하게 수정 폼 + `[승인]`/`[보류]`
  버튼이 다시 보임 → "다시 검토 가능" 요구사항 충족.
- 이미 approved인 콘텐츠는 보류할 수 없음(서버 측 400 거부).

## 5. 승인 로직
- `[승인]`은 여전히 `generation_status == "valid"`이고 `review_status !=
  "approved"`일 때만 가능(REJECTED/ERROR 불가, 재승인 idempotent).
- Threads pending draft 생성 시 `ai_rewritten_title`/`ai_rewritten_body`에
  `record.final_title`/`final_body`를 사용하도록 변경 — 사람이 수정했다면
  그 수정본이, 안 했다면 AI 생성본이 그대로 pending queue로 들어감.

## 6. 최종 콘텐츠 선택 규칙
`MediaArchiveRecord.final_title`/`final_body` 프로퍼티로 한 곳에 고정:

```
edited_title/edited_body가 있으면 그 값
없으면 rewritten_title/rewritten_body(AI 생성본)
그것도 없으면 original_title/original_body
```

Threads pending 생성, Blog Publishing Pack 후보 변환, Shorts→ShortsScript
변환 세 곳 모두 이 프로퍼티 하나만 사용하므로 규칙이 한 곳에서만 정의된다.

## 7. Blog 연결
- `content_engine/blog_publish_pack.py`에 `select_approved_blog_candidates_
  from_archive()` + `build_blog_publish_pack_from_archive()` 추가(순수 함수,
  기존 `build_blog_publish_pack()`/`select_blog_publish_candidates()`는
  무수정).
- 조건: `platform == "blog"`, `generation_status == "valid"`,
  `review_status == "approved"`, 아직 `PublishHistory`에 없는 것만.
- 기존 선정 규칙(서로 다른 KNOWLEDGE 우선, `max_count`, 금융 review_required
  판정) 그대로 재사용 — 테스트로 재확인.
- `scripts/generate_blog_publish_pack.py --from-archive`로 실제 CLI에서
  연결(LLM 미호출, `--output`/`archive_report` 미실행). 기존 기본 동작(LLM
  실행 경로)은 완전히 그대로 유지.
- **Naver 게시는 절대 실행하지 않음** — 이 경로도 Markdown Pack 생성까지만.

## 8. Shorts 연결
- `content_engine/shorts_adapter.py`에
  `approved_media_archive_record_to_shorts_script()` 추가.
- 조건 불만족(`platform != "shorts"` / `generation_status != "valid"` /
  `review_status != "approved"`) 시 `ShortsAdapterError`.
- `record.final_title`/`final_body`로 `ShortDraft`를 만든 뒤 기존
  `short_draft_to_shorts_script()`를 그대로 호출 — 새 변환 로직 없음.
- **MP4 렌더링은 절대 실행하지 않음** — `content_engine.shorts_renderer`는
  이 함수에서 import조차 하지 않음. ShortsScript 객체 반환까지만.

## 9. Threads 연결
기존 구조(MEDIA 승인 → `threads_review.upsert_pending()` → pending) 무수정.
이번 변경은 그 안에서 넘기는 값만 `rewritten_*` → `final_*`로 바꿨다 — 사람이
수정한 최종 콘텐츠가 실제로 pending queue에 들어가는지 테스트로 확인(H, I, P).
이미 존재하는 pending/approved/published/failed draft는 여전히 덮어쓰지 않음
(재확인 테스트 통과).

## 10. 중복 방지
- 아카이브 자체: 같은 content_id 재승인/재수정은 upsert(교체)일 뿐 레코드
  수가 늘지 않음(테스트).
- Blog: 같은 승인 항목으로 Pack을 여러 번 생성해도 후보 1건만 나오고(순수
  함수라 상태 누적 없음), 실제 게시(`PublishHistory` 기록) 후에는 후보에서
  자동 제외됨(테스트).
- Threads: 기존 `upsert_pending()`의 "이미 있으면 덮어쓰지 않음" 가드를
  그대로 재사용, 신규 저장 구조를 만들지 않음.

## 11. 테스트 결과
A~R 요구 항목 전부 작성·통과:
- A~G, 편집 전용 흐름(`tests/test_media_dashboard.py::MediaEditAndDismissHttpTests`)
- H, I, P: 수정/미수정 각각 Threads pending queue에 반영되는지
- J, K: VALID만 승인 가능 / REJECTED·ERROR 불가(기존 5-28 테스트 + 신규 보강)
- L, M: dismissed 저장 + 재검토 가능
- N, Q(Blog): `tests/test_blog_publish_pack.py::BlogPublishPackFromArchiveTests`,
  `GenerateBlogPublishPackFromArchiveCliTests`
- O(Shorts): `tests/test_shorts_adapter.py::ApprovedMediaArchiveRecordConversionTests`
- R: 외부 API import 정적 검사 + 승인/수정/보류 전체 흐름 실행 성공으로
  기능적 재확인

## 12. 전체 pytest 결과
**669 passed, 68 subtests passed** (실패 0)

## 13. 실제 LLM 호출 여부
**없음.** `--from-archive` 모드는 `OpenAICompatibleRewriteProvider.from_environment`
를 아예 호출하지 않음(테스트로 `mocked_from_env.assert_not_called()` 확인).
MEDIA Dashboard의 수정/승인/보류 코드 경로도 LLM을 호출하지 않음.

## 14. 실제 Threads 발행 여부
**없음.** `ThreadsClient`/`threads_publisher` import가 이번에 수정한 파일
어디에도 없음(정적 검사). 승인은 여전히 `tak_threads_pending.json`의
`status="pending"`으로 이동시키는 것까지만.

## 15. 실제 YouTube 업로드 여부
**없음.** `YouTubeClient`/`youtube_publisher` import 없음. Shorts는
`ShortsScript` 반환까지만 하고 `content_engine.shorts_renderer`(MP4 렌더링)나
YouTube 업로드 스크립트는 전혀 호출하지 않음.

## 16. 실제 Naver 게시 여부
**없음.** `--from-archive` 포함 이 스크립트의 어떤 경로도 네이버에 로그인·게시
API를 호출하지 않음 — 지금까지와 동일하게 Markdown Pack을 파일로 저장하는
것까지만 하고, 실제 게시는 여전히 사람이 `scripts/mark_blog_published.py`로
수동 기록해야 하는 별도 단계.

## 17. commit
`0e6778d` — "feat: add human edit + dismiss on MEDIA Dashboard, wire Blog/Shorts downstream"

## 18. push
`origin/main`에 반영 완료 (`9329770..0e6778d`)

## 19. 남은 작업
- Shorts: `ShortsScript` 생성까지만 연결됨 — 실제 파일로 저장(예:
  `data/shorts_scripts/<content_id>.json`)하거나 렌더링 트리거하는 CLI는
  아직 없음.
- Blog: `--from-archive`로 Pack까지는 만들어지지만, 매일 자동 실행되는
  파이프라인(`run_daily.py` 등)에는 아직 연결되지 않음 — 사람이 수동으로
  실행해야 함.
- Dashboard에 Blog/Shorts 승인 후 "다음엔 무엇을 실행해야 하는지" 안내
  문구가 없음(예: "이 Blog 콘텐츠는 `generate_blog_publish_pack.py
  --from-archive`로 Pack을 만들 수 있습니다" 같은 안내).
- `content_engine/__init__.py`, `generator.py`, `llm_provider.py`,
  `rewrite.py`, `data/tak_brain_knowledge.json`, `tests/test_content_engine.py`,
  `tests/test_media_batch.py`, `content_engine/shorts_renderer.py`는 여전히
  이전 세션의 미커밋 상태 그대로 — 이번에도 손대지 않고 남겨둠.
