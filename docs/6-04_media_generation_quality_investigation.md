# TAK AUTO 6-04 — MEDIA 생성 품질 문제 원인 분석

## 1. 발견된 문제

6-03 보고서의 승인을 받아 사용자가 직접 실행한 `python3 scripts/run_media_batch.py --execute --id knowledge-scout-b28b782b2a33`(실제 LLM 호출) 결과를 사람이 검수하던 중 심각한 품질 문제가 발견됐다.

- 대상 KNOWLEDGE: `knowledge-scout-b28b782b2a33`
- source title: *"Anthropic boss Dario Amodei calls for AI development to slow down"*
- KNOWLEDGE의 `domain`: `"금융"`(article_type: `"finance"`)
- 생성된 Blog 원본 제목: **"재무 판단에서 함께 볼 기준"**
- 생성된 Blog 본문에 삽입된 문구: **"이 글의 금융 관련 내용은 원문 작성자의 설명이며, 금융기관의 공식 심사 기준으로 해석하지 않습니다."**
- AI 재작성(LLM) 결과 Blog 제목: **"신기술을 바라보는 나의 기준"**

이 KNOWLEDGE는 AI 개발 속도 완화를 촉구하는 뉴스(금융/대출과 무관)인데도 "재무 판단", "금융기관의 공식 심사 기준" 같은 금융 전용 문구가 자동 삽입됐다.

## 2. 실제 production 9개 생성 결과

`data/tak_media_archive.json`(실제 LLM 호출 결과, 이번 세션에서 절대 삭제/덮어쓰지 않음)에 저장된 9건 전부를 읽기 전용으로 조사했다.

| content_id | platform | generated title(AI 재작성) | source와 관련성 | 금융 템플릿 오염 | 원문 사실 반영 | 새 사실 추가 | validation |
|---|---|---|---|---|---|---|---|
| `content-5971ed5204437cdd` | blog | 신기술을 바라보는 나의 기준 | 있음(핵심 우려·의견 모두 포함) | **있음** — 원본 제목 "재무 판단에서 함께 볼 기준", 본문에 "금융기관의 공식 심사 기준으로 해석하지 않습니다" 삽입(마침표 누락) | 있음 | 없음 | valid |
| `content-e787c9201b94a948` | shorts | 새로운 기술을 마주하는 나의 기준 | 있음 | 없음(제목만 "재무 판단의 출발점"이었으나 재작성으로 사라짐) | 있음 | 없음 | valid |
| `content-3ae2d78568210164` | shorts | 신기술을 마주하는 내 기준 | 있음 | 없음 | 있음 | 없음 | valid |
| `content-cabd37f3a2745724` | shorts | 신기술을 대하는 내 기준 | 있음 | 없음(제목에 금융 문구 없음) | 있음 | **있음 — "기준"이라는 단어가 원문/KNOWLEDGE 어디에도 없이 재작성 제목에 새로 추가됨** | **rejected**(사실 범위 확장) |
| `content-dbf0fb4eb5cfd791` | threads | AI에 대한 우려와 내가 택한 태도 | 있음 | 없음 | 있음 | 없음 | valid |
| `content-81d4e7c5723598f6` | threads | 신기술은 직접 부딪혀 봐야 한다 | 있음 | 없음 | 있음 | 없음 | valid |
| `content-4015df0692e0bcc4` | threads | AI에 대한 우려, 직접 마주해 보기 | 있음 | 없음 | 있음 | 없음 | valid |
| `content-5a6b175ac6023db1` | threads | AI를 두려워하기 전에 | 있음 | 원본 자체엔 없었지만 **재작성 과정에서 "금융기관의 공식 기준을 설명하는 글이 아니라"는 문구를 LLM이 스스로 추가** | 있음 | **있음 — "기관"이라는 신규 위험 단어 추가** | **rejected**(금융 경계 오인 표현 + 사실 범위 확장) |
| `content-cbcf705b6056c9fc` | threads | 신기술은 직접 부딪혀 봐야 한다 | 있음 | 없음 | 있음 | 없음 | valid |

