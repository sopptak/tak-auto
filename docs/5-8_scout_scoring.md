# 5-8 TAK SCOUT Scoring MVP

## 1. 목적

TAK SCOUT는 매일 최대 10건의 후보를 모아 오는데, 지금까지는 어떤 소재를 먼저
볼지 사람이 목록을 처음부터 끝까지 읽으며 판단해야 했다. 이번 단계의 목표는
**완벽한 추천 알고리즘이 아니라**, 수집된 후보를 몇 가지 단순한 기준으로
점수화해서 "오늘 먼저 볼 만한 소재"를 상위로 정렬해 보여주는 MVP를 만드는
것이다. LLM은 쓰지 않는다 — 제목/요약/category/발행시각처럼 이미 있는 필드만
보고, 미리 정한 키워드 목록으로 점수를 계산하는 완전히 설명 가능한
(rule-based, deterministic) 방식이다.

## 2. 현재 SCOUT 구조

코드를 작성하기 전에 `tak_scout` 전체를 읽고 확인했다.

- `tak_scout/models.py`: `ScoutCandidate` dataclass(scout_id, title, summary,
  source_url, published_at, source_name, category) + `to_dict`/`from_dict`.
  `from_dict`는 알 수 없는 키를 그냥 무시한다(중요 — 4번에서 이 특성을
  그대로 활용한다).
- `tak_scout/rss.py`: RSS 파싱. `published_at`은
  `email.utils.parsedate_to_datetime(...).isoformat()`로 만들어져
  `datetime.fromisoformat()`으로 그대로 다시 파싱할 수 있다.
- `tak_scout/collector.py`: `collect_all` → `dedupe_candidates`(URL/제목 기준
  중복 제거) → `select_candidates`(수집 순서를 유지한 채 상위 N개만 자름,
  `DEFAULT_MAX_CANDIDATES=10`) → `save_daily_pack_json`/`save_daily_pack_markdown`.
  `load_daily_pack`는 JSON을 읽어 다시 `ScoutCandidate` 목록으로 되돌린다.
- `data/scout_sources.json`: 현재 등록된 source는 **BBC Business
  (category="finance") 와 Hacker News (category="tech")** 2개뿐이며, 둘 다
  **영문 RSS**다. 이 사실이 3번 키워드 설계에 큰 영향을 줬다(아래 참고).
- `tak_brain/models.py`의 `CATEGORIES = ("금융", "대출", "경매", "부동산",
  ...)` 와 `tak_brain/article_types.py`의 `_RULES` 키워드 딕셔너리를 참고해
  "티몽 전문성"의 범위(금융/대출/경매/부동산)를 정했다.

**기존 기능과의 경계를 명확히 하기 위해 내린 설계 결정**: `scripts/run_scout.py`
와 그 출력(`data/tak_scout_daily.json`, `.md`)은 **전혀 수정하지 않았다.**
대신 이미 만들어진 `tak_scout_daily.json`을 읽기 전용으로 읽어 점수를 매기고
별도 파일에 저장하는 새 스크립트 `scripts/run_scout_score.py`를 추가했다.
이유:

1. `run_scout.py`를 바꿔 후보 순서를 점수순으로 재배열하면, "기존 JSON/MD
   결과 구조와 하위 호환성을 최대한 유지"라는 요구와 "python3
   scripts/run_scout.py가 계속 작동해야 한다"는 요구를 굳이 함께 시험할
   이유가 없었다. 완전히 손대지 않는 쪽이 가장 안전하다.
2. `ScoutCandidate.from_dict()`가 모르는 키를 무시하는 특성 덕분에, 점수
   필드가 붙은 새 JSON도 기존 `load_daily_pack()`으로 그대로 읽힌다(8번에서
   직접 확인). 즉 "score 관련 필드만 추가"라는 요구는 새 파일 쪽에서 이미
   충족된다.
3. `tak_scout`, `tak_brain`, `content_engine`의 기존 파일은 `tak_scout/__init__.py`
   에 새 export 4개(`ScoutScore`, `score_candidate`, `rank_candidates`,
   `top_candidates`)를 추가한 것 외에는 전혀 수정하지 않았다(`git diff`로
   확인 가능, 7번 참고).

