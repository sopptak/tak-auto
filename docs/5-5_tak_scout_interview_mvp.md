# TAK SCOUT + INTERVIEW MVP

TAK SCOUT(외부 소재 발굴) → TAK INTERVIEW(티몽의 의견 수집) → TAK BRAIN(KNOWLEDGE 연결) →
TAK MEDIA(Blog/Shorts/Threads Draft)로 이어지는 전체 자동화 흐름을, 완벽한 품질이 아니라
"한 번 실제로 끝까지 돌려볼 수 있는" MVP로 만든 작업 기록이다.

## 1. 현재 구조

작업 시작 시점의 `tak_scout/`는 다음 한 줄짜리 placeholder뿐이었다.

```python
"""향후 공개 자료 탐색 기능 자리."""
```

반면 TAK BRAIN(`tak_brain/`)과 TAK MEDIA(`content_engine/`)는 이미 완성된 파이프라인을
갖추고 있었다.

- `tak_brain.models.KnowledgeRecord` — RAW와 분리된 KNOWLEDGE 스키마. `evidence`,
  `opinion`, `factual_information` 등 이번 작업에 그대로 쓸 수 있는 필드가 이미 있었다.
- `tak_brain.knowledge.validate_knowledge` / `append_knowledge_file` — KNOWLEDGE 생성 시
  불변식(`pending` 상태, `rule_based_template`, `confidence=None` 등)을 검증하고 파일에
  원자적으로 누적하는 함수.
- `content_engine.generator.generate_content_bundle` — 승인(`approved`)된 KNOWLEDGE 1건을
  Blog 1 + Shorts 3 + Threads 5 Draft로 변환. `experience`, `problem`, `lesson`,
  `reusable_principle` 등 정해진 필드만 근거로 사용한다.
- `content_engine.pipeline.run_media_batch` — 승인 KNOWLEDGE 목록을 받아 Draft 생성 +
  재작성(Rewrite) + 검증까지 배치로 처리.
- `scripts/publish_threads.py --auto` — 게시 이력에 없는 첫 valid Threads Draft를 자동
  선택해 게시(+ 이력 기록).

이번 작업은 이 구조를 **하나도 바꾸지 않고**, TAK SCOUT가 만든 소재 + 티몽의 답변을
KNOWLEDGE로 변환해 위 파이프라인의 입구에 연결하는 다리 역할만 새로 만들었다.

## 2. 추가한 파일

```text
tak_scout/models.py             ScoutCandidate, scout_id 생성, category별 주어 라벨
tak_scout/rss.py                RSS 2.0 XML 파서 (fetch_rss / parse_rss_items)
tak_scout/collector.py          source 순회 수집 + 중복 제거 + 선정 + 저장/로드
tak_scout/interview.py          4지선다(A/B/C/D) 질문 생성 + 저장/로드
tak_scout/answers.py            사용자 답변 모델 + 저장/로드/upsert
tak_scout/knowledge_bridge.py   후보+답변 -> KNOWLEDGE(pending) 변환, 파일 누적
tak_scout/__init__.py           위 모듈들의 공개 API 재노출 (기존 1줄 placeholder 대체)

scripts/run_scout.py            CLI 1: RSS -> 오늘의 후보
scripts/run_interview.py        CLI 2: 후보 -> 질문 생성 (+ --interactive 답변 수집)
scripts/apply_interview.py      CLI 3: 답변 -> KNOWLEDGE(pending) 연결

data/scout_sources.json         RSS source 설정 (신규 추적 대상, git에 커밋)

tests/test_scout_rss.py                 RSS 파싱/오류 처리
tests/test_scout_collector.py           수집/중복 제거/선정/저장·로드
tests/test_scout_interview.py           질문 생성/저장·로드
tests/test_scout_answers.py             답변 검증/저장·로드/upsert
tests/test_scout_knowledge_bridge.py    KNOWLEDGE 변환 + 미답변 차단 + 중복 방지
tests/test_scout_pipeline_e2e.py        RSS->SCOUT->INTERVIEW->BRAIN->MEDIA 전체 1건
```

