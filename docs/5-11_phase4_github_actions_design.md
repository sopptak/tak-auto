# 5-11 Phase 4 — GitHub Actions 연결 설계 (설계 전용, 미구현)

> **이 문서는 설계 전용이다.** 코드 수정, `.github/workflows/*.yml` 수정,
> 실제 Threads API 호출, 운영 데이터 수정, git commit/push를 전혀 수행하지
> 않았다. 아래 내용은 실제로 읽은 코드/workflow에 근거한다.

## 0. 읽은 파일 목록

- `docs/5-11_threads_human_review_design.md`, `docs/5-11_phase2_dashboard_review.md`,
  `docs/5-11_phase3_publish_approved_threads.md`
- `scripts/publish_approved_threads.py`(Phase 3, 전체 재확인)
- `content_engine/threads_review.py`, `content_engine/publish_history.py`,
  `content_engine/threads_publisher.py`
- `scripts/publish_threads.py`, `scripts/generate_threads_draft.py`,
  `scripts/run_scout_dashboard.py`
- `.github/workflows/daily-threads-post.yml`(현재 저장소에 존재하는 유일한
  workflow — 전문을 읽고 아래 설계에서 그 구조를 여러 번 재사용한다)

---

## 1. 전체 운영 흐름

```
[TAK SCOUT] 소재 랭킹 → [TAK INTERVIEW] Dashboard 인터뷰(최대 3턴)
      │
      ▼
[TAK BRAIN] KNOWLEDGE 생성(pending) → 사람이 review_knowledge.py로 승인
      │
      ▼
[TAK MEDIA] scripts/generate_threads_draft.py
      - 승인 KNOWLEDGE 로드 → run_media_batch() → select_unpublished_threads_item()
      - ThreadsClient 미사용(import조차 안 함) — 실제 게시 코드 경로 자체가 없음
      ▼
data/tak_threads_pending.json (status: pending)
      │
      ▼
[Dashboard] scripts/run_scout_dashboard.py의 /threads, /threads/{content_id}
      - 티몽이 그대로 승인하거나 제목/본문을 고쳐 승인
      - mark_approved() → final_title/final_body 확정
      ▼
data/tak_threads_pending.json (status: approved)
      │
      │  ★ 이번 Phase 4가 설계하는 연결 지점 ★
      ▼
[GitHub Actions] (신규 workflow, 이번 문서가 설계하는 대상)
      │
      ▼
python3 scripts/publish_approved_threads.py --execute   (Phase 3, 무수정 재사용)
      - status == "approved" && final_title/final_body 있는 항목만 대상
      - PublishHistory.is_published(content_id)로 중복 확인
      ▼
ThreadsClient.publish_text(final_body)   (content_engine/threads_publisher.py, 무수정)
      │
      ├─ 성공 → PublishHistory.append() + mark_published() (threads_post_id, published_at 기록)
      └─ 실패 → mark_failed() (PublishHistory는 불변)
      ▼
data/tak_threads_pending.json, data/threads_publish_log.json 갱신
      │
      ▼
[GitHub Actions] git add + commit + push  (기존 daily-threads-post.yml과 동일한 패턴)
```

**이번 Phase 4의 범위**: 위 그림에서 "★" 표시한 지점 — Dashboard가 만든
`approved` 상태를 GitHub Actions가 어떻게 찾아서
`scripts/publish_approved_threads.py --execute`를 안전하게 실행하고, 그 결과를
다시 git에 커밋하는가를 설계한다. `scripts/publish_approved_threads.py` 자체의
내부 로직(Phase 3, 이미 구현·검증됨)은 전혀 바꾸지 않는다.

---

## 2. GitHub Actions 실행 방식 비교

### A. 매일 정해진 시간 자동 발행 (schedule cron 전용)

기존 `daily-threads-post.yml`과 동일한 트리거 패턴(`on.schedule`)만 사용.

| 항목 | 평가 |
|---|---|
| 장점 | 구현이 가장 단순함(기존 workflow 구조 그대로 복제). 운영 리듬이 "하루 1건 순환 발행"이라는 현재 rotation 정책(5-10 Phase 4-4)과 자연스럽게 맞음. GitHub Actions 실행 빈도가 낮아 큐잉/동시성 부담이 적음. |
| 단점 | 승인 시점과 발행 시점 사이에 **최대 24시간 지연**이 생길 수 있다(예: 오늘 아침 생성 → 저녁에 승인 → 다음날 아침 cron에서야 발행). "승인 후 바로 나갔으면 좋겠다"는 심리적 기대와 어긋날 수 있음. |
| 적합성 | 지연을 감수할 수 있다면 가장 안전하고 구현이 쉬운 선택. |

### B. workflow_dispatch 수동 실행 (스케줄 없음)

티몽이 GitHub Actions 탭에서 직접 "Run workflow" 버튼을 눌러야만 실행된다.

| 항목 | 평가 |
|---|---|
| 장점 | 완전한 사람의 통제 — 우발적 자동 발행 리스크가 구조적으로 없다(자동 트리거 자체가 없으므로). |
| 단점 | "Dashboard에서 승인 클릭"과 "GitHub Actions에서 다시 버튼 클릭"이라는 **두 번의 수동 조작**이 필요해져, "티몽이 10~20초만 판단하면 나머지는 자동"이라는 5-11 반자동화의 근본 목표와 어긋난다. |
| 참고 | 5-11 설계 문서 3장(6번 근거)에서 이미 확인했듯, Codespace 기본 GitHub App 토큰으로는 `workflow_dispatch` **API 호출**이 403으로 막힌다 — 그러나 이는 "프로그램이 API로 트리거하는 것"이 막힌 것이지, **사람이 GitHub 웹 UI에서 직접 버튼을 클릭하는 것**은 이 제약과 무관하게 항상 가능하다. B안은 후자(사람이 직접 클릭)를 전제로 한다. |
| 적합성 | 승인 즉시 발행을 원하지만 자동화를 아직 신뢰하기 전 단계(검증 기간)의 임시 방편으로는 적합. 정상 운영의 유일한 트리거로 쓰기에는 번거로움. |

