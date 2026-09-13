# TAK AUTO 5-3-2: 품질/출처/검증 구조 설계

이 문서는 설계 문서다. **이번 단계에서 코드는 수정하지 않았다.** 모든 분석은 실제 저장소
코드(`content_engine/*.py`, `tak_brain/*.py`, `tests/*.py`)와 `docs/5-3_real_llm_test.md`의
실제 LLM 실행 로그를 근거로 작성했으며, 추측이 필요한 부분은 "추측"이라고 명시했다.

---

## 0. 문서 상 부정확한 표기 정정

작업 지시문은 `content_engine/rewrite_validator.py`를 분석 대상으로 지목했지만, 이 파일은
저장소에 **존재하지 않는다**. 실제로 `RewriteValidator` 클래스는 `content_engine/rewrite.py`
안에 `RewriteRequest`, `RewriteResult`, `RewriteProvider`, `MockRewriteProvider`,
`RewriteService`와 함께 정의되어 있다(`content_engine/rewrite.py:90-219`). 이 문서의 이후
모든 절은 이 실제 위치를 기준으로 서술한다.

---

## 1. 현재 구현 정확히 분석

### 1-1) LLM이 생성한 제목/본문을 어떻게 검증하는가?

`RewriteService.rewrite()` (`content_engine/rewrite.py:228-247`)가 다음을 순서대로 수행한다.

1. `knowledge.knowledge_review_status != "approved"`면 즉시 `ValueError` (승인 안 된 KNOWLEDGE는
   애초에 재작성 대상이 될 수 없음).
2. `RewriteRequest`(knowledge, draft, source_url, evidence, article_type, knowledge_type)를 구성.
3. `provider.rewrite(request)` 호출 — 실제로는 `OpenAICompatibleRewriteProvider.rewrite()`
   (`content_engine/llm_provider.py:99-116`)가 OpenAI 호환 Chat Completions API를 1회 호출하고,
   응답 JSON에서 `title`/`body`만 꺼내 `dataclasses.replace(original, title=title, body=body)`로
   원본 draft를 복제한다. 이때 `source_url`, `evidence`, `evidence_unit_ids`는 **LLM 응답과
   무관하게 원본 draft 값이 그대로 유지된다** (LLM이 이 필드를 바꿀 방법 자체가 없음 — LLM은
   title/body만 반환하고 나머지는 코드가 강제로 원본을 복사).
4. `RewriteValidator.validate(request, rewritten_draft)`가 5개 검사군을 순서대로 실행하고
   에러가 하나라도 있으면 `status="invalid"` → `RewriteService`가 `rewrite_status="rejected"`로
   변환.

검증기가 실제로 확인하는 것은 **"LLM이 반환한 title/body 문자열이 검증 규칙을 통과하는가"**뿐이다.
LLM이 무엇을 "이해"했는지, 의미를 얼마나 보존했는지는 검증하지 않으며, 모두 정규식/집합 연산
기반의 표층 텍스트 검사다.

### 1-2) fact boundary는 어떻게 검증하는가?

`RewriteValidator._fact_scope_errors()` (`rewrite.py:148-179`)가 두 가지를 본다.

- **새 개체명(entity) 탐지**: `_ENTITY_PATTERN`(`은행|증권|보험|카드|법률|법|규정|령|고시|님|씨|앱|
  서비스|상품|프로젝트`로 끝나는 2자 이상 한글/영문 토큰)으로 재작성 텍스트에서 후보를 뽑고,
  `source_text`(원본 draft title/body + KNOWLEDGE의 title/knowledge_type/experience/problem/
  action/result/lesson/reusable_principle/derived_insight/judgment_rule + evidence)에 **부분
  문자열로도 없으면** 에러.
- **위험 용어 확장 탐지**: `_FACT_RISK_TERMS`라는 고정 단어집합(경험, 성과, 수익, 매출, 고객,
  출시, 수상, 계약, 투자, 창업, 근무, 기관, 은행, 상품, 서비스, 프로젝트, 법률, 규정, 조례,
  시행령, 법적, 기준)이 재작성 텍스트에 등장했는데 `source_text`에는 없으면 에러. 단, finance
  article에서는 면책 문구 패턴(`_FINANCE_BOUNDARY_PATTERN`)에 매칭된 문장은 이 검사에서 제외.

**이것은 "사실관계"를 이해하는 검증이 아니라 "새 단어가 원문 텍스트 어딘가에 부분 문자열로
있는가"만 보는 검증이다.** 예를 들어 원문에 "비공개"라는 단어가 있고 LLM이 "비공식"으로
바꿔도, "비공식"이 `_FACT_RISK_TERMS`에도 `_ENTITY_PATTERN`에도 해당하지 않으므로 **전혀
잡히지 않는다.** 이는 `docs/5-3_real_llm_test.md` [8]-①에서 실제로 관찰된 문제다.

숫자 검증은 별도(`_new_number_errors`, `rewrite.py:136-146`): 재작성 텍스트의 모든 숫자가
`source_text` 또는 `source_url`에 없으면 에러. 이건 완전히 결정적이라 신뢰도가 높다.

### 1-3) 금융/부동산/대출 관련 문장은 어떻게 처리하는가?

두 층에서 처리된다.

- **콘텐츠 엔진 층(생성 시점)**: `generator.py:_criterion_blog()`가 `profile == "finance"`일 때
  고정 문자열 `"이 글의 금융 관련 내용은 원문 작성자의 설명이며, 금융기관의 공식 심사 기준으로
  해석하지 않습니다."`를 본문 마지막 문단에 하드코딩으로 삽입한다(`generator.py:151-155`).
  즉 원본 draft 단계에서는 면책 문구가 **고정 문자열**이라 안전하다.
- **검증 층(재작성 이후)**: `RewriteValidator._finance_errors()` (`rewrite.py:182-195`)가
  `article_type == "finance"`인 경우에만 동작. `_FINANCE_BOUNDARY_PATTERN` 정규식이 원본
  draft body에 매칭되는데 재작성 결과에는 매칭되지 않으면 즉시 거부. 추가로 "공식 심사 기준"/
  "공식 기준"/"심사 기준"이라는 문구가 면책 패턴 없이 단독으로 등장하면 별도로 거부.
- **Blog Publishing Pack 층**: `is_review_required()`(`blog_publish_pack.py:83-97`)가
  `article_type == "finance"` 또는 `category`/`domain`에 `FINANCE_REVIEW_KEYWORDS =
  ("금융", "대출", "경매", "부동산")`가 있으면 `review_required=True`로 표시하고, `knowledge`를
  찾지 못하면 안전 측 기본값(`True`)을 준다. 이 플래그는 Markdown에 체크박스로 표시될 뿐,
  **검증을 대체하거나 콘텐츠를 자동으로 차단하지는 않는다** — 사람이 보게 될 뿐이다.