`.gitignore`에는 `data/scout_sources.json`(설정 파일)만 추적 대상으로 추가했다.
`data/tak_scout_daily.json/.md`, `data/tak_interview_questions.json/.md`,
`data/tak_interview_answers.json`은 기존 `tak_media_batch_daily.json`과 같은 성격의
휘발성 산출물이라 커밋하지 않는다(JSON은 기존 `data/*.json` 규칙으로 이미 제외되고,
MD 2종은 이번에 명시적으로 추가했다).

기존 파일은 하나도 수정하지 않았다. (`content_engine/__init__.py`, `.gitignore`의
`blog_publish_pack` 관련 항목은 이 작업 이전 세션에서 이미 만들어져 있던 변경사항이다.)

## 3. TAK SCOUT 흐름

```
data/scout_sources.json
  -> tak_scout.collector.load_sources
  -> (source마다) tak_scout.rss.fetch_rss + parse_rss_items
  -> tak_scout.collector.dedupe_candidates   (URL 또는 제목 기준 중복 제거)
  -> tak_scout.collector.select_candidates   (최대 10개, 기본값)
  -> save_daily_pack_json / save_daily_pack_markdown
     -> data/tak_scout_daily.json (프로그램용)
     -> data/tak_scout_daily.md   (사람이 보기 위한 용도)
```

- 공개 RSS만 읽는다. 로그인, 브라우저 크롤링, 접근 제한 우회를 하지 않는다.
- `scout_id`는 `title + source_url`을 정규화해 만든 SHA-256 앞 12자리이므로
  (`scout-<hash12>`), 같은 기사면 언제 다시 수집해도 같은 id가 나온다(deterministic).
- 원문 전체를 저장하지 않는다. `description`에서 HTML 태그를 제거하고 200자로 자른
  짧은 요약만 남긴다.
- source 하나가 실패(네트워크 오류, 잘못된 XML)해도 나머지 source 수집은 계속된다.
  실패 내역은 CLI 출력에 그대로 보여준다.
- 실제 RSS source는 현재 환경에서 접근을 직접 확인한 두 개만 등록했다(임의로 지어내지
  않음): **BBC Business**(`https://feeds.bbci.co.uk/news/business/rss.xml`, category
  `finance`), **Hacker News**(`https://news.ycombinator.com/rss`, category `tech`).
  더 추가하려면 `data/scout_sources.json`에 같은 형식으로 등록하면 된다.

## 4. TAK INTERVIEW 흐름

```
data/tak_scout_daily.json
  -> tak_scout.interview.build_interview_questions
  -> save_questions_json / save_questions_markdown
     -> data/tak_interview_questions.json
     -> data/tak_interview_questions.md
```

후보마다 다음 구조의 질문을 만든다.

```
question, option_a, option_b, option_c, option_d
```

- `option_a/b/c`는 "긍정적으로 본다 / 부정적으로 본다 / 상황을 더 지켜봐야 한다"이며,
  category(예: `finance`)에 맞춰 주어("이 경제 이슈" 등)만 조금 구체화한다.
- `option_d`는 항상 "기타 / 내 생각 직접 입력"을 의미한다.
- 완벽한 AI 인터뷰 시스템을 만들지 않았다. 규칙 기반 템플릿이며, 그만큼 단순하고
  예측 가능하다.

`scripts/run_interview.py --interactive`를 주면 터미널에서 후보를 하나씩 보여주고
A/B/C/D 입력을 받아 바로 `data/tak_interview_answers.json`에 저장한다(이미 답변한
소재는 다시 묻지 않는다). `--interactive` 없이 실행하면 질문 파일만 만들고, 사람이
`tak_interview_answers.json`을 직접 편집해도 된다고 안내한다.

## 5. 사용자 답변 구조

`data/tak_interview_answers.json`:

```json
[
  {
    "scout_id": "scout-4a25c9bcac4e",
    "selected_option": "A",
    "custom_answer": "",
    "answered_at": "2026-09-14T03:10:00+00:00"
  },
  {
    "scout_id": "scout-...",
    "selected_option": "D",
    "custom_answer": "내가 직접 입력한 생각",
    "answered_at": "..."
  }
]
```

