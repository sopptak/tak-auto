# Phase 4-1 GitHub Actions 실패 조사 (조사 전용, 수정/커밋/push 없음)

## 0. 요약

- **원인**: `content_engine/threads_review.py`가 아직 커밋되지 않았다(로컬 working
  tree에만 존재하는 untracked 파일). origin/main(=현재 HEAD)에는 이미
  `scripts/publish_approved_threads.py`와 `tests/test_publish_approved_threads.py`가
  커밋돼 있고, 이 두 파일이 `content_engine.threads_review`를 import하기 때문에
  GitHub Actions의 `python3 -m unittest discover -s tests -p 'test*.py'` 단계에서
  `ModuleNotFoundError: No module named 'content_engine.threads_review'`가 발생한다.
- **최소 커밋 후보는 파일 1개**: `content_engine/threads_review.py`. 이 모듈은
  stdlib(`dataclasses`, `json`, `pathlib`, `tempfile`, `typing`)만 import하므로
  다른 미커밋 파일에 의존하지 않는다.
- 229개 vs 457개 테스트 수 차이는 전부 "origin/main에 없는 파일" 때문이며,
  실행 로직 차이가 아니다(3장 참조로 정확히 재현 및 검산 완료).

## 1. 현재 HEAD와 origin/main의 차이

```
git fetch origin main
git log --oneline HEAD -1        -> badac01 feat: add approved Threads publish workflow
git log --oneline origin/main -1 -> badac01 feat: add approved Threads publish workflow
git rev-list --left-right --count HEAD...origin/main -> 0	0
```

**HEAD == origin/main.** 즉 "커밋했는데 안 올라간" 상황이 아니라, **애초에
커밋조차 되지 않은 로컬 변경/신규 파일**이 원인이다. `git status`에는 수정된
추적 파일 8개와 미추적(untracked) 파일 다수(문서, 스크립트, 테스트, 모듈)가
있다.

## 2. Phase 4-1 workflow 실행에 반드시 필요한, 아직 커밋 안 된 파일

`.github/workflows/publish-approved-threads.yml`이 실행하는 단계는 다음 두 가지뿐이다.

1. `python3 -m unittest discover -s tests -p 'test*.py'` (전체 테스트)
2. `python3 scripts/publish_approved_threads.py --dry-run` (또는 `--execute`)

이 두 단계가 실제로 import하는 모듈을 커밋된 버전 기준으로 추적한 결과:

| 파일 | HEAD(origin/main)에 존재? | 비고 |
|---|---|---|
| `scripts/publish_approved_threads.py` | ✅ 있음 | 이미 커밋됨 |
| `tests/test_publish_approved_threads.py` | ✅ 있음 | 이미 커밋됨 |
| `content_engine/threads_publisher.py` | ✅ 있음 | 이미 커밋됨 |
| `content_engine/publish_history.py` | ✅ 있음 | 이미 커밋됨 |
| `content_engine/__init__.py` (ThreadsClient 등 re-export) | ✅ 있음 | 이미 커밋됨 |
| **`content_engine/threads_review.py`** | ❌ **없음** | **untracked, 이번 실패의 직접 원인** |

## 3. 의존성 확인 결과 (질문에 명시된 항목별)

- **`content_engine/threads_review.py`**: origin/main에 없음(untracked). 이 파일
  자체는 `dataclasses`, `json`, `pathlib`, `tempfile`, `typing`만 import하며,
  다른 프로젝트 내부 모듈에 의존하지 않는다. → **이것 하나만 없어서 실패한다.**
- **`scripts/publish_approved_threads.py`**: 이미 origin/main에 커밋되어 있음.
  이 파일이 `from content_engine.threads_review import (...)`를 하기 때문에
  threads_review.py 부재의 영향을 그대로 받는다.
- **`tests/test_publish_approved_threads.py`**: 이미 origin/main에 커밋되어 있음.
  마찬가지로 `content_engine.threads_review`를 직접 import하며, 이 파일이 바로
  `unittest discover` 단계에서 `ModuleNotFoundError`를 던지는 지점이다
  (`ERROR: test_publish_approved_threads (unittest.loader._FailedTest...)`).