### C. 승인 발생 후 자동 실행 (예: `on: push: paths: [...]`)

원 설계 문서(`5-11_threads_human_review_design.md` 10-2장, 11장)가 "B안"으로
이미 권고한 방식 — `data/tak_threads_pending.json`이 git에 push되는 순간
자동으로 발행 workflow가 실행된다.

| 항목 | 평가 |
|---|---|
| 장점 | 지연이 가장 짧다(승인 → push → 수십 초~1~2분 내 발행). "승인이 곧 발행 트리거"라는 목표에 가장 부합. `workflow_dispatch` API 403 문제를 구조적으로 우회(일반 `git push` 권한만 있으면 트리거되므로). |
| 단점(★핵심 제약) | 이 방식이 성립하려면 **Dashboard가 승인 시 `data/tak_threads_pending.json`을 자동으로 git add/commit/push해야 한다.** 그런데 Phase 2 구현 보고서(`docs/5-11_phase2_dashboard_review.md` 3, 12장)를 실제로 다시 확인한 결과, **Dashboard는 현재 로컬 파일만 갱신할 뿐 git commit/push를 전혀 하지 않는다**("Dashboard의 git commit/push 자동화도 이 시점에 켠다"는 항목은 원 설계 문서 13-14장의 "Phase 4"였는데, 이는 이번 대화의 "Phase 4"(GitHub Actions 연결)와 **번호가 겹치지만 다른 작업**이다 — 혼동 방지를 위해 6장에서 다시 짚는다). 즉 지금 상태에서 C안을 쓰려면 "티몽이 승인 후 수동으로 `git push`까지 해야" 트리거되므로, 실제로는 B안보다 더 번거로울 수 있다. |
| 적합성 | 목표에는 가장 이상적이지만, **선행 조건(Dashboard git 자동화)이 아직 없다** — 지금 당장 채택하면 "승인 → (사람이 잊지 않고 수동 push) → 발행"이 되어 오히려 신뢰도가 낮아진다. |

### D. A + B 혼합 (schedule + workflow_dispatch 병행, C는 채택하지 않음)

기존 `daily-threads-post.yml`과 정확히 동일한 트리거 패턴(`on.schedule` +
`on.workflow_dispatch`).

| 항목 | 평가 |
|---|---|
| 장점 | 기본은 A처럼 하루 1회 자동 발행 리듬을 유지하면서, 급하게 오늘 안에 내보내고 싶을 때는 B처럼 사람이 언제든 수동으로 즉시 실행할 수 있다. **Dashboard git 자동화라는 선행 조건이 필요 없다** — cron은 이미 로컬(→다음 push로 이미 반영된) 파일 상태를 그대로 읽고, 수동 실행은 사람이 원할 때 바로 트리거하면 된다. 기존 `daily-threads-post.yml`과 완전히 동일한 트리거·조건·시크릿 구조를 그대로 복제할 수 있어 구현/리뷰 부담이 최소화된다. |
| 단점 | C보다는 최대 지연이 길다(최악의 경우 24시간). 다만 이는 "10~20초 안에 승인 판단"이라는 목표와는 다른 지표(발행 완료 시각 vs. 판단 소요 시각)라고 원 설계 문서 4장에서 이미 명시적으로 구분해 두었다. |
| 적합성 | **현재 상태(Dashboard git 자동화 없음, workflow_dispatch API 403 제약)에서 가장 실현 가능하고, 기존 코드 재사용도 최대화하는 선택.** |

### 설계상 권고 (구현은 하지 않음)

**D안(schedule + workflow_dispatch 병행)을 권고한다.** C안(push 트리거)은
이상적이지만 "Dashboard가 승인 시 자동으로 git push한다"는, 아직 존재하지 않는
기능에 의존하므로 지금 채택하면 오히려 사람이 매번 수동 push를 잊지 않아야
하는 새로운 실패 지점을 만든다. Dashboard git 자동화가 나중에 실제로
구현되면(이는 이번 문서의 범위 밖이며 별도 Phase 판단이 필요), 그때 C안으로
전환하는 것을 재검토할 수 있다 — 이 전환 가능성 자체를 5장의 workflow 구조
설계에 미리 반영해 둔다(트리거 교체만으로 전환 가능하게, job 본문은
트리거와 독립적으로 설계).

---

## 3. 안전장치 설계

지난 세션에서 "dry-run/live 혼동"으로 인한 사고 우려가 있었으므로, 아래
항목마다 **이미 코드로 보장된 것**과 **workflow 설계에서 추가로 챙겨야 할
것**을 구분해 명시한다.