`tak_scout.answers.InterviewAnswer.create()`가 다음을 강제한다.

- `selected_option`은 A/B/C/D 중 하나만 허용(대소문자 무관, 나머지는 오류).
- `D`를 선택하면 `custom_answer`가 비어 있으면 오류(반드시 직접 입력이 있어야 함).
- `scout_id`가 없으면 오류.

같은 `scout_id`로 다시 답하면(`upsert_answer`) 기존 답을 덮어쓴다.

## 6. TAK BRAIN 연결

`tak_scout/knowledge_bridge.py`가 후보 1건 + 답변 1건을 KNOWLEDGE(pending) 1건으로
변환한다(`build_knowledge_from_interview`). 외부 자료의 사실과 티몽의 의견을 evidence에
라벨로 명확히 구분해 남긴다.

```
SOURCE FACT: <RSS 요약 또는 제목>
SOURCE URL: <원문 주소>
USER ANGLE: <A/B/C를 선택했을 때, 규칙 기반으로 만든 의견 문장>
USER ORIGINAL THOUGHT: <D를 선택했을 때, 직접 입력한 문장 그대로>
```

`USER ANGLE`과 `USER ORIGINAL THOUGHT`는 동시에 생기지 않는다(선택한 옵션에 따라 둘 중
하나만 evidence에 들어간다). 같은 내용이 `factual_information`(사실)과 `opinion`(의견)
필드에도 각각 그대로 남아, `review_knowledge.py --show`로 볼 때 사실과 의견을 한눈에
구분할 수 있다.

TAK MEDIA(`content_engine.generator`)가 실제로 참조하는 필드는 `evidence`가 아니라
`experience/problem/action/result/lesson/reusable_principle/derived_insight`이므로,
콘텐츠가 실제로 만들어지도록 SOURCE FACT는 `lesson`에, USER ANGLE/THOUGHT는
`reusable_principle`에도 그대로 채운다(원문/의견 텍스트를 요약·재작성하지 않고 그대로
옮긴다).

그 외 나머지는 기존 TAK BRAIN 규칙을 그대로 재사용한다.

- `id`: `knowledge-scout-<hash12>` (scout_id + 선택 답변으로 계산, deterministic —
  같은 답변으로 다시 실행해도 같은 id라 중복 추가되지 않는다).
- `knowledge_review_status`: 항상 `pending`. `inference_method`:
  `rule_based_template`. `confidence`: `null`. →
  `tak_brain.knowledge.validate_knowledge()`를 그대로 통과한다(새 검증 로직을
  만들지 않았다).
- `category`/`domain`: `tak_brain.models.CATEGORIES`(금융/대출/…/기타)에 매핑하고,
  `금융/대출/경매/부동산`이면 `article_type="finance"`로 설정해 기존
  `blog_publish_pack.is_review_required()`가 "사람 확인 필요"로 자동 표시하게 했다.

`scripts/apply_interview.py`(`append_scout_knowledge`)는 `data/tak_scout_daily.json`과
`data/tak_interview_answers.json`을 대조해:

- **답변이 없는 후보는 KNOWLEDGE로 만들지 않는다**(요구사항 4번 핵심).
- 이미 같은 답변으로 만들어진 KNOWLEDGE(같은 id)는 중복 추가하지 않는다.
- 기존 `data/tak_brain_knowledge.json`에 이미 있는 레코드(예: 블로그 RAW에서 만든 것)는
  그대로 보존한다.
- 저장은 `tak_brain.knowledge.append_knowledge_file`과 동일하게
  tempfile + `replace()`로 원자적으로 쓴다.

생성된 KNOWLEDGE는 그대로 `scripts/review_knowledge.py --pending` / `--id ... --approve`
로 검토·승인한다(새 review 로직을 만들지 않았다).

## 7. TAK MEDIA 연결

TAK BRAIN까지 연결되면 그 다음은 **기존 코드를 전혀 바꾸지 않고** 그대로 이어진다.

