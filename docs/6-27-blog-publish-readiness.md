# 6-27 Blog Publish Readiness

## 1. 목적

6-24 Production Readiness Audit(`docs/6-24-production-readiness-audit.md`
12장, 18장 P1)에서 확인된 Blog 관련 문제를 실제 코드 기준으로 정리하고,

```
KNOWLEDGE -> MEDIA Generation -> Human Review -> Production Archive
-> Publish Readiness -> Blog Draft/Publish Pack -> Human Copy/Paste Publish
-> Publish Audit
```

경로를 하나의 명확한 운영 흐름으로 정리한다. Naver 공식 글쓰기 API가 없는
현재 정책(docstring 여러 곳에 이미 명시)을 그대로 존중한다 - 이번 작업은
"사람이 안전하게 최종 게시할 수 있는 Publish Pack"을 운영 가능하게 만드는
것이지, Naver 게시를 자동화하는 것이 아니다. 브라우저 자동화/쿠키/비공식
API를 이번에도 만들지 않았다(17장에서 소스 레벨로 재확인).

## 2. 전체 Blog 경로

3장 조사(실제 import/호출 관계) 결과, Threads(6-25)와 달리 **레거시/중복
경로가 없다** - YouTube(6-26)와 같은 상황이다.

```
data/tak_media_archive.json(platform=="blog", approved)
  -> Dashboard "/media" 승인 (또는 scripts/generate_blog_publish_pack.py --from-archive)
  -> content_engine.blog_publish_pack.build_blog_publish_pack_from_archive()
  -> data/blog_publish_pack_daily.md (Publish Pack, 매 실행마다 덮어씀)
  -> 사람이 직접 네이버 블로그에 복사/붙여넣기 + 예약 발행
  -> scripts/mark_blog_published.py [6-27: Production Archive 재검증 추가]
  -> data/blog_publish_log.json
  -> scripts/audit_publish_candidates.py (Publish Audit, 재확인용)
```

**레거시 하위 경로**: `generate_blog_publish_pack.py --generate-without-review`
(6-14가 이미 기본 실행에서 차단, 명시적으로 플래그를 줘야만 동작 - 아래
4장 참고)는 `--from-archive`와 별개로 여전히 존재하지만, 실제 자동화
워크플로우(`prepare_approved_media.py`, `.github/workflows/daily-media-prepare.yml`)는
**항상 `--from-archive`만 쓴다**(코드로 확인, `prepare_approved_media.py:113`).
GitHub Actions 자동 Naver 게시(PATH C)는 존재하지 않는다.

## 3. Blog Draft

**"Blog Draft"라는 별도 아티팩트 파일은 없다** - Shorts의
`data/shorts_scripts/<content_id>.json`, Threads의
`data/tak_threads_pending.json`과 달리, Blog는 `MediaArchiveRecord`의
`final_title`/`final_body`를 **그 자리에서 직접** `BlogPublishItem`으로
변환한다(`build_blog_publish_pack_from_archive()`). 별도 draft 파일이
존재한 적이 없으므로 `data/blog_drafts/`는 이 코드베이스 어디에도
참조되지 않는다(6-21에서 이미 확인, 재확인 - grep 결과 0건).

**이것이 5장의 D(ShortsScript 없음)/E(content_id mismatch)/6(ShortsScript
missing)/7(content_id mismatch) 시나리오가 Blog에는 적용되지 않는 이유다** -
비교할 "별도 아티팩트"가 원천적으로 없다. Production Archive 레코드
자체가 유일한 source다.

## 4. Publish Pack

`content_engine/blog_publish_pack.py`를 전부 읽었다. 핵심 함수
`select_approved_blog_candidates_from_archive()`가 이미 확인하는 것
(변경 없음, 재확인):

```python
record.platform == "blog"
and record.generation_status == "valid"
and record.review_status == "approved"
and record.content_id not in published_ids
```

