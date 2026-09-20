# TAK AUTO 6-10 — Generation Pool 편집 기능 + 최종 Human Review 완성 + Promotion 안전성 보강

## 1. 작업 목적

6-09까지 다음 구조가 완성됐다.

```
KNOWLEDGE → Generation Pool → /media/generations → Human Review
  → approved → Batch Dry-Run → Batch Execute → Production Archive
```

단, Generation Pool에는 승인/보류 기능만 있고 production `/media`처럼 제목/본문을
직접 고치는 편집 기능이 없었다. 사람이 콘텐츠를 읽다가 "제목만 조금 고치면
승인할 만하다"고 판단해도, 이 화면에서는 그럴 방법이 없었다(보류하거나 그대로
승인하거나 둘 중 하나뿐).

이번 6-10의 목표는 실제 Production promotion을 실행하는 것이 아니라, Human
Review를 실제 운영 수준으로 완성하는 것이다:

```
Generation Pool → 내용 확인 → 필요하면 제목/본문 수정 → 수정하면 자동으로
  unreviewed → 다시 검토 → approved → Batch Promotion
```

추가로 6-09에서 남겨둔 두 가지 테스트 공백(혼합 idempotency, edited content가
promotion에 실제로 반영되는지)을 이번에 메운다.

## 2. 시작 상태

```
$ git branch --show-current
main

$ git fetch origin   # (출력 없음, 최신)
$ git log origin/main..HEAD --oneline   # (출력 없음, 앞서가는 커밋 없음)
```

`git status --short`(작업 시작 시점 전체, 발췌):

```
 M .gitignore
 M content_engine/__init__.py
 M content_engine/generator.py
 M content_engine/llm_provider.py
 M content_engine/rewrite.py
 M data/tak_brain_knowledge.json
 M tests/test_content_engine.py
 M tests/test_media_batch.py
?? data/tak_media_archive.json
?? (다수의 기존 untracked 문서/스크립트 — 이번 작업과 무관, 손대지 않음)
```

이 목록에 있는 파일은 이번 작업 시작 전부터 이미 존재하던, 다른 세션의
미커밋 변경이다. `git reset --hard`/`git clean -fd`/`git checkout -- .`/
`git add .`/`git add -A`는 전혀 사용하지 않았고, 작업 종료 시점에도 이
목록이 그대로 남아 있는지 19장에서 재확인한다.

실제 대상도 재확인했다:

- knowledge_id: `knowledge-scout-6d1d0e2fa762`
- generation_id: `gen-20260920T033856-6e8d98fb`
- 파일: `data/tak_media_generation_6-07_knowledge-scout-6d1d0e2fa762.json`
- 총 9건(Blog 1 · Shorts 3 · Threads 5), 전부 `generation_status=valid`,
  `review_status=unreviewed`

## 3. 6-09 baseline

```
$ python -m pytest -q
900 passed, 68 subtests passed in 150.88s (0:02:30)
```

지시받은 baseline(900 passed / 68 subtests / 0 failed)과 정확히 일치했다.

## 4. Generation Pool 편집 설계

기존 production `/media`의 `handle_media_edit_submission()` 의미를 그대로
따랐다(4장 지시):

- 편집 가능한 필드: `edited_title`, `edited_body`뿐이다.
- `original_title`/`original_body`(생성 전 원본), `rewritten_title`/
  `rewritten_body`(AI 생성 결과)는 절대 건드리지 않는다.
- 저장 후에는 항상 `review_status = "unreviewed"`로 되돌린다.
- 새 review status를 만들지 않고 기존 `unreviewed`/`approved`/`dismissed`
  enum만 그대로 재사용한다.
- 최종 콘텐츠 우선순위(edited → rewritten → original)는 이미
  `content_engine/media_archive.py`의 `MediaArchiveRecord.final_title`/
  `final_body` property가 제공하므로 그대로 재사용했다 - 이번 작업에서 다시
  구현하지 않았다.

### 7장 관련 결정: "approved 상태를 수정하면 unreviewed로 되돌린다"는 지시와
### 기존 정책의 충돌 처리

원 지시문(7장)은 "approved → edit → unreviewed" 흐름을 예시로 들었다. 하지만
기존 production `/media`의 `_can_review_media_record()`는 **이미 approved인
레코드는 애초에 수정 자체를 차단**한다(`test_approved_content_cannot_be_edited`,
`handle_media_edit_submission`의 "이미 승인된 콘텐츠는 수정할 수 없습니다."
오류) - 승인은 이 Dashboard에서 되돌릴 수 없는 종결 상태이고, 승인 이후에는
이미 downstream(Threads pending queue, ShortsScript 등)으로 넘어갔을 수도 있어
그 뒤의 수정이 안전하지 않기 때문이다.

