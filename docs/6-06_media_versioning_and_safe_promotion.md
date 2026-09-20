# TAK AUTO 6-06 — MEDIA generation/version 관리 및 안전한 promotion

## 1. 작업 시작 상태

```
$ git branch --show-current
main

$ git log -10 --oneline
a2094c4 docs: record final commit/push confirmation in 6-05 report
a473262 fix: correct scout knowledge type before media regeneration
3d8556a docs: record final commit/push confirmation in 6-04 report
31488ee fix: prevent cross-domain media template leakage
8cb4923 docs: record final commit/push confirmation in 6-03 report
1e8d875 fix: validate knowledge to media operational pipeline
025916d docs: record final commit/push confirmation in 6-02 report
9e99a47 feat: operationalize publish performance tracking
f2988da docs: record final commit/push confirmation in 6-01 report
39cfb35 feat: add channel performance data foundation

$ git fetch origin   # (출력 없음, 최신)
$ git log origin/main..HEAD --oneline   # (출력 없음, 앞서가는 커밋 없음)
```

`git status --short`(작업 시작 시점 전체 — 6-05 종료 시점과 완전히 동일함을 확인했다):

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

이 목록은 6-05 보고서(`docs/6-05_..._regeneration.md` 1장·22장)가 마지막에 기록한
상태와 정확히 일치한다 — 6-05 이후 다른 세션이 아무것도 커밋/변경하지 않았다는 뜻이다.
이번 6-06 작업도 이 목록의 파일들을 **그대로 보존**하는 것을 최우선 제약으로 삼았다
(17장·20장 참고).

Baseline 전체 테스트:

```
819 passed, 68 subtests passed in 123.80s (0:02:03)
```

6-05 종료 시점 보고와 정확히 일치함을 확인했다(0 failed).

## 2. 기존 archive 구조

`content_engine/media_archive.py`를 읽고 분석했다.

- **`MediaArchiveRecord`** (frozen dataclass): `content_id`, `knowledge_id`,
  `platform`, `generation_status`(`valid`/`rejected`/`error`),
  `original_title`/`original_body`(재작성 전 템플릿), `rewritten_title`/
  `rewritten_body`(LLM 결과), `source_url`, `evidence`, `evidence_unit_ids`,
  `created_at`, `validation_errors`, `error_message`,
  `review_status`(`unreviewed`/`approved`/`dismissed`, 기본값 `unreviewed`),
  `edited_title`/`edited_body`(사람이 Dashboard에서 고친 최종본, 5-29).
- **`compute_content_id()`**(`content_engine/publish_history.py`): `knowledge_id
  + platform + source_url + evidence_unit_ids + original_title + original_body`의
  해시. **재작성(rewritten_*) 텍스트는 지문 계산에 쓰이지 않는다** — "같은 KNOWLEDGE로
  같은 슬롯을 재실행해도 값이 바뀌지 않아야 한다"는 목적을 위한 설계다. 이 성질이
  바로 6-05/6-06 문제의 근원이다(4장).
- **`archive_report(report, path)`**: `MediaBatchReport`의 모든 항목(valid+rejected+error)을
  `upsert_archive()`로 저장한다. 이미 있던 `content_id`라면 `review_status`/
  `edited_*`를 그대로 이어받고 생성 결과만 최신화한다.
- **`upsert_archive(path, records)`**: `{content_id: record}` **딕셔너리**를 만들어
  덮어쓴다 — 즉 **`content_id`가 유일한 키**이며, 파일 안에 같은 `content_id`를
  가진 레코드는 항상 정확히 1개만 존재할 수 있다.
- **`load_archive(path)`**: 파일이 없으면 빈 목록. `MediaArchiveRecord.from_dict()`가
  `dict.get()`으로 필드를 읽으므로, JSON에 없는 키는 각 필드의 기본값으로 채워진다
  (이 성질을 6장의 backward compatibility에 그대로 활용했다).

이 archive를 실제로 소비하는 지점(`grep`으로 확인):
`scripts/run_scout_dashboard.py`(`/media` Dashboard, 승인 처리),
`content_engine/blog_publish_pack.py`(`build_blog_publish_pack_from_archive`),
`scripts/generate_approved_shorts_script.py`,
`scripts/generate_threads_draft.py`,
`scripts/prepare_approved_media.py`(승인된 레코드를 Blog Pack/ShortsScript로
오케스트레이션),
`content_engine/performance/*`. 이들은 전부 **"이 content_id의 활성 레코드는
정확히 1개"**라는 전제로 짜여 있다. 특히
`scripts/run_scout_dashboard.py:handle_media_approve_submission()`을 읽어보면,
현재 시스템에서 "승인(review_status→approved)"은 이미 부분적으로 "promotion"
역할도 겸하고 있었다 — platform이 `threads`/`shorts`면 승인 즉시
`content_engine.threads_review.upsert_pending()`/ShortsScript 파일 생성까지
자동으로 연결된다(단, 그 결과물도 각자 별도 화면에서 다시 승인해야 실제 발행
후보가 된다 — 실제 게시로 바로 이어지지는 않는다). Blog만 별도 CLI
(`generate_blog_publish_pack.py --from-archive`)가 필요하다. 이 기존 동작은
9장에서 다시 다룬다.

