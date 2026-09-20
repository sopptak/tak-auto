# TAK AUTO 6-07 — 두 번째 KNOWLEDGE 정정 및 실제 Generation Pool 재생성

## 1. 작업 시작 상태

```
$ git branch --show-current
main

$ git log -10 --oneline
08b5a1d docs: record final commit/push confirmation in 6-06 report
74c3491 feat: add media generation versioning and safe promotion
a2094c4 docs: record final commit/push confirmation in 6-05 report
a473262 fix: correct scout knowledge type before media regeneration
3d8556a docs: record final commit/push confirmation in 6-04 report
31488ee fix: prevent cross-domain media template leakage
8cb4923 docs: record final commit/push confirmation in 6-03 report
1e8d875 fix: validate knowledge to media operational pipeline
025916d docs: record final commit/push confirmation in 6-02 report
9e99a47 feat: operationalize publish performance tracking

$ git fetch origin   # (출력 없음, 최신)
$ git log origin/main..HEAD --oneline   # (출력 없음, 앞서가는 커밋 없음)
```

`git status --short`(작업 시작 시점 전체 — 6-06 종료 시점과 완전히 동일함을 확인했다):

```
 M .gitignore
 M content_engine/__init__.py
 M content_engine/generator.py
 M content_engine/llm_provider.py
 M content_engine/rewrite.py
 M data/tak_brain_knowledge.json
 M tests/test_content_engine.py
 M tests/test_media_batch.py
?? data/tak_media_archive.json
?? (다수의 기존 untracked 문서/스크립트 — 이번 작업과 무관, 손대지 않음)
```

Baseline 전체 테스트:

```
840 passed, 68 subtests passed in 130.53s (0:02:10)
```

6-06 종료 시점 보고와 정확히 일치함을 확인했다(0 failed).

## 2. 대상 KNOWLEDGE

- knowledge_id: `knowledge-scout-6d1d0e2fa762`
- source title: "Uncontrolled AI could lead to 'silicon species' rivalling
  humans, warns Microsoft"

`data/tak_brain_knowledge.json`에서 이 레코드를 직접 읽어 확인했다(6-05가 기록한
값과 정확히 일치함을 재확인).

## 3. 정정 전 상태

```json
{
  "id": "knowledge-scout-6d1d0e2fa762",
  "source_raw_id": "scout-23b521e0ecbb",
  "source_url": "https://www.bbc.co.uk/news/articles/c6n07ypqz8kzo?at_medium=RSS&at_campaign=rss",
  "title": "Uncontrolled AI could lead to 'silicon species' rivalling humans, warns Microsoft",
  "article_type": "finance",
  "domain": "금융",
  "knowledge_type": "의견",
  "lesson": "Mustafa Suleyman says he believes rival AI firm Anthropic is in effect teaching Claude it \"may be conscious\".",
  "reusable_principle": "Q1. AI에게 '의식이 있을 수 있다'고 가르치는 일이 논란이 된다면... (Q1~Q3 문답 전문)",
  "evidence": [
    "SOURCE FACT: Mustafa Suleyman says he believes rival AI firm Anthropic is in effect teaching Claude it \"may be conscious\".",
    "SOURCE URL: https://www.bbc.co.uk/news/articles/c6n07ypqz8kzo?at_medium=RSS&at_campaign=rss",
    "USER ORIGINAL THOUGHT: Q1~Q3 문답 전문"
  ],
  "knowledge_review_status": "approved",
  "reviewed_at": "2026-09-19T04:56:09.685072+00:00",
  "review_note": "SCOUT 인터뷰 테스트 승인",
  "category": "금융",
  "created_at": "2026-09-19T04:49:15.737804+00:00"
}
```

## 4. 정정 근거

- `tak_scout/knowledge_bridge.py` (97행)를 다시 확인했다 — 6-04 수정이 그대로
  살아 있으며, SCOUT 경로에서 생성되는 모든 KNOWLEDGE의 `article_type`은 항상
  `None`이다.
- 이 레코드의 `created_at`은 `2026-09-19T04:49:15`로, 6-04 수정이 이미 코드에
  반영된 이후(6-04 커밋 `31488ee`는 그보다 훨씬 이전)의 시각이다 — 즉 "6-04
  수정 이전 코드로 만들어진 레코드"라는 가정이 첫 번째 KNOWLEDGE와는 다르다.
  하지만 실제로는 이 레코드가 6-04의 코드 수정과 무관하게, **다른 경로(수동
  인터뷰 테스트, `review_note: "SCOUT 인터뷰 테스트 승인"`)로 생성됐거나
  수정 전 코드가 여전히 실행 중이던 세션에서 만들어졌을 가능성**이 있다 —
  정확한 생성 경로를 코드로 재현할 수는 없었지만(과거 실행 로그가 없음),
  **현재 실제 데이터가 `article_type="finance"`이면서 source 내용은 명백히
  AI/기술 뉴스라는 사실 자체**가 정정 근거다("현재 코드가 고쳐졌다는 이유만으로
  과거 데이터가 자동 수정됐다고 가정하지 않는다"는 지시를 따라, 코드가 아니라
  **데이터와 source 내용**을 근거로 판단했다).
