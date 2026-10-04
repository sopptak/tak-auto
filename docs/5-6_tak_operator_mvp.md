# TAK OPERATOR MVP

## 1. 목표

TAK AUTO의 각 단계(SCOUT → INTERVIEW → BRAIN/KNOWLEDGE → 승인 → MEDIA)는 이미
개별 스크립트(`run_scout.py`, `run_interview.py`, `apply_interview.py`,
`review_knowledge.py`, `run_media_batch.py`)로 구현·테스트되어 있었지만, 사람이
매번 여러 스크립트를 손으로 순서대로 실행해야 했다. 이번 단계의 목표는 **완벽한
UI가 아니라**, 이 흐름을 하나의 CLI 진입점(`python3 scripts/tak_auto.py`)으로
묶어서

> "오늘 소재 하나 선택 → 내 의견 입력 → KNOWLEDGE → 승인 → MEDIA"

가 실제로 한 번에 끝까지 작동하는 것을 만드는 것이었다.

## 2. 기존 모듈 연결 구조

코드를 작성하기 전에 다음을 실제로 읽고 확인했다(추측 없이 현재 코드 기준).

- `tak_scout` (`models.py`, `collector.py`, `interview.py`, `answers.py`,
  `knowledge_bridge.py`): `ScoutCandidate`, `load_daily_pack`,
  `build_interview_question`, `InterviewAnswer.create`/`upsert_answer`,
  `append_scout_knowledge`, `build_knowledge_from_interview`가 이미 모두
  존재하며 `tak_scout/__init__.py`에서 export됨을 확인.
- `tak_brain` (`knowledge.py`, `models.py`): `load_knowledge_records`,
  `review_knowledge_file(path, knowledge_id, status, review_note=None)`,
  `select_approved`가 이미 존재하며 `scripts/review_knowledge.py`가 그대로
  사용 중임을 확인.
- `content_engine` (`pipeline.py`, `rewrite.py`, `llm_provider.py`):
  `run_media_batch_file(input_path, output_path, provider, knowledge_id=...)`,
  `MockRewriteProvider`, `OpenAICompatibleRewriteProvider.from_environment()`가
  이미 존재하며 `scripts/run_media_batch.py`가 그대로 사용 중임을 확인. `--id`로
  KNOWLEDGE 1건만 대상으로 실행하는 경로도 이미 지원됨을 확인(지난 단계에서
  실사용).
- `scripts/run_scout.py`, `run_interview.py`, `apply_interview.py`,
  `review_knowledge.py`, `run_media_batch.py`: 각각의 argparse 옵션과 내부에서
  호출하는 라이브러리 함수를 확인. 모두 "새 로직을 스크립트에 넣지 않고 기존
  함수만 호출한다"는 동일한 패턴을 따르고 있었다.
- `scripts/run_daily.py`: TAK BRAIN → TAK MEDIA → Threads를 잇는 기존
  오케스트레이터. **이번 Operator 설계가 그대로 참고한 템플릿**이다(라이브러리
  함수만 호출하고 새 로직을 만들지 않는 원칙, provider 선택 방식 등).
- `operator/`: 현재는 `README.md` 한 개만 있고 "Python 표준 라이브러리
  `operator`와의 이름 충돌을 피하기 위해 패키지로 초기화하지 않는다"고 명시되어
  있음을 확인. **이 설계를 그대로 존중**해 새 코드를 `operator/` 안에 두지
  않고, 기존 다른 오케스트레이터들과 동일하게 `scripts/tak_auto.py`에 두었다
  (실제로 `tests/`의 다른 테스트들도 `from scripts.run_daily import main`처럼
  `scripts.*`를 이름 충돌 없는 모듈 경로로 이미 사용하고 있음을 확인하고 따름).

결론적으로 **새 KNOWLEDGE 스키마, 새 Validator 규칙, 새 LLM 프롬프트, 새
Threads/Naver 게시 로직은 전혀 추가하지 않았다.** `scripts/tak_auto.py`는
위 모듈들의 기존 함수를 순서대로 호출하는 얇은 오케스트레이션 레이어일 뿐이다.

## 3. 사용자 실행 방법

```
python3 scripts/tak_auto.py
```

기본 경로:

| 인자 | 기본값 |
|---|---|
| `--daily-pack` | `data/tak_scout_daily.json` |
| `--answers` | `data/tak_interview_answers.json` |
| `--knowledge` | `data/tak_brain_knowledge.json` |
| `--media-output` | `data/tak_media_batch_operator.json` |

TAK MEDIA 단계는 기본적으로 **`MockRewriteProvider`(네트워크 호출 없음)**로
실행되어, API 키 설정 없이도 흐름 전체가 항상 끝까지 작동한다. 실제 LLM으로
재작성·검증까지 확인하려면:

