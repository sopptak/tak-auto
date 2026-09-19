# 실제 생성된 TAK MEDIA 결과 확인 (코드 수정/재생성 없음, 파일 읽기만)

## 조사 방법

코드를 실행하지 않고, `data/` 아래 실제로 저장된 미디어 배치 결과 파일들을
읽어서 blog / threads / shorts 각 1건씩 확인했다.

- `data/tak_media_batch_blog.json` — blog·threads·shorts가 함께 들어 있는
  가장 최근 완결 배치 (2026-09-16 07:08 생성)
- `data/tak_media_batch_dario_first_test.json` — "USER ORIGINAL THOUGHT"
  (실제 인터뷰 답변)가 반영된 지식으로 만든 배치 (2026-09-14 04:53 생성)
- `data/tak_brain_knowledge.json` — 각 콘텐츠의 원본 지식(knowledge) 레코드

## 중요한 발견: 두 종류의 "원래 생각"이 섞여 있었다

지식(knowledge) 레코드에는 두 가지 유형이 있었다.

1. **실제 인터뷰 답변이 반영된 것** — `evidence`에 `"USER ORIGINAL THOUGHT: ..."`
   가 들어 있고, `opinion` 필드가 채워져 있음.
2. **원문 기사 내용만 규칙 기반으로 요약한 것** — `opinion`이 `null`이고,
   `reusable_principle`/`lesson`이 원문 문장을 그대로 재구성한 것.

blog + threads + shorts 3종이 모두 성공적으로 만들어진 유일한 배치
(`tak_media_batch_blog.json`)는 **2번 유형**(인터뷰 미반영, 원문 요약)의
지식 하나(`knowledge-e1cc05264953`, "은행 대출 재무제표" 글)에서 나온 것이었다.

**1번 유형**(실제 인터뷰 답변 반영, 예: Dario Amodei 관련 지식
`knowledge-scout-b28b782b2a33`)은 threads 1건만 검증(validation)을 통과했고,
같은 지식으로 만든 blog 1건과 shorts 3건은 모두 "사실 범위를 넓히는 표현이
추가되었습니다" 사유로 반려(rejected)되어 파일에 존재하지 않는다.

즉, "인터뷰가 실제로 반영된 완결 3종 세트"는 지금 데이터에 없다. 아래는
실제 파일에 있는 것을 있는 그대로 정리한 것이다.

---

## 1. Blog (`data/tak_media_batch_blog.json`, knowledge-e1cc05264953)

**생성된 제목:** 대출 판단을 위한 재무 지표 확인하기

**본문 전체:**
> 대출 판단에서 매출만으로 충분한지 고민해 보았습니다.
>
> 매출 외에도 확인해야 할 재무 항목들이 존재하는데, 특히 영업이익, 당기순이익, 매출 증가 추이, 이익률 등이 중요합니다.
>
> 금융 판단에서는 이러한 다양한 재무 지표를 함께 확인하는 것이 필요하다는 원칙을 제시합니다.
>
> 이 글의 금융 관련 내용은 원문 작성자의 설명이며, 금융기관의 공식 심사 기준으로 해석하지 않습니다.

**원출처:** https://blog.naver.com/tmong2/224407146649

**인터뷰/원래 생각 반영 여부:** 반영 안 됨. 이 지식의 `opinion` 필드는 `null`이고,
`evidence`에도 `USER ORIGINAL THOUGHT`가 없다. 본문은 원문 기사(재무제표에서
확인할 항목 — 매출, 영업이익, 당기순이익, 매출 증가 추이, 이익률)의 내용을
규칙 기반 템플릿으로 재구성한 것이며, 사용자 개인 의견이 들어간 문장은 없다.
말미의 면책 문구("금융기관의 공식 심사 기준으로 해석하지 않습니다")는
금융 콘텐츠 안전장치로 고정 삽입되는 문장이다.

---

## 2. Threads

같은 지식 기준 threads도 있지만, "인터뷰가 반영된" 사례를 보여주기 위해
실제로 `USER ORIGINAL THOUGHT`가 담긴 쪽을 골랐다 (`data/tak_media_batch_dario_first_test.json`,
knowledge-scout-b28b782b2a33).

