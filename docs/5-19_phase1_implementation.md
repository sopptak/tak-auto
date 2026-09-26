# 5-19 Phase 1 구현 — Threads cron 중단 + Shorts 어댑터 + SCOUT 점수 선정 + 08:00 SCOUT workflow

`docs/5-19_daily_pipeline_investigation.md`에서 정리한 구현 계획 중 1~4번을
단계적으로 구현했다. **아직 커밋하지 않았다.**

## 1. 변경 파일

| 파일 | 종류 | 내용 |
|---|---|---|
| `.github/workflows/daily-threads-post.yml` | 수정 | `schedule:` cron 트리거만 주석 처리(비활성화) + 사유 주석 추가. 그 외 로직 무수정 |
| `content_engine/shorts_adapter.py` | 신규 | `ShortDraft -> ShortsScript` 변환 어댑터 |
| `content_engine/__init__.py` | 수정(+3줄) | `shorts_adapter`의 `ShortsAdapterError`, `short_draft_to_shorts_script` export 추가 |
| `scripts/run_scout.py` | 수정 | 후보 선정을 수집 순서 기준 → TAK SCOUT SCORE 기준으로 변경 |
| `.github/workflows/daily-scout.yml` | 신규 | 08:00 KST SCOUT 수집+점수화 전용 workflow |
| `tests/test_shorts_adapter.py` | 신규 | 어댑터 테스트 14건 |
| `tests/test_run_scout_cli.py` | 신규 | 점수 기반 선정 테스트 3건 |

`content_engine/__init__.py`는 이번 세션 이전부터 이미 미커밋 변경(5-17에서
추가된 shorts_script/shorts_renderer/blog_publish_pack export 등)이 있던
파일이다 — 이번에 실제로 추가한 것은 정확히 3줄(`shorts_adapter` import 1줄 +
`__all__` 2줄)이며, `git diff`로 확인했다. 그 외 기존 미커밋 변경분은 손대지
않았다.

TAK BRAIN 핵심 로직, TAK MEDIA generator(`content_engine/generator.py`),
Shorts renderer(`content_engine/shorts_renderer.py`, `shorts_script.py`),
YouTube publisher/OAuth, Threads publisher, 기존 Dashboard 인터뷰 로직
(`scripts/run_scout_dashboard.py`, `tak_scout/interview_session.py`,
`tak_scout/interview_llm.py`)은 이번 작업에서 **전혀 수정하지 않았다.**

## 2. Threads cron 비활성화 여부

**비활성화했다.** `.github/workflows/daily-threads-post.yml`의 `on.schedule`
블록을 주석 처리해 08:00 KST 자동 실행(`scripts/run_daily.py` →
`scripts/publish_threads.py --auto`, 승인 없는 실제 게시)을 멈췄다.

- workflow 파일 자체는 삭제하지 않음
- `workflow_dispatch`(수동 실행, dry-run 기본값 true)는 그대로 살아있음 — 필요하면
  사람이 여전히 이 경로로 수동 실행 가능
- 실행 로직(테스트 → dry-run/live 분기 → publish history commit)은 한 줄도
  수정하지 않음
- `publish-approved-threads.yml`(승인 게이트가 있는 새 경로)은 그대로 유지,
  무수정
- 비활성화 사유는 workflow 파일 안에 주석으로 남기고, `docs/5-19_daily_pipeline_investigation.md`
  3-a를 참조하도록 링크했다

## 3. ShortDraft → ShortsScript 변환 결과

새 파일 `content_engine/shorts_adapter.py`, 함수 `short_draft_to_shorts_script()`.

규칙:
- `title` → 그대로 `ShortsScript.title`
- `body`를 `"\n\n"` 기준으로 나눈 문단이 `cards`가 된다(TAK MEDIA generator가
  원래 이 구분자로 문단을 합치는 기존 관례를 그대로 재사용)
- 문단이 여러 개면 **마지막 문단이 `takeaway`**, 나머지가 `cards`
- **문단이 1개뿐이면** 그 문단을 `cards`와 `takeaway` 양쪽에 그대로 재사용
  (새 문장을 지어내지 않기 위한 안전한 fallback)
- `cards`가 9개 이상이 되면(문단 10개 이상) **일부를 임의로 잘라내지 않고
  `ShortsAdapterError`로 명시적 실패** — 콘텐츠를 새로 편집/창작하지 않는다는
  원칙에 따른 선택
- `subtitle`은 대응하는 원본 필드가 없어 빈 문자열(없는 내용을 지어내지 않음,
  `ShortsScript`도 `subtitle`을 필수로 요구하지 않음)