지시문 7장 마지막 줄 "기존 프로젝트의 의미와 다르면 임의로 바꾸지 말고 현재
동작을 우선한다"와 4장 "기존 /media의 편집 의미를 그대로 따른다", 10장
"기존 정책을 확인한다. 임의로 새 정책을 만들지 않는다"를 종합해, **이번
Generation Pool 편집도 approved는 수정 차단(기존 정책 그대로), dismissed/
unreviewed만 수정 가능하고 수정하면 unreviewed로 돌아간다**는 정책을 그대로
적용했다. 이는 `_can_review_generation_record()`(6-08에서 이미
`_can_review_media_record()`와 동일한 기준으로 구현돼 있었다)를
`handle_generation_edit_submission()`에서도 그대로 재사용하는 것만으로
자연스럽게 달성된다 - 새 판단 로직을 추가하지 않았다.

이 결정에 따라 16장의 "Edit → Approve → Promotion 통합 테스트"는 지시문의
문자 그대로("approved 레코드를 곧바로 edit")가 아니라, "dismissed 상태를
사람이 수정 → unreviewed로 복귀 → 다시 approve"라는 동등하게 유효한 현실
시나리오로 구현했다(`EditApprovePromotionIntegrationTests`, 11장 참고) - "수정하면
반드시 unreviewed로 돌아간다"는 지시문의 핵심 안전 요구사항 자체는 정확히
동일하게 검증한다.

## 5. 편집 라우트

기존 6-08 승인/보류 라우트와 동일한 구조를 그대로 따랐다.

- `GET /media/generations/record/<content_id>/<generation_id>/edit`
  - 제목 input + 본문 textarea 폼을 보여준다(`render_generation_edit_html`).
  - `_can_review_generation_record()`가 False면(approved 또는
    rejected/error) 폼 대신 안내 문구만 보여준다.
  - 레코드를 찾지 못하면 404.
- `POST /media/generations/record/<content_id>/<generation_id>/edit`
  - `handle_generation_edit_submission()` 호출 → `/media/generations?notice=saved`로
    리다이렉트.
  - 레코드 없음 → 404, 정책 위반(approved/rejected 등) → 400.

두 라우트 모두 `/media/generations/`로 시작하는 일반 knowledge_id 필터
라우트, `/media/`로 시작하는 production `/media` 편집 라우트보다 **반드시
먼저** 검사하도록 배치했다 - 6-08의 승인/보류 라우트가 이미 같은 순서
원칙을 쓰고 있어서(주석 참고) 그 패턴을 그대로 따랐다. 실제로 순서를
바꿔서 테스트해보지는 않았지만(불필요한 위험이라 생략), 기존 approve/dismiss
라우트가 이미 이 순서로 정상 동작하고 있고 새 라우트도 똑같은 위치·조건
(`path.startswith("/media/generations/record/") and path.endswith(...)`)을
그대로 복제했으므로 안전하다.

`(content_id, generation_id)` 복합 키는 `find_generation_pool_record()`
(6-08에 이미 존재)를 그대로 재사용해 정확히 그 파일, 그 레코드만
`upsert_generation_archive()`로 갱신한다.

## 6. review_status 안전장치

`handle_generation_edit_submission()`은 `handle_media_edit_submission()`과
정확히 같은 순서로 검증한다:

1. `(content_id, generation_id)`로 레코드 조회 → 없으면 `(None, None)` (호출부가
   404 처리).
2. `_can_review_generation_record()` 확인 → False면 approved/rejected 각각
   다른 오류 메시지와 함께 `(None, message)` 반환.
3. 제목/본문 공백 검증.
4. `replace(record, edited_title=title, edited_body=body,
   review_status="unreviewed")` → `upsert_generation_archive(path, [updated])`.

`GenerationEditRouteTests`(11개 테스트)로 다음을 고정했다:

- unreviewed 레코드 수정 → `edited_*` 저장, `review_status`는 계속 unreviewed.
- dismissed 레코드 수정 → `review_status`가 unreviewed로 돌아감.
- approved 레코드 수정 시도 → 400 + "이미 승인된" 오류, `edited_title`은
  `None`으로 유지(저장 자체가 실행되지 않음).