| # | 요구사항 | 이미 보장됨(코드) | workflow에서 추가로 챙길 것 |
|---|---|---|---|
| 1 | 기본 실행은 절대 실제 발행 안 함 | `scripts/publish_approved_threads.py`의 `execute = args.execute`(기본 `False`) — `--execute`가 없으면 `ThreadsClient.from_environment()` 호출 지점이 코드 흐름상 도달 불가능(Phase 3 self-review 1번, PASS 확인됨) | workflow YAML의 모든 실행 스텝이 **`--dry-run` 또는 `--execute` 둘 중 하나를 명시적으로 넘기도록** 작성한다(플래그 없이 스크립트를 호출하는 스텝을 만들지 않는다 — 있어도 안전하지만, "의도가 코드에 드러나야 한다"는 원칙상 항상 명시). |
| 2 | 실제 발행은 명시적 `--execute` | 상동 | workflow_dispatch input(`dry_run: boolean`, 기본값 `true`)을 두고, 이 값이 정확히 `--dry-run`/`--execute` 중 하나로만 매핑되도록 if 조건을 작성(4번 항목과 동일 패턴). |
| 3 | `--dry-run`과 `--execute` 동시 실행 차단 | 스크립트 자체가 둘 다 주어지면 즉시 오류(exit 1) 반환(Phase 3 구현, `if args.dry_run and args.execute:`) | workflow 레벨에서도 **두 스텝이 서로 배타적인 `if` 조건**을 갖도록 설계해 애초에 같은 실행에서 두 스텝이 동시에 트리거되지 않게 한다 — 기존 `daily-threads-post.yml`의 dry-run 스텝/live 스텝 배타 조건 패턴(76-92행)을 그대로 복제하면 검증된 패턴을 재사용하는 것이므로 새 위험을 만들지 않는다. |
| 4 | workflow_dispatch 입력값별 조건 분리 | 해당 없음(workflow 설계 사항) | `if: github.event_name == 'workflow_dispatch' && github.event.inputs.dry_run == 'true'` (dry-run 스텝) / `if: github.event_name != 'workflow_dispatch' || github.event.inputs.dry_run == 'false'` (execute 스텝) — 기존 workflow와 문자 그대로 동일한 조건식을 재사용해 새로 검증해야 할 조건 로직 자체를 최소화한다. |
| 5 | 승인되지 않은 draft 발행 방지 | `load_approved_drafts()`가 `status == "approved"`만 필터링(Phase 3 self-review 3번, PASS) | 추가 조치 불필요 — workflow는 이 계약을 그대로 신뢰하면 된다. |
| 6 | 이미 published/history의 content_id 중복 발행 방지 | `PublishHistory.is_published()` 체크가 API 호출보다 먼저 실행됨(Phase 3 self-review 5번, PASS) | 단일 workflow 실행 안에서는 추가 조치 불필요. **다만 서로 다른 workflow(예: 기존 daily-threads-post.yml과 신규 workflow)가 동시에 실행되는 경우**는 파일 기반 체크만으로 막을 수 없다 — 4, 7장에서 별도로 다룬다. |
| 7 | 실패 시 retry 가능한 상태 | `mark_failed()`가 `failure_reason`/`failed_at`을 기록하고, `content_engine/threads_review.py`의 `_ALLOWED_TRANSITIONS`가 `failed → approved` 재승인 전이를 이미 허용(Phase 1) | 자동 재시도(GitHub Actions의 retry action 등)는 **도입하지 않는다** — 그러면 "사람이 재승인해야만 재발행된다"는 안전 원칙이 깨진다. workflow는 실패를 그대로 job 실패로 보고하고 끝내면 된다. |
| 8 | THREADS_ACCESS_TOKEN은 GitHub Secrets에만 | 현재도 이미 그러함(`daily-threads-post.yml` 78-79행 `env: THREADS_ACCESS_TOKEN: ${{ secrets.THREADS_ACCESS_TOKEN }}`) | 신규 workflow도 **정확히 같은 시크릿 이름**을 그대로 재사용 — 새 시크릿을 만들지 않는다. |
| 9 | Dashboard에는 token 없음 | `scripts/run_scout_dashboard.py`는 `ThreadsClient`를 어디에서도 import하지 않음(Phase 2에서 정적 검사 + 동적 테스트로 이중 확인됨, `tests/test_threads_dashboard.py` 8, 9번) | 변경 없음 — 이번 Phase도 Dashboard를 수정하지 않으므로 그대로 유지됨. |
| 10 | GitHub Actions 로그에 token 노출 금지 | `ThreadsClient._safe_http_error_message()`가 토큰을 제외한 안전한 필드(message/type/code 등)만 노출하도록 이미 구현됨(`content_engine/threads_publisher.py:72-86`) | workflow의 `run:` 스텝에서 `echo`나 `print`로 환경변수 값을 직접 출력하는 코드를 절대 추가하지 않는다(리뷰 체크리스트 항목). GitHub Actions 자체의 기본 시크릿 마스킹도 이중 안전장치로 작동한다. |

---

## 4. 기존 `daily-threads-post.yml` 처리

### 선택지별 분석

**옵션 1 — 그대로 유지(병행 운영)**

- 장점: 기존 완전 자동 발행이 안전망으로 계속 살아있음 — 신규 시스템에 문제가
  생겨도 콘텐츠가 아예 안 나가는 최악의 상황은 피할 수 있음.
- 단점(★핵심 위험, 아래 상세): 신규 시스템 검증 전 **동시 운영 시 "사람이
  검수했다고 믿었지만 실제로는 AI 원본이 게시된" 조용한 실패**가 발생할 수
  있다.

**동시 실행 시 중복 발행 가능성 분석**: 두 workflow는 같은
`select_unpublished_threads_item()`/`PublishHistory`를 공유하므로 **완전히
동일한 content_id를 완전히 동일한 순간에 두 번 게시하는 것(진짜 중복)** 은
`PublishHistory.is_published()` 체크 덕분에 사실상 방지된다 — 둘 중 먼저
성공한 쪽이 history에 기록하면, 나중에 실행되는 쪽은 같은 content_id를 보고
API를 호출하지 않는다(3장 6번 항목). **그러나 진짜 문제는 "무엇이 게시되는가"가
다르다는 점이다**:

- `daily-threads-post.yml`(`scripts/run_daily.py` → `scripts/publish_threads.py`)은
  `rewritten_body`(AI 재작성 원본, **사람이 검수하지 않은 텍스트**)를 그대로
  게시한다(`scripts/publish_threads.py:121`).
- `publish_approved_threads.py`(신규)는 `final_body`(**사람이 승인/수정한
  텍스트**)를 게시한다.