**"Pack이 만들어졌다"와 "게시해도 된다"를 동일시하지 않는가?** 확인
결과 `select_approved_blog_candidates_from_archive()` 자체는 이 원칙을
지킨다 - `review_status == "approved"`라는 동등 비교이므로, supersede로
`review_status`가 `"superseded"`로 바뀐 레코드는 **다음 Pack 생성 시점에는**
자동으로 제외된다(별도 supersede 검사 없이도 안전 - 6-19가 이미 이렇게
결론 냈다, `content_engine/publish_eligibility.py` 모듈 docstring 참고).
**그러나** 이미 만들어진 **과거의** Pack 파일(Markdown)은 생성 시점의
스냅샷일 뿐이다 - 생성 후 Production 상태가 바뀌어도 그 파일 내용은
저절로 갱신되지 않는다. 이것이 6-27이 실제로 다뤄야 하는 문제였다(6장/10장).

**CLI 안전장치(6-14, 재확인, 변경 없음)**: `generate_blog_publish_pack.py`는
`--from-archive` 또는 `--generate-without-review` 중 하나를 명시하지 않으면
실행 자체를 거부한다(콘텐츠 단위 승인 없이 Pack이 만들어지는 것을 막음).

## 5. Production Archive

`load_archive()`, `MediaArchiveRecord`, `find_production_record()`를 그대로
재사용했다(6-19/6-06). 새로운 eligibility 로직을 만들지 않았다(6장에서
자세히).

**⚠️ 6-27에서 발견·수정한 P0(6-24와 동일 클래스)**: `generate_blog_publish_pack.py`의
레거시 경로(`--generate-without-review`)가 `archive_report()`를 직접
호출하면서 6-24에서 추가한 `find_protected_overwrite_targets()` 가드를
거치지 않고 있었다 - `scripts/run_media_batch.py`/`scripts/run_daily.py`에만
그 가드가 적용되어 있었고, 이 파일은 6-24 조사에서 누락됐다. 이미
approved/superseded인 content_id를 이 레거시 경로로 재실행하면 승인된
문구가 조용히 최신 LLM 결과로 바뀔 수 있었다(6-24 4장과 동일한 문제).
이번에 같은 가드를 추가했다. **동일 문제가 `generate_threads_draft.py`,
`scripts/tak_auto.py`에도 남아 있다** - 이번 6-27 범위(Blog)에서는
`generate_blog_publish_pack.py`만 수정했고, 나머지 둘은 19장(향후 작업)에
기록했다(Threads/전체 오케스트레이터는 이번 작업 범위 밖).

## 6. Publish Eligibility

**공식 Blog Publish Contract(지시사항 4장 12개 조건)**:

| # | 조건 | 구현 |
|---|---|---|
| 1 | content_id 존재 | `MediaArchiveRecord.content_id`(항상 존재) |
| 2 | Production Archive record 존재 | Pack 생성: 레코드 자체가 입력이므로 자동 만족. `mark_blog_published.py`: `find_production_record()`로 확인(6-27 신규, 9장) |
| 3 | review_status == approved | `select_approved_blog_candidates_from_archive()`(기존) / `mark_blog_published.py`(6-27 신규) |
| 4 | generation_status 유효 | `generation_status == "valid"` 필터(기존) |
| 5 | superseded 아님 | 3번과 동일한 등호 비교로 자동 충족(4장 설명) |
| 6 | title 존재 | `record.final_title`(빈 문자열이면 렌더링에 그대로 드러남 - 별도 검증 없음, 기존 동작) |
| 7 | body 존재 | 동일 |
| 8 | source_url 존재 또는 허용 | `record.source_url`을 그대로 씀(별도 필수 검증 없음, 기존 동작 - `publish_audit.py`의 BLOCKED 판정과 달리 Pack 생성 자체는 빈 source_url을 막지 않는다, 20장 위험) |
| 9 | Publish Readiness가 허용 | `content_engine.publish_audit.audit_record()`가 이미 blog를 다룬다(6-14, 변경 없음) - `scripts/audit_publish_candidates.py`로 별도 실행 가능 |
| 10 | 이미 게시된 콘텐츠가 아님 | `PublishHistory.is_published()`(기존) |
| 11 | duplicate publish 아님 | 10번과 동일 |
| 12 | required evidence/source 정보 | `record.evidence`/`evidence_unit_ids`는 Pack에 렌더링되지 않는다(사람이 읽는 문서에는 source_url만 노출 - 기존 설계, 15장에서 상세) |