- **Phase 1/2에서 만든 Threads review 관련 파일 전반**: `threads_review`를
  참조하는 파일은 working tree 전체에서 다음 7개다.
  - `scripts/generate_threads_draft.py` (untracked)
  - `scripts/publish_approved_threads.py` (**커밋됨**)
  - `scripts/run_scout_dashboard.py` (untracked)
  - `tests/test_generate_threads_draft.py` (untracked)
  - `tests/test_publish_approved_threads.py` (**커밋됨**)
  - `tests/test_threads_dashboard.py` (untracked)
  - `tests/test_threads_review.py` (untracked)
- **Dashboard가 사용하는 Threads review 관련 파일**: `scripts/run_scout_dashboard.py`
  가 `content_engine.threads_review`를 사용하지만, 이 스크립트는 Phase 4-1
  workflow(`publish-approved-threads.yml`)가 직접 호출하지 않고, 관련 테스트인
  `tests/test_threads_dashboard.py`, `tests/test_scout_dashboard.py`도 아직
  커밋되지 않아 CI의 `unittest discover` 대상에도 포함되지 않는다. → **Phase
  4-1 실패와는 무관**하며, 대시보드 자체는 별도 Phase(Dashboard 관련) 범위.
- **기타 import dependency**: `content_engine/__init__.py`의 로컬 미커밋 diff는
  `blog_publish_pack` re-export 추가뿐이며, 기존에 있던 `ThreadsClient`,
  `ThreadsAPIError`, `ThreadsConfigurationError` re-export는 origin/main에 이미
  존재한다. 즉 이 파일의 로컬 수정분은 Phase 4-1과 무관한 별개 작업(블로그
  발행팩 기능)이다.

## 4. Phase 4-1 workflow가 요구하는 최소 파일 집합

현재 실패를 없애기 위한 **최소 요건은 파일 1개 커밋**이다.

- `content_engine/threads_review.py`

나머지(예: `scripts/generate_threads_draft.py`, `scripts/run_scout_dashboard.py`,
`tests/test_threads_review.py`, `tests/test_generate_threads_draft.py`,
`tests/test_threads_dashboard.py` 등)는 Phase 4-1 workflow가 직접 실행하지도,
import하지도 않으므로 이 workflow를 통과시키는 데는 필요하지 않다.

## 5. origin/main에 이미 있는 파일 vs 아직 push되지 않은 파일 (Threads 관련만)

**이미 origin/main에 있음(커밋 완료):**
- `scripts/publish_approved_threads.py`
- `tests/test_publish_approved_threads.py`
- `content_engine/threads_publisher.py`
- `content_engine/publish_history.py`
- `.github/workflows/publish-approved-threads.yml`
- `.github/workflows/daily-threads-post.yml`

**아직 push되지 않음(로컬 untracked, Threads 관련):**
- `content_engine/threads_review.py` ← **Phase 4-1 수정에 필요한 유일한 파일**
- `scripts/generate_threads_draft.py`
- `scripts/run_scout_dashboard.py`
- `tests/test_threads_review.py`
- `tests/test_generate_threads_draft.py`
- `tests/test_threads_dashboard.py`
- `tests/test_scout_dashboard.py`

## 6. 최소 커밋 후보 (제안, 미실행)

Phase 4-1을 정상 작동시키기 위한 최소 커밋 후보는 다음 **1개 파일**뿐이다.

```
content_engine/threads_review.py
```

다음은 **포함하지 않는 것**을 권장한다(Phase 4-1과 무관하거나 다른
작업 단위이므로):
- `data/tak_brain_knowledge.json` (데이터 변경, 별도 검토 필요)
- `content_engine/__init__.py`, `content_engine/generator.py`,
  `content_engine/llm_provider.py`, `content_engine/rewrite.py` (블로그
  발행팩/LLM 관련 별도 작업)
