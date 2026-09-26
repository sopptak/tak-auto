# Phase 4-2 실제 1건 발행 테스트 준비 — Threads pending draft 1건 생성

이 문서는 [[5-11_phase4_2_approved_check]]에서 확인한 대로 pending 파일이
존재하지 않는 상태에서, `scripts/generate_threads_draft.py`를 사용해 실제
LLM(OpenAI 호환 API)으로 Threads pending draft **1건만** 생성한 결과를
기록한다. **Threads API 호출, 실제 발행, git add/commit/push는 전혀
수행하지 않았다.**

## 1. 사용 가능한 approved KNOWLEDGE 확인

`data/tak_brain_knowledge.json`에서 `knowledge_review_status == "approved"`
인 항목은 총 5건이었다.

| knowledge_id | title | knowledge_type |
|---|---|---|
| knowledge-da6ddf5aa459 | 57화) 개발을 모르는 내가 앱을 만들다 | 경험 |
| knowledge-e1cc05264953 | 은행에서 대출받을 때 재무제표에서 가장 먼저 보는 것은? | 판단기준 |
| knowledge-da8e52862a79 | 직장에서 인정받는 사람은 일을 잘하는 것보다 이것을 잘한다 | 판단기준 |
| knowledge-a3f43f9bb62e | 거절을 잘하는 사람이 직장에서 더 신뢰받는 이유, 23년차 직장인이 보니 | 판단기준 |
| knowledge-scout-b28b782b2a33 | Anthropic boss Dario Amodei calls for AI development to slow down | 의견 |

기존 `data/threads_publish_log.json`(5건)과 대조하면, 위 5건 중
`knowledge-da6ddf5aa459` / `knowledge-e1cc05264953` / `knowledge-da8e52862a79`
는 이미 Threads로 발행된 이력이 있고, `knowledge-a3f43f9bb62e`와
`knowledge-scout-b28b782b2a33`는 아직 발행 이력이 없다.

→ 이번 draft 생성 대상으로 **`knowledge-a3f43f9bb62e`**(거절/신뢰 관련
판단기준, 아직 미발행)를 `--id`로 명시 지정했다.

## 2. 실행 커맨드

```
$ TAK_MEDIA_LLM_ENDPOINT="https://api.openai.com/v1/chat/completions" \
  TAK_MEDIA_LLM_MODEL="gpt-4o-mini" \
  python3 scripts/generate_threads_draft.py --id knowledge-a3f43f9bb62e
```

- `TAK_MEDIA_LLM_API_KEY`는 세션에 기존 설정된 값을 그대로 사용(조회/출력
  하지 않음).
- `TAK_MEDIA_LLM_ENDPOINT`/`TAK_MEDIA_LLM_MODEL`은 [[5-11_phase1_real_llm_test]],
  [[5-3_real_llm_test]]에서 사용한 것과 동일하게 이번 실행에만 환경변수로
  지정(`https://api.openai.com/v1/chat/completions` / `gpt-4o-mini`) —
  실제 LLM을 사용했다(MockRewriteProvider 아님).
- 이 스크립트는 설계상 `ThreadsClient`를 import하지 않고, Threads API를
  호출하지 않으며, `PublishHistory`에는 append하지 않는다
  (`scripts/generate_threads_draft.py` 주석/코드 기준).

### 실행 로그

```
TAK BRAIN: 승인 KNOWLEDGE 1건 확인
TAK MEDIA: 배치 실행 중 (콘텐츠 생성 + LLM 재작성 + 검증)...
TAK MEDIA 완료: 총 Draft 9건 (valid 6, rejected 3, error 0)
Threads 초안 생성 완료 (검수 대기): content_id=content-43786cf3ee0d89c5 KNOWLEDGE=knowledge-a3f43f9bb62e
```

## 3. `data/tak_threads_pending.json` 생성 결과 확인

실행 후 파일이 새로 생성되었고, 배열 안에 **정확히 1건**만 들어있다.