**새 중복 eligibility 로직을 만들지 않았다**: `find_production_record()`
(6-19)를 `mark_blog_published.py`에 재사용했을 뿐이다(6-25/6-26과 동일
패턴).

## 7. Human Publish Contract

지시사항 11장의 8단계를 코드 동작과 대조했다 - **이미 정확히 이 순서를
강제하는 구조였다**(이번에 순서를 바꾸지 않음, 재확인):

1. Publish Readiness 실행(`scripts/audit_publish_candidates.py`) - 선택 사항이지만 권장.
2. READY 확인 - 사람이 직접 결과를 읽는다(자동 판단 없음).
3. Publish Pack 생성(`--from-archive`) - approved만 후보가 됨(6장).
4. 제목/본문/source 확인 - Pack Markdown에 전부 렌더링됨(review_required 체크박스 포함).
5. 사람이 Naver Blog에서 게시 - **이 저장소 어떤 코드도 이 단계를 수행하지 않는다**(17장).
6. 실제 게시 성공을 사람이 확인 - 마찬가지로 검증 불가능한 인간 행위.
7. `mark_blog_published.py` 실행 - **6-27부터 Production Archive 상태를
   재검증한다**(9장) - 4단계 이후 상태가 바뀌었으면(superseded 등) 여기서
   차단된다.
8. Publish Audit 재실행 - 선택 사항, 권장.

**단계 중 하나라도 실패하면 자동으로 published 처리하지 않는다**: 7번이
실패(차단)하면 `history.append()`에 도달하지 않으므로 그 자체로 이 원칙이
지켜진다(코드 순서 확인).

## 8. Publish History

`data/blog_publish_log.json`(`content_engine/publish_history.py`의
`PublishHistory`/`PublishRecord`를 Threads와 동일하게 재사용, 별도 파일만
분리 - 기존 구조, 변경 없음)를 확인했다. `content_id`/`knowledge_id`/
`source_url`/`published_at`은 저장되지만 **`generation_id`는 저장되지
않는다**(`PublishRecord`에 그런 필드 자체가 없음, Threads/Blog 공용
스키마이므로 이번에 Blog만을 위해 추가하지 않았다 - 최소 변경 원칙, 12장
stale 판정은 content_id만으로 충분하다고 판단했다).

**이미 게시된 content_id 재게시 방지**: `is_published()`(기존, `PublishHistory`
공용) - 확인 완료.

## 9. mark_blog_published.py

**집중 조사 결과(지시사항 10장)**: 이 스크립트는 원래 `--content-id`
인자를 **전혀 검증하지 않고** 그대로 이력에 기록했다 - 오타, 잘못된
content_id, 아직 승인되지 않은 content_id, 심지어 superseded된
content_id도 아무 경고 없이 "게시 완료"로 기록될 수 있었다. **사람이
실수로 순서를 착각해 이 스크립트를 먼저 실행하면, 실제로 게시하지 않은
콘텐츠가 영구히 "이미 게시됨"으로 처리되어 이후 Pack에서 조용히
제외된다** - 지시사항이 우려한 바로 그 시나리오가 실제로 가능했다.

**이번에 추가한 최소 안전장치**: `--production-archive`(기본값
`data/tak_media_archive.json`)를 새로 받아, `find_production_record()`로
content_id가 존재하고 `review_status == "approved"`인지 확인한다(6-19
헬퍼 재사용, 새 로직 아님). 없으면 ORPHAN, approved가 아니면(unreviewed/
dismissed/superseded) 차단한다. `--content-id`는 원래부터 필수 인자였고
"임의 콘텐츠를 자유롭게 기록"하는 정당한 사용례가 없으므로(YouTube의
`--video` 자유 업로드와 달리), 이 검사를 선택적(opt-in)이 아니라 기본
동작으로 만들었다.