```
python3 scripts/tak_auto.py --execute
```

를 사용한다(환경변수 `TAK_MEDIA_LLM_API_KEY`/`TAK_MEDIA_LLM_ENDPOINT`/
`TAK_MEDIA_LLM_MODEL` 필요 — `scripts/run_media_batch.py --execute`와 정확히
같은 규칙이며, 코드도 그대로 재사용함).

이 스크립트는 실행 중 **어떤 시점에도 Threads/Naver 게시 API를 호출하지
않는다.** TAK MEDIA 결과를 보여주고 종료하며, 실제 게시는 사람이 별도로
`scripts/publish_threads.py` 등 기존 스크립트를 통해 직접 결정·실행해야 한다.

## 4. 실제 CLI 화면 예시

아래는 **실제로 스크립트를 실행한 결과를 그대로 옮긴 것**이다(가짜로 작성한
화면이 아님). 오늘 실제 SCOUT 데이터를 건드리지 않기 위해 임시 디렉터리에 예시용
소재 2건(가상 데이터)과 빈 답변/KNOWLEDGE 파일을 준비해 `--daily-pack/--answers/
--knowledge/--media-output`으로 격리 실행했다. 입력은 `1`(1번 소재 선택) →
`D`(직접 입력) → `신기술은 두려워 말고 부딪혀서 느껴봐야 한다` → `Y`(승인)
순서로 주었다.

```
========================================
          TAK AUTO
========================================

오늘의 소재

1. 예시: 중앙은행, 기준금리 동결 발표
   출처: 예시 경제 뉴스
   요약: 중앙은행이 이번 회의에서 기준금리를 동결하기로 결정했다.

2. 예시: 수도권 아파트 거래량 반등
   출처: 예시 경제 뉴스
   요약: 수도권 아파트 거래량이 두 달 연속 늘었다.

번호 선택: 1

선택한 소재:

제목: 예시: 중앙은행, 기준금리 동결 발표
출처: 예시 경제 뉴스 (https://example.test/news/rate-hold)

질문:
[예시: 중앙은행, 기준금리 동결 발표] 이 경제 이슈에 대해 어떻게 생각하시나요?

A. 이 경제 이슈를 긍정적으로 본다
B. 이 경제 이슈를 부정적으로 본다
C. 상황을 더 지켜봐야 한다
D. 기타 / 내 생각 직접 입력

선택 (A/B/C/D): D
직접 입력: 신기술은 두려워 말고 부딪혀서 느껴봐야 한다

TAK BRAIN: 신규 KNOWLEDGE 1건 생성 (미답변 건너뜀 1건, 중복 0건)

KNOWLEDGE 생성 완료

id: knowledge-scout-3fd9c87d7869
제목: 예시: 중앙은행, 기준금리 동결 발표
도메인: 금융

  SOURCE FACT: 중앙은행이 이번 회의에서 기준금리를 동결하기로 결정했다.
  SOURCE URL: https://example.test/news/rate-hold
  USER ORIGINAL THOUGHT: 신기술은 두려워 말고 부딪혀서 느껴봐야 한다

현재 상태: pending

승인하시겠습니까? (Y=승인 / N=보류): Y

KNOWLEDGE 승인 완료: knowledge-scout-3fd9c87d7869 -> approved

TAK MEDIA 실행 중 (--execute 없이 실행: MockRewriteProvider 사용, 실제 LLM 호출 없음)...

결과:

Blog         valid
Shorts 1     valid
Shorts 2     valid
Shorts 3     valid
Threads 1    valid
Threads 2    valid
Threads 3    valid
Threads 4    valid
Threads 5    valid

총 9건 (valid 9, rejected 0, error 0)

배치 결과 저장: .../tak_media_batch_demo.json

안내: 위 결과는 Draft이며, Threads 실제 게시/Naver Blog 게시는 이 스크립트에서
수행하지 않습니다. 사람이 별도로 검토·게시하세요.
```

(`--daily-pack` 소재 2건 중 1번은 "미답변 건너뜀 1건"으로 정확히 집계됨 —
2번 소재는 이번 실행에서 답하지 않았으므로 KNOWLEDGE로 넘어가지 않았다.)

**참고**: 이번 예시는 `MockRewriteProvider`를 사용해 9건 전부 `valid`로
나왔다. Mock은 원본 Draft를 그대로 돌려주기 때문에 Validator가 항상 통과한다
(재작성 자체가 없으므로 당연한 결과). `--execute`로 실제 LLM을 쓰면 이전 단계
(`docs/5-5_first_scout_media_test.md`)에서 확인했듯 일부만 valid로 나올 수
있다 — 이는 Validator가 정상 작동한다는 뜻이며 Operator의 결함이 아니다.

