# 5-5 실제 인터뷰 데이터 정리 결과

작업 시각(UTC): 2026-09-14, `docs/5-5_actual_interview_correction.md` 진단을
기준으로 데이터만 정리했다. 코드 수정, git commit/push, KNOWLEDGE 승인,
TAK MEDIA 실행, Threads 게시는 수행하지 않았다.

## 1. 백업 결과

정리 전에 두 파일을 백업했다.

- `/tmp/tak_interview_answers.20260914T044116Z.json`
- `/tmp/tak_brain_knowledge.20260914T044116Z.json`

(작업 세션 임시 디렉터리에도 동일 내용을 추가로 보관: 세션 종료 시 `/tmp`가 정리될
경우를 대비한 이중 백업.)

## 2. Reject 처리한 KNOWLEDGE

`scripts/review_knowledge.py --id <ID> --reject --note "..."`로 총 9건을
`rejected` 상태로 전환했다(삭제 아님, 이력 보존).

**의도하지 않은 8건** — note: "5-5 실제 운영 테스트에서 의도하지 않게 생성된 답변 정리"

| id | source_raw_id | title |
|---|---|---|
| knowledge-scout-e981e03d8737 | scout-66639b297fc0 | Committee calls for bill to address AI threat to human rights |
| knowledge-scout-624fd3789798 | scout-ba66996771b4 | 'Culture shift' needed in how UK does business, PM urges |
| knowledge-scout-c8a717882561 | scout-87f2284ff52b | How to protect your laptop, phone and bike from thieves at uni |
| knowledge-scout-d21393bd1af0 | scout-e630ed0ba090 | Amazon pauses work with cargo firm after fatal crash |
| knowledge-scout-70346e8dbd16 | scout-d4fca881c453 | Trump downplays warnings of AI risks, citing rivalry with China |
| knowledge-scout-9ee1fb847bed | scout-ba089403ed6d | AI staff 'genuinely frightened' for humanity's future, ex-Anthropic researcher tells BBC |
| knowledge-scout-da6d70cade1b | scout-82de86b62e46 | Dramatic insider warnings over AI fall flat with some in Silicon Valley |
| knowledge-scout-26c322127579 | scout-89f867fe002d | Trump says he will remove all Irish whiskey tariffs as he ends two-day visit |

**잘못된 Dario Amodei KNOWLEDGE 1건** — note: "사용자 의도와 다른 인터뷰 답변(C)으로
생성된 테스트 데이터. 올바른 의견으로 재생성."

| id | source_raw_id | title |
|---|---|---|
| knowledge-scout-56f0f4f75183 | scout-0db222f63dd1 | Anthropic boss Dario Amodei calls for AI development to slow down |

모두 `--reject` 명령이 정상 처리를 보고했고(각 id별 `rejected` 응답 확인),
파일에서 삭제된 항목은 없다.

## 3. Dario 답변 수정 결과

`data/tak_interview_answers.json`의 `scout-0db222f63dd1` 항목을 아래로 수정했다
(`InterviewAnswer.create` + `upsert_answer` 사용, 기존 형식 그대로 유지).

- 이전: `selected_option: "C"`, `custom_answer: ""`
- 이후: `selected_option: "D"`, `custom_answer: "신기술은 두려워 말고 부딪혀서 느껴봐야 한다."`
- `answered_at`: 현재 시각(2026-09-14T04:41:37 UTC)으로 갱신됨

`data/tak_interview_answers.json`의 총 답변 수는 그대로 **10건**이다(수정이지
추가/삭제 아님). `scout-4a25c9bcac4e`(임대료 상승, D)는 지시대로 손대지 않고
그대로 유지했다.

## 4. 새로 생성된 KNOWLEDGE

`python3 scripts/apply_interview.py` 재실행 결과:

```
신규 KNOWLEDGE(pending): 1건
미답변으로 건너뜀: 0건
이미 연결됨(중복): 9건
```

새로 생성된 항목: `knowledge-scout-b28b782b2a33` (source_raw_id:
`scout-0db222f63dd1`, `knowledge_review_status: pending`)

evidence 필드 확인 완료:

```
SOURCE FACT: The call comes amid growing concerns that AI models may become able to inflict serious damage worldwide.
SOURCE URL: https://www.bbc.co.uk/news/articles/c14dpgm0rg4o?at_medium=RSS&at_campaign=rss
USER ORIGINAL THOUGHT: 신기술은 두려워 말고 부딪혀서 느껴봐야 한다.
```

