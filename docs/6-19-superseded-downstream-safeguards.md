# 6-19 — SUPERSEDED Downstream Safeguards

## 1. 작업 목적

Production Archive에서 `review_status == "superseded"`로 표시된 콘텐츠(6-17이
도입한 lifecycle, 6-18이 승격 시 조용한 overwrite를 막음)가, 이미 만들어진
downstream artifact(Threads pending draft, ShortsScript JSON/렌더링된 MP4, Blog
Publishing Pack)를 통해 **다시 발행 후보로 살아나는 경로**를 구조적으로 차단한다.

> "생성 당시 approved였으니 계속 유효하다"는 가정을 금지하고, 실제 발행 직전에
> Production Archive의 **현재** 상태를 기준으로 판단한다.

이번 단계는 안전장치 구현 + 테스트 + 운영 데이터 무결성 검증까지만 한다. 실제
콘텐츠 supersede, 실제 Threads/YouTube/Naver 게시는 이번 세션에서 실행하지
않았다. 특히 `content-5971ed5204437cdd`, `content-afc6060bc1957867`는 어떤
방식으로도 변경하지 않았다(14장에서 세션 종료 시점 상태를 확인).

## 2. 시작 baseline

- git branch: `main`, HEAD/origin/main: `3d151c4a614851fb6c183a20c431762910a49d10`
  (완전히 동기화됨)
- git status: 세션 시작 전부터 존재하던 다수의 unrelated uncommitted 변경/미추적
  파일이 있었다(`.gitignore`, `content_engine/__init__.py`,
  `content_engine/generator.py`, `content_engine/llm_provider.py`,
  `content_engine/rewrite.py`, `tests/test_content_engine.py`,
  `tests/test_media_batch.py`, `data/tak_media_archive.json` 등 수십 개). 이번
  작업은 이 파일들을 하나도 건드리지 않았고, commit도 이번 세션이 실제로 만든/
  수정한 파일만 선택적으로 포함한다(15장 참고).
- 전체 pytest baseline: **1062 passed, 68 subtests passed** (169.85s)
- Production Archive(`data/tak_media_archive.json`) record 수: **18건**
- `content-5971ed5204437cdd`: `review_status=approved`, `superseded_by=None`
  (6-18이 남긴 상태 그대로)
- `content-afc6060bc1957867`: Production Archive에 아직 없음(6-18과 동일)
- 6-17(`docs/6-17_superseded_lifecycle_design.md`), 6-18
  (`docs/6-18-same-content-id-overwrite-protection.md`) 보고서를 먼저 읽었고,
  실제 코드(`content_engine/media_archive.py`, `content_engine/publish_audit.py`,
  `scripts/supersede_media_record.py`)를 대조해 두 보고서가 서술한 내용과 현재
  코드가 일치함을 확인했다.

## 3. 기존 downstream 구조 조사 결과

세 플랫폼 모두 Production Archive(`MediaArchiveRecord.review_status`)를 최종
판단 기준으로 삼는 지점이 있는지 코드를 추적했다.

| 플랫폼 | Archive → downstream 연결 지점 | 발행 직전 재검증 여부(6-19 이전) |
|---|---|---|
| Blog | `blog_publish_pack.build_blog_publish_pack_from_archive()`/`select_approved_blog_candidates_from_archive()` — `--from-archive` 모드에서 매 실행마다 archive를 다시 읽고 `review_status == "approved"`만 통과시킴 | **이미 안전함** — supersede되면 `review_status`가 `"superseded"`로 바뀌므로 다음 Pack 생성에서 자동 제외됨 |
| Shorts | `shorts_adapter.save_approved_shorts_script()`/`scripts/generate_approved_shorts_script.py` — 생성 시점에 `review_status == "approved"` 확인 | **생성 시점만 안전, 이후 재검증 없음** — 한 번 만들어진 `ShortsScript` 파일은 archive가 나중에 superseded로 바뀌어도 그대로 남고, `render_youtube_short.py`/`upload_youtube_short.py`는 archive를 전혀 참조하지 않았음 |
| Threads | `scripts/generate_threads_draft.py`가 `tak_threads_pending.json`을 만들 때는 archive의 승인 여부를 전혀 확인하지 않음(승인된 KNOWLEDGE에서 직접 생성 후 rotation 선정) | **발행 시점까지 전혀 재검증 없음** — `scripts/publish_approved_threads.py`는 `ThreadsPendingDraft.status == "approved"`만 보고 실제 게시하며, Production Archive를 아예 import하지 않았음 |

