# Threads 3일 연속 중복(유사) 발행 원인 분석

> 이 문서는 **원인 분석 전용**이다. 코드 수정, git commit, git push는
> 전혀 하지 않았다. 조사는 GitHub Actions 실제 실행 로그(`gh run view`)와
> GitHub `origin/main`의 실제 커밋 상태(`git fetch` + `git show
> origin/main:<path>`)만을 근거로 했다 - 추측이나 "개발 중이라서" 식의
> 설명은 배제했다.

## 0. 조사 방법 및 사전 확인 사항

`gh run list/view`로 GitHub Actions 실제 로그를 가져오고, `git fetch` +
`git show origin/main:<path>`로 **원격 main의 실제 커밋 상태**(로컬
dev 사본이 아님)를 대조했다.

> 조사 중 확인된 별개 사실: 이 로컬 개발 환경의 `git log`는 `f77ee05`가
> 최신이지만, GitHub `origin/main`은 이미 `8350504`까지 진행돼 있었다(1
> 커밋 뒤처짐). 이 자체는 버그가 아니라 "로컬 sandbox가 최신 push를 아직
> pull하지 않은 상태"일 뿐이며, 아래 분석은 전부 **origin/main(실제
> 운영 상태)** 기준이다.

## 1. 최근 3일 실행

| 날짜(UTC) | workflow run | trigger | command | knowledge_id | content_id | Threads post_id | history 반영 |
|---|---|---|---|---|---|---|---|
| 2026-09-13 13:44 | 34760506206 | workflow_dispatch(live) | `python3 scripts/run_daily.py` → 내부적으로 `publish_threads.py --auto` | `knowledge-da6ddf5aa459` | `content-f2082a27c88c26ca` | `18114019807999154` | 반영됨 (commit `7833255`, 파일 신규 생성, push 성공 `b2b28d0..7833255`) |
| 2026-09-14 00:45 | 34793484744 | schedule | 동일 | `knowledge-da6ddf5aa459` | `content-b4b9a05c461ad595` | `18099811769051475` | 반영됨 (commit `f2417fd`, push 성공 `a941830..f2417fd`) |
| 2026-09-15 01:12 | 34916118494 | schedule | 동일 | `knowledge-da6ddf5aa459` | `content-45d8e97f0fab7b16` | `18134252149645663` | 반영됨 (commit `8350504`, push 성공 `f77ee05..8350504`) |

세 실행 모두: `TAK BRAIN: 승인 KNOWLEDGE 4건 확인` → `TAK MEDIA 완료: 총
Draft 36건(valid 35~34)` → `Threads 계정 확인 완료: @tmong_wisdom` →
`게시 중: 자동 선택 (게시 이력에 없는 첫 valid 항목, ...)` → `성공:
Threads 게시 완료!` → history commit/push 성공, 순서로 정확히 동일하게
진행됐다.

> 참고: 각 run의 로그 앞부분에 `TAK BRAIN: 승인 KNOWLEDGE 1건 확인` 등이
> 대량 반복되는 구간이 있는데, 이는 **"Run existing test suite"(unittest)
> 스텝이 자체적으로 run_daily류 시나리오를 fixture로 재현하며 출력한
> 테스트 로그**였다(`th_seq_1`, `Post ID: th_custom`,
> `/tmp/tmpXXXX/batch_daily.json` 같은 가짜 값이 섞여 있어 식별 가능).
> `##[group]Run python3 scripts/run_daily.py` 마커 이후만 실제 실행이며,
> 위 표는 그 부분만 추출한 것이다.

## 2. history 상태

- **현재 파일 존재 여부**: 존재함 (`data/threads_publish_log.json`,
  origin/main 기준).
- **최근 기록**(origin/main 실제 내용, 3건 전부):