- rejected(generation_status) 레코드 수정 시도 → 400 + "VALID" 오류.
- 제목 공백 → 400 + "제목을 입력해주세요.".
- 원본/AI 생성 필드(`original_*`/`rewritten_*`)는 수정 후에도 그대로 보존.

## 7. generation_id/content_id 보존

편집 시 `generation_id`나 `content_id`를 새로 만들지 않는다 - `replace()`는
`content_id`/`generation_id` 필드를 아예 건드리지 않으므로, 코드 구조상
이 두 값이 바뀔 수 없다. `test_edit_only_touches_matching_generation_id_for_same_content_id`
테스트로, 같은 `content_id`를 가진 서로 다른 `generation_id`의 두 레코드
중 하나만 수정해도 다른 하나는 전혀 영향받지 않는다는 것을 확인했다(복합
키 조회가 정확히 동작함을 실제 파일로 검증).

## 8. Dashboard 변경

- `/media/generations` 목록의 각 카드(`_generation_pool_card_html`)에
  `[수정]` 링크를 추가했다 - `_can_review_generation_record()`가 True일
  때만(기존 승인/보류 버튼과 정확히 같은 조건) 보인다. approved/rejected
  레코드에는 이 링크 자체가 나타나지 않는다(`test_edit_link_shown_only_for_reviewable_records_in_pool_list`).
- `render_generation_pool_html()`의 notice 처리에 `"saved"`를 추가해,
  수정 저장 후 목록으로 돌아왔을 때 "수정 내용이 저장되었습니다 - 검토
  상태가 '검토대기(unreviewed)'로 돌아갔습니다" 배너를 보여준다.
- 새 화면(`render_generation_edit_html`)은 제목 input + 본문 textarea +
  저장 버튼만 있는 최소 폼이다 - 기존 `.card`/`.actions`/`.btn`/`textarea`
  스타일을 그대로 재사용했고 새 CSS를 추가하지 않았다. 대규모 UI 개편을
  하지 않았다(11장 지시대로).

## 9. Production Archive 보호

이 함수들(`handle_generation_edit_submission`, GET 편집 라우트가 쓰는
`find_generation_pool_record`)은 **production archive 경로를 인자로 아예
받지 않는다** - 시그니처 자체가 구조적으로 production archive를 건드릴 수
없다(6-08의 승인/보류 함수와 동일한 안전 패턴).

`GenerationEditRouteTests.test_edit_never_touches_production_archive`가
편집 전후 production archive 파일의 SHA-256 해시가 완전히 동일함을
확인한다(승인/보류에 이미 있던 `test_approving_generation_pool_never_touches_production_archive`와
동일한 방법론).

## 10. 혼합(mixed) Idempotency 테스트

6-09에서 남긴 테스트 공백을 `tests/test_batch_promotion.py`의
`MixedIdempotencyBatchPromotionTests`(2개 시나리오)로 메웠다. 전부 실제
`tempfile` 파일 I/O로 CLI(`promote_media_generation.main`)를 두 번 실행해
검증한다.

**시나리오 1** — A=approved, B=approved, C=unreviewed:

- 1차 execute → A+B 승격("승격 완료: 2건"), production에 A/B 각 1건.
- 2차 execute(상태 변화 없이 재실행) → 둘 다 "ALREADY PROMOTED", "promotion
  대상이 없습니다" 출력, 아무것도 다시 쓰지 않음.
- 최종 production: `{a, b}` 정확히 2건(중복 없음), C는 0건.
- `plan_batch_promotion()` 재조회로 액션 분류(`already_promoted`/
  `already_promoted`/`skip`)도 함께 고정했다.

**시나리오 2** — 1차 실행 시점엔 A만 approved(B/C는 unreviewed):

- 1차 execute → A만 승격("승격 완료: 1건").
- 1차와 2차 사이에 B를 approved로 바꾼다(Dashboard 승인과 동일한 파일
  갱신을 직접 재현).
- 2차 실행 전 `plan_batch_promotion()` 확인 → A=already_promoted,
  B=promote, C=skip.
- 2차 execute → B만 새로 승격("승격 완료: 1건").
- 최종 production: `{a, b}`, a는 여전히 정확히 1건(재승격으로 중복되지
  않음), C는 끝까지 0건.

## 11. Edit → Approve → Promotion 통합 테스트

`tests/test_generation_review_and_promotion.py`의
`EditApprovePromotionIntegrationTests`로 다음 전체 흐름을 하나의 테스트로
검증했다(4장에서 설명한 이유로 시작 상태를 approved 대신 dismissed로 삼았다):