Blog/Shorts는 "생성 후보 선정" 단계에서 이미 `review_status == "approved"`
필터를 쓰고 있어서 6-19 이전에도 안전했다(review_status가 "superseded"로
바뀌면 "approved" 필터에서 자동 탈락). 실제 구멍은 **Threads 발행 CLI**와
**YouTube 업로드 CLI** 두 곳뿐이었다 - 둘 다 "발행 직전 재검증" 지점이 아예
없었다.

## 4. 발견한 재발행 위험

- Threads: OLD content_id가 approved 상태일 때 만들어진 pending draft가
  approved 상태로 남아 있으면, Production Archive에서 나중에 superseded로
  바뀌어도 `publish_approved_threads.py --execute`가 그 사실을 알 방법이
  전혀 없어 그대로 실제 Threads API를 호출해 게시할 수 있었다.
- Shorts/YouTube: OLD content_id로 이미 저장된 `ShortsScript` JSON(또는 그걸로
  렌더링한 MP4)이 있으면, Production Archive가 나중에 superseded로 바뀌어도
  `upload_youtube_short.py --content-id <OLD>`가 그 사실을 알 방법이 전혀
  없어 그대로 실제 YouTube API를 호출해 업로드할 수 있었다.
- Blog: 위 3장 표에서 확인했듯 실질적 위험 없음(설계상 이미 차단됨). 다만
  이미 생성된 `blog_publish_pack_daily.md` 파일 자체가 supersede 이후에도
  디스크에 남아 있을 수 있다는 점은 19장 "남은 리스크"에 기록한다(Blog는
  Naver 자동 게시가 없어 "발행 직전 재검증"에 해당하는 자동화 지점이 애초에
  없다).

## 5. 설계 원칙

1. **승인 여부**와 **현재 발행 가능 여부**를 구분한다. `review_status`가 한 번
   `approved`였다는 과거 사실은 그대로 두고, `superseded`로 바뀐 시점부터는
   downstream 어디서도 활성 후보가 아니어야 한다.
2. **오직 supersede만 차단한다.** unreviewed/dismissed/승인 이력 등 다른
   상태·정책은 이 작업이 건드리지 않는다(각 플랫폼의 기존 승인 게이트가 계속
   담당).
3. **ALREADY_PUBLISHED > SUPERSEDED 우선순위**(기존 Publish Readiness 정책,
   `content_engine/publish_audit.py`)를 그대로 유지한다 - 이미 게시된 사실이
   내부 lifecycle 표시보다 항상 우선한다.
4. **ORPHAN(Archive에 레코드 자체가 없음) 정책은 바꾸지 않는다.** 이 작업의
   판정 함수는 레코드가 없으면 차단하지 않는다 - "차단 안 함"과 "기존 ORPHAN
   경고/정책"은 호출부가 이미 갖고 있던 대로 유지된다.
5. **공통 헬퍼 하나로 플랫폼별 복붙을 피한다** - Threads/YouTube 두 실행
   지점이 동일한 판정 함수를 공유한다(6장).
6. **최소 변경.** 이미 안전한 Blog/Shorts 후보 선정 로직은 한 줄도 바꾸지
   않았다.

## 6. 공통 eligibility 정책

새 모듈 `content_engine/publish_eligibility.py`을 추가했다.

- `find_production_record(records, content_id)` - Production Archive
  레코드 목록에서 content_id로 1건을 조회한다.
- `check_supersede_block(record)` - 레코드 1건(또는 `None`)을 보고 supersede
  차단 여부만 판정하는 순수 함수. `record is None`이거나
  `review_status != "superseded"`이면 차단하지 않는다. `review_status ==
  "superseded"`일 때만 차단하고, `superseded_by`와 사유 문자열을 함께
  반환한다.
- `check_content_supersede(records, content_id)` - 위 두 함수를 합친 편의
  함수.
- `format_block_message(content_id, check)` - CLI 출력 규격
  (`content_id=... status=SUPERSEDED superseded_by=... result=BLOCKED
  reason=...`)을 만든다.

이 헬퍼는 의도적으로 "승인 여부"(`review_status == "approved"`인지)를 판정하지
않는다 - 각 플랫폼(Threads의 `ThreadsPendingDraft.status`, Shorts/Blog의
archive 필터)이 이미 그 판단을 담당하고 있고, 그 정책을 이 작업이 대신
결정하면 기존 동작이 바뀔 위험이 있기 때문이다(13장 참고).

