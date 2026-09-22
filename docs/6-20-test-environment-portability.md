# 6-20 Test Environment Portability

## 1. 목적

Production Archive(`data/tak_media_archive.json`) 등 실제 운영 산출물이 없는 새
환경(이 세션에서는 "노트북2", 새로 clone한 저장소)에서 `python -m unittest discover
-s tests -p "test_*.py"`를 실행했을 때 발생한 5 failed / 2 errors를, "이 환경에만
없는 운영 데이터 때문에 생기는 정상적인 차이"와 "실제 코드/테스트 문제"로 정확히
구분하고, 후자만 코드/테스트 수정으로 고친다. Production Archive를 새로 만들거나
복구하는 작업은 이번 범위에 포함하지 않는다.

## 2. 노트북2에서 발견된 테스트 문제

- 이 환경에는 `data/tak_media_archive.json`, `data/tak_media_generation_*.json`,
  `data/shorts_scripts/`, `data/blog_drafts/`가 없다.
- `data/tak_brain_knowledge.json`, `data/tak_threads_pending.json`은 git에
  커밋되어 있어 존재한다.
- `git log --all -- data/tak_media_archive.json`으로 확인한 결과, 이 파일은
  **main 브랜치 어떤 커밋에도 실제로 커밋된 적이 없다.** `.gitignore`에는
  `!data/tak_media_archive.json` 예외 규칙과 "사람이 승인 후 직접 커밋/푸시해야
  GitHub Actions 러너의 새 checkout에서도 이 상태가 보인다"는 주석이 있어,
  이 파일이 커밋되는 것이 문서화된 의도임을 알 수 있다. 그러나 실제로는 한 번도
  커밋되지 않았다 — 즉 CI(GitHub Actions) 러너에서 새로 checkout해도 이 파일은
  없고, 이번에 실패한 4개 회귀 테스트는 CI에서도 동일하게 실패했을 것으로
  추정된다(단, 이 저장소에는 `gh` CLI가 없어 실제 워크플로 실행 로그로 직접
  확인하지는 못했다 — 추정임을 명시한다). 이 불일치 자체는 6-20 범위 밖의 별도
  운영 프로세스 이슈로, 이번에는 고치지 않았다(11장 참고).

## 3. 실패/오류 7개 분류

1.
- 테스트: `test_media_versioning_and_promotion.GenerationIdTests.test_real_production_archive_records_are_legacy_generations`
- 원인: `PRODUCTION_ARCHIVE_PATH`(`data/tak_media_archive.json`)를 읽어 legacy(
  generation_id 없음) 레코드 수가 9건인지 확인. 파일이 없어 `load_archive()`가
  빈 목록을 반환 → 기대값 9, 실제값 0.
- 분류: A (Production Archive 부재로 인한 환경 제한)
- 조치: `PRODUCTION_ARCHIVE_PATH.exists()`가 거짓이면 건너뛰는
  `@unittest.skipUnless`를 메서드에 추가. 파일이 있는 환경에서는 그대로 실행되어
  9건 검증을 계속 수행한다.

2.
- 테스트: `test_media_versioning_and_promotion.ExistingProductionArchiveUntouchedTests.test_production_archive_still_has_exactly_nine_unreviewed_legacy_records`
- 원인: 동일 파일을 읽어 legacy 9건을 확인. 기대값 9, 실제값 0.
- 분류: A
- 조치: 클래스 전체(`ExistingProductionArchiveUntouchedTests`)에
  `@unittest.skipUnless`를 적용. 같은 클래스의 다른 메서드
  (`test_new_generation_added_to_a_temp_copy_does_not_drop_existing_nine`)는
  파일이 없으면 `original`이 빈 목록이 되어 "0건 + 1 = 1건"으로 우연히
  통과(vacuous pass)하고 있었는데, 이는 "기존 9건이 보존된다"를 실제로 검증한
  것이 아니므로 함께 skip 처리해 거짓 통과를 없앴다.