**생성된 제목:** AI의 위험성에 대한 고찰

**본문 전체:**
> AI 모델이 전 세계에 심각한 피해를 줄 수 있다는 우려가 커지는 가운데, "신기술은 두려워 말고 부딪혀서 느껴봐야 한다"는 생각이 듭니다. 우리가 새로운 기술을 마주할 때 두려움을 넘어서야 한다고 믿습니다. [출처](https://www.bbc.co.uk/news/articles/c14dpgm0rg4o?at_medium=RSS&at_campaign=rss)

**원출처:** BBC, "Anthropic boss Dario Amodei calls for AI development to slow down"

**인터뷰/원래 생각 반영 여부:** 반영됨. 이 지식의 `evidence`에
`"USER ORIGINAL THOUGHT: 신기술은 두려워 말고 부딪혀서 느껴봐야 한다."`가
그대로 들어 있고, `opinion` 필드에도 동일 문장이 저장돼 있다. 실제
threads 본문 문장 `"신기술은 두려워 말고 부딪혀서 느껴봐야 한다"`가 사용자의
인터뷰 답변 원문과 정확히 일치한다 — 원문 기사의 사실(AI가 심각한 피해를
줄 수 있다는 우려)과 사용자의 개인 의견이 한 문단 안에 결합된 구조다.

참고: 같은 지식으로 시도된 blog 1건, shorts 3건, threads 추가 3건은 모두
"사실 범위를 넓히는 표현이 추가되었습니다(경험/성과)" 사유로 반려되어
파일에 남아있지 않다.

---

## 3. Shorts (`data/tak_media_batch_blog.json`, knowledge-e1cc05264953)

**생성된 제목:** 대출 판단 시 재무제표에서 확인해야 할 항목

**본문 전체 (카드 스크립트 텍스트):**
> 나는 대출 결정을 할 때 매출만으로 충분한지 고민해봤다. 원문에서는 매출 외에도 확인해야 할 재무 항목으로 영업이익, 당기순이익, 매출 증가 추이, 이익률이 필요하다고 설명한다. 금융 판단에서는 원문에 제시된 여러 재무 지표를 함께 확인하는 것이 중요하다. finance_boundary_sentence_required_verbatim

**원출처:** https://blog.naver.com/tmong2/224407146649

**인터뷰/원래 생각 반영 여부:** 반영 안 됨 (blog와 동일한 지식, `opinion: null`).
본문 1인칭 문장("나는 대출 결정을 할 때...")은 원문 기사 내용을 1인칭 화법으로
바꿔 쓴 것일 뿐, 실제 사용자 인터뷰 답변에서 나온 문장이 아니다.

**⚠️ 파일에서 그대로 관찰된 이상 현상:** 본문 마지막에
`finance_boundary_sentence_required_verbatim`라는 문자열이 그대로 노출돼 있다.
이는 금융 콘텐츠 면책 문구가 들어가야 할 자리에 치환되지 않은 placeholder
텍스트로 보인다 (blog 항목에는 정상적인 면책 문장이 들어갔지만 이 shorts
항목에는 코드/변수명이 그대로 남았다). 요청대로 코드 수정이나 재생성은
하지 않았으므로, 파일에 저장된 원문 그대로 보고한다.

---

## 요약

| 구분 | 인터뷰 반영 | 비고 |
|---|---|---|
| Blog | ❌ 없음 | 원문 기사 요약, `opinion: null` |
| Threads | ✅ 있음 (다른 지식) | `USER ORIGINAL THOUGHT` 문장이 본문에 그대로 사용됨 |
| Shorts | ❌ 없음 | 원문 기사 요약 + placeholder 문자열 노출 버그 관찰됨 |

"인터뷰가 반영된 blog/threads/shorts 3종 세트"는 아직 실제로 존재하지
않는다 — 인터뷰 기반 지식은 검증 단계에서 threads 1건만 통과했고 blog/shorts는
모두 반려되었다. 오늘(2026-09-19) 새로 승인된 인터뷰 지식
(`knowledge-scout-6d1d0e2fa762`, AI "silicon species" 관련)은 아직 미디어
배치가 한 번도 생성되지 않은 상태다.