## 3. content_id 충돌 문제 재현

6-05가 만든 두 archive를 실제 LLM 호출 없이 비교했다(`data/tak_media_archive.json` vs
`data/tak_media_archive_6-05_b28b782b2a33_regeneration.json`, 둘 다 읽기만 함).

| platform | content_id | old title | new title | old body hash(sha256 앞 8자리) | new body hash | same content_id | 실제 내용 다름 |
|---|---|---|---|---|---|---|---|
| blog | content-5971ed5204437cdd → content-afc6060bc1957867 | 신기술을 바라보는 나의 기준 | 두려움보다 먼저, 직접 확인하는 태도 | (id 자체가 다름) | (id 자체가 다름) | ✗ (id 다름) | — |
| shorts | content-e787c9201b94a948 → content-4a2e38caa47ba717 | 새로운 기술을 마주하는 나의 기준 | 두려움보다 먼저 필요한 것 | (id 자체가 다름) | (id 자체가 다름) | ✗ (id 다름) | — |
| shorts | content-3ae2d78568210164 | 신기술을 마주하는 내 기준 | 두려움보다 먼저, 직접 느껴보기 | cff4fe19 | 4d99ef4d | **✓ 같음** | **✓ 다름** |
| shorts | content-cabd37f3a2745724 | 신기술을 대하는 내 기준 | 두려움보다 먼저 필요한 것 | ce089302 | 522588b9 | **✓ 같음** | **✓ 다름** |
| threads | content-dbf0fb4eb5cfd791 | AI에 대한 우려와 내가 택한 태도 | 신기술은 두려움보다 직접 경험이다 | 54c4a9f7 | 35d9061a | **✓ 같음** | **✓ 다름** |
| threads | content-81d4e7c5723598f6 | 신기술은 직접 부딪혀 봐야 한다 | 신기술은 직접 부딪혀 봐야 한다 | 2178b500 | 2b851ae4 | **✓ 같음** | **✓ 다름**(본문 미세 차이) |
| threads | content-4015df0692e0bcc4 | AI에 대한 우려, 직접 마주해 보기 | 신기술은 두려움보다 직접 경험 | 4b143739 | 966d8c7f | **✓ 같음** | **✓ 다름** |
| threads | content-5a6b175ac6023db1 | AI를 두려워하기 전에 | 신기술을 마주하는 기준 | 4b11a01e | b874c636 | **✓ 같음** | **✓ 다름** |
| threads | content-cbcf705b6056c9fc | 신기술은 직접 부딪혀 봐야 한다 | 신기술은 직접 부딪혀봐야 한다 | 91b0fa0e | a702a936 | **✓ 같음** | **✓ 다름**(띄어쓰기 등 미세 차이) |

(body hash는 이번 보고서 작성을 위해 `rewritten_body`에 sha256을 적용해 실제로
계산한 앞 8자리 값이다 — 재현용 참고값이며 별도 저장하지 않는다.)

**9건 중 7건이 content_id는 동일한데 `rewritten_title`/`rewritten_body` 실제 내용은
다르다.** 이 7건에 대해 `archive_report()`를 production archive에 그대로
실행했다면, `upsert_archive()`의 `{content_id: record}` 덮어쓰기 규칙 때문에 기존
레코드의 재작성 텍스트가 새 텍스트로 **조용히 대체**됐을 것이다(6-05는 이를
별도 파일로 우회해서 막았다 — 이번 6-06은 그 우회를 구조로 만든다).

## 4. 문제의 원인

`compute_content_id()`가 `original_title`/`original_body`(재작성 **이전** 템플릿
텍스트, `content_engine/generator.py`가 만듦)만 지문에 쓰기 때문이다.
`generator.py:_profile()`은 `article_type`에 따라 "finance"/"book"/
"experience"/"criterion" 프로파일을 고르고, 그 프로파일이 **일부** 슬롯의 제목
템플릿만 바꾼다(`_criterion_blog()`의 blog 제목, `_criterion_content()`의
shorts 제목 1개). 나머지 슬롯(shorts 2개, threads 5개)은 제목 템플릿이 프로파일과
무관하므로, `article_type`이 바뀌어도 `original_title`/`original_body`가 그대로고
따라서 `content_id`도 그대로다. 반면 재작성(rewritten_*) 단계는 LLM이 매번 다른
표현을 만들어내므로, **"같은 content_id인데 실제 콘텐츠는 다른"** 상황이
구조적으로 발생한다. 즉 문제는 하나의 결함이 아니라, `content_id`의 설계 목적
("같은 슬롯 재실행 시 안정적인 식별자")과 "재생성마다 다른 결과를 구분해야
한다"는 새 요구사항이 애초에 서로 다른 축이라는 점이다.