3.
- 테스트: `test_same_content_id_overwrite_protection.ExistingProductionArchiveReadOnlyRegressionTests.test_real_production_archive_still_has_eighteen_records`
- 원인: 동일 파일을 읽어 전체 레코드 수 18건을 확인. 기대값 18, 실제값 0.
- 분류: A
- 조치: 클래스 전체에 `@unittest.skipUnless` 적용.

4.
- 테스트: `test_same_content_id_overwrite_protection.ExistingProductionArchiveReadOnlyRegressionTests.test_known_forbidden_content_id_is_untouched_and_still_approved`
- 원인: 동일 파일을 읽어 특정 content_id(`content-5971ed5204437cdd`)가
  `approved` 상태로 존재하는지 확인. 기대값: 존재. 실제값: 빈 dict(파일 없음).
- 분류: A
- 조치: 3번과 같은 클래스이므로 같은 클래스 단위 skip으로 함께 해결됨. 같은
  클래스의 `test_real_production_archive_has_no_duplicate_content_ids`도
  0건일 때 우연히 통과하고 있었으므로 함께 skip 처리했다(2번과 동일한 이유).

5.
- 테스트: `test_media_batch.MediaBatchPipelineTests.test_cli_dry_run_saves_json_output`
- 원인: `scripts/run_media_batch.py`를 `--limit` 없이 실행해 **git에 커밋된 실제**
  `data/tak_brain_knowledge.json`을 읽고 승인 KNOWLEDGE 수를 집계. 이 테스트는
  2026-09-13 커밋(10917ec)에서 승인 4건을 하드코딩했는데, 이후 커밋(6-15 근처,
  8b3f816 등)에서 지식 데이터가 갱신되며 실제 승인 수가 6건으로 늘었다. `git show
  HEAD:data/tak_brain_knowledge.json`으로 확인한 HEAD(커밋된) 버전이 이미 6건
  approved이고 작업 디렉터리와 완전히 동일(`git diff` 없음) — 즉 이 실패는 이
  세션의 테스트 실행이 실제 파일을 바꿔서 생긴 것이 아니라, **테스트 작성 시점
  이후 커밋된 실제 데이터가 자라났는데 테스트의 하드코딩된 기대값만 갱신되지
  않아서** 생긴, 어느 clone에서나 동일하게 재현되는 문제다.
- CLI 자체는 `--output`에만 쓰고 실제 `data/tak_brain_knowledge.json`은 읽기만
  한다(코드로 직접 확인함, `content_engine/pipeline.py`/`scripts/run_media_batch.py`
  어디에도 이 파일에 대한 쓰기 코드가 없다) — "테스트가 운영 데이터 파일을
  수정한다"는 가설은 사실이 아니었다.
- 분류: C (테스트 fixture/설계 문제 — 실제 코드 버그 아님)
- 조치: 같은 파일의 `test_generate_media_batch_dry_run_structure`가 이미 쓰고
  있는 패턴(절대값 대신 `len(self.approved_records)`로 동적 계산)을 그대로
  적용해, `approved_knowledge_count`/`total_draft_count`/`items` 길이 기대값을
  하드코딩 대신 `setUp()`에서 읽은 실제 승인 수 기준으로 계산하도록 수정했다.
  운영 지식 데이터가 앞으로 더 늘어나도 이 테스트가 불필요하게 깨지지 않는다.

6.
- 테스트: `test_blog_publish_pack.MarkBlogPublishedScriptTests.test_marks_content_as_published` (ERROR)
- 원인: `from scripts.mark_blog_published import main` → `ModuleNotFoundError`.
- 분류: D (실제 코드 문제 — 구현 누락)
- 조치: 아래 6장 참고. `scripts/mark_blog_published.py`를 새로 구현했다.

7.
- 테스트: `test_blog_publish_pack.MarkBlogPublishedScriptTests.test_marking_twice_is_idempotent` (ERROR)
- 원인: 6번과 동일한 `ModuleNotFoundError`.
- 분류: D
- 조치: 6번과 동일.

## 4. Production Archive 의존 테스트 정책

