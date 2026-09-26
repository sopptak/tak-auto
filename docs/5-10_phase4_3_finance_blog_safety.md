# 5-10 Phase 4-3 — 금융 Blog 안전 경계 문구 보존 보고서

## 1. 원인

`content_engine/generator.py::_criterion_blog()`는 `article_type == "finance"`일
때 항상 규칙 기반 원본 Blog 본문 끝에 고정 문구를 덧붙인다:

> "이 글의 금융 관련 내용은 원문 작성자의 설명이며, 금융기관의 공식 심사
> 기준으로 해석하지 않습니다."

`RewriteValidator._finance_errors`는 이 문구(정확히는
`_FINANCE_BOUNDARY_PATTERN`에 매치되는 문장)가 원본에 있었는데 재작성본에
없으면 무조건 거부한다. 그런데 실제 LLM 재작성 prompt
(`OpenAICompatibleRewriteProvider._system_prompt`/`_user_prompt`)는 지금까지
**"금융 콘텐츠는 공식 기준과 저자 의견의 경계를 유지하라"는 추상적인
지시만** 담고 있었다 - 정확히 *어떤 문장*을 *어떻게*(그대로 vs 의역해서)
보존해야 하는지는 알려주지 않았다. LLM은 "자연스럽게 다듬어도 된다"는
허용 지시와 "경계를 유지하라"는 금지 지시 사이에서, 이 딱딱한 법적 문구를
자연스러운 1인칭 블로그 톤으로 의역하거나 생략하는 쪽을 자주 선택했다
(Phase 4-1: 3/3, Phase 4-2: 1/1, 누적 4/4 Blog이 이 이유로만 rejected됨).

**결론**: 이것은 Validator의 버그가 아니라 **LLM에게 "무엇을 그대로
지켜야 하는지"를 명시적으로 알려주지 않은 prompt 설계의 공백**이었다.
Validator를 완화하지 않고, prompt 쪽에서 이 공백을 메우는 것이 이번
Phase의 목표다.

## 2. 수정 파일

- `content_engine/rewrite.py`
- `content_engine/llm_provider.py`
- `tests/test_content_engine.py`(테스트만 추가, production 코드 아님)

`RewriteRequest`/`RewriteProvider`/`RewriteResult`/`MockRewriteProvider`
등 기존 타입·계약은 **한 글자도 바꾸지 않았다**. `RewriteValidator`의
검증 로직(`_finance_errors`, `_new_number_errors` 등)도 전혀 건드리지
않았다 - Validator는 여전히 예전과 똑같은 기준으로 거부한다.

## 3. 수정 내용

### 3-1. `content_engine/rewrite.py` — 경계 문장 탐지 함수 추가(공개 함수)

```python
def find_finance_boundary_sentence(text: str) -> str | None:
    """금융 안전 경계 문구가 포함된 문장을 text에서 찾아 원문 그대로 반환한다.

    RewriteValidator._finance_errors가 재작성 결과를 검사할 때 쓰는 것과
    완전히 동일한 패턴(_FINANCE_BOUNDARY_PATTERN)을 사용한다 - LLM에게
    "반드시 그대로 보존하라"고 전달하는 문장과, 실제로 검증하는 문장이
    항상 같은 기준(단일 source of truth)을 공유하도록 하기 위함이다.
    """
    for sentence in _SENTENCE_PATTERN.findall(text):
        if _FINANCE_BOUNDARY_PATTERN.search(sentence):
            return sentence.strip()
    return None
```

Validator가 검증에 쓰는 것과 **똑같은 패턴**으로 문장을 찾기 때문에,
"LLM에게 보존하라고 알려준 문장"과 "실제로 검증할 문장"이 절대 어긋나지
않는다(별도 문구 하드코딩 없음 - 단일 기준).

### 3-2. `content_engine/llm_provider.py` — prompt에 문장 명시 + 지시 강화

`_user_prompt()`가 `article_type == "finance"`이고 원본 `draft.body`에서
경계 문장을 실제로 찾은 경우에만, prompt JSON에 새 필드를 추가한다:

```python
if request.article_type == "finance":
    boundary_sentence = find_finance_boundary_sentence(request.draft.body)
    if boundary_sentence:
        payload["finance_boundary_sentence_required_verbatim"] = boundary_sentence
```

`_system_prompt()`에는 이 필드가 있을 때 어떻게 행동해야 하는지 명시하는
문장을 추가했다:

> "When the user message includes 'finance_boundary_sentence_required_verbatim',
> that exact Korean sentence is a mandatory safety disclaimer: reproduce it
> character-for-character, unmodified, somewhere in your rewritten body. Do
> not paraphrase, translate, shorten, reorder its words, or omit it, even
> while you improve the rest of the text."

**금융 콘텐츠에만 적용되는 최소 범위**: `article_type != "finance"`이면
`boundary_sentence`를 아예 계산하지 않고, prompt에 이 필드 자체가
추가되지 않는다 - 시스템 프롬프트의 새 문장은 "필드가 있을 때"라는
조건부 지시라 일반 콘텐츠에는 아무 영향이 없다. Shorts/Threads도
`_criterion_content()`가 애초에 이 경계 문구를 넣지 않으므로(오직
`_criterion_blog`만 추가), `find_finance_boundary_sentence`가 그 초안
본문에서는 항상 `None`을 반환해 필드가 붙지 않는다 - Blog 하나에만
정확히 적용된다.

**새 사실/숫자 허용 없음, Validator 안전 기준 무변경**: 이 수정은 prompt에
"이 문장을 그대로 복사하라"는 지시 하나만 추가할 뿐, `RewriteValidator`의
어떤 검사도 느슨하게 하지 않았다. LLM이 지시를 어겨도(예: 문구를 계속
생략) Validator는 여전히 정확히 예전과 같은 기준으로 거부한다(4번 B, C
테스트로 확인).

## 4. 추가 테스트 수

`tests/test_content_engine.py::FinanceBoundaryPromptTests` — **6개**(실제
네트워크 없음, fake transport만 사용):

| # | 테스트 | 검증 내용 |
|---|---|---|
| 1 | `test_finance_prompt_includes_boundary_sentence_verbatim_field` | 금융 Blog prompt에 `finance_boundary_sentence_required_verbatim` 필드와 정확한 문장이 실리는지, system prompt에 "character-for-character" 지시가 있는지 |
| A | `test_a_finance_rewrite_preserving_boundary_sentence_passes` | fake LLM이 경계 문구를 그대로 포함해 재작성하면 **valid** |
| B | `test_b_finance_rewrite_dropping_boundary_sentence_is_rejected` | fake LLM이 경계 문구를 생략하면 **invalid**(기존 Validator 안전성 유지) - prompt에는 여전히 보존 지시가 있었음을 함께 확인 |
| C | `test_c_finance_rewrite_altering_boundary_sentence_meaning_is_rejected` | fake LLM이 문구를 반대 의미("공식 심사 기준입니다")로 바꾸면 **invalid** |
| D | `test_d_non_finance_prompt_has_no_boundary_field` | 비금융 Blog에는 이 필드가 prompt에 전혀 추가되지 않고, 재작성은 정상적으로 valid |
| F | `test_f_finance_shorts_and_threads_prompts_unaffected` | 같은 금융 KNOWLEDGE의 Shorts 3개·Threads 5개 전부, 원본에 경계 문구가 없으므로 이 필드가 붙지 않고 기존처럼 valid |

(E는 5번 전체 회귀 테스트 결과로 별도 테스트 없이 확인)

**결과**: 6개 전부 PASS.

## 5. 전체 테스트 결과

```
python3 -m unittest discover -s tests -p 'test_*.py'
Ran 351 tests in 12.873s
OK
```

Phase 4-2 종료 시점(345개) + 이번 신규 6개 = **351개 전부 PASS**. 기존
테스트(숫자 검증, Q1/A1 수정, `--id` 필터, 그 외 전체)는 단 하나도
깨지지 않았다.

## 6. 실제 LLM 테스트 방법

Phase 4-2와 동일한 방법론: 운영 데이터는 전혀 건드리지 않고, 임시
디렉터리에 Phase 4-1/4-2와 **동일한 KNOWLEDGE**
(`knowledge-scout-1815b0991f5e`, 임대료 소재)만 승인 상태로 담긴 파일을
직접 구성했다(Phase 4-1 보고서에 기록된 값 그대로 재구성 - 운영
`data/tak_brain_knowledge.json`은 읽지도 않음). 실제
`OpenAICompatibleRewriteProvider.from_environment()`(`TAK_MEDIA_LLM_ENDPOINT`
=`https://api.openai.com/v1/chat/completions`, `TAK_MEDIA_LLM_MODEL`=
`gpt-4o-mini`, 이번 프로세스에만 설정)로 `scripts/run_media_batch.py
--execute`를 **독립적으로 3회** 실행했다(Fake Provider 아님).