## 5. 선택한 versioning architecture

지시서 7장의 세 안을 실제 코드/기존 사용 방식 기준으로 비교했다.

| 기준 | A안(content_id + generation_id, 같은 파일에서 복합 키로 전환) | B안(레코드 내부에 versions 배열) | C안(별도 generation pool + 명시적 promotion) |
|---|---|---|---|
| 기존 Dashboard 호환성 | `find_media_archive_record()`가 content_id로 1건을 찾는 로직이 다중 매치를 처리하도록 바꿔야 함(어떤 걸 보여줄지 새 규칙 필요) | `MediaArchiveRecord` 리스트를 순회하는 모든 코드(Dashboard, blog_publish_pack, shorts_adapter, performance 등)가 새 중첩 구조를 알아야 함 — 사실상 전면 재작성 | **변경 없음** — production archive 스키마/파일이 전혀 안 바뀌므로 기존 Dashboard 코드 0줄 수정으로 계속 동작 |
| 기존 publish workflow 호환성 | `upsert_archive`의 "content_id당 1건" 불변식이 깨져 downstream(승인된 것만 골라 쓰는 스크립트들)이 어떤 걸 골라야 할지 몰라짐 | 동일 문제, 더 심각(스키마 자체가 다름) | **변경 없음** — downstream은 지금처럼 production archive만 본다 |
| 기존 archive 파일 호환성 | 기존 9건을 그대로 두되 새 레코드부터 복합 키로 취급 — 혼재 상태 관리가 까다로움 | 기존 9건을 새 중첩 스키마로 감싸야 함(최소한의 migration 필요) | **필요 없음** — production archive는 지금 스키마 그대로, 새 저장소는 완전히 별개 파일 |
| 테스트 영향 | 기존 `test_media_archive.py`의 "content_id당 1건" 전제를 검사하는 테스트들과 충돌 가능 | 광범위 | **0건 영향** — 기존 테스트가 쓰는 함수/스키마를 전혀 바꾸지 않음(추가만 함) |
| 사람이 이해하기 쉬운 구조 | "이 파일 안에서 어떤 게 활성인지" 규칙을 새로 배워야 함 | 스키마가 완전히 달라져 가장 낯섦 | "초안 더미(generation pool) → 사람이 승인 → 승격(promotion)"이라는 실제 출판 워크플로 감각과 정확히 일치 |

**C안을 선택했다.** 근거: 지시서 8장이 요구하는 "old generation + new generation이
동시에 존재"와 "production active record는 하나"라는 두 요구가 애초에 서로 다른
저장소의 역할이면 코드를 거의 바꾸지 않고 자연스럽게 만족된다 — production
archive(`data/tak_media_archive.json`)는 지금처럼 "활성 레코드 1개 = 지금
production에 있는 그 레코드"로 두고, "여러 generation의 병존"은 generation
pool이라는 별도 파일에서만 일어나게 한다. 6-05에서 이미 임시방편으로
"별도 archive 파일"을 썼는데, 이번 작업은 그 임시방편을 정식 구조(공유 스키마 +
전용 함수 + 명시적 promotion CLI)로 승격한 것이기도 하다.

## 6. generation_id 설계

`content_engine/media_archive.py::new_generation_id(knowledge_id: str) -> str`:

```
gen-<UTC 컴팩트 타임스탬프 YYYYmmddTHHMMSS>-<8자리 hex>
```

8자리 hex는 `sha256(knowledge_id + timestamp + os.urandom(8))`의 앞 8자리다.
`content_id`와 달리 **결정적(deterministic)일 필요가 없다** — generation_id는
"이 생성 시도 자체"를 가리키는 1회성 식별자이기 때문이다(같은 초 안에 같은
KNOWLEDGE를 두 번 생성해도 서로 다른 id가 나와야 하므로 `os.urandom`을 섞었다).

실행 예시(실제로 두 번 호출해 충돌 없음을 확인):

```
>>> new_generation_id('knowledge-test')
'gen-20260920T030925-7610fa05'
>>> new_generation_id('knowledge-test')
'gen-20260920T030925-073a1c60'
```

`archive_generation_report(report, path, generation_id=None)`은 `report.items`에
등장하는 **knowledge_id별로 `new_generation_id()`를 한 번씩만** 호출해, 같은
KNOWLEDGE의 이번 실행에서 나온 Blog/Shorts/Threads 9건이 모두 같은
`generation_id`를 공유하게 한다 — "이 KNOWLEDGE의 이번 생성 시도 1건"이 자연스러운
generation 단위가 되도록 하기 위함이다(테스트로 확인, 13장).

## 7. legacy compatibility

