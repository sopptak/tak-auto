# TAK MEDIA Draft 영구 저장 누락 원인 조사 + 최소 수정 설계 (코드 수정 없음)

## 배경

오늘 실제 E2E 테스트(`SCOUT → 인터뷰 → KNOWLEDGE → 승인 → TAK MEDIA LLM 생성`)는
성공했다 (승인 KNOWLEDGE 1건, Draft 9건 생성, Valid 8 / Rejected 1 / Error 0).
그러나 실행 종료 후 이 9건의 Draft가 `data/` 아래 어떤 파일에도 남아있지 않다
(이전 조사 `docs/5-26_tak_media_20260919_result_check.md` 참고). 이 문서는
**왜** 사라졌는지 코드 추적으로 원인을 확정하고, 코드 수정 없이 설계안만 제시한다.

이 조사에서는 코드를 실행하지 않았고, LLM을 호출하지 않았고, 테스트도 실행하지
않았다 — 전부 정적 코드 읽기로만 확인했다.

---

## 1. 9개 Draft가 어디서 만들어지고 어디로 흘러가는지 추적

호출 체인 (`scripts/run_media_batch.py --execute` 기준):

```
scripts/run_media_batch.py (main)
  └─ content_engine.pipeline.run_media_batch_file(input_path, output_path, provider, ...)
        └─ tak_brain.load_knowledge_records()          # KNOWLEDGE 로드
        └─ tak_brain.select_approved()                 # 승인분만 필터
        └─ content_engine.pipeline.run_media_batch(records, provider)
              └─ (KNOWLEDGE 1건당) content_engine.generator.generate_content_bundle()
                    → ContentBundle(blog=1, shorts=3, threads=5)  = 9개 draft
              └─ (draft 9개마다) RewriteService.rewrite(knowledge, draft)
                    → content_engine.rewrite.RewriteResult
                      (validation_status: valid|rejected, validation_errors)
              └─ 9개 결과를 MediaBatchItem 9개로 감싸서
                 MediaBatchReport(items=...) 반환   ← 이 시점까지는 전부 메모리 내부
        └─ if output_path: report.save_json(output_path)   # ★ 유일한 저장 지점
  └─ print(report 요약)   # 화면에는 건수만 출력, 본문은 출력 안 함
```

핵심: **`MediaBatchReport`는 끝까지 순수 메모리 객체다.** 디스크에 쓰이는
유일한 경로는 `content_engine/pipeline.py:250-252`의
`if output_path: report.save_json(output_path)` 한 줄뿐이다.

```python
# content_engine/pipeline.py
def run_media_batch_file(..., output_path=None, ...):
    ...
    report = run_media_batch(records, service=service, provider=provider)
    if output_path:
        report.save_json(output_path)
    return report
```

## 2. 왜 `data/` 아래에 저장되지 않았는가

`scripts/run_media_batch.py`의 `--output` 인자를 보면:

```python
# scripts/run_media_batch.py:31-36
parser.add_argument(
    "--output",
    type=Path,
    default=None,             # ★ 기본값이 None
    help="배치 결과 저장 JSON 경로 (선택)",
)
```

`--output`이 **선택(optional) 인자이고 기본값이 `None`**이다. 오늘 실행에서
`--id knowledge-scout-6d1d0e2fa762 --execute`만 주고 `--output`을 명시하지
않았다면 (지금 파일 시스템 상태와 정확히 일치하는 시나리오다 — `docs/5-26_...md`에서
확인했듯 지식 승인 이후 어떤 새 파일도 생기지 않았다), `run_media_batch_file()`은
`output_path=None`을 받고, `if output_path:`가 거짓이 되어 `save_json()`이 아예
호출되지 않는다. 프로세스가 끝나면 `MediaBatchReport`와 그 안의 9개 `MediaBatchItem`
전부가 그냥 가비지 컬렉션된다.

즉 버그가 아니라 **"저장은 항상 opt-in"이라는 설계 자체가 원인**이다. 이 CLI는
"저장하지 않고 화면 확인만 하고 싶을 때"를 위해 `--output`을 선택 사항으로 뒀는데,
`--execute`(= 실제 LLM 호출, 즉 비용이 드는 실행)와 결합됐을 때도 똑같이
무저장이 기본값이라는 게 문제다. Dry-run(`--execute` 없음)은 애초에 비용이 없으니
무저장 기본값이 합리적이지만, `--execute` 실행은 결과를 잃으면 LLM 비용을 그냥
버리는 셈이다.