**이 스크립트가 여전히 할 수 없는 것(문서화 요구사항)**: **실제로 네이버
블로그에 게시가 됐는지는 API로 절대 확인할 수 없다.** Naver 공식 글쓰기
API가 없다는 프로젝트 정책(1장) 자체가 이 한계의 근본 원인이다 - 이번에
추가한 검증은 "이 content_id가 기록해도 되는 정당한 대상인가"(존재+승인
여부)만 확인할 뿐, "사람이 정말로 Naver에 게시를 마쳤는가"는 여전히
100% 사람의 신고를 신뢰한다. 이 한계는 기술적으로 해소할 방법이 없다 -
공식 API가 생기기 전에는 구조적으로 불가능하다.

## 10. Stale Pack

지시사항 12장의 문제(Pack 생성 9/20 → Production 변경 9/22 → 사람 게시
9/23)를 조사했다.

**이번에 구현한 최소 대응**: `_render_item()`(`content_engine/blog_publish_pack.py`)이
`content_id`를 Markdown 출력에 새로 노출한다(이전에는 `BlogPublishItem.content_id`가
데이터에는 있었지만 **사람이 보는 문서에는 렌더링되지 않았다** - 그래서
사람도, 어떤 재확인 스크립트도 "이 Pack의 이 항목이 지금 archive에서
어떤 상태인지" 조회할 방법이 없었다). 이제 Pack의 각 항목에서 content_id를
직접 읽어 `scripts/audit_publish_candidates.py --archive <경로>`(기존
CLI, 새로 만들지 않음)를 다시 실행해 그 content_id의 **현재** 상태를
확인할 수 있다.

**새로운 DB/hash 시스템을 만들지 않은 이유**: "production revision/hash"를
Pack에 심으려면 archive 전체를 해싱해 저장하는 새 메커니즘이 필요한데,
이는 이미 있는 `content_id` + 기존 `audit_publish_candidates.py` 조합으로
같은 목적(재확인)을 달성할 수 있어 불필요한 복잡도라고 판단했다(24장
원칙). `generation_id`도 같은 이유로 Pack/history 스키마에 추가하지
않았다 - Blog는 Threads/Shorts와 달리 **한 content_id당 활성 레코드가
정확히 하나**(6-06 promotion 규칙)이므로, content_id만으로 "이 슬롯의
지금 상태"를 완전히 특정할 수 있다.

## 11. SUPERSEDED 보호

지시사항 13장의 시나리오(Pack 생성 → Production SUPERSEDED → 사람이 old
pack을 게시하려 함)를 정확히 테스트했다
(`tests/test_blog_publish_readiness.py`의
`test_pack_built_then_superseded_then_mark_published_is_blocked`):

1. Pack 생성 시점: `c1`이 approved라 정상 후보.
2. 그 사이 `c1`이 `c2`로 supersede됨.
3. 사람이 (이미 손에 들고 있던 stale pack을 보고) `mark_blog_published.py
   --content-id c1`을 실행 → **차단됨**(exit 1, history 미기록).
4. 대체품 `c2`는 정상적으로 기록 가능(대체 자체는 막지 않음).

**결과**: 자동 publish 없음(애초에 이 저장소는 자동 publish를 하지
않음), published 자동 기록 없음(위에서 확인), old pack 자동 삭제 없음
(`save_markdown()`은 기존과 동일하게 파일을 덮어쓸 뿐 삭제 로직 자체가
없다 - "역사 보존"이라는 개념이 애초에 이 파일 하나짜리 휘발성 설계에는
적용되지 않는다, 아래 14장에서 상세).

## 12. Same content_id 보호

Production Archive 쓰기 시점(6-18 `check_promotion_conflict()`, 6-24
`find_protected_overwrite_targets()`)에서 이미 보호된다 - Blog Pack은
그 archive를 **읽기만** 하므로, "Pack의 content_id=X generation_id=B"가
"Production의 X=A"와 다른 상황 자체가 상위 계층에서 이미 막혀 있어야
정상이다(6-25/6-26과 동일 결론). 이번에 Blog 레벨에서 별도 검사를
추가하지 않았다 - 이미 존재하는 불변조건이기 때문이다.

## 13. Source / Evidence

**finance template contamination 재발 여부(지시사항 15장)**: 6-15에서
이미 완전히 해결됐고(`docs/6-15_data_integrity_and_publish_readiness_report.md`,
6-24 감사에서도 재확인) regression test(`tests/test_article_types.py`,
`tests/test_critical_content_replacement_audit.py`)가 계속 지키고 있다.
Blog 전용 민감 콘텐츠 판정(`is_review_required()`,
`content_engine/blog_publish_pack.py`)은 `knowledge.article_type`/
`category`/`domain`만 읽고 새로 분류하지 않는다 - **category/domain/
article_type이 서로 섞일 여지가 구조적으로 없다**(각각 다른 필드, 다른
용도로만 쓰임, 코드 재확인). 이번에 새로 발견한 교차 오염 문제는 없었다.

**source URL/evidence 보존**: `record.source_url`이 `BlogPublishItem.source_url`로
그대로 전달되고 Markdown에 렌더링된다(기존, 변경 없음). `evidence`/
`evidence_unit_ids`는 Pack에 렌더링되지 않는다(기존 설계 - Blog Pack은
사람이 읽을 최종 문구만 보여주고 근거 원문 조각은 보여주지 않는다) - 이는
결함이 아니라, `record.evidence`가 Production Archive에 이미 보존되어
있고 필요하면 archive를 직접 조회하면 되기 때문이다(중복 표시 불필요).

## 14. Dashboard

`scripts/run_scout_dashboard.py`의 `compute_media_downstream_status()`
(6-13, 6-25/6-26에서 이미 확인한 것과 같은 함수)를 재확인했다. Blog
레코드에 대해 이미 표시하는 것(변경 없음):

- "승인 전" / "승인됨 (Pack 생성 가능)" / "게시 기록됨"(마크 완료 시)

**빠진 정보(지시사항 18장 체크리스트 대비)**: Publish Pack Ready(pack에
실제로 포함됐는지 여부, "승인됨"과는 다른 개념)와 Superseded, Stale을
별도로 표시하지 않는다 - 6-25(Threads)/6-26(YouTube)에서 발견한 것과
같은 종류의 gap이다. **이번에도 UI를 고치지 않았다** - 세 플랫폼(Threads/
Shorts/Blog) 모두 같은 gap이 반복되므로, 개별 플랫폼마다 따로 고치기보다
`compute_media_downstream_status()` 자체를 한 번에 개선하는 것이 더
합리적이라 판단했고, 이는 "UI 전면개편 금지" 범위를 넘어설 수 있어 이번
세션에서 시도하지 않았다(20장 향후 작업).

## 15. GitHub Actions / Artifact

`.github/workflows/daily-media-prepare.yml`을 재조사했다(6-21/6-24가
이미 확인한 내용과 일치):

- `data/blog_publish_pack_daily.md`는 **git에 커밋되지 않는다** - 매 실행
  워크플로우 아티팩트(`blog-publish-pack-daily`, retention 14일)로만
  보관된다(주석이 이미 명시: "휘발성 결과물, git에 커밋하지 않음").
- `prepare_approved_media.py`가 항상 `--from-archive`로 호출한다(2장에서
  확인) - LLM 호출도, `archive_report()` 쓰기도 이 경로에서는 발생하지
  않는다(읽기 전용).

**"Blog draft는 Git에 저장하지 않고 artifact로 보관하는 정책"과
"Production Archive source of truth 정책"이 충돌하지 않는가?**
충돌하지 않는다 - source of truth는 어디까지나 Production Archive
(`data/tak_media_archive.json`)이고, Pack은 그 archive에서 **파생된
휘발성 렌더링 결과**일 뿐이다(3장에서 확인했듯 별도 draft 아티팩트 개념
자체가 없다). Pack을 git에 커밋하지 않아도 정보 손실이 없다 - archive만
있으면 언제든 Pack을 다시 만들 수 있다(멱등적 재생성, 4장/`tests/test_blog_publish_readiness.py`의
`PackRegenerationIdempotencyTests`가 이를 확인한다).

## 16. Security

read-only로 확인했다(실제 값은 읽지 않았다):

- Blog Pack(`BlogPublishItem`)에 포함되는 필드: title/body/category/
  keywords/hashtags/image_ideas/knowledge_id/source_url/content_id -
  API key/token/OAuth secret/개인정보/내부 경로/운영 메모가 들어갈 필드
  자체가 없다(dataclass 정의 확인).
- `content_engine/blog_publish_pack.py`, `scripts/generate_blog_publish_pack.py`,
  `scripts/mark_blog_published.py` 어디에도 환경변수(secrets)를 읽는
  코드가 없다 - Blog 경로에는 애초에 인증이 필요한 외부 API가 없기
  때문이다(1장 정책과 일치).
- `tests/test_blog_publish_readiness.py`의
  `test_blog_modules_never_reference_browser_or_naver_login_automation`이
  브라우저 자동화/쿠키/비공식 API 관련 문자열이 이 세 모듈 소스에 전혀
  없음을 회귀로 고정한다.
- 이 문서와 테스트는 실제 KNOWLEDGE/Production Archive 데이터를 전혀
  읽지 않았다(전부 synthetic fixture).

## 17. Synthetic E2E

지시사항 16장의 20개 시나리오를 조사·테스트했다.

| # | 시나리오 | 결과/구현 위치 |
|---|---|---|
| 1 | approved+valid → READY | `select_approved_blog_candidates_from_archive` 기존 테스트(변경 없음) |
| 2 | unreviewed → BLOCK | 기존 `test_only_approved_blog_records_become_candidates` |
| 3 | dismissed → BLOCK | 같은 테스트 |
| 4 | superseded → BLOCK | 4장에서 설명(등호 비교로 자동 충족) + 기존 6-19 `test_old_blog_is_excluded_from_publish_pack` |
| 5 | production missing → ORPHAN | Pack 생성: 해당 없음(레코드가 입력 자체). `mark_blog_published.py`: 신규 `test_missing_production_record_is_orphan_blocked` |
| 6 | blog draft missing → MISSING_ARTIFACT | 해당 없음(3장 - 별도 draft 파일 개념 자체가 없음) |
| 7 | content_id mismatch → CONFLICT | 해당 없음(3장, 같은 이유) |
| 8 | generation mismatch → CONFLICT | 상위 계층(6-18/6-24)이 이미 보장(12장) |
| 9 | already published → ALREADY_PUBLISHED | 기존 `test_already_published_content_id_is_excluded` |
| 10 | valid publish pack → READY_FOR_HUMAN_PUBLISH | 4장/7장에서 설명(개념적으로 이미 성립) |
| 11 | stale publish pack → REVIEW/BLOCK | 10장(content_id 노출 + audit 재실행 절차) |
| 12 | production superseded after pack creation → final recheck BLOCK | 신규 `test_pack_built_then_superseded_then_mark_published_is_blocked` |
| 13 | same content_id different generation → CONFLICT | 12장(상위 계층이 이미 보장) |
| 14 | source_url mismatch → 기존 policy | 해당 없음(6장 조건 8 - 별도 아티팩트가 없어 mismatch 자체가 불가능) |
| 15 | mark_blog_published without valid production → BLOCK | 신규 `test_missing_production_record_is_orphan_blocked` |
| 16 | mark_blog_published twice → idempotent | 기존 `test_marking_twice_is_idempotent`(archive fixture 추가, 변경 없이 통과) |
| 17 | mark_blog_published for superseded → BLOCK | 신규 `test_superseded_record_is_blocked` |
| 18 | publish failure → history 기록 없음 | 신규 `test_history_append_failure_does_not_report_success` |
| 19 | dry-run → 실제 외부 API 0 | 해당 없음/자명(Blog 경로에는 애초에 외부 API 호출이 없음, 16장에서 소스 레벨 확인) |
| 20 | publish pack overwrite → 기존 pack 안전 보호 | 신규 `PackRegenerationIdempotencyTests`(2건) - 재생성해도 미게시 후보가 사라지지 않음을 확인 |

**전체 결과**:

| 구분 | 결과 |
|---|---|
| 신규(`tests/test_blog_publish_readiness.py`) | 5 passed |
| 신규(`tests/test_blog_publish_pack.py`에 추가) | 11 passed(`MarkBlogPublishedEligibilityGateTests` 5건 + `GenerateBlogPublishPackOverwriteGuardTests` 2건 신규+3건 상속 + content_id 노출 테스트 1건) |
| 갱신(기존 `MarkBlogPublishedScriptTests` 2건) | 2 passed(archive fixture 추가, 결과 동일) |
| 6-19 회귀 | 21 passed(변경 없음) |
| 전체(`python -m unittest discover -s tests -p "test_*.py"`) | **1048 passed(1031 실행+17 skip), 0 failed, 0 errors** — 6-26 종료 1032개에서 이번에 추가한 16개와 정확히 일치 |

## 18. 실제 Blog 게시 전 체크리스트

```
[ ] git fetch && git status로 최신 상태 확인
[ ] python scripts/audit_data_state.py로 Production Archive 상태 확인
[ ] python scripts/audit_publish_candidates.py --archive data/tak_media_archive.json
    로 Publish Readiness 확인(READY 항목 파악)
[ ] python scripts/generate_blog_publish_pack.py --from-archive
    로 Publish Pack 생성(data/blog_publish_pack_daily.md)
[ ] Pack의 각 항목에서 제목/본문/source_url/content_id 확인
[ ] (게시 직전, 시간이 좀 지났다면) python scripts/audit_publish_candidates.py를
    다시 실행해 해당 content_id들이 여전히 READY인지 재확인(stale pack 방지, 10장)
[ ] 사람이 네이버 블로그에서 직접 게시(카테고리/예약 발행 포함)
[ ] 실제 게시 성공을 사람이 직접 확인
[ ] python scripts/mark_blog_published.py --content-id <id> \
        --production-archive data/tak_media_archive.json
    (6-27: 이제 archive에서 approved/not-superseded인지 재검증한다)
[ ] python scripts/audit_publish_candidates.py로 재실행해 최신 상태 확인
[ ] git add data/blog_publish_log.json && git commit && git push
```

이번 6-27 범위에서 위 절차를 실제로 실행하지 않았다.

## 19. 남은 위험

- **5장**에서 발견한 대로, `generate_threads_draft.py`와
  `scripts/tak_auto.py`에 동일한 P0급 패턴(`archive_report()` 직접
  호출, `find_protected_overwrite_targets()` 가드 없음)이 남아있다 -
  이번 Blog 범위에서는 `generate_blog_publish_pack.py`만 고쳤다.
- **14장**에서 확인한 Dashboard 표시 gap(Superseded/Stale/Publish Pack
  Ready 배지 없음)은 Threads(6-25)/YouTube(6-26)에서도 동일하게 발견된
  반복 패턴이다 - 개별 수정보다 `compute_media_downstream_status()`
  자체의 통합 개선이 필요해 보인다.
- **6장 조건 8**: Pack 생성 자체는 빈 `source_url`을 막지 않는다(기존
  동작) - `publish_audit.py`의 BLOCKED 판정과 달리 Pack 생성 단계는
  이 필드를 검증하지 않는다. 실무상 KNOWLEDGE 생성 단계에서 이미
  source_url이 보장되므로 지금까지 문제가 되지 않았지만, 방어적 검증은
  아니다.
- **10장**: stale pack 판정은 사람이 `audit_publish_candidates.py`를
  "다시 실행해야 한다"는 절차적 안전장치일 뿐, 자동으로 강제되지 않는다 -
  사람이 이 단계를 건너뛰면 여전히 stale pack을 시도할 수 있다(단,
  `mark_blog_published.py`의 새 게이트가 최종 방어선 역할을 한다, 11장).

## 20. 향후 작업

- `generate_threads_draft.py`/`scripts/tak_auto.py`에
  `find_protected_overwrite_targets()` 가드 적용(19장).
- `compute_media_downstream_status()`를 Threads/Shorts/Blog 공통으로
  Superseded/Stale 배지를 보여주도록 개선(14장, 6-25/6-26과 함께 검토).
- Blog Pack 생성 시 `source_url` 필수 검증 추가 검토(19장).
- Naver 공식 글쓰기 API가 실제로 제공되면(현재는 없음), 이 문서의 1장
  정책 자체를 재검토해야 한다 - 그 전까지는 사람이 직접 게시하는 현재
  구조를 유지한다.