**공통 관찰**: 9건 모두 원문 사실(AI 모델의 잠재적 위험에 대한 우려, "신기술은 두려워 말고 부딪혀서 느껴봐야 한다"는 사용자 의견)을 실제로 담고 있다 — 완전히 날조된 사실은 없다. 문제는 두 층위다:

1. **명백한 금융 템플릿 오염(Blog 1건)** — `_criterion_blog()`가 `article_type == "finance"`일 때만 삽입하는 제목/캡션이, 금융과 무관한 이 KNOWLEDGE에도 그대로 적용됨.
2. **2건 rejected 중 1건만 금융 오염과 직접 관련**(`content-5a6b175ac6023db1` — 금융 경계 검증기가 트리거됨). 나머지 1건(`content-cabd37f3a2745724`)은 금융과 무관한, `_FACT_RISK_TERMS`의 일반적인 "새 위험 단어 추가" 검증(`기준`이라는 단어가 새로 등장)으로 인한 거부다 — **이건 이번 원인 분석의 대상(금융 템플릿 오염)과 별개의, 기존에도 있었을 정상적인 검증 동작**이다. 정확성을 위해 명시한다: 이번 수정이 이 rejected 건을 valid로 바꾸지는 않는다(6-04 지시 "성공하지 않은 것을 성공했다고 기록하지 않는다"를 따름).

## 3. KNOWLEDGE 원문 분석

`data/tak_brain_knowledge.json`에서 `knowledge-scout-b28b782b2a33`를 읽기 전용으로 확인:

```
id: knowledge-scout-b28b782b2a33
source_raw_id: scout-0db222f63dd1
source_url: https://www.bbc.co.uk/news/articles/c14dpgm0rg4o?...
title: Anthropic boss Dario Amodei calls for AI development to slow down
article_type: finance       <- 문제의 근원
domain: 금융
category: 금융
knowledge_type: 의견
lesson: "The call comes amid growing concerns that AI models may become able to inflict serious damage worldwide."
reusable_principle: "신기술은 두려워 말고 부딪혀서 느껴봐야 한다."
evidence:
  - SOURCE FACT: The call comes amid growing concerns...
  - SOURCE URL: https://www.bbc.co.uk/news/articles/c14dpgm0rg4o...
  - USER ORIGINAL THOUGHT: 신기술은 두려워 말고 부딪혀서 느껴봐야 한다.
inference_method: rule_based_template
```

**질문 I(코드 근거)에 대한 답**: generator에 실제로 전달되는 값은 `title`, `article_type="finance"`, `knowledge_type="의견"`, `evidence`(evidence_units로 분해됨), `lesson`, `reusable_principle`이다(`content_engine/generator.py::build_content_brief()`). 이 중 `article_type="finance"`가 이번 문제의 직접 트리거다 — `lesson`/`reusable_principle`/`evidence`는 실제로 AI 안전성 관련 내용을 정확히 담고 있었고 generator가 그것들을 올바르게 사용했다(2장 표에서 확인).

## 4. Generator 분석

`content_engine/generator.py::_profile()`:

```python
def _profile(brief: ContentBrief) -> str:
    if brief.article_type == "finance":
        return "finance"
    if brief.article_type == "book_philosophy":
        return "book"
    if brief.knowledge_type == "경험" or brief.article_type in {"experience", "ai_business"}:
        return "experience"
    return "criterion"
```

`article_type == "finance"`만으로 `"finance"` 프로파일을 결정한다 — 다른 필드(도메인, 실제 본문 내용)는 전혀 고려하지 않는다. 이 프로파일은:

- `_criterion_blog(brief, "finance")`: 제목을 `"재무 판단에서 함께 볼 기준"`으로 고정하고, `caution = "이 글의 금융 관련 내용은 원문 작성자의 설명이며, 금융기관의 공식 심사 기준으로 해석하지 않습니다."`를 본문 마지막에 무조건 추가한다(L182-187).
- `_criterion_content(brief, "finance")`: Shorts 첫 제목을 `"재무 판단의 출발점"`으로 고정한다(L304).

**질문 A(정답)**: 그렇다 — `domain="finance"` 때문이 아니라 정확히 `article_type == "finance"`이기 때문에 이 템플릿이 선택된다(`domain`은 `_profile()`에서 아예 참조되지 않는다).
**질문 C**: 아니다 — `article_type=None`이었다면 `_profile()`은 (`knowledge_type=="경험"`이 아니므로) `"criterion"`(일반)으로 떨어졌을 것이다. `article_type=None` 자체가 문제가 아니라, `article_type="finance"`가 잘못 채워진 것이 문제다.
**질문 D**: 그렇다 — `_criterion_blog`/`_criterion_content`가 `article_type=="finance"`인 모든 KNOWLEDGE에 무조건 이 문구를 삽입한다. 이 로직 자체는 "의도된 안전장치"이지 버그가 아니다(6장에서 상세) — 문제는 이 로직에 **잘못된 입력**(`article_type="finance"`)이 들어간 것이다.

## 5. Rewrite 분석

`content_engine/rewrite.py::RewriteValidator._finance_errors()`(L231-244):

```python
@staticmethod
def _finance_errors(request: RewriteRequest, rewritten_draft: ContentDraft) -> tuple[str, ...]:
    if request.article_type != "finance":
        return ()
    ...
```

이 함수는 `article_type == "finance"`일 때만 활성화되는 안전 검증이다:
1. 원본 draft에 "공식 기준 비해석 경계"(caution) 문장이 있었는데 재작성 결과에서 사라지면 오류.
2. 재작성 결과에 "공식 심사 기준"/"공식 기준"/"심사 기준" 문구가 경계 문장 없이 새로 등장하면 오류.

`content-5a6b175ac6023db1`(Threads, rejected)의 재작성 결과에 LLM이 스스로 "금융기관의 공식 기준을 설명하는 글이 아니라"는 문구를 추가했는데, 이것이 `official_claim` 패턴("공식 기준"을 포함하면서 경계 문장은 아님)에 걸려 거부됐다 - **LLM이 오히려 "이건 금융기관 기준이 아니다"라고 스스로 해명하려다 검증에 걸린 것**이다. 이는 `article_type="finance"`가 잘못 붙어 LLM 프롬프트(6장)에도 "금융 콘텐츠"라는 맥락이 전달됐음을 보여주는 방증이다.

**질문 E**: 아니다 — Rewrite prompt/검증기가 KNOWLEDGE 내용을 무시하지 않는다. 오히려 `article_type="finance"`라는 (잘못된) 신호에 충실하게 반응한 것이다 - 검증기 자체의 로직은 정상 작동했다.

## 6. LLM prompt 분석

`content_engine/llm_provider.py::OpenAICompatibleRewriteProvider._user_prompt()`(L130-169):

```python
"prohibited_changes": (
    "...금융기관 공식 기준으로의 확대, ..."
),
"validation_requirements": (
    "...금융 초안의 공식 기준 비해석 문구는 삭제하거나 약화하지 않는다"
),
...
if request.article_type == "finance":
    boundary_sentence = find_finance_boundary_sentence(request.draft.body)
    if boundary_sentence:
        payload["finance_boundary_sentence_required_verbatim"] = boundary_sentence
```

`article_type == "finance"`일 때만(그리고 원본 draft.body에 실제 경계 문장이 있을 때만) 이 필드가 프롬프트에 추가된다 - 이 KNOWLEDGE의 경우 `_criterion_blog`가 만든 원본 Blog draft에 이미 경계 문장이 들어가 있었으므로(4장), 이 필드가 프롬프트에 포함되어 LLM에게 "이 경계 문장을 그대로 보존하라"고 지시했다. **LLM은 그 지시를 정확히 따랐다**(재작성된 Blog 본문에도 경계 문장이 그대로 남아 있다, 단 마침표가 하나 누락된 것은 LLM의 사소한 재현 오차로 보인다 - 별도 이슈로 8장/15장에 기록).