**추가로 발견한 두 번째, 별개의 문제**: 설령 오늘 `--output`을 지정했더라도,
`MediaBatchItem`(`content_engine/pipeline.py:20-34`) 자체에 **생성 시각 필드가
없다.**

```python
@dataclass(frozen=True)
class MediaBatchItem:
    knowledge_id: str
    platform: str
    status: str
    original_title: str
    original_body: str
    rewritten_title: str | None
    rewritten_body: str | None
    source_url: str
    evidence: tuple[str, ...]
    evidence_unit_ids: tuple[str, ...]
    rejection_reasons: tuple[str, ...] = ()
    error_message: str | None = None
    # created_at 없음
```

저장된 JSON에는 파일 자체의 mtime 말고는 "언제 생성됐는지"를 알 방법이 없고,
같은 경로에 다시 저장하면 그 mtime 정보마저 덮어써진다. 사용자가 요구한
"생성 시각 보존"은 `--output` 문제와 별개로 지금 구조로는 애초에 불가능하다.

## 3. 기존 채널별 저장 구조 조사 (재사용 가능성 검토)

`run_media_batch()`가 반환한 `MediaBatchReport`를 실제로 디스크에 남기는 경로는
현재 4갈래로 나뉘어 있고, 넷 다 "전부 저장"이 아니라 "필요한 것만 골라서 저장"이다.

| 진입점 | `MediaBatchReport` 저장 여부 | 저장 대상 | 비고 |
|---|---|---|---|
| `scripts/run_media_batch.py` | `--output` 줄 때만 | valid+rejected+error 전부 (raw report 그대로) | 오늘 문제의 직접 원인. `--output` 기본값 `None` |
| `scripts/run_daily.py` | 항상 (`--output` 기본값 `data/tak_media_batch_daily.json`) | valid+rejected+error 전부 | 코드 주석에 "매 실행마다 새로 생성/덮어쓰는 **휘발성** 파일, git 커밋 안 함"이라고 명시 — 하루 지나면 다음 실행이 덮어써서 이력이 안 남음 |
| `scripts/tak_auto.py` | 항상 (`--media-output` 기본값 `data/tak_media_batch_operator.json`) | valid+rejected+error 전부 | 역시 단일 슬롯, 재실행 시 덮어씀 |
| `scripts/generate_threads_draft.py` | **저장 안 함** (report는 메모리에서만 씀) | 9건 중 rotation으로 고른 **valid Threads 1건만** `content_engine/threads_review.py`의 `data/tak_threads_pending.json`에 upsert | 나머지 8건(blog 1, shorts 3, threads 4)은 valid든 rejected든 전부 버려짐 — 설계 의도(사람 검수용 draft 1개만 만드는 스크립트)상 당연한 동작이지 버그는 아님 |
| `scripts/generate_blog_publish_pack.py` / `content_engine/blog_publish_pack.py` | report 직접 `save_json` 가능(스크립트가 명시 호출) | valid Blog만, 최대 `DEFAULT_MAX_CANDIDATES=5`건 | rejected/error, 그리고 blog가 아닌 나머지 플랫폼은 pack에 안 들어감 |
| Shorts 전용 저장소 | **없음** | - | `content_engine/shorts_adapter.py`는 이미 valid한 `ShortDraft` 1개를 렌더러 입력(`ShortsScript`)으로 변환만 한다. Shorts 전용 pending/review JSON 저장소 자체가 존재하지 않는다 |

재사용 가치가 가장 높은 기존 구조: **`content_engine/threads_review.py`**
(`ThreadsPendingDraft` + `load_pending`/`save_pending`/`upsert_pending`,
상태 전이 `pending → approved → published/failed`, `tempfile` + `Path.replace()`
원자적 저장). 그리고 **`content_engine/publish_history.py::compute_content_id()`**
(`knowledge_id + platform + source_url + evidence_unit_ids + original_title +
original_body`로 결정적 해시를 만드는 함수 — rewritten 텍스트는 지문 계산에
안 쓰므로 재실행해도 같은 draft는 같은 id를 갖는다). 이 두 가지는 이미 Threads와
Blog가 "같은 draft 재실행 시 중복 처리 방지"에 실제로 쓰고 있는 검증된 패턴이다.