- `brand` 기본값은 `"티몽의 지혜"`(`shorts_script.DEFAULT_BRAND` 재사용, 새로
  하드코딩하지 않음)

`ShortsScript`/`shorts_renderer.py`/`generator.py`는 무수정. Finance/사실성
검증 로직도 새로 만들지 않았다(그건 이미 `rewrite.py`의 책임이고, 이 어댑터가
받는 `ShortDraft`는 이미 그 검증을 통과한 콘텐츠라고 가정).

## 4. SCOUT 후보 선정 방식

`scripts/run_scout.py`가 기존에는 `collector.build_daily_pack()`(수집 순서대로
앞에서 `--max`개만 자름)을 썼는데, 이를 `collect_all()` → `dedupe_candidates()`
→ `tak_scout.scoring.top_candidates()`로 재구성했다. **점수 계산 로직
(`scoring.py`) 자체는 한 줄도 수정하지 않았고**, 기존에 있던 순수 함수를
호출 순서만 바꿔 연결했다(Dashboard `/` 화면이 이미 같은 함수로 "보여주는
순서"를 정하던 것과 동일한 기준을 "선정되는 후보 자체"에도 적용).

`--max` 기본값(10)은 바꾸지 않았다 — "오늘의 후보 3~5개"는 실제 운영 시
`daily-scout.yml`이 `--max 5`를 넘겨서 결정하는 운영 파라미터로 남겼다(기존
스크립트의 기본 동작을 조용히 바꾸지 않기 위함).

## 5. `daily-scout.yml` 내용

신규 workflow `.github/workflows/daily-scout.yml`:

- 트리거: `schedule: '0 23 * * *'`(KST 08:00, 기존 daily-threads-post.yml과
  동일한 cron 표현식 재사용) + `workflow_dispatch`(수동 실행, `max_candidates`
  입력값 기본 5)
- 단계: checkout → Python 3.14 설정 → 기존 테스트 스위트 실행 → `scripts/run_scout.py --max <N>` 실행 → `data/tak_scout_daily.json`/`.md` 변경 여부 확인 → 변경 시에만 commit/push
- **Threads 게시, YouTube 업로드, Blog 게시를 전혀 수행하지 않는다** — `run_scout.py`가
  LLM/게시 API를 호출하지 않으므로 이 workflow는 관련 Secrets을 하나도 쓰지
  않는다
- commit 대상은 `data/tak_scout_daily.json`, `data/tak_scout_daily.md` 두
  파일로 한정(기존 daily-threads-post.yml의 "변경 있을 때만 commit" 패턴 재사용)

## 6. 테스트 결과 (개별)

```
$ pytest tests/test_shorts_adapter.py tests/test_run_scout_cli.py -v
17 passed
```

- `test_shorts_adapter.py`(14건): 1문단(카드+takeaway 재사용, 새 텍스트 미생성
  확인), 3/5문단(마지막 문단→takeaway), title 그대로 사용, subtitle 빈 문자열,
  brand 기본값/커스텀, **카드 한도 경계**(8문단→성공, 9문단→정확히 MAX_CARDS
  경계에서 성공, 10문단→명시적 실패 + "일부 생략 안 함" 확인), 빈 body/공백만
  있는 body → 실패
- `test_run_scout_cli.py`(3건): RSS 피드에서 **낮은 점수 기사가 먼저, 높은
  점수 기사가 나중에** 오도록 배치한 뒤 `--max 1`로 실행 → 점수가 높은 기사가
  선택됨(수집 순서가 아니라 점수 기준임을 직접 증명), `--max`가 점수화 이후에도
  개수를 제한하는지, markdown 결과도 함께 저장되는지 확인. **실제 RSS
  네트워크 호출 없음**(`tak_scout.collector.fetch_rss`를 patch)

## 7. 전체 pytest 결과

```
$ pytest -q
566 passed, 68 subtests passed in 101.01s
```

(5-18 종료 시점 549건 → 이번에 추가한 17건 포함 566건, 회귀 없음)

## 8. 미커밋 변경사항

이번 세션에서 손댄 파일은 위 1번 표의 7개뿐이다. 5-2~5-18에서 쌓인 기존
미커밋 변경분(수정된 9개 파일 + 다수의 untracked 파일)은 **전혀 정리하거나
삭제하지 않았다** — `git status --short`로 확인 시 이전과 동일하게 그대로
남아 있다.

**아직 Git commit/push하지 않았다** — 확인 후 진행 여부를 알려달라.
