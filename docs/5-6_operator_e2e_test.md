# 5-6 TAK AUTO 실제 E2E 테스트

이 문서는 두 가지 작업을 함께 기록한다: (1) 실제 데이터에 하드코딩되어 있던
기존 테스트 실패를 수정한 내역, (2) 그 이후 실제 SCOUT 데이터로 TAK OPERATOR
(`scripts/tak_auto.py`)의 전체 흐름을 실제 LLM(`--execute`)까지 포함해 1회
검증한 결과. **실제 Threads API 게시, Naver Blog 게시, GitHub Actions 실행은
전혀 수행하지 않았다.**

## 0. 기존 테스트 수정 (E2E 이전 선행 작업)

`tests/test_media_batch.py::test_cli_dry_run_saves_json_output`가
`scripts/run_media_batch.py`를 `--input` 없이(=기본값인 실제
`data/tak_brain_knowledge.json`) 실행해 `approved_knowledge_count == 4`를
기대하고 있었다. 지난 단계에서 Dario KNOWLEDGE를 승인해 실제 승인 건수가
5건이 되면서 이 하드코딩된 기대값과 어긋나 실패했다.

**수정 방식**: 이 테스트 하나만, 실제 데이터 대신 테스트 전용의 결정적인
fixture(`self.approved_records[0]`를 템플릿으로 id만 바꾼 approved
KnowledgeRecord 2건)를 임시 디렉터리에 만들어 `--input`으로 명시하도록
바꿨다. 검증 내용(CLI가 dry-run JSON을 올바른 구조로 저장하는지, summary
카운트가 실제 입력과 일치하는지, item 필드가 모두 있는지)은 그대로 유지했고,
기대값만 실제 데이터 의존 값(4/36)에서 fixture 기준 결정적 값(2/18)으로
바꿨다. `data/tak_brain_knowledge.json`은 **읽지도 수정하지도 않았다**
(다른 기존 테스트들은 원래 `self.approved_records[0]`처럼 인덱스 기반으로
접근하고 있어 실제 데이터 건수 변화에 이미 영향받지 않는 구조였고, 이번에
건드린 것은 정확히 개수를 하드코딩한 이 테스트 1건뿐이다).

TAK MEDIA 본체 코드(`content_engine/*`, `scripts/run_media_batch.py`)는
수정하지 않았다.

**수정 후 테스트 결과**:

```
$ python3 -m unittest tests.test_media_batch.MediaBatchPipelineTests.test_cli_dry_run_saves_json_output -v
test_cli_dry_run_saves_json_output ... ok
Ran 1 test in 0.185s
OK

$ python3 -m unittest discover -s tests -p 'test*.py'
Ran 240 tests in 1.603s
OK
```

**240개 테스트 전체 PASS.** 실제 `data/tak_brain_knowledge.json`은 이 수정
전후로 21건(승인 5 / 대기 7 / 거절 9)으로 변화 없음을 확인했다.

## 1. 테스트 목적

`scripts/tak_auto.py`(TAK OPERATOR MVP)가 **실제 SCOUT 데이터**로
SCOUT → 소재 선택 → INTERVIEW(USER ORIGINAL THOUGHT 입력) → KNOWLEDGE 생성 →
승인 → 실제 LLM(`--execute`) → TAK MEDIA(Blog 1 / Shorts 3 / Threads 5)까지
정말로 한 번에 끝까지 동작하는지 확인한다. 이전 단계(`docs/5-6_tak_operator_mvp.md`)
의 E2E 테스트/데모는 가짜 소재 또는 `MockRewriteProvider`(실제 LLM 미호출)를
썼으므로, 이번에는 실제 소재 + 실제 LLM 조합으로 한 번 더 검증한다.

## 2. 테스트 환경

- 실제 운영 데이터가 오염되지 않도록, 아래 3개 파일을 세션 임시 디렉터리로
  **복사**한 뒤 그 복사본만 대상으로 실행했다(`--daily-pack`/`--answers`/
  `--knowledge`로 명시).
  - `data/tak_scout_daily.json` (오늘 실제 SCOUT 소재 10건)
  - `data/tak_interview_answers.json` (기존 실제 답변 10건 포함 상태로 복사)
  - `data/tak_brain_knowledge.json` (기존 실제 KNOWLEDGE 21건 포함 상태로 복사)
