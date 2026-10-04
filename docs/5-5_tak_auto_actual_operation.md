# TAK AUTO 실제 운영 가이드

현재 구현된 TAK AUTO 전체 파이프라인(TAK SCOUT → TAK INTERVIEW → TAK BRAIN →
TAK MEDIA → Threads 게시)을 처음부터 끝까지 실제로 따라 할 수 있도록 정리한 문서다.
모든 명령어는 각 스크립트의 `--help` 출력과 실제 소스 코드를 직접 확인해 정확한
옵션명과 기본값을 그대로 옮겼다(추측으로 작성한 명령어는 없다). 저장소 루트
(`/workspaces/tak-auto`)에서 실행하는 것을 기준으로 한다.

이 문서를 작성하는 과정에서는 코드를 수정하지 않았고, commit/push도 하지 않았으며,
실제 Threads 게시도 실행하지 않았다.

---

## 1. TAK SCOUT

인터넷 공개 RSS에서 오늘 검토할 소재 후보를 모으는 단계다.

### 실행 명령

```bash
python3 scripts/run_scout.py
```

주요 옵션(전부 기본값이 있어 옵션 없이 실행해도 된다):

| 옵션 | 기본값 | 설명 |
| --- | --- | --- |
| `--sources` | `data/scout_sources.json` | RSS source 목록 JSON 경로 |
| `--output-json` | `data/tak_scout_daily.json` | 결과 JSON 저장 경로 |
| `--output-md` | `data/tak_scout_daily.md` | 결과 Markdown 저장 경로 |
| `--max` | `10` | 오늘 선정할 후보의 최대 개수 |
| `--timeout` | `20.0` | RSS 요청 타임아웃(초) |

### 생성되는 파일

- **`data/tak_scout_daily.json`** — 프로그램(다음 단계인 `run_interview.py`,
  `apply_interview.py`)이 읽는 용도. `generated_at`, `candidate_count`,
  `candidates`(각 후보의 `scout_id`/`title`/`summary`/`source_url`/
  `published_at`/`source_name`/`category`) 구조를 가진다.
- **`data/tak_scout_daily.md`** — 사람이 눈으로 보기 위한 용도. 후보마다 제목,
  출처, 발행일, 원문 URL, 요약, "왜 주목할 만한가" 안내 문구, `scout_id`를
  보여준다. 이 파일을 열어서 다음 단계(인터뷰)에 답할 소재를 고르면 된다.

두 파일 모두 실행할 때마다 새로 덮어써지는 결과물이며(git에 커밋되지 않음),
`data/scout_sources.json`에 등록된 RSS source(현재 BBC Business, Hacker News)만
읽는다. 로그인이나 크롤링, 원문 전체 수집은 하지 않고 제목/짧은 요약/URL만 저장한다.

---

## 2. TAK INTERVIEW

`run_scout.py`가 만든 후보 목록을 읽어 후보마다 4지선다 질문을 만들고, 원하면
터미널에서 바로 답까지 받는 단계다.

### 실행 명령

```bash
python3 scripts/run_interview.py --interactive
```

`--interactive`를 빼고 실행하면 질문 파일만 만들고 답변은 받지 않는다.

주요 옵션:

| 옵션 | 기본값 | 설명 |
| --- | --- | --- |
| `--daily-pack` | `data/tak_scout_daily.json` | TAK SCOUT 결과 경로 |
| `--output-json` | `data/tak_interview_questions.json` | 질문 저장 경로(JSON) |
| `--output-md` | `data/tak_interview_questions.md` | 질문 저장 경로(Markdown) |
| `--answers` | `data/tak_interview_answers.json` | 답변 저장 경로 |
| `--interactive` | (플래그) | 터미널에서 바로 A/B/C/D 답변을 입력받는다 |

### 생성되는 파일

- **질문 파일** — `data/tak_interview_questions.json`(프로그램용) /
  `data/tak_interview_questions.md`(사람이 읽는 용도). 후보마다
  `question`, `option_a`, `option_b`, `option_c`, `option_d`가 들어 있다.