---

## 4. 최소 수정 설계안

목표 흐름 (사용자 지정):

```
KNOWLEDGE → TAK MEDIA 생성 → 모든 결과 저장(+validation) → Dashboard 확인
→ 사람이 수정/승인 → 승인된 것만 각 채널 발행(기존 파이프라인 그대로)
```

### 4-1. 새 저장소 1개 추가: "TAK MEDIA 생성 아카이브"

기존 파일들을 대체하지 않고 **그 앞단에** 하나 추가한다.

- 새 모듈: `content_engine/media_archive.py` (기존 `threads_review.py`와
  동일한 패턴 그대로 재사용 — JSON 배열 파일, `tempfile` + `Path.replace()`
  원자적 저장, `content_id` 기준 upsert).
- 새 저장 파일: `data/tak_media_archive.json`.
- 레코드 필드 (요구사항 1:1 대응):
  - `content_id` (`compute_content_id()` 재사용 — 새로 계산 방식 만들지 않음)
  - `knowledge_id` (보존)
  - `platform` (`blog`/`shorts`/`threads` 구분)
  - `generation_status` (`valid`/`rejected`/`error` — 기존 `MediaBatchItem.status` 그대로)
  - `original_title` / `original_body` (LLM 재작성 전 원본 draft)
  - `rewritten_title` / `rewritten_body` (LLM 생성문 그대로)
  - `validation_errors` / `error_message` (반려/오류 사유 그대로 보존)
  - `source_url`, `evidence`, `evidence_unit_ids` (보존)
  - `created_at` (신규 — 배치 실행 1회당 타임스탬프 1개를 9개 항목이 공유해도 충분)
  - `review_status` (신규, 이 아카이브만의 필드: `unreviewed`/`approved`/`dismissed`,
    기본값 `unreviewed`) — **`generation_status`(LLM 검증 결과)와 `review_status`
    (사람 검수 결과)를 분리한다.** rejected여도 `review_status`는 그대로
    `unreviewed`로 남아 "왜 반려됐는지" 사람이 나중에 볼 수 있다.

### 4-2. 연결 지점: 새 함수 1개, 각 CLI에서 명시적으로 호출

`run_media_batch()`/`run_media_batch_file()`의 시그니처는 건드리지 않는다
(기존 테스트들이 이 함수들을 직접 호출하므로, 시그니처를 바꾸면 불필요하게
넓은 범위에 영향을 준다). 대신:

```python
# content_engine/media_archive.py (신규, 개념 스케치 — 실제 구현 아님)
def archive_report(report: MediaBatchReport, path: Path | str, created_at: str) -> None:
    """report.items 전부(valid+rejected+error)를 content_id 기준 upsert로 저장한다."""
```

그리고 `run_media_batch()`를 호출하는 **각 스크립트**(`run_media_batch.py`,
`run_daily.py`, `tak_auto.py`, `generate_threads_draft.py`,
`generate_blog_publish_pack.py`)에서, report를 받은 직후 한 줄만 추가한다:

```python
archive_report(report, ROOT / "data" / "tak_media_archive.json", utc_now())
```

이렇게 하면:
- `generate_threads_draft.py`가 rotation으로 1건만 골라 `tak_threads_pending.json`에
  넣기 **전에** 9건 전부가 이미 아카이브에 남는다 — 지금처럼 나머지 8건이
  통째로 사라지는 일이 없어진다.
- `run_media_batch.py`는 `--output`을 안 줘도(오늘 발생한 시나리오) 아카이브에는
  항상 남는다 — `--output`은 "이번 실행 결과만 따로 보고 싶을 때 쓰는 스냅샷",
  아카이브는 "TAK MEDIA가 지금까지 만든 모든 것의 누적 로그"로 역할이 분리된다.
- `run_daily.py`/`tak_auto.py`가 매번 덮어쓰는 단일 슬롯 파일 문제도, 아카이브가
  `content_id` 기준 upsert(추가 누적)라서 자연히 해결된다.
