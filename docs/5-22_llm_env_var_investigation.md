# LLM 환경변수(TAK_MEDIA_LLM_*) 설정 조사 (코드 수정 없음)

## 목적

Dashboard의 한국어 제목 번역 기능이 현재 `TAK_MEDIA_LLM_ENDPOINT`/
`TAK_MEDIA_LLM_MODEL` 미설정으로 영어 원문 fallback으로만 동작 중이다. 이번
작업은 실제 API 호출이나 코드 수정 없이, **설정 방법만** 정확히 확인하는
조사다.

## 1. 현재 Codespace 환경변수 상태 (값은 확인하지 않음)

| 환경변수 | 상태 |
|---|---|
| `TAK_MEDIA_LLM_API_KEY` | 설정됨 |
| `TAK_MEDIA_LLM_ENDPOINT` | 미설정 |
| `TAK_MEDIA_LLM_MODEL` | 미설정 |

`env | grep`으로 변수 **이름**만 확인했고, 값은 어디에도 출력하지 않았다.

## 2. 코드가 요구하는 정확한 이름/형식

`content_engine/llm_provider.py:88-96`와 `tak_scout/interview_llm.py:220-228`의
`from_environment()`가 완전히 동일한 이름 3개를 요구한다(대소문자/접두어
변형 없이 `os.environ.get()`으로 직접 읽음):

- `TAK_MEDIA_LLM_API_KEY` — OpenAI 호환 API의 Bearer 토큰
  (`Authorization: Bearer {값}` 헤더로 그대로 전송).
- `TAK_MEDIA_LLM_ENDPOINT` — **경로까지 포함한 전체 URL**. 코드가 이 값을
  그대로 `POST` 대상으로 사용하므로 base URL만 넣으면 안 된다.
- `TAK_MEDIA_LLM_MODEL` — Chat Completions 요청 JSON의 `"model"` 필드에
  그대로 들어가는 모델명 문자열.

세 값 중 하나라도 비면 `LLMConfigurationError`가 발생하고,
`tak_scout/interview_llm.py`는 이를 조용히 흡수해 영어 원문 fallback으로
처리한다(현재 실제 동작).

## 3. 기존 설정 재사용 가능 여부

`.github/workflows/daily-threads-post.yml:100-101, 109-110`에서 이미
`secrets.TAK_MEDIA_LLM_ENDPOINT`, `secrets.TAK_MEDIA_LLM_MODEL`을 참조하고
있다 — 이 저장소의 GitHub Actions Secrets에 이미 실제 운영 값이 등록되어
있을 가능성이 높다(Threads 자동 게시 workflow가 이 값으로 이미 LLM을 호출
중).

`gh secret list`로 실제 등록 여부를 확인하려 했으나 gh CLI 토큰 권한
부족(`403: Resource not accessible by integration`)으로 조회하지 못했다
(이전 workflow_dispatch 시도 때와 동일한 제약 — Codespaces 기본
`GITHUB_TOKEN`에는 `actions` 관련 권한이 없음).

**GitHub Actions Secrets와 Codespaces Secrets는 서로 다른 저장소**이므로,
Actions에 등록되어 있어도 Codespace에 자동으로 들어오지 않는다.

## 4. 결론 (설정 안내만, 실제 설정/호출은 하지 않음)

| 항목 | 내용 |
|---|---|
| 필요한 환경변수 이름 | `TAK_MEDIA_LLM_ENDPOINT`, `TAK_MEDIA_LLM_MODEL` (`API_KEY`는 이미 있어 불필요) |
| `TAK_MEDIA_LLM_ENDPOINT`에 넣을 값 | 사용 중인 OpenAI 호환 Chat Completions API의 전체 URL(예: `https://api.openai.com/v1/chat/completions` — 프로젝트 문서들이 지금까지 일관되게 예시로 사용). `daily-threads-post.yml`에 이미 등록된 값과 **동일하게** 맞추는 것을 권장 |
| `TAK_MEDIA_LLM_MODEL`에 넣을 값 | 그 엔드포인트에서 쓸 모델명(예: `gpt-4o-mini` — 과거 문서 예시). 역시 workflow에 등록된 값과 동일하게 권장 |
| Codespace에서 설정할 위치 | GitHub **Settings → Codespaces → Codespaces secrets**(계정 단위) 또는 저장소 **Settings → Secrets and variables → Codespaces**(저장소 단위). `TAK_MEDIA_LLM_API_KEY`가 이미 이 경로로 주입된 것으로 보임 — 같은 경로에 두 항목 추가 후 Codespace 재시작하면 자동 반영 |

## 5. 이번 조사에서 하지 않은 것

- 코드 수정 없음
- 실제 LLM API 호출 없음
- `TAK_MEDIA_LLM_API_KEY` 값 또는 다른 어떤 시크릿 값도 출력/로그에 남기지 않음