- source 내용 확인: title "Uncontrolled AI could lead to 'silicon species'
  rivalling humans, warns Microsoft", evidence "Mustafa Suleyman(당시 Microsoft
  AI 총괄)이 경쟁사 Anthropic이 Claude에게 '의식이 있을 수 있다'고 가르치고
  있다고 믿는다" — **금융/대출/투자와 전혀 무관한 AI 산업 뉴스**다. `category`/
  `domain`이 "금융"인 것은 6-05에서 확인한 것과 동일한 근본 원인(SCOUT RSS
  소스의 뭉뚱그려진 카테고리 태깅)으로 보인다.
- `content_engine/generator.py:_profile()`가 `article_type == "finance"`일
  때만 finance 템플릿(제목/면책 문구)을 적용하는 것은 6-05·6-06에서 이미
  코드로 확인했다 — 다시 읽어 동일함을 재확인했다.

## 5. 정정 후 상태

**변경된 필드는 `article_type` 단 하나뿐이다.**

```diff
-  "article_type": "finance",
+  "article_type": null,
```

그 외 `title`, `source_url`, `source_raw_id`, `domain`, `category`,
`knowledge_type`, `lesson`, `reusable_principle`, `evidence`,
`knowledge_review_status`, `reviewed_at`, `review_note`, `created_at`은
정정 전/후 완전히 동일함을 `tests/test_second_knowledge_correction_and_generation_pool.py::SecondKnowledgeCorrectionTests::test_other_fields_are_unchanged_from_6_05_report`로
고정했다.

**5장 사람 수정 흔적 확인**: `review_note`("SCOUT 인터뷰 테스트 승인")는
`knowledge_review_status`(승인 여부)에 대한 일반적인 메모이지, `article_type`
분류 자체를 사람이 의도적으로 "finance"로 판단했다는 근거가 아니다.
`reviewed_at`/`review_note` 어디에도 "금융으로 분류함" 같은 명시적 판단 흔적이
없어 **blocker 없이 정정을 진행**했다.

## 6. 안전한 데이터 staging

`data/tak_brain_knowledge.json`은 6-05 때와 마찬가지로 다른 세션이 추가한
미커밋 KNOWLEDGE 레코드가 다수 섞여 있었다(6-05 이후 정리되지 않고 그대로
남아 있음).

```
$ git show HEAD:data/tak_brain_knowledge.json | python3 -c "..."
HEAD count: 11   # 6-05가 이미 커밋한 knowledge-scout-b28b782b2a33 정정 포함
현재 working tree count: 28
```

6-05와 동일한 방법으로, HEAD의 11개 레코드 + 이번에 정정한
`knowledge-scout-6d1d0e2fa762` 레코드 1건만 담은 blob을 직접 인덱스에 올렸다.

```
git hash-object -w <staged_knowledge.json>   # HEAD(11) + 정정된 1건 = 12건
git update-index --cacheinfo 100644,<blob>,data/tak_brain_knowledge.json
```

확인 결과:

```
$ git diff --cached --stat -- data/tak_brain_knowledge.json
 data/tak_brain_knowledge.json | 38 ++++++++++++++++++++++++++++++++++++++
 1 file changed, 38 insertions(+)

$ git diff --stat -- data/tak_brain_knowledge.json   # 작업 트리 vs 인덱스
 data/tak_brain_knowledge.json | 608 ++++++++++++++++++++++++++++++++++++++++++
 1 file changed, 608 insertions(+)
```

`git diff`(작업 트리 vs 인덱스)에서 `knowledge-scout-6d1d0e2fa762`의 `id` 줄이
**컨텍스트 줄(`+` 없음)로만 나타남**을 확인했다 — 이번 세션이 정정한 레코드는
정확히 인덱스에 반영됐고, 나머지 16개 레코드(6-05 이후 계속 남아 있던 다른
세션의 작업)는 여전히 미커밋 상태로 손대지 않았다는 뜻이다.

## 7. 실제 LLM 실행

실행 전 확인:

```
$ env | grep -o "^TAK_MEDIA_LLM_[A-Z_]*" | sort
TAK_MEDIA_LLM_API_KEY
TAK_MEDIA_LLM_ENDPOINT
TAK_MEDIA_LLM_MODEL
```

(값은 절대 출력하지 않았다 — 존재 여부만 확인.)

실행 명령(정확히 1회):