- `content_engine/blog_publish_pack.py`, `scripts/generate_blog_publish_pack.py`,
  `scripts/mark_blog_published.py` (블로그 발행팩 기능, 별도 Phase)
- Dashboard/Scout/Interview 관련 파일들(`tak_scout/*`, `scripts/run_scout_*.py`,
  관련 테스트) 및 `docs/*.md` 전부 (Phase 4-1 workflow 실행과 무관)

## 7. 229개(GitHub Actions) vs 457개(로컬) 테스트 수 차이 검증

원인을 추측이 아니라 **origin/main과 동일한 상태를 임시 디렉터리에 재현**해서
직접 확인했다(`git archive HEAD`로 별도 clean checkout, 로컬 working tree는
전혀 건드리지 않음).

**origin/main(HEAD) 상태로 재현한 결과:**
```
tests/ 디렉터리 내 test*.py 파일 수: 22개
python3 -m unittest discover -s tests -p 'test*.py'
Ran 229 tests in 1.563s
FAILED (errors=1)
ERROR: test_publish_approved_threads (unittest.loader._FailedTest.test_publish_approved_threads)
ModuleNotFoundError: No module named 'content_engine.threads_review'
```
→ GitHub Actions 로그의 229개, 실패 1건과 정확히 일치.

**현재 로컬 working tree 결과:**
```
tests/ 디렉터리 내 test*.py 파일 수: 31개
Ran 457 tests in 26.219s
OK
```

**차이(228개)의 구성 내역:**

1. **origin/main에 아예 없는 신규 테스트 파일 9개**(전부 untracked):

   | 파일 | 테스트 수 |
   |---|---|
   | `tests/test_blog_publish_pack.py` | 22 |
   | `tests/test_generate_threads_draft.py` | 9 |
   | `tests/test_interview_llm.py` | 36 |
   | `tests/test_interview_session.py` | 21 |
   | `tests/test_scout_dashboard.py` | 26 |
   | `tests/test_scout_scoring.py` | 6 |
   | `tests/test_tak_auto_e2e.py` | 5 |
   | `tests/test_threads_dashboard.py` | 27 |
   | `tests/test_threads_review.py` | 37 |
   | 합계 | **189** |

2. **origin/main에 이미 있지만 로컬에서 테스트가 추가된 파일**:
   - `tests/test_content_engine.py`: HEAD 49개 → 로컬 65개 (**+16**, 예:
     `InterviewQAFormatTests` 클래스 신규 추가)
   - `tests/test_media_batch.py`: HEAD 11개 → 로컬 11개 (0, 내용만 수정,
     `data/tak_brain_knowledge.json`의 승인 건수 의존성 제거)

3. **`test_publish_approved_threads.py`의 "숨은 손실분" 23개**: origin/main에서는
   이 파일의 import가 실패하기 때문에 실제 테스트 24개가 전혀 실행되지 못하고,
   unittest가 대신 만들어내는 placeholder 실패 테스트(`_FailedTest`) **1개**만
   229에 포함된다. 로컬에서는 이 24개가 전부 정상 실행된다(+23).

   `189 + 16 + 0 + 23 = 228` → `229 + 228 = 457` (정확히 일치)

**결론**: 실행 로직이나 환경 차이가 아니라, 순전히 "origin/main에 아직 없는
파일 개수" 때문에 테스트 수가 다르다. `content_engine/threads_review.py` 하나만
커밋되어도 `test_publish_approved_threads.py`의 24개 테스트는 정상 실행되지만,
나머지 9개 신규 파일과 `test_content_engine.py`의 +16개는 그 파일들 자체를
커밋하기 전까지는 GitHub Actions에 나타나지 않는다(이는 Phase 4-1 workflow
통과에는 영향 없음 — 4장 참조).

---

*이 문서는 조사 전용이다. 파일 수정, `git add`, commit, push, workflow 실행,
실제 Threads API 호출은 전혀 하지 않았다.*