```json
[
  {
    "content_id": "content-f2082a27c88c26ca",
    "published_at": "2026-09-13T13:44:03.929530+00:00",
    "threads_post_id": "18114019807999154",
    "knowledge_id": "knowledge-da6ddf5aa459",
    "platform": "threads",
    "source_url": "https://blog.naver.com/tmong2/224407187378?fromRss=true&trackingCode=rss"
  },
  {
    "content_id": "content-b4b9a05c461ad595",
    "published_at": "2026-09-14T00:45:01.757008+00:00",
    "threads_post_id": "18099811769051475",
    "knowledge_id": "knowledge-da6ddf5aa459",
    "platform": "threads",
    "source_url": "https://blog.naver.com/tmong2/224407187378?fromRss=true&trackingCode=rss"
  },
  {
    "content_id": "content-45d8e97f0fab7b16",
    "published_at": "2026-09-15T01:12:52.467451+00:00",
    "threads_post_id": "18134252149645663",
    "knowledge_id": "knowledge-da6ddf5aa459",
    "platform": "threads",
    "source_url": "https://blog.naver.com/tmong2/224407187378?fromRss=true&trackingCode=rss"
  }
]
```

- **다음 실행에서 실제로 읽히는지**: 그렇다. 매 실행 로그에 `게시 중:
  자동 선택 (게시 이력에 없는 첫 valid 항목, content_id=...)`가 매번
  **새로운** content_id로 찍혔다는 것 자체가, 이전 실행들의 history를
  정상적으로 읽고 그걸 피해서 다음 항목을 골랐다는 직접 증거다. commit이
  매번 이전 커밋 위에 정확히 이어졌다(`b2b28d0→7833255→f2417fd→8350504`,
  파일이 override되지 않고 계속 append됨).

## 3. 코드 흐름

```
run_daily.py
  → load_knowledge_records + select_approved()   [순서 보존, 필터만 함]
  → run_media_batch(approved, provider=실제 LLM)   [approved 순서대로 KNOWLEDGE마다 Blog1+Shorts3+Threads5 생성]
  → publish_threads.py --auto
       → select_unpublished_threads_item(all_items, history)
            all_items를 "생성된 순서" 그대로 스캔 → platform=="threads" and status=="valid" and
            content_id not in history인 첫 항목 리턴
       → ThreadsClient.publish_text() 실제 게시
       → history.append(PublishRecord(...))
  → git add/commit/push (Actions 스텝)
```

| 단계 | 판정 |
|---|---|
| `run_daily` | **정상**. 3회 모두 정확히 이 스크립트가 실행됨(로그에서 직접 확인). |
| `run_media_batch` | **정상**. 실제 LLM 호출, 매번 4건 승인 KNOWLEDGE × 9 Draft = 36건 생성, valid 34~35건. |
| `publish_threads --auto` | **정상 동작하지만, 선택 알고리즘 자체가 "한 KNOWLEDGE를 다 쓸 때까지 다음으로 안 넘어가는" 구조**. `select_unpublished_threads_item()`은 `all_items`를 **생성 순서**(= 승인 KNOWLEDGE 파일 순서 × Blog→Shorts×3→Threads×5 고정 순서) 그대로 스캔하며 "이력에 없는 첫 valid Threads"를 고른다. `knowledge-da6ddf5aa459`가 승인 목록의 **0번째(가장 앞)**이고 매번 9/9 valid이므로, 이 KNOWLEDGE의 Threads 슬롯 5개가 모두 소진(발행)되기 전까지는 그 뒤에 있는 다른 3개 KNOWLEDGE(`knowledge-e1cc05264953` 등)의 Threads로 절대 넘어가지 않는다. |
| `PublishHistory` | **정상**. append/조회 모두 정확히 동작, 파일 손상·초기화 없음. |
| git commit/push | **정상**. 3회 모두 diff 있음 → commit → push 성공(원격에서 직접 확인). |

## 4. 원인 판정

**F. 매일 같은 KNOWLEDGE만 valid가 되어(정확히는 "가장 먼저" 선택되어)
반복 게시되는 구조적 문제 — 확정.**

근거(코드로 직접 재현):

```python
records = load_knowledge_records('data/tak_brain_knowledge.json')  # origin/main 기준
approved = select_approved(records)
# file_order_index=0 id=knowledge-da6ddf5aa459  ← 승인 목록의 맨 앞
# file_order_index=1 id=knowledge-e1cc05264953
# file_order_index=2 id=knowledge-da8e52862a79
# file_order_index=9 id=knowledge-a3f43f9bb62e
```