실제 LLM 테스트에서 이 구조가 정확히 설계대로 동작했다: finance KNOWLEDGE
(`knowledge-e1cc05264953`)의 Blog Draft가 면책 문구를 의역("금융기관의 공식 심사 기준으로
해석하지 않습니다" → "금융기관의 공식 심사 기준을 대표하지는 않습니다")했다는 이유로
`RewriteValidator`에 의해 **rejected**되어 Pack에 노출조차 되지 않았다(`5-3_real_llm_test.md`
[5]).

### 1-4) 원문의 의미가 미묘하게 변하는 문제를 잡을 수 있는가?

**잡을 수 없다.** 현재 검증기에는 의미(semantic) 비교 로직이 전혀 없다. 검증은 다음 4가지
표층 검사로만 구성된다: (a) 타입 일치, (b) source_url/evidence/evidence_unit_ids 불변,
(c) 새 숫자 없음, (d) 새 개체명/위험 용어 없음(부분 문자열 매칭), (e) finance 면책 문구
정규식 매칭, (f) 경험형 콘텐츠의 3인칭 요약체 금지 패턴, (g) Threads 500자 제한. 이 중
어느 것도 "단어를 동의어처럼 보이는 다른 단어로 바꿔서 의미가 달라지는" 경우를 탐지하지
않는다. `docs/5-3_real_llm_test.md` [8]-①에서 실측된 "비공개 테스트" → "비공식 테스트"
사례가 정확히 이 사각지대다.

### 1-5) 키워드/해시태그 품질은 어떻게 만들어지는가?

`suggest_keywords()` (`blog_publish_pack.py:115-131`)는 다음 순서로 후보를 모은다.

1. `knowledge.category` (예: "자기계발") 전체를 그대로 1개 후보로 추가.
2. `knowledge.domain`을 `·`, `,`, `/`로 분리한 조각들을 후보로 추가.
3. **제목 문자열 전체**에 `_KEYWORD_TOKEN_PATTERN = re.compile(r"[A-Za-z가-힣]{2,}")`를 적용해
   찾은 모든 토큰(조사 포함, 순수 정규식 분절)을 후보로 추가.
4. 중복 제거 후 앞에서부터 `limit`(기본 5)개.

즉 형태소 분석이나 불용어 필터가 전혀 없다. "아이디어를 현실로: 앱 제작 여정에서 얻은 교훈"이라는
제목은 정규식으로 어절 단위(공백/구두점 기준)로만 쪼개져 "아이디어를", "현실로", "여정에서" 같은
조사가 붙은 문자열이 그대로 키워드가 된다 — 실측(`5-3_real_llm_test.md` [6])과 정확히 일치한다.
`suggest_hashtags()` (`blog_publish_pack.py:134-135`)는 이 키워드 목록에 `#`만 붙이므로 동일한
문제가 해시태그에도 그대로 전파된다.

### 1-6) LLM 실패 시 현재 retry 구조가 있는가?

**없다.** `grep -rni "retry" content_engine/ scripts/`로 확인한 결과 저장소 전체에 retry 관련
코드가 전혀 없다. `RewriteService.rewrite()`는 provider를 정확히 1회 호출하고, 검증에
실패하면 그 결과를 그대로 `rejected`로 반환한다(`rewrite.py:239-247`). LLM 응답이 계약과
다르면(`content_engine/llm_provider.py`의 `LLMResponseError` — JSON 파싱 실패, choices 누락,
title/body 비어있음 등) 예외가 그대로 전파되고, `pipeline.run_media_batch()`의
`try/except Exception`(`pipeline.py:171-214`)이 이를 잡아 `status="error"`로 기록할 뿐,
**재시도는 하지 않는다.**

### 1-7) rejected가 발생하면 복구할 방법이 있는가?

**없다.** `rejected` 항목은 `MediaBatchReport.rejected_items`에 남아 JSON에 저장되지만
(`pipeline.py:70-72`, `95-98`), `blog_publish_pack.build_blog_publish_pack()`은
`platform == "blog" and status == "valid"`인 항목만 사용한다(`blog_publish_pack.py:189-191`).
rejected된 KNOWLEDGE는 그날의 Pack에서 완전히 사라지고, **같은 KNOWLEDGE를 재작성 재시도하거나
원본 그대로 사용하는 fallback 경로가 없다.** 다음 날 배치를 다시 돌려도 LLM이 다시 같은
표현으로 재작성하면 다시 rejected될 수 있다(결정적 재현 여부는 LLM temperature에 의존 —
코드상 temperature를 지정하지 않으므로 OpenAI 기본값에 맡겨져 있다).

### 1-8) KNOWLEDGE의 evidence/source 정보가 최종 BlogDraft에 얼마나 보존되는가?

`ContentDraft` (`content_engine/models.py:42-48`)는 `source_url`, `evidence: tuple[str, ...]`,
`evidence_unit_ids: tuple[str, ...]`를 필드로 갖는다. `generator.py`가 draft를 만들 때
`_draft_metadata()`(`generator.py:73-74`)로 `source_url`/`evidence`를 그대로 복사하고,
`evidence_unit_ids`는 실제 사용된 `EvidenceUnit.id`(`"{field_name}:{index}"` 형식, 예:
`"lesson:1"`)만 기록한다. `RewriteValidator`는 이 세 필드가 재작성 전후 **완전히 동일**한지
강제한다(`rewrite.py:101-106`) — LLM은 이 필드를 절대 바꿀 수 없다(애초에 `llm_provider.py`가
title/body만 덮어쓰므로 구조적으로 불가능).

다만 `BlogPublishItem`(`blog_publish_pack.py:52-80`)까지 오면 `evidence`와
`evidence_unit_ids`는 **버려진다** — `BlogPublishItem`에는 `source_url`과 `knowledge_id`만
남고 `evidence`/`evidence_unit_ids` 필드 자체가 없다. 즉 "이 문장이 KNOWLEDGE의 어느
필드/몇 번째 문장에서 왔는가"라는 세밀한 추적성은 파이프라인 중간(`MediaBatchItem`,
`MediaBatchReport` JSON)까지는 보존되지만, 사람이 실제로 보는 최종 산출물(Markdown Pack)에는
`knowledge_id`와 `source_url` 두 가지 굵은 단위로만 축약되어 나타난다.

---

## 2. 실제 LLM 테스트 문제 유형별 분류

`docs/5-3_real_llm_test.md`의 실측 결과를 근거로 분류한다. 실측 규모는 KNOWLEDGE 4건,
Draft 36건(Blog 4 + Shorts 12 + Threads 20), Blog만 보면 valid 1 / rejected 3(25% 통과율)이며,
Mock provider 기준(`docs/5-3_result.md`)으로는 동일 입력에서 36/36 valid(100%)였다는 대조가
핵심 근거다.

### A. 사실관계 변형

- **현재 문제**: "비공개 테스트" → "비공식 테스트"로 원본 결과(result) 필드의 사실이 미세하게
  달라졌다(`5-3_real_llm_test.md` [4], [8]-①).
- **왜 발생하는가**: LLM이 "동일 의미의 한국어 재표현"을 허용받은 상태에서(시스템 프롬프트
  `llm_provider.py:120-129`) "비공개"를 유의어로 착각해 "비공식"으로 바꿈. 두 단어는 표면상
  비슷해 보이지만 의미가 다르다.
- **현재 구조의 어느 부분에서 발생하는가**: `_fact_scope_errors()`(`rewrite.py:148-179`)의
  탐지 대상은 "새 개체명 패턴"과 "고정 위험 용어 집합"뿐이며, "비공식"은 둘 중 어디에도
  속하지 않아 검증을 통과한다.
- **개선 방향**: 원본 핵심 서술어/형용사(특히 "비공개", "확정", "무료", "전액", "보장" 등 의미가
  반대로도 갈 수 있는 단어)를 evidence 문장에서 추출해 재작성본에 **그대로 남아있거나, 사전에
  정의된 안전한 동의어 집합 내에서만 치환**되도록 검사(§3-2 참고).
- **자동화 가능 여부**: 부분 자동화 가능(핵심어 사전 기반 매칭). 완전한 의미 비교는
  LLM-judge 방식이 필요해 완전 자동화는 어려움.
- **인간 검토 필요 여부**: 필요. 특히 결과/성과/시점을 나타내는 단어는 최종적으로 사람이
  한 번은 훑어보는 게 안전.

### B. 의미 변형

- **현재 문제**: 위 A와 근본적으로 같은 범주이나 더 넓게, "인과관계·정도·시점을 나타내는
  부사/어미"가 바뀌며 의미가 달라질 위험(이번 실측에서는 A 사례 1건 외 추가 발견 없음 —
  표본이 1건이라 결론을 일반화하기엔 이름).
- **왜 발생하는가**: LLM에게 허용된 범위(`allowed_changes`, `llm_provider.py:143-146`)가
  "조사와 어미 변경, 문장 순서 조정, 동일 의미의 한국어 재표현"으로 넓게 정의되어 있고,
  "동일 의미"인지 아닌지는 LLM 스스로 판단하게 맡겨져 있다.
- **현재 구조의 어느 부분에서 발생하는가**: 프롬프트 설계(`_system_prompt`,
  `_user_prompt`)의 지시가 정성적("동일 의미")이라 LLM이 오판할 여지가 구조적으로 남아있다.
- **개선 방향**: KNOWLEDGE의 evidence 문장 중 "핵심 의미가 고정되어야 하는 문장"(예: result,
  lesson처럼 사실 확정 필드)은 프롬프트에서 "재구성 가능"이 아니라 "표현만 다듬기 가능, 핵심
  서술어 교체 금지"로 세분화해서 지시.
- **자동화 가능 여부**: 프롬프트 개선은 즉시 가능. 탐지 자동화는 어휘 사전 매칭 수준까지만
  현실적.
- **인간 검토 필요 여부**: 필요(경계 사례가 애매함).

### C. 금융/부동산 안전문구 변형

- **현재 문제**: 원문 면책 문구 "금융기관의 공식 심사 기준으로 해석하지 않습니다"를 LLM이
  "금융기관의 공식 심사 기준을 대표하지는 않습니다"로 의역했고, 의미는 거의 동일하지만
  `_FINANCE_BOUNDARY_PATTERN` 정규식과 정확히 매칭되지 않아 **rejected**됨
  (`5-3_real_llm_test.md` [5]).
