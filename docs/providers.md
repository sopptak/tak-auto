# 외부 AI Provider 계층

콘텐츠 파이프라인에 외부 서비스 코드를 직접 넣지 않고, 교체 가능한 Provider Adapter를 통해 호출한다.
위치: `content_engine/providers/` (저장소가 표준 라이브러리 위주이므로 `urllib`만 사용, 새 dependency 없음).
`tak_workforce`는 P2-02 브랜치에만 있어 이 브랜치에서는 의존하지 않는다.

## 구조

| 파일 | 역할 |
|---|---|
| `base.py` | 표준 결과 모델(`ResearchResult`, `VoiceResult`, `MediaGenerationResult`, `VideoResult`, `ClipResult`), 예외, 인터페이스(ABC) |
| `perplexity.py` | 실제 구현: Perplexity Search API (`POST https://api.perplexity.ai/search`) |
| `skeletons.py` | ElevenLabs/Recraft/Runway/OpusClip 골격(credential 검증 + `ProviderNotImplementedError`) |
| `mock.py` | 결정적 Mock(네트워크 없음) |
| `registry.py` | `get_*_provider()` 선택 |
| `../research_bridge.py` | `ResearchResult` → pending KNOWLEDGE 후보, accepted 후속 후보 → 생성 요청 |

결과 모델은 `provider, request_id, status, created_at, output_url, local_path, metadata, error`를 공통으로 갖는다.
벤더 raw 응답은 모델에 담지 않는다. 벤더 URL은 임시일 수 있으므로 보존이 필요하면 다운로드 후 `local_path`에 둔다(실제 다운로드는 각 어댑터 구현 시 추가).

## 지원 상태

| Provider | 종류 | 상태 | 환경변수 |
|---|---|---|---|
| Perplexity | research | **구현됨**(Search API, 단위 테스트는 가짜 transport) | `PERPLEXITY_API_KEY` |
| ElevenLabs | voice | 골격(호출 시 `ProviderNotImplementedError`) | `ELEVENLABS_API_KEY` |
| Recraft | image | 골격 | `RECRAFT_API_KEY` |
| Runway | video | 골격 | `RUNWAYML_API_SECRET` |
| OpusClip | clip | 골격 | `OPUSCLIP_API_KEY` |
| Mock | 전부 | 구현됨 | 없음 |

Perplexity는 실제 API로 호출해 본 적이 없다(credential 없음). 요청/응답 형식은 공식 문서(Search API)를 따랐다.

## Provider 선택

우선순위: 함수 인자 > `TAK_<KIND>_PROVIDER` 환경변수 > 기본값.
`TAK_RESEARCH_PROVIDER`, `TAK_VOICE_PROVIDER`, `TAK_IMAGE_PROVIDER`, `TAK_VIDEO_PROVIDER`, `TAK_CLIP_PROVIDER`.
research 기본값은 `PERPLEXITY_API_KEY`가 있으면 perplexity, 없으면 mock. 나머지 기본값은 mock.
이름을 명시했는데 credential이 없으면 mock으로 조용히 대체하지 않고 `ProviderNotConfiguredError`를 낸다.

## 사용법

```bash
# Mock (credential 불필요)
python scripts/research_knowledge.py "대출 금리 비교"

# Perplexity (key는 환경변수로만)
export PERPLEXITY_API_KEY=...      # 셸/Codespaces secret/GitHub Actions secret에 설정
python scripts/research_knowledge.py "대출 금리 비교" --recency month --domain bok.or.kr --write
```

`--write`가 있어야만 `data/tak_brain_knowledge.json`에 **pending + verification_required** 후보가 추가된다.
기존 `review_knowledge.py`로 사람이 승인해야만 콘텐츠 파이프라인(`select_approved`)이 사용한다. 자동 승인/발행은 없다.

```python
from content_engine.providers import get_research_provider
result = get_research_provider().research("질의", domains=["example.com"], recency="week", max_results=5)
```

## 파이프라인 연결 지점

```
Perplexity → ResearchResult → research_to_knowledge() → pending KNOWLEDGE → (사람 review) → 기존 콘텐츠 생성
accepted 후속 후보 → accepted_followups_to_requests() → research_query/생성 요청 → (사람 review) → 발행
```

`accepted_followups_to_requests()`는 `accepted` 후보만 `requires_human_review=True` 요청으로 바꾸는 순수 함수이며 아무것도 실행하지 않는다.

## 테스트

```bash
python -m pytest tests/test_providers.py          # 기본: 네트워크 호출 없음
TAK_RUN_INTEGRATION=1 PERPLEXITY_API_KEY=... python -m pytest tests/test_providers.py   # 실제 호출(명시적 opt-in)
```

## 나머지 서비스 연결 방법

1. 해당 서비스의 공식 API 문서로 요청/응답을 확인한다.
2. `skeletons.py`의 클래스(또는 별도 파일)에서 `transport` 주입이 가능한 형태로 HTTP 호출을 구현한다(Perplexity 구현 참고).
3. 결과를 표준 모델로 변환하고, 오류는 `ProviderAuthError/ProviderRequestError/ProviderResponseError`로 변환한다.
4. 임시 URL은 `local_path`로 내려받아 보존한다. 비동기 작업(Runway, OpusClip)은 `status="pending"` + `request_id`로 반환하고 폴링을 분리한다.
5. 가짜 transport 기반 테스트를 `tests/test_providers.py`에 추가한다.

## 보안 원칙

- API key는 환경변수(Codespaces/GitHub Actions secret)에만 둔다. 코드·JSON·YAML·README·로그·예외 메시지에 넣지 않는다(예외에는 변수명만 포함).
- `.env`는 `.gitignore`에 포함되어 있다. secret 파일을 commit하지 않는다.
