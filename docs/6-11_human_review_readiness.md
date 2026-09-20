# TAK AUTO 6-11 — 6-10 Git 동기화 확인 + 실제 Human Review 운영 준비

## 1. 작업 목적

6-10에서 Generation Pool 편집 기능(제목/본문 수정 + 자동 unreviewed 복귀)과
6-09의 테스트 공백(혼합 idempotency, edited content promotion)을 메웠다. 다만
6-10 보고서 마지막에 "보고서 자체의 최종 커밋/push 확인 기록: `4ef7da9`"라는
문구가 있었고, 그 이후 세션 안에서 다시 한번 후속 커밋(`97792f1`)을 만든
정황이 있어 실제 Git 상태(HEAD/origin/main 동기화 여부)를 재확인할 필요가
있었다.

이번 6-11의 목표는 두 가지다.

1. 6-10에서 언급된 커밋들의 실존 여부와 push 상태를 정확히 검증한다.
2. 실제 9건(knowledge-scout-6d1d0e2fa762 / gen-20260920T033856-6e8d98fb)을
   사람이 검토할 때 화면에 충분한 정보가 표시되는지 점검하고, 부족하면
   대규모 UI 개편 없이 최소한의 개선만 한다.

**절대 원칙(0장)**: 이번 작업에서 실제 9건에 대해 approve/approve-all/
dismiss/edit/promotion/production archive write를 전혀 수행하지 않는다.
LLM도 호출하지 않는다.

## 2. 6-10 Git 상태 불일치 검증 결과

```
$ git status --short   # (아래 4장/16장에서 전체 목록 확인 - 기존 미커밋만 남아 있음)
$ git log --oneline -10
97792f1 docs: note 6-10 report follow-up commit hash
4ef7da9 docs: record final commit/push confirmation in 6-10 report
6d8bdbb feat: add generation pool content editing
370e2ce docs: record final commit/push confirmation in 6-09 report
76009c9 feat: add batch media generation promotion
8f7086a docs: record final commit/push confirmation in 6-08 report
92a8a1f feat: add generation review and safe promotion workflow
188f13c docs: record final commit/push confirmation in 6-07 report
8acceca fix: correct second scout knowledge and generate safe media revision
08b5a1d docs: record final commit/push confirmation in 6-06 report

$ git branch --show-current
main

$ git fetch origin   # (출력 없음, 이미 최신)
$ git log origin/main..HEAD --oneline   # (출력 없음)
$ git log HEAD..origin/main --oneline   # (출력 없음)
```

`git show --stat`로 두 커밋을 직접 확인했다.

```
$ git show --stat 6d8bdbb
commit 6d8bdbb1a4e183df8903de4a3db2208076988f83
    feat: add generation pool content editing
 docs/6-10_generation_edit_and_final_review.md | 382 +++++++++++++++++++++++
 scripts/run_scout_dashboard.py                | 164 ++++++++++
 tests/test_batch_promotion.py                 | 161 ++++++++++
 tests/test_generation_review_and_promotion.py | 424 +++++++++++++++++++++++++-
 4 files changed, 1130 insertions(+), 1 deletion(-)

$ git show --stat 4ef7da9
commit 4ef7da95bb2dae641edaf4a7d4e51299d2336449
    docs: record final commit/push confirmation in 6-10 report
 docs/6-10_generation_edit_and_final_review.md | 39 ++++++++++++++++++++-------
 1 file changed, 30 insertions(+), 9 deletions(-)

$ git show --stat 97792f1
commit 97792f134480ac1cf86eba9df517dee1d4eab580
    docs: note 6-10 report follow-up commit hash
 docs/6-10_generation_edit_and_final_review.md | 3 +++
 1 file changed, 3 insertions(+)
```

**결론: 6-10 보고서가 언급한 불일치는 실재하지 않았다.**

- `4ef7da9`는 실제로 존재하며, 6-10 보고서(9~18장)를 최종 확정하는 후속
  커밋이었다.
- 그 뒤에 이미 한 커밋(`97792f1`)이 더 있었다 - 이것도 같은 보고서에 실제
  커밋 해시를 기록하는 후속 커밋으로, 6-10 세션 안에서 이미 만들고 push까지
  완료된 것이었다.
