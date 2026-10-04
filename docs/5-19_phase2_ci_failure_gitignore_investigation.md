# 5-19 Phase 2: CI 실패 원인 조사 (run 35417007439)

- 조사 대상: GitHub Actions run [35417007439](https://github.com/sopptak/tak-auto/actions/runs/35417007439)
  (workflow_dispatch #3, commit `46422bb`, max_candidates=5)
- 조사 범위: 코드 수정 없이 실패 원인만 확인 (사용자 지시)

## 실제 실패 단계

`Collect SCOUT candidates and select top N by score` job의
**`Check for SCOUT result changes`** 스텝 (`git add data/tak_scout_daily.json data/tak_scout_daily.md`)

이전 단계인 `Run existing test suite`, `Run TAK SCOUT collection + scoring`는 모두 ✓ 성공했다.

## 정확한 에러

```
The following paths are ignored by one of your .gitignore files:
data/tak_scout_daily.json
data/tak_scout_daily.md
hint: Use -f if you really want to add them.
hint: Disable this message with "git config set advice.addIgnoredFile false"
##[error]Process completed with exit code 1.
```

`git add`가 `.gitignore`에 의해 무시된 경로를 명시적으로 받으면 git이 비정상 종료(exit 1)한다.
이번 실패는 ModuleNotFoundError/import 문제가 아니라 **`.gitignore` 규칙 문제**다.

## traceback

Python traceback은 없다. 이 실패는 Python 예외가 아니라 셸 스텝(`git add`)의 종료 코드 1로 인한
GitHub Actions 스텝 실패다. 위 "정확한 에러"에 인용한 로그 전문이 전부다.

## RSS 수집 실행 여부

**실행됨 (성공).** `Run TAK SCOUT collection + scoring` 스텝 로그:

```
TAK SCOUT: 등록된 source 2개에서 수집 시작...
  성공: BBC Business - 53건 수집
  성공: Hacker News - 30건 수집
오늘의 후보 5건 선정 완료 (최대 5건, 중복 제거 후 SCOUT SCORE 상위)
```

## scoring 실행 여부

**실행됨 (성공).** 위 로그의 "오늘의 후보 5건 선정 완료"는 `tak_scout/scoring.py`의
`top_candidates()`가 정상 동작해 SCOUT SCORE 상위 5건을 골랐다는 뜻이다.
Phase 1에서 발생했던 `tak_scout.scoring` ModuleNotFoundError는 이번 run에서 재발하지 않았다.

## 파일 저장 실행 여부

**실행됨 (성공).**

```
JSON 저장: /home/runner/work/tak-auto/tak-auto/data/tak_scout_daily.json
MD 저장: /home/runner/work/tak-auto/tak-auto/data/tak_scout_daily.md
```

파일 자체는 러너 워크스페이스에 정상적으로 생성되었다. 실패는 그 다음 스텝(git add)에서 발생했다.

## 로컬 재현 결과

Codespace에서 commit `46422bb`를 격리된 임시 clone(`/tmp/.../repro_46422bb`)으로 체크아웃해
동일하게 재현했다(작업 중이던 미커밋 변경분과 섞이지 않도록 별도 clone 사용, 조사 후 삭제).

1. `python3 -m unittest discover -s tests -p 'test*.py'` → `Ran 278 tests ... OK` (CI와 동일하게 통과)
2. `python3 scripts/run_scout.py --max 5` → BBC Business 53건, Hacker News 30건 수집,
   5건 선정, JSON/MD 저장까지 CI 로그와 동일하게 재현됨
3. `git check-ignore -v data/tak_scout_daily.json data/tak_scout_daily.md` 결과:
   ```
   .gitignore:6:data/*.json          data/tak_scout_daily.json
   .gitignore:14:data/tak_scout_daily.md   data/tak_scout_daily.md
   ```
   두 파일 모두 `.gitignore`가 명시적으로 무시하고 있음을 로컬에서 확인. CI 실패와 100% 일치.

## 근본 원인

commit `46422bb` 시점의 `.gitignore`(레포 루트)에 다음 두 규칙이 있다:

```gitignore
data/*.json
!data/tak_brain_knowledge.json
!data/tak_media_batch_e2e_test.json
!data/threads_publish_log.json
!data/scout_sources.json
...
data/tak_scout_daily.md
data/tak_interview_questions.md
```

- `data/tak_scout_daily.json`은 `data/*.json` 규칙에 걸리는데, 이를 예외 처리하는
  `!data/tak_scout_daily.json` negation 라인이 이 commit에는 없다.
- `data/tak_scout_daily.md`는 아예 명시적으로 ignore되어 있다.

즉 daily-scout.yml workflow가 만들려는 결과 산출물 2개 모두 `.gitignore`가
"휘발성 로컬 산출물"로 취급해 추적 대상에서 제외하고 있다. 이 workflow는 애초에
이 두 파일을 commit/push해야 하는데(workflow 자체 주석: "data/tak_scout_daily.json,
data/tak_scout_daily.md를 이 workflow가 직접 commit/push해야 하므로..."),
`.gitignore`가 그 의도와 충돌한다.

참고로 현재 작업 디렉터리(미커밋 상태)의 `.gitignore`에는 이미
`!data/tak_scout_daily.json` negation이 추가되어 있으나, `data/tak_scout_daily.md`를
ignore하는 라인은 여전히 남아 있고, 이 변경 자체가 아직 commit되지 않은 상태다.

## 최소 수정안 (참고용 — 이번 조사에서는 적용하지 않음)

`.gitignore`에서:
1. `data/*.json` 예외 목록에 `!data/tak_scout_daily.json` 추가
2. `data/tak_scout_daily.md` ignore 라인 제거(또는 `!data/tak_scout_daily.md` 추가)

## 수정이 필요한 파일

- `.gitignore` (1개 파일)

## 코드 수정 필요 여부

**아니오.** Python 코드(`scripts/run_scout.py`, `tak_scout/scoring.py` 등)는 정상 동작했다.
필요한 수정은 `.gitignore` 규칙 변경뿐이며, 로직 수정은 필요 없다.
