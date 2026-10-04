# 6-80 MarketingBrief → 콘텐츠 생성 연결

> 승인된 MarketingBrief를 기존 콘텐츠 생성 파이프라인에 **어댑터로** 연결한다. 결과는 항상 `review_required` 후보이며 자동 발행하지 않는다.

코드: `content_engine/marketing/generation.py`, `content_engine/rewrite.py`(`marketing_guidance`), CLI: `scripts/marketing_brief.py`
테스트: `tests/test_marketing_generation.py`, `tests/test_marketing_cli.py`
선행 문서: [6-79 AI Marketing Intelligence Layer](6-79-ai-marketing-intelligence.md)

## 흐름

```
Market Demand → MarketingBrief(draft)
  ↓ research / evidence
Suggestion (suggest: 근거 인용형 빈칸 제안, status=suggested)
  ↓
Human Review (review, suggestion accept|reject)   ← 사람이 결정
  ↓
Edit (set DIM.ELEM VALUE)                          ← approved 브리프를 고치면 draft로 돌아감
  ↓
Approval Gate (approve: approval_blockers 통과 필요)
  ↓
Platform Generation Contract (build_content_prompt → render_prompt_text = marketing_guidance)
  ↓
기존 생성기 (generate_content_bundle → [RewriteService] → [short_draft_to_shorts_script])
  ↓
review_required 후보 (data/tak_marketing_contents.json) + brief.content_ids 연결
```

기존 `generator.py` / `pipeline.py` / 발행 코드는 수정하지 않았다. 어댑터는 다음 기존 함수를 그대로 호출한다.

| 역할 | 기존 코드 |
|---|---|
| 승인 KNOWLEDGE 로드 | `tak_brain.knowledge.load_knowledge_records` |
| 규칙 기반 초안 | `content_engine.generator.generate_content_bundle` |
| 선택적 재작성 + 검증 | `content_engine.rewrite.RewriteService` |
| YouTube 구조 변환 | `content_engine.shorts_adapter.short_draft_to_shorts_script` |
| 콘텐츠 식별자 | `content_engine.publish_history.compute_content_id` |
| 브리프 연결 | `content_engine.marketing.store.link_content` |

## 생성 조건 (generation_blockers)

다음 중 하나라도 해당하면 아무것도 생성하지 않는다.

- 브리프가 `approved`가 아님(`draft`, `suggested`) 또는 `rejected`
- `platform`이 비어 있음(공통 브리프). `platforms`로 파생한 플랫폼 브리프를 승인해야 한다.
- `readiness_blockers`가 남아 있음: 승인 이후에도 현재 내용으로 승인 조건(시장 근거, 대상/문제/행동, 핵심 요소, 점수/신뢰도)을 다시 확인한다.
- `brief.knowledge_ids`와 일치하는 **approved** KNOWLEDGE가 없음 → 명시적 차단 사유 반환

`save_candidates`는 저장 직전에 저장소의 브리프를 다시 읽어 같은 게이트를 재확인한다. 생성 후 사람이 브리프를 편집(→ draft)하거나 반려했다면 저장하지 않는다.

KNOWLEDGE의 근거 단위가 없어 번들이 `insufficient_distinct_evidence`이면 빈 후보와 사유(`skipped`)를 반환한다.

## 플랫폼 매핑

| brief.platform | 사용하는 초안 | 추가 보존 |
|---|---|---|
| blog | `bundle.blog` (1건) | |
| threads | `bundle.threads` (5건) | |
| shorts | `bundle.shorts` (3건) | |
| youtube | `bundle.shorts` (3건) | `media_platform="shorts"`, `shorts_script`(title/subtitle/cards/takeaway/brand) |

YouTube의 `shorts_script`는 재작성이 `rewritten`(검증 통과)일 때만 재작성본으로, 그 외에는 원본 초안으로 변환한다. 변환 실패는 `shorts_script_error`로 남긴다.

## marketing_guidance

