# 5-11 — Threads "티몽 최종 검수 후 발행" 반자동 전환 설계

> **이 문서는 설계/분석 전용이다.** 코드 수정, git commit/push, 실제 Threads 발행을
> 전혀 하지 않았다. 아래 내용은 모두 기존 코드를 실제로 읽고 분석한 결과에 근거한다.

---

## 0. 읽은 파일 목록 (실제 구조 확인)

- `scripts/run_daily.py`, `scripts/publish_threads.py`
- `content_engine/publish_history.py`, `content_engine/generator.py`,
  `content_engine/rewrite.py`, `content_engine/models.py`,
  `content_engine/pipeline.py`, `content_engine/threads_publisher.py`,
  `content_engine/__init__.py`
- `scripts/run_scout_dashboard.py`, `scripts/tak_auto.py`
- `tak_scout/dashboard_state.py`, `tak_scout/interview_session.py`, `tak_scout/__init__.py`
- `.github/workflows/daily-threads-post.yml`
- `docs/5-10_phase4_4_threads_rotation.md`, `docs/5-10_phase4_3_finance_blog_safety.md`
- Threads 관련 테스트 전체: `tests/test_threads_publisher.py`(11개),
  `tests/test_publish_threads_auto_select.py`(13개),
  `tests/test_publish_history.py`(23개, rotation 8개 포함)
- `.gitignore`, `git ls-files data/` (어떤 데이터 파일이 실제로 git에 커밋되는지 확인)

---

## 1. 현재 자동 발행 구조

```
[GitHub Actions: daily-threads-post.yml, 매일 KST 08:00]
  1. actions/checkout (fresh clone, stateless)
  2. python3 -m unittest discover  ← 실패하면 이후 스텝 전부 skip
  3. python3 scripts/run_daily.py
       ├─ tak_brain.load_knowledge_records + select_approved   (승인 KNOWLEDGE 로드)
       ├─ content_engine.pipeline.run_media_batch(provider=실제 LLM)
       │     → 승인 KNOWLEDGE 1건당 Blog 1 + Shorts 3 + Threads 5 생성 + LLM 재작성 + RewriteValidator 검증
       ├─ report.save_json(data/tak_media_batch_daily.json)   ← 휘발성, git 비커밋
       └─ scripts/publish_threads.py --auto --history data/threads_publish_log.json
             ├─ select_unpublished_threads_item()  ← rotation 정책 (5-10 Phase 4-4)
             ├─ ThreadsClient.from_environment().publish_text()  ← 실제 API 호출 ★
             └─ 성공 시에만 PublishHistory.append()
  4. git add data/threads_publish_log.json; diff 있으면 commit + push
```

핵심 관찰:

- **"생성"과 "실제 발행"이 `run_daily.py` 한 프로세스 안에서 분리 불가능하게 묶여
  있다.** `publish_threads_main(publish_argv)`(`scripts/run_daily.py:155`)가 선택과
  게시를 동시에 수행하는 `--auto` 경로를 그대로 호출한다.
- `THREADS_ACCESS_TOKEN`은 **GitHub Actions Secrets에만 존재**한다
  (`.github/workflows/daily-threads-post.yml:79`, `:88`). 로컬 Codespace 환경변수나
  코드 어디에도 하드코딩되어 있지 않다 — `ThreadsClient.from_environment()`
  (`content_engine/threads_publisher.py:99-109`)가 매 실행마다 환경변수에서 읽는다.
- **GitHub Actions는 완전히 stateless다.** 매 실행마다 `git init` + `git checkout
  origin/main`으로 새로 시작한다(오늘 실제 워크플로 로그에서 확인:
  `Deleting the contents of '.../tak-auto'` → `Initialized empty Git repository`).
  따라서 실행 간에 살아남는 유일한 상태는 **git에 커밋된 파일**뿐이다. 이것이 기존
  워크플로가 `data/threads_publish_log.json`을 굳이 commit+push하는 이유다.
- rotation 정책(`select_unpublished_threads_item`, 5-10 Phase 4-4)은 실제 운영에서
  검증 완료됨(`docs/5-10_phase4_4_threads_rotation.md`) — 이번 설계에서 **절대
  건드리지 않는다.**
- `compute_content_id()`(`content_engine/publish_history.py:26-47`)는
  `knowledge_id/platform/source_url/evidence_unit_ids/original_title/original_body`
  만으로 계산하고, **`rewritten_title`/`rewritten_body`는 의도적으로 제외**한다
  (LLM 호출마다 문구가 달라져도 같은 콘텐츠로 취급하기 위함). 이 설계 결정이
  아래 7장 content_id 정책의 근거가 된다.
- `PublishHistory`는 "성공 게시만 기록하는 append-only 로그"다
  (`PublishRecord` 클래스 docstring: "실제 게시 성공 후에만 생성되어야 한다").
  `scripts/publish_threads.py:159-174`에서 `client.publish_text()`가 성공한 뒤에만
  `history.append()`가 호출된다 — 실패 시 history는 전혀 건드리지 않는다.
- `data/*.json`은 기본적으로 `.gitignore`되어 있고, 화이트리스트로 예외 처리된
  파일만 git에 커밋된다(`.gitignore:5-9`): 현재 `tak_brain_knowledge.json`,
  `tak_media_batch_e2e_test.json`, `threads_publish_log.json`,
  `blog_publish_log.json`, `scout_sources.json`만 추적 대상이다. TAK SCOUT
  Dashboard가 쓰는 `tak_interview_sessions.json` 등은 **로컬 전용**(git 비추적)이다
  — 이는 TAK SCOUT Dashboard가 GitHub Actions와 전혀 연동되지 않기 때문에 가능한
  구조다.

---

## 2. 반자동 운영 목표

> "AI가 초안을 만들고, 티몽이 10~20초 정도 읽고 필요하면 직접 수정한 뒤 발행한다."

요구 UX 13개 항목(1~13, 사용자 메시지 원문)을 그대로 목표로 삼는다. 핵심은:

1. **생성과 발행 사이에 반드시 "사람의 확인"이라는 강제 관문이 생긴다.**
2. 수정 여부와 무관하게 "이것이 최종 텍스트"라고 사람이 확정한 것만 게시된다.
3. 화면은 "AI가 쓴 글을 다듬는 편집기"처럼 단순해야 하고, 개발자용 정보(SOURCE
   FACT/KNOWLEDGE/USER ORIGINAL THOUGHT 등)는 기본 숨김.
4. 금융/대출/부동산 안전장치(Validator, 경계 문구 보존)와 rotation/중복 방지는
   그대로 유지.

---

## 3. 현재 구조의 문제점 (반자동 전환 관점)

| # | 문제 | 근거 |
|---|---|---|
| 1 | 생성 즉시 발행되어 사람이 개입할 시점 자체가 없다 | `run_daily.py:144-155` |
| 2 | AI 초안(규칙 기반 템플릿 + LLM 재작성)이 티몽 특유의 자연스러운 문체와 다를 수 있음(요구사항 8, 9) | `content_engine/generator.py`의 고정 문구 템플릿(`_quote()`, `"작성자는 ~고 적었습니다"` 등) |
| 3 | 실제로 티몽이 손대면 더 자연스러워졌다는 관찰 사례가 이미 있음(요구사항 9) — 즉 "사람 최종 편집"이 품질에 실질적으로 기여한다는 증거가 이미 확보됨 | 사용자 제공 정보 |
| 4 | 발행 판단을 사람이 위임하고 싶어도, 현재 아키텍처에는 "승인 대기" 상태 자체가 없음 | `MediaBatchItem.status`는 `valid/rejected/error`뿐, `PublishHistory`는 성공 로그뿐 — "검토 대기" 개념이 어느 데이터 구조에도 없음 |
| 5 | Dashboard가 Threads API를 직접 부르게 하면 토큰을 Dashboard 실행 환경(로컬 Codespace, 향후 클라우드)에도 심어야 함 → 토큰 노출 지점이 2배로 늘어남 | `THREADS_ACCESS_TOKEN`은 현재 GitHub Actions Secrets에만 존재 |
| 6 | GitHub Actions는 stateless이고 Dashboard(로컬/클라우드)와 별개 환경이므로, "승인" 이벤트를 Actions에 전달할 방법이 git commit/push 외에는 마땅치 않음 | 오늘 세션에서 실제로 `gh workflow run`이 `403 Resource not accessible by integration`으로 실패한 것을 직접 확인(Codespace 기본 GitHub App 토큰은 `workflow_dispatch` 호출 권한이 원천적으로 없음) |

6번은 이번 설계에서 실제로 부딪힌 제약이라 매우 중요하다 — 10장/11장/13장에서
이 제약을 정면으로 반영한 구조를 제안한다.

---

## 4. UX 흐름

```
[매일 08:00 KST, GitHub Actions "생성" 워크플로]
      │  TAK BRAIN 승인 KNOWLEDGE 로드
      │  TAK MEDIA 배치 실행 (Blog/Shorts/Threads 9종, 기존 로직 그대로)
      │  select_unpublished_threads_item() 으로 "오늘의 Threads 후보" 1건 선정 (rotation 그대로)
      │  ⚠ 이 시점에 Threads API는 절대 호출하지 않는다
      ▼
data/tak_threads_pending.json  (status: pending, git commit + push)
      │
      ▼
[티몽이 아무 때나 브라우저에서 Dashboard 접속]
      │  화면: 오늘의 초안 1건 카드 (제목 + 본문, 편집 가능한 텍스트 영역)
      │  기본 표시: AI 재작성 결과(rewritten_body)만. SOURCE FACT/KNOWLEDGE ID/
      │            evidence_unit_ids는 "자세히 보기" 접힘 안에만.
      │  10~20초 내 판단:
      │    A. 그대로 [승인 및 발행] 클릭 → 원본 그대로 최종 텍스트로 확정
      │    B. 텍스트 직접 수정 → [승인 및 발행] 클릭 → 수정본이 최종 텍스트로 확정
      ▼
data/tak_threads_pending.json 갱신 (status: approved, final_title/final_body 확정)
      │  Dashboard가 git commit + push (Phase 2부터, 아래 13장 참고)
      ▼
[push 트리거 GitHub Actions "발행" 워크플로]
      │  status == approved 인 항목 1건을 찾음
      │  ThreadsClient.publish_text() 호출 (기존 코드 100% 재사용)
      │  성공 → PublishHistory.append() (기존 계약 그대로) + pending 항목 status: published
      │  실패 → PublishHistory 불변 + pending 항목 status: failed (+ 사유 기록, 재승인 가능)
      ▼
data/threads_publish_log.json, data/tak_threads_pending.json 갱신 (git commit + push)
```

"10~20초" 목표는 **승인 클릭까지의 시간**이다 — 실제 게시 완료 타이밍(다음 push
트리거 실행까지 보통 1~2분)은 별개이며, 이는 16장에서 정직하게 다룬다.

---

## 5. 상태 모델

기존 `MediaBatchItem.status`(`valid/rejected/error`, 생성 파이프라인 내부 개념)와
절대 혼동되지 않도록, pending draft 전용의 새 상태 필드를 만든다. 사용자가 예시로
제안한 4개 상태를 그대로 채택한다 — 더 세분화하지 않는 것이 "기존 구조와 충돌하지
않는 가장 단순한 모델"이라는 요구에 부합한다.

```
pending ──[승인 클릭]──▶ approved ──[발행 워크플로 성공]──▶ published (종결)
                              │
                              └──[발행 워크플로 실패]──▶ failed ──[재승인]──▶ approved (재시도)
```

- **pending**: 생성 워크플로가 방금 만든, 아직 티몽이 보지 않은 초안.
- **approved**: 티몽이 (수정했든 안 했든) 최종 텍스트를 확정한 상태. 발행 대기 큐.
- **published**: 발행 워크플로가 Threads API 호출에 성공. `PublishHistory`에도
  이 순간 동시에 기록됨. **종결 상태 — 재발행 대상에서 영구 제외.**