두 파이프라인 모두 `select_unpublished_threads_item()`으로 "같은 content_id"를
후보로 고를 수 있으므로, **완전 자동 쪽이 먼저 실행되어 AI 원본을 이미
게시해버리면**, 그 content_id는 `PublishHistory`에 기록되고, 이후 사람이
Dashboard에서 정성껏 다듬어 승인한 `approved` draft는 "이미 history에
있음" 체크에 걸려 **API 호출 자체가 스킵**된다(3장 6번 항목의 정상 동작). 결과:
**티몽은 "내가 승인한 문장이 게시됐다"고 믿지만, 실제로 Threads에 올라간 것은
사람이 보지 못한 AI 원본**이라는 조용한 불일치가 생긴다 — 이것이 두 workflow
동시 운영의 진짜 위험이며, 에러나 경고 없이 발생하기 때문에 더 위험하다.

**옵션 2 — 비활성화(cron만 주석 처리, workflow_dispatch는 유지)**

- 원 설계 문서 13장이 이미 제안한 방식과 동일: 파일은 남기고 스케줄만 꺼서
  비상시 수동 발행 경로로 보존.
- 위 핵심 위험을 원천 차단하면서도 안전망 자체를 완전히 없애지는 않는다.
- **권고: 이 옵션을 채택한다.** 단, 실행 시점은 "신규 시스템(9장 Phase
  4-3)이 cron으로 전환되기 직전"이어야 한다 — 그 전까지는 신규 시스템도
  아직 cron이 없으므로(9장 Phase 4-1/4-2는 workflow_dispatch만 사용) 기존
  cron을 미리 꺼도 발행 자체가 끊기지 않는다는 보장이 없다(신규가 아직
  workflow_dispatch 검증 단계일 때 기존 cron까지 꺼버리면 "둘 다 자동으로
  안 나가는" 공백이 생김) — 이 순서는 9장에서 다시 명확히 규정한다.

**옵션 3 — 완전 대체(파일 삭제)**

- 검증 전 삭제는 안전망을 완전히 잃는 것 — 신규 시스템에 문제가 생기면
  발행이 완전히 멈춘다.
- 원 설계 문서도 "사용자의 최종 승인이 필요한 결정"으로 명시(13장, 14장) —
  이번 문서에서도 **권고하지 않는다.** 신규 시스템이 며칠간 안정적으로
  운영됨을 확인한 뒤, 별도로 사용자와 논의해 결정한다.

---

## 5. 권장 workflow 구조

생성과 발행을 분리한 2개 workflow 구조를 권고한다(원 설계 문서 10장의 구조를
그대로 계승).

### `daily-threads-generate.yml` (신규, 이번 Phase의 범위는 아니지만 구조상 짝을 이룸)

| 항목 | 내용 |
|---|---|
| 담당 | Threads **초안 생성**만. 실제 게시는 절대 하지 않음. |
| 호출 스크립트 | `python3 scripts/generate_threads_draft.py`(Phase 1, 무수정) |
| 트리거 | `schedule`(기존 `daily-threads-post.yml`과 동일한 KST 08:00) + `workflow_dispatch`(수동 재생성용) |
| 커밋 대상 | `data/tak_threads_pending.json` (신규 pending draft 생성 시에만 diff 발생) |
| 안전장치 | `ThreadsClient`를 이 스크립트가 아예 import하지 않으므로(Phase 1에서 정적/동적 이중 검증됨), 이 workflow에는 애초에 "실제 게시"라는 개념 자체가 없다 — dry-run/execute 구분도 필요 없다. |

### `publish-approved-threads.yml` (신규, **이번 Phase 4의 핵심 대상**)

| 항목 | 내용 |
|---|---|
| 담당 | **승인된(approved) 초안만** 실제 Threads API로 발행. |
| 호출 스크립트 | `python3 scripts/publish_approved_threads.py --execute` 또는 `--dry-run`(Phase 3, 무수정) |
| 트리거 | 2장 권고에 따라 D안 — `schedule`(생성 workflow보다 몇 시간 뒤, 예: KST 09:00 이후 — 티몽이 승인할 시간 여유를 주기 위함, 정확한 시각은 실제 운영 관찰 후 조정) + `workflow_dispatch`(`dry_run: boolean`, 기본값 `true`; 선택적으로 `content_id: string`, 기본값 빈 문자열 — 6장 참고) |
| 권한 | `permissions: contents: write` (기존과 동일, 그 이상 요구하지 않음) |
| concurrency | `group: publish-approved-threads`(workflow 이름을 그대로 그룹명으로 — 기존 `daily-threads-post.yml`과 동일한 `cancel-in-progress: false` 정책, 이유도 동일: 실행 중인 게시를 취소하면 history 커밋 전에 잘려 다음 실행이 중복 판단을 할 위험이 더 크다) |
| job 단계 | 1) checkout 2) setup-python 3) 기존 테스트 스위트 실행(`python3 -m unittest discover`) 4) dry-run/execute 배타적 스텝(3장 표의 3, 4번 패턴) 5) `data/tak_threads_pending.json` + `data/threads_publish_log.json` 두 파일의 diff 확인 6) 변경 있으면 commit + push |
| 기존과의 차이점 | 기존 `daily-threads-post.yml`은 커밋 대상이 `threads_publish_log.json` **하나뿐**이었지만(생성과 발행이 한 프로세스 안에 있었으므로), 신규 workflow는 **pending 파일도 함께 커밋**해야 한다(승인된 draft가 `published`/`failed`로 상태가 바뀌므로) — 이 차이를 diff 체크 스텝에서 명시적으로 반영해야 한다(두 파일 모두 `git add` 대상). |

### 트리거 교체 여지(2장 C안으로의 향후 전환 대비)

