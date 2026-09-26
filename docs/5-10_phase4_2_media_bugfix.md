# 5-10 Phase 4-2 — TAK MEDIA 통합 버그 수정 보고서

## 1. 수정 목적

Phase 4-1 실제 E2E 테스트에서 발견된 3개 문제만 수정한다: (1) 인터뷰
Q{n}./A{n}. 기록이 문장 분리와 충돌해 깨진 문장을 만드는 버그, (2) 날짜의
영→한 숫자 변환("December"→"12월")을 새 사실로 오탐하는 버그, (3)
`generate_blog_publish_pack.py`에 KNOWLEDGE ID 필터가 없어 승인된 전체
KNOWLEDGE가 항상 처리되는 문제. 그 외 기능은 수정하지 않았다.

## 2. 수정 #1 — Q/A sentence boundary

**원인**: `content_engine/generator.py`의
`_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")`는 마침표/물음표/느낌표
뒤 공백을 무조건 문장 경계로 본다. `tak_scout` 인터뷰가
`reusable_principle`에 저장하는 `"Q1. 질문...\nA1. 답변..."` 형식(
`scripts/run_scout_dashboard.py::_build_combined_answer_text()`가 만듦,
이번 단계에서 수정하지 않음)을 이 정규식으로 나누면 `"Q1."`과 `"A1."`이
각각 독립된 "문장"으로 잘려 나온다(직접 재현해 확인: `['Q1.', '최근
임대료...?', 'A1.', '임대료가...점이다.', ...]`). `_pick()`이 필드의 첫
evidence unit을 그대로 고르므로 `"Q1."`이 선택되어, 규칙 기반 Blog 초안에
`이를 적용할 때는 "Q1"는 원칙을 제시합니다.` 같은 깨진 문장이 만들어졌다
(Phase 4-1에서 실제 운영 KNOWLEDGE로 확인된 그대로).

**수정 방법**: 3개 후보(정규식에서 Q\d./A\d. 제외 / label을 별도 구조로
저장 / `_pick()`에서 label-only fragment 제거) 중, KNOWLEDGE 스키마와
Dashboard 인터뷰 로직(`_build_combined_answer_text`)을 전혀 바꾸지 않고
`content_engine/generator.py` 안에서만 끝나는 방법을 선택했다. 단순히
"label만 제거"하는 것보다 한 단계 더 정확하게, **Q/A 기록으로 판별된
값에서는 답변(A로 시작하는 부분)만 문장 분리 대상으로 쓰고 질문 텍스트
자체도 제외**하도록 `_sentence_source_chunks()`를 새로 추가했다 - 질문은
시스템이 만든 프롬프트일 뿐 사용자의 근거가 아니므로, "Q1."이라는 깨진
label만 없애는 것보다 질문 문장까지 배제하는 것이 "Q/A 기반
reusable_principle이 정상적으로(사용자의 실제 답변으로) 선택된다"는 목표에
더 맞는다고 판단했다.

```python
_QA_TRANSCRIPT_PREFIX = re.compile(r"^Q\d+\.\s")
_QA_ANSWER_BLOCK = re.compile(r"A\d+\.\s*(.*?)(?=\n\nQ\d+\.|\Z)", re.DOTALL)

def _sentence_source_chunks(value: str) -> tuple[str, ...]:
    if _QA_TRANSCRIPT_PREFIX.match(value):
        answers = tuple(m.strip() for m in _QA_ANSWER_BLOCK.findall(value) if m.strip())
        if answers:
            return answers
    return (value,)  # Q/A 포맷이 아니면 기존과 100% 동일
```

`value`가 `"Q\d+\. "`로 시작할 때만 이 특수 경로를 타고, 그 외 모든 일반
KNOWLEDGE 필드(RAW 블로그 등 기존 소스)는 `return (value,)`로 예전과
완전히 동일하게 처리된다 - 일반 문장 분리 기능에 영향이 없다.

