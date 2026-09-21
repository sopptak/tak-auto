# 6-16 — CRITICAL 콘텐츠 정정 절차 사전 검증 + SCOUT Category 개선 설계

## 1. 작업 목적

6-15가 CRITICAL로 남긴 문제 — 승인된(approved) Production Archive 레코드
`content-5971ed5204437cdd`(blog, finance 템플릿 오염)를 어떻게 안전하게
정정할지 — 를 실제로 실행하기 전에, **현재 코드/데이터 구조가 그 정정을
안전하게 지원하는지**를 검증하는 것이 이번 세션의 유일한 목적이다.

절대 원칙(작업 지시 0장)에 따라 이번 세션에서는 다음을 전혀 하지 않았다:

- 외부 플랫폼(Naver/Threads/YouTube) 게시
- LLM 호출
- Production Archive(`data/tak_media_archive.json`) 실제 변경
- `data/tak_brain_knowledge.json`(KNOWLEDGE) 실제 변경
- 승인 상태(review_status) 실제 변경
- 실제 콘텐츠 교체 실행

모든 "교체 시뮬레이션"은 `tempfile.TemporaryDirectory()`/`tempfile.NamedTemporaryFile()`
로 만든 임시 파일에서만 수행했고, 실제 파일은 처음부터 끝까지 읽기만 했다(12장에서
SHA256으로 재확인).

## 2. 시작 상태

```
$ git branch --show-current
main
$ git rev-parse HEAD
8b3f816d2ce0c6b83b5e9ef90aeff22640f3b582
$ git fetch origin   # (출력 없음)
$ git log --oneline -5
8b3f816 fix: repair category/article_type integrity and Threads publish consistency (6-15)
fc13577 docs: record final commit/push confirmation in 6-14 report
4459a67 feat: add publish readiness audit + close blog pack review-gate bypass (6-14)
2e0c283 docs: record final commit/push confirmation in 6-13 report
745d67c feat: add YouTube dedup + publish status visibility, fix stale 6-06/6-07 snapshots (6-13)
$ git log origin/main..HEAD    # (비어 있음)
$ git log HEAD..origin/main    # (비어 있음)
```

`git status --short`: 이전 세션들이 남긴 기존 미커밋 변경 목록(`.gitignore`,
`content_engine/__init__.py`, `content_engine/generator.py`,
`content_engine/llm_provider.py`, `content_engine/rewrite.py`,
`tests/test_content_engine.py`, `tests/test_media_batch.py`)과 다수의 기존
untracked 문서/스크립트만 있었다 — 이번 세션에서 전혀 손대지 않았다.

Baseline 전체 테스트:

```
998 passed, 68 subtests passed in 170.63s (0:02:50), 0 failed
```

지시서 예상치(998 passed, 0 failed)와 정확히 일치했다.

데이터 파일 SHA256(작업 전, 12장에서 작업 후와 비교):

```
ebe1249fe36c3fe681660c3659d2199f5ecd4f6949b7890479fac9a4e8ea8d33  data/tak_media_archive.json
e2ad1d39fa254ceaad4fb646124cb3e9b0b8e591ea688c1e0836fa1b6f706a31  data/tak_brain_knowledge.json
d122a0b68c093fb0e894251e60d5d987b40d9a268cd9b44522c4385bf5cabf72  data/tak_threads_pending.json
d89074291327bc759d5416531c6cc6fb9a8cad0c5fcb6e8dc32660535d995c68  data/threads_publish_log.json
```

## 3. `content-5971ed5204437cdd` 상세 조사

`data/tak_media_archive.json`에서 직접 읽었다(전체 18건 중 1건).

| 필드 | 값 |
|---|---|
| content_id | content-5971ed5204437cdd |
| knowledge_id | knowledge-scout-b28b782b2a33 |
| platform | blog |
| generation_status | valid |
| review_status | **approved** |
| generation_id | None(legacy — 6-06 이전, generation pool 도입 전 레코드) |
| original_title | "재무 판단에서 함께 볼 기준" |
| rewritten_title | "신기술을 바라보는 나의 기준" |
| rewritten_body | "...\n\n이 글의 금융 관련 내용은 원문 작성자의 설명이며, 금융기관의 공식 심사 기준으로 해석하지 않습니다" 로 끝남 |
| source_url | https://www.bbc.co.uk/news/articles/c14dpgm0rg4o... |
| evidence | SOURCE FACT(AI 위험 우려) + SOURCE URL + USER ORIGINAL THOUGHT(신기술을 두려워 말고 부딪혀 봐야 한다) |
| created_at | 2026-09-20T01:26:36 |
| edited_title / edited_body | 둘 다 None(사람이 Dashboard에서 손으로 고친 적 없음) |
| validation_errors | [] |

`original_title`("재무 판단에서 함께 볼 기준")과 `rewritten_body`의 금융기관 면책
문구는 6-04가 이미 지적한 finance 템플릿 오염의 흔적 그대로다 — 원문(BBC, Anthropic
CEO의 AI 개발 속도 완화 촉구)은 금융과 무관하다.

`knowledge-scout-b28b782b2a33`(`data/tak_brain_knowledge.json`)를 함께 읽었다:

| 필드 | 값 |
|---|---|
| article_type | **None**(6-05에서 "finance"→None으로 정정 완료) |
| category | **금융**(정정하지 않음 — 4-9장에서 이유 설명) |
| domain | **금융**(위와 동일) |
| knowledge_type | 의견 |
| knowledge_review_status | approved (2026-09-14) |
| source_url | BBC 원문, source_raw_id=scout-0db222f63dd1 |
| evidence | 3건(SOURCE FACT/SOURCE URL/USER ORIGINAL THOUGHT), 변경 없음 |