- **왜 발생하는가**: 검증이 "의미 보존"이 아니라 "정확한 정규식 패턴 재현"을 요구하기 때문.
  LLM은 애초에 "동일 의미의 재표현"을 허용받았으므로 이 문구도 재표현 대상으로 취급했다.
- **현재 구조의 어느 부분에서 발생하는가**: `_finance_errors()`(`rewrite.py:182-195`) +
  프롬프트의 `allowed_changes`가 면책 문구를 예외로 명시하지 않음.
- **개선 방향**: §3에서 상세 설계 — 면책 문구를 "재작성 가능한 일반 텍스트"가 아니라
  "고정 보호 문구(protected span)"로 취급해 LLM에게 애초에 재작성 대상에서 제외하도록
  프롬프트/후처리 이중 방어.
- **자동화 가능 여부**: 완전 자동화 가능(고정 문구는 LLM 출력에 문자열 그대로 삽입/치환하는
  후처리로 강제 가능).
- **인간 검토 필요 여부**: 설계 확정 시점에는 필요(면책 문구 자체의 법적 적절성 검토는 사람
  몫), 운영 중에는 불필요.

### D. 과도한 validator rejection

- **현재 문제**: Blog 4건 중 3건이 rejected(위 C 사례 포함), 결과적으로 Blog 통과율 25%.
- **왜 발생하는가**: LLM의 "안전한 재표현" 성향과 validator의 "정확한 원문 재현" 요구 사이의
  간극. `5-3_real_llm_test.md` [8] 결론: "버그가 아니라 실제 LLM의 재작성 스타일과 검증기의
  엄격한 사실경계·표현 매칭 사이의 간극에서 비롯된 현상".
- **현재 구조의 어느 부분에서 발생하는가**: validator 자체보다는, **1회 생성 → 1회 검증 →
  실패 시 폐기**라는 구조(§1-6, 1-7)가 원인. 검증기를 완화하면 위험 문구가 새어나갈 수 있으므로
  느슨화는 해법이 아니다.
- **개선 방향**: §3의 Constrained Retry 구조. 검증 실패 사유를 LLM에게 그대로 알려주고
  "그 부분만 원문 그대로 복원"하도록 재시도.
- **자동화 가능 여부**: 가능(retry 루프는 순수 엔지니어링).
- **인간 검토 필요 여부**: 재시도도 실패하면(§3) 사람 검토 큐로.

### E. 제목 품질

- **현재 문제**: 이번 실측 1건은 제목-본문 일치가 양호했음(`5-3_real_llm_test.md` [4]).
  다만 검증기에는 제목 전용 품질 규칙이 없다(길이 제한, 클릭베이트 여부, 특수문자 남용 등
  전혀 검사 안 함).
- **왜 발생하는가**: `RewriteValidator`는 title/body를 합쳐서만 검사하고, title만의 별도
  규칙(글자 수, 특수기호, 낚시성 여부)이 없다.
- **현재 구조의 어느 부분**: `rewrite.py` 전체에 title 전용 검사 없음.
- **개선 방향**: 네이버 블로그 제목 길이 권장(대략 25~40자) 등 플랫폼 규칙을 title 전용
  validator로 분리.
- **자동화 가능 여부**: 완전 자동화 가능(길이/특수문자 카운트).
- **인간 검토 필요 여부**: 불필요(규칙 기반으로 충분).

### F. 본문 품질

- **현재 문제**: 실측 1건 기준 537자로 "네이버 블로그 포스트로서는 다소 짧은 편"
  (`5-3_real_llm_test.md` [4], [8]-⑩). 원인은 애초에 `generator.py`의 규칙 기반 템플릿이
  evidence 문장 5~6개를 인용 형태로 나열하는 구조라 정보량 자체가 KNOWLEDGE 필드 개수에 묶여
  있기 때문(추측이 아니라 `_experience_blog`/`_criterion_blog`의 실제 구현이 그렇다 —
  `generator.py:122-168`).
- **왜 발생하는가**: 본문 분량이 evidence 문장 개수에 선형으로 비례하는 구조이며, LLM은
  "새 사실 추가 금지"라 분량을 늘릴 수 없다(의도된 설계 — 사실 경계 유지가 최우선).
- **현재 구조의 어느 부분**: `generator.py`의 템플릿 함수들(문단 6개 이하로 고정) +
  `llm_provider.py` 프롬프트가 "사실 추가 금지"를 강조.
- **개선 방향**: 분량 확대는 "새 사실 추가"가 아니라 "기존 evidence에 대한 해설/맥락 추가
  (사용자 관점, 배경 설명)"로 늘려야 한다. 이는 곧 §4의 `user_experience_angle`,
  `original_angle` 같은 필드가 필요해지는 지점과 연결된다.
- **자동화 가능 여부**: 부분 가능(최소 글자 수 하한을 validator에 추가하는 것 자체는 쉬움).
  다만 "채우기"를 위해 억지로 늘리면 F가 아니라 새로운 품질 문제를 만든다.
- **인간 검토 필요 여부**: 분량 기준 설정은 사람이 판단(SEO 목표에 달림).

### G. 키워드 품질

- **현재 문제**: "자기계발, 아이디어를, 현실로, 제작, 여정에서" — 조사 결합형 키워드가
  다수(`5-3_real_llm_test.md` [6]). §1-5에서 원인 규명.
- **개선 방향**: §8 참고.
- **자동화 가능 여부**: 대부분 자동화 가능(조사 제거 규칙, 최소 길이, 명사형 검증).
- **인간 검토 필요 여부**: 불필요(규칙 기반 개선으로 충분).

### H. 해시태그 품질

- **현재 문제**: 키워드 품질 문제가 그대로 전파(`suggest_hashtags`가 키워드에 `#`만 붙임).
- **개선 방향**: G와 동일한 소스 문제이므로 키워드 개선 시 자동 해결.
- **자동화 가능 여부**: G에 종속.
- **인간 검토 필요 여부**: 불필요.

### I. 동일/유사 콘텐츠 위험

- **현재 문제**: 이번 실측 범위에서는 관찰되지 않았음(승인 KNOWLEDGE가 4건뿐이라 표본 부족).
  다만 구조적으로 `select_blog_publish_candidates()`(`blog_publish_pack.py:143-178`)는 "서로
  다른 KNOWLEDGE 우선"만 볼 뿐, **같은 KNOWLEDGE에서 나온 문장이 여러 플랫폼(Blog/Shorts/
  Threads)에 거의 동일하게 반복되는 것은 막지 않는다** — 실제로 `generator.py`의 템플릿
  구조상 동일 evidence 문장이 Blog/Shorts/Thread 각각에 재사용되는 게 정상 동작이다(예:
  `_experience_content`가 `problem`/`action`/`result`를 Shorts와 Threads 양쪽에서 재사용).
- **왜 발생하는가**: 콘텐츠 엔진이 "1개 KNOWLEDGE → 9개 Draft(Blog 1 + Shorts 3 + Threads 5)"를
  만드는 구조 자체가 원본 evidence 문장을 재조합하는 방식이라, 플랫폼 간 유사도가 태생적으로
  높다.
- **현재 구조의 어느 부분**: `generator.py`의 `_pick()` 함수는 이미 사용된 evidence unit id를
  피하려 하지만(`used_ids` 집합), 이는 **같은 Draft 내부** 중복만 막을 뿐 플랫폼 간(예: Blog와
  Thread) 중복은 애초에 설계 목표가 아니다.
- **개선 방향**: 플랫폼 간 콘텐츠는 원래 의도적으로 겹치는 게 정상(같은 소스를 여러 채널에
  맞게 재가공)이므로 이 자체는 문제라기보다, 향후 외부 소스가 늘어났을 때 "서로 다른
  KNOWLEDGE인데 결과물이 표현만 다르고 사실상 같은 글"이 되는 리스크에 대비해 §6에서
  유사도 검사를 설계한다.
- **자동화 가능 여부**: 간단한 자카드/코사인 유사도로 부분 자동화 가능.
- **인간 검토 필요 여부**: 경계값 근처는 필요.

### J. 원문 의존성

- **현재 문제**: 콘텐츠 품질이 KNOWLEDGE 원문(`experience`/`problem`/`action`/`result`/`lesson`/
  `reusable_principle`/`derived_insight`)의 품질에 전적으로 의존한다. `generator.py`는 이
  필드들을 문장 단위로 쪼개 인용 형태로 나열할 뿐(`_evidence_units`, `generator.py:32-43`),
  독자적인 분석이나 재구성을 하지 않는다.