**질문 F/G**: 아니다 - 이전 작업의 금융 문구나 예시가 프롬프트에 하드코딩되어 있지 않다. 입력 JSON도 정상적으로 구성되어 있다(`article_type`, `evidence`, `original_draft` 등 정확히 이 KNOWLEDGE의 실제 값이 전달됨) - 유일하게 "오염된" 입력값은 `article_type="finance"` 그 자체다.

**질문 H**: 부분적으로 그렇다 - "finance용 규칙"(caution 문구 삽입, LLM 경계 보존 지시, `_finance_errors` 검증)이 "다른 domain"(이 경우 AI 뉴스)에 적용된 것은 맞지만, 이는 규칙이 "다른 domain에도 적용되도록 설계"된 게 아니라 **`article_type` 값 자체가 domain과 무관하게 틀렸기 때문**이다(7장에서 정확한 원인 확정).

## 7. 정확한 원인

**직접 원인은 `tak_scout/knowledge_bridge.py::build_knowledge_from_interview()`의 다음 두 줄이다:**

```python
category = _map_category(candidate.category)
article_type = "finance" if category in _FINANCE_CATEGORIES else None
```

`candidate.category`는 SCOUT 후보가 어느 RSS 소스에서 왔는지에 따른 **소스 단위의 블랭킷 카테고리**다(`data/scout_sources.json`: `{"name": "BBC Business", "category": "finance"}`) - 이 후보 기사 한 건의 실제 내용을 분석한 결과가 아니다. BBC Business RSS는 AI 산업 뉴스를 포함한 온갖 비즈니스 뉴스를 다루는데, 이 매핑은 "BBC Business에서 왔다"는 사실만으로 무조건 `article_type="finance"`를 부여한다. 그 결과 이 `article_type` 값이 `content_engine/generator.py::_profile()`(4장)로 흘러 들어가 `"finance"` 템플릿(재무 판단 제목 + 공식 심사 기준 비해석 문구)을 선택하게 만들고, `content_engine/rewrite.py::_finance_errors()`(5장)와 `content_engine/llm_provider.py`의 프롬프트(6장)까지 "이건 금융 콘텐츠"라는 잘못된 전제로 연쇄 작동시킨다.

대조군으로, 진짜 금융 KNOWLEDGE(`knowledge-e1cc05264953`, "은행에서 대출받을 때 재무제표에서 가장 먼저 보는 것은?")는 이 SCOUT 경로가 아니라 **블로그 RAW 임포트 경로**(`tak_brain/article_types.py::ArticleTypeClassifier`)를 거쳤다 - 이 분류기는 실제 제목/본문 텍스트에서 "대출", "재무제표", "은행" 같은 한국어 키워드를 직접 찾아 분류하므로 내용 기반으로 정확하다. **SCOUT 경로에는 이런 내용 기반 분류기가 전혀 적용되지 않고, 소스의 블랭킷 카테고리만 그대로 article_type으로 승격된다** - 이것이 이번 문제가 오직 SCOUT 유래 KNOWLEDGE에서만 발생하고 블로그 RAW 유래 KNOWLEDGE에서는 발생하지 않는 이유다.

## 8. 코드 수정

**수정 파일: `tak_scout/knowledge_bridge.py`**(작업 시작 시점 clean/커밋된 파일)

```python
category = _map_category(candidate.category)
article_type = None  # (기존: "finance" if category in _FINANCE_CATEGORIES else None)
```

