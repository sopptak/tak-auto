# TAK AUTO — Dashboard 후보 제목 한국어 표시 (5-21)

## 배경

Phase 2 Dashboard를 실제로 사용해보니 SCOUT 후보 제목이 BBC/Hacker News 원문
영어로 그대로 표시되어 한국어 사용자가 읽기 불편하다는 피드백을 받았다. 목표는
"원문(title)은 데이터에 절대 손대지 않고, Dashboard 화면에만 한국어 표시용
제목을 별도로 보여주는 것"이다.

## 1. 수정 파일

| 파일 | 종류 | 내용 |
|---|---|---|
| `tak_scout/title_translation.py` | 신규 | 한국어 표시 제목 캐시 데이터 계층 (`TitleTranslation`, load/save/upsert, `tak_interview_sessions.json`/`tak_interview_answers.json`과 동일한 atomic write 패턴) |
| `tak_scout/interview_llm.py` | 수정 | `InterviewLLMProvider.translate_titles()` 메서드 추가 (기존 `_call`/`_http_transport`/환경변수 재사용) |
| `scripts/run_scout_dashboard.py` | 수정 | `get_display_titles()` 오케스트레이션 함수 + 목록/turn/review 화면에 한국어 제목 표시 + `DashboardConfig.title_translations_path` + `--title-translations` CLI 인자 |
| `tests/test_interview_llm.py` | 수정 | `TranslateTitlesTests` 13개 추가 |
| `tests/test_scout_dashboard.py` | 수정 | `TitleTranslationTests`(11개) + `TitleTranslationOverHttpTests`(4개) 추가 |
| `tests/test_scout_title_translation.py` | 신규 | 캐시 계층 단위 테스트 13개 |

**건드리지 않은 것**: `tak_scout/models.py`(ScoutCandidate 스키마 무변경),
`tak_scout/collector.py`, `tak_scout/scoring.py`(SCOUT SCORE 계산/정렬 로직
무변경), `tak_scout/knowledge_bridge.py`(KNOWLEDGE의 source title은 원문
그대로), Blog/Threads/YouTube 관련 코드 전부.

## 2. 구현 방식

### 2-1. LLM provider 구조 재사용 여부 확인 (지시 4번)

기존 `InterviewLLMProvider`(인터뷰 질문 생성용)의 `_call()` 메서드가 이미
"system prompt + user message → HTTP POST(OpenAI 호환 Chat Completions) →
JSON 파싱"을 전부 처리하고 있어, 이 메서드를 그대로 재사용해 새 공개 메서드
`translate_titles()`만 추가했다. 새 HTTP transport, 새 환경변수, 새 예외
클래스를 전혀 만들지 않았다 — `TAK_MEDIA_LLM_API_KEY/ENDPOINT/MODEL`을 그대로
쓰고, `content_engine.LLMConfigurationError/LLMResponseError`도 기존과
동일하게 재사용한다. **새로운 외부 API나 별도 번역 서비스는 추가하지
않았다**(지시 5번).

### 2-2. 배치 번역 (지시 8번: 비용/응답속도 억제)

후보마다 개별 LLM 호출을 하지 않고, **캐시에 없는 후보 전체를 한 번의 LLM
호출로 묶어** 번역한다(`translate_titles(titles: tuple[(scout_id, title), ...])`).
TOP 5가 전부 미번역 상태여도 LLM 호출은 딱 1번이다.

- 응답 형식: `{"translations": {"<scout_id>": "<한국어 제목>", ...}}`
- 호출 자체가 실패(네트워크/설정/JSON 파싱 오류)하면 전체를 `None`으로 취급 →
  모든 후보가 원문 fallback.
- 호출은 성공했지만 일부 scout_id만 응답에 없거나 형식이 잘못된 경우, **그
  항목만** 원문 fallback으로 처리한다(부분 실패가 전체를 막지 않음).
- 원문 제목이 이미 한국어면 그대로 반환하도록 system prompt에 명시.

### 2-3. Dashboard 표시 (지시: UI/인터뷰 화면)