- 기존 발행 로직(`threads_review.py`, `blog_publish_pack.py`,
  `publish_history.py`, `shorts_adapter.py`, 실제 Threads/YouTube/Naver 발행
  코드)은 **한 줄도 안 바뀐다.**

### 4-3. Dashboard: 읽기 전용 확인 + "승인" 액션만 추가

`scripts/run_scout_dashboard.py`는 이미 `--pending`/`--sessions`/`--skipped`처럼
여러 JSON 저장소를 인자로 받아 읽고 쓰는 패턴이 있으므로, 같은 패턴으로
`--media-archive` 인자(기본값 `data/tak_media_archive.json`)를 추가하고:

1. **목록 화면**: 아카이브를 `knowledge_id`/`platform`별로 묶어서 원문·재작성문·
   validation 결과(반려 사유 포함)를 그대로 렌더링만 한다 (새 비즈니스 로직 없음).
2. **승인 액션**: `generation_status == "valid"`인 항목에 대해서만 노출.
   눌렀을 때 하는 일은 **딱 하나** — 아카이브의 `review_status`를 `approved`로
   바꾸고, **플랫폼에 맞는 기존 검수 대기열로 그대로 넘긴다**:
   - `platform == "threads"` → `content_engine.threads_review.upsert_pending(...)`
     호출 (지금 `generate_threads_draft.py`가 하는 것과 동일한 호출, 새 로직 아님).
   - `platform == "blog"` → 기존 `content_engine.blog_publish_pack` 후보 목록에
     포함되도록 표시만 함 (실제 pack 생성/게시는 기존 스크립트가 그대로 담당).
   - `platform == "shorts"` → `content_engine.shorts_adapter`가 읽어갈 수 있게
     "승인됨" 표시만 함 (렌더링/업로드는 기존 코드 그대로).
3. **발행은 여전히 건드리지 않는다** — 승인 액션은 "아카이브 → 기존 채널별
   대기열"로 옮기는 것으로 끝난다. 실제 Threads API 호출/Naver 게시/YouTube
   업로드는 지금 그대로 사람이 기존 스크립트(`publish_threads.py`,
  `mark_blog_published.py`, `upload_youtube_short.py`)로 수행한다. 자동 발행은
  추가하지 않는다.

### 4-4. 이 설계가 "최소 수정"인 이유

- `content_engine/generator.py`, `content_engine/rewrite.py` (생성/검증 로직) — **무수정**.
- `content_engine/pipeline.py`의 `run_media_batch`/`run_media_batch_file` 시그니처 — **무수정**
  (단, `MediaBatchItem`에 `created_at` 필드 추가는 필요 — 아카이브가 아니라 이
  dataclass 쪽에 두는 이유는, "생성 시각"이 애초에 report 자체의 속성이지
  아카이브만의 부가 정보가 아니기 때문. 이 필드 하나만 기존 dataclass에 추가하면
  `--output`으로 저장하는 기존 JSON에도 자동으로 생성 시각이 남는 부수 효과가 있다).
- 실제 발행 코드(`threads_publisher.py`, `youtube_publisher.py`, Naver 게시 절차) — **무수정**.
- 새로 추가하는 것은 모듈 1개(`content_engine/media_archive.py`, 기존
  `threads_review.py`를 그대로 본뜬 형태)와, 각 CLI 스크립트에 한 줄씩 추가하는
  명시적 `archive_report(...)` 호출, 그리고 Dashboard에 읽기 전용 화면 + 승인
  버튼 1개뿐이다.

---

## 5. 회귀 테스트 제안 (오늘 문제 재발 방지)

오늘 문제의 본질은 **"`--execute`로 실제 LLM을 호출해 Draft를 만들었는데,
프로세스 종료 후 그 결과를 담은 파일이 하나도 존재하지 않는다"**는 것이다.
이걸 직접 코드로 표현하면 좋은 회귀 테스트가 된다.