```
scripts/review_knowledge.py --id <ID> --approve
  -> tak_brain.select_approved()
  -> content_engine.pipeline.run_media_batch() / generate_content_bundle()
  -> scripts/run_media_batch.py, scripts/generate_blog_publish_pack.py, scripts/run_daily.py 등
```

TAK SCOUT/INTERVIEW는 "승인된 KNOWLEDGE를 하나 더 만드는" 역할만 하고, 그 뒤 Blog/
Shorts/Threads Draft 생성, LLM 재작성, Threads 자동 게시(`--auto`)는 모두 기존 로직
그대로다. 이번 작업으로 실제 Threads 게시가 발생하지 않도록, 아래 "실제 사용 방법"과
테스트 모두 `run_media_batch.py`(기본 dry-run) 또는 `MockRewriteProvider`까지만
확인했다.

## 8. 실제 사용 방법

```bash
# 1. 오늘의 소재 후보 수집 (실제 공개 RSS에 접속)
python3 scripts/run_scout.py

# 2. 인터뷰 질문 생성 + 터미널에서 바로 답변
python3 scripts/run_interview.py --interactive
# (또는 --interactive 없이 실행한 뒤 data/tak_interview_answers.json을 직접 편집)

# 3. 답변한 소재만 KNOWLEDGE(pending)로 연결
python3 scripts/apply_interview.py

# 4. 기존 TAK BRAIN 검토 흐름 그대로 승인
python3 scripts/review_knowledge.py --pending
python3 scripts/review_knowledge.py --id knowledge-scout-xxxxxxxxxxxx --approve

# 5. 기존 TAK MEDIA 파이프라인 그대로 사용 (실제 게시는 사람이 별도 판단)
python3 scripts/run_media_batch.py --id knowledge-scout-xxxxxxxxxxxx
# 또는 python3 scripts/run_daily.py / generate_blog_publish_pack.py 등
```

이 순서를 실제로 실행해 확인했다(아래 9번 참고). RSS 수집은 실제 네트워크(BBC
Business, Hacker News)에 접속했고, KNOWLEDGE 생성·승인까지 실제로 진행했으며, TAK
MEDIA는 `run_media_batch.py`의 기본 dry-run(네트워크 호출 없음)으로 Blog/Shorts/
Threads Draft 9건이 만들어지는 것까지 확인했다. Threads 실제 게시는 수행하지 않았고,
`data/threads_publish_log.json` 등 기존 게시 이력 파일은 전혀 건드리지 않았다(모든
수동 확인은 `/tmp` 아래 별도 파일에서 진행).

## 9. 테스트 결과

```bash
python3 -m unittest discover -s tests -p 'test*.py'
```

```
Ran 238 tests in 1.4s
OK
```

기존 195개 테스트가 모두 그대로 통과하고(회귀 없음), 이번에 추가한 43개 테스트가
전부 통과한다.

| 테스트 파일 | 확인 내용 |
| --- | --- |
| `test_scout_rss.py` | RSS 파싱(제목/요약/URL/발행일), scout_id 결정성, 필수 필드 없는 item 스킵, 잘못된 XML에서 `ScoutRssError`, 긴 요약 200자 절단 |
| `test_scout_collector.py` | source 목록 구조 검증, URL/제목 기준 중복 제거, 최대 개수 제한, source 1건 실패가 나머지 수집을 막지 않음(mock으로 네트워크 대체), JSON/MD 저장·로드 |
| `test_scout_interview.py` | 4지선다 생성, D="직접 입력" 고정, category별 문구 차이, 질문 저장·로드 |
| `test_scout_answers.py` | A/B/C는 직접 입력 불필요, D는 필수, 잘못된 옵션 거부, 저장·로드, upsert로 재답변 시 덮어쓰기 |
| `test_scout_knowledge_bridge.py` | evidence에 SOURCE FACT/URL/USER ANGLE 또는 USER ORIGINAL THOUGHT가 정확히 구분되어 남는지, **미답변 후보는 KNOWLEDGE로 넘어가지 않는지**, 동일 답변 재실행 시 중복 생성 안 됨, 기존 KNOWLEDGE 보존, KNOWLEDGE id 결정성 |
| `test_scout_pipeline_e2e.py` | RSS(mock) → SCOUT → INTERVIEW(D, 직접 입력) → BRAIN(pending→approved) → MEDIA(`generate_content_bundle`, `run_media_batch`)까지 한 번에 흐르는지, 최종 evidence에 세 라벨이 모두 남는지 |