`MediaArchiveRecord.generation_id: str | None = None`(새 필드, 기본값 None)을
추가했다. `from_dict()`는 `data.get("generation_id")`로 읽으므로, 이 키 자체가
없는 기존(5-27) JSON을 읽어도 **KeyError 없이** `generation_id=None`으로
파싱된다 — 실제 production archive(`data/tak_media_archive.json`)로 회귀
테스트했다(13장, `test_real_production_archive_records_are_legacy_generations`).
`to_dict()`도 항상 `generation_id` 키를 쓰므로, 한 번이라도 새 코드로 저장된
파일은 이후 다시 읽을 때도 문제 없다. `MediaArchiveRecord.from_item()`에도
`generation_id: str | None = None` 기본 인자를 추가했을 뿐, 기존 호출부
(`archive_report()`)는 이 인자를 넘기지 않으므로 **동작이 1바이트도 바뀌지
않았다**(13장에서 기존 테스트 전체 재실행으로 확인).

## 8. review / approval / promotion 분리

2장에서 확인했듯, 기존 시스템의 "승인(review_status: unreviewed→approved)"은
이미 실제 게시(Threads/YouTube/Naver API 호출)와는 분리돼 있었다(Threads/Shorts는
승인 즉시 각자의 대기열/파일로 넘어가지만, 거기서 다시 한번 사람이 최종 승인해야
실제 발행 후보가 된다. Blog는 승인만으로는 아무 일도 안 일어나고 별도 CLI가
필요하다). 이번 6-06이 새로 분리한 것은 그 앞 단계다:

```
GENERATED (run_media_batch, generation pool에 저장)
  ↓
UNREVIEWED (review_status="unreviewed", 기본값)
  ↓ (사람이 generation pool에서 검토)
APPROVED (review_status="approved") — 아직 production에는 없음
  ↓ (사람이 promote_media_generation.py --execute 실행)
PROMOTED / ACTIVE (production archive의 그 content_id 레코드가 됨)
  ↓ (기존 시스템 그대로) 사람이 다시 승인/CLI 실행 → Threads pending / ShortsScript / Blog Pack
```

`review_status="approved"`가 곧 "production 반영"이 아니라는 것이 핵심이다 —
generation pool 안에서 승인해도 `scripts/promote_media_generation.py`를 명시적으로
실행하기 전까지는 production archive가 전혀 바뀌지 않는다(10장·11장에서 실증).

## 9. promotion CLI

`scripts/promote_media_generation.py` (신규 파일).

```
python3 scripts/promote_media_generation.py \
  --archive <generation pool 경로> \
  --production-archive <production archive 경로, 기본값 data/tak_media_archive.json> \
  --content-id <id> \
  --generation-id <generation-id> \
  [--execute]
```

핵심 함수:

- `find_active_record(production_archive_path, content_id)`: production
  archive에서 이 content_id의 현재 활성 레코드를 찾는다(없으면 None).
- `plan_promotion(generation_archive_path, production_archive_path, content_id,
  generation_id) -> (candidate, current_active)`: 순수 조회/검증 함수. **파일을
  전혀 쓰지 않는다.** 다음 중 하나라도 아니면 `PromotionError`를 던진다.
  1. `(content_id, generation_id)`가 generation pool에 정확히 존재
  2. `candidate.generation_status == "valid"`
  3. `candidate.review_status == "approved"`
- `main()`: 기본은 dry-run(계획만 출력). `--execute`를 줘야
  `upsert_archive(production_archive_path, [candidate])`를 호출한다 —
  **기존 `upsert_archive()`를 그대로 재사용**하므로 production archive의
  upsert 규칙(같은 content_id는 덮어쓰기)이 전혀 바뀌지 않는다. 이미 같은
  `generation_id`가 활성 상태면 아무것도 다시 쓰지 않고 idempotent하게 끝낸다.

이 CLI가 승인 기능을 갖지 않는다는 점이 중요하다 — `review_status`를
`approved`로 바꾸는 것은 이 스크립트의 책임이 아니다(Dashboard 등 기존 승인
경로의 역할로 남겨둔다).

## 10. dry-run 결과

임시 generation pool(`/tmp`, 실제 knowledge-scout-b28b782b2a33의 mock 재생성
결과)로 실제 CLI를 실행해 확인했다.

**1) unreviewed 상태에서 시도 → 실패, 파일 미변경**

```
오류: review_status가 'approved'가 아니면 promotion할 수 없습니다: 'unreviewed'
(content_id='content-afc6060bc1957867', generation_id='gen-...'). 이 스크립트는
승인 기능이 없습니다 - Dashboard 등에서 먼저 승인하세요.
```

**2) 승인 후 dry-run(파일 변경 없음 확인)**

```
=== MEDIA Generation Promotion [DRY-RUN (파일 변경 없음)] ===
content_id:      content-afc6060bc1957867
...
기존 production 활성 레코드: 없음 (이 content_id는 production archive에 처음 추가됨)

dry-run 완료. 실제로 반영하려면 --execute를 추가하세요.
```

dry-run 실행 후 `prod.json` 파일이 아예 생성되지 않았음을 확인했다(파일 존재
여부 자체를 확인 — dry-run은 읽기만 한다).