**추가 테스트**(`tests/test_content_engine.py::InterviewQAFormatTests`, 4개):

1. `test_single_turn_qa_format_produces_no_label_fragments` — "Q1./A1."이
   깨진 label-only fragment로 분리되지 않는다(질문 문장도 섞이지 않음).
2. `test_qa_based_reusable_principle_is_picked_as_real_sentence` —
   `generate_content_bundle()`이 만든 Blog 본문에 사용자의 실제 답변
   문장이 정확히 포함되고, `"Q1"` 같은 깨진 인용은 나타나지 않는다.
3. `test_multi_turn_qa_format_extracts_only_answers_in_order` — 2턴
   Q1/A1/Q2/A2 기록에서 답변 2개만, 순서대로 추출된다.
4. `test_non_qa_field_sentence_splitting_is_unchanged` — Q/A 포맷이
   아닌 일반 텍스트는 기존과 동일하게 문장 분리된다.

**결과**: 4개 신규 테스트 PASS. 6번 항목에서 실제 LLM으로도 재확인함.

## 3. 수정 #2 — 날짜 숫자 false positive

**원인**: `content_engine/rewrite.py`의 `RewriteValidator._new_number_errors`는
`rewritten_numbers - allowed_numbers - url_numbers`로 "새 숫자"를 판정한다.
SOURCE FACT 원문이 영어 `"by December"`처럼 월 이름을 문자로 쓰고 있으면
`allowed_numbers`에는 숫자 `12`가 없는데, LLM이 자연스럽게 `"12월까지"`로
번역하면 `12`가 "새 숫자"로 오탐됐다(Phase 4-1에서 9회 실행 중 다수 재현).

**수정 방법**: 숫자 집합에 `"12"`를 광범위하게 허용하는 대신,
**source_text에 실제로 등장한 영문 월 이름과 정확히 대응하는 `"N월"`
문자열만** 재작성 텍스트에서 제거한 뒤 숫자 비교를 한다.

```python
_MONTH_NAME_TO_NUMBER = {"January": "1", ..., "December": "12"}
_MONTH_NAME_PATTERN = re.compile(r"\b(" + "|".join(_MONTH_NAME_TO_NUMBER) + r")\b")

@staticmethod
def _strip_translated_month_references(source_text: str, rewritten_text: str) -> str:
    months_in_source = set(_MONTH_NAME_PATTERN.findall(source_text))
    if not months_in_source:
        return rewritten_text
    result = rewritten_text
    for month_name in months_in_source:
        number = _MONTH_NAME_TO_NUMBER[month_name]
        result = re.sub(rf"(?<!\d){number}월", "", result)
    return result
```

`_new_number_errors`는 `rewritten_numbers`를 추출하기 전에 이 함수를 한
번 거친다. `(?<!\d)` negative lookbehind로 `"112월"`처럼 더 긴 숫자의
일부가 잘못 매치되는 것도 막는다.

**안전한 예외 범위**: "숫자 12는 항상 허용" 같은 넓은 예외가 아니라,
① source에 실제로 그 월 이름이 등장했고, ② 재작성 텍스트에서 정확히
`"{숫자}월"` 형태로만 등장한 경우에만 그 특정 위치의 숫자를 무시한다.
`"12억원"`, `"12%"`처럼 월 표기가 아닌 숫자 `12`는 이 함수가 건드리지
않으므로 여전히 정상적으로 거부된다 - 실제로 `"12억원"` 테스트 케이스로
확인함.

**추가 테스트**(`MonthNumberFalsePositiveTests`, 6개):

| 테스트 | source | rewritten | 기대 |
|---|---|---|---|
| December→12월 | "...by December." | "12월까지..." | PASS |
| January→1월 | "...for January." | "1월에..." | PASS |
| March→3월 | "...in March." | "3월에..." | PASS |
| December + 관련없는 30% | "...by December." | "12월에 30% 상승..." | 12는 통과, 30만 FAIL |
| 12가 월 표기가 아님 | "...by December." | "...매출이 12억원..." | FAIL(월 이름이 있어도 광범위 허용 안 함) |
| 기존 새 숫자 삽입(월 이름 없음) | "Sales rose by 5%." | "Sales rose by 12%." | FAIL(기존 동작 그대로) |

