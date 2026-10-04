# 6-79 AI Marketing Intelligence Layer

> TAK AUTO는 콘텐츠를 많이 만드는 시스템이 아니라, 사람의 행동을 만들어내는 콘텐츠 시스템을 구축한다.

코드: `content_engine/marketing/`, CLI: `scripts/marketing_brief.py`, 테스트: `tests/test_marketing.py`.

## 흐름

```
Market Demand (content_engine/market_demand: MarketDemand, OpportunityScore)
  ↓
Opportunity (IdeaCandidate - 시장 수요 근거 없으면 브리프 생성 거부)
  ↓
Research (research_tasks: idea.research_query + 8개 표준 aspect → ResearchProvider/Perplexity)
  ↓
Knowledge (research_bridge: 항상 pending + verification_required)
  ↓
Marketing Brief (MarketingBrief: 심리·스토리·판매·디자인·유통, 근거 evidence)
  ↓
Content (prompt.build_content_prompt: 8단계 사고 순서, approved 브리프만)
  ↓
Design / Media (design 요소, thumbnail/visual_hook 지시 - 기존 Shorts/미디어 단계가 사용)
  ↓
Distribution (platforms: blog/threads/shorts/youtube별 브리프)
  ↓
Performance (기존 content_engine/performance 스냅샷)
  ↓
Marketing Insight (insight: 성과를 attention/engagement/conversion으로 분리, 속성별 lift)
  ↓
Follow-up / Next Opportunity (followup.py, market_demand)
```

시장 수요 → 심리학 → 스토리텔링 → 판매 → 디자인 → 유통 → 콘텐츠 → 성과 → 피드백.

## 5개 관점 (MarketingBrief)
| 관점 | 요소 |
|---|---|
| psychology | attention, curiosity, pain, desire, trust, social_proof, loss_aversion, urgency, identification |
| storytelling | hook, problem, tension, insight, transformation, conclusion, call_to_action |
| sales | target_customer, customer_problem, value_proposition, benefit, objection, proof, offer, call_to_action, conversion_goal |
| design | visual_hook, readability, information_hierarchy, thumbnail_concept, visual_clarity, brand_consistency |
| distribution | target_platform, search_intent, discovery_keyword, audience, distribution_angle, repurpose_targets |

브리프 공통 필드: topic, target_audience, customer_problem, desired_action, evidence, confidence.
빈 요소는 "아직 모름"이다. 초안(`brief_from_idea`)은 지어내지 않고 근거와 확실한 값(카테고리 키워드)만 채우며
`missing_fields()`로 채울 목록을 보여 준다. LLM 없이도 저장/검증/점수화가 된다.

## MarketingScore
- 5개 관점 점수(`psychology_score`…`distribution_score`), `total_score`, `confidence`.
- **조회와 판매의 분리**: `attention_score`(조회), `engagement_score`(참여), `conversion_score`(전환)를 요소별
  가중치 표(`AXIS_WEIGHTS`)로 따로 계산한다. `profile`이 `attention_without_conversion`(조회형),
  `conversion_without_attention`(전환형), `balanced`, `weak`, `insufficient_data`를 구분한다.
- total은 단순 합이 아니라 관점 평균 60% + 가장 약한 축 40%다(플랫폼별 관점 가중치 적용).
- 결측은 0점이 아니라 제외되고 confidence를 낮춘다. 점수는 구조의 충실도/구체성만 본다 - 내용의 질은 사람이 검토한다.

## 리서치 (Perplexity)
표준 aspect 8개: market_demand, competitors, customer_problem, search_intent, recurring_questions,
pricing_signals, competitor_positioning, content_angles. 결과는 사실로 확정하지 않는다.
출처는 `EvidenceItem`(provider/aspect/url/snippet)으로 보존하고 KNOWLEDGE는 pending/verification_required다.
설정·인증 오류는 즉시 올리고, 일부 aspect의 요청 실패는 `bundle.errors`에 남긴다.

## 콘텐츠 생성 계약 (`prompt.py`)
문제 → 대상 → 관심 이유 → 첫 문장 → 이야기 → 증거 → 행동 → 유통, 8단계 질문과 제약(근거 없는 사실 금지,
검증 전 근거 표시, 과장 금지, 사람 검토 전 발행 금지)을 담은 dict/텍스트를 만든다.
게이트(`readiness_blockers`): approved, 시장 수요 근거, 대상/문제/행동, 점수·신뢰도 기준.

## 플랫폼별 전략 (`platforms.py`)
Blog = 검색 의도 + 문제 해결, Threads = 의견 + 반전 + 논쟁, Shorts = 강한 hook + 시각적 변화,
YouTube = 스토리 + 신뢰 + 깊이. 같은 소재에서 플랫폼별 브리프(`brief_id`, distribution_angle, 우선 요소)를 파생한다.
파생 브리프는 항상 draft로 초기화된다.

## 성과 피드백 (`insight.py`)
브리프에 `content_ids`를 연결(`link_content`)하면 최신 성과 스냅샷을 views/likes/replies/reposts/shares/clicks/leads/conversion 등에서
attention·engagement·conversion으로 나누고, 브리프에 쓰인 속성(`psychology.curiosity`, `platform.blog` …)과 발행 전 예측 점수를 함께 남긴다.
`attribute_lift`는 속성 유무에 따른 평균 지표 차이를 낸다. 표본(n)이 작으면 방향 참고용이며, 측정되지 않은 지표는 None이다.
현재 성과 데이터가 거의 없어(스냅샷 2건) 실제 학습은 데이터가 쌓인 뒤의 일이다. 이 연결이 향후 AI 학습의 기초 데이터다.

## 안전 원칙
- 모든 브리프/후보는 draft + `requires_human_review`로 시작하고 승인은 사람이 한다. 자동 발행 없음.
- 기존 KNOWLEDGE/followup/performance/publish 코드는 수정하지 않는다(읽기·재사용만).
- 기본 테스트는 외부 API를 호출하지 않는다. CLI는 `--write`가 있어야 저장하고 `--research`를 줄 때만 Provider를 호출한다.

## 사용
```
python scripts/market_demand.py --input demands.json --write
python scripts/marketing_brief.py draft IDEA_ID --research mock          # 미리보기
python scripts/marketing_brief.py --write draft IDEA_ID --research perplexity
python scripts/marketing_brief.py score BRIEF_ID
python scripts/marketing_brief.py --write platforms BRIEF_ID
python scripts/marketing_brief.py status BRIEF_ID approved               # 사람이 요소를 채운 뒤 승인
python scripts/marketing_brief.py prompt BRIEF_ID
python scripts/marketing_brief.py link BRIEF_ID CONTENT_ID
python scripts/marketing_brief.py insights
```
(`--write`, `--data-dir`는 하위 명령 앞에 둔다.) 브리프 요소는 현재 data/tak_marketing_briefs.json을 직접 편집해 채운다.

## 한계 / 다음 단계
- 요소를 채우는 LLM 단계 없음(다음: 리서치 evidence → 요소 초안 제안, 사람 승인).
- 승인된 브리프 → 기존 블로그/Threads/Shorts 생성 입력 연결, 브리프 편집 CLI.
- Perplexity 실호출은 키 확보 후 검증 필요.
