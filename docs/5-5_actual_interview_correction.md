# 5-5 실제 운영 테스트 — 의도하지 않은 인터뷰 답변 진단

조사 시각(UTC): 2026-09-14 (진단만 수행, 데이터 변경 없음)

## 요약

`python3 scripts/run_interview.py --interactive`는 터미널에서 사람이 한 문항씩
답하는 CLI다. 이번 세션은 백그라운드 환경이라 실시간 터미널 입력을 그대로 전달할
수 없어, 어시스턴트가 채팅 질의응답으로 9개 미답변 문항을 전부 대신 물어보고 그
결과를 `data/tak_interview_answers.json`에 순서대로 기록했다. 원래 의도는 "Anthropic
boss Dario Amodei calls for AI development to slow down" 한 건만 답하는 것이었으나,
실제로는 10개 후보 전부에 답변이 생성되었고, 이어 `apply_interview.py` 실행으로
10건 모두 pending KNOWLEDGE로 변환되었다.

## 1. `data/tak_interview_answers.json` 현재 답변 수

**총 10건**

| # | scout_id | selected_option | answered_at (UTC) | 비고 |
|---|---|---|---|---|
| 1 | scout-4a25c9bcac4e | D | 2026-09-14T03:50:11 | 이번 세션 이전에 이미 존재하던 답변(사전 답변) |
| 2 | scout-66639b297fc0 | A | 2026-09-14T04:19:56 | 이번 세션에서 생성 |
| 3 | scout-ba66996771b4 | B | 2026-09-14T04:19:56 | 이번 세션에서 생성 |
| 4 | scout-87f2284ff52b | A | 2026-09-14T04:19:56 | 이번 세션에서 생성 |
| 5 | scout-e630ed0ba090 | A | 2026-09-14T04:19:56 | 이번 세션에서 생성 |
| 6 | scout-d4fca881c453 | A | 2026-09-14T04:22:30 | 이번 세션에서 생성 |
| 7 | scout-ba089403ed6d | A | 2026-09-14T04:22:30 | 이번 세션에서 생성 |
| 8 | scout-82de86b62e46 | A | 2026-09-14T04:22:30 | 이번 세션에서 생성 |
| 9 | scout-89f867fe002d | A | 2026-09-14T04:22:30 | 이번 세션에서 생성 |
| 10 | scout-0db222f63dd1 | C | 2026-09-14T04:22:48 | 이번 세션에서 생성 — **의도했던 소재이나 값이 다름** |

(모든 A/B/C 답변은 `custom_answer`가 비어 있음. scout-4a25c9bcac4e만 D + 커스텀
텍스트가 사전에 존재.)

## 2. 새로 생성된 pending KNOWLEDGE 수

`data/tak_brain_knowledge.json` 전체 20건 중 scout 연동 항목은 **10건**이며,
전부 `knowledge_review_status: "pending"`이다(승인/거절된 항목 없음). 기존 블로그
기반 KNOWLEDGE 10건(모두 `approved`)은 이번 작업과 무관하게 그대로 보존되어 있다.

| id | source_raw_id | review_status |
|---|---|---|
| knowledge-scout-e981e03d8737 | scout-66639b297fc0 | pending |
| knowledge-scout-a5e1a31ccbd6 | scout-4a25c9bcac4e | pending |
| knowledge-scout-624fd3789798 | scout-ba66996771b4 | pending |
| knowledge-scout-c8a717882561 | scout-87f2284ff52b | pending |
| knowledge-scout-d21393bd1af0 | scout-e630ed0ba090 | pending |
| knowledge-scout-70346e8dbd16 | scout-d4fca881c453 | pending |
| knowledge-scout-9ee1fb847bed | scout-ba089403ed6d | pending |
| knowledge-scout-da6d70cade1b | scout-82de86b62e46 | pending |
| knowledge-scout-26c322127579 | scout-89f867fe002d | pending |
| knowledge-scout-56f0f4f75183 | scout-0db222f63dd1 | pending |

→ **아직 승인된 항목은 없다.** TAK MEDIA/Threads 파이프라인은 `approved` 상태만
사용하므로, 현재까지는 콘텐츠 생성이나 게시로 이어지지 않았다.

## 3. 각 답변의 scout_id와 selected_option

(1번 표와 동일 — 위 표 참고)

- scout-4a25c9bcac4e → D (사전 존재)
- scout-66639b297fc0 → A
- scout-ba66996771b4 → B
- scout-87f2284ff52b → A
- scout-e630ed0ba090 → A
- scout-d4fca881c453 → A
- scout-ba089403ed6d → A
- scout-82de86b62e46 → A
- scout-89f867fe002d → A
- scout-0db222f63dd1 → C

## 4. 9번("Anthropic boss Dario Amodei calls for AI development to slow down") 소재

- scout_id: `scout-0db222f63dd1`
- `data/tak_interview_questions.md` 상 번호: **[10]** (전체 10개 후보 순서 기준.
  미답변 문항만 셀 경우에는 9번째 질문이 됨 — 사용자가 말한 "9번"과 일치)
- 현재 저장된 답변: `selected_option: "C"`, `custom_answer: ""`
  ("상황을 더 지켜봐야 한다")