- LLM: `TAK_MEDIA_LLM_ENDPOINT=https://api.openai.com/v1/chat/completions`,
  `TAK_MEDIA_LLM_MODEL=gpt-4o-mini`(이 실행에만 적용, 세션 종료 후 unset).
  `TAK_MEDIA_LLM_API_KEY`는 세션에 이미 설정되어 있던 값을 그대로 사용했고
  값 자체는 출력하지 않았다.
- 실행 명령: `python3 scripts/tak_auto.py --daily-pack ... --answers ...
  --knowledge ... --media-output ... --execute` (모두 임시 디렉터리 경로).

## 3. 테스트 입력

오늘 실제 SCOUT 소재 10건 중 **10번, "Anthropic boss Dario Amodei calls for
AI development to slow down"**(Dario 소재)를 선택했다. 이 소재는 이미 실제
운영 데이터에서 승인까지 끝난 KNOWLEDGE(`knowledge-scout-b28b782b2a33`)가
있는 소재지만, **이번 실행은 그 복사본 위에서만 이루어져 실제
`data/tak_brain_knowledge.json`을 전혀 건드리지 않는다.**

입력 순서: `10`(소재 선택) → `D`(직접 입력) →
`신기술은 두려워 말고 부딪혀서 느껴봐야 한다.`(USER ORIGINAL THOUGHT, 기존
실제 답변과 동일한 문장) → `Y`(승인).

## 4. 실제 실행 흐름

```
========================================
          TAK AUTO
========================================

오늘의 소재
 1. Committee calls for bill to address AI threat to human rights
 2. Gloomy forecast for tenants as rent rises set to speed up
 3. 'Culture shift' needed in how UK does business, PM urges
 4. How to protect your laptop, phone and bike from thieves at uni
 5. Amazon pauses work with cargo firm after fatal crash
 6. Trump downplays warnings of AI risks, citing rivalry with China
 7. AI staff 'genuinely frightened' for humanity's future, ex-Anthropic researcher tells BBC
 8. Dramatic insider warnings over AI fall flat with some in Silicon Valley
 9. Trump says he will remove all Irish whiskey tariffs as he ends two-day visit
10. Anthropic boss Dario Amodei calls for AI development to slow down

번호 선택: 10

선택한 소재:
제목: Anthropic boss Dario Amodei calls for AI development to slow down
출처: BBC Business (https://www.bbc.co.uk/news/articles/c14dpgm0rg4o?at_medium=RSS&at_campaign=rss)

질문: [Anthropic boss Dario Amodei calls for AI development to slow down] 이 경제 이슈에 대해 어떻게 생각하시나요?
A. 긍정적으로 본다 / B. 부정적으로 본다 / C. 더 지켜봐야 한다 / D. 직접 입력

선택 (A/B/C/D): D
직접 입력: 신기술은 두려워 말고 부딪혀서 느껴봐야 한다.
```

10개 소재 목록 표시 → 선택 → 질문/선택지 표시 → D 입력 순서가 정확히
기획대로 동작했다.

## 5. INTERVIEW 결과

```
TAK BRAIN: 신규 KNOWLEDGE 0건 생성 (미답변 건너뜀 0건, 중복 10건)
```

복사해온 답변 파일에 이미 10개 소재 전부의 답변이 있었기 때문에(실제 운영
데이터 스냅샷이므로), 방금 입력한 답변도 기존과 동일한 내용이라 "신규 0건 /
중복 10건"으로 정확히 집계됐다 — **결정적 id(scout_id + 선택지 + 직접입력
문장)로 중복을 올바르게 판단하는 기존 로직이 그대로 잘 작동함을 확인.**
USER ORIGINAL THOUGHT는 입력한 그대로 다음 단계로 전달됐다(6번 참고).

## 6. KNOWLEDGE 결과

```
KNOWLEDGE 생성 완료

id: knowledge-scout-b28b782b2a33
제목: Anthropic boss Dario Amodei calls for AI development to slow down
도메인: 금융

  SOURCE FACT: The call comes amid growing concerns that AI models may become able to inflict serious damage worldwide.
  SOURCE URL: https://www.bbc.co.uk/news/articles/c14dpgm0rg4o?at_medium=RSS&at_campaign=rss
  USER ORIGINAL THOUGHT: 신기술은 두려워 말고 부딪혀서 느껴봐야 한다.

현재 상태: approved

승인하시겠습니까? (Y=승인 / N=보류): Y

KNOWLEDGE 승인 완료: knowledge-scout-b28b782b2a33 -> approved
```