```
python3 scripts/run_media_batch.py --execute --as-generation \
  --id knowledge-scout-6d1d0e2fa762 \
  --archive data/tak_media_generation_6-07_knowledge-scout-6d1d0e2fa762.json \
  --output data/tak_media_batch_6-07_knowledge-scout-6d1d0e2fa762_snapshot.json
```

실제 출력:

```
=== TAK MEDIA Batch Pipeline 실행 완료 ===
전체 KNOWLEDGE: 1건
승인 KNOWLEDGE 처리: 1건 (건너뜀: 0건)
총 생성 Draft: 9건
  - Valid (검증 통과): 9건
  - Rejected (검증 실패): 0건
  - Error (오류): 0건
결과 저장 완료: data/tak_media_batch_6-07_knowledge-scout-6d1d0e2fa762_snapshot.json
generation pool 저장 완료 (valid/rejected/error 전체 누적): data/tak_media_generation_6-07_knowledge-scout-6d1d0e2fa762.json
이번 실행의 generation_id: gen-20260920T033856-6e8d98fb
production archive는 전혀 바뀌지 않았습니다. 사람이 검토/승인한 뒤 scripts/promote_media_generation.py로 명시적으로 승격하세요.
```

`--as-generation` 플래그(6-06에서 추가)를 사용했으므로 `archive_generation_report()`가
호출되며, **`data/tak_media_archive.json`(production archive)은 이 명령
어디에서도 열리지 않았다** — 8장에서 실제로 재확인했다. LLM 호출은 이 1회
실행뿐이며, 재시도/반복 호출을 하지 않았다.

## 8. generation_id

이번 실행으로 만들어진 9건 전체가 같은 `generation_id`를 공유하는지 확인했다.

| platform | content_id | generation_id | generation_status | review_status |
|---|---|---|---|---|
| blog | content-80a05485e895abf4 | gen-20260920T033856-6e8d98fb | valid | unreviewed |
| shorts | content-ec0c38b9a20c424c | gen-20260920T033856-6e8d98fb | valid | unreviewed |
| shorts | content-e3b8d986ea6db98e | gen-20260920T033856-6e8d98fb | valid | unreviewed |
| shorts | content-91869ed8be17f3f3 | gen-20260920T033856-6e8d98fb | valid | unreviewed |
| threads | content-5e9c2842373b859b | gen-20260920T033856-6e8d98fb | valid | unreviewed |
| threads | content-62450803823399d3 | gen-20260920T033856-6e8d98fb | valid | unreviewed |
| threads | content-696790d5bda07e90 | gen-20260920T033856-6e8d98fb | valid | unreviewed |
| threads | content-c04f9f6efc86969e | gen-20260920T033856-6e8d98fb | valid | unreviewed |
| threads | content-8dc32a88a18c0ede | gen-20260920T033856-6e8d98fb | valid | unreviewed |

- 9건 전부 `knowledge_id = knowledge-scout-6d1d0e2fa762`, `generation_id =
  gen-20260920T033856-6e8d98fb` 단일값을 공유함을 확인했다.
- 이 `generation_id`는 6-05/6-06에서 만든 첫 번째 KNOWLEDGE의 어떤
  `generation_id`와도 다르다(타임스탬프+임의 해시 구조상 당연히 다르지만,
  실제로 `gen-20260920T033856-6e8d98fb`가 기존에 저장된 어떤 파일에도
  존재하지 않음을 `grep`으로 확인했다).

## 9. 생성 결과 9건

전체 `rewritten_title`/`rewritten_body`를 읽었다(보안상 민감한 내용 없음 —
전문 게재).

**Blog** (`content-80a05485e895abf4`):
> 제목: AI 의식 가능성을 다룰 때 필요한 기준
>
> Mustafa Suleyman은 경쟁 AI 기업 Anthropic이 Claude에게 자신이 '의식이 있을
> 수 있다'고 사실상 가르치고 있다고 믿는다고 말합니다.
>
> 이 주장에 대한 내 생각은 투명한 연구와 감독 아래 제한적으로 허용하되,
> 사회적 논의를 이어가야 한다는 것입니다.
>
> AI의 의식 가능성을 연구할 때는 연구 범위와 실험 대상을 명확히 정하고,
> 독립적인 검토를 받아야 한다고 봅니다. 또한 AI 의식 연구는 검증 가능한
> 피해가 발생할 때만 중단해야 한다고 생각합니다.
>
> 출처: https://www.bbc.co.uk/news/articles/c6n07ypqz8kzo?at_medium=RSS&at_campaign=rss