- **왜 발생하는가**: 설계 철학상 "사실을 창작하지 않는다"를 최우선으로 삼았기 때문에
  의도된 트레이드오프다.
- **개선 방향**: 이 자체는 안전장치이므로 없애면 안 됨. 다만 §4/§5에서 `user_experience_angle`,
  `original_angle` 같은 "사람이 명시적으로 추가한 관점" 필드를 도입하면 원문 의존성을 낮추면서도
  사실 경계는 유지할 수 있다.
- **자동화 가능 여부**: 구조 설계는 자동화 가능하나, 관점/의견 자체는 사람(또는 승인된
  TAK BRAIN 추론)이 넣어야 한다.
- **인간 검토 필요 여부**: 필요(관점 추가는 본질적으로 사람의 판단 영역).

### K. 출처/근거 추적성

- **현재 문제**: §1-8에서 확인했듯 `evidence_unit_ids`는 `MediaBatchItem`/배치 JSON까지는
  보존되지만 `BlogPublishItem`(최종 Markdown)에는 `knowledge_id`+`source_url` 수준으로만
  축약된다. "본문의 몇 번째 문장이 KNOWLEDGE의 어느 필드에서 왔는지"는 최종 산출물만 보고는
  알 수 없다.
- **왜 발생하는가**: `BlogPublishItem` 데이터클래스 자체에 `evidence`/`evidence_unit_ids`
  필드가 없다(`blog_publish_pack.py:52-65`).
- **현재 구조의 어느 부분**: `build_blog_publish_pack()`이 `BlogPublishItem`을 만들 때
  이 필드들을 전달하지 않음(`blog_publish_pack.py:201-215`).
- **개선 방향**: 외부 소스를 다루게 될 §5-6에서는 이 추적성이 안전의 핵심이 되므로,
  최소한 배치 JSON 수준의 추적 정보를 최종 Pack까지 이어지게 하거나, 최소한 사람이 원한다면
  조회할 수 있는 링크(knowledge_id로 배치 JSON을 역참조)를 문서에 명시해야 한다.
- **자동화 가능 여부**: 가능(필드 추가 수준).
- **인간 검토 필요 여부**: 불필요(구조 문제).

---

## 3. 핵심 개선안 설계 — Constrained Retry

### 3-1) 구조

```
[1차 생성]
KNOWLEDGE → generator.py → ContentDraft (원본, 항상 안전)
    ↓
[LLM 재작성 시도 1회차]
RewriteProvider.rewrite(request) → rewritten_draft_1
    ↓
[Validator]
RewriteValidator.validate(request, rewritten_draft_1)
    ↓
통과 → 사용 가능 (현재와 동일)
실패 → [Constrained Retry, 최대 1~2회]
    실패 사유(validation_errors)를 구조화해 LLM에게 그대로 반환
    "다음 부분만 원문 그대로 복원하고 나머지는 유지하라"고 재요청
    ↓
[재검증]
통과 → 사용 가능
실패 → Reject (현재와 동일하게 Pack에서 제외, 사람이 배치 JSON에서 확인 가능)
```

핵심 원칙: **retry는 validator를 우회하는 통로가 아니라, "실패 사유를 좁혀서 같은 LLM에게
다시 기회를 주는" 통로**다. 재시도 요청 프롬프트는 자유 재작성이 아니라 "검증 실패 부분만
수정, 나머지는 그대로"로 범위를 좁힌다. 재시도 횟수는 반드시 상한(예: 1회)을 두고, 상한
초과 시 즉시 reject — 무한 재시도로 비용이 새는 것을 막는다.

### 3-2) 실패 사유의 기계 판독 가능한 코드화

현재 `RewriteValidation.errors`는 사람이 읽는 한국어 문장(`tuple[str, ...]`)이다
(`rewrite.py:56-58`). Constrained Retry를 구현하려면 각 에러에 안정적인 코드(예:
`NEW_NUMBER`, `NEW_ENTITY`, `FINANCE_BOUNDARY_LOST`, `THREADS_TOO_LONG`,
`STYLE_THIRD_PERSON`)를 붙여, 재시도 프롬프트가 "어떤 규칙을 어떻게 고쳐야 하는지"를 LLM에게
구조화된 형태로 전달할 수 있어야 한다. 이는 `RewriteValidation`/`errors` 문자열 형식을
바꾸는 것이므로 구현 단계의 일이며, 이번 설계 문서에서는 "에러 코드화가 필요하다"는 요건만
못박는다.

### 3-3) 금융 안전문구는 "재작성 대상"이 아니라 "보호 구간(protected span)"으로 취급

현재 문제(§2-C)의 근본 원인은 면책 문구를 LLM에게 "재표현 가능한 일반 텍스트"로 노출한 것이다.
개선 방향은 다음 두 가지를 병행하는 것이다(어느 하나만으로는 부족).

**(a) 프롬프트 층 — 보호 구간 명시**: `_user_prompt()`가 이미 `original_draft.body` 전체를
넘기고 있으므로, finance article에서는 면책 문구가 포함된 문장을 별도 필드
(예: `"protected_sentences": [...]`, 정확한 원문 문자열)로 명시하고 시스템 프롬프트에
"protected_sentences에 나열된 문장은 단 한 글자도 바꾸지 말고 그대로 포함하라"는 지시를
추가한다. 이는 "동일 의미의 재표현" 허용 범위에서 면책 문구를 명시적으로 제외하는 것이다.

**(b) 검증/후처리 층 — 결정적 강제**: 프롬프트 지시는 LLM이 어길 수 있으므로(현재 실측이
정확히 그 사례), 안전망으로 "finance article이고 원본에 보호 문구가 있었는데 재작성본에
정확히 같은 문자열이 없으면, 검증 실패로 처리하는 대신 **재작성본의 해당 위치(문단 끝)에
원본 보호 문구를 코드가 강제로 이어붙이는 후처리**"를 검토한다. 이 방식은 "느슨하게 검증을
통과시키는" 것이 아니라 "LLM이 무엇을 하든 최종 산출물에는 안전 문구가 정확한 원문 그대로
반드시 존재하게 만드는" 결정적 보정이다. 단, 이 후처리를 적용하면 검증기가 최종적으로
검사하는 대상은 "후처리 이후 텍스트"여야 한다(후처리 전 텍스트만 검사하고 후처리로 다시
깨뜨리는 순서 실수를 방지).