SOURCE FACT / SOURCE URL / USER ORIGINAL THOUGHT가 화면에 정확히 구분되어
표시됐고, Y 입력 후 `knowledge_review_status`가 `approved`로 바뀌었다(단,
이 변화는 **임시 디렉터리 복사본에만** 반영되었다 — 9번 참고).

## 7. TAK MEDIA 결과

```
TAK MEDIA 실행 중 (--execute: 실제 LLM 호출)...

결과:

Blog         rejected
Shorts 1     rejected
Shorts 2     valid
Shorts 3     valid
Threads 1    rejected
Threads 2    valid
Threads 3    rejected
Threads 4    valid
Threads 5    valid

총 9건 (valid 5, rejected 4, error 0)
```

목표했던 "1 KNOWLEDGE → Blog 1 / Shorts 3 / Threads 5 = 9 Draft" 구성이
정확히 생성됐고, 실제 LLM 재작성 + Validator 검증까지 끝까지 실행되어
valid 5 / rejected 4 / error 0으로 마무리됐다(error 0건 — 파이프라인이
중간에 죽지 않고 9건 모두 끝까지 처리됨).

## 8. Blog / Shorts / Threads 결과

**Blog (1건, rejected)**: "AI와 금융 판단"을 주제로 사용자 의견을 자연스럽게
녹였으나, 거부 사유는 `['사실 범위를 넓히는 표현이 추가되었습니다: 경험',
'금융 콘텐츠의 공식 기준 비해석 경계가 유지되지 않았습니다.']` — 지난
`docs/5-5_first_scout_media_test.md`에서 관찰한 것과 동일한 패턴(금융
면책 문구 누락 + "경험" 단어로 인한 사실범위 확장 판정)이 이번에도
재현됐다.

**Shorts (3건, 1 rejected / 2 valid)**: rejected 1건은 "경험"이라는 단어
때문에 거부됨(동일 패턴). valid 2건은 사용자 문장 "신기술은 두려워 말고
부딪혀서 느껴봐야 한다"를 거의 그대로 문장 앞부분에 배치하고, "경험"류
단어를 새로 추가하지 않아 통과했다. 3건 모두 티몽의 관점이 담겨 있고,
valid 2건은 내용이 서로 다른 문장 구성을 사용해 지난 테스트보다는 다양성이
나아졌다.

**Threads (5건, 2 rejected / 3 valid)**: rejected 2건 중 1건은 "경험" 확장,
다른 1건은 `원문 근거에 없는 사람·기관·상품명이 추가되었습니다: 접근법`
(제목의 "접근법"이라는 단어가 Validator의 고유명사/기관명 패턴에 걸려
새로운 항목으로 잡힘 — 오탐에 가까운 사례로 보인다). valid 3건은 각각
"AI 기술에 대한 적대감 극복하기", "신기술과의 싸움", "신기술과 AI에 대한
나의 생각"으로 제목이 서로 다르고 본문 구성도 이전 테스트보다 조금 더
다양했다.

**공통 확인 사항 (전체 9건)**:

- 모든 draft의 `source_url`이 원본과 정확히 일치.
- 어떤 draft도 사용자 의견을 "AI 찬성"처럼 단순화하지 않았고, "두려워 말고
  부딪혀서/경험하며 느껴봐야 한다"는 취지를 9건 모두 일관되게 유지했다.
- Blog 항목에서만 "경험이 진정한 가치/이해로 이어진다"는 식의 확장 주장이
  다시 나타났는데, Validator가 이를 다시 정확히 잡아 거부했다(안전장치
  정상 작동, 지난 테스트와 동일 패턴 재현).

## 9. 실제 API 게시 여부

- **Threads 실제 게시: 수행하지 않음.** `scripts/tak_auto.py`는
  `content_engine.threads_publisher`나 `scripts/publish_threads.py`를 전혀
  import/호출하지 않는다(코드 자체에 호출 경로가 없음).
- **Naver Blog 게시: 수행하지 않음.** `blog_publish_pack`/`mark_blog_published`
  관련 함수를 호출하지 않았다.
