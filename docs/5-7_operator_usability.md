# 5-7 TAK AUTO 운영 편의성 개선

## 1. 개선 목적

5-6 단계(`docs/5-6_operator_e2e_test.md`)에서 TAK OPERATOR MVP
(`scripts/tak_auto.py`)가 실제 SCOUT 데이터 + 실제 LLM으로 끝까지 동작함을
확인했다. 다만 매일 반복 사용할 때, 오늘의 소재 10개 중 이미 답변한 것과
아직 답변하지 않은 것을 구분할 방법이 없어 매번 어떤 소재를 처리했는지
기억해야 하는 불편이 있었다. 이번 단계의 목적은 **완벽한 UI가 아니라**, 이
불편만 최소한으로 없애는 것이다:

1. 오늘의 소재 목록에서 이미 답변한 소재를 표시한다.
2. 이미 답변한 소재를 다시 선택하면 안내 문구를 보여준다.

그 외 콘텐츠 품질, Validator, LLM prompt, 자동 게시, UI, 데이터 구조 등은
이번 단계에서 전혀 건드리지 않았다(요청된 제한 사항 그대로 준수).

## 2. 변경 내용

기존 파일(`tak_scout`, `tak_brain`, `content_engine`, 다른 `scripts/*.py`,
`.github/workflows/*.yml`)은 전혀 수정하지 않았다. 변경은 5-6에서 새로 만든
`scripts/tak_auto.py`와 `tests/test_tak_auto_e2e.py`(둘 다 이번 프로젝트가
직접 만든 오케스트레이션/테스트 코드) 안에서만 이루어졌다.

`scripts/tak_auto.py`:

- `format_candidate_list(candidates, answered_scout_ids=frozenset())`:
  `data/tak_interview_answers.json`에 이미 답변이 있는 `scout_id`의 제목 뒤에
  `" [이미 답변함]"`을 붙이는 옵션 인자를 추가했다. 기존 호출부(기본값
  `frozenset()`)는 그대로 동작해 하위 호환된다.
- `select_candidate(...)`: 같은 `answered_scout_ids` 인자를 받아 목록에
  전달하고, 사용자가 이미 답변한 소재를 실제로 선택하면 다음 안내를 출력한다.

  ```
  이 소재에는 이미 답변이 있습니다.
  기존 답변을 다시 사용하거나 새로운 답변으로 덮어쓸 수 있습니다.
  ```

- `run_operator(...)`: 소재를 고르기 전에
  `tak_scout.load_answers(answers_path)`로 이미 답변한 `scout_id` 집합을
  읽어 `select_candidate`에 넘긴다. **`tak_scout.answers.load_answers`는
  기존 함수를 그대로 재사용**했고, 새 데이터 구조나 새 필드를 추가하지
  않았다.

이번 단계에서 KNOWLEDGE 생성/승인/중복 처리 로직(`append_scout_knowledge`,
`InterviewAnswer.create`/`upsert_answer`, `review_knowledge_file`)은 한 줄도
바꾸지 않았다 — 표시와 안내 문구만 추가했을 뿐, 저장되는 데이터나 판단
로직은 이전 단계와 완전히 동일하다.

## 3. 이미 답변한 소재 표시

실제 오늘 SCOUT 데이터(10개 소재, 전부 이미 답변됨)의 복사본으로 확인한
결과, 요청한 형식과 동일하게 표시된다:

```
1. Committee calls for bill to address AI threat to human rights [이미 답변함]
2. Gloomy forecast for tenants as rent rises set to speed up [이미 답변함]
...
10. Anthropic boss Dario Amodei calls for AI development to slow down [이미 답변함]
```

답변이 하나도 없는 소재 없이는 대조가 안 보이므로, 소재 2건 중 1건만 답한
가상 데이터로도 확인했다:

```
1. 예시: 중앙은행, 기준금리 동결 발표 [이미 답변함]
2. 예시: 수도권 아파트 거래량 반등
```

1번(이미 답변)에만 표시가 붙고 2번(미답변)에는 붙지 않는 것을 확인했다.
`data/tak_interview_answers.json`의 파일 구조나 내용은 조회만 했을 뿐 전혀
바꾸지 않았다.