두 방법 중 하나만 구현하는 것보다, (a)로 애초에 LLM이 건드리지 않게 유도하고 (b)로 그래도
건드렸을 때 결정적으로 복구하는 **이중 방어**가 원칙에 부합한다("느슨하게 만드는 방식은
지양"이라는 지시와도 일치 — (b)는 검증을 느슨하게 하는 게 아니라 출력을 강제 교정하는 것).

### 3-4) 다른 검증 실패 유형에 대한 재시도 전략

| 실패 유형 | 재시도 시 LLM에게 줄 지시 | Retry로 해결 가능성 |
|---|---|---|
| `NEW_NUMBER` | "다음 숫자는 원문에 없습니다: {numbers}. 원문 숫자만 사용하라" | 높음 |
| `NEW_ENTITY`/`FACT_RISK_TERM` | "다음 단어는 원문에 없는 새로운 사실입니다: {terms}. 삭제하거나 원문 표현으로 되돌려라" | 높음 |
| `FINANCE_BOUNDARY_LOST` | §3-3의 protected_sentences 강제 삽입(재시도보다 후처리가 더 결정적) | 후처리 권장 |
| `STYLE_THIRD_PERSON` | "다음 표현은 3인칭 요약체입니다: {phrase}. 1인칭으로 다시 써라" | 높음 |
| `THREADS_TOO_LONG` | "본문을 500자 이하로 줄여라(현재 {length}자)" | 높음 |
| source_url/evidence 불일치 | 발생 불가능(코드가 강제 복사) — retry 대상 아님 | 해당 없음 |

---

## 4. 외부 소스 활용을 위한 데이터 구조 설계

### 4-1) 원칙

지시문의 "실제로 필요한 필드만 제안, 불필요하게 복잡한 구조는 만들지 않는다"는 원칙에 따라,
현재 `KnowledgeRecord`(`tak_brain/models.py:50-84`)를 무작정 확장하지 않고, **소스 출처
정보와 KNOWLEDGE 사실 정보를 분리**하는 최소 구조를 제안한다. 현재 `KnowledgeRecord`는
이미 `source_url`, `source_raw_id` 필드가 있지만 "출처가 OWNED 블로그"라는 가정이 암묵적으로
깔려 있다(`article_types.py`의 분류 규칙도 사용자 본인 블로그 문체를 전제).

### 4-2) 제안 필드 (KnowledgeRecord 확장 — 향후 구현 시)

모두 **선택적(optional) 필드**로 추가해 기존 OWNED 소스 흐름과 하위 호환을 유지한다.

| 필드 | 타입 | 용도 |
|---|---|---|
| `source_type` | `"owned" \| "external_blog" \| "news" \| "official" \| "multi_source"` | 소스 신뢰도/처리 정책 분기의 기준. 기본값 `"owned"`(현재 데이터와 하위 호환). |
| `source_domain` | `str \| None` | `source_url`에서 파생 가능하지만, 다중 소스 비교 시 빠른 필터링용으로 별도 저장. |
| `source_author` | `str \| None` | 외부 블로그/뉴스의 저자 표시(저작권/인용 표기용). |
| `source_published_at` | `str \| None` | 정보의 최신성 판단(특히 금융/세제처럼 시점에 민감한 정보). |
| `source_reliability` | `"high" \| "medium" \| "low" \| None` | OFFICIAL은 기본 high, EXTERNAL_BLOG는 기본 medium/low. 자동 산출이 아니라 TAK SCOUT 또는 사람이 부여. |

`source_summary`, `evidence`(이미 존재), `fact_claims`/`opinion_claims`는 4-3의 SOURCE
개념과 겹치므로 KnowledgeRecord에 직접 추가하지 않고 별도 SOURCE 모델(4-3)에만 둔다 —
이것이 "불필요하게 복잡한 구조를 만들지 않는다"는 원칙에 부합한다: KnowledgeRecord는
지금처럼 "승인된 사실"만 담당하고, "출처의 원본 성격"은 SOURCE가 담당하는 역할 분리.

`original_angle`, `user_experience_angle`은 KnowledgeRecord가 아니라 **KNOWLEDGE 생성
단계의 입력 필드**로 추가하는 편이 낫다(§9와 연결) — TAK BRAIN이 SOURCE에서 사실을 뽑아낸
뒤, "사용자(티몽)의 관점/경험"을 명시적으로 채워 넣는 필드로, 현재 `experience`/`lesson`
필드와 역할이 겹치지 않도록 "이 KNOWLEDGE가 왜 티몽만의 콘텐츠인가"를 담는 용도로 한정한다.

`related_knowledge_ids`는 MULTI_SOURCE 유형에서만 의미가 있다(여러 KNOWLEDGE를 종합한
새 KNOWLEDGE가 원본들을 가리킴). 이 역시 선택적 필드로 늦게 추가해도 무방 — P2/P3 우선순위.

### 4-3) 신규 SOURCE 모델 (KnowledgeRecord와 별도)

`RawContent`(`tak_brain/models.py:20-47`)가 이미 "원본 콘텐츠"를 담당하지만, 이는 "사용자
자신의 블로그 글"을 전제로 설계되어 있다(`BlogPost`에서 변환). 외부 소스는 RawContent를
억지로 재사용하기보다 **얇은 신규 모델 `Source`**를 별도로 두는 편이 기존 구조를 어지럽히지
않는다.

```
Source (신규, 제안)
  id
  source_type        # owned | external_blog | news | official | multi_source
  source_url
  source_title
  source_author
  source_published_at
  source_domain
  source_reliability
  fetched_at
  raw_text_ref        # 원문 전체가 아니라 저장 위치(파일 경로/해시) — 원문 그대로를
                       # KNOWLEDGE에 복제하지 않기 위한 참조
```

`fact_claims`/`opinion_claims`/`source_summary`는 Source 자체가 아니라 **SOURCE ANALYSIS**
단계(§5)의 산출물로 분리하는 것을 권장한다 — Source는 "무엇을 가져왔는가"만 담고, "그것을
어떻게 해석했는가"는 별도 단계의 책임으로 두는 것이 §6의 SOURCE FACT/OPINION 구분과도
자연스럽게 맞물린다.

---

## 5. TAK SCOUT 연결 구조

### 5-1) 파이프라인과 책임 분리

```
TAK SCOUT          외부 소스 수집 (OWNED 제외 4개 유형) — 지금은 placeholder
   ↓
SOURCE              4-3의 Source 모델. "무엇을 가져왔는가"만 기록.
   ↓
SOURCE ANALYSIS     Source에서 fact_claims/opinion_claims/source_summary를 뽑아내는 단계.
   ↓                여러 Source를 비교해 MULTI_SOURCE KNOWLEDGE를 만들 때도 이 단계에서 처리.
KNOWLEDGE           tak_brain.KnowledgeRecord. "승인된, 사용 가능한 사실+관점"만 기록.
   ↓                (기존 승인 워크플로우 knowledge_review_status 그대로 유지)
TAK MEDIA           content_engine 전체(변경 없음). 승인 KNOWLEDGE만 입력으로 받는 원칙도 유지.
   ↓
Blog / Threads / Shorts
```

### 5-2) 최소 필요 필드만 (재확인)

지시문이 예시로 든 필드(`source_type`, `source_url`, `source_title`, `source_author`,
`source_published_at`, `source_domain`, `source_reliability`, `evidence`, `fact_claims`,
`opinion_claims`, `source_summary`, `original_angle`, `user_experience_angle`,
`related_knowledge_ids`) 중 실제로 5-3-2 설계에서 "지금 확정해도 되는 것"과 "나중에
TAK SCOUT를 실제로 만들 때 확정할 것"을 구분한다.

- **지금 확정 가능(구조가 명확함)**: `source_type`, `source_url`, `source_title`,
  `source_domain`, `evidence`, `fact_claims`, `opinion_claims`.
- **TAK SCOUT 구현 시점에 확정(정책 의존적)**: `source_reliability`(신뢰도 산정 기준 자체가
  아직 없음 — 도메인 화이트리스트? 사람 평가? 향후 결정 필요), `source_author`/
  `source_published_at`(외부 소스마다 메타데이터 형식이 달라 파싱 전략이 필요).
- **뒤로 미뤄도 되는 것(P2/P3)**: `related_knowledge_ids`(MULTI_SOURCE를 실제로 다룰 때만
  필요), `original_angle`/`user_experience_angle`(§9 우선순위와 연결 — 콘텐츠 다양화 단계에서).

---

## 6. '원문 복제 위험' 검증 설계

### 6-1) 개념 정의

| 개념 | 정의 |
|---|---|
| SOURCE FACT | 외부 Source 원문에 명시적으로 쓰인, 검증 가능한 사실 진술(수치, 날짜, 발표 내용 등). |
| SOURCE OPINION | 외부 Source 저자/기관의 해석·주장·전망(사실이 아니라 그 출처의 관점). |
| GENERATED FACT | TAK MEDIA가 최종 콘텐츠에 실제로 포함한, SOURCE FACT에서 그대로 가져온 사실 진술. |
| GENERATED OPINION | 최종 콘텐츠에 포함된 의견 — SOURCE OPINION을 인용한 것인지, 티몽 본인의 새 의견(USER ORIGINAL ANGLE)인지 반드시 구분 표시. |
| USER ORIGINAL ANGLE | 어떤 Source에도 없는, 사용자(티몽)가 직접 추가한 경험/해석/판단. |

### 6-2) 관계 추적 방법

현재 `EvidenceUnit`(`content_engine/models.py:14-19`, `generator.py:32-43`)이 이미
"KNOWLEDGE 필드:문장번호 → 텍스트"라는 추적 단위를 갖고 있다. 이 패턴을 그대로 확장한다.

- SOURCE ANALYSIS 단계에서 `fact_claims`/`opinion_claims`에 담기는 각 항목에도
  `EvidenceUnit`과 동일한 형태의 id(`{source_id}:fact:{n}` / `{source_id}:opinion:{n}`)를
  부여한다.
- KNOWLEDGE의 각 필드(`experience`, `lesson` 등)를 만들 때, 그 문장이 어느 SOURCE FACT/
  OPINION에서 왔는지, 혹은 USER ORIGINAL ANGLE인지를 `evidence_units`처럼 매핑 테이블로
  남긴다(신규: `KnowledgeEvidenceLink(knowledge_field, knowledge_unit_id, source_unit_id | None)`
  — `source_unit_id`가 `None`이면 USER ORIGINAL ANGLE).
- 이렇게 하면 "이 KNOWLEDGE의 몇 %가 SOURCE FACT 인용이고 몇 %가 사용자 원본 관점인지"를
  기계적으로 계산할 수 있다 — 이것이 바로 아래 6-3 게이트의 입력이 된다.

### 6-3) Validator/Quality Gate 설계

| 위험 | 게이트 규칙(제안) | 자동화 |
|---|---|---|
| 원문 문장 재작성 수준에 그침(패러프레이즈만) | KNOWLEDGE의 USER ORIGINAL ANGLE 비율이 최소 임계치(예: 20~30%) 미만이면 콘텐츠화 차단, "관점 보강 필요"로 반려 | 가능(비율 계산은 결정적) |
| 특정 출처 하나에 과도 의존 | 하나의 `source_id`에서 온 SOURCE FACT/OPINION 비율이 임계치(예: 80%) 초과 시 경고 — MULTI_SOURCE 권장 | 가능 |
| 원문 구조를 그대로 따라감 | evidence_units의 등장 순서와 원문 SOURCE의 문단 순서 간 상관도가 지나치게 높으면 경고(구현 난이도 있음 — 순서만 비교하는 간단한 휴리스틱으로 시작) | 부분 가능, 정교화는 어려움 |
| 출처의 의견을 사실처럼 변환 | GENERATED FACT로 표시된 문장의 근원(source_unit_id)이 SOURCE OPINION이면 하드 차단(사실과 의견의 taxonomy가 6-1에서 이미 구분되므로 기계적으로 검사 가능) | 가능(가장 중요한 게이트) |
| 원문에 없는 내용을 AI가 추가 | 현재 `_fact_scope_errors`와 동일한 원리를 SOURCE 기반으로 확장 — source_unit_id로 추적 안 되는 새 사실 진술은 차단 | 가능(기존 로직 재사용) |
| 여러 출처 간 정보 충돌 | MULTI_SOURCE KNOWLEDGE 생성 시, 같은 주제의 SOURCE FACT들이 서로 다른 값(예: 금리 수치)을 담고 있으면 자동 병합 금지 → 사람이 어느 쪽을 채택할지 결정 | 탐지는 가능(값 비교), 해결은 사람 |

가장 중요한 게이트는 "출처의 의견을 사실처럼 변환"이다 — 이것이 뉴스/외부 블로그 활용 시
가장 흔하고 위험한 실수(예: "전문가는 ~라고 전망했다"를 "~다"로 단정)이기 때문이다.

---

## 7. 금융/부동산 콘텐츠 별도 품질 게이트

### 7-1) 현재 상태 재확인

이미 §1-3에서 확인했듯, 현재 구조는 이미 "일반 콘텐츠"와 "금융 콘텐츠"를 다르게 취급하는
씨앗이 있다: `generator.py`의 finance 프로필 고정 면책 문구, `rewrite.py`의
`_finance_errors()`, `blog_publish_pack.py`의 `is_review_required()`. 다만 이 셋은
서로 독립적으로 구현되어 있고 "게이트"로 명시적으로 묶여 있지는 않다.

### 7-2) 제안 게이트 순서(향후 외부 소스 포함 확장판)

```
콘텐츠 유형 판정 (article_type == "finance" 또는 category/domain에 금융 키워드)
    ↓ Yes
[fact validation]
  - 수치(금리, 세율, 한도 등)는 반드시 evidence_unit 또는 SOURCE FACT로 추적 가능해야 함
  - 추적 불가능한 수치는 생성 단계에서부터 차단(현재 generator.py는 이미 이 원칙을 지킴 —
    template이 KNOWLEDGE 필드 밖의 숫자를 만들 수 없는 구조)
    ↓
[source verification] (외부 소스 도입 이후에만 의미가 생김)
  - source_type == "official"이 아닌 소스에서 온 "현재 제도/금리/세율" 성격 정보는
    source_published_at이 오래되었거나 없으면 차단 또는 review_required 강제
    ↓
[boundary validation] (현재 _finance_errors, §3-3의 protected span 포함)
  - 확정적 투자 판단, 법률적 확정 판단, 세금 확정 해석, 특정 상품 가입 유도 표현을
    금지어 사전 + 패턴으로 차단(아래 7-3)
    ↓
[human review required] (현재 is_review_required + Markdown 체크박스, 변경 없음)
```

### 7-3) 자동으로 만들어내지 않도록 방어할 표현 — 금지어/패턴 사전(제안)

지시문이 나열한 6가지 위험 표현 각각에 대해, `RewriteValidator`에 추가할 수 있는 탐지
방향을 제안한다(전부 "새로운 검증 규칙 카테고리"이지 기존 `_finance_errors`를 느슨하게
푸는 것이 아님).

| 위험 표현 | 탐지 방향(제안) |
|---|---|
| 확정적 투자 판단 ("~하면 무조건 오릅니다") | "무조건", "확실히", "반드시 ~됩니다" 같은 확정 부사 + 투자/가격/수익 관련 명사 공기(co-occurrence) 패턴 |
| 금융기관 공식 심사기준처럼 보이는 표현 | 기존 `_FINANCE_BOUNDARY_PATTERN`/"공식 심사 기준" 탐지를 유지·강화(§3-3) |
| 법률적 확정 판단 ("이것은 불법입니다") | "불법", "합법", "위법" + 확정 어미("~입니다/~됩니다") 조합, 판단 근거(법령 조항) 인용 없이 등장하면 차단 |
| 세금 확정 해석 ("이 경우 비과세입니다") | "과세", "비과세", "공제" + 확정 어미, source_type이 official이 아니면 차단 |
| 특정 금융상품 가입 유도 | "가입하세요", "추천합니다", 특정 상품명 + 행동 유도 어미 조합 |
| 근거 없는 수치 | 기존 `_new_number_errors` 원리 그대로(이미 강함) — 외부 소스 도입 시 source_unit_id로 추적 안 되는 수치도 동일하게 차단하도록 확장 |
| 출처 없는 최신 제도 정보 | source_published_at 없음 + "최근", "이번 달부터", "새로 바뀐" 같은 시의성 표현 공존 시 차단 |

이 사전은 정규식 기반이라 오탐(false positive)이 발생할 수 있음을 인지해야 한다 —
`docs/5-3_real_llm_test.md` [9]-3에서 이미 "느슨하게 풀었다가 실제 위험 문구를 통과시키는
리스크가 더 크다"고 결론 낸 것과 같은 원칙으로, **오탐이 있더라도 엄격한 쪽을 기본값으로
하고, 오탐 사례는 사람이 반려하며 사전을 다듬는 방식**을 권장한다.

---

## 8. Blog 품질 설계

현재 `BlogPublishItem`/`render_markdown`(`blog_publish_pack.py:51-141, 219-277`) 구조를
기준으로 항목별 개선 방향을 정리한다.

| 항목 | 현재 상태 | 개선 방향 |
|---|---|---|
| 제목 | `generator.py` 템플릿 고정 제목(예: "직접 시도하며 얻은 교훈") 또는 LLM 재작성 결과. 길이/품질 검증 없음 | §2-E: title 전용 validator(길이, 특수문자) 추가 |
| 도입부 | 별도 개념 없음 — 본문 첫 문단이 곧 도입부 | 첫 문단에 "훅" 역할을 명시적으로 요구하는 프롬프트 지시 추가(이미 `_platform_requirements`에 일부 존재) |
| 본문 구조 | evidence 문장을 인용문("~고 적었습니다" 등) 형태로 나열 | §2-F: 사용자 관점/맥락 문단을 구조적으로 추가할 자리를 템플릿에 마련(원본 사실 자리와 분리) |
| 소제목 | 없음(단일 흐름 본문) | 네이버 블로그는 소제목이 있으면 가독성이 좋아짐 — evidence_units의 field_name을 소제목 후보로 매핑하는 방안 검토(예: "문제" / "시도" / "결과" / "교훈") |
| 키워드 | §1-5, §2-G의 조사 결합 문제 | 아래 8-1 상세 규칙 |
| 해시태그 | 키워드와 동일 문제 | 키워드 개선 시 자동 해결 |
| 이미지 아이디어 | `_GENERIC_IMAGE_IDEAS` 완전 고정 3개 문구(`blog_publish_pack.py:44-48`), 콘텐츠와 무관 | 콘텐츠 유형(profile: experience/finance/book)별로 이미지 아이디어 후보를 다양화(여전히 "사실을 추가하지 않는" 원칙 유지 — 이미지 아이디어는 사실 진술이 아니므로 위험도 낮음) |
| 출처 표시 | `source_url`, `knowledge_id`만 원문란에 표시 | §2-K: evidence_unit_ids 수준까지는 아니어도 최소한 "이 글은 N개의 원문 근거 문장을 기반으로 함" 같은 요약 카운트 추가 검토 |
| 개인 경험/의견 | KNOWLEDGE의 experience/lesson 필드에 의존, 별도 "의견" 슬롯 없음 | §4의 `user_experience_angle` 필드 도입과 연결 |
| CTA | 전혀 없음(`generator.py` 어떤 프로필에도 CTA 문단 없음) | 신규 도입 시 "구독/이웃추가 유도" 같은 정형 CTA는 사실 진술이 아니므로 낮은 리스크로 추가 가능 — 다만 이번 설계에서는 우선순위 낮음(P3) |

### 8-1) 키워드/해시태그 품질 규칙(상세 제안)

`5-3_real_llm_test.md`가 지적한 "자기계발, 아이디어를, 현실로, 제작, 여정에서" 문제를
다음 규칙으로 개선할 것을 제안한다(구현하지 않음, 규칙만 설계).

1. **조사 후보 제거**: 한국어 조사 목록(을/를, 이/가, 은/는, 에서, 으로/로, 의, 와/과 등)이
   단어 끝에 붙어 있으면 제거한 나머지를 후보로 삼는다. 다만 이는 형태소 분석기 없이는
   완벽할 수 없으므로(오탐 가능 — 예: "미로"에서 "로"를 조사로 착각), **명사형 사전에
   존재하는 경우만 조사 제거를 적용**하는 보수적 접근 또는 경량 형태소 분석 라이브러리
   도입 중 하나를 선택해야 한다(구현 단계에서 결정).
2. **최소 길이 및 문장형 배제**: 공백을 포함하거나 어미(다/니다/습니다 등)로 끝나는 후보는
   애초에 후보에서 제외한다(현재 `_KEYWORD_TOKEN_PATTERN`은 공백을 자동으로 토큰 경계로
   삼으므로 이 문제는 없지만, "~에서" 같은 조사형은 여전히 통과함 — 1번 규칙과 함께 적용).
3. **불용어 사전**: "제작", "여정" 같은 일반명사는 남기되, 지시문의 우려처럼 "너무 일반적인
   단어만 남는" 것도 품질 저하이므로, `category`/`domain`처럼 이미 신뢰할 수 있는 소스에서
   나온 키워드를 우선순위 상단에 고정하고, 제목에서 뽑은 키워드는 후순위로 배치.
4. **원칙 재확인**: 이 개선은 "새 키워드를 창작"하는 게 아니라 "이미 존재하는 텍스트(제목/
   category/domain)에서 문법적으로 더 정확하게 추출"하는 것이므로, 사실 경계 원칙(새 사실
   추가 금지)과 충돌하지 않는다.