**3) `--execute`로 실제 반영 → 1건 생성, review_status/generation_id 그대로 기록됨**

**4) 같은 명령을 다시 `--execute`로 실행 → "이미 승격된 generation입니다. 아무것도
쓰지 않았습니다." (idempotent 확인)**

이 4단계는 그대로 `tests/test_media_versioning_and_promotion.py`의
`PromotionDryRunAndExecuteTests`로 고정했다(13장). **실제 production
archive(`data/tak_media_archive.json`)에는 이 CLI를 단 한 번도 실행하지
않았다** — 전부 `/tmp`의 임시 경로에서만 검증했다(15장).

## 11. Dashboard 변경

`scripts/run_scout_dashboard.py`에 최소 변경만 했다(대규모 재작성 없음).

- `_generation_label(record)` 함수 추가: `record.generation_id`가 있으면
  `"세대 <id> (활성)"`, 없으면 `"레거시 생성 (generation_id 없음)"`을 반환한다.
  production archive에 표시되는 레코드는 정의상 그 content_id의 현재
  활성/승격된 레코드이므로(2장에서 확인한 "content_id당 1건" 불변식), 별도의
  "active" 플래그 없이 이 레이블만으로 section 12가 요구한 정보(generation_id,
  active 여부)를 모두 표현할 수 있었다.
- `_media_card_html()`(목록 카드)과 `render_media_detail_html()`(상세 페이지
  "⑤ 생성 정보" 블록)에 이 레이블을 한 줄씩 추가했다.
- 기존 `platform`/`VALID`/`검수대기`/`승인`/`보류` 배지, 필터, 승인/보류/수정
  폼, downstream 상태 표시는 **한 글자도 바꾸지 않았다**.

`tests/test_media_dashboard.py`(기존 43개 테스트, 수정하지 않음)로 회귀 확인 —
전부 통과(14장).

## 12. 기존 9개 보존 검증

지시서 13장이 요구한 10개 시나리오를 전부 확인했다(대부분
`tests/test_media_versioning_and_promotion.py`로 고정, 일부는 6-05가 이미
검증한 것을 재확인).

| # | 시나리오 | 확인 방법 | 결과 |
|---|---|---|---|
| 1 | 기존 archive 9개 읽기 | `test_production_archive_still_has_exactly_nine_unreviewed_legacy_records` | 통과 |
| 2 | 같은 content_id로 새 generation 추가 | `test_same_content_id_different_generation_id_both_survive` | 통과 |
| 3 | 기존 9개가 사라지지 않음 | `test_new_generation_added_to_a_temp_copy_does_not_drop_existing_nine`(임시 복사본 사용, 실제 파일 미변경) | 통과 |
| 4 | 기존 review_status 유지 | `archive_generation_report`/`upsert_generation_archive`가 `archive_report`와 동일한 보존 규칙 사용(코드 리뷰 + `test_same_content_id_same_generation_id_upserts_in_place`) | 통과 |
| 5 | 새 generation은 unreviewed로 시작 | `test_items_from_one_report_share_a_generation_id`(review_status 기본값 확인 포함, 기존 `test_media_archive.py`와 동일 규칙) | 통과 |
| 6 | 새 generation이 기존 active record를 자동으로 대체하지 않음 | generation pool과 production archive가 애초에 다른 파일 — `archive_generation_report()`는 production archive를 열지도 않음(코드 검토) | 통과(구조적으로 불가능) |
| 7 | 승인되지 않은 generation은 promotion 불가 | `test_unreviewed_generation_cannot_be_promoted` | 통과 |
| 8 | rejected generation은 promotion 불가 | `test_rejected_generation_cannot_be_promoted_even_if_approved` | 통과 |
| 9 | valid+approved만 promotion 가능 | `test_approved_valid_generation_can_be_promoted` | 통과 |
| 10 | promotion 이후에도 generation history 조회 가능 | `test_generation_history_still_queryable_after_promotion` | 통과 |

## 13. 테스트 추가

신규 파일 **`tests/test_media_versioning_and_promotion.py`** (21개 테스트,
6개 클래스). 실제 LLM은 호출하지 않는다(`MockRewriteProvider`만 사용).

- `GenerationIdTests` (3): id 형식/유일성, legacy 레코드 KeyError 없음,
  실제 production archive 9건이 전부 legacy(generation_id=None)임을 확인.
- `GenerationPoolPreservesHistoryTests` (4): 같은 content_id+다른
  generation_id 동시 보존, 같은 (content_id, generation_id)는 upsert(덮어쓰기),
  이력 조회, 정확한 매칭 조회.
- `ArchiveGenerationReportRealPipelineTests` (2): 한 번의 배치가 하나의
  generation_id를 공유, **6-05에서 실제로 재현된 "9건 중 7건 content_id
  충돌" 상황을 이 저장 방식이 18건 모두 보존하는지**(핵심 회귀 테스트).
- `PromotionGatingTests` (5): unreviewed/rejected/dismissed 차단,
  존재하지 않는 generation 오류, approved+valid만 통과.