- **답변 파일** — `data/tak_interview_answers.json`. `--interactive`로 실제
  답한 소재만 여기에 저장된다(자세한 구조는 3번 참고).

`--interactive`로 실행하면 후보 하나하나마다 질문과 A/B/C/D 선택지를 보여주고
입력을 기다린다. **답하고 싶은 소재에서만 A/B/C/D를 입력하고, 나머지는 그냥
Enter를 눌러 건너뛰면 된다.** 이미 답변한 소재는 다시 묻지 않는다(`--answers`
파일에 이미 있는 `scout_id`는 건너뜀).

---

## 3. 티몽의 의견 입력

`--interactive` 실행 중 다음과 같은 화면이 후보마다 뜬다.

```
[Gloomy forecast for tenants as rent rises set to speed up] 이 경제 이슈에 대해 어떻게 생각하시나요?
  A. 이 경제 이슈를 긍정적으로 본다
  B. 이 경제 이슈를 부정적으로 본다
  C. 상황을 더 지켜봐야 한다
  D. 기타 / 내 생각 직접 입력
선택 (A/B/C/D, 건너뛰려면 Enter):
```

- **A/B/C 중 하나를 입력**하면 그대로 저장되고 추가 입력은 없다.
- **D를 입력**하면 바로 이어서 "직접 입력:" 프롬프트가 한 번 더 뜨고, 여기에
  실제 생각을 문장으로 적으면 된다. D는 반드시 직접 입력 문장이 있어야 저장된다
  (비어 있으면 오류로 처리되어 저장되지 않는다).
- **아무것도 입력하지 않고 Enter만 누르면** 그 소재는 건너뛴다(답변 파일에
  기록되지 않는다).

### 답변 JSON 구조 (`data/tak_interview_answers.json`)

```json
[
  {
    "scout_id": "scout-4a25c9bcac4e",
    "selected_option": "A",
    "custom_answer": "",
    "answered_at": "2026-09-14T03:10:00+00:00"
  },
  {
    "scout_id": "scout-abcdef123456",
    "selected_option": "D",
    "custom_answer": "임대료 상승은 결국 세입자의 실질 소득 감소로 이어질 수 있어 우려된다",
    "answered_at": "2026-09-14T03:12:00+00:00"
  }
]
```

- `scout_id`: `tak_scout_daily.json`에 있는 후보의 id와 정확히 일치해야 한다.
- `selected_option`: `"A"`, `"B"`, `"C"`, `"D"` 중 하나(대문자, 소문자 모두
  가능하나 저장 시 대문자로 정규화된다).
- `custom_answer`: A/B/C는 빈 문자열(`""`)로 둔다. D는 반드시 내용이 있어야 한다.
- `answered_at`: 답변 시각(ISO 8601, UTC). `--interactive`로 답하면 자동으로
  채워지며, 파일을 직접 편집할 때는 아무 시각 문자열이나 넣어도 동작에는
  영향이 없다(기록용).

코딩을 몰라도 `--interactive` 없이 `run_interview.py`를 한 번 실행해 질문 파일만
만든 뒤, 위 구조 그대로 `data/tak_interview_answers.json`을 텍스트 편집기로 직접
작성해도 똑같이 동작한다.

---

## 4. APPLY INTERVIEW

티몽의 답변을 TAK BRAIN(KNOWLEDGE)으로 넘기는 단계다.

### 실행 명령

```bash
python3 scripts/apply_interview.py
```

주요 옵션:

| 옵션 | 기본값 | 설명 |
| --- | --- | --- |
| `--daily-pack` | `data/tak_scout_daily.json` | TAK SCOUT 결과 경로 |
| `--answers` | `data/tak_interview_answers.json` | TAK INTERVIEW 답변 경로 |
| `--knowledge` | `data/tak_brain_knowledge.json` | KNOWLEDGE 누적 저장 경로 |

실행하면 다음과 같이 출력된다.