```
dismissed record
  → HTTP POST .../edit (제목/본문 수정)
  → review_status = unreviewed (파일에서 직접 확인)
  → plan_promotion() 호출 시 PromotionError 발생 (production 파일 자체가 생성되지 않음)
  → HTTP POST .../approve
  → plan_batch_promotion() dry-run → promotion 대상 1건, 여전히 파일 미생성
  → CLI --execute
  → production archive에 1건 승격, final_title/final_body가 방금 사람이
    입력한 내용과 정확히 일치
```

이 테스트는 실제 production archive 경로를 매번 새 임시 파일로 만들어
쓰므로 `data/tak_media_archive.json`을 전혀 사용하지 않는다.

## 12. edited content promotion 검증

`tests/test_batch_promotion.py`의 `EditedContentPromotionTests`로, 11장
통합 테스트와는 별개로 "rewritten과 edited가 서로 다른 값일 때 promotion
결과가 정확히 edited를 쓰는지"만 좁게 검증했다:

- `rewritten_title="원래 제목"`, `edited_title="사람이 수정한 제목"` (본문도
  동일한 구조)인 approved record 1건을 batch execute.
- 승격된 record의 `rewritten_title`/`rewritten_body`는 그대로 "원래
  제목"/"원래 본문"으로 보존되고, `final_title`/`final_body`는 "사람이
  수정한 제목"/"사람이 수정한 본문"이다.

이 property는 `content_engine/media_archive.py`가 이미 제공하던 것을
batch promotion 경로 전체(파일 저장 → 재로딩)로 다시 한번 회귀 확인한 것뿐이고,
새로 구현한 로직은 없다.

## 13. 전체 테스트

```
$ python -m pytest -q tests/test_generation_review_and_promotion.py tests/test_batch_promotion.py tests/test_media_dashboard.py tests/test_second_knowledge_correction_and_generation_pool.py
103 passed in 28.15s   # (기능 구현 직후, regression 없음 확인)

$ python -m pytest -q
919 passed, 68 subtests passed in 143.42s (0:02:23)
```

baseline(900 passed) 대비 정확히 **+19개** 신규 테스트가 추가됐고
(`GenerationEditRouteTests` 11개 + `EditApprovePromotionIntegrationTests` 1개 +
`MixedIdempotencyBatchPromotionTests` 2개 + `EditedContentPromotionTests` 1개 +
기존 두 클래스에 추가한 나머지 - 정확한 내역은 `git diff` 참고), **0 failed**로
전부 통과했다.

## 14. 실제 9건 변경 여부

**변경하지 않았다.** 작업 종료 시점에 다시 확인:

```
$ python3 -c "..."
count: 9
review_status: Counter({'unreviewed': 9})
generation_status: Counter({'valid': 9})
any edited_title set: False
```

파일 mtime도 이번 세션 시작 이전(작업 중 어떤 코드/테스트도 이 경로를
쓰지 않음 - 전부 `tempfile.TemporaryDirectory()` fixture만 사용)과 동일하게
유지됐다.

## 15. 실제 Production promotion 여부

**실행하지 않았다.** `data/tak_media_archive.json`도 이번 세션에서 mtime이
전혀 바뀌지 않았다(=이번 작업 코드가 그 경로를 한 번도 쓰지 않았다).
`scripts/promote_media_generation.py`는 이번 작업에서 전혀 수정하지 않았고
(기존 6-09 코드 그대로), 모든 신규 테스트는 임시 production archive 파일만
사용했다.

## 16. Git 변경 파일

이번 작업에서 수정한 파일은 정확히 3개뿐이다.

```
 M scripts/run_scout_dashboard.py                | 164 ++++++++++
 M tests/test_batch_promotion.py                 | 161 ++++++++++
 M tests/test_generation_review_and_promotion.py | 424 +++++++++++++++++++++++++-
```

기존 미커밋 변경(`.gitignore`, `content_engine/*`, `data/tak_brain_knowledge.json`,
`tests/test_content_engine.py`, `tests/test_media_batch.py`, `data/tak_media_archive.json`,
그 외 다수의 untracked 문서/스크립트)은 전혀 건드리지 않았고, `git add .`/
`git add -A`를 쓰지 않고 이번에 수정한 3개 파일만 이름을 명시해 `git add`했다.

## 17. Commit

