# 5-19 Phase 1 — `daily-scout.yml` 실행 #1 실패 원인 조사 (코드 수정 없음)

`TAK SCOUT Daily Collect (5-19, collection + scoring only)` workflow 수동 실행 #1
(`run 35322743597`, commit `4d6b968`)이 실패한 원인을 조사했다. **코드는 한 줄도
수정하지 않았다.** workflow를 재실행하지도 않았다.

## 0. 결론 먼저

**RSS 수집, 점수화, 파일 저장 중 어느 단계도 실행되지 않았다.** 실패는 그보다
훨씬 앞선 **"Run existing test suite" 스텝**에서 발생했고, 원인은 **5-19에서
새로 커밋한 `scripts/run_scout.py`가 여전히 git에 커밋되지 않은
`tak_scout/scoring.py`를 import한다는 것**이다. 추가로, **이번 5-19 작업과
무관한 기존(5-18) 문제 하나**도 같은 스텝에서 함께 발견됐다: `tests/test_upload_youtube_short_cli.py`가
아직 커밋되지 않은 `content_engine/youtube_publisher.py` 등을 import한다.

이건 GitHub Actions 권한/환경 문제가 아니다 — `git worktree add`로 commit
`4d6b968`만을 독립적으로 체크아웃해 로컬에서 그대로 재현했고, CI 로그와
정확히 동일한 결과(`ERROR` 2건, `FAILED (errors=2)`, exit 1)가 나왔다.

## 1. 어떤 command에서 exit code 1이 발생했는가

```
python3 -m unittest discover -s tests -p 'test*.py'
```
("Run existing test suite" 스텝). `unittest`가 테스트 모듈 import 단계에서
실패(`_FailedTest`)를 오류로 집계해 `FAILED (errors=2)`로 종료했고, 그 결과
프로세스 exit code가 1이 되었다.

## 2. Python traceback이 있는가

있다. 정확히 2건:

```
ERROR: test_run_scout_cli (unittest.loader._FailedTest.test_run_scout_cli)
...
  File "/home/runner/work/tak-auto/tak-auto/tests/test_run_scout_cli.py", line 17, in <module>
    from scripts.run_scout import main
  File "/home/runner/work/tak-auto/tak-auto/scripts/run_scout.py", line 30, in <module>
    from tak_scout.scoring import top_candidates
ModuleNotFoundError: No module named 'tak_scout.scoring'

ERROR: test_upload_youtube_short_cli (unittest.loader._FailedTest.test_upload_youtube_short_cli)
...
  File "/home/runner/work/tak-auto/tak-auto/tests/test_upload_youtube_short_cli.py", line 26, in <module>
    from content_engine.youtube_publisher import (
    ...
ModuleNotFoundError: No module named 'content_engine.youtube_publisher'
```

## 3. RSS 수집에서 실패했는가

**아니다.** workflow job 스텝 목록을 보면 "Run TAK SCOUT collection + scoring"
스텝 자체가 `-`(건너뜀)로 표시된다 — 앞 스텝(테스트)이 실패해 GitHub Actions가
이후 스텝을 자동으로 건너뛰었다(별도 `if: always()`를 주지 않았으므로 의도한
동작 그대로).

## 4. scoring에서 실패했는가

**아니다.** `tak_scout.scoring.top_candidates()` 로직 자체는 실행조차 되지
않았다. 실패는 "이 모듈을 import할 수 있는가"라는, 로직 이전 단계의 문제다.

## 5. 파일 저장에서 실패했는가

**아니다.** "Check for SCOUT result changes", "Commit and push today's SCOUT
candidates" 두 스텝 모두 `-`(건너뜀)로 표시된다. `data/tak_scout_daily.json`,
`.md`는 이번 실행에서 전혀 생성/갱신되지 않았다.

## 6. GitHub Actions 권한/환경 문제인가

**아니다.** `actions/checkout@v4`, `actions/setup-python@v5`, "Show Python
version" 스텝은 모두 정상 성공(✓)했다. Node.js 20 deprecated 경고와
Ubuntu 26 마이그레이션 안내는 지시하신 대로 실패 원인으로 취급하지 않았다.

**로컬 재현으로 확정**: `git worktree add /tmp/ci-repro 4d6b968`로 이 커밋만
독립적으로 체크아웃한 뒤 같은 명령을 그대로 실행하자 CI와 정확히 동일한 결과가
나왔다:
```
$ python3 -m unittest discover -s tests -p 'test*.py'
ERROR: test_run_scout_cli ...
ERROR: test_upload_youtube_short_cli ...
Ran 268 tests in 1.700s
FAILED (errors=2)
```
(재현에 사용한 `/tmp/ci-repro` worktree는 조사 완료 후 `git worktree remove`로
제거했다 — 실제 저장소/작업 트리는 전혀 건드리지 않았다.)