**키워드를 설정 파일로 뺄지 여부**: `data/scout_sources.json`처럼 별도 JSON
으로 분리할지 검토했지만, (a) 키워드 개수가 dimension당 15~30개 수준으로
많지 않고, (b) 점수 계산 로직(가중치, 상한선, 카테고리 보너스)과 강하게
얽혀 있어 파일로 분리해도 결국 코드를 함께 봐야 하며, (c) 이 저장소의 다른
규칙 기반 로직들(`content_engine/rewrite.py`의 `_FACT_RISK_TERMS`,
`tak_brain/article_types.py`의 `_RULES`)도 전부 코드 상수로 되어 있어 같은
방식을 따르는 것이 일관성 있다고 판단했다. `tak_scout/scoring.py` 안에
`_INTEREST_KEYWORDS` 등으로 모듈 상수로만 두었다.

## 3. 점수 체계

총점 100점, 5개 항목:

| 항목 | 배점 | 판단 기준 |
|---|---|---|
| A. 콘텐츠 관심도 | 0~25 | 주목도 높은 표현(경고/충격/논란/crash/surge 등) + 제목·요약에 숫자 포함 여부 |
| B. 티몽 전문성과의 연관성 | 0~25 | 금융/대출/경매/부동산 실무 키워드(대출/금리/부동산/mortgage/rent 등) + category가 금융 계열이면 소폭 가산 |
| C. 의견을 만들기 좋은 정도 | 0~20 | 정책/발표/논쟁성 표현(발표/규제/논란/policy/bill/urges 등) |
| D. 수익화 관련성 | 0~15 | 경제/금융/부동산/AI 키워드(economy/finance/property/AI/ChatGPT/Anthropic 등) + category 가산 |
| E. 최신성 | 0~15 | 발행 후 경과 시간(6h 이내 15점 → 24h 12점 → 48h 8점 → 72h 4점 → 이후 0점) |

키워드는 **한국어와 영어를 함께** 등록했다. 2번에서 확인했듯 현재 실제 source
(BBC Business, Hacker News)는 전부 영문 RSS라서, 한국어 키워드만으로는 실제
데이터에서 거의 아무것도 걸리지 않는다는 것을 실제 실행으로 먼저 확인한 뒤
영문 키워드를 추가했다(6번 참고 — 첫 시도에서 "How to protect your laptop..."
같은 무관한 소재도 카테고리 보너스만으로 다른 소재와 큰 차이 없이 높게
나오는 문제를 발견해 바로잡았다).

키워드 매칭은 단어 경계(`\b`, 대소문자 무시)를 기준으로 한다. 단순 부분
문자열 검사(`in`)를 썼다면 "ai"가 "said"에, "rate"가 "corporate"에 우연히
걸리는 등 영문 키워드에서 오탐이 많이 발생했을 것이다.

## 4. 점수 계산 방식

`tak_scout/scoring.py`의 `score_candidate(candidate, reference_time=None)`가
순수 함수(같은 입력 → 같은 출력)로 5개 항목을 각각 계산해 합산한다.

- A(관심도) = `min(25, 5 + 5 × min(주목 키워드 히트 수, 4) + (숫자 포함 시 3))`
- B(전문성) = `min(25, (category가 금융 계열이면 +3) + 5 × min(전문 키워드 히트 수, 4))`
- C(의견 가능성) = `min(20, 4 + 4 × min(의견 유도 키워드 히트 수, 4))`
- D(수익화) = `min(15, (category가 금융 계열이면 +2) + 4 × min(수익화 키워드 히트 수, 3))`
- E(최신성) = 위 표의 시간 구간표 그대로

각 항목에 상한(min)을 둬서 키워드가 아무리 많이 겹쳐도 배점을 넘지 않게
했고, `total = sum(breakdown.values())`로 계산해 **breakdown 합계와 total이
항상 정확히 일치**한다(7번 테스트로 검증).

정렬(`rank_candidates`)은 점수 내림차순이며, 동점일 때는 ① 더 최근에
발행된 소재 우선 → ② 그래도 같으면 `scout_id` 오름차순으로 완전히
결정적이다. 입력 리스트의 순서를 뒤집어도 정렬 결과가 항상 같음을 테스트로
확인했다(7번).