`tests/test_media_versioning_and_promotion.py`의 `GenerationIdTests`(해당 1개
메서드)/`ExistingProductionArchiveUntouchedTests`(클래스 전체),
`tests/test_same_content_id_overwrite_protection.py`의
`ExistingProductionArchiveReadOnlyRegressionTests`(클래스 전체)는 자체
docstring이 "실제 production archive 파일을 읽기 전용으로 검증하는 회귀
테스트"라고 명시하고 있어, **A(실제 운영 데이터 파일을 반드시 읽어야 하는
통합/회귀 테스트)**로 판단했다. synthetic fixture로 대체하면 "실제 운영
데이터가 이번 변경으로 훼손되지 않았는가"라는 이 테스트들의 원래 검증 목적
자체가 사라지므로, fixture 전환은 하지 않았다.

대신 파일이 없을 때 `unittest.skipUnless(PRODUCTION_ARCHIVE_PATH.exists(), ...)`
로 명확한 사유와 함께 skip되도록 했다. 파일이 있는 환경(예: Production
Archive를 보유한 운영 노트북, 또는 향후 CI에 이 파일이 실제로 커밋되는 경우)
에서는 이 조건이 항상 참이 되어 지금까지와 동일하게 엄격히 실행된다 — "테스트
숫자를 예쁘게 만들기 위한 무조건 skip"이 아니라, "검증에 필요한 전제 조건이
없을 때만 skip"이다.

## 5. test fixture / temp directory 개선

- `test_media_batch.py`의 `test_cli_dry_run_saves_json_output`을 실제 파일
  기반 동적 계산으로 바꿔, 운영 데이터 성장에 대한 내성을 확보했다(3장 5번).
- Production Archive 의존 테스트 3곳에 `skipUnless` 가드를 추가했다(4장).
- `scripts/mark_blog_published.py` 테스트(`MarkBlogPublishedScriptTests`)는
  원래부터 `tempfile.TemporaryDirectory()`의 `blog_publish_log.json`만
  사용하도록 이미 올바르게 격리되어 있었다 — 실제로 누락된 것은 테스트 격리가
  아니라 스크립트 구현 자체였다(6장).
- 이 외의 파일들(`test_same_content_id_overwrite_protection.py` 대부분,
  `test_media_versioning_and_promotion.py` 대부분)은 이미 tempfile 기반으로
  잘 격리되어 있어 추가 변경이 필요하지 않았다.

## 6. mark_blog_published.py 조사 결과

