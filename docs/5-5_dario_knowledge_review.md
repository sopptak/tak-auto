# Dario KNOWLEDGE 최종 검토

검토 대상: `knowledge-scout-b28b782b2a33` (source_raw_id: `scout-0db222f63dd1`)
조회 방법: `python3 scripts/review_knowledge.py --show knowledge-scout-b28b782b2a33`
(코드 확인 결과 `--show`는 `scripts/review_knowledge.py:53,76-81`에 이미 구현되어
있어 그대로 사용함. 별도 코드 수정 없음.)

## 원본 SCOUT

`data/tak_scout_daily.json`의 `scout-0db222f63dd1` 원본 레코드:

- title: "Anthropic boss Dario Amodei calls for AI development to slow down"
- summary: "The call comes amid growing concerns that AI models may become able to inflict serious damage worldwide."
- source_url: `https://www.bbc.co.uk/news/articles/c14dpgm0rg4o?at_medium=RSS&at_campaign=rss`
- category: finance / source_name: BBC Business

## SOURCE FACT

KNOWLEDGE의 `lesson` / evidence 중 `SOURCE FACT`:

> "The call comes amid growing concerns that AI models may become able to inflict serious damage worldwide."

원본 `summary`와 **글자 그대로 동일**하다. 재작성이나 요약 왜곡 없음.

## SOURCE URL

KNOWLEDGE의 `source_url` / evidence 중 `SOURCE URL`:

> `https://www.bbc.co.uk/news/articles/c14dpgm0rg4o?at_medium=RSS&at_campaign=rss`

원본 `source_url`과 **완전히 일치**한다.

## USER ORIGINAL THOUGHT

KNOWLEDGE evidence 중:

> "USER ORIGINAL THOUGHT: 신기술은 두려워 말고 부딪혀서 느껴봐야 한다."

`data/tak_interview_answers.json`의 `scout-0db222f63dd1` 답변
(`selected_option: "D"`, `custom_answer: "신기술은 두려워 말고 부딪혀서 느껴봐야 한다."`)과
**정확히 일치**한다. 요청된 문장("신기술은 두려워 말고 부딪혀서 느껴봐야 한다.")과도
동일하다.

## reusable_principle / opinion

- `reusable_principle`: "신기술은 두려워 말고 부딪혀서 느껴봐야 한다."
- `opinion`: "신기술은 두려워 말고 부딪혀서 느껴봐야 한다."

두 필드 모두 사용자의 원문 문장을 그대로 담고 있으며, 요약·재해석·과장 등
왜곡이 없다.

## 검토 결과

| # | 기준 | 결과 |
|---|---|---|
| 1 | 제목이 원래 SCOUT 소재와 일치하는가 | 일치함 |
| 2 | SOURCE FACT가 실제 SCOUT 데이터에서 온 것인가 | 일치함 (summary 원문 그대로) |
| 3 | SOURCE URL이 정확히 보존되었는가 | 일치함 |
| 4 | USER ORIGINAL THOUGHT가 요청된 문장과 정확히 같은가 | 일치함 |
| 5 | reusable_principle/opinion이 사용자 의견을 왜곡하지 않았는가 | 왜곡 없음 |
| 6 | source와 user opinion이 섞여 사실처럼 저장되지 않았는가 | 분리됨 — `lesson`/`factual_information`은 원문 사실, `reusable_principle`/`opinion`은 사용자 의견으로 필드가 명확히 구분되고, evidence에도 `SOURCE FACT`와 `USER ORIGINAL THOUGHT` 라벨이 따로 붙어 있음 |
| 7 | TAK MEDIA(Blog/Shorts/Threads)용으로 구조가 충분한가 | title/domain/knowledge_type/lesson/reusable_principle/evidence/source_url을 모두 갖춤. 기존 승인된 KNOWLEDGE와 동일한 스키마(`tak_brain.models.KnowledgeRecord`)를 따름. 다만 `experience/problem/action/decision/result`는 모두 None — 이는 "의견" 유형 템플릿의 정상적인 형태이며, 이번 항목만의 결함은 아님 |
| 8 | finance/AI 관련 안전 문제 소지 | 발견되지 않음. 투자 권유·수익 보장·개인정보·내부정보 성격 없음(`privacy_risk: false`, `internal_information_risk: false`). "신기술을 두려워 말고 부딪혀 보라"는 일반적 태도 표명으로, 특정 종목/투자 조언이 아님 |
| 9 | 현재 상태가 pending인가 | `knowledge_review_status: pending` 확인됨 (approved/rejected 아님) |

참고로 `scripts/review_knowledge.py`의 자체 품질 평가는 `quality: A`,
`approval_recommendation: 승인`으로 표시되어 있다. 이는 도구의 자동 추천일 뿐이며,
이번 단계에서는 그 추천을 실행(approve)하지 않았다.

## 승인 가능 여부

내용상 승인 결격 사유는 발견되지 않았다. SOURCE FACT/SOURCE URL이 원본과
정확히 일치하고, USER ORIGINAL THOUGHT도 요청된 문장 그대로이며, 사실과 의견이
필드 단위로 명확히 분리되어 있다. **다만 이번 단계의 지시에 따라 실제 approve는
수행하지 않았으며, 승인 여부의 최종 결정은 사용자 몫으로 남겨둔다.**

## 발견된 문제

없음. (구조적 결함, 사실 왜곡, 안전 이슈 모두 발견되지 않음)

## 다음 단계

1. 이번 검토 결과에 동의하면, 별도 단계에서
   `python3 scripts/review_knowledge.py --id knowledge-scout-b28b782b2a33 --approve`로
   승인한다(이번 검토에서는 실행하지 않음).
2. 승인 이후에만 기존 TAK MEDIA 파이프라인(`run_media_batch.py`, `run_daily.py`
   등)으로 Blog/Shorts/Threads 콘텐츠 생성을 진행한다.
3. Threads 게시는 콘텐츠 생성·검수가 끝난 다음 별도 단계에서 결정한다.