## 5. 추천 이유

`recommendation_reason`은 **실제로 매칭된 키워드/신호만** 근거로 문장을
만든다. 예(실제 데이터, 6번 [1]번 결과):

> "금융/대출/경매/부동산/AI 등 관련 키워드(property, rent, tenants)가
> 포함되어 있음. 발행 후 약 6시간 경과로 최신 소재임."

매칭된 것이 하나도 없으면 없는 근거를 지어내지 않고 다음처럼 그대로
말한다(실제 데이터, 6번 [10]번 결과 — "최신성"만 해당돼 그 문장만 남음):

> "발행 후 약 6시간 경과로 최신 소재임."

아무 신호도 없으면(최신성도 낮으면) "금융/AI 관련 키워드나 의견을 유도하는
표현이 뚜렷하게 발견되지 않았습니다."라고만 말한다 — 근거 없이 좋게
포장하지 않는다.

## 6. TOP 10 실제 결과

오늘 실제 `data/tak_scout_daily.json`(10건, 전부 BBC Business/영문)을
**임시 디렉터리 복사본**으로 점수화했다(원본은 건드리지 않음, 8번 참고).
`python3 scripts/run_scout_score.py --daily-pack <복사본> ...` 실행 결과
상위 10건(전체 10건이라 사실상 전체 순위):

| 순위 | 점수 | 제목 | 핵심 근거 |
|---|---|---|---|
| 1 | 44 | Gloomy forecast for tenants as rent rises set to speed up | property/rent/tenants, 6시간 이내 |
| 2 | 42 | Amazon pauses work with cargo firm after fatal crash | crash/fatal, 3시간 이내 |
| 3 | 41 | Committee calls for bill to address AI threat to human rights | ai + bill/calls for, 2시간 이내 |
| 4 | 39 | Trump downplays warnings of AI risks, citing rivalry with China | ai + downplays, 11시간 이내 |
| 5 | 39 | AI staff 'genuinely frightened'... ex-Anthropic researcher tells BBC | ai/anthropic + frightened, 15시간 이내 |
| 6 | 39 | Anthropic boss Dario Amodei calls for AI development to slow down | ai/anthropic + calls for |
| 7 | 37 | Trump says he will remove all Irish whiskey tariffs... | tariff/tariffs, 10시간 이내 |
| 8 | 35 | 'Culture shift' needed in how UK does business, PM urges | business + urges, 8시간 이내 |
| 9 | 30 | Dramatic insider warnings over AI fall flat with some in Silicon Valley | ai, 20시간 이내 |
| 10 | 29 | How to protect your laptop, phone and bike from thieves at uni | (특별한 근거 없음, 최신성만) |

**가장 낮은 점수가 정확히 "How to protect your laptop, phone and bike from
thieves at uni"(생활 팁 소재)로 나왔다** — 사용자가 예로 든 "단순 생활 팁은
낮게 평가한다"는 기준이 실제 데이터에서도 그대로 확인됐다. 임대료/부동산
소재가 1위(티몽의 전문 분야와 직접 연관), AI 관련 소재들이 중상위권에
모여있는 것도 의도한 설계와 일치한다.

## 7. 테스트 결과

`tests/test_scout_scoring.py`에 6개 테스트를 추가했다:

1. `test_same_input_produces_same_score` — 같은 입력 → 완전히 같은
   total/breakdown/reason.
2. `test_finance_and_ai_candidate_gets_relevance_score` — 금융/AI 키워드가
   있는 소재는 전문성/수익화 점수가 기본값보다 뚜렷하게 높다.
3. `test_generic_lifestyle_candidate_scores_lower_than_finance_candidate` —
   생활 팁 소재가 금융 소재보다 총점이 낮고, 전문성/수익화 점수가 거의
   0에 가깝다.
4. `test_breakdown_sums_to_total` — 여러 소재에 대해 breakdown 합계 ==
   total.
5. `test_top_n_sorting_is_deterministic` — 입력 순서를 뒤집어도 정렬 결과가
   동일하고, 완전히 같은 소재(동점)는 `scout_id` 오름차순으로 정렬됨을
   확인.