- **failed**: 발행 워크플로가 Threads API 호출에 실패(네트워크 오류, 500 등).
  `PublishHistory`는 건드리지 않음(기존 계약 유지). 티몽이 Dashboard에서 다시
  승인하면 `approved`로 되돌아가 재시도 가능.

`pending`/`approved`는 "아직 발행 안 됨"이라는 점에서 `select_unpublished_threads_item`의
"이미 게시된 content_id" 판단(=`PublishHistory` 기준)과 전혀 간섭하지 않는다 —
`PublishHistory`는 오직 `published`가 될 때만 갱신되기 때문이다(8장 참고).

---

## 6. 데이터 구조

새 파일 `data/tak_threads_pending.json` (git 추적 대상으로 `.gitignore` 화이트리스트에
추가 필요). 구조는 기존 `PublishRecord`/`InterviewSession` 패턴(dataclass +
`to_dict`/`from_dict` + tempfile 원자적 저장)을 그대로 따른다.

```jsonc
[
  {
    "content_id": "content-ff8909844fa80b99",      // compute_content_id() 그대로 재사용 (7장)
    "knowledge_id": "knowledge-e1cc05264953",
    "source_url": "https://example.com/original-post",
    "evidence_unit_ids": ["lesson:1", "reusable_principle:1"],

    // 개발자 정보 (Dashboard 기본 화면에서는 숨김, "자세히 보기"에서만 노출)
    "original_title": "원문이 제시한 판단",           // 규칙 기반 템플릿 원본
    "original_body": "\"...\"",

    // AI 초안 (LLM 재작성 결과) — Dashboard 기본 표시 대상
    "ai_rewritten_title": "원문이 제시한 판단",
    "ai_rewritten_body": "은행 대출 심사에서는...",

    // 최종 발행 텍스트 — 승인 시점에 확정. 수정 안 했으면 ai_rewritten_*와 동일하게 복사.
    "final_title": "은행 대출, 이렇게 준비하세요",
    "final_body": "은행 대출 심사에서는... (티몽이 다듬은 문장)",
    "edited_by_user": true,

    "status": "approved",
    "created_at": "2026-09-16T23:00:12+00:00",
    "approved_at": "2026-09-16T23:04:31+00:00",
    "published_at": null,
    "failed_at": null,
    "failure_reason": null,
    "threads_post_id": null
  }
]
```

- 목록(list) 구조로 유지하되, 실제로는 **미해결(pending/approved) 상태가 항상
  0~1개**가 되도록 생성 로직에서 강제한다(9-1장 idempotency). `published`/`failed`
  이력은 목록에 계속 쌓이므로, `PublishHistory`처럼 append-only 감사(audit) 기록
  역할도 겸한다.
- `article_type`/`knowledge_type`을 필드로 추가해 두면(생성 시점에 함께 저장)
  Dashboard가 금융 콘텐츠 경고 배너를 띄울 때 KNOWLEDGE를 다시 조회할 필요가
  없다 — 이 필드는 표에는 생략했지만 실제 구현 시 포함 권장.

---

## 7. content_id 정책 (요구사항 13번 검토)

**결론: 사용자의 텍스트 수정 여부와 무관하게 content_id는 그대로 유지한다.
새로 계산하지 않는다.**

근거는 이미 `compute_content_id()` 자체의 설계에 있다
(`content_engine/publish_history.py:26-47`):

```python
fingerprint_source = {
    "knowledge_id": ..., "platform": ..., "source_url": ...,
    "evidence_unit_ids": [...],
    "original_title": ..., "original_body": ...,   # ← rewritten_* 아님
}
```

`rewritten_title`/`rewritten_body`는 애초에 지문 계산에서 **의도적으로 제외**되어
있다(주석: "LLM 호출마다 결과가 달라질 수 있으므로 식별자 계산에 사용하지 않는다").
사람의 편집은 개념적으로 "아주 정교한 rewrite 한 번 더"에 불과하며, 이미 존재하는
이 설계를 그대로 연장하면 된다:

- content_id는 **"어떤 KNOWLEDGE의 어떤 evidence_unit들에서 나온 콘텐츠인가"**라는
  근거(evidence) 정체성만 추적하고, 표현(문구)이 AI든 사람이든 바뀌는 것은 추적
  대상이 아니다.
- 이 정책을 따르면 요구사항 10번("이미 발행된 content_id는 다시 발행하지 않는다")과
  14번("실제 게시 이후 동일 콘텐츠 재게시 방지")이 **코드 변경 없이 자동으로
  성립**한다 — 사람이 아무리 문장을 고쳐도 같은 `original_*`/`evidence_unit_ids`인
  이상 같은 content_id이므로, 이미 `published`된 항목은 `PublishHistory.is_published()`에
  걸려 rotation 후보에서 영구 제외된다.