1. **아카이브 유닛 테스트** (`tests/test_media_archive.py`, 신규)
   - `MockRewriteProvider`(실제 LLM 호출 없음, 기존 테스트들과 동일한 관례)로
     `run_media_batch()`를 돌려 9개 item(valid 8 + rejected 1 같은 조합)을 만든 뒤,
     `archive_report(report, tmp_path, created_at)`을 호출.
   - 저장된 JSON에 **9개 전부**(valid + rejected + error 포함)가 들어있는지,
     각 항목에 `created_at`·`knowledge_id`·`validation_errors`가 보존됐는지 확인.
   - 같은 `content_id`로 두 번째 `archive_report()`를 호출했을 때 중복 추가가
     아니라 upsert(덮어쓰기)되는지 확인 (기존 `threads_review.py`
     `upsert_pending` 테스트와 동일한 형태).

2. **"저장 안 하면 안 된다"는 정책을 직접 검증하는 회귀 테스트**
   (`tests/test_run_media_batch_cli.py`, 신규 또는 `tests/test_media_batch.py`에 추가)
   - 오늘처럼 `--id <knowledge>`만 주고 `--output`을 주지 않는 상황을 재현.
     단, 실제 `--execute`(진짜 LLM 호출)는 테스트에서 쓰면 안 되므로, CLI를
     그대로 subprocess로 부르는 대신 **`run_media_batch_file()`을
     Python API로 직접 호출**(`provider=MockRewriteProvider()`, `output_path=None`,
     `archive_path=<tmp 경로>`처럼)하는 방식으로 검증한다 — 이미
     `tests/test_media_batch.py`/`test_blog_publish_pack.py`가 이 방식(subprocess가
     아니라 직접 함수 호출 + `MockRewriteProvider`)을 쓰고 있어 관례에 맞는다.
   - 단언(assert) 내용: `output_path=None`이어도 아카이브 파일에는 9개 항목이
     전부 남아있어야 한다 — 즉 "출력 경로를 깜빡해도 결과 자체는 사라지지 않는다"를
     테스트로 고정한다.
   - 추가로, `MediaBatchItem`에 `created_at`이 항상 채워지는지(빈 문자열/`None`이
     아닌지)도 같은 테스트에서 확인 — 오늘 확인된 "생성 시각 보존 안 됨" 문제의
     재발도 함께 막는다.

3. **기존 `generate_threads_draft.py` 관련 테스트 보강**
   - `tests/test_scout_pipeline_e2e.py` 등 기존 e2e 테스트가 이미
     `run_media_batch()`를 호출하는 지점에서, "rotation으로 선택되지 않은 나머지
     draft들도 아카이브에는 남아있다"는 assert를 추가하면, 향후 rotation 로직이
     바뀌어도 "선택 안 된 draft가 통째로 유실"되는 회귀를 잡을 수 있다.

이 세 테스트는 전부 `MockRewriteProvider`만 쓰고 실제 LLM API를 호출하지
않으므로, "LLM 재호출 금지"와 무관하게 회귀 방지 목적에 충분하다 (실제
구현 단계에서 이 테스트들을 작성/실행할지는 사용자 승인 후 진행 — 지금은
설계 제안까지만).

---

## 요약

| 항목 | 원인/현황 | 최소 수정 제안 |
|---|---|---|
| 오늘 9개 Draft 유실 | `scripts/run_media_batch.py --output` 기본값이 `None`이라 저장 자체가 안 됨 (`content_engine/pipeline.py:251-252`) | `content_engine/media_archive.py` 신규 + 각 CLI에서 `archive_report()` 명시 호출 |
| 생성 시각 없음 | `MediaBatchItem`에 timestamp 필드 자체가 없음 | `MediaBatchItem`에 `created_at` 필드 1개 추가 |
| Rejected 사유 유실 | 기존 채널별 저장소(threads_review, blog_publish_pack)는 valid만 저장 | 아카이브는 `generation_status` 그대로 보존(valid/rejected/error 전부) |
| 채널 구분 | 이미 `MediaBatchItem.platform`으로 구분됨 (변경 불필요) | 아카이브도 동일 필드 재사용 |
| 기존 Threads 검수 구조 재사용 | `content_engine/threads_review.py` 패턴(원자적 JSON, 상태 전이)이 그대로 재사용 가능 | 아카이브 모듈을 이 패턴으로 구현, 승인 시 기존 `upsert_pending()` 그대로 호출 |
| 발행 기능 | 무수정 대상 | 승인 액션은 "아카이브 → 기존 채널별 대기열"까지만, 실제 발행/자동 발행은 손대지 않음 |