- 세 커밋(`6d8bdbb`/`4ef7da9`/`97792f1`) 모두 `origin/main`에 이미
  반영되어 있었다 - `git log origin/main..HEAD`와 `git log HEAD..origin/main`
  둘 다 출력이 없어 **완전히 동기화된 상태**였다.
- 따라서 1장 지시의 "push 누락 여부 판단" 절차(`git show --stat HEAD`,
  `git diff origin/main..HEAD --stat` 확인 후 push)는 적용 대상이 아니었다 -
  push할 것이 애초에 없었다. 새로운 push는 이 단계에서 하지 않았다.

## 3. HEAD / origin/main 상태

작업 시작 시점 기준:

```
HEAD:        97792f1
origin/main: 97792f1
origin/main..HEAD:  (없음)
HEAD..origin/main:  (없음)
```

완전히 동기화됨을 확인했다.

## 4. 테스트 baseline

```
$ python -m pytest -q
919 passed, 68 subtests passed in 143.99s (0:02:23)
```

지시받은 baseline(919 passed / 68 subtests / 0 failed)과 정확히 일치했다.

## 5. Generation Pool 무결성

```
$ sha256sum data/tak_media_generation_6-07_knowledge-scout-6d1d0e2fa762.json
ed6aa24461f40880489a9e88107cc253036316a2ef95dd1911f1af5a69676e9e

$ stat -c '%Y %y' data/tak_media_generation_6-07_knowledge-scout-6d1d0e2fa762.json
1789875536 2026-09-20 03:38:56.953478311 +0000
```

파이썬으로 내용 확인:

```
count: 9
knowledge_ids: {'knowledge-scout-6d1d0e2fa762'}
generation_ids: {'gen-20260920T033856-6e8d98fb'}
generation_status: Counter({'valid': 9})
review_status: Counter({'unreviewed': 9})
platform: Counter({'threads': 5, 'shorts': 3, 'blog': 1})
edited_title set: 0
edited_body set: 0
```

지시받은 모든 조건(9건 · knowledge_id 동일 · generation_id 동일 · valid 9 ·
unreviewed 9 · edited_title/edited_body 없음)을 만족했다. 이 작업에서는 이
파일을 한 번도 쓰지 않았고, 작업 종료 시점에 SHA-256/mtime을 다시 측정해
**완전히 동일함**을 재확인했다(17장).

## 6. Production Archive 무결성

```
$ sha256sum data/tak_media_archive.json
823ba83930116cb3bf0cf9d46bd3876c7a833c58f5871a380a5de0cad3dd1662

$ stat -c '%Y %y' data/tak_media_archive.json
1789867628 2026-09-20 01:27:08.445167898 +0000

record count: 9
```

이번 작업에서 이 파일을 한 번도 쓰지 않았다 - Generation Pool 검토 준비
기능(`load_knowledge_titles` 등, 10장)은 production archive 경로를 아예
인자로 받지 않는다. 작업 종료 시점 재측정 결과 SHA-256/mtime 모두
**완전히 동일**했다(17장).

## 7. Human Review 화면 점검

코드 수준에서 다음 라우트를 다시 확인했다(`scripts/run_scout_dashboard.py`).

- `GET /media/generations`, `GET /media/generations/<knowledge_id>` -
  `render_generation_pool_html()`이 각 record를 카드로 렌더링.
- `GET /media/generations/record/<content_id>/<generation_id>/edit` -
  `render_generation_edit_html()`(6-10에서 추가).
- `POST /media/generations/record/<content_id>/<generation_id>/edit` -
  `handle_generation_edit_submission()`.
- `POST /media/generations/record/<content_id>/<generation_id>/approve|dismiss` -
  `handle_generation_review_submission()`.
- `POST /media/generations/generation/<generation_id>/approve-all` -
  `handle_generation_approve_all_submission()`.

상태별 버튼 가시성(`_can_review_generation_record()` 기준, `generation_status
== "valid" and review_status != "approved"`)을 다시 추적했다:

| 상태 | 수정 버튼 | 승인 버튼 | 보류 버튼 |
| --- | --- | --- | --- |
| valid + unreviewed | 보임 | 보임 | 보임 |
| valid + dismissed | 보임 | 보임 | 보임 |
| valid + approved | **없음** | **없음** | **없음** |
| rejected/error (generation_status) | **없음** | **없음** | **없음** |