`knowledge-da6ddf5aa459`의 5개 Threads 초안(제목: "교훈에서 찾은 기준",
"경험으로 확인한 관찰", "실행에서 확인한 방법", "문제가 남긴 교훈",
"적용할 원칙")의 `compute_content_id()` 값을 로컬에서 재계산해보면
**정확히 3일간 실제로 게시된 content_id 3개와 100% 일치**한다(1~3번째
슬롯이 이미 소진, 4~5번째만 남음). 즉 내일도, 모레도 이 KNOWLEDGE가
계속 선택될 것이다 - 이 KNOWLEDGE 하나가 승인 목록의 가장 앞에 있고
항상 valid이기 때문이다.

부수적으로 **B의 성격도 일부 있음**: content_id/post_id는 매번 다르고
실제 텍스트도 다르지만, 5개 Threads가 전부 "개발을 모르는 내가 AI로
앱을 만든 경험" 하나의 KNOWLEDGE에서 나온 서로 다른 문장 인용일 뿐이라,
독자 입장에서는 "비슷한 이야기가 반복된다"고 느낄 수밖에 없는 구조다.
B를 "같은 내용의 재탕"이라는 좁은 의미로 본다면 아니지만(원문 자체는
매번 다름), "같은 소스 스토리의 반복"이라는 넓은 의미로는 사용자의
체감과 일치한다.

**A(같은 content_id 재선택), C(history 미저장), D(history가 다음
실행에서 사라짐), E(다른 workflow/코드 실행)는 전부 근거로 배제됨** -
위 1~3번 항목에서 각각 직접 반증됨(content_id 3개 모두 다름 / history
3건 모두 origin/main에 누적 확인됨 / 매 커밋이 이전 커밋 위에 정상적으로
쌓임 / 실행된 command가 로그에 `python3 scripts/run_daily.py`로 명시적으로
확인됨).

## 5. 수정 필요 여부

- **코드 버그는 아니다.** `PublishHistory`, `compute_content_id`,
  `select_unpublished_threads_item`, git commit/push 파이프라인 전부
  설계대로 정확히 동작하고 있다.
- **GitHub Actions 문제도 아니다.** workflow, secrets, checkout,
  commit/push 전부 정상.
- **데이터 문제에 가깝다**: 현재 승인된 KNOWLEDGE가 4건뿐이고, 그중
  하나가 우연히 파일 맨 앞에 있으며 5개의 Threads 슬롯을 갖고 있어
  "선입선출로 한 KNOWLEDGE를 다 쓸 때까지" 도달하는 데 최대 5일이
  걸린다.
- **더 근본적으로는 제품/설계 정책 문제**다: `select_unpublished_threads_item()`이
  "KNOWLEDGE 간 순환(rotation)"이 아니라 "생성 순서상 첫 valid" 방식으로
  설계되어 있다는 것 자체가, 승인 KNOWLEDGE 수가 적을 때 이런 편중을
  구조적으로 만든다.

## 6. 수정안 (코드는 수정하지 않음, 제안만)

가장 작은 수정 후보를 우선순위 순으로 제안한다(적용 여부는 별도 판단):

1. **(가장 작음, 운영 조치)** 승인 KNOWLEDGE를 더 확보한다 - 근본 원인
   (코드)을 안 건드려도, 승인 목록이 다양해지고 순서가 섞이면 자연히
   완화된다. 코드 변경 0줄.
2. **(작음)** `select_unpublished_threads_item()`이 "같은 knowledge_id의
   항목은 한 번 고른 뒤 뒤로 미루고, 서로 다른 knowledge_id를 우선"하도록
   1차 정렬 로직을 추가한다 - `content_engine/blog_publish_pack.py::select_blog_publish_candidates()`가
   이미 Blog에 대해 "서로 다른 KNOWLEDGE 우선" 로직을 갖고 있으므로, 그
   패턴을 Threads 선택에도 동일하게 적용하는 정도의 국소 수정.
3. **(선택)** `run_daily.py`/`publish_threads.py`에 "최근 N일 이내 같은
   knowledge_id 재게시 금지" 같은 쿨다운 규칙을 추가하는 것도 검토
   가능하나, 이는 새 정책 도입이라 위 2번보다 범위가 크다.

이번 단계에서는 위 어떤 것도 적용하지 않았다.

---

**수정하지 않음 / commit 없음 / push 없음**