- `PromotionDryRunAndExecuteTests` (6): dry-run 미기록, execute 정확한 기록,
  중복 실행 idempotent, promotion 후 이력 조회 가능, rejected는 CLI 레벨에서도
  차단(파일 미기록).
- `ExistingProductionArchiveUntouchedTests` (2): 실제 production archive
  9건 불변 확인(읽기 전용), 임시 복사본에서의 추가가 기존 9건을 지우지 않음.

기존 테스트는 **하나도 삭제하지 않았다**. 기존 `test_media_archive.py`/
`test_media_batch.py`/`test_media_dashboard.py`와 중복되는 내용(예: content_id
단독 키 upsert 자체의 동작)은 새로 만들지 않고 그 파일들이 이미 검증하고
있음을 확인하는 선에서 그쳤다.

## 14. 전체 테스트 결과

```
840 passed, 68 subtests passed in 128.33s (0:02:08)
0 failed
```

`819`(6-05 baseline) + `21`(신규) = `840`, subtests 수 68은 그대로(신규 테스트가
`subTest`를 쓰지 않음 — 예상과 일치). 0 failed를 확인한 뒤에만 20장 이후의
commit/push를 진행했다.

## 15. production data 보호

- `data/tak_media_archive.json`은 이번 작업 동안 **읽기만** 했다(테스트에서
  `load_archive()`로 9건을 확인) — 어떤 코드 경로에서도 이 파일에 쓰지 않았다.
  promotion CLI 실증(10장)은 전부 `/tmp` 임시 경로로만 수행했다.
- 실제 LLM 호출은 **전혀 하지 않았다** — 모든 검증에 `MockRewriteProvider` 또는
  6-05가 이미 만들어 둔 결과 파일(`data/tak_media_archive_6-05_..._regeneration.json`,
  읽기만 함)을 사용했다.
- `data/tak_brain_knowledge.json`은 이번 작업에서 열지도 않았다(단, KNOWLEDGE
  레코드 조회에는 `tak_brain.load_knowledge_records()`로 읽기만 함 — 6장/16장
  참고 목적).
- Threads/YouTube/Naver 게시 관련 코드는 이번 세션에서 어떤 파일도 import하지
  않았다(`promote_media_generation.py`, `media_archive.py` 모두 게시 API를
  참조하지 않음).

## 16. 보안 검증

- 보고서·코드·테스트 어디에도 API key, refresh token, access token, secret 값,
  OAuth credential을 기록하지 않았다.
- generation_id 생성에 `os.urandom()`을 쓰지만 이 값 자체를 비밀로 취급할
  필요는 없다 — 단순히 충돌 방지용 논스이며 보고서/커밋에 그대로 노출해도
  안전하다(암호학적 비밀이 아님).
- 커밋 대상 파일에 시크릿이 없음을 `git diff --cached`로 직접 확인했다.

## 17. Commit

`git status --short`(스테이징 직전)를 확인해 이번 작업이 만든 변경만 정확히
골라 스테이징했다.

이번에도 `content_engine/__init__.py`가 6-05와 같은 문제를 안고 있었다 — 이
파일은 세션 시작 전부터 이미 미커밋 상태(youtube_publisher/shorts_script/
shorts_renderer/blog_publish_pack의 export 추가, 다른 세션의 작업)였고, 이번
작업은 여기에 `media_archive`의 새 함수 5개(`archive_generation_report`,
`find_generation_record`, `list_generations_for_content_id`, `new_generation_id`,
`upsert_generation_archive`) export만 추가했다. 6-05와 동일한 방법으로 처리했다:

```
git hash-object -w <HEAD 내용 + 이번에 추가한 10줄(import 5 + __all__ 5)만 담은 파일>
git update-index --cacheinfo 100644,<blob>,content_engine/__init__.py
```

`git diff --cached -- content_engine/__init__.py`는 10줄 추가만 보여줬고,
`git diff -- content_engine/__init__.py`(작업 트리 vs 인덱스)는 다른 세션이
추가한 80줄(youtube_publisher 등)이 그대로 미커밋 상태로 남아 있음을 확인했다.

나머지 파일은 일반적으로 스테이징했다(전부 이번 세션 시작 시점에 이미 깨끗했던
파일이거나 신규 파일이라 부분 스테이징이 필요 없었다):

```
git add content_engine/media_archive.py
git add scripts/promote_media_generation.py
git add scripts/run_media_batch.py
git add scripts/run_scout_dashboard.py
git add tests/test_media_versioning_and_promotion.py
git add docs/6-06_media_versioning_and_safe_promotion.md
```

최종 staged diff:

```
content_engine/__init__.py                   |  10 +
content_engine/media_archive.py              | 155 +++++++++++
scripts/promote_media_generation.py          | 176 +++++++++++++
scripts/run_media_batch.py                   |  31 ++-
scripts/run_scout_dashboard.py               |  12 +
tests/test_media_versioning_and_promotion.py | 372 +++++++++++++++++++++++++++
(+docs/6-06_....md)
```