`RewriteRequest.marketing_guidance`(마지막 필드, 기본 `None`)와 `RewriteService.rewrite(..., marketing_guidance=None)`가 추가되었다.
값이 있을 때만 LLM 사용자 프롬프트에 `marketing_guidance`와 `marketing_guidance_rule`이 들어간다. 이 규칙은 가이드를 훅·구성·강조점·CTA 방향에만 쓰도록 한다.
가이드 안의 evidence나 브리프 문구는 본문의 새 사실이 될 수 없다. 사실 경계는 기존 `prohibited_changes`와 `RewriteValidator`가 그대로 지킨다.
값이 없으면 기존 프롬프트와 동작이 바뀌지 않는다.

## 후보 레코드 (data/tak_marketing_contents.json)

`brief_id, platform, media_platform, knowledge_id, content_id, status="review_required", requires_human_review=true, original_title, original_body, evidence_unit_ids, source_url, evidence, rewritten_title, rewritten_body, rewrite_status(not_requested|rewritten|rejected|error), validation_errors, [rewrite_error], marketing_guidance, generation_contract, created_at, [shorts_script, shorts_script_error]`

- `content_id`는 MEDIA content_id다. 기존 `compute_content_id`에 MEDIA 플랫폼(`media_platform`)을 넣어 계산한다(`media_content_id()`). 재작성 결과는 식별자에 영향을 주지 않는다.
- Marketing 계층의 `platform`은 youtube 전략을 유지한다. MEDIA로 넘어갈 때만 `youtube`를 `shorts`로 정규화한다(6-82).
  - YouTube 업로드, Shorts 변환, 성과 수집이 모두 `platform="shorts"` archive 레코드를 기준으로 동작하기 때문이다.
  - 그래서 youtube 후보의 content_id는 같은 슬롯의 기존 shorts content_id와 같다. 둘은 generation_id로 구분한다.
  - blog/threads/shorts의 content_id는 이전과 같다.
- 같은 `(brief_id, content_id)`는 다시 저장하지 않고, `link_content`는 중복 연결하지 않는다.
- 쓰기는 기존 store와 같은 원자적 방식(tempfile + replace)이다. 이 파일은 `data/*.json` 규칙으로 git에 올라가지 않는다.

## 사용

```
python scripts/marketing_brief.py suggest BRIEF_ID                 # 미리보기
python scripts/marketing_brief.py --write suggest BRIEF_ID         # 제안 저장(브리프는 그대로)
python scripts/marketing_brief.py review BRIEF_ID                  # 빈칸/대기 제안/승인·생성 차단 사유
python scripts/marketing_brief.py suggestion accept SUGGESTION_ID
python scripts/marketing_brief.py suggestion reject SUGGESTION_ID
python scripts/marketing_brief.py set BRIEF_ID storytelling.hook "..."
python scripts/marketing_brief.py approve BRIEF_ID                 # 또는 reject BRIEF_ID
python scripts/marketing_brief.py generate BRIEF_ID                # 미리보기(저장 안 함)
python scripts/marketing_brief.py --write generate BRIEF_ID --rewrite mock
python scripts/marketing_brief.py --write generate BRIEF_ID --rewrite llm   # TAK_MEDIA_LLM_* 환경변수 필요
```

`set`/`approve`/`reject`/`suggestion`은 사람의 결정이므로 즉시 브리프 저장소에 반영된다(기존 `status`/`link`와 같음). `suggest`와 `generate`는 `--write`가 있을 때만 저장한다.

## 안전 원칙

- **자동 발행 금지.** 어댑터는 발행 모듈(threads/youtube publisher)을 import하거나 호출하지 않는다. 후보는 `review_required`로만 저장되며, 이후 검토·승인·발행은 기존 절차를 따른다.
- 승인되지 않은 브리프와 미승인 KNOWLEDGE는 생성 단계로 들어가지 않는다.
- 외부 API는 `--rewrite llm`을 줄 때만 호출하며, 키는 환경변수에서만 읽는다. 기본 테스트는 네트워크를 쓰지 않는다.

## 한계 / 다음 단계

- `review_required` 후보를 기존 MEDIA 검토 대시보드/아카이브로 넘기는 연결은 아직 없다. 지금은 파일로만 검토한다.
- 브리프 1개는 플랫폼 1개만 생성한다. 여러 플랫폼은 플랫폼별 브리프를 각각 승인한다.