**Shorts 3건** — 모두 "AI 의식 연구, 어디까지 허용할까(해야 할까)?"류 제목,
Mustafa Suleyman/Anthropic/Claude 사실과 Q1 답변("투명한 연구와 감독 아래
제한적으로 허용")을 각기 다른 순서/표현으로 재구성.

**Threads 5건** — 전부 같은 핵심 사실+의견을 담되 문장 구성만 다름(예:
"AI 의식 연구, 어디까지 허용해야 할까"/"허용할까").

(전체 9건의 원문은 `data/tak_media_generation_6-07_knowledge-scout-6d1d0e2fa762.json`에
그대로 보존돼 있다 — 이 파일은 21장에서 설명하는 이유로 git에는 커밋하지
않았지만 로컬에는 그대로 남아 있다.)

## 10. VALID / REJECTED / ERROR 결과

```
Blog:    1/1 valid
Shorts:  3/3 valid
Threads: 5/5 valid
------------------------
전체:    9 valid, 0 rejected, 0 error
```

6-05에서 관찰된 threads 2건 rejected(다음 14장 참고)는 이번 실행에서는
**재현되지 않았다** — 9건 전부 valid다. rejected가 0건이므로 "rejected를
임의로 valid로 바꿨는가"를 걱정할 필요가 없다(실제로 그런 조작은 전혀
하지 않았다 — `run_media_batch.py` 실행 결과를 그대로 저장했을 뿐이다).

## 11. 금융 템플릿 오염 검사

다음 문구를 9건 전체(제목+본문)에서 검색했다 — **전부 0건 검출**.

- "재무 판단에서 함께 볼 기준"
- "재무 판단의 출발점"
- "금융기관의 공식 심사 기준"
- "심사 기준"
- "대출 판단"
- "투자 판단"

"금융"이라는 단어 자체도 9건 전체에서 **0회** 등장했다(단순 검색으로 확인 —
`.count('금융') == 0`). 즉 이번에는 "오염되진 않았지만 방어 문구가 남아 있는"
6-05의 blog 사례(면책 문구)조차 없이, 애초에 금융 관련 언급이 전혀 생성되지
않았다.

## 12. source relevance 검사

9건 모두 다음 핵심 주제를 벗어나지 않았다.

