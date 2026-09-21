# 6-14 Publish Readiness & Operation Report

## 1. 작업 목적

6-12에서 실제 Promotion을 처음 끝까지 실행했고, 6-13에서 게시 상태 구조(승인 ≠
게시)를 Blog/Threads/Shorts 세 플랫폼 모두 일관되게 정리했다. 이번 6-14는
그 위에서 "사람이 `/media`, `/media/generations`를 열어 콘텐츠를 하나씩 확인
하지 않아도 되는 구조"를 만드는 작업이다. 구체적으로:

- 6-13에서 발견한 승인 게이트 우회 가능성(`generate_blog_publish_pack.py`를
  `--from-archive` 없이 실행하면 콘텐츠 단위 검수 없이 Pack이 만들어지는 문제)을
  실제로 막고,
- Production Archive 전체를 자동으로 점검해 READY/NEEDS_HUMAN_REVIEW/BLOCKED/
  ALREADY_PUBLISHED/ERROR로 분류하는 감사(audit) 도구와, 그 결과를 사람이 링크를
  열지 않고도 읽을 수 있는 Markdown 보고서를 만들고,
- 이미 존재하는 Publish Pack 기능(Blog/Shorts)을 실제로 한 번 실행해 승인된
  콘텐츠의 게시 준비 상태를 실제로 진전시키고,
- Dashboard에 같은 감사 결과를 읽기 전용으로 보여주는 화면(`/publish-readiness`)을
  추가해 "최종 확인용 화면"이라는 역할을 명확히 하는 것

이 목적이다. 이번 세션도 실제 외부 플랫폼(Naver/Threads/YouTube)에는 아무것도
게시하지 않았다 - 실행한 명령은 전부 읽기 전용 조사, 로컬 파일만 만드는 Pack
생성, 또는 이미 게시된 것을 대상으로 한 안전한 dry-run이었다.

## 2. 작업 전 상태

- branch `main`, HEAD `2e0c283`(6-13 report follow-up commit), `origin/main`과
  완전히 동기화된 상태로 세션을 시작했다.
- `git status --short`: 6-13 종료 시점과 정확히 같은 기존 미커밋 목록
  (`.gitignore`, `content_engine/__init__.py`, `content_engine/generator.py`,
  `content_engine/llm_provider.py`, `content_engine/rewrite.py`,
  `data/tak_brain_knowledge.json`, `data/tak_threads_pending.json`,
  `tests/test_content_engine.py`, `tests/test_media_batch.py`)과 다수의
  untracked 문서/스크립트만 있었다.
- 기존 전체 테스트: `python -m pytest -q` → **939 passed, 68 subtests passed,
  0 failed**(6-13이 남긴 상태 그대로).
- Production Archive(`data/tak_media_archive.json`) 실측: **18건**
  (platform: threads 10 · shorts 6 · blog 2, review_status: approved 16 ·
  unreviewed 2, generation_status: valid 16 · rejected 2, knowledge_id:
  `knowledge-scout-b28b782b2a33` 9건 · `knowledge-scout-6d1d0e2fa762` 9건).
- 핵심 데이터 파일 해시가 6-13 보고서가 마지막에 기록한 값과 **전부 정확히
  일치**했다(3장) - 6-13 종료 이후 이번 세션 시작까지 어떤 파일도 바뀌지 않았다.
- KNOWLEDGE 28건(approved 6 / pending 13 / rejected 9), Threads pending 5건
  (pending 4 / approved 1), Threads publish log 7건, YouTube publish log
  1건, Blog publish log 없음(한 건도 게시된 적 없음), Shorts Script 파일
  2건(+예시 1건).
- `.github/workflows/`: `daily-scout.yml`, `daily-media-prepare.yml`
  (schedule 활성), `daily-threads-post.yml`(schedule 비활성, workflow_dispatch
  전용), `publish-approved-threads.yml`(workflow_dispatch 전용),
  `youtube-shorts-upload.yml`(workflow_dispatch 전용, scaffold) - 6-13에서
  확인한 것과 동일. 어떤 workflow도 실제 외부 게시를 schedule로 자동
  실행하지 않는다(6-13 3장 재확인, 이번 세션에서 다시 코드로 검증).

## 3. 6-13 결과 확인

- 6-13이 추가한 YouTube 업로드 중복 방지(`YouTubeUploadHistory.
  published_content_ids()`/`is_published()`), `/media` downstream 상태의
  "YouTube 업로드됨" 표시가 코드에 그대로 남아 있음을 확인했다(`git log`,
  실제 파일 diff 없이 존재만 재확인).
