# TAK_MEDIA_LLM_API_KEY 발급처 조사 (값 미출력, 실제 API 호출 없음)

## 방법

API 키 값(전체/일부/prefix 문자 포함)을 어떤 형태로도 출력하지 않고, bash의
`case` 패턴 매칭으로 키 형식이 알려진 LLM 제공업체의 표준 키 포맷과 일치하는지
**내부적으로만 비교**한 뒤, 매칭 결과(제공업체 이름)만 보고했다. 매칭에 사용한
실제 문자열(`sk-`, `sk-proj-` 등)은 스크립트 안의 비교 패턴일 뿐, 키 자체에서
추출해 출력한 적이 없다. 실제 API 호출은 하지 않았다.

## 조사 결과

| 확인 항목 | 결과 |
|---|---|
| 존재 여부 | 설정됨 |
| 길이(문자 수) | 164자 |
| 알려진 prefix 패턴 매칭 | **OpenAI project key 스타일(`sk-proj-...`)과 일치** |
| 다른 LLM 제공업체 관련 env var (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `GEMINI_API_KEY`, `GROQ_API_KEY`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `COHERE_API_KEY`, `MISTRAL_API_KEY`, `OPENROUTER_API_KEY`) | 전부 미설정 — 이 Codespace에는 `TAK_MEDIA_LLM_API_KEY` 외에 다른 LLM 제공업체 키가 없음 |
| `.devcontainer/devcontainer.json` 등 설정 파일에 provider 관련 문서화 | 없음(devcontainer.json 자체가 저장소에 없음) |

## 결론

**`TAK_MEDIA_LLM_API_KEY`는 OpenAI 발급 키로 강하게 추정된다.**

근거:
- 키 형식이 OpenAI의 project-scoped key 표준 prefix(`sk-proj-`)와 정확히
  일치한다. 이 prefix는 OpenAI만 사용하는 고유 포맷이라 다른 제공업체(Anthropic
  `sk-ant-`, Google `AIza`, Groq `gsk_`, OpenRouter `sk-or-` 등)와 혼동될
  여지가 없다.
- 길이(164자)도 OpenAI project key의 전형적인 길이대(classic `sk-...` 키의
  ~51자보다 훨씬 긴, project key 특유의 길이)와 일치한다.
- 이 결론은 `docs/` 내 과거 세션들이 실제 값이 없을 때 임시로 선택했던
  기본값(`https://api.openai.com/v1/chat/completions`, `gpt-4o-mini`)과도
  방향이 일치한다 — 다만 이전 조사(5-22)에서 확인했듯 그 값들 자체는 "실제
  등록된 Secret"이라는 근거가 없는 임시 테스트값이었다는 점은 변하지 않는다.
  이번 조사는 그 값들이 **우연히도 맞는 제공업체 계열을 가리키고 있었을
  가능성이 높다**는 정황적 뒷받침을 추가한 것이다.

## 남은 불확실성

- **정확한 모델명(`TAK_MEDIA_LLM_MODEL`)은 키 형식만으로는 알 수 없다.**
  OpenAI 계정에는 여러 모델(gpt-4o, gpt-4o-mini, gpt-4.1 등)이 있고, 어떤
  모델을 쓸지는 프로젝트 결정 사항이지 키에 내장된 정보가 아니다.
- **엔드포인트가 `https://api.openai.com/v1/chat/completions`인지도 100%
  확정할 수는 없다** — OpenAI 키라도 Azure OpenAI 프록시, 사내 게이트웨이,
  OpenRouter 같은 호환 프록시를 거치도록 구성했을 가능성은 남아 있다. 다만
  `AZURE_OPENAI_ENDPOINT`/`OPENROUTER_API_KEY` 등 관련 env var가 전혀 없는
  것으로 보아, 표준 OpenAI 엔드포인트를 직접 쓰고 있을 가능성이 더 높다.

## 하지 않은 것

- API 키 값(전체/부분/prefix 문자) 출력 없음
- 실제 LLM API 호출 없음
- 코드 수정 없음