`get_display_titles()`가 목록(`/`), 인터뷰 turn(`/candidate/{id}`), review
(`/candidate/{id}/review`) 화면에서 공통으로 쓰인다. 렌더링은:

```html
<div class="title-ko">한국어 제목</div>
<div class="title-en">원문: English original title</div>
```

한국어 제목(`title-ko`, 1.05rem/굵게)을 먼저, 영어 원문(`title-en`, 0.78rem/회색)을
그 아래 작게 표시한다. 번역이 없으면(LLM 미설정/실패) `title-en` 자체를
생략하고 원문만 `title-ko` 자리에 그대로 보여준다(원문 제목 이중 노출 방지).

### 2-4. Fallback (지시 6번)

LLM provider가 없거나(`llm_provider is None`) 호출이 실패하면 `get_display_titles`는
해당 scout_id에 대해 `candidate.title`(원문)을 그대로 반환한다. Dashboard는
이 실패를 절대 사용자에게 오류로 노출하지 않는다(기존 `interview_llm.py`의
"실패는 조용히 fallback" 원칙과 동일).

### 2-5. KNOWLEDGE의 source title (지시 10번)

`tak_scout/knowledge_bridge.py`를 전혀 수정하지 않았으므로
`build_knowledge_from_interview`는 여전히 `candidate.title`(원문)만 사용한다.
한국어 표시 제목은 `title_translation.py`/Dashboard 렌더링에만 존재하고
KNOWLEDGE 생성 경로에는 전혀 섞이지 않는다.

## 3. 캐시 방식 (지시 7번)

`data/tak_scout_title_translations.json`에 `scout_id -> {source_title,
display_title, translated_at}`로 저장한다(`tak_interview_sessions.json`과
동일한 파일 구조·atomic write).

- `scout_id`는 `title+source_url`의 결정적 해시(`compute_scout_id`)이므로,
  원문 제목이 바뀌면 scout_id 자체가 달라진다 — 이 캐시는 "오염된 캐시"를
  걱정할 필요가 없다(같은 scout_id는 항상 같은 원문 제목을 의미).
- 캐시에 있는 후보는 LLM을 다시 호출하지 않는다 — 새로고침해도 반복 번역
  없음(4번 요구사항, 아래 5번에서 실측 확인).
- 실패한(원문 fallback) 항목은 캐시에 저장하지 않는다 — LLM이 나중에
  복구되면 다음 조회 때 다시 시도할 수 있다(기존 `interview_llm.py`의
  "실패를 영구 상태로 남기지 않는다"는 철학과 동일).
- 이 파일은 `.gitignore`의 `data/*.json` 규칙에 그대로 포함되어 추적
  대상이 아니다 — `tak_interview_sessions.json`과 동일하게 "런타임에
  생성되는 캐시"로 취급했다(추가 설정 불필요).

## 4. 테스트 결과

```
$ python3 -m pytest -q
612 passed, 68 subtests passed   (기존 570 + 신규 42개)
```

요구 항목별 커버리지:

| # | 요구 항목 | 테스트 |
|---|---|---|
| 1 | 영어 title → 한국어 display title 표시 | `test_english_title_gets_korean_display_title`, `test_list_html_shows_korean_title_first_and_english_original_small`, `test_candidate_list_page_shows_korean_title`(HTTP) |
| 2 | 원문 title 불변 | `test_source_title_is_never_modified`, `test_source_titles_sent_unmodified_in_request` |
| 3 | LLM 실패 시 영어 원문 fallback | `test_llm_missing_falls_back_to_source_title`, `test_llm_failure_falls_back_to_source_title`, `test_llm_returning_none_falls_back_to_source_title`, `test_llm_unset_shows_original_title_only`(HTTP) |
| 4 | 새로고침 시 반복 호출 없음 | `test_cached_translation_is_not_requested_again`, `test_second_page_load_reuses_cached_translation`(HTTP) |
| 5 | TOP 5 정렬/점수 무영향 | `test_score_and_ranking_unaffected_by_translation` |
| 6 | 전체 테스트 통과 | 612 passed |
| (추가) | 배치 호출(개별 호출 금지) | `test_batch_of_multiple_titles_in_one_call`(HTTP: 1회만) |
| (추가) | 부분 실패 격리 | `test_partial_translation_falls_back_only_for_missing_candidate`, `test_missing_scout_id_in_response_is_simply_absent` |
| (요청한 실제 샘플) | "We simply don't know - JP Morgan..." | `test_success_translates_real_sample_title`(단위), `TitleTranslationOverHttpTests` 전체(HTTP), 5번 실제 E2E |

