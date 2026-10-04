# TAK_MEDIA_LLM_MODEL=gpt-5.6-luna 호환성 조사 (코드 수정 없음, 실제 TAK_MEDIA_LLM API 호출 없음)

## 방법

1. `tak_scout/interview_llm.py`, `content_engine/llm_provider.py`의 실제 HTTP
   요청 payload 구성 코드를 직접 읽었다.
2. `gpt-5.6-luna`가 실제 존재하는 모델인지, Chat Completions API에서 어떤
   파라미터를 요구/지원하는지는 코드만으로 알 수 없으므로 일반 웹 검색으로
   외부 정보를 확인했다(TAK_MEDIA_LLM_API_KEY로 실제 API를 호출한 것이 아니라,
   OpenAI 공식/3rd-party 문서를 조회한 일반 웹 검색이다).

## 1. 현재 코드가 보내는 실제 요청 payload

`interview_llm.py:237-242`, `llm_provider.py:106-113` 둘 다 동일한 구조:

```python
{
    "model": self.model,                 # TAK_MEDIA_LLM_MODEL 값 그대로
    "response_format": {"type": "json_object"},
    "messages": [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ],
}
```

**`temperature`, `top_p`, `max_tokens`, `max_completion_tokens`,
`reasoning_effort`, `tools` 중 어느 것도 코드에 존재하지 않는다** —
`grep`으로 두 파일 전체를 확인했다. 모델명(`self.model`)에 대한 검증, 화이트
리스트, 분기 로직도 전혀 없다 — 문자열 그대로 payload에 꽂아 넣을 뿐이다.

## 2. gpt-5.6-luna 실제 사양 (웹 검색 결과)

- 2026년 6월 26일 프리뷰, 7월 9일 GA. OpenAI의 GPT-5.6 계열(Luna/Terra/Sol)
  중 가장 빠르고 저렴한 티어. `/v1/chat/completions` 엔드포인트를 지원한다.
- Chat Completions에서 `system`/`user` role 메시지를 정상 지원한다
  (`developer` role로 바꿀 필요 없음).
- 구조화 출력(JSON 응답)을 지원한다 — 다만 문서들이 강조하는 것은 최신
  `json_schema` 방식이고, 기존 `{"type": "json_object"}`(단순 JSON 모드)가
  그대로도 동작하는지는 명확히 확인되지 않았다(**추측하지 않음**).
- reasoning 계열 모델 공통 특성: `temperature`/`top_p`는 **지원하지
  않고**, 길이 제한은 `max_tokens`가 아니라 `max_completion_tokens`를
  쓴다. `reasoning_effort`(none/low/medium/high/xhigh/max, 기본값 medium
  추정)라는 별도 파라미터를 받는다.
- 알려진 제약: Chat Completions에서 **`tools`(function calling)와
  `reasoning_effort`를 함께 보내면 400 에러**가 난다 — Responses API로
  옮겨야 하는 경우다.

## 3. 질문별 결론

### 3-1. gpt-5.6-luna를 현재 interview_llm.py에서 사용할 수 있는가?

**예, 구조적으로 사용 가능하다.** 근거:

- 모델명은 문자열로 그대로 전달될 뿐, 코드에 모델명 검증/제한이 없다.
- gpt-5.6-luna는 실제 존재하는 모델이며 `/v1/chat/completions`를 지원한다.
- `system` role을 그대로 지원하므로 role 관련 수정이 필요 없다.
- 코드가 `tools`(function calling)를 전혀 쓰지 않으므로(payload에 `tools`
  키 자체가 없음), gpt-5.6 계열의 "tools + reasoning_effort 동시 사용 시
  400 에러" 이슈에 해당하지 않는다.

### 3-2. max_tokens, temperature 등 요청 파라미터가 호환되는가?

**현재 코드는 이 파라미터들을 애초에 전혀 보내지 않는다** — 그래서
"지원되지 않는 파라미터를 보내서 에러가 나는" 충돌 자체가 구조적으로
발생하지 않는다.

- `temperature`/`top_p`: gpt-5.6-luna(reasoning 계열)는 이 파라미터들을
  지원하지 않지만, 코드가 애초에 보내지 않으므로 문제 없음.
- `max_tokens`: gpt-5.6-luna는 `max_completion_tokens`를 요구하지만,
  코드가 어느 쪽도 보내지 않으므로 충돌 없음(모델의 기본 출력 길이로 동작).
- `reasoning_effort`: 코드가 보내지 않으므로 API 기본값(추정 medium)으로
  동작할 것으로 보인다 — 요청 실패 원인은 아니지만, 필요 이상으로 reasoning
  토큰을 써서 응답이 느려지거나 비용이 늘어날 가능성은 있다(에러는 아님,
  튜닝 여지).

### 3-3. 모델명을 gpt-5.6-luna로 설정했을 때 코드 수정이 필요한가?

**구조적으로는 필요 없다.** 다만 한 가지 확정하지 못한 지점이 있다:

- `response_format: {"type": "json_object"}`가 gpt-5.6-luna에서 그대로
  동작하는지는 외부 문서로 명확히 확인하지 못했다(최신 `json_schema` 방식이
  권장되는 추세라는 정황만 확인됨). **추측해서 "된다/안 된다"라고 단정하지
  않는다** — 실제로 한 번 호출해봐야 확정할 수 있는 부분이다.
- 만약 이 부분이 실제로 문제가 되더라도, 코드는 이미 모든 LLM 실패를
  안전하게 흡수하도록 설계되어 있다:
  - `interview_llm.py`의 `_call()`이 `HTTPError`를 잡아
    `LLMResponseError`로 변환하고,
  - `generate_first_question`/`decide_next_turn`/`translate_titles`
    전부 모든 예외를 잡아 `None`을 반환하며,
  - 호출부(`scripts/run_scout_dashboard.py`)는 `None`을 받으면 조용히
    기존 템플릿 질문/영어 원문 제목으로 fallback한다.
  - 즉 gpt-5.6-luna가 예상과 다르게 응답해도 **Dashboard가 깨지거나
    사용자에게 오류가 노출되지 않는다** — 최악의 경우 "LLM 기능이 그냥
    안 켜진 것처럼" 동작한다.

## 4. 요약

| 확인 항목 | 결과 |
|---|---|
| 모델명 하드코딩/검증 여부 | 없음 — 어떤 문자열이든 그대로 전달됨 |
| temperature/top_p 전송 여부 | 전송 안 함 → 충돌 없음 |
| max_tokens/max_completion_tokens 전송 여부 | 둘 다 전송 안 함 → 충돌 없음 |
| system role 지원 여부 | gpt-5.6-luna가 지원함 → 코드 그대로 동작 |
| tools(function calling) 사용 여부 | 코드가 아예 안 씀 → gpt-5.6 계열의 tools 관련 400 이슈 무관 |
| response_format:json_object 호환 여부 | **확정 불가**(실제 호출 전까지 알 수 없음) — 실패해도 fallback으로 안전하게 처리됨 |
| 코드 수정 필요 여부 | 구조적으로 불필요. 실제 호출 후 json_object 응답 문제가 확인되면 그때 `json_schema`로 전환 검토 |

## 하지 않은 것

- 코드 수정 없음
- `TAK_MEDIA_LLM_API_KEY`로 실제 API 호출 없음(웹 검색만 수행)