```
$ git add scripts/run_scout_dashboard.py tests/test_generation_review_and_promotion.py \
    tests/test_batch_promotion.py docs/6-10_generation_edit_and_final_review.md
$ git diff --cached --stat
 docs/6-10_generation_edit_and_final_review.md | 382 +++++++++++++++++++++++
 scripts/run_scout_dashboard.py                | 164 ++++++++++
 tests/test_batch_promotion.py                 | 161 ++++++++++
 tests/test_generation_review_and_promotion.py | 424 +++++++++++++++++++++++++-
 4 files changed, 1130 insertions(+), 1 deletion(-)

$ git commit -m "feat: add generation pool content editing" (+본문)
[main 6d8bdbb] feat: add generation pool content editing
 4 files changed, 1130 insertions(+), 1 deletion(-)
 create mode 100644 docs/6-10_generation_edit_and_final_review.md
```

**커밋 해시: `6d8bdbb`**

## 18. Push

```
$ git push
To https://github.com/sopptak/tak-auto
   370e2ce..6d8bdbb  main -> main

$ git fetch origin
$ git log origin/main..HEAD --oneline
(출력 없음 - origin/main과 완전히 동기화됨)
```

**Push 완료. origin/main과 동기화 확인됨.**

(이 보고서 자체의 최종 커밋/push 확인 기록: `4ef7da9` - 6-08/6-09와 동일한
관례로, 보고서에 실제 커밋 해시를 기록하는 후속 커밋 1건을 추가했다.)

## 19. 최종 git status

커밋 직후 `git status --short`를 실행한 결과, 2장의 시작 시점 목록과
정확히 같은 기존 미커밋(`M .gitignore`, `M content_engine/*`,
`M data/tak_brain_knowledge.json`, `M tests/test_content_engine.py`,
`M tests/test_media_batch.py`)과 untracked 문서/스크립트만 남았고, 이번에
커밋한 4개 파일(`scripts/run_scout_dashboard.py`,
`tests/test_generation_review_and_promotion.py`,
`tests/test_batch_promotion.py`,
`docs/6-10_generation_edit_and_final_review.md`)은 더 이상 목록에
나타나지 않는다 - 이번 작업에서 만든 파일만 정확히 commit됐고, 기존
미커밋 변경은 작업 시작 때와 동일하게 그대로 보존됐다.

## 20. 보안 검증

- `handle_generation_edit_submission()`/`render_generation_edit_html()`
  어디에도 `ThreadsClient`/`YouTubeClient`/`threads_publisher`/
  `youtube_publisher`/naver 관련 import가 없다(기존
  `test_dashboard_module_never_imports_external_publish_clients`가 파일
  전체의 import 구문을 검사하므로 이번 추가 코드도 그 테스트 범위 안에
  포함돼 자동으로 재확인됐다 - 여전히 통과).
- LLM 호출 코드(`InterviewLLMProvider` 등)를 이번 변경 어디에서도 새로
  호출하지 않았다 - 편집 기능은 순수 파일 읽기/쓰기(`load_archive`/
  `upsert_generation_archive`)만 한다.
- 사용자 입력(제목/본문)은 전부 `html.escape()`를 거쳐 렌더링되므로 기존
  화면들과 동일한 XSS 방어 수준을 유지한다.

## 21. 남은 문제

- Generation Pool 편집 화면에는 production `/media` 상세 화면에 있는
  "①KNOWLEDGE ~ ⑦Downstream 상태" 같은 전체 컨텍스트 섹션이 없다(11장
  지시에 따라 의도적으로 최소 폼만 구현) - 실제 9건을 검토할 때 원문/검증
  결과를 보려면 여전히 `/media/generations` 목록 카드로 돌아가야 한다.
- "approved 레코드를 곧바로 편집"하는 지시문 7장의 문자 그대로의 시나리오는
  기존 정책(승인은 종결 상태)과 충돌해 구현하지 않았다(4장에서 상세 설명) -
  만약 실제로 "승인 후에도 편집하고 싶다"는 요구가 나오면 이는 이번 6-10
  범위를 넘는 새로운 정책 결정이 필요하다.

## 22. 다음 작업 제안

- 실제 9건을 사람이 직접 검토(필요하면 이번에 만든 편집 기능으로 제목/본문
  수정) → 승인 → `scripts/promote_media_generation.py --generation-id
  gen-20260920T033856-6e8d98fb --production-archive
  data/tak_media_archive.json`으로 실제 batch dry-run/execute를 사람이
  직접 실행하는 것이 다음 단계다(이번 6-10에서는 하지 않음).
- approve-all과 마찬가지로 "이 generation 전체를 한 화면에서 편집"하는
  일괄 편집 기능은 이번 범위가 아니다 - 필요성이 확인되면 별도 작업으로.