`git add .`/`git add -A`는 사용하지 않았다.
`data/tak_media_archive.json`과 `data/tak_brain_knowledge.json`은 지시서 20장
지시대로 **의도적으로 staging하지 않았다**(6-05가 남긴 미커밋 상태 그대로 유지).
`.gitignore`, `content_engine/generator.py`, `content_engine/llm_provider.py`,
`content_engine/rewrite.py`, `tests/test_content_engine.py`,
`tests/test_media_batch.py`, 그리고 나머지 untracked 문서/스크립트도 이번
커밋에 포함하지 않았다.

커밋 결과:

```
[main 74c3491] feat: add media generation versioning and safe promotion
 7 files changed, 1312 insertions(+), 2 deletions(-)
 create mode 100644 docs/6-06_media_versioning_and_safe_promotion.md
 create mode 100644 scripts/promote_media_generation.py
 create mode 100644 tests/test_media_versioning_and_promotion.py
```

## 18. Push

```
$ git push
To https://github.com/sopptak/tak-auto
   a2094c4..74c3491  main -> main

$ git fetch origin   # (출력 없음)
$ git log origin/main..HEAD --oneline   # (출력 없음 — 비어 있음, origin과 완전히 동기화)

$ git status --short
```

최종 `git status --short`는 **6-05 종료 시점(및 이번 작업 시작 시점, 1장)과
정확히 동일한 파일 목록**을 그대로 출력했다 — `.gitignore`,
`content_engine/generator.py`, `content_engine/llm_provider.py`,
`content_engine/rewrite.py`, `tests/test_content_engine.py`,
`tests/test_media_batch.py`(수정됨, M), `data/tak_media_archive.json`(신규,
untracked)과 동일한 untracked 문서/스크립트 목록. `content_engine/__init__.py`도
여전히 `M`으로 표시되지만, 그 diff는 이번 커밋에 포함되지 않은 다른 세션의
80줄(youtube_publisher 등)만 남아 있다 — 이번 6-06이 추가한 10줄은 커밋에
반영됐고 인덱스에서 빠졌다(17장에서 확인한 대로). `data/tak_brain_knowledge.json`도
6-05가 남긴 상태 그대로(M) 유지된다. 즉 **이번 작업이 만든 변경(6개 파일 커밋)만
깨끗이 빠지고, 세션 시작 전부터 있던 기존 미커밋 변경은 단 한 글자도 건드리지
않은 채 그대로 남아 있음**을 확인했다.

## 19. 남은 문제