job 본문(스텝 4~6)은 `on:` 트리거 종류와 완전히 독립적으로 설계되어 있으므로,
나중에 Dashboard git 자동화가 구현되어 C안(push 트리거)으로 전환하고 싶어지면
`on:` 블록만 `push: paths: ["data/tak_threads_pending.json"]`으로 바꾸면 되고
job 본문은 그대로 재사용 가능하다 — 이 점을 염두에 두고 job을 트리거에
의존하지 않는 형태로 작성할 것을 권고한다(예: `github.event.inputs.dry_run`을
참조하는 조건은 `workflow_dispatch`가 아닐 때 항상 "생략된 것으로" 안전하게
처리되도록, 기존 `daily-threads-post.yml`의 조건식이 이미 그렇게 되어 있다 —
`github.event_name != 'workflow_dispatch' || ...`).

---

## 6. 승인과 GitHub Actions의 관계

- **approved 항목을 찾는 방법**: `scripts/publish_approved_threads.py`의
  `load_approved_drafts()`(Phase 3)가 이미 pending 파일 전체를 읽어
  `status == "approved"`인 항목을 모두 골라낸다 — workflow는 이 스크립트를
  인자 없이(또는 `--execute`만) 실행하기만 하면 되고, "찾는 로직"을 workflow
  YAML이나 별도 스크립트에 새로 만들 필요가 없다.
- **여러 approved 항목이 있을 경우**: 현재 Phase 3 구현(`for draft in
  approved: ...`)은 **리스트 전체를 순서대로 처리**한다(첫 항목만 처리하는
  게 아니다). 실무에서는 생성 스크립트의 idempotency 설계(`has_unresolved_draft`)
  때문에 미해결 draft가 항상 0~1건이므로 이 경로가 거의 발생하지 않지만,
  코드 계약상으로는 다건 처리를 이미 지원한다. **이번 설계에서는 이 동작을
  그대로 받아들이는 것을 권고**한다 — "하루 1건만 처리"로 인위적으로
  제한하려면 스크립트 수정이 필요해 이번 범위를 벗어난다.
- **하루 몇 건을 발행할지**: 코드에 명시적 상한은 없다 — 생성 단계의
  idempotency가 사실상 "하루 최대 1건 생성" 리듬을 만들어내는 간접적
  장치일 뿐이다. 명시적 `--limit` 옵션을 원한다면 향후 Phase에서 추가할 수
  있으나, 이번 문서에서는 제안만 하고 구현하지 않는다.
- **특정 content_id만 발행하는 방법**: 이미 Phase 3의 `--id` 옵션으로
  지원된다. workflow_dispatch input으로 `content_id`(옵션, 기본값 빈 문자열)를
  추가하고, 값이 있을 때만 `--id "${{ github.event.inputs.content_id }}"`를
  커맨드에 붙이는 방식으로 **코드 수정 없이 CLI 인자 전달만으로** 연결
  가능하다.
- **발행 순서**: pending 파일 내 JSON 배열 순서(=`load_pending()`이 반환하는
  순서, 즉 생성/업서트된 순서) 그대로다 — 별도의 우선순위 정렬 로직은 없다
  (Phase 3 코드 확인).
- **실패한 항목 처리**: `mark_failed()`로 상태 전환되고, **자동 재시도는
  없다**(3장 7번 항목) — 사람이 다시 `approved`로 되돌려야만(현재는 이
  재승인 UI 자체가 Dashboard에 없다는 것이 Phase 2/3 보고서에 명시된 남은
  이슈) 다음 실행에서 다시 자동으로 시도된다.

**용어 혼동 방지**: 원 설계 문서(`5-11_threads_human_review_design.md`)
14장의 "Phase 4"는 **"Dashboard에 git commit/push 자동화 추가"**를 가리키고,
이번 대화의 "Phase 4"는 **"GitHub Actions 연결"**을 가리킨다 — 서로 다른
작업이며, 이번 문서가 다루는 것은 후자뿐이다. Dashboard git 자동화는 여전히
구현되지 않은 상태이며, 이 문서는 그 부재를 전제로 설계했다(2장 D안 권고의
근거).

---

## 7. 실제 운영 시나리오