## 7. `max_candidates=5` 입력값이 제대로 전달됐는가

**확인할 수 없다 — 그 단계 자체가 실행되지 않았다.** GitHub API로 이 실행이
`workflow_dispatch` 이벤트로, commit `4d6b968` 기준으로 정상적으로 시작된
것은 확인했다(`event: workflow_dispatch`, `head_sha: 4d6b968...`, `status: completed`,
`conclusion: failure`). 다만 입력값을 실제로 사용하는 "Run TAK SCOUT
collection + scoring" 스텝 자체가 건너뛰어져서, `--max` 값이 셸 명령까지
도달했는지는 이번 실행 로그로는 검증 불가능하다. workflow YAML의 입력값 처리
로직(`${{ github.event.inputs.max_candidates || '5' }}`) 자체에는 문제가
없어 보이지만, 이 부분은 테스트 스텝 실패가 해결된 뒤 재실행해야 실제로
확인 가능하다.

## 8. 근본 원인 정리

이 저장소는 지금 "이미 작성했지만 아직 git에 커밋하지 않은 파일"이 매우
많은 상태다(5-2~5-18 누적). 로컬 Codespace에서는 git 추적 여부와 무관하게
디스크에 파일이 있으면 그냥 import되므로 `pytest -q`가 항상 통과했다. 하지만
GitHub Actions의 `actions/checkout`은 **커밋된 파일만** 가져오므로, "커밋된
파일이 아직 커밋되지 않은 파일을 import하는" 조합이 있으면 CI에서만
`ModuleNotFoundError`로 드러난다.

5-19 Phase 1 커밋(`4d6b968`) 작업 중 정확히 이런 패턴을 한 번 발견해서
(`content_engine/shorts_adapter.py` -> `content_engine/shorts_script.py`)
사용자께 확인받고 `shorts_script.py`를 함께 커밋했었다. **이번에 실패한
`tak_scout.scoring`도 완전히 동일한 패턴인데, 그때 이 파일까지는 점검하지
못하고 놓쳤다** — `scripts/run_scout.py`를 수정해 `from tak_scout.scoring
import top_candidates`를 추가했지만, `tak_scout/scoring.py` 자체는 여전히
git에 없는 상태였다. 이 부분은 제가 사전에 더 꼼꼼히 확인했어야 하는
점이었다.

`content_engine.youtube_publisher` 쪽은 5-19와 무관한 5-18 이전부터 있던
동일 패턴의 기존 문제이며, 이번 CI 실행에서 우연히 같이 드러났다(같은
`unittest discover` 호출이 테스트 디렉터리 전체를 한 번에 수집하기 때문에,
어느 한 파일만 고쳐서는 이 스텝 전체가 통과하지 않는다).

## 9. 검증된 최소 수정안 (아직 적용하지 않음)

`/tmp/ci-repro` worktree에 아래 4개 파일을 하나씩 추가하며 재확인한 결과,
**정확히 이 4개 파일을 추가로 커밋하면 `python3 -m unittest discover`가
278 tests 전부 통과(`OK`)한다**(로직 수정 없이 파일 추가만):

| 파일 | 필요한 이유 |
|---|---|
| `tak_scout/scoring.py` | `scripts/run_scout.py`(5-19에서 이미 커밋됨)가 직접 import |
| `content_engine/youtube_publisher.py` | `tests/test_upload_youtube_short_cli.py`(5-18에서 이미 커밋됨)가 직접 import |
| `content_engine/youtube_upload_history.py` | `scripts/upload_youtube_short.py`가 import(아래 항목의 연쇄 의존성) |
| `scripts/upload_youtube_short.py` | `tests/test_upload_youtube_short_cli.py`가 직접 import |

네 파일 모두 내부적으로 표준 라이브러리 + 이미 커밋된 모듈(`content_engine.models`,
`content_engine.threads_publisher`와 무관, `tak_scout.models`)만 참조하며,
추가 연쇄 의존성은 없음을 확인했다(각 파일의 `from .`/`import .` 구문을 grep으로
직접 확인).

이 4개 파일을 커밋에 포함하는 것 외에는 **`scripts/run_scout.py`,
`.github/workflows/daily-scout.yml`, `content_engine/shorts_adapter.py` 등
5-19에서 이미 만든 로직을 전혀 수정할 필요가 없다.**

## 10. 다음 단계 제안 (승인 후 진행)

1. 위 4개 파일을 커밋에 추가(로직 수정 없이 신규 파일 추가만)
2. push
3. `daily-scout.yml` workflow_dispatch 재실행(`max_candidates=5`)로 실제
   RSS 수집 -> 점수화 -> 상위 5개 선정 -> 파일 저장 -> commit/push까지
   끝까지 확인

**아직 아무 코드도 수정하지 않았고, workflow도 재실행하지 않았다** —
진행 여부를 확인해달라.