1. **`compute_content_id()`가 여전히 rewritten 텍스트를 포함하지 않는다** — 이번
   작업은 이를 바꾸지 않았다(지시서 14장: "content_id 자체를 무조건 변경하지
   않는다"). 따라서 앞으로도 "같은 content_id, 다른 generation" 상황이 계속
   생길 것이다 — 그것이 바로 이번에 만든 generation pool + promotion 구조가
   대응하려는 상황이므로 의도된 설계다.
2. **generation pool 자체를 사람이 보기 편하게 볼 UI가 없다** — 지시서 12장이
   "UI를 대규모로 다시 만들지 않는다"고 명시했으므로, 이번에는 기존
   `/media`(production archive 전용) 화면에 generation_id 표시만 추가했다.
   generation pool의 여러 generation을 나란히 비교하는 화면은 만들지 않았다
   (20장에 다음 작업으로 제안).
3. **`scripts/run_media_batch.py --as-generation --execute`는 이번 세션에서
   실제로 실행해 보지 않았다** — 절대 원칙 13(실제 LLM 호출 금지)에 따라
   `archive_generation_report()` 자체는 `run_media_batch()` + `MockRewriteProvider`
   조합으로 충분히 검증했지만(13장), CLI 전체 경로(환경변수 기반 실제
   `OpenAICompatibleRewriteProvider` 생성 포함)는 다음 작업에서 실제 재생성을
   할 때 처음 실제로 실행하게 된다.
4. **RewriteValidator의 "경험" 오탐(6-05에서 확인)은 이번에도 수정하지
   않았다**(지시서 17장 지시대로 분석만 함). `content_engine/rewrite.py`의
   `_FACT_RISK_TERMS`(51~57행)에 `"경험"`이 "성과", "수익", "매출" 등과
   함께 "사업 성과/실적 과장"을 막기 위한 범용 위험 단어 목록으로 들어 있다.
   `_fact_scope_errors()`는 이 목록의 단어가 재작성 결과에 나타나고 원문
   evidence에는 없으면 무조건 "사실 범위를 넓히는 표현"으로 판정한다
   (`content_type`/`knowledge_type`을 구분하지 않음). 우리 KNOWLEDGE의 evidence
   문장에는 "경험"이라는 단어가 없지만, LLM이 "신기술은 두려워 말고 부딪혀서
   느껴봐야 한다"를 "직접 경험이다/직접 경험"처럼 자연스럽게 의역하면서 이
   단어를 새로 등장시켜 오탐이 발생한다. 이 필터는 원래 "경험담을 지어내는 것"을
   막기 위한 것으로 보이는데, `지식_type=의견`처럼 애초에 개인 경험 서술이 아닌
   콘텐츠에서도 똑같이 적용돼 지나치게 엄격하다.
5. **`knowledge-scout-6d1d0e2fa762`는 여전히 미정정 상태**(16장·20장) — 이번
   작업 범위에서 dry-run 구조 검증만 했다.
6. **`data/tak_brain_knowledge.json`의 17개 신규 레코드가 여전히 미커밋
   상태**(6-05부터 이어짐, 이번 세션과 무관, 손대지 않음).

## 20. 다음 5~6시간 작업 제안

1. `scripts/run_media_batch.py --as-generation --id knowledge-scout-6d1d0e2fa762`로
   (article_type 정정 후) 실제 LLM 재생성을 generation pool에 수행 — 6-05와
   동일한 절차를 이번에 만든 정식 구조로 반복.
2. generation pool 전용 최소 조회 화면(또는 기존 Dashboard에 `/media/generations?content_id=...`
   같은 읽기 전용 라우트 1개) 추가 — "이 content_id의 generation 이력을 나란히
   비교"할 수 있게. 대규모 UI가 아니라 `list_generations_for_content_id()`를
   그대로 테이블로 뿌리는 수준으로 충분.
3. `_FACT_RISK_TERMS`를 `article_type`/`knowledge_type`별로 세분화하는 설계
   검토(19-4장) — 예: "경험"은 `knowledge_type != "경험"`이고 사업 성과 맥락이
   아니면 위험 단어에서 제외하는 등.
4. 사람이 generation pool에서 승인한 뒤 `scripts/promote_media_generation.py
   --execute`로 실제 production archive에 처음으로 promotion을 실행 — 이번
   작업은 구조만 만들고 실제 반영은 하지 않았다.
5. `scripts/prepare_approved_media.py` 같은 기존 오케스트레이터가
   generation pool의 승인된 항목을 자동으로 promotion까지 이어줄지, 아니면
   지금처럼 별도 CLI로 분리된 채 둘지 결정 — 이번 작업은 "승인이 곧 promotion이
   아니다"라는 원칙을 지키기 위해 의도적으로 자동 연결하지 않았다.

## 결론

- **같은 content_id를 가진 서로 다른 generation을 동시에 보존**: `archive_generation_report()`/
  `upsert_generation_archive()`가 `(content_id, generation_id)` 복합 키로
  동작함을 실제 6-05 데이터(9건 중 7건 충돌)로 재현·검증했다(13장,
  `test_regenerating_under_different_profile_keeps_both_generations_even_when_content_id_collides`).
- **기존 production archive 9개 무변경**: 이번 세션 동안 그 파일은 읽기만
  했고, 최종 테스트에서도 9건·전부 legacy(`generation_id=None`)임을 재확인했다.
- **승인되지 않은/거절된 generation은 promotion 불가, approved+valid만 가능**:
  `plan_promotion()`이 세 조건을 모두 강제하며, CLI 레벨(`main()`)에서도
  동일하게 차단됨을 실제로 실행해 확인했다.
- **기존 Dashboard/publish workflow 무변화 + legacy archive 로딩**: 기존
  43개 Dashboard 테스트, 기존 media archive/batch 테스트가 수정 없이 모두
  통과했고, generation_id 없는 실제 production 레코드도 KeyError 없이 읽힌다.
- **전체 pytest 0 failed, 실제 LLM 호출 없이 구조 검증 완료**: 840 passed,
  68 subtests, 0 failed.

### Before

```
content_id  ──유일 키──>  MediaArchiveRecord (review_status, generation_status 포함)
```
"이 content_id의 레코드"는 언제나 정확히 1개뿐이었고, 재실행은 곧 덮어쓰기였다.

### After

```
generation pool (여러 파일 가능, (content_id, generation_id) 복합 키)
  content_id=X, generation_id=A  (review_status=approved, generation_status=valid)
  content_id=X, generation_id=B  (review_status=unreviewed, generation_status=valid)
  content_id=X, generation_id=C  (review_status=approved, generation_status=rejected)
        │
        │  scripts/promote_media_generation.py
        │  (조건: generation_status=="valid" AND review_status=="approved"만 통과)
        ▼
production archive (content_id 유일 키, 기존 구조 그대로)
  content_id=X  ──→  generation_id=A였던 레코드 (지금의 "활성" 레코드)
```

`content_id`는 여전히 "콘텐츠 슬롯/내용 식별자"라는 원래 의미를 유지하고,
`generation_id`는 그 위에 "몇 번째 생성 시도인가"를 얹는 별도 축이다.
`review_status`(사람 검수)와 "production에 있다/승격됐다"(promotion) 역시
generation pool과 production archive라는 서로 다른 파일로 물리적으로 분리했다.