| 시나리오 | 예상 동작 |
|---|---|
| **approved 0건** | `load_approved_drafts()`가 빈 리스트 반환 → "발행할 승인된(approved) Threads 초안이 없습니다" 출력, exit 0 → pending/history 파일 변경 없음 → workflow의 diff 체크 스텝이 `changed=false` 판정 → commit 스텝 스킵, workflow 정상 종료. |
| **approved 1건** | 정상 경로 — execute 시 API 1회 호출, 성공하면 `published` + history 기록 → 두 파일 모두 diff 발생 → commit+push. |
| **approved 여러 건** | for 루프가 순서대로 전부 처리(6장) — 각 건 독립적으로 성공/실패 판정, **부분 성공**(일부 published, 일부 failed)도 정상적으로 가능. 하나라도 실패하면 스크립트 exit code가 1이 되어 **job 자체는 "실패"로 표시**되지만, 성공한 항목의 `published` 상태/history 기록은 이미 파일에 반영되어 있다 — 따라서 **commit 스텝은 job 성공 여부와 무관하게(`if: always()` 또는 이전 실패 스텝과 독립적으로) 실행되도록 설계해야 한다.** 이는 기존 `daily-threads-post.yml`에는 없던 새로운 고려사항이다(기존 스크립트는 단건만 다뤄 부분 실패 개념이 없었다). |
| **이미 published** | `load_approved_drafts()`가 애초에 상태 필터로 걸러냄 — 대상에서 제외, 아무 일도 일어나지 않음. |
| **history에는 있는데 status가 approved** (이례적 상태 불일치) | Phase 3의 dedup 동기화 분기가 처리 — API 호출 없이 기존 history 레코드 값으로 draft를 `published`로 동기화(Phase 3 self-review 5번 항목에서 검증됨). pending 파일만 변경되므로 commit 대상이 된다. |
| **Threads API 실패** | `mark_failed()` + `PublishHistory` 불변(Phase 3 self-review 4번) → pending 파일만 변경되어 commit 대상 → job은 exit code 1로 실패 표시되지만, `failed` 상태 기록은 반드시 커밋되어야 한다(위 "approved 여러 건" 항목과 동일한 이유). |
| **GitHub Actions 중복 실행**(같은 workflow가 겹쳐 실행) | `concurrency` 그룹 설정(`cancel-in-progress: false`)으로 두 번째 실행이 큐에서 대기 → 첫 실행이 끝난 뒤 시작되므로, 이미 반영된 content_id는 두 번째 실행의 dedup 검사(`is_published`)에 걸려 API 미호출. **단, 이 방어는 "같은 workflow 파일" 안에서만 유효하다** — 아래 항목 참고. |
| **같은 content_id가 동시에 두 workflow에서 대상이 되는 경우** | `concurrency` 그룹은 **workflow 파일 단위로 독립적**이다 — 예를 들어 기존 `daily-threads-post.yml`(그룹명 `daily-threads-post.yml`에 해당하는 `github.workflow` 값)과 신규 `publish-approved-threads.yml`(그룹명 `publish-approved-threads`)은 서로 다른 그룹이므로 **서로를 큐잉시키지 않는다.** 두 workflow가 정말로 같은 순간에 각자 다른 GitHub Actions 러너에서 체크아웃해 실행되면, 각자 "그 순간의" 파일 상태만 보고 판단하므로 이론적으로 두 번의 API 호출과 두 번의 파일 커밋(레이스, git push 충돌)이 발생할 수 있다. **이것이 4장에서 기존 workflow를 반드시 비활성화해야 한다고 결론 내린 핵심 근거다** — 두 workflow가 동시에 살아있는 한 이 위험은 workflow 설계만으로 완전히 제거할 수 없다. |

---

## 8. 현재 코드와의 연결점

새 workflow가 재사용할 기존 함수/스크립트(전부 무수정):

| 계층 | 재사용 대상 |
|---|---|
| CLI 진입점 | `scripts/publish_approved_threads.py`(Phase 3) |
| pending 상태 관리 | `content_engine/threads_review.py`의 `load_pending`/`mark_published`/`mark_failed`/`upsert_pending`(Phase 1) |
| 게시 이력 | `content_engine/publish_history.py`의 `PublishHistory`/`PublishRecord`(기존, 무수정) |
| Threads API | `content_engine/threads_publisher.py`의 `ThreadsClient`(기존, 무수정) — **새 Threads API 클라이언트를 만들지 않는다.** |

새 workflow가 **직접** 하는 일은 다음 다섯 가지뿐이다:

1. `actions/checkout`
2. `actions/setup-python`(기존과 동일 버전 `3.14`)
3. `python3 -m unittest discover -s tests -p 'test*.py'`(안전장치, 실패 시
   이후 스텝 자동 스킵 — 기존 workflow와 동일 관례)
4. `python3 scripts/publish_approved_threads.py --dry-run` 또는 `--execute`
   (배타적 조건, 3장 참고)
5. `data/tak_threads_pending.json` + `data/threads_publish_log.json` diff
   확인 후 commit + push(기존 `daily-threads-post.yml`의 `history_diff`/
   `Commit and push publish history` 스텝 패턴을 두 파일로 확장)

새로운 Python 모듈, 새로운 HTTP 클라이언트, 새로운 데이터 구조는 전혀 필요
없다.

---

## 9. 구현 순서 (설계 제안, 미구현)

### Phase 4-1 — workflow_dispatch 전용으로 안전하게 배선

- `publish-approved-threads.yml` 신규 작성. **트리거는 `workflow_dispatch`만**
  (cron은 아직 넣지 않는다). `dry_run` input 기본값 `true`(기존
  `daily-threads-post.yml`과 동일한 안전 기본값 관례 — 아무것도 안 바꾸고
  실행 버튼을 눌러도 항상 안전한 경로).
- 기존 `daily-threads-post.yml`은 **그대로 둔다**(cron도 그대로 유지) — 아직
  신규 workflow가 workflow_dispatch 검증 단계이므로, 기존 cron을 먼저 끄면
  "둘 다 자동으로 안 나가는" 공백이 생긴다(4장 옵션 2의 순서 조건).
- 목표: workflow YAML 자체(트리거/조건/권한/시크릿 배선)가 실제 GitHub
  Actions 환경에서 정확히 동작하는지 확인. 이 단계에서는 approved 항목이
  실제로 없거나 테스트용 항목으로만 `dry_run=true`를 실행해 로그를 확인한다.

### Phase 4-2 — 실 운영에서 소규모 execute 검증

- Phase 4-1에서 `dry_run=true` 로그가 기대대로 나오는 것을 사람이 확인한 뒤,
  실제로 승인된 draft가 정확히 1건 있을 때 **딱 한 번** 사람이
  workflow_dispatch를 `dry_run=false`로 수동 실행해 "실제 발행 1건"이
  의도대로 동작하는지 확인한다.
- 이 시점까지도 cron은 켜지 않는다 — 완전히 사람이 통제하는 상태에서만
  실제 발행이 일어난다.
- 이 단계에서 "approved 여러 건" 시나리오(7장)와 "실패 → 재승인" 흐름도
  최소 한 번씩은 의도적으로 만들어 실제로 검증해 볼 것을 권고한다(10장의
  갭 항목과 연결).

### Phase 4-3 — 스케줄 전환 + 기존 workflow 비활성화

- Phase 4-2까지 문제 없이 검증되면, `publish-approved-threads.yml`에
  `schedule`(cron) 트리거를 추가해 2장의 D안(스케줄+수동 병행)으로 전환한다.
