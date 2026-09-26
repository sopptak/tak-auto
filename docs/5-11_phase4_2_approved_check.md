# Phase 4-2 실제 1건 발행 테스트 준비 — approved 항목 조사 (조사 전용)

## 0. 결론 먼저

**현재 `data/tak_threads_pending.json` 파일 자체가 존재하지 않는다.**
즉 pending/approved 상태의 Threads draft가 **0건**이며, Phase 4-2(실제 1건
발행 테스트)에 바로 쓸 수 있는 approved 항목이 **없다**.

## 1. approved 항목 조회

```
$ ls -la data/tak_threads_pending.json
ls: cannot access 'data/tak_threads_pending.json': No such file or directory
```

- `git ls-files data/tak_threads_pending.json` → 결과 없음 (git에 추적된 적도 없음)
- `git log --all --oneline -- data/tak_threads_pending.json` → 결과 없음 (커밋 이력 전무)
- `content_engine/threads_review.py`의 `load_pending()`은 파일이 없으면
  **빈 목록을 반환**하도록 설계되어 있다(에러 아님):

  ```python
  def load_pending(path: Path | str) -> list[ThreadsPendingDraft]:
      """pending 파일을 읽는다. 파일이 없거나 비어 있으면 빈 목록을 반환한다."""
      target = Path(path)
      if not target.exists():
          return []
      ...
  ```

→ approved 항목 목록: **없음 (0건)**

## 2. 각 항목 상세 (content_id / knowledge_id / final_title / final_body / status / ai_original 또는 edited 여부)

해당 없음 — 조회된 항목이 0건이므로 표시할 데이터가 없다.

## 3. publish history 중복 확인

`data/threads_publish_log.json`에는 이미 발행 이력 5건이 있다(전부 daily
자동 발행 workflow, `daily-threads-post.yml` 경로로 생성된 것으로 보임):

| content_id | knowledge_id | published_at |
|---|---|---|
| content-f2082a27c88c26ca | knowledge-da6ddf5aa459 | 2026-09-13T13:44:03Z |
| content-b4b9a05c461ad595 | knowledge-da6ddf5aa459 | 2026-09-14T00:45:01Z |
| content-45d8e97f0fab7b16 | knowledge-da6ddf5aa459 | 2026-09-15T01:12:52Z |
| content-ff8909844fa80b99 | knowledge-e1cc05264953 | 2026-09-15T04:10:33Z |
| content-ce61d77ee620c435 | knowledge-da8e52862a79 | 2026-09-16T01:07:02Z |

pending 파일이 아예 없어 비교할 approved `content_id`가 없으므로, 이
publish history와의 중복 여부는 **현재는 판정 대상 자체가 없다**(비교할
approved 항목이 생기면 그때 이 5개 `content_id`와 대조하면 된다).

## 4. 실제 발행 테스트에 쓸 수 있는 approved 항목이 있는가?

**없다.** `data/tak_threads_pending.json`이 존재하지 않으므로 Phase 2에서
사람이 검수/승인(approve)한 draft 자체가 아직 하나도 만들어지지 않은
상태다.

이 파일은 다음 두 스크립트가 채우는 구조로 보인다(코드만 확인, 실행하지
않음):
- `scripts/generate_threads_draft.py` — knowledge 1건을 골라 pending draft
  1건을 이 파일에 씀 (`status: "pending"`)
- `scripts/run_scout_dashboard.py` — 사람이 대시보드에서 draft를 검토하고
  승인하면 `status`를 `"approved"`로 바꿔 같은 파일에 저장

두 스크립트 모두 현재 git에는 커밋되지 않은 상태(untracked)이고, 이 조사에서는
지시에 따라 실행하지 않았다.

## 5. 제시할 항목

**해당 없음.** 승인된 항목이 0건이므로 "이 항목 하나"로 특정할 대상 자체가
없다. Phase 4-2 실제 발행 테스트를 진행하려면, 이 조사 범위 밖에서(사람의
별도 지시 하에) 먼저:

1. `scripts/generate_threads_draft.py`로 draft 1건을 pending으로 생성하고,
2. `scripts/run_scout_dashboard.py`(또는 동등한 검수 절차)로 그 draft를
   사람이 검토해 `status: "approved"`로 승인해야
   비로소 Phase 4-2에서 쓸 수 있는 approved 항목이 생긴다.

---

*이 문서는 조사 전용이다. 파일 수정, git add/commit/push, Threads API 호출,
publish script 실행, workflow 실행은 전혀 하지 않았다.*