6. `test_top_candidates_respects_n` — `top_candidates(n=5)`가 정확히 5건만
   반환.

```
$ python3 -m unittest tests.test_scout_scoring -v
Ran 6 tests in 0.015s
OK
```

기존 SCOUT 관련 테스트 전부(`test_scout_collector`, `test_scout_interview`,
`test_scout_answers`, `test_scout_knowledge_bridge`, `test_scout_pipeline_e2e`,
`test_scout_rss`) + 신규 `test_scout_scoring`을 함께 실행:

```
$ python3 -m unittest tests.test_scout_collector tests.test_scout_interview \
    tests.test_scout_answers tests.test_scout_knowledge_bridge \
    tests.test_scout_pipeline_e2e tests.test_scout_rss tests.test_scout_scoring -v
Ran 49 tests in 0.053s
OK
```

전체 테스트 스위트:

```
$ python3 -m unittest discover -s tests -p 'test*.py'
Ran 249 tests in 1.658s
OK
```

**249/249 전체 통과**(5-7 단계 243건 + 이번에 추가한 신규 6건). `git diff`로
확인한 결과 `tak_scout/__init__.py`(export 4개 추가) 외에 `tak_scout`,
`tak_brain`, `content_engine`, `scripts/run_scout.py`의 기존 파일은 전혀
수정되지 않았다.

## 8. 발견된 문제

1. **1차 구현 시 한국어 키워드만 넣었더니 실제 데이터에서 거의 무의미했다.**
   실제 source(BBC Business, Hacker News)가 전부 영문이라, "How to protect
   your laptop..." 같은 무관한 소재도 category 보너스만으로 다른 소재와
   점수 차이가 거의 없었다. 영문 키워드를 추가하고서야 3번/6번에 기록한
   대로 의미 있게 구분되기 시작했다 — **이 문제는 해결 후 보고서에 반영했고,
   지금 코드는 해결된 상태다.**
2. `category`가 "finance" 하나로 뭉뚱그려진 source(BBC Business)에서는,
   category만 보면 모든 기사가 "금융 관련"처럼 보인다. 그래서 이번 설계는
   category 가산점을 일부러 작게(전문성 +3, 수익화 +2) 유지하고 실제
   제목/요약의 키워드 매칭에 더 무게를 뒀다 — category만으로 점수가 크게
   갈리지 않도록 의도적으로 제한한 것이다.
3. source가 2개뿐이고 전부 영문이라, 현재 키워드 목록은 이 두 source
   기준으로 다듬어졌다. 한국어 RSS source가 새로 추가되면 한국어 키워드
   쪽의 실효성을 다시 확인해야 한다(코드에는 이미 있지만 실제 데이터로
   검증되지는 않았다).
4. "티몽 전문성"과 "수익화 관련성" 키워드가 일부 겹친다(금융, 부동산, 금리
   등). 의도적인 설계이며(둘 다 진짜 금융 소재면 함께 높아야 함이 자연스러움),
   완전히 독립적인 두 축은 아니다.

## 9. 다음 단계 (제안, 이번 단계에서는 실행하지 않음)

1. source가 늘어나면(특히 한국어 RSS) 키워드 목록을 실제 데이터로 다시
   검증하고 필요시 보강한다.
2. 카테고리 가산점 비중, 키워드별 가중치 등을 몇 주간의 실제 사용 데이터로
   재조정할지 검토한다(지금은 첫 설계값을 그대로 둠).
3. `scripts/run_scout_score.py`의 출력을 `scripts/run_interview.py
   --daily-pack data/tak_scout_daily_scored.json`처럼 바로 이어서 쓸 수
   있는지(현재도 `ScoutCandidate.from_dict` 호환이라 가능은 하지만, 인터뷰
   질문 번호를 점수 순서로 자동으로 매길지) TAK OPERATOR와의 연결 여부를
   사용자와 상의한다.
4. LLM 기반 점수 보정, 웹 UI, 자동 게시 등은 이번 단계의 범위 밖이며 요청이
   있을 때 별도로 진행한다.