## 5. 데이터 흐름

```
data/tak_scout_daily.json  (읽기 전용, 사용자가 선택)
        │  tak_scout.load_daily_pack
        ▼
  [사용자: 소재 1개 선택]
        │  tak_scout.build_interview_question
        ▼
  [사용자: A/B/C/D (+D면 직접 입력)]
        │  tak_scout.InterviewAnswer.create + upsert_answer
        ▼
data/tak_interview_answers.json  (갱신)
        │  tak_scout.append_scout_knowledge(daily_pack, answers, knowledge)
        ▼
data/tak_brain_knowledge.json  (신규 KNOWLEDGE, pending으로 추가)
        │  tak_brain.load_knowledge_records + build_knowledge_from_interview로 조회
        ▼
  [화면에 KNOWLEDGE 표시: SOURCE FACT / SOURCE URL / USER ANGLE|ORIGINAL THOUGHT]
        │
  [사용자: 승인(Y) / 보류(N)]
        │  Y → tak_brain.review_knowledge_file(..., "approved", ...)
        ▼           N → 상태 변경 없이 종료 (KNOWLEDGE는 pending으로 남음)
data/tak_brain_knowledge.json  (해당 항목만 approved로 갱신)
        │  content_engine.run_media_batch_file(knowledge, output, provider, knowledge_id=...)
        ▼
data/tak_media_batch_operator.json  (Blog 1 + Shorts 3 + Threads 5 = 9 Draft,
                                      각 valid/rejected/error 상태 포함)
        │
  [화면에 Draft별 상태 표시. 여기서 종료 — Threads/Naver 게시는 하지 않음]
```

이번 단계에서 새로 만든 파일은 위 흐름을 "읽고 쓰는" 오케스트레이션 코드뿐이며,
파일 스키마·검증 로직·KNOWLEDGE 생성 규칙은 모두 기존 그대로다.

## 6. 테스트 결과

새 E2E 테스트 `tests/test_tak_auto_e2e.py`를 추가했다(2개 케이스):

1. `test_full_flow_select_answer_approve_media` — RSS를 patch해 만든 소재 2건
   중 1번 선택 → D(직접 입력) → 커스텀 의견 저장 → 승인(Y) → TAK MEDIA까지
   실행되는지 확인. KNOWLEDGE가 `pending → approved`로 바뀌는지, evidence에
   `SOURCE FACT`/`SOURCE URL`/`USER ORIGINAL THOUGHT`와 사용자의 실제 문장이
   보존되는지, 9건(Blog 1 + Shorts 3 + Threads 5)이 생성되는지, "Threads 실제
   게시/Naver Blog 게시는 하지 않는다"는 안내 문구가 출력되는지까지 검증.
2. `test_hold_does_not_run_media` — 2번 소재 선택 → A 선택 → 보류(N)를 주면
   KNOWLEDGE가 `pending`으로 남고 TAK MEDIA는 아예 실행되지 않는지(출력 파일이
   생성되지 않는지) 확인.

두 테스트 모두 실제 RSS 네트워크, 실제 LLM API, 실제 Threads API를 호출하지
않는다(`fetch_rss`는 patch, TAK MEDIA는 기본값인 `MockRewriteProvider` 사용).

```
$ python3 -m unittest tests.test_tak_auto_e2e -v
test_full_flow_select_answer_approve_media ... ok
test_hold_does_not_run_media ... ok

Ran 2 tests in 0.009s
OK
```

전체 기존 테스트 스위트(`python3 -m unittest discover -s tests -p 'test*.py'`)도
실행했다:

```
Ran 240 tests in 1.764s
FAILED (failures=1)
```

**240건 중 239건 통과, 1건 실패.** 실패한 테스트는
`tests/test_media_batch.py::test_cli_dry_run_saves_json_output`이며, 이번
Operator 작업과 **무관한 기존(사전 존재) 이슈**다:

- 이 테스트는 `scripts/run_media_batch.py`를 `--input` 없이(=기본값인 실제
  `data/tak_brain_knowledge.json`) 실행해 `approved_knowledge_count == 4`를
  기대하는데, 실제로는 `5`가 나와 실패했다.
- 원인: 이 테스트가 임시 fixture가 아니라 **저장소의 실제 데이터 파일을 직접
  읽도록** 작성되어 있다. 지난 단계(`docs/5-5_dario_knowledge_approval.md`)에서
  사용자 지시에 따라 `knowledge-scout-b28b782b2a33`(Dario 소재)을 approve하면서
  실제 승인 KNOWLEDGE 수가 4건 → 5건으로 늘었고, 이 테스트의 하드코딩된 기대값
  `4`가 더 이상 현재 데이터와 맞지 않게 되었다.