---

## 9. 하루 5개 생성에 대한 품질 관점 재검토

### 9-1) 현재 구조가 "선택"이 아니라 "필터링"에 가까운 이유

현재 `select_blog_publish_candidates()`(`blog_publish_pack.py:143-178`)는 후보 풀 자체가
**승인된 KNOWLEDGE 전체 = 후보 전체**다. "10~20개 후보 중 상위 5개를 고르는" 개념이 아니라,
"승인된 것 중 아직 안 쓴 것을 앞에서부터 최대 5개 채우는" 방식이다(서로 다른 KNOWLEDGE
우선순위만 있고, 품질/검색가치/신뢰도 기반 순위는 없음). 실측에서도 승인 KNOWLEDGE 4건 중
Blog로 valid한 게 1건뿐이라 "선택"이라고 부를 만한 여지 자체가 없었다
(`5-3_real_llm_test.md` [2]).

### 9-2) TAK SCOUT과 TAK MEDIA의 역할 구분(제안)

| 역할 | 담당 모듈 | 현재 상태 |
|---|---|---|
| 후보 소재 발굴(10~20개 규모) | TAK SCOUT(향후) | placeholder, 미구현 |
| 소재의 검색가치/트렌드성 평가 | TAK SCOUT(향후) | 미구현 |
| 출처 신뢰도 평가 | TAK SCOUT(향후, official/external_blog 등급) | 미구현. OWNED만 있는 지금은 애초에 불필요했음 |
| 중복/유사 콘텐츠 배제 | TAK SCOUT(발굴 단계) + TAK MEDIA(생성 이후, §6) 이중 체크 | 현재는 "서로 다른 KNOWLEDGE 우선"이라는 최소 수준만 TAK MEDIA(`blog_publish_pack.py`)에 있음 |
| 승인된 사실을 콘텐츠로 변환 | TAK MEDIA(`generator.py`+`rewrite.py`) | 구현되어 있고 잘 동작(안전 경계 준수는 실측으로 확인됨) |
| 사실 경계/안전 검증 | TAK MEDIA(`RewriteValidator`) | 구현되어 있음, 개선 필요(§2, §3) |
| 플랫폼별 포맷팅/최종 패키징 | TAK MEDIA(`blog_publish_pack.py`) | 구현되어 있음, 개선 필요(§8) |