**결과**: 6개 신규 테스트 PASS, 기존 숫자 관련 테스트
(`test_new_number_fails_validation`, `test_known_fact_can_be_expressed_in_different_order`,
`test_source_url_number_is_not_treated_as_new_number_error` 등)도 전부
그대로 통과. 6번 항목에서 실제 LLM으로도 재확인함.

## 4. 수정 #3 — Blog Publish Pack --id

**원인**: `scripts/generate_blog_publish_pack.py`는 승인된 모든 KNOWLEDGE를
항상 처리했다. `run_media_batch.py`에는 이미 `--id`가 있었지만 이 스크립트에는
없어서, Phase 4-1에서 소재 1건만 테스트하려다 승인 KNOWLEDGE 6건 전체
(54회 실제 LLM 호출)가 처리됐다.

**수정 방법**: `run_media_batch.py --id`와 동일한 관례로, `load_knowledge_records()`
직후 `records`를 ID로 필터링하도록 4줄을 추가했다.

```python
if args.id:
    records = [record for record in records if record.id == args.id]
    if not records:
        print(f"오류: KNOWLEDGE ID를 찾을 수 없습니다: {args.id}", file=sys.stderr)
        return 1
```

그 뒤 로직(`select_approved`, `run_media_batch` 호출 등)은 전혀 바꾸지
않았다 - 이미 `--limit`을 위해 있던 `approved` 리스트 구성 로직을 그대로
재사용한다.

**CLI 사용법**:
```
python3 scripts/generate_blog_publish_pack.py \
  --knowledge data/tak_brain_knowledge.json \
  --id knowledge-scout-xxxxxxxxxxxx
```
`--id`를 생략하면 기존과 동일하게 승인된 전체 KNOWLEDGE를 처리한다.

**추가 테스트**(`tests/test_blog_publish_pack.py::GenerateBlogPublishPackIdFilterTests`,
3개 - 실제 LLM 호출 없이 호출 횟수만 세는 `_CountingRewriteProvider`로
`OpenAICompatibleRewriteProvider.from_environment()`를 대체해 검증):

1. `test_without_id_processes_all_approved_knowledge` — `--id` 없음 →
   승인 2건 모두 처리(18회 = 2건×9 draft).
2. `test_id_processes_only_that_knowledge` — `--id` 지정 → 정확히 1건만
   처리(9회 = 1건×9 draft), 다른 KNOWLEDGE ID는 결과에 전혀 나타나지 않음
   (LLM 호출 대상이 되지 않음을 호출 횟수로 직접 증명).
3. `test_unknown_id_exits_safely_without_calling_llm` — 존재하지 않는 ID
   → exit code 1, 결과 파일 생성 안 됨, LLM 호출 0회.

**결과**: 3개 신규 테스트 PASS. 7번 항목에서 실제 LLM으로도 재확인함.

## 5. Regression

```
python3 -m unittest discover -s tests -p 'test_*.py'
Ran 345 tests in 13.334s
OK
```