기존 6-08/6-10 테스트(`DashboardApprovalRouteTests`,
`GenerationEditRouteTests`)가 이미 이 표를 실제 HTTP 응답으로 검증하고
있었고, 이번에 다시 실행해도 그대로 통과했다 - 코드 변경 없이 기존 동작이
맞다는 것만 재확인했다.

## 8. Source URL 확인

`MediaArchiveRecord.source_url`은 generation pool record 각각에 이미
저장돼 있고(`_record()`/실제 9건 모두 필드 존재), `_generation_pool_card_html()`가
이를 `<a href="..." target="_blank" rel="noopener">`로 렌더링해 **클릭
가능한 링크**로 이미 보여주고 있었다. 다만 라벨이 영어 "source:"였는데,
Dashboard의 다른 모든 화면(`/media` 상세 등)은 "출처:"라는 한국어 라벨을
쓰고 있어 통일성이 없었다.

**작은 개선(7장 허용 범위 내)**: `_generation_pool_card_html()`의 라벨을
"source:" → "출처:"로 바꿨다(`scripts/run_scout_dashboard.py`). source_url
값 자체나 링크 구조는 전혀 바꾸지 않았다 - 텍스트 라벨 1곳만 수정.

## 9. KNOWLEDGE 연결 확인

`data/tak_brain_knowledge.json`은 이미 `id`로 조회 가능한 구조이고
(`tak_brain.load_knowledge_records()`, production `/media` 상세 화면이
이미 같은 방식으로 조회하고 있었다), generation pool record의
`knowledge_id`로 그대로 매칭할 수 있는 구조였다.

다만 기존 Generation Pool 화면(`/media/generations`)의 그룹 헤더는
"KNOWLEDGE: {knowledge_id}"만 보여주고 있었다 - **제목은 표시되지
않았다**. 사람이 어떤 기사에서 나온 MEDIA인지 ID만 보고 즉시 알기 어려운
문제였다.

**작은 개선(8장 지시대로 최소한만)**: `load_knowledge_titles(knowledge_path)`
함수를 새로 추가해(`knowledge_id -> title` 매핑, 읽기 전용) `/media/generations`
GET 라우트에서 호출하고, `render_generation_pool_html()` → `_generation_group_html()`에
넘겨 그룹 헤더를 "KNOWLEDGE: {제목} ({knowledge_id})" 형태로 바꿨다. 제목을
찾지 못하면(캐시를 안 넘겼거나 해당 KNOWLEDGE가 없으면) 기존처럼
knowledge_id만 보여주도록 fallback을 유지했다 - 기존 호출부/테스트와
100% 하위 호환(모든 매개변수가 기본값 `None`).

대규모 상세 페이지(KNOWLEDGE 원문 전체 표시 등)는 만들지 않았다 - 제목
한 줄만 추가했다.

## 10. UI 변경 사항

`scripts/run_scout_dashboard.py`에 정확히 3가지 변경만 했다.

1. `load_knowledge_titles(knowledge_path) -> dict[str, str]` 신규 함수
   (읽기 전용, `load_knowledge_records()` 재사용).
2. `_generation_group_header_label()` 신규 헬퍼 + `_generation_group_html()`/
   `render_generation_pool_html()`에 `knowledge_titles` 선택적 매개변수 추가 -
   그룹 헤더에 "KNOWLEDGE: {제목} ({id})" 표시(제목 없으면 id만, 기존과
   동일).
3. `_generation_pool_card_html()`의 "source:" 라벨을 "출처:"로 변경.

두 GET 라우트(`/media/generations`, `/media/generations/<knowledge_id>`)에서
`load_knowledge_titles(config.knowledge_path)`를 호출해 위 함수들에
넘기도록 라우트 코드도 함께 수정했다. 그 외 라우트/HTML 구조는 전혀
바꾸지 않았다 - 대규모 UI 개편이나 새 CSS/JS를 추가하지 않았다.

evidence(SOURCE FACT 목록) 표시는 이번에 추가하지 않았다 - production
`/media` 상세 화면도 이 필드를 표시하지 않는 기존 관례였고(20장 참고),
"대규모 UI 개편 금지" 지시에 따라 이번 범위에 포함하지 않았다.

## 11. 테스트 결과

12장 A~F를 `tests/test_generation_review_and_promotion.py`의
`GenerationPoolReviewContextTests`(9개 테스트)로 고정했다.

- **A**. `/media/generations`가 200으로 정상 렌더링되고 두 record의
  content_id가 모두 보인다.