```
신규 KNOWLEDGE(pending): 1건
미답변으로 건너뜀: 9건
이미 연결됨(중복): 0건
저장 위치: data/tak_brain_knowledge.json
```

**답변하지 않은 소재는 KNOWLEDGE로 절대 넘어가지 않는다.** `tak_scout_daily.json`의
후보 중 `tak_interview_answers.json`에 같은 `scout_id`의 답변이 없으면 무조건
건너뛴다(위 출력의 "미답변으로 건너뜀"). 같은 답변으로 이미 KNOWLEDGE가 만들어져
있으면 중복으로 다시 추가하지 않는다.

### SOURCE FACT / SOURCE URL / USER ANGLE / USER ORIGINAL THOUGHT 연결

새로 만들어지는 KNOWLEDGE의 `evidence` 필드에 아래 네 가지가 라벨과 함께
그대로 남는다.

```
SOURCE FACT: <RSS 요약 또는 제목 — 외부 자료에서 확인한 사실>
SOURCE URL: <원문 주소>
USER ANGLE: <A/B/C를 선택했을 때, 그 선택을 문장으로 바꾼 것>
USER ORIGINAL THOUGHT: <D를 선택했을 때, 직접 입력한 문장 그대로>
```

`USER ANGLE`과 `USER ORIGINAL THOUGHT`는 동시에 생기지 않는다(선택한 옵션에
따라 둘 중 하나만 들어간다). 같은 내용이 `factual_information`(사실) /
`opinion`(의견) 필드에도 각각 그대로 저장되어, 나중에 KNOWLEDGE를 검토할 때
"이건 원문 사실이고, 이건 티몽 의견이다"를 한눈에 구분할 수 있다.

새로 만들어지는 KNOWLEDGE는 항상 `knowledge_review_status: "pending"` 상태이며,
KNOWLEDGE `id`는 `knowledge-scout-<해시>` 형식이다(같은 소재+같은 답변이면
항상 같은 id가 나오므로, `apply_interview.py`를 여러 번 실행해도 중복 생성되지
않는다).

---

## 5. KNOWLEDGE 승인

방금 만들어진 KNOWLEDGE는 아직 `pending` 상태다. **승인(`approved`) 전에는
TAK MEDIA로 절대 넘어가지 않는다.** (TAK MEDIA는 `select_approved()`로 걸러진
`approved` 상태 KNOWLEDGE만 대상으로 삼는다.)

### 확인 명령

```bash
python3 scripts/review_knowledge.py --pending
```

pending 상태인 KNOWLEDGE 전체의 상세 필드(`evidence` 포함)와 자동 품질 판정
(A/B/C, 승인 권고)을 보여준다. 요약만 보고 싶으면:

```bash
python3 scripts/review_knowledge.py --report
```

특정 KNOWLEDGE 1건만 자세히 보고 싶으면:

```bash
python3 scripts/review_knowledge.py --show knowledge-scout-xxxxxxxxxxxx
```

### 승인/거절 명령

```bash
python3 scripts/review_knowledge.py --id knowledge-scout-xxxxxxxxxxxx --approve --note "검토 완료"
```

거절하려면:

```bash
python3 scripts/review_knowledge.py --id knowledge-scout-xxxxxxxxxxxx --reject --note "사유"
```

`--input`으로 KNOWLEDGE 파일 경로를 바꿀 수 있으며 기본값은
`data/tak_brain_knowledge.json`이다.

---

## 6. TAK MEDIA

승인된 KNOWLEDGE를 Blog 1건 + Shorts 3건 + Threads 5건, 총 9개 Draft로 만드는
단계다.

### 실행 명령

```bash
python3 scripts/run_media_batch.py --id knowledge-scout-xxxxxxxxxxxx
```

주요 옵션:

| 옵션 | 기본값 | 설명 |
| --- | --- | --- |
| `--input` | `data/tak_brain_knowledge.json` | 읽기 전용 KNOWLEDGE JSON 경로 |
| `--output` | (없음) | 배치 결과 저장 JSON 경로(선택) |
| `--execute` | (플래그) | 실제 LLM API 호출을 명시적으로 허용 |
| `--limit` | (없음) | 처리할 승인 KNOWLEDGE 최대 개수 제한 |
| `--id` | (없음) | 특정 KNOWLEDGE ID 1건만 대상으로 실행 |

### Dry-run과 실제 LLM 실행의 차이

- **`--execute` 없이 실행(기본값) = Dry-run.** 네트워크 호출이 전혀 없다.
  콘텐츠 생성 로직(`generate_content_bundle`)만 규칙 기반으로 돌려서 "이런
  Draft가 몇 건 만들어질 예정"이라는 메타데이터만 보여준다.

  ```
  === TAK MEDIA Batch Pipeline (Dry-run) ===
  입력 파일: data/tak_brain_knowledge.json
  전체 KNOWLEDGE: 1건
  승인 KNOWLEDGE: 1건
  예상 생성 Draft: 9건 (1 KNOWLEDGE당 Blog 1, Shorts 3, Threads 5)
  네트워크 호출 없음. 실제 실행에는 --execute와 환경변수(TAK_MEDIA_LLM_API_KEY, TAK_MEDIA_LLM_ENDPOINT, TAK_MEDIA_LLM_MODEL)가 필요합니다.
  ```

- **`--execute`를 붙이면 실제 LLM API를 호출**해 Draft를 재작성(Rewrite)하고
  검증까지 수행한다. 아래 환경변수 3개가 반드시 설정되어 있어야 한다
  (`content_engine/llm_provider.py`의 `OpenAICompatibleRewriteProvider.from_environment()`가
  요구하는 값 그대로다).

  - `TAK_MEDIA_LLM_API_KEY`
  - `TAK_MEDIA_LLM_ENDPOINT`
  - `TAK_MEDIA_LLM_MODEL`

  ### 실제 LLM 실행 명령 (참고용 — 이 문서 작성 중에는 실행하지 않음)

  ```bash
  export TAK_MEDIA_LLM_API_KEY="실제 API 키"
  export TAK_MEDIA_LLM_ENDPOINT="실제 LLM 엔드포인트 URL"
  export TAK_MEDIA_LLM_MODEL="실제 모델명"
  python3 scripts/run_media_batch.py --id knowledge-scout-xxxxxxxxxxxx --execute --output data/tak_media_batch_daily.json
  ```

  실행이 끝나면 valid/rejected/error 건수와 함께 결과가 `--output` 경로에
  저장된다. **이 단계는 Threads/Blog에 실제로 게시하지 않는다.** Draft를
  만들고 검증까지만 하는 단계다.

---

## 7. Threads 실제 게시

TAK MEDIA가 만든 valid 상태의 Threads Draft 중 하나를 실제로 Threads에 올리는
마지막 단계다. 흐름은 다음과 같다.

```
TAK MEDIA(run_media_batch.py --execute 결과, valid Threads draft 포함)
  → scripts/publish_threads.py
  → 게시 성공 시 data/threads_publish_log.json(publish history)에 기록
  → Threads
```

### 게시 확인용 명령 (Dry-run — 실제 게시 없음)

```bash
python3 scripts/publish_threads.py --input data/tak_media_batch_daily.json --auto --dry-run
```

- `--input`: TAK MEDIA 배치 결과 JSON 경로(기본값은
  `data/tak_media_batch_e2e_test.json`이므로, 직접 만든 배치 결과를 쓰려면
  반드시 `--input`을 지정해야 한다).
- `--auto`: valid 상태이면서 아직 게시 이력(`--history`)에 없는 Threads 콘텐츠
  1건을 자동으로 골라준다. (`--auto` 없이 `--index`로 몇 번째 항목인지 수동
  지정할 수도 있다.)
- `--dry-run`: 실제 API를 호출하지 않고 "게시될 예정 내용"만 화면에 보여준다.
  **게시 이력도 기록하지 않는다.**