`_FINANCE_CATEGORIES` 상수(이제 미사용)도 제거했다. `category`/`domain` 필드는 **그대로 유지**한다(변경 없음) - `content_engine/blog_publish_pack.py::is_review_required()`가 `article_type`과 무관하게 `category`/`domain`만으로도 "금융/대출/경매/부동산 → 사람 확인 필요" 안전장치를 이미 독립적으로 보장하므로(코드 확인, 8장), 이 변경이 기존 안전장치를 약화시키지 않는다.

**수정 방식에 대한 근거(하드코딩 금지 원칙 준수)**: `if title contains "Anthropic"` 같은 개별 사례 하드코딩을 하지 않았다. 대신 "SCOUT 경로는 내용 기반 분류 신호가 전혀 없다"는 **구조적 사실**에 근거해, 신뢰할 수 없는 신호(소스의 블랭킷 카테고리)로 `article_type`을 단정하지 않도록 일반화했다 - 이 수정은 BBC Business든 다른 어떤 소스든, Anthropic 기사든 다른 어떤 주제든 동일하게 적용된다.

**검토했지만 채택하지 않은 대안**:
- `tak_brain.article_types.ArticleTypeClassifier`를 SCOUT 후보의 title/summary에 적용하는 방안: 이 분류기의 키워드가 한국어 전용이라(`_RULES["finance"] = ("대출", "재무제표", "은행", ...)`), 영문 RSS(BBC/Hacker News) 제목에는 거의 매칭되지 않아 사실상 이번 수정과 동일한 결과(`article_type` 거의 항상 None)를 내면서 더 복잡한 의존성만 추가한다 - 채택하지 않았다.
- `content_engine/generator.py`의 `_profile()`/`_criterion_blog()`를 수정하는 방안: 이 함수들의 finance 전용 로직 자체는 (진짜 금융 KNOWLEDGE에 대해서는) 올바르게 설계된 안전장치이므로 건드리지 않았다 - 문제는 여기가 아니라 입력값(`article_type`)의 신뢰도였다.

## 9. 테스트

**수정한 기존 테스트**: `tests/test_scout_knowledge_bridge.py::test_finance_category_maps_to_finance_article_type` → `test_finance_category_maps_to_domain_but_not_article_type`로 이름/내용 변경. 기존 테스트는 버그 자체를 "기대 동작"으로 고정하고 있었다(`category="finance"` -> `article_type == "finance"` 단정) - 수정된 테스트는 `article_type is None`이면서 `domain`/`category`는 여전히 `"금융"`임을 확인한다.

**신규 회귀 테스트**(`tests/test_scout_pipeline_e2e.py`, 작업 시작 시점 clean/커밋된 파일):

1. `test_finance_tagged_source_with_ai_content_does_not_get_finance_template` — 실제 버그를 그대로 재현하는 fixture(BBC Business/category="finance"/AI 뉴스 제목)로 `knowledge_bridge` → `generator` 전체를 통과시켜, 생성된 Blog/Shorts/Threads 9개 어디에도 `"재무 판단"`/`"금융기관"`/`"심사 기준"` 문구가 없음을 확인한다(2번 요구사항: AI/news KNOWLEDGE → 금융 템플릿 안 들어감).
2. `test_finance_tagged_source_ai_content_keeps_core_facts` — 원문 핵심 사실("AI models may become able to inflict serious damage worldwide")과 사용자 의견("신기술은 두려워 말고...")이 Blog Draft에 그대로 유지되는지 확인(5번 요구사항).
3. `test_workplace_tagged_source_does_not_get_finance_template` — workplace 카테고리도 finance 템플릿과 무관함을 확인(3번 요구사항, 구조적으로 원래도 영향이 없었지만 명시적으로 고정).