- **B**. reviewable(valid+unreviewed) record에 `/edit` 링크가 보인다.
- **C**. approved record에는 `/edit` 링크가 없다.
- **D**. source URL이 "출처:" 라벨과 함께 `<a href=... target="_blank"
  rel="noopener">` 클릭 가능한 링크로 렌더링된다(값 자체는 그대로).
- **E**. KNOWLEDGE 제목이 그룹 헤더에 표시된다(2개 테스트: 정상 표시 +
  매핑에 없을 때 knowledge_id로 안전하게 fallback) + `load_knowledge_titles()`
  단위 테스트 1개.
- **F**. 이 화면의 GET 요청 3종(목록/knowledge_id 필터/edit 폼)이
  production archive 파일 해시를 전혀 바꾸지 않는다.

**G**(실제 9건 파일을 테스트가 변경하지 않음)는
`tests/test_second_knowledge_correction_and_generation_pool.py`의
`RealGenerationPoolResultTests`에 2개 테스트를 추가해 고정했다 - 실제
generation pool 파일과 production archive 파일의 SHA-256 해시가 테스트
실행 전후 동일함을 직접 확인한다(이 클래스의 다른 모든 테스트도
`load_archive()`만 호출하고 저장 함수를 import조차 하지 않는다는 사실과
함께). 같은 파일에 `load_knowledge_titles()`가 실제 대상 knowledge_id에
대해 올바른 제목을 반환하는지 확인하는 회귀 테스트도 1개 추가했다(읽기
전용).

```
$ python -m pytest -q tests/test_generation_review_and_promotion.py \
    tests/test_second_knowledge_correction_and_generation_pool.py \
    tests/test_batch_promotion.py tests/test_media_dashboard.py
133 passed in 40.33s

$ python -m pytest -q
930 passed, 68 subtests passed in 147.98s (0:02:27)
```

baseline(919 passed) 대비 정확히 **+11개** 신규 테스트가 추가됐고
(`GenerationPoolReviewContextTests` 9개 +
`RealGenerationPoolResultTests` 신규 2개), **0 failed**로 전부 통과했다.

## 12. 실제 9건 변경 여부

**변경하지 않았다.** 5장에서 측정한 SHA-256(`ed6aa244...`)/mtime
(`1789875536`)이 작업 종료 시점에도 정확히 동일했다.

```
review_status: unreviewed = 9 (변경 없음)
edited_title/edited_body: 0건 (변경 없음)
```

## 13. 실제 승인 여부

**하지 않았다.** approve/approve-all/dismiss를 실제 9건에 대해 한 번도
호출하지 않았다 - 이번 세션에서 실행한 모든 승인/보류/편집 HTTP 요청은
`tempfile.TemporaryDirectory()` 안의 fixture 파일만 대상으로 했다.

## 14. 실제 Promotion 여부

**실행하지 않았다.** `scripts/promote_media_generation.py`를 이번 세션에서
`--execute`나 `--production-archive data/tak_media_archive.json`으로
실행한 적이 없다. 6장에서 측정한 production archive의 SHA-256
(`823ba839...`)/mtime(`1789867628`)이 작업 종료 시점에도 정확히 동일했다.

## 15. LLM 호출 여부

**호출하지 않았다.** 이번 작업은 코드 읽기/검증 + 정적 텍스트 라벨/조회
함수 추가뿐이었고, `InterviewLLMProvider`/`OpenAICompatibleRewriteProvider`
등 어떤 LLM 클라이언트도 import하거나 호출하지 않았다. regenerate/
rewrite/automatic correction/automatic approval/automatic dismissal 중
어느 것도 수행하지 않았다.

## 16. Git 변경 파일

```
 M scripts/run_scout_dashboard.py                     |  54 +++++-
 M tests/test_generation_review_and_promotion.py      | 196 +++++++++++++++++++++
 M tests/test_second_knowledge_correction_and_generation_pool.py | 40 ++++-
```

`docs/6-11_human_review_readiness.md`(이 보고서, 신규)도 함께 commit
대상이다. 기존 미커밋 변경(`.gitignore`, `content_engine/*`,
`data/tak_brain_knowledge.json`, `tests/test_content_engine.py`,
`tests/test_media_batch.py`, `data/tak_media_archive.json`, 그 외 다수의
untracked 문서/스크립트)은 전혀 건드리지 않았다 - `git add .`/`git add -A`를
쓰지 않고 이번에 수정한 파일 이름을 전부 명시해 `git add`했다.