## 5. 실제 브라우저(HTTP) 확인 결과

`TAK_MEDIA_LLM_ENDPOINT`/`TAK_MEDIA_LLM_MODEL`이 현재 환경에 설정되어 있지
않아(`TAK_MEDIA_LLM_API_KEY`만 있음), 실제 운영 LLM으로 이 자리에서 과금
호출을 하는 대신 **로컬 스텁 OpenAI 호환 서버**를 띄우고
`InterviewLLMProvider._http_transport`(수정하지 않은 실제 production HTTP
코드 경로)가 그 서버를 실제로 호출하도록 해 검증했다(단위 테스트의 Python
레벨 mock과 달리 진짜 HTTP 왕복까지 확인). 운영 데이터는 격리된 복사본만
사용했다.

```
GET /  (실제 오늘자 TOP 5, data/tak_scout_daily.json 복사본)
→ 200, 5개 카드 모두 한국어 제목이 title-ko로, 영어 원문이 title-en으로 표시됨

title-ko: 일본, 물가 상승 억제 위해 금리 31년 만에 최고 수준으로 인상
title-ko: 통제되지 않은 AI, 인간과 경쟁하는 '실리콘 종'으로 이어질 수 있다 - MS 경고
title-ko: 정말 알 수 없다 — JP모건, 이란 전쟁으로 유가 전망에 어려움   ← 요청하신 예시와 일치
title-ko: 경제부 장관, 소셜미디어 설전에서 '악의적 개입' 주장
title-ko: 금리는 동결, 그러나 에너지 가격 고공행진시 인상 시사

GET /candidate/scout-e9b389bf6365 (JP Morgan 후보 인터뷰 화면)
→ <h1>정말 알 수 없다 — JP모건, 이란 전쟁으로 유가 전망에 어려움</h1>
→ <div class="title-en">원문: 'We simply don't know' - JP Morgan ...</div>

새로고침(GET / 재요청) 후 캐시 파일 mtime 불변 → LLM 재호출 없음 확인
```

원문 `data/tak_scout_daily.json`은 이 검증 동안 전혀 수정되지 않았고
(diff 없음 확인), KNOWLEDGE/Threads/YouTube는 전혀 건드리지 않았다.

**중요**: 지금 실제로 켜져 있는 프로덕션 Dashboard(포트 8000)는
`TAK_MEDIA_LLM_ENDPOINT`/`MODEL`이 설정돼 있지 않아 **현재는 영어 원문
fallback으로만 보인다** — 이는 설계된 안전한 동작이며 버그가 아니다. 실제
한국어 번역을 켜려면 이 두 환경변수를 채우기만 하면 되고, 코드 변경은
필요 없다. 새 코드가 반영되도록 Dashboard 프로세스는 재시작해 두었다.

## 6. commit hash

`d35bf79` — `feat: show Korean display titles for SCOUT candidates in Dashboard`
(6개 파일: `tak_scout/interview_llm.py`, `tak_scout/title_translation.py`,
`scripts/run_scout_dashboard.py`, `tests/test_interview_llm.py`,
`tests/test_scout_dashboard.py`, `tests/test_scout_title_translation.py`)

## 7. push 성공 여부

성공. `cf9ff6e..d35bf79 main -> main` (fast-forward, 병합 불필요), local
main == origin/main(`d35bf79`) 확인됨. 기존 미커밋 변경사항(`content_engine/*`,
`.gitignore`의 다른 pending 라인, `data/tak_brain_knowledge.json` 등)은
전부 그대로 보존됨.