```
=== TAK MEDIA Threads Publish (Dry-run) ===
게시 예정 내용:
...
네트워크 호출 없음. 실제 게시에는 --dry-run 없이 THREADS_ACCESS_TOKEN 환경변수가 필요합니다.
Dry-run에서는 게시 이력을 기록하지 않습니다.
```

### `--history` 옵션

게시 이력 JSON 경로다(기본값: `data/threads_publish_log.json`). `--auto`가
"이미 게시한 콘텐츠"를 판단하는 기준이 되며, 실제 게시가 성공하면 이 파일에
`content_id`/`published_at`/`threads_post_id` 등이 자동으로 추가된다.

---

### ⚠️ 실제 게시 명령 (여기서부터는 진짜로 Threads에 올라간다)

아래 명령은 `--dry-run`이 없고 `THREADS_ACCESS_TOKEN` 환경변수가 설정되어
있으면 **실제로 Threads에 글이 게시된다.** 위 dry-run 명령과 혼동하지 않도록
별도로 표시한다. 이 문서를 작성하는 과정에서는 이 명령을 실행하지 않았다.

```bash
export THREADS_ACCESS_TOKEN="실제 Threads Access Token"
python3 scripts/publish_threads.py --input data/tak_media_batch_daily.json --auto
```

성공하면 다음처럼 출력되고, `data/threads_publish_log.json`에 이력이 남는다.

```
Threads 계정 확인 완료: @tmong_wisdom (ID: 111)
게시 중: 자동 선택 (게시 이력에 없는 첫 valid 항목, content_id=content-...) KNOWLEDGE=knowledge-...
성공: Threads 게시 완료! (Post ID: ...)
```

---

## 8. 전체 운영 흐름

```
RSS (BBC Business, Hacker News)
  ↓  python3 scripts/run_scout.py
TAK SCOUT (data/tak_scout_daily.json/.md)
  ↓  python3 scripts/run_interview.py --interactive
TAK INTERVIEW (질문 생성 + A/B/C/D 또는 D 직접 입력)
  ↓
티몽 의견 (data/tak_interview_answers.json)
  ↓  python3 scripts/apply_interview.py
TAK BRAIN (KNOWLEDGE, 상태: pending)
  ↓  python3 scripts/review_knowledge.py --id ... --approve
KNOWLEDGE 승인 (상태: approved)
  ↓  python3 scripts/run_media_batch.py --id ... --execute
TAK MEDIA (Blog 1 / Shorts 3 / Threads 5 Draft, 검증 완료)
  ↓  python3 scripts/publish_threads.py --input ... --auto
Blog / Threads / Shorts 게시
  ↓
수익화
```

Blog는 자동 게시가 아니라 `scripts/generate_blog_publish_pack.py`로 "복사/
붙여넣기용 Markdown"을 만들어 사람이 네이버 블로그에 직접 옮기는 방식이다
(9번 참고). Threads만 API로 자동 게시된다.

---

## 9. 현재 자동화된 부분과 수동 부분

**자동화됨**

- TAK SCOUT: RSS 수집, 중복 제거, 후보 선정 (`run_scout.py`)
- TAK INTERVIEW: 질문 생성 (`run_interview.py`), 답변 파일 저장
- TAK BRAIN: 답변 → KNOWLEDGE(pending) 변환 (`apply_interview.py`)
- TAK MEDIA: 승인 KNOWLEDGE → Blog/Shorts/Threads Draft 생성 + LLM 재작성 +
  검증 (`run_media_batch.py --execute`)
- **Threads 게시 자체**: `scripts/publish_threads.py`(API 호출), 그리고
  **매일 자동 실행**: `.github/workflows/daily-threads-post.yml`이 매일
  한국시간(KST) 오전 8시(cron `0 23 * * *`, UTC 기준)에
  `python3 scripts/run_daily.py`(KNOWLEDGE 로드 → TAK MEDIA 실행 →
  `publish_threads.py --auto` 순으로 이어지는 오케스트레이터)를 자동
  실행한다. 이 workflow는 실제로 게시가 성공하면
  `data/threads_publish_log.json`을 커밋/푸시까지 자동으로 한다. 수동으로
  workflow를 실행(`workflow_dispatch`)할 때는 `dry_run` 입력값의 기본값이
  `true`라서, 값을 바꾸지 않고 그대로 실행하면 항상 게시 없는 안전한 경로로
  돈다. `dry_run`을 `false`로 바꿔서 수동 실행하거나 매일 스케줄(schedule
  트리거, `dry_run` 입력 자체가 없음)로 돌아갈 때만 실제 게시 경로를 탄다.