## 7. 실제 LLM 테스트 결과

| 실행 | Blog | Shorts(3개 중 valid) | Threads(5개 중 valid) | 총 valid |
|---|---|---|---|---|
| Run 1 | **rejected**(경계 문구 대신 prompt 필드 이름 자체가 본문에 출력됨) | 3 | 3 | 7/9 |
| Run 2 | **valid**(경계 문구 완전 보존) | 2 | 5 | 8/9 |
| Run 3 | **valid**(경계 문구 완전 보존, 인용부호로 감싸 인용) | 2 | 5 | 8/9 |

**실제 LLM 호출 수**: 3회 × 9 Draft = **27회**(각 실행 정확히 9회, 재시도
없음).

Phase 4-1/4-2 누적(4회 연속 Blog 0/4)과 비교하면 **2/3(66%)로 Blog이
valid를 얻기 시작했다** - 뚜렷한 개선이다. 다만 100%는 아니다(8번, 12번
참고).

## 8. 금융 경계 문구 보존 여부

- **Run 2**: `"...세입자의 입장에서... 도움이 된다고 말해주고 싶다. 이
  글의 금융 관련 내용은 원문 작성자의 설명이며, 금융기관의 공식 심사
  기준으로 해석하지 않습니다. 또한, 부동산 웹사이트 Zoopla에 따르면..."`
  → 문구가 토씨 하나 다르지 않게 본문 중간에 자연스럽게 녹아들어
  보존됐다.
- **Run 3**: `"...금융 관련 내용은 "이 글의 금융 관련 내용은 원문
  작성자의 설명이며, 금융기관의 공식 심사 기준으로 해석하지
  않습니다"."` → 인용부호로 감싸 인용하는 방식이지만, 문구 자체는 완전히
  그대로 보존됐다(Validator는 정규식 매치만 확인하므로 인용부호 유무와
  무관하게 정상적으로 통과했다).
- **Run 1**: 경계 문구 대신 **prompt JSON의 필드 이름
  `"finance_boundary_sentence_required_verbatim"` 문자열 자체**가 본문
  끝에 그대로 출력됐다 - LLM이 지시를 완전히 잘못 이해한 사례(12번에
  기록). 실제 경계 문구는 나타나지 않았고, Validator가 정확히 이를
  잡아내 rejected 처리했다.

**결론**: 3회 중 2회는 완벽하게 보존됐고, 1회는 LLM이 예상치 못한 방식으로
지시를 오해했다(문구 누락이 아니라 필드 이름 출력이라는 새로운 실패
양상). 완전한 결정론적 보장은 아니지만, 이전 4회 연속 실패(0%)에서
2/3(66%) 성공으로 뚜렷하게 개선됐다.

## 9. Blog valid 여부

**3회 중 2회 valid(Run 2, Run 3).** Run 1은 rejected였지만 사유가 달라졌다
- 더 이상 "그냥 문구를 생략/의역했다"가 아니라 "LLM이 prompt 구조 자체를
잘못 해석해 필드 이름을 출력했다"는, 이전과는 다른 새로운 실패
양상이다(12번).

## 10. Validator 안전성 유지 여부

**완전히 유지됨.** 이번 수정은 `RewriteValidator`의 어떤 메서드도
수정하지 않았다:

- Run 1처럼 LLM이 지시를 어겨 경계 문구가 없으면, Validator는 예전과
  똑같이 `"금융 콘텐츠의 공식 기준 비해석 경계가 유지되지 않았습니다."`로
  거부했다(4번 B 테스트로 재확인, 실제 LLM으로도 Run 1에서 재확인).
- 4번 C 테스트(경계 문구를 반대 의미로 바꾸면 거부)도 그대로 통과 -
  "의미가 바뀌면 거부"하는 기존 안전 기준이 전혀 느슨해지지 않았다.
- 새로운 숫자·사실을 허용하는 방향의 변경은 전혀 없다 - prompt에 문장 하나를
  "그대로 복사하라"고 추가했을 뿐, 어떤 검증 규칙도 낮추지 않았다.

## 11. 운영 데이터 무결성

코드 수정은 코드 파일만 변경했다. 실제 LLM 재검증은 전부 `/tmp` 임시
디렉터리의 KNOWLEDGE 파일만 사용했고, 운영 `data/tak_brain_knowledge.json`은
**읽지도 않았다**(Phase 4-1 보고서에 기록된 값으로 임시 파일을 직접
구성).