`content-5971ed5204437cdd`에 연결된 **같은 knowledge_id의 나머지 8건**도 함께
조사했다(9건 전체가 이 knowledge에서 나옴) — 이 사실이 4장·17장의 핵심이다:

| content_id | platform | generation_status | review_status |
|---|---|---|---|
| content-5971ed5204437cdd | blog | valid | **approved** |
| content-e787c9201b94a948 | shorts | valid | **approved** |
| content-3ae2d78568210164 | shorts | valid | **approved** |
| content-cabd37f3a2745724 | shorts | rejected | unreviewed |
| content-dbf0fb4eb5cfd791 | threads | valid | **approved** |
| content-81d4e7c5723598f6 | threads | valid | **approved** |
| content-4015df0692e0bcc4 | threads | valid | **approved** |
| content-5a6b175ac6023db1 | threads | rejected | unreviewed |
| content-cbcf705b6056c9fc | threads | valid | **approved** |

**7건이 이미 approved다.** 지시서가 지목한 것은 blog 1건이지만, 같은 오염된
KNOWLEDGE에서 나온 shorts 2건 + threads 4건도 동일하게 이미 승인된 상태다(단,
6-05/6-08 조사에 따르면 shorts/threads는 blog와 달리 실제 금융 문구 오염은 없었다 —
finance 프로파일이 바꾸는 제목 슬롯은 blog와 shorts 1개뿐이었고, 그 shorts 슬롯의
old 제목("새로운 기술을 마주하는 나의 기준")도 눈에 띄는 오염은 없었다). 승인된
shorts 2건에는 이미 downstream 파생 파일(`data/shorts_scripts/content-e787c9201b94a948.json`,
`data/shorts_scripts/content-3ae2d78568210164.json`)이 존재하고, 승인된 threads
4건에는 `data/tak_threads_pending.json`에 동일 content_id의 pending draft가
이미 생성돼 있다(5장에서 게시 여부 확인).

## 4. `content-afc6060bc1957867` 정정본 비교

`data/tak_media_archive_6-05_b28b782b2a33_regeneration.json`(6-05가 실제 LLM으로
만든 재생성 결과, 9건)에서 발견했다.

| 필드 | content-5971ed5204437cdd(구) | content-afc6060bc1957867(신) |
|---|---|---|
| content_id | content-5971ed5204437cdd | content-afc6060bc1957867 |
| knowledge_id | knowledge-scout-b28b782b2a33 | **동일** |
| platform | blog | **동일** |
| generation_status | valid | valid |
| review_status | **approved** | **unreviewed** |
| generation_id | None | **None**(6-06의 generation pool 스키마 도입 이전에 만들어진 파일이라 이 필드 자체가 항상 None — 6장에서 상세) |
| source_url | BBC 원문 | **동일** |
| evidence / evidence_unit_ids | 3건, lesson:1+reusable_principle:1 | **동일** |
| original_title | "재무 판단에서 함께 볼 기준" | "판단에 앞서 확인할 기준"(finance 슬롯 사라짐) |
| rewritten_title | "신기술을 바라보는 나의 기준" | "두려움보다 먼저, 직접 확인하는 태도" |
| rewritten_body 끝 | 금융기관 심사 기준 면책 문구 포함 | **면책 문구 없음** |
| created_at | 2026-09-20T01:26:36 | 2026-09-20T02:31:43(약 1시간 뒤) |
| edited_title/body | None | None |

6가지 확인 항목에 대한 답:

1. **같은 KNOWLEDGE에서 만들어졌는가** — 예. `knowledge_id` 완전히 동일.
2. **finance template contamination을 제거했는가** — 예. `original_title`의
   finance 전용 슬롯("재무 판단...")과 `rewritten_body`의 금융기관 면책 문구가
   신버전에서 문자 그대로 사라졌다. 문맥까지 확인: 신버전 본문은 "AI 모델이
   전 세계적으로 심각한 피해를 일으킬 수 있다는 우려" + "직접 부딪혀 봐야 한다"는
   의견만 담고, "금융", "심사 기준", "금융기관" 등 어떤 형태의 금융 관련 표현도
   전혀 없다(단어 매칭이 아니라 전체 3문단을 직접 읽어 확인).
3. **source/evidence가 유지되는가** — 예. `source_url`, `evidence`,
   `evidence_unit_ids` 전부 바이트 단위로 동일.
4. **새로운 사실을 추가한 흔적** — 없음. 신버전 본문 "판단에 앞서 실제로
   확인해 보는 태도가 필요합니다"는 evidence의 USER ORIGINAL THOUGHT("신기술은
   두려워 말고 부딪혀서 느껴봐야 한다")를 재진술한 것이지 새 사실이 아니다.
5. **기존 승인 레코드의 대체 대상으로 써도 되는 구조인가** — **부분적으로만
   그렇다.** content_id/generation_id가 다르므로 6장(dry-run)에서 실증하듯
   "대체"가 아니라 "추가"가 된다 — 이 세션의 핵심 발견이다.
6. **정정 버전 자체에 다른 문제가 있는가** — 육안/의미 검토로는 없다. 단,
   `review_status="unreviewed"`이므로 사람의 승인을 아직 거치지 않았고, 이
   파일 자체가 6-06 이전(generation pool 스키마 도입 전)에 만들어져
   `generation_id`가 없다 — 그대로는 `promote_media_generation.py`가 요구하는
   `(content_id, generation_id)` 매칭 대상이 될 수 없다(6장에서 실증).

## 5. 실제 게시 여부 확인

로컬 로그만 사용했다(외부 API 호출 없음).