외부 인터넷에 의존하는 로직(RSS 수집)은 전부 `unittest.mock.patch`로 `fetch_rss`를
대체해 테스트했고, 실제 네트워크를 사용하는 테스트는 없다(기존
`tests/test_naver_raw.py`의 mock 패턴을 그대로 따랐다).

## 10. 현재 한계

- **RSS source 2개뿐**: 실제 접근을 확인한 공개 RSS만 등록했다(BBC Business, Hacker
  News). 한국어/금융 특화 RSS를 더 쓰려면 실제 URL 접근을 확인한 뒤
  `data/scout_sources.json`에 추가해야 한다.
- **"왜 주목할 만한가" 문구가 정형화되어 있다**: 소재 내용을 분석해 만든 것이 아니라
  "출처/category에서 다룬 소재"라는 고정 안내 문구다. 근거 없는 판단을 자동으로
  만들지 않기 위한 의도적 선택이지만, 사람이 실제로 판단해야 하는 몫이 크다.
- **인터뷰 질문이 규칙 기반**: 소재 제목/category만 보고 선택지 문구를 조금 바꾸는
  수준이며, 본문 내용을 깊이 분석하지 않는다.
- **KNOWLEDGE 문장이 영문 원문을 그대로 포함할 수 있다**: 영문 RSS(BBC, HN)의
  요약을 번역하지 않고 그대로 `SOURCE FACT`/`lesson`에 넣는다. 원문을 왜곡하지
  않기 위한 선택이지만, 실제 Blog/Threads로 나갈 때는 사람이 다듬어야 한다.
- **`lesson`/`reusable_principle`에 사실과 의견을 나눠 넣는 방식은 TAK MEDIA의
  기존 문구("원문에서는 ~라고 설명합니다", "이를 적용할 때는 ~는 원칙을 제시합니다")에
  맞춘 것**이라, "의견"이 마치 "원문이 제시한 원칙"처럼 보일 수 있다. `evidence`와
  `opinion`/`factual_information` 필드에는 명확히 구분되어 있지만, TAK MEDIA가 만드는
  최종 문장에서는 그 경계가 완전히 드러나지는 않는다. TAK MEDIA 자체는 이번 작업
  범위에서 수정하지 않았다.
- **중복 제거가 단순하다**: URL 정규화(소문자/trailing slash 제거)와 제목 공백 정규화
  수준이며, 의미가 같지만 표현이 다른 기사(다른 매체의 같은 이슈 재보도 등)는 걸러내지
  못한다.
- **`--interactive`는 자동 테스트 대상이 아니다**: `input()`을 직접 받는 부분은
  수동으로만 확인했고(터미널 붙여넣기), 질문 생성·답변 저장·KNOWLEDGE 연결 로직은
  전부 자동 테스트로 커버했다.

## 11. 다음 단계

- 실제 접근 가능한 한국어/금융 특화 RSS를 추가로 검증해 `scout_sources.json`을
  확장한다.
- "왜 주목할 만한가" 판단을 규칙(키워드 매칭 등) 기반으로 조금 더 구체화할지, 계속
  사람 판단에 맡길지 결정한다.
- 인터뷰 질문에 소재 요약을 조금 더 반영해(예: 키워드 추출) 선택지를 구체화한다.
- 영문 소재의 `SOURCE FACT`를 그대로 둘지, 사람이 검토 단계에서 한국어로 옮기는
  절차를 별도로 문서화할지 정한다.
- MVP 사용 결과를 바탕으로, TAK SCOUT 전용 KNOWLEDGE 품질 기준(예:
  `assess_knowledge_quality`에 scout 출신 레코드를 위한 조건 추가 여부)을 검토한다.