- **GitHub Actions: 실행하지 않음.** `gh workflow run` 등을 호출하지
  않았고, 확인 결과 이번 세션에서 트리거된 workflow 실행도 없다(기존
  스케줄러가 이 작업과 무관하게 매일 자동 실행되는 것과는 별개).
- 이번 실행에서 사용한 KNOWLEDGE/답변/배치 결과 파일은 모두 **세션 임시
  디렉터리 복사본**이었고, 실제 `data/tak_scout_daily.json`,
  `data/tak_interview_answers.json`, `data/tak_brain_knowledge.json`은
  실행 전후로 내용이 동일함을 직접 확인했다(승인 5건 / 대기 7건 / 거절
  9건, 답변 10건 — 변화 없음).

## 10. 테스트 결과

| 항목 | 결과 |
|---|---|
| 기존 테스트 스위트 (수정 후) | **240/240 PASS** |
| 실제 SCOUT 데이터 소재 목록 표시 | 성공 (10건 정상 표시) |
| 소재 선택(10번) | 성공 |
| INTERVIEW 질문/선택지 표시 | 성공 |
| D(직접 입력) + USER ORIGINAL THOUGHT 저장 | 성공 (중복 판정도 정상) |
| KNOWLEDGE 생성 및 화면 표시 | 성공 (SOURCE FACT/URL/USER ORIGINAL THOUGHT 모두 표시) |
| 승인(Y) → approved 반영 | 성공 (복사본에만 반영, 실제 데이터 불변 확인) |
| TAK MEDIA 실제 LLM 실행(`--execute`) | 성공 (9 Draft 생성, error 0) |
| Blog 1 / Shorts 3 / Threads 5 구성 | 정확히 일치 |
| valid/rejected 상태 표시 | 성공 (valid 5 / rejected 4) |
| 실제 Threads/Naver 게시 | 수행하지 않음(확인 완료) |

**전체 시스템이 실제 SCOUT 데이터 + 실제 LLM으로 끝까지 정상 작동함을
확인했다.**

## 11. 발견된 문제

1. (기존 알려진 이슈, 재확인) Validator의 "경험" 단어 기반 사실범위 확장
   판정이 이번에도 다수 draft를 거부시켰다 — Blog 1건, Shorts 1건, Threads
   1건, 총 3건이 이 사유로 거부됨(9건 중 3건).
2. (신규 관찰) Threads 1건이 `원문 근거에 없는 사람·기관·상품명이
   추가되었습니다: 접근법`으로 거부됐다. "접근법"은 실제로는 고유명사가
   아니라 일반 단어인데, Validator의 엔티티 탐지 정규식(`_ENTITY_PATTERN`)
   패턴에 우연히 걸린 것으로 보인다(오탐 가능성). 코드 수정은 이번 단계
   범위 밖이라 수정하지 않고 관찰만 기록한다.
3. Blog는 이번에도 금융 면책 문구 누락으로 거부됐다 — 5-5 단계에서 이미
   확인된 패턴이 실제 데이터로도 동일하게 재현됨(회귀가 아니라 일관된
   기존 동작).
4. 위 모든 문제는 **Validator가 정상적으로 작동해 걸러낸 것**이며, 사용자
  가 요청한 대로 이번 단계에서 Validator/LLM prompt 개선은 하지 않았다.

## 12. 다음 단계 (제안, 이번 단계에서는 실행하지 않음)

1. `_ENTITY_PATTERN`이 "접근법" 같은 일반 단어를 고유명사로 오탐하는
   사례를 별도로 더 수집해, Validator 개선이 필요한지 검토한다(이번
   단계에서는 수정 금지 지시에 따라 관찰만 함).
2. `data/tak_brain_knowledge.json`의 실제 승인 건수에 의존하던 테스트
   패턴이 이번에 1건 더 발견되지 않았는지, 유사 패턴이 다른 테스트
   파일에도 있는지 별도로 전수 점검하는 방안을 검토한다.
3. 이번에 valid로 나온 Threads 3건/Shorts 2건 중 실제 게시할 것이 있는지는
   사람이 별도로 검토·결정한다(이번 단계에서는 게시하지 않음).
4. 코드 수정, Threads/Naver 게시, commit/push는 모두 사용자의 별도 지시가
   있을 때 진행한다.
