# 6-78 Market Demand Research

시장 수요 데이터 → 기회 점수 → 사업 아이디어 후보를 TAK AUTO 내부 표준으로 만드는 계층.
특정 플랫폼에 종속되지 않는다. 코드: `content_engine/market_demand/`, CLI: `scripts/market_demand.py`.

## 범위
- 실제 크롤러/브라우저 자동화는 **없다**. Fello, Flippa, Empire Flippers, Acquire, SideProject, Fiverr의 공식 API
  존재 여부와 자동 수집의 약관 적합성을 확인하지 못했으므로, 해당 이름을 provider로 지정하면
  "수동 입력을 사용하라"는 오류를 낸다.
- 지원: `manual`(사람이 확인한 JSON/CSV, 모든 소스 공통 입구), `mock`(테스트/시연).
- 공식 API가 확인되면 `MarketDemandProvider`를 구현해 `register_provider()`로 추가한다. 하위 단계는 불변.

## 표준 모델
- `MarketDemand`: source, title, category, description, price(+currency), demand_signal(0~1), competition_signal(0~1, 높을수록 경쟁 치열), url, collected_at, metadata.
- `MarketDemandProvider`: `search_marketplace()`, `collect_demand()`, `normalize()`, `score_opportunity()`.
- `OpportunityScore`: 요소별 0~100 + 근거 + total + confidence.
  요소: transaction(실제 거래), price, recurring(반복 수요), competition(낮을수록 고득점), automation(AI 자동화 가능성), fit(TAK 적합성).
  모르는 요소는 0이 아니라 `None`이며 total에서 제외되고 confidence를 낮춘다.
  automation/fit은 키워드 규칙의 1차 필터이므로 최종 판단은 사람이 한다.
- `IdeaCandidate`: 카테고리별로 수요를 묶은 아이디어. 항상 `candidate`로 시작하고 accepted/rejected는 사람이 정한다.
  `research_query`는 `content_engine.providers`의 리서치 Provider로 검증할 질의다.

## 사용
```
python scripts/market_demand.py --input demands.json            # 미리보기
python scripts/market_demand.py --input demands.csv --write     # data/tak_market_demands.json, tak_idea_candidates.json에 append
python scripts/market_demand.py --set-status IDEA_ID accepted
```
입력 필드: source,title,category,description,price,currency,demand_signal,competition_signal,url,collected_at,
verified_transaction,recurring,monthly_revenue (CSV/JSON 동일).

## 한계/다음 단계
- 점수는 결정적 규칙이며 LLM 분석은 아직 없다(다음: 아이디어 `research_query`를 Perplexity provider로 검증 → KNOWLEDGE 연결).
- 수집 데이터 사용 시 각 출처의 이용 약관을 사람이 확인한다.