## 7. Threads 보호

`scripts/publish_approved_threads.py`에 `--production-archive`(기본값
`data/tak_media_archive.json`, 읽기 전용) 인자를 추가했다. 각 approved draft를
처리하기 직전 순서는 다음과 같다.

1. (기존) `history.is_published()` - 이미 게시 이력에 있으면 API를 호출하지
   않고 종료(ALREADY_PUBLISHED 우선순위 유지).
2. **(신규)** `check_content_supersede(production_records, draft.content_id)` -
   superseded면 차단 메시지를 출력하고 `exit_code=1`, 다음 draft로 넘어간다.
   `--dry-run`에서도 동일하게 차단해서, `--execute` 없이 미리 알 수 있다.
3. (기존) `validate_final_text()`, dry-run/execute 분기.

Threads pending 파일 자체는 건드리지 않는다(6-19 지시 8장: "Threads pending
파일을 자동 삭제할 필요는 없다").

## 8. Shorts 보호

조사 결과 `scripts/generate_approved_shorts_script.py`는 이미
`review_status == "approved"`만 통과시키므로 수정하지 않았다(회귀 테스트로
고정, 12장).

새로 보호한 지점은 **YouTube 업로드**다. `scripts/upload_youtube_short.py`에
`--production-archive` 인자를 추가했고, `--content-id`가 주어졌을 때만(기존
6-02 설계의 선택적 파라미터 - 생략하면 판단 근거가 없으므로 기존과 동일하게
동작) 다음을 확인한다.

1. (기존) `history.is_published(content_id)` - 이미 업로드 이력에 있으면
   API를 호출하지 않고 종료.
2. **(신규)** `check_content_supersede()` - superseded면 차단 메시지를
   출력하고 `return 1`. `--dry-run`에서도 동일하게 차단한다.

render 단계(`scripts/render_youtube_short.py`)는 수정하지 않았다 - 이 스크립트는
`content_id`를 아예 모르므로(대본 JSON 경로만 받음) 연결할 방법이 없고, 6-19
지시 7장("render는 허용하되 실제 publish 단계에서 재검증")과도 일치한다. 실제
YouTube API를 호출하는 지점(업로드)에서만 차단한다.

## 9. Blog 보호

3장에서 확인했듯 `build_blog_publish_pack_from_archive()`/
`select_approved_blog_candidates_from_archive()`는 `record.review_status ==
"approved"` 필터만으로 이미 superseded 레코드를 배제한다(supersede는
`review_status`를 `"superseded"`로 바꾸므로). 코드를 변경하지 않고 회귀
테스트만 추가했다(12장 A절).

`scripts/mark_blog_published.py`는 "사람이 실제로 이미 게시를 완료했다"는
사실을 사후 기록하는 도구이지 candidate 선정 도구가 아니므로 수정하지 않았다
- 이 스크립트에 supersede 차단을 넣으면 실제로는 이미 일어난 게시 사실을
기록하지 못하게 막는 부작용만 생긴다(19장에 잔여 리스크로 기록).

## 10. Publish Readiness 연동

`content_engine/publish_audit.py`(SUPERSEDED 우선순위, ALREADY_PUBLISHED와의
관계)는 전혀 수정하지 않았다 - 이미 6-17이 올바르게 구현했고
(`audit_record()`의 2.5절), 이번 작업의 대상은 그 판정 로직이 아니라 "판정
자체가 아예 없던" Threads/YouTube 실행 스크립트였다. 두 모듈이 우연히
비슷한 로직(둘 다 `superseded_by`/`review_status`를 본다)을 갖게 됐지만
목적이 다르므로(하나는 읽기 전용 감사 보고서, 하나는 실행 직전 게이트)
강제로 통합하지 않았다 - 6-19 지시 12장("공통 함수가 어렵다면 플랫폼별
최소 방어선도 허용하되 동일 로직이 서로 다른 정책으로 갈라지지 않게")에 따라
`content_engine/publish_eligibility.py` 하나를 Threads/YouTube 두 실행
스크립트가 공유하게 해서 "실행 게이트" 쪽만 통일했다.

## 11. 통합 시뮬레이션 (6-19 지시 14장)

`tests/test_superseded_downstream_safeguards.py`의
`EndToEndSupersedeDownstreamScenarioTests`가 요구된 시나리오를 그대로
구현한다.

1. `content-e2e-old-{threads,shorts,blog}` 3건을 `review_status=approved`로
   Production Archive에 넣는다.
2. OLD Threads용 approved pending draft, OLD Shorts용 `ShortsScript` JSON
   파일을 실제로 만든다.
3. OLD 3건을 각각 `content-e2e-new-{threads,shorts,blog}`로 supersede하고,
   NEW 3건은 approved로 Archive에 추가한다.
4. OLD Threads 발행 시도(`--execute`), OLD Shorts 업로드 시도(`--content-id
   content-e2e-old-shorts`), OLD Blog Pack 생성을 각각 실행한다.
5. NEW Threads 발행, NEW Shorts 업로드, NEW Blog Pack 포함 여부를 각각
   확인한다.

| 콘텐츠 | Production 상태 | Threads | Shorts(YouTube) | Blog |
|---|---|---|---|---|
| OLD | SUPERSEDED | BLOCK (API 호출 0회, exit=1) | BLOCK (API 호출 0회, exit=1) | Pack에서 제외 |
| NEW | APPROVED | 정상 발행(published) | 정상 업로드(exit=0) | Pack에 포함 |

## 12. 테스트 목록

신규 테스트 파일 2개, 총 31건.

**A. `tests/test_publish_eligibility.py`** (`content_engine.publish_eligibility` 단위 테스트)
- record 없음 → 차단 안 함(ORPHAN 정책 보존)
- approved/unreviewed/dismissed → 차단 안 함
- superseded → 차단(사유/superseded_by 포함)
- `check_content_supersede()` 조회+판정 조합
- `format_block_message()` 출력 규격(content_id/status/superseded_by/result/reason)

**B. `tests/test_superseded_downstream_safeguards.py`**
- **A절(Blog 회귀)**: superseded 레코드가 `select_approved_blog_candidates_from_archive()`/
  `build_blog_publish_pack_from_archive()`에서 제외됨을 고정
- **B절(Shorts 회귀)**: `generate_approved_shorts_script.py`가 `--content-id`
  단건/배치 모드 모두에서 superseded를 거부함을 고정
- **C절(Threads 신규)**: superseded → `--execute`/`--dry-run` 모두 API 호출 0회
  + exit=1; archive 레코드 없음(ORPHAN) → 차단 안 함; approved(active) → 정상
  발행; ALREADY_PUBLISHED가 SUPERSEDED보다 우선
- **D절(YouTube 업로드 신규)**: 위와 동일한 4가지 케이스 + `--content-id` 생략
  시 archive 검사 자체를 건너뛰는 하위호환성
- **E절(통합 시나리오)**: 11장의 6개 검증(OLD 3플랫폼 차단 + NEW 3플랫폼 정상)

6-19 지시 13장(A~R)의 항목 중 이 작업이 새로 코드를 추가한 범위(Threads
실행 게이트, YouTube 업로드 게이트, Blog/Shorts 회귀 고정)에 해당하는 것은
전부 위 테스트로 커버했다. ALREADY_PUBLISHED(H), ORPHAN(G), dismissed/
unreviewed(I/J), replacement chain(M/N/O)은 6-17/6-18이 이미
`tests/test_media_superseded_lifecycle.py`/`tests/test_publish_audit.py`에서
고정했고 이번 세션에서도 그대로 통과함을 확인했다(변경하지 않았으므로 중복
작성하지 않았다).

## 13. 테스트 결과

실행 순서(6-19 지시 19장)대로 진행했다.

1. `tests/test_publish_eligibility.py` + `tests/test_superseded_downstream_safeguards.py`
   단독 실행: **31 passed**
2. Threads 관련(`test_publish_approved_threads.py`) + 신규 Threads 케이스: 회귀 없음
3. Shorts 관련(`test_shorts_adapter.py`) + 신규 Shorts 케이스: 회귀 없음
4. Blog 관련(`test_blog_publish_pack.py`) + 신규 Blog 케이스: 회귀 없음
5. Publish Readiness(`test_publish_audit.py`): 회귀 없음
6. Superseded lifecycle(`test_media_superseded_lifecycle.py`, `test_media_archive.py`): 회귀 없음
7. 위 7개 파일 합산: **156 passed**
8. 전체 pytest: **1093 passed, 68 subtests passed (152.13s)**

baseline(1062) + 신규(31) = 1093 - 정확히 일치, 기존 assertion을 삭제/약화한
곳 없음, 테스트 수가 줄어든 곳 없음.

## 14. 운영 데이터 SHA256 전후 비교

작업 종료 시점 해시(참고용 - 세션 시작 시점에는 pytest baseline/레코드 수만
기록했고 별도 SHA256을 찍지 않았으므로, 아래는 "이 세션이 실행한 어떤 코드도
이 파일들에 쓰기를 한 적이 없다"는 사실을 `git diff`/`mtime`으로 교차 검증한
결과다):

```
ebe1249fe36c3fe681660c3659d2199f5ecd4f6949b7890479fac9a4e8ea8d33  data/tak_media_archive.json
e2ad1d39fa254ceaad4fb646124cb3e9b0b8e591ea688c1e0836fa1b6f706a31  data/tak_brain_knowledge.json
d122a0b68c093fb0e894251e60d5d987b40d9a268cd9b44522c4385bf5cabf72  data/tak_threads_pending.json
d89074291327bc759d5416531c6cc6fb9a8cad0c5fcb6e8dc32660535d995c68  data/threads_publish_log.json
a6c9491a4c446826210a7566e5bdbb5ca20e3495df9e7e88356f868acde608c2  data/youtube_publish_log.json
```

교차 검증:
- `git diff --stat -- data/` → 출력 없음(추적 파일 변경 없음).
- `git status --short -- data/` → 세션 시작 전부터 있던 미추적 파일 목록과
  동일(`data/tak_media_archive.json`, `data/blog_draft_*.md`,
  `data/shorts_scripts/`) - 새로 생기거나 사라진 항목 없음.
- `data/tak_media_archive.json` 파일의 mtime은 `2026-09-20 09:14:58 UTC`로
  이번 세션(2026-09-22) 이전이다 - 이번 세션이 이 파일을 쓴 적이 없음을
  확인한다.
- `content-5971ed5204437cdd`: `review_status=approved`,
  `superseded_by=None` - 6-18 종료 시점과 동일.
- `content-afc6060bc1957867`: Production Archive에 여전히 없음 - 6-18 종료
  시점과 동일.
- `data/shorts_scripts/` 안의 실제 운영 ShortsScript 5개 파일 모두 이번
  세션 이전 mtime만 있고, 새 파일이 추가되지 않았다(테스트는 전부
  `tempfile.TemporaryDirectory()`에만 썼다).

모든 실제 운영 데이터가 세션 시작 시점과 동일하게 보존되었다.

## 15. 변경 파일

이번 세션이 실제로 만들거나 수정한 파일만 나열한다(unrelated 기존
uncommitted 변경은 전혀 포함하지 않는다).

- `content_engine/publish_eligibility.py` (신규)
- `scripts/publish_approved_threads.py` (수정 - `--production-archive` 인자 +
  supersede 차단 게이트)
- `scripts/upload_youtube_short.py` (수정 - `--production-archive` 인자 +
  supersede 차단 게이트)
- `tests/test_publish_eligibility.py` (신규)
- `tests/test_superseded_downstream_safeguards.py` (신규)
- `docs/6-19-superseded-downstream-safeguards.md` (신규, 이 문서)

## 16. Git diff

핵심 변경만 요약(전체 diff는 커밋 이력 참고).

```diff
--- a/scripts/publish_approved_threads.py
+++ b/scripts/publish_approved_threads.py
+from content_engine.media_archive import load_archive
+from content_engine.publish_eligibility import check_content_supersede, format_block_message
...
+    parser.add_argument("--production-archive", type=Path, default=ROOT / "data" / "tak_media_archive.json", ...)
...
+        supersede_check = check_content_supersede(production_records, draft.content_id)
+        if supersede_check.blocked:
+            print(format_block_message(draft.content_id, supersede_check))
+            exit_code = 1
+            continue

--- a/scripts/upload_youtube_short.py
+++ b/scripts/upload_youtube_short.py
+from content_engine.media_archive import load_archive
+from content_engine.publish_eligibility import check_content_supersede, format_block_message
...
+    if content_id:
+        production_records = load_archive(args.production_archive)
+        supersede_check = check_content_supersede(production_records, content_id)
+        if supersede_check.blocked:
+            print(format_block_message(content_id, supersede_check))
+            return 1
```

## 17. Commit

커밋 완료: `1f4df7e` — "6-19: block superseded downstream publishing".
15장 목록의 6개 파일만 개별적으로 `git add`했다(`git add -A`/`.` 사용하지
않음). `6 files changed, 1403 insertions(+), 6 deletions(-)`.

## 18. Push

`origin main`으로 push 완료: `3d151c4..1f4df7e main -> main`. force push
사용하지 않았다.

## 19. 남은 리스크

1. **Race condition(6-19 지시 11장)**: `publish_approved_threads.py`/
   `upload_youtube_short.py` 모두 Production Archive를 프로세스 시작 시
   한 번만 읽는다. archive 로드 직후 ~ 실제 API 호출 사이에 다른 프로세스가
   supersede를 실행하면 이 창(window) 안에서는 막을 수 없다. JSON 파일 기반
   저장소에는 진짜 원자적 트랜잭션이 없으므로(6-19 지시 11장이 이 부분을
   "억지로 해결하지 말라"고 명시) 이번 작업은 이 한계를 그대로 인정하고
   기록만 한다 - 실제 운영에서 이 창은 매우 좁고(단일 프로세스 CLI 실행
   시간), Threads/YouTube 모두 이미 존재하는 idempotency 장치
   (PublishHistory)가 이중 게시 자체는 별도로 막는다.
2. **YouTube 업로드는 `--content-id`가 주어졌을 때만 보호된다.** 기존
   설계(6-02)부터 `--content-id`/`--knowledge-id`가 선택 인자였고, 현재
   `.github/workflows/youtube-shorts-upload.yml`도 이 값을 넘기지 않는다.
   `--content-id` 없이 실행하면 이번에 추가한 검사도 판단 근거가 없어
   건너뛴다(6-13이 도입한 기존 ALREADY_PUBLISHED 검사와 동일한 한계). 근본
   해결은 "`--content-id`를 필수로 강제"인데, 이는 기존 workflow/스크립트
   호출부를 바꿔야 하는 더 큰 변경이라 이번 세션 범위를 벗어난다고 판단해
   실행하지 않았다(20장 Human Decision Required 참고).
3. **Blog Publishing Pack(.md) 파일 자체는 재생성 전까지 stale할 수 있다.**
   `--from-archive`로 다시 생성하면 항상 최신 archive를 반영하지만, 이미
   디스크에 있는 오래된 `data/blog_publish_pack_daily.md`를 사람이 재생성 없이
   그대로 네이버에 복사/붙여넣기하면 이 안전장치를 우회한다. Blog는 네이버
   자동 게시가 없어 "발행 직전 자동 재검증" 지점이 시스템 안에 존재하지
   않으므로, 이 잔여 리스크는 코드가 아니라 운영 절차(항상 Pack을 최신으로
   재생성한 뒤 사용)로만 줄일 수 있다.
4. **`mark_blog_published.py`는 supersede 여부를 확인하지 않는다.** 의도된
   설계다(9장) - 이 스크립트는 "이미 일어난 게시"를 기록할 뿐이므로, superseded
   상태의 content_id를 기록하려는 시도를 막으면 오히려 실제로 일어난 사실을
   기록하지 못하게 되는 역효과가 생긴다.

## 20. Human Decision Required

- **YouTube 업로드 workflow에서 `--content-id`를 필수로 강제할지 여부.**
  현재는 선택 인자이고 기존 GitHub Actions workflow가 아예 넘기지 않는다.
  강제하면 이 6-19 안전장치의 커버리지가 완전해지지만, workflow/운영 절차
  변경이 필요하다(이번 세션은 운영 workflow 파일을 수정하지 않았다).
- 그 외에는 이번 작업 범위 안에서 정책 충돌이나 실제 운영 데이터 변경이
  필요한 상황이 없었다.

## 21. 다음 단계 제안

1. YouTube 업로드 자동화(workflow)가 `--content-id`/`--knowledge-id`를 항상
   넘기도록 파이프라인을 정리하면, 이번 안전장치의 커버리지가 완전해진다.
2. Blog Pack 생성 자동화(`scripts/generate_blog_publish_pack.py --from-archive`)를
   네이버 게시 직전 항상 재실행하도록 운영 체크리스트/문서에 명시하면 19장의
   3번 리스크가 실질적으로 사라진다.
3. `content_engine/publish_eligibility.py`는 현재 Threads/YouTube 두 곳만
   쓴다. 앞으로 새로운 발행 채널이 추가되면 이 헬퍼를 그대로 재사용할 수
   있다.