- Mustafa Suleyman의 발언(경쟁사 Anthropic이 Claude에게 "의식이 있을 수
  있다"고 가르친다고 믿음) — 9건 전체에 등장.
- 사용자 의견(Q1 답변: "투명한 연구와 감독 아래 제한적으로 허용하며 사회적
  논의를 이어가야 한다") — 9건 전체에 등장.
- 일부 항목은 Q2/Q3 답변(연구 범위·실험 대상 명확화, 독립적 검토, 검증 가능한
  피해 시에만 중단)까지 포함해 원문 KNOWLEDGE의 여러 evidence 단위를 자연스럽게
  엮었다.

source title의 "silicon species"라는 표현 자체는 9건 어디에도 등장하지
않는다 — 이는 이번 재생성의 결함이 아니라, 애초에 `evidence`/`lesson` 필드에
그 문구가 캡처되지 않았기 때문이다(KNOWLEDGE 추출 단계의 특성이며, 이번
작업(article_type만 수정) 범위 밖이다). 마찬가지로 "Microsoft"라는 이름도
evidence에 없어(evidence는 "Mustafa Suleyman... Anthropic... Claude"만 언급)
9건 어디에도 등장하지 않았다 — LLM이 source title만 보고 "Microsoft가
경고했다"는 사실을 임의로 덧붙이지 않았다는 뜻이며, 오히려 evidence 범위를
엄격히 지킨 바람직한 결과다.

## 13. 사실성 검사

- **evidence에 없는 구체적 사실/수치/사건 추가**: 없음. 9건 모두 evidence의
  두 구성요소(SOURCE FACT: Mustafa Suleyman의 발언, USER ORIGINAL THOUGHT:
  Q1~Q3 문답)만 재표현했다.
- **"Microsoft"라는 새 인물/기관명 추가 여부**: 9건 전체를 문자열 검색했고
  **0건** — 추가되지 않았다.
- **사용자 의견 확대 여부**: `reusable_principle`(Q1~Q3 문답)의 "제한적으로
  허용", "연구 범위와 실험 대상을 명확히", "검증 가능한 피해가 발생할 때만
  중단" 등의 표현이 원래 의미보다 강하게/약하게 바뀌지 않고 그대로 재표현됨을
  확인했다.
- **source URL**: 9건 전체가 정확히 같은 URL
  `https://www.bbc.co.uk/news/articles/c6n07ypqz8kzo?at_medium=RSS&at_campaign=rss`을
  유지했다(`set(...)`으로 확인 — 원소 1개).

## 14. RewriteValidator 결과

6-05에서 관찰된 "경험" 오탐(threads 2건 rejected)이 이번에도 재현되는지
확인했다 — **재현되지 않았다**. 9건의 `rewritten_body`를 전부 검색한 결과
`"경험"`이라는 문자열이 **단 한 번도 등장하지 않았다**. 즉 `content_engine/rewrite.py`의
`_FACT_RISK_TERMS`(51~57행, "경험", "성과", "수익" 등)에 걸리는 단어가 이번
LLM 출력에는 우연히 하나도 나오지 않았다 — 6-06 보고서에서 분석한 대로
이 오탐은 **LLM이 그 특정 단어를 실제로 사용하는지에 좌우되는, 결정적이지
않은(non-deterministic) 현상**임을 다시 확인한 것이다. 이번 작업에서도
`RewriteValidator` 자체는 전혀 수정하지 않았다 — 관찰만 기록한다.

## 15. 기존 production archive 보호 검증

`data/tak_media_archive.json`을 LLM 실행 전/후로 비교했다.

```
$ sha256sum data/tak_media_archive.json   # 실행 후
823ba83930116cb3bf0cf9d46bd3876c7a833c58f5871a380a5de0cad3dd1662  data/tak_media_archive.json

$ stat -c '%y' data/tak_media_archive.json
2026-09-20 01:27:08 +0000   # 이번 세션의 LLM 실행 시각(03:38:56)보다 훨씬 이전
```

파일의 최종 수정 시각이 이번 세션에서 LLM을 실행한 시각보다 약 2시간 이상
앞선다 — **이번 세션 동안 이 파일에 쓰기가 전혀 발생하지 않았다는 것을
파일시스템 타임스탬프로 확인**했다(이 파일은 git으로 추적되지 않는 파일이라
`git diff`로는 비교할 수 없어, 해시 + mtime + 레코드 내용 비교를 함께 썼다).

레코드 수/내용도 6-05 보고서가 기록한 값과 정확히 일치했다.

```python
records = load_archive('data/tak_media_archive.json')
len(records) == 9   # True
{r.content_id for r in records} == {6-05가 기록한 9개 content_id}   # True
```

`tests/test_second_knowledge_correction_and_generation_pool.py::RealGenerationPoolResultTests::test_production_archive_still_has_only_the_original_nine_records`로
이 9개 content_id 집합 전체를 정확히 하드코딩해 회귀 테스트로 고정했다 —
production archive가 미래에 조용히 바뀌면 이 테스트가 실패한다.

**두 hash를 직접 비교하는 절차(작업 전 hash 기록 → 작업 후 hash 비교)는
이번 세션에서 "작업 전" 시점에 사전 계산해 두지 못했다** — 이는 절차상의
누락이며, 대신 위의 mtime 증거 + 정확한 레코드 집합 일치로 동등한 수준의
확인을 했다. 두 값이 일치하지 않았다면(레코드 수/내용이 달랐다면) 이 시점에서
작업을 중단하고 blocker로 기록했을 것이나, **실제로는 완전히 일치했다.**

## 16. content_id 충돌 검증

새 generation 9개의 content_id와 production archive 9개의 content_id를
비교했다.

```
production content_ids ∩ generation pool content_ids = 공집합(0개)
```

이번 대상 KNOWLEDGE(`knowledge-scout-6d1d0e2fa762`)는 애초에 production
archive에 어떤 MEDIA도 가진 적이 없었으므로(6-05 보고서 16장에서 이미 확인),
content_id가 겹칠 이유가 없다 — 6-06이 실제로 검증하려던 "같은 KNOWLEDGE를
재생성했을 때 content_id가 우연히 겹치는" 시나리오는 **이번 6-07 대상에는
해당하지 않는다**(그 시나리오는 6-05/6-06에서 첫 번째 KNOWLEDGE로 이미
실증했다). 이번 6-07이 실제로 검증한 것은 "**서로 다른 KNOWLEDGE의 generation
pool이 서로를 침범하지 않고, production archive도 침범하지 않는다**"는
더 기초적이지만 여전히 중요한 성질이다.

## 17. generation Dashboard / 조회 화면

`scripts/run_scout_dashboard.py`에 읽기 전용 라우트 2개를 추가했다(대규모
UI 개편 없음).

- `GET /media/generations` — `config.generation_archive_paths`에 설정된
  모든 generation pool 파일을 읽어 content_id별로 묶어 보여준다(같은
  content_id의 여러 generation을 나란히 비교할 수 있음, `created_at` 오름차순).
- `GET /media/generations/<knowledge_id>` — 위 화면을 특정 knowledge_id로
  필터링한 버전.
- `DashboardConfig`에 `generation_archive_paths: tuple[Path, ...] = ()`
  필드를 추가하고, CLI에 `--generation-archive`(여러 번 지정 가능, `append`)
  인자를 추가했다. 기본값이 빈 튜플이라 이 인자를 주지 않는 기존 실행
  (테스트 포함)은 완전히 그대로 동작한다.
- 이 화면은 **승인/보류/수정 폼도, promotion 버튼도 전혀 없다** — HTML에
  `<form` 태그가 하나도 없음을 테스트로 고정했다
  (`test_generations_page_has_no_action_forms`). 즉 "본다"만 가능하다.

실제로 이번에 만든 generation pool 파일을 붙여 로컬 서버(포트 8092)에서
GET 요청만으로 확인했다(POST 없음):

```
$ curl -s -o generations.html http://127.0.0.1:8092/media/generations -w "HTTP %{http_code}\n"
HTTP 200
$ curl -s -o generations_filtered.html "http://127.0.0.1:8092/media/generations/knowledge-scout-6d1d0e2fa762" -w "HTTP %{http_code}\n"
HTTP 200
$ curl -s -o /dev/null http://127.0.0.1:8092/media -w "media page HTTP %{http_code}\n"
media page HTTP 200   # 기존 /media도 여전히 정상 동작
```

렌더링 결과에서 9개 content_id, 1개 generation_id(`gen-20260920T033856-6e8d98fb`),
KNOWLEDGE 그룹 헤더가 모두 정확히 나타남을 확인했다. 조회 후 generation pool
파일의 `review_status`를 다시 읽어 전부 `unreviewed`로 **바뀌지 않았음**을
확인했다(GET만 보냈으므로 당연하지만 명시적으로 재확인).

## 18. Human Review 상태

- 새로 생성된 9건: 전부 `review_status = "unreviewed"`.
- 이번 작업에서 승인/거절 버튼을 누르거나, `review_status`를 프로그램적으로
  바꾸는 코드를 실행한 적이 없다.
- 정정한 KNOWLEDGE(`knowledge-scout-6d1d0e2fa762`) 자체의 `knowledge_review_status`도
  건드리지 않았다 — 여전히 6-05 이전부터 있던 `approved` 상태 그대로다(이
  승인은 KNOWLEDGE 승인이지 MEDIA 승인이 아니다 - 별개 개념).

## 19. Promotion 미실행 확인

`scripts/promote_media_generation.py`는 이번 세션에서 **한 번도 실행하지
않았다**(dry-run조차 실행하지 않았다 — 이번 작업 범위는 generation까지이며
promotion 검증은 6-06에서 이미 끝냈다). production archive는 15장에서 확인한
대로 이번 세션 동안 완전히 그대로다.

최종 상태(27장이 요구한 그대로):

```
Generation Pool: knowledge-scout-6d1d0e2fa762의 새 generation 9건 존재 (unreviewed)
Production:      기존 9건(knowledge-scout-b28b782b2a33 관련) 그대로, 변경 없음
```

## 20. 테스트

신규 파일 **`tests/test_second_knowledge_correction_and_generation_pool.py`**
(18개 테스트, 4개 클래스). 실제 LLM은 이 테스트 파일 안에서 호출하지 않는다
(`MockRewriteProvider`만 사용, 실제 LLM 결과 파일은 읽기만 함).

- `SecondKnowledgeCorrectionTests` (5): article_type 정정 확인, 다른 필드
  불변 확인, finance 템플릿 미적용, `is_review_required()` 여전히 True,
  mock 생성 9건 확인.
- `RealGenerationPoolResultTests` (7, `@unittest.skipUnless(파일 존재)`):
  이번 세션의 실제 LLM 결과 파일을 대상으로 — 9건·같은 generation_id·전부
  unreviewed·generation_status 값 보존·금융 템플릿 미검출·source_url 일치·
  production archive와 content_id 무충돌 + production archive가 정확히
  6-05가 기록한 9개 content_id만 가짐(하드코딩 비교).
- `GenerationPoolDashboardRouteTests` (5): `/media/generations`가 여러 pool
  파일을 합쳐 보여줌, 액션 폼 없음(읽기 전용), knowledge_id 필터링, pool 미설정
  시 빈 상태 표시, 기존 `/media` 라우트 회귀 확인.
- `test_generation_status_values_are_faithfully_stored`가 "rejected를 valid로
  임의로 바꾸지 않는다"에 해당하는 항목인데, 이번 실제 실행 결과가 0건
  rejected였으므로 이 테스트는 "저장된 값이 valid/rejected/error 중 하나로
  정확히 보존된다"는 형태로 작성했다 — 6-06의 `PromotionGatingTests`가 이미
  "rejected는 promotion 불가"를 별도로 강하게 검증하므로 중복하지 않았다.

6-06의 `tests/test_media_versioning_and_promotion.py`와 중복되는 내용(일반적인
generation_id 유일성, dry-run 동작, legacy 호환성 등)은 새로 만들지 않았다.

전체 신규 테스트 실행:

```
18 passed in 2.71s
```

## 21. 보안 검증

- API key, refresh token, access token, secret 값을 로그/보고서 어디에도
  기록하지 않았다. 환경변수 이름만 확인했고 값은 절대 출력하지 않았다.
- generation pool 파일(`data/tak_media_generation_6-07_knowledge-scout-6d1d0e2fa762.json`)과
  스냅샷 파일(`data/tak_media_batch_6-07_knowledge-scout-6d1d0e2fa762_snapshot.json`)은
  `.gitignore:6`의 `data/*.json` 규칙에 걸린다(6-05가 만든
  `data/tak_media_archive_6-05_..._regeneration.json`과 동일한 규칙,
  허용목록에 없음). 6-05 때와 동일한 판단을 내렸다: 이 파일들은 "1회성
  재현 가능한 생성 결과"이지 코드가 의존하는 source of truth가 아니므로
  (Dashboard는 `--generation-archive` 인자로 경로를 넘겨야만 읽으며, 기본값이
  없다 — 17장), 기존 저장소 관례(`data/tak_media_batch_36_v1.json` 등 과거
  batch 산출물들도 전부 gitignore됨)를 그대로 따라 강제 추가하지 않았다.
  `.gitignore` 자체는 수정하지 않았다(다른 세션이 이미 미커밋 상태로 수정
  중인 파일이라 손대지 않음).
- 커밋 대상 파일(`data/tak_brain_knowledge.json`의 부분 diff,
  `scripts/run_scout_dashboard.py`, 신규 테스트, 이 보고서)에 시크릿이
  없음을 `git diff --cached`로 직접 확인했다.

## 22. Commit

`git status --short`(스테이징 직전)로 이번 작업이 만든 변경만 정확히
골라 스테이징했다. `content_engine/__init__.py`는 이번 세션에서 전혀
수정하지 않았으므로(6-06까지 커밋된 상태 그대로, 다른 세션의 80줄
미커밋 diff만 남아 있음을 `git diff --stat`으로 재확인) 이번에는 부분
staging이 필요 없었다.

```
git update-index --cacheinfo 100644,<blob>,data/tak_brain_knowledge.json   # HEAD(11) + 정정된 1건만
git add scripts/run_scout_dashboard.py
git add tests/test_second_knowledge_correction_and_generation_pool.py
git add docs/6-07_second_knowledge_regeneration.md
```

최종 staged diff:

```
data/tak_brain_knowledge.json                                          |  38 +++
scripts/run_scout_dashboard.py                                         | 146 +++++++++
tests/test_second_knowledge_correction_and_generation_pool.py          | 327 +++++++++++++++++++++
(+docs/6-07_....md)
3 files changed, 511 insertions(+)  (+ 보고서)
```

`git add .`/`git add -A`는 사용하지 않았다. `data/tak_media_archive.json`은
staging하지 않았다(읽기만 함, 15장). `.gitignore`, `content_engine/__init__.py`,
`content_engine/generator.py`, `content_engine/llm_provider.py`,
`content_engine/rewrite.py`, `tests/test_content_engine.py`,
`tests/test_media_batch.py`, 그리고 나머지 untracked 문서/스크립트도
이번 커밋에 포함하지 않았다.

커밋 결과:

```
[main 8acceca] fix: correct second scout knowledge and generate safe media revision
 4 files changed, 1120 insertions(+)
 create mode 100644 docs/6-07_second_knowledge_regeneration.md
 create mode 100644 tests/test_second_knowledge_correction_and_generation_pool.py
```

## 23. Push

```
$ git push
To https://github.com/sopptak/tak-auto
   08b5a1d..8acceca  main -> main

$ git fetch origin   # (출력 없음)
$ git log origin/main..HEAD --oneline   # (출력 없음 — 비어 있음, origin과 완전히 동기화)
```

## 24. 최종 git status

```
$ git status --short
```

작업 시작 시점(1장)과 **정확히 동일한 파일 목록**을 그대로 출력했다 —
`.gitignore`, `content_engine/__init__.py`(다른 세션의 미커밋 export 추가분,
이번 세션 무관), `content_engine/generator.py`, `content_engine/llm_provider.py`,
`content_engine/rewrite.py`, `tests/test_content_engine.py`,
`tests/test_media_batch.py`, `data/tak_media_archive.json`(untracked), 그리고
동일한 목록의 untracked 문서/스크립트. `data/tak_brain_knowledge.json`도 여전히
`M`으로 표시되지만, 그 diff는 이번 커밋에 반영되지 않은 나머지 16개 레코드
(다른 세션의 미커밋 작업)만 남아 있다(6장에서 확인한 대로) — 이번 세션이
정정한 `knowledge-scout-6d1d0e2fa762` 1건은 커밋에 포함돼 인덱스/HEAD 양쪽에
반영됐다. 즉 **이번 작업이 만든 변경(4개 파일 커밋)만 깨끗이 빠지고, 세션
시작 전부터 있던 기존 미커밋 변경은 단 한 글자도 건드리지 않은 채 그대로
남아 있음**을 확인했다.

## 25. 남은 문제

1. **15장에서 지적한 대로, "작업 전 hash"를 사전에 기록해 두지 않았다** —
   production archive의 mtime과 레코드 내용 일치로 동등하게 확인했지만,
   다음에는 실행 순서를 `해시 기록 → LLM 실행 → 해시 재확인`으로 명확히
   지키는 것이 더 엄밀하다.
2. **generation pool 파일이 여전히 knowledge별 개별 파일**이다(6-06의
   "남은 문제"에서 이미 지적한 한계) — `/media/generations`가 여러 파일을
   받도록 만들었지만(`--generation-archive` 반복 지정), 실제로 사람이 매번
   dashboard 실행 시 어떤 파일들을 넘겨야 하는지 기억해야 한다. 파일들을
   자동으로 찾아 합치는 방식(예: `data/tak_media_generation_*.json` glob)은
   이번에 의도적으로 만들지 않았다(관례를 임의로 바꾸지 않기 위해).
3. **`knowledge-scout-6d1d0e2fa762`의 `category`/`domain`은 여전히 "금융"**이다
   — 6-05/6-06과 동일한 이유로 이번 작업 범위 밖(article_type 외 필드는
   수정하지 않는다는 원칙).
4. **RewriteValidator의 "경험" 오탐 이슈(6-05/6-06)는 여전히 미수정**이다 —
   이번 실행에서는 우연히 재현되지 않았을 뿐, 근본 원인은 그대로 남아 있다.
5. **generation pool → production 승격(promotion)은 이번 두 KNOWLEDGE 모두
   아직 실행되지 않았다** — 사람이 Dashboard(`/media/generations`)에서 9건을
   검토하고 `review_status`를 승인으로 바꾼 뒤, `scripts/promote_media_generation.py`로
   명시적으로 승격해야 한다(이번 작업 범위 밖).
6. **`data/tak_brain_knowledge.json`의 나머지 16개 신규 레코드가 여전히
   미커밋 상태**(6-05부터 이어짐, 이번 세션과 무관, 손대지 않음).

## 26. 다음 5~6시간 작업 제안

1. 사람이 `/media/generations`에서 이번 두 KNOWLEDGE의 generation 18건
   (9+9)을 실제로 검토 — 승인할 항목의 `review_status`를 approved로 바꾸는
   최소 기능(현재는 이 화면에 그 기능이 없다 - "본다"만 가능. 승인은 아직
   별도 도구/수동 JSON 편집이 필요하다는 뜻이므로, 다음 작업에서 이 화면에
   "generation pool 전용 승인" 액션을 추가할지, 아니면 production archive의
   승인 흐름과 통합할지 설계 결정이 필요하다).
2. 승인된 generation에 대해 `scripts/promote_media_generation.py --execute`로
   실제 promotion을 처음 실행 — 이번 작업까지 dry-run/구조 검증만 마쳤다.
3. `/media/generations`가 어떤 pool 파일을 봐야 하는지 자동으로 찾는 방법
   검토(예: `data/` 밑 명명 규칙을 정하고 glob) — 매번 CLI 인자로 정확한
   파일명을 알아야 하는 현재의 수동적 한계를 줄인다.
4. RewriteValidator의 `_FACT_RISK_TERMS` 세분화(6-06 20장에서 이미 제안) —
   이번에도 재확인했듯 이 문제는 LLM 출력의 우연성에 좌우되므로, 여러 번
   실행했을 때의 재현율을 관찰해 우선순위를 정한다.
5. 두 KNOWLEDGE 모두의 최종 승격이 끝난 뒤, 6-05가 지적한 기존 오염된 9건
   (blog `content-5971ed5204437cdd` 등)을 어떻게 처리할지(보존 vs dismissed
   처리 후 새 버전으로 대체) 사람이 정책을 결정.

## 27. 가장 중요한 최종 상태 확인

```
KNOWLEDGE (knowledge-scout-6d1d0e2fa762)
  ↓ article_type: "finance" → null (정정 완료)
실제 LLM (1회 실행, gen-20260920T033856-6e8d98fb)
  ↓
Generation Pool (data/tak_media_generation_6-07_knowledge-scout-6d1d0e2fa762.json)
  9건, 전부 generation_status=valid, review_status=unreviewed
  ↓
사람이 /media/generations에서 검수 가능 (읽기 전용 화면, 승인/promotion 버튼 없음)
  ↓
아직 promotion 안 함
```

Production archive(`data/tak_media_archive.json`)는 이번 작업 시작 전과
완전히 동일하다(9건, 전부 `knowledge-scout-b28b782b2a33` 관련, generation_id
없는 legacy 레코드) — 15장·19장에서 확인했다.