| 파일 | 테스트 전 | 테스트 후 | 결과 |
|---|---|---|---|
| `data/tak_scout_daily.json` | `cdbcc8f0...` | `cdbcc8f0...` | 동일 |
| `data/tak_interview_answers.json` | `f4e315c4...` | `f4e315c4...` | 동일 |
| `data/tak_brain_knowledge.json` | `3d441115...` | `3d441115...` | 동일 |
| `data/tak_interview_sessions.json` | 파일 없음 | 파일 없음 | 동일(생성되지 않음) |
| `data/tak_scout_dashboard_skipped.json` | 파일 없음 | 파일 없음 | 동일(생성되지 않음) |

**결과: ALL UNCHANGED.** 실제 Naver/Threads/YouTube 발행도 전혀 실행하지
않았다.

## 12. 남은 문제

1. **100% 결정론적이지 않음**: 3회 중 1회(Run 1)는 여전히 경계 문구가
   본문에 나타나지 않았다. 다만 실패 양상이 바뀌었다 - "문구를 의역/생략"이
   아니라 "prompt의 JSON 필드 이름 문자열 자체를 본문에 출력"하는, 이번
   수정이 만든 새로운(그리고 더 드문 것으로 보이는) 실패 유형이다. 코드
   버그가 아니라 LLM의 확률적 특성 - Validator가 정상적으로 잡아내므로
   안전에는 문제가 없지만, Blog 성공률을 더 끌어올리려면 별도 검토가
   필요하다(예: few-shot 예시를 prompt에 추가하는 방안 등 - 이번 단계
   범위 밖).
2. **Threads의 "경험" 키워드 오탐(Phase 4-2에서 이미 기록된 별도 문제)**은
   이번 3회 실행에서 1회(Run 1) 재현됐다 - 이번 Phase의 수정 대상이
   아니므로 손대지 않았다.
3. **Shorts의 "기관/상품명 추가" + "공식 기준 오해" 오탐**이 Run 3에서
   1회 관찰됐다(`사실 범위를 넓히는 표현이 추가되었습니다: 기관, 상품`) -
   금융 콘텐츠에서 LLM이 "부동산", "은행" 같은 일반 명사를 살짝 다른
   형태로 표현했을 때 `_ENTITY_PATTERN`/`_FACT_RISK_TERMS`가 오탐할
   가능성을 시사한다. 이번 Phase의 수정 대상이 아니며, 별도 검토 후보로만
   기록한다.

## 13. 결론

**PASS.**

목표(Validator를 완화하지 않고 LLM rewrite 단계에서 금융 안전 경계
문구를 보존시키는 것)를 최소 범위로 달성했다. `RewriteRequest`/
`RewriteProvider`/`RewriteValidator` 계약은 전혀 바꾸지 않았고, prompt에만
"금융 Blog일 때, 원본에서 실제로 발견된 경계 문장을 그대로 복사하라"는
조건부 지시 하나를 추가했다. 비금융 콘텐츠와 금융 Shorts/Threads(원본에
애초에 이 문구가 없음)에는 전혀 영향이 없음을 6개 신규 테스트로 증명했고,
351개 전체 테스트가 통과했다. 실제 LLM 3회 독립 실행에서 Blog valid가
0/4(Phase 4-1~4-2 누적) → 2/3(Phase 4-3)로 개선됐고, Validator는 LLM이
지시를 어긴 나머지 1회를 여전히 정확히 거부해 안전 기준이 전혀 느슨해지지
않았음을 실증했다. 완전한 100% 보장은 아니지만(12번), 안전장치를 낮추지
않으면서 실질적인 개선을 이뤘다는 점에서 이번 단계 목표를 충족한다고
판단한다.

---

## 수정 파일 / 테스트 결과 요약

- **수정 파일**: `content_engine/rewrite.py`, `content_engine/llm_provider.py`
  (+ `tests/test_content_engine.py`에 테스트만 추가)
- **추가 테스트**: 6개(`FinanceBoundaryPromptTests`)
- **전체 테스트**: 351/351 PASS(기존 345 + 신규 6)
- **실제 LLM 재검증**: 3회 독립 실행, 27회 실제 호출, Blog valid 2/3(Run
  2·3), Shorts 2~3/3, Threads 3~5/5
- **Validator 안전성**: 완전히 유지(경계 문구 누락/의미 변경 시 여전히
  정확하게 거부)
- **운영 데이터**: ALL UNCHANGED
- **git commit/push**: 없음(검토 대기)