즉 **"좋은 5개를 고르는 능력"은 TAK SCOUT의 책임 영역**이고, 지금 TAK MEDIA는 애초에
"고르는" 단계가 아니라 "승인된 것을 변환·검증"하는 단계만 맡고 있다. 현재 하루 5건 목표
미달(실측 1건)은 TAK MEDIA의 실패가 아니라, **TAK SCOUT이 아직 없어서 후보 풀 자체가
작다**는 상류 문제다.

---

## 10. 최종 권장 아키텍처 — 모듈별 책임

```
OWNED KNOWLEDGE + EXTERNAL BLOG + NEWS + OFFICIAL + MULTI SOURCE
        ↓
    TAK SCOUT       — 소재 발굴, source_type 태깅, source_reliability 1차 평가,
                       후보 10~20개 규모 확보, 중복 소재 사전 배제
        ↓
 SOURCE ANALYSIS    — SOURCE FACT/OPINION 분리, fact_claims/opinion_claims 추출,
                       MULTI_SOURCE 비교·충돌 탐지(§6)
        ↓
    TAK BRAIN        — 승인 워크플로우(knowledge_review_status), KnowledgeRecord 생성,
                       privacy/internal_information 위험 탐지(기존 `build_metadata` 그대로),
                       USER ORIGINAL ANGLE 결합
        ↓
    TAK MEDIA        — generator.py(Draft 생성) + rewrite.py(LLM 재작성 + Validator,
                       §3의 Constrained Retry 추가) + blog_publish_pack.py(포맷팅,
                       §8의 키워드/구조 개선, §7의 finance 게이트)
        ↓
 Blog / Threads / Shorts
        ↓
      TRAFFIC        — 현재 미구현(조회수/도달 추적)
        ↓
     MONETIZATION     — `docs/5-2_monetization_analysis.md` 범위(별도 문서)
```

TAK SCOUT과 SOURCE ANALYSIS를 별도 단계로 명시한 이유: TAK SCOUT은 "무엇을 가져올까"를
결정하고, SOURCE ANALYSIS는 "가져온 것에서 무엇이 사실이고 무엇이 의견인가"를 결정한다.
이 둘을 합치면 "발굴 기준"과 "해석 기준"이 뒤섞여 향후 신뢰도 조정이 어려워지므로 분리를
권장한다. TAK BRAIN은 지금처럼 "승인" 게이트를 유지하되, 입력이 OWNED 하나에서 여러 SOURCE
유형으로 늘어나는 것뿐 — 승인 워크플로우 자체의 책임은 바뀌지 않는다.

---

## 11. 구현 우선순위