## 17. Commit

Git 동기화 자체는 확인만 하고 추가 조치가 필요 없었지만(2장), 실제로
코드(Human Review 정보 표시 개선)와 테스트를 수정했으므로 15장 지시에
따라 commit을 진행했다.

```
$ git add scripts/run_scout_dashboard.py \
    tests/test_generation_review_and_promotion.py \
    tests/test_second_knowledge_correction_and_generation_pool.py \
    docs/6-11_human_review_readiness.md
$ git diff --cached --stat
 docs/6-11_human_review_readiness.md                | 386 +++++++++++++++++++++
 scripts/run_scout_dashboard.py                     |  54 ++-
 tests/test_generation_review_and_promotion.py      | 196 +++++++++++
 tests/test_second_knowledge_correction_and_generation_pool.py |  40 ++-
 4 files changed, 669 insertions(+), 7 deletions(-)

$ git commit -m "feat: improve generation review context" (+본문)
[main 250076f] feat: improve generation review context
 4 files changed, 669 insertions(+), 7 deletions(-)
 create mode 100644 docs/6-11_human_review_readiness.md
```

**커밋 해시: `250076f`**

## 18. Push

```
$ git push
To https://github.com/sopptak/tak-auto
   97792f1..250076f  main -> main

$ git fetch origin
$ git log origin/main..HEAD --oneline
(출력 없음)
$ git log HEAD..origin/main --oneline
(출력 없음)
```

**Push 완료. origin/main과 완전히 동기화됨(양방향 모두 비어 있음).**

## 19. 최종 git status

커밋/push 직후 `git status --short`를 실행한 결과, 시작 시점(2장)과
정확히 같은 기존 미커밋(`M .gitignore`, `M content_engine/*`,
`M data/tak_brain_knowledge.json`, `M tests/test_content_engine.py`,
`M tests/test_media_batch.py`)과 untracked 문서/스크립트만 남았고, 이번에
커밋한 4개 파일(`scripts/run_scout_dashboard.py`,
`tests/test_generation_review_and_promotion.py`,
`tests/test_second_knowledge_correction_and_generation_pool.py`,
`docs/6-11_human_review_readiness.md`)은 더 이상 목록에 나타나지 않는다 -
이번 작업에서 만든/수정한 파일만 정확히 commit됐고, 기존 미커밋 변경은
작업 시작 때와 동일하게 그대로 보존됐다.

## 20. 남은 문제

- Generation Pool 카드에는 여전히 `evidence`(SOURCE FACT 목록)가 표시되지
  않는다 - production `/media` 상세 화면도 이 필드를 노출하지 않는 기존
  관례라 이번에 새로 추가하지 않았다. 실제로 사람이 "이 콘텐츠가 어떤
  근거에서 나왔는지"까지 봐야 한다면 원문(source URL)을 열어 직접 확인해야
  한다.
- KNOWLEDGE 제목 표시는 그룹 헤더 1곳에만 추가했다 - 개별 record 카드에는
  아직 없다(그룹 헤더가 이미 그 그룹 전체의 KNOWLEDGE를 나타내므로 카드마다
  중복 표시하지 않았다).
- 6-10 보고서의 "불일치 가능성" 우려는 실제로는 근거가 없었다(2장) - 다음부터는
  후속 "commit/push confirmation" 커밋을 만들 때, 그 커밋의 실제 해시를
  보고서에 기록하는 시점과 실제 커밋 시점 사이의 순서를 더 명확히 문서화하면
  이런 혼동을 줄일 수 있다.

## 21. 다음 단계

- 실제 9건을 사람이 이 화면(`/media/generations`)에서 직접 검토 - 필요하면
  6-10에서 만든 편집 기능으로 제목/본문을 고치고, 승인 후
  `scripts/promote_media_generation.py`로 batch dry-run → execute까지
  사람이 직접 진행하는 것이 다음 단계다(이번 6-11에서도 하지 않음).
- evidence 표시가 실제로 필요하다고 판단되면, production `/media` 상세
  화면과 Generation Pool 화면 양쪽에 동시에 추가하는 별도 작업으로 진행하는
  것을 권장한다(한쪽만 바꾸면 두 화면의 정보 표시 방식이 갈라진다).