Git history(`git log --all --diff-filter=A -- scripts/mark_blog_published.py`,
`git log --all --oneline -- scripts/mark_blog_published.py`)를 확인한 결과
이 파일은 **main 브랜치 어떤 커밋에도 추가된 적이 없다**(이동/이름 변경/삭제
흔적도 없음 — 애초에 존재한 적이 없다). 테스트(`MarkBlogPublishedScriptTests`)
는 6-14 커밋(4459a67, "feat: add publish readiness audit + close blog pack
review-gate bypass")에서 추가됐지만 구현 스크립트는 같은 커밋에도, 이후
어떤 커밋에도 포함되지 않았다.

동시에 `scripts/generate_blog_publish_pack.py`의 모듈 docstring(13~15행)이
이렇게 명시하고 있다: "실제 '게시 완료' 기록은 이 스크립트가 하지 않는다.
사람이 실제로 네이버에 게시를 마친 뒤 scripts/mark_blog_published.py로 명시적으로
기록해야 다음 실행에서 같은 콘텐츠가 후보에서 빠진다." 또한
`content_engine/blog_publish_pack.py`는 실제로 `PublishHistory`를 가져와
`select_blog_publish_candidates`/`build_blog_publish_pack_from_archive`에서
이미 게시된 content_id를 후보에서 제외하는 데 쓰고 있다.

즉 이것은 (조사 지시의 4가지 가능성 중) **"1. 실제로 필요한 스크립트인데 현재
누락된 것"**에 해당한다 — 폐기된 구조도, 이름/경로 이동도, 잘못된 import도
아니다. 사람이 블로그에 수동으로 게시를 마친 뒤 그 사실을 기록할 유일한
수단이 처음부터 구현되지 않았을 뿐이다.

**조치**: `scripts/mark_blog_published.py`를 최소 구현했다.
- `argparse`로 `--content-id`(필수), `--knowledge-id`/`--source-url`(선택,
  기본값 `""`), `--history`(기본값 `data/blog_publish_log.json`, Threads 이력
  `data/threads_publish_log.json`과 분리, `generate_blog_publish_pack.py`의
  동일 옵션 기본값과 일치)를 받는다.
- 기존 `content_engine/publish_history.py`의 `PublishHistory`/`PublishRecord`를
  그대로 재사용한다(새 클래스/새 저장 포맷을 만들지 않았다). `PublishRecord`의
  `threads_post_id` 필드는 Blog에는 해당 개념이 없어 빈 문자열로 채우고
  `platform="blog"`로 기록한다.
- 이미 기록된 content_id를 다시 넘기면 중복 append 없이 그대로 종료 0을
  반환해 멱등성(idempotent)을 보장한다(`test_marking_twice_is_idempotent`가
  검증).
- 실제 네이버 게시, 로그인, API 호출은 전혀 수행하지 않는다 — 로컬 JSON 이력
  파일에 "게시를 마쳤다"는 사실만 기록한다(기존 스크립트들과 동일한 원칙).

## 7. tak_brain_knowledge 변경 문제 조사 결과

조사 지시에서 제기된 "테스트 중 실제 `data/tak_brain_knowledge.json`이
변경된 것으로 보인다"는 가설을 확인했다.

- `scripts/run_media_batch.py`와 그것이 호출하는
  `content_engine/pipeline.py`의 관련 함수들을 확인한 결과, 이 CLI는
  `data/tak_brain_knowledge.json`을 **읽기만** 하고 어디에도 쓰지 않는다.
  결과는 사용자가 지정한 `--output` 경로(테스트에서는 `tempfile.TemporaryDirectory()`
  내부 경로)에만 저장된다.
- 이번 세션에서 전체 테스트를 여러 차례 실행한 뒤 `git status --short`,
  `git diff --stat -- data/tak_brain_knowledge.json`을 확인했지만 어떤 변경도
  없었다(10장 참고).
- `git show HEAD:data/tak_brain_knowledge.json`과 작업 디렉터리 사본을 비교한
  결과 완전히 동일했다(승인 6건/전체 28건).
- 결론: 테스트 실행이 실제 파일을 수정한 사실은 없다. 실패의 진짜 원인은
  3장 5번에 정리한 대로, "테스트가 실제 커밋된 데이터에 대해 오래된 하드코딩
  값(4건)을 기대했는데, 그 사이 커밋된 실제 데이터가 6건으로 늘어난 것"이었다.
  실제 운영 데이터 파일을 되돌리는 조치는 필요하지 않았고 시도하지도 않았다 —
  테스트의 기대값 계산 방식만 고쳤다(5번 조치).

## 8. 6-19 회귀 테스트 결과

`tests/test_superseded_downstream_safeguards.py`(6-19, 21개 테스트)를 이번
작업 전후로 각각 단독 실행해 확인했다.

- 작업 전: 21 passed, 0 failed, 0 errors
- 작업 후: 21 passed, 0 failed, 0 errors (변경 없음)

이 파일의 테스트나 이 파일이 의존하는 `content_engine`/`scripts` 코드는 이번
작업에서 전혀 건드리지 않았다. SUPERSEDED → Threads/Shorts/Blog 차단, OLD
superseded/NEW approved 시나리오 등 6-19의 정책은 그대로 유지된다.

## 9. 전체 테스트 결과

| 구분 | 작업 전 | 작업 후 |
|---|---|---|
| total | 924 | 924 |
| passed | 906 | 907 |
| failed | 5 | 0 |
| errors | 2 | 0 |
| skipped | 11 | 17 |

(전체 924건은 동일 — 실패/에러였던 7건 중 6건이 명시적 사유가 있는 skip으로,
1건(`test_cli_dry_run_saves_json_output`)이 pass로 전환됐다. 기존에 skip이던
11건과는 무관하다. `full_output` 로그 기준 `Ran 924 tests ... OK (skipped=17)`.)

세부:
- 실행 명령: `python -m unittest discover -s tests -p "test_*.py" -v`
- 이번에 새로 skip된 6건: `GenerationIdTests`의 1개 메서드 +
  `ExistingProductionArchiveUntouchedTests`의 2개 메서드 +
  `ExistingProductionArchiveReadOnlyRegressionTests`의 3개 메서드
  (3장·4장 참고). 전부 "Production Archive 파일이 없어 실제 운영 데이터
  회귀 테스트를 검증할 수 없다"는 동일한 이유의 명시적 skip이다.
- pytest는 설치하지 않았다(공식 테스트 방법은 unittest — 이전 세션의
  Python 설정 점검에서 이미 확인함).

## 10. 운영 데이터 변경 여부

전체 테스트 실행 전후로 확인했다.

- `git status --short`: 이번 세션이 직접 편집한 3개 테스트 파일(수정)과
  `scripts/mark_blog_published.py`(신규, untracked) 외에는 아무 변경 없음.
- `data/tak_brain_knowledge.json`: `git diff --stat` 결과 변경 없음.
- `data/tak_threads_pending.json`: `git diff --stat` 결과 변경 없음.
- `data/tak_media_archive.json`: 생성되지 않음(여전히 존재하지 않음).
- `data/tak_media_generation_*.json`: 생성되지 않음.
- `data/shorts_scripts/`: 생성되지 않음.
- `data/blog_drafts/`: 생성되지 않음.
- 실제 Threads 게시, YouTube 업로드, 네이버 블로그 게시, 외부 API 호출은
  이번 세션에서 전혀 수행하지 않았다.

## 11. 남은 문제

- `.gitignore`의 `!data/tak_media_archive.json` 예외 규칙과 그 주석은 이
  파일이 "사람이 승인 후 커밋해야 하는" 파일이라고 명시하지만, 실제로는 main
  브랜치 어떤 커밋에도 커밋된 적이 없다(2장). 이 때문에 CI(GitHub Actions)
  러너의 새 checkout에서도 이번에 skip 처리한 4개 회귀 테스트 대상 파일이
  없을 가능성이 높다 — 다만 실제 워크플로 실행 로그를 이 세션에서 직접
  조회하지는 못했다(`gh` CLI 없음). Production Archive를 실제로 커밋할지,
  아니면 이 gitignore 주석/정책 문구를 현재 실태에 맞게 고칠지는 사람의 결정이
  필요하며, 이번 6-20 범위에서는 그 결정을 대신 내리지 않았다.
- `test_media_versioning_and_promotion.py`의
  `test_new_generation_added_to_a_temp_copy_does_not_drop_existing_nine`은
  이번에 skip 대상에 포함시켰지만, Production Archive가 있는 환경에서는
  여전히 정상적으로 실행되어 "임시 복사본에 새 generation을 추가해도 기존
  레코드가 사라지지 않는다"를 검증한다 — 로직 자체는 바꾸지 않았다.
- `docs`의 여러 과거 세션 문서(예: 6-19 보고서)가 언급하는 "전체 pytest
  1093 passed" 같은 기록은 pytest가 설치된 다른 환경(과거 세션에서
  "노트북1"로 지칭)에서 실행된 결과로 보이며, 이 저장소의 공식 테스트 방법
  (README 기준 unittest)과는 별개다. 이번 6-20 작업은 이 불일치를 고치는
  작업은 아니다.

## 12. 다음 작업

- Production Archive(`data/tak_media_archive.json`)를 실제로 git에 커밋할지
  여부를 결정하고, 그 결정에 따라 `.gitignore` 주석/CI workflow를 실태에
  맞게 정리한다(11장).
- `scripts/mark_blog_published.py`는 이번에 테스트를 통과시키기 위한 최소
  구현이다. 실제 운영에서 사람이 이 스크립트를 어떻게 호출할지(예: Dashboard
  버튼 연동 여부)는 별도 논의가 필요하다.