**부가 발견 및 수정(계획에 없던 것, 정직하게 기록)**: 전체 pytest를 처음 돌렸을 때 `tests/test_media_archive.py::MediaArchiveToDashboardIntegrationTests::test_real_approved_knowledge_generates_drafts_the_dashboard_can_render`(6-03에서 추가한 테스트)가 실패했다 - 원인은 이번 세션의 코드 수정과 **무관**했다: 이 테스트는 "production `data/tak_media_archive.json`은 존재하지 않는다"를 전제로 `assertFalse(production_archive.exists())`를 검증하고 있었는데, 6-03 종료 이후 실제로 사람이 `--execute`를 실행해(이 대화의 앞부분) production archive가 실제로 생겼기 때문에 그 전제가 깨졌다. 코드 버그가 아니라 테스트의 낡은 가정이 원인이었으므로, "production archive가 없어야 한다"가 아니라 "이 테스트가 production archive를 새로 만들거나 바꾸지 않는다"(실행 전/후 바이트 비교)로 검증 방식을 수정했다 - `tests/test_media_archive.py` 파일 자체 수정이라 12장 변경 파일 목록에 포함했다.

**기존 테스트로 이미 충족되는 요구사항** (새로 만들지 않고 재사용, 11장 지시):

- 1번(finance KNOWLEDGE → 금융 콘텐츠 생성 가능): `tests/test_article_types.py::test_finance_output_does_not_claim_official_bank_criteria` 등이 블로그 RAW 임포트 경로의 진짜 finance KNOWLEDGE에 대해 이미 검증하고 있다 - 이 경로는 이번 수정의 영향을 받지 않는다(6-04 조사로 재확인만 함).
- 4번(source title/domain/article_type 전달 검증): `tests/test_scout_knowledge_bridge.py`의 기존 테스트들이 이미 검증.
- 6번(기존 valid/rejected validation 유지): `tests/test_article_types.py`, `tests/test_media_archive.py`의 기존 테스트로 이미 커버.
- 7번(기존 MEDIA archive 구조 유지): 이번 세션에서 `content_engine/media_archive.py`를 전혀 수정하지 않았다 - 구조 변경 없음.

전체 pytest(작업 종료 직전):

```
812 passed, 68 subtests passed in 129.16s (0:02:09)
```

**0 failed.** (참고: 이번 세션 시작 시점 baseline은 6-03 종료 시점인 809 passed였다 - 3건 추가: 신규 3개(`ScoutSourcedFinanceTemplateLeakageTests`) + 수정 2개(`test_scout_knowledge_bridge.py`/`test_media_archive.py`, 순증감 없이 내용만 교체) = 정확히 +3.)

## 10. 기존 production archive 보존 여부

**`data/tak_media_archive.json`의 기존 9개 레코드는 이번 세션에서 단 1바이트도 수정하지 않았다.** `git status --short data/tak_media_archive.json`/`git diff`로 확인 가능(작업 종료 시 재확인). 이 9개는 실제 LLM 호출 결과이자 이번 품질 문제를 재현할 수 있는 검증 자료로 그대로 보존했다(4장 지시).

**중요: 이번 코드 수정은 이미 저장된 `knowledge-scout-b28b782b2a33` KNOWLEDGE 레코드의 `article_type` 값(여전히 `"finance"`)이나, 이미 생성된 9개 Draft를 소급 수정하지 않는다.** `data/tak_brain_knowledge.json`의 이 레코드도 이번 세션에서 전혀 수정하지 않았다(자동 migration 금지 지시를 그대로 지켰다). 즉:

- 오늘 이후 **새로** SCOUT → INTERVIEW로 KNOWLEDGE를 만들면(`append_scout_knowledge`/`build_knowledge_from_interview`가 다시 호출되면) `article_type`이 올바르게 `None`으로 생성된다.
- 이미 만들어진 `knowledge-scout-b28b782b2a33`(그리고 그 자매 레코드 `knowledge-scout-6d1d0e2fa762`)는 여전히 `article_type: "finance"`가 저장된 채로 남아 있다 - 이 KNOWLEDGE로 다시 `--execute`를 실행하면 **오늘 수정 전과 동일하게 금융 템플릿이 다시 생성된다.** 이 두 기존 레코드를 고치려면 사람이 KNOWLEDGE 데이터를 직접 수정하기로 결정해야 한다(코드가 자동으로 고치지 않는다 - 15장/16장에서 다시 언급).