## 4. 중복 소재 선택 처리

위 가상 데이터에서 1번(이미 A로 답변됨)을 다시 선택하자:

```
번호 선택: 1

이 소재에는 이미 답변이 있습니다.
기존 답변을 다시 사용하거나 새로운 답변으로 덮어쓸 수 있습니다.

선택한 소재:
제목: 예시: 중앙은행, 기준금리 동결 발표
...
선택 (A/B/C/D): B

TAK BRAIN: 신규 KNOWLEDGE 1건 생성 (미답변 건너뜀 1건, 중복 0건)
...
```

- 안내 문구가 정확히 출력됨을 확인.
- 새 답(B)을 입력하면 **기존 `upsert_answer` 그대로** 같은 `scout_id`의
  답변이 덮어써진다(A → B로 교체, 답변 파일은 여전히 1건). 실제로 확인한
  결과:

  ```json
  [
    {
      "scout_id": "scout-demo0000001",
      "selected_option": "B",
      "custom_answer": "",
      "answered_at": "2026-09-14T05:19:33...Z"
    }
  ]
  ```

- KNOWLEDGE 쪽은 `append_scout_knowledge`의 기존 설계(“scout_id + 선택지 +
  직접입력 내용”으로 결정되는 해시가 KNOWLEDGE id)가 그대로 적용된다. 답이
  A→B로 **내용이 바뀌면** 새 결정적 id가 생겨 KNOWLEDGE가 1건 더 늘어나고
  (A 기반 1건은 그대로 남고, B 기반 1건이 새로 추가됨), 반대로 **같은 답을
  또 제출하면** 같은 id이므로 중복으로 처리되어 추가되지 않는다(아래 5번
  테스트로 확인). 이는 이번에 새로 만든 동작이 아니라 `knowledge_bridge.py`의
  기존 설계이며, 새 KNOWLEDGE 스키마도 추가하지 않았다.

## 5. 테스트 결과

`tests/test_tak_auto_e2e.py`에 3개 테스트를 추가했다(기존 2개 + 신규 3개 =
총 5개):

1. `test_unanswered_candidate_has_no_marker` — 아직 아무도 답변하지 않은
   상태(`answered_scout_ids`가 비어 있음)에서는 목록 어디에도
   `[이미 답변함]`이 나오지 않는지 확인.
2. `test_answered_candidate_shows_marker` — 소재 2건 중 1건의 `scout_id`만
   `answered_scout_ids`에 넣으면, 정확히 그 소재의 목록 줄에만
   `[이미 답변함]`이 붙고 나머지 소재 줄에는 붙지 않는지 확인.
3. `test_reselecting_answered_candidate_warns_and_reuses_upsert_logic` —
   1회차(1번 소재 A로 답변 후 보류) → 2회차(같은 1번 소재를 다시 골라 B로
   덮어쓰고 보류)를 실행해:
   - 목록에 `[이미 답변함]`이 뜨는지,
   - 선택 시 안내 문구 2줄이 정확히 출력되는지,
   - `tak_interview_answers.json`이 여전히 1건이고 값이 B로 바뀌었는지
     (`upsert_answer` 재사용 확인),
   - KNOWLEDGE가 A 기반 1건 + B 기반 1건 = 2건으로 정상적으로 늘어나는지
     (새 스키마 없이 기존 결정적 id 로직 그대로),
   - 3회차로 **완전히 같은 B 답을 다시 제출**해도 KNOWLEDGE가 2건에서
     늘지 않는지(`append_scout_knowledge`의 기존 중복 처리 로직이 여전히
     정상 작동하는지)
   까지 전부 확인한다.

```
$ python3 -m unittest tests.test_tak_auto_e2e -v
test_answered_candidate_shows_marker ... ok
test_full_flow_select_answer_approve_media ... ok
test_hold_does_not_run_media ... ok
test_reselecting_answered_candidate_warns_and_reuses_upsert_logic ... ok
test_unanswered_candidate_has_no_marker ... ok

Ran 5 tests in 0.016s
OK
```

전체 기존 테스트 스위트:

```
$ python3 -m unittest discover -s tests -p 'test*.py'
Ran 243 tests in 1.734s
OK
```