```json
[
  {
    "content_id": "content-43786cf3ee0d89c5",
    "knowledge_id": "knowledge-a3f43f9bb62e",
    "source_url": "https://blog.naver.com/tmong2/224394736479?fromRss=true&trackingCode=rss",
    "evidence_unit_ids": ["lesson:1", "reusable_principle:1"],
    "article_type": "workplace",
    "knowledge_type": "판단기준",
    "original_title": "원문이 제시한 판단",
    "original_body": "\"업무상 거절 방식과 직장 내 신뢰의 관계를 설명한다\".\n\n원문은 \"거절이 필요한 상황에서는 관계와 업무 맥락을 함께 고려한다\"고 덧붙입니다.",
    "ai_rewritten_title": "거절을 잘하는 사람이 직장에서 더 신뢰받는 이유",
    "ai_rewritten_body": "업무상 거절 방식과 직장 내 신뢰의 관계를 설명합니다. 거절이 필요한 상황에서는 관계와 업무 맥락을 함께 고려해야 합니다. 23년차 직장생활을 하면서, '약속', '신뢰', '거절', '말' 이 네 가지 요소가 직장 내 관계에 어떻게 영향을 미치는지 직접 확인해보았습니다. 거절을 효과적으로 하는 것이 직장에서 신뢰를 쌓는 데 어떤 역할을 하는지에 대해 생각해보면, 직장생활에 많은 도움이 될 것입니다. [출처](https://blog.naver.com/tmong2/224394736479?fromRss=true&trackingCode=rss) - 23년차 직장인 관찰)",
    "final_title": null,
    "final_body": null,
    "edited_by_user": false,
    "status": "pending",
    "created_at": "2026-09-16T06:09:39.168311+00:00",
    "approved_at": null,
    "published_at": null,
    "failed_at": null,
    "failure_reason": null,
    "threads_post_id": null
  }
]
```

## 4. 요청된 항목별 요약

| 항목 | 값 |
|---|---|
| content_id | `content-43786cf3ee0d89c5` |
| knowledge_id | `knowledge-a3f43f9bb62e` |
| status | `pending` |
| title | `거절을 잘하는 사람이 직장에서 더 신뢰받는 이유` (AI 재작성 제목, `final_title`은 아직 `null` — 사람 승인 전) |
| body | `ai_rewritten_body` 참고(위 JSON 전문) — 마지막에 원문 출처(`[출처](...)`)가 포함되어 있음. `final_body`는 아직 `null` |
| ai_original 여부 | `edited_by_user: false` → 사람이 아직 수정하지 않은 **AI 원본 그대로**(승인/수정 전 pending 상태) |

## 5. 기존 publish history와 content_id 중복 확인

`data/threads_publish_log.json`의 기존 5건 `content_id`:

```
content-f2082a27c88c26ca
content-b4b9a05c461ad595
content-45d8e97f0fab7b16
content-ff8909844fa80b99
content-ce61d77ee620c435
```

새로 생성된 `content-43786cf3ee0d89c5`는 위 5건 어디에도 없다 → **중복
없음.**

## 6. 금지 사항 준수 확인

- Threads API 호출: 안 함 (`generate_threads_draft.py`는 `ThreadsClient`를
  import하지 않는 구조)
- `publish_approved_threads.py` 실행: 안 함
- GitHub Actions 실행: 안 함
- `git add` / commit / push: 안 함
- `data/tak_brain_knowledge.json` 수정: 이 스크립트는 읽기만 하며, 실제로
  수정하지 않았다. (`git diff --stat` 기준 이 파일에 418줄 추가 변경이
  있으나, 이는 **이번 세션 시작 이전부터 이미 존재하던 미커밋 변경**이며
  — 대화 시작 시점 `git status` 스냅샷에 이미 `M
  data/tak_brain_knowledge.json`으로 표시되어 있었다 — 이번 작업으로 인한
  변경이 아니다.)
- `data/threads_publish_log.json` 수정: 안 함 (`git status --short`
  결과에 해당 파일 변경 없음, 읽기만 했음)
- 다른 파일 수정: 없음. 이번 작업으로 새로 생긴 변경은
  `data/tak_threads_pending.json`(신규 생성) 하나뿐이다.

```
$ git status --short data/tak_threads_pending.json data/tak_brain_knowledge.json data/threads_publish_log.json
 M data/tak_brain_knowledge.json   # 세션 시작 전부터 있던 기존 변경(본 작업과 무관)
?? data/tak_threads_pending.json  # 이번 작업으로 신규 생성
```

## 7. 다음 단계(참고, 이번 작업 범위 아님)

이 draft는 아직 `status: pending`이고 `final_title`/`final_body`가
`null`이므로, 사람 검수·승인(`content_engine/threads_review.py`의 승인
경로) 없이는 `publish_approved_threads.py`로 실제 발행할 수 없는 상태다.
Phase 4-2의 다음 단계(실제 1건 발행)는 이 draft를 사람이 승인한 뒤 별도
지시가 있을 때 진행한다.