## 11. 실제 LLM 호출 여부

**이번 조사/수정 세션에서는 실제 LLM을 호출하지 않았다.** 9장의 모든 신규/수정 테스트는 `generate_content_bundle()`(LLM 없이 결정적으로 Draft를 만드는 규칙 기반 함수)까지만 실행한다 - `content_engine.pipeline.run_media_batch()`(재작성 단계, LLM 호출 지점)는 이번 세션의 신규 테스트에서 호출하지 않았다. 기존 회귀 테스트(`tests/test_scout_pipeline_e2e.py`의 원래 테스트, `tests/test_media_archive.py` 등)가 `run_media_batch()`를 호출하는 부분은 전부 기존과 동일하게 `MockRewriteProvider`만 사용한다(수정하지 않음). 실제 LLM 재호출이 필요한 상황은 발생하지 않았다 - 코드 분석(4~7장)과 mock 기반 재현(9장)만으로 원인 확정과 수정 검증이 모두 가능했다.

## 12. 변경 파일

**기존 파일 수정(작업 시작 시점에 이미 git에 커밋된 clean 파일):**

- `tak_scout/knowledge_bridge.py` — `article_type` 추론 로직 제거(항상 `None`), `_FINANCE_CATEGORIES` 상수 제거.
- `tests/test_scout_knowledge_bridge.py` — 버그를 기대 동작으로 고정하던 기존 테스트 1개를 수정된 동작에 맞게 재작성.
- `tests/test_scout_pipeline_e2e.py` — 신규 회귀 테스트 3개 추가(`ScoutSourcedFinanceTemplateLeakageTests`).
- `tests/test_media_archive.py` — production archive 존재를 전제로 한 낡은 assertion을 스냅샷 비교 방식으로 수정(9장 "부가 발견" 참고, 이번 코드 수정과는 무관한 별개 수정).

**신규 파일:**

- `docs/6-04_media_generation_quality_investigation.md`(이 파일)

**변경하지 않은 파일**(명시적으로 건드리지 않기로 판단): `content_engine/generator.py`, `content_engine/rewrite.py`, `content_engine/llm_provider.py`, `content_engine/pipeline.py`, `scripts/run_media_batch.py`, `data/tak_media_archive.json`, `data/tak_brain_knowledge.json`.

## 13. Commit

`git status --short`로 staging 대상을 먼저 확인한 뒤(기존 미커밋 변경은 전부 그대로 있음을 재확인 - `.gitignore`, `content_engine/__init__.py`, `content_engine/generator.py`, `content_engine/llm_provider.py`, `content_engine/rewrite.py`, `data/tak_brain_knowledge.json`, `tests/test_content_engine.py`, `tests/test_media_batch.py` 등), 이번 세션에서 실제로 수정/생성한 파일 5개만 명시적으로 `git add`했다. **`data/tak_media_archive.json`(production, 이번 대화 앞부분에서 사람이 직접 실행한 실제 LLM 결과)은 이번 커밋에 포함하지 않았다** - 아직 사람이 Dashboard에서 검토/승인하지 않은 상태이므로, 이 세션은 코드 수정 + 테스트 + 보고서만 커밋한다:

```
$ git add tak_scout/knowledge_bridge.py tests/test_media_archive.py \
    tests/test_scout_knowledge_bridge.py tests/test_scout_pipeline_e2e.py \
    docs/6-04_media_generation_quality_investigation.md
$ git status --short | grep "^[MA]"
A  docs/6-04_media_generation_quality_investigation.md
M  tak_scout/knowledge_bridge.py
M  tests/test_media_archive.py
M  tests/test_scout_knowledge_bridge.py
M  tests/test_scout_pipeline_e2e.py

$ git commit -m "fix: prevent cross-domain media template leakage" (전체 메시지는 실제 커밋 참고)
[main 31488ee] fix: prevent cross-domain media template leakage
 5 files changed, 375 insertions(+), 11 deletions(-)
 create mode 100644 docs/6-04_media_generation_quality_investigation.md
```