- 6-13이 6-06/6-07 회귀 테스트 6건을 수정한 내용(legacy 부분집합 기준으로
  범위를 좁힌 것)도 여전히 유효했다 - 이번 세션 시작 시점 전체 테스트가
  0 failed였다는 사실 자체가 그 재확인이다.
- 6-13 보고서 14장이 남긴 MEDIUM 1번 문제("`generate_blog_publish_pack.py`를
  `--from-archive` 없이 실행하면 콘텐츠 단위 승인 없이 Pack이 만들어질 수
  있다")를 이번 세션 4장에서 실제로 해결했다.

## 4. 승인 게이트 개선

`scripts/generate_blog_publish_pack.py`에 `--generate-without-review` 플래그를
새로 추가하고, `--from-archive`도 `--generate-without-review`도 주지 않으면
**LLM을 호출하기 전에** 실행 자체를 거부하도록 바꿨다.

```
$ python3 scripts/generate_blog_publish_pack.py --knowledge data/tak_brain_knowledge.json
오류: --from-archive 없이 실행하면 콘텐츠 단위 Human Review (review_status==approved)
없이 Blog Publishing Pack이 만들어집니다. 안전을 위해 이 실행을 거부합니다.
  권장: --from-archive를 사용해 이미 /media에서 승인된 항목만으로 Pack을 만드세요.
  예전 방식(승인 KNOWLEDGE 전체에서 바로 TAK MEDIA를 새로 실행)을 정말 원하면
  --generate-without-review를 명시적으로 추가하세요.
(종료 코드 1)
```

설계 판단:

- 6-13 지시가 예로 든 세 가지 옵션(`--from-archive`를 기본값으로 바꾸기 /
  게이트 없는 실행을 명시적으로 차단하기 / 실행 자체를 안전하게 제한하기)
  중 **차단 + 명시적 opt-in**을 선택했다. `--from-archive`의 기본값을 바로
  `True`로 바꾸는 대신 "선택을 강제"하는 쪽을 고른 이유: `--from-archive`
  모드와 예전(비-archive) 모드는 완전히 다른 동작(하나는 LLM을 호출하지
  않고 이미 있는 archive만 읽고, 다른 하나는 실제로 LLM을 호출해 새
  배치를 생성한다)이라, 암묵적으로 기본값만 바꾸면 "왜 LLM을 호출하는 줄
  알았는데 archive만 읽지?"라는 정반대의 혼란이 생길 수 있다고 판단했다.
  반면 "둘 다 안 주면 거부"는 어떤 경우에도 사용자의 의도를 추측하지 않는다.
- `content_engine.blog_publish_pack.build_blog_publish_pack()`(예전 모드가
  내부적으로 쓰는 함수) 자체와 `--from-archive` 모드는 단 한 줄도 바꾸지
  않았다 - 이 함수를 직접 테스트하는 `tests/test_blog_publish_pack.py`의
  기존 테스트는 전부 그대로 통과한다(CLI의 "아무 플래그도 없는 기본 실행"만
  안전한 쪽으로 바뀌었을 뿐이다).
- 실제 자동화 워크플로(`scripts/prepare_approved_media.py` →
  `.github/workflows/daily-media-prepare.yml`)는 이미 `--from-archive`만
  명시적으로 써왔으므로 이번 변경으로 전혀 영향받지 않는다(코드/테스트로
  재확인, 5장).

발견/수정한 부수 문제: 기존 `tests/test_blog_publish_pack.py`의
`GenerateBlogPublishPackIdFilterTests` 클래스(3개 테스트)가 정확히 이
"예전 모드"를 `--id` 필터와 함께 검증하고 있었다 - 이 클래스의 헬퍼가
`--generate-without-review`를 명시적으로 추가하도록 수정했다(테스트가
검증하려던 내용은 전혀 바뀌지 않았다 - 그 모드를 켜는 방법만 바뀌었다).
새로 `GenerateBlogPublishPackReviewGateTests`(4개 테스트)를 추가해 게이트
자체(아무 플래그 없으면 거부/거부 시 LLM 호출 안 함/두 플래그 각각으로
정상 진행)를 직접 검증했다.

## 5. Publish Readiness 자동 점검

새 순수 로직 모듈 `content_engine/publish_audit.py`와 CLI
`scripts/audit_publish_candidates.py`를 추가했다. 새 저장소나 새로운 승인
개념은 만들지 않았다 - 전부 기존 구조(`MediaArchiveRecord.review_status`,
`PublishHistory`, `ThreadsPendingDraft`, `YouTubeUploadHistory`, ShortsScript
파일 존재 여부, `content_engine.blog_publish_pack.is_review_required()`)를
읽기만 해서 판정한다.

분류 5가지와 판정 우선순위(코드 그대로):

1. **ERROR** - 같은 `content_id`가 production archive에 두 번 이상 있는
   구조적 이상(정상 운영에서는 `upsert_archive()`의 단독 키 upsert가 막지만
   방어적으로 확인).
2. **ALREADY_PUBLISHED** - 채널별 실제 게시 이력(Blog: `PublishHistory`,
   Threads: `PublishHistory` 또는 `ThreadsPendingDraft.status=="published"`,
   Shorts: `YouTubeUploadHistory`)에 이미 있음. 승인/보류 상태와 무관하게
   가장 먼저 확인한다.
3. **BLOCKED** - `generation_status!=valid`, `review_status!=approved`,
   제목/본문/`source_url` 누락, Shorts인데 ShortsScript 파일 없음 중 하나라도
   해당하면(여러 개면 전부 나열).
4. **NEEDS_HUMAN_REVIEW** - 위 조건을 전부 통과했지만(=승인됨, 필수 필드
   있음, 아직 게시 안 됨) `is_review_required()`가 True인 금융/부동산/대출
   민감 콘텐츠. **이 모듈은 이 판정을 새로 만들지 않았다** - 5-10부터 있던
   Blog Pack의 `review_required` 개념을 세 플랫폼 전체에 재사용한 것뿐이다.
5. **READY** - 그 외 전부.

절대 원칙(6-14 지시 3장)을 코드로 강제한다: `review_status != "approved"`인
레코드는 이 모듈의 어떤 판정 경로를 거쳐도 `READY`가 될 수 없다(BLOCKED에서
먼저 걸린다). 이 모듈은 `review_status`를 읽기만 하고 절대 쓰지 않는다.

CLI는 요약을 터미널에 짧게 출력하고(READY/NEEDS_HUMAN_REVIEW/ERROR 목록만 -
BLOCKED는 상세 이유가 많아 터미널에는 개수만, 전체 목록은 보고서 파일에만
쓴다), `docs/publish_readiness_latest.md`에 상세 Markdown 보고서를 저장한다
(6장에서 실제 실행 결과 전문을 수록).

```
$ python3 scripts/audit_publish_candidates.py --no-report
=== Publish Readiness 요약 ===
전체 Production 콘텐츠: 18
게시 가능(READY): 0
사람 검토 필요(NEEDS_HUMAN_REVIEW): 13
게시 차단(BLOCKED): 5
이미 게시됨(ALREADY_PUBLISHED): 0
오류(ERROR): 0
```

(이 결과는 7장에서 설명하는 Shorts Script 생성 **이전** 값이다 - BLOCKED 5건
중 3건은 승인된 Shorts인데 아직 ShortsScript 파일이 없어서였다.)

## 6. 자동 게시 후보 산출

6-14 지시 6장의 원칙("Claude가 임의로 좋은 콘텐츠를 선택하지 않는다 - 객관적
조건만 사용하고, 여러 개면 전부 보여준다")을 그대로 구현했다. `audit_archive()`는
콘텐츠 간 우선순위를 매기지 않는다 - 원본 archive 순서를 그대로 보존하고
(`test_audit_archive_preserves_input_order`), Dashboard 화면(`/publish-readiness`,
11장)에서도 "지금 사람이 봐야 하는 것(READY/NEEDS_HUMAN_REVIEW/ERROR)을 위로,
같은 상태 안에서는 원래 순서 그대로"만 적용하고 그 외의 점수/랭킹은 전혀
매기지 않는다.

실제 데이터에서 "게시 가능 후보"(READY)는 이번 세션 내내 **0건**이었다 -
production archive의 승인된 16건이 전부 `knowledge-scout-6d1d0e2fa762`
(category=="금융") 소속이라 `is_review_required()`가 True로 판정되어
NEEDS_HUMAN_REVIEW로 분류됐기 때문이다(이 모듈이 임의로 만든 결과가 아니라,
기존 5-10 판정 기준을 그대로 적용한 정직한 결과다 - 실제로 이 KNOWLEDGE는
AI 관련 의견 콘텐츠지만 category 필드가 "금융"으로 태깅돼 있어 안전한 쪽으로
분류된다).

## 7. Blog Publish Pack

기존 `content_engine.blog_publish_pack.build_blog_publish_pack_from_archive()`
+ `scripts/generate_blog_publish_pack.py --from-archive`를 그대로 재사용했다
(새로 만들지 않음). 실제로 실행했다:

```
$ python3 scripts/prepare_approved_media.py
=== 1/3: Blog Publishing Pack 준비 (--from-archive) ===
[--from-archive] Blog Publishing Pack 생성 완료: 2건 (사람 확인 필요 2건)
→ data/blog_publish_pack_daily.md
```

승인된 Blog 2건(legacy 1 + promoted 1) 모두 `review_required` 경고가 표시된
Pack이 만들어졌다. `data/blog_publish_pack_daily.md`는 `.gitignore`에 등록된
휘발성 파일이라(매 실행마다 새로 덮어씀) git에는 잡히지 않는다 - 이번 실행도
git 상태에 아무 흔적을 남기지 않았다.

## 8. Threads Publish Pack

Threads는 "Pack 생성" 단계가 따로 없다 - 승인 시점(`/media`에서 사람이
approve)에 이미 `content_engine.threads_review.upsert_pending()`으로
`data/tak_threads_pending.json`에 자동 연결된다(5-29 설계, 6-13에서 재확인,
이번 세션도 코드를 바꾸지 않았다). `scripts/prepare_approved_media.py`
실행 결과:

```
=== 3/3: Threads pending 현황 (읽기 전용) ===
[Threads] 현재 상태: approved 1건, pending 4건 (총 5건)
```

## 9. Shorts / YouTube Publish Pack

기존 `content_engine.shorts_adapter.save_approved_shorts_script()` +
`scripts/generate_approved_shorts_script.py`를 재사용했다. 실행 결과:

```
=== 2/3: Shorts ShortsScript 준비 ===
대상: 5건
건너뜀(이미 존재): content-e787c9201b94a948.json
건너뜀(이미 존재): content-3ae2d78568210164.json
저장 완료: content-ec0c38b9a20c424c.json
저장 완료: content-e3b8d986ea6db98e.json
저장 완료: content-91869ed8be17f3f3.json
완료: 신규 저장 3건, 이미 존재해 건너뜀 2건
```

승인된 Shorts 6건 중 legacy 2건은 이미 예전 세션에서 생성돼 있었고(idempotent
- 다시 쓰지 않음), 이번 6-12 promotion으로 새로 승인된 3건은 이번 세션에서
처음 실제로 ShortsScript 파일이 만들어졌다. 실행 전후 Publish Readiness
재점검으로 효과를 직접 확인했다:

| | 실행 전 | 실행 후 |
| --- | --- | --- |
| BLOCKED(Shorts, missing script) | 3건 | 0건 |
| NEEDS_HUMAN_REVIEW | 13건 | 16건 |
| BLOCKED(전체) | 5건 | 2건 |

남은 BLOCKED 2건은 전부 legacy KNOWLEDGE(`knowledge-scout-b28b782b2a33`)의
`generation_status=="rejected"`(검증 실패) + `review_status=="unreviewed"`
레코드다 - 사람이 `/media`에서 승인해도 `generation_status`가 `rejected`인
이상 이 도구가 절대 READY/NEEDS_HUMAN_REVIEW로 올리지 않는다(검증 실패
콘텐츠를 게시 후보로 올리는 것은 안전 원칙 위반이라고 판단해 그대로 뒀다).

MP4 렌더링/YouTube 업로드는 이번 세션에서 실행하지 않았다(6-14 지시 0장:
실제 외부 게시는 사용자 승인 없이 하지 않는다 - MP4 렌더링 자체는
외부 게시가 아니지만, 비용/시간이 크고 사람이 별도로 결정할 단계라는 기존
5-29 설계 원칙을 그대로 따랐다).

## 10. 게시 상태 확인 구조

6-13이 만든 `compute_media_downstream_status()`(개별 레코드 1건의 상태)와
이번 세션이 만든 `audit_archive()`(전체 배치 일괄 분류 + BLOCKED/ERROR까지
포함한 더 세밀한 이유)는 서로 다른 목적의 별개 함수이지만 **같은 원본
데이터**(review_status, PublishHistory, ThreadsPendingDraft, YouTubeUploadHistory,
ShortsScript 파일 존재 여부)만 읽는다 - 결과가 서로 모순될 수 없는 구조다.

게시가 실제로 실행된 뒤 확인하는 절차는 이미 존재하는 이력 파일을 다시
읽기만 하면 된다(새 코드 불필요):

- Blog: `PublishHistory(blog_publish_log.json).is_published(content_id)`
- Threads: `PublishHistory(threads_publish_log.json)` 또는
  `ThreadsPendingDraft.status`(`published`/`failed`, `failure_reason` 보존)
- YouTube: `YouTubeUploadHistory(youtube_publish_log.json).is_published(content_id)`

`scripts/audit_publish_candidates.py`를 게시 직후 다시 실행하면 해당
`content_id`가 자동으로 `ALREADY_PUBLISHED`로 넘어가는 것을 즉시 확인할 수
있다 - "게시 후 자동 확인"이 곧 "감사 도구를 다시 실행하는 것"이다(6-14
지시 9장을 만족하기 위해 별도 확인 스크립트를 새로 만들지 않았다 - 중복
구현을 피했다).

## 11. Dashboard 개선

새 읽기 전용 라우트 `GET /publish-readiness`를 추가했다
(`scripts/run_scout_dashboard.py`). `content_engine.publish_audit.audit_archive()`를
그대로 호출해 요청마다 최신 데이터로 다시 계산한다(캐시 없음 - 저장된
`docs/publish_readiness_latest.md`와는 별개 경로). 이 화면은:

- 승인/보류/게시/수정 폼이 **전혀 없다**(`test_page_has_no_approve_or_publish_forms`로
  검증) - 순수하게 "지금 상태를 보여주기만" 한다.
- READY/NEEDS_HUMAN_REVIEW/ERROR를 먼저 보여주고 BLOCKED/ALREADY_PUBLISHED를
  뒤로 보낸다(6장에서 설명한 것과 동일한 "임의 순위 없음" 원칙 - 같은 상태
  안에서는 원래 순서 유지).
- 각 카드의 "상세보기" 링크는 기존 `/media/{content_id}` 상세 화면으로
  연결된다(ERROR로 분류된 경우 content_id가 중복이라 어느 레코드를
  가리켜야 할지 확정할 수 없으므로 링크 대신 안내 문구만 표시).
- 홈(SCOUT Dashboard) 화면의 상단 nav-links에 "✅ Publish Readiness" 링크를
  추가해 다른 화면들과 동일하게 접근할 수 있게 했다.

기존 `/media`, `/media/generations`의 승인/보류/수정 기능은 전혀 건드리지
않았다 - "Dashboard를 없애지 않는다, 역할만 재정의한다"는 6-14 지시 11장을
그대로 따라, `/publish-readiness`가 먼저 전체를 훑어 보여주고, 사람이 실제
행동(승인/보류/수정)이 필요할 때만 기존 `/media` 상세로 넘어가는 구조가
됐다.

## 12. 성과 데이터 연결 준비

6-13에서 이미 조사한 `content_engine/performance/`, `scripts/
collect_performance.py`의 구조를 다시 확인했다 - 변경 사항 없음(6-01에서
완성, 6-13에서 조사, 이번 세션은 그 결론을 재확인만 했다):

- `PerformanceRecord`/`append_snapshot()`(시계열, content_id+수집시각 기준
  idempotent) 등 저장 계층은 이미 완성돼 있다.
- `scripts/collect_performance.py`는 `--dry-run`/`--confirm-live`/
  `GITHUB_ACTIONS` 3중 안전장치가 있지만, 이를 호출하는 GitHub Actions
  workflow가 **하나도 없다**(스크립트 자체 docstring이 명시) - 성과 데이터가
  쌓이려면 여전히 사람이 CLI를 수동 실행해야 한다.

"게시 완료 → publish log → 성과 수집 대상"이라는 연결은 이미 자연스럽게
성립한다: `content_id`가 서로 다른 목적의 모든 저장소(archive, publish
history, performance record)를 관통하는 유일한 조인 키이기 때문이다(5-27
설계 이후 일관). 이번 세션은 이 연결 자체를 검증만 했고, 실제 API 연동이나
새 workflow는 만들지 않았다(6-14 지시 10장: "외부 API를 무리하게 연결하지
않는다").

## 13. 테스트 결과

```
$ python -m pytest -q   # 작업 시작 시점
939 passed, 68 subtests passed in 150.61s

$ python -m pytest -q tests/test_blog_publish_pack.py tests/test_prepare_approved_media.py   # 4장 수정 직후
43 passed in 0.65s

$ python -m pytest -q tests/test_publish_audit.py   # 5장 신규 모듈
24 passed in 0.18s

$ python -m pytest -q tests/test_audit_publish_candidates_cli.py   # 5장 신규 CLI
7 passed in 0.17s

$ python -m pytest -q tests/test_publish_readiness_dashboard.py   # 11장 신규 라우트
6 passed in 3.18s

$ python -m pytest -q tests/test_media_dashboard.py tests/test_scout_dashboard.py \
    tests/test_threads_dashboard.py tests/test_generation_review_and_promotion.py \
    tests/test_performance_dashboard.py tests/test_second_knowledge_correction_and_generation_pool.py \
    tests/test_media_archive.py   # dashboard 회귀
197 passed in 73.27s

$ python -m pytest -q tests/test_publish_audit.py tests/test_audit_publish_candidates_cli.py \
    tests/test_publish_readiness_dashboard.py tests/test_blog_publish_pack.py   # 6-14 신규/수정 전체
75 passed in 3.44s

$ python -m pytest -q   # 전체 재실행(최종)
980 passed, 68 subtests passed in 147.01s
```

실패 0건. 삭제/약화시킨 테스트는 없다(4장에서 수정한 3건은 "예전 모드를
켜는 방법이 바뀐 것"을 반영했을 뿐, 검증 내용 자체는 그대로다). 순증가
41건(939 → 980) - 신규 테스트 파일 3개(`test_publish_audit.py` 24건,
`test_audit_publish_candidates_cli.py` 7건, `test_publish_readiness_dashboard.py`
6건) + `test_blog_publish_pack.py`에 추가한 4건.

6-14 지시 12장이 요구한 테스트 케이스 전부 실제로 존재한다: approved→READY,
unreviewed→BLOCKED, dismissed→BLOCKED, Blog/Threads/YouTube 각각의
already-published→ALREADY_PUBLISHED, missing source→BLOCKED, missing Shorts
script→BLOCKED, duplicate content_id→ERROR, Publish Pack에는 approved만
포함(기존 `test_blog_publish_pack.py`가 이미 검증), 실제 외부 API 미호출,
dry-run이 실제 게시하지 않음(9장 실측 dry-run으로 재확인).

## 14. 데이터 무결성 검증

| 파일 | 작업 전 SHA-256 | 작업 후 SHA-256 | 변경 여부 |
| --- | --- | --- | --- |
| `data/tak_media_archive.json` | `ebe1249f...` | `ebe1249f...`(동일) | 없음 |
| `data/tak_media_generation_6-07_knowledge-scout-6d1d0e2fa762.json` | `9aa3677e...` | `9aa3677e...`(동일) | 없음 |
| `data/tak_brain_knowledge.json` | `a4cbb521...` | `a4cbb521...`(동일) | 없음 |
| `data/tak_threads_pending.json` | `9dd8a8c0...` | `9dd8a8c0...`(동일) | 없음 |
| `data/youtube_publish_log.json` | `a6c94919...` | `a6c94919...`(동일) | 없음 |
| `data/threads_publish_log.json` | `d8907429...` | `d8907429...`(동일) | 없음 |
| `data/blog_publish_log.json` | (파일 없음) | (파일 없음) | 없음 |

Production Archive는 이번 세션에서 **단 한 번도** 열어서 쓴 적이 없다
(`content_engine.media_archive`의 `upsert_archive`/`save_archive`/
`archive_report`류 함수를 이번 세션의 신규 코드 어디에서도 호출하지 않는다 -
`audit_publish_candidates.py`와 `publish_audit.py`는 `load_archive()`만
import한다).

이번 세션이 실제로 만든/바꾼 파일(비-소스코드):

- `data/shorts_scripts/content-ec0c38b9a20c424c.json`,
  `content-e3b8d986ea6db98e.json`, `content-91869ed8be17f3f3.json`(신규,
  9장) - `data/shorts_scripts/`는 애초에 git 추적 대상이 아닌(gitignore
  제외 목록에는 없지만 지금까지 한 번도 commit되지 않은) 운영 산출물
  디렉터리라 이번에도 커밋 대상에 포함하지 않는다.
- `data/blog_publish_pack_daily.md`(재생성, 7장) - `.gitignore`에 등록된
  휘발성 파일.
- `docs/publish_readiness_latest.md`(신규, 5장) - 이 보고서와 함께 커밋한다
  (6-14 지시 4장이 명시한 산출물이므로 문서로 취급).

## 15. Git / Commit / Push 결과

```
$ git branch --show-current
main

$ git rev-parse HEAD origin/main   # 작업 시작 시점
2e0c2832331c301e40b06a87c4092074a2b9b03d
2e0c2832331c301e40b06a87c4092074a2b9b03d
```

이번 세션이 수정/추가한 파일만 정확히 `git add`한다(기존 미커밋 변경은
포함하지 않음):

```
$ git add content_engine/publish_audit.py \
    scripts/audit_publish_candidates.py \
    scripts/generate_blog_publish_pack.py \
    scripts/run_scout_dashboard.py \
    tests/test_blog_publish_pack.py \
    tests/test_publish_audit.py \
    tests/test_audit_publish_candidates_cli.py \
    tests/test_publish_readiness_dashboard.py \
    docs/publish_readiness_latest.md \
    docs/6-14_publish_readiness_and_operation_report.md
```

```
$ git status --short   # 위 10개 파일만 A/M으로 표시, 나머지는 기존과 동일한 M/?? 그대로
```

```
$ git commit -m "feat: add publish readiness audit + close blog pack review-gate bypass (6-14)" (+본문)
[main 4459a67] feat: add publish readiness audit + close blog pack review-gate bypass (6-14)
 10 files changed, 2091 insertions(+), 1 deletion(-)
 create mode 100644 content_engine/publish_audit.py
 create mode 100644 docs/6-14_publish_readiness_and_operation_report.md
 create mode 100644 docs/publish_readiness_latest.md
 create mode 100644 scripts/audit_publish_candidates.py
 create mode 100644 tests/test_audit_publish_candidates_cli.py
 create mode 100644 tests/test_publish_audit.py
 create mode 100644 tests/test_publish_readiness_dashboard.py
```

**커밋 해시: `4459a67`**

```
$ git push
To https://github.com/sopptak/tak-auto
   2e0c283..4459a67  main -> main

$ git fetch origin
$ git log origin/main..HEAD --oneline
(출력 없음)
$ git log HEAD..origin/main --oneline
(출력 없음)
```

**Push 완료. origin/main과 완전히 동기화됨(양방향 모두 비어 있음).**

커밋/push 직후 `git status --short`가 작업 시작 시점(2장)과 정확히 같은
기존 미커밋(`.gitignore`, `content_engine/__init__.py`,
`content_engine/generator.py`, `content_engine/llm_provider.py`,
`content_engine/rewrite.py`, `data/tak_brain_knowledge.json`,
`data/tak_threads_pending.json`, `tests/test_content_engine.py`,
`tests/test_media_batch.py`)과 untracked 문서/스크립트만 남았고, 이번에
커밋한 10개 파일은 더 이상 목록에 나타나지 않았다 - 이번 작업에서
만든/수정한 파일만 정확히 commit됐고, 기존 미커밋 변경은 작업 시작 때와
동일하게 그대로 보존됐다.

## 16. 남은 문제

**CRITICAL**
- (없음)

**HIGH**
- (없음)

**MEDIUM**
- production archive 승인 16건이 전부 `NEEDS_HUMAN_REVIEW`로 분류된다
  (6장) - `knowledge-scout-6d1d0e2fa762`의 `category`가 "금융"으로 태깅돼
  있기 때문인데, 실제 내용은 AI 관련 의견 콘텐츠다. `category` 태깅
  자체가 부정확한 것인지(그렇다면 KNOWLEDGE 정정 필요), 아니면 AI 주제도
  "금융" 인접 카테고리로 의도적으로 넓게 잡은 것인지 이 세션은 판단하지
  않았다 - 사람의 확인이 필요하다.
- 9장에서 발견: `data/tak_threads_pending.json`의
  `content-43786cf3ee0d89c5` draft가 `status=="approved"`로 남아 있지만
  실제로는 이미 `threads_publish_log.json`에 게시 기록이 있다(과거 어느
  시점에 `--execute`로 발행된 뒤 pending 파일 동기화가 누락된 것으로
  보인다 - `publish_approved_threads.py`는 `--execute` 실행 시에만 pending
  상태를 동기화한다). 이 draft는 production archive에 대응 레코드가 없어
  `audit_publish_candidates.py`의 판정 대상에도 포함되지 않는다 - 별도로
  `data/tak_threads_pending.json`을 직접 확인해야 발견된다. 데이터 손상은
  아니지만(실제로 발행은 됐다) 표시 상태가 낡았다.

**LOW**
- YouTube 업로드 실패는 여전히 이력에 기록되지 않는다(6-13이 이미 남긴
  문제, 이번 세션에서 손대지 않음).
- Blog Publishing Pack 기본 모드(`--from-archive` 없이)는 여전히
  존재한다(`--generate-without-review`로 명시적으로 켜야 함) - 완전히
  제거하는 대신 안전한 기본값으로 남겨뒀다(4장 설계 판단 참고).
- `/publish-readiness`는 매 요청마다 archive/knowledge/threads pending/
  publish log 3개를 다시 읽어 즉석에서 계산한다 - production archive가
  수천 건 규모로 커지면(현재 18건) 응답이 느려질 수 있다. 지금 규모에서는
  문제가 되지 않는다.

## 17. 다음 5~6시간 작업 추천

1. **`category` 태깅 정확성 검토** - 16장 MEDIUM 1번. KNOWLEDGE의
   `category`/`domain` 값이 실제 콘텐츠 주제를 정확히 반영하는지 사람이
   확인하고, 필요하면 SCOUT/KNOWLEDGE 생성 단계에서 카테고리 판정 로직을
   다시 살펴본다 - 이 부분이 부정확하면 `is_review_required()`가 계속
   과도하게 넓게 잡혀 진짜 READY 콘텐츠가 하나도 안 나올 수 있다.
2. **`tak_threads_pending.json` 동기화 점검** - 16장 MEDIUM 2번. 과거
   발행분 중 pending 파일이 실제 게시 이력과 어긋난 사례가 더 있는지
   전수 확인하고, 필요하면 `threads_publish_log.json`을 기준으로
   `tak_threads_pending.json`을 한 번 동기화하는 일회성 스크립트를 사람의
   확인 아래 실행한다.
3. **실제 게시 1건 실행** - 이번 세션이 만든 감사 도구로 최소 1건이
   NEEDS_HUMAN_REVIEW에서 사람이 직접 최종 확인해 실제로 게시하고(Blog:
   `mark_blog_published.py`, Threads: `publish_approved_threads.py
   --execute`), `audit_publish_candidates.py`를 다시 실행해 그 건이
   ALREADY_PUBLISHED로 정확히 넘어가는지 실측으로 확인.
4. **성과 데이터 수집 workflow 설계**(6-13이 이미 추천, 여전히 미착수) -
   `scripts/collect_performance.py`를 호출하는 workflow와 API 토큰을 CI에
   넣을지 결정.
5. **`/publish-readiness`에서 Blog Pack/Shorts Script 자동 생성 트리거
   검토** - 지금은 CLI(`prepare_approved_media.py`)를 따로 실행해야 한다.
   화면에서 바로 "Pack 생성"을 트리거하는 것(승인 상태를 바꾸지 않는,
   순수 파생 파일 생성이므로 여전히 안전한 액션)이 가치가 있을지 검토.

## 18. 최종 결론

**PASS**

- 6-13이 남긴 유일한 MEDIUM 문제(승인 게이트 우회 가능성)를 실행 자체를
  안전하게 제한하는 방식으로 해결했다(4장) - 기존 정상 경로/테스트를 깨지
  않았다(43개 관련 테스트 전부 통과).
- 새 감사 도구(`content_engine/publish_audit.py`,
  `scripts/audit_publish_candidates.py`)는 어떤 콘텐츠도 임의로 승인하지
  않는다 - `review_status != approved`는 코드 구조상 READY가 될 수 없다
  (테스트로 명시적으로 고정).
- 실제 production 데이터(Production Archive, Generation Pool, KNOWLEDGE,
  Threads pending, 각 채널 publish log)는 이번 세션 동안 단 한 번도 쓰이지
  않았다(14장 해시로 재확인) - Shorts Script 3건 생성, Blog Pack
  재생성(둘 다 gitignore/비추적 운영 산출물)만 실제로 일어났다.
- 전체 테스트 980 passed, 0 failed(13장).
- 실제 외부 플랫폼(Naver/Threads/YouTube) 게시는 이번 세션에서 전혀
  수행하지 않았다 - 9장의 Threads dry-run 실행도 실제로는 이미 게시된
  content_id라 "게시 이력에 이미 있습니다"로 즉시 종료됐고, 파일 해시
  비교로 무변경을 재확인했다.
- 발견한 데이터 이상(16장 MEDIUM 2번, pending 동기화 누락)은 임의로
  고치지 않고 사람의 판단이 필요한 문제로 명확히 남겼다.