- 이 답변으로 만들어진 KNOWLEDGE: `knowledge-scout-56f0f4f75183`
  (`reusable_principle: "상황을 더 지켜봐야 한다고 본다."`)
- **사용자가 실제로 의도한 답변**: A — "신기술은 두려워 말고 부딪혀서 느껴봐야 한다"
- → 저장된 값(C, 커스텀 텍스트 없음)과 사용자의 실제 의도(A + 위 문장)가 **일치하지
  않는다.**

## 5. 의도하지 않은 답변 목록 (9건)

원래 의도는 10개 후보 중 위 4번 항목(scout-0db222f63dd1) 하나만 답하는 것이었다.
이번 세션 중 어시스턴트가 채팅으로 대신 물어 기록한 나머지 9건은 전부 의도하지
않은 답변이다.

| scout_id | title | 기록된 답변 |
|---|---|---|
| scout-66639b297fc0 | Committee calls for bill to address AI threat to human rights | A |
| scout-ba66996771b4 | 'Culture shift' needed in how UK does business, PM urges | B |
| scout-87f2284ff52b | How to protect your laptop, phone and bike from thieves at uni | A |
| scout-e630ed0ba090 | Amazon pauses work with cargo firm after fatal crash | A |
| scout-d4fca881c453 | Trump downplays warnings of AI risks, citing rivalry with China | A |
| scout-ba089403ed6d | AI staff 'genuinely frightened' for humanity's future, ex-Anthropic researcher tells BBC | A |
| scout-82de86b62e46 | Dramatic insider warnings over AI fall flat with some in Silicon Valley | A |
| scout-89f867fe002d | Trump says he will remove all Irish whiskey tariffs as he ends two-day visit | A |
| scout-0db222f63dd1 | Anthropic boss Dario Amodei calls for AI development to slow down | C (의도한 소재이지만 값 자체도 틀림 — 사용자 의도는 A) |

참고: scout-4a25c9bcac4e(임대료 상승 관련, D)는 이번 세션 이전(03:50:11 UTC)에
이미 존재하던 답변이라 "이번에 새로 생성된 의도하지 않은 답변"에는 포함하지 않았다.
다만 원래 "10개 중 1개만" 의도였다는 기준으로 보면 이 항목도 함께 재검토 대상이 될
수 있다.

## 6. 안전하게 정리하는 방법 (실행하지 않음 — 제안만)

**현재 상태의 안전성**: pending KNOWLEDGE 10건 중 승인된 것이 없으므로, 아직
TAK MEDIA/Threads로 넘어간 콘텐츠는 없다. 즉 지금 정리해도 이미 발행된 결과물에
영향을 주지 않는다.

제안하는 순서(모두 사용자 승인 후 별도로 진행):

1. **백업 먼저**: 수정 전에 두 파일을 복사해 둔다.
   `cp data/tak_interview_answers.json data/tak_interview_answers.json.bak`
   `cp data/tak_brain_knowledge.json data/tak_brain_knowledge.json.bak`
2. **KNOWLEDGE 쪽 정리 — 기존 도구 사용(직접 편집 대신 권장)**:
   의도하지 않은 8건(scout-66639b297fc0, ba66996771b4, 87f2284ff52b,
   e630ed0ba090, d4fca881c453, ba089403ed6d, 82de86b62e46, 89f867fe002d)에 대해
   `python3 scripts/review_knowledge.py --id <knowledge-id> --reject`를 실행한다.
   삭제가 아니라 `rejected` 상태로 표시되므로 이력이 남고 되돌리기도 쉽다.
3. **9번(Dario) 항목 값 수정**:
   - KNOWLEDGE: `knowledge-scout-56f0f4f75183`도 우선 `--reject`로 표시한 뒤,
   - `data/tak_interview_answers.json`에서 scout-0db222f63dd1 항목을 실제 의도
     (선택지 + "신기술은 두려워 말고 부딪혀서 느껴봐야 한다")로 correction한다.
     A를 선택지로 유지하면서 직접 입력 문구를 남기고 싶다면, 이 프로젝트의 답변
     스키마(`tak_scout/answers.py`)는 커스텀 텍스트를 D 선택지에서만 허용하므로,
     "A로 유지 + 커스텀 텍스트 병기"가 필요하면 스키마 처리 방식을 사용자와 먼저
     확인하는 것이 좋다.
   - 이후 `python3 scripts/apply_interview.py`를 다시 실행하면 정정된 내용으로
     새 KNOWLEDGE가 pending 상태로 생성된다(중복 방지 로직이 있어 기존 값과
     다르면 새 id로 만들어짐).
4. **scout-4a25c9bcac4e(임대료 답변) 처리 여부 확인**: 이번 세션 이전에 생성된
   답변이라 원래 목적과는 무관할 수 있으나, "10개 중 1개만" 기준으로 재검토가
   필요하면 사용자에게 유지/삭제 여부를 먼저 확인한다.
5. 정리가 끝난 뒤에만 `scripts/review_knowledge.py --pending`으로 남은 목록을
   확인하고, 승인 여부는 그 다음 단계에서 별도로 결정한다.

이번 보고서 작성 과정에서는 위 어떤 단계도 실행하지 않았다: 데이터 삭제/수정,
코드 수정, git commit/push, KNOWLEDGE 승인, TAK MEDIA 실행, Threads 게시 전부
수행하지 않았다.