**243/243 전체 통과**(5-6 단계 240건 + 이번에 추가한 신규 3건). 기존
E2E 테스트 2건(`test_full_flow_select_answer_approve_media`,
`test_hold_does_not_run_media`)도 함수 시그니처에 기본값을 추가하는 방식으로
바꿔 그대로 통과함을 확인했다(하위 호환 유지, 기존 테스트 코드 자체는 수정
하지 않음).

## 6. 실제 운영 데이터 테스트

실제 운영 데이터(`data/tak_scout_daily.json`, `data/tak_interview_answers.json`,
`data/tak_brain_knowledge.json`)를 세션 임시 디렉터리로 **복사**한 뒤 그
복사본만으로 실행했다:

```
$ python3 scripts/tak_auto.py --daily-pack <복사본> --answers <복사본> \
    --knowledge <복사본> --media-output <복사본>

1. Committee calls for bill to address AI threat to human rights [이미 답변함]
2. Gloomy forecast for tenants as rent rises set to speed up [이미 답변함]
...
10. Anthropic boss Dario Amodei calls for AI development to slow down [이미 답변함]

번호 선택: 1

이 소재에는 이미 답변이 있습니다.
기존 답변을 다시 사용하거나 새로운 답변으로 덮어쓸 수 있습니다.
...
```

오늘 실제 SCOUT 소재 10건은 이미 5-5~5-6 단계에서 전부 답변했기 때문에
10건 모두 `[이미 답변함]`으로 표시됐고, 1번을 다시 선택하니 안내 문구가
정확히 출력됨을 확인했다. 이 실행은 입력을 `A/B/C/D` 단계까지 진행하지
않고(번호만 준 뒤) 중단해, 복사본에도 새 답변을 추가로 기록하지 않았다.

실행 전후로 실제 데이터 파일 내용을 직접 비교해 변화가 없음을 확인했다:

```
data/tak_brain_knowledge.json: 총 21건 (승인 5 / 대기 7 / 거절 9) — 변화 없음
data/tak_interview_answers.json: 총 10건 — 변화 없음
```

## 7. 발견된 문제

1. 오늘 실제 SCOUT 데이터는 10건 전부 이미 답변된 상태라, 실제 데이터만
   가지고는 "표시 안 됨" 케이스를 눈으로 보여주기 어려웠다(그래서 4번 섹션에서
   가상 2건 데이터로 대조 확인함 — 실제 데이터에서의 로직 자체는 5번 테스트와
   6번의 안내 문구 출력으로 이미 검증됨).
2. 같은 소재를 다른 답으로 여러 번 덮어쓰면 KNOWLEDGE가 계속 쌓인다(4번 항목
   참고 — A 기반, B 기반 KNOWLEDGE가 각각 남음). 이번 단계는 "표시/안내"만
   추가하기로 했으므로 이 동작 자체는 건드리지 않았지만, 사람이 여러 번
   답을 바꾸는 습관이 있다면 pending/rejected KNOWLEDGE가 계속 누적될 수
   있다는 점은 알아둘 필요가 있다.
3. 목록에 몇 번째 항목이 이미 답변됐는지는 보이지만, "무엇으로 답했는지"는
   아직 보여주지 않는다(범위 밖 — 다음 단계 제안 참고).

## 8. 다음 단계 (제안, 이번 단계에서는 실행하지 않음)

1. 같은 소재를 다른 답으로 반복해서 덮어쓸 때 오래된 KNOWLEDGE(예: A 기반)를
   pending 상태에서 자동으로 정리할지(또는 그대로 사람이 review_knowledge.py로
   거절하게 둘지) 정책을 검토한다.
2. `[이미 답변함]` 옆에 실제 선택했던 옵션(A/B/C/D)까지 짧게 보여주는 방안을
   검토한다.
3. 이번 단계와 마찬가지로 "완벽한 UI"가 아니라 "실제 매일 쓸 때 불편한 지점"
   위주로 다음 개선 후보를 계속 모은다.
4. Validator/LLM prompt 개선, 자동 게시, 새 API 연결 등은 여전히 범위 밖이며
   사용자가 별도로 요청할 때 진행한다.