- **트레이드오프**: 티몽이 같은 evidence를 완전히 다른 관점으로 다시 쓰고 싶어도
  "이미 발행된 콘텐츠"로 취급되어 재선정되지 않는다. 이는 의도된 안전장치(중복
  발행 방지가 최우선)이며, 이번 설계 범위에서는 허용 가능한 제약으로 판단한다.
  필요해지면 "강제로 새 content_id 발급" 같은 예외 경로를 별도 Phase에서 검토할
  수 있으나, 지금 도입하면 불필요한 복잡도가 생긴다(요구사항: "가장 단순한 상태
  모델").
- `content_engine/publish_history.py`는 **한 글자도 수정하지 않는다** — `compute_content_id`,
  `select_unpublished_threads_item`, `_used_knowledge_ids` 전부 기존 그대로 재사용.

---

## 8. PublishHistory와의 관계

**`PublishHistory`/`PublishRecord`는 전혀 수정하지 않는다.** pending draft
데이터 구조는 완전히 별도 파일(`data/tak_threads_pending.json`)에 존재하며, 둘의
관계는 다음 한 방향으로만 연결된다:

```
발행 워크플로가 ThreadsClient.publish_text() 성공
        │
        ├──▶ PublishHistory.append(PublishRecord(content_id, ...))   (기존 함수 그대로)
        └──▶ pending 항목의 status를 published로 갱신 (새 모듈의 책임)
```

- **성공 시에만** 두 파일이 함께 갱신된다(같은 워크플로 실행, 같은 커밋에 담아도
  됨).
- **실패 시** `PublishHistory`는 절대 건드리지 않는다(기존 `scripts/publish_threads.py:170-174`의
  "게시는 성공했지만 이력 저장 실패" 방어 로직과 동일한 원칙: 이력 파일은
  "실제로 게시된 것"의 정확한 진실 소스여야 한다) — 대신 pending 항목만
  `failed`로 표시한다.
- rotation 판단(`select_unpublished_threads_item`)은 여전히 `PublishHistory`만
  보고 동작한다 — pending/approved 상태의 draft가 있어도 rotation 로직 자체는
  전혀 알 필요가 없다(9-1장에서 생성 단계가 별도로 idempotency를 챙긴다).

---

## 9. Dashboard 설계

### 9-1. 생성 스크립트: `scripts/generate_threads_draft.py` (신규)

`run_daily.py`의 1~3단계(TAK BRAIN 로드 → TAK MEDIA 배치 → rotation 선정)를 **그대로
재사용**하되, 마지막에 `scripts/publish_threads.py`를 호출하는 대신 pending 파일에
쓰기만 한다.

```
승인 KNOWLEDGE 로드 (tak_brain, 무수정)
  → run_media_batch(provider=실제 LLM, 무수정)
  → valid Threads 항목들 추출
  → select_unpublished_threads_item(items, history)   ← rotation 그대로 재사용, 무수정
  → 선택된 항목이 있고, pending 파일에 "미해결(pending/approved)" 항목이 하나도 없으면:
        새 pending 레코드 생성 (status=pending)
    이미 미해결 항목이 있으면:
        아무것도 하지 않고 "오늘은 이미 검토 대기 중인 초안이 있습니다" 로그만 출력
        (요구사항 4번: 재실행 시 중복 생성 방지)
```

이 스크립트는 **`ThreadsClient`를 import조차 하지 않는다** — 실수로라도 실제
게시가 일어날 코드 경로 자체가 존재하지 않도록 원천 차단한다("Validator를
우회하는 구조를 만들지 않는다"는 원칙과 같은 정신으로, "발행 코드가 물리적으로
없으면 우회할 수도 없다").

### 9-2. 발행 스크립트: `scripts/publish_approved_threads.py` (신규)

```
pending 파일에서 status == "approved" 인 항목 1건을 찾음
  없으면: "발행할 승인된 항목 없음" 로그, 정상 종료(exit 0)
  있으면:
    ThreadsClient.from_environment().publish_text(final_body)  ← 기존 클라이언트 그대로
    성공 → PublishHistory.append(...) + pending 항목 status=published, threads_post_id 기록
    실패 → pending 항목 status=failed, failure_reason 기록 (PublishHistory 불변)
```

`scripts/publish_threads.py`의 게시/이력기록 로직(라인 150-176)을 함수로 추출해
공유하거나, 최소한 동일한 호출 순서(프로필 확인 → publish_text → 성공 시에만
history.append)를 그대로 복제한다 — 이 부분의 안전 계약을 새로 발명하지 않는다.

### 9-3. Dashboard: `scripts/run_threads_review_dashboard.py` (신규)

`scripts/run_scout_dashboard.py`와 **완전히 동일한 패턴**을 따른다: Python 표준
`http.server`만 사용, 프레임워크 없음, `127.0.0.1` 기본 바인딩, 서버 없이 테스트
가능한 순수 함수(`handle_*`)와 HTTP 핸들러를 분리.

화면은 딱 1개(단순함 요구사항):

```
┌─────────────────────────────────────────────┐
│  오늘의 Threads 초안                          │
│                                               │
│  ┌─────────────────────────────────────┐    │
│  │ [본문 textarea, AI 재작성 결과가      │    │
│  │  기본으로 채워져 있음. 자유 편집 가능] │    │
│  └─────────────────────────────────────┘    │
│                                               │
│  ⚠ 금융 관련 콘텐츠입니다. 공식 심사 기준     │  ← article_type=="finance"일 때만
│    관련 문구를 지우지 않도록 주의하세요.      │
│                                               │
│  [ 승인 및 발행 ]        ▶ 자세히 보기(개발자용) │
└─────────────────────────────────────────────┘
```

- **[승인 및 발행]** 버튼 하나로 "수정 안 함"과 "수정함"을 통합한다(요구사항 5, 6) —
  폼 제출 시 textarea의 현재 값을 그대로 `final_body`로 저장하므로, 사용자가
  아무것도 안 건드렸으면 AI 원본 그대로, 뭔가 고쳤으면 고친 그대로 확정된다.
  별도의 "그대로 승인" / "수정 후 승인" 버튼을 나누지 않는 것이 더 단순하고
  실수 여지가 적다.
- **자세히 보기**는 `<details>` 태그로 접어 둔다 — SOURCE FACT(=`original_body`),
  KNOWLEDGE ID, `evidence_unit_ids`, `source_url` 등은 이 안에만 노출(요구사항:
  "필요할 때만 볼 수 있도록").
- 승인 클릭 시 서버 핸들러가 하는 일:
  1. pending 항목의 `final_title`/`final_body`를 폼 값으로 갱신, `edited_by_user`
     계산(polling `ai_rewritten_body`와 다르면 true).
  2. status를 `pending → approved`로 전이, `approved_at` 기록.
  3. (Phase 2부터) `git add data/tak_threads_pending.json && git commit && git push`
     자동 실행 — 13장 참고.
  4. "승인 완료. 곧 발행됩니다" 배너와 함께 같은 화면 재표시.
- **Validator와의 관계** (안전 vs 자유 편집의 긴장 해소): `RewriteValidator`를
  발행을 막는 게이트로는 재사용하지 않는다(그러면 "사람이 자유롭게 고칠 수
  있어야 한다"는 목표와 정면 충돌). 대신 `find_finance_boundary_sentence()`
  (`content_engine/rewrite.py:36-48`, 이미 공개 함수로 존재)를 **경고 배너
  용도로만** 재사용한다 — `article_type == "finance"`인데 최종 텍스트에 그
  문장이 없으면 화면에 경고만 띄우고, 발행 자체를 막지는 않는다. 최종 책임은
  "사람이 확인했다"는 사실로 넘어간다는 것이 이번 반자동화의 근본 취지이기
  때문이다. Threads 500자 제한처럼 **API 자체의 하드 제약**은 기존 그대로
  유지된다(`ThreadsClient.publish_text`가 이미 체크, 우회 불가능한 물리적
  제약이므로 "Validator 우회"와는 다른 층위).

---

## 10. GitHub Actions 설계

기존 `daily-threads-post.yml`은 **즉시 삭제하지 않는다**(요구사항). 대신 신규
워크플로 2개를 추가한다.

### 10-1. `daily-threads-generate.yml` (신규)

```yaml
on:
  schedule:
    - cron: '0 23 * * *'   # 기존과 동일한 시각 (KST 08:00)
  workflow_dispatch: {}     # 수동 재생성용
permissions:
  contents: write
steps:
  - checkout
  - setup-python
  - python -m unittest discover   # 기존과 동일한 안전장치
  - python3 scripts/generate_threads_draft.py   # Threads API 호출 코드 자체가 없음
  - data/tak_threads_pending.json 변경 있으면만 commit + push
```

### 10-2. `publish-approved-threads.yml` (신규) — 11장에서 트리거 방식 결정

```yaml
on:
  push:
    paths: ["data/tak_threads_pending.json"]   # ★ 승인 커밋이 push되면 자동 발행
  workflow_dispatch: {}                         # 수동 재시도용 (실패 후 재승인 등)
permissions:
  contents: write
concurrency:
  group: publish-approved-threads
  cancel-in-progress: false
steps:
  - checkout
  - setup-python
  - python -m unittest discover
  - python3 scripts/publish_approved_threads.py
  - (threads_publish_log.json 또는 tak_threads_pending.json 변경 있으면) commit + push
```

`on: push: paths:` 트리거를 쓰는 이유는 11장에서 상세히 설명한다 — 오늘 세션에서
실제로 겪은 `workflow_dispatch` 권한 문제(Codespace 기본 토큰으로는 API 호출
불가, `403`)를 근본적으로 우회하는 선택이다.

**자기 자신을 다시 트리거하는 문제**: `publish-approved-threads.yml`이 발행 성공
후 `tak_threads_pending.json`을 다시 커밋하면, 그 push가 같은 워크플로를 한 번
더 트리거한다. 하지만 그때는 이미 상태가 `published`라 "발행할 승인된 항목 없음"으로
즉시 정상 종료(exit 0, 커밋 없음)하므로 **1회성의 무해한 추가 실행**으로 끝나고
연쇄 반응은 없다. `concurrency` 설정으로 동시 실행만 막으면 충분하다.

---

## 11. A안 / B안 비교

| 기준 | A안: Dashboard가 직접 Threads API 호출 | B안: Dashboard는 승인만, GitHub Actions가 발행 |
|---|---|---|
| `THREADS_ACCESS_TOKEN` 위치 | GitHub Actions Secrets **+ Dashboard 실행 환경(로컬/클라우드)** 두 곳 | **GitHub Actions Secrets 한 곳만** (현재와 동일) |
| 토큰 노출 범위 | 로컬 Codespace 프로세스 환경변수, 향후 클라우드 서비스에도 필요 → 노출 표면 2배 | 변화 없음 |
| 상태 동기화 | Dashboard가 곧 발행 주체이므로 즉시 반영, 별도 워크플로 불필요 | 승인 → git push → 워크플로 실행까지 지연(수 초~수 분) 발생 |
| GitHub Actions와의 관계 | 기존 발행 워크플로와 로직이 중복(같은 `ThreadsClient` 호출을 두 군데서) | 기존 `publish_threads.py`/`ThreadsClient`/`PublishHistory` 계약을 100% 그대로 재사용, 중복 없음 |
| 향후 클라우드 Dashboard 확장(요구사항 14) | 클라우드 서비스에 시크릿을 새로 심어야 함 → 시크릿 관리 지점 증가, 공격 표면 증가 | 클라우드 Dashboard는 git repo에 읽기/쓰기 권한만 있으면 됨(GitHub API로 파일 read/write) — 시크릿은 여전히 Actions에만 존재 |
| 장애/재시도 | 실패 처리(재시도, 로그)를 Dashboard가 새로 구현해야 함 | 기존 `scripts/publish_threads.py`의 실패 처리 계약을 그대로 상속 |
| "즉시 발행됐다"는 체감 | 있음 | 약함(다음 push 트리거까지 지연) — 16장에서 트레이드오프로 다룸 |
| 오늘 실제로 확인된 제약과의 정합성 | 관련 없음 | `on: push`는 일반 git push 권한만 있으면 트리거된다 — 오늘 겪은 `workflow_dispatch` 403 문제를 구조적으로 회피 |

**추천: B안.** 근거:

1. **보안이 최우선 기준이다.** 이 프로젝트는 지금까지 "Threads 토큰은 GitHub
   Actions Secrets에만 둔다"는 원칙을 한 번도 깬 적이 없다(코드 전체 grep으로
   확인). A안은 이 원칙을 깨야만 성립한다.
2. **클라우드 확장(요구사항 14)에서 A안은 구조적으로 막힌다** — 매번 확장할
   때마다 시크릿을 새 실행 환경에 복제해야 하는 반면, B안은 "git에 읽고 쓸 수
   있는 곳이면 어디서든 Dashboard를 띄울 수 있다"는 훨씬 유연한 성질을 가진다.
3. **기존 코드 재사용 원칙과 일치한다** — 이 프로젝트의 모든 기존 문서(Phase
   4-3, 4-4 등)가 반복해서 강조하는 "새 로직을 만들지 않고 기존 함수를 그대로
   호출한다"는 관례를, B안은 `publish_threads.py`/`ThreadsClient`/`PublishHistory`를
   그대로 재사용함으로써 그대로 따른다.
4. 유일한 단점(발행까지의 지연)은 "10~20초 안에 승인 판단"이라는 목표와는
   별개의 지표다 — 목표는 **판단 소요 시간**이지 **발행 완료 시간**이 아니다.
   지연 자체도 `on: push` 트리거를 쓰면 보통 수십 초~1~2분 내로 충분히 빠르다
   (GitHub Actions 워크플로 시작 지연 수준).

---

## 12. 보안 고려사항

1. **토큰 단일 보관 원칙 유지** (11장에서 이미 다룸) — B안 채택으로 자동 충족.
2. **Dashboard 자체의 네트워크 노출**: `run_scout_dashboard.py`와 동일하게
   기본값 `127.0.0.1` 바인딩 유지 — 외부에서 접근 불가능한 로컬 전용 서버로
   시작한다. 클라우드 확장은 별도 Phase(이번 범위 밖, 요구사항 명시).
3. **git push 주체**: Dashboard가 자동으로 push할 경우, 이 push는 사람(티몽) 계정의
   git 자격증명을 그대로 쓰게 된다(현재 Codespace가 이미 `sopptak` 계정으로
   push 가능한 것과 동일) — 새로운 자격증명을 추가로 발급/저장할 필요가 없다.
   이는 A안이었다면 "Threads API 토큰"이라는 **새로운 자격증명**을 추가로
   관리해야 했을 것과 대비된다.
4. **Validator 우회 금지 원칙**: 9-3장에서 설명했듯, Validator의 판정 로직은
   전혀 수정/약화하지 않는다. 다만 "차단"에서 "경고 노출"로 역할이 바뀌는데,
   이는 우회가 아니라 **결정 권한을 사람에게 명시적으로 이전**하는 것이다 —
   기존에도 Validator 자체가 "AI 생성물의 안전성"만 보장했지 "사람이 검토한
   최종 발행물"까지 통제하는 도구는 아니었다.
5. **pending 파일에 담기는 정보의 민감도**: `source_url`, `evidence_unit_ids`
   등은 이미 `data/threads_publish_log.json`에도 기록되는 수준의 정보이며,
   새로운 민감정보 클래스를 추가하지 않는다.
6. **워크플로 권한 최소화**: 신규 워크플로 2개 모두 `permissions: contents: write`
   외 다른 권한을 요구하지 않는다(기존 `daily-threads-post.yml`과 동일한
   최소 권한 원칙).

---

## 13. 단계적 전환 방법

기존 `daily-threads-post.yml`(완전 자동 발행)을 **곧바로 끄지 않고**, 안전망으로
유지하면서 병행 검증한다.

- **Phase 1** (아래 14장): 신규 파일/스크립트만 추가한다. 기존
  `daily-threads-post.yml`은 스케줄까지 그대로 살아 있다 — 즉 이 단계에서는
  "완전 자동 발행"과 "반자동 초안 생성"이 **동시에** 돌아간다(둘 다 같은
  rotation 로직을 거치므로, 완전 자동 쪽이 먼저 게시해버리면 반자동 쪽 초안은
  자동으로 다음 rotation 대상으로 넘어감 — 서로 충돌하지 않고 그냥 "완전
  자동이 이긴다"). 이 Phase의 목적은 **신규 코드가 운영 데이터를 망가뜨리지
  않는지 안전하게 검증**하는 것.
- **Phase 2**: 검증이 끝나면 `daily-threads-post.yml`의 **cron 스케줄만
  주석 처리**(파일은 남기고 `workflow_dispatch`만 남겨 수동 비상 발행 경로로
  보존)하고, `daily-threads-generate.yml` + `publish-approved-threads.yml`을
  실제 운영 경로로 전환한다. Dashboard의 git commit/push 자동화도 이 시점에
  켠다.
- **Phase 3**: 며칠간 반자동 경로만으로 안정적으로 운영됨을 확인한 뒤,
  `daily-threads-post.yml`을 완전히 제거할지 판단한다(이번 설계 범위 밖 —
  사용자의 최종 승인이 필요한 결정).

이 순서는 "기존 자동 발행 기능을 안전하게 유지하면서 전환"이라는 요구사항을
그대로 만족한다 — 어느 시점에도 기존 워크플로 파일을 삭제하거나 기존 함수의
동작을 바꾸지 않는다.

---

## 14. 구현 Phase 제안 (설계만, 미구현)

| Phase | 내용 | 위험도 |
|---|---|---|
| **Phase 1** | `content_engine/threads_review.py`(pending 데이터 모델 + load/save/upsert) 신규 작성 + 단위 테스트. `scripts/generate_threads_draft.py` 신규 작성(Threads API 미호출). `.gitignore`에 `!data/tak_threads_pending.json` 추가. 로컬에서만 수동 실행 검증(워크플로 아직 안 만듦). | 낮음 — 순수 추가, 기존 코드 무수정 |
| **Phase 2** | `scripts/publish_approved_threads.py` 신규 작성 + 단위 테스트(성공/실패 시 PublishHistory 반영 여부 집중 검증). | 낮음 — 기존 `publish_threads.py`의 검증된 호출 순서를 그대로 복제 |
| **Phase 3** | `scripts/run_threads_review_dashboard.py` 신규 작성(수정/승인 UI, git commit/push 없이 로컬 파일만 갱신) + 테스트. | 중간 — 신규 UI 코드, 그러나 `run_scout_dashboard.py` 패턴 재사용으로 위험 완화 |
| **Phase 4** | Dashboard 승인 핸들러에 git add/commit/push 자동화 추가(push 실패/충돌 시 안전하게 실패하고 로컬 파일은 보존하는 재시도 로직 포함). | 중간 — 이번 대화에서 겪은 "origin/main보다 뒤처짐" 같은 merge 상황을 고려해야 함 |
| **Phase 5** | `.github/workflows/daily-threads-generate.yml`, `publish-approved-threads.yml` 신규 작성. 기존 `daily-threads-post.yml`은 무수정. | 중간 — 워크플로 트리거/동시성 설정 실수 여지 |
| **Phase 6** | 13장의 단계적 전환(기존 워크플로 cron 비활성화) — 실제 운영 데이터로 병행 검증 후 진행. | 운영 판단 필요, 코드 위험도 낮음 |

각 Phase는 이전 Phase가 테스트로 검증된 뒤에만 진행하며, Phase 1~3은 기존
운영 파이프라인에 **어떤 영향도 주지 않는다**(신규 파일만 추가, 기존
`run_daily.py`/`daily-threads-post.yml` 무수정).

---

## 15. 테스트 전략

기존 테스트 스타일(순수 함수 우선, `tempfile.TemporaryDirectory()`, mock
transport, 실제 네트워크 호출 없음)을 그대로 따른다.

| 신규 테스트 파일 | 검증 대상 |
|---|---|
| `tests/test_threads_review.py` | pending 레코드 load/save/upsert 원자성, 상태 전이(pending→approved→published/failed), "미해결 항목이 있으면 새로 안 만든다" idempotency |
| `tests/test_generate_threads_draft.py` | `select_unpublished_threads_item` 그대로 재사용되는지(rotation 정책 무변경 회귀), `ThreadsClient`가 import/호출되지 않는지(코드 정적 검사 또는 mock으로 "호출 0회" 확인), 이미 pending인 content_id/이미 published인 content_id는 재선정 안 됨 |
| `tests/test_publish_approved_threads.py` | approved 항목만 게시 대상, 성공 시 `PublishHistory.append` 정확히 1회 호출 + pending status=published, 실패 시 `PublishHistory` 완전 불변 + pending status=failed, published 항목은 재게시 시도 자체가 안 됨 |
| `tests/test_threads_review_dashboard.py` | GET으로 카드 렌더링(승인 전/후), POST로 텍스트 수정 저장 정확성, "수정 없이 승인" 시 `ai_rewritten_*`와 `final_*`가 동일하게 저장되는지, 서버 재시작(모듈 재호출) 후에도 상태 유지(파일 기반이므로 자동 보장), 금융 콘텐츠 경고 배너 노출 조건 |
| 기존 테스트 회귀 | `tests/test_publish_history.py`(23개), `tests/test_publish_threads_auto_select.py`(13개), `tests/test_threads_publisher.py`(11개) — **단 한 줄도 수정하지 않고 그대로 통과**해야 함. 전체 스위트(`python3 -m unittest discover`)가 계속 100% PASS 유지되어야 Phase 진행 가능 |

---

## 16. 운영상 예상되는 문제

1. **승인 지연 누적**: 티몽이 며칠 검수를 안 하면 파이프라인이 밀린다. 9-1장의
   idempotency 규칙(미해결 항목이 있으면 새로 안 만듦) 때문에 콘텐츠가 겹쳐
   쌓이지는 않지만, 대신 새 초안 생성 자체가 계속 보류된다 — "매일 발행"이라는
   기존 리듬이 깨질 수 있음. 운영 관찰 필요, 코드로 강제 해결할 문제는 아님.
2. **git push 충돌**: Dashboard의 자동 push와 발행 워크플로의 자동 push가 겹치면
   (예: 발행 워크플로가 `published`로 갱신+push하는 도중 티몽이 다음 날 초안을
   승인) 오늘 이 대화에서 실제로 겪은 것과 같은 "origin보다 뒤처짐" 상황이
   재현될 수 있다. Dashboard의 push 로직은 **강제 push(`--force`)를 절대 쓰지
   않고**, 실패 시 fetch+merge 재시도 1회, 그래도 실패하면 로컬 파일은 보존한
   채 사람에게 "다시 시도해달라"고 안내해야 한다.
3. **발행까지의 지연**: `on: push` 트리거도 GitHub Actions 큐 대기 시간이 있어
   승인 직후 즉시 게시되지는 않는다(보통 수십 초~수 분). "10~20초 안에 판단"과
   "즉시 게시됨"은 다른 지표임을 티몽에게 명확히 안내하는 문구가 Dashboard에
   필요하다.
4. **워크플로 자기 재트리거**: 10-2장에서 설명한 무해한 1회 추가 실행 — Actions
   사용량이 아주 약간 늘어나지만 기능적 문제는 없다.
5. **Codespace가 꺼져 있으면 Dashboard 접근 불가**: TAK SCOUT Dashboard와 동일한
   제약(로컬 바인딩 서버는 컨테이너가 살아있어야 접속 가능). 클라우드 이전
   전까지는 "확인하려면 Codespace를 켜야 한다"는 운영상 제약이 있음(요구사항
   14에서 다룬 "향후 클라우드 확장"의 실질적 동기).
6. **Validator 경고를 사람이 무시할 위험**: 9-3장에서 다룬 트레이드오프 — 금융
   경계 문구를 사람이 실수로 지우고도 경고를 무시한 채 발행할 수 있다. 이는
   "최종 책임을 사람에게 넘긴다"는 반자동화의 근본 전제에서 발생하는 구조적
   위험이며, Validator를 다시 강제 차단으로 되돌리면 목표 자체가 성립하지
   않는다 — 문서로 명확히 인지시키는 것 외에 코드로 완전히 없앨 수 있는
   문제는 아니다.

---

## 17. 추천안

- **아키텍처**: 사용자가 제시한 기본 骨格(GENERATION → pending 파일 → Dashboard →
  승인 → Threads API → PublishHistory)을 그대로 채택하되, **"승인"과 "실제
  Threads API 호출" 사이에 GitHub Actions라는 경계를 하나 더 둔다**(B안).
- **트리거**: `workflow_dispatch`가 아니라 **`on: push: paths:
  ["data/tak_threads_pending.json"]`**을 발행 워크플로의 주 트리거로 쓴다 —
  오늘 실제로 겪은 권한 문제를 코드 변경 없이 근본적으로 회피하는 선택이다.
- **content_id**: 편집 여부와 무관하게 기존 `compute_content_id()` 그대로 사용
  (7장) — 코드 변경 없음.
- **상태 모델**: `pending/approved/published/failed` 4개 그대로(5장) — 더
  세분화하지 않음.
- **전환 방식**: 기존 완전 자동 워크플로는 즉시 제거하지 않고, Phase 1~3(순수
  추가)이 검증된 뒤에만 Phase 5~6(워크플로 전환)으로 진행(13장/14장).

## 18. 결론

현재 코드베이스는 이미 반자동 전환에 유리한 구조를 갖추고 있다:
`select_unpublished_threads_item`(rotation)과 `compute_content_id`(중복 방지)가
"생성/선정" 단계에, `ThreadsClient`+`PublishHistory.append`가 "실제 발행" 단계에
이미 명확히 분리되어 존재하고(`scripts/publish_threads.py` 안에서 두 단계가
순서대로 호출될 뿐 서로 얽혀 있지 않음), 유일한 문제는 이 둘을 "사람의 확인"
없이 같은 프로세스 안에서 곧바로 이어 붙였다는 점뿐이다. 따라서 이번 전환은
**기존 로직을 재작성하는 것이 아니라, 이미 분리 가능한 두 단계 사이에 새로운
데이터 파일(`data/tak_threads_pending.json`)과 그 파일을 매개로 하는 사람의
검수 관문 하나를 끼워 넣는 작업**이다. `generator.py`/`rewrite.py`/
`publish_history.py`/`threads_publisher.py`는 전부 무수정으로 재사용 가능하며,
새로 필요한 코드는 "pending 상태 관리" + "Dashboard UI" + "워크플로 분리"라는
세 가지 얇은 레이어뿐이다. 보안·클라우드 확장성 두 기준 모두에서 B안(Dashboard는
승인만, GitHub Actions가 실제 발행)이 A안보다 명확히 우월하다고 판단한다.

---

## 최종 정리

### 구현할 파일 목록 (전체)

| 구분 | 파일 |
|---|---|
| 신규 | `content_engine/threads_review.py` |
| 신규 | `scripts/generate_threads_draft.py` |
| 신규 | `scripts/publish_approved_threads.py` |
| 신규 | `scripts/run_threads_review_dashboard.py` |
| 신규 | `.github/workflows/daily-threads-generate.yml` |
| 신규 | `.github/workflows/publish-approved-threads.yml` |
| 신규 | `tests/test_threads_review.py` |
| 신규 | `tests/test_generate_threads_draft.py` |
| 신규 | `tests/test_publish_approved_threads.py` |
| 신규 | `tests/test_threads_review_dashboard.py` |
| 수정 | `.gitignore` (`!data/tak_threads_pending.json` 한 줄 추가) |
| 수정(Phase 6, 선택적) | `.github/workflows/daily-threads-post.yml` (cron만 비활성화, 삭제 아님) |

### 수정할 기존 파일 목록

- `.gitignore` — 화이트리스트에 `!data/tak_threads_pending.json` 한 줄 추가.
  이것이 새 pending 파일을 git 추적 대상(=GitHub Actions와 Dashboard 사이의
  상태 동기화 매개체)으로 만드는 유일하게 필요한 기존 파일 수정이다.
- (Phase 6, 운영 안정화 이후, 선택적) `.github/workflows/daily-threads-post.yml`의
  `on.schedule` 항목만 주석 처리. 그 외 어떤 기존 파일도 로직 변경이 필요 없다.

### 새로 만들 파일 목록

- `content_engine/threads_review.py` — pending draft 데이터 모델(dataclass) +
  load/save/upsert(원자적 저장) + 상태 전이 헬퍼.
- `scripts/generate_threads_draft.py` — 생성 전용 CLI(Threads API 미사용).
- `scripts/publish_approved_threads.py` — 발행 전용 CLI(승인된 1건만 게시).
- `scripts/run_threads_review_dashboard.py` — 로컬 웹 검수 UI.
- `.github/workflows/daily-threads-generate.yml`
- `.github/workflows/publish-approved-threads.yml`
- `tests/test_threads_review.py`
- `tests/test_generate_threads_draft.py`
- `tests/test_publish_approved_threads.py`
- `tests/test_threads_review_dashboard.py`

### 삭제하면 안 되는 기존 기능

- `scripts/run_daily.py`, `scripts/publish_threads.py` — Phase 6까지 원본 그대로
  보존(안전망).
- `.github/workflows/daily-threads-post.yml` — 파일 자체는 삭제 금지(요구사항
  명시). Phase 6에서도 cron만 끄고 파일은 남긴다(수동 비상 발행 경로).
- `content_engine/publish_history.py`의 `select_unpublished_threads_item`
  (rotation, 5-10 Phase 4-4) — 무수정 재사용.
- `content_engine/publish_history.py`의 `compute_content_id` — 무수정 재사용.
- `content_engine/rewrite.py`의 `RewriteValidator` 전체 — 무수정(9-3장: 경고
  용도로 `find_finance_boundary_sentence`만 추가 재사용, 판정 로직 자체는
  손대지 않음).
- `content_engine/threads_publisher.py`(`ThreadsClient`) — 무수정 재사용.
- Naver 자동 발행, Shorts 자동 업로드, 로그인 자동화 관련 기존 코드 — 이번
  설계와 무관, 손대지 않음.

### Phase 1부터 Phase N까지 구현 순서

1. **Phase 1**: `content_engine/threads_review.py` + `scripts/generate_threads_draft.py`
   + 단위 테스트. `.gitignore` 수정.
2. **Phase 2**: `scripts/publish_approved_threads.py` + 단위 테스트.
3. **Phase 3**: `scripts/run_threads_review_dashboard.py` + 테스트(git 자동화
   없이, 로컬 파일만).
4. **Phase 4**: Dashboard에 git commit/push 자동화 추가(안전한 재시도/실패
   처리 포함).
5. **Phase 5**: `daily-threads-generate.yml` + `publish-approved-threads.yml`
   신규 워크플로 추가(기존 워크플로는 그대로 병행).
6. **Phase 6**: 운영 데이터로 병행 검증 후, 기존 `daily-threads-post.yml`의
   cron 비활성화 여부를 사용자와 함께 최종 판단.

---

**다시 강조**: 이 문서 작성 과정에서 코드 수정, git commit, git push, 실제
Threads 발행을 전혀 수행하지 않았다. 모든 파일/함수 경로는 실제로 읽고 확인한
내용에 근거한다.