| 대상 | 로그 | 결과 |
|---|---|---|
| content-5971ed5204437cdd(blog) | `data/blog_publish_log.json` **파일 자체가 존재하지 않음** | **NOT_PUBLISHED**(빈 이력으로 처리되나, 5-15장에서 지적된 기존 한계 — 6-15가 이미 MEDIUM으로 기록) |
| content-e787c9201b94a948, content-3ae2d78568210164(shorts, approved) | `data/youtube_publish_log.json`(1건, 테스트 업로드만 기록) + `data/shorts/`(mp4 없음) | **NOT_PUBLISHED**(ShortsScript 파일만 존재, 렌더링/업로드 흔적 없음) |
| content-dbf0fb4eb5cfd791, content-81d4e7c5723598f6, content-4015df0692e0bcc4, content-cbcf705b6056c9fc(threads, approved) | `data/threads_publish_log.json`(7건, 전부 다른 knowledge_id) + `data/tak_threads_pending.json`(같은 content_id 4건, 전부 `status="pending"`, `published_at=null`) | **NOT_PUBLISHED** |

`docs/publish_readiness_latest.md`(10장에서 재실행)도 `content-5971ed5204437cdd`를
`ALREADY_PUBLISHED`가 아니라 `NEEDS_HUMAN_REVIEW`로 분류한다 — 독립적으로 같은
결론을 뒷받침한다. **UNKNOWN으로 분류해야 할 항목은 없었다** — 모든 채널에 대해
로그 부재/미기록을 근거로 NOT_PUBLISHED로 확정할 수 있었다(단, blog 채널은
이력 파일 자체가 없다는 구조적 한계가 있으므로 "이력에 없다"≠"게시 안 됐다는 것을
100% 보증"이라는 단서를 남긴다 — 6-15의 MEDIUM 항목과 동일).

## 6. Production Archive 교체 경로 — 코드 조사

`scripts/promote_media_generation.py`(6-06, 6-09 batch 확장)와
`content_engine/media_archive.py`를 읽고 실제로 실행해 검증했다(전부 tmp 파일).

핵심 구조:

- `MediaArchiveRecord`는 frozen dataclass. `content_id`가 production archive의
  유일 키(`upsert_archive()`가 `{content_id: record}` dict로 관리).
- `compute_content_id()`는 `knowledge_id+platform+source_url+evidence_unit_ids+
  original_title+original_body`의 해시 — **rewritten_* 텍스트는 지문에 포함되지
  않는다.**
- `generation pool`(6-06)은 `(content_id, generation_id)` 복합 키의 별도 파일이며,
  `plan_promotion()`이 세 조건(① `(content_id, generation_id)`가 pool에 정확히
  존재, ② `generation_status=="valid"`, ③ `review_status=="approved"`)을 모두
  만족해야만 production archive에 `upsert_archive()`로 반영한다.
- `promote_media_generation.py`는 **review_status를 승인하는 기능이 없다** —
  이미 Dashboard 등에서 사람이 approved로 만든 generation만 대상으로 한다.
- `_can_review_media_record()`(`scripts/run_scout_dashboard.py`)는 **approved를
  되돌릴 수 없는 종결 상태로 취급한다** — `handle_media_edit_submission()`과
  `handle_media_dismiss_submission()` 둘 다 `review_status=="approved"`이면
  각각 "이미 승인된 콘텐츠는 수정할 수 없습니다"/"...보류할 수 없습니다"를
  반환하고 파일을 쓰지 않는다. 코드 전체(`dir(run_scout_dashboard)`)를 뒤져도
  approved를 되돌리는(`unapprove`/`revoke`/`supersede`) 라우트나 함수는
  **존재하지 않는다**(7장 테스트로 고정).

### A/B/C 방법 비교

| 기준 | A. 기존 승인 취소 후 재검수 | B. 정정 버전 promotion | C. 사람이 직접 텍스트 수정 |
|---|---|---|---|
| 가능한가(현재 코드) | **불가능** — approved 레코드에 "취소" 라우트 자체가 없다 | **부분 가능** — `promote_media_generation.py`가 존재하지만 그대로 쓸 수는 없다(아래 참고) | **불가능** — approved 레코드는 edit 라우트가 거부한다 |
| 기존 코드가 지원하는가 | 아니오(구조적으로 막혀 있음, `_can_review_media_record`) | 부분적으로(단건 promotion 자체는 있지만 사전 준비 필요) | 아니오(`handle_media_edit_submission`이 명시적으로 거부) |
| 변경되는 파일 | 해당 없음(불가) | production archive(신규 레코드 1건 추가) | 해당 없음(불가) |
| content_id가 바뀌는가 | 해당 없음 | **예**(6-05/6-06이 이미 문서화 — 9건 중 2건이 profile 변경으로 content_id가 바뀜, blog가 그중 하나) | 해당 없음 |
| publish history와 충돌하는가 | 해당 없음 | 아니오 — 대상 content_id는 5장에서 NOT_PUBLISHED로 확인됨. 단 **content_id가 바뀌므로, "이 knowledge가 이미 다른 content_id로 게시됐는지"는 promotion도 그 다음 audit도 자동으로 확인하지 않는다**(7장 4번 테스트, 실제 사각지대) | 해당 없음 |
| 이미 게시된 콘텐츠라면 | — | 만약 옛 content_id가 이미 게시됐다면, 새 content_id를 promotion해도 "게시 완료" 여부와 무관하게 진행돼 버린다(사람이 별도로 재게시 여부를 판단해야 함) | — |
| downstream audit 영향 | — | promotion 후 `audit_publish_candidates.py`가 새 content_id를 정상적으로(READY 후보로) 잡아낸다(단 옛 레코드가 approved로 여전히 NEEDS_HUMAN_REVIEW에도 같이 남는다 — 8장 참고) | — |
| rollback 가능한가 | 해당 없음(애초에 실행 불가) | 가능 — `upsert_archive()`가 파일을 덮어쓰기 전에는 아무 흔적도 안 남으므로, promotion 전 production archive를 백업해두면 파일 교체로 되돌릴 수 있다. 단 **자동 rollback 도구는 없다**(사람이 백업/복원해야 함) | 해당 없음(애초에 실행 불가) |

**결론**: 현재 코드에서 유일하게 실행 가능한 경로는 **B(promotion)** 뿐이다.
A와 C는 코드 레벨에서 명시적으로 차단돼 있다(안전장치이지 버그가 아니다 —
승인 이후 threads/shorts는 이미 downstream 파일이 만들어졌을 수 있어 "되돌릴
수 없는 상태"로 설계된 것으로 보인다). 하지만 B도 그대로 실행할 수는 없다 —
`content-afc6060bc1957867`가 들어 있는 `data/tak_media_archive_6-05_..._regeneration.json`은
6-06의 generation pool 스키마(= `generation_id` 필드)가 생기기 **이전**에
만들어진 파일이라 모든 레코드의 `generation_id`가 `None`이고 `review_status`도
`unreviewed`다 — `plan_promotion()`의 세 조건 중 두 개를 만족하지 못한다.

## 7. dry-run 교체 시뮬레이션

실제 파일은 전혀 열지 않고(생성 pool 파일은 읽기만 함) `tempfile.TemporaryDirectory()`
안에서만 실행했다. 스크립트: `/tmp/.../scratchpad/6-16/dry_run_simulation.py`
(세션 스크래치패드, 저장소에는 포함하지 않음 — 절차는 아래 실제 출력과
`tests/test_critical_content_replacement_audit.py`에 재현 가능한 형태로 고정했다).

```
=== BEFORE (tmp copy of production archive) ===
total records: 18
content-5971ed5204437cdd: review_status=approved generation_status=valid generation_id=None
  title: 신기술을 바라보는 나의 기준

=== Simulated generation-pool candidate (tmp only) ===
content-afc6060bc1957867: review_status=approved generation_status=valid generation_id=gen-simulated-6-16-dryrun
  title: 두려움보다 먼저, 직접 확인하는 태도

=== Method B: plan_promotion() + execute (tmp production archive only) ===
candidate.knowledge_id == old.knowledge_id: True
current_active for NEW_CONTENT_ID before promote: None
total records after promotion: 19 (before: 18)
OLD content-5971ed5204437cdd still present: True, review_status=approved (UNCHANGED)
NEW content-afc6060bc1957867 present: True, review_status=approved

=== Method A: attempt to dismiss the already-approved OLD record ===
handle_media_dismiss_submission result: updated=None, error='이미 승인된 콘텐츠는 보류할 수 없습니다.'
OLD record review_status after attempted dismiss: approved (expected: approved, unchanged)

=== Method C: attempt to hand-edit the already-approved OLD record ===
handle_media_edit_submission result: updated=None, error='이미 승인된 콘텐츠는 수정할 수 없습니다.'
OLD record edited_title after attempted edit: None (expected: None, unchanged)

=== content_id collision check across the 9-record regeneration set ===
old production content_ids for this knowledge: [...9개...]
new regeneration content_ids: [...9개...]
colliding content_ids: ['content-3ae2d78568210164', 'content-4015df0692e0bcc4',
  'content-5a6b175ac6023db1', 'content-81d4e7c5723598f6', 'content-cabd37f3a2745724',
  'content-cbcf705b6056c9fc', 'content-dbf0fb4eb5cfd791']  (7건, 6-05/6-06과 완전히 동일)

=== Real file integrity check ===
production archive sha256 unchanged: True
regeneration file sha256 unchanged: True
```

**중요 주석**: `review_status="approved"`로 세팅된 시뮬레이션 candidate는
**실제로 아무도 승인하지 않았다** — 이 세션이 "만약 사람이 generation pool에서
이 레코드를 승인했다면"이라는 가정을 tmp 파일에서만 재현한 것이다. 실제
`data/tak_media_archive_6-05_..._regeneration.json`, `data/tak_brain_knowledge.json`,
Dashboard 승인 상태는 이 시뮬레이션으로 전혀 바뀌지 않았다(위 SHA256 확인 참고).

BEFORE/AFTER 표:

| 항목 | BEFORE | AFTER(시뮬레이션) |
|---|---|---|
| 전체 레코드 수 | 18 | 19 |
| content-5971ed5204437cdd | approved, 오염된 텍스트 | **변경 없음**(approved, 오염된 텍스트 그대로) |
| content-afc6060bc1957867 | 없음 | **신규 추가**(approved, 정정된 텍스트) |
| 삭제되는 레코드 | — | **없음**(promotion은 삭제하지 않는다) |
| content_id 변경 여부 | — | 옛 레코드의 content_id는 안 바뀜; 새 레코드는 별개의 새 content_id |
| knowledge_id 변경 여부 | — | 둘 다 knowledge-scout-b28b782b2a33로 동일(안 바뀜) |
| generation_id 변경 여부 | 옛 레코드: None | 새 레코드: gen-simulated-6-16-dryrun(시뮬레이션 값) |
| review_status 변경 여부 | 옛 레코드: approved | **변경 없음**(옛 레코드는 그대로 approved로 남음 — 취소되지 않음) |
| publish history 영향 | — | 없음(둘 다 NOT_PUBLISHED, 5장) |
| downstream readiness 영향 | 옛 레코드만 존재 시 NEEDS_HUMAN_REVIEW 1건 | **두 레코드 다 존재** — 옛 것은 여전히 NEEDS_HUMAN_REVIEW, 새 것은 (category="금융"이 그대로이므로) **역시 NEEDS_HUMAN_REVIEW**(READY 아님 — knowledge의 category를 안 바꿨으므로 안전장치가 그대로 작동, 9장 참고) |

## 8. 안전성 테스트 추가

신규 파일 **`tests/test_critical_content_replacement_audit.py`**(10개 테스트,
5개 클래스). 전부 합성(synthetic) fixture 또는 `tempfile`만 사용하고, **실제
production archive/knowledge/threads pending 파일은 경로조차 참조하지 않는다**
(6-06 계열 테스트와 달리 이 파일은 실제 데이터를 읽는 테스트도 포함하지 않기로
했다 — 실제 데이터 상태가 향후 바뀌어도 이 회귀 테스트들이 깨지지 않게 하기 위함).

이미 커버된 내용(다시 만들지 않음): `tests/test_media_versioning_and_promotion.py`의
generation pool 보존/승격 게이팅/dry-run, `tests/test_media_dashboard.py`의
"approved 콘텐츠에는 edit/dismiss 버튼이 없다".

새로 고정한 4가지 사실:

1. **`ApprovedRecordReplacementIsAdditiveTests`**: content_id가 바뀌는 정정
   promotion은 옛 승인 레코드를 교체하지 않고 **추가**한다는 것, 그 결과 같은
   knowledge_id에 approved 레코드가 2건 동시에 존재하게 된다는 것(6-6장에서
   실증한 것과 동일한 사실을 pytest로 고정).
2. **`ApprovedRecordCannotBeSupersededInPlaceTests`**: approved 레코드는
   edit/dismiss 둘 다 거부되고, `run_scout_dashboard` 모듈에 승인을 되돌리는
   핸들러(`handle_media_*` 중 approve/dismiss/edit 세 개 외 다른 것) 자체가
   없음을 `dir()` 기반으로 고정 — 향후 이런 핸들러가 추가되면 이 테스트가
   실패해 이 보고서의 A/B/C 비교를 다시 검토하도록 강제한다.
3. **`ContentIdCollisionSilentOverwriteRiskTests`**: generation pool을 쓰지
   않고 같은 content_id를 production archive 파일에 직접 `upsert_archive()`
   하면 이전 `rewritten_title`뿐 아니라 **`review_status`(사람의 승인 여부)까지
   조용히 덮어써진다**는 것 — 6-05/6-06이 별도 generation pool 파일을 도입한
   이유를 회귀 테스트로 고정했다.
4. **`PromotionIgnoresPublishHistoryGapTests`**: `promote_media_generation.py`는
   publish 이력을 전혀 참조하지 않고, `content_engine.publish_audit`의
   `ALREADY_PUBLISHED` 판정도 content_id 단위로만 대조하므로, **content_id가
   바뀌는 정정에서는 "이 knowledge/source가 이미 다른 content_id로 게시됐는지"를
   아무 코드도 자동으로 잡아주지 않는다**는 사각지대를 문서화했다(고치지 않음 —
   17장에서 정책 결정 사항으로 남긴다).

추가로 `ContentIdIdentityGuaranteesTests`(3개)는 `compute_content_id()`가
knowledge_id/source_url이 다르면 항상 다른 content_id를 낸다는 것을 확인해,
"content_id가 같다 = knowledge_id/source가 같다"는 promotion의 암묵적 전제가
실제로 안전한지 뒷받침한다.

10개 전부 통과:

```
$ python -m pytest tests/test_critical_content_replacement_audit.py -v
...
10 passed in 0.19s
```

## 9. SCOUT category 구조적 문제 분석 (코드 재확인)

`tak_scout/collector.py`, `tak_scout/knowledge_bridge.py`, `data/scout_sources.json`을
다시 읽고 실제 실행 경로를 추적했다(6-15의 조사와 동일한 결론에 독립적으로
도달했다 — 6-15를 그대로 인용하지 않고 코드를 직접 재확인함).

```
data/scout_sources.json: "BBC Business" 소스의 category="finance" (RSS 피드
  단위 블랭킷 태그, 등록된 소스는 이 2개뿐 — "BBC Business"/"Hacker News")
    -> tak_scout/collector.py:46  candidate.category = source["category"] (그대로 복사)
    -> tak_scout/knowledge_bridge.py:_map_category()  "finance" -> "금융"
    -> KnowledgeRecord.category = KnowledgeRecord.domain = "금융"
       (기사 개별 내용을 전혀 분석하지 않음)
tak_scout/knowledge_bridge.py:97  article_type = None (6-04부터 항상 고정,
  "신뢰할 수 있는 content-based 분류 신호가 없다"는 이유의 명시적 주석 포함)
```

**대조**: 블로그 RAW import 경로(`tak_brain/knowledge.py::transform_raw()` →
`tak_brain/article_types.py::ArticleTypeClassifier`)는 이미 **제목+본문 양쪽에
근거 키워드가 모두 있어야만** `article_type`을 결정한다(`_RULES` 딕셔너리,
최소 점수 2, 동점이면 "general"로 후퇴) — 그리고 그 결과로 `domain`도
content_type-transformer가 정해준다(`knowledge_transformers.py`, 예:
finance transformer → domain="금융"). 즉 **"제목/본문 키워드 기반 분류기"는
이미 이 저장소에 존재하고, 실제로 쓰이고 있으며, deterministic 테스트도
갖췄다**(`tests/test_article_types.py`) — 단 SCOUT 경로에는 전혀 연결돼 있지
않다. 흥미로운 점: 두 경로가 category/domain을 다루는 방향이 정확히
반대다 — RAW 경로는 `category`를 아예 안 쓰고 `domain`을 content 기반으로
정하는데, SCOUT 경로는 `category`/`domain`을 둘 다 소스 태그로 정하고
`article_type`을 비운다. 이 비대칭 자체는 이번 세션에서 고치지 않았다(코드
동작을 바꾸지 않기로 한 원칙, 10장) — 다만 향후 설계 시 "두 경로가 같은
필드를 다른 방식으로 채운다"는 점을 반드시 고려해야 한다.

### 설계 A vs 설계 B

**설계 A — "신뢰할 수 있는 content 신호가 없으면 category를 None/기타로 둔다"**
(article_type에 이미 적용된 원칙을 category/domain까지 확장)

| 평가 항목 | 내용 |
|---|---|
| false positive | 없음(애초에 판정을 안 하므로) |
| false negative | **최대** — 실제 금융/부동산/대출 기사가 SCOUT으로 들어와도 category가 "기타"가 되면 `is_review_required()`가 `article_type`/`domain` 둘 다 신호를 잃어 False를 반환할 수 있다(`category`/`domain`이 유일한 안전망인 SCOUT 경로에서 이 방식은 안전장치 자체를 지운다) |
| 금융 콘텐츠→일반 오분류 위험 | **매우 높음** — 지금 SCOUT 소스에 실제 금융시장 기사도 섞여 있다(6-15 3-2장: RSS 18건 중 4건이 진짜 금융시장 기사) — 이 안을 SCOUT에 그대로 적용하면 그 4건도 안전망을 잃는다 |
| 비금융→금융 오분류 위험 | 없음(판정을 안 하므로) |
| review_required 안전장치 | **약화됨** — 이것이 결정적 단점. 현재 `is_review_required()`는 category/domain/article_type 3중 신호로 설계됐는데, category/domain까지 비우면 SCOUT 경로에서는 사실상 안전장치가 전무해진다 |
| article_type과의 역할 분리 | 완전히 분리 유지(가장 단순) |
| LLM 의존성 | 없음 |
| deterministic 테스트 | 쉬움(항상 None/기타) |
| 유지보수성 | 매우 쉬움(로직 삭제) |

**설계 B — "제목/요약 기반 최소 keyword 분류기 도입"**
(SCOUT candidate 자체 title+summary에 `ArticleTypeClassifier`류 규칙 적용)

| 평가 항목 | 내용 |
|---|---|
| false positive | 존재(예: "은행", "대출"이라는 단어가 비유적으로 쓰인 기사) — `ArticleTypeClassifier`처럼 제목+본문 양쪽 매치를 요구하고 최소 점수/동점 후퇴 규칙을 넣으면 최소화 가능하나 0으로 만들 수는 없음 |
| false negative | 설계 A보다 낮지만 여전히 존재(키워드에 없는 표현 사용 시) |
| 금융 콘텐츠→일반 오분류 위험 | **중간** — 키워드 사전 밖의 표현을 쓰면 놓칠 수 있음(예: "기준금리" 대신 "정책금리" 사용) |
| 비금융→금융 오분류 위험 | **낮음**(제목+요약 양쪽 매치 요구로 완화 가능, `ArticleTypeClassifier` 선례가 이미 검증된 패턴) |
| review_required 안전장치 | 이론적으로는 **더 정교해질 여지가 있지만**, 지금처럼 "모르면 최대한 넓게 잡는(= category="금융"으로 보수적으로 유지)" 전략보다 오탐/누락 실패 모드가 더 복잡해진다 — 안전장치를 정교화하려는 시도가 새로운 실패 지점을 만들 위험 |
| article_type과의 역할 분리 | article_type처럼 "구조적 템플릿 신호"가 아니라 "주제 분류"라는 다른 목적이므로, 같은 분류기를 그대로 재사용하면 두 필드의 의미가 다시 섞일 위험(6-04가 막으려던 문제의 재발 형태) — **반드시 별도 규칙/함수로 분리해야 함** |
| LLM 의존성 | 없음(순수 키워드 규칙 유지 시) — 단, 이 정도 정밀도로는 근본 해결이 안 되고 LLM 분류로 가야 한다는 압력이 생길 수 있음(이번 세션 범위 밖) |
| deterministic 테스트 | `ArticleTypeClassifier` 선례로 가능함이 이미 증명됨(`tests/test_article_types.py`) |
| 유지보수성 | 설계 A보다 어려움 — 새 카테고리/새 소스가 추가될 때마다 키워드 사전을 계속 관리해야 함 |

### 권고(설계만 — 구현하지 않음)

**category/domain에는 설계 A(신뢰 신호 없음=None/기타)를 적용하지 않는 것을
권고한다.** 이유: SCOUT 경로에서 `is_review_required()`의 유일한 안전망이
category/domain이기 때문이다(article_type은 이미 SCOUT에서 항상 None). 지금의
"블랭킷하지만 보수적인" category="금융"은 **false positive(비금융을 review에
가둠)는 만들지만 false negative(진짜 금융을 놓침)는 만들지 않는다** — 안전
우선 시스템에서는 이 비대칭이 바람직하다. 설계 A는 이 비대칭을 뒤집어 false
negative를 만들 수 있으므로 채택하지 않는다.

**설계 B(최소 키워드 분류기)는 "category/domain을 대체"하는 용도가 아니라
"category/domain과 별도로, article_type에 준하는 새로운 3번째 신호"로
설계해야 한다** — 예: `is_review_required()`가 여전히 지금의 category/domain
블랭킷 신호를 그대로 유지한 채(안전망 유지), 여기에 `suggest_category()`
같은 **참고용/비안전 판정**에만 설계 B의 결과를 추가로 쓰는 방식. 이렇게
분리하면 설계 B가 완벽하지 않아도(false positive/negative가 있어도) 안전
판정 자체는 약화되지 않는다. 이 권고는 **설계일 뿐이며 이번 세션에서
구현하지 않았다** — 사람의 결정과 별도 세션이 필요하다.

## 10. category/domain/article_type contract

코드와 docstring을 직접 근거로 정리했다(임의로 의미를 만들지 않음).

| 필드 | 실제 의미(코드 근거) | 소비하는 코드 | 신뢰 수준 |
|---|---|---|---|
| `article_type` | **콘텐츠 생성 템플릿을 결정하는 구조적 신호.** `content_engine/generator.py::_profile()`(109~115행)이 이 값만으로 finance/book/experience/criterion 프로파일을 고른다. `content_engine/blog_publish_pack.py::is_review_required()`(92행)도 `article_type=="finance"`를 안전 신호 중 하나로 쓴다. | `generator.py::_profile()`, `is_review_required()`, `suggest_category()` | **높아야만 설정한다** — 블로그 RAW 경로는 제목+본문 양쪽 키워드 매치를 요구하는 `ArticleTypeClassifier`로만 설정하고, SCOUT 경로는 신뢰 신호가 없으므로 항상 `None`(6-04) |
| `category` | KNOWLEDGE의 **주제 분류**. `tak_brain/models.py::CATEGORIES`(금융/대출/경매/부동산/인간관계/심리/자기계발/독서/건강/가족/골프/기타)라는 고정 어휘 중 하나. `is_review_required()`가 이 값이 `FINANCE_REVIEW_KEYWORDS`(금융/대출/경매/부동산) **완전 일치**(tuple containment)면 True를 반환한다. `suggest_category()`(Naver 블로그 카테고리 추천, 비안전 용도)도 이 값을 참고한다. | `is_review_required()`, `suggest_category()` | SCOUT 경로는 RSS 소스 태그(낮은 신뢰도)를 그대로 씀. 블로그 RAW 경로는 이 필드를 아예 채우지 않음(`knowledge_transformers.py`에 `category=` 대입이 없음) |
| `domain` | `article_type`보다 **넓은 도메인/안전 검토 신호**. `is_review_required()`가 이 값에 `FINANCE_REVIEW_KEYWORDS` 중 하나라도 **부분 문자열로 포함**(`in` 연산자)되면 True를 반환한다 — `category`의 완전 일치보다 느슨한 매칭. 블로그 RAW 경로에서는 article_type별 transformer가 사람이 읽을 수 있는 설명형 문자열로 채운다(예: finance→"금융", ai_business→"자기계발·AI", book_philosophy→"독서·철학") — 이 자체도 content 기반(간접적으로 article_type에서 파생). | `is_review_required()` | SCOUT 경로는 category와 동일한 소스 태그를 그대로 복사(`domain = category = _map_category(...)`) — 블로그 경로와 도출 방식이 반대(위 9장 "대조" 참고) |

**요약**: 세 필드는 코드상 명확히 분리돼 있다 — `article_type`은 "무슨 템플릿을
쓸지"만 결정하고, `category`/`domain`은 오직 `is_review_required()`의 안전
판정에만 쓰인다(그리고 `suggest_category()`의 비안전 추천에도 `category`가
쓰인다). 이 분리 자체는 6-04/6-15가 이미 검증했고 이번 세션도 코드를 다시 읽어
동일하게 확인했다 — **문제는 필드 간 암묵적 연결이 아니라, SCOUT 경로에서
category/domain을 채우는 데이터 소스(RSS 피드 블랭킷 태그)의 신뢰도가
애초에 낮다는 것**이다.

## 11. Publish Readiness 재실행

```
$ python3 scripts/audit_publish_candidates.py
=== Publish Readiness 요약 ===
전체 Production 콘텐츠: 18
게시 가능(READY): 9
사람 검토 필요(NEEDS_HUMAN_REVIEW): 7
게시 차단(BLOCKED): 2
이미 게시됨(ALREADY_PUBLISHED): 0
오류(ERROR): 0
```

`content-5971ed5204437cdd`는 **여전히 NEEDS_HUMAN_REVIEW**로 남아 있음을
확인했다(임의로 READY로 만들지 않았다 — 이 세션은 KNOWLEDGE/archive를 전혀
쓰지 않았으므로 결과가 바뀔 이유가 애초에 없다). READY 9건은 전부 다른
knowledge(`knowledge-scout-6d1d0e2fa762`, 6-12에서 이미 promotion됨) 소속이고,
NEEDS_HUMAN_REVIEW 7건은 전부 이번 조사 대상 knowledge(`knowledge-scout-b28b782b2a33`)의
approved+valid 7건과 정확히 일치한다.

`docs/publish_readiness_latest.md`를 재생성했다(이 스크립트의 정상 설계 동작 —
Production Archive/KNOWLEDGE는 읽기만 하고 이 보고서 파일만 갱신한다). 이전
커밋 버전과 비교하면 **생성 시각(타임스탬프)만 바뀌고 나머지 내용은 완전히
동일**했다:

```
$ git diff docs/publish_readiness_latest.md
-생성 시각(UTC): 2026-09-21T04:21:16...
+생성 시각(UTC): 2026-09-21T05:40:07...
```

## 12. Threads consistency 재확인

```
$ python3 scripts/audit_threads_publish_consistency.py
전체 대상 content_id: 11
CONSISTENT: 1
PUBLISHED_BUT_PENDING_STALE: 0
PENDING_WITHOUT_PUBLISH_LOG: 4
FAILED: 0
ORPHAN: 6
DUPLICATE: 0
```

6-15가 남긴 결과와 **완전히 동일**하다(`docs/threads_publish_consistency_latest.md`
diff도 타임스탬프 한 줄만 바뀜). 이번 세션에서 Threads 데이터를 전혀 바꾸지
않았으므로 예상대로다 — 원인 조사가 필요한 변경은 없었다.

## 13. 데이터 SHA256(작업 전/후)

```
                                                                   작업 전  ==  작업 후
data/tak_media_archive.json      ebe1249f...8ea8d33   ==   ebe1249f...8ea8d33   (동일)
data/tak_brain_knowledge.json    e2ad1d39...6f706a31  ==   e2ad1d39...6f706a31  (동일)
data/tak_threads_pending.json    d122a0b6...5cabf72   ==   d122a0b6...5cabf72   (동일)
data/threads_publish_log.json    d8907429...d995c68   ==   d8907429...d995c68   (동일)
```

4개 파일 전부 세션 시작 시점과 바이트 단위로 완전히 동일하다.

## 14. 테스트 결과

```
$ python -m pytest -q
1008 passed, 68 subtests passed in 147.64s (0:02:27), 0 failed
```

(998 baseline + 신규 10건 = 1008. subtests 수 68은 그대로 — 신규 테스트가
`subTest`를 쓰지 않아 예상과 일치.) 기존 미커밋 변경(`.gitignore`,
`content_engine/__init__.py` 등)으로 인한 실패는 없었다 — 애초에 이번 세션은
그 파일들을 열지도 않았다.

## 15. 실제 데이터 변경 여부

**없음.** 13장의 SHA256이 이를 확정적으로 증명한다. Production Archive,
KNOWLEDGE, Threads pending, Threads publish log 중 어느 것도 이번 세션에서
한 바이트도 바뀌지 않았다. 이번 세션이 실제로 변경한 파일은:

- `tests/test_critical_content_replacement_audit.py`(신규, 10개 테스트)
- `docs/publish_readiness_latest.md`(재생성 — 스크립트의 정상 설계 동작, 내용은
  타임스탬프 외 동일)
- `docs/threads_publish_consistency_latest.md`(재생성 — 위와 동일한 성격)
- `docs/6-16_critical_content_replacement_audit.md`(이 문서, 신규)

## 16. Git 처리

`git status --short`/`git diff`로 이번 세션이 만든 변경만 정확히 식별했다.
이전 세션들이 남긴 기존 미커밋 변경(`.gitignore`, `content_engine/__init__.py`,
`content_engine/generator.py`, `content_engine/llm_provider.py`,
`content_engine/rewrite.py`, `tests/test_content_engine.py`,
`tests/test_media_batch.py`, 그리고 다수의 기존 untracked 문서/스크립트)은
`git add`에 포함하지 않았다. `git add .`/`git add -A`는 사용하지 않고, 이번
세션이 만든 4개 파일만 이름을 명시해 스테이징한다.

## 17. 다음 작업에서 사람이 결정해야 하는 사항

1. **CRITICAL — `content-5971ed5204437cdd`(및 동일 knowledge의 승인된 형제
   6건: shorts 2건 + threads 4건) 처리 방침.** 6장/7장에서 확인했듯, 현재
   코드로 실행 가능한 유일한 경로는 **B(promotion으로 정정본 추가)**이고, 그
   결과 옛 레코드는 approved 상태로 영구히 남는다(A/C는 코드가 차단). 사람이
   결정해야 할 것:
   - 옛 오염 레코드 7건을 "이력으로 영구 보존"할지, 아니면 이를 처리할 새
     기능(예: `review_status`에 `superseded` 상태를 추가하고 approved도
     그 상태로는 전환 가능하게 하는 최소 변경)을 별도 세션에서 설계할지.
   - `content-afc6060bc1957867`(blog)만 우선 promotion할지, 아니면
     shorts/threads 형제까지 6-05 재생성 결과 전체를 함께 promotion할지(그
     경우 shorts 2건 + threads 4건도 같은 사각지대를 갖는다).
2. **HIGH — SCOUT category 분류 개선 방향.** 9장에서 설계 A/B를 비교했고,
   category/domain은 안전장치 유지를 위해 **바꾸지 말 것**을 권고했다. 다만
   설계 B(참고용 최소 키워드 분류기, 안전 판정과 분리)를 실제로 도입할지는
   사람의 정책 결정이 필요하다.
3. **`generation_id` 없는 6-05 regeneration 파일을 어떻게 promotion 가능한
   형태로 만들지.** 두 옵션: (a) 사람이 승인 후 이 파일을 그대로
   `generation_id`를 하나 부여해 승격하거나(이번 세션이 tmp에서 시뮬레이션한
   방식), (b) `knowledge-scout-b28b782b2a33`을 `--as-generation` 플래그로
   다시 한번 실제 LLM 호출해 정식 generation pool에 새로 생성한다(6-06 19장
   3번이 이미 남긴 미해결 항목). (b)는 LLM 호출이 필요하므로 이번 세션
   범위 밖이다.
4. **`content-afc6060bc1957867`의 `review_status="unreviewed"`를 실제로
   승인할지.** 이 세션은 그 판단을 시뮬레이션(tmp)으로만 대신했다 — 실제
   승인은 Dashboard에서 사람이 텍스트를 직접 읽고 해야 한다.
5. **`PromotionIgnoresPublishHistoryGapTests`가 문서화한 사각지대**(content_id가
   바뀌면 "이미 게시된 knowledge/source"인지 자동 감지가 안 됨)를 이번
   시나리오(둘 다 NOT_PUBLISHED로 확인됨, 5장) 이후에도 남겨둘지, 아니면
   `promote_media_generation.py`나 `audit_publish_candidates.py`에 knowledge_id/
   source_url 기준의 추가 확인을 넣을지 — 이번 세션은 설계도 제안하지 않고
   사실만 확인했다(범위 밖).
6. **`data/blog_publish_log.json` 파일 부재**(6-15가 이미 MEDIUM으로 기록,
   5장에서 재확인) — Naver 블로그 실제 게시 이력을 추적하는 별도 방법이
   필요한지 여전히 미해결이다.