- **정확히 같은 시점에** 기존 `daily-threads-post.yml`의 `on.schedule`을
  주석 처리(4장 옵션 2 — 파일은 삭제하지 않고 `workflow_dispatch`만 남겨
  비상 수동 발행 경로로 보존)한다. cron 전환과 기존 cron 비활성화를
  **동시에** 해야만 7장의 "두 workflow 동시 대상" 위험이 실제로 발생하는
  창구(둘 다 cron으로 자동 실행되는 기간)를 아예 만들지 않는다.
- 이 전환은 사용자의 최종 승인 하에만 진행한다(원 설계 문서 13장의 원칙과
  동일).

각 Phase 사이에는 반드시 실제 GitHub Actions 실행 로그를 사람이 눈으로
확인하는 수동 게이트를 둔다 — 자동으로 다음 Phase로 넘어가지 않는다.

---

## 10. 테스트 전략

실제 Threads API를 호출하지 않고 검증하는 방법을 다음과 같이 구분한다:
**(a) 이미 로컬 unittest로 충분히 커버된 것**, **(b) 이번 Phase 준비를 위해
로컬에서 보강이 필요하다고 판단되는 것(갭)**, **(c) GitHub Actions 상에서
사람이 직접 확인해야 하는 것(자동화 불가/비권장)**.

| 구분 | 항목 | 상태/방법 |
|---|---|---|
| (a) 기존 커버 | dry-run 시 API 호출 0회, pending/history 불변 | `tests/test_publish_approved_threads.py`의 `test_dry_run_calls_api_zero_times`, `test_dry_run_does_not_modify_pending_or_history` 등(Phase 3, 22개 중 다수)이 이미 검증 |
| (a) 기존 커버 | execute 성공/실패 경로, published/failed 상태 전환, PublishHistory 기록 여부 | `test_execute_success_*`, `test_execute_failure_*` 등(Phase 3) |
| (a) 기존 커버 | history 중복 시 API 미호출 | `test_content_id_already_in_history_skips_api_call`(Phase 3) |
| (a) 기존 커버 | `--id`로 단건 제한 | `test_id_flag_limits_to_single_content_id`(Phase 3) |
| (b) **갭 — 보강 권고** | **여러 approved 건을 `--id` 없이 전부 처리**하고, 하나가 실패해도 나머지는 계속 처리되는지 | Phase 3 테스트는 항상 draft 1건 또는 `--id`로 좁힌 단건 케이스 위주다. "승인된 게 2건 이상 있고, 첫 건이 실패해도 둘째 건은 정상 처리되는지"를 검증하는 테스트가 현재 없다 — **Phase 4-1 착수 전에 이 유닛테스트를 `tests/test_publish_approved_threads.py`에 추가할 것을 권고**(코드 변경 없이 지금은 필요성만 지적, 이번 문서 범위 밖). |
| (b) **갭 — 보강 권고** | **실패 → 재승인 → 재실행 → 성공**까지 이어지는 end-to-end 흐름 | 실패 시 상태 전환(`test_execute_failure_marks_failed_with_reason`, Phase 3)과 `failed → approved` 재승인 전이 자체(`test_failed_to_approved_retry`, Phase 1)는 각각 검증되어 있지만, 이 둘을 이어붙인 전체 흐름 테스트는 아직 없다 — Phase 4-1 착수 전 보강 권고. |
| (c) 수동 확인 | workflow YAML의 if 조건(`event_name`/`inputs.dry_run` 분기)이 실제로 의도대로 동작하는지 | 기존 `daily-threads-post.yml`에서 이미 검증된 조건식을 문자 그대로 복제하는 것이 1차 방어(새로 검증할 조건 로직의 범위를 최소화). 그래도 실제 GitHub Actions에서 `dry_run=true`/`false` 각각 한 번씩 사람이 직접 실행해 로그를 확인해야 한다 — 9장 Phase 4-1/4-2가 이 수동 검증을 포함한다. |
| (c) 수동 확인 | execute 경로의 실제 GitHub Actions 환경 검증 | 실제 서비스 대신 로컬 mock 서버로 `THREADS_API_BASE`를 바꿔치기하는 방법도 이론상 가능하나, 이는 이번 범위를 넘는 과도한 인프라라 **권장하지 않는다.** 대신 로컬 unittest로 검증된 스크립트 계약(Phase 3)을 신뢰하고, workflow는 "스크립트를 올바른 인자로 호출하는가"만 확인 대상으로 좁힌다 — 실제 execute 검증은 Phase 4-2의 "운영에서 딱 1건 수동 실행" 절차로 대체(자동화된 CI 테스트가 아니라 사람이 지켜보는 운영 게이트). |
| (c) 수동 확인 | 중복 실행 시 concurrency 큐잉이 실제로 동작하는지 | 같은 workflow를 짧은 간격으로 두 번 트리거해, 두 번째 실행이 "Queued"로 대기하는지 GitHub Actions UI에서 육안 확인 — 자동화하기 어려운 항목이며, 기존 `daily-threads-post.yml`도 같은 방식(패턴 재사용, 별도 자동 테스트 없음)이므로 새로운 리스크는 아니다. |

---

## 11. 설계상 가장 중요한 위험 5개 + 방지 장치 + 구현 전 확인 사항

### 위험 5개와 방지 장치