| 우선순위 | 항목 | 근거 |
|---|---|---|
| **P0** | Constrained Retry(§3-1, 3-2) | 실측 Blog 통과율 25%의 직접 원인 해결. 코드 변경량 대비 효과가 가장 큼. |
| **P0** | 금융 안전문구 protected span 처리(§3-3) | 실측에서 정확히 재현된 문제이자, 금융 콘텐츠는 리스크가 가장 크므로 가장 먼저 확정해야 함. |
| **P0** | 키워드/해시태그 개선(§8-1) | 실측으로 재현된 문제, 구현 난이도가 낮고 사실 경계와 무관해 안전하게 즉시 개선 가능. |
| **P1** | Validator 에러 코드화(§3-2) | Constrained Retry의 전제 조건. P0와 사실상 묶어서 진행. |
| **P1** | Finance safety gate 명시적 통합(§7) | 기존 3개 조각(면책 문구, `_finance_errors`, `is_review_required`)을 하나의 게이트로 문서화·정렬. |
| **P1** | Source provenance를 BlogPublishItem까지 보존(§2-K) | 외부 소스 도입 전에도 이미 유용(추적성 개선), 구현 비용 낮음. |
| **P2** | Duplicate/similarity detection(§2-I, §6) | 외부 소스가 실제로 늘어나기 전까지는 긴급하지 않음(현재 표본에서 미관찰). |
| **P2** | External source 지원 — Source 모델(§4-3), SOURCE FACT/OPINION 구분(§6) | TAK SCOUT 구현과 강하게 결합되어 있어 TAK SCOUT 착수 시점과 함께 진행하는 게 자연스러움. |
| **P2** | TAK SCOUT 최소 구현(소재 발굴 + source_type 태깅) | OWNED 소스만으로는 "하루 5개" 목표 자체가 상류 병목(§9)이므로, Retry/게이트 개선 이후 다음 큰 단계. |
| **P2** | Topic scoring(검색가치/신뢰도 기반 후보 순위) | TAK SCOUT 구현과 함께 진행. 후보 풀이 커진 뒤에야 의미가 생김. |
| **P3** | Human review 워크플로우 강화(현재는 체크박스뿐, 리뷰 결과를 기록/추적하는 시스템 없음) | 현재도 사람이 최종 게시 전 전량 검토하므로 급하지 않음. 물량이 늘어나면 재검토. |
| **P3** | Performance feedback(TRAFFIC → 콘텐츠 품질 피드백 루프) | 아직 TRAFFIC 단계 자체가 없어 전제 조건 미충족. |

---

## 12. 마지막 정리

### 12-1) 현재 가장 심각한 품질 문제 TOP 5

1. **Blog 검증 통과율이 25%에 불과하고 복구 수단이 없다** — `RewriteService`가 1회 생성/
   1회 검증만 하고 재시도가 전혀 없어(§1-6, 1-7), rejected된 KNOWLEDGE는 그날 완전히
   버려진다. 이는 "하루 5개" 목표와 직접 충돌한다.
2. **의미가 미묘하게 달라져도 검증기가 못 잡는다** — "비공개"→"비공식" 사례(§2-A)처럼,
   표층 텍스트 매칭(새 숫자/새 개체명/고정 위험어) 밖에 있는 의미 변형은 구조적으로
   탐지 불가능하다.
3. **금융 안전문구가 "정확한 문자열 재현"에만 의존한다** — 의미상 안전한 의역도 정규식이
   다르면 거부되고(§2-C), 반대로 정규식만 맞으면 의미가 살짝 달라져도 통과할 여지가
   이론상 남아있다(현재는 거부 쪽에서만 실측되었지만, 통과 쪽 실패 사례도 원리적으로
   가능).
4. **키워드/해시태그가 조사 결합형으로 나와 그대로 쓸 수 없다** — 순수 정규식 토큰화의
   한계(§1-5)로, 실측 5개 중 3개가 부적합.
5. **출처 추적성이 최종 산출물에서 끊긴다** — `evidence_unit_ids`가 배치 JSON까지는 살아
   있지만 사람이 실제로 보는 Markdown Pack에는 `knowledge_id`/`source_url`로만 뭉뚱그려져,
   "이 문장이 정확히 어디서 왔는가"를 최종 산출물만으로는 알 수 없다(§1-8, §2-K). 외부
   소스가 늘어나면 이 문제는 안전 이슈로 격상된다.

### 12-2) 가장 먼저 구현해야 할 개선안 TOP 5

1. **Constrained Retry 도입(§3-1)** — validation_errors를 코드화(§3-2)하고, 실패 부분만
   좁혀서 1회 재시도. TOP 5 문제 1번을 직접 해결.
2. **금융 면책 문구 protected span 이중 방어(§3-3)** — 프롬프트에서 명시적으로 "건드리지
   말라" 지시 + 후처리로 결정적 강제 삽입. TOP 5 문제 3번 해결.
3. **키워드 추출 규칙 보강(§8-1)** — 조사 제거 + 문장형 배제 + 소스 우선순위. 구현 난이도가
   낮고 사실 경계와 무관해 리스크 없이 바로 적용 가능. TOP 5 문제 4번 해결.
4. **핵심 서술어 사전 기반 의미 변형 탐지(§2-A 개선 방향)** — "비공개/비공식", "확정/추정"
   처럼 반의어에 가까운 단어쌍을 최소 사전으로 관리해 치환을 탐지. 완전한 해법은 아니지만
   TOP 5 문제 2번의 가장 저비용 완화책.
5. **BlogPublishItem에 evidence/evidence_unit_ids(또는 최소 요약) 보존(§2-K)** — 외부
   소스 도입 이전에 지금 당장 고쳐도 이득이 있고, TOP 5 문제 5번을 해결하며 §6의 추적
   구조를 위한 선행 작업이 된다.

### 12-3) 향후 TAK SCOUT와 연결할 때 반드시 지켜야 할 원칙 TOP 10

1. TAK SCOUT은 "무엇을 가져올까"만 결정하고, "그것이 사실인지 의견인지"는 SOURCE ANALYSIS
   단계로 넘긴다 — 두 책임을 한 모듈에 합치지 않는다(§10).
2. 외부 소스 원문을 KNOWLEDGE 필드에 그대로 복사하지 않는다 — 반드시 SOURCE FACT/OPINION
   분해를 거친 뒤에만 KNOWLEDGE로 승격한다(§6).
3. 하나의 외부 출처만 보고 KNOWLEDGE를 만들지 않는 것을 원칙으로 하되, 예외(단일 출처
   허용)는 `source_reliability == "official"`처럼 명시적 조건으로만 허용한다.
4. SOURCE OPINION을 GENERATED FACT로 전환하는 것은 항상 하드 차단한다(§6-3) — 이것이
   가장 위험한 실수 유형이다.
5. `source_published_at`이 없거나 오래된 소스의 시의성 있는 정보(금리, 세율, 제도)는
   기본적으로 콘텐츠화하지 않거나 review_required를 강제한다(§7-3).
6. 기존 KNOWLEDGE 승인 워크플로우(`knowledge_review_status`)를 SOURCE 유형에 따라
   우회하지 않는다 — OWNED든 EXTERNAL이든 승인 절차는 동일하게 적용한다.
7. USER ORIGINAL ANGLE(티몽의 관점)이 일정 비율 이상 포함되지 않은 콘텐츠는 "단순
   재작성"으로 간주해 게시 후보에서 제외하거나 낮은 우선순위로 둔다(§6-3).
8. 새로 추가하는 필드는 전부 선택적(optional)으로 시작해 기존 OWNED 데이터/테스트와
   하위 호환을 깨지 않는다(§4-2).
9. `RewriteValidator`가 이미 지키는 원칙(숫자/개체명/사실범위 불변, source_url/evidence
   불변)을 외부 소스 기반 KNOWLEDGE에도 예외 없이 동일하게 적용한다 — 소스가 다양해져도
   "새 사실을 창작하지 않는다"는 최우선 원칙은 절대 완화하지 않는다.
10. 여러 SOURCE가 서로 다른 값(수치, 날짜, 결론)을 말할 때 자동으로 하나를 고르지 않고,
    반드시 사람이 채택 여부를 결정하게 한다(§6-3 정보 충돌 게이트).

### 12-4) 다음 개발 단계에 대한 권장안

가장 먼저 §11의 P0 세 항목(Constrained Retry, 금융 protected span, 키워드 개선)을
`content_engine/rewrite.py`와 `content_engine/blog_publish_pack.py`에 한정된 범위로
구현하고, 실제 LLM으로 다시 1회 실전 테스트(`docs/5-3_real_llm_test.md`와 같은 형식의
새 문서)를 돌려 Blog 통과율이 개선되었는지 수치로 확인하는 것을 권장한다. 이 P0 작업은
외부 소스나 TAK SCOUT과 무관하게 지금 승인 KNOWLEDGE만으로도 즉시 검증 가능하므로, TAK
SCOUT 착수보다 먼저 완료하는 것이 순서상 합리적이다. TAK SCOUT/외부 소스 지원(P2)은
Source 모델과 SOURCE FACT/OPINION 분리 설계가 이미 이 문서에 준비되어 있으므로, P0/P1이
안정화된 다음 별도 단계(5-4 등)로 착수할 것을 권장한다.

---

**이번 단계에서는 코드 변경 없음.**