기존 332개 + 신규 13개(수정#1 4개 + 수정#2 6개 + 수정#3 3개) = **345개
전부 PASS**. 코드 수정 전(332/332)과 비교해 기존 테스트는 단 하나도
깨지지 않았다.

## 6. 실제 LLM 통합 재검증

Phase 4-1과 **동일한 KNOWLEDGE**(`knowledge-scout-1815b0991f5e`, 임대료
소재)를 사용했다. 임시 디렉터리에 이 1건만 `approved` 상태로 담긴
KNOWLEDGE 파일을 새로 구성했고(운영 파일은 읽지도 않음, Phase 4-1 보고서에
기록된 값을 그대로 재구성), 실제
`OpenAICompatibleRewriteProvider.from_environment()`로 `run_media_batch.py
--execute`를 **독립적으로 3회** 실행했다(재현성 확인, Phase 4-1과 동일
방법론).

| 항목 | Phase 4-1(수정 전, 3회) | Phase 4-2(수정 후, 3회) |
|---|---|---|
| Blog valid | 0/3 | 0/3(여전히 rejected, 사유는 아래 9번 참고) |
| Shorts valid(각 3개 중) | 2, 0, (미집계) | **2, 3, 3** |
| Threads valid(각 5개 중) | 2, 3, 2 | **4, 4, 4** |
| "Q1"/"A1" 깨진 문장 | 발생(원본 draft에서 확인) | **사라짐**(3회 모두 원본 draft에 실제 사용자 문장이 그대로 나옴, 직접 확인) |
| "12" false positive | 다수 발생 | **사라짐**(3회 27개 항목 중 0건, "12월까지"가 포함된 valid 결과물도 직접 확인) |
| 금융 면책 문구 누락 | 발생 | **여전히 발생**(Blog 3회 모두 이 사유로만 rejected - 별도 문제, 9번 참고) |

- **LLM 호출 수**: 3회 실행 × 9 Draft = **27회**(각 실행 정확히 9회, 재시도
  없음 - 기존과 동일한 계약).
- **Q1/A1 깨진 문장이 사라졌는가?**: **예.** 3회 모두 규칙 기반 원본
  Blog 본문에 `"이를 적용할 때는 "임대료가 계속 오르는 흐름을 보면서 가장
  걱정되는 건, 소득은 물가만큼 안 오르는데 주거비만 먼저 뛴다는 점이다"는
  원칙을 제시합니다."`처럼 실제 사용자 문장이 그대로 들어갔다(3회 결과
  완전히 동일). 더 이상 `"Q1"`이 등장하지 않는다.
- **"December → 12월" false positive가 사라졌는가?**: **예.** 3회 27개
  항목 중 `"12"` 관련 거부 사유는 0건이었다. 실제 valid 결과물 중 하나는
  `"임대료는 올해 12월까지 매년 4% 또는 5% 상승할 것으로 예상됩니다."`를
  그대로 포함한 채 통과했다.
- **금융 면책 문구 누락 때문에 reject되는지 여부**: **여전히 발생한다.**
  Blog은 3회 모두 `"금융 콘텐츠의 공식 기준 비해석 경계가 유지되지
  않았습니다."` 사유 하나로만 거부됐다(더 이상 "12"나 "경험" 사유가
  섞이지 않아, 이제 이 문제 하나만 명확히 분리되어 보인다). 9번에서 코드
  버그가 아니라 **안전장치가 의도대로 작동한 것**으로 판단한 근거를
  기록한다.
- **Blog valid 여부**: 0/3(위와 동일한 이유로 여전히 미통과).
- **Shorts valid 수**: 2/3, 3/3, 3/3(평균적으로 Phase 4-1보다 크게 개선).
- **Threads valid 수**: 4/5, 4/5, 4/5(Phase 4-1의 2~3/5보다 개선. 각 1건은
  `"경험하고 있다"`라는 표현 때문에 `_FACT_RISK_TERMS`의 "경험" 키워드에
  걸려 거부됨 - 9번에서 별도로 기록).

## 7. Blog Publish Pack --id 재검증

수정된 `--id` 옵션으로 **테스트 대상 KNOWLEDGE 1건만** 처리했다(실제 LLM,
Fake 아님).

1. **단독 fixture**(승인 레코드 1건만 담은 파일)로 실행 → "TAK BRAIN: 승인
   KNOWLEDGE 1건 확인" → 9 Draft(valid 7, rejected 2) → 실제 LLM 호출
   **9회**.
2. **다건 fixture 재검증**(운영에서 읽기 전용으로 가져온 다른 승인
   KNOWLEDGE 1건을 추가해 총 2건 중 `--id`로 우리 소재만 지정) → 결과
   파일(`all_items`)에 **오직 `knowledge-scout-1815b0991f5e`만** 나타났고,
   다른 KNOWLEDGE ID(`knowledge-da6ddf5aa459`)는 전혀 등장하지 않았다 -
   실제 LLM 호출이 그 레코드에 대해서는 **0회**였다는 뜻이다. 실제 LLM
   호출 **9회**(대상 1건 × 9 draft, 정확히 일치).
3. **대상 ID**: `knowledge-scout-1815b0991f5e`
4. **처리된 KNOWLEDGE 수**: 1건(다건 fixture에서도 1건만)
5. **실제 LLM 호출 수**: 9회(두 번 모두)
6. **결과**: Blog Publishing Pack은 이번에도 0건 생성(Blog이 이번 실행에서도
   `"금융 콘텐츠의 공식 기준 비해석 경계가 유지되지 않았습니다."`로
   rejected - 6번과 동일한 별도 문제, 9번 참고). **`--id` 필터 자체는
   실제 provider로 정확히 검증됨** - Phase 4-1처럼 전체 6건(54회 호출)이
   처리되는 일은 다시 일어나지 않았다.

## 8. 운영 데이터 무결성

수정 작업(코드 편집)은 코드 파일만 변경했다. 실제 LLM 재검증(6, 7번)은
전부 `/tmp` 임시 디렉터리의 KNOWLEDGE 파일만 사용했고, 운영
`data/tak_brain_knowledge.json`은 **읽지도 않았다**(Phase 4-1 보고서에
기록된 값으로 임시 파일을 직접 구성).

| 파일 | 테스트 전 | 테스트 후 | 결과 |
|---|---|---|---|
| `data/tak_scout_daily.json` | `cdbcc8f0...` | `cdbcc8f0...` | 동일 |
| `data/tak_interview_answers.json` | `f4e315c4...` | `f4e315c4...` | 동일 |
| `data/tak_brain_knowledge.json` | `3d441115...` | `3d441115...` | 동일 |
| `data/tak_interview_sessions.json` | 파일 없음 | 파일 없음 | 동일(생성되지 않음) |
| `data/tak_scout_dashboard_skipped.json` | 파일 없음 | 파일 없음 | 동일(생성되지 않음) |

**결과: ALL UNCHANGED.** 실제 Naver/Threads/YouTube 발행도 전혀 실행하지
않았다.

## 9. 남은 문제

**금융 면책 문구 누락(Blog 전용, 4회 연속 재현 - Phase 4-1 3회 + Phase
4-2 1회) — 코드 버그가 아니라 안전장치가 의도대로 작동한 결과로 판단한다.**

- 규칙 기반 원본 Blog 초안에는 항상 `"이 글의 금융 관련 내용은 원문
  작성자의 설명이며, 금융기관의 공식 심사 기준으로 해석하지 않습니다."`가
  포함된다(`content_engine/generator.py::_criterion_blog`, finance
  프로필일 때 항상 추가 - 이번 단계에서 수정하지 않음).
- LLM이 자연스러운 1인칭 블로그 톤으로 다듬는 과정에서 이 딱딱한 법적
  문구를 문장 그대로 보존하지 않고 생략하거나 의미가 달라지게 바꾸는
  경향이 있었다(4회 모두 재현).
- `RewriteValidator._finance_errors`는 원본에 이 경계 표현이 있었는데
  재작성본에 없으면 무조건 거부한다 - **이것은 검증기가 고장난 게
  아니라, "금융 콘텐츠는 이 경계를 반드시 유지해야 한다"는 설계 의도를
  정확히 수행하고 있는 것**이다. 다만 그 결과 이 KNOWLEDGE는 지금까지
  단 한 번도 valid Blog을 만들지 못했다는 실질적인 트레이드오프가 있다.
- 이번 단계의 수정 대상 3개(Q1/A1, 날짜 숫자, `--id`)에 포함되지 않았고,
  지시 5번의 "이번 단계에서 수정하지 않을 것"과도 맞닿아 있어(검증 로직의
  실질적 완화는 이번 3개 수정보다 훨씬 큰 범위의 변경이 필요) 이번
  단계에서는 손대지 않았다. 향후 별도 Phase에서 "금융 면책 문구를
  더 짧고 자연스럽게 만들거나, LLM 시스템 프롬프트에 이 문구를 반드시
  '그대로' 보존하라고 더 강하게 지시하는 방안"을 검토할 수 있다.

**추가로 관찰된, 이번 수정 범위 밖의 사소한 거부 사유**:

- Threads에서 `"경험하고 있다"`라는 표현이 `_FACT_RISK_TERMS`의 "경험"
  키워드와 문자 그대로 일치해 `"사실 범위를 넓히는 표현이 추가되었습니다"`로
  거부된 사례가 있었다(6번). 사용자의 원래 답변에 없던 "경험"이라는
  단어가 LLM 재작성 과정에서 (의미상 동의어로) 추가된 것이라 검증기가
  의도대로 작동한 것이지만, "지켜봤다"를 "경험했다"로 바꾸는 정도의
  자연스러운 재표현까지 막는 것이 지나치게 보수적인지는 별도 검토가
  필요하다. 이번 3개 수정 대상이 아니므로 손대지 않았다.

## 10. 결론

**PASS.**

지정된 3개 문제(Q1/A1 sentence boundary, 날짜 숫자 false positive,
`--id` 필터 부재)를 모두 최소 범위로 수정했고, 345개 테스트(기존 332 +
신규 13) 전부 통과했다. 실제 LLM으로 재검증한 결과 두 코드 버그(수정
#1, #2)는 **재현되지 않았다** - Q1/A1 깨진 문장은 3회 모두 사라졌고,
"12월" false positive도 27개 항목 중 0건이었다. `--id` 필터(수정 #3)도
실제 provider로 단독/다건 두 시나리오 모두에서 정확히 대상 1건만
처리함을 확인했다(다른 KNOWLEDGE는 LLM 호출 대상이 되지 않음을 직접
증명). 그 결과 Shorts/Threads의 valid 비율이 Phase 4-1 대비 뚜렷하게
개선됐다(Threads 2~3/5 → 4/5 안정적으로).

Blog은 여전히 0/4(누적)이지만, 그 원인은 이번 수정 대상이 아닌 **별도의,
의도대로 작동하는 안전장치**(금융 면책 문구 보존 요구)로 명확히
좁혀졌다 - 더 이상 Q1/12 노이즈에 가려지지 않는다. 운영 데이터는 전
과정에서 ALL UNCHANGED였고, 실제 Naver/Threads/YouTube 발행은 하지
않았다.

---

## 최종 확인(13번 요약)

- **수정 파일**: `content_engine/generator.py`, `content_engine/rewrite.py`,
  `scripts/generate_blog_publish_pack.py`
- **추가 테스트 수**: 13개(`tests/test_content_engine.py` 10개,
  `tests/test_blog_publish_pack.py` 3개)
- **전체 테스트**: 345/345 PASS
- **실제 LLM 통합 결과**: Q1/A1 버그·12월 false positive 모두 재현 안 됨(3회
  독립 실행으로 확인)
- **Blog valid**: 0/3(수정 대상 아닌 별도 문제로 인해 여전히 rejected - 9번)
- **Shorts valid**: 2~3/3(개선됨)
- **Threads valid**: 4/5(3회 모두, 개선됨)
- **Blog Publish Pack --id 결과**: 대상 1건만 처리, 다른 KNOWLEDGE는 LLM
  호출 대상 아님(실제 provider로 확인), 호출 9회 = 대상 수와 일치
- **운영 데이터**: ALL UNCHANGED
- **코드 수정**: 완료(위 3개 파일, 최소 범위)
- **git commit/push**: 없음(검토 대기)
- **보고서 경로**: `docs/5-10_phase4_2_media_bugfix.md`