| # | 위험 | 방지 장치 |
|---|---|---|
| 1 | 기존 `daily-threads-post.yml`과 신규 workflow가 동시에 살아있는 동안, **같은 content_id에 대해 서로 다른 텍스트(AI 원본 vs 사람 승인본)가 게시 경쟁**을 벌여 "사람이 검수했다고 믿었지만 실제로는 AI 원본이 게시된" 조용한 실패가 발생 (4, 7장) | 신규 workflow가 cron으로 전환되는 **정확히 같은 시점에** 기존 workflow의 cron을 비활성화(9장 Phase 4-3). 그 전까지(Phase 4-1/4-2)는 신규 workflow가 workflow_dispatch로만 실행되므로 기존 cron과 "동시에 자동 실행"될 일이 없다. |
| 2 | Dashboard가 아직 git push를 자동화하지 않아, "승인 즉시 자동 발행"이라는 기대와 실제 지연(다음 cron 또는 사람의 수동 workflow_dispatch까지) 사이의 괴리 (2, 6장) | D안(schedule+workflow_dispatch 병행) 채택 — 급하면 사람이 수동 실행, 급하지 않으면 다음 cron. 이 지연을 Dashboard 문구 등으로 사람에게 명확히 안내하는 것은 향후 Dashboard 개선 과제(이번 범위 밖). |
| 3 | approved 여러 건 처리 시 **부분 실패**(일부 published, 일부 failed)를 job 실패로만 뭉뚱그려, 성공한 항목까지 재확인이 필요한지 헷갈릴 위험 (7장) | commit 스텝을 job 성공 여부와 무관하게 실행하도록 설계(9장 명시) — 성공분은 즉시 커밋되어 워크플로 로그의 exit code와 무관하게 실제 데이터 상태를 신뢰할 수 있게 한다. |
| 4 | `concurrency` 그룹이 **workflow 파일 단위로만 독립적**이라, 서로 다른 workflow가 동시에 같은 content_id를 대상으로 실행되는 경쟁 상태 (7장 마지막 시나리오) | 근본 해결책은 "동시에 살아있는 자동 발행 workflow를 하나로 유지"하는 것뿐이다(위험 1과 동일 근거) — 4장에서 기존 workflow 비활성화를 권고한 핵심 이유가 바로 이것이다. |
| 5 | 새 workflow 작성 시 사람의 구현 실수(예: env 블록 누락, 디버그용 `echo $TOKEN` 추가)로 토큰이 로그에 노출되거나 예상치 못한 경로로 API가 호출됨 | 기존 `daily-threads-post.yml`의 이미 검증된 env 배선/조건식을 **문자 그대로 복제**해 새로 작성해야 하는 부분을 최소화. 구현 시 코드 리뷰 체크리스트로 "echo/print로 시크릿 값을 출력하는 스텝이 없는가"를 명시적으로 확인. |

### 구현 전 반드시 확인해야 할 사항

1. **Dashboard git 자동화 여부와 시점** — C안(push 트리거) 전환을 언제,
   누가 결정할지(별도 Phase로 다룰지, 아예 D안으로 계속 갈지) 사용자와
   먼저 합의해야 한다.
2. **기존 `daily-threads-post.yml` cron 비활성화 시점**에 대한 사용자
   승인 — 9장 Phase 4-3은 "신규 cron 전환과 동시에" 비활성화할 것을
   권고하지만, 최종 결정은 사용자 몫이다(원 설계 문서 13장 원칙 유지).
3. **`THREADS_ACCESS_TOKEN`/`TAK_MEDIA_LLM_*` 시크릿이 이미 GitHub Secrets에
   등록되어 있는지** 재확인(신규 workflow가 기존과 같은 이름을 재사용하므로
   이미 있을 가능성이 높지만, 새 workflow 파일에서 정확한 시크릿 이름을
   한 번 더 대조해야 한다).
4. **하루 발행 상한 정책**이 필요한지 여부 — 현재는 상한이 없고 idempotency
   설계가 간접적으로 "하루 1건" 리듬을 만들 뿐이다. 향후 여러 KNOWLEDGE를
   동시에 승인 대기시키는 방향으로 확장한다면 명시적 상한(`--limit`)이
   필요해질 수 있다.
5. **failed 항목 재승인 UI**가 Dashboard에 아직 없다는 사실(Phase 2/3
   보고서에 이미 명시된 남은 이슈) — Phase 4 구현 전에 이 UI를 함께 만들지,
   당분간 수동으로 JSON을 편집해 재승인할지 결정이 필요하다.
6. **10장 (b)의 두 테스트 갭**(여러 approved 동시 처리, 실패→재승인→재실행
   end-to-end)을 Phase 4-1 착수 전에 보강할지 여부 — 보강 없이 진행해도
   Phase 4-1/4-2가 workflow_dispatch 기반 수동 검증으로 사실상 같은 것을
   확인하지만, 회귀 방지를 위해서는 유닛테스트로 남겨두는 편이 더 안전하다.

---

## 결론

이번 문서는 코드/workflow를 전혀 수정하지 않고, `scripts/publish_approved_threads.py`
(Phase 3, 이미 5가지 안전 요구사항이 PASS로 검증됨)를 기존 `daily-threads-post.yml`과
동일한 검증된 트리거·조건·시크릿 패턴으로 감싸는 `publish-approved-threads.yml`
설계만 제시했다. 핵심 결론은 세 가지다:

1. **트리거는 D안(schedule + workflow_dispatch 병행)을 권고** — C안(push
   트리거)은 이상적이지만 Dashboard git 자동화라는 아직 없는 선행 조건에
   의존한다.
2. **기존 `daily-threads-post.yml`은 즉시 비활성화하지 않고, 신규 workflow가
   cron으로 전환되는 시점에 정확히 맞춰 비활성화**해야 한다 — 그 전까지
   신규 workflow는 workflow_dispatch로만 실행해 "두 자동 발행 경로가 동시에
   살아있는 기간"을 원천적으로 만들지 않는다.
3. **새 Python 코드나 새 Threads API 클라이언트는 전혀 필요 없다** — 이미
   구현·검증된 `scripts/publish_approved_threads.py`를 그대로 호출하는
   workflow만 있으면 된다.