## 14. Push

```
$ git push
To https://github.com/sopptak/tak-auto
   8cb4923..31488ee  main -> main

$ git fetch origin
(변경 없음)

$ git log origin/main..HEAD --oneline
(빈 결과)

$ git status --short | grep "^[MA]"
(빈 결과)
```

`origin/main`이 로컬 HEAD(`31488ee`)와 완전히 일치함을 확인했다. push 성공. 기존 미커밋 변경은 이 시점에도 전부 그대로 남아 있고, `data/tak_media_archive.json`도 여전히 untracked 상태로 사람의 검토를 기다리고 있다.

## 15. 남은 문제

1. **이미 생성된 9개 production Draft(및 `knowledge-scout-b28b782b2a33`/`knowledge-scout-6d1d0e2fa762` 두 KNOWLEDGE 레코드)는 여전히 금융 템플릿이 섞인 상태로 남아 있다.** 사람이 Dashboard `/media`에서 직접 수정(edit)하거나, KNOWLEDGE의 `article_type`을 수동으로 고친 뒤 재생성할지 결정해야 한다 - 이번 수정은 자동으로 소급 적용되지 않는다(10장).
2. Blog 본문의 caution 문구 끝에 마침표가 누락된 것을 발견했다(`"...해석하지 않습니다"` vs 원본 `"...해석하지 않습니다."`) - LLM 재작성 과정에서 발생한 사소한 재현 오차로 보이나, 이번 조사 범위(금융 템플릿 cross-domain 오염) 밖이라 별도로 수정하지 않았다.
3. `content-cabd37f3a2745724`(Shorts, rejected)는 이번 수정과 무관한 별개 원인(`_FACT_RISK_TERMS`의 "기준" 단어 신규 추가 감지)으로 거부됐다 - 이것이 실제 버그인지 의도된 보수적 검증인지는 이번 조사 범위 밖이다.
4. SCOUT 경로에는 여전히 영문 기사에 대한 신뢰할 수 있는 content-based article_type 분류기가 없다(항상 `None`) - 향후 진짜 금융/전문 분야 SCOUT 기사가 늘어나면 `article_type` 기반 세분화 템플릿(예: finance 안전 문구)이 SCOUT 경로에서는 전혀 적용되지 않는다는 한계가 있다. 이번 수정은 "틀린 걸 자신 있게 적용하는 것"보다 "모르면 일반 템플릿을 쓰는 것"을 택한 보수적 선택이다.

## 16. 다음 작업 제안

1. `knowledge-scout-b28b782b2a33`/`knowledge-scout-6d1d0e2fa762` 두 KNOWLEDGE의 `article_type`을 사람이 직접 `null`로 수정할지 결정 - 그 후 Dashboard에서 해당 9개(+ 자매 KNOWLEDGE의 9개) Draft를 다시 검토하거나, `--execute --id`로 재생성(추가 LLM 호출 필요, 사람 승인 필요)할지 판단.
2. 향후 SCOUT 소스가 늘어나면 영문 콘텐츠에도 적용 가능한 content-based 분류(키워드 사전 확장 또는 경량 규칙)를 SCOUT 경로에 추가할지 검토 - 이번에는 "안전한 기본값(None)"만 확보했고 실제 분류 기능 추가는 범위 밖으로 남겼다.
3. Blog caution 문구의 마침표 누락(15장 2번)을 별도 이슈로 조사할지 결정.
4. 이번 수정 이후 실제로 새 SCOUT 후보 1건을 인터뷰까지 진행해 KNOWLEDGE를 만들어보고, `article_type=None`이 실제 운영 흐름에서도 기대대로 나오는지 실사용으로 재확인(이번 세션은 코드/테스트 검증까지만 함).