- 이는 **이번 Operator 코드(`scripts/tak_auto.py`)나 새 테스트가 만든 회귀가
  아니다.** `scripts/tak_auto.py`, `tests/test_tak_auto_e2e.py`를 추가하기 전
  상태(이전 단계가 끝난 시점)에서도 이 테스트는 이미 실패 상태였을 것이다(원인이
  이번 작업 이전 단계의 데이터 변경이기 때문).
- 이번 단계 지시("기존 TAK MEDIA 코드를 불필요하게 수정하지 않는다", "코드
  수정은 오직 Operator에 집중")에 따라 **이 기존 테스트 파일은 수정하지
  않았다.**

## 7. 변경 파일

이번 단계에서 새로 추가한 파일만 있으며, 기존 파일은 하나도 수정하지 않았다.

| 파일 | 종류 | 설명 |
|---|---|---|
| `scripts/tak_auto.py` | 신규 | TAK OPERATOR MVP CLI 진입점 |
| `tests/test_tak_auto_e2e.py` | 신규 | Operator 전체 흐름 E2E 테스트 2건 |
| `docs/5-6_tak_operator_mvp.md` | 신규 | 이 보고서 |

`tak_scout`, `tak_brain`, `content_engine`, `operator/`, 기존 `scripts/*.py`,
`.github/workflows/*.yml`은 전혀 수정하지 않았다(git diff 없음, `git status`로
확인 가능).

## 8. 현재 한계

1. **위 [6]의 사전 존재 테스트 실패**: `data/tak_brain_knowledge.json`의 실제
   승인 건수에 의존하는 기존 테스트가 있어, 앞으로도 KNOWLEDGE를 승인할 때마다
   같은 이유로 깨질 수 있다(이번 단계 범위 밖이라 수정하지 않음).
2. **재시도 제한 없음**: 번호/선택지 입력이 잘못되면 무한히 다시 묻는다(MVP
   범위에서는 의도적으로 단순하게 둠). Ctrl+D(EOF) 등으로만 중단 가능.
3. **`보류`는 상태를 그대로 둔다**: 이미 이전에 `approved`/`rejected`였던
   KNOWLEDGE를 다시 골라 같은 답을 하면(결정적 id라 동일 KNOWLEDGE를 다시
   가리킴), 승인(Y)을 누르면 이전 상태와 무관하게 `approved`로 덮어쓴다(사람이
   "지금" 내리는 결정을 우선한다는 기존 `review_knowledge.py --approve`와 동일한
   동작). 보류(N)를 눌러도 기존 상태를 되돌리지는 않는다.
4. **MockRewriteProvider 기본값의 함정**: `--execute` 없이 실행하면 항상
   전부 `valid`로 보인다(재작성이 아예 일어나지 않기 때문). "TAK MEDIA가 항상
   9/9 통과한다"는 착각을 줄 수 있어 문서([4], [8])에 명시적으로 경고를
   남겼다.
5. **중복 소재 선택 시 안내 부족**: 이미 답변한 소재를 다시 선택해도 막지
   않는다(에러는 아니지만, 사용자가 "새 소재"로 착각할 수 있음). 목록에
   "이미 답변함" 같은 표시는 이번 MVP에는 없다.
6. **Threads/Naver 게시로 이어지는 다음 버튼 없음**: 의도적으로 만들지
   않았다(요구사항). 결과 확인 후 게시는 여전히 사람이 기존 스크립트로 별도
   진행해야 한다.

## 9. 다음 단계 (제안, 이번 단계에서는 실행하지 않음)

1. `data/tak_brain_knowledge.json`에 의존하는 기존 테스트들을 실제 데이터가
   아닌 fixture/임시 디렉터리 기반으로 바꾸는 방안을 별도로 검토한다([6]의
   근본 원인 제거).
2. 목록에 "이미 답변한 소재" 표시를 추가해 사용자가 오늘 처리할 소재를 더
   쉽게 고를 수 있게 하는 방안을 검토한다.
3. `--execute` 여부와 무관하게, KNOWLEDGE가 이미 `approved`/`rejected`
   상태일 때 "다시 승인하시겠습니까?" 같은 명시적 확인 문구를 추가하는 방안을
   검토한다.
4. TAK MEDIA 결과 확인 후, 사람이 원하면 이어서 `scripts/publish_threads.py`를
   수동으로 실행하도록 안내 문구에 정확한 다음 명령을 포함하는 방안을 검토한다
   (자동 실행은 계속 하지 않음).
5. 위 항목들은 모두 사용자 승인 후 별도 단계에서 진행한다.