- 게시 이력 관리(중복 게시 방지): `content_engine/publish_history.py`

**수동으로 해야 함**

- TAK SCOUT 후보 중 답할 소재 선택, A/B/C/D 선택 또는 D 직접 입력 (사람의 판단)
- KNOWLEDGE 승인/거절 (`review_knowledge.py --approve/--reject`) — 사람이
  내용을 읽고 판단해야 함
- Blog는 자동 게시가 아니라 사람이 직접 네이버 블로그에 복사/붙여넣기하고
  예약 발행해야 함 (`generate_blog_publish_pack.py`로 후보 Markdown을 만든
  뒤, 실제 게시 후 `mark_blog_published.py`로 이력을 수동 기록)

**아직 구현되지 않은 것**

- 네이버 로그인/브라우저 자동 게시 (정책상 구현하지 않음, README에 명시)
- Shorts(영상) 자동 게시 — TAK MEDIA는 Shorts용 텍스트 Draft만 만들 뿐, 실제
  영상 제작이나 유튜브/인스타그램 업로드 자동화는 없음
- RSS source 확장(현재 BBC Business, Hacker News 2개뿐), 인터뷰 질문의 소재
  본문 기반 자동 심화 분석

---

## 10. 초보자용 하루 운영 예시

코딩을 전혀 몰라도 아래 순서만 그대로 따라 하면 된다. 터미널(명령 프롬프트)에
한 줄씩 복사해서 Enter만 누르면 된다.

1. **아침에 오늘 소재 받기**

   ```bash
   python3 scripts/run_scout.py
   ```

   → `data/tak_scout_daily.md` 파일을 열어서 오늘 뜬 뉴스 제목/요약을 쭉 읽는다.

2. **마음에 드는 소재 하나에 내 생각 남기기**

   ```bash
   python3 scripts/run_interview.py --interactive
   ```

   → 소재마다 A/B/C/D 질문이 뜬다. 관심 있는 소재가 나오면 `D`를 입력하고
   내 생각을 한 문장으로 적는다. 나머지 소재는 그냥 Enter만 눌러서 넘긴다.

3. **내 생각을 시스템에 등록하기**

   ```bash
   python3 scripts/apply_interview.py
   ```

   → "신규 KNOWLEDGE(pending): 1건"이 뜨면 성공.

4. **내가 방금 만든 내용 확인하고 승인하기**

   ```bash
   python3 scripts/review_knowledge.py --pending
   ```

   → 화면에 뜬 `id: knowledge-scout-...` 값을 복사한다.

   ```bash
   python3 scripts/review_knowledge.py --id knowledge-scout-복사한값 --approve
   ```

5. **Blog/Shorts/Threads 초안이 어떻게 나오는지 미리 보기 (실제 게시 아님)**

   ```bash
   python3 scripts/run_media_batch.py --id knowledge-scout-복사한값
   ```

   → "Dry-run" 결과만 나오고 아무것도 실제로 게시되지 않는다. 여기까지가
   하루 운영의 전부다. 실제 Threads 게시는 매일 아침 자동(GitHub Actions)으로
   이미 돌아가므로, 사람이 직접 게시 버튼을 누를 필요는 없다(9번 참고).

이 5단계만 매일 반복하면 "오늘 뜬 뉴스 → 내 생각 한 줄 → KNOWLEDGE 승인"까지
사람이 담당하고, 그 뒤 실제 Threads 게시는 자동화된 파이프라인이 이어받는다.