`reusable_principle`/`opinion` 필드에도 동일한 사용자 문장이 들어갔다. 기존
`knowledge-scout-56f0f4f75183`(잘못된 C 기반 항목)는 `rejected` 상태로 남아 있어
새 항목과 중복되지 않는다(서로 다른 id, 서로 다른 selected_option 기반).

## 5. 최종 pending/approved/rejected 현황

`data/tak_brain_knowledge.json` 전체 **21건** (기존 20건 + 신규 1건).

| 구분 | pending | approved | rejected |
|---|---|---|---|
| 기존 블로그 기반 (10건) | 6 | 4 | 0 |
| TAK SCOUT/INTERVIEW 연동 (11건) | 2 | 0 | 9 |

scout 연동 11건 상세:

| id | status | source_raw_id |
|---|---|---|
| knowledge-scout-e981e03d8737 | rejected | scout-66639b297fc0 |
| knowledge-scout-a5e1a31ccbd6 | **pending** | scout-4a25c9bcac4e (임대료, 기존 유지) |
| knowledge-scout-624fd3789798 | rejected | scout-ba66996771b4 |
| knowledge-scout-c8a717882561 | rejected | scout-87f2284ff52b |
| knowledge-scout-d21393bd1af0 | rejected | scout-e630ed0ba090 |
| knowledge-scout-70346e8dbd16 | rejected | scout-d4fca881c453 |
| knowledge-scout-9ee1fb847bed | rejected | scout-ba089403ed6d |
| knowledge-scout-da6d70cade1b | rejected | scout-82de86b62e46 |
| knowledge-scout-26c322127579 | rejected | scout-89f867fe002d |
| knowledge-scout-56f0f4f75183 | rejected | scout-0db222f63dd1 (잘못된 C 값) |
| knowledge-scout-b28b782b2a33 | **pending** | scout-0db222f63dd1 (수정된 D 값, 신규) |

확인한 항목:

- 기존 블로그 기반 approved 4건은 그대로 유지됨 (건드리지 않음)
- 의도하지 않은 8건 → 전부 `rejected` 확인
- 잘못된 Dario KNOWLEDGE(`knowledge-scout-56f0f4f75183`) → `rejected` 확인
- 올바른 Dario KNOWLEDGE(`knowledge-scout-b28b782b2a33`) → `pending`으로 신규 생성 확인
- 새 Dario KNOWLEDGE에 SOURCE FACT / SOURCE URL / USER ORIGINAL THOUGHT 문구 포함 확인
- `scout-4a25c9bcac4e`(임대료) 관련 답변·KNOWLEDGE는 변경 없이 유지됨

## 6. 안전성 확인

- 어떤 KNOWLEDGE도 이번 작업에서 **approve하지 않았다**(scout 연동 11건 중
  approved 0건).
- `scripts/run_media_batch.py`, `run_daily.py` 등 TAK MEDIA 파이프라인은
  실행하지 않았다.
- Threads 게시 관련 스크립트/명령은 실행하지 않았다.
- 소스 코드(`.py` 파일)는 일절 수정하지 않았다. 변경된 파일은 데이터 파일
  두 개뿐이다: `data/tak_interview_answers.json`, `data/tak_brain_knowledge.json`.
- git commit/push는 수행하지 않았다(두 데이터 파일은 `.gitignore`의
  `data/*.json` 규칙에 의해 애초에 git 추적 대상도 아니다).
- 모든 reject는 삭제가 아닌 상태 전환이라 `review_note`/`reviewed_at`로
  이력이 남아 있고, 필요하면 다시 `--approve`로 되돌릴 수 있다.

## 7. 다음 단계

1. `python3 scripts/review_knowledge.py --show knowledge-scout-b28b782b2a33`로
   새 Dario KNOWLEDGE 내용을 최종 육안 검토한다.
2. 검토 후 문제가 없으면 그때 `--id knowledge-scout-b28b782b2a33 --approve`로
   승인한다(이번 작업에서는 승인하지 않음).
3. 승인 이후에만 기존 TAK MEDIA 파이프라인(`run_media_batch.py`, `run_daily.py`
   등)으로 콘텐츠 생성을 진행한다.
4. `scout-4a25c9bcac4e`(임대료 답변)를 이번 정리 범위에 포함할지 여부는 여전히
   사용자 판단이 필요하다(이번에는 지시대로 손대지 않음).
5. 정리 결과에 문제가 없다고 확인되면, 이번에 생성한 `/tmp` 백업 파일들은
   더 이상 필요하지 않을 때 정리해도 된다.
